"""Real end-to-end check of the Phase 8A API over HTTP against a running
server + PostgreSQL. Usage: start the API with COOKIE_SECURE=false (local
http), then `python scripts/e2e_phase8a.py http://127.0.0.1:8000/api/v1`.
Uses a sensor-telemetry dataset that shares no names with StatFlow's."""

import io
import json
import sys
import uuid

import httpx
import numpy as np
import pandas as pd

B = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000/api/v1"
rng = np.random.default_rng(42)
n = 150
df = pd.DataFrame(
    {
        "observed_on": pd.date_range("2026-01-01", periods=n).astype(str),
        "sensor_reading": rng.normal(50, 10, n).round(2),
        "battery_pct": rng.uniform(20, 100, n).round(1),
        "location": rng.choice(["lab", "field", "depot"], n),
    }
)
df["power_draw"] = (
    1.8 * df["sensor_reading"] - 0.4 * df["battery_pct"] + rng.normal(0, 2, n)
).round(3)
df.loc[0:3, "battery_pct"] = None
df = pd.concat([df, df.iloc[[20]]], ignore_index=True)  # one duplicate row
csv_bytes = df.to_csv(index=False).encode()
xbuf = io.BytesIO()
df.to_excel(xbuf, index=False)
xlsx_bytes = xbuf.getvalue()
CLEAN = {"numeric_strategy": "median", "categorical_strategy": "mode", "duplicate_strategy": "keep"}


def ok(label, r, code=200):
    assert r.status_code == code, f"{label}: {r.status_code} {r.text[:300]}"
    print(f"  [{r.status_code}] {label}")
    return r.json()


c = httpx.Client(base_url=B)
email = f"e2e-{uuid.uuid4().hex[:12]}@example.com"  # unique per run: safe to re-run
pw = "correct-horse-battery"
print("REGISTER / LOGIN")
ok("register", c.post("/auth/register", json={"email": email, "password": pw}), 201)
c.post("/auth/logout")
ok("login", c.post("/auth/login", json={"email": email, "password": pw}))
ok("me", c.get("/auth/me"))

print("DASHBOARD (empty user)")
d = ok("summary", c.get("/dashboard/summary"))
assert (
    d["total_projects"],
    d["files_analyzed"],
    d["reports_generated"],
    d["ai_insights_generated"],
) == (0, 0, 0, 0)
print("  honest zeros:", {k: v for k, v in d.items() if k != "recent_projects"})

print("CSV PROJECT")
p = ok("create project", c.post("/projects", json={"name": "Sensor Telemetry"}), 201)["id"]
up = ok(
    "upload csv", c.post(f"/projects/{p}/upload", files={"file": ("sensors.csv", csv_bytes)}), 201
)
pr = up["profile"]
print(
    f"  profile: {pr['row_count']} rows x {pr['column_count']} cols, "
    f"missing={pr['total_missing_values']}, dupes={pr['duplicate_row_count']}"
)
ok("GET profile", c.get(f"/projects/{p}/profile"))
assert c.get(f"/projects/{p}").json()["status"] == "profiled"

print("CLEAN")
cl = ok("clean", c.post(f"/projects/{p}/clean", json={**CLEAN, "duplicate_strategy": "remove"}))
r = cl["cleaning"]
print(
    f"  rows {r['rows_before']}->{r['rows_after']}, "
    f"missing {r['missing_before']}->{r['missing_after']}, "
    f"dupes removed {r['duplicates_removed']}"
)
assert (r["rows_before"], r["rows_after"], r["missing_before"], r["missing_after"]) == (
    151,
    150,
    4,
    0,
)
assert c.get(f"/projects/{p}").json()["status"] == "cleaning_completed"
assert c.get(f"/projects/{p}/profile").json()["row_count"] == 151, (
    "source profile must stay original"
)
print("  source file untouched: stored profile still reports 151 rows")

print("ANALYZE")
an = ok("analyze", c.post(f"/projects/{p}/analyze"))
print("  stages:", an["stages"])
assert an["status"] == "completed" and c.get(f"/projects/{p}").json()["status"] == "completed"

print("RESULT ENDPOINTS")
st = ok("statistics", c.get(f"/projects/{p}/statistics"))
print("  columns:", [x["column"] for x in st["columns"]])
co = ok("correlations", c.get(f"/projects/{p}/correlations"))
sp = co["strongest_positive"]
print(f"  strongest +: {sp['column_a']} ~ {sp['column_b']} r={sp['correlation']:.3f}")
ou = ok("outliers", c.get(f"/projects/{p}/outliers"))
print("  outliers total:", ou["total_outlier_count"])
ch = ok("charts", c.get(f"/projects/{p}/charts"))
print("  charts:", [x["chart_type"] for x in ch["charts"]])

