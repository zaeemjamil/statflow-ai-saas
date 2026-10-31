"""Phase 9 Stage 1: the evidence packet - content, privacy, determinism, size."""

from __future__ import annotations

import json
import unicodedata
import uuid
from datetime import UTC, datetime
from typing import Any

import pandas as pd
import pytest

from app.ai import evidence
from app.ai.eligibility import EVIDENCE_TOO_LARGE, EvidenceNotEligible
from app.ai.evidence import MAX_EVIDENCE_BYTES, build_evidence_packet, clean_text
from app.ai.fingerprint import canonical_json, fingerprint_content
from app.analytics.cleaning import CleaningConfig
from app.schemas.analysis import AnalysisPublic
from tests.ai_helpers import build_both, make_analysis, sample_frame, walk, wide_frame

SENTINEL = "ZZ_SECRET_CELL_VALUE_4471"


def _source_notes(analysis: AnalysisPublic) -> list[dict[str, Any]]:
    assert analysis.profile is not None
    return list((analysis.profile.model_extra or {})["import_notes"])


# --- shape and honesty ---------------------------------------------------


def test_packet_has_the_expected_sections_and_states_what_is_covered() -> None:
    analysis = make_analysis(sample_frame(), regression=("y", ["x", "z"]))
    content = build_evidence_packet(analysis).content
    assert content["schema_version"] == evidence.EVIDENCE_SCHEMA_VERSION
    for section in (
        "dataset",
        "columns",
        "import_notes",
        "cleaning",
        "statistics",
        "correlations",
        "outliers",
        "regression",
        "charts",
        "coverage",
        "omitted",
    ):
        assert section in content, section
    assert content["coverage"] == {
        "statistics": "included",
        "correlations": "included",
        "outliers": "included",
        "regression": "included",
        "charts": "included",
    }
    assert content["omitted"] == []


def test_regression_not_run_is_reported_as_not_run_and_section_is_absent() -> None:
    content = build_evidence_packet(make_analysis(sample_frame())).content
    assert content["coverage"]["regression"] == "not_run"
    assert "regression" not in content


def test_packet_numbers_are_the_numbers_the_dashboard_shows() -> None:
    analysis = make_analysis(sample_frame(), regression=("y", ["x", "z"]))
    packet, packet_aliases = build_both(analysis)
    content = packet.content
    shown = {
        packet_aliases.alias_for(c.column): c
        for c in analysis.statistics.columns  # type: ignore[union-attr]
    }
    for row in content["statistics"]["columns"]:
        source = shown[row["column"]]
        assert row["mean"] == pytest.approx(source.mean, rel=1e-5)
        assert row["count"] == source.count
    assert analysis.regression is not None and analysis.regression.metrics is not None
    assert content["regression"]["metrics"]["r_squared"] == pytest.approx(
        analysis.regression.metrics.r_squared, rel=1e-5
    )
    assert content["dataset"]["rows_uploaded"] == analysis.profile.row_count  # type: ignore[union-attr]
    assert content["cleaning"]["rows_after"] == analysis.cleaning.rows_after  # type: ignore[union-attr]


def test_correlation_pairs_are_strongest_first_and_matrix_is_not_copied() -> None:
    content = build_evidence_packet(make_analysis(sample_frame())).content
    values = [abs(p["correlation"]) for p in content["correlations"]["pairs"]]
    assert values == sorted(values, reverse=True)
    assert "matrix" not in content["correlations"]


def test_outliers_report_counts_and_bounds_but_never_row_positions() -> None:
    packet, packet_aliases = build_both(make_analysis(sample_frame()))
    content = packet.content
    flagged = {c["column"]: c for c in content["outliers"]["columns"]}
    assert flagged[packet_aliases.alias_for("x")]["outlier_count"] >= 1
    assert "outlier_indices" not in json.dumps(content)


# --- privacy: no raw data, no identifiers --------------------------------


def _forbidden_keys() -> set[str]:
    return {
        "outlier_indices",
        "sample_predictions",
        "matrix",
        "data",
        "details",
        "number_format_examples",
        "examples",
        "storage_key",
        "original_filename",
    }


