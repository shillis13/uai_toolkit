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


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")

    state_path = Path(context.session_dir) / f"{context.tracking_id}_state.json"
    if not state_path.exists():
        return HookResult.skip("no state file")

    try:
        state = json.loads(state_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return HookResult.error(f"state read failed: {e}")

    if "context.used_pct" not in state:
        return HookResult.skip("no context.used_pct to reset")

    prev = state.pop("context.used_pct", None)
    try:
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(state_path)
    except OSError as e:
        return HookResult.error(f"state write failed: {e}")

    return HookResult.allow(f"cleared context.used_pct (was {prev}) post-compact")


if __name__ == "__main__":
    sys.exit(run_hook("reset_context_used_pct", "PostCompact", handler))
