# StatFlow AI — release checklist (patch 1)

**Status: not live, not accepted.** Nothing here has been deployed. `DEPLOYMENT.md` is kept as originally shipped; **where it differs from this file, follow this file** (see "Corrections to DEPLOYMENT.md").

Legend: 👤 = needs YOUR account, key, money or decision · 🖥 = a command to run on the server.

## 1. Review result

**Release blockers (all resolved in this patch, except one that is a setup rule):**
| # | Finding | Resolution |
|---|---|---|
| B1 | Next.js 16.4.0 had critical advisories (RCE in image optimizer / `use cache`, Server Actions DoS). The code paths are not used by the app, but the framework was exposed to the internet. | `next` and `eslint-config-next` → 16.4.3; transitive `fast-uri` → 3.1.9. `npm audit`: **0 vulnerabilities**. |
| B2 | Frontend container would run as the unprivileged `node` user on root-owned files; `/_next/image` then threw `EACCES` as an unhandled rejection (reproduced). | `COPY --chown=node:node` in `frontend/Dockerfile`; re-tested: 0 errors. |
| B3 | `docker compose ps/logs/exec` fail with "required variable POSTGRES_PASSWORD is missing" when the env file is not named `.env` (confirmed with Compose 2.29.7). | Use a file named `.env` (below). |
| B4 | **Setup rule, not code:** registration is open and there is no global AI budget. | If you enable AI on a public site, set a **spending limit on the OpenRouter key** first. Otherwise leave `OPENROUTER_API_KEY` empty. |

**Known limitations (accepted, documented):**
- Sign-in lock is counted per worker process. Measured with the limit at 8 and 2 workers: an account tolerated **12–16** wrong passwords before locking (10 trials). Spoofing `X-Forwarded-For` through Caddy does **not** bypass the per-IP limit (locked at attempt 41).
- The per-IP limit (40 failures) locks **everyone behind that IP** for 15 minutes, including correct passwords. An attacker can also lock a known email for 15 minutes with 8–16 wrong tries.
- No email verification, no admin role, no way to switch registration off, no registration rate limit. Anyone with the URL can create an account.
- AI explanations send anonymous aliases and **summary statistics** (counts, mean, median, quartiles, correlations, outlier bounds, regression results) to a third party. Column names, file name, individual rows and the exact minimum/maximum of each column are not sent; a summary number such as a median can occasionally equal a real value. Tell your users.
- Password-reset email failures are only visible in the server log; the user always sees the same message.
- PDF: Chinese/Japanese/Korean column names print as `?`. No Content-Security-Policy header. One server only.
- Docker images were never built where this was prepared; AI provider and SMTP were tested against local stand-ins only; HTTPS issuance needs your real domain.
- Billing is not built (no provider or scope agreed).

**Optional future improvements:** global daily AI budget; registration switch / invite / email verification; shared (database) throttle store; CSP header; block unused `/_next/image` at the proxy; automated off-site backups and uptime alerts; pin ruff/mypy versions; CJK font.

## 2. What you need (👤)
1. 👤 A **domain name** (about 10–15 €/year).
2. 👤 A **server** (hosting decision and monthly cost): Ubuntu 22.04/24.04, ≥ 2 CPU cores, ≥ 4 GB RAM, ≥ 20 GB disk, public IPv4.
3. 👤 *(optional)* **OpenRouter** account + API key + a credit limit on that key (AI analyst).
4. 👤 *(optional)* **SMTP account** from any email provider, with your sending address verified (SPF/DKIM) — needed for "Forgot password" emails.
5. 👤 Somewhere to keep **off-server backups** (another machine or a storage bucket).
6. 👤 Someone to do the **independent review** of 6g and this release.

## 3. Steps, in order
**3.1 👤 DNS.** At your domain provider add an **A record**: `app` → your server's public IP. If your hosting provider has its own firewall, allow ports **22, 80, 443**. Check from your computer: `ping app.yourdomain.com`.

**3.2 🖥 Prepare the server** (`ssh root@SERVER_IP`):
```bash
apt-get update && apt-get install -y ca-certificates curl unzip
curl -fsSL https://get.docker.com | sh
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw --force enable
```

**3.3 🖥 Put the release on the server** (copy the ZIP up with `scp`, then):
```bash
mkdir -p /opt/zaimex && cd /opt/zaimex
unzip ~/zaimex-release-build-after-6g-patch1.zip
```

**3.4 🖥 Create your settings file** (it must be named `.env`):
```bash
cp .env.production.example .env
chmod 600 .env
echo "POSTGRES_PASSWORD=$(openssl rand -hex 32)"   # copy the output into .env
echo "JWT_SECRET=$(openssl rand -hex 32)"          # copy the output into .env
nano .env
```
Fill in `DOMAIN=app.yourdomain.com` (no `https://`). 👤 Optional: `OPENROUTER_API_KEY`, and `EMAIL_PROVIDER=smtp` with `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM_ADDRESS`. Never share or commit `.env`. The server refuses to start in production if the secret is weak, cookies are not secure, or the URL is not `https://`.

