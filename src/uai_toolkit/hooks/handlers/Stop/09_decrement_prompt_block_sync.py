#!/usr/bin/env python3
"""Stop hook — decrement a 'turns'-mode prompt block by one completed turn.

When a session is blocked `--turns N`, each *completed* turn counts down one. At 0
the block auto-lifts and any held prompts are released (flush_held), delivered on
the next drain. No-op for indefinite/until blocks or unblocked sessions.

Numbered 09 deliberately — AFTER every blocking Stop handler (02 permission-seek,
05 intent-without-action, …). A blocked turn exits 2 and short-circuits the chain
before reaching 09, so a retried turn is NOT counted: "completed turn" means the
response actually went out. (Also after 01_deliver, so held prompts that this lift
releases ride the *next* turn's drain.)
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common.lib_hook_scripts import get_tracking_id


def handler(hook_input, context):
    tracking_id = get_tracking_id()
    if not tracking_id:
        return HookResult.skip("no tracking_id")
    try:
        ai_root = os.environ.get("AI_ROOT", str(Path.home() / "AI/ai_root"))
        msgs = str(Path(ai_root) / "ai_general" / "scripts" / "messages")
        if msgs not in sys.path:
            sys.path.insert(0, msgs)
        from uai_toolkit.messages import prompt_blocks as pb
    except Exception as e:  # noqa: BLE001 — never let a hook error stall the turn
        return HookResult.skip("prompt_blocks unavailable: {}".format(e))

    rec = pb.decrement_turn(tracking_id)
    if rec is None:
        return HookResult.allow("no active turns-block (or it just lifted)")
    return HookResult.allow("turns-block: {} turn(s) left".format(rec.get("turns_remaining")))


if __name__ == "__main__":
    sys.exit(run_hook("decrement_prompt_block", "Stop", handler))
