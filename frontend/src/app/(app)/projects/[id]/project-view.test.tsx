import { screen } from "@testing-library/react";
import { Suspense } from "react";
import { describe, expect, it, vi } from "vitest";
import { jsonResponse, mockApi, renderWithQuery } from "@/test/helpers";
import { ProjectView } from "./project-view";

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace: vi.fn(), push: vi.fn() }) }));

const PROJECT = { id: "p1", name: "Turbine telemetry", status: "profiled", created_at: "2026-10-01T10:00:00Z", updated_at: "2026-10-01T10:05:00Z" };
const FILE = {
  id: "f1", project_id: "p1", original_filename: "turbine.csv", file_type: "csv",
  size_bytes: 2048, row_count: 500, column_count: 2, created_at: "2026-10-01T10:05:00Z",
};
const PROFILE = {
  row_count: 500, column_count: 2, numeric_column_count: 1, categorical_column_count: 1, date_column_count: 0,
  total_missing_values: 12, duplicate_row_count: 3,
  columns: [
    { name: "rpm", classification: "numeric", pandas_dtype: "float64", missing_count: 12, missing_percentage: 2.4, unique_count: 480, is_unique: false, min_value: 10, max_value: 1500 },
    { name: "site", classification: "categorical", pandas_dtype: "object", missing_count: 0, missing_percentage: 0, unique_count: 4, is_unique: false },
  ],
};

// React's use() reads a promise synchronously once it carries status "fulfilled",
// which avoids depending on Suspense retry timing under jsdom.
function fulfilled<T>(value: T): Promise<T> {
  return Object.assign(Promise.resolve(value), { status: "fulfilled" as const, value });
}

function renderView(id = "p1") {
  return renderWithQuery(
    <Suspense fallback={<p>suspended</p>}>
      <ProjectView params={fulfilled({ id })} />
    </Suspense>,
  );
}

describe("ProjectView", () => {
  it("offers upload when the project has no file yet", async () => {
    mockApi({
      "GET /projects/p1": () => jsonResponse(200, { ...PROJECT, status: "created" }),
      "GET /projects/p1/file": () => jsonResponse(404, { error: { code: "not_found", message: "No uploaded file was found for this project." } }),
    });
    renderView();
    expect(await screen.findByText("Upload your data")).toBeInTheDocument();
    expect(screen.getByText("Awaiting file")).toBeInTheDocument();
  });

  it("shows the stored file and the server-computed profile", async () => {
    mockApi({
      "GET /projects/p1": () => jsonResponse(200, PROJECT),
      "GET /projects/p1/file": () => jsonResponse(200, FILE),
      "GET /projects/p1/profile": () => jsonResponse(200, PROFILE),
      "GET /projects/p1/analysis": () => jsonResponse(404, { error: { code: "analysis_not_found", message: "No analysis exists for this project yet." } }),
    });
    renderView();
    expect(await screen.findByText("turbine.csv")).toBeInTheDocument();
    expect(await screen.findByRole("table", { name: "Per-column profile" })).toBeInTheDocument();
    expect(screen.getByRole("rowheader", { name: "rpm" })).toBeInTheDocument();
    expect(screen.getByText("12 (2.4%)")).toBeInTheDocument();
    expect(screen.getByText("10 – 1,500")).toBeInTheDocument();
    expect(screen.queryByText("Upload your data")).not.toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "Run analysis" })).toBeInTheDocument();
  });

  it("shows a not-found message for a missing or foreign project", async () => {
    mockApi({
      "GET /projects/zzz": () => jsonResponse(404, { error: { code: "not_found", message: "Project not found." } }),
      "GET /projects/zzz/file": () => jsonResponse(404, { error: { code: "not_found", message: "Project not found." } }),
    });
    renderView("zzz");
    expect(await screen.findByText(/doesn't exist or you don't have access/)).toBeInTheDocument();
  });
});
