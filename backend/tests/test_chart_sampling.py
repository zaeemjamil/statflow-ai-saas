"""
V1 hardening, Stage 2 - chart payload reduction.

Pins three things:
  1. the sampling functions are deterministic, bounded, order-preserving and
     statistically representative;
  2. chart generation applies them (and only to scatter/line), and the
     response stays small at the V1 row limit;
  3. sampling NEVER changes a reported statistic - the whole pipeline is run
     with and without it and every non-chart result is compared.
"""

from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import pytest

from app.analytics import profiling, sampling, visualization
from app.analytics.correlation import compute_correlations
from app.analytics.visualization import bound_chart_payload, recommend_charts
from app.services.analysis_service import run_analysis

N = 100_000
LIMIT = visualization.MAX_CHART_POINTS


def _frame(n: int, seed: int = 11) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    a = rng.normal(50, 10, n)
    return pd.DataFrame(
        {
            "observed_at": pd.date_range("2024-01-01", periods=n, freq="min"),
            "alpha": a,
            "beta": 0.8 * a + rng.normal(0, 6, n),
            "gamma": rng.exponential(3.0, n),
            "group": rng.choice(["p", "q", "r", "s"], n),
        }
    )


def _first(result: dict[str, Any], chart_type: str) -> dict[str, Any]:
    return next(c for c in result["charts"] if c["chart_type"] == chart_type)


def _classes(df: pd.DataFrame) -> dict[str, str]:
    return {
        "observed_at": "date",
        "alpha": "numeric",
        "beta": "numeric",
        "gamma": "numeric",
        "group": "categorical",
    }


# --- 1. the sampling functions ---------------------------------------------------------------


def test_the_limit_is_inside_the_requested_2000_to_5000_range() -> None:
    assert 2_000 <= visualization.MAX_CHART_POINTS <= 5_000


def test_data_that_already_fits_is_returned_whole() -> None:
    x = np.arange(100.0)
    assert sampling.scatter_positions(x, x, 2_500).tolist() == list(range(100))
    assert sampling.line_positions(x, 2_500).tolist() == list(range(100))
    assert sampling.spread_positions(100, 100).tolist() == list(range(100))


def test_spread_is_bounded_unique_increasing_and_exact_in_size() -> None:
    chosen = sampling.spread_positions(N, 2_500)
    assert len(chosen) == 2_500
    assert len(set(chosen.tolist())) == 2_500
    assert bool((np.diff(chosen) > 0).all())
    assert chosen[0] >= 0 and chosen[-1] < N


def test_selection_is_deterministic() -> None:
    rng = np.random.default_rng(1)
    x, y = rng.normal(size=N), rng.normal(size=N)
    first = sampling.scatter_positions(x, y, 2_500)
    second = sampling.scatter_positions(x.copy(), y.copy(), 2_500)
    assert first.tolist() == second.tolist()
    # ...and does not depend on the values at all, only on the position, so the
    # same rows are drawn in every scatter chart of one dataset.
    again = sampling.spread_positions(N, 2_500).tolist()
    assert sampling.spread_positions(N, 2_500).tolist() == again


def test_scatter_always_keeps_the_extremes_of_both_axes() -> None:
    rng = np.random.default_rng(2)
    x, y = rng.normal(size=N), rng.normal(size=N)
    kept = set(sampling.scatter_positions(x, y, 2_500).tolist())
    for index in (x.argmin(), x.argmax(), y.argmin(), y.argmax()):
        assert int(index) in kept
    assert len(kept) <= 2_500


def test_sample_is_spread_evenly_through_the_row_order() -> None:
    chosen = sampling.spread_positions(N, 2_500)
    per_tenth = np.histogram(chosen, bins=10, range=(0, N))[0]
    assert per_tenth.min() >= 225 and per_tenth.max() <= 275  # 250 each, +/-10%


