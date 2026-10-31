"use client";

import { useRef, useState } from "react";
import { Loader2, Play } from "lucide-react";
import { AiTab } from "@/components/analysis/ai-tab";
import { ChartsTab } from "@/components/analysis/charts-tab";
import { CleaningPanel } from "@/components/analysis/cleaning-panel";
import { CorrelationsTab } from "@/components/analysis/correlations-tab";
import { OutliersTab } from "@/components/analysis/outliers-tab";
import { RegressionTab } from "@/components/analysis/regression-tab";
import { StageStrip } from "@/components/analysis/stage-strip";
import { StatisticsTab } from "@/components/analysis/statistics-tab";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyBlock, ErrorBlock, LoadingBlock } from "@/components/ui/state";
import { Tabs, type TabItem } from "@/components/ui/tabs";
import { describeAnalysisError } from "@/lib/analysis-errors";
import { formatDate } from "@/lib/format";
import { useAnalysis, useAnalyzeProject, useCleanProject, useRunRegression } from "@/lib/projects";
import type { DatasetProfile, StageName, StageState } from "@/lib/schemas";

type TabId = "cleaning" | "statistics" | "correlations" | "outliers" | "regression" | "charts" | "ai";
const TABS: TabItem<TabId>[] = [
  { id: "cleaning", label: "Cleaning" },
  { id: "statistics", label: "Statistics" },
  { id: "correlations", label: "Correlations" },
  { id: "outliers", label: "Outliers" },
  { id: "regression", label: "Regression" },
  { id: "charts", label: "Charts" },
  { id: "ai", label: "AI analyst" },
];

const STAGE_FOR_TAB: Partial<Record<TabId, StageName>> = {
  statistics: "statistics",
  correlations: "correlations",
  outliers: "outliers",
  charts: "visualizations",
};

export function AnalysisWorkspace({ projectId, profile }: { projectId: string; profile: DatasetProfile | undefined }) {
  const [tab, setTab] = useState<TabId>("cleaning");
  const analysisQuery = useAnalysis(projectId, true);
  const clean = useCleanProject(projectId);
  const analyze = useAnalyzeProject(projectId);
  const regression = useRunRegression(projectId);
  const busy = clean.isPending || analyze.isPending || regression.isPending;
  // `busy` only turns true after React re-renders, so two clicks that arrive back to back (a fast
  // double-click) could both start a request. This ref closes that gap: one action at a time.
  const inFlight = useRef(false);
  function once(start: (done: () => void) => void) {
    if (inFlight.current) return;
    inFlight.current = true;
    start(() => {
      inFlight.current = false;
    });
  }

  if (analysisQuery.isPending) return <LoadingBlock label="Loading analysis" />;
  if (analysisQuery.isError) {
    return <ErrorBlock message={describeAnalysisError(analysisQuery.error)} onRetry={() => analysisQuery.refetch()} />;
  }

  const analysis = analysisQuery.data;
  // Before any run there is no analysis row; the upload itself did profile the file.
  const stages: Partial<Record<StageName, StageState>> = {
    ...(profile ? { profiling: "completed" as const } : {}),
    ...(analysis?.stages ?? {}),
  };
  const analysisDone = analysis?.status === "completed";
  const lastRunFailed = analysis?.status === "failed";

  function stagePanel(id: TabId) {
    const stageName = STAGE_FOR_TAB[id];
    const state = stageName ? analysis?.stages[stageName] : undefined;
    if (state === "failed") {
      return <EmptyBlock title="This step failed" hint={analysis?.error_message ?? "It could not be computed for this dataset."} />;
    }
    if (!analysis || state !== "completed") {
      return (
        <EmptyBlock
          title="No results yet"
          hint={analysis?.cleaning ? "Cleaning is saved. Choose Run analysis to calculate this." : "Choose Run analysis to calculate this from your data."}
        />
      );
    }
    switch (id) {
      case "statistics":
        return analysis.statistics ? <StatisticsTab statistics={analysis.statistics} /> : <EmptyBlock title="No statistics were returned" />;
      case "correlations":
        return analysis.correlations ? <CorrelationsTab result={analysis.correlations} /> : <EmptyBlock title="Correlations could not be computed for this dataset" />;
      case "outliers":
        return analysis.outliers ? <OutliersTab result={analysis.outliers} /> : <EmptyBlock title="Outliers could not be computed for this dataset" />;
      case "charts":
        return analysis.visualizations ? (
          <ChartsTab charts={analysis.visualizations.charts} available={analysis.visualizations.available} reason={analysis.visualizations.reason} />
        ) : (
          <EmptyBlock title="No charts were returned" />
        );
      default:
        return null;
    }
  }

  return (
    <div className="flex flex-col gap-4">
      <Card>
        <CardHeader>
          <CardTitle>Cleaning &amp; analysis</CardTitle>
          <CardDescription>
            Everything below is calculated on the server from your uploaded file and saved with this project.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <StageStrip stages={stages} />
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={() => once((done) => analyze.mutate(undefined, { onSettled: done }))} disabled={busy}>
              {analyze.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <Play className="h-4 w-4" aria-hidden />}
              {analysis?.stages.statistics === "completed" ? "Re-run analysis" : "Run analysis"}
            </Button>
            {analyze.isPending ? (
              <p role="status" className="text-sm text-muted-foreground">Running analysis… this can take a few seconds for larger files.</p>
            ) : analysisDone && analysis?.completed_at ? (
              <p role="status" className="text-sm text-muted-foreground">Analysis completed {formatDate(analysis.completed_at)}.</p>
            ) : null}
          </div>
          {analyze.isError ? (
            <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              {describeAnalysisError(analyze.error)}
            </p>
          ) : null}
          {lastRunFailed && !analyze.isError ? (
            <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
              The last run failed{analysis?.error_message ? `: ${analysis.error_message}` : "."} You can adjust the cleaning settings and run it again.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Tabs tabs={TABS} value={tab} onChange={setTab} label="Analysis sections" idPrefix="analysis" />
      <div role="tabpanel" id={`analysis-panel-${tab}`} aria-labelledby={`analysis-tab-${tab}`} tabIndex={0} className="focus-visible:outline-none">
        {tab === "cleaning" ? (
          <CleaningPanel
            key={JSON.stringify(analysis?.cleaning?.config ?? null)}
            analysis={analysis}
            profile={profile}
            onApply={(config) => once((done) => clean.mutate(config, { onSettled: done }))}
            isPending={clean.isPending}
            error={clean.error}
            busy={busy}
          />
        ) : tab === "regression" ? (
          <RegressionTab
            analysis={analysis}
            profile={profile}
            onRun={(input) => once((done) => regression.mutate(input, { onSettled: done }))}
            isPending={regression.isPending}
            error={regression.error}
            busy={busy}
          />
        ) : tab === "ai" ? (
          <AiTab projectId={projectId} analysis={analysis} />
        ) : (
          stagePanel(tab)
        )}
      </div>
    </div>
  );
}
