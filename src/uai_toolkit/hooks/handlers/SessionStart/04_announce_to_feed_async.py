#!/usr/bin/env python3
"""SessionStart hook — announce this session to the awareness feed (auto-floor event).

Posts a kind=event line when a session starts/resumes/compacts, so the roster
stays current without anyone self-reporting. Async (fire-and-forget); fails open.

Design: ai_general/work/todos/todo_0313_awareness_feed_shared_session_activity_channel/
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "coordination"))


def handler(hook_input, context):
    if not context.tracking_id:
        return HookResult.skip("no tracking_id")
    try:
        from uai_toolkit.coordination import feed_lib
        from uai_toolkit.coordination import feed_identity

        rec = feed_identity.get_record(context.tracking_id)
        if not rec:
            return HookResult.skip("no session record")
        source = (hook_input or {}).get("source") or "startup"
        feed_lib.append(
            session=context.tracking_id,
            name=feed_identity.name_of(rec),
            text=feed_identity.start_text(rec, source),
            kind="event",
        )
        return HookResult.allow(f"feed: announced ({source})")
    except Exception as e:  # noqa: BLE001 — fail open by contract
        return HookResult.skip(f"feed announce failed (open): {e}")


if __name__ == "__main__":
    sys.exit(run_hook("announce_to_feed", "SessionStart", handler))
