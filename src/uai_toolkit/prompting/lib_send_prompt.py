#!/usr/bin/env python3
"""lib_send_prompt.py — Thin adapter for sending prompts to CLI sessions.

Discovers sessions by pattern, checks busy status, and sends text via
session_ops.write_to(). Does NOT modify the MCP server.

Usage (CLI):
    python lib_send_prompt.py send claude-cli "Hello world" --submit
    python lib_send_prompt.py find claude-cli
    python lib_send_prompt.py busy claude-cli
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from pathlib import Path

# ---------------------------------------------------------------------------
# sys.path setup so we can import from session_mgmt
# ---------------------------------------------------------------------------
_SESSION_MGMT_DIR = Path(__file__).resolve().parent.parent / "session_mgmt"
if str(_SESSION_MGMT_DIR) not in sys.path:
    sys.path.insert(0, str(_SESSION_MGMT_DIR))

from uai_toolkit.session_mgmt import session_ops  # noqa: E402
from uai_toolkit.session_mgmt.lib_session_substrate import get_substrate, SubstrateError  # noqa: E402
from uai_toolkit.session_mgmt.session_store import SessionStore  # noqa: E402


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

SESSION_PATTERNS: dict[str, str] = {
    "claude-cli": r"(^(cli_task_|claude_cli_)|_cla$)",
    "codex-cli": r"(^codex_|_cod$)",
    "gemini-cli": r"(^gemini_|_gem$)",
    "grok-cli": r"_grk$",
    "antigravity-cli": r"_agy$",
}

PLATFORM_MAP: dict[str, str] = {
    "claude-cli": "claude_cli",
    "codex-cli": "codex_cli",
    "gemini-cli": "gemini_cli",
    "grok-cli": "grok_cli",
    "antigravity-cli": "antigravity_cli",
}


# ---------------------------------------------------------------------------
# Data
# ---------------------------------------------------------------------------

@dataclass
class SendResult:
    ok: bool
    session: str
    substrate_name: str
    error: str | None = None


# ---------------------------------------------------------------------------
# Core functions
# ---------------------------------------------------------------------------

def find_cli_session(target: str) -> str | None:
    """Find the first session matching the target's naming pattern.

    Returns the session name string, or None if no match.
    """
    pattern_str = SESSION_PATTERNS.get(target)
    if pattern_str is None:
        return None

    pattern = re.compile(pattern_str)
    try:
        sessions = session_ops.list_sessions()
    except (SubstrateError, Exception):
        return None

    for s in sessions:
        if pattern.search(s["name"]):
            return s["name"]
    return None


def is_busy_cli(
    target: str,
    session_name: str | None = None,
    double_check: bool = True,
) -> bool:
    """Check if the CLI session is busy (not idle).

    Reads the terminal status. If double_check is True, reads twice with a
    2-second gap — both must show idle for the session to be considered free.
    Returns True if busy, False if idle.
    """
    if session_name is None:
        session_name = find_cli_session(target)
    if session_name is None:
        return True  # no session found — treat as busy

    platform = PLATFORM_MAP.get(target, "claude_cli")

    try:
        status = session_ops.get_ai_status(session_name, platform)
    except Exception:
        return True  # error reading — treat as busy

    if status.get("state") != "idle":
        return True

    if double_check:
        time.sleep(2)
        try:
            status = session_ops.get_ai_status(session_name, platform)
        except Exception:
            return True
        if status.get("state") != "idle":
            return True

    return False


def send_cli(
    target: str,
    message: str,
    submit: bool = True,
    session_name: str | None = None,
) -> SendResult:
    """Send a message to a CLI session.

    When submit is True:
      - Claude gets Enter pressed twice (confirmation behavior).
      - Other platforms get Enter pressed once.
    When submit is False:
      - Text is typed but no Enter is sent.

    Never raises — returns SendResult with ok=False on error.
    """
    substrate = None
    try:
        substrate = get_substrate()
    except Exception as e:
        return SendResult(
            ok=False, session="", substrate_name="unknown",
            error=f"Failed to get substrate: {e}",
        )

    sub_name = substrate.substrate_name

    # Resolve session name
    if session_name is None:
        session_name = find_cli_session(target)
    if session_name is None:
        return SendResult(
            ok=False, session="", substrate_name=sub_name,
            error=f"No active session found for target '{target}'",
        )

    # Look up per-session substrate override from the store
    session_substrate = None
    try:
        store = SessionStore()
        session_rec = store.resolve(session_name)
        if session_rec:
            session_substrate = session_rec.get("substrate")  # None = use global default
            if session_substrate:
                sub_name = session_substrate
    except Exception:
        pass  # fall back to global substrate

    try:
        if not submit:
            # Type text without Enter
            session_ops.write_to(session_name, message, press_enter=False,
                                 substrate=session_substrate)
        else:
            # Type text without Enter first, then send Enter(s)
            session_ops.write_to(session_name, message, press_enter=False,
                                 substrate=session_substrate)

            # Wait for paste-buffer delivery to complete before sending Enter.
            # Without this delay, Enter can arrive while the terminal is still
            # processing bracketed paste, causing it to be swallowed.
            time.sleep(0.3)

            # Send Enter — Claude needs two presses, others need one
            is_claude = target == "claude-cli" or session_name.startswith(("cli_task_", "claude_cli_"))
            if is_claude:
                session_ops.write_to(session_name, "", press_enter=True,
                                     substrate=session_substrate)
                time.sleep(0.5)
                session_ops.write_to(session_name, "", press_enter=True,
                                     substrate=session_substrate)
            else:
                session_ops.write_to(session_name, "", press_enter=True,
                                     substrate=session_substrate)

        return SendResult(ok=True, session=session_name, substrate_name=sub_name)

    except Exception as e:
        return SendResult(
            ok=False, session=session_name, substrate_name=sub_name,
            error=str(e),
        )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="lib_send_prompt",
        description="Send prompts to CLI sessions.",
    )
    sub = parser.add_subparsers(dest="command")

    # find
    p_find = sub.add_parser("find", help="Find a CLI session by target name")
    p_find.add_argument("target", choices=list(SESSION_PATTERNS))

    # busy
    p_busy = sub.add_parser("busy", help="Check if a CLI session is busy")
    p_busy.add_argument("target", choices=list(SESSION_PATTERNS))
    p_busy.add_argument("--session", help="Explicit session name")
    p_busy.add_argument("--no-double-check", action="store_true",
                        help="Skip the second status check")

    # send
    p_send = sub.add_parser("send", help="Send a message to a CLI session")
    p_send.add_argument("target", choices=list(SESSION_PATTERNS))
    p_send.add_argument("message")
    p_send.add_argument("--submit", action="store_true",
                        help="Press Enter after typing (default: no)")
    p_send.add_argument("--session", help="Explicit session name")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 0

    if args.command == "find":
        name = find_cli_session(args.target)
        print(json.dumps({"session": name, "found": name is not None}))

    elif args.command == "busy":
        busy = is_busy_cli(
            args.target,
            session_name=args.session,
            double_check=not args.no_double_check,
        )
        print(json.dumps({"busy": busy}))

    elif args.command == "send":
        result = send_cli(
            args.target,
            args.message,
            submit=args.submit,
            session_name=args.session,
        )
        print(json.dumps(asdict(result)))
        return 0 if result.ok else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
