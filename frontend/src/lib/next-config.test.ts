import { describe, expect, it } from "vitest";

import nextConfig from "../../next.config";

const MiB = 1024 * 1024;

describe("next.config proxy body buffer", () => {
  it("covers the largest upload (25 MB CSV) plus the backend's 1 MiB multipart allowance", () => {
    const buffer = nextConfig.experimental?.proxyClientMaxBodySize;
    expect(typeof buffer).toBe("number");
    // The backend answers 413 only above limit + 1 MiB, so anything it would still
    // accept must fit in the buffer unmodified.
    expect(buffer as number).toBeGreaterThanOrEqual(25 * MiB + 1 * MiB);
  });

  it("still proxies /api/v1 to the backend", async () => {
    const rules = await nextConfig.rewrites?.();
    expect(JSON.stringify(rules)).toContain("/api/v1/:path*");
  });
});
