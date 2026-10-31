import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { formatNumber, formatPercent } from "@/lib/format";
import type { DatasetProfile, ImportNote } from "@/lib/schemas";

function Metric({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-border p-4">
      <p className="text-xs text-muted-foreground">{label}</p>
      <p className="mt-1 text-2xl font-semibold tabular-nums">{formatNumber(value)}</p>
    </div>
  );
}

function range(min?: number | null, max?: number | null) {
  if (min == null || max == null) return "—";
  return `${formatNumber(min)} – ${formatNumber(max)}`;
}

function ImportNotes({ notes }: { notes: ImportNote[] }) {
  if (notes.length === 0) return null;
  return (
    <section aria-labelledby="import-notes-heading" className="flex flex-col gap-2">
      <h3 id="import-notes-heading" className="text-sm font-semibold">
        Things to check in your data ({notes.length})
      </h3>
      <ul className="flex flex-col gap-2">
        {notes.map((note) => (
          <li
            key={note.code}
            data-severity={note.severity}
            className="rounded-lg border border-border p-3 text-sm"
          >
            <span className="font-medium">{note.severity === "warning" ? "Warning: " : "Note: "}</span>
            {note.message}
          </li>
        ))}
      </ul>
    </section>
  );
}

export function ProfileView({ profile }: { profile: DatasetProfile }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Dataset profile</CardTitle>
        <CardDescription>Computed on the server when the file was uploaded.</CardDescription>
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Metric label="Rows" value={profile.row_count} />
          <Metric label="Columns" value={profile.column_count} />
          <Metric label="Missing values" value={profile.total_missing_values} />
          <Metric label="Duplicate rows" value={profile.duplicate_row_count} />
          <Metric label="Numeric columns" value={profile.numeric_column_count} />
          <Metric label="Categorical columns" value={profile.categorical_column_count} />
          <Metric label="Date columns" value={profile.date_column_count} />
        </div>

        <ImportNotes notes={profile.import_notes ?? []} />

        <div className="overflow-x-auto rounded-lg border border-border">
          <table className="w-full min-w-[40rem] text-left text-sm">
            <caption className="sr-only">Per-column profile</caption>
            <thead className="bg-muted text-xs text-muted-foreground">
              <tr>
                <th scope="col" className="px-3 py-2 font-medium">Column</th>
                <th scope="col" className="px-3 py-2 font-medium">Type</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Missing</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Unique</th>
                <th scope="col" className="px-3 py-2 text-right font-medium">Range</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {profile.columns.map((c) => (
                <tr key={c.name}>
                  <th scope="row" className="px-3 py-2 font-medium">{c.name}</th>
                  <td className="px-3 py-2 capitalize">{c.classification}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {formatNumber(c.missing_count)} ({formatPercent(c.missing_percentage)})
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">{formatNumber(c.unique_count)}</td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {c.classification === "numeric" ? range(c.min_value, c.max_value) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </CardContent>
    </Card>
  );
}
