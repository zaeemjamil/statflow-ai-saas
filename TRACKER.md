# StatFlow AI — requirement tracker

Legend: ✅ implemented **and verified** · 🟡 implemented, a specific part cannot be verified here · ⛔ not built / blocked · "author-side" = verified by the author, **not independently reviewed**.

**Scope note.** The original Phase 1 audit and Phase 2 UI/UX spec documents were not available. This tracker follows the scope documented inside the repository (README, RECOVERY.md Stage 2 notes, code comments). Nothing was silently dropped; items without a documented phase are listed at the bottom.

| # | Requirement | Status | Evidence (all author-side) |
|---|---|---|---|
| 1 | Authentication: register, login, logout, me, forgot/reset password, HttpOnly cookie | ✅ | pytest (35 auth tests); `e2e_auth` ALL PASSED via Caddy; browser journey 101/101 |
| 2 | Sign-in brute-force protection; reset-request throttling (no enumeration) | ✅ | 11 tests (`test_auth_hardening`); e2e: 8 wrong passwords then 429, correct password refused while locked |
| 3 | Password-reset email delivery (provider-neutral SMTP, sent in background) | 🟡 | Unit tests with a fake SMTP (STARTTLS/SSL, link, no token in logs, failures swallowed). **Not verified against a live mail server** (needs your SMTP details) |
| 4 | Projects CRUD + strict ownership (404 for others) | ✅ | pytest; `e2e_projects` ALL PASSED; isolation checks in new e2e |
| 5 | Upload CSV/XLSX with size, row, column limits | ✅ | pytest; `e2e_upload_limits` 32/32 via Caddy |
| 6 | Dataset profiling | ✅ | pytest; browser journey |
| 7 | Cleaning (missing values, duplicates, report) | ✅ | pytest; `e2e_analysis` 64/64; browser journey |
| 8 | Statistics, correlations, outliers | ✅ | pytest; `e2e_analysis` 64/64 |
| 9 | Regression | ✅ | pytest; `e2e_analysis`; browser journey |
| 10 | Charts / visualizations | ✅ | pytest; browser journey |
| 11 | Dashboard and complete user workflow | ✅ | `browser_e2e` 30/30, browser journey 101/101 (incl. mobile, dark mode, axe accessibility: 0 serious/critical) |
| 12 | **Phase 9 Stage 1** — AI evidence layer (aliases, closed vocabulary, eligibility, canonical JSON, 32,768-byte cap) | ✅ built · ⛔ **not formally accepted** | 6g candidate; needs independent review. Checkpoint 5 baseline comparison **blocked** (archive unavailable) |
| 13 | **Phase 9 Stage 2** — provider integration (OpenRouter-compatible, key never logged, redirects refused, response capped) | 🟡 | 54 tests; sends only `canonical_json()`; e2e confirms no column name/category value reaches the provider. **Not run against the live provider** (needs `OPENROUTER_API_KEY`) |
| 14 | Phase 9 — AI endpoints, storage in `analyses.ai_insights`, alias restore on read, stale-explanation withholding, cooldown, daily cap, untrusted-output validation | ✅ | tests + e2e 33/33; 8 mutation checks caught |
| 15 | Phase 9 — frontend AI analyst tab (not-configured / ineligible / small-sample / limit / error states, plain-text rendering) | ✅ | 7 component tests; browser journey (tab bar, keyboard, axe) |
| 16 | **Phase 10** — PDF reports (same numbers as dashboard, charts, optional AI section, safe text, Unicode font) | ✅ | 17 tests incl. hostile names, number match, 6 mutation checks; e2e checks PDF numbers equal dashboard numbers |
| 17 | Phase 10 — report storage, list, download, delete, retention (20), cleanup with project, ownership | ✅ | tests + e2e; frontend reports panel (5 tests) |
| 18 | 4d early-`Content-Length` upload limitation | ✅ in production topology · 🟡 in dev | Caddy refuses declared >limit instantly (probes: 200 MB and limit+1 → 413 in 0.0 s; exactly the limit passes). Still present if Next.js alone proxies (development) |
| 19 | Production configuration guards (strong secret, HTTPS URL + secure cookie, HTTPS AI endpoint, SMTP needs host) | ✅ | config tests |
| 20 | Deployment package (Docker Compose, Dockerfiles, Caddy HTTPS, env template, `DEPLOYMENT.md`) | 🟡 | Config validated: Caddy loaded the real Caddyfile; stack run natively on PostgreSQL. **Docker images not built (no Docker here)**; automatic HTTPS needs your domain |
| 21 | Error handling / reliability | ✅ | uniform error envelope, safe provider/SMTP failures, 502/429/409 paths tested |
| 22 | Quality gates | ✅ | pytest 721 passed · ruff clean · format clean · mypy strict 123 files · frontend lint/typecheck clean · vitest 85 (+8 contract tests 8/8 live) · `next build` ok |
| 23 | Billing / subscriptions | ⛔ | No phase or provider specified anywhere in the repo; only an unused data model. **Needs your product decision** (and a payment account) |
| 24 | Formal checkpoint acceptance (6g, release build) | ⛔ | Requires independent review — not claimed |

## What needs you
1. Deploy (DEPLOYMENT.md): domain, server, secrets, `docker compose up`.
2. For AI: an OpenRouter API key. For password-reset emails: SMTP host/user/password.
3. A decision on billing (if wanted) and who performs the independent review of 6g / this release.
