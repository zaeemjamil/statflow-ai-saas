"""Regression - correctness against analytically known coefficients,
plus every validation path."""

from __future__ import annotations

from typing import Any

import pandas as pd
import pytest

from app.analytics.regression import run_regression
from app.core.exceptions import ValidationException
from tests.analytics_fixtures import (
    collinear_dataset,
    numeric_classifications,
    regression_dataset,
    tiny_dataset,
)


def _run(df: pd.DataFrame, **kwargs: Any) -> dict[str, Any]:
    return run_regression(df, numeric_classifications(df), **kwargs)


def test_recovers_known_coefficients_exactly_on_noiseless_data() -> None:
    """target = 5 + 3*driver_a - 2*driver_b, no noise. A correct OLS
    implementation must recover those parameters to floating-point
    precision - this is the core correctness check for the module."""
    df = regression_dataset(noise=0.0)
    result = _run(df, target="target", predictors=["driver_a", "driver_b"])

    assert result["model"]["intercept"] == pytest.approx(5.0, abs=1e-8)
    coefficients = {c["name"]: c["coefficient"] for c in result["coefficients"]}
    assert coefficients["driver_a"] == pytest.approx(3.0, abs=1e-8)
    assert coefficients["driver_b"] == pytest.approx(-2.0, abs=1e-8)
    assert result["metrics"]["r_squared"] == pytest.approx(1.0, abs=1e-8)


def test_metrics_are_present_and_sane_on_noisy_data() -> None:
    df = regression_dataset(noise=5.0)
    result = _run(df, target="target", predictors=["driver_a", "driver_b"])
    metrics = result["metrics"]

    assert 0.0 <= metrics["r_squared"] <= 1.0
    assert metrics["adjusted_r_squared"] <= metrics["r_squared"]
    assert metrics["mae"] > 0
    assert metrics["rmse"] >= metrics["mae"]  # RMSE >= MAE always holds
    assert metrics["residual_degrees_of_freedom"] > 0


def test_inference_statistics_are_returned() -> None:
    df = regression_dataset(noise=3.0)
    result = _run(df, target="target", predictors=["driver_a", "driver_b"])

    for coefficient in result["coefficients"]:
        assert coefficient["std_error"] is not None
        assert coefficient["t_statistic"] is not None
        assert coefficient["p_value"] is not None
        assert coefficient["conf_int_lower"] is not None
        assert coefficient["conf_int_upper"] is not None
        assert coefficient["conf_int_lower"] <= coefficient["coefficient"]
        assert coefficient["coefficient"] <= coefficient["conf_int_upper"]


def test_genuine_predictors_are_statistically_significant() -> None:
    df = regression_dataset(noise=2.0)
    result = _run(df, target="target", predictors=["driver_a", "driver_b"])

    for coefficient in result["coefficients"]:
        assert coefficient["p_value"] < 0.05
        assert coefficient["significant_at_05"] is True


def test_train_test_split_is_eighty_twenty_by_default() -> None:
    df = regression_dataset(n=200)
    model = _run(df, target="target", predictors=["driver_a"])["model"]

    assert model["train_observations"] == 160
    assert model["test_observations"] == 40
    assert model["train_observations"] + model["test_observations"] == 200


def test_split_size_and_seed_are_configurable() -> None:
    df = regression_dataset(n=100)
    model = _run(df, target="target", predictors=["driver_a"], test_size=0.5, random_seed=7)[
        "model"
    ]

    assert model["test_observations"] == 50
    assert model["random_seed"] == 7


def test_same_seed_is_reproducible_and_different_seed_is_not() -> None:
    """The original StatFlow split was a sequential slice, so results
    depended on row order. A seeded shuffle must be reproducible across
    runs but genuinely different across seeds."""
    df = regression_dataset(n=120, noise=4.0)
    first = _run(df, target="target", predictors=["driver_a"], random_seed=1)
    second = _run(df, target="target", predictors=["driver_a"], random_seed=1)
    third = _run(df, target="target", predictors=["driver_a"], random_seed=2)

    assert first["metrics"] == second["metrics"]
    assert first["metrics"]["rmse"] != third["metrics"]["rmse"]


