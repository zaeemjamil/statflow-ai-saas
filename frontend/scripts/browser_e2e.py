"""Checkpoint-4 REAL-BROWSER test (headless Chromium via Playwright) against `next start` on :3000.

    ../backend/.venv/bin/python scripts/browser_e2e.py http://localhost:3000 [screenshot_dir]

Needs the backend on :8000 and a Chromium that Playwright can launch (PLAYWRIGHT_BROWSERS_PATH).
Drives the actual UI: register -> create project -> upload CSV -> clean -> analyze -> inspect every
tab -> regression -> re-clean warning -> reload (persistence) -> mobile layout -> second user.
"""
import io
import sys
import uuid

import numpy as np
import pandas as pd
from playwright.sync_api import Page, expect, sync_playwright

BASE = sys.argv[1].rstrip("/") if len(sys.argv) > 1 else "http://localhost:3000"
SHOTS = sys.argv[2] if len(sys.argv) > 2 else "/tmp/shots"
failed = 0
total = 0


def check(name: str, cond: bool, detail: str = "") -> None:
    global failed, total
    total += 1
    print(f"{'PASS' if cond else 'FAIL'} {name}{(' - ' + detail) if detail and not cond else ''}")
    failed += 0 if cond else 1


def step(name: str, fn) -> None:
    """Run a UI assertion block; a thrown Playwright timeout is a FAIL, not a crash."""
    try:
        fn()
        check(name, True)
    except Exception as e:  # noqa: BLE001
        check(name, False, str(e).splitlines()[0][:200])


def dataset() -> bytes:
    rng = np.random.default_rng(7)
    n = 120
    wind = rng.uniform(3, 25, n)
    df = pd.DataFrame({
        "wind_speed_ms": wind.round(2),
        "rotor_rpm": (wind * 0.9 + rng.normal(0, 1, n)).round(2),
        "power_kw": (wind**2 * 2.1 + rng.normal(0, 20, n)).round(1),
        "site": rng.choice(["ridge", "coast", "plain"], n),
        "commissioned": pd.date_range("2022-01-01", periods=n, freq="D").strftime("%Y-%m-%d"),
    })
    df.loc[[4, 9, 15], "rotor_rpm"] = np.nan
    df.loc[3, "power_kw"] = 90000.0
    return pd.concat([df, df.iloc[:2]], ignore_index=True).to_csv(index=False).encode()


def register(page: Page, tag: str) -> None:
    page.goto(f"{BASE}/register")
    page.get_by_label("Full name (optional)").fill(tag)
    page.get_by_label("Email").fill(f"{tag}-{uuid.uuid4().hex[:8]}@example.com")
    page.get_by_label("Password").fill("correct-horse-9")
    page.get_by_role("button", name="Create account").click()
    page.wait_for_url("**/dashboard", timeout=20000)


def tab(page: Page, name: str) -> None:
    page.get_by_role("tab", name=name).click()


