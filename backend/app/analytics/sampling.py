"""
Deterministic reduction of per-row chart data.

Why this exists: a scatter or line chart built from every row is one JSON
object per row. At the V1 limit (100,000 rows) that is ~27 MB per analysis
- stored in JSONB, returned by four endpoints, and drawn as SVG by the
browser. A chart cannot usefully show more than a few thousand marks, so
the chart *display* data is reduced here.

What this does NOT touch: statistics, correlations, outliers, cleaning,
regression, and the already-aggregated bar / histogram / count charts are
all computed from the full dataframe elsewhere. Nothing in this module can
change a reported number; it only chooses which rows are *drawn*.

Properties every function here guarantees (and tests pin):

* Deterministic: the same input always selects the same rows. No random
  number generator is used (generator streams are not guaranteed stable
  across NumPy versions), so results are reproducible across runs,
  machines and library upgrades.
* Bounded: never returns more than `max_points` positions.
* Order-preserving: returned positions are strictly increasing.
* Identity when small: if the data already fits, every position is returned.
* Extremes are kept: the shape of the plotted range is never misleading.
"""

from __future__ import annotations

import numpy as np

# Knuth's multiplicative constant, ~ 2**32 / golden ratio. Taking i * C mod
# 2**32 gives the fractional parts of i * 0.618..., a classic low-discrepancy
# (evenly spread) sequence: choosing the rows whose value is smallest picks a
# set that is spread uniformly through the row order. Unlike a fixed stride
# ("every 40th row") it does not alias with cyclical data: over data with a
# period of 8 rows, a stride of 40 sees 1 of the 8 phases and so draws a
# misleading picture, while this selection sees all 8 (pinned in the tests).
_GOLDEN_MULTIPLIER = np.uint64(2654435761)
_MASK_32 = np.uint64(0xFFFFFFFF)


def spread_positions(n: int, k: int) -> np.ndarray:
    """`k` of the positions 0..n-1, evenly spread through the sequence."""
    if k <= 0:
        return np.empty(0, dtype=np.int64)
    if n <= k:
        return np.arange(n, dtype=np.int64)
    positions = np.arange(n, dtype=np.uint64)
    # n < 2**32 here, so positions * multiplier cannot overflow uint64, and
    # multiplying by an odd constant mod 2**32 is a bijection: all keys are
    # distinct, so which k are "smallest" is unambiguous (deterministic).
    keys = (positions * _GOLDEN_MULTIPLIER) & _MASK_32
    chosen = np.argpartition(keys, k - 1)[:k]
    return np.sort(chosen).astype(np.int64)


def scatter_positions(x: np.ndarray, y: np.ndarray, max_points: int) -> np.ndarray:
    """Positions to draw for a scatter plot of at most `max_points` points.

    The (up to four) points holding the minimum and maximum of each axis are
    always included, so the visible range is the true range of the data.
    """
    n = len(x)
    if n <= max_points:
        return np.arange(n, dtype=np.int64)
    extremes = {int(np.argmin(x)), int(np.argmax(x)), int(np.argmin(y)), int(np.argmax(y))}
    body = spread_positions(n, max(max_points - len(extremes), 0))
    return np.union1d(body, np.fromiter(extremes, dtype=np.int64))[:max_points]


def line_positions(y: np.ndarray, max_points: int) -> np.ndarray:
    """Positions to draw for a line chart whose points are already in x order.

    Min/max decimation: the sequence is cut into equal-count buckets and the
    lowest and highest point of each bucket is kept, plus the first and last
    point overall. A spike or dip inside a bucket therefore always survives -
    a mean or a plain stride would flatten it away.
    """
    n = len(y)
    if n <= max_points:
        return np.arange(n, dtype=np.int64)
    buckets = max((max_points - 2) // 2, 1)
    edges = np.linspace(0, n, buckets + 1).astype(np.int64)
    keep = {0, n - 1}
    for lo, hi in zip(edges[:-1], edges[1:], strict=True):
        if hi > lo:
            segment = y[lo:hi]
            keep.add(int(lo) + int(np.argmin(segment)))
            keep.add(int(lo) + int(np.argmax(segment)))
    return np.fromiter(sorted(keep), dtype=np.int64)[:max_points]
