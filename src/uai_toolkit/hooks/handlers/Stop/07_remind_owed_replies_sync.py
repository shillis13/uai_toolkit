#!/usr/bin/env python3
"""Stop hook — remind session if it owes replies to pending messages."""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
PENDING_REPLIES_DIR = AI_ROOT / "ai_general" / "data" / "comms" / "pending_replies"


def _time_ago(created_at_str):
    try:
        created = datetime.fromisoformat(created_at_str)
        delta = datetime.now() - created
        total_seconds = int(delta.total_seconds())
        if total_seconds < 60:
            return "{}s ago".format(total_seconds)
        minutes = total_seconds // 60
        if minutes < 60:
            return "{}m ago".format(minutes)
        hours = minutes // 60
        if hours < 24:
            return "{}h ago".format(hours)
        return "{}d ago".format(hours // 24)
    except (ValueError, TypeError):
        return "unknown time ago"


def handler(hook_input, context):
    if not context.tracking_id:
        return HookResult.skip("no tracking_id")

    if not PENDING_REPLIES_DIR.exists():
        return HookResult.skip("no pending_replies dir")

    try:
        import yaml
    except ImportError:
        return HookResult.skip("yaml not available")

    now = datetime.now()
    owed = []

    for filepath in sorted(PENDING_REPLIES_DIR.glob("pending_*.yml")):
        try:
            with open(filepath) as f:
                entry = yaml.safe_load(f)
        except Exception:
            continue

        if not entry or not isinstance(entry, dict):
            continue
        if entry.get("to") != context.tracking_id:
            continue

        expires_at = entry.get("expires_at")
        if expires_at:
            try:
                if datetime.fromisoformat(expires_at) <= now:
                    continue
            except (ValueError, TypeError):
                pass

        owed.append(entry)

    if not owed:
        return HookResult.allow("no owed replies")

    lines = ["You owe replies to the following messages:"]
    for entry in owed:
        msg_id = entry.get("responding_to_msg_id", entry.get("message_id", "???"))
        sender = entry.get("from", "unknown")
        convo_id = entry.get("conversation_id", "???")
        created_at = entry.get("created_at", "")
        ago = _time_ago(created_at) if created_at else "unknown time ago"
        lines.append(f"- {msg_id} from {sender} (conversation {convo_id}) -- sent {ago}")
    lines.append('Use: messaging.py reply --id MSG_ID --from YOUR_ID --content "your reply"')

    reminder_text = "\n".join(lines)
    output = json.dumps({"systemMessage": reminder_text})
    return HookResult.output(output, f"{len(owed)} owed replies")


if __name__ == "__main__":
    sys.exit(run_hook("remind_owed_replies", "Stop", handler))
