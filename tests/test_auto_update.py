"""deploy/update.sh and deploy/install-auto-update.sh, run for real against throwaway git repos.

The flask/pip/systemctl commands are replaced by small stand-ins that write to a log, so every path
(no change, clean update, each failure and its rollback, the safety refusals) is exercised without
touching anything real. "Healthy" is a file the health URL (file://...) points at.
"""

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
UPDATE = ROOT / "deploy" / "update.sh"
INSTALL = ROOT / "deploy" / "install-auto-update.sh"

pytestmark = pytest.mark.skipif(
    not all(shutil.which(tool) for tool in ("bash", "git", "flock", "curl")),
    reason="needs bash, git, flock and curl",
)

FAKE_FLASK = """#!/usr/bin/env bash
echo "flask $*" >> "$KV_LOG"
case "$4" in
  backup)
    [ -e "$KV_DIR/fail-backup" ] && { echo "disk full" >&2; exit 1; }
    mkdir -p "$KV_DIR/backups"; echo db > "$KV_DIR/backups/kyvon-1.db"
    echo "Backup written: $KV_DIR/backups/kyvon-1.db (3 bytes). Keeping 1." ;;
  doctor) [ -e "$KV_DIR/fail-doctor" ] && exit 1 ;;
  db-upgrade) [ -e "$KV_DIR/fail-migrate" ] && exit 1 ;;
esac
exit 0
"""

FAKE_PIP = '#!/usr/bin/env bash\necho "pip $*" >> "$KV_LOG"\n'

# stop/start/restart: record the call, then set health. A restart is unhealthy when the checked-out
# VERSION is listed in unhealthy.txt.
FAKE_CTL = """#!/usr/bin/env bash
echo "ctl $1" >> "$KV_LOG"
case "$1" in
  stop) rm -f "$KV_DIR/healthy" ;;
  start|restart)
    if grep -qx "$(cat "$KV_APP/VERSION")" "$KV_DIR/unhealthy.txt" 2>/dev/null; then
      rm -f "$KV_DIR/healthy"
    else
      touch "$KV_DIR/healthy"
    fi ;;
esac
"""


def git(cwd, *args):
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def script(path, body):
    path.write_text(body)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class World:
    """A remote repo, an app checkout that follows it, and the stand-in commands."""

    def __init__(self, tmp: Path):
        self.dir = tmp / "world"
        self.dir.mkdir()
        self.remote = self.dir / "remote.git"
        git(self.dir, "init", "--bare", "-b", "main", str(self.remote))
        self.work = self.dir / "work"
        git(self.dir, "clone", "-q", str(self.remote), str(self.work))
        self.app = self.dir / "app"
        self.log = self.dir / "log.txt"
        self.log.write_text("")
        self.release("v1", requirements="flask\n")
        git(self.dir, "clone", "-q", str(self.remote), str(self.app))
        (self.dir / "healthy").touch()
        self.bin = self.dir / "bin"
        self.bin.mkdir()
        script(self.bin / "flask", FAKE_FLASK)
        script(self.bin / "pip", FAKE_PIP)
        script(self.bin / "ctl", FAKE_CTL)

    def release(self, version, requirements=None):
        (self.work / "VERSION").write_text(version + "\n")
        if requirements is not None:
            (self.work / "requirements.txt").write_text(requirements)
        git(self.work, "add", "-A")
        git(self.work, "commit", "-q", "-m", version)
        git(self.work, "push", "-q", "origin", "main")

    def head(self):
        return git(self.app, "rev-parse", "HEAD")

    def version(self):
        return (self.app / "VERSION").read_text().strip()

    def calls(self):
        return self.log.read_text().splitlines()

    def mark(self, name, content=""):
        (self.dir / name).write_text(content)

    def run(self):
        env = {
            **os.environ,
            "KV_LOG": str(self.log),
            "KV_DIR": str(self.dir),
            "KV_APP": str(self.app),
            "KYVON_APP_DIR": str(self.app),
            "KYVON_FLASK": str(self.bin / "flask"),
            "KYVON_PIP": str(self.bin / "pip"),
            "KYVON_STOP_CMD": f"{self.bin}/ctl stop",
            "KYVON_START_CMD": f"{self.bin}/ctl start",
            "KYVON_RESTART_CMD": f"{self.bin}/ctl restart",
            "KYVON_HEALTH_URL": f"file://{self.dir}/healthy",
            "KYVON_HEALTH_TRIES": "2",
            "KYVON_HEALTH_SLEEP": "0",
        }
        return subprocess.run(
            ["bash", str(UPDATE)], env=env, capture_output=True, text=True, cwd=self.app
        )


@pytest.fixture
def world(tmp_path):
    return World(tmp_path)


def test_nothing_new_does_nothing(world):
    result = world.run()
    assert result.returncode == 0 and result.stdout == ""
    assert world.calls() == []