def test_raw_cell_values_never_reach_the_packet() -> None:
    frame = sample_frame()
    frame["notes"] = [f"{SENTINEL}_{i}" for i in range(len(frame))]  # unique text per row
    frame["segment"] = SENTINEL  # one repeated text value
    frame.loc[[1, 2], "segment"] = None  # imputed with the most common text (the sentinel)
    packet, packet_aliases = build_both(make_analysis(frame))
    serialized = canonical_json(packet.content)
    assert SENTINEL not in serialized
    actions = {a["column"]: a for a in packet.content["cleaning"]["column_actions"]}
    segment = actions[packet_aliases.alias_for("segment")]
    assert segment["action"] == "imputed"
    assert "fill_value" not in segment
    # ...while a numeric fill (a median) is a summary and is kept.
    frame2 = sample_frame()
    frame2.loc[[1, 2], "z"] = None
    packet2, packet2_aliases = build_both(make_analysis(frame2))
    numeric_actions = {a["column"]: a for a in packet2.content["cleaning"]["column_actions"]}
    assert isinstance(numeric_actions[packet2_aliases.alias_for("z")]["fill_value"], float)


def test_example_values_quoted_inside_import_notes_are_not_copied() -> None:
    frame = sample_frame()
    frame["price"] = [f"${73000 + i * 7:,}.55" for i in range(len(frame))]  # numbers as text
    analysis = make_analysis(frame)
    source_note = next(
        n for n in _source_notes(analysis) if n["code"] == "formatted_numbers_as_text"
    )
    examples = source_note["details"]["formats"]["price"]["examples"]
    assert examples and all(e in source_note["message"] for e in examples)  # the source leaks...
    packet, packet_aliases = build_both(analysis)
    content = packet.content
    serialized = canonical_json(content)
    for example in examples:
        assert example not in serialized  # ...the packet does not
    assert "$" not in serialized and "73," not in serialized
    note = next(n for n in content["import_notes"] if n["code"] == "formatted_numbers_as_text")
    price = packet_aliases.alias_for("price")
    assert note["columns"] == [price]
    assert note["format_kinds"] == {price: "currency"}


def test_an_unknown_future_note_is_reported_as_unknown_and_loses_its_free_text() -> None:
    """Closed-vocabulary policy: an unrecognised note code is never passed
    through (it could be anything, including a column name); it is reported
    as the safe constant "unknown". Severity (also closed) and the aliased
    columns are kept; the message and details are not."""
    extra_note = {
        "code": "some_future_note",
        "severity": "warning",
        "message": f"contains {SENTINEL}",
        "columns": ["x"],
        "details": {"example": SENTINEL},
    }
    analysis = make_analysis(sample_frame())
    assert analysis.profile is not None
    analysis.profile.import_notes = [*_source_notes(analysis), extra_note]  # type: ignore[attr-defined]
    packet, aliases = build_both(analysis)
    content = packet.content
    unknown = [n for n in content["import_notes"] if n["code"] == "unknown"]
    assert len(unknown) == 1
    kept = unknown[0]
    assert kept["severity"] == "warning"
    assert kept["columns"] == [aliases.alias_for("x")]
    assert "message" not in kept
    assert all(n["code"] != "some_future_note" for n in content["import_notes"])
    assert "some_future_note" not in canonical_json(content)
    assert SENTINEL not in canonical_json(content)


def test_a_built_packet_is_read_only_and_its_saved_size_and_fingerprint_stay_true() -> None:
    packet = build_evidence_packet(make_analysis(sample_frame(), regression=("y", ["x", "z"])))
    before_text, before_print = packet.canonical_json(), packet.fingerprint
    with pytest.raises(TypeError):
        packet.content["dataset"]["rows_uploaded"] = 1
    with pytest.raises(TypeError):
        packet.content["columns"].append({"column": "Column_999"})
    with pytest.raises(TypeError):
        packet.content["columns"][0]["column"] = "x"
    assert packet.canonical_json() == before_text
    assert packet.fingerprint == before_print
    assert packet.size_bytes == len(before_text.encode("utf-8")) <= MAX_EVIDENCE_BYTES
    packet.verify_integrity()


def test_no_row_level_or_bulky_keys_appear_anywhere() -> None:
    analysis = make_analysis(sample_frame(), regression=("y", ["x", "z"]))
    content = build_evidence_packet(analysis).content
    found = {value for kind, value in walk(content) if kind == "key"}
    assert not (found & _forbidden_keys()), found & _forbidden_keys()


