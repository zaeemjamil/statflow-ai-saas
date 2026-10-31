"""Stage 3 review fixes through real HTTP requests: entirely blank columns,
dotted dates, and projects uploaded before Stage 3 (stored profile vs. the
analysis re-read of the stored file)."""

from __future__ import annotations

import io
import uuid
from typing import Any

import pandas as pd
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.analytics.profiling import profile_dataset
from app.models import File

PROJECTS_URL = "/api/v1/projects"


def _project(client: TestClient, email: str) -> str:
    response = client.post(
        "/api/v1/auth/register", json={"email": email, "password": "correct-horse-1"}
    )
    assert response.status_code == 201, response.text
    created = client.post(PROJECTS_URL, json={"name": "Review fixes"})
    assert created.status_code == 201, created.text
    return str(created.json()["id"])


def _upload(client: TestClient, project_id: str, name: str, content: bytes) -> Any:
    return client.post(
        f"{PROJECTS_URL}/{project_id}/upload", files={"file": (name, content, "text/plain")}
    )


def _column(profile: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in profile["columns"] if c["name"] == name)


def _xlsx(frame: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        frame.to_excel(writer, sheet_name="Sheet1", index=False)
    return buf.getvalue()


# --- 1. entirely blank column ------------------------------------------------


def _blank_column_csv() -> bytes:
    frame = pd.DataFrame(
        {"x": range(1, 13), "y": [i * 2.5 for i in range(12)], "empty": [None] * 12}
    )
    return frame.to_csv(index=False).encode()


def test_blank_csv_column_is_not_numeric_and_analysis_still_runs(client: TestClient) -> None:
    pid = _project(client, "rf1@example.com")
    uploaded = _upload(client, pid, "blank.csv", _blank_column_csv())
    assert uploaded.status_code == 201, uploaded.text
    profile = uploaded.json()["profile"]
    assert _column(profile, "empty")["classification"] == "categorical"
    assert _column(profile, "empty")["missing_percentage"] == 100.0
    assert profile["numeric_column_count"] == 2

    analysed = client.post(f"{PROJECTS_URL}/{pid}/analyze")
    assert analysed.status_code == 200, analysed.text
    body = analysed.json()
    assert body["status"] == "completed"
    stats_columns = [c["column"] for c in body["statistics"]["columns"]]
    assert stats_columns == ["x", "y"]  # valid numeric statistics preserved
    assert "empty" in body["statistics"]["skipped_columns"]
    assert set(body["correlations"]["matrix"]) == {"x", "y"}


def test_blank_xlsx_column_is_not_numeric(client: TestClient) -> None:
    pid = _project(client, "rf2@example.com")
    frame = pd.DataFrame({"x": range(1, 9), "empty": [None] * 8})
    uploaded = _upload(client, pid, "blank.xlsx", _xlsx(frame))
    assert uploaded.status_code == 201, uploaded.text
    profile = uploaded.json()["profile"]
    assert _column(profile, "empty")["classification"] == "categorical"
    assert profile["numeric_column_count"] == 1


# --- 2. dotted dates -----------------------------------------------------------


def test_dotted_ambiguous_dates_get_the_warning_through_the_api(client: TestClient) -> None:
    pid = _project(client, "rf3@example.com")
    frame = pd.DataFrame(
        {"when": ["01.02.2025", "03.04.2025", "05.06.2025", "07.08.2025"] * 3, "v": range(12)}
    )
    uploaded = _upload(client, pid, "dotted.csv", frame.to_csv(index=False).encode())
    assert uploaded.status_code == 201, uploaded.text
    profile = uploaded.json()["profile"]
    assert _column(profile, "when")["classification"] == "date"
    assert _column(profile, "when")["date_order_issue"] == "ambiguous"
    notes = {n["code"]: n for n in profile["import_notes"]}
    assert notes["ambiguous_dates"]["columns"] == ["when"]
    assert notes["ambiguous_dates"]["severity"] == "warning"


# --- 3. projects uploaded before Stage 3 -------------------------------------------

_LEGACY_CSV = (
    "code,score\n" + "\n".join(f"{'NA' if i % 4 == 0 else 'US'},{i * 1.5}" for i in range(24))
).encode()


def _make_legacy(db: Session, project_id: str) -> dict[str, Any]:
    """Turn the project's file into what a pre-Stage-3 upload stored: a profile
    built from a stock-pandas parse (the text 'NA' is missing) with no
    `import_notes`."""
    legacy_profile = profile_dataset(pd.read_csv(io.BytesIO(_LEGACY_CSV), index_col=False))
    file_row = db.execute(select(File).where(File.project_id == uuid.UUID(project_id))).scalar_one()
    file_row.profile = legacy_profile
    db.commit()
    return legacy_profile


def test_stage_3_upload_keeps_na_as_a_value_and_analysis_agrees(client: TestClient) -> None:
    pid = _project(client, "rf4@example.com")
    uploaded = _upload(client, pid, "codes.csv", _LEGACY_CSV).json()["profile"]
    assert _column(uploaded, "code")["missing_count"] == 0
    assert "import_notes" in uploaded

    body = client.post(f"{PROJECTS_URL}/{pid}/analyze").json()
    assert "code" not in {a["column"] for a in body["cleaning"]["column_actions"]}
    assert body["profile"]["columns"] == uploaded["columns"]


def test_legacy_upload_is_reread_with_the_policy_its_profile_was_built_with(
    client: TestClient, db_session: Session
) -> None:
    pid = _project(client, "rf5@example.com")
    assert _upload(client, pid, "codes.csv", _LEGACY_CSV).status_code == 201
    legacy_profile = _make_legacy(db_session, pid)
    assert "import_notes" not in legacy_profile
    assert _column(legacy_profile, "code")["missing_count"] == 6

    # The displayed (stored) profile is untouched ...
    shown = client.get(f"{PROJECTS_URL}/{pid}/profile").json()
    assert _column(shown, "code")["missing_count"] == 6
    assert shown["import_notes"] == []

    # ... and the analysis sees the same six missing cells, not a literal "NA".
    analysed = client.post(f"{PROJECTS_URL}/{pid}/analyze")
    assert analysed.status_code == 200, analysed.text
    body = analysed.json()
    assert body["profile"]["columns"] == legacy_profile["columns"]
    actions = {a["column"]: a for a in body["cleaning"]["column_actions"]}
    assert actions["code"]["missing_before"] == 6
    assert body["cleaned_profile"]["total_missing_values"] == 0


def test_legacy_upload_cleaning_endpoint_uses_the_same_policy(
    client: TestClient, db_session: Session
) -> None:
    pid = _project(client, "rf6@example.com")
    assert _upload(client, pid, "codes.csv", _LEGACY_CSV).status_code == 201
    _make_legacy(db_session, pid)

    cleaned = client.post(f"{PROJECTS_URL}/{pid}/clean", json={})
    assert cleaned.status_code == 200, cleaned.text
    actions = {a["column"]: a for a in cleaned.json()["cleaning"]["column_actions"]}
    assert actions["code"]["missing_before"] == 6
