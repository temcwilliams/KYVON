#!/usr/bin/env bash
# One-time setup on the VM: run KYVON under systemd and update it automatically from main.
#
#   sudo ./deploy/install-auto-update.sh [--user NAME]
#
# Installs three things, with this checkout's real folder and user filled in:
#   kyvon.service         the app (restarts if it crashes or the VM reboots)
#   kyvon-update.timer    every few minutes runs deploy/update.sh (pull, migrate, restart)
#   a sudoers rule        lets that user start/stop/restart ONLY the kyvon service
# Safe to run again. It does not stop a copy of KYVON you started by hand; it tells you how.

set -euo pipefail

APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="$(stat -c %U "$APP_DIR")"
SYSTEMD_DIR="${KYVON_SYSTEMD_DIR:-/etc/systemd/system}"
SUDOERS_DIR="${KYVON_SUDOERS_DIR:-/etc/sudoers.d}"
SYSTEMCTL="${KYVON_SYSTEMCTL:-systemctl}"
VISUDO="${KYVON_VISUDO:-visudo}"
PORT="${KYVON_PORT:-8080}"
INTERVAL="${KYVON_UPDATE_INTERVAL:-5min}"

while [ $# -gt 0 ]; do
  case "$1" in
    --user) APP_USER="$2"; shift 2 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

if [ "$(id -u)" != 0 ] && [ -z "${KYVON_SKIP_ROOT_CHECK:-}" ]; then
  echo "Run this with sudo." >&2; exit 1
fi
[ -x "$APP_DIR/.venv/bin/flask" ] || [ -n "${KYVON_SKIP_ROOT_CHECK:-}" ] \
  || { echo "No virtualenv at $APP_DIR/.venv. Follow docs/DEPLOYMENT.md first." >&2; exit 1; }
[ -f "$APP_DIR/.env" ] || [ -n "${KYVON_SKIP_ROOT_CHECK:-}" ] \
  || { echo "No $APP_DIR/.env (your settings and keys). Create it first." >&2; exit 1; }
id "$APP_USER" >/dev/null 2>&1 || [ -n "${KYVON_SKIP_ROOT_CHECK:-}" ] \
  || { echo "User $APP_USER does not exist." >&2; exit 1; }

mkdir -p "$SYSTEMD_DIR" "$SUDOERS_DIR"
chmod +x "$APP_DIR/deploy/update.sh"

# The app unit: the template in the repo, with this checkout's folder and user.
sed -e "s#/home/traxc93/kyvon-assistant#$APP_DIR#g" -e "s#^User=.*#User=$APP_USER#" \
  "$APP_DIR/deploy/kyvon.service" > "$SYSTEMD_DIR/kyvon.service"

cat > "$SYSTEMD_DIR/kyvon-update.service" <<EOF
# Installed by deploy/install-auto-update.sh
[Unit]
Description=Update KYVON from $APP_DIR (git, migrations, restart)
After=network-online.target
Wants=network-online.target

[Service]
Type=oneshot
User=$APP_USER
WorkingDirectory=$APP_DIR
EnvironmentFile=$APP_DIR/.env
Environment=KYVON_ENV=production
ExecStart=$APP_DIR/deploy/update.sh
# Leave room for a backup, pip install and a slow start.
TimeoutStartSec=15min
EOF

cat > "$SYSTEMD_DIR/kyvon-update.timer" <<EOF
# Installed by deploy/install-auto-update.sh
[Unit]
Description=Check for a new KYVON release

[Timer]
OnBootSec=2min
OnUnitActiveSec=$INTERVAL
RandomizedDelaySec=30s

[Install]
WantedBy=timers.target
EOF

# Only these three commands, only for this one service.
CTL_PATH="$(command -v "$SYSTEMCTL" || echo /usr/bin/systemctl)"
SUDOERS_TMP="$(mktemp)"
cat > "$SUDOERS_TMP" <<EOF
# Installed by deploy/install-auto-update.sh: the update job may control the kyvon service, nothing else.
$APP_USER ALL=(root) NOPASSWD: $CTL_PATH start kyvon, $CTL_PATH stop kyvon, $CTL_PATH restart kyvon
EOF
chmod 440 "$SUDOERS_TMP"
if ! "$VISUDO" -cf "$SUDOERS_TMP" >/dev/null; then
  rm -f "$SUDOERS_TMP"; echo "The generated sudoers rule failed validation; nothing was installed." >&2; exit 1
fi
mv "$SUDOERS_TMP" "$SUDOERS_DIR/kyvon-update"

"$SYSTEMCTL" daemon-reload
"$SYSTEMCTL" enable kyvon.service >/dev/null 2>&1 || true
"$SYSTEMCTL" enable --now kyvon-update.timer

# Starting the service while a hand-started copy holds the port would fail, so check first.
if "$SYSTEMCTL" is-active --quiet kyvon.service 2>/dev/null; then
  echo "kyvon.service is already running."
elif command -v ss >/dev/null 2>&1 && ss -ltn "sport = :$PORT" 2>/dev/null | grep -q LISTEN; then
  cat <<EOF

Port $PORT is in use by a copy of KYVON that was started by hand. Stop that copy, then run:
    sudo systemctl start kyvon
(Ctrl+C in the terminal where it runs, or: pkill -f 'gunicorn.*wsgi')
Auto-update is installed and will keep working once the service is running.
EOF
else
  "$SYSTEMCTL" start kyvon.service
  echo "Started kyvon.service."
fi

cat <<EOF

Done. KYVON will check $(git -C "$APP_DIR" remote get-url origin 2>/dev/null || echo "its git remote") (branch main) every $INTERVAL.
  Watch updates:    journalctl -u kyvon-update -f
  Update now:       sudo systemctl start kyvon-update
  Pause updates:    sudo systemctl stop kyvon-update.timer
  App logs:         journalctl -u kyvon -f
EOF
