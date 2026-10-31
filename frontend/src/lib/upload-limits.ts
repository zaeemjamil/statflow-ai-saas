import { formatBytes } from "@/lib/format";

/**
 * Client-side pre-check for uploads. This is a courtesy only: it saves the
 * user from uploading a file the server is certain to refuse. The backend
 * re-validates everything (size per type, rows, columns, encoding, content)
 * and is the only authority - these numbers must never be trusted as the rule.
 *
 * The defaults mirror the backend's V1 defaults. If an operator changes the
 * backend limits, set the matching NEXT_PUBLIC_* variables at build time;
 * if they drift, the worst case is that this check is stricter or looser
 * than the server, and the server's response is what the user sees.
 */
const MB = 1024 * 1024;

function positiveNumber(raw: string | undefined, fallback: number): number {
  const n = Number(raw);
  return raw !== undefined && Number.isFinite(n) && n > 0 ? n : fallback;
}

// Each NEXT_PUBLIC_* variable must be referenced as a literal property access
// so the bundler can inline it.
export const MAX_CSV_MB = positiveNumber(process.env.NEXT_PUBLIC_MAX_CSV_UPLOAD_MB, 25);
export const MAX_XLSX_MB = positiveNumber(process.env.NEXT_PUBLIC_MAX_XLSX_UPLOAD_MB, 10);
export const MAX_ROWS = positiveNumber(process.env.NEXT_PUBLIC_MAX_DATASET_ROWS, 100_000);
export const MAX_COLUMNS = positiveNumber(process.env.NEXT_PUBLIC_MAX_DATASET_COLUMNS, 100);

export const SUPPORTED_FORMATS_MESSAGE = "Only .csv and .xlsx files are supported.";

/** One line describing the limits, shown under the upload title. */
export function describeUploadLimits(): string {
  return (
    `CSV up to ${MAX_CSV_MB} MB, Excel (.xlsx) up to ${MAX_XLSX_MB} MB; ` +
    `at most ${new Intl.NumberFormat("en-US").format(MAX_ROWS)} rows and ${MAX_COLUMNS} columns.`
  );
}

/** Returns a user-facing problem, or null if the file may be sent to the server. */
export function checkUploadFile(file: { name: string; size: number }): string | null {
  const match = /\.(csv|xlsx)$/i.exec(file.name);
  if (!match) return SUPPORTED_FORMATS_MESSAGE;

  if (file.size === 0) return "This file is empty.";

  const isCsv = match[1].toLowerCase() === "csv";
  const limitMb = isCsv ? MAX_CSV_MB : MAX_XLSX_MB;
  if (file.size > limitMb * MB) {
    const label = isCsv ? "CSV" : "Excel (.xlsx)";
    return `This ${label} file is ${formatBytes(file.size)}, over the ${limitMb} MB limit for ${label} files.`;
  }
  return null;
}
