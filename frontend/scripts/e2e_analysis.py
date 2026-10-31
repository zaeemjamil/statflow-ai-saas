"""Checkpoint-4 HTTP e2e through the Next.js origin (proxy -> FastAPI -> PostgreSQL).

    ../backend/.venv/bin/python scripts/e2e_analysis.py http://localhost:3000

This is an HTTP-level test, NOT a browser test: it exercises the same endpoints, in the same
order, as the Cleaning & Analysis UI, and checks the numbers against an independent pandas
calculation on the original data.
"""
import sys
import uuid

import httpx
import numpy as np
import pandas as pd

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:3000"
API = f"{BASE}/api/v1"
failed = 0
total = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global failed, total
    total += 1
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
    df.loc[3, "power_kw"] = 90000.0  # a deliberate, obvious outlier
    return pd.concat([df, df.iloc[:2]], ignore_index=True)  # 2 duplicate rows


def new_user(tag: str) -> httpx.Client:
    c = httpx.Client(base_url=API, timeout=120, follow_redirects=False)
    r = c.post("/auth/register", json={"email": f"{tag}-{uuid.uuid4().hex[:10]}@example.com", "password": "correct-horse-9", "full_name": tag})
    assert r.status_code == 201, r.text
    return c


def code(r: httpx.Response) -> str:
    return r.json().get("error", {}).get("code", "")


a, b = new_user("alice"), new_user("bob")
df = telemetry(300, 1)
csv = df.to_csv(index=False).encode()

# --- 1-4: project + upload + profile
pid = a.post("/projects", json={"name": "Turbine analysis"}).json()["id"]
check("analysis before upload -> 404 analysis_not_found", (r := a.get(f"/projects/{pid}/analysis")).status_code == 404 and code(r) == "analysis_not_found")
check("clean before upload -> 409 no_file_uploaded", (r := a.post(f"/projects/{pid}/clean", json={})).status_code == 409 and code(r) == "no_file_uploaded")
check("analyze before upload -> 409 no_file_uploaded", (r := a.post(f"/projects/{pid}/analyze")).status_code == 409 and code(r) == "no_file_uploaded")
up = a.post(f"/projects/{pid}/upload", files={"file": ("turbines.csv", csv, "text/csv")})
check("upload CSV -> 201", up.status_code == 201, up.text[:200])
check("profile: 302 rows, 7 missing, 2 duplicates", (lambda p: p["row_count"] == 302 and p["total_missing_values"] == 7 and p["duplicate_row_count"] == 2)(up.json()["profile"]))

# --- invalid cleaning input
check("clean with an unsupported option -> 422", a.post(f"/projects/{pid}/clean", json={"numeric_strategy": "mean"}).status_code == 422)
check("clean with an unsupported duplicate option -> 422", a.post(f"/projects/{pid}/clean", json={"duplicate_strategy": "drop_all"}).status_code == 422)
check("regression before analysis -> 404 analysis_not_found", (r := a.post(f"/projects/{pid}/regression", json={"target": "power_kw", "predictors": ["wind_speed_ms"]})).status_code == 404 and code(r) == "analysis_not_found")

# --- 5: clean (defaults except duplicates=remove)
cl = a.post(f"/projects/{pid}/clean", json={"duplicate_strategy": "remove"})
check("clean -> 200", cl.status_code == 200, cl.text[:200])
c = cl.json()
rep = c["cleaning"]
check("cleaning report: 302 -> 300 rows, 2 duplicates removed", (rep["rows_before"], rep["rows_after"], rep["duplicates_removed"]) == (302, 300, 2), str(rep)[:200])
check("cleaning report: all 7 missing values filled", (rep["missing_before"], rep["missing_after"], rep["missing_values_imputed"]) == (7, 0, 7), str(rep)[:200])
check("cleaning stages: profiling+cleaning done, rest pending", c["stages"]["cleaning"] == "completed" and c["stages"]["statistics"] == "pending" and c["statistics"] is None)
check("project status -> cleaning_completed", a.get(f"/projects/{pid}").json()["status"] == "cleaning_completed")
check("statistics before analyze -> 409 analysis_not_completed", (r := a.get(f"/projects/{pid}/statistics")).status_code == 409 and code(r) == "analysis_not_completed")
check("regression after clean only -> 409 analysis_not_completed", (r := a.post(f"/projects/{pid}/regression", json={"target": "power_kw", "predictors": ["wind_speed_ms"]})).status_code == 409 and code(r) == "analysis_not_completed")

# --- 6-7: analyze + inspect, verified against pandas on the original data
an = a.post(f"/projects/{pid}/analyze")
check("analyze -> 200 completed", an.status_code == 200 and an.json()["status"] == "completed", an.text[:200])
d = an.json()
check("stages: statistics/correlations/outliers/charts completed, regression skipped", all(d["stages"][s] == "completed" for s in ("statistics", "correlations", "outliers", "visualizations")) and d["stages"]["regression"] == "skipped", str(d["stages"]))
check("project status -> completed", a.get(f"/projects/{pid}").json()["status"] == "completed")

