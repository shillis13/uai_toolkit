#!/usr/bin/env python3
"""UserPromptSubmit hook — record authoritative BUSY activity state.

A prompt was just submitted, so the session is about to respond: record
state=busy + a timestamp to the per-session activity_state.json. The matching
Stop/00_mark_idle_async.py records idle when the turn ends.

This event-driven busy/idle signal is what get_ai_status prefers over the
unreliable terminal-prompt scraping. Dedicated file (not the shared
{tracking_id}_state.json) to avoid racing other state writers.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

# Shared writer for the app-facing session.activity_state field (in the shared
# {tracking_id}_state.json). Imported lazily-via-path from session_mgmt.
_AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
sys.path.insert(0, str(_AI_ROOT / "ai_general" / "scripts" / "session_mgmt"))
try:
    from uai_toolkit.session_mgmt.lib_session_activity import set_activity_state
except Exception:  # pragma: no cover - never break the hook on import trouble
    set_activity_state = None


def set_activity(session_dir, state):
    """Atomically write the activity state to {session_dir}/activity_state.json."""
    path = Path(session_dir) / "activity_state.json"
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"state": state, "at": datetime.now().isoformat()}))
        tmp.rename(path)
        return True
    except OSError:
        return False


def handler(hook_input, context):
    if not context.session_dir:
        return HookResult.skip("no session_dir")
    set_activity(context.session_dir, "busy")
    # Also publish to the app-facing field (responding) so the UAI indicator
    # breathes the moment a turn starts. Change-guarded; best-effort.
    if set_activity_state and context.tracking_id:
        set_activity_state(context.session_dir, context.tracking_id, "responding")
    return HookResult.allow("activity=busy")


if __name__ == "__main__":
    sys.exit(run_hook("mark_busy", "UserPromptSubmit", handler))
