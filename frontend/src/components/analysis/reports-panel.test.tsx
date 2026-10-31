import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { jsonResponse, mockApi, renderWithQuery } from "@/test/helpers";
import { ReportsPanel } from "./reports-panel";

const DONE = {
  id: "a1", project_id: "p1", file_id: "f1", status: "completed", stages: { statistics: "completed" },
  created_at: "2026-10-24T10:00:00Z", updated_at: "2026-10-24T10:00:00Z",
};
const REPORT = {
  id: "r1", project_id: "p1", analysis_id: "a1", file_name: "Sales-report-20261024-1200.pdf",
  generated_at: "2026-10-24T12:00:00Z",
};

describe("ReportsPanel", () => {
  it("is disabled with an explanation until an analysis is completed", async () => {
    mockApi({ "GET /projects/p1/analysis": () => jsonResponse(404, { error: { code: "not_found", message: "none" } }) });
    renderWithQuery(<ReportsPanel projectId="p1" />);
    expect(await screen.findByText("Reports become available once the analysis has finished.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /create pdf report/i })).toBeDisabled();
  });

  it("lists reports with a same-origin download link", async () => {
    mockApi({
      "GET /projects/p1/analysis": () => jsonResponse(200, DONE),
      "GET /projects/p1/reports": () => jsonResponse(200, [REPORT]),
    });
    renderWithQuery(<ReportsPanel projectId="p1" />);
    const list = await screen.findByRole("list", { name: "Created reports" });
    const link = within(list).getByRole("link", { name: /download/i });
    expect(link).toHaveAttribute("href", "/api/v1/projects/p1/reports/r1/download");
    expect(link).toHaveAttribute("download");
  });

  it("creates a report and shows it afterwards", async () => {
    let created = false;
    mockApi({
      "GET /projects/p1/analysis": () => jsonResponse(200, DONE),
      "GET /projects/p1/reports": () => jsonResponse(200, created ? [REPORT] : []),
      "POST /projects/p1/reports": () => {
        created = true;
        return jsonResponse(201, REPORT);
      },
    });
    renderWithQuery(<ReportsPanel projectId="p1" />);
    expect(await screen.findByText("No reports yet.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /create pdf report/i }));
    expect(await screen.findByText(REPORT.file_name)).toBeInTheDocument();
  });

  it("shows the server's message when creation is refused", async () => {
    mockApi({
      "GET /projects/p1/analysis": () => jsonResponse(200, DONE),
      "GET /projects/p1/reports": () => jsonResponse(200, []),
      "POST /projects/p1/reports": () =>
        jsonResponse(429, { error: { code: "report_rate_limited", message: "A report was just created. Please wait a few seconds." } }),
    });
    renderWithQuery(<ReportsPanel projectId="p1" />);
    await userEvent.click(await screen.findByRole("button", { name: /create pdf report/i }));
    expect(await screen.findByRole("alert")).toHaveTextContent("just created");
  });

  it("deletes a report", async () => {
    let deleted = false;
    mockApi({
      "GET /projects/p1/analysis": () => jsonResponse(200, DONE),
      "GET /projects/p1/reports": () => jsonResponse(200, deleted ? [] : [REPORT]),
      "DELETE /projects/p1/reports/r1": () => {
        deleted = true;
        return new Response(null, { status: 204 });
      },
    });
    renderWithQuery(<ReportsPanel projectId="p1" />);
    await userEvent.click(await screen.findByRole("button", { name: /delete sales-report/i }));
    await waitFor(() => expect(screen.getByText("No reports yet.")).toBeInTheDocument());
  });
});
