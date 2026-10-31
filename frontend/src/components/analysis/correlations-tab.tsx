import { EmptyBlock } from "@/components/ui/state";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber, formatStat, humanizeCode } from "@/lib/format";
import type { CorrelationResult } from "@/lib/schemas";

function cellStyle(value: number | null) {
  if (value == null) return undefined;
  // Shading only encodes the backend's own |r|; it adds no numbers of its own.
  return { backgroundColor: `rgba(79, 70, 229, ${(Math.min(Math.abs(value), 1) * 0.35).toFixed(2)})` };
}

export function CorrelationsTab({ result }: { result: CorrelationResult }) {
  if (!result.available) {
    return (
      <EmptyBlock
        title="Correlations are not available for this dataset"
        hint={result.reason ? humanizeCode(result.reason) + "." : "At least two numeric columns are needed."}
      />
    );
  }
  const names = Object.keys(result.matrix);
  return (
    <div className="flex flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Pearson correlations</CardTitle>
          <CardDescription>
            {formatNumber(result.numeric_column_count)} numeric columns. Correlation shows association, not causation.
          </CardDescription>
        </CardHeader>
        <CardContent className="flex flex-col gap-4">
          <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
            {[
              { label: "Strongest positive", pair: result.strongest_positive },
              { label: "Strongest negative", pair: result.strongest_negative },
            ].map(({ label, pair }) => (
              <div key={label} className="rounded-lg border border-border p-4">
                <p className="text-xs text-muted-foreground">{label}</p>
                {pair ? (
                  <p className="mt-1 text-sm">
                    <span className="font-medium">{pair.column_a}</span> &amp; <span className="font-medium">{pair.column_b}</span>{" "}
                    <span className="tabular-nums">(r = {formatStat(pair.correlation)}, {pair.strength})</span>
                  </p>
                ) : (
                  <p className="mt-1 text-sm text-muted-foreground">None found</p>
                )}
              </div>
            ))}
          </div>

          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full min-w-[32rem] text-left text-sm">
              <caption className="sr-only">Column pairs ranked by correlation strength</caption>
              <thead className="bg-muted text-xs text-muted-foreground">
                <tr>
                  <th scope="col" className="px-3 py-2 font-medium">Column A</th>
                  <th scope="col" className="px-3 py-2 font-medium">Column B</th>
                  <th scope="col" className="px-3 py-2 text-right font-medium">r</th>
                  <th scope="col" className="px-3 py-2 font-medium">Strength</th>
                  <th scope="col" className="px-3 py-2 font-medium">Direction</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {result.pairs.map((p) => (
                  <tr key={`${p.column_a}|${p.column_b}`}>
                    <th scope="row" className="px-3 py-2 font-medium">{p.column_a}</th>
                    <td className="px-3 py-2">{p.column_b}</td>
                    <td className="px-3 py-2 text-right tabular-nums">{formatStat(p.correlation)}</td>
                    <td className="px-3 py-2 capitalize">{p.strength}</td>
                    <td className="px-3 py-2 capitalize">{p.direction}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {result.undefined_pair_count > 0 ? (
            <p className="text-xs text-muted-foreground">
              {formatNumber(result.undefined_pair_count)} pair(s) have no defined correlation (for example, one column is constant) and are shown as a dash.
            </p>
          ) : null}
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Correlation matrix</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="overflow-x-auto rounded-lg border border-border">
            <table className="w-full text-sm">
              <caption className="sr-only">Correlation matrix</caption>
              <thead className="bg-muted text-xs text-muted-foreground">
                <tr>
                  <td className="px-3 py-2" />
                  {names.map((n) => (
                    <th key={n} scope="col" className="px-3 py-2 text-right font-medium">{n}</th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {names.map((row) => (
                  <tr key={row}>
                    <th scope="row" className="px-3 py-2 font-medium">{row}</th>
                    {names.map((col) => {
                      const v = result.matrix[row]?.[col] ?? null;
                      return (
                        <td key={col} className="px-3 py-2 text-right tabular-nums" style={cellStyle(v)}>{formatStat(v)}</td>
                      );
                    })}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
