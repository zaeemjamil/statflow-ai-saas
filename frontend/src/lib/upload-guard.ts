import { MAX_CSV_MB, MAX_XLSX_MB } from "@/lib/upload-limits";

/**
 * Early rejection of oversized uploads at the Next.js origin.
 *
 * Why this exists: Next buffers a proxied request body (see `proxyClientMaxBodySize`
 * in next.config.ts) and forwards at most that much. When the body is bigger, the
 * backend's own early check answers 413 from the Content-Length alone and closes the
 * connection while Next is still writing, which Next reports as a bare, non-JSON 500.
 * Answering 413 here, with the same JSON shape as the backend, avoids that.
 *
 * Not the authoritative check: the backend still enforces the exact per-type limits.
 * This mirrors the backend's early threshold (largest per-type limit + 1 MiB of
 * multipart framing) so a file the backend would accept is never rejected here.
 */
const MiB = 1024 * 1024;
const MULTIPART_OVERHEAD_BYTES = 1 * MiB;
const UPLOAD_PATH = /^\/api\/v1\/projects\/[^/]+\/upload\/?$/;

export const UPLOAD_PROXY_LIMIT_MB = Math.max(MAX_CSV_MB, MAX_XLSX_MB);

export function isUploadRequest(pathname: string, method: string): boolean {
  return method === "POST" && UPLOAD_PATH.test(pathname);
}

/** True when the declared Content-Length is over the early threshold. A missing or
 * malformed header is not judged here (the backend and its handler still bound it). */
export function exceedsUploadLimit(contentLength: string | null): boolean {
  if (contentLength === null || !/^\d+$/.test(contentLength.trim())) return false;
  return Number(contentLength) > UPLOAD_PROXY_LIMIT_MB * MiB + MULTIPART_OVERHEAD_BYTES;
}

/** Same body as the backend's early 413 (code `file_too_large`). */
export function tooLargeResponseBody() {
  const limitMb = Math.floor(UPLOAD_PROXY_LIMIT_MB);
  return {
    error: {
      code: "file_too_large",
      message: `This upload is larger than the ${limitMb} MB maximum file size.`,
      details: { limit_bytes: limitMb * MiB, limit_mb: limitMb },
    },
  };
}
