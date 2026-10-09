"""Smoke-test a running KYVON server over real HTTP.

    python scripts/smoke_test.py http://127.0.0.1:8080 USERNAME [--chat]

The password is read from the KYVON_SMOKE_PASSWORD environment variable (never a command-line
argument). It exercises sign-in, the main resources and the admin view, and leaves the
data it creates deleted. ``--chat`` also sends one message to the language model.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

results: list[tuple[str, bool, str]] = []


class Client:
    def __init__(self, base: str):
        self.base = base.rstrip("/")
        self.token = None

    def call(self, method: str, path: str, body=None):
        data = None if body is None else json.dumps(body).encode()
        request = urllib.request.Request(self.base + "/api/v1" + path, data=data, method=method)
        request.add_header("Content-Type", "application/json")
        if self.token:
            request.add_header("Authorization", f"Bearer {self.token}")
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return response.status, json.loads(response.read() or b"{}")
        except urllib.error.HTTPError as error:
            try:
                return error.code, json.loads(error.read() or b"{}")
            except ValueError:
                return error.code, {}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, ok, detail))
    print(f"[{'ok' if ok else 'FAIL'}] {name}{' - ' + detail if detail and not ok else ''}")


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    client = Client(sys.argv[1])
    username = sys.argv[2]
    password = os.environ.get("KYVON_SMOKE_PASSWORD", "")
    with_chat = "--chat" in sys.argv

    status, body = client.call("GET", "/health")
    check("health", status == 200 and body.get("status") == "ok")
    status, body = client.call("GET", "/health/ready")
    check("readiness", status == 200 and body.get("status") == "ready")
    status, _ = client.call("GET", "/memories")
    check("protected without sign-in", status == 401)
    status, body = client.call(
        "POST", "/auth/login", {"username": username, "password": "wrong-password-x"}
    )
    check("wrong password refused", status == 401)
    status, body = client.call(
        "POST", "/auth/login", {"username": username, "password": password, "device_name": "smoke"}
    )
    check("login", status == 200 and "token" in body, str(status))
    if status != 200:
        return 1
    client.token = body["token"]
    status, body = client.call("GET", "/auth/me")
    check("current user", status == 200 and body["user"]["username"] == username.lower())

    status, body = client.call("POST", "/memories", {"text": "smoke test memory fact"})
    memory_id = body.get("memory", {}).get("id")
    check("memory create", status in (200, 201) and memory_id)
    status, body = client.call("GET", "/memories?q=smoke")
    check("memory search", status == 200 and any("smoke" in m["memory"] for m in body["memories"]))
    check("memory delete", client.call("DELETE", f"/memories/{memory_id}")[0] == 200)

    status, body = client.call(
        "POST", "/tasks", {"title": "smoke task", "due": "2099-01-01", "priority": "high"}
    )
    task_id = body.get("task", {}).get("id")
    check("task create", status == 201 and task_id)
    check("task complete", client.call("POST", f"/tasks/{task_id}/complete")[0] == 200)
    check("task delete", client.call("DELETE", f"/tasks/{task_id}")[0] == 200)

    status, body = client.call("PATCH", "/settings", {"tone": "warm"})
    check("settings update", status == 200 and body["settings"]["tone"] == "warm")
    client.call("POST", "/settings/reset")

    status, body = client.call(
        "POST",
        "/automations",
        {
            "name": "smoke reminder",
            "kind": "reminder",
            "text": "smoke",
            "schedule": {"type": "daily", "time": "08:00"},
        },
    )
    automation_id = body.get("automation", {}).get("id")
    check("automation create", status == 201 and automation_id)
    check("automation delete", client.call("DELETE", f"/automations/{automation_id}")[0] == 200)

    status, body = client.call("GET", "/tools")
    check(
        "tool catalogue",
        status == 200 and len(body["tools"]) > 20,
        f"{len(body.get('tools', []))} tools",
    )
    status, body = client.call("GET", "/agents")
    check("agents", status == 200 and len(body["agents"]) >= 5)
    check("notifications", client.call("GET", "/notifications")[0] == 200)
    check("voice config", client.call("GET", "/voice/config")[0] == 200)
    status, body = client.call("GET", "/calendar/status")
    check(
        "calendar status",
        status == 200,
        json.dumps({k: body.get(k) for k in ("configured", "connected")}),
    )
    check("logseq status", client.call("GET", "/logseq/status")[0] == 200)
    status, body = client.call("GET", "/admin/status")
    check(
        "admin status",
        status == 200 and body.get("database", {}).get("ok") is True,
        f"healthy={body.get('healthy')}",
    )

    if with_chat:
        status, body = client.call("POST", "/chat", {"message": "Reply with the single word: pong"})
        check(
            "chat",
            status == 200 and body.get("response"),
            str(body.get("error") or body.get("response", ""))[:80],
        )
        if status == 200:
            client.call("DELETE", f"/conversations/{body['conversation_id']}")

    check("logout", client.call("POST", "/auth/logout")[0] == 200)
    check("token revoked", client.call("GET", "/auth/me")[0] == 401)

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
