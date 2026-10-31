"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import { StatusBadge } from "@/components/projects/status-badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { ErrorBlock, LoadingBlock } from "@/components/ui/state";
import { formatDate } from "@/lib/format";
import { useProjects } from "@/lib/projects";

export function ProjectsList() {
  const projects = useProjects();

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
        <Button asChild>
          <Link href="/projects/new">
            <Plus className="h-4 w-4" aria-hidden />
            New project
          </Link>
        </Button>
      </div>

      {projects.isPending ? <LoadingBlock label="Loading projects" /> : null}
      {projects.isError ? <ErrorBlock message={projects.error.message} onRetry={() => projects.refetch()} /> : null}

      {projects.data && projects.data.length === 0 ? (
        <Card className="flex flex-col items-center gap-3 p-10 text-center">
          <p className="font-medium">No projects yet</p>
          <p className="text-sm text-muted-foreground">Each project holds one CSV or Excel file and its analysis.</p>
          <Button asChild>
            <Link href="/projects/new">Create a project</Link>
          </Button>
        </Card>
      ) : null}

      {projects.data && projects.data.length > 0 ? (
        <Card>
          <ul className="divide-y divide-border">
            {projects.data.map((p) => (
              <li key={p.id}>
                <Link href={`/projects/${p.id}`} className="flex items-center justify-between gap-3 px-5 py-4 hover:bg-muted/50">
                  <span className="min-w-0">
                    <span className="block truncate font-medium">{p.name}</span>
                    <span className="block text-xs text-muted-foreground">
                      Created {formatDate(p.created_at)} · Updated {formatDate(p.updated_at)}
                    </span>
                  </span>
                  <StatusBadge status={p.status} />
                </Link>
              </li>
            ))}
          </ul>
        </Card>
      ) : null}
    </div>
  );
}
