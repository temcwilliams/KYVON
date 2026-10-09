# Deploying KYVON

Target: the existing **Ubuntu 24.04 VM** at `/home/traxc93/kyvon-assistant`, running as the systemd
service `kyvon.service` on **port 8080**, with a **Cloudflare Tunnel** providing HTTPS. Nothing
below has been run for you: the VM has not been touched, and its Git remote has not been verified.
Work through it in order and check each result.

The application is host-independent (Python 3.12, a data folder, environment variables). A
`Dockerfile` is included so it can move to another host later without code changes.

## 0. What is in a release

| Piece | Where |
|---|---|
| Server | `kyvon/`, started by `gunicorn -c gunicorn.conf.py wsgi:app` (one worker, four threads) |
| Web app / PWA | `web/` (served by the same process) |
| Database | SQLite `data/kyvon.db`, migrated by `flask --app wsgi kyvon db-upgrade` |
| Settings | environment variables / `.env` ([reference](CONFIGURATION.md)) |
| Service files | `deploy/kyvon.service`, `deploy/kyvon-backup.{service,timer}`, `deploy/cloudflared-config.example.yml` |

**One gunicorn worker on purpose:** SQLite is a single-file database, and the scheduler, login
throttle and rate limits live in process memory.

## 1. First upgrade from the prototype (or a fresh install)

**1. Inspect what is there**

```bash
cd /home/traxc93/kyvon-assistant
git remote -v                      # confirm it is temcwilliams/kyvon
git status                         # should be clean
systemctl cat kyvon.service        # note ExecStart and where GROQ_API_KEY comes from
ls -la data/ 2>/dev/null           # the prototype's memory file, if any
```

**2. Back up (before changing anything)**

```bash
cp -a data "data.backup-$(date +%F)" 2>/dev/null || true
sudo cp /etc/systemd/system/kyvon.service ~/kyvon.service.backup
git rev-parse HEAD > ~/kyvon-previous-commit.txt
```

**3. Get the code** (use `main` once the branch is merged)

```bash
git fetch origin && git checkout main && git pull
```

**4. Install**

```bash
sudo apt install -y python3-venv
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**5. Configure** - create `.env` with mode 600. Only `GROQ_API_KEY` is required; production
defaults handle the rest. See [CONFIGURATION.md](CONFIGURATION.md).

```bash
install -m 600 /dev/null .env && nano .env
```

```
GROQ_API_KEY=<your existing key>
KYVON_ENV=production
KYVON_PUBLIC_URL=https://kyvon.example.com     # your tunnel hostname
```

If the key currently lives in the unit file (`Environment=GROQ_API_KEY=...`), move it into `.env`
and remove it from the unit.

**6. Check, create the database and the owner, import old memories**

```bash
.venv/bin/flask --app wsgi kyvon doctor            # explains anything that is wrong
.venv/bin/flask --app wsgi kyvon db-upgrade
.venv/bin/flask --app wsgi kyvon create-user       # username + password (min 10 chars)
.venv/bin/flask --app wsgi kyvon import-memories   # only if data/kyvon_memory.json exists
```

The import never changes the JSON file (it stays as a backup). The prototype stored memory
timestamps without a time zone; they are imported as UTC.

**7. Install the service**

Compare `deploy/kyvon.service` with your current unit, keep anything specific to your setup, then:

```bash
sudo cp deploy/kyvon.service /etc/systemd/system/kyvon.service
sudo systemctl daemon-reload
sudo systemctl restart kyvon
systemctl status kyvon
journalctl -u kyvon -n 50 --no-pager
```

The unit runs `kyvon doctor` and `db-upgrade` before every start, so a bad configuration fails with a
readable message instead of a broken service.

**8. Verify**

```bash
curl -s http://127.0.0.1:8080/api/v1/health/ready                      # {"status":"ready"}
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/api/v1/memories   # 401 without sign-in
```

Then open your tunnel URL, sign in, send a message, and open **Admin** in the menu for a status
summary (use *Deep check* once to confirm the AI model is reachable).

## 2. HTTPS with Cloudflare Tunnel

KYVON keeps listening on `127.0.0.1:8080`; the tunnel terminates HTTPS. Example:
`deploy/cloudflared-config.example.yml`. In `.env`:

```
KYVON_ENV=production
KYVON_PUBLIC_URL=https://kyvon.example.com
KYVON_COOKIE_SECURE=true
```

- With production mode, sign-in cookies are `Secure` and HSTS is sent, so open KYVON through the
  HTTPS URL (plain-HTTP testing on the VM needs `KYVON_COOKIE_SECURE=false` temporarily).
- Browser location, microphone, install-to-Home-Screen and notifications all need HTTPS: the tunnel
  provides it.
- Behind the tunnel every request appears to come from 127.0.0.1, so the failed-login limit applies
  per username (see [SECURITY.md](SECURITY.md)).
- Cloudflare closes connections idle for about 100 seconds. A very long agent run can outlast that;
  the reply is still saved and appears when the page reloads.

## 3. Optional features (each is off until configured)

| Feature | What to set | Notes |
|---|---|---|
| Google Calendar | `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `KYVON_ENCRYPTION_KEY` (`kyvon generate-key`), `KYVON_PUBLIC_URL` | In Google Cloud Console create an OAuth client (Web application), enable the Calendar API, and add the redirect URI `<KYVON_PUBLIC_URL>/api/v1/calendar/callback`. Then press *Connect* in the Calendar tab. |
| Logseq | `KYVON_LOGSEQ_DIR` | A folder containing `pages/` and `journals/`. KYVON reads freely and writes only with your approval. |
| Hermes | `KYVON_HERMES_URL` (+ `KYVON_HERMES_API_KEY`, `KYVON_HERMES_MODEL`) | An OpenAI-compatible endpoint on a private address. Never point it at anything with shell access to the VM. |
| Web Push | `kyvon generate-vapid-keys`, then the three `KYVON_VAPID_*` values | Reminders always reach the in-app Inbox; push is a bonus. |
| Voice | (nothing) | Uses your Groq key for Whisper; replies are read aloud by the device. |

