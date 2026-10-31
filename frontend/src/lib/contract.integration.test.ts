// @vitest-environment node
/**
 * Checkpoint 5 - API contract check against a REAL backend.
 *
 * Skipped unless CONTRACT_BASE_URL is set (e.g. http://localhost:3000 through Next, or
 * http://127.0.0.1:8000 direct); `npm test` therefore stays hermetic. Run it with:
 *
 *   CONTRACT_BASE_URL=http://localhost:3000 npx vitest run src/lib/contract.integration.test.ts
 *
 * It registers a throwaway user, uploads fixtures, calls every endpoint the UI uses, and parses each
 * real response with the SAME Zod schemas the app uses. It also reports response fields the frontend
 * schemas do not know about (so a backend field added/renamed without a frontend change is visible),
 * and checks the error envelope (`error.code`, `error.message`) for the 4xx cases the UI handles.
 */
import { describe, expect, it } from "vitest";
import { z } from "zod";

import {
  analysisSchema,
  dashboardSummarySchema,
  datasetProfileSchema,
  fileInfoSchema,
  projectSchema,
  uploadResponseSchema,
  visualizationResultSchema,
  descriptiveStatisticsSchema,
  correlationResultSchema,
  outlierResultSchema,
} from "@/lib/schemas";
import { userSchema } from "@/lib/auth";

const BASE = process.env.CONTRACT_BASE_URL?.replace(/\/$/, "");
const API = `${BASE}/api/v1`;

let cookie = "";

async function call(path: string, init: RequestInit & { json?: unknown } = {}) {
  const { json, headers, ...rest } = init;
  const res = await fetch(`${API}${path}`, {
    ...rest,
    headers: {
      Accept: "application/json",
      ...(json !== undefined ? { "Content-Type": "application/json" } : {}),
      ...(cookie ? { Cookie: cookie } : {}),
      ...headers,
    },
    body: json !== undefined ? JSON.stringify(json) : rest.body,
  });
  const setCookie = res.headers.getSetCookie?.() ?? [];
  if (setCookie.length) {
    cookie = setCookie.map((c) => c.split(";")[0]).join("; ");
  }
  const text = await res.text();
  let body: unknown = null;
  try {
    body = text ? JSON.parse(text) : null;
  } catch {
    body = text;
  }
  return { status: res.status, body };
}

/** Keys present in the raw JSON but dropped by the schema (Zod strips unknown keys). */
function extraKeys(raw: unknown, parsed: unknown, path = "$"): string[] {
  if (Array.isArray(raw) && Array.isArray(parsed)) {
    return raw.flatMap((r, i) => extraKeys(r, parsed[i], `${path}[]`)).filter((v, i, a) => a.indexOf(v) === i);
  }
  if (raw && typeof raw === "object" && parsed && typeof parsed === "object") {
    const r = raw as Record<string, unknown>;
    const p = parsed as Record<string, unknown>;
    const out: string[] = [];
    for (const key of Object.keys(r)) {
      if (!(key in p)) out.push(`${path}.${key}`);
      else out.push(...extraKeys(r[key], p[key], `${path}.${key}`));
    }
    return out;
  }
  return [];
}

const extras = new Map<string, string[]>();
function parseWith<T extends z.ZodTypeAny>(label: string, schema: T, raw: unknown): z.infer<T> {
  const result = schema.safeParse(raw);
  if (!result.success) {
    throw new Error(`${label}: response does not match the frontend schema: ${JSON.stringify(result.error.issues.slice(0, 5))}`);
  }
  const unknownKeys = extraKeys(raw, result.data);
  if (unknownKeys.length) extras.set(label, [...new Set([...(extras.get(label) ?? []), ...unknownKeys])]);
  return result.data;
}

