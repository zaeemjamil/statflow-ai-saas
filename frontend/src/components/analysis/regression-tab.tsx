"use client";

import { useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyBlock } from "@/components/ui/state";
import { describeAnalysisError } from "@/lib/analysis-errors";
import { formatNumber, formatStat, humanizeCode } from "@/lib/format";
import type { Analysis, DatasetProfile, RegressionInput, RegressionResult } from "@/lib/schemas";

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-border p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-xl font-semibold tabular-nums">{value}</p>
    </div>
  );
}

function RegressionResultView({ result }: { result: RegressionResult }) {
  if (!result.available || !result.model || !result.metrics) {
    return (
      <EmptyBlock
        title="The regression could not be fitted"
        hint={result.message ?? (result.reason ? humanizeCode(result.reason) + "." : undefined)}
      />
    );
  }
  const { model, metrics } = result;
  return (
    <div className="flex flex-col gap-6" data-testid="regression-result">
      <div>
        <h3 className="text-sm font-semibold">
          {model.target} ~ {model.predictors.join(" + ")}
        </h3>
        <p className="text-xs text-muted-foreground">
          Ordinary least squares. {formatNumber(model.observations_used)} of {formatNumber(model.observations_total)} rows used
          {model.rows_dropped_for_missing_values > 0 ? ` (${formatNumber(model.rows_dropped_for_missing_values)} dropped for missing values)` : ""}; {formatNumber(model.train_observations)} for fitting, {formatNumber(model.test_observations)} held out for testing (test size {formatStat(model.test_size)}, seed {model.random_seed}).
        </p>
      </div>

      <div>
        <p className="mb-2 text-xs font-medium text-muted-foreground">Fit on the training rows</p>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="R²" value={formatStat(metrics.r_squared)} />
          <Stat label="Adjusted R²" value={formatStat(metrics.adjusted_r_squared)} />
          <Stat label="F statistic" value={formatStat(metrics.f_statistic)} />
          <Stat label="F p-value" value={formatStat(metrics.f_p_value)} />
        </div>
      </div>
      <div>
        <p className="mb-2 text-xs font-medium text-muted-foreground">Error on the held-out test rows</p>
        <div className="grid grid-cols-2 gap-3">
          <Stat label="MAE" value={formatStat(metrics.mae)} />
          <Stat label="RMSE" value={formatStat(metrics.rmse)} />
        </div>
      </div>

      <div className="overflow-x-auto rounded-lg border border-border">
        <table className="w-full min-w-[40rem] text-left text-sm">
          <caption className="sr-only">Regression coefficients</caption>
          <thead className="bg-muted text-xs text-muted-foreground">
            <tr>
              <th scope="col" className="px-3 py-2 font-medium">Term</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Coefficient</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">Std error</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">t</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">p-value</th>
              <th scope="col" className="px-3 py-2 text-right font-medium">95% CI</th>
              <th scope="col" className="px-3 py-2 font-medium">Significant (p &lt; 0.05)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            <tr>
              <th scope="row" className="px-3 py-2 font-medium">Intercept</th>
              <td className="px-3 py-2 text-right tabular-nums">{formatStat(model.intercept)}</td>
              <td colSpan={5} className="px-3 py-2 text-muted-foreground" />
            </tr>
            {result.coefficients.map((c) => (
              <tr key={c.name}>
                <th scope="row" className="px-3 py-2 font-medium">{c.name}</th>
                <td className="px-3 py-2 text-right tabular-nums">{formatStat(c.coefficient)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{formatStat(c.std_error)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{formatStat(c.t_statistic)}</td>
                <td className="px-3 py-2 text-right tabular-nums">{formatStat(c.p_value)}</td>
                <td className="px-3 py-2 text-right tabular-nums">
                  {formatStat(c.conf_int_lower)} to {formatStat(c.conf_int_upper)}
                </td>
                <td className="px-3 py-2">{c.significant_at_05 ? "Yes" : "No"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {Object.keys(result.residual_summary).length > 0 ? (
        <p className="text-xs text-muted-foreground">
          Test residuals — {Object.entries(result.residual_summary).map(([k, v]) => `${k}: ${formatStat(v)}`).join(" · ")}
        </p>
      ) : null}

      {result.sample_predictions.length > 0 ? (
        <div className="flex flex-col gap-2">
          <h3 className="text-sm font-semibold">Sample predictions (held-out rows)</h3>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[24rem] text-left text-sm">
              <caption className="sr-only">Sample predictions</caption>
              <thead className="bg-muted text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Actual</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Predicted</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">Residual</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {result.sample_predictions.map((p, i) => (
                  <tr key={i}>
                    <td className="px-3 py-2 text-right tabular-nums">{formatStat(p.actual)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatStat(p.predicted)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatStat(p.residual)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ) : null}
    </div>
  );
}

export function RegressionTab({
  analysis,
  profile,
  onRun,
  isPending,
  error,
  busy,
}: {
  analysis: Analysis | null | undefined;
  profile: DatasetProfile | null | undefined;
  onRun: (input: RegressionInput) => void;
  isPending: boolean;
  error: unknown;
  busy: boolean;
}) {
  const [target, setTarget] = useState("");
  const [predictors, setPredictors] = useState<string[]>([]);

  if (!analysis || analysis.status !== "completed") {
    return <EmptyBlock title="Run the analysis first" hint="A regression is fitted on the cleaned data, so the analysis must complete before you can choose a target and predictors." />;
  }

  const columnSource = analysis.cleaned_profile ?? profile ?? analysis.profile;
  const numeric = (columnSource?.columns ?? []).filter((c) => c.classification === "numeric").map((c) => c.name);

  if (numeric.length < 2) {
    return <EmptyBlock title="Not enough numeric columns" hint="Regression needs one numeric target and at least one other numeric predictor column." />;
  }

  const available = numeric.filter((n) => n !== target);
  const chosen = predictors.filter((p) => p !== target);
  const canRun = target !== "" && chosen.length > 0 && !busy;

  function toggle(name: string) {
    setPredictors((prev) => (prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name]));
  }

  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Regression</CardTitle>
          <CardDescription>Fit a linear (OLS) model: choose the numeric column to predict and the numeric columns to predict it from.</CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="flex flex-col gap-1.5">
            <label htmlFor="reg-target" className="text-sm font-medium">Target column</label>
            <select
              id="reg-target"
              value={target}
              disabled={busy}
              onChange={(e) => setTarget(e.target.value)}
              className="h-10 w-full max-w-sm rounded-md border border-border bg-background px-3 text-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            >
              <option value="">Select a numeric column…</option>
              {numeric.map((n) => (
                <option key={n} value={n}>{n}</option>
              ))}
            </select>
          </div>

          <fieldset className="flex flex-col gap-2" disabled={busy || target === ""}>
            <legend className="mb-1 text-sm font-medium">Predictor columns</legend>
            {target === "" ? <p className="text-xs text-muted-foreground">Choose a target first.</p> : null}
            <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {available.map((n) => (
                <label key={n} className="flex cursor-pointer items-center gap-2 rounded-md border border-border p-2 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/5">
                  <input type="checkbox" checked={chosen.includes(n)} onChange={() => toggle(n)} />
                  <span className="truncate">{n}</span>
                </label>
              ))}
            </div>
          </fieldset>

          <div className="flex flex-wrap items-center gap-3">
            <Button disabled={!canRun} onClick={() => onRun({ target, predictors: chosen })}>
              {isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              Fit regression
            </Button>
            {isPending ? <p role="status" className="text-sm text-muted-foreground">Fitting regression…</p> : null}
            {!isPending && !canRun && !busy ? <p className="text-xs text-muted-foreground">Select a target and at least one predictor.</p> : null}
          </div>

          {error ? (
            <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {describeAnalysisError(error)}
            </p>
          ) : null}
        </CardContent>
      </Card>

      {analysis.regression ? (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Last fitted model</CardTitle>
            <CardDescription>Saved with this project. A rejected request never overwrites it.</CardDescription>
          </CardHeader>
          <CardContent>
            <RegressionResultView result={analysis.regression} />
          </CardContent>
        </Card>
      ) : (
        <EmptyBlock title="No regression fitted yet" hint="Pick a target and predictors above, then choose Fit regression." />
      )}
    </div>
  );
}
