import { describe, expect, it } from "vitest";
import { DEFAULT_NEXT, safeNextPath } from "./safe-next";

// Values as they arrive from URLSearchParams.get("next") (already decoded once).
const MALICIOUS: Array<[string, string | null | undefined]> = [
  ["encoded backslash: /%5Cevil.com", "/%5Cevil.com"],
  ["encoded backslash, lower case: /%5cevil.com", "/%5cevil.com"],
  ["raw backslash: /\\evil.com", "/\\evil.com"],
  ["double slash: //evil.com", "//evil.com"],
  ["encoded double slash: /%2Fevil.com", "/%2Fevil.com"],
  ["double-encoded backslash: /%255Cevil.com", "/%255Cevil.com"],
  ["triple-encoded backslash", "/%25255Cevil.com"],
  ["raw tab: /\\t/evil.com", "/\t/evil.com"],
  ["encoded tab: /%09/evil.com", "/%09/evil.com"],
  ["encoded tab before backslash: /%09%5Cevil.com", "/%09%5Cevil.com"],
  ["raw newline: /\\n/evil.com", "/\n/evil.com"],
  ["encoded newline: /%0a/evil.com", "/%0a/evil.com"],
  ["encoded carriage return: /%0D/evil.com", "/%0D/evil.com"],
  ["encoded NUL: /%00/evil.com", "/%00/evil.com"],
  ["encoded DEL: /%7F/evil.com", "/%7F/evil.com"],
  ["control char later in the path", "/dashboard\u0001"],
  ["tab after first slash then slash", "/\t/\t/evil.com"],
  ["absolute http URL", "http://evil.com"],
  ["absolute https URL", "https://evil.com/x"],
  ["scheme-relative with backslashes", "\\\\evil.com"],
  ["javascript: scheme", "javascript:alert(1)"],
  ["data: scheme", "data:text/html,<script>alert(1)</script>"],
  ["no leading slash", "evil.com"],
  ["malformed percent-encoding", "/%E0%A4%A"],
  ["empty string", ""],
  ["null", null],
  ["undefined", undefined],
];

const VALID = [
  "/dashboard",
  "/projects",
  "/projects/abc-123",
  "/projects/abc-123/analysis",
  "/projects/abc-123?tab=ai",
  "/projects/abc-123#charts",
  "/projects/new",
  "/projects/a%20b",
  "/projects/%C3%A9",
  "/settings?x=1&y=2",
  "/",
];

describe("safeNextPath", () => {
  it.each(MALICIOUS)("rejects %s", (_label, value) => {
    expect(safeNextPath(value)).toBe(DEFAULT_NEXT);
  });

  it.each(VALID)("keeps the internal path %s unchanged", (value) => {
    expect(safeNextPath(value)).toBe(value);
  });

  it("uses a caller-supplied fallback", () => {
    expect(safeNextPath("//evil.com", "/home")).toBe("/home");
  });

  it("never returns a value that resolves off-origin", () => {
    for (const [, value] of MALICIOUS) {
      const result = safeNextPath(value);
      const url = new URL(result, "https://same-origin.invalid");
      expect(url.origin).toBe("https://same-origin.invalid");
    }
  });
});
