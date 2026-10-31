import { screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import type { Analysis } from "@/lib/schemas";
import { jsonResponse, mockApi, renderWithQuery } from "@/test/helpers";
import { AiTab } from "./ai-tab";

const DONE = { status: "completed", stages: { statistics: "completed" } } as unknown as Analysis;
const DISCLAIMER = "AI-generated explanation of the analysis on this page. It can be wrong.";
const STATE = {
  configured: true, eligible: true, reason_code: null, message: null, warnings: [], insight: null,
  has_outdated_insight: false, remaining_today: 5, disclaimer: DISCLAIMER,
};
const INSIGHT = {
  summary: "“revenue” rises with “ad spend”.", key_findings: ["<script>alert(1)</script> stays text"],
  data_quality: [], limitations: ["Association only."], next_steps: ["Check “discount”."],
  evidence_warnings: ["small_sample"], generated_at: "2026-10-24T10:00:00Z", model: "fake/model", prompt_version: "1",
};
const GET = "GET /projects/p1/ai-insights";
const POST = "POST /projects/p1/ai-insights";

describe("AiTab", () => {
  it("asks for a completed analysis first and makes no request", () => {
    const fetchMock = mockApi({});
    renderWithQuery(<AiTab projectId="p1" analysis={null} />);
    expect(screen.getByText("Run the analysis first")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("explains that the feature is off when the server has no key", async () => {
    mockApi({ [GET]: () => jsonResponse(200, { ...STATE, configured: false }) });
    renderWithQuery(<AiTab projectId="p1" analysis={DONE} />);
    expect(await screen.findByText("AI explanations are not turned on")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /generate/i })).not.toBeInTheDocument();
  });

  it("shows the server's reason when the data is not eligible", async () => {
    mockApi({ [GET]: () => jsonResponse(200, { ...STATE, eligible: false, reason_code: "too_few_rows", message: "Need at least 5 rows." }) });
    renderWithQuery(<AiTab projectId="p1" analysis={DONE} />);
    expect(await screen.findByText("Need at least 5 rows.")).toBeInTheDocument();
  });

  it("generates, shows the explanation as plain text with warnings and the disclaimer", async () => {
    let generated = false;
    mockApi({
      [GET]: () => jsonResponse(200, { ...STATE, warnings: ["small_sample"] }),
      [POST]: () => {
        generated = true;
        return jsonResponse(200, { ...STATE, warnings: ["small_sample"], insight: INSIGHT, remaining_today: 4 });
      },
    });
    renderWithQuery(<AiTab projectId="p1" analysis={DONE} />);
    await userEvent.click(await screen.findByRole("button", { name: "Generate explanation" }));
    expect(await screen.findByText("“revenue” rises with “ad spend”.")).toBeInTheDocument();
    expect(generated).toBe(true);
    // model text is inert: shown literally, not turned into an element
    expect(screen.getByText("<script>alert(1)</script> stays text")).toBeInTheDocument();
    expect(document.querySelector("script[src], li script")).toBeNull();
    expect(screen.getAllByText(/Small sample/).length).toBeGreaterThan(0);
    expect(screen.getByText(/It can be wrong/)).toBeInTheDocument();
    expect(screen.getByText("4 left today.")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Regenerate explanation" })).toBeInTheDocument();
  });

  it("shows a friendly error when generation fails and keeps the page usable", async () => {
    mockApi({
      [GET]: () => jsonResponse(200, STATE),
      [POST]: () => jsonResponse(502, { error: { code: "ai_provider_timeout", message: "The AI service took too long to answer. Please try again." } }),
    });
    renderWithQuery(<AiTab projectId="p1" analysis={DONE} />);
    await userEvent.click(await screen.findByRole("button", { name: "Generate explanation" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("took too long");
    await waitFor(() => expect(screen.getByRole("button", { name: "Generate explanation" })).toBeEnabled());
  });

  it("disables the button when today's limit is used up", async () => {
    mockApi({ [GET]: () => jsonResponse(200, { ...STATE, remaining_today: 0 }) });
    renderWithQuery(<AiTab projectId="p1" analysis={DONE} />);
    expect(await screen.findByRole("button", { name: "Generate explanation" })).toBeDisabled();
    expect(screen.getByText("Daily limit reached. Try again tomorrow.")).toBeInTheDocument();
  });

  it("tells the user an old explanation was removed after the results changed", async () => {
    mockApi({ [GET]: () => jsonResponse(200, { ...STATE, has_outdated_insight: true }) });
    renderWithQuery(<AiTab projectId="p1" analysis={DONE} />);
    expect(await screen.findByText(/results changed since the last explanation/)).toBeInTheDocument();
  });
});
