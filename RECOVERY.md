# Zaimex — Recovery Guide

**Current phase:** **Phase 9 Stage 1 (AI evidence layer) - CANDIDATE 6g (serialization cap/contract corrections; builds on 6f), author-side verified only, awaiting independent review. NOT accepted.** History: the first Stage 1 candidate
(`zaimex-checkpoint-6-phase9-stage1-evidence-layer.zip`) was rejected (original column names in the packet; 10-row minimum); 6b/6c/6d applied later review findings (aliases, 5/30-row policy, closed vocabularies, separate local alias
map, duplicate-name handling, test fixes; see the "Checkpoint 6c", "6d" and "6e" sections below). 6e fixes exactly three audit findings: a mutable `EvidencePacket.content`, a test/doc contradiction about unknown note codes, and this
status text. 6f added the serialization-contract tests and tooling gates; 6g corrects the 6f audit findings F1-F3 (see the "Checkpoint 6g" section). Stage 2 and the rest of the roadmap were implemented AFTER 6g as a release build (see "Release build after 6g" at the end of this file and `TRACKER.md`); none of that later work has had independent review, and Stage 1 (6g) itself is still NOT accepted. Cumulative on top of the accepted Checkpoint 5 baseline `zaimex-checkpoint-5-phase8-final-verification.zip`
(SHA-256 of the copy reviewed: `02943d041dc9f6f5928ce4dca48c0f3748af03d310849dda021006dc80085aab`, 385,912 bytes). Claim, NOT independently re-verified (the Checkpoint 5 archive was not available in the later review sandboxes): against that
baseline the only changes are new files under `backend/app/ai/` and `backend/tests/`, plus this RECOVERY.md.
(This paragraph describes the 6g Stage 1 candidate. The later release build added a provider, endpoints and frontend features, still with NO migration: alembic single head is still `41696db86df6`.)
The early-`Content-Length` upload limitation (4d) still exists when Next.js alone proxies the API (development topology). In the production topology (Caddy in front, `deploy/Caddyfile`) it is closed and verified: see the release section.
**Latest checkpoint:** `zaimex-checkpoint-6g-phase9-stage1-serialization-cap-corrections.zip` (6f: `zaimex-checkpoint-6f-phase9-stage1-serialization-contract.zip`, kept unmodified; 6e: `zaimex-checkpoint-6e-phase9-stage1-integrity-corrections.zip`, kept unmodified; 6d: `zaimex-checkpoint-6d-phase9-stage1-verification-corrections.zip`, kept unmodified; 6c: `zaimex-checkpoint-6c-phase9-stage1-final-corrections.zip`, kept unmodified; 6b: `zaimex-checkpoint-6b-phase9-stage1-corrections.zip`, kept unmodified) (in `/mnt/user-data/outputs/`; its byte size and SHA-256 are
given in the hand-off message, not here, because a file cannot contain its own hash). The first candidate ZIP is kept, unmodified, for the record.
Earlier ZIPs are kept untouched: `zaimex-checkpoint-5-phase8-final-verification.zip` (accepted Checkpoint 5 baseline),
`zaimex-checkpoint-5s3r-v1-hardening-stage3-review-fixes.zip` (accepted Stage 3 baseline, SHA-256 `a74d09f49a398ad606fabb76b7c6a2d6352cf9d8b6a5a257ceba3885d651d507`),
`zaimex-checkpoint-5s3-v1-hardening-stage3-data-correctness.zip` (Stage 3 before its review fixes),
`zaimex-checkpoint-4d-v1-hardening-stage1-2-verified-fixes.zip`, `zaimex-checkpoint-4-phase8b-cleaning-analysis.zip`,
`zaimex-checkpoint-4b-v1-hardening-stage1-upload-safety.zip` and `zaimex-checkpoint-4c-v1-hardening-stage1-2-upload-and-chart-payload.zip`
(4c has the defects fixed in 4d). Checkpoints are cumulative: each contains the whole project (backend/ + frontend/) as of that point.
**Not started (do not begin without review):** Phase 9 Stage 2 onward (provider call, API endpoint, storage of AI output, frontend AI UI),
Phase 10 (PDF reports), any fix for the 4d early-`Content-Length` limitation (still open, still documented), deployment work.

## Restore

```bash
mkdir -p /home/claude/zaimex && cd /home/claude/zaimex
unzip /mnt/user-data/outputs/zaimex-checkpoint-6g-phase9-stage1-serialization-cap-corrections.zip   # -> RECOVERY.md, backend/, frontend/
cd backend  && python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
cd ../frontend && cp .env.example .env.local && npm ci
```

The sandbox can be wiped between sessions. Not in a zip = lost: `node_modules`, venvs, PostgreSQL, `.env` files.
PostgreSQL: `apt-get update && apt-get install -y postgresql` (the `update` is required, a bare install 404s), then `service postgresql start`.
Create role/db `zaimex` (see DATABASE_URL below) and run `alembic upgrade head`.

**Sandbox gotchas:** (Checkpoint 5) after a pause BOTH PostgreSQL and the servers were down; `service postgresql start`, then the start
script, then wait ~10 s before the first request (an empty `curl` just means "not up yet"; the second start attempt printed
`EADDRINUSE` because the first had finished starting). `npm run build` must be re-run after any frontend change before
`next start`, or the old build answers. Background jobs started with `&` inside a tool call (e.g. `npm run ... &`) are killed when
the call returns: run them in the foreground. `/bin/sh` is the tool shell (`${PIPESTATUS[0]}` needs `bash -c`). Older note: servers started with `setsid cmd </dev/null >log 2>&1 &` DID survive between tool calls in the 4d
session (PostgreSQL also needed `service postgresql start` again after a pause). A stale server then makes a new
`next start` fail with `EADDRINUSE` while the OLD build keeps answering, so e2e results can silently come from old code:
check the fresh log for "Failed to start" / "Ready", or stop everything first. Never `pkill -f "<pattern>"` where the
pattern appears in your own command line (it kills the shell; this happened three times). Put start/stop commands in a
script file (`/tmp/start_stack.sh`, `/tmp/stop_stack.sh`) and run that. `ss` is not installed. Google Fonts is unreachable: the app uses the
self-hosted `geist` package.

## Environment variables

Backend (`backend/.env`, not shipped; see `backend/.env.example`):

| Variable | Notes |
|---|---|
| `DATABASE_URL` | Use `postgresql+psycopg2://…`, not bare `postgresql://` |
| `FRONTEND_URL` | CORS allow-origin, e.g. `http://localhost:3000` |
| `JWT_SECRET` | ≥32 chars; production rejects placeholder/short values |
| `COOKIE_SECURE` | Defaults `true`; set `false` **only** for local http |
| `LOCAL_STORAGE_PATH` | Upload dir for dev |
| `MAX_CSV_UPLOAD_SIZE_MB` / `MAX_XLSX_UPLOAD_SIZE_MB` | V1 hardening: per-type upload limits (defaults 25 / 10). `MAX_UPLOAD_SIZE_MB` (default now 25) stays as the overall ceiling; effective limit = min(per-type, ceiling) |
| `MAX_DATASET_ROWS` / `MAX_DATASET_COLUMNS` | V1 hardening: data-row (header excluded) and column limits (defaults 100000 / 100), enforced while parsing |
| `MAX_XLSX_UNCOMPRESSED_SIZE_MB` | V1 hardening: refuse an .xlsx that unpacks to more than this (default 250) |

Frontend (`frontend/.env.local`, from `.env.example`): `BACKEND_URL` (default `http://127.0.0.1:8000`),
`NEXT_PUBLIC_SESSION_COOKIE` (must equal backend `COOKIE_NAME`, default `access_token`).
Optional, V1 hardening (display + pre-check only; backend is the authority; inlined at build time):
`NEXT_PUBLIC_MAX_CSV_UPLOAD_MB`, `NEXT_PUBLIC_MAX_XLSX_UPLOAD_MB`, `NEXT_PUBLIC_MAX_DATASET_ROWS`, `NEXT_PUBLIC_MAX_DATASET_COLUMNS`.

> A `backend/.env` containing a real-looking `JWT_SECRET` makes `test_production_rejects_the_placeholder_jwt_secret`
> fail (env-file leakage). Move `.env` aside before running `pytest`.

## Verify

```bash
# backend/  (move .env aside first)
pytest                                  # Phase 9 Stage 1 candidate 6g: 635 passed (author-side run; environment and per-file counts in the "Checkpoint 6g" section at the end of this file)
ruff check . && ruff format --check . && mypy app tests
alembic upgrade head && alembic heads   # single head: 41696db86df6

# frontend/
npm run typecheck && npm run lint && npm test && npm run build    # Checkpoint 5: 73 passed + 8 skipped (13 files; 68 before = +3 workspace, +2 api; the 8 skipped are the gated contract test); 11 routes + proxy
# API-contract test (real backend, same Zod schemas as the app; skipped unless CONTRACT_BASE_URL is set; 8 tests)
CONTRACT_BASE_URL=http://localhost:3000 npx vitest run src/lib/contract.integration.test.ts   # also works with http://127.0.0.1:8000

# real HTTP e2e through the Next origin (API on :8000 with COOKIE_SECURE=false, `next start -p 3000`)
bash scripts/e2e_auth.sh                # 22 checks (22 PASS in 4d)
../backend/.venv/bin/python scripts/e2e_projects.py http://localhost:3000   # 43 checks (43 PASS in 4d; needs backend deps: httpx, pandas, openpyxl)
../backend/.venv/bin/python scripts/e2e_analysis.py http://localhost:3000   # 64 checks: clean/analyze/regression, pandas cross-check, persistence, isolation (64/64 in 4d)
../backend/.venv/bin/python scripts/e2e_upload_limits.py http://localhost:3000 http://127.0.0.1:8000   # 4d: 31/32 — see below; the one FAIL is a known limitation, not a regression
python ../backend/scripts/e2e_phase8a.py http://127.0.0.1:8000/api/v1   # backend analysis e2e (ALL CHECKS PASSED in 4d)

# REAL browser test (headless Chromium via Playwright; 30 checks, 30/30 in 4d). Uses SYSTEM python3, which has playwright,
# numpy and pandas (the backend venv does not have playwright). Browsers live in $PLAYWRIGHT_BROWSERS_PATH (/opt/pw-browsers).
mkdir -p /tmp/shots && python3 scripts/browser_e2e.py http://localhost:3000 /tmp/shots
# Checkpoint 5 journey + data-correctness + errors + keyboard + axe-core (light & dark) + responsive (101 checks, 101/101 in Checkpoint 5).
# The legacy-project step needs the backend venv python and the DB URL (otherwise it is reported "NOT RUN"). Needs node_modules/axe-core.
python3 scripts/browser_journey_e2e.py http://localhost:3000 /tmp/shots --backend-python ../backend/.venv/bin/python --database-url "$DATABASE_URL"
```

