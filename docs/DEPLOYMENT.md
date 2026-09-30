# Deploying KYVON

KYVON runs on an Ubuntu 24.04 VM at `/home/traxc93/kyvon-assistant`, as the systemd service
`kyvon.service`, on port 8080, with a Cloudflare Tunnel providing HTTPS. Phase 1 keeps all of that.
The application is host-independent: it only needs Python 3.12, a writable data directory, and
environment variables, so it can move later (a Dockerfile is included) without code changes.

## Upgrade the VM to the Phase 1 build

Nothing below has been run for you. Do it step by step and check each result. Steps 1-2 only
inspect the VM.

**1. Inspect the current setup**

```bash
cd /home/traxc93/kyvon-assistant
git remote -v                      # confirm this is temcwilliams/jarvis-assistant
git status                         # should be clean
systemctl cat kyvon.service        # note ExecStart and where GROQ_API_KEY comes from
ls -la data/ 2>/dev/null           # the current memory file, if any
```

**2. Back up**

```bash
cp -a data "data.backup-$(date +%F)" 2>/dev/null || true
sudo cp /etc/systemd/system/kyvon.service ~/kyvon.service.backup
git rev-parse HEAD > ~/kyvon-previous-commit.txt
```

**3. Get the code** (after the branch is merged to `main`; before that, use the branch name)

```bash
git fetch origin
git checkout main && git pull        # or: git checkout phase-1/foundation && git pull
```

**4. Install dependencies** (Python 3.12 is the Ubuntu 24.04 default)

```bash
sudo apt install -y python3-venv     # if needed
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

**5. Configuration**

Create `/home/traxc93/kyvon-assistant/.env` (permissions `600`) with your existing Groq key:

```bash
install -m 600 /dev/null .env
nano .env
```

```
GROQ_API_KEY=<your existing key>
KYVON_ENV=production
```

If the key currently lives in the unit file (`Environment=GROQ_API_KEY=...`), move it into `.env`
and remove it from the unit so it is not stored in two places. Do not commit `.env` (it is in
`.gitignore`).

**6. Create the database, the owner account, and import memories**

```bash
.venv/bin/flask --app wsgi kyvon db-upgrade
.venv/bin/flask --app wsgi kyvon create-user          # prompts for username and password
.venv/bin/flask --app wsgi kyvon import-memories      # reads data/kyvon_memory.json
```

The import never changes the JSON file, so it stays as a backup. The prototype stored memory
timestamps without a timezone; they are imported as UTC.

**7. Switch the service to gunicorn**

Compare `deploy/kyvon.service` with your current unit (`~/kyvon.service.backup`), keep anything that
is specific to your setup, then install it:

```bash
sudo cp deploy/kyvon.service /etc/systemd/system/kyvon.service   # after adjusting it
sudo systemctl daemon-reload
sudo systemctl restart kyvon
systemctl status kyvon
journalctl -u kyvon -n 50 --no-pager
```

The unit runs migrations before each start (`ExecStartPre`). The port stays 8080, so the Cloudflare
Tunnel configuration does not change.

**8. Verify**

```bash
curl -s http://127.0.0.1:8080/api/v1/health                        # {"status":"ok"}
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8080/api/v1/memories   # 401 without sign-in
```

Then open your tunnel URL, sign in, send a message, press MEMORY, and check that your imported
memories appear.

## Notes

- **HTTPS and cookies:** with `KYVON_ENV=production`, sign-in cookies are marked Secure, so the web
  client must be opened through the tunnel's HTTPS URL. To test over plain HTTP on the VM's IP, set
  `KYVON_COOKIE_SECURE=false` temporarily.
- **Sign-in throttle:** behind the tunnel every request arrives from 127.0.0.1, so the failed-login
  limit (5 attempts, then 15 minutes) applies per username, not per client address.
- **One gunicorn worker** is intentional (SQLite plus an in-memory throttle). Threads handle
  concurrency.
- **Locked out?** `.venv/bin/flask --app wsgi kyvon set-password` resets the password and signs out
  every device.

## Rollback

```bash
sudo cp ~/kyvon.service.backup /etc/systemd/system/kyvon.service
cd /home/traxc93/kyvon-assistant && git checkout "$(cat ~/kyvon-previous-commit.txt)"
sudo systemctl daemon-reload && sudo systemctl restart kyvon
```

The old version reads `data/kyvon_memory.json`, which was never modified. Memories saved after the
upgrade exist only in `data/kyvon.db`.

## Docker (optional, not used on the VM)

```bash
docker build -t kyvon .
docker run -d --name kyvon -p 8080:8080 --env-file .env -v kyvon-data:/app/data kyvon
docker exec -it kyvon flask --app wsgi kyvon create-user
```

The image runs migrations on start. It has not been built in the development environment used so
far; CI builds it on every pull request.
