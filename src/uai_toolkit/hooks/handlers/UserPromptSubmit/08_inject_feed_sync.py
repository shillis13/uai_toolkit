#!/usr/bin/env python3
"""UserPromptSubmit hook — inject the awareness feed.

Reads entries newer than this session's FeedIndex on the `activity` channel,
renders a compact block, injects it as additionalContext, and advances the
FeedIndex. Recency-first, excludes the reader's own entries.

Fails open: any error injects nothing and never blocks the turn.

Design: ai_general/work/todos/todo_0313_awareness_feed_shared_session_activity_channel/
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

_AI_GENERAL = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(_AI_GENERAL / "scripts" / "coordination"))
sys.path.insert(0, str(_AI_GENERAL / "scripts" / "session_mgmt"))

CHANNEL = "activity"
VOLUME = 12


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no tracking_id/session_dir")

    # Everything below fails open — a feed problem must never block the prompt.
    try:
        import feed_lib
        from uai_toolkit.session_mgmt.store import SessionStore

        key = f"feed.index.{CHANNEL}"
        store = SessionStore(tracking_id=context.tracking_id,
                             session_data_dir=context.session_dir)
        try:
            idx = store.get(key)
        except Exception:
            idx = None

        unread, total = feed_lib.read_since(CHANNEL, idx)
        block = feed_lib.render_block(
            unread, total, exclude_session=context.tracking_id, volume=VOLUME)

        # Advance the index to "now" regardless of what was rendered (recency:
        # the reader is presumed current up to total once it has taken a turn).
        try:
            store.set(key, total)
        except Exception:
            pass

        if not block:
            return HookResult.allow("feed: nothing new")

        output = json.dumps({"hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": block,
        }})
        return HookResult.output(output, f"feed: injected {min(len(unread), VOLUME)}")
    except Exception as e:  # noqa: BLE001 — fail open by contract
        return HookResult.skip(f"feed inject failed (open): {e}")


if __name__ == "__main__":
    sys.exit(run_hook("inject_feed", "UserPromptSubmit", handler))