## 4. Backups

```bash
.venv/bin/flask --app wsgi kyvon backup          # consistent copy in data/backups/, keeps 14
```

Automatic daily backups:

```bash
sudo cp deploy/kyvon-backup.service deploy/kyvon-backup.timer /etc/systemd/system/
sudo systemctl enable --now kyvon-backup.timer
```

Copy `data/backups/` somewhere off the VM as well (a backup on the same disk is not a backup).
Also keep a safe copy of `.env`, especially `KYVON_ENCRYPTION_KEY`: without it a restored database
cannot decrypt the Google tokens (you would simply reconnect Calendar).

**Restore:**

```bash
sudo systemctl stop kyvon
.venv/bin/flask --app wsgi kyvon restore data/backups/kyvon-YYYYMMDD-HHMMSS.db --yes
.venv/bin/flask --app wsgi kyvon db-upgrade      # only needed if the backup is older
sudo systemctl start kyvon
```

The database it replaced is kept beside it as `kyvon.db.pre-restore-<time>`.

## 5. Upgrading later

```bash
cd /home/traxc93/kyvon-assistant
.venv/bin/flask --app wsgi kyvon backup
git pull
.venv/bin/pip install -r requirements.txt
sudo systemctl restart kyvon        # runs doctor + migrations, then starts
journalctl -u kyvon -n 30 --no-pager
```

## 6. Operating it

| Need | Command |
|---|---|
| Logs (JSON) | `journalctl -u kyvon -o cat \| tail -50` (each line has a `request_id`) |
| Health | `curl http://127.0.0.1:8080/api/v1/health/ready`; the *Admin* panel shows details |
| Reset a forgotten password / sign out all devices | `flask --app wsgi kyvon set-password` |
| Sign out every device | `flask --app wsgi kyvon revoke-tokens` |
| Check configuration | `flask --app wsgi kyvon doctor` |
| Stop cleanly | `sudo systemctl stop kyvon` (finishes in-flight requests, stops the scheduler) |

**Startup:** systemd runs `doctor` and `db-upgrade`, then gunicorn. **Shutdown:** SIGTERM; in-flight
requests get up to 30 seconds, background schedulers and agent workers are stopped.

## 7. Rollback

```bash
sudo cp ~/kyvon.service.backup /etc/systemd/system/kyvon.service
cd /home/traxc93/kyvon-assistant && git checkout "$(cat ~/kyvon-previous-commit.txt)"
sudo systemctl daemon-reload && sudo systemctl restart kyvon
```

The prototype reads `data/kyvon_memory.json`, which was never modified. Anything saved after the
upgrade exists only in `data/kyvon.db` (restore a database backup if you need it back in a newer
version).

## 8. Docker (optional; not used on the VM)

```bash
docker build -t kyvon .
docker run -d --name kyvon -p 8080:8080 --env-file .env -v kyvon-data:/app/data kyvon
docker exec -it kyvon flask --app wsgi kyvon create-user
```

The image runs as a non-root user, checks configuration and migrates on start, and has a health
check on `/api/v1/health/ready`. It has not been built in the development environment; CI builds it
on every pull request.