def test_ids_timestamps_and_names_of_files_are_not_in_the_packet() -> None:
    analysis = make_analysis(sample_frame())
    serialized = canonical_json(build_evidence_packet(analysis).content)
    for identifier in (analysis.id, analysis.project_id, analysis.file_id):
        assert str(identifier) not in serialized
    assert "2026-10-20T09" not in serialized


# --- text hygiene (column names are untrusted) ---------------------------


def test_clean_text_removes_control_and_invisible_characters() -> None:
    dirty = "a\nb\tc\u200bd\u202ee\u2028f\x00g  h"
    # Invisible characters are deleted (glued), line/control characters become spaces.
    assert clean_text(dirty, 80) == "a b cde f g h"
    assert clean_text("x" * 500, 80) == "x" * 79 + "…"
    composed = unicodedata.normalize("NFC", "caf\u00e9")
    assert clean_text(unicodedata.normalize("NFD", "caf\u00e9"), 80) == composed


# --- determinism and sensitivity -----------------------------------------


def test_packet_is_exactly_what_is_hashed_and_measured() -> None:
    packet = build_evidence_packet(make_analysis(sample_frame(), regression=("y", ["x"])))
    assert json.loads(canonical_json(packet.content)) == packet.content
    assert packet.fingerprint == fingerprint_content(packet.content)
    assert packet.size_bytes == len(canonical_json(packet.content).encode())
    assert packet.size_bytes <= MAX_EVIDENCE_BYTES


def test_same_analysis_gives_identical_packet_and_fingerprint() -> None:
    analysis = make_analysis(sample_frame(), regression=("y", ["x", "z"]))
    first, second = build_evidence_packet(analysis), build_evidence_packet(analysis)
    assert first.content == second.content
    assert first.fingerprint == second.fingerprint


def test_rebuilding_from_the_same_data_gives_the_same_fingerprint() -> None:
    one = build_evidence_packet(make_analysis(sample_frame(seed=7)))
    two = build_evidence_packet(make_analysis(sample_frame(seed=7)))
    assert one.fingerprint == two.fingerprint


def test_ids_and_timestamps_do_not_change_the_fingerprint() -> None:
    analysis = make_analysis(sample_frame())
    later = analysis.model_copy(
        update={
            "id": uuid.uuid4(),
            "project_id": uuid.uuid4(),
            "file_id": uuid.uuid4(),
            "created_at": datetime(2030, 1, 1, tzinfo=UTC),
            "updated_at": datetime(2030, 1, 2, tzinfo=UTC),
            "completed_at": datetime(2030, 1, 3, tzinfo=UTC),
        }
    )
    assert build_evidence_packet(analysis).fingerprint == build_evidence_packet(later).fingerprint


def test_a_real_change_to_the_results_changes_the_fingerprint() -> None:
    base = build_evidence_packet(make_analysis(sample_frame(seed=7))).fingerprint
    other_data = build_evidence_packet(make_analysis(sample_frame(seed=8))).fingerprint
    assert other_data != base

    frame = sample_frame()
    frame.loc[[5, 6], "z"] = None
    keep = build_evidence_packet(make_analysis(frame, cleaning=CleaningConfig())).fingerprint
    unchanged = build_evidence_packet(
        make_analysis(frame, cleaning=CleaningConfig(numeric_strategy="unchanged"))
    ).fingerprint
    assert keep != unchanged  # a different cleaning choice is different evidence

    # Renaming a column no longer changes the evidence: the AI never saw the
    # name, only its alias. (Covered in test_ai_aliasing.py.)
    renamed = build_evidence_packet(
        make_analysis(sample_frame(seed=7).rename(columns={"z": "zeta"}))
    ).fingerprint
    assert renamed == base

    with_regression = build_evidence_packet(
        make_analysis(sample_frame(seed=7), regression=("y", ["x"]))
    ).fingerprint
    assert with_regression != base


def test_changing_the_schema_version_changes_the_fingerprint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = make_analysis(sample_frame())
    before = build_evidence_packet(analysis).fingerprint
    monkeypatch.setattr(evidence, "EVIDENCE_SCHEMA_VERSION", 99)
    assert build_evidence_packet(analysis).fingerprint != before


# --- size limits ---------------------------------------------------------


def _wide_analysis() -> Any:
    names = list(wide_frame().columns)
    return make_analysis(wide_frame(), regression=(names[0], names[1:25]))


