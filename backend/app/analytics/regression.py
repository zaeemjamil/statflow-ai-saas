"""
Multiple linear regression via statsmodels OLS.

Rebuilds StatFlow's `Machine Learning` node (Phase 1 audit S5/S7). The
original solved OLS by hand - transpose, matrix multiply, Gauss-Jordan
inverse - which was mathematically correct but could not produce
standard errors, t-statistics, p-values, or confidence intervals,
because the normal-equations approach doesn't yield them without
substantial extra work. statsmodels provides all of it, which is
exactly why the approved architecture specifies it over scikit-learn.

Three behaviours from the original are deliberately NOT carried
forward:
  * a hardcoded target (`Profit`) and five hardcoded predictors
  * a sequential 80/20 split (`X[:split]`), which makes results depend
    on row order and is neither reproducible across re-sorts nor
    representative - replaced by a seeded shuffled split
  * silent row dropping - rows removed for missing values are now
    counted and reported
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import statsmodels.api as sm

from app.analytics._common import numeric_columns, safe_float
from app.core.exceptions import ValidationException

DEFAULT_TEST_SIZE = 0.2
DEFAULT_RANDOM_SEED = 42

# An OLS fit needs more observations than parameters (predictors + 1
# intercept) to have residual degrees of freedom at all. At exactly
# equal it interpolates perfectly (R2 = 1) and tells you nothing, and
# every inference statistic is undefined. A small margin above that is
# the practical floor for a model whose p-values mean anything.
MIN_RESIDUAL_DEGREES_OF_FREEDOM = 2

MAX_SAMPLE_PREDICTIONS = 20


def _fail(message: str, code: str) -> None:
    """All regression failures surface as application-level errors with
    safe messages - never a raw statsmodels/numpy exception (Phase 7
    S10). The message tells the user what to change, since every one of
    these is a fixable configuration problem, not a server fault."""
    raise ValidationException(message, error_code=code)


def run_regression(
    df: pd.DataFrame,
    classifications: dict[str, str],
    target: str,
    predictors: list[str],
    test_size: float = DEFAULT_TEST_SIZE,
    random_seed: int = DEFAULT_RANDOM_SEED,
) -> dict[str, Any]:
    """Fit OLS with a reproducible shuffled train/test split.

    Args:
        target: one numeric column, chosen by the user from the
            profiler's numeric columns. Never hardcoded.
        predictors: one or more numeric columns, same constraint.
        test_size / random_seed: both configurable; the seed makes a run
            exactly reproducible, which matters because these numbers
            end up in a saved report a user may revisit.
    """
    available = set(numeric_columns(df, classifications))

    # --- configuration validation (before touching any data) ---------
    if not target:
        _fail("A target column is required.", "regression_target_required")
    if not predictors:
        _fail("At least one predictor column is required.", "regression_predictors_required")
    if target in predictors:
        _fail(
            "The target column cannot also be used as a predictor.",
            "regression_target_in_predictors",
        )
    if target not in df.columns:
        _fail(f"Target column '{target}' is not in the dataset.", "regression_target_not_found")
    if target not in available:
        _fail(
            f"Target column '{target}' is not numeric. Regression requires a numeric target.",
            "regression_target_not_numeric",
        )

    missing_predictors = [p for p in predictors if p not in df.columns]
    if missing_predictors:
        _fail(
            f"Predictor column(s) not in the dataset: {', '.join(missing_predictors)}.",
            "regression_predictor_not_found",
        )
    non_numeric = [p for p in predictors if p not in available]
    if non_numeric:
        _fail(
            f"Predictor column(s) not numeric: {', '.join(non_numeric)}. "
            "Regression requires numeric predictors.",
            "regression_predictor_not_numeric",
        )
    if not 0.0 < test_size < 1.0:
        _fail("Test size must be between 0 and 1 (exclusive).", "regression_invalid_test_size")

    # --- assemble the modelling dataset -------------------------------
    columns = [target, *predictors]
    model_df = df[columns].apply(pd.to_numeric, errors="coerce")

    rows_before = int(len(model_df))
    model_df = model_df.dropna()
    rows_used = int(len(model_df))
    rows_dropped = rows_before - rows_used

    parameter_count = len(predictors) + 1  # + intercept
    minimum_rows = parameter_count + MIN_RESIDUAL_DEGREES_OF_FREEDOM
    if rows_used < minimum_rows:
        _fail(
            f"Not enough complete rows to fit this model: {rows_used} usable "
            f"row(s) for {len(predictors)} predictor(s), but at least {minimum_rows} "
            "are needed. Try fewer predictors or a dataset with fewer missing values.",
            "regression_insufficient_observations",
        )

    # Zero-variance predictors make the design matrix singular (a
    # constant column is a perfect duplicate of the intercept), so they
    # are caught here with a clear message rather than surfacing as an
    # opaque linear-algebra failure downstream.
    constant_predictors = [p for p in predictors if model_df[p].nunique() <= 1]
    if constant_predictors:
        _fail(
            f"Predictor column(s) have no variation: {', '.join(constant_predictors)}. "
            "A constant column cannot explain anything and makes the model unsolvable.",
            "regression_constant_predictor",
        )

    x_all = sm.add_constant(model_df[predictors], has_constant="add")

    # Perfect multicollinearity: one predictor is an exact linear
    # combination of others (e.g. a duplicated column, or a/b/a+b).
    # The design matrix is rank-deficient, and statsmodels would return
    # a "successful" fit with silently meaningless coefficients rather
    # than raising - so this is checked explicitly.
    rank = int(np.linalg.matrix_rank(x_all.to_numpy(dtype=float)))
    if rank < x_all.shape[1]:
        _fail(
            "These predictors are perfectly collinear - at least one is an exact "
            "combination of the others, so the model has no unique solution. "
            "Remove the redundant predictor(s) and try again.",
            "regression_singular_matrix",
        )

    # --- reproducible shuffled split ----------------------------------
    shuffled = model_df.sample(frac=1.0, random_state=random_seed)
    test_count = int(round(len(shuffled) * test_size))
    # Both splits must be non-empty: no test rows means no holdout
    # metrics, and too few train rows means an unfittable model.
    test_count = max(1, min(test_count, len(shuffled) - parameter_count - 1))
    train_df = shuffled.iloc[test_count:]
    test_df = shuffled.iloc[:test_count]

    x_train = sm.add_constant(train_df[predictors], has_constant="add")
    y_train = train_df[target]

    try:
        model = sm.OLS(y_train, x_train).fit()
    except Exception as exc:  # pragma: no cover - guarded by checks above
        _fail(
            "The regression model could not be fitted with these columns.",
            "regression_fit_failed",
        )
        raise AssertionError("unreachable") from exc  # pragma: no cover

    if model.df_resid < MIN_RESIDUAL_DEGREES_OF_FREEDOM:
        _fail(
            "Not enough residual degrees of freedom for reliable inference with "
            "this many predictors. Try fewer predictors or more data.",
            "regression_insufficient_degrees_of_freedom",
        )

    x_test = sm.add_constant(test_df[predictors], has_constant="add")
    y_test = test_df[target]
    predictions = model.predict(x_test)

    residuals = y_test - predictions
    mae = safe_float(np.mean(np.abs(residuals)))
    rmse = safe_float(np.sqrt(np.mean(np.square(residuals))))

    conf_int = model.conf_int()

    coefficients = [
        {
            "name": name,
            "coefficient": safe_float(model.params[name]),
            "std_error": safe_float(model.bse[name]),
            "t_statistic": safe_float(model.tvalues[name]),
            "p_value": safe_float(model.pvalues[name]),
            "conf_int_lower": safe_float(conf_int.loc[name, 0]),
            "conf_int_upper": safe_float(conf_int.loc[name, 1]),
            "significant_at_05": (
                safe_float(model.pvalues[name]) is not None and float(model.pvalues[name]) < 0.05
            ),
        }
        for name in predictors
    ]

    sample_predictions = [
        {
            "actual": safe_float(actual),
            "predicted": safe_float(predicted),
            "residual": safe_float(actual - predicted),
        }
        # Bounded: a large test set must not produce an enormous payload
        # in JSONB / an API response / an AI prompt (Phase 7 S13).
        for actual, predicted in list(zip(y_test, predictions, strict=True))[
            :MAX_SAMPLE_PREDICTIONS
        ]
    ]

    return {
        "available": True,
        "model": {
            "target": target,
            "predictors": list(predictors),
            "method": "ols",
            "observations_total": rows_before,
            "observations_used": rows_used,
            "rows_dropped_for_missing_values": rows_dropped,
            "train_observations": int(len(train_df)),
            "test_observations": int(len(test_df)),
            "test_size": test_size,
            "random_seed": random_seed,
            "intercept": safe_float(model.params.get("const")),
        },
        "coefficients": coefficients,
        "metrics": {
            "r_squared": safe_float(model.rsquared),
            "adjusted_r_squared": safe_float(model.rsquared_adj),
            "mae": mae,
            "rmse": rmse,
            "f_statistic": safe_float(model.fvalue),
            "f_p_value": safe_float(model.f_pvalue),
            "residual_degrees_of_freedom": safe_float(model.df_resid),
        },
        "sample_predictions": sample_predictions,
        "residual_summary": {
            "mean": safe_float(np.mean(residuals)),
            "std": safe_float(np.std(residuals, ddof=1)) if len(residuals) > 1 else None,
            "min": safe_float(np.min(residuals)) if len(residuals) else None,
            "max": safe_float(np.max(residuals)) if len(residuals) else None,
        },
    }
