"""
Pairwise Pearson correlation across all numeric columns.

Generalizes StatFlow's `get_correlation()` (Phase 1 audit S5), which
implemented Pearson's r correctly from first principles but applied it
to exactly six hardcoded retail column pairs. The formula's intent is
preserved; the hardcoded pairs are gone, replaced by the full matrix
over whatever numeric columns the profiler found.

On causation: this module returns numbers and labels only. It never
emits language implying that a relationship is causal, and it exposes
the strength label separately from the value so that downstream
consumers (AI service, PDF, frontend) share one vocabulary instead of
each inventing their own. The AI prompt in Phase 9 and the UI copy in
Phase 8 carry the explicit correlation-is-not-causation caveat.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from app.analytics._common import numeric_columns, safe_float

# Pearson's r needs at least 2 paired observations to be defined at all,
# and with exactly 2 points it is always exactly +/-1 regardless of the
# data - a mathematically true but analytically worthless result. 3 is
# the minimum at which the value carries any information.
MIN_OBSERVATIONS = 3


def _strength_label(value: float) -> str:
    magnitude = abs(value)
    if magnitude >= 0.7:
        return "strong"
    if magnitude >= 0.4:
        return "moderate"
    if magnitude >= 0.2:
        return "weak"
    return "negligible"


def compute_correlations(df: pd.DataFrame, classifications: dict[str, str]) -> dict[str, Any]:
    """Full matrix plus the strongest positive/negative relationships.

    Returns a `matrix` as nested dicts (JSON-safe, with undefined
    entries as null) and a flat `pairs` list sorted by absolute
    strength. The flat list is what the UI and AI service actually
    consume - deriving "strongest relationships" from it is trivial,
    whereas re-deriving it from the nested matrix would mean every
    consumer reimplementing the same self-pair-exclusion logic.
    """
    targets = numeric_columns(df, classifications)

    if len(targets) < 2:
        return {
            "available": False,
            "reason": "at_least_two_numeric_columns_required",
            "numeric_column_count": len(targets),
            "matrix": {},
            "pairs": [],
            "strongest_positive": None,
            "strongest_negative": None,
        }

    numeric_df = df[targets].apply(pd.to_numeric, errors="coerce")
    matrix = numeric_df.corr(method="pearson", min_periods=MIN_OBSERVATIONS)

    pairs: list[dict[str, Any]] = []
    # Upper triangle only: the matrix is symmetric, and i == j is the
    # self-correlation (always 1.0), which must never be reported as a
    # "strongest relationship" (Phase 7 S3).
    for i, column_a in enumerate(targets):
        for column_b in targets[i + 1 :]:
            value = safe_float(matrix.loc[column_a, column_b])
            if value is None:
                # NaN here means undefined, not zero - a constant column
                # has no variance, so r has a zero denominator; too few
                # overlapping non-null observations does the same. Both
                # are excluded from ranking rather than being coerced
                # to 0.0, which would falsely read as "no relationship".
                continue
            pairs.append(
                {
                    "column_a": column_a,
                    "column_b": column_b,
                    "correlation": value,
                    "strength": _strength_label(value),
                    "direction": "positive" if value >= 0 else "negative",
                }
            )

    pairs.sort(key=lambda pair: abs(pair["correlation"]), reverse=True)

    positives = [p for p in pairs if p["correlation"] > 0]
    negatives = [p for p in pairs if p["correlation"] < 0]

    return {
        "available": True,
        "numeric_column_count": len(targets),
        "matrix": _matrix_to_dict(matrix),
        "pairs": pairs,
        "strongest_positive": max(positives, key=lambda p: p["correlation"], default=None),
        "strongest_negative": min(negatives, key=lambda p: p["correlation"], default=None),
        "undefined_pair_count": (len(targets) * (len(targets) - 1)) // 2 - len(pairs),
    }


def _matrix_to_dict(matrix: pd.DataFrame) -> dict[str, dict[str, float | None]]:
    return {
        str(row): {str(col): safe_float(matrix.loc[row, col]) for col in matrix.columns}
        for row in matrix.index
    }
