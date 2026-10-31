"""Chart recommendation - correct type selection per column combination."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from app.analytics.correlation import compute_correlations
from app.analytics.visualization import recommend_charts
from tests.analytics_fixtures import (
    all_categorical_dataset,
    all_numeric_dataset,
    date_and_numeric_dataset,
    mixed_dataset,
    numeric_classifications,
)


def _types(result: dict[str, Any]) -> set[str]:
    return {chart["chart_type"] for chart in result["charts"]}


def test_two_numeric_columns_produce_a_scatter_plot() -> None:
    df = all_numeric_dataset()
    result = recommend_charts(df, numeric_classifications(df))

    assert "scatter" in _types(result)
    scatter = next(c for c in result["charts"] if c["chart_type"] == "scatter")
    assert scatter["data_requirements"] == {"x": "numeric", "y": "numeric"}
    assert len(scatter["data"]) == len(df)


def test_date_and_numeric_produce_a_line_chart() -> None:
    df = date_and_numeric_dataset()
    result = recommend_charts(df, numeric_classifications(df))

    assert "line" in _types(result)
    line = next(c for c in result["charts"] if c["chart_type"] == "line")
    assert line["x_column"] == "recorded_at"
    assert line["y_column"] == "reading"


def test_line_chart_data_is_sorted_by_date() -> None:
    """An unsorted line chart draws a zigzag that misrepresents a trend."""
    df = pd.DataFrame(
        {
            "day": pd.to_datetime(["2026-01-03", "2026-01-01", "2026-01-02"]),
            "value": [30.0, 10.0, 20.0],
        }
    )
    result = recommend_charts(df, numeric_classifications(df))
    line = next(c for c in result["charts"] if c["chart_type"] == "line")

    x_values = [point["x"] for point in line["data"]]
    assert x_values == sorted(x_values)
    assert [point["y"] for point in line["data"]] == [10.0, 20.0, 30.0]


def test_categorical_and_numeric_produce_a_bar_chart() -> None:
    df = mixed_dataset()
    result = recommend_charts(df, numeric_classifications(df))

    assert "bar" in _types(result)
    bar = next(c for c in result["charts"] if c["chart_type"] == "bar")
    assert bar["group_column"] == "site"
    assert bar["aggregation"] == "mean"


def test_numeric_columns_produce_histograms() -> None:
    df = all_numeric_dataset()
    result = recommend_charts(df, numeric_classifications(df))

    assert "histogram" in _types(result)
    histogram = next(c for c in result["charts"] if c["chart_type"] == "histogram")
    assert all("bin_start" in point and "count" in point for point in histogram["data"])


def test_categorical_columns_produce_count_charts() -> None:
    df = all_categorical_dataset()
    result = recommend_charts(df, numeric_classifications(df))

    assert "count" in _types(result)
    count_chart = next(c for c in result["charts"] if c["chart_type"] == "count")
    # 'colour' has red x2, blue, green -> red is most frequent
    assert count_chart["data"][0]["count"] == 2


def test_every_chart_explains_why_it_was_recommended() -> None:
    """No chart may be an unexplained default (Phase 7 S6)."""
    df = mixed_dataset()
    result = recommend_charts(df, numeric_classifications(df))

    assert result["charts"]
    for chart in result["charts"]:
        assert chart["reason"]
        assert len(chart["reason"]) > 20


def test_scatter_uses_the_strongest_correlations_when_available() -> None:
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "b": [2.0, 4.0, 6.0, 8.0, 10.0, 12.0],  # perfectly correlated with a
            "c": [5.0, 1.0, 4.0, 2.0, 6.0, 3.0],  # weakly related
        }
    )
    classifications = numeric_classifications(df)
    correlations = compute_correlations(df, classifications)
    result = recommend_charts(df, classifications, correlations)

    scatter = next(c for c in result["charts"] if c["chart_type"] == "scatter")
    assert {scatter["x_column"], scatter["y_column"]} == {"a", "b"}
    assert "does not imply causation" in scatter["reason"]


def test_constant_numeric_column_gets_no_histogram() -> None:
    """A single meaningless bar is worse than no chart."""
    df = pd.DataFrame({"fixed": [5.0, 5.0, 5.0, 5.0]})
    result = recommend_charts(df, numeric_classifications(df))

    assert not any(
        c["x_column"] == "fixed" for c in result["charts"] if c["chart_type"] == "histogram"
    )


def test_high_cardinality_identifier_column_is_not_charted() -> None:
    """A near-unique text column (an ID, an email) would render one bar
    per row, which is noise rather than insight."""
    df = pd.DataFrame({"record_id": [f"id-{i}" for i in range(100)]})
    result = recommend_charts(df, numeric_classifications(df))

    assert not any(c["x_column"] == "record_id" for c in result["charts"])


def test_empty_dataset_reports_unavailable_without_crashing() -> None:
    df = pd.DataFrame({"nothing": pd.Series([], dtype="object")})
    result = recommend_charts(df, numeric_classifications(df))

    assert result["available"] is False
    assert result["reason"] == "no_chartable_column_combinations_found"


def test_total_chart_count_is_bounded() -> None:
    from app.analytics.visualization import MAX_TOTAL_CHARTS

    df = pd.DataFrame({f"col_{i}": [float(i), float(i + 1), float(i + 2)] for i in range(20)})
    result = recommend_charts(df, numeric_classifications(df))
    assert len(result["charts"]) <= MAX_TOTAL_CHARTS


def test_chart_configs_are_json_serializable() -> None:
    """These go into JSONB and an API response, so any numpy scalar or
    NaN leaking through would break serialization."""
    df = mixed_dataset()
    result = recommend_charts(df, numeric_classifications(df))
    assert json.loads(json.dumps(result)) == result


def test_unusual_column_names_are_preserved_exactly() -> None:
    from tests.analytics_fixtures import unusual_column_names_dataset

    df = unusual_column_names_dataset()
    result = recommend_charts(df, numeric_classifications(df))

    referenced = {c["x_column"] for c in result["charts"]} | {
        c["y_column"] for c in result["charts"]
    }
    assert referenced & set(df.columns)
