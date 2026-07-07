#!/usr/bin/env python3
"""UserPromptSubmit hook — deliver pending context from the context_to_load/ inbox.

A thin driver: it hands the session's context_to_load/ inbox to the shared
loader (common/lib_context_load.drain) and injects whatever came back as
additionalContext. It has NO type-specific logic — whatever is in the directory
loads, whatever is not, does not. SessionStart uses the same loader.

Stage entries via:
  - stage_context.py / load_context.py (raw files or .ref pointers)
  - a .ref drop into <session_dir>/context_to_load/ (resolved via the knowledge
    loader — see lib_context_load)
  - a direct file/symlink drop
"""

import json
import sys
from pathlib import Path

_COMMON = Path(__file__).resolve().parent.parent / "common"
sys.path.insert(0, str(_COMMON))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common import lib_context_load


def handler(hook_input, context):
    session_dir = context.session_dir
    tracking_id = context.tracking_id
    if not session_dir or not tracking_id:
        return HookResult.skip("no session identity")

    delivered = lib_context_load.drain(session_dir, tracking_id)
    if not delivered:
        return HookResult.skip("nothing pending in context_to_load")

    sections = [
        f"--- Context: {stem} (from {source}) ---\n{content}\n--- End: {stem} ---"
        for stem, content, source in delivered
    ]
    instruction = (
        f"The following {len(sections)} context file(s) were staged for loading "
        f"into this session. This is reference context — absorb it silently.\n\n"
        + "\n\n".join(sections)
    )
    output = json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": instruction,
        }
    })
    names = ", ".join(stem for stem, _, _ in delivered)
    return HookResult.output(output, f"delivered {len(delivered)} context items: {names}")


if __name__ == "__main__":
    sys.exit(run_hook("deliver_pending_context", "UserPromptSubmit", handler))