function csv(rows: string[][]): Blob {
  return new Blob([rows.map((r) => r.join(",")).join("\n") + "\n"], { type: "text/csv" });
}
function form(name: string, blob: Blob): FormData {
  const f = new FormData();
  f.append("file", blob, name);
  return f;
}
async function newProject(name = "contract"): Promise<string> {
  const r = await call("/projects", { method: "POST", json: { name } });
  expect(r.status).toBe(201);
  return parseWith("POST /projects", projectSchema, r.body).id;
}

// Fixtures ---------------------------------------------------------------------------------------
function cleanFixture(): Blob {
  const rows = [["x", "y", "group", "when"]];
  for (let i = 0; i < 80; i++) {
    rows.push([String(i), String((i * 2.5 + (i % 7)).toFixed(2)), ["a", "b", "c"][i % 3], `2024-01-${String((i % 28) + 1).padStart(2, "0")}`]);
  }
  return csv(rows);
}
function messyFixture(): Blob {
  const rows = [["row_id", "score", "country", "price", "when", "empty", "measure"]];
  for (let i = 0; i < 40; i++) {
    rows.push([
      String(i + 1),
      i % 7 ? String(i) : "NA",
      i % 5 === 0 ? "NA" : "US",
      `"$${(i * 10 + 1).toLocaleString("en-US")}"`,
      ["01.02.2025", "03.04.2025", "05.06.2025", "07.08.2025"][i % 4],
      "",
      String(i * 1.5),
    ]);
  }
  return csv(rows);
}
function largeFixture(rows = 3200): Blob {
  const out = [["t", "a", "b"]];
  for (let i = 0; i < rows; i++) out.push([String(i), String(Math.sin(i / 50) * 10 + (i % 13)), String((i * 7) % 101)]);
  return csv(out);
}

