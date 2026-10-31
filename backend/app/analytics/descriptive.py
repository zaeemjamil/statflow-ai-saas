"""
Descriptive statistics for every profiler-detected numeric column.

Generalizes StatFlow's `Code in Python` node (Phase 1 audit S5/S7),
which looped in pure Python over seven hardcoded retail column names
and computed six statistics. The mathematical intent is preserved -
including its use of the *sample* standard deviation - but the
implementation is vectorized on pandas and driven entirely by the
profiler's column classifications, and it adds Q1/Q3/IQR, which the
original never computed at all.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.analytics._common import numeric_columns, safe_float, safe_int

# Every metric name here is also a `statistics.metric` value in the
# Phase 4 schema, so the persistence layer can map results with no
# translation table.
METRIC_NAMES = ("count", "mean", "median", "std", "min", "q1", "q3", "max", "iqr")


def compute_descriptive_stats(df: pd.DataFrame, classifications: dict[str, str]) -> dict[str, Any]:
    """Per-column descriptive statistics, plus the columns skipped.

    Every statistic is computed on the column's non-missing values -
    pandas' default `skipna=True` behaviour - so a column with missing
    values still yields meaningful statistics for the values that do
    exist, with `count` reporting how many that was. That count is the
    honest denominator for everything else in the row.

    A column that cannot produce a meaningful statistic never raises:
    a single-observation column has no sample standard deviation
    (division by n-1 = 0), and pandas returns NaN, which `safe_float`
    maps to JSON null. One awkward column must not take down the whole
    analysis (Phase 7 S10).
    """
    targets = numeric_columns(df, classifications)
    columns: list[dict[str, Any]] = []

    for name in targets:
        series = pd.to_numeric(df[name], errors="coerce")
        columns.append(_describe_series(name, series))

    return {
        "columns": columns,
        "numeric_column_count": len(columns),
        "skipped_columns": [c for c in df.columns if c not in targets],
    }


def _describe_series(name: str, series: pd.Series) -> dict[str, Any]:
    non_null = series.dropna()
    q1 = non_null.quantile(0.25) if not non_null.empty else None
    q3 = non_null.quantile(0.75) if not non_null.empty else None
    iqr = (q3 - q1) if (q1 is not None and q3 is not None) else None

    return {
        "column": name,
        # count = non-missing observations, matching pandas/SQL
        # convention and the denominator the other statistics used.
        "count": safe_int(non_null.count()) or 0,
        "missing_count": safe_int(series.isna().sum()) or 0,
        "mean": safe_float(non_null.mean()),
        "median": safe_float(non_null.median()),
        # ddof=1 (sample standard deviation) stated explicitly rather
        # than relying on the pandas default. It happens to match today
        # (verified against this pandas version), but numpy's default
        # is ddof=0, so an explicit value documents the intent and
        # survives anyone porting this to numpy. It also matches
        # StatFlow's original hand-rolled n-1 divisor.
        "std": safe_float(non_null.std(ddof=1)),
        "min": safe_float(non_null.min()),
        "q1": safe_float(q1),
        "q3": safe_float(q3),
        "max": safe_float(non_null.max()),
        "iqr": safe_float(iqr),
    }