def test_rows_dropped_for_missing_values_are_reported_not_silent() -> None:
    df = regression_dataset(n=100)
    df.loc[0:9, "driver_a"] = None

    model = _run(df, target="target", predictors=["driver_a", "driver_b"])["model"]
    assert model["rows_dropped_for_missing_values"] == 10
    assert model["observations_used"] == 90
    assert model["observations_total"] == 100


def test_sample_predictions_are_bounded_and_internally_consistent() -> None:
    from app.analytics.regression import MAX_SAMPLE_PREDICTIONS

    df = regression_dataset(n=500, noise=2.0)
    result = _run(df, target="target", predictors=["driver_a"])

    assert len(result["sample_predictions"]) <= MAX_SAMPLE_PREDICTIONS
    for prediction in result["sample_predictions"]:
        expected = prediction["actual"] - prediction["predicted"]
        assert prediction["residual"] == pytest.approx(expected, abs=1e-8)


@pytest.mark.parametrize(
    ("kwargs", "expected_code"),
    [
        ({"target": "", "predictors": ["driver_a"]}, "regression_target_required"),
        ({"target": "target", "predictors": []}, "regression_predictors_required"),
        (
            {"target": "target", "predictors": ["target", "driver_a"]},
            "regression_target_in_predictors",
        ),
        ({"target": "nope", "predictors": ["driver_a"]}, "regression_target_not_found"),
        ({"target": "target", "predictors": ["nope"]}, "regression_predictor_not_found"),
        (
            {"target": "target", "predictors": ["driver_a"], "test_size": 1.5},
            "regression_invalid_test_size",
        ),
    ],
)
def test_invalid_configurations_raise_application_errors(
    kwargs: dict[str, Any], expected_code: str
) -> None:
    df = regression_dataset(n=60)
    with pytest.raises(ValidationException) as exc_info:
        _run(df, **kwargs)
    assert exc_info.value.error_code == expected_code


def test_non_numeric_target_and_predictor_are_rejected() -> None:
    df = regression_dataset(n=60)
    df["category"] = ["x", "y"] * 30

    with pytest.raises(ValidationException) as exc_info:
        _run(df, target="category", predictors=["driver_a"])
    assert exc_info.value.error_code == "regression_target_not_numeric"

    with pytest.raises(ValidationException) as exc_info:
        _run(df, target="target", predictors=["category"])
    assert exc_info.value.error_code == "regression_predictor_not_numeric"


def test_insufficient_observations_is_rejected_with_a_clear_error() -> None:
    with pytest.raises(ValidationException) as exc_info:
        run_regression(tiny_dataset(), numeric_classifications(tiny_dataset()), "y", ["x"])
    assert exc_info.value.error_code == "regression_insufficient_observations"


def test_constant_predictor_is_rejected() -> None:
    df = regression_dataset(n=60)
    df["fixed"] = 3.0

    with pytest.raises(ValidationException) as exc_info:
        _run(df, target="target", predictors=["fixed"])
    assert exc_info.value.error_code == "regression_constant_predictor"


def test_perfectly_collinear_predictors_are_rejected() -> None:
    """`total` is exactly part_one + part_two. statsmodels would return
    a 'successful' fit with silently meaningless coefficients rather
    than raising, so this must be caught explicitly."""
    df = collinear_dataset()

    with pytest.raises(ValidationException) as exc_info:
        _run(df, target="outcome", predictors=["part_one", "part_two", "total"])
    assert exc_info.value.error_code == "regression_singular_matrix"


def test_duplicated_predictor_column_is_rejected_as_singular() -> None:
    df = regression_dataset(n=60)
    df["copy_of_a"] = df["driver_a"]

    with pytest.raises(ValidationException) as exc_info:
        _run(df, target="target", predictors=["driver_a", "copy_of_a"])
    assert exc_info.value.error_code == "regression_singular_matrix"


def test_no_statflow_column_names_are_required() -> None:
    """The original hardcoded `Profit` as target and five retail
    columns as predictors. Nothing here shares a single name with it."""
    df = regression_dataset(n=80)
    result = _run(df, target="target", predictors=["driver_a", "driver_b"])
    assert result["available"] is True
