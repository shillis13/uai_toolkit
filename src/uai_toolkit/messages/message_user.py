#!/usr/bin/env python3
"""
message_user.py — AI -> user message (the human's own channel).

The peer to AI-to-AI messaging: an AI tells the USER something. Composes existing
pieces (no shared-code surgery):
  1. persist   — messaging.py send --to uai://user/<id> (records in the user's
                 message store; returns a messageId, reviewable later)
  2. surface   — send_user_notification.py (so the human actually sees it), unless
                 --silent (persist-only, like an async inbox note)

The user is auto-resolved to the primary registered user (users_mgr) so callers
never hardcode 'piano_man'. Business logic lives here; MCP/tool faces stay thin.

Usage:
    message_user.py --subject "Broadcast report" --content "3 delivered, 1 held"
    message_user.py --subject S --content C --silent           # persist, no popup
    message_user.py --subject S --content C --open <url|file>   # notification opens it
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
MESSAGING = HOME / "bin" / "ai" / "messages" / "messaging.py"
USERS_MGR = HOME / "AI" / "ai_root" / "ai_general" / "scripts" / "users" / "users_mgr.py"
NOTIFY = HOME / "bin" / "ai" / "notifications" / "send_user_notification.py"


def _run_json(cmd: list[str], timeout: int = 30) -> dict:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        # tolerate leading [DEPRECATED]/log lines: parse the last JSON object
        out = (r.stdout or "").strip()
        start = out.rfind("{")
        if start >= 0:
            return json.loads(out[start:])
        return {"ok": r.returncode == 0, "stdout": out, "stderr": (r.stderr or "").strip()[:300]}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def primary_user() -> str:
    """Resolve the primary registered user's id (e.g. 'piano_man')."""
    d = _run_json(["python3", str(USERS_MGR), "list"])
    users = d.get("users", []) if isinstance(d, dict) else []
    for u in users:
        if u.get("primary"):
            return u.get("id")
    return users[0].get("id") if users else "piano_man"


def notify(subject: str, preview: str, open_target: str | None = None) -> bool:
    """Fire a user-facing notification. Returns True on success."""
    if not NOTIFY.exists():
        return False
    msg = f"{subject}: {preview}" if preview else subject
    cmd = ["python3", str(NOTIFY), "done", msg]
    if open_target:
        cmd += ["--open", open_target]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=15).returncode == 0
    except Exception:  # noqa: BLE001
        return False


def message_user(subject: str, content: str, *, user: str | None = None,
                 silent: bool = False, open_target: str | None = None,
                 reply_to: str = "none") -> dict:
    """Persist a message to the user + (unless silent) surface a notification."""
    uid = user or primary_user()
    sent = _run_json(["python3", str(MESSAGING), "send",
                      "--to", f"uai://user/{uid}",
                      "--subject", subject, "--content", content,
                      "--reply-to", reply_to])
    msg_id = sent.get("messageId") or sent.get("msg_id")
    result = {"user": uid, "messageId": msg_id, "persisted": bool(msg_id), "notified": False}
    if not silent:
        preview = content if len(content) <= 140 else content[:137] + "…"
        result["notified"] = notify(subject, preview, open_target)
    if not msg_id:
        result["send_error"] = sent
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a message to the user (persist + notify).")
    ap.add_argument("--subject", required=True)
    ap.add_argument("--content", required=True)
    ap.add_argument("--user", help="user id (default: primary registered user)")
    ap.add_argument("--silent", action="store_true", help="persist only; no notification")
    ap.add_argument("--open", dest="open_target", help="url/file the notification opens")
    ap.add_argument("--reply-to", default="none")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = message_user(a.subject, a.content, user=a.user, silent=a.silent,
                       open_target=a.open_target, reply_to=a.reply_to)
    print(json.dumps(res, indent=2))
    return 0 if res.get("persisted") else 1


if __name__ == "__main__":
    sys.exit(main())
