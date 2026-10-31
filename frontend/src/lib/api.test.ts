import { describe, expect, it, vi } from "vitest";
import { ApiError, apiFetch, SESSION_ENDED_MESSAGE } from "@/lib/api";
import { jsonResponse } from "@/test/helpers";

describe("apiFetch", () => {
  it("parses the backend error envelope into ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(
      jsonResponse(401, { error: { code: "invalid_credentials", message: "Invalid email or password." } }),
    ));
    const err = await apiFetch("/auth/login", { method: "POST", json: {} }).catch((e) => e);
    expect(err).toBeInstanceOf(ApiError);
    expect(err).toMatchObject({ status: 401, code: "invalid_credentials", message: "Invalid email or password." });
  });

  it("falls back to a safe message for non-JSON failures", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Internal Server Error", { status: 500 })));
    const err = (await apiFetch("/x").catch((e) => e)) as Error;
    expect(err.message).toMatch(/server is unavailable/i);
  });

  it("sends JSON bodies same-origin under /api/v1", async () => {
    const f = vi.fn().mockResolvedValue(jsonResponse(200, { ok: true }));
    vi.stubGlobal("fetch", f);
    await apiFetch("/auth/login", { method: "POST", json: { a: 1 } });
    const [url, init] = f.mock.calls[0];
    expect(url).toBe("/api/v1/auth/login");
    expect(init).toMatchObject({ credentials: "same-origin", body: '{"a":1}' });
  });

  it("tells the user to sign in again when the session cookie is missing or invalid (401 on a data request)", async () => {
    for (const code of ["missing_token", "invalid_token"]) {
      vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(401, { error: { code, message: "Not authenticated." } })));
      const err = (await apiFetch("/projects/p1/analyze", { method: "POST" }).catch((e) => e)) as ApiError;
      expect(err).toBeInstanceOf(ApiError);
      expect(err).toMatchObject({ status: 401, code, message: SESSION_ENDED_MESSAGE });
    }
  });

  it("keeps the backend's own wording for an expired token and for a failed login", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse(401, { error: { code: "token_expired", message: "Your session has expired. Please log in again." } })));
    expect(await apiFetch("/projects").catch((e) => e)).toMatchObject({ message: "Your session has expired. Please log in again." });
  });
});
