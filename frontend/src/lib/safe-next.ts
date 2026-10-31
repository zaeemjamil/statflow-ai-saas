/**
 * Post-login redirect target validation (open-redirect protection).
 *
 * Only same-origin, path-absolute targets are honoured. Anything else falls
 * back to `fallback`. Checks, all of which must pass:
 *
 *  1. The raw value is a string that starts with a single "/".
 *  2. It has no control characters (tab, CR, LF, NUL, DEL, ...). Browsers strip
 *     tab/CR/LF while parsing URLs, so "/\t/evil.com" would become "//evil.com".
 *  3. It has no backslash. Browsers treat "\" like "/" in http(s) URLs, so
 *     "/\evil.com" means "//evil.com".
 *  4. The same checks hold after percent-decoding (repeated, so "%5C" and the
 *     double-encoded "%255C" are caught), and decoding must succeed.
 *  5. Resolved against a fixed dummy origin by the standard URL parser, the
 *     result must stay on that origin.
 *
 * The original (still encoded) path is returned unchanged when it passes.
 */
export const DEFAULT_NEXT = "/dashboard";

const MAX_DECODE_ROUNDS = 5;
const DUMMY_ORIGIN = "https://same-origin.invalid";

function hasControlChar(text: string): boolean {
  for (let i = 0; i < text.length; i += 1) {
    const code = text.charCodeAt(i);
    if (code <= 0x1f || (code >= 0x7f && code <= 0x9f)) return true;
  }
  return false;
}

function isUnsafeForm(text: string): boolean {
  return (
    !text.startsWith("/") ||
    text.startsWith("//") ||
    text.includes("\\") ||
    hasControlChar(text)
  );
}

export function safeNextPath(raw: string | null | undefined, fallback: string = DEFAULT_NEXT): string {
  if (typeof raw !== "string" || raw === "") return fallback;
  if (isUnsafeForm(raw)) return fallback;

  let current = raw;
  for (let round = 0; round < MAX_DECODE_ROUNDS; round += 1) {
    let decoded: string;
    try {
      decoded = decodeURIComponent(current);
    } catch {
      return fallback; // malformed percent-encoding
    }
    if (decoded === current) break;
    if (isUnsafeForm(decoded)) return fallback;
    current = decoded;
  }

  try {
    const resolved = new URL(raw, DUMMY_ORIGIN);
    if (resolved.origin !== DUMMY_ORIGIN) return fallback;
  } catch {
    return fallback;
  }
  return raw;
}
