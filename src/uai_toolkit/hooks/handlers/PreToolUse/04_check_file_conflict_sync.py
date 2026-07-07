#!/usr/bin/env python3
"""PreToolUse hook — anti-clobbering. Blocks writes if another session modified the file since last read."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
sys.path.insert(0, '$AI_ROOT/ai_general/scripts/file_access')
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.file_access.tracker import check_conflict, log_deny


def handler(hook_input, context):
    tool_name = hook_input.get("tool_name", "")
    if tool_name not in ("Edit", "Write", "apply_patch"):
        return HookResult.skip(f"not a write tool ({tool_name})")

    file_path = hook_input.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return HookResult.skip("no file_path")

    session_id = hook_input.get("session_id", "unknown")
    conflict = check_conflict(session_id, file_path)

    if conflict is None:
        return HookResult.allow()

    short_session = conflict.conflicting_session[:12]
    log_deny(session_id, file_path, conflict.conflicting_session)

    result = json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"CONFLICT: File '{Path(file_path).name}' was modified by session "
                f"{short_session}... since you last read it. "
                f"Re-read the file before editing to see what changed."
            ),
        }
    })
    return HookResult.block(result, f"conflict: {Path(file_path).name} modified by {short_session}")


if __name__ == "__main__":
    sys.exit(run_hook("check_file_conflict", "PreToolUse", handler))
