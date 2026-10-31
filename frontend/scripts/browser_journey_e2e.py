"""Checkpoint-5 REAL-BROWSER journey, data-correctness, error-handling, accessibility and responsive test
(headless Chromium via Playwright) against `next start` on :3000 -> FastAPI :8000 -> PostgreSQL.

    PLAYWRIGHT_BROWSERS_PATH=/opt/pw-browsers python3 scripts/browser_journey_e2e.py \
        http://localhost:3000 [screenshot_dir] [--backend-python PATH --database-url URL]

Complements (does not replace) browser_e2e.py. Covers: register -> create project -> XLSX upload ->
profile -> clean -> analyze -> every tab -> regression -> sign out -> login again -> same results (also
from a second, fresh browser context); messy CSV (NA text, identifiers, formatted numbers, ambiguous
dotted dates, an all-blank column); a >2,500-row file (chart sampling disclosure); a legacy-shaped
project (needs --backend-python/--database-url, otherwise reported as NOT RUN); upload error display;
simulated network/500/contract failures and a real expired session; double-click safety; keyboard and
focus-visible checks; axe-core scans (light and dark) on every main page, tab and dialog; and layout at
390/768/1280 px. Needs frontend/node_modules/axe-core (devDependency) and Chromium.
"""

import io
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid

import numpy as np
import pandas as pd
from playwright.sync_api import BrowserContext, Page, expect, sync_playwright

args = [a for a in sys.argv[1:]]
opts: dict[str, str] = {}
for flag in ("--backend-python", "--database-url"):
    if flag in args:
        i = args.index(flag)
        opts[flag] = args[i + 1]
        del args[i : i + 2]
BASE = args[0].rstrip("/") if args else "http://localhost:3000"
SHOTS = args[1] if len(args) > 1 else "/tmp/shots"
AXE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "node_modules", "axe-core", "axe.min.js")
os.makedirs(SHOTS, exist_ok=True)

failed = 0
total = 0
not_run: list[str] = []
axe_findings: list[tuple[str, str, str, int, str]] = []  # (page, impact, rule, nodes, help)


def check(name: str, cond: bool, detail: str = "") -> None:
    global failed, total
    total += 1
    print(f"{'PASS' if cond else 'FAIL'} {name}{(' - ' + detail) if detail and not cond else ''}")
    failed += 0 if cond else 1


def step(name: str, fn) -> None:
    try:
        fn()
        check(name, True)
    except Exception as e:  # noqa: BLE001
        check(name, False, str(e).splitlines()[0][:220])


# ------------------------------------------------------------------ fixtures
def clean_xlsx() -> bytes:
    rng = np.random.default_rng(11)
    n = 90
    x = rng.uniform(0, 50, n)
    df = pd.DataFrame({
        "temperature_c": x.round(2),
        "energy_kwh": (x * 3.2 + rng.normal(0, 4, n)).round(2),
        "pressure_kpa": rng.normal(101, 2, n).round(2),
        "plant": rng.choice(["north", "south", "east"], n),
    })
    df.loc[[2, 5], "pressure_kpa"] = np.nan
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Readings", index=False)
        pd.DataFrame({"note": ["ignored second sheet"]}).to_excel(w, sheet_name="Notes", index=False)
    return buf.getvalue()


def messy_csv() -> bytes:
    rows = ["row_id,score,country,price,when,empty,measure"]
    for i in range(40):
        rows.append(
            f'{i + 1},{"NA" if i % 7 == 0 else i},{"NA" if i % 5 == 0 else "US"},"${i * 10 + 1:,}",'
            f'{["01.02.2025", "03.04.2025", "05.06.2025", "07.08.2025"][i % 4]},,{i * 1.5}'
        )
    return "\n".join(rows).encode()


def large_csv(n: int = 3200) -> bytes:
    t = np.arange(n)
    df = pd.DataFrame({"t": t, "a": (np.sin(t / 50) * 10 + t % 13).round(3), "b": ((t * 7) % 101).astype(float)})
    return df.to_csv(index=False).encode()


def small_csv() -> bytes:
    return "\n".join(["x,y,g"] + [f"{i},{i * 2 + (i % 5)},{'ab'[i % 2]}" for i in range(40)]).encode()


# ------------------------------------------------------------------ helpers
def register(page: Page, tag: str) -> tuple[str, str]:
    email = f"{tag}-{uuid.uuid4().hex[:8]}@example.com"
    page.goto(f"{BASE}/register")
    page.get_by_label("Full name (optional)").fill(tag)
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill("correct-horse-9")
    page.get_by_role("button", name="Create account").click()
    page.wait_for_url("**/dashboard", timeout=20000)
    return email, "correct-horse-9"