## Checkpoints
1. ✅ Phase 8A backend API  2. ✅ Phase 8B app shell/auth  3. ✅ Phase 8B dashboard/projects/upload
4. ✅ Phase 8B cleaning + analysis dashboard  5. ✅ Final Phase 8 frontend/integration verification (accepted baseline)
6. ⏳ Phase 9 Stage 1 — AI evidence layer; first candidate not accepted (privacy); latest candidate 6g awaiting independent review, NOT accepted (Stage 2 not started)

## Phase 9 Stage 1 — AI evidence layer (2026-10-20; corrected 2026-10-22)

**Scope (as approved):** evidence packet builder, stable fingerprinting, eligibility checks, evidence size limits, unit tests. Nothing else.
**Assumption to confirm:** the written Phase 9 plan was not available to the implementer; Stage 1 was built from the scope statement.

### What was added (all new files; zero existing files modified except this RECOVERY.md)
| File | Purpose |
|---|---|
| `backend/app/ai/__init__.py` | Package doc: offline, pure, no provider/key/network/DB write |
| `backend/app/ai/aliases.py` | `ColumnAliasMap`: LOCAL-ONLY original<->alias mapping (refuses repr/pickle/JSON) |
| `backend/app/ai/eligibility.py` | `check_eligibility(AnalysisPublic)` -> `EligibilityResult(eligible, reason_code, message, warnings)`; `EvidenceNotEligible` (a `ConflictException`, HTTP 409 if ever surfaced; no endpoint uses it) |
| `backend/app/ai/evidence.py` | `build_evidence(AnalysisPublic)` -> local `EvidenceBuild(.packet, .aliases)`; `build_evidence_packet()` -> provider-facing `EvidencePacket(content, fingerprint, size_bytes)` only; size tiers |
| `backend/app/ai/fingerprint.py` | `canonical_json`, `fingerprint_content`, `normalize_number/text` |
| `backend/app/ai/loader.py` | `evidence_packet_for_analysis(Analysis row)` = `build_evidence_packet(project_analysis_service.to_public(row))`; reads only |
| `backend/tests/ai_helpers.py`, `test_ai_fingerprint.py`, `test_ai_eligibility.py`, `test_ai_evidence.py`, `test_ai_evidence_api.py`, `test_ai_aliasing.py` | 95 tests |

Architecture preserved: the packet is built from `AnalysisPublic` (what `GET /analysis` returns), so an explanation can only quote numbers
the dashboard shows. `app/analytics/*`, services, models, schemas, API routes, config, frontend and migrations are untouched.

### Correction pass (what changed from the first candidate, and why)
1. **Column aliases (privacy).** The first candidate cleaned column names (control characters, length) and still put them in the packet. Sanitizing is
   not anonymizing. Now NO original column name is in the packet: every column is `Column_001`, `Column_002` ... (3 digits, more only if >999 columns),
   numbered in dataset order, used identically in every section (columns, statistics, skipped columns, cleaning actions, correlations, outliers,
   regression target/predictors/coefficients, charts, import notes). The regression constant term is `intercept`. Aliases are assigned for ALL columns
   (including ones cut by size limits), so an alias never changes between size tiers.
2. **Exact-string aliasing.** Lookup uses the exact original string, so look-alike names (NFC vs NFD `café`, `Price` vs `price `, full-width letters) get
   different aliases; a name that appears twice in the profile still gets one alias per position (references by name resolve to the first). Names mentioned
   by other sections but absent from the profile get aliases after the profile's, in a fixed order. A name with no alias would print `Column_unmapped`
   (fail-safe; never expected, tested not to occur).
3. **Local-only mapping.** (Since 6c) The mapping is `EvidenceBuild.aliases`, a separate local object - not on `EvidencePacket`, not in `content`, not in the fingerprint, and
   `ColumnAliasMap` refuses `pickle`/`json`; its `repr` prints only a count. Stage 2 uses it locally to turn `Column_003` back into a real name for display.
4. **Free text is templated, not copied.** Import-note messages and chart titles can quote column names, sheet names, cell values or instructions. Each known
   note code is re-stated from a fixed template using aliases and counts only (the `formatted_numbers_as_text` note, which quotes example cell values, is
   one of them); an unknown/future note code is NOT passed through: it is reported as the safe constant `"unknown"` (closed vocabulary; fixed in 6e, earlier text said it kept its code), keeping only its (closed) severity and aliased columns, with no message. Chart titles are rebuilt as e.g. `scatter: Column_003 vs Column_002`.
   Sheet names are never included (only a count). (SUPERSEDED in 6c: token SHAPE is no longer enough, see below.) Engine labels pass only if they are MEMBERS of a closed vocabulary. Cleaning settings are whitelisted. Every remaining string also gets a final control/invisible-character scrub.
5. **Row policy** (rows after cleaning; both numbers in `eligibility.py`): fewer than `MIN_ROWS_FOR_EXPLANATION` = **5** -> refused with the existing `too_few_rows`;
   5-29 -> eligible with machine-readable warning `small_sample`; `SMALL_SAMPLE_ROWS` = **30** or more -> no warning from this rule. The warning is on
   `EligibilityResult.warnings` and in the packet as `warnings: [{"code":"small_sample","rows_after_cleaning":N,"threshold_rows":30}]` (always present, empty when none).
   **The warning does not establish reliability.** 30+ rows does not either. Future AI explanations must avoid unsupported statistical-significance or
   causal claims at any row count.
6. `EVIDENCE_SCHEMA_VERSION` bumped 1 -> 2 (shape and meaning changed). `MAX_EVIDENCE_BYTES` = 32,768, the four size tiers, the canonical fingerprint algorithm and the known-answer test are unchanged.

### Eligibility rules (first failing rule is reported; codes are stable strings)
1. `analysis_not_completed`  2. `statistics_not_completed`  3. `no_dataset_profile`  4. `too_few_rows` (< 5 rows after cleaning; cleaned profile preferred, so removing
duplicates can make a dataset ineligible, or add the small-sample warning)  5. `no_numeric_columns`  6. `evidence_too_large` (raised by the builder if even the smallest tier exceeds the cap).
Correlations, outliers, regression and charts are optional: absence never blocks, and `coverage` says `included` / `not_available` / `not_run` / `omitted_for_size`.

### Packet contents and what is deliberately excluded
Included: `schema_version`, `dataset` counts, `warnings`, `columns` (alias, type, missing/unique counts, flags; exact min/max withheld since schema_version 3), `import_notes` (code, severity, aliased columns, template message,
aliased per-column kinds), `cleaning` (whitelisted settings, counts, per-column actions), `statistics`, top `correlations.pairs`, `outliers` (counts/bounds of flagged columns),
`regression` (model, metrics, coefficients, residual summary), `charts` (type, templated title, aliased columns), `coverage`, `omitted`.
Never included: ORIGINAL COLUMN NAMES, sheet names, raw rows, exact column minimum/maximum values (withheld from `columns` and `statistics` since schema_version 3; other summary numbers such as a median can coincide with a real value), `outlier_indices`, `sample_predictions`, chart point data, the full correlation matrix, text fill values,
import-note `details`/examples, free-text titles/messages, ids, timestamps, file name, project name, the alias mapping.

### Fingerprint rules
`"sha256:" + SHA-256(canonical JSON)`: sorted keys, no spaces, ASCII escapes, NaN/inf -> null, -0 -> 0, floats rounded to 6 significant digits, text NFC, list order kept,
bool/int/string distinct, non-JSON types and colliding keys rejected. Built from packet content only. A known-answer test pins the algorithm (`c7fd0072...5db1`, also checked with `sha256sum`).
Consequences of aliasing, by design: **renaming columns without changing anything else does NOT change the fingerprint** (the AI never saw the names); **reordering columns DOES** (aliases follow
position); the small-sample warning is part of the evidence. Stage 2 must therefore translate aliases with the CURRENT local alias map (`EvidenceBuild.aliases`), never with a stored one.

### Size limits
`MAX_EVIDENCE_BYTES` = 32,768 (canonical JSON; a byte bound, not a token count). Four fixed tiers of per-list caps; the first that fits wins, so results are deterministic.
Every cut is listed in `omitted` as `{section, shown, total}`. Measured: typical 40-row/5-column analysis with regression = 4,642 bytes (nothing cut); 13-column hostile scenario = 10,925 bytes; deliberately extreme 100 columns + 24 predictors = 20,773 bytes (cuts disclosed; was 30,889 before aliasing).

### Notes for Stage 2 (not done here)
- Names never enter the packet, but the AI's OUTPUT will cite aliases (and could be wrong or hostile); render it as untrusted text and map aliases back locally for display only.
- Do not claim significance, causation or reliability from the evidence; the `small_sample` warning is a flag, not a verdict.
- `OPENROUTER_API_KEY` / `OPENROUTER_MODEL` settings and `analyses.ai_insights` already exist and are untouched and unused.
- Known simplifications: with extremely many columns (>999) alias width grows (not reachable: uploads are capped at 100 columns); `ignored_sheet_count_listed` can understate (upstream lists few sheet names).

### Test changes in the correction pass (the 482 baseline tests are untouched; only first-candidate Stage 1 tests changed, all listed here)
- Replaced: `test_hostile_column_names_become_single_line_bounded_text` (asserted the OLD behaviour - sanitized names kept in the packet) -> superseded by `test_ai_aliasing.py`.
- Replaced: `test_row_threshold_boundary_is_exact` (10-row policy) -> parametrized 4/5/29/30 boundary test; `test_row_count_is_judged_after_cleaning_not_before` re-based on the new numbers.
- Re-keyed to aliases (same intent): packet-numbers, outliers, raw-cell-value and note-example tests. Fingerprint test: renaming a column now asserts the fingerprint is UNCHANGED (new design); schema-version test uses 99 (2 is now the real version).
- Added: 28 aliasing/leakage tests, boundary and warning-propagation tests, API-level small-sample, too-few-rows and name-free tests. Leakage tests were mutation-checked: 13 deliberate re-introductions of original names (every section, note messages, chart titles, mapping inside the content) were each caught.

### Phase 9 Stage 1 verification record (RUN this session by the implementer; Python 3.12.3, Node 22; SQLite test DB)
[Historical record of the 6b-era run, kept for history; superseded by the "Checkpoint 6g" record at the end of this file.] Backend: `pytest` 577 passed (baseline re-run first: 482 passed); `ruff check .` clean; `ruff format --check .` clean; `mypy app tests` (strict) clean (104 files).
Frontend (code unchanged): `npm run typecheck` pass; `npm test` 73 passed + 8 skipped (same as Checkpoint 5); `eslint .` clean.
NOT run this session (no PostgreSQL / running servers; nothing they cover was touched): `npm run build`, `alembic upgrade head` against Postgres, the real-HTTP e2e scripts, the Playwright browser journey,
`e2e_upload_limits.py`. Known open limitation, unchanged and still documented, NOT fixed and not touched by Stage 1: the early-`Content-Length` upload rejection through Next
(declare 200 MB, send nothing) - see "Remaining limitations" below.

