#!/usr/bin/env python3
"""UserPromptSubmit hook — deliver queued prompts as additionalContext."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common.lib_hook_scripts import (
    get_tracking_id, get_queue_dir, load_queue_entries,
    filter_ready, compose_context, mark_all_delivered, is_locked,
    drop_blocked_sources,
)


def handler(hook_input, context):
    tracking_id = get_tracking_id()
    if not tracking_id:
        return HookResult.skip("no tracking_id")

    if is_locked(tracking_id):
        return HookResult.skip("session is conversation-locked")

    entries = load_queue_entries(get_queue_dir(tracking_id))
    if not entries:
        return HookResult.skip("no queue entries")

    deliverable = filter_ready(entries, ["pre-prompt", "post-prompt"])
    deliverable = drop_blocked_sources(tracking_id, deliverable)  # hold non-exempt while prompt-blocked
    if not deliverable:
        return HookResult.skip("no deliverable entries")

    composed, included, overflow = compose_context(deliverable)
    if not included:
        return HookResult.skip("no entries composed")

    mark_all_delivered(included)
    output = json.dumps({"hookSpecificOutput": {"additionalContext": composed}})
    return HookResult.output(output, f"delivered {len(included)} entries, {len(overflow)} overflow")


if __name__ == "__main__":
    sys.exit(run_hook("deliver_queued_prompts", "UserPromptSubmit", handler))