print("REGRESSION")
rg = ok(
    "regression",
    c.post(
        f"/projects/{p}/regression",
        json={"target": "power_draw", "predictors": ["sensor_reading", "battery_pct"]},
    ),
)["regression"]
coefs = {x["name"]: round(x["coefficient"], 3) for x in rg["coefficients"]}
print(
    f"  coefficients {coefs}  (true: sensor_reading=1.8, battery_pct=-0.4)  "
    f"R2={rg['metrics']['r_squared']:.4f}"
)
assert abs(coefs["sensor_reading"] - 1.8) < 0.1 and abs(coefs["battery_pct"] + 0.4) < 0.05
bad = c.post(f"/projects/{p}/regression", json={"target": "power_draw", "predictors": ["location"]})
assert bad.status_code == 422 and bad.json()["error"]["code"] == "regression_predictor_not_numeric"
print("  [422] invalid predictor rejected:", bad.json()["error"]["code"])
assert c.get(f"/projects/{p}/analysis").json()["regression"] == rg, (
    "good regression must survive a bad request"
)

print("CONSISTENCY across endpoints")
whole = c.get(f"/projects/{p}/analysis").json()
for key, path in [
    ("statistics", "statistics"),
    ("correlations", "correlations"),
    ("outliers", "outliers"),
    ("visualizations", "charts"),
]:
    assert c.get(f"/projects/{p}/{path}").json() == whole[key], key
print("  statistics/correlations/outliers/charts identical to /analysis")
text = c.get(f"/projects/{p}/analysis").text
assert "NaN" not in text and "Infinity" not in text
json.loads(text)

print("XLSX PROJECT")
p2 = ok("create project", c.post("/projects", json={"name": "Sensor XLSX"}), 201)["id"]
ok(
    "upload xlsx",
    c.post(f"/projects/{p2}/upload", files={"file": ("sensors.xlsx", xlsx_bytes)}),
    201,
)
ok("clean", c.post(f"/projects/{p2}/clean", json=CLEAN))
a2 = ok("analyze", c.post(f"/projects/{p2}/analyze"))
assert a2["statistics"]["numeric_column_count"] == 3

print("DASHBOARD (after analysis)")
d = ok("summary", c.get("/dashboard/summary"))
print(
    "  ",
    {k: v for k, v in d.items() if k != "recent_projects"},
    "| recent:",
    [x["name"] for x in d["recent_projects"]],
)
assert d["total_projects"] == 2 and d["files_analyzed"] == 2
assert d["reports_generated"] == 0 and d["ai_insights_generated"] == 0

print("CROSS-USER ISOLATION")
c.post("/auth/logout")
ok("register user B", c.post("/auth/register", json={"email": f"b-{email}", "password": pw}), 201)
bodies = set()
for method, path, body in [
    ("GET", "analysis", None),
    ("GET", "statistics", None),
    ("GET", "correlations", None),
    ("GET", "outliers", None),
    ("GET", "charts", None),
    ("POST", "analyze", None),
    ("POST", "clean", CLEAN),
    ("POST", "regression", {"target": "power_draw", "predictors": ["sensor_reading"]}),
]:
    r = c.request(method, f"/projects/{p}/{path}", json=body)
    assert r.status_code == 404, (path, r.status_code)
    bodies.add(json.dumps(r.json(), sort_keys=True))
bodies.add(
    json.dumps(
        c.get("/projects/00000000-0000-4000-8000-000000000000/statistics").json(), sort_keys=True
    )
)
assert len(bodies) == 1, bodies
print("  8 foreign-project requests -> 404, byte-identical to a nonexistent project's 404")
d = c.get("/dashboard/summary").json()
assert d["total_projects"] == 0 and d["recent_projects"] == []
print("  user B dashboard: zero projects (no leakage)")

print("UNAUTHENTICATED")
anon = httpx.Client(base_url=B)
for path in ("/dashboard/summary", f"/projects/{p}/statistics", f"/projects/{p}/analysis"):
    assert anon.get(path).status_code == 401
print("  [401] dashboard + result endpoints reject anonymous requests")
print("\nE2E: ALL CHECKS PASSED")
