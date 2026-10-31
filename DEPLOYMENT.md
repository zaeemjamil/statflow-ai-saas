# Deploying StatFlow AI (beginner guide)

This puts the whole product on one small server with automatic HTTPS. It takes about 30–45 minutes the first time.

**What you need**
1. A domain name you control (e.g. `app.yourcompany.com`).
2. A Linux server ("VPS") with at least **2 CPU cores and 4 GB RAM** and Ubuntu 22.04/24.04. Any provider works (Hetzner, DigitalOcean, AWS Lightsail, …).
3. (Optional) an **OpenRouter** account + API key for the AI analyst, and **SMTP** details from any email provider for password-reset emails. The product works without both; those two features are simply switched off.

> **Honest status:** the code, database migrations, proxy configuration and all tests were verified on a real PostgreSQL + Caddy + Next.js stack. The Docker images themselves were **not built** in the environment where this was prepared (no Docker there), and the AI provider and SMTP were only tested against local stand-ins, not live accounts. Step 6 tells you how to check each of these yourself.

## 1. Point your domain at the server
In your domain provider's DNS settings, create an **A record**: name `app` (or whatever you chose) → the server's public IP address. Wait a few minutes. Check from your own computer: `ping app.yourcompany.com` should show your server's IP.

## 2. Prepare the server
Log in over SSH (`ssh root@YOUR_SERVER_IP`), then:
```bash
apt-get update && apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sh          # installs Docker + Compose
ufw allow 22 && ufw allow 80 && ufw allow 443 && ufw --force enable   # firewall: only SSH + web
```

## 3. Put the project on the server
Upload the project folder (for example `scp -r zaimex root@YOUR_SERVER_IP:/opt/`, or unzip the release ZIP into `/opt/zaimex`), then `cd /opt/zaimex`.

## 4. Create your settings file
```bash
cp .env.production.example .env.production
nano .env.production
```
Fill in:
- `DOMAIN` – your domain **without** `https://`.
- `POSTGRES_PASSWORD` and `JWT_SECRET` – generate each with `openssl rand -hex 32` and paste the output.
- `OPENROUTER_API_KEY` – optional (AI analyst). Leave empty to keep AI off.
- `EMAIL_PROVIDER=smtp` plus `SMTP_HOST`, `SMTP_PORT`, `SMTP_USERNAME`, `SMTP_PASSWORD`, `EMAIL_FROM_ADDRESS` – optional (password-reset emails).

Keep this file private; never share or commit it. The server refuses to start in production if the secret is weak, the cookie setting is insecure or the site URL is not `https://`.

## 5. Start it
```bash
docker compose --env-file .env.production up -d --build
docker compose ps          # every service should say "running" / "healthy" after ~1-2 minutes
```
The first start downloads images and builds the app (several minutes). Caddy obtains the HTTPS certificate automatically as soon as the domain points at the server and ports 80/443 are open.

## 6. Check that it works
1. Open `https://app.yourcompany.com` → you should see the sign-in page with a padlock.
2. **Register** an account, create a project, upload a CSV, click through Cleaning → Statistics → Charts → Regression.
3. **PDF report:** open *PDF reports* → *Create PDF report* → *Download*.
4. **AI analyst** (only if you set a key): open the *AI analyst* tab → *Generate explanation*. If you see "AI explanations are not turned on", the key is missing or not loaded; run `docker compose logs backend`.
5. **Password reset** (only if you set SMTP): use *Forgot password*. If no email arrives, check `docker compose logs backend` for "could not be sent" and re-check the SMTP details and sender address.
6. **Size limit check:** `curl -i -X POST https://app.yourcompany.com/api/v1/projects/x/upload -H "Content-Length: 209715200"` should answer `413` instantly.

## Everyday operations
| Task | Command |
|---|---|
| See logs | `docker compose logs -f backend` (or `frontend`, `proxy`, `db`) |
| Stop / start | `docker compose stop` / `docker compose start` |
| Update to a new version | replace the project files, then `docker compose --env-file .env.production up -d --build` (database changes apply automatically) |
| **Back up the database** | `docker compose exec -T db pg_dump -U zaimex zaimex > backup-$(date +%F).sql` |
| Back up uploaded files and reports | `docker run --rm -v zaimex_appdata:/d -v "$PWD":/b alpine tar czf /b/files-$(date +%F).tgz -C /d .` |
| Restore a database backup | `docker compose exec -T db psql -U zaimex zaimex < backup-YYYY-MM-DD.sql` |

Do the two backups at least daily (a cron job) and copy them **off the server**.

## Things to know
- **Uploads:** the limits (25 MB CSV, 10 MB Excel by default) are enforced by the proxy and the backend. If you change them, change the backend `MAX_*` settings, the frontend build arguments and `MAX_BODY_BYTES` for the proxy together.
- **Sign-in protection:** after 8 wrong passwords an account is locked for 15 minutes (counted per server process; the stack runs 2 workers, so the effective number can be up to 16).
- **AI privacy:** the AI service receives anonymous aliases (`Column_001`) and summary numbers (counts, mean, median, quartiles, correlations, outlier bounds, regression results). It does not receive column names, the file name, sheet names, individual rows or the exact minimum and maximum of any column. A summary number such as a median can occasionally equal a value in the data, so describe it to users as summary statistics, not as "no data values". Each user has a daily cap (default 20 explanations).
- **Report fonts:** PDF reports render Latin, Greek and Cyrillic names. Chinese/Japanese/Korean column names appear as `?` in PDFs (the web pages are fine).
- **Data deletion:** deleting a project also deletes its uploaded file and its PDF reports.
- **Not included:** payments/subscriptions (no payment provider was specified), a content-security-policy header, and multi-server scaling. Run one server first.

## If something goes wrong
- *Site not loading / no padlock:* DNS not pointing at the server yet, or ports 80/443 blocked. `docker compose logs proxy`.
- *"backend exited":* usually a missing/short secret in `.env.production`. `docker compose logs backend` shows the exact message.
- *502 Bad Gateway for a minute after starting:* normal while the backend finishes starting.
