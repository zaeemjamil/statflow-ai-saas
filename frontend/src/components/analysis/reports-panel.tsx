"use client";

import { Download, FileText, Loader2, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { LoadingBlock } from "@/components/ui/state";
import { describeAnalysisError } from "@/lib/analysis-errors";
import { formatDate } from "@/lib/format";
import { useAnalysis, useCreateReport, useDeleteReport, useReports } from "@/lib/projects";

export function ReportsPanel({ projectId }: { projectId: string }) {
  const analysis = useAnalysis(projectId, true);
  const ready = analysis.data?.status === "completed" && analysis.data.stages.statistics === "completed";
  const reports = useReports(projectId, ready);
  const create = useCreateReport(projectId);
  const remove = useDeleteReport(projectId);

  if (analysis.isPending) return <LoadingBlock label="Loading reports" />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>PDF reports</CardTitle>
        <CardDescription>
          A downloadable summary of the saved analysis (cleaning, statistics, correlations, outliers, regression, charts
          and, if you generated one, the AI explanation). The numbers are the same ones shown above.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={() => create.mutate()} disabled={!ready || create.isPending}>
            {create.isPending ? <Loader2 className="h-4 w-4 animate-spin" aria-hidden /> : <FileText className="h-4 w-4" aria-hidden />}
            Create PDF report
          </Button>
          {!ready ? <p className="text-sm text-muted-foreground">Reports become available once the analysis has finished.</p> : null}
          {create.isPending ? (
            <p role="status" className="text-sm text-muted-foreground">Creating the report…</p>
          ) : null}
        </div>
        {create.isError ? (
          <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {describeAnalysisError(create.error)}
          </p>
        ) : null}
        {remove.isError ? (
          <p role="alert" className="rounded-md border border-destructive/40 bg-destructive/10 px-3 py-2 text-sm text-destructive">
            {describeAnalysisError(remove.error)}
          </p>
        ) : null}
        {ready && reports.isPending ? <LoadingBlock label="Loading report list" /> : null}
        {ready && reports.isError ? (
          <p role="alert" className="text-sm text-destructive">{describeAnalysisError(reports.error)}</p>
        ) : null}
        {reports.data && reports.data.length > 0 ? (
          <ul className="divide-y divide-border rounded-md border border-border" aria-label="Created reports">
            {reports.data.map((report) => (
              <li key={report.id} className="flex flex-wrap items-center justify-between gap-3 px-3 py-2">
                <div className="min-w-0">
                  <p className="truncate text-sm font-medium">{report.file_name ?? "report.pdf"}</p>
                  <p className="text-xs text-muted-foreground">Created {formatDate(report.generated_at)}</p>
                </div>
                <div className="flex items-center gap-2">
                  <Button asChild variant="outline" size="sm">
                    <a href={`/api/v1/projects/${projectId}/reports/${report.id}/download`} download>
                      <Download className="h-4 w-4" aria-hidden />
                      Download
                    </a>
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Delete ${report.file_name ?? "report"}`}
                    onClick={() => remove.mutate(report.id)}
                    disabled={remove.isPending}
                  >
                    <Trash2 className="h-4 w-4" aria-hidden />
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        ) : null}
        {ready && reports.data && reports.data.length === 0 ? (
          <p className="text-sm text-muted-foreground">No reports yet.</p>
        ) : null}
      </CardContent>
    </Card>
  );
}
