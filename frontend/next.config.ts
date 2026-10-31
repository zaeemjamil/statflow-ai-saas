import type { NextConfig } from "next";

// The browser only ever talks to this origin. /api/v1/* is proxied to the
// FastAPI backend, so the HttpOnly session cookie is first-party and no
// CORS or SameSite=none setup is needed.
const BACKEND_URL = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

// Next.js buffers the request body of every proxied request in memory and, past its
// default of 10 MB, silently forwards a TRUNCATED body: a 10-25 MB upload then
// stalls and fails with a non-JSON 500 instead of reaching the backend's exact
// limit check. The buffer must therefore cover the largest accepted upload plus
// multipart framing. The backend itself admits up to (largest per-type limit +
// 1 MiB) before answering 413; PROXY_SLACK_MB (2) keeps this buffer above that.
// The sizes come from the same env vars the UI uses for its limits, so changing
// the backend limits means changing them in one place on the frontend as well.
const PROXY_SLACK_MB = 2;
function positiveMb(raw: string | undefined, fallback: number): number {
  const n = Number(raw);
  return Number.isFinite(n) && n > 0 ? n : fallback;
}
const PROXY_MAX_BODY_BYTES = Math.ceil(
  (Math.max(
    positiveMb(process.env.NEXT_PUBLIC_MAX_CSV_UPLOAD_MB, 25),
    positiveMb(process.env.NEXT_PUBLIC_MAX_XLSX_UPLOAD_MB, 10),
  ) +
    PROXY_SLACK_MB) *
    1024 *
    1024,
);

const nextConfig: NextConfig = {
  cacheComponents: true,
  experimental: {
    proxyClientMaxBodySize: PROXY_MAX_BODY_BYTES,
  },
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
  async rewrites() {
    return [
      {
        source: "/api/v1/:path*",
        destination: `${BACKEND_URL}/api/v1/:path*`,
      },
    ];
  },
};

export default nextConfig;