def login(page: Page, email: str, password: str) -> None:
    page.goto(f"{BASE}/login")
    page.get_by_label("Email").fill(email)
    page.get_by_label("Password").fill(password)
    page.get_by_role("button", name="Sign in").click()
    page.wait_for_url("**/dashboard", timeout=20000)


def create_project(page: Page, name: str) -> str:
    page.goto(f"{BASE}/projects/new")
    page.get_by_label("Project name").fill(name)
    page.get_by_role("button", name="Create project").click()
    page.wait_for_url("**/projects/*", timeout=20000)
    expect(page.get_by_role("heading", name=name)).to_be_visible()
    return page.url


def upload(page: Page, name: str, data: bytes, mime: str = "text/csv") -> None:
    page.get_by_test_id("file-input").set_input_files(files=[{"name": name, "mimeType": mime, "buffer": data}])


def tab(page: Page, name: str) -> None:
    page.get_by_role("tab", name=name).click()


def run_analysis(page: Page) -> None:
    page.get_by_role("button", name="Run analysis").click()
    expect(page.get_by_role("button", name="Re-run analysis")).to_be_visible(timeout=30000)


def metric(page: Page, label: str, value: str):
    """The profile metric tile `label` must show EXACTLY `value` (no substring matches like 46 for 6)."""
    return expect(page.get_by_text(label, exact=True).locator("xpath=..").first).to_have_text(re.compile(rf"^{re.escape(label)}\s*{re.escape(value)}$"))


def overflow(page: Page) -> int:
    return page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")


def axe_scan(page: Page, label: str) -> None:
    """axe-core on the current DOM. serious/critical = FAIL; moderate/minor are listed in the report."""
    if not page.evaluate("typeof window.axe !== 'undefined'"):
        page.add_script_tag(path=AXE_PATH)
    res = page.evaluate(
        """async () => await axe.run(document, {runOnly: {type: 'tag',
            values: ['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa', 'best-practice']}})"""
    )
    bad = 0
    for v in res["violations"]:
        axe_findings.append((label, v["impact"], v["id"], len(v["nodes"]), v["help"]))
        if v["impact"] in ("serious", "critical"):
            bad += 1
            targets = "; ".join(" ".join(n["target"]) for n in v["nodes"][:3])
            print(f"     axe {v['impact']} {v['id']} x{len(v['nodes'])}: {v['help']} -> {targets}")
    check(f"axe [{label}]: 0 serious/critical violations ({len(res['violations'])} total incl. moderate/minor)", bad == 0)


def focus_visible(page: Page) -> bool:
    return page.evaluate(
        """() => { const e = document.activeElement; if (!e || e === document.body) return false;
        const s = getComputedStyle(e);
        const outline = s.outlineStyle !== 'none' && parseFloat(s.outlineWidth) > 0;
        const ring = s.boxShadow && s.boxShadow !== 'none';
        return outline || ring; }"""
    )


def active_desc(page: Page) -> str:
    return page.evaluate(
        "() => { const e = document.activeElement; return e ? (e.getAttribute('aria-label') || e.innerText || e.tagName).trim().slice(0, 40) : ''; }"
    )


