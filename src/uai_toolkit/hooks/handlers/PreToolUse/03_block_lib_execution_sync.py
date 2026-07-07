#!/usr/bin/env python3
"""PreToolUse hook — block direct execution of lib_* scripts.

lib_* files are libraries meant to be imported, not executed directly.
Running 'python3 /path/to/lib_something.py' is almost always a mistake.
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

# Match: python3 <any path>/lib_<name>.py
LIB_EXEC_PATTERN = re.compile(r'python3?\s+\S*/lib_\w+\.py')


def handler(hook_input, context):
    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Bash":
        return HookResult.skip("not a Bash call")

    tool_input = hook_input.get("tool_input", {})
    command = tool_input.get("command", "")
    if not command:
        return HookResult.skip("no command")

    if LIB_EXEC_PATTERN.search(command):
        match = LIB_EXEC_PATTERN.search(command)
        return HookResult.block(
            f"You're trying to execute a library file directly: {match.group(0)}\n\n"
            f"lib_* files are internal libraries — not for direct execution or import by AI sessions.\n\n"
            f"Correct approach:\n"
            f"1. Use the MCP tool that wraps this functionality\n"
            f"2. If no MCP tool exists or it doesn't do what's needed, assess whether it should be fixed — notify the user either way\n"
            f"3. Less optimal: use an existing CLI script that wraps the library\n"
            f"4. If that doesn't work either, consider a fix — notify the user either way",
            "lib_ script direct execution"
        )

    return HookResult.allow()


if __name__ == "__main__":
    sys.exit(run_hook("block_lib_execution", "PreToolUse", handler))
