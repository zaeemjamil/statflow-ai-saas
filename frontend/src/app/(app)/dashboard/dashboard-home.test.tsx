import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { jsonResponse, mockApi, renderWithQuery } from "@/test/helpers";
import { DashboardHome } from "./dashboard-home";

const ME = { id: "u1", email: "a@example.com", full_name: "Ada Lovelace", created_at: "2026-01-01T00:00:00Z" };
const SUMMARY = {
  total_projects: 3,
  files_analyzed: 2,
  reports_generated: 0,
  ai_insights_generated: 0,
  recent_projects: [{ id: "p1", name: "Turbine telemetry", status: "completed", updated_at: "2026-10-01T10:00:00Z" }],
};

describe("DashboardHome", () => {
  it("renders the server's counts and recent projects", async () => {
    mockApi({
      "GET /auth/me": () => jsonResponse(200, ME),
      "GET /dashboard/summary": () => jsonResponse(200, SUMMARY),
    });
    renderWithQuery(<DashboardHome />);
    expect(await screen.findByText("Welcome, Ada")).toBeInTheDocument();
    expect(await screen.findByTestId("stat-Projects")).toHaveTextContent("3");
    expect(screen.getByTestId("stat-Files analyzed")).toHaveTextContent("2");
    expect(screen.getByTestId("stat-Reports")).toHaveTextContent("0");
    expect(screen.getByRole("link", { name: /Turbine telemetry/ })).toHaveAttribute("href", "/projects/p1");
    expect(screen.getByText("Analysis complete")).toBeInTheDocument();
  });

  it("shows an empty state (not fake rows) when there are no projects", async () => {
    mockApi({
      "GET /auth/me": () => jsonResponse(200, ME),
      "GET /dashboard/summary": () => jsonResponse(200, { ...SUMMARY, total_projects: 0, files_analyzed: 0, recent_projects: [] }),
    });
    renderWithQuery(<DashboardHome />);
    expect(await screen.findByText(/No projects yet/)).toBeInTheDocument();
    expect(screen.getByTestId("stat-Projects")).toHaveTextContent("0");
  });

  it("shows the server error and lets the user retry", async () => {
    let calls = 0;
    mockApi({
      "GET /auth/me": () => jsonResponse(200, ME),
      "GET /dashboard/summary": () => {
        calls += 1;
        return calls === 1
          ? jsonResponse(500, { error: { code: "internal_error", message: "Something broke." } })
          : jsonResponse(200, SUMMARY);
      },
    });
    renderWithQuery(<DashboardHome />);
    expect(await screen.findByText("Something broke.")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: /try again/i }));
    expect(await screen.findByTestId("stat-Projects")).toHaveTextContent("3");
  });
});
