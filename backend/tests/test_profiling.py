"""Unit tests for app.analytics.profiling — pure DataFrame in, dict out,
no DB/HTTP involved. Column-classification edge cases mirror the
reasoning documented directly in profiling.py."""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.analytics.profiling import profile_dataset


def _column(profile: dict[str, Any], name: str) -> dict[str, Any]:
    return next(c for c in profile["columns"] if c["name"] == name)


def test_mixed_numeric_and_categorical_dataset() -> None:
    df = pd.DataFrame({"Revenue": [100.0, 200.0, 300.0], "Region": ["East", "West", "East"]})
    profile = profile_dataset(df)

    assert profile["row_count"] == 3
    assert profile["column_count"] == 2
    assert profile["numeric_column_count"] == 1
    assert profile["categorical_column_count"] == 1
    assert profile["date_column_count"] == 0

    revenue = _column(profile, "Revenue")
    assert revenue["classification"] == "numeric"
    assert revenue["min_value"] == 100.0
    assert revenue["max_value"] == 300.0

    region = _column(profile, "Region")
    assert region["classification"] == "categorical"
    assert region["unique_count"] == 2
    assert region["min_value"] is None


def test_all_numeric_dataset() -> None:
    df = pd.DataFrame({"a": [1, 2, 3], "b": [4.5, 5.5, 6.5]})
    profile = profile_dataset(df)
    assert profile["numeric_column_count"] == 2
    assert profile["categorical_column_count"] == 0
    assert profile["date_column_count"] == 0


def test_all_categorical_dataset() -> None:
    df = pd.DataFrame({"a": ["x", "y", "z"], "b": ["p", "q", "r"]})
    profile = profile_dataset(df)
    assert profile["numeric_column_count"] == 0
    assert profile["categorical_column_count"] == 2


def test_date_column_is_detected() -> None:
    df = pd.DataFrame(
        {"order_date": ["2026-01-01", "2026-01-02", "2026-01-03"], "amount": [10, 20, 30]}
    )
    profile = profile_dataset(df)
    assert profile["date_column_count"] == 1
    assert _column(profile, "order_date")["classification"] == "date"
    assert _column(profile, "amount")["classification"] == "numeric"


def test_digit_string_id_column_is_not_misclassified_as_date() -> None:
    # The exact regression case documented in profiling.py's own
    # comment: an unbroken numeric-looking ID string must not be
    # classified as a date just because pandas *can* parse it as one.
    df = pd.DataFrame({"record_id": [str(20260100 + i) for i in range(20)]})
    profile = profile_dataset(df)
    assert profile["columns"][0]["classification"] != "date"


def test_missing_values_are_counted() -> None:
    df = pd.DataFrame({"a": [1, None, 3, None]})
    profile = profile_dataset(df)
    assert profile["total_missing_values"] == 2
    col = profile["columns"][0]
    assert col["missing_count"] == 2
    assert col["missing_percentage"] == 50.0


def test_duplicate_rows_are_counted() -> None:
    df = pd.DataFrame({"a": [1, 1, 2], "b": ["x", "x", "y"]})
    profile = profile_dataset(df)
    assert profile["duplicate_row_count"] == 1


def test_header_only_dataset_profiles_as_zero_rows_without_crashing() -> None:
    df = pd.DataFrame({"a": pd.Series([], dtype="object"), "b": pd.Series([], dtype="float64")})
    profile = profile_dataset(df)
    assert profile["row_count"] == 0
    assert profile["column_count"] == 2
    for col in profile["columns"]:
        assert col["missing_percentage"] == 0.0
        assert col["is_unique"] is False


def test_unusual_column_names_are_preserved() -> None:
    df = pd.DataFrame({"Column With Spaces": [1, 2], "日本語": [3, 4], "123_leading_digit": [5, 6]})
    profile = profile_dataset(df)
    assert {c["name"] for c in profile["columns"]} == {
        "Column With Spaces",
        "日本語",
        "123_leading_digit",
    }


def test_small_single_row_dataset() -> None:
    df = pd.DataFrame({"a": [1], "b": ["x"]})
    profile = profile_dataset(df)
    assert profile["row_count"] == 1
    for col in profile["columns"]:
        assert col["is_unique"] is True


def test_boolean_column_is_categorical_not_numeric() -> None:
    df = pd.DataFrame({"is_active": [True, False, True]})
    profile = profile_dataset(df)
    assert profile["columns"][0]["classification"] == "categorical"


def test_column_with_mixed_types_does_not_crash() -> None:
    df = pd.DataFrame({"mixed": [1, "two", 3.0, None, "5"]})
    profile = profile_dataset(df)  # the assertion is simply that this doesn't raise
    assert profile["row_count"] == 5


def test_profiling_does_not_mutate_the_source_dataframe() -> None:
    df = pd.DataFrame({"a": [3, 1, 2, 1], "b": ["z", "x", "y", "x"]})
    original = df.copy(deep=True)
    profile_dataset(df)
    pd.testing.assert_frame_equal(df, original)
