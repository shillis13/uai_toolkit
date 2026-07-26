#!/usr/bin/env python3
"""Stop hook — arm the idle-gated auto-bounce when a resume is worth it on CAPACITY.

Runs after 99 (offload). Reads the capacity recommendation (metrics.resume.recommend
= hold/worth_it/urgent, from uai_toolkit.hooks.common.lib_offload_metrics — context pressure x sheddable, NOT
a token->$ cost model) and, for a session that opted in (state `bounce.auto`),
arms/cancels a self-destructing one-shot (deferred_offload_bounce.py) that will
self-bounce during a genuine idle lull IF the recommendation still says bounce. This
closes the lossless loop: Stop/99 offloads (pre-stage) → this realizes it with a
stop+resume when context pressure makes it worthwhile.

OPT-IN: does nothing unless state `bounce.auto` is truthy — so the mere presence
of this hook auto-restarts no one. Touches launchd only on tier transitions.

Non-blocking in spirit: it only arms/cancels a timer; the bounce itself happens
later, idle-gated, in the one-shot.
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common.lib_session_state_union import read_union   # union read: see MCP-set bounce.auto (todo_0495)

# .../ai_general/data/hooks/Stop/this -> parents[3] = ai_general
_BOUNCE = Path(__file__).resolve().parents[3] / "scripts" / "session_bounce"


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")

    # Union read so an MCP-set bounce.auto (which lands in the canonical accessor
    # file) is seen alongside the hook-written metrics.resume in the legacy file
    # (todo_0495). This hook doesn't write state back, so no absorption concern.
    state = read_union(context.session_dir, context.tracking_id)

    if not state.get("bounce.auto"):
        return HookResult.skip("bounce.auto not enabled")

    recommend = (state.get("metrics.resume") or {}).get("recommend")
    if recommend is None:
        return HookResult.skip("no metrics.resume.recommend yet (first Stop after resume backfills it)")

    try:
        if str(_BOUNCE) not in sys.path:
            sys.path.insert(0, str(_BOUNCE))
        from uai_toolkit.session_bounce import deferred_offload_bounce as dob
        status = dob.reconcile_from_stop(context.session_dir, context.tracking_id, recommend)
    except Exception as e:
        return HookResult.allow(f"auto_bounce reconcile error: {e}")

    return HookResult.allow(status)


if __name__ == "__main__":
    sys.exit(run_hook("auto_bounce", "Stop", handler))