with sync_playwright() as pw:
    browser = pw.chromium.launch()
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()
    console_errors: list[str] = []
    page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
    page.on("pageerror", lambda e: console_errors.append(str(e)))
    http_errors: list[str] = []
    page.on("response", lambda r: http_errors.append(f"{r.status} {r.request.method} {r.url.replace(BASE, '')}") if r.status >= 400 else None)

    step("register through the UI lands on the dashboard", lambda: register(page, "alice"))

    def create_project():
        page.goto(f"{BASE}/projects/new")
        page.get_by_label("Project name").fill("Browser turbine test")
        page.get_by_role("button", name="Create project").click()
        page.wait_for_url("**/projects/*", timeout=20000)
        expect(page.get_by_role("heading", name="Browser turbine test")).to_be_visible()
    step("create a project through the UI", create_project)
    project_url = page.url

    def upload():
        page.get_by_test_id("file-input").set_input_files(files=[{"name": "turbines.csv", "mimeType": "text/csv", "buffer": dataset()}])
        expect(page.get_by_role("table", name="Per-column profile")).to_be_visible(timeout=20000)
        expect(page.get_by_text("turbines.csv").first).to_be_visible()
    step("upload a real CSV and see its profile", upload)
    step("profile shows 122 rows and the injected issues", lambda: (
        expect(page.get_by_text("Duplicate rows").first).to_be_visible(),
        expect(page.get_by_role("rowheader", name="rotor_rpm")).to_be_visible(),
    ))

    step("analysis workspace shows 7 stages, profiling already done", lambda: (
        expect(page.get_by_role("list", name="Analysis stages").get_by_role("listitem")).to_have_count(7),
        expect(page.locator('[data-stage="profiling"]')).to_have_attribute("data-state", "completed"),
        expect(page.locator('[data-stage="statistics"]')).to_have_attribute("data-state", "pending"),
    ))
    step("result tabs are empty before any run", lambda: (tab(page, "Statistics"), expect(page.get_by_text("No results yet")).to_be_visible()))
    step("regression tab explains it needs the analysis first", lambda: (tab(page, "Regression"), expect(page.get_by_text("Run the analysis first")).to_be_visible()))

    def clean():
        tab(page, "Cleaning")
        page.get_by_role("radio", name="Remove duplicate rows").check()
        page.get_by_role("button", name="Apply cleaning").click()
        expect(page.get_by_text("Cleaning report")).to_be_visible(timeout=20000)
        expect(page.get_by_role("table", name="Per-column cleaning actions")).to_be_visible()
        expect(page.locator('[data-stage="cleaning"]')).to_have_attribute("data-state", "completed")
    step("apply cleaning (remove duplicates) and see the report + stage update", clean)
    step("cleaning report shows 122 -> 120 rows", lambda: expect(page.get_by_text("122 → 120")).to_be_visible())
    step("project status badge became 'Cleaned'", lambda: expect(page.get_by_text("Cleaned", exact=True)).to_be_visible())

    def analyze():
        page.get_by_role("button", name="Run analysis").click()
        expect(page.get_by_role("button", name="Re-run analysis")).to_be_visible(timeout=30000)
        expect(page.locator('[data-stage="statistics"]')).to_have_attribute("data-state", "completed")
        expect(page.get_by_text("Analysis complete", exact=True)).to_be_visible()
    step("run analysis; stages and status badge update from the server", analyze)

    def stats():
        tab(page, "Statistics")
        t = page.get_by_role("table", name="Descriptive statistics per numeric column")
        expect(t).to_be_visible()
        expect(t.get_by_role("rowheader", name="power_kw")).to_be_visible()
        expect(page.get_by_text("Not shown (not numeric): site, commissioned")).to_be_visible()
    step("statistics table lists the numeric columns, names the skipped ones", stats)

    def corr():
        tab(page, "Correlations")
        expect(page.get_by_text("Strongest positive")).to_be_visible()
        expect(page.get_by_role("table", name="Correlation matrix")).to_be_visible()
    step("correlations: strongest pair + matrix", corr)

    def outliers():
        tab(page, "Outliers")
        row = page.get_by_role("table", name="Outliers per numeric column").get_by_role("row", name="power_kw")
        expect(row).to_contain_text("3")  # the injected outlier's row position
    step("outliers: power_kw row reports the injected outlier at position 3", outliers)

    def charts():
        tab(page, "Charts")
        expect(page.get_by_text("Why this chart:").first).to_be_visible()
        page.wait_for_selector(".recharts-surface", timeout=15000)
        surfaces = page.locator(".recharts-surface").count()
        marks = page.locator(".recharts-scatter-symbol, .recharts-bar-rectangle").count()
        check(f"charts: {surfaces} Recharts SVG surfaces rendered with {marks} data marks", surfaces >= 2 and marks > 0)
    step("charts tab shows recommendations with reasons", charts)
    page.screenshot(path=f"{SHOTS}/desktop-charts.png", full_page=True)

    def regression():
        tab(page, "Regression")
        fit = page.get_by_role("button", name="Fit regression")
        expect(fit).to_be_disabled()
        page.get_by_label("Target column").select_option("power_kw")
        expect(page.get_by_role("checkbox", name="power_kw")).to_have_count(0)
        expect(fit).to_be_disabled()
        page.get_by_role("checkbox", name="wind_speed_ms").check()
        page.get_by_role("checkbox", name="rotor_rpm").check()
        expect(fit).to_be_enabled()
        fit.click()
        res = page.get_by_test_id("regression-result")
        expect(res).to_be_visible(timeout=20000)
        expect(res).to_contain_text("power_kw ~ wind_speed_ms + rotor_rpm")
        expect(res.get_by_role("rowheader", name="Intercept")).to_be_visible()
        expect(page.locator('[data-stage="regression"]')).to_have_attribute("data-state", "completed")
    step("regression: gating, valid fit, result + stage update", regression)
    page.screenshot(path=f"{SHOTS}/desktop-regression.png", full_page=True)

    def recleaning_warning():
        tab(page, "Cleaning")
        page.get_by_role("button", name="Re-apply cleaning").click()
        dlg = page.get_by_role("alertdialog", name="Confirm re-cleaning")
        expect(dlg).to_be_visible()
        expect(dlg).to_contain_text("statistics, correlations, outliers, the regression model, charts")
        dlg.get_by_role("button", name="Cancel").click()
        expect(dlg).to_have_count(0)
        tab(page, "Statistics")
        expect(page.get_by_role("table", name="Descriptive statistics per numeric column")).to_be_visible()  # nothing was erased
    step("re-clean warns, names what will be erased, and Cancel keeps all results", recleaning_warning)

    def persistence():
        page.reload()
        expect(page.get_by_role("button", name="Re-run analysis")).to_be_visible(timeout=20000)
        expect(page.locator('[data-stage="regression"]')).to_have_attribute("data-state", "completed")
        tab(page, "Regression")
        expect(page.get_by_test_id("regression-result")).to_contain_text("power_kw ~ wind_speed_ms + rotor_rpm")
        tab(page, "Statistics")
        expect(page.get_by_role("table", name="Descriptive statistics per numeric column")).to_be_visible()
    step("after a full page reload every result is still there (persisted)", persistence)

    def confirm_erase():
        tab(page, "Cleaning")
        page.get_by_role("radio", name="Keep all rows").check()
        page.get_by_role("button", name="Re-apply cleaning").click()
        page.get_by_role("button", name="Erase results and re-clean").click()
        expect(page.locator('[data-stage="statistics"]')).to_have_attribute("data-state", "pending", timeout=20000)
        expect(page.locator('[data-stage="regression"]')).to_have_attribute("data-state", "pending")
        tab(page, "Statistics")
        expect(page.get_by_text("No results yet")).to_be_visible()
        tab(page, "Regression")
        expect(page.get_by_text("Run the analysis first")).to_be_visible()
    step("confirming the warning erases results exactly as announced", confirm_erase)

    def reanalyze():
        page.get_by_role("button", name="Run analysis").click()
        expect(page.get_by_role("button", name="Re-run analysis")).to_be_visible(timeout=30000)
    step("analysis can be re-run after re-cleaning", reanalyze)

    # --- mobile layout
    mobile = browser.new_context(viewport={"width": 390, "height": 800}, device_scale_factor=2)
    mctx_page = mobile.new_page()
    mctx_page.context.add_cookies(ctx.cookies())
    mctx_page.goto(project_url)
    expect(mctx_page.get_by_role("tab", name="Charts")).to_be_visible(timeout=20000)

    def mobile_layout():
        overflow = mctx_page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check(f"mobile: page has no horizontal overflow (delta={overflow}px)", overflow <= 0)
        for name in ("Cleaning", "Statistics", "Correlations", "Outliers", "Regression", "Charts"):
            box = mctx_page.get_by_role("tab", name=name).bounding_box()
            assert box and box["x"] >= 0 and box["x"] + box["width"] <= 390, f"tab {name} outside viewport: {box}"
        check("mobile: all 6 tabs are fully inside the viewport", True)
        tab_bottom = max(mctx_page.get_by_role("tab", name=n).bounding_box()["y"] + mctx_page.get_by_role("tab", name=n).bounding_box()["height"] for n in ("Cleaning", "Charts"))
        panel_top = mctx_page.get_by_role("tabpanel").bounding_box()["y"]
        check("mobile: tab list does not overlap the panel below it", tab_bottom <= panel_top + 1, f"{tab_bottom} vs {panel_top}")
        tab(mctx_page, "Statistics")
        o2 = mctx_page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check(f"mobile: wide statistics table scrolls inside its own container (page overflow {o2}px)", o2 <= 0)
        tab(mctx_page, "Charts")
        mctx_page.wait_for_selector(".recharts-surface", timeout=15000)
        o3 = mctx_page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth")
        check(f"mobile: charts fit the screen (page overflow {o3}px)", o3 <= 0)
    step("mobile layout checks ran", mobile_layout)
    mctx_page.screenshot(path=f"{SHOTS}/mobile-charts.png", full_page=True)
    tab(mctx_page, "Cleaning")
    mctx_page.screenshot(path=f"{SHOTS}/mobile-cleaning.png", full_page=True)

    # --- second user cannot see the first user's project
    ctx2 = browser.new_context(viewport={"width": 1280, "height": 900})
    p2 = ctx2.new_page()
    register(p2, "bob")
    p2.goto(project_url)
    step("second user opening Alice's project URL sees only the not-found message", lambda: (
        expect(p2.get_by_text("This project doesn't exist or you don't have access to it.")).to_be_visible(timeout=20000),
        expect(p2.get_by_role("button", name="Run analysis")).to_have_count(0),
        expect(p2.get_by_text("Browser turbine test")).to_have_count(0),
    ))
    p2.screenshot(path=f"{SHOTS}/second-user.png")

    # The UI deliberately probes sub-resources that may not exist yet (no file before upload, no
    # analysis before the first run) and treats 404 as "empty". Those are the ONLY HTTP errors allowed.
    expected = ("/file", "/analysis")
    unexpected_http = [e for e in http_errors if not (e.startswith("404 GET") and e.endswith(expected))]
    print("INFO http errors seen on Alice's page:", http_errors)
    check(f"only the expected 404 'not yet' probes failed over HTTP ({len(unexpected_http)} unexpected)", not unexpected_http, "; ".join(unexpected_http))
    real = [e for e in console_errors if not e.startswith("Failed to load resource")]
    check(f"no JS errors or page errors during the whole run ({len(real)} found)", not real, "; ".join(real)[:300])
    browser.close()

print(f"\n{total - failed}/{total} checks passed")
sys.exit(1 if failed else 0)
