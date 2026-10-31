"""
IQR-based outlier detection.

New capability - the Phase 1 audit found no outlier logic anywhere in
StatFlow. Purely informational: nothing is removed, flagged rows stay
in the dataset, and the caller decides what (if anything) to do. That
mirrors the cleaning module's principle - the engine reports, the user
decides.

Method (per the approved spec):
    IQR         = Q3 - Q1
    lower bound = Q1 - 1.5 * IQR
    upper bound = Q3 + 1.5 * IQR
Values strictly outside the bounds are flagged.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.analytics._common import numeric_columns, safe_float

IQR_MULTIPLIER = 1.5

# Row indices are returned so the Phase 2 Outliers tab can show a
# flagged row in context, but an unbounded list would be a problem on a
# large dataset: a pathological column could flag tens of thousands of
# rows, and this payload ends up in JSONB, an API response, and an AI
# prompt. The total count is always exact; only the index list is
# capped (Phase 7 S13, bounded payloads).
MAX_REPORTED_INDICES = 100


def detect_outliers(df: pd.DataFrame, classifications: dict[str, str]) -> dict[str, Any]:
    targets = numeric_columns(df, classifications)
    columns: list[dict[str, Any]] = []

    for name in targets:
        series = pd.to_numeric(df[name], errors="coerce")
        columns.append(_detect_in_series(name, series))

    return {
        "columns": columns,
        "method": "iqr",
        "iqr_multiplier": IQR_MULTIPLIER,
        "total_outlier_count": sum(c["outlier_count"] for c in columns),
        "columns_with_outliers": sum(1 for c in columns if c["outlier_count"] > 0),
    }


def _detect_in_series(name: str, series: pd.Series) -> dict[str, Any]:
    non_null = series.dropna()
    observation_count = int(len(non_null))

    base: dict[str, Any] = {
        "column": name,
        "observation_count": observation_count,
        "outlier_count": 0,
        "outlier_percentage": 0.0,
        "outlier_indices": [],
        "outlier_indices_truncated": False,
    }

    if non_null.empty:
        return {**base, "detected": False, "reason": "no_non_missing_values"}

    q1 = non_null.quantile(0.25)
    q3 = non_null.quantile(0.75)
    iqr = q3 - q1

    bounds = {
        "q1": safe_float(q1),
        "q3": safe_float(q3),
        "iqr": safe_float(iqr),
        "lower_bound": safe_float(q1 - IQR_MULTIPLIER * iqr),
        "upper_bound": safe_float(q3 + IQR_MULTIPLIER * iqr),
    }

    if iqr == 0:
        # A constant column (or one where the middle 50% is identical)
        # gives IQR = 0, collapsing both bounds onto the same value. The
        # method would then flag every value that differs even slightly
        # as an outlier, which is not a meaningful result - so detection
        # is reported as unavailable rather than producing noise. The
        # bounds are still returned for transparency.
        return {**base, **bounds, "detected": False, "reason": "zero_iqr_constant_column"}

    mask = (non_null < bounds["lower_bound"]) | (non_null > bounds["upper_bound"])
    outlier_index = non_null.index[mask]
    outlier_count = int(len(outlier_index))

    reported = [int(i) for i in outlier_index[:MAX_REPORTED_INDICES]]

    return {
        **base,
        **bounds,
        "detected": True,
        "outlier_count": outlier_count,
        "outlier_percentage": round(outlier_count / observation_count * 100, 4),
        "outlier_indices": reported,
        "outlier_indices_truncated": outlier_count > len(reported),
    }
