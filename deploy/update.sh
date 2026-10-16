#!/usr/bin/env bash
# Update KYVON when the main branch has new commits. Run by kyvon-update.timer (see
# docs/DEPLOYMENT.md, "Automatic updates"); safe to run by hand.
#
# For each new release it: backs up the database, fast-forwards the code, installs changed
# dependencies, runs `doctor` and `db-upgrade`, restarts the service and waits for it to be
# healthy. If a step fails it puts the previous code back (and the database backup, when a
# migration itself failed), restarts, and exits non-zero so systemd shows the failure.
#
# Every command can be overridden with a KYVON_* variable; the tests rely on that.

set -euo pipefail

APP_DIR="${KYVON_APP_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
REMOTE="${KYVON_UPDATE_REMOTE:-origin}"
BRANCH="${KYVON_UPDATE_BRANCH:-main}"
PIP="${KYVON_PIP:-$APP_DIR/.venv/bin/pip}"
FLASK="${KYVON_FLASK:-$APP_DIR/.venv/bin/flask}"
STOP_CMD="${KYVON_STOP_CMD:-sudo -n systemctl stop kyvon}"
START_CMD="${KYVON_START_CMD:-sudo -n systemctl start kyvon}"
RESTART_CMD="${KYVON_RESTART_CMD:-sudo -n systemctl restart kyvon}"
HEALTH_URL="${KYVON_HEALTH_URL:-http://127.0.0.1:8080/api/v1/health/ready}"
HEALTH_TRIES="${KYVON_HEALTH_TRIES:-30}"
HEALTH_SLEEP="${KYVON_HEALTH_SLEEP:-2}"

log() { echo "kyvon-update: $*"; }
die() { log "ERROR: $*"; exit 1; }

cd "$APP_DIR"
[ -d .git ] || die "$APP_DIR is not a git checkout."

# One update at a time (the timer and a manual run must not overlap).
exec 9>"${KYVON_LOCK_FILE:-$APP_DIR/.git/kyvon-update.lock}"
flock -n 9 || { log "another update is running; skipping."; exit 0; }

# Never overwrite work done by hand on the VM, and only follow the release branch.
git diff --quiet && git diff --cached --quiet \
  || die "there are uncommitted changes in $APP_DIR; commit or discard them first."
[ "$(git rev-parse --abbrev-ref HEAD)" = "$BRANCH" ] \
  || die "checked out branch is not $BRANCH; refusing to update."

git fetch --quiet "$REMOTE" "$BRANCH" || die "could not fetch $REMOTE/$BRANCH (network?)."
OLD="$(git rev-parse HEAD)"
NEW="$(git rev-parse "$REMOTE/$BRANCH")"
if [ "$OLD" = "$NEW" ]; then
  exit 0   # nothing new; stay quiet so the journal is not full of noise
fi
git merge-base --is-ancestor "$OLD" "$NEW" \
  || die "this checkout has commits that are not on $REMOTE/$BRANCH; refusing to overwrite them."

log "updating ${OLD:0:7} -> ${NEW:0:7}"

changed() { ! git diff --quiet "$OLD" "$NEW" -- "$@"; }

# 1. Back up first. If the backup fails, nothing has changed yet.
BACKUP_OUT="$("$FLASK" --app wsgi kyvon backup --keep 14 2>&1)" \
  || die "backup failed, update cancelled: $BACKUP_OUT"
BACKUP_FILE="$(printf '%s\n' "$BACKUP_OUT" | sed -n 's/^Backup written: \(.*\) ([0-9]* bytes).*/\1/p' | tail -1)"
[ -n "$BACKUP_FILE" ] && [ -f "$BACKUP_FILE" ] || die "could not find the backup file; update cancelled."
log "backup: $BACKUP_FILE"

MIGRATION_FAILED=0

wait_healthy() {
  local i
  for i in $(seq 1 "$HEALTH_TRIES"); do
    if curl -fsS --max-time 3 "$HEALTH_URL" >/dev/null 2>&1; then return 0; fi
    sleep "$HEALTH_SLEEP"
  done
  return 1
}

rollback() {
  log "rolling back to ${OLD:0:7}"
  # Stop first so nothing holds the database open while we put things back.
  $STOP_CMD || log "warning: could not stop the service"
  git reset --hard --quiet "$OLD"
  if changed requirements.txt; then "$PIP" install --quiet -r requirements.txt || true; fi
  if [ "$MIGRATION_FAILED" = 1 ]; then
    # A migration that failed part-way may leave the schema half changed; put the backup back.
    "$FLASK" --app wsgi kyvon restore "$BACKUP_FILE" --yes \
      || log "warning: restoring the backup failed; the backup is at $BACKUP_FILE"
  fi
  $START_CMD || log "warning: could not start the service"
  if wait_healthy; then log "rolled back; ${OLD:0:7} is running again."
  else log "WARNING: the rolled-back version is not healthy either. Check: journalctl -u kyvon"; fi
}

fail() { log "ERROR: $1"; rollback; exit 1; }

# 2. Code, dependencies, checks, migrations.
git merge --ff-only --quiet "$NEW" || die "could not fast-forward to ${NEW:0:7}."

if changed requirements.txt; then
  log "dependencies changed; installing"
  "$PIP" install --quiet -r requirements.txt || fail "pip install failed."
fi

"$FLASK" --app wsgi kyvon doctor --quiet || fail "doctor found a problem with the new version."

MIGRATION_FAILED=1
"$FLASK" --app wsgi kyvon db-upgrade || fail "db-upgrade failed."
MIGRATION_FAILED=0   # migrations here only add columns and tables, so later failures keep the data

# 3. Restart and wait until it answers.
$RESTART_CMD || fail "could not restart the service."
wait_healthy || fail "the new version did not become healthy."

log "updated to ${NEW:0:7}."
