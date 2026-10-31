/** Typed fetch wrapper for the Zaimex backend (same-origin via rewrite). */

export const API_BASE = "/api/v1";
export const SESSION_ENDED_MESSAGE = "Your session has ended. Please sign in again to continue.";

export class ApiError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

type ErrorBody = { error?: { code?: string; message?: string } };

export async function apiFetch<T>(
  path: string,
  init: RequestInit & { json?: unknown } = {},
): Promise<T> {
  const { json, headers, ...rest } = init;
  const res = await fetch(`${API_BASE}${path}`, {
    credentials: "same-origin",
    ...rest,
    headers: {
      Accept: "application/json",
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });

  if (!res.ok) {
    let body: ErrorBody = {};
    try {
      body = (await res.json()) as ErrorBody;
    } catch {
      /* non-JSON error (e.g. proxy failure) */
    }
    const code = body.error?.code ?? "http_error";
    // A 401 on a data request means the session cookie is gone or invalid. The backend's wording
    // ("Not authenticated.") does not say what to do; login failures use their own code and text.
    if (res.status === 401 && (code === "missing_token" || code === "invalid_token")) {
      throw new ApiError(res.status, code, SESSION_ENDED_MESSAGE);
    }
    throw new ApiError(
      res.status,
      code,
      body.error?.message ??
        (res.status >= 500
          ? "The server is unavailable. Please try again."
          : `Request failed (${res.status}).`),
    );
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}
