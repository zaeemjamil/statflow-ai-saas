"""V1-hardening HTTP probe for the upload path: browser-facing Next.js origin -> rewrite proxy -> FastAPI.

    ../backend/.venv/bin/python scripts/e2e_upload_limits.py http://localhost:3000
    ../backend/.venv/bin/python scripts/e2e_upload_limits.py http://localhost:3000 http://127.0.0.1:8000

Run it against a REAL running stack (backend with its default limits: 25 MB CSV / 10 MB XLSX /
100,000 rows / 100 columns, frontend `next start` or `next dev`). With two arguments the identical
suite runs through the Next.js origin AND directly against FastAPI, so any difference between the two
columns is caused by the proxy (body truncation, size caps, timeouts), not by the backend.

It reports, for every case: expected vs actual HTTP status and error code, elapsed seconds, and the
fixture's real byte size. It is an HTTP test, not a browser test. It does NOT prove anything about
concurrent uploads, a production reverse proxy (nginx/ALB/...), or real network latency.

The last section deliberately sends a request whose Content-Length header claims 200 MB without
sending the body, to see whether the early Content-Length rejection works through each origin.
"""
import http.client
import io
import sys
import time
import urllib.parse
import uuid

import httpx
import numpy as np
import pandas as pd

MB = 1024 * 1024
CSV_LIMIT, XLSX_LIMIT, MAX_ROWS, MAX_COLS = 25 * MB, 10 * MB, 100_000, 100
SLOW_WARN_SECONDS = 25  # a proxy default of ~30 s would cut a request off soon after this

failed = total = 0
rows_out: list[tuple[str, str, str, str, str, str]] = []


def new_user(base: str) -> httpx.Client:
    c = httpx.Client(base_url=f"{base}/api/v1", timeout=300, follow_redirects=False)
    r = c.post("/auth/register", json={"email": f"limits-{uuid.uuid4().hex[:10]}@example.com", "password": "correct-horse-9", "full_name": "limits"})
    assert r.status_code == 201, r.text
    return c


def error_code(r: httpx.Response) -> str:
    try:
        return r.json().get("error", {}).get("code", "")
    except Exception:
        return f"<non-JSON {r.status_code}: {r.text[:60]!r}>"


def attempt(c: httpx.Client, origin: str, name: str, filename: str, payload: bytes, want_status: int, want_code: str = "", allow_early_close: bool = False) -> None:
    """Fresh project per case (one file per project), upload, compare.

    allow_early_close: a body far over the limit is rejected from its Content-Length alone, so the
    server may answer 413 and close the connection while the client is still sending; the client
    can then see a connection error (status 0 here) instead of the JSON body. Both are acceptable
    for that case and the output says which one happened."""
    global failed, total
    total += 1
    pid = c.post("/projects", json={"name": name[:60]}).json()["id"]
    t0 = time.perf_counter()
    try:
        r = c.post(f"/projects/{pid}/upload", files={"file": (filename, payload)})
        status, code = r.status_code, error_code(r) if r.status_code >= 400 else ""
    except httpx.HTTPError as exc:  # connection reset / timeout etc. is itself a finding
        status, code = 0, f"<{type(exc).__name__}>"
    elapsed = time.perf_counter() - t0
    ok = status == want_status and (not want_code or code == want_code)
    if allow_early_close and status == 0:
        ok, code = True, code + " (server closed early; client saw a connection error, not the JSON 413)"
    slow = " SLOW" if elapsed > SLOW_WARN_SECONDS else ""
    failed += 0 if ok else 1
    rows_out.append(("PASS" if ok else "FAIL", origin, name, f"{len(payload) / MB:.2f} MB", f"want {want_status} {want_code}".strip(), f"got {status} {code}".strip() + f" in {elapsed:.1f}s{slow}"))
    print(f"{'PASS' if ok else 'FAIL'} [{origin}] {name}: {len(payload) / MB:.2f} MB, want {want_status} {want_code}, got {status} {code}, {elapsed:.1f}s{slow}")


def csv_exact_size(target_bytes: int, rows: int) -> bytes:
    """A valid one-column CSV of exactly `target_bytes` bytes and `rows` data rows."""
    header = b"v\n"
    body_budget = target_bytes - len(header)
    base, extra = divmod(body_budget, rows)  # every row is `base` bytes incl. newline; `extra` rows get one more
    lines = [b"x" * (base - 1 + (1 if i < extra else 0)) + b"\n" for i in range(rows)]
    out = header + b"".join(lines)
    assert len(out) == target_bytes
    return out


