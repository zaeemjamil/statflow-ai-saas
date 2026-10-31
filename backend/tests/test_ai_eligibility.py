"""Phase 9 Stage 1: which analyses may be explained, and why not when refused."""

from __future__ import annotations

import pandas as pd
import pytest

from app.ai import eligibility
from app.ai.eligibility import EvidenceNotEligible, check_eligibility
from app.ai.evidence import build_evidence_packet
from app.analytics.cleaning import CleaningConfig
from app.schemas.analysis import AnalysisPublic
from tests.ai_helpers import make_analysis, sample_frame


def _numeric_rows(count: int) -> pd.DataFrame:
    return pd.DataFrame(
        {"a": [float(i) for i in range(count)], "b": [i * 2.0 for i in range(count)]}
    )


def test_a_completed_analysis_is_eligible() -> None:
    result = check_eligibility(make_analysis(sample_frame()))
    assert result.eligible is True
    assert result.reason_code == eligibility.ELIGIBLE


@pytest.mark.parametrize("status", ["pending", "running", "failed"])
def test_an_analysis_that_is_not_completed_is_refused(status: str) -> None:
    analysis = make_analysis(sample_frame()).model_copy(update={"status": status})
    result = check_eligibility(analysis)
    assert (result.eligible, result.reason_code) == (False, eligibility.ANALYSIS_NOT_COMPLETED)


@pytest.mark.parametrize("stage_state", ["pending", "failed", "skipped"])
def test_statistics_stage_must_have_completed(stage_state: str) -> None:
    analysis = make_analysis(sample_frame())
    analysis = analysis.model_copy(
        update={"stages": {**analysis.stages, "statistics": stage_state}}
    )
    assert check_eligibility(analysis).reason_code == eligibility.STATISTICS_NOT_COMPLETED


def test_missing_profile_is_refused() -> None:
    analysis = make_analysis(sample_frame()).model_copy(update={"profile": None})
    assert check_eligibility(analysis).reason_code == eligibility.NO_DATASET_PROFILE


@pytest.mark.parametrize(
    ("rows", "eligible", "warnings"),
    [
        (4, False, ()),  # below the minimum: refused
        (5, True, (eligibility.SMALL_SAMPLE,)),  # the minimum: allowed, with a warning
        (29, True, (eligibility.SMALL_SAMPLE,)),  # last row count that warns
        (30, True, ()),  # no small-sample warning from this rule
    ],
)
def test_row_policy_boundaries_are_exact(
    rows: int, eligible: bool, warnings: tuple[str, ...]
) -> None:
    result = check_eligibility(make_analysis(_numeric_rows(rows)))
    assert result.eligible is eligible
    assert result.warnings == warnings
    if not eligible:
        assert result.reason_code == eligibility.TOO_FEW_ROWS
        assert f"only {rows} rows" in result.message
    else:
        assert result.reason_code == eligibility.ELIGIBLE


def test_the_policy_numbers_are_the_documented_ones_and_live_in_one_place() -> None:
    assert eligibility.MIN_ROWS_FOR_EXPLANATION == 5
    assert eligibility.SMALL_SAMPLE_ROWS == 30
    assert eligibility.SMALL_SAMPLE == "small_sample"


def test_a_refused_result_never_carries_warnings() -> None:
    analysis = make_analysis(_numeric_rows(20)).model_copy(update={"status": "failed"})
    assert check_eligibility(analysis).warnings == ()


def test_row_count_is_judged_after_cleaning_not_before() -> None:
    # 8 uploaded rows: 4 distinct plus 4 exact copies. Removing the copies leaves 4.
    frame = pd.concat([_numeric_rows(4), _numeric_rows(4)], ignore_index=True)
    kept = make_analysis(frame, cleaning=CleaningConfig(duplicate_strategy="keep"))
    removed = make_analysis(frame, cleaning=CleaningConfig(duplicate_strategy="remove"))
    assert check_eligibility(kept).eligible is True
    refused = check_eligibility(removed)
    assert refused.reason_code == eligibility.TOO_FEW_ROWS
    assert "only 4 rows" in refused.message


def test_the_warning_follows_cleaned_rows_too() -> None:
    # 32 uploaded rows, 4 copies: 28 remain after removal -> warns; kept -> 32, no warning.
    frame = pd.concat([_numeric_rows(28), _numeric_rows(28).head(4)], ignore_index=True)
    kept = make_analysis(frame, cleaning=CleaningConfig(duplicate_strategy="keep"))
    removed = make_analysis(frame, cleaning=CleaningConfig(duplicate_strategy="remove"))
    assert check_eligibility(kept).warnings == ()
    assert check_eligibility(removed).warnings == (eligibility.SMALL_SAMPLE,)


def test_small_sample_warning_reaches_the_packet_only_when_it_applies() -> None:
    for rows, expected in [(5, True), (29, True), (30, False), (100, False)]:
        packet = build_evidence_packet(make_analysis(_numeric_rows(rows)))
        warnings = packet.content["warnings"]
        if expected:
            assert warnings == [
                {"code": "small_sample", "rows_after_cleaning": rows, "threshold_rows": 30}
            ]
        else:
            assert warnings == []


def test_the_warning_is_part_of_the_evidence_content() -> None:
    # Either side of the 30-row line the evidence content itself differs.
    a = build_evidence_packet(make_analysis(_numeric_rows(29))).content["warnings"]
    b = build_evidence_packet(make_analysis(_numeric_rows(30))).content["warnings"]
    assert a != b


def test_a_dataset_without_numeric_statistics_is_refused() -> None:
    frame = pd.DataFrame({"colour": ["red", "blue", "green", "red"] * 5})
    analysis = make_analysis(frame)
    result = check_eligibility(analysis)
    assert (result.eligible, result.reason_code) == (False, eligibility.NO_NUMERIC_COLUMNS)


def test_optional_sections_never_block_eligibility() -> None:
    # One numeric column: no correlations are possible; no regression was run.
    analysis = make_analysis(pd.DataFrame({"only": [float(i) for i in range(20)]}))
    assert analysis.regression is None
    assert check_eligibility(analysis).eligible is True
    packet = build_evidence_packet(analysis)
    assert packet.content["coverage"]["regression"] == "not_run"
    # The correlation step ran but could not produce a result with one column.
    assert packet.content["coverage"]["correlations"] == "not_available"


def test_the_first_failing_rule_is_the_one_reported() -> None:
    analysis = make_analysis(sample_frame()).model_copy(
        update={"status": "running", "profile": None}
    )
    assert check_eligibility(analysis).reason_code == eligibility.ANALYSIS_NOT_COMPLETED


def test_building_for_an_ineligible_analysis_raises_with_the_specific_code() -> None:
    analysis: AnalysisPublic = make_analysis(sample_frame()).model_copy(update={"status": "failed"})
    with pytest.raises(EvidenceNotEligible) as caught:
        build_evidence_packet(analysis)
    assert caught.value.error_code == eligibility.ANALYSIS_NOT_COMPLETED
    assert caught.value.status_code == 409
    assert caught.value.result.eligible is False
