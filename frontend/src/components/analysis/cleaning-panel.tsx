"use client";

import { useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { describeAnalysisError } from "@/lib/analysis-errors";
import { formatNumber, formatStat, humanizeCode } from "@/lib/format";
import type { Analysis, CleaningConfig, CleaningReport, DatasetProfile } from "@/lib/schemas";

export const DEFAULT_CLEANING: CleaningConfig = { numeric_strategy: "median", categorical_strategy: "mode", duplicate_strategy: "keep" };

type Option<V extends string> = { value: V; label: string; hint: string };
const NUMERIC: Option<CleaningConfig["numeric_strategy"]>[] = [
  { value: "median", label: "Fill with the median", hint: "Each missing number is replaced by its column's median." },
  { value: "unchanged", label: "Leave as is", hint: "Missing numbers stay missing." },
];
const CATEGORICAL: Option<CleaningConfig["categorical_strategy"]>[] = [
  { value: "mode", label: "Fill with the most common value", hint: "Each missing category is replaced by its column's most frequent value." },
  { value: "unchanged", label: "Leave as is", hint: "Missing categories stay missing." },
];
const DUPLICATES: Option<CleaningConfig["duplicate_strategy"]>[] = [
  { value: "keep", label: "Keep all rows", hint: "Repeated rows can be genuine repeated measurements, so they are kept by default." },
  { value: "remove", label: "Remove duplicate rows", hint: "Exact duplicate rows are dropped." },
];

function RadioGroup<V extends string>({
  legend,
  name,
  options,
  value,
  onChange,
  disabled,
}: {
  legend: string;
  name: string;
  options: Option<V>[];
  value: V;
  onChange: (v: V) => void;
  disabled: boolean;
}) {
  return (
    <fieldset className="flex flex-col gap-2" disabled={disabled}>
      <legend className="mb-1 text-sm font-medium">{legend}</legend>
      {options.map((o) => (
        <label key={o.value} className="flex cursor-pointer items-start gap-2 rounded-md border border-border p-3 text-sm has-[:checked]:border-primary has-[:checked]:bg-primary/5">
          <input type="radio" name={name} value={o.value} checked={value === o.value} onChange={() => onChange(o.value)} className="mt-0.5" />
          <span>
            <span className="block font-medium">{o.label}</span>
            <span className="block text-xs text-muted-foreground">{o.hint}</span>
          </span>
        </label>
      ))}
    </fieldset>
  );
}

/** Which already-computed results a re-clean would delete (the backend wipes them all). */
export function resultsThatWouldBeErased(analysis: Analysis | null | undefined): string[] {
  if (!analysis) return [];
  const s = analysis.stages;
  const out: string[] = [];
  if (s.statistics === "completed") out.push("statistics");
  if (s.correlations === "completed") out.push("correlations");
  if (s.outliers === "completed") out.push("outliers");
  if (analysis.regression || s.regression === "completed") out.push("the regression model");
  if (s.visualizations === "completed") out.push("charts");
  return out;
}

const REASONS: Record<string, string> = {
  strategy_unchanged: "Left unchanged by your choice",
  no_non_missing_values: "No non-missing values to calculate a fill value from",
};

function Pair({ label, before, after }: { label: string; before: number; after: number }) {
  return (
    <div className="rounded-lg border border-border p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">
        {formatNumber(before)} <span className="text-muted-foreground">→</span> {formatNumber(after)}
      </p>
    </div>
  );
}

function CleaningReportView({ report }: { report: CleaningReport }) {
  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
        <Pair label="Rows (before → after)" before={report.rows_before} after={report.rows_after} />
        <Pair label="Missing values (before → after)" before={report.missing_before} after={report.missing_after} />
        <Pair label="Duplicate rows (before → after)" before={report.duplicates_before} after={report.duplicates_after} />
      </div>
      <p className="text-sm text-muted-foreground">
        {formatNumber(report.missing_values_imputed)} missing value(s) filled · {formatNumber(report.duplicates_removed)} duplicate row(s) removed ·{" "}
        {formatNumber(report.rows_removed)} row(s) removed in total.
      </p>
      {report.column_actions.length === 0 ? (
        <p className="text-sm text-muted-foreground">No columns needed cleaning.</p>
      ) : (
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <caption className="sr-only">Per-column cleaning actions</caption>
            <thead className="bg-muted text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Column</th>
                <th scope="col" className="px-3 py-2 font-medium">Action</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Fill value</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Missing</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Values changed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {report.column_actions.map((a) => (
                <tr key={a.column}>
                  <th scope="row" className="px-3 py-2 font-medium">{a.column}</th>
                  <td className="px-3 py-2">
                    {a.action === "imputed" ? `Filled (${a.method ?? "—"})` : (a.reason ? (REASONS[a.reason] ?? humanizeCode(a.reason)) : "Left unchanged")}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {a.fill_value == null ? "—" : typeof a.fill_value === "number" ? formatStat(a.fill_value) : a.fill_value}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatNumber(a.missing_before)} → {formatNumber(a.missing_after)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatNumber(a.values_changed)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

export function CleaningPanel({
  analysis,
  profile,
  onApply,
  isPending,
  error,
  busy,
}: {
  analysis: Analysis | null | undefined;
  profile: DatasetProfile | undefined;
  onApply: (config: CleaningConfig) => void;
  isPending: boolean;
  error: unknown;
  busy: boolean;
}) {
  const applied = analysis?.cleaning?.config as CleaningConfig | undefined;
  const [draft, setDraft] = useState<CleaningConfig>({ ...DEFAULT_CLEANING, ...applied });
  const [confirming, setConfirming] = useState(false);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const triggerRef = useRef<HTMLButtonElement>(null);
  const returnFocus = useRef(false);
  // The confirmation is rendered inline (not a modal), so keyboard users need focus moved onto it
  // (the safe choice, Cancel, first) and handed back to the button they came from when they back out.
  useEffect(() => {
    if (confirming) cancelRef.current?.focus();
    else if (returnFocus.current) {
      returnFocus.current = false;
      triggerRef.current?.focus();
    }
  }, [confirming]);
  function cancelConfirm() {
    returnFocus.current = true;
    setConfirming(false);
  }
  const erased = resultsThatWouldBeErased(analysis);

  function submit() {
    if (erased.length > 0 && !confirming) {
      setConfirming(true);
      return;
    }
    setConfirming(false);
    onApply(draft);
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Data cleaning</CardTitle>
        <CardDescription>
          Choose how missing values and duplicate rows are handled. Cleaning works on a copy; your uploaded file is never modified.
          {" "}Analysis uses the last settings you applied (or the defaults below if you never applied any).
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-5">
        {profile ? (
          <p className="text-sm text-muted-foreground">
            Your file currently has {formatNumber(profile.total_missing_values)} missing value(s) and {formatNumber(profile.duplicate_row_count)} duplicate row(s).
          </p>
        ) : null}

        <div className="grid grid-cols-1 gap-5 lg:grid-cols-3">
          <RadioGroup legend="Missing numbers" name="numeric_strategy" options={NUMERIC} value={draft.numeric_strategy} disabled={busy} onChange={(v) => { setConfirming(false); setDraft({ ...draft, numeric_strategy: v }); }} />
          <RadioGroup legend="Missing categories" name="categorical_strategy" options={CATEGORICAL} value={draft.categorical_strategy} disabled={busy} onChange={(v) => { setConfirming(false); setDraft({ ...draft, categorical_strategy: v }); }} />
          <RadioGroup legend="Duplicate rows" name="duplicate_strategy" options={DUPLICATES} value={draft.duplicate_strategy} disabled={busy} onChange={(v) => { setConfirming(false); setDraft({ ...draft, duplicate_strategy: v }); }} />
        </div>

        {confirming ? (
          <div
            role="alertdialog"
            aria-label="Confirm re-cleaning"
            onKeyDown={(e) => {
              if (e.key === "Escape") {
                e.stopPropagation();
                cancelConfirm();
              }
            }}
            className="flex flex-col gap-3 rounded-lg border border-amber-500/50 bg-amber-500/10 p-4 text-sm">
            <p>
              <strong>Re-cleaning will erase your existing results:</strong> {erased.join(", ")}. They were computed from the previous cleaning
              and can&apos;t be kept alongside the new one. You&apos;ll need to run the analysis (and any regression) again.
            </p>
            <div className="flex flex-wrap gap-2">
              <Button size="sm" onClick={submit} disabled={busy}>Erase results and re-clean</Button>
              <Button ref={cancelRef} size="sm" variant="ghost" onClick={cancelConfirm}>Cancel</Button>
            </div>
          </div>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <Button ref={triggerRef} onClick={submit} disabled={busy}>
              {isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : null}
              {analysis?.cleaning ? "Re-apply cleaning" : "Apply cleaning"}
            </Button>
            {isPending ? <p role="status" className="text-sm text-muted-foreground">Applying cleaning…</p> : null}
          </div>
        )}

        {error ? (
          <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {describeAnalysisError(error)}
          </p>
        ) : null}

        {analysis?.cleaning ? (
          <div className="flex flex-col gap-3 border-t border-border pt-5">
            <h3 className="text-sm font-semibold">Cleaning report</h3>
            <p className="text-xs text-muted-foreground">
              Settings in effect: missing numbers → {analysis.cleaning.config.numeric_strategy}; missing categories → {analysis.cleaning.config.categorical_strategy}; duplicates → {analysis.cleaning.config.duplicate_strategy}.
            </p>
            <CleaningReportView report={analysis.cleaning} />
          </div>
        ) : (
          <p className="border-t border-border pt-5 text-sm text-muted-foreground">No cleaning has been applied yet.</p>
        )}
      </CardContent>
    </Card>
  );
}
