"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError, apiFetch } from "@/lib/api";
import {
  aiInsightsStateSchema,
  analysisSchema,
  dashboardSummarySchema,
  datasetProfileSchema,
  fileInfoSchema,
  projectSchema,
  reportSchema,
  uploadResponseSchema,
  type Analysis,
  type CleaningConfig,
  type Project,
  type RegressionInput,
} from "@/lib/schemas";
import { z } from "zod";

export const qk = {
  dashboard: ["dashboard"] as const,
  projects: ["projects"] as const,
  project: (id: string) => ["projects", id] as const,
  file: (id: string) => ["projects", id, "file"] as const,
  profile: (id: string) => ["projects", id, "profile"] as const,
  analysis: (id: string) => ["projects", id, "analysis"] as const,
  aiInsights: (id: string) => ["projects", id, "ai-insights"] as const,
  reports: (id: string) => ["projects", id, "reports"] as const,
};

/** 404 means "nothing there yet" for sub-resources, not a failure. */
async function nullOn404<T>(fn: () => Promise<T>): Promise<T | null> {
  try {
    return await fn();
  } catch (e) {
    if (e instanceof ApiError && e.status === 404) return null;
    throw e;
  }
}

export function useDashboardSummary() {
  return useQuery({
    queryKey: qk.dashboard,
    queryFn: async () => dashboardSummarySchema.parse(await apiFetch<unknown>("/dashboard/summary")),
  });
}

export function useProjects() {
  return useQuery({
    queryKey: qk.projects,
    queryFn: async () => z.array(projectSchema).parse(await apiFetch<unknown>("/projects")),
  });
}

export function useProject(id: string) {
  return useQuery({
    queryKey: qk.project(id),
    queryFn: async () => projectSchema.parse(await apiFetch<unknown>(`/projects/${id}`)),
  });
}

export function useProjectFile(id: string) {
  return useQuery({
    queryKey: qk.file(id),
    queryFn: () =>
      nullOn404(async () => fileInfoSchema.parse(await apiFetch<unknown>(`/projects/${id}/file`))),
  });
}

export function useProfile(id: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.profile(id),
    enabled,
    queryFn: () =>
      nullOn404(async () => datasetProfileSchema.parse(await apiFetch<unknown>(`/projects/${id}/profile`))),
  });
}

function useInvalidateAll() {
  const qc = useQueryClient();
  return () =>
    Promise.all([
      qc.invalidateQueries({ queryKey: qk.projects }),
      qc.invalidateQueries({ queryKey: qk.dashboard }),
    ]);
}

export function useCreateProject() {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: async (name: string): Promise<Project> =>
      projectSchema.parse(await apiFetch<unknown>("/projects", { method: "POST", json: { name } })),
    onSuccess: invalidate,
  });
}

export function useRenameProject(id: string) {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: async (name: string): Promise<Project> =>
      projectSchema.parse(await apiFetch<unknown>(`/projects/${id}`, { method: "PATCH", json: { name } })),
    onSuccess: invalidate,
  });
}

export function useDeleteProject(id: string) {
  const qc = useQueryClient();
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: () => apiFetch<void>(`/projects/${id}`, { method: "DELETE" }),
    onSuccess: async () => {
      qc.removeQueries({ queryKey: qk.project(id) });
      await invalidate();
    },
  });
}

export function useUploadFile(id: string) {
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: async (file: File) => {
      const body = new FormData();
      body.append("file", file);
      return uploadResponseSchema.parse(await apiFetch<unknown>(`/projects/${id}/upload`, { method: "POST", body }));
    },
    onSuccess: invalidate,
  });
}

// --- Cleaning & analysis ---------------------------------------------------
// Every analysis endpoint that mutates returns the same AnalysisPublic shape
// as GET /analysis, so the response is written straight into that one cache entry.

/** 404 = "no analysis has been run yet", which is a normal state. */
export function useAnalysis(id: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.analysis(id),
    enabled,
    queryFn: () => nullOn404(async () => analysisSchema.parse(await apiFetch<unknown>(`/projects/${id}/analysis`))),
  });
}

function useAnalysisMutation<V>(id: string, request: (vars: V) => Promise<unknown>) {
  const qc = useQueryClient();
  const invalidate = useInvalidateAll();
  return useMutation({
    mutationFn: async (vars: V): Promise<Analysis> => analysisSchema.parse(await request(vars)),
    onSuccess: async (analysis) => {
      qc.setQueryData(qk.analysis(id), analysis);
      // Any new result makes an earlier AI explanation outdated; refetch its state.
      void qc.invalidateQueries({ queryKey: qk.aiInsights(id) });
      // The project status changes (cleaning_completed / completed), as do the dashboard counts.
      await Promise.all([qc.invalidateQueries({ queryKey: qk.project(id), exact: true }), invalidate()]);
    },
    onError: async () => {
      // A failed run can leave the project/analysis in a failed state on the server.
      await Promise.all([
        qc.invalidateQueries({ queryKey: qk.project(id), exact: true }),
        qc.invalidateQueries({ queryKey: qk.analysis(id) }),
      ]);
    },
  });
}

export function useCleanProject(id: string) {
  return useAnalysisMutation<CleaningConfig>(id, (json) => apiFetch<unknown>(`/projects/${id}/clean`, { method: "POST", json }));
}

export function useAnalyzeProject(id: string) {
  return useAnalysisMutation<void>(id, () => apiFetch<unknown>(`/projects/${id}/analyze`, { method: "POST" }));
}

export function useRunRegression(id: string) {
  return useAnalysisMutation<RegressionInput>(id, (json) => apiFetch<unknown>(`/projects/${id}/regression`, { method: "POST", json }));
}

/** The AI analyst state (configured? eligible? stored explanation?). */
export function useAiInsights(id: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.aiInsights(id),
    enabled,
    queryFn: async () => aiInsightsStateSchema.parse(await apiFetch<unknown>(`/projects/${id}/ai-insights`)),
  });
}

export function useGenerateAiInsights(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      aiInsightsStateSchema.parse(await apiFetch<unknown>(`/projects/${id}/ai-insights`, { method: "POST" })),
    onSuccess: (state) => {
      qc.setQueryData(qk.aiInsights(id), state);
    },
    // A failed call still uses up one of today's attempts, so refresh the counter.
    onError: () => qc.invalidateQueries({ queryKey: qk.aiInsights(id) }),
  });
}

export function useReports(id: string, enabled: boolean) {
  return useQuery({
    queryKey: qk.reports(id),
    enabled,
    queryFn: async () => z.array(reportSchema).parse(await apiFetch<unknown>(`/projects/${id}/reports`)),
  });
}

export function useCreateReport(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async () => reportSchema.parse(await apiFetch<unknown>(`/projects/${id}/reports`, { method: "POST" })),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.reports(id) }),
  });
}

export function useDeleteReport(id: string) {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (reportId: string) => apiFetch<unknown>(`/projects/${id}/reports/${reportId}`, { method: "DELETE" }),
    onSuccess: () => qc.invalidateQueries({ queryKey: qk.reports(id) }),
  });
}
