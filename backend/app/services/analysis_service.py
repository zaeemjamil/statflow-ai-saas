"""
Analysis orchestration.

Runs the analytics modules in order and assembles one result document.
This is the layer the Phase 8 API/UI and the Phase 9 AI service will
call; it is deliberately the *only* place that knows the pipeline
order, so each analytics module stays independently testable and none
of them import each other.

Stage names match the Phase 2 staged-progress UI labels exactly
(cleaning -> statistics -> outliers -> regression -> ...), so the
frontend can display real pipeline state rather than a generic spinner.

Scope: no OpenRouter call and no PDF generation here - those are
Phases 9 and 10. Execution is synchronous per the approved Phase 2
decision #4, but the stage structure below is exactly what a future
background-job runner would iterate over, so moving it async later
does not require rewriting the engine.
"""

from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from app.analytics import correlation, descriptive, outliers, profiling, visualization
from app.analytics.cleaning import CleaningConfig, clean_dataset
from app.analytics.regression import run_regression
from app.core.exceptions import ValidationException

logger = logging.getLogger("zaimex.analysis")

STAGES = (
    "profiling",
    "cleaning",
    "statistics",
    "correlations",
    "outliers",
    "regression",
    "visualizations",
)


def _classifications(profile: dict[str, Any]) -> dict[str, str]:
    return {column["name"]: column["classification"] for column in profile["columns"]}


def run_analysis(
    df: pd.DataFrame,
    cleaning_config: CleaningConfig | None = None,
    regression_target: str | None = None,
    regression_predictors: list[str] | None = None,
    profile: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run the full pipeline against an in-memory DataFrame.

    Args:
        df: the parsed dataset. Never mutated - cleaning takes a copy,
            and every later stage reads the cleaned copy.
        profile: an existing profile from the Phase 6 upload step. Passed
            in rather than recomputed so a single upload+analyse flow
            doesn't profile the same file twice (Phase 7 S13).
        regression_target / regression_predictors: when either is
            absent, regression is skipped and reported as not requested,
            rather than the engine guessing a target - guessing is
            precisely the StatFlow behaviour this rebuild removes.

    Never raises for a single failed stage: an analysis that can produce
    statistics but not regression should still return the statistics
    (Phase 7 S10). Only an unusable dataset fails the whole run.
    """
    if df.empty or len(df.columns) == 0:
        raise ValidationException(
            "This dataset has no rows to analyse.", error_code="empty_dataset"
        )

    profile = profile or profiling.profile_dataset(df)
    classifications = _classifications(profile)

    cleaned_df, cleaning_report = clean_dataset(df, classifications, cleaning_config)

    # Cleaning can change row counts and fill values, so the profile is
    # recomputed on the cleaned frame. Both are returned: the Phase 2
    # Data Quality tab shows the before/after comparison, which is the
    # whole point of making cleaning transparent.
    cleaned_profile = profiling.profile_dataset(cleaned_df)

    results: dict[str, Any] = {
        "stages": {},
        "profile": profile,
        "cleaned_profile": cleaned_profile,
        "cleaning": cleaning_report,
    }

    results["statistics"] = _run_stage(
        results,
        "statistics",
        lambda: descriptive.compute_descriptive_stats(cleaned_df, classifications),
    )
    results["correlations"] = _run_stage(
        results,
        "correlations",
        lambda: correlation.compute_correlations(cleaned_df, classifications),
    )
    results["outliers"] = _run_stage(
        results, "outliers", lambda: outliers.detect_outliers(cleaned_df, classifications)
    )

    if regression_target and regression_predictors:
        results["regression"] = _run_stage(
            results,
            "regression",
            lambda: run_regression(
                cleaned_df, classifications, regression_target, regression_predictors
            ),
        )
    else:
        results["stages"]["regression"] = "skipped"
        results["regression"] = {
            "available": False,
            "reason": "no_target_and_predictors_selected",
        }

    correlations_result = results.get("correlations")
    results["visualizations"] = _run_stage(
        results,
        "visualizations",
        lambda: visualization.recommend_charts(
            cleaned_df,
            classifications,
            correlations_result if isinstance(correlations_result, dict) else None,
        ),
    )

    results["stages"]["profiling"] = "completed"
    results["stages"]["cleaning"] = "completed"
    return results


def _run_stage(results: dict[str, Any], stage: str, operation: Any) -> dict[str, Any]:
    """Run one stage, converting a failure into a reported result rather
    than aborting the pipeline."""
    try:
        outcome: dict[str, Any] = operation()
        results["stages"][stage] = "completed"
        return outcome
    except ValidationException as exc:
        # An expected, explainable failure (e.g. an invalid regression
        # configuration). The user-facing message is safe to surface.
        results["stages"][stage] = "failed"
        return {"available": False, "error_code": exc.error_code, "message": exc.message}
    except Exception:
        # Unexpected: log the traceback server-side for debugging, but
        # return only a generic message - no stack trace reaches the
        # client (Phase 7 S10). The dataset itself is never logged
        # (Phase 7 S13, no sensitive uploaded content in logs).
        logger.exception("Analysis stage '%s' failed unexpectedly", stage)
        results["stages"][stage] = "failed"
        return {
            "available": False,
            "error_code": "stage_failed",
            "message": f"The {stage} step could not be completed for this dataset.",
        }
