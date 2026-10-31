import { EmptyBlock } from "@/components/ui/state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber, formatPercent, formatStat, humanizeCode } from "@/lib/format";
import type { OutlierResult } from "@/lib/schemas";

export function OutliersTab({ result }: { result: OutlierResult }) {
  if (result.columns.length === 0) {
    return <EmptyBlock title="No numeric columns" hint="Outlier detection only applies to numeric columns." />;
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Outliers (IQR method)</CardTitle>
        <CardDescription>
          A value is flagged when it falls more than {formatStat(result.iqr_multiplier)} × IQR below Q1 or above Q3. Flagged values are not removed from your data.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-4">
        <div className="grid grid-cols-2 gap-3">
          <div className="rounded-lg border border-border p-4">
            <p className="text-xs text-muted-foreground">Total outliers flagged</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{formatNumber(result.total_outlier_count)}</p>
          </div>
          <div className="rounded-lg border border-border p-4">
            <p className="text-xs text-muted-foreground">Columns with outliers</p>
            <p className="mt-1 text-2xl font-semibold tabular-nums">{formatNumber(result.columns_with_outliers)}</p>
          </div>
        </div>

        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[44rem] text-left text-sm">
            <caption className="sr-only">Outliers per numeric column</caption>
            <thead className="bg-muted text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Column</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Observations</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Lower bound</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Upper bound</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Outliers</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Share</th>
                <th scope="col" className="px-3 py-2 font-medium">Row positions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {result.columns.map((c) =>
                c.detected ? (
                  <tr key={c.column}>
                    <th scope="row" className="px-3 py-2 font-medium">{c.column}</th>
                    <td className="px-3 py-2 text-right tabular-nums">{formatNumber(c.observation_count)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatStat(c.lower_bound)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatStat(c.upper_bound)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatNumber(c.outlier_count)}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatPercent(c.outlier_percentage)}</td>
                    <td className="max-w-[16rem] px-3 py-2 text-xs">
                      {c.outlier_indices.length === 0 ? (
                        "—"
                      ) : (
                        <>
                          {c.outlier_indices.join(", ")}
                          {c.outlier_indices_truncated ? ` … (first ${c.outlier_indices.length} of ${formatNumber(c.outlier_count)})` : ""}
                        </>
                      )}
                    </td>
                  </tr>
                ) : (
                  <tr key={c.column}>
                    <th scope="row" className="px-3 py-2 font-medium">{c.column}</th>
                    <td colSpan={6} className="px-3 py-2 text-muted-foreground">
                      Not checked: {c.reason ? humanizeCode(c.reason).toLowerCase() : "not enough data"}.
                    </td>
                  </tr>
                ),
              )}
            </tbody>
          </table>
        </div>
        <p className="text-xs text-muted-foreground">Row positions are 0-based positions in the cleaned dataset (the first row is 0).</p>
      </CardContent>
    </Card>
  );
}
