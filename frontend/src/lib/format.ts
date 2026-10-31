export function formatBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function formatNumber(n: number): string {
  return new Intl.NumberFormat("en-US").format(n);
}

export function formatDate(iso: string): string {
  return new Intl.DateTimeFormat("en-US", { dateStyle: "medium", timeStyle: "short" }).format(new Date(iso));
}

export function formatPercent(n: number): string {
  return `${n.toFixed(n % 1 === 0 ? 0 : 1)}%`;
}

/** Statistic values can legitimately be null (e.g. std of one value); show a dash, never 0. */
export function formatStat(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return "—";
  if (n !== 0 && Math.abs(n) < 0.0001) return n.toExponential(2);
  return new Intl.NumberFormat("en-US", { maximumFractionDigits: Math.abs(n) >= 1000 ? 2 : 4 }).format(n);
}

/** Turns backend reason codes such as "no_non_missing_values" into readable text. */
export function humanizeCode(code: string): string {
  const text = code.replace(/_/g, " ").trim();
  return text.charAt(0).toUpperCase() + text.slice(1);
}
