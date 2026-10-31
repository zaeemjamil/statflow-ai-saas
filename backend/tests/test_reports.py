"""Phase 10: PDF reports. The renderer is tested directly (numbers match the
stored analysis, hostile text stays inert text, Unicode works) and through the
HTTP API (ownership, lifecycle, limits, storage cleanup)."""

from __future__ import annotations

import io
import json
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ai.provider import ProviderResult
from app.api.deps import get_ai_provider, get_storage
from app.core.config import get_settings
from app.models import Report
from app.schemas.ai import AIInsightPublic
from app.services import report_pdf, report_service
from app.services.report_pdf import _num, build_report_pdf
from tests.ai_helpers import make_analysis, sample_frame

PROJECTS = "/api/v1/projects"
NOW = datetime(2026, 10, 24, 12, 0, tzinfo=UTC)


def _text(pdf: bytes) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(io.BytesIO(pdf)).pages)


def _render(
    frame: pd.DataFrame, *, name: str = "Quarterly sales", ai: AIInsightPublic | None = None
) -> bytes:
    return build_report_pdf(
        project_name=name,
        file_name="data.csv",
        analysis=make_analysis(frame, regression=("y", ["x"])),
        ai=ai,
        generated_at=NOW,
    )


# --- renderer ---------------------------------------------------------------


def test_the_pdf_is_valid_and_shows_the_same_numbers_as_the_analysis() -> None:
    frame = sample_frame()
    analysis = make_analysis(frame, regression=("y", ["x"]))
    pdf = build_report_pdf(
        project_name="Sales", file_name="data.csv", analysis=analysis, ai=None, generated_at=NOW
    )
    assert pdf.startswith(b"%PDF-") and len(PdfReader(io.BytesIO(pdf)).pages) >= 1
    text = _text(pdf)
    assert analysis.statistics is not None and analysis.regression is not None
    stat = next(c for c in analysis.statistics.columns if c.column == "x")
    assert _num(stat.mean) in text and _num(stat.max) in text  # same value the dashboard shows
    assert analysis.regression.metrics is not None
    assert _num(analysis.regression.metrics.r_squared) in text
    for heading in (
        "Dataset and cleaning",
        "Descriptive statistics",
        "Correlations",
        "Outliers",
        "Regression",
        "Charts",
    ):
        assert heading in text
    assert "AI-generated explanation" not in text  # only when a current explanation exists


def test_hostile_column_names_stay_inert_text() -> None:
    evil = '<img src="/etc/passwd" width="50" height="50"/><b>BOLD</b><font color="red">'
    frame = sample_frame().rename(columns={"x": evil, "y": "</para><para>injected"})
    pdf = build_report_pdf(
        project_name="<b>proj</b>",
        file_name="<a href='http://evil.test'>f</a>.csv",
        analysis=make_analysis(frame),
        ai=None,
        generated_at=NOW,
    )
    text = _text(pdf)
    assert "<img" in text and "BOLD" in text  # shown literally, not interpreted
    assert b"/Subtype /Image" not in pdf and b"/Subtype/Image" not in pdf
    assert b"/URI" not in pdf  # no clickable link was created from user text
    assert "root:" not in text  # nothing was read from the server's disk


def test_latin_greek_and_cyrillic_names_render_and_unsupported_scripts_show_a_question_mark() -> (
    None
):
    frame = sample_frame().rename(
        columns={"x": "Größe", "y": "温度", "group": "Регион", "z": "Δελτα"}
    )
    text = _text(_render(frame))
    assert "Größe" in text and "Регион" in text and "Δελτα" in text
    # Known limitation: the bundled font has no CJK glyphs, so those show as "?", not blank boxes.
    assert "温度" not in text and "??" in text


def test_the_fallback_font_still_produces_a_pdf(monkeypatch: pytest.MonkeyPatch) -> None:
    report_pdf._fonts.cache_clear()
    monkeypatch.setattr(report_pdf, "FONT_DIR", report_pdf.FONT_DIR / "missing")
    try:
        pdf = _render(sample_frame().rename(columns={"x": "温度"}))
        assert pdf.startswith(b"%PDF-")
    finally:
        report_pdf._fonts.cache_clear()


def test_control_characters_and_huge_names_are_bounded() -> None:
    frame = sample_frame().rename(columns={"x": "a\x00b\u202e" + "z" * 5000})
    pdf = _render(frame)
    assert pdf.startswith(b"%PDF-") and len(pdf) < 2_000_000


