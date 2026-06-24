"""Claude Code hook entry points for file-access anti-clobbering.

Each reads a hook payload as JSON on stdin and acts via the SQLite tracker.
Exposed as console_scripts (see pyproject), so they become real per-OS
launchers — no shebang or interpreter-path assumptions, works on Windows.

Wiring (PreToolUse/PostToolUse) is written by `ai-toolkit init`; these are the
handlers it points at.
"""
from __future__ import annotations

import json
import random
import sys
from pathlib import Path

from ai_toolkit.file_access.tracker import (
    check_conflict,
    log_deny,
    log_read,
    log_write,
    prune,
)

PRUNE_PROBABILITY = 0.01


def _payload() -> dict:
    try:
        return json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return {}


def _fields(data: dict) -> tuple[str, str]:
    session_id = data.get("session_id", "unknown")
    file_path = data.get("tool_input", {}).get("file_path", "")
    return session_id, file_path


def track_read() -> int:
    """PostToolUse[Read] — record the read."""
    session_id, file_path = _fields(_payload())
    if file_path:
        log_read(session_id, file_path)
    print("{}")
    return 0


def track_write() -> int:
    """PostToolUse[Edit|Write] — record the write; occasionally prune."""
    session_id, file_path = _fields(_payload())
    if file_path:
        log_write(session_id, file_path)
    if random.random() < PRUNE_PROBABILITY:
        prune()
    print("{}")
    return 0


def check_before_write() -> int:
    """PreToolUse[Edit|Write] — block if another session wrote since our read.

    Returns 2 (block) on conflict, 0 (allow) otherwise — the exit code the
    hook dispatcher reads.
    """
    session_id, file_path = _fields(_payload())
    if not file_path:
        print("{}")
        return 0

    conflict = check_conflict(session_id, file_path)
    if conflict is None:
        print("{}")
        return 0

    log_deny(session_id, file_path, conflict.conflicting_session)
    short = conflict.conflicting_session[:12]
    result = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"CONFLICT: File '{Path(file_path).name}' was modified by session "
                f"{short}... since you last read it. "
                f"Re-read the file before editing to see what changed."
            ),
        }
    }
    print(json.dumps(result))
    return 2