@pytest.mark.parametrize("period", [8, 10, 20, 40])
def test_sample_does_not_alias_with_cyclical_data(period: int) -> None:
    """A fixed stride (every 40th row) over data that repeats every `period`
    rows sees a single phase. The spread selection must see them all."""
    cycle = np.tile(np.arange(period), N // period + 1)[:N]
    stride = N // 2_500
    assert len(set(cycle[::stride].tolist())) == 1  # the failure this avoids
    seen = set(cycle[sampling.spread_positions(N, 2_500)].tolist())
    assert seen == set(range(period))


def test_sample_is_statistically_representative_of_the_full_data() -> None:
    df = _frame(N)
    x, y = df["alpha"].to_numpy(), df["beta"].to_numpy()
    kept = sampling.scatter_positions(x, y, 2_500)
    assert abs(x[kept].mean() - x.mean()) < 0.5  # sd is 10; se of a 2,500-sample is 0.2
    assert abs(x[kept].std() - x.std()) < 0.5
    assert abs(np.corrcoef(x[kept], y[kept])[0, 1] - np.corrcoef(x, y)[0, 1]) < 0.03


def test_line_decimation_keeps_spikes_dips_ends_and_order() -> None:
    rng = np.random.default_rng(3)
    y = rng.normal(0, 1, N)
    y[61_234], y[12_345] = 50.0, -50.0
    kept = sampling.line_positions(y, 2_500)
    assert len(kept) <= 2_500
    assert bool((np.diff(kept) > 0).all())
    assert kept[0] == 0 and kept[-1] == N - 1
    assert 61_234 in set(kept.tolist()) and 12_345 in set(kept.tolist())
    assert y[kept].max() == y.max() and y[kept].min() == y.min()


# --- 2. chart generation ---------------------------------------------------------------------


def test_scatter_and_line_are_capped_and_describe_the_reduction() -> None:
    df = _frame(N)
    result = recommend_charts(df, _classes(df))

    per_row = [c for c in result["charts"] if c["chart_type"] in ("scatter", "line")]
    assert {c["chart_type"] for c in per_row} == {"scatter", "line"}
    for chart in per_row:
        assert len(chart["data"]) <= LIMIT
        info = chart["sampling"]
        assert info["total_points"] == N
        assert info["displayed_points"] == len(chart["data"])
        assert info["max_points"] == LIMIT
        assert info["method"] == ("even_spread" if chart["chart_type"] == "scatter" else "min_max")


def test_aggregated_charts_are_never_sampled_and_use_every_row() -> None:
    df = _frame(N)
    result = recommend_charts(df, _classes(df))
    aggregated = [c for c in result["charts"] if c["chart_type"] in ("bar", "histogram", "count")]
    assert {c["chart_type"] for c in aggregated} == {"bar", "histogram", "count"}
    for chart in aggregated:
        assert "sampling" not in chart
    histogram = next(c for c in result["charts"] if c["chart_type"] == "histogram")
    assert sum(b["count"] for b in histogram["data"]) == N  # every row is binned
    count = next(c for c in result["charts"] if c["chart_type"] == "count")
    assert sum(b["count"] for b in count["data"]) == N


def test_small_datasets_are_unchanged_and_carry_no_sampling_key() -> None:
    df = _frame(500)
    for chart in recommend_charts(df, _classes(df))["charts"]:
        assert "sampling" not in chart
        if chart["chart_type"] in ("scatter", "line"):
            assert len(chart["data"]) == 500


def test_exactly_at_the_limit_is_not_sampled() -> None:
    df = _frame(LIMIT)
    scatter = _first(recommend_charts(df, _classes(df)), "scatter")
    assert len(scatter["data"]) == LIMIT and "sampling" not in scatter
    over = _frame(LIMIT + 1)
    sampled = _first(recommend_charts(over, _classes(over)), "scatter")
    assert len(sampled["data"]) <= LIMIT and sampled["sampling"]["total_points"] == LIMIT + 1


def test_chart_response_stays_small_at_the_row_limit() -> None:
    """Was ~27 MB for 100,000 rows before sampling."""
    df = _frame(N)
    size = len(json.dumps(recommend_charts(df, _classes(df))))
    assert size < 1.5 * 1024 * 1024, f"{size / 1024 / 1024:.2f} MB"


def test_sampled_scatter_points_are_real_rows_of_the_data() -> None:
    """Sampling selects rows; it never invents or alters a coordinate."""
    df = _frame(N)
    scatter = _first(recommend_charts(df, _classes(df)), "scatter")
    x_values = df[scatter["x_column"]].round(9)
    y_values = df[scatter["y_column"]].round(9)
    pairs = set(zip(x_values, y_values, strict=True))
    for point in scatter["data"][:200]:
        assert (round(point["x"], 9), round(point["y"], 9)) in pairs


# --- 3. sampling never changes a statistic ---------------------------------------------------


def _without_chart_points(analysis: dict[str, Any]) -> dict[str, Any]:
    out = {k: v for k, v in analysis.items() if k != "visualizations"}
    charts = analysis["visualizations"]["charts"]
    out["aggregated_charts"] = [c for c in charts if c["chart_type"] not in ("scatter", "line")]
    return out


def test_every_statistic_is_identical_with_and_without_chart_sampling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    df = _frame(20_000)
    profile = profiling.profile_dataset(df)

    monkeypatch.setattr(visualization, "MAX_CHART_POINTS", 10**9)  # effectively no sampling
    full = run_analysis(df.copy(), profile=profile)
    monkeypatch.setattr(visualization, "MAX_CHART_POINTS", 500)  # heavy sampling
    sampled = run_analysis(df.copy(), profile=profile)

    # The charts really did differ...
    full_scatter = _first(full["visualizations"], "scatter")
    sampled_scatter = _first(sampled["visualizations"], "scatter")
    assert len(full_scatter["data"]) == 20_000 and len(sampled_scatter["data"]) <= 500

    # ...and nothing else did: statistics, correlations, outliers, cleaning, stages and
    # the aggregated charts are exactly equal.
    assert _without_chart_points(sampled) == _without_chart_points(full)


def test_reported_correlation_comes_from_all_rows_not_from_the_plotted_sample() -> None:
    df = _frame(N)
    exact = float(np.corrcoef(df["alpha"], df["beta"])[0, 1])
    correlations = compute_correlations(df, _classes(df))
    reported = {
        frozenset((p["column_a"], p["column_b"])): p["correlation"] for p in correlations["pairs"]
    }
    assert reported[frozenset(("alpha", "beta"))] == pytest.approx(exact, abs=1e-9)


# --- legacy (already stored) analyses ----------------------------------------------------------


def _legacy_chart(kind: str, n: int) -> dict[str, Any]:
    return {
        "chart_type": kind,
        "title": "legacy",
        "reason": "r",
        "data_requirements": {},
        "data": [{"x": float(i), "y": float((i * 7) % 101)} for i in range(n)],
    }


def test_stored_full_size_charts_are_bounded_when_read() -> None:
    for kind in ("scatter", "line"):
        stored = _legacy_chart(kind, 40_000)
        bounded = bound_chart_payload(stored)
        assert len(bounded["data"]) <= LIMIT
        assert bounded["sampling"]["total_points"] == 40_000
        assert len(stored["data"]) == 40_000  # the stored dict is not mutated


def test_bounding_is_idempotent_and_leaves_small_or_aggregated_charts_alone() -> None:
    small = _legacy_chart("scatter", 100)
    assert bound_chart_payload(small) is small
    once = bound_chart_payload(_legacy_chart("scatter", 40_000))
    assert bound_chart_payload(once) is once  # already carries sampling metadata
    bar = {"chart_type": "bar", "title": "b", "reason": "r", "data": [{"x": "a", "y": 1.0}] * 5_000}
    assert bound_chart_payload(bar) is bar


def test_bounding_a_stored_chart_tolerates_missing_values() -> None:
    stored = _legacy_chart("scatter", 10_000)
    stored["data"][5]["y"] = None
    assert len(bound_chart_payload(stored)["data"]) <= LIMIT
