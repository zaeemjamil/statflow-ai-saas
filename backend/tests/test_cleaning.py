"""Cleaning module tests - transparency, correctness, non-mutation."""

from __future__ import annotations

import pandas as pd

from app.analytics.cleaning import CleaningConfig, clean_dataset
from tests.analytics_fixtures import (
    duplicate_rows_dataset,
    missing_values_dataset,
    numeric_classifications,
)


def test_median_imputation_fills_numeric_with_the_correct_value() -> None:
    df = missing_values_dataset()
    cleaned, report = clean_dataset(df, numeric_classifications(df))

    # Non-missing values are [2, 4, 10] -> median 4.0
    assert cleaned["quantity"].isna().sum() == 0
    action = next(a for a in report["column_actions"] if a["column"] == "quantity")
    assert action["method"] == "median"
    assert action["fill_value"] == 4.0
    assert action["values_changed"] == 2


def test_mode_imputation_fills_categorical_with_the_correct_value() -> None:
    df = missing_values_dataset()
    cleaned, report = clean_dataset(df, numeric_classifications(df))

    # Non-missing are [p, p, q] -> mode 'p'
    assert cleaned["label"].isna().sum() == 0
    action = next(a for a in report["column_actions"] if a["column"] == "label")
    assert action["method"] == "mode"
    assert action["fill_value"] == "p"
    assert action["values_changed"] == 2


def test_unchanged_strategy_leaves_missing_values_in_place() -> None:
    df = missing_values_dataset()
    config = CleaningConfig(numeric_strategy="unchanged", categorical_strategy="unchanged")
    cleaned, report = clean_dataset(df, numeric_classifications(df), config)

    assert cleaned["quantity"].isna().sum() == 2
    assert report["missing_after"] == report["missing_before"]
    assert report["missing_values_imputed"] == 0
    assert all(a["action"] == "left_unchanged" for a in report["column_actions"])


def test_duplicates_are_detected_but_kept_by_default() -> None:
    df = duplicate_rows_dataset()
    cleaned, report = clean_dataset(df, numeric_classifications(df))

    assert report["duplicates_before"] == 2
    assert report["duplicates_removed"] == 0
    assert len(cleaned) == len(df)


def test_duplicates_are_removed_when_requested() -> None:
    df = duplicate_rows_dataset()
    config = CleaningConfig(duplicate_strategy="remove")
    cleaned, report = clean_dataset(df, numeric_classifications(df), config)

    assert report["duplicates_before"] == 2
    assert report["duplicates_removed"] == 2
    assert report["rows_before"] == 6
    assert report["rows_after"] == 4
    assert len(cleaned) == 4


def test_imputation_never_creates_duplicates_that_delete_real_rows() -> None:
    """Regression guard for a real bug found while building this module.

    Originally imputation ran before deduplication, so an all-missing
    row could be imputed into an exact copy of a real row and then
    deleted as a "duplicate" - destroying a genuine observation because
    of a value the engine itself had just invented. It also made the
    report self-contradictory (1 duplicate detected, 2 rows removed).
    """
    df = pd.DataFrame({"n": [1.0, None, 3.0, 3.0], "c": ["a", None, "b", "b"]})
    config = CleaningConfig(duplicate_strategy="remove")
    cleaned, report = clean_dataset(df, {"n": "numeric", "c": "categorical"}, config)

    # Exactly the one genuinely duplicated source row is removed.
    assert report["duplicates_before"] == 1
    assert report["duplicates_removed"] == 1
    assert report["rows_after"] == 3
    assert len(cleaned) == 3


def test_cleaning_never_mutates_the_source_dataframe() -> None:
    df = missing_values_dataset()
    before = df.copy()
    clean_dataset(df, numeric_classifications(df), CleaningConfig(duplicate_strategy="remove"))
    pd.testing.assert_frame_equal(df, before)


def test_column_of_entirely_missing_values_is_reported_not_invented() -> None:
    df = pd.DataFrame({"empty_col": [None, None, None], "other": [1.0, 2.0, 3.0]})
    cleaned, report = clean_dataset(df, {"empty_col": "numeric", "other": "numeric"})

    action = next(a for a in report["column_actions"] if a["column"] == "empty_col")
    assert action["action"] == "left_unchanged"
    assert action["reason"] == "no_non_missing_values"
    assert cleaned["empty_col"].isna().sum() == 3


def test_report_counts_are_internally_consistent() -> None:
    df = missing_values_dataset()
    _, report = clean_dataset(df, numeric_classifications(df))
    assert report["missing_before"] - report["missing_after"] == report["missing_values_imputed"]
    assert report["rows_before"] - report["rows_after"] == report["rows_removed"]
