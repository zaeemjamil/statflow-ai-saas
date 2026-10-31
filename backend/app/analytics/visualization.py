"""
Chart recommendation.

New capability - the Phase 1 audit found zero visualization code
anywhere in StatFlow (its PDF contained only text, tables and number
cards). This module decides *which* charts suit a dataset and emits
structured configs; it renders nothing. Phase 8's frontend renders
these with Recharts, and Phase 10's PDF reuses the identical configs,
so on-screen and in-report charts cannot drift apart.

Rules (from the approved spec):
    numeric x numeric        -> scatter
    date x numeric           -> line
    categorical x numeric    -> bar (aggregated)
    numeric distribution     -> histogram
    categorical distribution -> count bar chart

Every recommendation carries a `reason`, so nothing is an unexplained
default (Phase 7 S6) and the UI can tell the user why a chart was
suggested.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from app.analytics import sampling
from app.analytics._common import columns_by_classification, safe_float, safe_int

# Caps chosen so the payload stays bounded (Phase 7 S13). A 40-column
# dataset has 780 numeric pairs; returning all of them would be useless
# to a user and enormous in JSONB.
MAX_CHARTS_PER_TYPE = 4
MAX_TOTAL_CHARTS = 12
MAX_CATEGORIES = 12
HISTOGRAM_BINS = 10
# Above this many distinct values a "category" is really an identifier
# (an order number, an email); charting it produces one bar per row.
MAX_CATEGORICAL_CARDINALITY = 30
# Per-row charts (scatter, line) draw at most this many points. A browser
# cannot usefully show more, and at the V1 row limit one point per row was
# ~27 MB of JSON per analysis. Only what is DRAWN is reduced: every statistic,
# correlation, outlier count and aggregated chart still uses all rows (see
# app/analytics/sampling.py). Inside the 2,000-5,000 target range.
MAX_CHART_POINTS = 2_500


def recommend_charts(
    df: pd.DataFrame,
    classifications: dict[str, str],
    correlations: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Recommend charts, returning configs plus the data to render them.

    Args:
        correlations: optional output of `compute_correlations`. When
            supplied, scatter plots are chosen for the most strongly
            correlated pairs rather than arbitrary first-N pairs - the
            pairs most worth looking at. Optional so this module stays
            independently testable and usable without it.
    """
    numeric = columns_by_classification(df, classifications, "numeric")
    categorical = columns_by_classification(df, classifications, "categorical")
    dates = columns_by_classification(df, classifications, "date")

    limit = MAX_CHART_POINTS  # read at call time so tests can lower it
    charts: list[dict[str, Any]] = []
    charts.extend(_scatter_charts(df, numeric, correlations, limit))
    charts.extend(_line_charts(df, dates, numeric, limit))
    charts.extend(_bar_charts(df, categorical, numeric))
    charts.extend(_histograms(df, numeric))
    charts.extend(_count_charts(df, categorical))

    charts = charts[:MAX_TOTAL_CHARTS]

    return {
        "available": bool(charts),
        "charts": charts,
        "chart_count": len(charts),
        "reason": None if charts else "no_chartable_column_combinations_found",
    }


def _low_cardinality(df: pd.DataFrame, columns: list[str]) -> list[str]:
    return [c for c in columns if 1 < df[c].nunique(dropna=True) <= MAX_CATEGORICAL_CARDINALITY]


def _sampling_info(method: str, total: int, shown: int, limit: int) -> dict[str, Any]:
    return {"method": method, "total_points": total, "displayed_points": shown, "max_points": limit}


def _scatter_charts(
    df: pd.DataFrame, numeric: list[str], correlations: dict[str, Any] | None, limit: int
) -> list[dict[str, Any]]:
    if len(numeric) < 2:
        return []

    pairs: list[tuple[str, str, float | None]] = []
    if correlations and correlations.get("pairs"):
        for pair in correlations["pairs"][:MAX_CHARTS_PER_TYPE]:
            pairs.append((pair["column_a"], pair["column_b"], pair["correlation"]))
    else:
        for i, a in enumerate(numeric):
            for b in numeric[i + 1 :]:
                pairs.append((a, b, None))
        pairs = pairs[:MAX_CHARTS_PER_TYPE]

    charts = []
    for x, y, correlation in pairs:
        if x not in df.columns or y not in df.columns:
            continue
        subset = df[[x, y]].dropna()
        reason = "Two numeric columns - a scatter plot shows their relationship."
        if correlation is not None:
            reason = (
                f"These two numeric columns have the strongest linear association "
                f"in the dataset (r = {correlation:.2f}); a scatter plot shows its shape. "
                "Association does not imply causation."
            )
        xs = subset[x].to_numpy(dtype=float)
        ys = subset[y].to_numpy(dtype=float)
        keep = sampling.scatter_positions(xs, ys, limit)
        chart: dict[str, Any] = {
            "chart_type": "scatter",
            "title": f"{y} vs {x}",
            "x_column": x,
            "y_column": y,
            "group_column": None,
            "reason": reason,
            "data_requirements": {"x": "numeric", "y": "numeric"},
            "data": [
                {"x": safe_float(rx), "y": safe_float(ry)}
                for rx, ry in zip(xs[keep], ys[keep], strict=True)
            ],
        }
        if len(keep) < len(xs):
            chart["sampling"] = _sampling_info("even_spread", len(xs), len(keep), limit)
        charts.append(chart)
    return charts


