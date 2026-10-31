/** Zod mirrors of the backend's Pydantic response models (app/schemas/*). */
import { z } from "zod";

export const PROJECT_STATUSES = [
  "created",
  "uploaded",
  "profiled",
  "cleaning_pending",
  "cleaning_completed",
  "analyzing",
  "completed",
  "failed",
] as const;
export const projectStatusSchema = z.enum(PROJECT_STATUSES);
export type ProjectStatus = z.infer<typeof projectStatusSchema>;

export const projectSchema = z.object({
  id: z.string(),
  name: z.string(),
  status: projectStatusSchema,
  created_at: z.string(),
  updated_at: z.string(),
});
export type Project = z.infer<typeof projectSchema>;

export const recentProjectSchema = projectSchema.pick({ id: true, name: true, status: true, updated_at: true });

export const dashboardSummarySchema = z.object({
  total_projects: z.number(),
  files_analyzed: z.number(),
  reports_generated: z.number(),
  ai_insights_generated: z.number(),
  recent_projects: z.array(recentProjectSchema),
});
export type DashboardSummary = z.infer<typeof dashboardSummarySchema>;

export const fileInfoSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  original_filename: z.string(),
  file_type: z.enum(["csv", "xlsx"]),
  size_bytes: z.number(),
  row_count: z.number().nullable(),
  column_count: z.number().nullable(),
  created_at: z.string(),
});
export type FileInfo = z.infer<typeof fileInfoSchema>;

export const columnProfileSchema = z.object({
  name: z.string(),
  classification: z.enum(["numeric", "categorical", "date"]),
  pandas_dtype: z.string(),
  missing_count: z.number(),
  missing_percentage: z.number(),
  unique_count: z.number(),
  is_unique: z.boolean(),
  min_value: z.number().nullable().optional(),
  max_value: z.number().nullable().optional(),
  // Stage 3 data-correctness findings (absent on profiles stored before Stage 3).
  likely_identifier: z.boolean().optional(),
  identifier_reason: z.string().nullable().optional(),
  number_format: z.string().nullable().optional(),
  number_format_examples: z.array(z.string()).optional(),
  date_order_issue: z.string().nullable().optional(),
});
export type ColumnProfile = z.infer<typeof columnProfileSchema>;

export const importNoteSchema = z.object({
  code: z.string(),
  severity: z.enum(["info", "warning"]),
  message: z.string(),
  columns: z.array(z.string()).optional(),
});
export type ImportNote = z.infer<typeof importNoteSchema>;

export const datasetProfileSchema = z.object({
  row_count: z.number(),
  column_count: z.number(),
  numeric_column_count: z.number(),
  categorical_column_count: z.number(),
  date_column_count: z.number(),
  total_missing_values: z.number(),
  duplicate_row_count: z.number(),
  columns: z.array(columnProfileSchema),
  import_notes: z.array(importNoteSchema).optional(),
});
export type DatasetProfile = z.infer<typeof datasetProfileSchema>;

export const uploadResponseSchema = z.object({ file: fileInfoSchema, profile: datasetProfileSchema });
export type UploadResponse = z.infer<typeof uploadResponseSchema>;

// --- Analysis (mirrors backend app/schemas/analysis.py, verified against real responses) ---

const num = z.number().nullable();

export const STAGE_NAMES = [
  "profiling",
  "cleaning",
  "statistics",
  "correlations",
  "outliers",
  "regression",
  "visualizations",
] as const;
export type StageName = (typeof STAGE_NAMES)[number];
export const stageStateSchema = z.enum(["pending", "completed", "failed", "skipped"]);
export type StageState = z.infer<typeof stageStateSchema>;

export const cleaningColumnActionSchema = z.object({
  column: z.string(),
  action: z.enum(["imputed", "left_unchanged"]),
  method: z.string().nullable().optional(),
  reason: z.string().nullable().optional(),
  fill_value: z.union([z.number(), z.string()]).nullable().optional(),
  missing_before: z.number(),
  missing_after: z.number(),
  values_changed: z.number(),
});