**3.5 🖥 Build and start** (database migrations run automatically when the backend starts):
```bash
docker compose build --pull       # --pull fetches current base images (security fixes)
docker compose up -d
docker compose ps                 # wait 1–2 min: db, backend, frontend, proxy "running"/"healthy"
docker compose exec backend alembic current     # expect: 41696db86df6 (head)
```
Caddy gets the HTTPS certificate by itself once DNS points at the server and ports 80/443 are reachable.

**3.6 First user.** There is no admin account or role. Open `https://app.yourdomain.com`, click **Register**: that is a normal user. Registration stays open to anyone with the URL (see B4).

## 4. Smoke tests (🖥 from your own computer unless stated)
```bash
curl -s https://app.yourdomain.com/api/v1/health
#  -> {"status":"ok","environment":"production","version":"0.1.0"}
curl -s -i -m 10 -X POST https://app.yourdomain.com/api/v1/projects/x/upload -H "Content-Length: 209715200" | head -1
#  -> HTTP/2 413
curl -sI https://app.yourdomain.com/login | grep -i -E "strict-transport|x-frame|x-content-type"
```
In the browser: register → create project → upload a CSV → Cleaning → Statistics → Charts → Regression → **PDF reports → Create → Download**. 👤 If AI is enabled: **AI analyst → Generate explanation** (errors appear in `docker compose logs backend`). 👤 If SMTP is enabled: use **Forgot password** with your own address; the log should say `Password reset email handed to the SMTP server` (or `could not be sent (<error type>)`).

## 5. Operations (🖥, always from `/opt/zaimex`)
```bash
docker compose logs -f --tail=100 backend        # also: frontend, proxy, db
docker compose ps
docker compose stop    /    docker compose start
```
**Never run `docker compose down -v`** (it deletes the database and uploaded files).

**Backup** (do this daily; 👤 copy the files off the server):
```bash
mkdir -p /opt/backups
docker compose exec -T db pg_dump -U zaimex zaimex | gzip > /opt/backups/db-$(date +%F-%H%M).sql.gz
docker compose exec -T backend tar czf - -C /data/storage . > /opt/backups/files-$(date +%F-%H%M).tgz
```
Daily at 03:00 (`crontab -e`):
`0 3 * * * cd /opt/zaimex && docker compose exec -T db pg_dump -U zaimex zaimex | gzip > /opt/backups/db-$(date +\%F).sql.gz`

**Restore a database backup** (replaces current data):
```bash
docker compose stop backend
docker compose exec -T db psql -U zaimex -d postgres -c "DROP DATABASE zaimex" -c "CREATE DATABASE zaimex OWNER zaimex"
gunzip -c /opt/backups/db-YYYY-MM-DD-HHMM.sql.gz | docker compose exec -T db psql -U zaimex -d zaimex -v ON_ERROR_STOP=1
docker compose start backend
# files: docker compose exec -T backend tar xzf - -C /data/storage < /opt/backups/files-YYYY-MM-DD-HHMM.tgz
```
(The dump → restore-into-empty-database sequence was proven on real PostgreSQL; the `docker compose exec` wrapping was not run here.)

**Update to a new version, with rollback:**
```bash
# 1. back up (above).  2. keep the old version:
cd /opt && mv zaimex zaimex-prev && mkdir zaimex && cd zaimex && unzip ~/NEW-RELEASE.zip && cp ../zaimex-prev/.env .env
docker compose build --pull && docker compose up -d
# ROLLBACK if it misbehaves:
docker compose down && cd /opt/zaimex-prev && docker compose up -d --build
# if the new version changed the database schema, also restore the DB backup from step 1 (do not use alembic downgrade in production).
```

## 6. Corrections to DEPLOYMENT.md
- Use a file named **`.env`** (not `.env.production`), otherwise `docker compose ps/logs/exec` fail.
- Use `docker compose build --pull` then `docker compose up -d`.
- Backup/restore: use the commands in section 5 (the volume name in DEPLOYMENT.md depends on the folder name).
- SMTP providers that require port 465: set `SMTP_PORT=465` and `SMTP_SSL=true` (newly passed through by `docker-compose.yml`).

## 7. Go-live checklist
- [ ] 👤 Domain A record points to the server; ports 22/80/443 open
- [ ] 🖥 `.env` created, `chmod 600`, both secrets generated, `DOMAIN` set
- [ ] 🖥 `docker compose build --pull && docker compose up -d`; all services healthy
- [ ] 🖥 `alembic current` shows `41696db86df6 (head)`
- [ ] 🖥 `https://…/api/v1/health` returns ok; 413 test passes; security headers present
- [ ] Registered, uploaded a CSV, ran the analysis, created and downloaded a PDF
- [ ] 👤 AI: key set **with a spending limit**, one explanation generated — or key left empty
- [ ] 👤 SMTP: test reset email received — or "Forgot password" left unused
- [ ] 🖥 First backup taken **and a test restore done on a spare database**; daily cron added; copy goes off-server
- [ ] 👤 Users told that AI sends anonymous summary statistics (not rows, names or exact min/max) to a third party (if AI is on)
- [ ] 👤 Independent review of 6g / this release arranged
