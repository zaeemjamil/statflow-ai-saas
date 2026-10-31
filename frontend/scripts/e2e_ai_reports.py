"""Phase 9-10 + hardening HTTP e2e through the public origin (proxy -> API -> PostgreSQL).

    python scripts/e2e_ai_reports.py http://localhost:8080

The BACKEND must be started with  OPENROUTER_API_KEY=sk-e2e-key  and
OPENROUTER_BASE_URL=http://127.0.0.1:9999/v1  (ENVIRONMENT must not be 'production': the
production validator insists on https for the AI URL). This script runs the stub "AI
provider" on port 9999 itself, so nothing leaves the machine, and checks what that
provider was actually sent.
"""

import io
import json
import socket
import sys
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import numpy as np
import pandas as pd
from pypdf import PdfReader

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:8080"
API = f"{BASE}/api/v1"
KEY = "sk-e2e-key"
REAL_NAMES = ["turbine_output_kw", "wind_speed_ms", "blade_pitch_deg", "wind_farm_site"]
SITES = ["Heidelberg-Nord", "Kaiserslautern-Sued", "Zwickau-West", "Hof-Ost"]
failed = 0
total = 0
received: list[dict] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global failed, total
    total += 1
    print(f"{'PASS' if cond else 'FAIL'} {name}{(' - ' + detail) if detail and not cond else ''}")
    failed += 0 if cond else 1


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a: object) -> None:
        pass

    def do_POST(self) -> None:  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        received.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body.decode()})
        reply = {
            "summary": "Column_001 and Column_002 rise together in this dataset.",
            "key_findings": ["Column_001 is associated with Column_002.", "Column_004 has 4 groups."],
            "data_quality": ["Nothing alarming."],
            "limitations": ["Association only, not cause."],
            "next_steps": ["Check Column_003 next."],
        }
        out = json.dumps({"model": "stub/model", "choices": [{"message": {"content": json.dumps(reply)}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


server = ThreadingHTTPServer(("127.0.0.1", 9999), Stub)
threading.Thread(target=server.serve_forever, daemon=True).start()


def frame(n: int = 60) -> pd.DataFrame:
    rng = np.random.default_rng(11)
    wind = rng.uniform(3, 25, n)
    return pd.DataFrame(
        {
            "turbine_output_kw": (wind**2 * 2.1 + rng.normal(0, 20, n)).round(1),
            "wind_speed_ms": wind.round(2),
            "blade_pitch_deg": rng.uniform(0, 30, n).round(2),
            "wind_farm_site": rng.choice(SITES, n),
        }
    )


def user(tag: str) -> httpx.Client:
    c = httpx.Client(base_url=API, timeout=120, follow_redirects=False)
    r = c.post("/auth/register", json={"email": f"{tag}-{uuid.uuid4().hex[:10]}@example.com", "password": "correct-horse-9"})
    assert r.status_code == 201, r.text
    return c


def pdf_text(data: bytes) -> str:
    return "\n".join(p.extract_text() or "" for p in PdfReader(io.BytesIO(data)).pages)


# ---- setup
owner = user("owner")
pid = owner.post("/projects", json={"name": "Wind farm"}).json()["id"]
up = owner.post(f"/projects/{pid}/upload", files={"file": ("wind.csv", frame().to_csv(index=False).encode(), "text/csv")})
check("upload accepted", up.status_code == 201, up.text[:200])
check("analysis runs", owner.post(f"/projects/{pid}/analyze").status_code == 200)

# ---- AI analyst
state = owner.get(f"/projects/{pid}/ai-insights").json()
check("AI is configured and the data is eligible", state["configured"] is True and state["eligible"] is True and state["insight"] is None, str(state))
gen = owner.post(f"/projects/{pid}/ai-insights")
check("generation succeeds", gen.status_code == 200, gen.text[:300])
insight = gen.json().get("insight") or {}
check("real column names are shown to the owner", "turbine_output_kw" in insight.get("summary", "") and "wind_speed_ms" in insight.get("summary", ""), insight.get("summary", ""))
check("no alias placeholder is left in the displayed text", "Column_00" not in json.dumps(insight))
check("the provider was called exactly once", len(received) == 1, str(len(received)))
sent = received[0]["body"] if received else ""
check("the API key went to the provider as a Bearer token", bool(received) and received[0]["auth"] == f"Bearer {KEY}")
check("the key is not inside the request body", KEY not in sent)
check("NO column name was sent to the provider", not any(n in sent for n in REAL_NAMES), "leak!")
check("NO category value was sent to the provider", not any(s in sent for s in SITES), "leak!")
check("the evidence is between the markers", "<<<EVIDENCE" in sent and "EVIDENCE>>>" in sent)
check("explanation persists on reload", owner.get(f"/projects/{pid}/ai-insights").json()["insight"] == insight)
check("immediate regeneration is rate limited", owner.post(f"/projects/{pid}/ai-insights").status_code == 429)
check("the rate-limited call did not reach the provider", len(received) == 1)

# ---- reports
rep = owner.post(f"/projects/{pid}/reports")
check("report created", rep.status_code == 201, rep.text[:200])
rid = rep.json()["id"]
dl = owner.get(f"/projects/{pid}/reports/{rid}/download")
check("download is a PDF attachment", dl.status_code == 200 and dl.content[:5] == b"%PDF-" and "attachment" in dl.headers.get("content-disposition", ""))
text = pdf_text(dl.content)
check("PDF carries the project, dataset and real names", all(s in text for s in ("Wind farm", "wind.csv", "turbine_output_kw")), text[:200])
check("PDF includes the labelled AI section", "AI-generated explanation" in text and "It can be wrong" in text)
analysis = owner.get(f"/projects/{pid}/analysis").json()
mean = next(c for c in analysis["statistics"]["columns"] if c["column"] == "wind_speed_ms")["mean"]
check("PDF numbers match the dashboard numbers", f"{mean:,.2f}" in text, f"mean {mean}")
check("report listed", [r["id"] for r in owner.get(f"/projects/{pid}/reports").json()] == [rid])
check("second report straight away is rate limited", owner.post(f"/projects/{pid}/reports").status_code == 429)

# ---- isolation
other = user("other")
for verb, path in (("get", f"/projects/{pid}/ai-insights"), ("post", f"/projects/{pid}/ai-insights"), ("get", f"/projects/{pid}/reports"),
                   ("get", f"/projects/{pid}/reports/{rid}/download"), ("delete", f"/projects/{pid}/reports/{rid}")):
    check(f"another user gets 404 for {verb.upper()} {path.split('/', 3)[-1]}", getattr(other, verb)(path).status_code == 404)
anon = httpx.Client(base_url=API, timeout=30)
check("anonymous download refused", anon.get(f"/projects/{pid}/reports/{rid}/download").status_code == 401)

# ---- stale explanation is withheld after the analysis changes
owner.post(f"/projects/{pid}/regression", json={"target": "turbine_output_kw", "predictors": ["wind_speed_ms"]})
after = owner.get(f"/projects/{pid}/ai-insights").json()
check("an explanation of older results is withheld", after["insight"] is None and after["has_outdated_insight"] is True)

# ---- login brute force
victim = f"victim-{uuid.uuid4().hex[:8]}@example.com"
anon.post("/auth/register", json={"email": victim, "password": "correct-horse-9"})
codes = [anon.post("/auth/login", json={"email": victim, "password": "wrong-password-0"}).status_code for _ in range(9)]
check("repeated wrong passwords end in 429", codes[:8] == [401] * 8 and codes[8] == 429, str(codes))
check("the right password is refused while locked", anon.post("/auth/login", json={"email": victim, "password": "correct-horse-9"}).status_code == 429)

# ---- edge behaviour: size limit and headers
s = socket.create_connection((BASE.split("//")[1].split(":")[0], int(BASE.rsplit(":", 1)[1])), timeout=10)
s.sendall(f"POST /api/v1/projects/{pid}/upload HTTP/1.1\r\nHost: x\r\nContent-Type: multipart/form-data; boundary=b\r\nContent-Length: {200 * 1024 * 1024}\r\nCookie: {'; '.join(f'{k}={v}' for k, v in owner.cookies.items())}\r\n\r\n".encode())
s.settimeout(5)
try:
    first = s.recv(200).decode(errors="replace").split("\r\n")[0]
except TimeoutError:
    first = "TIMEOUT (no response)"
s.close()
check("a declared 200 MB upload is refused immediately with 413", "413" in first, first)
h = httpx.get(f"{BASE}/login", timeout=30)
check("security headers present", h.headers.get("x-content-type-options") == "nosniff" and h.headers.get("x-frame-options") == "DENY" and "server" not in h.headers)

print(f"\n{total - failed}/{total} checks passed")
sys.exit(1 if failed else 0)
