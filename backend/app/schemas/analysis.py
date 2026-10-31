"""
Typed result contracts for the analytics engine.

These are the stable structures that Phase 4's JSONB columns, the
Phase 8 API/dashboard, the Phase 9 AI service, and the Phase 10 PDF all
consume. Defining them once here means the frontend never parses raw
pandas output, and the AI service and the PDF quote the *same* numbers
the dashboard shows - which is a stated requirement, not a nicety.

Every float is `| None`: NaN and infinity are not representable in JSON
and occur legitimately (std of one observation, correlation against a
constant column), so they are normalized to null rather than dropped or
coerced to zero.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

ChartType = Literal["scatter", "line", "bar", "histogram", "count"]


# --- cleaning ---------------------------------------------------------


class CleaningColumnAction(BaseModel):
    column: str
    action: Literal["imputed", "left_unchanged"]
    method: str | None = None
    reason: str | None = None
    fill_value: float | str | None = None
    missing_before: int
    missing_after: int
    values_changed: int


class CleaningReport(BaseModel):
    config: dict[str, str]
    rows_before: int
    rows_after: int
    rows_removed: int
    missing_before: int
    missing_after: int
    missing_values_imputed: int
    duplicates_before: int
    duplicates_after: int
    duplicates_removed: int
    column_actions: list[CleaningColumnAction]


# --- descriptive statistics -------------------------------------------


class ColumnStatistics(BaseModel):
    column: str
    count: int
    missing_count: int
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    min: float | None = None
    q1: float | None = None
    q3: float | None = None
    max: float | None = None
    iqr: float | None = None


class DescriptiveStatistics(BaseModel):
    columns: list[ColumnStatistics]
    numeric_column_count: int
    skipped_columns: list[str] = Field(default_factory=list)


# --- correlation ------------------------------------------------------


class CorrelationPair(BaseModel):
    column_a: str
    column_b: str
    correlation: float
    strength: Literal["strong", "moderate", "weak", "negligible"]
    direction: Literal["positive", "negative"]


class CorrelationResult(BaseModel):
    available: bool
    reason: str | None = None
    numeric_column_count: int = 0
    matrix: dict[str, dict[str, float | None]] = Field(default_factory=dict)
    pairs: list[CorrelationPair] = Field(default_factory=list)
    strongest_positive: CorrelationPair | None = None
    strongest_negative: CorrelationPair | None = None
    undefined_pair_count: int = 0


# --- outliers ---------------------------------------------------------


class ColumnOutliers(BaseModel):
    column: str
    detected: bool
    reason: str | None = None
    observation_count: int
    q1: float | None = None
    q3: float | None = None
    iqr: float | None = None
    lower_bound: float | None = None
    upper_bound: float | None = None
    outlier_count: int
    outlier_percentage: float
    outlier_indices: list[int] = Field(default_factory=list)
    outlier_indices_truncated: bool = False


class OutlierResult(BaseModel):
    columns: list[ColumnOutliers]
    method: Literal["iqr"]
    iqr_multiplier: float
    total_outlier_count: int
    columns_with_outliers: int


# --- regression -------------------------------------------------------


class RegressionCoefficient(BaseModel):
    name: str
    coefficient: float | None = None
    std_error: float | None = None
    t_statistic: float | None = None
    p_value: float | None = None
    conf_int_lower: float | None = None
    conf_int_upper: float | None = None
    significant_at_05: bool = False


class RegressionModel(BaseModel):
    target: str
    predictors: list[str]
    method: Literal["ols"]
    observations_total: int
    observations_used: int
    rows_dropped_for_missing_values: int
    train_observations: int
    test_observations: int
    test_size: float
    random_seed: int
    intercept: float | None = None


class RegressionMetrics(BaseModel):
    r_squared: float | None = None
    adjusted_r_squared: float | None = None
    mae: float | None = None
    rmse: float | None = None
    f_statistic: float | None = None
    f_p_value: float | None = None
    residual_degrees_of_freedom: float | None = None


class SamplePrediction(BaseModel):
    actual: float | None = None
    predicted: float | None = None
    residual: float | None = None


class RegressionResult(BaseModel):
    available: bool
    # Present when a regression was not run or failed - the UI shows the
    # message, never a stack trace.
    error_code: str | None = None
    message: str | None = None
    reason: str | None = None
    model: RegressionModel | None = None
    coefficients: list[RegressionCoefficient] = Field(default_factory=list)
    metrics: RegressionMetrics | None = None
    sample_predictions: list[SamplePrediction] = Field(default_factory=list)
    residual_summary: dict[str, float | None] = Field(default_factory=dict)


# --- visualization ----------------------------------------------------


class ChartSampling(BaseModel):
    """Present only when a scatter/line chart's per-row data was reduced for
    display. Statistics are unaffected: they always use every row."""

    method: str  # "even_spread" (scatter) or "min_max" (line)
    total_points: int
    displayed_points: int
    max_points: int


class ChartRecommendation(BaseModel):
    chart_type: ChartType
    title: str
    x_column: str | None = None
    y_column: str | None = None
    group_column: str | None = None
    aggregation: str | None = None
    bins: int | None = None
    # Why this chart was chosen - shown in the UI so no chart is an
    # unexplained default (Phase 7 S6).
    reason: str
    data_requirements: dict[str, str] = Field(default_factory=dict)
    data: list[dict[str, Any]] = Field(default_factory=list)
    # Additive: absent (null) when the chart shows every point.
    sampling: ChartSampling | None = None


class VisualizationResult(BaseModel):
    available: bool
    charts: list[ChartRecommendation] = Field(default_factory=list)
    chart_count: int = 0
    reason: str | None = None


# --- full analysis ----------------------------------------------------


class AnalysisResult(BaseModel):
    """The complete pipeline output. `stages` mirrors the Phase 2
    staged-progress UI so the frontend can show which steps succeeded
    even when one of them didn't."""

    stages: dict[str, Literal["completed", "failed", "skipped"]]
    cleaning: CleaningReport
    statistics: DescriptiveStatistics
    correlations: CorrelationResult
    outliers: OutlierResult
    regression: RegressionResult
    visualizations: VisualizationResult


