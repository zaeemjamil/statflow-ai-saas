import { render, screen } from "@testing-library/react";
import { beforeAll, describe, expect, it } from "vitest";
import type { ChartRecommendation } from "@/lib/schemas";
import { chartRecommendationSchema } from "@/lib/schemas";
import { ChartsTab, samplingNote } from "./charts-tab";

beforeAll(() => {
  // Recharts' ResponsiveContainer needs ResizeObserver, which jsdom lacks.
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
});

const base = {
  title: "t", x_column: "a", y_column: "b", reason: "because", data_requirements: {}, data: [{ x: 1, y: 2 }],
};
const full: ChartRecommendation = { ...base, chart_type: "scatter", title: "full chart" };
const sampledScatter: ChartRecommendation = {
  ...base, chart_type: "scatter", title: "sampled scatter",
  sampling: { method: "even_spread", total_points: 100000, displayed_points: 2500, max_points: 2500 },
};
const sampledLine: ChartRecommendation = {
  ...base, chart_type: "line", title: "sampled line",
  sampling: { method: "min_max", total_points: 100000, displayed_points: 2498, max_points: 2500 },
};

describe("samplingNote", () => {
  it("is null when every point is drawn", () => {
    expect(samplingNote(full)).toBeNull();
    expect(samplingNote({ ...full, sampling: null })).toBeNull();
  });

  it("states how many points are shown, formatted, and that statistics use all rows", () => {
    const note = samplingNote(sampledScatter);
    expect(note).toContain("Showing 2,500 of 100,000 points");
    expect(note).toContain("evenly spread sample");
    expect(note).toContain("highest and lowest values are always included");
    expect(note).toContain("Statistics always use all rows.");
  });

  it("describes line charts by how peaks and dips are kept", () => {
    expect(samplingNote(sampledLine)).toContain("peaks and dips are preserved");
  });
});

describe("ChartsTab sampling note", () => {
  it("shows the note only on the charts that were reduced", () => {
    render(<ChartsTab available charts={[full, sampledScatter, sampledLine]} />);
    expect(screen.getAllByText(/Statistics always use all rows\./)).toHaveLength(2);
    expect(screen.getAllByText(/Showing 2,500 of 100,000 points/)).toHaveLength(1);
    expect(screen.getAllByText(/Why this chart:/)).toHaveLength(3);
  });
});

describe("chartRecommendationSchema compatibility", () => {
  it("accepts a chart from an older backend with no sampling field", () => {
    expect(chartRecommendationSchema.safeParse({ ...base, chart_type: "scatter" }).success).toBe(true);
  });

  it("accepts null (what the API sends when nothing was reduced) and a populated value", () => {
    expect(chartRecommendationSchema.safeParse({ ...base, chart_type: "line", sampling: null }).success).toBe(true);
    expect(chartRecommendationSchema.safeParse(sampledScatter).success).toBe(true);
  });
});
