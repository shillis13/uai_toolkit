#!/usr/bin/env python3
"""UserPromptSubmit hook — notify session of unread messages."""

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult


def handler(hook_input, context):
    if not context.tracking_id:
        return HookResult.skip("no tracking_id")

    messaging_py = os.path.expanduser("~/bin/ai/messages/messaging.py")
    if not os.path.isfile(messaging_py):
        return HookResult.skip("messaging.py not found")

    try:
        result = subprocess.run(
            [sys.executable, messaging_py, "check", "--session", context.tracking_id],
            capture_output=True, text=True, timeout=10,
        )
    except (subprocess.TimeoutExpired, OSError):
        return HookResult.skip("messaging.py check failed")

    if result.returncode != 0:
        return HookResult.skip("messaging.py returned non-zero")

    try:
        data = json.loads(result.stdout.strip())
    except (json.JSONDecodeError, ValueError):
        return HookResult.skip("messaging.py output not JSON")

    if not data.get("success"):
        return HookResult.skip("messaging check unsuccessful")

    total = data.get("total_unread", 0)
    if total <= 0:
        return HookResult.allow("no unread messages")

    inbox = data.get("inbox_unread", 0)
    broadcast = data.get("broadcast_unread", 0)
    s = "s" if total != 1 else ""

    notice = (
        f"You have {total} unread message{s} "
        f"({inbox} inbox, {broadcast} broadcast). "
        f"Use messaging.py read --id MSG_ID to read them, "
        f"or messaging.py list --dir inbox --recipient {context.tracking_id} "
        f"to see the list."
    )

    output = json.dumps({"hookSpecificOutput": {"additionalContext": notice}})
    return HookResult.output(output, f"{total} unread messages")


if __name__ == "__main__":
    sys.exit(run_hook("notify_unread_messages", "UserPromptSubmit", handler))
