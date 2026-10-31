"""Outlier detection - verified against hand-computed IQR boundaries."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from app.analytics.outliers import detect_outliers
from tests.analytics_fixtures import (
    constant_column_dataset,
    numeric_classifications,
    outlier_dataset,
)

TOLERANCE = 1e-9


def _column_result(df: pd.DataFrame, column: str) -> dict[str, Any]:
    result = detect_outliers(df, numeric_classifications(df))
    return next(c for c in result["columns"] if c["column"] == column)


def test_known_iqr_boundaries_are_computed_correctly() -> None:
    """Values 1..10 plus 100. By hand: Q1=3.5, Q3=8.5, IQR=5.0,
    lower = 3.5 - 1.5*5 = -4.0, upper = 8.5 + 1.5*5 = 16.0."""
    result = _column_result(outlier_dataset(), "reading")

    assert result["q1"] == pytest.approx(3.5, abs=TOLERANCE)
    assert result["q3"] == pytest.approx(8.5, abs=TOLERANCE)
    assert result["iqr"] == pytest.approx(5.0, abs=TOLERANCE)
    assert result["lower_bound"] == pytest.approx(-4.0, abs=TOLERANCE)
    assert result["upper_bound"] == pytest.approx(16.0, abs=TOLERANCE)


def test_correct_outlier_count_and_indices() -> None:
    result = _column_result(outlier_dataset(), "reading")

    assert result["outlier_count"] == 1
    assert result["outlier_indices"] == [10]  # the value 100
    assert result["detected"] is True


def test_outlier_percentage_is_correct() -> None:
    result = _column_result(outlier_dataset(), "reading")
    # 1 outlier out of 11 observations
    assert result["outlier_percentage"] == pytest.approx(100 / 11, abs=1e-3)


def test_dataset_without_outliers_reports_none() -> None:
    df = pd.DataFrame({"steady": [10.0, 11.0, 12.0, 13.0, 14.0, 15.0]})
    result = _column_result(df, "steady")

    assert result["outlier_count"] == 0
    assert result["outlier_indices"] == []


def test_constant_column_does_not_flag_everything() -> None:
    """IQR is 0 for a constant column, collapsing both bounds onto one
    value; without a guard the method would flag every differing value.
    Detection is reported unavailable instead of producing noise."""
    df = constant_column_dataset()
    result = _column_result(df, "fixed")

    assert result["detected"] is False
    assert result["reason"] == "zero_iqr_constant_column"
    assert result["outlier_count"] == 0


def test_missing_values_are_excluded_from_the_calculation() -> None:
    df = pd.DataFrame({"v": [1.0, 2.0, 3.0, 4.0, None, None, 5.0]})
    result = _column_result(df, "v")

    assert result["observation_count"] == 5
    assert result["detected"] is True


def test_column_of_all_missing_values_is_handled_safely() -> None:
    """Must be explicitly float dtype: a column built from bare `None`
    becomes pandas `object` dtype, which the profiler classifies as
    categorical, so it would never reach outlier detection at all. A
    genuinely all-missing *numeric* column is float with NaN - that's
    the case this guards."""
    df = pd.DataFrame({"empty": pd.Series([None, None, None], dtype="float64")})
    result = _column_result(df, "empty")

    assert result["detected"] is False
    assert result["reason"] == "no_non_missing_values"


def test_outliers_are_never_removed_from_the_data() -> None:
    """Detection is informational only (Phase 7 S4)."""
    df = outlier_dataset()
    before = df.copy()
    detect_outliers(df, numeric_classifications(df))
    pd.testing.assert_frame_equal(df, before)


def test_index_list_is_bounded_for_large_outlier_counts() -> None:
    """A pathological column must not produce an unbounded payload; the
    count stays exact while the index list is capped."""
    from app.analytics.outliers import MAX_REPORTED_INDICES

    # Tight cluster with many extreme values far outside the bounds.
    values = [0.0] * 500 + [1.0] * 500 + [10_000.0] * 300
    df = pd.DataFrame({"skewed": values})
    result = _column_result(df, "skewed")

    assert result["outlier_count"] == 300
    assert len(result["outlier_indices"]) == MAX_REPORTED_INDICES
    assert result["outlier_indices_truncated"] is True


def test_small_dataset_does_not_crash() -> None:
    df = pd.DataFrame({"x": [1.0, 2.0]})
    result = _column_result(df, "x")
    assert result["outlier_count"] == 0
