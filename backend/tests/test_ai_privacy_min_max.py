"""What the AI provider is told about the data: no exact min/max, no rows, honest wording."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from app.ai import evidence, prompt
from app.ai.evidence import WITHHELD_STATISTICS_FIELDS, build_evidence, build_evidence_packet
from tests.ai_helpers import make_analysis, walk

ROOT = Path(__file__).resolve().parents[2]

# Distinctive values: the exact smallest and largest of each column. None of them
# can be produced by any aggregate of the data (mean, median, quartiles, bounds ...).
LOW_X, HIGH_X = -7316.25, 918273.5
LOW_Y, HIGH_Y = -4417.125, 33891.875


def _frame(rows: int = 41) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    x = rng.normal(1000, 50, rows)
    y = rng.normal(500, 30, rows)
    x[0], x[1] = LOW_X, HIGH_X
    y[0], y[1] = LOW_Y, HIGH_Y
    return pd.DataFrame({"x": x, "y": y, "group": ["a", "b"] * (rows // 2) + ["a"] * (rows % 2)})


def _numbers(value: Any) -> list[float]:
    out: list[float] = []
    for item in walk(value):
        if isinstance(item, int | float) and not isinstance(item, bool):
            out.append(float(item))
    return out


def test_the_dashboard_really_holds_these_exact_extremes() -> None:
    """Guards the test itself: the values below are real data and are shown on the dashboard."""
    analysis = make_analysis(_frame())
    assert analysis.profile is not None and analysis.statistics is not None
    profile = {c["name"]: c for c in analysis.profile.columns}
    assert profile["x"]["min_value"] == LOW_X and profile["x"]["max_value"] == HIGH_X
    stats = {c.column: c for c in analysis.statistics.columns}
    assert stats["x"].min == LOW_X and stats["x"].max == HIGH_X
    assert stats["y"].min == LOW_Y and stats["y"].max == HIGH_Y


def test_exact_min_and_max_are_not_in_the_columns_or_statistics_sections() -> None:
    content = build_evidence_packet(make_analysis(_frame())).content
    for entry in content["columns"]:
        assert "min" not in entry and "max" not in entry, entry
    for entry in content["statistics"]["columns"]:
        assert "min" not in entry and "max" not in entry, entry
    assert WITHHELD_STATISTICS_FIELDS == {"min", "max"}


def test_no_exact_extreme_value_appears_anywhere_in_the_provider_text() -> None:
    packet = build_evidence_packet(make_analysis(_frame(), regression=("y", ["x"])))
    text = packet.canonical_json()
    for exact in (LOW_X, HIGH_X, LOW_Y, HIGH_Y):
        assert exact not in _numbers(packet.content), exact
        assert repr(exact) not in text and str(exact) not in text, exact
    # ... nor in the complete request body built from that packet
    body = json.dumps(prompt.build_messages(packet))
    for exact_text in ("-7316.25", "918273.5", "-4417.125", "33891.875"):
        assert exact_text not in body, exact_text


def test_the_useful_summary_numbers_are_still_sent() -> None:
    content = build_evidence_packet(make_analysis(_frame())).content
    by_alias = {c["column"]: c for c in content["statistics"]["columns"]}
    assert set(by_alias) == {"Column_001", "Column_002"}
    for entry in by_alias.values():
        for field in ("count", "mean", "median", "std", "q1", "q3", "iqr"):
            assert field in entry, field
    columns = {c["column"]: c for c in content["columns"]}
    assert columns["Column_001"]["type"] == "numeric"
    assert columns["Column_003"]["type"] == "categorical"
    for entry in columns.values():
        assert "missing_count" in entry and "unique_count" in entry
    assert content["outliers"]["total_outlier_count"] >= 1  # the extremes are still flagged


def test_column_aliases_stay_deterministic_and_complete() -> None:
    analysis = make_analysis(_frame())
    first, second = build_evidence(analysis), build_evidence(analysis)
    assert first.packet.fingerprint == second.packet.fingerprint
    assert first.packet.canonical_json() == second.packet.canonical_json()
    assert [c["column"] for c in first.packet.content["columns"]] == [
        "Column_001",
        "Column_002",
        "Column_003",
    ]
    assert first.aliases.alias_for("x") == "Column_001"
    # original names never reach the provider-facing packet
    text = first.packet.canonical_json()
    assert '"x"' not in text and '"y"' not in text and '"group"' not in text


def test_changing_only_the_extremes_does_not_change_the_packet_when_aggregates_match() -> None:
    """Min/max are not an input of the packet any more: two datasets that differ only
    in their extremes but share every aggregate give the same evidence."""
    base = make_analysis(_frame())
    assert base.profile is not None and base.statistics is not None
    assert base.profile.columns[0]["max_value"] == HIGH_X
    packet = build_evidence_packet(base)
    mutated = base.model_copy(deep=True)
    assert mutated.profile is not None and mutated.statistics is not None
    mutated.profile.columns[0]["max_value"] = 123456789.0
    mutated.profile.columns[0]["min_value"] = -123456789.0
    mutated.statistics.columns[0].max = 123456789.0
    mutated.statistics.columns[0].min = -123456789.0
    assert build_evidence_packet(mutated).fingerprint == packet.fingerprint


def test_the_schema_version_records_the_shape_change() -> None:
    assert evidence.EVIDENCE_SCHEMA_VERSION >= 3
    content = build_evidence_packet(make_analysis(_frame())).content
    assert content["schema_version"] == evidence.EVIDENCE_SCHEMA_VERSION


def test_no_raw_row_values_reach_the_packet() -> None:
    frame = _frame()
    frame["group"] = ["ZZ_ROW_SENTINEL_A", "ZZ_ROW_SENTINEL_B"] * 20 + ["ZZ_ROW_SENTINEL_A"]
    text = build_evidence_packet(make_analysis(frame)).canonical_json()
    assert "ZZ_ROW_SENTINEL" not in text


# --- wording: what users and operators are told ---------------------------------


def test_the_ui_and_docs_no_longer_claim_that_no_cell_values_are_sent() -> None:
    tab = (ROOT / "frontend/src/components/analysis/ai-tab.tsx").read_text(encoding="utf-8")
    assert "never your column names or cell values" not in tab
    assert "exact smallest and largest value" in tab
    assert "individual rows" in tab and "column names" in tab
    assert "median can occasionally equal one of your values" in tab

    deployment = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
    assert "never column names or cell values" not in deployment
    assert "exact minimum and maximum" in deployment

    checklist = (ROOT / "RELEASE-CHECKLIST.md").read_text(encoding="utf-8")
    assert "(not names or cell values)" not in checklist
    assert "exact minimum/maximum" in checklist
    assert "anonymous numbers to a third party" not in checklist
