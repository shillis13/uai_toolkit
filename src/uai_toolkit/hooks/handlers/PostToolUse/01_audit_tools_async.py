#!/usr/bin/env python3
"""PostToolUse / AfterTool audit hook for Claude Code, Codex, and Gemini CLI.

Reads hook JSON from stdin, normalizes cross-platform differences, emits
an audit event to the 'tools' category. Exits 0 always (async, fire-and-forget).
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
# ai_general/scripts (for `from uai_toolkit.audit import lib_audit`): honor $AI_SCRIPTS
# override, else derive from location (…/data/hooks/PostToolUse/ -> parents[3]).
sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[3] / "scripts"))

from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

PREVIEW_CAP = 512

_FILE_PATH_TOOLS = {"Edit", "Write", "Read", "NotebookEdit"}
_PATH_TOOLS = {"Grep", "Glob"}

_SUCCESS_PATTERNS = {
    "Edit": (re.compile(r"updated successfully"), re.compile(r"not unique|old_string not found|Error", re.I)),
    "Write": (re.compile(r"created successfully"), re.compile(r"Error", re.I)),
    "Read": (re.compile(r"^\d+\t"), re.compile(r"Error|not found", re.I)),
    "read_file": (re.compile(r"^\d+\t"), re.compile(r"Error|not found", re.I)),
    "Bash": (re.compile(r"Exit code 0\b"), re.compile(r"Exit code [1-9]")),
}
_GENERIC_FAILURE = re.compile(r"\bError\b|\berror\b")


def _extract_file(tool_name, tool_input):
    if tool_name in _FILE_PATH_TOOLS:
        return tool_input.get("file_path")
    if tool_name in _PATH_TOOLS:
        return tool_input.get("path")
    return None


def _detect_success(tool_name, result):
    if not result:
        return None
    patterns = _SUCCESS_PATTERNS.get(tool_name)
    if patterns:
        success_re, failure_re = patterns
        if failure_re.search(result):
            return False
        if success_re.search(result):
            return True
        return None
    if _GENERIC_FAILURE.search(result):
        return False
    return None


def handler(hook_input, context):
    if not hook_input:
        return HookResult.skip("no input")

    tool_name = hook_input.get("tool_name", "unknown")
    tool_input = hook_input.get("tool_input") or {}
    session_id = hook_input.get("session_id")

    event_name = hook_input.get("hook_event_name", "")
    platform_env = os.environ.get("AUDIT_PLATFORM", "")
    if event_name == "AfterTool":
        result_raw = hook_input.get("tool_response", "")
    elif platform_env == "codex":
        result_raw = hook_input.get("tool_response", "")
    else:
        result_raw = hook_input.get("tool_result", "")

    if isinstance(result_raw, (dict, list)):
        result_str = json.dumps(result_raw, ensure_ascii=False)
    elif result_raw is None:
        result_str = ""
    else:
        result_str = str(result_raw)

    input_json = json.dumps(tool_input, ensure_ascii=False)

    try:
        from uai_toolkit.audit import lib_audit
        lib_audit.emit(
            category="tools",
            action=tool_name,
            target={
                "tool": tool_name,
                "file": _extract_file(tool_name, tool_input),
                "session": session_id,
            },
            details={
                "input_preview": input_json[:PREVIEW_CAP],
                "input_length": len(input_json),
                "result_preview": result_str[:PREVIEW_CAP],
                "result_length": len(result_str),
                "success": _detect_success(tool_name, result_str),
            },
        )
    except Exception:
        return HookResult.skip("audit emit failed")

    return HookResult.allow(f"audited {tool_name}")


if __name__ == "__main__":
    sys.exit(run_hook("audit_tools", "PostToolUse", handler))
