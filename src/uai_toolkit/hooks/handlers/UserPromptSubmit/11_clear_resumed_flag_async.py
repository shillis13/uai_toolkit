#!/usr/bin/env python3
"""UserPromptSubmit hook — clear the 'resumed, awaiting prompt' indication.

A Bounce resumes the session IDLE and sets `bounce.resumed_awaiting_prompt` in the
shared {tracking_id}_state.json (see lib_orchestrator._mark_resumed_awaiting_prompt), so
the statusline/footer can show which sessions are resumed-but-unprompted. This event
fires only on a REAL human prompt (injected/meta context is not a UserPromptSubmit), so
the arrival of a prompt is exactly when that indication should lift. Idempotent + async
(state-only, no chat injection).
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")
    sp = Path(context.session_dir) / f"{context.tracking_id}_state.json"
    if not sp.exists():
        return HookResult.skip("no state file")
    try:
        state = json.loads(sp.read_text())
    except (json.JSONDecodeError, OSError):
        return HookResult.skip("state unreadable")
    if not state.get("bounce.resumed_awaiting_prompt"):
        return HookResult.skip("flag not set")
    state.pop("bounce.resumed_awaiting_prompt", None)
    state.pop("bounce.resumed_at", None)
    try:
        sp.write_text(json.dumps(state, indent=2))
    except OSError as e:
        return HookResult.allow(f"could not clear resumed flag: {e}")
    return HookResult.allow("cleared resumed_awaiting_prompt (first prompt after resume)")


if __name__ == "__main__":
    sys.exit(run_hook("clear_resumed_flag", "UserPromptSubmit", handler))