ref = df.drop_duplicates().reset_index(drop=True)
ref["rotor_rpm"] = ref["rotor_rpm"].fillna(ref["rotor_rpm"].median())  # same cleaning the user chose
stats = {s["column"]: s for s in a.get(f"/projects/{pid}/statistics").json()["columns"]}
check("statistics cover exactly the 3 numeric columns", set(stats) == {"wind_speed_ms", "rotor_rpm", "power_kw"}, str(set(stats)))
for col in ("wind_speed_ms", "rotor_rpm", "power_kw"):
    s = stats[col]
    check(f"statistics[{col}] mean/std/median match pandas", np.isclose(s["mean"], ref[col].mean()) and np.isclose(s["std"], ref[col].std()) and np.isclose(s["median"], ref[col].median()), str(s))
check("statistics: 300 observations, 0 missing after cleaning", stats["rotor_rpm"]["count"] == 300 and stats["rotor_rpm"]["missing_count"] == 0)

cor = a.get(f"/projects/{pid}/correlations").json()
exp = ref[["wind_speed_ms", "rotor_rpm", "power_kw"]].corr()
pair = next(p for p in cor["pairs"] if {p["column_a"], p["column_b"]} == {"wind_speed_ms", "rotor_rpm"})
check("correlation wind~rpm matches pandas and is strong/positive", np.isclose(pair["correlation"], exp.loc["wind_speed_ms", "rotor_rpm"]) and pair["strength"] == "strong" and pair["direction"] == "positive", str(pair))
check("correlation matrix is symmetric with 1.0 diagonal", np.isclose(cor["matrix"]["power_kw"]["power_kw"], 1.0) and np.isclose(cor["matrix"]["power_kw"]["rotor_rpm"], cor["matrix"]["rotor_rpm"]["power_kw"]))

out = a.get(f"/projects/{pid}/outliers").json()
pw = next(o for o in out["columns"] if o["column"] == "power_kw")
q1, q3 = ref["power_kw"].quantile(0.25), ref["power_kw"].quantile(0.75)
check("outliers: IQR bounds match pandas", np.isclose(pw["upper_bound"], q3 + 1.5 * (q3 - q1)) and np.isclose(pw["lower_bound"], q1 - 1.5 * (q3 - q1)), str(pw))
check("outliers: the injected 90000 kW row (position 3) is flagged", 3 in pw["outlier_indices"] and pw["outlier_count"] >= 1, str(pw["outlier_indices"]))
check("outliers: total count is the sum over columns", out["total_outlier_count"] == sum(o["outlier_count"] for o in out["columns"]))

# --- 9: charts
ch = a.get(f"/projects/{pid}/charts").json()
types = {x["chart_type"] for x in ch["charts"]}
check("charts available with a reason and data on every chart", ch["available"] and ch["chart_count"] == len(ch["charts"]) > 0 and all(x["reason"] and x["data"] for x in ch["charts"]))
check("chart types include scatter + histogram", {"scatter", "histogram"} <= types, str(types))
check("chart data shapes match the contract the UI reads", all(
    ("x" in x["data"][0] and "y" in x["data"][0]) if x["chart_type"] in ("scatter", "line", "bar")
    else ({"bin_start", "bin_end", "count"} <= set(x["data"][0]) if x["chart_type"] == "histogram" else {"x", "count"} <= set(x["data"][0]))
    for x in ch["charts"]
))

# --- 8 + 11: regression, valid and invalid
reg = a.post(f"/projects/{pid}/regression", json={"target": "power_kw", "predictors": ["wind_speed_ms", "rotor_rpm"]})
check("regression valid -> 200 and stage completed", reg.status_code == 200 and reg.json()["stages"]["regression"] == "completed", reg.text[:200])
rr = reg.json()["regression"]
check("regression: model echoes target/predictors, 300 rows, train+test = used", rr["model"]["target"] == "power_kw" and rr["model"]["predictors"] == ["wind_speed_ms", "rotor_rpm"] and rr["model"]["observations_total"] == 300 and rr["model"]["train_observations"] + rr["model"]["test_observations"] == rr["model"]["observations_used"], str(rr["model"]))
check("regression: one coefficient per predictor, R² in [0,1]", [x["name"] for x in rr["coefficients"]] == ["wind_speed_ms", "rotor_rpm"] and 0 <= rr["metrics"]["r_squared"] <= 1, str(rr["metrics"]))
check("regression: sample residual == actual - predicted", all(np.isclose(p["residual"], p["actual"] - p["predicted"]) for p in rr["sample_predictions"]) and len(rr["sample_predictions"]) > 0)
saved = rr

