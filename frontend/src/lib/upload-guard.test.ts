import { describe, expect, it } from "vitest";

import {
  exceedsUploadLimit,
  isUploadRequest,
  tooLargeResponseBody,
  UPLOAD_PROXY_LIMIT_MB,
} from "@/lib/upload-guard";

const MiB = 1024 * 1024;

describe("upload guard", () => {
  it("only matches POST to the project upload path", () => {
    expect(isUploadRequest("/api/v1/projects/abc/upload", "POST")).toBe(true);
    expect(isUploadRequest("/api/v1/projects/abc/upload/", "POST")).toBe(true);
    expect(isUploadRequest("/api/v1/projects/abc/upload", "GET")).toBe(false);
    expect(isUploadRequest("/api/v1/projects/abc/analyze", "POST")).toBe(false);
    expect(isUploadRequest("/api/v1/projects/a/b/upload", "POST")).toBe(false);
  });

  it("uses the largest configured upload limit (25 MB by default)", () => {
    expect(UPLOAD_PROXY_LIMIT_MB).toBe(25);
  });

  it("never rejects a body the backend would still accept (limit + 1 MiB framing)", () => {
    expect(exceedsUploadLimit(String(25 * MiB))).toBe(false);
    expect(exceedsUploadLimit(String(26 * MiB))).toBe(false);
    expect(exceedsUploadLimit(String(26 * MiB + 1))).toBe(true);
    expect(exceedsUploadLimit(String(200 * MiB))).toBe(true);
  });

  it("does not judge a missing or malformed Content-Length", () => {
    expect(exceedsUploadLimit(null)).toBe(false);
    expect(exceedsUploadLimit("abc")).toBe(false);
    expect(exceedsUploadLimit("-5")).toBe(false);
  });

  it("builds the same error shape as the backend's 413", () => {
    expect(tooLargeResponseBody()).toEqual({
      error: {
        code: "file_too_large",
        message: "This upload is larger than the 25 MB maximum file size.",
        details: { limit_bytes: 25 * MiB, limit_mb: 25 },
      },
    });
  });
});
