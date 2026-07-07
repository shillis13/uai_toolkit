#!/usr/bin/env python3
"""Hook for PreCompact and PostCompact events — logs compaction and notifies."""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))

# Canonical "DisplayName (tracking_id)" for user-facing notices.
sys.path.insert(0, str(AI_ROOT / "ai_general" / "scripts" / "session_mgmt"))
try:
    from uai_toolkit.session_mgmt.lib_identity_display import format_identity
except Exception:  # pragma: no cover - degrade to raw id; a lookup must not break the hook
    def format_identity(identity, *, unknown="unknown"):
        return identity if identity else unknown


def handler(hook_input, context):
    event = hook_input.get("hook_event_name", "unknown")
    timestamp = datetime.utcnow().isoformat() + "Z"

    log_entry = {
        "timestamp": timestamp,
        "event": event,
        "session_id": os.environ.get("AI_CLI_SESSION_ID", "unknown"),
        "tracking_id": context.tracking_id or "unknown",
        "hook_input": hook_input,
    }

    # Log to session dir
    if context.session_dir:
        log_path = Path(context.session_dir) / "compaction_events.jsonl"
        try:
            with open(log_path, "a") as f:
                f.write(json.dumps(log_entry) + "\n")
        except OSError:
            pass

    # Central compaction log
    central_log = AI_ROOT / "ai_general" / "data" / "audit" / "compaction_events.jsonl"
    try:
        with open(central_log, "a") as f:
            f.write(json.dumps(log_entry) + "\n")
    except OSError:
        pass

    # User notification
    notify_script = os.path.expanduser("~/bin/ai/notifications/send_user_notification.py")
    if os.path.exists(notify_script):
        msg = f"COMPACTION {event}: session {format_identity(context.tracking_id)}"
        try:
            subprocess.run(
                [sys.executable, notify_script, "info", msg],
                timeout=5, capture_output=True,
            )
        except (subprocess.TimeoutExpired, OSError):
            pass

    return HookResult.allow(f"compaction {event} logged")


if __name__ == "__main__":
    # Infer hook type from directory name
    hook_type = Path(__file__).resolve().parent.name  # "PreCompact" or "PostCompact"
    sys.exit(run_hook("compaction", hook_type, handler))
