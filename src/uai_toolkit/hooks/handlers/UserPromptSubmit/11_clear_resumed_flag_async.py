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
from uai_toolkit.hooks.common.lib_session_state_union import read_union, write_session_state  # session-state bridge (todo_0495)


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")
    state = read_union(context.session_dir, context.tracking_id)
    if not state.get("bounce.resumed_awaiting_prompt"):
        return HookResult.skip("flag not set")
    # Targeted delete through the bridge (enrolled → canonical, else legacy).
    if not write_session_state(context.session_dir, context.tracking_id,
                               deletes=["bounce.resumed_awaiting_prompt", "bounce.resumed_at"]):
        return HookResult.allow("could not clear resumed flag")
    return HookResult.allow("cleared resumed_awaiting_prompt (first prompt after resume)")


if __name__ == "__main__":
    sys.exit(run_hook("clear_resumed_flag", "UserPromptSubmit", handler))
