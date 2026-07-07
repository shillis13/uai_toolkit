#!/usr/bin/env python3
"""Stop hook — record authoritative IDLE activity state.

When a session finishes its turn and goes to wait for input, Stop fires. We
record state=idle + a timestamp to a small per-session activity_state.json.

This is the event-driven idle signal: Stop = "now idle", the next
UserPromptSubmit = "now busy". get_ai_status prefers this over the unreliable
terminal-prompt (the last-`❯`-has-text) heuristic, which mis-reads long
sessions' custom statuslines/scrollback as occupied.

Written to a DEDICATED file (not the shared {tracking_id}_state.json) so it
never races the concurrent async telemetry handler's read-modify-write.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult


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
    set_activity(context.session_dir, "idle")
    return HookResult.allow("activity=idle")


if __name__ == "__main__":
    sys.exit(run_hook("mark_idle", "Stop", handler))