# --- API request/response schemas (Phase 8A) --------------------------
#
# Everything above this line is Phase 7's pure-computation contract.
# What follows is the database-backed, API-facing shape: request bodies
# the frontend sends, and the persisted Analysis row's public
# representation - stages advance for real as cleaning/analyze/
# regression are actually called (Phase 8A: "do not fake progress"),
# never all at once.


class CleanRequest(BaseModel):
    numeric_strategy: Literal["median", "unchanged"] = "median"
    categorical_strategy: Literal["mode", "unchanged"] = "mode"
    duplicate_strategy: Literal["remove", "keep"] = "keep"


class RegressionRequest(BaseModel):
    target: str = Field(..., min_length=1)
    predictors: list[str] = Field(..., min_length=1)


class DatasetProfilePublic(BaseModel):
    """Re-declared here (rather than imported from the upload schemas)
    to keep this module's public contract self-contained for frontend
    codegen - same field names as Phase 6's profiler output either way."""

    model_config = ConfigDict(extra="allow")

    row_count: int
    column_count: int
    numeric_column_count: int
    categorical_column_count: int
    date_column_count: int
    total_missing_values: int
    duplicate_row_count: int
    columns: list[dict[str, Any]]


class AnalysisPublic(BaseModel):
    """What every analysis-reading endpoint returns - GET /analysis,
    the response of POST /clean, POST /analyze and POST /regression, so
    the frontend's TanStack Query cache for "this project's analysis"
    is always the same shape regardless of which call populated it.

    Stages reflect what has genuinely run against *this* persisted row,
    not the full Phase 7 pipeline's stage set - e.g. immediately after
    /clean, only "cleaning" is "completed"; the rest are "pending" until
    /analyze actually runs them.
    """

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    project_id: uuid.UUID
    file_id: uuid.UUID
    status: str
    current_stage: str | None = None
    stages: dict[str, Literal["pending", "completed", "failed", "skipped"]] = Field(
        default_factory=dict
    )

    profile: DatasetProfilePublic | None = None
    cleaned_profile: DatasetProfilePublic | None = None
    cleaning: CleaningReport | None = None
    statistics: DescriptiveStatistics | None = None
    correlations: CorrelationResult | None = None
    outliers: OutlierResult | None = None
    regression: RegressionResult | None = None
    visualizations: VisualizationResult | None = None

    error_message: str | None = None
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime
    updated_at: datetime
