"""End-to-end orchestration tests - every stage coexisting on realistic
datasets, plus graceful degradation when one stage can't run."""

from __future__ import annotations

import json

import pandas as pd
import pytest

from app.analytics.cleaning import CleaningConfig
from app.core.exceptions import ValidationException
from app.schemas.analysis import AnalysisResult
from app.services.analysis_service import run_analysis
from tests.analytics_fixtures import (
    all_categorical_dataset,
    mixed_dataset,
    regression_dataset,
)


def _realistic_dataset() -> pd.DataFrame:
    """Mixed types, missing values, a duplicate row and a real linear
    relationship - the closest thing to a genuine user upload, and
    sharing no column names with StatFlow's retail dataset."""
    df = regression_dataset(n=120, noise=3.0)
    df["region"] = ["north", "south", "east", "west"] * 30
    df["captured_on"] = pd.to_datetime("2026-02-01") + pd.to_timedelta(range(120), unit="D")
    df.loc[0:4, "driver_a"] = None
    return pd.concat([df, df.iloc[[7]]], ignore_index=True)


def test_full_pipeline_completes_every_stage() -> None:
    result = run_analysis(
        _realistic_dataset(),
        regression_target="target",
        regression_predictors=["driver_a", "driver_b"],
    )

    assert result["stages"]["profiling"] == "completed"
    assert result["stages"]["cleaning"] == "completed"
    assert result["stages"]["statistics"] == "completed"
    assert result["stages"]["correlations"] == "completed"
    assert result["stages"]["outliers"] == "completed"
    assert result["stages"]["regression"] == "completed"
    assert result["stages"]["visualizations"] == "completed"


def test_full_pipeline_output_matches_the_declared_schema() -> None:
    """Guards against the code and the typed contracts drifting apart -
    these structures feed Phase 8's UI, Phase 9's AI and Phase 10's PDF."""
    result = run_analysis(
        _realistic_dataset(),
        regression_target="target",
        regression_predictors=["driver_a"],
    )
    validated = AnalysisResult.model_validate(
        {key: value for key, value in result.items() if key in AnalysisResult.model_fields}
    )
    assert validated.regression.available is True
    assert validated.statistics.numeric_column_count >= 3


def test_full_result_is_json_serializable() -> None:
    result = run_analysis(
        _realistic_dataset(), regression_target="target", regression_predictors=["driver_b"]
    )
    assert json.loads(json.dumps(result)) == result


def test_regression_is_skipped_rather_than_guessed_when_not_requested() -> None:
    """StatFlow hardcoded its target; guessing one is exactly the
    behaviour this rebuild removes."""
    result = run_analysis(_realistic_dataset())

    assert result["stages"]["regression"] == "skipped"
    assert result["regression"]["available"] is False
    assert result["regression"]["reason"] == "no_target_and_predictors_selected"


def test_a_failed_regression_does_not_abort_the_other_stages() -> None:
    """An analysis that can produce statistics but not regression must
    still return the statistics (Phase 7 S10)."""
    result = run_analysis(
        _realistic_dataset(),
        regression_target="target",
        regression_predictors=["region"],  # categorical - invalid predictor
    )

    assert result["stages"]["regression"] == "failed"
    assert result["regression"]["available"] is False
    assert result["regression"]["error_code"] == "regression_predictor_not_numeric"
    # everything else still succeeded
    assert result["stages"]["statistics"] == "completed"
    assert result["stages"]["correlations"] == "completed"
    assert result["statistics"]["columns"]


def test_failed_stage_message_is_safe_and_has_no_stack_trace() -> None:
    result = run_analysis(
        _realistic_dataset(),
        regression_target="target",
        regression_predictors=["nonexistent_column"],
    )
    message = result["regression"]["message"]

    assert "Traceback" not in message
    assert "statsmodels" not in message
    assert "nonexistent_column" in message  # tells the user what to fix


def test_cleaning_report_is_carried_through_the_pipeline() -> None:
    result = run_analysis(
        _realistic_dataset(), cleaning_config=CleaningConfig(duplicate_strategy="remove")
    )

    assert result["cleaning"]["duplicates_removed"] == 1
    assert result["cleaning"]["missing_values_imputed"] == 5


def test_before_and_after_profiles_are_both_returned() -> None:
    """The Phase 2 Data Quality tab shows the comparison - that's the
    whole point of transparent cleaning."""
    result = run_analysis(
        _realistic_dataset(), cleaning_config=CleaningConfig(duplicate_strategy="remove")
    )

    assert result["profile"]["row_count"] == 121
    assert result["cleaned_profile"]["row_count"] == 120
    assert result["profile"]["total_missing_values"] == 5
    assert result["cleaned_profile"]["total_missing_values"] == 0


def test_source_dataframe_is_never_mutated_by_the_pipeline() -> None:
    df = _realistic_dataset()
    before = df.copy()
    run_analysis(
        df,
        cleaning_config=CleaningConfig(duplicate_strategy="remove"),
        regression_target="target",
        regression_predictors=["driver_b"],
    )
    pd.testing.assert_frame_equal(df, before)


def test_all_categorical_dataset_degrades_gracefully() -> None:
    """No numeric columns at all: statistics and correlation have
    nothing to report, but the run must not fail - count charts are
    still useful."""
    result = run_analysis(all_categorical_dataset())

    assert result["statistics"]["numeric_column_count"] == 0
    assert result["correlations"]["available"] is False
    assert result["visualizations"]["available"] is True
    assert result["stages"]["statistics"] == "completed"


def test_mixed_dataset_produces_results_for_every_module() -> None:
    result = run_analysis(mixed_dataset())

    assert result["statistics"]["columns"]
    assert result["correlations"]["pairs"]
    assert result["outliers"]["columns"]
    assert result["visualizations"]["charts"]


def test_empty_dataset_is_rejected_with_a_clear_error() -> None:
    with pytest.raises(ValidationException) as exc_info:
        run_analysis(pd.DataFrame())
    assert exc_info.value.error_code == "empty_dataset"


def test_supplied_profile_is_reused_rather_than_recomputed() -> None:
    """Phase 6 already profiled the file on upload; re-profiling the
    same data would be wasted work (Phase 7 S13)."""
    from app.analytics import profiling

    df = mixed_dataset()
    supplied = profiling.profile_dataset(df)
    result = run_analysis(df, profile=supplied)

    assert result["profile"] is supplied
