"use client";

import { Loader2, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "@/components/ui/state";
import { describeAnalysisError } from "@/lib/analysis-errors";
import { formatDate } from "@/lib/format";
import { useAiInsights, useGenerateAiInsights } from "@/lib/projects";
import type { AiInsight, Analysis } from "@/lib/schemas";

const WARNING_TEXT: Record<string, string> = {
  small_sample:
    "Small sample: with fewer than 30 rows, treat any pattern as a hint to check, not as a conclusion.",
};

function Section({ title, items }: { title: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <section>
      <h3 className="mb-1 text-sm font-semibold">{title}</h3>
      <ul className="list-disc space-y-1 pl-5 text-sm">
        {items.map((item, i) => (
          // The text comes from an AI model: rendered as plain text only, never as HTML.
          <li key={i}>{item}</li>
        ))}
      </ul>
    </section>
  );
}

function InsightView({ insight }: { insight: AiInsight }) {
  return (
    <div className="flex flex-col gap-4">
      {insight.evidence_warnings.map((code) => (
        <p key={code} className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
          {WARNING_TEXT[code] ?? "The analysis carries a data-quality warning. Interpret with care."}
        </p>
      ))}
      <section>
        <h3 className="mb-1 text-sm font-semibold">Summary</h3>
        <p className="text-sm">{insight.summary}</p>
      </section>
      <Section title="Key findings" items={insight.key_findings} />
      <Section title="Data quality" items={insight.data_quality} />
      <Section title="Limitations" items={insight.limitations} />
      <Section title="Things you could check next" items={insight.next_steps} />
      <p className="text-xs text-muted-foreground">
        Generated {formatDate(insight.generated_at)} by {insight.model}.
      </p>
    </div>
  );
}

export function AiTab({ projectId, analysis }: { projectId: string; analysis: Analysis | null | undefined }) {
  const ready = analysis?.status === "completed" && analysis.stages.statistics === "completed";
  const query = useAiInsights(projectId, ready);
  const generate = useGenerateAiInsights(projectId);

  if (!ready) {
    return <EmptyBlock title="Run the analysis first" hint="The AI analyst explains the results of a completed analysis." />;
  }
  if (query.isPending) return <LoadingBlock label="Loading AI analyst" />;
  if (query.isError) return <ErrorBlock message={describeAnalysisError(query.error)} onRetry={() => query.refetch()} />;

  const state = query.data;
  if (!state.configured) {
    return (
      <EmptyBlock
        title="AI explanations are not turned on"
        hint="The site administrator needs to add an AI provider key to the server. Everything else works without it."
      />
    );
  }
  if (!state.eligible) {
    return <EmptyBlock title="Not enough data to explain" hint={state.message ?? "This analysis cannot be explained yet."} />;
  }

  const limitReached = state.remaining_today <= 0;
  return (
    <Card>
      <CardHeader>
        <CardTitle>AI analyst</CardTitle>
        <CardDescription>
          A plain-language explanation of the results above. What is sent to the AI service: anonymous column labels
          like “Column_001” and summary numbers (counts, averages, medians, quartiles, correlations and model
          results). Not sent: your column names, file name, individual rows, or the exact smallest and largest value
          of any column. A summary number such as a median can occasionally equal one of your values.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        {state.warnings.map((code) => (
          <p key={code} className="rounded-md border border-amber-500/40 bg-amber-500/10 px-3 py-2 text-sm">
            {WARNING_TEXT[code] ?? "The analysis carries a data-quality warning. Interpret with care."}
          </p>
        ))}
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => generate.mutate()} disabled={generate.isPending || limitReached}>
            {generate.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Sparkles className="h-4 w-4" aria-hidden />}
            {state.insight ? "Regenerate explanation" : "Generate explanation"}
          </Button>
          <p className="text-sm text-muted-foreground">
            {limitReached ? "Daily limit reached. Try again tomorrow." : `${state.remaining_today} left today.`}
          </p>
        </div>
        {generate.isPending ? (
          <p role="status" className="text-sm text-muted-foreground">Asking the AI analyst… this usually takes 5–20 seconds.</p>
        ) : null}
        {generate.isError ? (
          <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {describeAnalysisError(generate.error)}
          </p>
        ) : null}
        {state.has_outdated_insight && !state.insight ? (
          <p role="status" className="rounded-md border border-border bg-muted px-3 py-2 text-sm">
            The results changed since the last explanation, so it was removed. Generate a new one.
          </p>
        ) : null}
        {state.insight ? <InsightView insight={state.insight} /> : null}
        <p className="border-t border-border pt-3 text-xs text-muted-foreground">{state.disclaimer}</p>
      </CardContent>
    </Card>
  );
}
