#!/usr/bin/env python3
"""
wait_response.py — Poll a terminal session for a regex pattern match.

Captures terminal output at intervals and checks for a pattern.
Returns JSON with match result, elapsed time, and session info.

Usage:
  wait_response.py <session> <pattern> [--timeout 60] [--poll-interval 2] [--lines 50]
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_SCRIPTS  # noqa: E402

# Add session_mgmt to path
SESSION_MGMT_DIR = str(AI_SCRIPTS / "session_mgmt")
if SESSION_MGMT_DIR not in sys.path:
    sys.path.insert(0, SESSION_MGMT_DIR)


def capture_terminal(session: str, lines: int = 50) -> str | None:
    """Capture terminal content via session_ops (substrate-agnostic)."""
    try:
        from uai_toolkit.session_mgmt.session_ops import read_terminal
        output = read_terminal(session)
        if not output:
            return None
        all_lines = output.split("\n")
        if lines and len(all_lines) > lines:
            all_lines = all_lines[-lines:]
        return "\n".join(all_lines)
    except Exception:
        return None


def has_session(session: str) -> bool:
    """Check if terminal session exists."""
    try:
        from uai_toolkit.session_mgmt.session_ops import list_sessions
        sessions = list_sessions()
        return any(s.get("name") == session for s in sessions)
    except Exception:
        return False


def wait_for_pattern(session: str, pattern: str, timeout: int = 60,
                     poll_interval: int = 2, lines: int = 50) -> dict:
    """Poll terminal output for a regex pattern match."""
    if not has_session(session):
        return {"error": f"Session not found: {session}"}

    elapsed = 0
    found = False

    while elapsed < timeout:
        output = capture_terminal(session, lines)
        if output and re.search(pattern, output, re.IGNORECASE):
            found = True
            break
        time.sleep(poll_interval)
        elapsed += poll_interval

    return {
        "found": found,
        "pattern": pattern,
        "elapsed": elapsed,
        "timeout": timeout,
        "session": session,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Poll a terminal session for a regex pattern match",
    )
    parser.add_argument("session", help="Terminal session name")
    parser.add_argument("pattern", help="Regex pattern to wait for")
    parser.add_argument("--timeout", type=int, default=60,
                        help="Timeout in seconds (default: 60)")
    parser.add_argument("--poll-interval", type=int, default=2,
                        help="Seconds between checks (default: 2)")
    parser.add_argument("--lines", type=int, default=50,
                        help="Terminal lines to capture per check (default: 50)")

    args = parser.parse_args()
    result = wait_for_pattern(
        args.session, args.pattern,
        timeout=args.timeout,
        poll_interval=args.poll_interval,
        lines=args.lines,
    )

    print(json.dumps(result, indent=2))
    return 0 if result.get("found") or "error" not in result else 1


if __name__ == "__main__":
    sys.exit(main())
