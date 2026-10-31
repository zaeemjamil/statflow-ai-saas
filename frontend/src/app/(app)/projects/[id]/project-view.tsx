"use client";

import Link from "next/link";
import { use } from "react";
import { ArrowLeft, FileSpreadsheet } from "lucide-react";
import { AnalysisWorkspace } from "@/components/analysis/analysis-workspace";
import { ReportsPanel } from "@/components/analysis/reports-panel";
import { ProfileView } from "@/components/projects/profile-view";
import { ProjectHeader } from "@/components/projects/project-header";
import { UploadDropzone } from "@/components/projects/upload-dropzone";
import { Card, CardContent } from "@/components/ui/card";
import { ErrorBlock, LoadingBlock } from "@/components/ui/state";
import { ApiError } from "@/lib/api";
import { formatBytes, formatDate, formatNumber } from "@/lib/format";
import { useProfile, useProject, useProjectFile } from "@/lib/projects";

export function ProjectView({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const project = useProject(id);
  const file = useProjectFile(id);
  const hasFile = !!file.data;
  const profile = useProfile(id, hasFile);

  const back = (
    <Link href="/projects" className="inline-flex items-center gap-1 text-sm text-muted-foreground hover:text-foreground">
      <ArrowLeft className="h-4 w-4" aria-hidden />
      All projects
    </Link>
  );

  if (project.isPending || file.isPending) return <LoadingBlock label="Loading project" />;

  if (project.isError) {
    const notFound = project.error instanceof ApiError && project.error.status === 404;
    return (
      <div className="mx-auto flex max-w-5xl flex-col gap-4">
        {back}
        {notFound ? (
          <ErrorBlock message="This project doesn't exist or you don't have access to it." />
        ) : (
          <ErrorBlock message={project.error.message} onRetry={() => project.refetch()} />
        )}
      </div>
    );
  }

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      {back}
      <ProjectHeader key={project.data.updated_at} project={project.data} />

      {file.isError ? <ErrorBlock message={file.error.message} onRetry={() => file.refetch()} /> : null}

      {!hasFile && !file.isError ? <UploadDropzone projectId={id} /> : null}

      {file.data ? (
        <>
          <Card>
            <CardContent className="flex flex-wrap items-center gap-4 p-5">
              <FileSpreadsheet className="h-8 w-8 text-primary" aria-hidden />
              <div className="min-w-0">
                <p className="truncate font-medium">{file.data.original_filename}</p>
                <p className="text-xs text-muted-foreground">
                  {file.data.file_type.toUpperCase()} · {formatBytes(file.data.size_bytes)}
                  {file.data.row_count != null && file.data.column_count != null
                    ? ` · ${formatNumber(file.data.row_count)} rows × ${formatNumber(file.data.column_count)} columns`
                    : ""}
                  {` · Uploaded ${formatDate(file.data.created_at)}`}
                </p>
              </div>
            </CardContent>
          </Card>

          {profile.isPending ? <LoadingBlock label="Loading profile" /> : null}
          {profile.isError ? <ErrorBlock message={profile.error.message} onRetry={() => profile.refetch()} /> : null}
          {profile.data ? <ProfileView profile={profile.data} /> : null}

          <AnalysisWorkspace projectId={id} profile={profile.data ?? undefined} />
          <ReportsPanel projectId={id} />
        </>
      ) : null}
    </div>
  );
}
