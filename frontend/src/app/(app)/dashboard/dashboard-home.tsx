"use client";

import Link from "next/link";
import { FileSpreadsheet, FolderKanban, FileText, Plus, Sparkles } from "lucide-react";
import { StatusBadge } from "@/components/projects/status-badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { ErrorBlock, LoadingBlock } from "@/components/ui/state";
import { useCurrentUser } from "@/lib/auth";
import { formatDate, formatNumber } from "@/lib/format";
import { useDashboardSummary } from "@/lib/projects";

function Stat({ label, value, icon: Icon, hint }: { label: string; value: number; icon: typeof FolderKanban; hint?: string }) {
  return (
    <Card>
      <CardContent className="flex items-start justify-between gap-3 p-5">
        <div>
          <p className="text-sm text-muted-foreground">{label}</p>
          <p className="mt-1 text-3xl font-semibold tabular-nums" data-testid={`stat-${label}`}>
            {formatNumber(value)}
          </p>
          {hint ? <p className="mt-1 text-xs text-muted-foreground">{hint}</p> : null}
        </div>
        <Icon className="h-5 w-5 text-muted-foreground" aria-hidden />
      </CardContent>
    </Card>
  );
}

export function DashboardHome() {
  const { data: user } = useCurrentUser();
  const summary = useDashboardSummary();
  const name = user?.full_name?.trim().split(" ")[0];

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">{name ? `Welcome, ${name}` : "Welcome"}</h1>
          <p className="text-sm text-muted-foreground">Turn Your Data Into Decisions.</p>
        </div>
        <Button asChild>
          <Link href="/projects/new">
            <Plus className="h-4 w-4" aria-hidden />
            New project
          </Link>
        </Button>
      </div>

      {summary.isPending ? <LoadingBlock label="Loading dashboard" /> : null}
      {summary.isError ? <ErrorBlock message={summary.error.message} onRetry={() => summary.refetch()} /> : null}

      {summary.data ? (
        <>
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label="Projects" value={summary.data.total_projects} icon={FolderKanban} />
            <Stat label="Files analyzed" value={summary.data.files_analyzed} icon={FileSpreadsheet} />
            <Stat label="Reports" value={summary.data.reports_generated} icon={FileText} hint="PDF reports are not available yet" />
            <Stat label="AI insights" value={summary.data.ai_insights_generated} icon={Sparkles} hint="AI insights are not available yet" />
          </div>

          <Card>
            <CardHeader>
              <CardTitle>Recent projects</CardTitle>
              <CardDescription>Your most recently updated projects.</CardDescription>
            </CardHeader>
            <CardContent>
              {summary.data.recent_projects.length === 0 ? (
                <div className="flex flex-col items-center gap-3 py-8 text-center">
                  <p className="text-sm text-muted-foreground">No projects yet. Create one and upload a CSV or Excel file.</p>
                  <Button asChild variant="outline">
                    <Link href="/projects/new">Create your first project</Link>
                  </Button>
                </div>
              ) : (
                <ul className="divide-y divide-border">
                  {summary.data.recent_projects.map((p) => (
                    <li key={p.id}>
                      <Link href={`/projects/${p.id}`} className="flex items-center justify-between gap-3 py-3 hover:bg-muted/50">
                        <span className="min-w-0">
                          <span className="block truncate font-medium">{p.name}</span>
                          <span className="block text-xs text-muted-foreground">Updated {formatDate(p.updated_at)}</span>
                        </span>
                        <StatusBadge status={p.status} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </CardContent>
          </Card>
        </>
      ) : null}
    </div>
  );
}