def test_new_release_is_backed_up_migrated_restarted_in_order(world):
    world.release("v2")
    result = world.run()
    assert result.returncode == 0, result.stdout + result.stderr
    assert world.version() == "v2"
    calls = world.calls()
    steps = [
        next(i for i, c in enumerate(calls) if key in c)
        for key in ("kyvon backup", "kyvon doctor", "kyvon db-upgrade", "ctl restart")
    ]
    assert steps == sorted(steps)
    assert "updated to" in result.stdout


def test_dependencies_install_only_when_requirements_change(world):
    world.release("v2")
    world.run()
    assert not any(c.startswith("pip") for c in world.calls())
    world.release("v3", requirements="flask\nrequests\n")
    world.run()
    assert any(c.startswith("pip install") for c in world.calls())


def test_failed_doctor_rolls_back_without_migrating(world):
    before = world.head()
    world.release("v2")
    world.mark("fail-doctor")
    result = world.run()
    assert result.returncode == 1 and world.head() == before
    calls = world.calls()
    assert not any("db-upgrade" in c for c in calls)
    assert not any("restore" in c for c in calls)  # nothing was migrated, nothing to restore
    assert "ctl start" in calls and (world.dir / "healthy").exists()


def test_failed_migration_restores_the_backup_and_old_code(world):
    before = world.head()
    world.release("v2")
    world.mark("fail-migrate")
    result = world.run()
    assert result.returncode == 1 and world.head() == before
    restore = [c for c in world.calls() if "kyvon restore" in c]
    assert len(restore) == 1 and "kyvon-1.db" in restore[0] and "--yes" in restore[0]
    assert (world.dir / "healthy").exists()  # the old version is serving again


def test_unhealthy_release_rolls_back_code_but_keeps_the_data(world):
    before = world.head()
    world.release("v2")
    world.mark("unhealthy.txt", "v2\n")
    result = world.run()
    assert result.returncode == 1 and world.head() == before and world.version() == "v1"
    assert not any("kyvon restore" in c for c in world.calls())  # migrations succeeded; data stays
    assert (world.dir / "healthy").exists()


def test_failed_backup_cancels_before_changing_anything(world):
    before = world.head()
    world.release("v2")
    world.mark("fail-backup")
    result = world.run()
    assert result.returncode == 1 and world.head() == before
    assert not any("restart" in c or "doctor" in c for c in world.calls())
    assert "backup failed" in result.stdout


def test_uncommitted_changes_are_never_overwritten(world):
    world.release("v2")
    (world.app / "VERSION").write_text("hand edit\n")
    result = world.run()
    assert result.returncode == 1 and "uncommitted" in result.stdout
    assert (world.app / "VERSION").read_text() == "hand edit\n" and world.calls() == []


def test_local_only_commits_are_never_discarded(world):
    (world.app / "LOCAL").write_text("mine\n")
    git(world.app, "add", "-A")
    git(world.app, "commit", "-q", "-m", "local change")
    world.release("v2")
    result = world.run()
    assert result.returncode == 1 and "not on origin/main" in result.stdout
    assert (world.app / "LOCAL").exists() and world.calls() == []


def test_other_branches_are_not_followed(world):
    git(world.app, "checkout", "-q", "-b", "experiment")
    world.release("v2")
    result = world.run()
    assert result.returncode == 1 and "not main" in result.stdout and world.calls() == []


def test_installer_writes_units_with_the_real_paths_and_a_narrow_sudoers_rule(tmp_path):
    app = tmp_path / "kyvon-new"
    shutil.copytree(ROOT / "deploy", app / "deploy")
    systemd, sudoers = tmp_path / "systemd", tmp_path / "sudoers.d"
    env = {
        **os.environ,
        "KYVON_SKIP_ROOT_CHECK": "1",
        "KYVON_SYSTEMD_DIR": str(systemd),
        "KYVON_SUDOERS_DIR": str(sudoers),
        "KYVON_SYSTEMCTL": "true",
        "KYVON_VISUDO": "true",
    }
    result = subprocess.run(
        ["bash", str(app / "deploy" / "install-auto-update.sh"), "--user", "kyvonuser"],
        env=env,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr

    service = (systemd / "kyvon.service").read_text()
    assert f"WorkingDirectory={app}" in service and "User=kyvonuser" in service
    assert "kyvon-assistant" not in service and "/home/traxc93" not in service

    update = (systemd / "kyvon-update.service").read_text()
    assert f"ExecStart={app}/deploy/update.sh" in update and "User=kyvonuser" in update
    assert "OnUnitActiveSec=5min" in (systemd / "kyvon-update.timer").read_text()

    rule = (sudoers / "kyvon-update").read_text()
    assert "kyvonuser ALL=(root) NOPASSWD:" in rule
    assert rule.count("kyvon") >= 4 and "ALL=(ALL)" not in rule and "NOPASSWD: ALL" not in rule
    assert oct((sudoers / "kyvon-update").stat().st_mode & 0o777) == "0o440"


def test_scripts_are_executable_and_valid_bash():
    for path in (UPDATE, INSTALL):
        assert path.stat().st_mode & stat.S_IXUSR, path.name
        subprocess.run(["bash", "-n", str(path)], check=True)