describe.skipIf(!BASE)("frontend schemas vs the real backend", () => {
  const email = `contract-${Date.now()}-${Math.random().toString(16).slice(2, 8)}@example.com`;

  it("auth: register, me, logout, login again", async () => {
    const reg = await call("/auth/register", { method: "POST", json: { email, password: "correct-horse-1" } });
    expect(reg.status).toBe(201);
    parseWith("POST /auth/register", userSchema, reg.body);
    expect(cookie).not.toBe("");
    const me = await call("/auth/me");
    expect(me.status).toBe(200);
    parseWith("GET /auth/me", userSchema, me.body);
    const out = await call("/auth/logout", { method: "POST" });
    expect(out.status).toBe(200);
    expect(out.body).toEqual({ message: expect.any(String) });
    cookie = "";
    expect((await call("/auth/me")).status).toBe(401);
    const login = await call("/auth/login", { method: "POST", json: { email, password: "correct-horse-1" } });
    expect(login.status).toBe(200);
    parseWith("POST /auth/login", userSchema, login.body);
    expect((await call("/auth/me")).status).toBe(200);
  });

  it("projects, dashboard, file and profile before/after upload", async () => {
    const id = await newProject("contract-clean");
    expect((await call(`/projects/${id}/file`)).status).toBe(404);
    expect((await call(`/projects/${id}/profile`)).status).toBe(404);
    expect((await call(`/projects/${id}/analysis`)).status).toBe(404);

    const up = await call(`/projects/${id}/upload`, { method: "POST", body: form("clean.csv", cleanFixture()) });
    expect(up.status).toBe(201);
    const uploaded = parseWith("POST /upload", uploadResponseSchema, up.body);
    const profile = parseWith("GET /profile", datasetProfileSchema, (await call(`/projects/${id}/profile`)).body);
    expect(profile).toEqual(uploaded.profile);
    parseWith("GET /file", fileInfoSchema, (await call(`/projects/${id}/file`)).body);

    const list = await call("/projects");
    parseWith("GET /projects", z.array(projectSchema), list.body);
    parseWith("GET /projects/{id}", projectSchema, (await call(`/projects/${id}`)).body);
    const renamed = await call(`/projects/${id}`, { method: "PATCH", json: { name: "contract-renamed" } });
    expect(parseWith("PATCH /projects/{id}", projectSchema, renamed.body).name).toBe("contract-renamed");
    parseWith("GET /dashboard/summary", dashboardSummarySchema, (await call("/dashboard/summary")).body);
  });

  it("clean, analyze, regression and the stored analysis agree", async () => {
    const id = await newProject("contract-analysis");
    await call(`/projects/${id}/upload`, { method: "POST", body: form("clean.csv", cleanFixture()) });

    const cleaned = await call(`/projects/${id}/clean`, {
      method: "POST",
      json: { numeric_strategy: "median", categorical_strategy: "mode", duplicate_strategy: "remove" },
    });
    expect(cleaned.status).toBe(200);
    parseWith("POST /clean", analysisSchema, cleaned.body);

    const analysed = await call(`/projects/${id}/analyze`, { method: "POST" });
    expect(analysed.status).toBe(200);
    const analysis = parseWith("POST /analyze", analysisSchema, analysed.body);
    expect(analysis.status).toBe("completed");

    const reg = await call(`/projects/${id}/regression`, { method: "POST", json: { target: "y", predictors: ["x"] } });
    expect(reg.status).toBe(200);
    const withRegression = parseWith("POST /regression", analysisSchema, reg.body);
    expect(withRegression.regression).toBeTruthy();

    // The persisted analysis is exactly what the last POST returned (what a reload shows).
    const stored = await call(`/projects/${id}/analysis`);
    expect(stored.status).toBe(200);
    parseWith("GET /analysis", analysisSchema, stored.body);
    const strip = (v: unknown) => {
      const o = JSON.parse(JSON.stringify(v)) as Record<string, unknown>;
      delete o.updated_at; // may differ by the write that produced the last POST
      return o;
    };
    expect(strip(stored.body)).toEqual(strip(reg.body));

    // Sub-resource GETs exist even though the UI reads only /analysis.
    parseWith("GET /statistics", descriptiveStatisticsSchema, (await call(`/projects/${id}/statistics`)).body);
    parseWith("GET /correlations", correlationResultSchema, (await call(`/projects/${id}/correlations`)).body);
    parseWith("GET /outliers", outlierResultSchema, (await call(`/projects/${id}/outliers`)).body);
    parseWith("GET /charts", visualizationResultSchema, (await call(`/projects/${id}/charts`)).body);
  });

  it("messy file: Stage 3 notes, blank column and dotted dates validate and survive a re-read", async () => {
    const id = await newProject("contract-messy");
    const up = await call(`/projects/${id}/upload`, { method: "POST", body: form("messy.csv", messyFixture()) });
    expect(up.status).toBe(201);
    const { profile } = parseWith("POST /upload (messy)", uploadResponseSchema, up.body);
    const codes = (profile.import_notes ?? []).map((n) => n.code);
    expect(codes).toEqual(expect.arrayContaining(["na_text_read_as_missing", "na_text_kept_as_value", "ambiguous_dates"]));
    const byName = Object.fromEntries(profile.columns.map((c) => [c.name, c]));
    expect(byName.empty.classification).toBe("categorical");
    expect(byName.empty.missing_percentage).toBe(100);
    expect(byName.when.classification).toBe("date");
    const analysed = await call(`/projects/${id}/analyze`, { method: "POST" });
    expect(analysed.status).toBe(200);
    const a = parseWith("POST /analyze (messy)", analysisSchema, analysed.body);
    expect(a.profile?.columns).toEqual(profile.columns);
    expect(a.statistics?.columns.map((c) => c.column)).not.toContain("empty");
  });

  it("large file: sampled charts carry sampling metadata the UI schema accepts", async () => {
    const id = await newProject("contract-large");
    await call(`/projects/${id}/upload`, { method: "POST", body: form("large.csv", largeFixture()) });
    const analysed = await call(`/projects/${id}/analyze`, { method: "POST" });
    expect(analysed.status).toBe(200);
    const a = parseWith("POST /analyze (large)", analysisSchema, analysed.body);
    const sampled = (a.visualizations?.charts ?? []).filter((c) => c.sampling);
    expect(sampled.length).toBeGreaterThan(0);
    for (const c of sampled) {
      expect(c.sampling!.total_points).toBeGreaterThan(c.sampling!.displayed_points);
      expect(c.sampling!.displayed_points).toBeLessThanOrEqual(2500);
    }
  });

  it("error envelope: the 4xx cases the UI maps", async () => {
    const id = await newProject("contract-errors");
    const code = (r: { body: unknown }) => (r.body as { error?: { code?: string; message?: string } }).error;

    const noFile = await call(`/projects/${id}/analyze`, { method: "POST" });
    expect([404, 409, 422]).toContain(noFile.status);
    expect(code(noFile)?.code).toBeTruthy();
    expect(code(noFile)?.message).toBeTruthy();

    const bad = await call(`/projects/${id}/upload`, { method: "POST", body: form("notes.txt", new Blob(["hello"])) });
    expect(bad.status).toBe(422);
    expect(code(bad)?.code).toBe("unsupported_file_type");

    await call(`/projects/${id}/upload`, { method: "POST", body: form("clean.csv", cleanFixture()) });
    const second = await call(`/projects/${id}/upload`, { method: "POST", body: form("clean.csv", cleanFixture()) });
    expect(second.status).toBe(409);
    expect(code(second)?.message).toBeTruthy();

    // No analysis row exists yet -> 404 analysis_not_found; once /clean has created one that is not
    // completed -> 409 analysis_not_completed (the UI gates both, this pins the real wire behaviour).
    const none = await call(`/projects/${id}/regression`, { method: "POST", json: { target: "y", predictors: ["x"] } });
    expect(none.status).toBe(404);
    expect(code(none)?.code).toBe("analysis_not_found");
    const cleanOnly = await call(`/projects/${id}/clean`, { method: "POST", json: {} });
    expect(cleanOnly.status).toBe(200);
    const early = await call(`/projects/${id}/regression`, { method: "POST", json: { target: "y", predictors: ["x"] } });
    expect(early.status).toBe(409);
    expect(code(early)?.code).toBe("analysis_not_completed");

    await call(`/projects/${id}/analyze`, { method: "POST" });
    const nonNumeric = await call(`/projects/${id}/regression`, { method: "POST", json: { target: "group", predictors: ["x"] } });
    expect(nonNumeric.status).toBe(422);
    expect(code(nonNumeric)?.code).toBe("regression_target_not_numeric");

    const missing = await call("/projects/00000000-0000-0000-0000-000000000000");
    expect(missing.status).toBe(404);
    expect(code(missing)?.code).toBe("not_found");

    const saved = cookie;
    cookie = "";
    const anon = await call("/projects");
    expect(anon.status).toBe(401);
    expect(code(anon)?.code).toBeTruthy();
    cookie = saved;
  });

  it("ownership: another user gets the same 404 as for a missing project", async () => {
    const id = await newProject("contract-owner");
    const mine = cookie;
    cookie = "";
    const other = await call("/auth/register", {
      method: "POST",
      json: { email: `other-${Date.now()}@example.com`, password: "correct-horse-1" },
    });
    expect(other.status).toBe(201);
    for (const path of [`/projects/${id}`, `/projects/${id}/file`, `/projects/${id}/analysis`, `/projects/${id}/profile`]) {
      const r = await call(path);
      expect(r.status).toBe(404);
    }
    expect((await call(`/projects/${id}/analyze`, { method: "POST" })).status).toBe(404);
    expect((await call(`/projects/${id}`, { method: "DELETE" })).status).toBe(404);
    cookie = mine;
    expect((await call(`/projects/${id}`)).status).toBe(200); // still intact
  });

  it("reports response fields the frontend schemas do not know about (informational)", () => {
    if (extras.size) {
      console.info("Backend fields ignored by the frontend schemas:", Object.fromEntries(extras));
    }
    expect(true).toBe(true);
  });
});