def test_a_wide_dataset_stays_under_the_cap_and_every_cut_is_recorded() -> None:
    packet = build_evidence_packet(_wide_analysis())
    assert packet.size_bytes <= MAX_EVIDENCE_BYTES
    cuts = {o["section"]: o for o in packet.content["omitted"]}
    assert cuts["columns"]["total"] == 100
    assert cuts["columns"]["shown"] == len(packet.content["columns"]) < 100
    assert cuts["statistics"]["shown"] == len(packet.content["statistics"]["columns"])
    assert cuts["correlation_pairs"]["shown"] == len(packet.content["correlations"]["pairs"])
    for cut in cuts.values():
        assert cut["shown"] < cut["total"]


def test_size_reduction_is_deterministic() -> None:
    first, second = build_evidence_packet(_wide_analysis()), build_evidence_packet(_wide_analysis())
    assert first.fingerprint == second.fingerprint
    assert first.content["omitted"] == second.content["omitted"]


def test_a_smaller_cap_selects_a_smaller_tier(monkeypatch: pytest.MonkeyPatch) -> None:
    analysis = _wide_analysis()
    full = build_evidence_packet(analysis)
    limit = full.size_bytes - 1
    monkeypatch.setattr(evidence, "MAX_EVIDENCE_BYTES", limit)
    smaller = build_evidence_packet(analysis)
    assert smaller.size_bytes <= limit < full.size_bytes
    assert len(smaller.content["columns"]) < len(full.content["columns"])
    assert smaller.fingerprint != full.fingerprint


def test_charts_are_the_first_thing_dropped_and_coverage_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    analysis = _wide_analysis()
    monkeypatch.setattr(evidence, "_TIERS", evidence._TIERS[2:3])  # the tier without charts
    content = build_evidence_packet(analysis).content
    assert "charts" not in content
    assert content["coverage"]["charts"] == "omitted_for_size"


def test_when_even_the_smallest_form_does_not_fit_no_packet_is_produced(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(evidence, "MAX_EVIDENCE_BYTES", 300)
    with pytest.raises(EvidenceNotEligible) as caught:
        build_evidence_packet(make_analysis(sample_frame()))
    assert caught.value.error_code == EVIDENCE_TOO_LARGE


def test_a_normal_dataset_is_not_reduced_at_all() -> None:
    packet = build_evidence_packet(make_analysis(sample_frame(), regression=("y", ["x", "z"])))
    assert packet.content["omitted"] == []
    assert packet.size_bytes < MAX_EVIDENCE_BYTES // 2


# --- guard: only the provider module may touch the network or the key -----
# (Stage 1 pinned "the whole package is offline". Stage 2 adds app/ai/provider.py
# as the single, tested network boundary; every other module stays offline.)

_PROVIDER_MODULE_MAY_USE = {"provider.py": {"httpx", "OPENROUTER"}, "loader.py": {"sqlalchemy"}}


def test_the_ai_package_has_no_network_provider_or_key_access() -> None:
    from pathlib import Path

    package = Path(evidence.__file__).parent
    banned = (
        "httpx",
        "requests",
        "urllib",
        "socket",
        "aiohttp",
        "openai",
        "anthropic",
        "OPENROUTER",
        "get_settings",
        "os.environ",
        "sqlalchemy",
        "open(",
    )
    for path in package.glob("*.py"):
        text = path.read_text()
        for word in banned:
            if word in _PROVIDER_MODULE_MAY_USE.get(path.name, set()):
                continue
            assert word not in text, f"{path.name} mentions {word}"


def test_only_the_provider_module_imports_the_http_client_or_reads_the_api_key() -> None:
    from pathlib import Path

    app_dir = Path(evidence.__file__).parents[1]
    http_importers: set[str] = set()
    key_users: set[str] = set()
    for path in app_dir.rglob("*.py"):
        text = path.read_text()
        rel = path.relative_to(app_dir).as_posix()
        if "import httpx" in text or "from httpx" in text:
            http_importers.add(rel)
        if "OPENROUTER_API_KEY" in text:
            key_users.add(rel)
    assert http_importers == {"ai/provider.py"}
    assert key_users == {"core/config.py", "ai/provider.py"}


def test_empty_frame_helper_sanity() -> None:
    # Guards the test helpers themselves: a frame of the wrong size would make
    # the size tests above meaningless.
    assert wide_frame().shape == (30, 100)
    assert isinstance(sample_frame(), pd.DataFrame) and len(sample_frame()) == 40
