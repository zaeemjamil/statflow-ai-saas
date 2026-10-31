import { fireEvent, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeAll, describe, expect, it } from "vitest";
import type { DatasetProfile } from "@/lib/schemas";
import { jsonResponse, mockApi, renderWithQuery } from "@/test/helpers";
import { AnalysisWorkspace } from "./analysis-workspace";

beforeAll(() => {
  // Recharts' ResponsiveContainer needs ResizeObserver, which jsdom lacks.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

const col = (name: string, classification: "numeric" | "categorical" | "date") => ({
  name, classification, pandas_dtype: "float64", missing_count: 0, missing_percentage: 0, unique_count: 5, is_unique: false,
});
const PROFILE: DatasetProfile = {
  row_count: 60, column_count: 4, numeric_column_count: 3, categorical_column_count: 1, date_column_count: 0,
  total_missing_values: 14, duplicate_row_count: 1,
  columns: [col("age", "numeric"), col("income", "numeric"), col("spend", "numeric"), col("city", "categorical")],
};

const CLEANING = {
  config: { numeric_strategy: "median", categorical_strategy: "mode", duplicate_strategy: "remove" },
  rows_before: 61, rows_after: 60, rows_removed: 1, missing_before: 14, missing_after: 0, missing_values_imputed: 14,
  duplicates_before: 1, duplicates_after: 0, duplicates_removed: 1,
  column_actions: [
    { column: "income", action: "imputed", method: "median", reason: null, fill_value: 44161.9, missing_before: 1, missing_after: 0, values_changed: 1 },
    { column: "city", action: "imputed", method: "mode", reason: null, fill_value: "B", missing_before: 13, missing_after: 0, values_changed: 13 },
  ],
};

const ALL_PENDING = { profiling: "completed", cleaning: "completed", statistics: "pending", correlations: "pending", outliers: "pending", regression: "pending", visualizations: "pending" };
const BASE = {
  id: "a1", project_id: "p1", file_id: "f1", status: "pending", current_stage: null, stages: ALL_PENDING,
  profile: PROFILE, cleaned_profile: PROFILE, cleaning: CLEANING, statistics: null, correlations: null, outliers: null,
  regression: null, visualizations: null, error_message: null, started_at: null, completed_at: null,
  created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:00:00Z",
};
const stat = (column: string, mean: number | null, std: number | null) => ({
  column, count: 60, missing_count: 0, mean, median: mean, std, min: 1, q1: 2, q3: 3, max: 900000, iqr: 1,
});
const PAIR = { column_a: "age", column_b: "spend", correlation: 0.798, strength: "strong", direction: "positive" };
const DONE = {
  ...BASE,
  status: "completed",
  stages: { ...ALL_PENDING, statistics: "completed", correlations: "completed", outliers: "completed", regression: "skipped", visualizations: "completed" },
  completed_at: "2026-10-01T10:01:00Z",
  statistics: { columns: [stat("age", 43.43, 11.2), stat("income", 56911.3, null)], numeric_column_count: 2, skipped_columns: ["city"] },
  correlations: {
    available: true, reason: null, numeric_column_count: 3,
    matrix: { age: { age: 1, spend: 0.798 }, spend: { age: 0.798, spend: 1 } },
    pairs: [PAIR], strongest_positive: PAIR, strongest_negative: null, undefined_pair_count: 0,
  },
  outliers: {
    method: "iqr", iqr_multiplier: 1.5, total_outlier_count: 1, columns_with_outliers: 1,
    columns: [
      { column: "income", detected: true, reason: null, observation_count: 60, q1: 1, q3: 2, iqr: 1, lower_bound: 5023.79, upper_bound: 83760.9, outlier_count: 1, outlier_percentage: 1.6667, outlier_indices: [7], outlier_indices_truncated: false },
      { column: "age", detected: false, reason: "constant_column", observation_count: 60, outlier_count: 0, outlier_percentage: 0, outlier_indices: [], outlier_indices_truncated: false },
    ],
  },
  visualizations: {
    available: true, chart_count: 2, reason: null,
    charts: [
      { chart_type: "scatter", title: "spend vs age", x_column: "age", y_column: "spend", reason: "Strongest linear association in the dataset (r = 0.80).", data_requirements: { x: "numeric", y: "numeric" }, data: [{ x: 1, y: 2 }, { x: 2, y: 3 }] },
      { chart_type: "histogram", title: "Distribution of age", x_column: "age", bins: 10, reason: "Shows the shape of a numeric column.", data_requirements: { x: "numeric" }, data: [{ bin_start: 20, bin_end: 30, count: 4 }] },
    ],
  },
};
const REGRESSION = {
  available: true, error_code: null, message: null, reason: null,
  model: { target: "spend", predictors: ["age", "income"], method: "ols", observations_total: 60, observations_used: 60, rows_dropped_for_missing_values: 0, train_observations: 48, test_observations: 12, test_size: 0.2, random_seed: 42, intercept: 628.6 },
  coefficients: [
    { name: "age", coefficient: 264.99, std_error: 33.1, t_statistic: 8, p_value: 3.4e-10, conf_int_lower: 198.2, conf_int_upper: 331.7, significant_at_05: true },
    { name: "income", coefficient: 0.0045, std_error: 0.003, t_statistic: 1.5, p_value: 0.134, conf_int_lower: -0.0014, conf_int_upper: 0.0105, significant_at_05: false },
  ],
  metrics: { r_squared: 0.6215, adjusted_r_squared: 0.6047, mae: 1849.4, rmse: 2308.5, f_statistic: 36.9, f_p_value: 3.2e-10, residual_degrees_of_freedom: 45 },
  sample_predictions: [{ actual: 4433.7, predicted: 8138.4, residual: -3704.7 }],
  residual_summary: { mean: -12.5, std: 2300, min: -3704.7, max: 3000 },
};
const NO_ANALYSIS = () => jsonResponse(404, { error: { code: "analysis_not_found", message: "No analysis exists for this project yet." } });
const err = (status: number, code: string, message: string) => jsonResponse(status, { error: { code, message } });

function setup(routes: Parameters<typeof mockApi>[0]) {
  const api = mockApi(routes);
  renderWithQuery(<AnalysisWorkspace projectId="p1" profile={PROFILE} />);
  return api;
}
const bodyOf = (init?: RequestInit) => JSON.parse(String(init?.body));
const posts = (api: ReturnType<typeof mockApi>, path: string) =>
  api.mock.calls.filter(([url, init]) => String(url).endsWith(path) && init?.method === "POST");

describe("AnalysisWorkspace — before any run", () => {
  it("treats a 404 as 'not run yet': shows real stages, an empty cleaning report and empty result tabs", async () => {
    setup({ "GET /projects/p1/analysis": NO_ANALYSIS });
    expect(await screen.findByRole("button", { name: "Run analysis" })).toBeInTheDocument();
    expect(screen.getByText("No cleaning has been applied yet.")).toBeInTheDocument();
    const stages = within(screen.getByRole("list", { name: "Analysis stages" })).getAllByRole("listitem");
    expect(stages).toHaveLength(7);
    expect(stages[0]).toHaveAttribute("data-state", "completed"); // profiling happened at upload
    expect(stages[2]).toHaveAttribute("data-state", "pending");
    await userEvent.click(screen.getByRole("tab", { name: "Statistics" }));
    expect(screen.getByText("No results yet")).toBeInTheDocument();
  });

  it("shows an error with retry when the analysis can't be loaded", async () => {
    setup({ "GET /projects/p1/analysis": () => err(500, "internal_error", "Boom") });
    expect(await screen.findByRole("alert")).toHaveTextContent("Boom");
    expect(screen.getByRole("button", { name: "Try again" })).toBeInTheDocument();
  });

  it("explains that regression needs a completed analysis", async () => {
    setup({ "GET /projects/p1/analysis": NO_ANALYSIS });
    await userEvent.click(await screen.findByRole("tab", { name: "Regression" }));
    expect(screen.getByText("Run the analysis first")).toBeInTheDocument();
  });
});

describe("AnalysisWorkspace — cleaning", () => {
  it("sends exactly the chosen options and shows the returned report", async () => {
    let first = true;
    const api = setup({
      "GET /projects/p1/analysis": () => (first ? NO_ANALYSIS() : jsonResponse(200, BASE)),
      "POST /projects/p1/clean": (init) => {
        first = false;
        return jsonResponse(200, { ...BASE, cleaning: { ...CLEANING, config: bodyOf(init) } });
      },
    });
    await userEvent.click(await screen.findByRole("radio", { name: /Remove duplicate rows/ }));
    await userEvent.click(screen.getByRole("radio", { name: /Leave as is\s*Missing numbers stay missing/ }));
    await userEvent.click(screen.getByRole("button", { name: "Apply cleaning" }));
    await waitFor(() => expect(posts(api, "/clean")).toHaveLength(1));
    expect(bodyOf(posts(api, "/clean")[0][1])).toEqual({ numeric_strategy: "unchanged", categorical_strategy: "mode", duplicate_strategy: "remove" });
    expect(await screen.findByText("Cleaning report")).toBeInTheDocument();
    expect(screen.getByRole("table", { name: "Per-column cleaning actions" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "city" })).toBeInTheDocument();
  });

  it("shows a readable error when cleaning fails", async () => {
    setup({
      "GET /projects/p1/analysis": NO_ANALYSIS,
      "POST /projects/p1/clean": () => err(409, "no_file_uploaded", "Upload a dataset to this project before analysing it."),
    });
    await userEvent.click(await screen.findByRole("button", { name: "Apply cleaning" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Upload a dataset to this project before cleaning or analysing it.");
  });

  it("does not warn when re-cleaning would erase nothing", async () => {
    const api = setup({ "GET /projects/p1/analysis": () => jsonResponse(200, BASE), "POST /projects/p1/clean": () => jsonResponse(200, BASE) });
    await userEvent.click(await screen.findByRole("button", { name: "Re-apply cleaning" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    await waitFor(() => expect(posts(api, "/clean")).toHaveLength(1));
  });

  it("warns before re-cleaning when results exist, names them, and only cleans after confirmation", async () => {
    const api = setup({
      "GET /projects/p1/analysis": () => jsonResponse(200, { ...DONE, regression: REGRESSION, stages: { ...DONE.stages, regression: "completed" } }),
      "POST /projects/p1/clean": () => jsonResponse(200, BASE),
    });
    await userEvent.click(await screen.findByRole("button", { name: "Re-apply cleaning" }));
    const dialog = screen.getByRole("alertdialog", { name: "Confirm re-cleaning" });
    expect(dialog).toHaveTextContent("statistics, correlations, outliers, the regression model, charts");
    expect(posts(api, "/clean")).toHaveLength(0);

    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(posts(api, "/clean")).toHaveLength(0);

    await userEvent.click(screen.getByRole("button", { name: "Re-apply cleaning" }));
    await userEvent.click(screen.getByRole("button", { name: "Erase results and re-clean" }));
    await waitFor(() => expect(posts(api, "/clean")).toHaveLength(1));
  });
});

describe("AnalysisWorkspace — running the analysis", () => {
  it("runs the analysis, then shows real statistics with nulls as dashes", async () => {
    let ran = false;
    const api = setup({
      "GET /projects/p1/analysis": () => (ran ? jsonResponse(200, DONE) : NO_ANALYSIS()),
      "POST /projects/p1/analyze": () => {
        ran = true;
        return jsonResponse(200, DONE);
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("button", { name: "Re-run analysis" })).toBeInTheDocument();
    expect(posts(api, "/analyze")).toHaveLength(1);
    expect(screen.getByText(/Analysis completed/)).toBeInTheDocument();

    await userEvent.click(screen.getByRole("tab", { name: "Statistics" }));
    const table = screen.getByRole("table", { name: "Descriptive statistics per numeric column" });
    const income = within(table).getByRole("rowheader", { name: "income" }).closest("tr")!;
    expect(income).toHaveTextContent("56,911.3");
    expect(income).toHaveTextContent("—"); // std is null for income in the fixture
    expect(screen.getByText(/Not shown \(not numeric\): city/)).toBeInTheDocument();
  });

  it("shows the server's message when the run fails", async () => {
    setup({
      "GET /projects/p1/analysis": NO_ANALYSIS,
      "POST /projects/p1/analyze": () => err(422, "empty_dataset", "This dataset has no rows to analyse."),
    });
    await userEvent.click(await screen.findByRole("button", { name: "Run analysis" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("This dataset has no rows to analyse.");
  });

  it("reports a previously failed run from the persisted state", async () => {
    setup({ "GET /projects/p1/analysis": () => jsonResponse(200, { ...BASE, status: "failed", error_message: "The analysis could not be completed for this dataset." }) });
    expect(await screen.findByRole("alert")).toHaveTextContent("The last run failed: The analysis could not be completed for this dataset.");
  });

  it("renders correlations, outliers and charts from the stored result", async () => {
    setup({ "GET /projects/p1/analysis": () => jsonResponse(200, DONE) });

    await userEvent.click(await screen.findByRole("tab", { name: "Correlations" }));
    expect(screen.getByText("Strongest positive")).toBeInTheDocument();
    expect(screen.getAllByText("0.798").length).toBeGreaterThan(0);
    expect(screen.getByText("None found")).toBeInTheDocument(); // strongest_negative is null

    await userEvent.click(screen.getByRole("tab", { name: "Outliers" }));
    const outliers = screen.getByRole("table", { name: "Outliers per numeric column" });
    expect(within(outliers).getByRole("rowheader", { name: "income" }).closest("tr")).toHaveTextContent("1.7%");
    expect(outliers).toHaveTextContent("Not checked: constant column.");

    await userEvent.click(screen.getByRole("tab", { name: "Charts" }));
    expect(screen.getByRole("img", { name: "spend vs age" })).toBeInTheDocument();
    expect(screen.getByText(/Strongest linear association/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: "Distribution of age" })).toBeInTheDocument();
  });

  it("shows empty states when correlations and charts are unavailable", async () => {
    setup({
      "GET /projects/p1/analysis": () =>
        jsonResponse(200, {
          ...DONE,
          correlations: { available: false, reason: "fewer_than_two_numeric_columns", numeric_column_count: 1, matrix: {}, pairs: [], undefined_pair_count: 0 },
          visualizations: { available: false, charts: [], chart_count: 0, reason: "no_chartable_column_combinations_found" },
        }),
    });
    await userEvent.click(await screen.findByRole("tab", { name: "Correlations" }));
    expect(screen.getByText("Correlations are not available for this dataset")).toBeInTheDocument();
    expect(screen.getByText("Fewer than two numeric columns.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("tab", { name: "Charts" }));
    expect(screen.getByText("No charts could be recommended")).toBeInTheDocument();
  });
});

describe("AnalysisWorkspace — regression", () => {
  it("only offers numeric columns, blocks incomplete input, and posts the chosen model", async () => {
    let fitted = false;
    const api = setup({
      "GET /projects/p1/analysis": () => jsonResponse(200, fitted ? { ...DONE, regression: REGRESSION } : DONE),
      "POST /projects/p1/regression": () => {
        fitted = true;
        return jsonResponse(200, { ...DONE, regression: REGRESSION, stages: { ...DONE.stages, regression: "completed" } });
      },
    });
    await userEvent.click(await screen.findByRole("tab", { name: "Regression" }));
    const select = screen.getByLabelText("Target column");
    expect(within(select).queryByRole("option", { name: "city" })).not.toBeInTheDocument();
    const fit = screen.getByRole("button", { name: "Fit regression" });
    expect(fit).toBeDisabled();

    await userEvent.selectOptions(select, "spend");
    expect(screen.queryByRole("checkbox", { name: "spend" })).not.toBeInTheDocument(); // target can't be a predictor
    expect(fit).toBeDisabled(); // no predictor yet
    await userEvent.click(screen.getByRole("checkbox", { name: "age" }));
    await userEvent.click(screen.getByRole("checkbox", { name: "income" }));
    expect(fit).toBeEnabled();
    await userEvent.click(fit);

    await waitFor(() => expect(posts(api, "/regression")).toHaveLength(1));
    expect(bodyOf(posts(api, "/regression")[0][1])).toEqual({ target: "spend", predictors: ["age", "income"] });
    const result = await screen.findByTestId("regression-result");
    expect(result).toHaveTextContent("spend ~ age + income");
    expect(within(result).getByText("0.6215")).toBeInTheDocument(); // R² straight from the API
    expect(within(result).getByRole("rowheader", { name: "Intercept" })).toBeInTheDocument();
    expect(within(result).getByText("3.40e-10")).toBeInTheDocument(); // tiny p-value, exponent form
  });

  it("shows the backend's validation message and keeps the previous model", async () => {
    setup({
      "GET /projects/p1/analysis": () => jsonResponse(200, { ...DONE, regression: REGRESSION, stages: { ...DONE.stages, regression: "completed" } }),
      "POST /projects/p1/regression": () => err(422, "regression_target_not_numeric", "Target column 'income' is not numeric. Regression requires a numeric target."),
    });
    await userEvent.click(await screen.findByRole("tab", { name: "Regression" }));
    expect(screen.getByTestId("regression-result")).toBeInTheDocument(); // persisted model shown on load
    await userEvent.selectOptions(screen.getByLabelText("Target column"), "income");
    await userEvent.click(screen.getByRole("checkbox", { name: "age" }));
    await userEvent.click(screen.getByRole("button", { name: "Fit regression" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("is not numeric");
    expect(screen.getByTestId("regression-result")).toHaveTextContent("spend ~ age + income");
  });
});

describe("Tabs", () => {
  it("supports arrow-key navigation and marks the active tab", async () => {
    setup({ "GET /projects/p1/analysis": NO_ANALYSIS });
    const cleaning = await screen.findByRole("tab", { name: "Cleaning" });
    expect(cleaning).toHaveAttribute("aria-selected", "true");
    cleaning.focus();
    await userEvent.keyboard("{ArrowRight}");
    expect(screen.getByRole("tab", { name: "Statistics" })).toHaveAttribute("aria-selected", "true");
    await userEvent.keyboard("{End}");
    // End jumps to the LAST tab (the AI analyst tab since Phase 9); Charts is one step back.
    expect(screen.getByRole("tab", { name: "AI analyst" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "analysis-tab-ai");
    await userEvent.keyboard("{ArrowLeft}");
    expect(screen.getByRole("tab", { name: "Charts" })).toHaveAttribute("aria-selected", "true");
    expect(screen.getByRole("tabpanel")).toHaveAttribute("aria-labelledby", "analysis-tab-charts");
  });
});


describe("AnalysisWorkspace — Checkpoint 5 fixes", () => {
  it("sends exactly one analyze request when Run analysis is clicked twice back to back", async () => {
    let ran = false;
    const api = setup({
      "GET /projects/p1/analysis": () => (ran ? jsonResponse(200, DONE) : NO_ANALYSIS()),
      "POST /projects/p1/analyze": () => {
        ran = true;
        return jsonResponse(200, DONE);
      },
    });
    const run = await screen.findByRole("button", { name: "Run analysis" });
    // fireEvent dispatches both clicks synchronously, before React can re-render the disabled state
    fireEvent.click(run);
    fireEvent.click(run);
    expect(await screen.findByRole("button", { name: "Re-run analysis" })).toBeInTheDocument();
    expect(posts(api, "/analyze")).toHaveLength(1);
  });

  it("allows a new run after the previous one failed (the guard is released)", async () => {
    let calls = 0;
    const api = setup({
      "GET /projects/p1/analysis": NO_ANALYSIS,
      "POST /projects/p1/analyze": () => {
        calls += 1;
        return calls === 1 ? err(500, "internal_error", "Simulated failure.") : jsonResponse(200, DONE);
      },
    });
    await userEvent.click(await screen.findByRole("button", { name: "Run analysis" }));
    expect(await screen.findByText(/Simulated failure/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Run analysis" }));
    await waitFor(() => expect(posts(api, "/analyze")).toHaveLength(2));
  });

  it("moves focus to Cancel when the re-clean warning opens, Escape closes it and focus returns", async () => {
    setup({ "GET /projects/p1/analysis": () => jsonResponse(200, DONE) });
    const trigger = await screen.findByRole("button", { name: "Re-apply cleaning" });
    await userEvent.click(trigger);
    const dialog = screen.getByRole("alertdialog", { name: "Confirm re-cleaning" });
    expect(within(dialog).getByRole("button", { name: "Cancel" })).toHaveFocus();
    await userEvent.keyboard("{Escape}");
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Re-apply cleaning" })).toHaveFocus();
  });
});