export const cleaningReportSchema = z.object({
  config: z.record(z.string(), z.string()),
  rows_before: z.number(),
  rows_after: z.number(),
  rows_removed: z.number(),
  missing_before: z.number(),
  missing_after: z.number(),
  missing_values_imputed: z.number(),
  duplicates_before: z.number(),
  duplicates_after: z.number(),
  duplicates_removed: z.number(),
  column_actions: z.array(cleaningColumnActionSchema),
});
export type CleaningReport = z.infer<typeof cleaningReportSchema>;

export const columnStatisticsSchema = z.object({
  column: z.string(),
  count: z.number(),
  missing_count: z.number(),
  mean: num.optional(),
  median: num.optional(),
  std: num.optional(),
  min: num.optional(),
  q1: num.optional(),
  q3: num.optional(),
  max: num.optional(),
  iqr: num.optional(),
});
export const descriptiveStatisticsSchema = z.object({
  columns: z.array(columnStatisticsSchema),
  numeric_column_count: z.number(),
  skipped_columns: z.array(z.string()),
});
export type DescriptiveStatistics = z.infer<typeof descriptiveStatisticsSchema>;

export const correlationPairSchema = z.object({
  column_a: z.string(),
  column_b: z.string(),
  correlation: z.number(),
  strength: z.enum(["strong", "moderate", "weak", "negligible"]),
  direction: z.enum(["positive", "negative"]),
});
export const correlationResultSchema = z.object({
  available: z.boolean(),
  reason: z.string().nullable().optional(),
  numeric_column_count: z.number(),
  matrix: z.record(z.string(), z.record(z.string(), num)),
  pairs: z.array(correlationPairSchema),
  strongest_positive: correlationPairSchema.nullable().optional(),
  strongest_negative: correlationPairSchema.nullable().optional(),
  undefined_pair_count: z.number(),
});
export type CorrelationResult = z.infer<typeof correlationResultSchema>;

export const columnOutliersSchema = z.object({
  column: z.string(),
  detected: z.boolean(),
  reason: z.string().nullable().optional(),
  observation_count: z.number(),
  q1: num.optional(),
  q3: num.optional(),
  iqr: num.optional(),
  lower_bound: num.optional(),
  upper_bound: num.optional(),
  outlier_count: z.number(),
  outlier_percentage: z.number(),
  outlier_indices: z.array(z.number()),
  outlier_indices_truncated: z.boolean(),
});
export const outlierResultSchema = z.object({
  columns: z.array(columnOutliersSchema),
  method: z.literal("iqr"),
  iqr_multiplier: z.number(),
  total_outlier_count: z.number(),
  columns_with_outliers: z.number(),
});
export type OutlierResult = z.infer<typeof outlierResultSchema>;

export const regressionResultSchema = z.object({
  available: z.boolean(),
  error_code: z.string().nullable().optional(),
  message: z.string().nullable().optional(),
  reason: z.string().nullable().optional(),
  model: z
    .object({
      target: z.string(),
      predictors: z.array(z.string()),
      method: z.literal("ols"),
      observations_total: z.number(),
      observations_used: z.number(),
      rows_dropped_for_missing_values: z.number(),
      train_observations: z.number(),
      test_observations: z.number(),
      test_size: z.number(),
      random_seed: z.number(),
      intercept: num.optional(),
    })
    .nullable()
    .optional(),
  coefficients: z.array(
    z.object({
      name: z.string(),
      coefficient: num.optional(),
      std_error: num.optional(),
      t_statistic: num.optional(),
      p_value: num.optional(),
      conf_int_lower: num.optional(),
      conf_int_upper: num.optional(),
      significant_at_05: z.boolean(),
    }),
  ),
  metrics: z
    .object({
      r_squared: num.optional(),
      adjusted_r_squared: num.optional(),
      mae: num.optional(),
      rmse: num.optional(),
      f_statistic: num.optional(),
      f_p_value: num.optional(),
      residual_degrees_of_freedom: num.optional(),
    })
    .nullable()
    .optional(),
  sample_predictions: z.array(z.object({ actual: num.optional(), predicted: num.optional(), residual: num.optional() })),
  residual_summary: z.record(z.string(), num),
});
export type RegressionResult = z.infer<typeof regressionResultSchema>;