## V1 hardening (post-checkpoint 4) — Stages 1, 2 and 3 implemented
Approved plan after the upload/dataset audit. Checkpoint 4 itself was NOT rebuilt or reverted. Work is staged and each
stage stops for review:
- **Stage 1 (Priority 1, upload & dataset safety): implemented.**
- **Stage 2 (Priority 2, chart/response payload size): implemented.**
- **Stage 3 (Priority 3, generic data correctness): implemented (see "Stage 3" below).** Original brief: "NA" must not be silently treated as missing, warn on
  extra XLSX sheets, detect likely identifier columns from data characteristics (explain, never silently drop), identify
  currency/percent/thousands formats, flag ambiguous dates and duplicate/blank headers. (Stage 1 already added UTF-8/UTF-16
  handling and the `unsupported_encoding` error because Priority 1 required clear encoding errors; a cp1252/Latin-1
  fallback was deliberately NOT added — it is a Stage 3 decision.)

## Stage 3 — generic data correctness (what changed)
Principle: **detect and explain; never silently change or drop the user's data.** Cleaning, statistics, correlations,
outliers, regression and chart numbers are computed exactly as before. Findings are "import notes" (`code`, `severity`
info|warning, `message`, `columns`, `details`) stored in the upload profile and shown in the UI panel
"Things to check in your data". Notes exist only on profiles produced by a new upload; the cleaned-data profile and
profiles stored before Stage 3 have none (the API/zod fields are optional, so they validate unchanged).

