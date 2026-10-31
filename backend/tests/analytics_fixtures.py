"""
Fixture datasets for the analytics engine tests.

Deliberately none of these use StatFlow's retail-sales column names.
Several use values chosen so the correct answer can be derived by hand
(see the docstrings), which is what lets the tests assert *correct
numbers* rather than merely "it returned something" (Phase 7 S12).
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def mixed_dataset() -> pd.DataFrame:
    """Numeric + categorical + date, the realistic general case."""
    return pd.DataFrame(
        {
            "measured_on": pd.to_datetime(
                ["2026-03-01", "2026-03-02", "2026-03-03", "2026-03-04", "2026-03-05", "2026-03-06"]
            ),
            "temperature_c": [12.5, 14.0, 11.0, 19.5, 13.0, 15.5],
            "humidity_pct": [60.0, 55.0, 70.0, 40.0, 65.0, 50.0],
            "site": ["north", "south", "north", "east", "south", "north"],
        }
    )


def all_numeric_dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "alpha": [1.0, 2.0, 3.0, 4.0],
            "beta": [10.0, 20.0, 30.0, 40.0],
            "gamma": [4.0, 3.0, 2.0, 1.0],
        }
    )


def all_categorical_dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {"colour": ["red", "blue", "red", "green"], "shape": ["round", "square", "round", "round"]}
    )


def date_and_numeric_dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "recorded_at": pd.to_datetime(
                ["2026-01-01", "2026-01-02", "2026-01-03", "2026-01-04", "2026-01-05"]
            ),
            "reading": [5.0, 7.0, 6.0, 9.0, 8.0],
        }
    )


def missing_values_dataset() -> pd.DataFrame:
    """Numeric column: non-missing values are [2, 4, 10] -> median 4.0.
    Categorical: non-missing are [p, p, q] -> mode 'p'."""
    return pd.DataFrame(
        {
            "quantity": [2.0, np.nan, 4.0, 10.0, np.nan],
            "label": ["p", "p", None, "q", None],
        }
    )


def duplicate_rows_dataset() -> pd.DataFrame:
    """6 rows, of which 2 are duplicates of earlier rows -> 4 unique."""
    return pd.DataFrame(
        {
            "code": ["a", "b", "a", "c", "b", "d"],
            "value": [1.0, 2.0, 1.0, 3.0, 2.0, 4.0],
        }
    )


def constant_column_dataset() -> pd.DataFrame:
    return pd.DataFrame({"varying": [1.0, 2.0, 3.0, 4.0], "fixed": [7.0, 7.0, 7.0, 7.0]})


def tiny_dataset() -> pd.DataFrame:
    return pd.DataFrame({"x": [1.0, 2.0], "y": [3.0, 4.0]})


def regression_dataset(n: int = 200, noise: float = 0.0, seed: int = 11) -> pd.DataFrame:
    """Analytically known: target = 5 + 3*driver_a - 2*driver_b (+noise).

    With noise=0 the fitted coefficients must recover 5, 3 and -2 to
    floating-point precision, which is a real correctness check rather
    than a smoke test.
    """
    rng = np.random.default_rng(seed)
    driver_a = rng.normal(10.0, 2.0, n)
    driver_b = rng.normal(4.0, 1.0, n)
    target = 5.0 + 3.0 * driver_a - 2.0 * driver_b
    if noise:
        target = target + rng.normal(0.0, noise, n)
    return pd.DataFrame({"driver_a": driver_a, "driver_b": driver_b, "target": target})


def collinear_dataset(n: int = 60, seed: int = 5) -> pd.DataFrame:
    """`total` is exactly `part_one + part_two`, so the three together
    form a rank-deficient design matrix."""
    rng = np.random.default_rng(seed)
    part_one = rng.normal(0.0, 1.0, n)
    part_two = rng.normal(0.0, 1.0, n)
    return pd.DataFrame(
        {
            "part_one": part_one,
            "part_two": part_two,
            "total": part_one + part_two,
            "outcome": 2.0 * part_one + rng.normal(0.0, 0.1, n),
        }
    )


def unusual_column_names_dataset() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Column With Spaces": [1.0, 2.0, 3.0, 4.0],
            "col-with-dashes": [4.0, 3.0, 2.0, 1.0],
            "UPPER_CASE": ["a", "b", "a", "b"],
            "unicode_café_☕": [10.0, 20.0, 30.0, 40.0],
            "123numeric_start": [1.0, 1.0, 2.0, 2.0],
        }
    )


def outlier_dataset() -> pd.DataFrame:
    """Values 1..10 plus 100.

    By hand: Q1 = 3.5, Q3 = 8.5, IQR = 5.0,
    lower = 3.5 - 7.5 = -4.0, upper = 8.5 + 7.5 = 16.0.
    So exactly one outlier (100), at positional index 10.
    """
    return pd.DataFrame({"reading": [1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10, 100]})


def numeric_classifications(df: pd.DataFrame) -> dict[str, str]:
    """Classify every column the way the profiler would, for tests that
    don't need to exercise profiling itself."""
    classifications: dict[str, str] = {}
    for column in df.columns:
        series = df[column]
        if pd.api.types.is_bool_dtype(series):
            classifications[column] = "categorical"
        elif pd.api.types.is_numeric_dtype(series):
            classifications[column] = "numeric"
        elif pd.api.types.is_datetime64_any_dtype(series):
            classifications[column] = "date"
        else:
            classifications[column] = "categorical"
    return classifications
