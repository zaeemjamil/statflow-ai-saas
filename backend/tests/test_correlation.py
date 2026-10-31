"""Correlation - verified against scipy's independent implementation."""

from __future__ import annotations

import pandas as pd
import pytest
from scipy import stats as scipy_stats

from app.analytics.correlation import compute_correlations
from tests.analytics_fixtures import (
    all_numeric_dataset,
    constant_column_dataset,
    numeric_classifications,
    tiny_dataset,
)

TOLERANCE = 1e-10


def test_perfect_positive_and_negative_correlations() -> None:
    df = all_numeric_dataset()  # beta = 10*alpha, gamma = -alpha + 5
    result = compute_correlations(df, numeric_classifications(df))

    pair = next(p for p in result["pairs"] if {p["column_a"], p["column_b"]} == {"alpha", "beta"})
    assert pair["correlation"] == pytest.approx(1.0, abs=TOLERANCE)
    assert pair["direction"] == "positive"

    pair = next(p for p in result["pairs"] if {p["column_a"], p["column_b"]} == {"alpha", "gamma"})
    assert pair["correlation"] == pytest.approx(-1.0, abs=TOLERANCE)
    assert pair["direction"] == "negative"


def test_values_match_scipy_pearsonr() -> None:
    """Cross-checked against a different library rather than asserting
    our own output back at ourselves (Phase 7 S12)."""
    df = pd.DataFrame(
        {
            "one": [1.0, 4.0, 2.0, 8.0, 5.0, 7.0],
            "two": [2.0, 3.0, 5.0, 7.0, 4.0, 9.0],
        }
    )
    result = compute_correlations(df, numeric_classifications(df))
    ours = result["pairs"][0]["correlation"]
    expected = scipy_stats.pearsonr(df["one"], df["two"])[0]

    assert ours == pytest.approx(expected, abs=TOLERANCE)


def test_full_matrix_is_square_symmetric_with_unit_diagonal() -> None:
    df = all_numeric_dataset()
    matrix = compute_correlations(df, numeric_classifications(df))["matrix"]

    columns = list(df.columns)
    assert set(matrix.keys()) == set(columns)
    for a in columns:
        assert matrix[a][a] == pytest.approx(1.0, abs=TOLERANCE)
        for b in columns:
            assert matrix[a][b] == pytest.approx(matrix[b][a], abs=TOLERANCE)


def test_self_correlation_is_never_a_strongest_relationship() -> None:
    df = all_numeric_dataset()
    result = compute_correlations(df, numeric_classifications(df))

    for pair in result["pairs"]:
        assert pair["column_a"] != pair["column_b"]
    assert result["strongest_positive"]["column_a"] != result["strongest_positive"]["column_b"]


def test_strongest_positive_and_negative_are_identified_correctly() -> None:
    df = pd.DataFrame(
        {
            "a": [1.0, 2.0, 3.0, 4.0, 5.0],
            "b": [1.0, 2.1, 2.9, 4.2, 4.9],  # near-perfect positive with a
            "c": [5.0, 4.0, 3.0, 2.0, 1.0],  # perfect negative with a
        }
    )
    result = compute_correlations(df, numeric_classifications(df))

    assert result["strongest_positive"]["correlation"] > 0.9
    assert result["strongest_negative"]["correlation"] == pytest.approx(-1.0, abs=1e-9)


def test_constant_column_is_excluded_rather_than_reported_as_zero() -> None:
    """Correlation with a zero-variance column is undefined (zero
    denominator), not zero - reporting 0.0 would read as 'no
    relationship found', which is a different and false claim."""
    df = constant_column_dataset()
    result = compute_correlations(df, numeric_classifications(df))

    assert all("fixed" not in (p["column_a"], p["column_b"]) for p in result["pairs"])
    assert result["undefined_pair_count"] >= 1
    assert result["matrix"]["fixed"]["varying"] is None


def test_insufficient_observations_yields_no_pairs() -> None:
    df = tiny_dataset()  # only 2 rows; r is trivially +/-1 and meaningless
    result = compute_correlations(df, numeric_classifications(df))
    assert result["pairs"] == []


def test_single_numeric_column_reports_unavailable() -> None:
    df = pd.DataFrame({"only": [1.0, 2.0, 3.0], "text": ["a", "b", "c"]})
    result = compute_correlations(df, numeric_classifications(df))

    assert result["available"] is False
    assert result["reason"] == "at_least_two_numeric_columns_required"


def test_strength_labels_are_assigned_by_magnitude() -> None:
    df = pd.DataFrame({"a": [1.0, 2.0, 3.0, 4.0, 5.0], "b": [1.0, 2.0, 3.0, 4.0, 5.0]})
    result = compute_correlations(df, numeric_classifications(df))
    assert result["pairs"][0]["strength"] == "strong"