def test_an_ai_section_is_labelled_and_carries_the_disclaimer() -> None:
    ai = AIInsightPublic(
        summary="“x” rises with “y”.",
        key_findings=["<b>one</b>"],
        data_quality=[],
        limitations=["Association only."],
        next_steps=[],
        evidence_warnings=["small_sample"],
        generated_at=NOW,
        model="fake/model",
        prompt_version="1",
    )
    text = _text(_render(sample_frame(), ai=ai))
    assert (
        "AI-generated explanation" in text and "It can be wrong" in text and "Small sample" in text
    )
    assert "<b>one</b>" in text


def test_empty_optional_sections_do_not_break_rendering() -> None:
    frame = pd.DataFrame({"only": ["a", "b", "c", "d", "e", "f"]})
    assert _render(frame).startswith(b"%PDF-")


# --- API --------------------------------------------------------------------


def _setup(client: TestClient, email: str, *, analyze: bool = True, rows: int = 40) -> str:
    assert (
        client.post(
            "/api/v1/auth/register", json={"email": email, "password": "correct-horse-1"}
        ).status_code
        == 201
    )
    pid = str(client.post(PROJECTS, json={"name": "Quarterly sales"}).json()["id"])
    csv = sample_frame(rows).to_csv(index=False).encode()
    assert (
        client.post(
            f"{PROJECTS}/{pid}/upload", files={"file": ("d.csv", csv, "text/csv")}
        ).status_code
        == 201
    )
    if analyze:
        assert client.post(f"{PROJECTS}/{pid}/analyze").status_code == 200
    return pid


