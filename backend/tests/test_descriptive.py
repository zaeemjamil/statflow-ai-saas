"""Descriptive statistics - numerical correctness against known values."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from app.analytics.descriptive import compute_descriptive_stats
from tests.analytics_fixtures import (
    all_categorical_dataset,
    constant_column_dataset,
    missing_values_dataset,
    numeric_classifications,
)

TOLERANCE = 1e-9


def _stats_for(df: pd.DataFrame, column: str) -> dict[str, Any]:
    result = compute_descriptive_stats(df, numeric_classifications(df))
    return next(c for c in result["columns"] if c["column"] == column)


def test_every_required_metric_is_present() -> None:
    df = pd.DataFrame({"v": [1.0, 2.0, 3.0, 4.0]})
    stats = _stats_for(df, "v")
    for metric in ("count", "mean", "median", "std", "min", "q1", "q3", "max", "iqr"):
        assert metric in stats, f"missing required metric: {metric}"


def test_known_values_odd_number_of_observations() -> None:
    # [2, 4, 4, 4, 5, 5, 7, 9] is the classic textbook set, but use an
    # odd count here so the median is a true middle element.
    df = pd.DataFrame({"v": [1.0, 3.0, 5.0, 7.0, 9.0]})
    stats = _stats_for(df, "v")

    assert stats["count"] == 5
    assert stats["mean"] == pytest.approx(5.0, abs=TOLERANCE)
    assert stats["median"] == pytest.approx(5.0, abs=TOLERANCE)
    assert stats["min"] == pytest.approx(1.0, abs=TOLERANCE)
    assert stats["max"] == pytest.approx(9.0, abs=TOLERANCE)
    # Sample std (ddof=1) of this set = sqrt(40/4) = sqrt(10)
    assert stats["std"] == pytest.approx(10.0**0.5, abs=TOLERANCE)


def test_known_values_even_number_of_observations() -> None:
    df = pd.DataFrame({"v": [1.0, 2.0, 3.0, 4.0]})
    stats = _stats_for(df, "v")

    assert stats["count"] == 4
    assert stats["mean"] == pytest.approx(2.5, abs=TOLERANCE)
    # Even count -> median is the mean of the two middle values
    assert stats["median"] == pytest.approx(2.5, abs=TOLERANCE)
    assert stats["q1"] == pytest.approx(1.75, abs=TOLERANCE)
    assert stats["q3"] == pytest.approx(3.25, abs=TOLERANCE)
    assert stats["iqr"] == pytest.approx(1.5, abs=TOLERANCE)


def test_uses_sample_standard_deviation_not_population() -> None:
    """The distinction is not cosmetic: for this set the two differ by
    ~11%, and StatFlow's original hand-rolled version used n-1, so
    matching it matters for continuity with prior reports."""
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    df = pd.DataFrame({"v": values})
    stats = _stats_for(df, "v")

    series = pd.Series(values)
    assert stats["std"] == pytest.approx(series.std(ddof=1), abs=TOLERANCE)
    assert stats["std"] != pytest.approx(series.std(ddof=0), abs=TOLERANCE)


def test_iqr_equals_q3_minus_q1() -> None:
    df = pd.DataFrame({"v": [1.0, 5.0, 9.0, 13.0, 17.0, 21.0]})
    stats = _stats_for(df, "v")
    assert stats["iqr"] == pytest.approx(stats["q3"] - stats["q1"], abs=TOLERANCE)


def test_missing_values_are_excluded_and_counted() -> None:
    df = missing_values_dataset()
    stats = _stats_for(df, "quantity")

    # Non-missing values are [2, 4, 10]
    assert stats["count"] == 3
    assert stats["missing_count"] == 2
    assert stats["mean"] == pytest.approx((2 + 4 + 10) / 3, abs=TOLERANCE)
    assert stats["median"] == pytest.approx(4.0, abs=TOLERANCE)


def test_constant_column_has_zero_spread_not_null() -> None:
    df = constant_column_dataset()
    stats = _stats_for(df, "fixed")

    assert stats["std"] == pytest.approx(0.0, abs=TOLERANCE)
    assert stats["iqr"] == pytest.approx(0.0, abs=TOLERANCE)
    assert stats["mean"] == pytest.approx(7.0, abs=TOLERANCE)


def test_single_observation_yields_null_std_without_crashing() -> None:
    """Sample std divides by n-1, which is zero for one observation, so
    the value is genuinely undefined - null, not a crash and not 0.0."""
    df = pd.DataFrame({"v": [42.0, None, None]})
    stats = _stats_for(df, "v")

    assert stats["count"] == 1
    assert stats["std"] is None
    assert stats["mean"] == pytest.approx(42.0, abs=TOLERANCE)


def test_categorical_columns_are_skipped_not_crashed_on() -> None:
    df = all_categorical_dataset()
    result = compute_descriptive_stats(df, numeric_classifications(df))

    assert result["columns"] == []
    assert result["numeric_column_count"] == 0
    assert set(result["skipped_columns"]) == {"colour", "shape"}


def test_mixed_dataset_only_describes_numeric_columns() -> None:
    df = pd.DataFrame({"n": [1.0, 2.0], "c": ["a", "b"]})
    result = compute_descriptive_stats(df, numeric_classifications(df))
    assert [c["column"] for c in result["columns"]] == ["n"]