/** Present only when a scatter/line chart's per-row data was reduced for display. */
export const chartSamplingSchema = z.object({
  method: z.string(),
  total_points: z.number(),
  displayed_points: z.number(),
  max_points: z.number(),
});
export type ChartSampling = z.infer<typeof chartSamplingSchema>;

export const chartRecommendationSchema = z.object({
  chart_type: z.enum(["scatter", "line", "bar", "histogram", "count"]),
  title: z.string(),
  x_column: z.string().nullable().optional(),
  y_column: z.string().nullable().optional(),
  group_column: z.string().nullable().optional(),
  aggregation: z.string().nullable().optional(),
  bins: z.number().nullable().optional(),
  reason: z.string(),
  data_requirements: z.record(z.string(), z.string()),
  data: z.array(z.record(z.string(), z.unknown())),
  sampling: chartSamplingSchema.nullable().optional(),
});
export type ChartRecommendation = z.infer<typeof chartRecommendationSchema>;
export const visualizationResultSchema = z.object({
  available: z.boolean(),
  charts: z.array(chartRecommendationSchema),
  chart_count: z.number(),
  reason: z.string().nullable().optional(),
});

export const analysisSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  file_id: z.string(),
  status: z.string(),
  current_stage: z.string().nullable().optional(),
  stages: z.record(z.string(), stageStateSchema),
  profile: datasetProfileSchema.nullable().optional(),
  cleaned_profile: datasetProfileSchema.nullable().optional(),
  cleaning: cleaningReportSchema.nullable().optional(),
  statistics: descriptiveStatisticsSchema.nullable().optional(),
  correlations: correlationResultSchema.nullable().optional(),
  outliers: outlierResultSchema.nullable().optional(),
  regression: regressionResultSchema.nullable().optional(),
  visualizations: visualizationResultSchema.nullable().optional(),
  error_message: z.string().nullable().optional(),
  started_at: z.string().nullable().optional(),
  completed_at: z.string().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});
export type Analysis = z.infer<typeof analysisSchema>;

export const CLEANING_OPTIONS = {
  numeric_strategy: ["median", "unchanged"],
  categorical_strategy: ["mode", "unchanged"],
  duplicate_strategy: ["keep", "remove"],
} as const;
export type CleaningConfig = {
  numeric_strategy: (typeof CLEANING_OPTIONS.numeric_strategy)[number];
  categorical_strategy: (typeof CLEANING_OPTIONS.categorical_strategy)[number];
  duplicate_strategy: (typeof CLEANING_OPTIONS.duplicate_strategy)[number];
};
export type RegressionInput = { target: string; predictors: string[] };

export const aiInsightSchema = z.object({
  summary: z.string(),
  key_findings: z.array(z.string()),
  data_quality: z.array(z.string()),
  limitations: z.array(z.string()),
  next_steps: z.array(z.string()),
  evidence_warnings: z.array(z.string()),
  generated_at: z.string(),
  model: z.string(),
  prompt_version: z.string(),
});
export type AiInsight = z.infer<typeof aiInsightSchema>;

export const aiInsightsStateSchema = z.object({
  configured: z.boolean(),
  eligible: z.boolean(),
  reason_code: z.string().nullable().optional(),
  message: z.string().nullable().optional(),
  warnings: z.array(z.string()),
  insight: aiInsightSchema.nullable().optional(),
  has_outdated_insight: z.boolean(),
  remaining_today: z.number(),
  disclaimer: z.string(),
});
export type AiInsightsState = z.infer<typeof aiInsightsStateSchema>;

export const reportSchema = z.object({
  id: z.string(),
  project_id: z.string(),
  analysis_id: z.string(),
  file_name: z.string().nullable(),
  generated_at: z.string(),
});
export type Report = z.infer<typeof reportSchema>;