for body, want_status, want_code, label in [
    ({"target": "site", "predictors": ["wind_speed_ms"]}, 422, "regression_target_not_numeric", "non-numeric target"),
    ({"target": "nope", "predictors": ["wind_speed_ms"]}, 422, "regression_target_not_found", "unknown target"),
    ({"target": "power_kw", "predictors": ["power_kw"]}, 422, "regression_target_in_predictors", "target as predictor"),
    ({"target": "power_kw", "predictors": ["ghost_column"]}, 422, None, "unknown predictor"),
    ({"target": "power_kw", "predictors": ["site"]}, 422, None, "categorical predictor"),
    ({"target": "power_kw", "predictors": []}, 422, "validation_error", "empty predictors"),
    ({"target": "", "predictors": ["wind_speed_ms"]}, 422, "validation_error", "empty target"),
]:
    r = a.post(f"/projects/{pid}/regression", json=body)
    check(f"invalid regression ({label}) -> {want_status}" + (f" {want_code}" if want_code else ""), r.status_code == want_status and (want_code is None or code(r) == want_code) and bool(r.json()["error"]["message"]), r.text[:200])
check("rejected regressions did not overwrite the saved model", a.get(f"/projects/{pid}/analysis").json()["regression"] == saved)

# --- 10: persistence - a brand-new session (fresh login) sees the identical stored results
email = a.get("/auth/me").json()["email"]
a2 = httpx.Client(base_url=API, timeout=120)
check("fresh login works", a2.post("/auth/login", json={"email": email, "password": "correct-horse-9"}).status_code == 200)
full = a2.get(f"/projects/{pid}/analysis").json()
check("persisted analysis identical after re-login (stats, corr, outliers, regression, charts)", all(full[k] == d[k] for k in ("statistics", "correlations", "outliers", "visualizations", "cleaning")) and full["regression"] == saved)
check("re-running analyze keeps the saved regression", a2.post(f"/projects/{pid}/analyze").json()["regression"] == saved)

# --- re-clean erases downstream results (the UI warns about exactly this)
rc = a2.post(f"/projects/{pid}/clean", json={"duplicate_strategy": "keep", "numeric_strategy": "unchanged"}).json()
check("re-clean wipes statistics/correlations/outliers/regression/charts", all(rc[k] is None for k in ("statistics", "correlations", "outliers", "regression", "visualizations")) and rc["stages"]["statistics"] == "pending" and rc["stages"]["regression"] == "pending", str(rc["stages"]))
check("re-clean report reflects the new options (302 rows kept, 7 missing left)", rc["cleaning"]["rows_after"] == 302 and rc["cleaning"]["missing_after"] == 7, str(rc["cleaning"])[:200])
check("project status back to cleaning_completed", a2.get(f"/projects/{pid}").json()["status"] == "cleaning_completed")
check("statistics now 409 again", a2.get(f"/projects/{pid}/statistics").status_code == 409)

# --- 12: isolation - Bob vs Alice's results
missing = "00000000-0000-0000-0000-000000000000"
a2.post(f"/projects/{pid}/analyze")  # make sure there is something to steal
for method, path, body in [
    ("GET", "/analysis", None), ("GET", "/statistics", None), ("GET", "/correlations", None), ("GET", "/outliers", None),
    ("GET", "/charts", None), ("POST", "/clean", {}), ("POST", "/analyze", None),
    ("POST", "/regression", {"target": "power_kw", "predictors": ["wind_speed_ms"]}),
]:
    rb = b.request(method, f"/projects/{pid}{path}", json=body)
    rm = b.request(method, f"/projects/{missing}{path}", json=body)
    check(f"Bob {method} Alice's {path} -> 404, identical to a nonexistent project", rb.status_code == 404 and rb.content == rm.content, f"{rb.status_code} {rb.text[:120]}")
check("Bob's dashboard shows nothing of Alice's work", (lambda s: s["total_projects"] == 0 and s["files_analyzed"] == 0)(b.get("/dashboard/summary").json()))
check("Alice's results were not changed by Bob's attempts", a2.get(f"/projects/{pid}/analysis").json()["status"] == "completed")

# --- unauthenticated access
anon = httpx.Client(base_url=API, timeout=30)
check("unauthenticated analysis read -> 401", anon.get(f"/projects/{pid}/analysis").status_code == 401)
check("unauthenticated analyze -> 401", anon.post(f"/projects/{pid}/analyze").status_code == 401)

# --- the project page itself renders for the owner and bounces anonymous users
pg = httpx.get(f"{BASE}/projects/{pid}", cookies=a.cookies, follow_redirects=False, timeout=60)
check("owner's project page -> 200", pg.status_code == 200, str(pg.status_code))
check("anonymous project page -> redirect to login", httpx.get(f"{BASE}/projects/{pid}", follow_redirects=False, timeout=60).status_code == 307)

print(f"\n{total - failed}/{total} checks passed")
sys.exit(1 if failed else 0)
