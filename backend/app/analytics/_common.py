"""
Shared helpers for the analytics modules.

The single most important job here is `safe_float`. Every analytics
result eventually becomes JSON (API response, JSONB column, AI service
input, PDF), and NaN/Infinity are *not* valid JSON - `json.dumps`
emits bare `NaN`/`Infinity` tokens that strict parsers reject. pandas
produces both routinely and legitimately: the standard deviation of a
single-row column is NaN, correlation against a constant column is NaN.
So every float crossing the boundary out of pandas goes through
`safe_float`, which maps those to None (JSON `null`).
"""

from __future__ import annotations

import math
from typing import Any

import pandas as pd


def safe_float(value: Any) -> float | None:
    """Convert a numpy/pandas scalar to a plain JSON-safe float.

    Returns None for NaN, infinity, None/NA, or anything non-numeric -
    all of which are meaningful "no value" results here rather than
    errors (e.g. std of one observation), so they must not raise.
    """
    if value is None or value is pd.NA:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return result


def safe_int(value: Any) -> int | None:
    if value is None or value is pd.NA:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(result) or math.isinf(result):
        return None
    return int(result)


def numeric_columns(df: pd.DataFrame, classifications: dict[str, str]) -> list[str]:
    """Columns the *profiler* classified as numeric, intersected with
    what's actually present in this DataFrame.

    Deliberately driven by the profiler's classification rather than a
    fresh `is_numeric_dtype` check, so one component decides what
    "numeric" means for the whole engine. That matters for booleans in
    particular: pandas calls them numeric, the profiler calls them
    categorical (a 2-level category is not a continuous variable), and
    regression/outliers must agree with the profiler or the frontend's
    variable pickers would offer columns the backend then rejects.
    """
    return [
        name
        for name, classification in classifications.items()
        if classification == "numeric" and name in df.columns
    ]


def columns_by_classification(
    df: pd.DataFrame, classifications: dict[str, str], kind: str
) -> list[str]:
    return [
        name
        for name, classification in classifications.items()
        if classification == kind and name in df.columns
    ]
