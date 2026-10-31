"""Checkpoint-3 e2e through the Next.js origin (proxy -> FastAPI -> PostgreSQL).

    ../backend/.venv/bin/python scripts/e2e_projects.py http://localhost:3000

Dataset is wind-turbine telemetry (deliberately unrelated to the old retail schema).
"""
import io
import sys
import time
import uuid

import httpx
import numpy as np
import pandas as pd

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:3000"
API = f"{BASE}/api/v1"
failed = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global failed
    print(f"{'PASS' if cond else 'FAIL'} {name}{(' - ' + detail) if detail and not cond else ''}")
    failed += 0 if cond else 1


def telemetry(n: int, seed: int) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    wind = rng.uniform(3, 25, n)
    df = pd.DataFrame({
        "wind_speed_ms": wind.round(2),
        "rotor_rpm": (wind * 0.9 + rng.normal(0, 1, n)).round(2),
        "power_kw": (wind**2 * 2.1 + rng.normal(0, 20, n)).round(1),
        "site": rng.choice(["ridge", "coast", "plain", "offshore"], n),
        "commissioned": pd.date_range("2021-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
    })
    df.loc[rng.choice(n, 7, replace=False), "rotor_rpm"] = np.nan
    return pd.concat([df, df.iloc[:2]], ignore_index=True)  # 2 duplicate rows


def new_user(tag: str) -> httpx.Client:
    c = httpx.Client(base_url=API, timeout=60, follow_redirects=False)
    email = f"{tag}-{uuid.uuid4().hex[:10]}@example.com"
    r = c.post("/auth/register", json={"email": email, "password": "correct-horse-9", "full_name": tag})
    assert r.status_code == 201, r.text
    return c


def pages(c: httpx.Client, path: str) -> int:
    return httpx.get(f"{BASE}{path}", cookies=c.cookies, follow_redirects=False, timeout=60).status_code


a, b = new_user("alice"), new_user("bob")

# --- empty dashboard is truthful zeros
s = a.get("/dashboard/summary").json()
check("fresh dashboard is all zeros", s["total_projects"] == 0 and s["files_analyzed"] == 0 and s["recent_projects"] == [] and s["reports_generated"] == 0 and s["ai_insights_generated"] == 0, str(s))

# --- create + upload CSV
p = a.post("/projects", json={"name": "Turbine fleet Q3"})
check("create project -> 201 status=created", p.status_code == 201 and p.json()["status"] == "created")
pid = p.json()["id"]
check("file info before upload -> 404", a.get(f"/projects/{pid}/file").status_code == 404)

df = telemetry(300, 1)
csv = df.to_csv(index=False).encode()
up = a.post(f"/projects/{pid}/upload", files={"file": ("turbines.csv", csv, "text/csv")})
check("CSV upload -> 201", up.status_code == 201, up.text[:200])
prof = up.json()["profile"]
check("profile row/col counts match the data", prof["row_count"] == len(df) and prof["column_count"] == 5, str(prof["row_count"]))
check("profile detects 3 numeric/1 categorical/1 date", (prof["numeric_column_count"], prof["categorical_column_count"], prof["date_column_count"]) == (3, 1, 1), str((prof["numeric_column_count"], prof["categorical_column_count"], prof["date_column_count"])))
check("profile counts the 7 injected missing values", prof["total_missing_values"] == 7, str(prof["total_missing_values"]))
check("profile counts the 2 duplicate rows", prof["duplicate_row_count"] == 2, str(prof["duplicate_row_count"]))

f = a.get(f"/projects/{pid}/file")
check("GET /file matches upload response", f.status_code == 200 and f.json() == up.json()["file"] and f.json()["original_filename"] == "turbines.csv")
check("GET /profile equals upload profile", a.get(f"/projects/{pid}/profile").json() == prof)
check("project status is profiled", a.get(f"/projects/{pid}").json()["status"] == "profiled")

# --- error paths
check("second upload -> 409 file_already_exists", (r := a.post(f"/projects/{pid}/upload", files={"file": ("x.csv", csv)})).status_code == 409 and r.json()["error"]["code"] == "file_already_exists")
p2 = a.post("/projects", json={"name": "Scratch"}).json()["id"]
r = a.post(f"/projects/{p2}/upload", files={"file": ("notes.txt", b"hello")})
check("wrong extension -> 422 unsupported_file_type", r.status_code == 422 and r.json()["error"]["code"] == "unsupported_file_type", r.text[:200])
r = a.post(f"/projects/{p2}/upload", files={"file": ("empty.csv", b"")})
check("empty file -> 422", r.status_code == 422, r.text[:200])
check("project name validation -> 422", a.post("/projects", json={"name": ""}).status_code == 422)

# --- XLSX on its own project
buf = io.BytesIO()
telemetry(120, 2).to_excel(buf, index=False)
r = a.post(f"/projects/{p2}/upload", files={"file": ("turbines.xlsx", buf.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
check("XLSX upload -> 201 file_type=xlsx", r.status_code == 201 and r.json()["file"]["file_type"] == "xlsx", r.text[:200])

# --- dashboard now reflects the data, from the same DB rows
s = a.get("/dashboard/summary").json()
check("dashboard: 2 projects", s["total_projects"] == 2, str(s))
check("dashboard: recent projects newest first, with status", len(s["recent_projects"]) == 2 and s["recent_projects"][0]["id"] == p2 and s["recent_projects"][1]["status"] == "profiled")
listed = a.get("/projects").json()
check("projects list agrees with dashboard", {x["id"] for x in listed} == {x["id"] for x in s["recent_projects"]})

# --- rename
r = a.patch(f"/projects/{pid}", json={"name": "Turbine fleet Q3 (clean)"})
check("rename -> 200 new name", r.status_code == 200 and r.json()["name"] == "Turbine fleet Q3 (clean)")
check("rename ignores client-set status", a.patch(f"/projects/{pid}", json={"name": "n", "status": "completed"}).json()["status"] == "profiled")

# --- isolation: Bob vs Alice
missing = "00000000-0000-0000-0000-000000000000"
for path in ("", "/file", "/profile"):
    rb, rm = b.get(f"/projects/{pid}{path}"), b.get(f"/projects/{missing}{path}")
    check(f"Bob GET Alice's project{path or ''} -> 404 identical to nonexistent", rb.status_code == 404 and rb.content == rm.content)
check("Bob cannot rename Alice's project", b.patch(f"/projects/{pid}", json={"name": "pwned"}).status_code == 404)
check("Bob cannot delete Alice's project", b.delete(f"/projects/{pid}").status_code == 404)
check("Bob cannot upload to Alice's project", b.post(f"/projects/{p2}/upload", files={"file": ("d.csv", csv)}).status_code == 404)
sb = b.get("/dashboard/summary").json()
check("Bob's dashboard counts none of Alice's data", sb["total_projects"] == 0 and sb["recent_projects"] == [])
check("Bob's project list is empty", b.get("/projects").json() == [])
check("Alice's project unchanged after Bob's attempts", a.get(f"/projects/{pid}").json()["name"] != "pwned")

# --- Next.js pages (proxy redirect + real render)
anon = httpx.Client(follow_redirects=False)
for path in ("/dashboard", "/projects", "/projects/new", f"/projects/{pid}"):
    check(f"anonymous {path.replace(pid, '<id>')} -> 307 to /login", anon.get(f"{BASE}{path}").status_code == 307)
for path in ("/dashboard", "/projects", "/projects/new", f"/projects/{pid}"):
    check(f"alice GET {path.replace(pid, '<id>')} -> 200", pages(a, path) == 200)
check("anonymous API /dashboard/summary -> 401", anon.get(f"{API}/dashboard/summary").status_code == 401)

# --- delete
check("delete -> 204", a.delete(f"/projects/{pid}").status_code == 204)
check("deleted project -> 404", a.get(f"/projects/{pid}").status_code == 404)
check("deleted project's file -> 404", a.get(f"/projects/{pid}/file").status_code == 404)
check("dashboard total decremented to 1", a.get("/dashboard/summary").json()["total_projects"] == 1)

print("\nALL PASSED" if not failed else f"\n{failed} FAILED")
sys.exit(1 if failed else 0)
