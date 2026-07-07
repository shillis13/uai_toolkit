#!/usr/bin/env python3
"""PreToolUse hook — block direct tmux/zellij commands.

Sessions must use session_ops.py for all multiplexer interactions.
Direct tmux/zellij calls bypass named server routing, substrate
abstraction, and session identity resolution.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

# Match: tmux or zellij as a command (not as part of a path or variable name)
# Catches: tmux list-sessions, tmux capture-pane, tmux has-session, zellij action, etc.
# Does NOT catch: grep tmux, echo "tmux", variable assignments like TMUX_FOO=
MULTIPLEXER_PATTERN = re.compile(
    r'(?:^|&&|\|\||;|\$\()\s*(?:tmux|zellij)\s',
    re.MULTILINE,
)


def handler(hook_input, context):
    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Bash":
        return HookResult.skip("not a Bash call")

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")
    if not command:
        return HookResult.skip("no command")

    if MULTIPLEXER_PATTERN.search(command):
        return HookResult.block(
            "Direct tmux/zellij commands are blocked.\n\n"
            "Use session_ops.py instead — it handles named tmux servers, "
            "substrate abstraction, and session identity resolution.\n\n"
            "Examples:\n"
            "  session_ops.py list-sessions          # instead of tmux list-sessions\n"
            "  session_ops.py read-terminal <name>    # instead of tmux capture-pane\n"
            "  session_ops.py write-to <name> <text>  # instead of tmux send-keys\n"
            "  session_ops.py session-exists <name>   # instead of tmux has-session\n",
            "direct multiplexer command"
        )

    return HookResult.allow()


if __name__ == "__main__":
    sys.exit(run_hook("block_direct_multiplexer", "PreToolUse", handler))