| Item | Behaviour |
|---|---|
| Text `NA` | The parser no longer treats `NA` as missing (`keep_default_na=False` + pandas' other default tokens listed explicitly in `data_quality.NA_TOKENS_WITHOUT_NA`; blank, `N/A`, `n/a`, `#N/A`, `null`, `NULL`, `None`, `NaN`, `nan`… behave as before — pinned by a test against stock pandas). Then per column: every other value numeric -> `NA` becomes missing and the column numeric (`na_text_read_as_missing`, info); otherwise (text column, or a column that is only `NA`) -> kept as the literal value (`na_text_kept_as_value`, warning). Same code path for CSV and XLSX and for the analysis re-read of the stored file (`parse_dataset`), so classifications and data agree. **Uploads made before Stage 3 are re-read with pandas' old policy instead (see "Stage 3 review fixes", item 3).** |
| Extra XLSX sheets | Still only the first sheet is read. `xlsx_extra_sheets` warning names the analysed and ignored sheets (read from `xl/workbook.xml`, ≤1 MiB, best effort, never fails an upload; no extra workbook load, `read_excel` call pattern unchanged). |
| Identifier columns | `detect_identifier` (data, not names; needs ≥20 non-missing values): `sequential_integers` (all distinct whole numbers spanning ≤1.5×N, not a calendar-year window 1800–2200) and `unique_text` (≥98% distinct text). Columns detected as formatted numbers are never identifiers. **Flagged and explained, not excluded** from any analysis (an exclusion control would be a new feature). Per-column `likely_identifier`/`identifier_reason` + note `likely_identifier_columns`. |
| Currency / percent / thousands | Text columns where ≥90% of a deterministic ≤1000-value sample match `$1,200` / `12,50 €` / `(50)` style currency (symbols `$ € £ ¥ ₹`), `45%`, or comma-grouped `1,234`: `number_format` + examples + note `formatted_numbers_as_text` (warning). **Values are NOT converted** (percent scale and `1,234` vs `1.234` are locale-ambiguous): such a column stays categorical, and the note says so and how to fix the file. |
| Ambiguous dates | For date-classified text columns of numeric `d/m/y` dates: `date_order_issue` = `ambiguous` (nothing proves an order), `inconsistent` (both orders proven), `partly_ambiguous` (one order proven, some rows could be either); note `ambiguous_dates`. ISO and month-name dates, and columns whose rows all prove one order, are not flagged. Dates are not converted (Zaimex only classifies date columns today). |
| Headers | pandas' automatic names are recognised and reported: `Unnamed: N` (`blank_headers`) and `name.k` next to `name` (`duplicate_headers`). Names are not changed. A header the user really wrote as `price.1` next to `price` is indistinguishable and is reported as well ("look like"). |
| cp1252 / Latin-1 | **Decision: not added.** Non-UTF-8 CSVs are still refused with instructions (`unsupported_encoding`). Many multi-byte or non-Latin encodings (Shift-JIS, GBK, Cyrillic) can "successfully" decode as cp1252 into garbage, which is worse than a clear refusal. Revisit only with a user-visible, confirmed encoding choice. |

Files changed vs 4d: `backend/app/services/file_service.py`, `backend/app/analytics/profiling.py`, `backend/app/schemas/upload.py`,
`frontend/src/lib/schemas.ts`, `frontend/src/components/projects/profile-view.tsx`, `RECOVERY.md`; new:
`backend/app/analytics/data_quality.py`, `backend/tests/test_data_quality_unit.py`, `backend/tests/test_data_quality_api.py`,
`frontend/src/components/projects/profile-view.test.tsx`. No migration, model, auth, proxy or e2e-script change.

### Stage 3 verification record (Python 3.12.3 / pandas 3.0.6, Node 22, PostgreSQL 16.15, Chromium via Playwright)
PASSED: backend `pytest` 446/446 (SQLite in-memory); `ruff check`; `ruff format --check` (93 files); `mypy app tests` strict
(90 files, no ignores); `alembic upgrade head` on PostgreSQL 16, single head `41696db86df6`; frontend `typecheck`, `lint`,
vitest 68/68 (12 files), `next build`; against the real stack (Next :3000 -> FastAPI :8000 -> PostgreSQL, API restarted on the
final code): `e2e_auth.sh` ALL PASSED, `e2e_projects.py` ALL PASSED, `e2e_analysis.py` 64/64, `e2e_phase8a.py` all checks,
`browser_e2e.py` 30/30, `e2e_upload_limits.py` 31/32 (the known failure below), plus an ad-hoc real check (not a shipped script):
a messy CSV uploaded through Next returned all five note kinds and a real Chromium page rendered the 5-item notes panel.
FAILED (1, known, unchanged from 4d, not fixed): `e2e_upload_limits.py` "early Content-Length 413 (200 MB declared, 0 sent)" through Next
(see the 4d record; the proxy limitations below are unchanged).
NOT RUN / NOT PROVEN: pytest against PostgreSQL; the new detectors on very large files (they scan a bounded sample or one
column at a time, but no timing was measured on a 100k x 100 file, nor XLSX with many sheets); non-Western real-world CSV corpora;
Firefox/Safari/phone; screen-reader check of the new panel; `npm audit`; everything listed as not run in 4d.
Behaviour changes to be aware of: (a) a CSV/XLSX whose text column contains `NA` now keeps `NA` as a value instead of
missing; a file of only `NA` cells is therefore accepted instead of refused as empty; (b) ~~projects uploaded before Stage 3 are
re-read with the same new rule~~ - **superseded by the review fixes**: legacy projects are re-read with the old rule, so their
stored profile and the analysed data agree (item 3 of "Stage 3 review fixes").
Stage 3 limitations: random-looking numeric IDs with large gaps are not flagged (indistinguishable from a unique whole-number
measure); currency detection covers `$ € £ ¥ ₹` symbols only (no ISO codes); formatted numbers are reported, not converted;
`None`/`null` text is still read as missing exactly as before (only `NA` was in scope).

## Checkpoint 5 — final Phase 8 frontend and integration verification (2026-10-17)
Baseline: `zaimex-checkpoint-5s3r-v1-hardening-stage3-review-fixes.zip`, SHA-256 `a74d09f4...d507` (verified before anything ran). Scope: verify the journey, contracts,
persistence, data-correctness display, upload limits, chart-sampling disclosure, errors, accessibility and responsive use; make
only small UI/accessibility fixes the verification itself showed were needed. No backend application code, API contract, schema,
migration, auth, ownership, upload-security or statistics change. No Phase 9/10, deployment or redesign work.

### Added (tests/tooling only)
| File | What |
|---|---|
| `frontend/src/lib/contract.integration.test.ts` | 8 tests. Registers a throwaway user, uploads clean/messy/blank/dotted-date/3,200-row fixtures, calls every endpoint the UI uses and parses each real response with the app's own Zod schemas; also checks the persisted `GET /analysis` equals the last POST, the error envelope for 401/404/409/422, and ownership 404s. Gated by `CONTRACT_BASE_URL` (so `npm test` shows 8 *skipped*; that is by design, not a weakened test). It also lists backend fields the schemas ignore: only `import_notes[].details`, which the UI does not display. |
| `frontend/scripts/browser_journey_e2e.py` | 101 checks in real Chromium: register, XLSX upload, profile, clean, analyze, every tab, regression, navigate away/back, reload, sign out, login again, a fresh browser context; messy CSV notes (exact texts and counts); all-blank column; ambiguous dotted dates; legacy-shaped project; 3,200-row chart-sampling disclosure; upload errors; simulated failures; double-click; expired session; keyboard/focus; axe-core scans (light and dark); 390/768/1280 px layout. |
| `backend/scripts/e2e_make_legacy.py` | Test helper: rewrites one project's stored profile to the pre-Stage-3 shape on the real database (a SIMULATION; no pre-Stage-3 build was available). |
| `frontend/package.json`, `package-lock.json` | `axe-core` 4.14.0 added as an exact-pinned devDependency (one line each). It was already installed transitively through `eslint-config-next` -> `eslint-plugin-jsx-a11y`, so the lockfile did not gain a package. `npm audit` is unchanged: 5 high (the known dev-tooling chain), 0 with `--omit=dev`; axe-core is not among them. |

### Findings and authorised fixes (first browser run on the UNCHANGED baseline build found them; the fixes were then verified)
| # | Finding (evidence) | Fix | Files |
|---|---|---|---|
| 1 | **Contrast (WCAG AA)**: axe `color-contrast` serious on every table header and the "Awaiting file" badge in light mode (`--muted-foreground` #64748b on `--muted` #f1f5f9 = 4.34:1). | Light-mode token darkened to #5b6b82 (4.95:1 on muted, 5.43:1 on white). Dark mode already passed. | `app/globals.css` |
| 2 | **Contrast**: the "Done" label of completed stages (`text-emerald-600`, 3.77:1 on white). | `text-emerald-700` (5.48:1). | `components/analysis/stage-strip.tsx` |
| 3 | **Re-clean warning not keyboard-friendly**: focus stayed on the (now removed) trigger, so keyboard/screen-reader users were not taken to the warning; Escape did nothing. | Focus moves to **Cancel** when it opens, Escape cancels, focus returns to "Re-apply cleaning". | `components/analysis/cleaning-panel.tsx`, `components/ui/button.tsx` (`ref` added to `ButtonProps`) |
| 4 | **Double submit**: two back-to-back clicks on "Run analysis" sent 2 `/analyze` requests (the button disables only after React re-renders). Same pattern for cleaning and regression. | A one-action-at-a-time ref guard released on settle (also after a failure). | `components/analysis/analysis-workspace.tsx` |
| 5 | **Unclear error after the session ends**: any action showed "Not authenticated." with a useless "Try again". | 401 with code `missing_token`/`invalid_token` now reads "Your session has ended. Please sign in again to continue." Login failures and `token_expired` keep their own texts. | `lib/api.ts` |
| 6 | **No level-one heading** on login, register, forgot/reset-password and "New project" (axe `page-has-heading-one`, moderate). | `CardTitle` takes `as`; those pages render `<h1>`. | `components/ui/card.tsx`, `components/layout/auth-card.tsx`, `app/(app)/projects/new/new-project-form.tsx` |

Added unit tests for 3, 4 and 5 (`analysis-workspace.test.tsx` +3, `api.test.ts` +2); run against the unfixed baseline source, the
three that exercise the defects FAIL there (double-click, dialog focus, 401 text) and the two control tests pass. No existing test was
edited except their import lines; none removed or weakened (analysis-workspace 15 -> 18 tests, api 3 -> 5).

Not defects (my own first-draft assertions were wrong; corrected, not the app): the 8-checkbox/Tab order of the regression form
(the select is the last tab stop until a target is chosen), 'NA' totals (the blank column adds 40 missing cells: 46 for a new upload,
54 for a legacy-shaped one), regression before any analysis is 404 `analysis_not_found` (409 `analysis_not_completed` only after `/clean`).

### Verification record (RUN IN CHECKPOINT 5 on the final tree; Python 3.12.3, pandas 3.0.6, Node 22, PostgreSQL 16, Chromium via Playwright)
PASSED: backend `pytest` 482/482 (SQLite); `ruff check`; `ruff format --check` (96 files); `mypy app tests` strict (92 files) and the new script;
`alembic upgrade head` on PostgreSQL 16 (single head `41696db86df6`); frontend `typecheck`, `lint` (0 warnings), vitest 73 passed + 8 skipped (gated),
`next build` (11 routes + proxy); against the real stack (Next :3000 -> FastAPI :8000 -> PostgreSQL), rebuilt and restarted on the final code:
`e2e_auth.sh` ALL PASSED, `e2e_projects.py` ALL PASSED, `e2e_analysis.py` 64/64, `e2e_phase8a.py` ALL CHECKS PASSED, `browser_e2e.py` 30/30,
contract test 8/8 through Next AND 8/8 direct to the API, `browser_journey_e2e.py` **101/101** (23 axe-core scans - 18 light, 5 dark - each with 0 violations at any impact).
FAILED (1, KNOWN, NOT FIXED, re-run and reproduced): `e2e_upload_limits.py` **31/32** - "early Content-Length rejection" through Next (declare 200 MB, send
no body: no response within 10 s; the same case passes direct to the API). Upload-limit verification is therefore NOT fully green. Everything else in that
script passes: through Next 15/16 (all but that case), direct to the API 16/16; the 8.77 MB XLSX near the limit took 27.4 s through Next and 26.3 s direct in this
session (4d measured ~12.8 s; the sandbox is slower now, the proxy still did not cut it off). In the browser a 32 MB CSV is refused locally, and a corrupt .xlsx and a
header-only CSV are rejected by the server and shown.
The first run of the new journey script on the baseline build FAILED 20 of 101 checks: 14 real findings (11 contrast scans, double click, dialog focus, 401 text) and 6 wrong assertions of mine (corrected in the script). The figures above are after the fixes.
SIMULATED (not real failures): the network-abort, 500, 502 and malformed-200 responses on `/analyze` use `page.route`; the legacy-shaped project is a real database row rewritten by `e2e_make_legacy.py`.
NOT RUN / NOT PROVEN: pytest against PostgreSQL (suite is SQLite by design); a legacy upload created by real pre-Stage-3 code; **screen-reader testing (none was done)**;
axe was not run on `/reset-password` or at the 390 px viewport (layout was checked there separately); automated axe cannot judge reading order, alt text quality or meaningful link text, so the accessibility result is "no automated serious/critical findings + keyboard checks",
not a full audit; Firefox/Safari/real phone; chunked uploads without `Content-Length`; a 100,000-row dataset in a browser (3,200 rows was used); concurrent uploads; large-XLSX timing; `npm audit fix`.

### What was verified, by area (existing behaviour that now has evidence)
- **Journey**: register, create project, XLSX upload (extra worksheet disclosed), profile, cleaning (2 -> 0 missing), analysis, statistics/correlations/outliers/charts, regression, sign out, protected pages redirect, login again - all in the browser.
- **Contracts**: every UI-used response parses with the app's Zod schemas via Next and direct; the stored `GET /analysis` equals the last POST response.
- **Persistence**: statistics and regression text identical after navigating away/back, hard reload, sign out + login again, and in a second fresh browser context.
- **Data correctness in the UI**: 5 notes (3 warnings, 2 info) with exact texts; metrics 3 numeric/3 categorical/1 date/46 missing; the blank column is categorical with 100% missing and absent from statistics, correlations and the regression pickers; ambiguous dotted dates warn; 'NA' read-as-missing vs kept-as-value both explained; a legacy-shaped project shows no notes, 54 missing, and cleaning/analysis use the same 54.
- **Chart sampling**: a 3,200-row file shows "Showing N of 3,200 points ... Statistics always use all rows." on each sampled chart and the number of scatter marks drawn (7,491 = 3 charts x 2,497) equals the disclosed totals; a 90-row file shows no disclosure.
- **Responsive**: no horizontal page overflow at 390, 768 and 1280 px on dashboard, projects, new project, profile+notes and all six tabs; all six tabs inside the 390 px viewport. One informational item: the 390 px "All projects" back link is 358x20 px (axe's WCAG 2.2 `target-size` rule passes it).

### Remaining limitations / defects after Checkpoint 5 (not fixed)
1. **4d early-`Content-Length` case through Next** (above): documented, unchanged; any fix needs separate approval.
2. **No automatic redirect to /login** when a session ends mid-use: the user now gets a clear message, but must navigate to sign in (the proxy redirects page loads only).
3. The profile table does not show the per-column Stage 3 fields (`likely_identifier`, `number_format`, `date_order_issue`); they reach the user only through the notes.
4. Backend sends `import_notes[].details`, which the frontend schema ignores (harmless).
5. Legacy projects cannot be re-uploaded from the UI (delete and recreate), so they keep the old `NA` rule.
6. Items 1-5 of "Known limitations / not done" below remain true except "No XLSX run through the browser test" (XLSX is now covered by the journey).

## Stage 3 review fixes (2026-10-17)
Review pass on `zaimex-checkpoint-5s3-v1-hardening-stage3-data-correctness.zip`. Only the three reported defects were fixed; no rebuild, no Checkpoint 5 / Phase 9 / Phase 10 work, no AI,
PDF, deployment, UI, model, migration, auth, proxy or e2e-script change.

| # | Defect | Fix |
|---|---|---|
| 1 | `_classify_column` checked the numeric dtype before checking for values, so a CSV/XLSX column of only blank cells (inferred `float64`) was a "numeric" column with no data. | `backend/app/analytics/profiling.py`: after the bool check and **before** any dtype check, a column with at least one row and no non-missing value is `categorical` (`min_value`/`max_value` stay `null`, `missing_percentage` 100, `unique_count` 0). It is therefore not counted in `numeric_column_count` and is skipped by statistics/correlations/outliers/regression pickers (it appears in `skipped_columns`); cleaning already handled an empty mode. Partially missing numeric columns are unchanged (still numeric, min/max and statistics over the values present). A zero-row frame keeps its dtype classification. No new import note was added (out of scope; the 100% missing figure is shown in the column table). |
| 2 | `_DATE_LIKE_PATTERN` had no dot, so `01.02.2025` was never tried as a date, became `categorical`, and `ambiguous_dates` never fired although `data_quality._NUMERIC_DATE_RE` supports dots. | `profiling.py`: the pattern now also matches the full dotted shape `d.m.yyyy` / `d.m.yy` (1-2 digit day/month, 2- or 4-digit year, not part of a longer digit/dot run), mirroring `_NUMERIC_DATE_RE`. A bare `.` was deliberately **not** added: it would make decimals and versions (`1.5`, `v2.3`, `1.2.3`) date-like. ISO, slash, hyphen, month-name and clearly unambiguous dates behave as before (pinned by tests); `20260115`-style digit strings are still categorical. |
| 3 | Pre-Stage-3 uploads were re-read with the new `NA` rule while their stored profile (shown to the user) kept old missing counts. | **Chosen behaviour: legacy uploads keep the old policy.** `file_service.is_legacy_upload(profile)` is true when the stored profile has no `import_notes` key (every Stage 3+ upload profile has the list, possibly empty) or there is no profile. `project_analysis_service._load_dataframe` passes `legacy_na_policy=is_legacy_upload(file.profile)` to `parse_dataset`, which then reads with pandas' stock missing-value tokens (text `NA` = missing) and produces no notes, i.e. exactly how that file was profiled. New uploads always use the Stage 3 policy. Shown profile, `GET /profile`, cleaning and analysis therefore agree for both kinds of project. **No migration, no new column**: the marker is the profile's own shape. Trade-off: a legacy project does not get the Stage 3 `NA` treatment or notes unless the file is uploaded again (the UI offers no re-upload for an existing project today; delete the project and upload again). |

Files changed vs `zaimex-checkpoint-5s3-v1-hardening-stage3-data-correctness.zip`: `backend/app/analytics/profiling.py`, `backend/app/services/file_service.py`,
`backend/app/services/project_analysis_service.py`, `RECOVERY.md`; new: `backend/tests/test_stage3_review_fixes_unit.py` (30 tests),
`backend/tests/test_stage3_review_fixes_api.py` (6 tests). `parse_dataset`/`parse_dataset_with_notes` gained a keyword-only
`legacy_na_policy` (default `False`, so every existing caller and test is unchanged). No existing test was edited, weakened or removed.

### Review-fix verification record (Python 3.12.3 / pandas 3.0.6, Node 22.22.2, PostgreSQL 16, Chromium via Playwright)
PASSED: backend `pytest` 482/482 (SQLite in-memory; 446 existing + 36 new); the new API tests were also run against the unfixed
5s3 source and 5 of 6 fail there as intended (the sixth is the Stage 3 control case); `ruff check`; `ruff format --check`
(95 files); `mypy app tests` strict (92 files, no ignores); `alembic upgrade head` on PostgreSQL 16, single head `41696db86df6`;
frontend `typecheck`, `lint`, vitest 68/68, `next build` (11 routes + proxy); against the real stack (Next :3000 -> FastAPI :8000 ->
PostgreSQL, started fresh on the final code): `e2e_auth.sh` ALL PASSED, `e2e_projects.py` ALL PASSED, `e2e_analysis.py` 64/64,
`e2e_phase8a.py` ALL CHECKS PASSED, `browser_e2e.py` 30/30, and an ad-hoc (not shipped) 7-check script covering blank CSV/XLSX
columns, dotted dates, and a project whose stored profile was rewritten to the legacy shape on PostgreSQL.
FAILED (1, known, unchanged from 4d, NOT fixed): `e2e_upload_limits.py` 31/32 - "early Content-Length rejection" through Next
(no response within 10 s; the same case passes direct to the API). See the 4d record; the proxy limitation is unchanged.
NOT RUN / NOT PROVEN: pytest against PostgreSQL (the suite is SQLite-based by design); a legacy upload created by *real* pre-Stage-3
code (legacy was simulated by writing a stock-pandas profile without `import_notes`; no pre-Stage-3 build was available to produce one);
the 4d ZIP itself (not in this session, so the diff is against 5s3, whose delta from 4d is the documented Stage 3 file list);
`npm audit`; large-file timing; non-Chrome browsers; everything listed as not run in 4d/Stage 3.

## Checkpoint 4d — verification and fixes (2026-10-16)
4c was first verified on a real toolchain (Python 3.12, Node 22, PostgreSQL 16, headless Chromium) and then fixed. Only the
four approved tasks were done; Stage 3 was not started.

1. **Next.js proxy upload size (real defect, fixed).** Next buffers every proxied request body and, past its default of
   10 MB, forwards a *truncated* body, so a 10-25 MB CSV (or an XLSX over 10 MB) stalled ~30 s and returned a bare non-JSON 500.
   - `frontend/next.config.ts`: `experimental.proxyClientMaxBodySize` = (larger of `NEXT_PUBLIC_MAX_CSV_UPLOAD_MB` /
     `NEXT_PUBLIC_MAX_XLSX_UPLOAD_MB`, default 25) + 2 MB = 27 MB. The backend admits up to limit + 1 MiB before its own 413,
     so everything it would accept fits unmodified. (The option is under `experimental` in Next 16.4; `middlewareClientMaxBodySize`
     is its deprecated name.)
   - Raising that alone was not enough: a body *larger* than the buffer made FastAPI answer 413 and close while Next was still
     writing, which Next reported as a bare 500 (the old 10 MB setting only passed the 40 MB case by luck). So
     `frontend/src/lib/upload-guard.ts` + `frontend/src/proxy.ts` now answer an oversized declared `Content-Length` at the Next
     origin with the **same JSON 413** the backend sends (`file_too_large`, `details.limit_mb`). The proxy matcher gained
     `/api/v1/projects/:id/upload` for this; the guard only touches `POST` on that exact path and never changes auth redirects
     or any other `/api` route. The guard's threshold equals the backend's early threshold (limit + 1 MiB), so a file the backend
     would accept is never rejected by it. The backend remains the authority for exact per-type limits.
   - Tests: `upload-guard.test.ts` (5), `next-config.test.ts` (2), and the real `e2e_upload_limits.py` run through Next.
2. **Two stale backend tests (fixed, coverage kept).** `test_analysis_of_an_empty_dataset_fails_safely_and_is_recorded` and
   `test_a_failed_analysis_can_be_retried_after_the_data_problem_is_fixed` uploaded a header-only file, which Stage 1 now refuses
   (422 `no_data_rows`). They now seed it with `_new_project_with_unvalidated_upload`, which skips only `validate_dataset` for that
   one upload (monkeypatch scoped with `monkeypatch.context()`); endpoint, parsing, profiling, storage and DB rows are real, and
   both still assert 422 `empty_dataset`, the `failed` status and the retry behaviour. New test
   `test_header_only_file_is_rejected_at_upload_so_it_never_reaches_analysis` pins the premise. Product behaviour is unchanged.
3. **mypy and formatting (fixed without ignores).** `tests/test_upload_limits_unit.py`: spy narrows `read_excel`'s overloaded
   return with `assert isinstance(..., pd.DataFrame)`. `tests/test_upload_limits_api.py`: middleware list typed `list[object]`.
   `ruff format` applied to `app/analytics/visualization.py` and `app/core/exceptions.py` (each a single joined line, no
   behaviour change) and `tests/test_upload_limits_api.py`. No mypy/ruff configuration was changed.
4. **Docs:** this file, `frontend/.env.example`, `frontend/README.md`.

Files changed vs 4c: `frontend/next.config.ts`, `frontend/src/proxy.ts`, `frontend/.env.example`, `frontend/README.md`, `RECOVERY.md`,
`backend/app/analytics/visualization.py`, `backend/app/core/exceptions.py` (formatting only), `backend/tests/test_analysis_api.py`,
`backend/tests/test_upload_limits_unit.py`, `backend/tests/test_upload_limits_api.py`; new: `frontend/src/lib/upload-guard.ts`,
`frontend/src/lib/upload-guard.test.ts`, `frontend/src/lib/next-config.test.ts`.

### 4d verification record (what actually ran; Python 3.12.3, Node 22, PostgreSQL 16, Chromium via Playwright)
PASSED: backend `pytest` 399/399 (note: pytest uses in-memory SQLite, not PostgreSQL); `ruff check`; `ruff format --check`
(90 files); `mypy app tests` (87 files, strict); `alembic upgrade head` on real PostgreSQL 16 (5 migrations, single head
`41696db86df6`); frontend `typecheck`, `lint`, vitest 65/65 (11 files), `next build` from a clean `.next`; against the real
stack (Next `:3000` -> FastAPI `:8000` -> PostgreSQL): `e2e_auth.sh` 22/22, `e2e_projects.py` 43/43, `e2e_analysis.py` 64/64,
`e2e_phase8a.py` all checks, `browser_e2e.py` 30/30 (headless Chromium), `e2e_upload_limits.py` **31/32** through Next and
16/16 directly (both columns: CSV exactly 25 MB -> 201, 1 byte over -> 413, 40 MB -> 413, XLSX 8.77 MB -> 201, XLSX 10.96 MB -> 413,
all rows/columns/encoding/header-only cases as expected; an explicit 22.47 MB CSV through Next -> 201).
FAILED (1, known, not fixed): `e2e_upload_limits.py` "early Content-Length 413 (200 MB declared, 0 sent)" through Next: no response within
10 s. That probe declares a huge body and sends none; Next waits for the body before running `proxy.ts`, so the guard never
sees it. It passes directly against FastAPI (413 in 0 s). A real client that actually sends the body is covered (40 MB -> JSON 413).
Residual risk: a client that stalls/lies about Content-Length holds a Next connection open until Next's own timeouts.
NOT RUN / NOT PROVEN: pytest against PostgreSQL; concurrent uploads; any production reverse proxy (nginx/ALB, whose
`client_max_body_size`-style limit is still the right control for bandwidth); real network latency; Firefox/Safari/real phone;
a browser-driven upload of a large file (the large-file cases are HTTP-level, not browser); chunked uploads without a
`Content-Length` through Next (the buffer would truncate them at 27 MB; behaviour untested); XLSX larger or slower than the
8.77 MB / ~12.8 s case through Next (the proxy timeout for slower files is still unverified); `npm audit`.
Observed, harmless: Next logs "Request body exceeded 27MB ..." and `ECONNRESET` lines for rejected oversized uploads.

### Changed files since original checkpoint 4, as of 4c (26 files: 10 new, 16 modified; 4d changes are listed under "Checkpoint 4d")
NEW: `backend/app/core/upload_limit.py`, `backend/app/analytics/sampling.py`, `backend/tests/test_upload_limits_unit.py`,
`backend/tests/test_upload_limits_api.py`, `backend/tests/test_chart_sampling.py`, `backend/tests/test_chart_sampling_api.py`,
`frontend/src/lib/upload-limits.ts`, `frontend/src/lib/upload-limits.test.ts`,
`frontend/src/components/analysis/charts-tab.test.tsx`, `frontend/scripts/e2e_upload_limits.py`.
MODIFIED: `RECOVERY.md`, `backend/.env.example`, `backend/app/core/config.py`, `backend/app/core/exceptions.py`,
`backend/app/schemas/common.py`, `backend/app/schemas/analysis.py`, `backend/app/main.py`, `backend/app/api/v1/uploads.py`,
`backend/app/services/file_service.py`, `backend/app/services/project_analysis_service.py`,
`backend/app/analytics/visualization.py`, `frontend/.env.example`, `frontend/src/lib/schemas.ts`,
`frontend/src/components/analysis/charts-tab.tsx`, `frontend/src/components/projects/upload-dropzone.tsx`,
`frontend/src/components/projects/upload-dropzone.test.tsx`.
Everything else is byte-identical to the original checkpoint 4. No migration, model, or auth change.

### Stage 1 — upload & dataset safety (what changed)
- Limits (see env table): CSV 25 MB, XLSX 10 MB, 100,000 data rows, 100 columns. Row/column limits are enforced
  *during* parsing (`nrows=max_rows+1`; header-first width check), not after loading the whole file.
- New structured error codes (additive `error.details` object, omitted when absent so old responses are unchanged):
  `file_too_large` (413, per file type; also an XLSX that unpacks beyond the limit), `too_many_rows`, `too_many_columns`,
  `no_data_rows` (header-only / all-empty), `unsupported_encoding`; `empty_file` now also covers whitespace-only CSVs;
  `unsupported_file_type` carries the supported list.
- A rejected upload never changes project status and never writes storage. Unsupported type and a second upload (409) are
  decided *before* the request body is read.
- `app/core/upload_limit.py`: ASGI middleware answering 413 from `Content-Length` before the body is read (courtesy layer).
- Re-reading an already-stored file (analysis/clean/regression) uses `parse_dataset(content, type)` with **no limits** on
  purpose, so projects uploaded before the limits existed keep working.
- Frontend: `lib/upload-limits.ts` pre-check (extension, empty, per-type size) + limits shown in the upload card.
- `frontend/scripts/e2e_upload_limits.py`: probe of the real Next -> FastAPI path (boundaries, XLSX timing, early
  Content-Length). Needs only the backend venv (openpyxl/numpy/pandas/httpx); no extra install. Run for real in 4d (31/32 through Next, 16/16 direct; see "Checkpoint 4d").

### Stage 2 — chart & response payload (what changed)
- Inspection first: each chart is one `visualizations` row; `config` (JSONB) holds the spec **including the full `data`
  array**. Only scatter and line carry per-row data (bar/histogram/count are already aggregated; regression
  `sample_predictions` was already bounded). Four endpoints return charts: `POST clean`, `POST analyze`, `GET analysis`,
  `POST regression` (plus `GET charts`). Before: 27 MB of chart JSON at 100,000 rows.
- `app/analytics/sampling.py` (pure, no RNG): scatter = at most `MAX_CHART_POINTS` (2,500) rows chosen by a golden-ratio
  hash of the row position (evenly spread, reproducible across runs/machines/NumPy versions, does not alias with cyclical
  data), always keeping the min and max of both axes; line = min/max decimation per equal-count bucket plus first and last
  point (spikes/dips survive). Constant lives in `app/analytics/visualization.py`.
- **Statistics are not touched**: stats, correlations, outliers, cleaning, regression, bar/histogram/count are computed from
  the full dataframe. A test runs the whole pipeline with and without sampling and requires every non-chart result equal.
- API: one additive optional field `sampling` on each chart (`method`, `total_points`, `displayed_points`, `max_points`);
  `null`/absent when every point is drawn. Old clients ignore it. Frontend zod schema accepts it as nullable+optional.
- Analyses stored before Stage 2 keep full-size arrays in the DB; `build_visualizations` bounds them **when read**
  (`bound_chart_payload`, idempotent, stored rows are not rewritten) so existing projects stop returning tens of MB.
- UI: a one-line note under a reduced chart ("Showing 2,500 of 100,000 points … Statistics always use all rows.").
- Measured (single runs, 1 CPU sandbox, run_analysis on real parsed files; BEFORE -> AFTER total response size):
  10k x 20: 2.77 -> 0.73 MB; 100k x 20: 27.07 -> 0.73 MB (3.4 s -> 1.3 s, peak RSS 381 -> 149 MB);
  100k x 30: 27.49 -> 0.78 MB; 100k x 99: 28.28 -> 1.43 MB; 5,000 x 100 numeric: 1.49 -> 1.23 MB.

### What was run vs not at 4c (historical; superseded by the 4d verification record above)
At 4c the author's sandbox had no network, so only stub-based checks ran; the 4d session ran the real toolchain and found the
defects listed under "Checkpoint 4d". The earlier statement "e2e_upload_limits.py not yet run" is obsolete: it has now been run.

## Architecture (frontend, as of checkpoint 4)

Browser -> Next.js (App Router, `next start :3000`) -> rewrite `/api/v1/*` -> FastAPI `:8000` -> PostgreSQL + file storage.
All statistics are computed by the backend (`backend/app/analytics`); the frontend only renders what the API returns
(no statistics, correlations, outlier bounds or chart aggregates are calculated in JavaScript).

New in checkpoint 4 (all under `frontend/src`):

| File | Purpose |
|---|---|
| `lib/schemas.ts` | Zod mirrors of the backend analysis contract (`analysisSchema`, cleaning/stat/correlation/outlier/regression/chart schemas). A contract mismatch fails loudly. |
| `lib/projects.ts` | `useAnalysis` (404 = "not run yet"), `useCleanProject`, `useAnalyzeProject`, `useRunRegression`. Every mutation writes the returned analysis into the `["projects", id, "analysis"]` cache and invalidates project/projects/dashboard. |
| `lib/analysis-errors.ts` | Maps backend error codes to readable text (specific regression messages pass through untouched). |
| `components/analysis/analysis-workspace.tsx` | Stage strip + "Run analysis" + tabs (Cleaning, Statistics, Correlations, Outliers, Regression, Charts). Mounted in `projects/[id]/project-view.tsx` under the profile. |
| `components/analysis/*-tab.tsx`, `cleaning-panel.tsx`, `stage-strip.tsx` | One component per section. |
| `components/ui/tabs.tsx` | Accessible tab list (arrow keys/Home/End); wraps into a grid on small screens, never scrolls or overlaps. |
| `lib/upload-guard.ts`, `proxy.ts` (4d) | Early JSON 413 at the Next origin for an oversized `POST /api/v1/projects/:id/upload`; same limit as the backend's early check. |
| `scripts/e2e_analysis.py`, `scripts/browser_e2e.py` | HTTP e2e and real-browser e2e (see Verify). |

### Backend analysis contract (verified against real responses and code)
- `POST /projects/{id}/clean` body `{numeric_strategy: median|unchanged, categorical_strategy: mode|unchanged, duplicate_strategy: keep|remove}` -> `AnalysisPublic`. **Wipes statistics, correlations, outliers, regression and charts** (the UI warns first).
- `POST /projects/{id}/analyze` (no body) uses the stored cleaning settings (defaults if never cleaned); keeps an existing regression.
- `POST /projects/{id}/regression` body `{target, predictors[]}`; needs a completed analysis (409 `analysis_not_completed`); invalid input -> 422 with codes such as `regression_target_not_numeric`, `regression_target_not_found`, `regression_target_in_predictors`; a rejected request keeps the previous model.
- `GET /projects/{id}/analysis` (404 `analysis_not_found` before any run) is the single source the UI reads; `/statistics`, `/correlations`, `/outliers`, `/charts` exist but the UI does not need them.
- Persisted in PostgreSQL: cleaning report + settings, statistics, correlations, outliers, regression, chart data. The cleaned table itself is NOT stored; it is recomputed from the original file + saved settings.
- Regression metrics: R², adjusted R², F, coefficients are fitted on the training split; MAE, RMSE, residuals and sample predictions are on the held-out test split (UI labels reflect this). Outlier row positions are 0-based positions in the cleaned dataset.

## Current state (checkpoint 4)
Working end to end: register/login -> create project -> upload CSV/XLSX -> profile -> choose cleaning options (with erase-warning) -> run analysis -> statistics, correlations, outliers, charts -> regression -> everything persisted across reloads. Second user gets the same 404 as for a nonexistent project.

## Known limitations / not done
- Browser test is one scripted headless-Chromium run (desktop 1280px + one 390px mobile viewport, Chromium only). No Firefox/Safari, no real phone, no screen-reader testing.
- Chart rendering is verified in the real browser test, not in the unit tests (jsdom has no layout, so unit tests only check chart containers/titles).
- No polling/progress percentage: analysis is synchronous; the UI shows a spinner and the server's real stage states after the call returns. Very large files may make the request long.
- An unapplied cleaning selection is lost when switching tabs (the selection resets to the last applied settings).
- Only one regression is stored per project (the last successful one). (XLSX through the browser: covered since Checkpoint 5 by `browser_journey_e2e.py`.)
- `npm run typecheck` does not type-check `scripts/`; those are Python.
- No PDF/export/save buttons (Phase 10), no AI insights (Phase 9) — intentionally.
- V1 hardening limitations (Stages 1-2):
  - **XLSX is slow to parse**: ~12-23 s for a 6-10 MB file on the 1-CPU test sandbox, and every analyze/clean/regression
    request re-parses the stored file. In 4d an 8.77 MB XLSX upload through Next completed in ~12.8 s (same as direct), so the
    proxy did not cut it off; slower files / other machines are untested. Options if it ever does: raise the proxy timeout,
    lower the XLSX cap, or parse once and cache a normalised copy.
  - The early `Content-Length` 413 is a courtesy: its threshold is the largest per-type limit (+1 MiB), it cannot see the
    file type, and it does not cover chunked uploads. FastAPI parses multipart before the handler runs (recalled framework
    behaviour, not tested here), so bandwidth/spool-disk protection needs a reverse-proxy body-size limit. Through Next (4d) a
    far-oversized body now gets the JSON 413 from `upload-guard.ts`; talking to FastAPI directly, a client may still see a
    connection reset instead. The Next buffer limit is derived from the `NEXT_PUBLIC_MAX_*_UPLOAD_MB` variables: raising a backend
    limit means rebuilding the frontend with the matching values, or large uploads are truncated/rejected at the proxy again.
  - An XLSX with too many rows is rejected only after ~100k rows are read (~11 s measured); the 250 MB unpack guard trusts
    the sizes declared in the zip.
  - Stored-file re-reads are deliberately unlimited (legacy compatibility), so a file uploaded before limits existed can
    still be huge. Each request still holds the whole file in memory (no streaming).
  - Non-UTF-8 CSVs (cp1252/Latin-1) are refused with instructions, not guessed (Stage 3 decision: kept; see "Stage 3").
  - Chart sampling: a 2,500-point scatter of 100,000 rows can look sparser/denser than the raw cloud in very dense regions;
    the UI says it is a sample. Line charts are min/max-decimated, so they show extremes, not the mean per bucket.
  - The correlation block is still O(columns^2): ~0.6-0.9 MB at 100 columns (the V1 ceiling). Not changed (existing API
    contract the frontend uses). No response compression is configured.
  - Chart rendering with sampled data was exercised by the 4d browser run on its own datasets (30/30), but not with a 100,000-row
    dataset in a browser. The Stage 2 HTTP tests and React tests now run and pass (399 backend / 65 frontend).
  - The "declare 200 MB, send nothing" probe still fails through Next (see 4d record).

## Security items (rechecked at checkpoint 4 — all still open)
1. **No login rate-limiting** (no limiter anywhere in `backend/app`). Brute-force protection must be added before production.
2. **No explicit CSRF token.** Mitigations in place: HttpOnly cookie, `SameSite=lax`, same-origin proxy, JSON bodies, CORS limited to `FRONTEND_URL`. Not equivalent to a CSRF token.
3. **`npm audit`: 5 high** (unchanged at Checkpoint 5; adding the `axe-core` devDependency introduced none) (`braces` -> micromatch -> fast-glob -> `@next/eslint-plugin-next` -> `eslint-config-next`). Dev/lint tooling only: `npm audit --omit=dev` reports 0. The only offered fix is `npm audit fix --force` (breaking downgrade), deliberately NOT applied.
4. `COOKIE_SECURE=false` is only for local http; production must keep the default `true`.

## Exact next steps
1. Independent review of Phase 9 Stage 1 (record above). Do NOT start Stage 2 (provider call / endpoint / storage / UI) until it is accepted
   and Stage 2 is explicitly approved.
2. Decide whether the stalled/lying-Content-Length case through Next needs more than a production reverse-proxy limit (still open).
3. Phase 10 (PDF) not started.


## Checkpoint 6c - final targeted corrections to Stage 1 (no Stage 2)

Changes are confined to `backend/app/ai/{evidence,aliases,loader}.py`, tests, and this file. No provider/SDK/key/network/endpoint/frontend/migration; accepted decisions
(5 / 30 row policy, `MAX_EVIDENCE_BYTES` = 32,768, size tiers, omission disclosures, fingerprint algorithm, 4d `Content-Length` limitation below) are unchanged.

1. **Closed vocabularies.** `_token()` / `[A-Za-z0-9_-]{1,40}` is gone (it checked shape: a column named `ZZ_REVENUE` passes it). `_choice(value, allowed, default)` accepts a value only if it
   is a member of an explicit set in `evidence.py`: `COLUMN_CLASSIFICATION_VALUES`, `NUMBER_FORMAT_VALUES`, `DATE_ISSUE_VALUES`, `IMPORT_NOTE_SEVERITY_VALUES`, `IMPORT_NOTE_CODE_VALUES`,
   `CLEANING_ACTION/METHOD/REASON_VALUES`, `REGRESSION_METHOD_VALUES`, `OUTLIER_METHOD_VALUES`, `CHART_TYPE_VALUES`, `CORRELATION_STRENGTH/DIRECTION_VALUES`, `RESIDUAL_SUMMARY_KEYS`
   (plus the existing cleaning-settings whitelist). Outside the set: replaced by `"unknown"` (type, severity, code, action, method of regression/outliers, chart type, strength, direction)
   or omitted (number format, cleaning method/reason, residual keys, note kinds map to `unknown`). A NEW engine value must be added to its set on purpose; until then it shows as `unknown`.
   Non-list note `columns` are ignored instead of iterated. Every key in the packet is a literal, an alias, or a fixed model field (checked by a test).
2. **Local alias mapping separated.** `EvidencePacket` now has only `content`, `fingerprint`, `size_bytes` (+ `canonical_json()`, `to_json()`). `build_evidence()` returns `EvidenceBuild`
   (`.packet`, `.aliases`): not a dataclass, `__slots__`, no `__dict__`, `repr` shows only the fingerprint, pickle raises `TypeError`. A provider call must take `build.packet`. `loader.py`:
   `evidence_packet_for_analysis` (packet only, unchanged signature) and new `evidence_build_for_analysis` (packet + local map).
3. **Duplicate exact column names.** Upstream sections (statistics, cleaning, correlations, outliers, regression, charts, notes) reference columns by NAME only, so a reference to a name shared by
   several columns cannot identify which one. Previously it silently resolved to the first. Now the packet writes `Column_ambiguous` for such references and adds a warning
   `duplicate_column_names_ambiguous_references` listing the positional aliases of each duplicate group (no names). The profile `columns` list stays exact (by position). `ColumnAliasMap.alias_for(name)`
   still returns the first slot for local code; `is_duplicated()` / `duplicated_groups()` were added. **Limitation (not fixed, by design of Stage 1):** the analysis contracts carry no column position,
   so which duplicate a statistic belongs to cannot be recovered; the upload parser renames duplicate headers (`x`, `x.1`), so this should only arise from non-standard inputs. Fixing it needs an upstream contract change (out of scope).
4. Tests: existing tests were adapted only to read the map from the build (`build_both` helper); none removed or weakened. New: `tests/test_ai_closed_vocabulary.py` (sentinel/hostile metadata in every enum-like field,
   every serialization form, no name-to-alias pairing, key and token-shaped-leaf constants check) and duplicate-name tests in `test_ai_aliasing.py`.

**Verification status of 6c:** see the hand-off message. The authoring sandbox had no network, so pydantic/pytest/statsmodels/fastapi/ruff/mypy and the frontend `node_modules` could not be installed; the backend test suite,
Ruff, mypy and frontend checks were NOT run there and must be run before acceptance (`pytest -q`, `ruff check .`, `ruff format --check .`, `mypy app`, frontend `npm ci && npm run lint && npx tsc --noEmit && npm test`).


## Checkpoint 6d - corrections from the independent verification of 6c (no behaviour change, no Stage 2)

Found by static scan (the real suite could not run in that sandbox): (1) `tests/test_ai_evidence.py` used `build_both` without importing it (5 tests would raise `NameError`) - import added;
(2) `app/ai/evidence.py` had unused `import re` and `field` (Ruff F401) - removed; (3) `tests/test_ai_closed_vocabulary.py` built its frame without missing values, so the cleaning step had no column actions and
`assert actions` would fail and the hostile action/method/reason/fill injections were never exercised - two missing values were added (one numeric, one text). No application behaviour changed; no test removed or weakened.
Known Low items left as-is: duplicate-name groups beyond 10 are cut from the warning (disclosed only by `group_count`); min/max/median/fill values are real data-derived numbers (as on the dashboard).
**Still unverified until run where dependencies exist:** full pytest, `ruff check`, `ruff format --check`, `mypy app`, frontend checks, and any comparison against Checkpoint 5 (that archive was not available).


## Checkpoint 6e - packet-integrity corrections (audit of 6d; no Stage 2)

Scope: only the three audit findings below. No provider/SDK/key/network/endpoint/frontend/migration change; eligibility (5 / 30 rows), aliases, closed vocabularies, omission disclosures, fingerprint algorithm and `MAX_EVIDENCE_BYTES` = 32,768 are unchanged.
1. **`EvidencePacket` integrity.** `content` used to be a plain dict: `packet.content[...]` could be changed after construction, leaving `size_bytes`/`fingerprint` describing the old content and allowing the 32,768-byte cap to be exceeded (reproduced on 6d: 3,842 recorded vs 43,877 actual bytes).
   Now (`backend/app/ai/evidence.py`): (a) the content is copied into read-only dict/list subclasses at construction - any in-place change at any depth raises `TypeError`; they are still real `dict`/`list` objects, so `json.dumps`, `==`, `asdict`, copy and pickle work and serialization/fingerprints are
   byte-for-byte unchanged; (b) `__post_init__` and `verify_integrity()` raise `EvidenceIntegrityError` if the content is not JSON, is over `MAX_EVIDENCE_BYTES`, or does not match the given `size_bytes`/`fingerprint`; (c) the supported serializers `canonical_json()` and `to_json()` call `verify_integrity()` first, so a change
   that gets around the read-only types (e.g. `dict.__setitem__`, `object.__setattr__`) is still refused. Known limit: this is tamper-EVIDENT, not tamper-PROOF - Python cannot stop deliberate bypasses, and code that calls `json.dumps(packet.content)` directly skips the check; a future provider payload must be `canonical_json()` only (its exact bytes are what the fingerprint and `size_bytes` describe, and the 32,768-byte cap applies to them); `to_json()` is a convenience/debug rendering and is not provider payload text. [Amended in 6g: the 6e text previously also named `to_json()` as an acceptable provider path, which was misleading; 6f did NOT amend it.]
   To change evidence, build a new packet. Tests: new `tests/test_ai_packet_integrity.py`; `test_a_built_packet_is_read_only_and_its_saved_size_and_fingerprint_stay_true` in `tests/test_ai_evidence.py`.
2. **Unknown note code.** `test_an_unknown_future_note_keeps_its_code_but_loses_its_free_text` asserted the OLD behaviour (raw code kept) and contradicted the closed-vocabulary policy. Renamed to `test_an_unknown_future_note_is_reported_as_unknown_and_loses_its_free_text` and now asserts: code `"unknown"`, raw code absent from the packet,
   closed severity and aliased columns kept, no message/details. The comment in `evidence.py` and the Checkpoint 6 notes above were corrected to say the same. The implementation was not changed.
3. **RECOVERY.md status** updated to 6e (this file).
Verification status: see the hand-off message (what was run, what was blocked). The early-`Content-Length` limitation remains open and documented.


## Checkpoint 6f - verified-serialization contract and tooling gates (audit of 6e; no Stage 2)

Scope: document and pin how `EvidencePacket` may be serialized, and run the verification that earlier sandboxes could not. No provider/SDK/key/network/endpoint/frontend/migration change. Eligibility, aliases, closed vocabularies, canonical JSON, fingerprint algorithm and `MAX_EVIDENCE_BYTES` = 32,768 are unchanged. No test removed or weakened.
1. **Serialization contract** (docstring on `EvidencePacket`; tests in `tests/test_ai_serialization_contract.py`, 9 tests). INTEGRITY-CHECKED before output: `canonical_json()`, `to_json()`, `verify_integrity()`, `dataclasses.replace` (6g clarification: integrity-checked does not mean safe to send; only `canonical_json()` is provider-bound). NOT VERIFIED (return tampered content, by design, because `content` stays a public attribute): direct `.content`, `dict(content)`, `asdict`/`astuple`, `vars`, `repr`, `copy`, `deepcopy`, pickle, module-level `fingerprint.canonical_json(content)`.
   `canonical_json()` is the ONLY text whose SHA-256 is the fingerprint. `to_json()` is a readable rendering: identical data for packets from `build_evidence`, but it skips NFC and 6-digit float rounding, so for hand-made content it can differ from the hashed text. A future provider must send `canonical_json()`. [Correction recorded in 6g: this 6f text said it corrected the 6e wording, but 6f did NOT amend the 6e text; that was done in 6g.]
   No provider integration exists, so NO future provider is claimed protected; that needs a test at a real integration boundary. A tripwire test fails if production code outside `evidence.py` starts reading `.content` or calling `asdict`/`astuple`.
2. **Tooling gates that failed on 6e** (found by running the real tools; behaviour-neutral): `ruff format --check` failed on `app/ai/evidence.py` and `tests/test_ai_closed_vocabulary.py` (formatter applied); `mypy` reported 10 errors: scoped `# type: ignore[misc]` on `_FrozenDict.__ior__` and `_FrozenList.__iadd__/__imul__` (runtime signatures unchanged); `tests/test_ai_aliasing.py` now imports `AMBIGUOUS_ALIAS` from `app.ai.aliases` (same object) and uses `cast(Any, ...)` instead of a version-specific ignore. Tool versions here were newer than the authors' (ruff 0.17.2, mypy 1.20.2, pandas 3.1.0); the 6e failures may be partly version-related, not re-tested on older versions.
3. **Baseline comparison against Checkpoint 5: STILL BLOCKED** (archive not available; not reconstructed).
Verification run (Python 3.12.3, Node 22.22.2, PostgreSQL 16.15, Playwright 1.56.0 + preinstalled Chromium): 6e unchanged: pytest 614 passed, ruff clean, format FAIL (2 files), mypy FAIL (10 errors). 6f: focused AI 141 passed (8 files), full pytest 623 passed, `ruff check` clean, `ruff format --check` clean (111 files), `mypy app tests` clean (107 files); frontend typecheck, lint pass, `npm test` 73 passed + 8 skipped, build ok; `alembic upgrade head` single head `41696db86df6`; e2e_auth 22/22, e2e_projects 43/43, e2e_analysis 64/64, e2e_phase8a all passed, contract test 8/8 (via Next and direct), browser_e2e 30/30, browser_journey 101/101; `e2e_upload_limits.py` 31/32.
**Known, unresolved, unchanged:** the early-`Content-Length` 413 through Next (200 MB declared, 0 sent) still gets no response within 10 s; direct backend is correct. Not touched by Phase 9 Stage 1.
Stage 1 is NOT accepted; Stage 2 has not been started.


## Checkpoint 6g - serialization cap/contract corrections (audit of 6f; no Stage 2)

Status: CANDIDATE. Verification below is AUTHOR-SIDE only (not an independent audit). NOT accepted. Stage 2 has NOT been started.
Source: the exact 6f ZIP (SHA-256 `f8a58f7dfc669fca059bacb592b65b89344f55f3cd111e834d62e203fae75e98`) was hash-verified before extraction. 6f, 6e and all earlier checkpoints are kept unmodified.
Scope: findings F1-F3 of the 6f audit only. Executable code is unchanged: `backend/app/ai/evidence.py` differs from 6f in docstrings only (checked by comparing the code ASTs with docstrings removed); `to_json()` behaviour is unchanged. The 32,768-byte cap, eligibility (<5 rows `too_few_rows`; 5-29 `small_sample`; 30+ no warning from that threshold), aliasing, closed vocabularies, canonical JSON and the fingerprint are unchanged. No provider/SDK, API key use, network call, endpoint, frontend change or migration (alembic single head still `41696db86df6`).
1. **F1 - serialization contract.** `canonical_json()` is the ONLY sanctioned provider-bound serialized text; its exact bytes (ASCII) are what `fingerprint` hashes and `size_bytes` counts, and the cap applies to those bytes. `to_json()` is a convenience/debug rendering only: it is integrity-checked, but its text is not hashed or measured and its formatted output (notably `indent=2`) is NOT guaranteed to stay within the cap. The 6f audit observed a valid packet of 20,773 canonical bytes rendering to 32,903 bytes with `to_json(indent=2)`. Docstrings on `EvidencePacket`, `canonical_json`, `to_json` and `EvidenceBuild` were corrected; the misleading sentence saying anything leaving the application must go through "them" (both serializers) is removed. New tests in `tests/test_ai_serialization_contract.py`: a deterministic fixture (500 columns: about 20.5 KB canonical, over 33 KB with `indent=2`) proving the cap binds canonical bytes only; the fingerprint and size describe the canonical text and not any `to_json()` text; docstring-contract tests; and a RECOVERY.md check that no note tells a provider to use `to_json()`. Proposed, NOT applied (needs approval): make `to_json()` enforce the cap, restrict or remove `indent`, or rename it as debug-only.
2. **F2 - RECOVERY.md.** Stale "corrected candidate 6b awaiting review" and the stale "577 passed" figures updated or marked historical; the 6e sentence that named `to_json()` as a provider path was amended (marked "[Amended in 6g]"); the 6f sentence claiming it had already corrected 6e is itself corrected; status kept: candidate only, NOT accepted, Stage 2 NOT started.
3. **F3 - tripwire (narrowed, still simple).** The check now looks only at code under `app/ai/` or modules importing from `app.ai`, so unrelated modules (HTTP responses, uploads) are no longer flagged; it also flags `.to_json` use there. It is import-based, not type-based, so limits remain and are pinned by tests: any `.content` inside a packet-handling module is still flagged (a provider client's `response.content` will need a conscious decision), and `getattr`, `vars`, `__dict__` and `repr` are not detected. It is a warning tripwire, not protection.
4. **Checkpoint 5 comparison: STILL BLOCKED** (the exact archive is not available; not reconstructed).
5. **Author-side verification record.** Environment: Python 3.12.3; pytest 8.4.2; ruff 0.17.2; mypy 1.20.2 (strict via `pyproject.toml`); pandas 3.1.0; numpy 2.5.4; scipy 1.18.1; statsmodels 0.15.0; fastapi 0.161.1; SQLAlchemy 2.1.6; pydantic 2.14.1 (these are newer than the versions recorded by earlier authors; ruff and mypy are not pinned). Commands run from `backend/` on the extracted 6g tree: (a) `python -m pytest tests/test_ai_fingerprint.py tests/test_ai_eligibility.py tests/test_ai_evidence.py tests/test_ai_evidence_api.py tests/test_ai_aliasing.py tests/test_ai_closed_vocabulary.py tests/test_ai_packet_integrity.py tests/test_ai_serialization_contract.py -q -p no:cacheprovider`: exit 0, 153 passed, 1 warning (fingerprint 12, eligibility 22, evidence 26, evidence_api 8, aliasing 32, closed_vocabulary 12, packet_integrity 20, serialization_contract 21; 6f had 9 in the last file, so 12 new tests); (b) `python -m pytest -q -p no:cacheprovider` (full backend suite): exit 0, 635 passed, 1 warning (6f: 623; the difference is exactly the 12 new tests); (c) `ruff check --no-cache .`: exit 0, all checks passed; (d) `ruff format --no-cache --check .`: exit 0, 111 files already formatted; (e) `mypy --cache-dir=/dev/null app tests`: exit 0, no issues in 107 source files. Frontend checks were NOT re-run for 6g: no frontend file differs from 6f (so the 6f frontend results stand as author-reported). Integration/e2e/browser suites were not re-run (see limitations). Mutation checks on throwaway copies: eight deliberate breakages of the new docstring, behaviour, RECOVERY-wording and tripwire contracts were each caught by the intended test, and an unrelated module reading `response.content` stayed silent as designed.
6. **Outstanding limitations.** Direct `.content` access and the other direct paths remain unverified by design (no provider boundary exists to test); `to_json()` can exceed the cap (documented, behaviour unchanged); the tamper check is tamper-EVIDENT, not tamper-PROOF (a consistent rewrite of content, fingerprint and size is accepted); ruff/mypy are unpinned and results depend on their versions (older mypy 1.11.2 crashes internally on this code base, so the type-ignore comments were not checked on older mypy); integration/e2e/browser suites were not re-run for 6g because no runtime code changed (the 6f results above stand as author-reported).
**Known, unresolved, unchanged:** the early-`Content-Length` 413 through Next (200 MB declared, 0 sent) still gets no response within 10 s; direct backend is correct. Not touched by Phase 9 Stage 1.
Stage 1 is NOT accepted; Stage 2 has not been started.


## Release build after 6g (Phase 9 Stage 2, Phase 10, hardening, deployment)

Status: IMPLEMENTED AND AUTHOR-VERIFIED ONLY. No independent review. Stage 1 (6g) is still NOT accepted; the Checkpoint 5 comparison is still BLOCKED (archive unavailable). The two original planning documents (Phase 1 audit, Phase 2 UI/UX spec) were not available; the scope used is the one documented in this repository (Stage 2 notes, README, code comments). `TRACKER.md` lists every requirement with its status and evidence.
Built on the exact 6g ZIP (SHA-256 `0021e9a8d56665e4cdee09d25ee62fe7c26ceab1298f060a639c8a047825445c`, hash-verified before use). The 6g contract is preserved: the ONLY provider-bound text is `EvidencePacket.canonical_json()`; `to_json()` is never sent.
Added: AI analyst (`app/ai/{prompt,output,provider}.py`, `app/services/ai_service.py`, `GET/POST /projects/{id}/ai-insights`, stored in the existing `analyses.ai_insights` column, aliases restored only on read with the current alias map and only while the evidence fingerprint matches, per-analysis cooldown, per-user daily cap); PDF reports (`app/services/report_pdf.py`, `report_service.py`, `/projects/{id}/reports...`, bundled DejaVu fonts, all user text escaped, 20 reports kept per project, files deleted with the project); SMTP password-reset email sent in a background task; in-memory sign-in and reset-request throttling; production config guards (HTTPS cookies and URLs); frontend AI analyst tab and PDF reports panel; Caddy/Docker deployment files (`deploy/`, `docker-compose.yml`, Dockerfiles, `DEPLOYMENT.md`).
Changed existing tests (intent kept): the Stage 1 offline guard now allows exactly `app/ai/provider.py` to use `httpx` and the API key (and a second test pins that); the tab keyboard checks treat "AI analyst" as the last tab; three production-config tests use a valid HTTPS production fixture.
Verification (author-side; Python 3.12.3, pytest 8.4.2, ruff 0.17.2, mypy 1.20.2 strict, Node 22.22.2, PostgreSQL 16, Caddy 2.8.4, Playwright 1.56.0): backend `pytest` 721 passed; `ruff check` clean; `ruff format --check` clean (127 files); `mypy app tests` clean (123 files); frontend `typecheck` and `lint` clean, `vitest` 85 passed + 8 gated contract tests (8/8 against the live stack), `next build` ok. Through Caddy in front of 2 uvicorn workers + `next start` on PostgreSQL: new e2e (AI, reports, isolation, throttling, size limit, headers) 33/33; auth, projects ALL PASSED; analysis 64/64; upload limits 32/32 (it was 31/32 through Next alone); browser e2e 30/30; browser journey 101/101 (run immediately before the last backend-only edits: a production-config validator and three test fixtures).
NOT verified here: Docker image builds (no Docker available); live OpenRouter calls and live SMTP delivery (stand-ins were used: a local stub provider and a fake SMTP class); Caddy automatic HTTPS issuance (needs a real domain); behaviour under multiple servers. Known limits: sign-in throttling is per process; CJK column names show as `?` in PDFs; no CSP header; billing is not implemented.


## Release patch 1 (release-readiness review; no new features)

Built from the shipped `zaimex-release-build-after-6g.zip` (SHA-256 `f6bbb437193b773d23e98c2167d8918382661c55d5810e629d3cd03b23254a30`), which is kept unchanged. Author-side only; NOT accepted; not independently reviewed.
Changes (complete list): `frontend/package.json` and `frontend/package-lock.json` (next and eslint-config-next 16.4.0 -> 16.4.3, transitive fast-uri -> 3.1.9; `npm audit` 0 vulnerabilities, previously 1 critical + 1 moderate); `frontend/Dockerfile` (`COPY --chown=node:node`); `docker-compose.yml` and `.env.production.example` (pass SMTP_STARTTLS / SMTP_SSL through); new `.gitignore`; new `RELEASE-CHECKLIST.md`; this section. Backend code, backend tests, migrations, `TRACKER.md` and `DEPLOYMENT.md` are byte-identical to the shipped release.
Reasons and evidence are in `RELEASE-CHECKLIST.md` section 1.


## Release patch 2 (three review blockers; no new features)

Built from `zaimex-release-build-after-6g-patch1.zip` (SHA-256 `a5025e736c6ff929123abc789d35d5ef8a2ddc6cc6f00df88fa1ba61e8d8a882`, 1,255,305 bytes), which is kept unchanged. Author-side only; NOT accepted; not a deployment sign-off.
1. **Open redirect** (`frontend/src/lib/safe-next.ts`, used by `login-form.tsx`): the post-login `next` target must start with a single `/`, contain no backslash or control character (raw or after repeated percent-decoding, so `/%5Cevil.com`, `/%255Cevil.com`, `/\evil.com`, `/%09/evil.com` are refused), decode cleanly, and resolve on the same origin through the URL parser. Otherwise `/dashboard`. Legitimate internal paths (with query/hash/encoded characters) are returned unchanged. Tests: `src/lib/safe-next.test.ts`, `src/app/(auth)/login/login-form-redirect.test.tsx`.
2. **Login throttle** (`backend/app/core/throttle.py`): the "clear the whole table when full" fallback is gone. When full: purge expired keys, then evict the least valuable unlocked keys (fewest recent attempts, oldest first) down to 90% of capacity; a key at or above its limit is never evicted; if every key is an active lockout the new key is simply not tracked (`untracked_records`) and nothing is dropped. Each key also keeps at most 1,000 timestamps. Public methods and call sites are unchanged (`record` gained an optional `limit`). Tests: `tests/test_throttle_capacity.py` (includes an HTTP-level test that a flooded table keeps a real account lock).
   Known limit: per-process, in-memory, as before. When the table holds only active lockouts, a brand-new key is not rate-limited by this process.
3. **AI privacy** (`backend/app/ai/evidence.py`, `ai-tab.tsx`, `DEPLOYMENT.md`, `RELEASE-CHECKLIST.md`): exact column `min`/`max` (real cells) are no longer in the `columns` or `statistics` sections; `EVIDENCE_SCHEMA_VERSION` 2 -> 3, so stored explanations built on the old packet are shown as out of date. Aliases (`Column_001`...) are unchanged. Still sent, and now described as such: counts, mean, median, std, quartiles, IQR, correlation pairs, outlier bounds, numeric fill values (medians), regression results, fixed-template text, plus a constant system prompt and the `X-Title: StatFlow AI` header. A median can coincide with a real value, so the wording is "no individual rows, names, or exact smallest/largest values", not "no values". Tests: `tests/test_ai_privacy_min_max.py`, `src/components/analysis/ai-tab-privacy.test.tsx`.
Not changed: any other file, dependency, migration (alembic head still `41696db86df6`) or feature. Remaining blockers from earlier sections of this file and `RELEASE-CHECKLIST.md` still stand.
