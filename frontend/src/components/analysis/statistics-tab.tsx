import { EmptyBlock } from "@/components/ui/state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber, formatStat } from "@/lib/format";
import type { DescriptiveStatistics } from "@/lib/schemas";

const COLS = ["mean", "median", "std", "min", "q1", "q3", "max", "iqr"] as const;
const HEAD: Record<(typeof COLS)[number], string> = { mean: "Mean", median: "Median", std: "Std dev", min: "Min", q1: "Q1", q3: "Q3", max: "Max", iqr: "IQR" };

export function StatisticsTab({ statistics }: { statistics: DescriptiveStatistics }) {
  if (statistics.columns.length === 0) {
    return <EmptyBlock title="No numeric columns" hint="Descriptive statistics are only calculated for numeric columns, and this dataset has none." />;
  }
  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-lg">Descriptive statistics</CardTitle>
        <CardDescription>
          {formatNumber(statistics.numeric_column_count)} numeric column(s), calculated on the cleaned data.
        </CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-3">
        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[48rem] text-left text-sm">
            <caption className="sr-only">Descriptive statistics per numeric column</caption>
            <thead className="bg-muted text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Column</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Count</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Missing</th>
                {COLS.map((c) => (
                  <th key={c} scope="col" className="px-3 py-2 text-right font-medium">{HEAD[c]}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {statistics.columns.map((row) => (
                <tr key={row.column}>
                  <th scope="row" className="px-3 py-2 font-medium">{row.column}</th>
                  <td className="px-3 py-2 text-right tabular-nums">{formatNumber(row.count)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatNumber(row.missing_count)}</td>
                  {COLS.map((c) => (
                    <td key={c} className="px-3 py-2 text-right tabular-nums">{formatStat(row[c])}</td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {statistics.skipped_columns.length > 0 ? (
          <p className="text-xs text-muted-foreground">Not shown (not numeric): {statistics.skipped_columns.join(", ")}.</p>
        ) : null}
        <p className="text-xs text-muted-foreground">A dash means the value can&apos;t be calculated (for example, a standard deviation needs at least two values).</p>
      </CardContent>
    </Card>
  );
}