def generic_xlsx(rows: int, cols: int) -> bytes:
    """Mixed id/date/categorical/numeric sheet. Uses openpyxl's write-only mode (a backend dependency,
    so no extra install) which streams rows instead of holding every cell in memory."""
    from openpyxl import Workbook

    rng = np.random.default_rng(7)
    ncat = max(1, (cols - 2) // 5)
    nnum = cols - 2 - ncat
    wb = Workbook(write_only=True)
    ws = wb.create_sheet("Sheet1")
    ws.append(["record_id", "event_date"] + [f"metric_{i + 1}" for i in range(nnum)] + [f"category_{i + 1}" for i in range(ncat)])
    dates = pd.date_range("2020-01-01", periods=rows, freq="min").strftime("%Y-%m-%d %H:%M:%S")
    nums = rng.normal(100, 15, (rows, nnum)).round(2)
    cats = rng.integers(0, 8, (rows, ncat))
    for i in range(rows):
        ws.append([f"R{i:08d}", dates[i], *nums[i].tolist(), *[f"grp{v}" for v in cats[i]]])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def suite(base: str, origin: str) -> None:
    c = new_user(base)
    small = pd.DataFrame({"a": range(10), "b": [x * 1.5 for x in range(10)]}).to_csv(index=False).encode()
    attempt(c, origin, "valid small csv", "ok.csv", small, 201)
    attempt(c, origin, "empty file (0 bytes)", "e.csv", b"", 422, "empty_file")
    attempt(c, origin, "header-only csv", "h.csv", b"a,b,c\n", 422, "no_data_rows")
    attempt(c, origin, "latin-1 csv", "l.csv", "n,c\nJosé,Zürich\n".encode("latin-1"), 422, "unsupported_encoding")
    attempt(c, origin, "unsupported .txt", "x.txt", b"a,b\n1,2\n", 422, "unsupported_file_type")
    attempt(c, origin, "malformed (ragged) csv", "r.csv", b"a,b,c\n1,2,3,4,5,6\n", 422, "unparseable_file")
    wide = pd.DataFrame({f"c{j}": [1, 2] for j in range(MAX_COLS + 1)}).to_csv(index=False).encode()
    attempt(c, origin, f"{MAX_COLS + 1} columns", "w.csv", wide, 422, "too_many_columns")
    ok_wide = pd.DataFrame({f"c{j}": [1, 2] for j in range(MAX_COLS)}).to_csv(index=False).encode()
    attempt(c, origin, f"exactly {MAX_COLS} columns", "w2.csv", ok_wide, 201)
    attempt(c, origin, f"{MAX_ROWS + 1:,} rows", "rows.csv", ("v\n" + "1\n" * (MAX_ROWS + 1)).encode(), 422, "too_many_rows")
    attempt(c, origin, f"exactly {MAX_ROWS:,} rows", "rows2.csv", ("v\n" + "1\n" * MAX_ROWS).encode(), 201)
    # Byte-size boundaries. These exercise the whole body path (proxy buffering/truncation included).
    attempt(c, origin, "CSV exactly at 25 MB limit", "big.csv", csv_exact_size(CSV_LIMIT, MAX_ROWS), 201)
    attempt(c, origin, "CSV 1 byte over 25 MB", "big2.csv", csv_exact_size(CSV_LIMIT + 1, MAX_ROWS), 413, "file_too_large")
    attempt(c, origin, "CSV 40 MB (far over)", "huge.csv", csv_exact_size(40 * MB, MAX_ROWS), 413, "file_too_large", allow_early_close=True)
    # XLSX is the slow path: this is the timeout probe. ~80k x 20 is ~9-10 MB.
    near = generic_xlsx(80_000, 20)
    print(f"  (xlsx fixture near the limit is {len(near) / MB:.2f} MB; limit is {XLSX_LIMIT / MB:.0f} MB)")
    attempt(c, origin, "XLSX just under 10 MB limit (timeout probe)", "near.xlsx", near, 201 if len(near) <= XLSX_LIMIT else 413)
    over = generic_xlsx(100_000, 20)
    attempt(c, origin, "XLSX over 10 MB limit", "over.xlsx", over, 413, "file_too_large")


def early_content_length_probe(base: str, origin: str) -> None:
    """Claim a 200 MB body but send none. A working early check answers 413 immediately."""
    global failed, total
    total += 1
    u = urllib.parse.urlparse(base)
    conn = http.client.HTTPConnection(u.hostname, u.port or 80, timeout=10)
    t0 = time.perf_counter()
    try:
        conn.putrequest("POST", f"/api/v1/projects/{uuid.uuid4()}/upload")
        conn.putheader("Content-Type", "multipart/form-data; boundary=probe")
        conn.putheader("Content-Length", str(200 * MB))
        conn.endheaders()
        resp = conn.getresponse()
        status = resp.status
        body = resp.read(300).decode(errors="replace")
        ok = status == 413 and "file_too_large" in body
        detail = f"got {status} in {time.perf_counter() - t0:.2f}s"
    except Exception as exc:  # timeout waiting for the response = the early check did NOT answer
        ok, detail = False, f"no response within 10 s ({type(exc).__name__}); the request was waiting for the body"
    finally:
        conn.close()
    failed += 0 if ok else 1
    rows_out.append(("PASS" if ok else "FAIL", origin, "early Content-Length 413 (200 MB declared, 0 sent)", "-", "want 413 file_too_large", detail))
    print(f"{'PASS' if ok else 'FAIL'} [{origin}] early Content-Length rejection: {detail}")


def main() -> None:
    origins = [("next", sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:3000")]
    if len(sys.argv) > 2:
        origins.append(("direct", sys.argv[2].rstrip("/")))
    for origin, base in origins:
        print(f"\n=== {origin}: {base} ===")
        suite(base, origin)
        early_content_length_probe(base, origin)
    print(f"\n{total - failed}/{total} passed")
    if failed:
        print("FAILED cases (compare the 'next' and 'direct' rows: a difference points at the proxy):")
        for row in rows_out:
            if row[0] == "FAIL":
                print("  ", " | ".join(row[1:]))
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
