#!/usr/bin/env python3
"""UserPromptSubmit hook — issue compact authorization token.

Detects when the user invokes a self-compact workflow and issues a one-time
authorization token (a zero-byte <token>.auth file in the session dir) that
the AI then passes to comms_send_slash_command(self, /compact, token=...).
The PreToolUse-adjacent guard in send_slash_command.py validates & consumes it.

IMPORTANT: Claude Code delivers the LITERAL slash-command string to this hook
(e.g. "/self-compact" — 13 chars), NOT the expanded custom-command body. So we
trigger on the literal command, not on markdown content from the .md file.
"""

import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

# Literal command/prefix triggers. The prompt arrives as the raw slash command
# or our >> shorthand — match on the stripped leading token.
COMPACT_TRIGGERS = [
    "/self-compact",
    ">>brief-and-compact",
    ">>compact",
]


def _generate_token(session_dir):
    """Generate a one-time authorization token (zero-byte .auth file)."""
    token = uuid.uuid4().hex[:16]
    token_path = Path(session_dir) / f"{token}.auth"
    token_path.touch()
    return token


def _is_compact_invocation(prompt):
    """True if the prompt is a self-compact invocation (literal command)."""
    stripped = prompt.strip()
    return any(
        stripped == trig or stripped.startswith(trig + " ") or stripped.startswith(trig + "\n")
        for trig in COMPACT_TRIGGERS
    )


def handler(hook_input, context):
    prompt = hook_input.get("prompt", "")
    if not prompt:
        return HookResult.skip("no prompt")

    session_dir = context.session_dir
    if not session_dir:
        return HookResult.skip("no session_dir")

    if not _is_compact_invocation(prompt):
        return HookResult.skip("not a compact invocation")

    token = _generate_token(session_dir)
    instruction = (
        f"Self-compact authorized. Write your session brief following the "
        f"operational_handoff procedure, then trigger compaction with:\n"
        f"  comms_send_slash_command(identifier=\"self\", command=\"/compact\", "
        f"authorization_token=\"{token}\")\n"
        f"This token is one-time-use and required — /compact is blocked without it."
    )
    output = json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": instruction,
        }
    })
    return HookResult.output(output, f"compact authorized, token issued: {token}")


if __name__ == "__main__":
    sys.exit(run_hook("authorize_self_compact", "UserPromptSubmit", handler))
