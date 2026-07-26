#!/usr/bin/env python3
"""PostCompact hook — clear the session's cached context-usage % after compaction.

Compaction empties most of the live context, but ``context.used_pct`` in session
state still holds the PRE-compact value (e.g. 86%) until the next Stop refreshes it
(Stop/04_store_session_data). For a turn or two that stale value makes the UAI /
statusline show a misleadingly-full bar right after a hand-off.

We CLEAR the key here (rather than write 0): post-compact usage isn't truly zero —
a brief + system prompt + tools are reloaded — so "unknown until remeasured" is the
honest state. Consumers already handle absence: the UAI session-store maps a missing
key to ``context_percent: null`` (session-store.ts), and the Python readers
(Stop/08_auto_self_compact, session_bounce) guard ``None``. The real value lands on
the next Stop.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult  # noqa: E402
from uai_toolkit.hooks.common.lib_session_state_union import read_union, write_session_state  # session-state bridge (todo_0495)


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")

    state = read_union(context.session_dir, context.tracking_id)
    if "context.used_pct" not in state:
        return HookResult.skip("no context.used_pct to reset")

    prev = state.get("context.used_pct")
    # Targeted delete through the bridge (enrolled → canonical, else legacy).
    if not write_session_state(context.session_dir, context.tracking_id,
                               deletes=["context.used_pct"]):
        return HookResult.error("state write failed")

    return HookResult.allow(f"cleared context.used_pct (was {prev}) post-compact")


if __name__ == "__main__":
    sys.exit(run_hook("reset_context_used_pct", "PostCompact", handler))
