import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Analysis } from "@/lib/schemas";
import { jsonResponse, mockApi, renderWithQuery } from "@/test/helpers";
import { AiTab } from "./ai-tab";

const DONE = { status: "completed", stages: { statistics: "completed" } } as unknown as Analysis;
const STATE = {
  configured: true, eligible: true, reason_code: null, message: null, warnings: [], insight: null,
  has_outdated_insight: false, remaining_today: 5, disclaimer: "AI-generated explanation.",
};

describe("AiTab privacy wording", () => {
  it("states accurately what is and is not sent to the AI service", async () => {
    mockApi({ "GET /projects/p1/ai-insights": () => jsonResponse(200, STATE) });
    renderWithQuery(<AiTab projectId="p1" analysis={DONE} />);
    const text = (await screen.findByText(/What is sent to the AI service/)).textContent ?? "";
    expect(text).toContain("anonymous column labels");
    expect(text).toContain("summary numbers");
    expect(text).toMatch(/Not sent:.*column names.*file name.*individual rows.*exact smallest and largest value/);
    expect(text).toContain("can occasionally equal one of your values");
  });

  it("no longer claims that cell values are never sent", async () => {
    mockApi({ "GET /projects/p1/ai-insights": () => jsonResponse(200, STATE) });
    renderWithQuery(<AiTab projectId="p1" analysis={DONE} />);
    const text = (await screen.findByText(/What is sent to the AI service/)).textContent ?? "";
    expect(text).not.toMatch(/never your column names or cell values/);
  });
});