def _line_charts(
    df: pd.DataFrame, dates: list[str], numeric: list[str], limit: int
) -> list[dict[str, Any]]:
    charts = []
    for date_column in dates[:1]:  # one time axis is enough for V1
        parsed = pd.to_datetime(df[date_column], errors="coerce", format="mixed")
        for y in numeric[:MAX_CHARTS_PER_TYPE]:
            subset = pd.DataFrame({"x": parsed, "y": pd.to_numeric(df[y], errors="coerce")})
            subset = subset.dropna().sort_values("x")
            if subset.empty:
                continue
            keep = sampling.line_positions(subset["y"].to_numpy(dtype=float), limit)
            shown = subset.iloc[keep]
            chart: dict[str, Any] = {
                "chart_type": "line",
                "title": f"{y} over time ({date_column})",
                "x_column": date_column,
                "y_column": y,
                "group_column": None,
                "reason": (
                    f"'{date_column}' is a date column and '{y}' is numeric - "
                    "a line chart shows how the value moves over time."
                ),
                "data_requirements": {"x": "date", "y": "numeric"},
                "data": [
                    {"x": x.isoformat(), "y": safe_float(y_value)}
                    for x, y_value in zip(shown["x"], shown["y"], strict=True)
                ],
            }
            if len(keep) < len(subset):
                chart["sampling"] = _sampling_info("min_max", len(subset), len(keep), limit)
            charts.append(chart)
    return charts


def _bar_charts(
    df: pd.DataFrame, categorical: list[str], numeric: list[str]
) -> list[dict[str, Any]]:
    charts = []
    for category in _low_cardinality(df, categorical)[:MAX_CHARTS_PER_TYPE]:
        for y in numeric[:1]:  # one measure per category keeps it readable
            grouped = (
                df[[category, y]]
                .dropna()
                .groupby(category, observed=True)[y]
                .mean()
                .sort_values(ascending=False)
                .head(MAX_CATEGORIES)
            )
            if grouped.empty:
                continue
            charts.append(
                {
                    "chart_type": "bar",
                    "title": f"Average {y} by {category}",
                    "x_column": category,
                    "y_column": y,
                    "group_column": category,
                    "aggregation": "mean",
                    "reason": (
                        f"'{category}' is categorical with a manageable number of "
                        f"distinct values and '{y}' is numeric - a bar chart compares "
                        "the average across groups."
                    ),
                    "data_requirements": {"x": "categorical", "y": "numeric"},
                    "data": [
                        {"x": str(index), "y": safe_float(value)}
                        for index, value in grouped.items()
                    ],
                }
            )
    return charts


def _histograms(df: pd.DataFrame, numeric: list[str]) -> list[dict[str, Any]]:
    charts = []
    for column in numeric[:MAX_CHARTS_PER_TYPE]:
        series = pd.to_numeric(df[column], errors="coerce").dropna()
        if series.empty or series.nunique() <= 1:
            # A constant column produces a single meaningless bar.
            continue
        counts, edges = pd.cut(series, bins=HISTOGRAM_BINS, retbins=True)
        binned = counts.value_counts().sort_index()
        charts.append(
            {
                "chart_type": "histogram",
                "title": f"Distribution of {column}",
                "x_column": column,
                "y_column": None,
                "group_column": None,
                "bins": HISTOGRAM_BINS,
                "reason": (
                    f"'{column}' is numeric - a histogram shows how its values are "
                    "distributed, including skew and possible outliers."
                ),
                "data_requirements": {"x": "numeric"},
                "data": [
                    {
                        "bin_start": safe_float(interval.left),
                        "bin_end": safe_float(interval.right),
                        "count": safe_int(count),
                    }
                    for interval, count in binned.items()
                ],
            }
        )
    return charts


def _count_charts(df: pd.DataFrame, categorical: list[str]) -> list[dict[str, Any]]:
    charts = []
    for column in _low_cardinality(df, categorical)[:MAX_CHARTS_PER_TYPE]:
        counts = df[column].value_counts(dropna=True).head(MAX_CATEGORIES)
        if counts.empty:
            continue
        charts.append(
            {
                "chart_type": "count",
                "title": f"Frequency of {column}",
                "x_column": column,
                "y_column": None,
                "group_column": None,
                "reason": (
                    f"'{column}' is categorical - a count chart shows how many rows "
                    "fall into each value."
                ),
                "data_requirements": {"x": "categorical"},
                "data": [
                    {"x": str(index), "count": safe_int(value)} for index, value in counts.items()
                ],
            }
        )
    return charts


def bound_chart_payload(chart: dict[str, Any], limit: int | None = None) -> dict[str, Any]:
    """Return `chart` with its per-row data reduced to at most `limit` points.

    Analyses stored before sampling existed hold one point per row in their
    JSONB. This is applied when they are READ, so existing projects stop
    returning tens of megabytes without a migration or a forced re-analysis.
    It is idempotent: a chart that is already within the limit, or already
    carries `sampling` metadata, is returned unchanged. Aggregated chart
    types (bar, histogram, count) are never touched.
    """
    limit = MAX_CHART_POINTS if limit is None else limit
    data = chart.get("data")
    chart_type = chart.get("chart_type")
    if chart_type not in ("scatter", "line") or not isinstance(data, list):
        return chart
    if len(data) <= limit or chart.get("sampling"):
        return chart

    def column(key: str) -> np.ndarray:
        return np.array([np.nan if (d.get(key) is None) else d[key] for d in data], dtype=float)

    if chart_type == "scatter":
        keep = sampling.scatter_positions(column("x"), column("y"), limit)
        method = "even_spread"
    else:  # stored line data is already in x order
        keep = sampling.line_positions(column("y"), limit)
        method = "min_max"
    return {
        **chart,
        "data": [data[int(i)] for i in keep],
        "sampling": _sampling_info(method, len(data), len(keep), limit),
    }
