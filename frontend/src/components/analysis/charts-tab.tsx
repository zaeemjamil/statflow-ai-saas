"use client";

import { Bar, BarChart, CartesianGrid, Line, LineChart, ResponsiveContainer, Scatter, ScatterChart, Tooltip, XAxis, YAxis } from "recharts";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { EmptyBlock } from "@/components/ui/state";
import { formatStat, humanizeCode } from "@/lib/format";
import type { ChartRecommendation } from "@/lib/schemas";

const COLOR = "#4f46e5";
const TICK = { fontSize: 11, fill: "#64748b" };

function asNumber(v: unknown): number | null {
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}
function asText(v: unknown): string {
  return v == null ? "" : String(v);
}
const tick = (v: unknown) => (typeof v === "number" ? formatStat(v) : asText(v));

/** Renders ONLY the points the backend returned; nothing is computed or sampled here.
 *  (For large datasets the backend has already reduced scatter/line points; see `samplingNote`.) */
export function ChartBody({ chart }: { chart: ChartRecommendation }) {
  const { chart_type: type, data } = chart;
  const margin = { top: 8, right: 12, bottom: 8, left: 4 };

  if (data.length === 0) return <p className="text-sm text-muted-foreground">No data points were returned for this chart.</p>;

  let body: React.ReactElement;
  if (type === "scatter") {
    const pts = data.map((d) => ({ x: asNumber(d.x), y: asNumber(d.y) })).filter((d): d is { x: number; y: number } => d.x != null && d.y != null);
    body = (
      <ScatterChart margin={margin}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis type="number" dataKey="x" name={chart.x_column ?? "x"} tick={TICK} tickFormatter={tick} domain={["auto", "auto"]} />
        <YAxis type="number" dataKey="y" name={chart.y_column ?? "y"} tick={TICK} tickFormatter={tick} width={56} domain={["auto", "auto"]} />
        <Tooltip cursor={{ strokeDasharray: "3 3" }} formatter={(v) => tick(v)} />
        <Scatter data={pts} fill={COLOR} />
      </ScatterChart>
    );
  } else if (type === "line") {
    const pts = data.map((d) => ({ x: asText(d.x), y: asNumber(d.y) }));
    body = (
      <LineChart data={pts} margin={margin}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="x" tick={TICK} tickFormatter={(v) => asText(v).slice(0, 10)} minTickGap={32} />
        <YAxis tick={TICK} tickFormatter={tick} width={56} />
        <Tooltip formatter={(v) => tick(v)} />
        <Line type="monotone" dataKey="y" stroke={COLOR} dot={false} strokeWidth={2} name={chart.y_column ?? "y"} />
      </LineChart>
    );
  } else if (type === "histogram") {
    const bins = data.map((d) => {
      const s = asNumber(d.bin_start);
      const e = asNumber(d.bin_end);
      return { label: s != null && e != null ? `${formatStat(s)}–${formatStat(e)}` : "", count: asNumber(d.count) ?? 0 };
    });
    body = (
      <BarChart data={bins} margin={margin} barCategoryGap={1}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="label" tick={TICK} minTickGap={24} />
        <YAxis tick={TICK} allowDecimals={false} width={40} />
        <Tooltip />
        <Bar dataKey="count" fill={COLOR} name="Count" />
      </BarChart>
    );
  } else {
    const key = type === "count" ? "count" : "y";
    const rows = data.map((d) => ({ x: asText(d.x), value: asNumber(d[key]) }));
    body = (
      <BarChart data={rows} margin={margin}>
        <CartesianGrid strokeDasharray="3 3" />
        <XAxis dataKey="x" tick={TICK} interval={0} tickFormatter={(v) => (asText(v).length > 10 ? `${asText(v).slice(0, 9)}…` : asText(v))} />
        <YAxis tick={TICK} tickFormatter={tick} width={56} allowDecimals={type !== "count"} />
        <Tooltip formatter={(v) => tick(v)} />
        <Bar dataKey="value" fill={COLOR} name={type === "count" ? "Count" : (chart.y_column ?? "Value")} />
      </BarChart>
    );
  }

  return (
    <div role="img" aria-label={chart.title} className="h-64 w-full">
      <ResponsiveContainer width="100%" height="100%">
        {body}
      </ResponsiveContainer>
    </div>
  );
}

const WHOLE = new Intl.NumberFormat("en-US");

/** Tells the user a chart shows a subset of rows. Null when every point is drawn. */
export function samplingNote(c: ChartRecommendation): string | null {
  const s = c.sampling;
  if (!s) return null;
  const counts = `Showing ${WHOLE.format(s.displayed_points)} of ${WHOLE.format(s.total_points)} points`;
  const how =
    s.method === "min_max"
      ? "each section of the series keeps its highest and lowest value, so peaks and dips are preserved"
      : "an evenly spread sample; the highest and lowest values are always included";
  return `${counts} (${how}). Statistics always use all rows.`;
}

function axesNote(c: ChartRecommendation) {
  const parts: string[] = [];
  if (c.x_column) parts.push(`X: ${c.x_column}`);
  if (c.y_column) parts.push(`Y: ${c.y_column}`);
  if (c.aggregation) parts.push(`Aggregation: ${c.aggregation}`);
  if (c.bins) parts.push(`${c.bins} bins`);
  return parts.join(" · ");
}

export function ChartsTab({ charts, available, reason }: { charts: ChartRecommendation[]; available: boolean; reason?: string | null }) {
  if (!available || charts.length === 0) {
    return (
      <EmptyBlock
        title="No charts could be recommended"
        hint={reason ? humanizeCode(reason) + "." : "This dataset has no column combinations the chart engine can plot."}
      />
    );
  }
  return (
    <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
      {charts.map((c, i) => (
        <Card key={`${c.chart_type}-${c.title}-${i}`}>
          <CardHeader className="p-5 pb-2">
            <CardTitle className="text-base">{c.title}</CardTitle>
            <CardDescription>{axesNote(c)}</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-col gap-3 p-5 pt-0">
            <ChartBody chart={c} />
            {samplingNote(c) && <p className="text-xs text-muted-foreground">{samplingNote(c)}</p>}
            <p className="text-xs text-muted-foreground">
              <span className="font-medium">Why this chart:</span> {c.reason}
            </p>
          </CardContent>
        </Card>
      ))}
    </div>
  );
}
