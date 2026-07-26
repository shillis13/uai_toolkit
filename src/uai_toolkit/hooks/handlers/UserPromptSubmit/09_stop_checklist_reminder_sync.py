#!/usr/bin/env python3
"""UserPromptSubmit hook — one-line reminder to declare_stop with the checklist.

Phase-in pointer for the declarative stop-gate (todo_0520). The full checklist
lives in the declare_stop tool's own schema; this just reminds the session to
call it at end of turn. Claude-only — the gate enforces claude_cli only, so
there's no point nudging platforms it skips. Sync so the additionalContext is
captured and injected.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

_REMINDER = (
    "End your turn by calling declare_stop (mcp__sessions__declare_stop) and "
    "filling in its `checklist` — a quick yes/no self-review of this turn."
)


def handler(hook_input, context):
    if os.environ.get("AI_SESSION_PLATFORM") != "claude_cli":
        return HookResult.skip("gate is claude-only")
    out = {"hookSpecificOutput": {"hookEventName": "UserPromptSubmit",
                                  "additionalContext": _REMINDER}}
    return HookResult.output(json.dumps(out), "stop-checklist reminder")


if __name__ == "__main__":
    sys.exit(run_hook("stop_checklist_reminder", "UserPromptSubmit", handler))
