"use client";

import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { z } from "zod";
import { ApiError, apiFetch } from "@/lib/api";

export const userSchema = z.object({
  id: z.string(),
  email: z.string(),
  full_name: z.string().nullable(),
  created_at: z.string(),
});
export type User = z.infer<typeof userSchema>;

export const ME_KEY = ["auth", "me"] as const;

/** Current user, or null when not signed in. Other errors surface as errors. */
export function useCurrentUser() {
  return useQuery<User | null>({
    queryKey: ME_KEY,
    queryFn: async () => {
      try {
        return userSchema.parse(await apiFetch<unknown>("/auth/me"));
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { email: string; password: string }) =>
      userSchema.parse(await apiFetch<unknown>("/auth/login", { method: "POST", json: v })),
    onSuccess: (user) => qc.setQueryData(ME_KEY, user),
  });
}

export function useRegister() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async (v: { email: string; password: string; full_name?: string }) =>
      userSchema.parse(await apiFetch<unknown>("/auth/register", { method: "POST", json: v })),
    onSuccess: (user) => qc.setQueryData(ME_KEY, user),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => apiFetch<{ message: string }>("/auth/logout", { method: "POST" }),
    onSettled: () => {
      // Drop every cached server value so the next user never sees this one's data.
      qc.clear();
      qc.setQueryData(ME_KEY, null);
    },
  });
}

export function useForgotPassword() {
  return useMutation({
    mutationFn: (v: { email: string }) =>
      apiFetch<{ message: string }>("/auth/forgot-password", { method: "POST", json: v }),
  });
}

export function useResetPassword() {
  return useMutation({
    mutationFn: (v: { token: string; new_password: string }) =>
      apiFetch<{ message: string }>("/auth/reset-password", { method: "POST", json: v }),
  });
}