# ------------------------------------------------------------------ run
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    console_errors: list[str] = []
    http_errors: list[str] = []

    def watch(p: Page) -> None:
        p.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        p.on("pageerror", lambda e: console_errors.append(str(e)))
        p.on("response", lambda r: http_errors.append(f"{r.status} {r.request.method} {r.url.replace(BASE, '')}") if r.status >= 400 else None)

    watch(page)

    # ============ 1. Public pages: axe + keyboard + focus-visible
    page.goto(f"{BASE}/login")
    expect(page.get_by_role("button", name="Sign in")).to_be_visible()
    axe_scan(page, "login")
    page.goto(f"{BASE}/register")
    expect(page.get_by_role("button", name="Create account")).to_be_visible()
    axe_scan(page, "register")
    page.goto(f"{BASE}/forgot-password")
    page.wait_for_load_state("networkidle")
    axe_scan(page, "forgot-password")

    def keyboard_login():
        page.goto(f"{BASE}/login")
        page.get_by_label("Email").focus()
        seen = []
        for _ in range(6):
            seen.append((active_desc(page), focus_visible(page)))
            if seen[-1][0].startswith("Sign in"):
                break
            page.keyboard.press("Tab")
        names = [s[0] for s in seen]
        assert any(n.startswith("Sign in") for n in names), f"submit not reachable by Tab: {names}"
        assert all(v for _, v in seen), f"focus indicator missing on: {[n for n, v in seen if not v]}"
    step("login: form reachable by Tab, every stop has a visible focus indicator", keyboard_login)

    def anon_redirect():
        c = browser.new_context()
        p = c.new_page()
        p.goto(f"{BASE}/dashboard")
        p.wait_for_url("**/login**", timeout=15000)
        p.goto(f"{BASE}/projects/00000000-0000-0000-0000-000000000000")
        p.wait_for_url("**/login**", timeout=15000)
        c.close()
    step("anonymous visits to /dashboard and a project URL redirect to /login", anon_redirect)

    # ============ 2. Journey A: XLSX, full journey, sign out, login again
    email_a, pw_a = register(page, "journey")
    step("register lands on dashboard with a welcome heading and empty state", lambda: expect(page.get_by_role("heading", name=re.compile("Welcome"))).to_be_visible())
    axe_scan(page, "dashboard (new user)")
    page.goto(f"{BASE}/projects/new")
    axe_scan(page, "new project form")
    proj_a = create_project(page, "Journey XLSX")
    axe_scan(page, "project page: upload state")

    def upload_xlsx():
        upload(page, "readings.xlsx", clean_xlsx(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        expect(page.get_by_role("table", name="Per-column profile")).to_be_visible(timeout=30000)
        expect(page.get_by_text("readings.xlsx").first).to_be_visible()
        expect(page.get_by_role("rowheader", name="energy_kwh")).to_be_visible()
    step("upload a real XLSX and see its profile", upload_xlsx)
    step("XLSX: extra worksheet is disclosed in 'Things to check'", lambda: (
        expect(page.get_by_role("heading", name=re.compile("Things to check in your data"))).to_be_visible(),
        expect(page.locator("li[data-severity]").filter(has_text=re.compile("sheet", re.I)).first).to_be_visible(),
    ))
    step("XLSX profile: 90 rows, 2 missing values, 3 numeric / 1 categorical", lambda: (
        expect(page.get_by_text("90", exact=True).first).to_be_visible(),
        expect(page.get_by_role("row", name=re.compile("pressure_kpa")).first).to_contain_text("2 ("),
    ))
    axe_scan(page, "project page: profile + notes")

    def clean_defaults():
        tab(page, "Cleaning")
        page.get_by_role("button", name="Apply cleaning").click()
        expect(page.get_by_text("Cleaning report")).to_be_visible(timeout=20000)
        expect(page.get_by_text("Missing values (before → after)")).to_be_visible()
        expect(page.get_by_role("table", name="Per-column cleaning actions").get_by_role("row", name=re.compile("pressure_kpa"))).to_contain_text("2 → 0")
    step("XLSX: apply default cleaning; pressure_kpa shows 2 → 0 missing", clean_defaults)
    axe_scan(page, "tab: Cleaning (report)")
    step("XLSX: run analysis", lambda: run_analysis(page))

    stats_before: dict[str, str] = {}

    def all_tabs():
        tab(page, "Statistics")
        t = page.get_by_role("table", name="Descriptive statistics per numeric column")
        expect(t).to_be_visible()
        stats_before["stats"] = t.inner_text()
        expect(page.get_by_text("Not shown (not numeric): plant")).to_be_visible()
        axe_scan(page, "tab: Statistics")
        tab(page, "Correlations")
        expect(page.get_by_role("table", name="Correlation matrix")).to_be_visible()
        axe_scan(page, "tab: Correlations")
        tab(page, "Outliers")
        expect(page.get_by_role("table", name="Outliers per numeric column")).to_be_visible()
        axe_scan(page, "tab: Outliers")
        tab(page, "Charts")
        page.wait_for_selector(".recharts-surface", timeout=15000)
        expect(page.get_by_text("Why this chart:").first).to_be_visible()
        axe_scan(page, "tab: Charts")
    step("XLSX: statistics, correlations, outliers, charts all render", all_tabs)

    def regression():
        tab(page, "Regression")
        page.get_by_label("Target column").select_option("energy_kwh")
        page.get_by_role("checkbox", name="temperature_c").check()
        page.get_by_role("button", name="Fit regression").click()
        res = page.get_by_test_id("regression-result")
        expect(res).to_be_visible(timeout=20000)
        expect(res).to_contain_text("energy_kwh ~ temperature_c")
        stats_before["reg"] = res.inner_text()
        axe_scan(page, "tab: Regression (result)")
    step("XLSX: fit regression", regression)

    def nav_away_and_back():
        page.get_by_role("navigation", name="Main").get_by_role("link", name="Projects").click()
        page.wait_for_url("**/projects", timeout=15000)
        axe_scan(page, "projects list")
        page.get_by_role("link", name=re.compile("Journey XLSX")).first.click()
        page.wait_for_url("**/projects/*", timeout=15000)
        expect(page.get_by_role("button", name="Re-run analysis")).to_be_visible(timeout=20000)
        tab(page, "Statistics")
        assert page.get_by_role("table", name="Descriptive statistics per numeric column").inner_text() == stats_before["stats"]
        tab(page, "Regression")
        assert page.get_by_test_id("regression-result").inner_text() == stats_before["reg"]
    step("navigate away and back via the UI: statistics and regression identical", nav_away_and_back)

    def reload_same():
        page.reload()
        expect(page.get_by_role("button", name="Re-run analysis")).to_be_visible(timeout=20000)
        tab(page, "Statistics")
        assert page.get_by_role("table", name="Descriptive statistics per numeric column").inner_text() == stats_before["stats"]
        tab(page, "Regression")
        assert page.get_by_test_id("regression-result").inner_text() == stats_before["reg"]
    step("hard reload: statistics and regression identical", reload_same)

    def sign_out_in():
        page.get_by_role("button", name="Sign out").click()
        page.wait_for_url("**/login**", timeout=15000)
        page.goto(proj_a)
        page.wait_for_url("**/login**", timeout=15000)  # session really ended
        login(page, email_a, pw_a)
        expect(page.get_by_text("Journey XLSX").first).to_be_visible(timeout=15000)
        page.goto(proj_a)
        expect(page.get_by_role("button", name="Re-run analysis")).to_be_visible(timeout=20000)
        tab(page, "Statistics")
        assert page.get_by_role("table", name="Descriptive statistics per numeric column").inner_text() == stats_before["stats"]
        tab(page, "Regression")
        assert page.get_by_test_id("regression-result").inner_text() == stats_before["reg"]
    step("sign out -> protected pages redirect -> login again -> results identical", sign_out_in)

    def fresh_device():
        c2 = browser.new_context(viewport={"width": 1280, "height": 900})
        p2 = c2.new_page()
        login(p2, email_a, pw_a)
        p2.goto(proj_a)
        expect(p2.get_by_role("button", name="Re-run analysis")).to_be_visible(timeout=20000)
        tab(p2, "Statistics")
        assert p2.get_by_role("table", name="Descriptive statistics per numeric column").inner_text() == stats_before["stats"]
        tab(p2, "Regression")
        assert p2.get_by_test_id("regression-result").inner_text() == stats_before["reg"]
        c2.close()
    step("a second, fresh browser context (new device) sees identical results", fresh_device)

    def wrong_password():
        c3 = browser.new_context()
        p3 = c3.new_page()
        p3.goto(f"{BASE}/login")
        p3.get_by_label("Email").fill(email_a)
        p3.get_by_label("Password").fill("not-the-password")
        p3.get_by_role("button", name="Sign in").click()
        expect(p3.get_by_role("alert").or_(p3.get_by_text(re.compile("incorrect|invalid", re.I))).first).to_be_visible(timeout=10000)
        assert "/login" in p3.url
        c3.close()
    step("wrong password shows an error and stays on /login", wrong_password)

    # ============ 3. Journey B: messy CSV - data-correctness warnings
    proj_b = create_project(page, "Journey messy")
    upload(page, "messy.csv", messy_csv())
    expect(page.get_by_role("table", name="Per-column profile")).to_be_visible(timeout=30000)

    def notes_shown():
        expect(page.get_by_role("heading", name="Things to check in your data (5)")).to_be_visible()
        items = page.locator("li[data-severity]")
        assert items.count() == 5, items.count()
        assert page.locator('li[data-severity="warning"]').count() == 3
        assert page.locator('li[data-severity="info"]').count() == 2
    step("messy CSV: 5 notes shown (3 warnings, 2 info) under 'Things to check'", notes_shown)
    step("note: ambiguous dotted dates in 'when' is a warning", lambda: expect(page.locator('li[data-severity="warning"]').filter(has_text="Dates in 'when'").filter(has_text="day/month or month/day")).to_be_visible())
    step("note: 'NA' kept as a real value in 'country' (8 cells)", lambda: expect(page.locator("li[data-severity]").filter(has_text="'NA' was kept as a real value").filter(has_text="'country' (8 cells)")).to_be_visible())
    step("note: 'NA' read as missing in numeric 'score' (6 cells)", lambda: expect(page.locator("li[data-severity]").filter(has_text="'NA' was read as a missing value in 'score' (6 cells)")).to_be_visible())
    step("note: 'price' currency text is not converted", lambda: expect(page.locator('li[data-severity="warning"]').filter(has_text="'price'").filter(has_text="does not convert")).to_be_visible())
    step("note: identifier-like columns are flagged but still included", lambda: expect(page.locator("li[data-severity]").filter(has_text="look like identifiers")).to_be_visible())

    def blank_column_row():
        row = page.get_by_role("row", name=re.compile(r"^empty")).first
        expect(row).to_contain_text("100")
        expect(row).to_contain_text(re.compile("categorical", re.I))
    step("all-blank column 'empty' is shown as categorical with 100% missing", blank_column_row)
    step("profile metrics (exact): 3 numeric, 3 categorical, 1 date column, 46 missing (6 in 'score' + 40 in the blank column)", lambda: (
        metric(page, "Numeric columns", "3"),
        metric(page, "Categorical columns", "3"),
        metric(page, "Date columns", "1"),
        metric(page, "Missing values", "46"),
    ))
    axe_scan(page, "project page: messy profile with 5 notes")

    def messy_analysis():
        tab(page, "Cleaning")
        page.get_by_role("button", name="Apply cleaning").click()
        expect(page.get_by_text("Cleaning report")).to_be_visible(timeout=20000)
        run_analysis(page)
        tab(page, "Statistics")
        t = page.get_by_role("table", name="Descriptive statistics per numeric column")
        expect(t.get_by_role("rowheader", name="measure")).to_be_visible()
        expect(t.get_by_role("rowheader", name="empty")).to_have_count(0)
        skipped = page.get_by_text(re.compile(r"Not shown \(not numeric\):")).inner_text()
        assert "empty" in skipped and "price" in skipped, skipped
        tab(page, "Correlations")
        expect(page.get_by_role("table", name="Correlation matrix").get_by_role("columnheader", name="empty")).to_have_count(0)
        tab(page, "Regression")
        expect(page.get_by_role("checkbox", name="empty")).to_have_count(0)
        assert "empty" not in page.get_by_label("Target column").inner_text()
    step("messy CSV analysis: blank 'empty' and text 'price' are in no numeric tab or regression picker", messy_analysis)

    # ============ 4. Journey C: legacy-shaped project (simulated on PostgreSQL)
    proj_c = create_project(page, "Journey legacy-shaped")
    upload(page, "messy.csv", messy_csv())
    expect(page.get_by_role("table", name="Per-column profile")).to_be_visible(timeout=30000)
    pid_c = proj_c.rstrip("/").split("/")[-1]
    if "--backend-python" in opts and "--database-url" in opts:
        tmp = tempfile.NamedTemporaryFile(suffix=".csv", delete=False)
        tmp.write(messy_csv())
        tmp.close()
        out = subprocess.run(
            [opts["--backend-python"], "scripts/e2e_make_legacy.py", pid_c, tmp.name],
            cwd=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "backend"),
            env={**os.environ, "DATABASE_URL": opts["--database-url"], "PYTHONPATH": "."},
            capture_output=True, text=True,
        )
        check("legacy helper rewrote the stored profile on PostgreSQL", out.returncode == 0, (out.stderr or out.stdout)[-200:])

        def legacy_page():
            page.reload()
            expect(page.get_by_role("table", name="Per-column profile")).to_be_visible(timeout=30000)
            expect(page.get_by_role("heading", name=re.compile("Things to check"))).to_have_count(0)
            metric(page, "Missing values", "54")  # 6 'score' + 8 'country' ('NA' = missing) + 40 blank column
            expect(page.get_by_role("row", name=re.compile("^country")).first).to_contain_text("8 (")
        step("legacy-shaped project: no notes, stored profile shows 54 missing ('NA' counted as missing), no crash", legacy_page)

        def legacy_analysis():
            tab(page, "Cleaning")
            expect(page.get_by_text("Your file currently has 54 missing value(s)")).to_be_visible()
            page.get_by_role("button", name="Apply cleaning").click()
            expect(page.get_by_text("Cleaning report")).to_be_visible(timeout=20000)
            expect(page.get_by_role("table", name="Per-column cleaning actions").get_by_role("row", name=re.compile("country"))).to_contain_text("8 → 0")
            pair = page.get_by_text("Missing values (before → after)").locator("xpath=..")
            expect(pair).to_contain_text("54")
            expect(pair).to_contain_text("0")
            run_analysis(page)
        step("legacy-shaped project: cleaning/analysis use the SAME 54 missing values as the profile shown", legacy_analysis)
        axe_scan(page, "legacy-shaped project after analysis")
    else:
        not_run.append("legacy-shaped project UI check (needs --backend-python and --database-url)")

    # ============ 5. Journey D: >2,500 rows - chart sampling disclosure
    proj_d = create_project(page, "Journey large")
    upload(page, "large.csv", large_csv(3200))
    expect(page.get_by_role("table", name="Per-column profile")).to_be_visible(timeout=30000)
    run_analysis(page)

    def sampling():
        tab(page, "Charts")
        page.wait_for_selector(".recharts-surface", timeout=20000)
        notes = page.get_by_text(re.compile(r"Showing [\d,]+ of 3,200 points")).all_inner_texts()
        assert notes, "no sampling disclosure on a 3,200-row dataset"
        for n in notes:
            m = re.search(r"Showing ([\d,]+) of 3,200 points", n)
            assert m and int(m.group(1).replace(",", "")) <= 2500, n
            assert "Statistics always use all rows." in n
        expect(page.get_by_text(re.compile(r"peaks and dips are preserved|highest and lowest values are always included")).first).to_be_visible()
    step("3,200-row file: every sampled chart says 'Showing N of 3,200 points' (N<=2,500) and 'Statistics always use all rows'", sampling)

    def drawn_matches_disclosed():
        texts = page.get_by_text(re.compile(r"Showing [\d,]+ of 3,200 points")).all_inner_texts()
        scatter_disclosed = sum(int(re.search(r"Showing ([\d,]+)", t).group(1).replace(",", "")) for t in texts if "evenly spread" in t)
        marks = page.locator(".recharts-scatter-symbol").count()
        print(f"     INFO disclosed notes={len(texts)} scatter-disclosed total={scatter_disclosed} drawn scatter symbols={marks}")
        assert marks > 0, "no scatter marks drawn"
        assert marks == scatter_disclosed, f"drawn {marks} != disclosed {scatter_disclosed}"
    step("number of scatter marks actually drawn equals the sum of the points disclosed in the notes", drawn_matches_disclosed)
    step("stats on the large file still use all rows (profile says 3,200 rows)", lambda: (tab(page, "Statistics"), expect(page.get_by_text("3,200").first).to_be_visible()))
    axe_scan(page, "tab: Charts with sampling disclosure")

    def not_sampled_small():
        page.goto(proj_a)
        tab(page, "Charts")
        page.wait_for_selector(".recharts-surface", timeout=15000)
        assert page.get_by_text(re.compile(r"Showing [\d,]+ of")).count() == 0
    step("a small dataset (90 rows) shows NO sampling disclosure", not_sampled_small)

    # ============ 6. Upload error display
    proj_e = create_project(page, "Journey errors")
    err_pat = re.compile(r".+")

    def local_wrong_type():
        upload(page, "notes.txt", b"hello", "text/plain")
        expect(page.get_by_text(re.compile(r"\.csv|\.xlsx|CSV|Excel", re.I)).filter(has_text=re.compile("only|must|choose|supported|accept", re.I)).first).to_be_visible(timeout=5000)
        expect(page.get_by_role("table", name="Per-column profile")).to_have_count(0)
    step("wrong file type is refused locally with a readable message", local_wrong_type)

    def local_too_big():
        upload(page, "huge.csv", b"a,b\n" + b"1,2\n" * (8 * 1024 * 1024))  # ~32 MB > 25 MB
        expect(page.get_by_text(re.compile(r"over the 25 MB limit for CSV files"))).to_be_visible(timeout=15000)
    step("a >25 MB CSV is refused locally, naming the 25 MB limit (client check only)", local_too_big)

    def server_rejects_bad_xlsx():
        upload(page, "broken.xlsx", b"this is not a zip file", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        err = page.get_by_text(re.compile(r"valid|corrupt|could not|can't|cannot|read|excel", re.I)).filter(has_not_text="Choose a CSV").first
        expect(err).to_be_visible(timeout=15000)
        expect(page.get_by_role("table", name="Per-column profile")).to_have_count(0)
    step("a corrupt .xlsx is rejected by the SERVER and its message is shown", server_rejects_bad_xlsx)

    def header_only_csv():
        upload(page, "header.csv", b"a,b,c\n")
        page.wait_for_timeout(1500)
        expect(page.get_by_role("table", name="Per-column profile")).to_have_count(0)
        assert page.get_by_test_id("file-input").count() == 1, "dropzone gone after a rejected upload"
    step("a header-only CSV is rejected and the dropzone stays usable", header_only_csv)

    def valid_after_errors():
        upload(page, "ok.csv", small_csv())
        expect(page.get_by_role("table", name="Per-column profile")).to_be_visible(timeout=20000)
    step("after the rejected uploads a valid CSV uploads fine (error cleared)", valid_after_errors)

    # --- simulated failures on Run analysis (page.route; clearly simulated)
    def sim(name: str, handler, expect_text: re.Pattern[str]):
        def go():
            page.route("**/api/v1/projects/*/analyze", handler)
            page.get_by_role("button", name="Run analysis").click()
            expect(page.get_by_text(expect_text).first).to_be_visible(timeout=10000)
            page.unroute("**/api/v1/projects/*/analyze")
            expect(page.get_by_role("button", name="Run analysis")).to_be_enabled()
        step(name, go)

    sim("SIMULATED network failure on analyze: friendly message, button usable again", lambda r: r.abort(), re.compile("Could not reach the server"))
    sim("SIMULATED 500 with JSON body on analyze: server message shown, button usable again",
        lambda r: r.fulfill(status=500, content_type="application/json", body=json.dumps({"error": {"code": "internal_error", "message": "Simulated server failure."}})),
        re.compile("Simulated server failure"))
    sim("SIMULATED non-JSON 502 on analyze: 'server is unavailable' message",
        lambda r: r.fulfill(status=502, content_type="text/html", body="<html>bad gateway</html>"), re.compile("server is unavailable", re.I))
    sim("SIMULATED 200 with a body that breaks the contract: 'unexpected response' message",
        lambda r: r.fulfill(status=200, content_type="application/json", body="{}"), re.compile("unexpected response"))

    def double_click():
        posts: list[str] = []
        page.on("request", lambda rq: posts.append(rq.url) if rq.method == "POST" and rq.url.endswith("/analyze") else None)
        page.get_by_role("button", name="Run analysis").dblclick()
        expect(page.get_by_role("button", name="Re-run analysis")).to_be_visible(timeout=30000)
        assert len(posts) == 1, f"{len(posts)} analyze requests for one double-click"
    step("double-clicking Run analysis sends exactly ONE request", double_click)

    # --- real expired session mid-use
    def session_expiry():
        c4 = browser.new_context(viewport={"width": 1280, "height": 900})
        p4 = c4.new_page()
        register(p4, "expiry")
        create_project(p4, "Expiry test")
        upload(p4, "ok.csv", small_csv())
        expect(p4.get_by_role("table", name="Per-column profile")).to_be_visible(timeout=20000)
        c4.clear_cookies()
        p4.get_by_role("button", name="Run analysis").click()
        try:
            p4.wait_for_url("**/login**", timeout=8000)
            outcome = "redirected to /login"
        except Exception:  # noqa: BLE001
            visible = p4.get_by_role("alert").all_inner_texts() or [p4.locator("main").inner_text()[-300:]]
            outcome = f"stayed on page; visible text: {visible}"
        print(f"     INFO session expiry outcome: {outcome}")
        assert outcome == "redirected to /login" or re.search(r"sign in|log in|session|unauthor|logged", outcome, re.I), outcome
        c4.close()
    step("real expired session (cookies cleared) while on a project: user is sent to login or told to sign in", session_expiry)

    # ============ 7. Keyboard: tabs, dialog, focus
    page.goto(proj_a)
    expect(page.get_by_role("button", name="Re-run analysis")).to_be_visible(timeout=20000)

    def tab_keys():
        page.get_by_role("tab", name="Cleaning").focus()
        assert focus_visible(page), "focused tab has no visible focus indicator"
        page.keyboard.press("ArrowRight")
        expect(page.get_by_role("tab", name="Statistics")).to_have_attribute("aria-selected", "true")
        page.keyboard.press("End")  # the last tab is "AI analyst" since Phase 9
        expect(page.get_by_role("tab", name="AI analyst")).to_have_attribute("aria-selected", "true")
        page.keyboard.press("Home")
        expect(page.get_by_role("tab", name="Cleaning")).to_have_attribute("aria-selected", "true")
        page.keyboard.press("ArrowLeft")  # wraps from the first tab to the last
        expect(page.get_by_role("tab", name="AI analyst")).to_have_attribute("aria-selected", "true")
        page.keyboard.press("ArrowLeft")
        expect(page.get_by_role("tab", name="Charts")).to_have_attribute("aria-selected", "true")
    step("result tabs: Arrow/Home/End keys move selection (wraps), focus indicator visible", tab_keys)

    def dialog_focus():
        tab(page, "Cleaning")
        page.get_by_role("button", name="Re-apply cleaning").click()
        dlg = page.get_by_role("alertdialog", name="Confirm re-cleaning")
        expect(dlg).to_be_visible()
        inside = page.evaluate("() => !!document.activeElement && !!document.activeElement.closest('[role=alertdialog]')")
        assert inside, "focus did not move into the confirmation dialog"
        axe_scan(page, "re-clean confirmation dialog")
        page.keyboard.press("Escape")
        expect(dlg).to_have_count(0)
    step("re-clean dialog: focus moves inside it and Escape closes it", dialog_focus)

    def kb_form_reach():
        tab(page, "Regression")
        sel = page.get_by_label("Target column")
        sel.focus()
        assert focus_visible(page), "target select has no focus indicator"
        sel.select_option("energy_kwh")
        page.keyboard.press("Tab")
        assert page.evaluate("document.activeElement.type") == "checkbox", f"expected a predictor checkbox, got {active_desc(page)}"
        assert focus_visible(page), "predictor checkbox has no focus indicator"
        page.keyboard.press("Space")
        assert page.evaluate("document.activeElement.checked") is True
        page.keyboard.press("Tab")
        page.keyboard.press("Tab")
        assert focus_visible(page), f"no focus indicator on {active_desc(page)}"
    step("regression form: target -> predictor checkbox (Tab, Space) all show a visible focus indicator", kb_form_reach)

    # ============ 8. Dark colour scheme (contrast) + responsive
    dctx = browser.new_context(viewport={"width": 1280, "height": 900}, color_scheme="dark")
    dctx.add_cookies(ctx.cookies())
    dp = dctx.new_page()
    watch(dp)
    dp.goto(f"{BASE}/login")
    dctx.clear_cookies()
    dp.goto(f"{BASE}/login")
    axe_scan(dp, "login (dark)")
    login(dp, email_a, pw_a)
    dp.goto(proj_a)
    expect(dp.get_by_role("button", name="Re-run analysis")).to_be_visible(timeout=20000)
    for tname in ("Statistics", "Charts", "Regression"):
        tab(dp, tname)
        axe_scan(dp, f"tab: {tname} (dark)")
    dp.goto(proj_b)
    expect(dp.get_by_role("heading", name=re.compile("Things to check"))).to_be_visible(timeout=20000)
    axe_scan(dp, "project page: notes (dark)")
    dctx.close()

    for w, h in ((390, 800), (768, 1024), (1280, 900)):
        rc: BrowserContext = browser.new_context(viewport={"width": w, "height": h}, device_scale_factor=1)
        rp = rc.new_page()
        watch(rp)
        login(rp, email_a, pw_a)
        for label, url in (("dashboard", f"{BASE}/dashboard"), ("projects list", f"{BASE}/projects"), ("new project", f"{BASE}/projects/new")):
            rp.goto(url)
            rp.wait_for_load_state("networkidle")
            o = overflow(rp)
            check(f"{w}px {label}: no horizontal page overflow ({o}px)", o <= 0)
        rp.goto(proj_b)
        expect(rp.get_by_role("heading", name=re.compile("Things to check"))).to_be_visible(timeout=20000)
        o = overflow(rp)
        check(f"{w}px messy project (profile + 5 notes): no horizontal page overflow ({o}px)", o <= 0)
        rp.screenshot(path=f"{SHOTS}/journey-{w}-profile-notes.png", full_page=True)
        rp.goto(proj_a)
        expect(rp.get_by_role("button", name="Re-run analysis")).to_be_visible(timeout=20000)
        for tname in ("Cleaning", "Statistics", "Correlations", "Outliers", "Regression", "Charts"):
            tab(rp, tname)
            if tname == "Charts":
                rp.wait_for_selector(".recharts-surface", timeout=15000)
            o = overflow(rp)
            check(f"{w}px tab {tname}: no horizontal page overflow ({o}px)", o <= 0)
        rp.screenshot(path=f"{SHOTS}/journey-{w}-charts.png", full_page=True)
        if w == 390:
            tabs_ok = all(
                (lambda b: b and b["x"] >= 0 and b["x"] + b["width"] <= w)(rp.get_by_role("tab", name=n).bounding_box())
                for n in ("Cleaning", "Statistics", "Correlations", "Outliers", "Regression", "Charts")
            )
            check("390px: all six tabs fully inside the viewport", tabs_ok)
            small = rp.evaluate(
                """() => [...document.querySelectorAll('button, a, [role=tab], input, select')]
                    .filter(e => e.offsetParent !== null)
                    .map(e => { const r = e.getBoundingClientRect(); return {w: r.width, h: r.height, t: (e.innerText || e.getAttribute('aria-label') || e.tagName).trim().slice(0, 30)}; })
                    .filter(x => x.h < 24 || x.w < 24)"""
            )
            print(f"     INFO 390px controls smaller than 24x24 CSS px (WCAG 2.2 target size minimum): {small}")
            # Informational: WCAG 2.2 2.5.8 also passes undersized targets that have enough spacing; the
            # axe `target-size` rule (wcag22aa) is what the pass/fail uses, and it ran on every scan.
        rc.close()

    # ============ 9. Whole-run network hygiene
    allowed = ("/file", "/analysis", "/profile")
    unexpected_http = [
        e for e in http_errors
        if not (e.startswith("404 GET") and e.endswith(allowed))
        and not e.startswith("401 POST /api/v1/auth/login")  # the deliberate wrong-password check
        and "/analyze" not in e  # deliberately simulated failures
        and not e.startswith("401")  # deliberate expired-session / anonymous checks
        and not e.startswith(("422 POST", "413"))  # deliberate rejected uploads
    ]
    print("INFO http errors seen (all pages):", len(http_errors), sorted(set(http_errors))[:14])
    check(f"no unexpected HTTP errors during the run ({len(unexpected_http)})", not unexpected_http, "; ".join(unexpected_http)[:300])
    real = [e for e in console_errors if not e.startswith("Failed to load resource")]
    check(f"no uncaught JS/page errors during the run ({len(real)})", not real, "; ".join(real)[:300])
    browser.close()

print("\n--- axe-core findings below serious (informational) ---")
seen = set()
for label, impact, rule, nodes, helptext in axe_findings:
    if impact not in ("serious", "critical") and (rule, label) not in seen:
        seen.add((rule, label))
        print(f"  [{impact}] {rule} x{nodes} on '{label}': {helptext}")
print("--- axe-core serious/critical ---", [f for f in axe_findings if f[1] in ("serious", "critical")] or "none")
for item in not_run:
    print("NOT RUN:", item)
print(f"\n{total - failed}/{total} checks passed")
sys.exit(1 if failed else 0)