@pytest.fixture()
def fast(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(report_service, "COOLDOWN_SECONDS", 0)


def _storage(client: TestClient) -> Any:
    return client.app.dependency_overrides[get_storage]()  # type: ignore[attr-defined]


def test_requires_login(client: TestClient) -> None:
    pid = "00000000-0000-0000-0000-000000000001"
    rid = "00000000-0000-0000-0000-000000000002"
    assert client.post(f"{PROJECTS}/{pid}/reports").status_code == 401
    assert client.get(f"{PROJECTS}/{pid}/reports").status_code == 401
    assert client.get(f"{PROJECTS}/{pid}/reports/{rid}/download").status_code == 401
    assert client.delete(f"{PROJECTS}/{pid}/reports/{rid}").status_code == 401


def test_create_list_download_delete_lifecycle(
    client: TestClient, db_session: Session, fast: None
) -> None:
    pid = _setup(client, "life@example.com")
    created = client.post(f"{PROJECTS}/{pid}/reports")
    assert created.status_code == 201, created.text
    report = created.json()
    assert report["file_name"].startswith("Quarterly-sales-report-") and report[
        "file_name"
    ].endswith(".pdf")
    assert set(report) == {
        "id",
        "project_id",
        "analysis_id",
        "file_name",
        "generated_at",
    }  # no storage key leaked

    assert [r["id"] for r in client.get(f"{PROJECTS}/{pid}/reports").json()] == [report["id"]]

    dl = client.get(f"{PROJECTS}/{pid}/reports/{report['id']}/download")
    assert dl.status_code == 200 and dl.headers["content-type"] == "application/pdf"
    assert dl.headers["content-disposition"] == f'attachment; filename="{report["file_name"]}"'
    assert (
        dl.headers["cache-control"] == "private, no-store"
        and dl.headers["x-content-type-options"] == "nosniff"
    )
    assert dl.content.startswith(b"%PDF-")

    stored = db_session.execute(select(Report)).scalar_one()
    assert _storage(client).get_file(storage_key=stored.storage_key) == dl.content

    assert client.delete(f"{PROJECTS}/{pid}/reports/{report['id']}").status_code == 204
    assert client.get(f"{PROJECTS}/{pid}/reports").json() == []
    assert client.get(f"{PROJECTS}/{pid}/reports/{report['id']}/download").status_code == 404
    with pytest.raises(FileNotFoundError):
        _storage(client).get_file(storage_key=stored.storage_key)


def test_another_users_reports_are_invisible(client: TestClient, fast: None) -> None:
    pid = _setup(client, "owner2@example.com")
    rid = client.post(f"{PROJECTS}/{pid}/reports").json()["id"]
    client.post("/api/v1/auth/logout")
    client.post(
        "/api/v1/auth/register", json={"email": "thief@example.com", "password": "correct-horse-1"}
    )
    assert client.get(f"{PROJECTS}/{pid}/reports").status_code == 404
    assert client.post(f"{PROJECTS}/{pid}/reports").status_code == 404
    assert client.get(f"{PROJECTS}/{pid}/reports/{rid}/download").status_code == 404
    assert client.delete(f"{PROJECTS}/{pid}/reports/{rid}").status_code == 404


def test_a_report_id_from_another_project_is_not_reachable(client: TestClient, fast: None) -> None:
    first = _setup(client, "twoproj@example.com")
    rid = client.post(f"{PROJECTS}/{first}/reports").json()["id"]
    second = str(client.post(PROJECTS, json={"name": "Second"}).json()["id"])
    assert client.get(f"{PROJECTS}/{second}/reports/{rid}/download").status_code == 404
    assert client.delete(f"{PROJECTS}/{second}/reports/{rid}").status_code == 404
    assert client.get(f"{PROJECTS}/{first}/reports/{rid}/download").status_code == 200


def test_no_report_before_the_analysis_has_run(client: TestClient, fast: None) -> None:
    pid = _setup(client, "early@example.com", analyze=False)
    assert client.post(f"{PROJECTS}/{pid}/reports").status_code == 404  # no analysis row yet
    client.post(f"{PROJECTS}/{pid}/clean", json={})
    refused = client.post(f"{PROJECTS}/{pid}/reports")
    assert (
        refused.status_code == 409 and refused.json()["error"]["code"] == "analysis_not_completed"
    )


def test_cooldown_stops_rapid_repeat_generation(client: TestClient) -> None:
    pid = _setup(client, "cool2@example.com")
    assert client.post(f"{PROJECTS}/{pid}/reports").status_code == 201
    again = client.post(f"{PROJECTS}/{pid}/reports")
    assert again.status_code == 429 and again.json()["error"]["code"] == "report_rate_limited"


def test_only_the_newest_reports_are_kept_and_old_files_are_removed(
    client: TestClient, db_session: Session, fast: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(report_service, "MAX_REPORTS_PER_PROJECT", 3)
    pid = _setup(client, "cap@example.com")
    ids = [client.post(f"{PROJECTS}/{pid}/reports").json()["id"] for _ in range(5)]
    listed = [r["id"] for r in client.get(f"{PROJECTS}/{pid}/reports").json()]
    assert listed == list(reversed(ids))[:3]
    keys = {r.storage_key for r in db_session.execute(select(Report)).scalars()}
    assert len(keys) == 3
    on_disk = list((_storage(client)._base_dir / "reports" / pid).glob("*.pdf"))
    assert len(on_disk) == 3


def test_a_missing_file_is_a_clean_404_not_a_crash(
    client: TestClient, db_session: Session, fast: None
) -> None:
    pid = _setup(client, "gone@example.com")
    rid = client.post(f"{PROJECTS}/{pid}/reports").json()["id"]
    stored = db_session.execute(select(Report)).scalar_one()
    _storage(client).delete_file(storage_key=stored.storage_key)
    gone = client.get(f"{PROJECTS}/{pid}/reports/{rid}/download")
    assert gone.status_code == 404 and gone.json()["error"]["code"] == "report_file_unavailable"


def test_deleting_the_project_removes_its_report_files(
    client: TestClient, db_session: Session, fast: None
) -> None:
    pid = _setup(client, "wipe@example.com")
    client.post(f"{PROJECTS}/{pid}/reports")
    key = db_session.execute(select(Report)).scalar_one().storage_key
    assert _storage(client).get_file(storage_key=key).startswith(b"%PDF-")
    assert client.delete(f"{PROJECTS}/{pid}").status_code == 204
    with pytest.raises(FileNotFoundError):
        _storage(client).get_file(storage_key=key)
    assert db_session.execute(select(Report)).first() is None


def test_the_report_includes_a_current_ai_explanation_and_drops_a_stale_one(
    client: TestClient, fast: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    class Fake:
        model = "fake/model"

        def generate(self, messages: list[dict[str, str]]) -> ProviderResult:
            return ProviderResult(
                text=json.dumps({"summary": "Column_002 and Column_003 move together."}),
                model="fake/m",
            )

    monkeypatch.setenv("AI_COOLDOWN_SECONDS", "0")
    get_settings.cache_clear()
    client.app.dependency_overrides[get_ai_provider] = lambda: Fake()  # type: ignore[attr-defined]
    pid = _setup(client, "aipdf@example.com")
    assert client.post(f"{PROJECTS}/{pid}/ai-insights").status_code == 200

    def latest_text() -> str:
        rid = client.post(f"{PROJECTS}/{pid}/reports").json()["id"]
        return _text(client.get(f"{PROJECTS}/{pid}/reports/{rid}/download").content)

    with_ai = latest_text()
    assert "AI-generated explanation" in with_ai and "“y” and “x”" in with_ai.replace(
        "“x” and “y”", "“y” and “x”"
    )
    client.post(
        f"{PROJECTS}/{pid}/regression", json={"target": "y", "predictors": ["x"]}
    )  # evidence changes
    assert "AI-generated explanation" not in latest_text()
