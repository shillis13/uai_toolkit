#!/usr/bin/env python3
"""
send_slash_command.py — Send a slash command to a CLI session's terminal.

Internally constructs and executes a send_prompt call. Accepts:
  - A prompt:// URI (e.g. prompt://claude-cli/Relay)
  - Any session identifier (tracking ID, CLI UUID, terminal name, display name)
  - The special value 'self' (resolved via AI_TRACKING_ID)

Non-URI identifiers are resolved to a session, then a prompt:// URI is built
and routed through send_prompt.py.

Usage:
    send_slash_command.py <identifier_or_uri> <command> [args...]
    send_slash_command.py self /compact
    send_slash_command.py prompt://claude-cli/Relay /color cyan
    send_slash_command.py Relay /rename "New Name"

The command is sent with Enter pressed automatically. If the command does not
start with '/', it is prefixed with '/'.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

_SCRIPT_DIR = Path(__file__).resolve().parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from uai_toolkit.session_mgmt.session_store import SessionStore

_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_SCRIPTS  # noqa: E402
PROMPTING_DIR = AI_SCRIPTS / "prompting"
SEND_PROMPT_SCRIPT = PROMPTING_DIR / "send_prompt.py"

# Map platform codes to send_prompt target names
_PLATFORM_TARGETS = {
    "claude_cli": "claude-cli",
    "codex_cli": "codex-cli",
    "gemini_cli": "gemini-cli",
}


def _resolve_to_endpoint(identifier: str) -> tuple[str | None, dict]:
    """Resolve an identifier to a prompt:// URI endpoint.

    Args:
        identifier: URI, tracking ID, CLI UUID, terminal name, display name, or 'self'.

    Returns:
        (endpoint_uri, info_dict) where info_dict has resolution metadata.
    """
    info: dict = {"identifier": identifier}

    # Already a URI — pass through
    parsed = urlparse(identifier)
    if parsed.scheme and parsed.scheme in ("prompt", "file", "fifo"):
        info["resolved_via"] = "uri_passthrough"
        return identifier, info

    # Resolve 'self'
    if identifier.lower() == "self":
        tracking_id = os.environ.get("AI_TRACKING_ID", "")
        if not tracking_id:
            info["error"] = "Cannot resolve 'self': AI_TRACKING_ID not set"
            return None, info
        identifier = tracking_id
        info["resolved_self"] = tracking_id

    # Resolve via session store
    store = SessionStore()
    session = store.resolve(identifier)
    if not session:
        matches = store.list(filters={"display_name": identifier})
        if not matches:
            matches = store.list(filters={"terminal_session": identifier})
        if len(matches) == 1:
            session = matches[0]
        elif len(matches) > 1:
            info["error"] = f"Ambiguous identifier: {identifier} matches {len(matches)} sessions"
            return None, info

    if not session:
        info["error"] = f"Session not found: {identifier}"
        return None, info

    terminal_session = session.get("terminal_session")
    platform = session.get("platform", "")
    target = _PLATFORM_TARGETS.get(platform)

    info["tracking_id"] = session["tracking_id"]
    info["terminal_session"] = terminal_session
    info["platform"] = platform

    if not terminal_session:
        info["error"] = "No terminal session — cannot send command"
        return None, info

    if not target:
        info["error"] = f"Platform {platform} not supported for send_prompt"
        return None, info

    endpoint = f"prompt://{target}/{terminal_session}?submit=true"
    info["resolved_via"] = "session_store"
    return endpoint, info


# NOTE: the /compact authorization-token guard (NEVER_SEND / GUARDED /
# _check_authorization) was removed 2026-07-14 — self-compaction is now freely
# invocable, so the whole "block the skill -> hook mints a token -> this script
# validates + consumes it" dance is gone. Slash commands (incl. /compact and
# /self-compact) are sent unguarded from here.


def send_slash_command(
    identifier: str,
    command: str,
) -> dict:
    """Send a slash command to a session.

    Args:
        identifier: prompt:// URI, tracking ID, CLI UUID, terminal name,
            display name, or 'self'.
        command: Slash command to send (e.g. '/compact', '/color cyan').
            Prefixed with '/' if not already present.

    Returns:
        Dict with results of the operation.
    """
    result: dict = {"identifier": identifier}

    # Normalize command — ensure it starts with /
    if not command.startswith("/"):
        command = f"/{command}"
    result["command"] = command

    # Resolve identifier to a prompt:// endpoint
    endpoint, info = _resolve_to_endpoint(identifier)
    result.update(info)

    if not endpoint:
        result["ok"] = False
        return result

    result["endpoint"] = endpoint

    # Send directly via session_ops.write_to
    terminal_session = info.get("terminal_session")
    if not terminal_session:
        result["ok"] = False
        result["error"] = "No terminal session to write to"
        return result

    try:
        from uai_toolkit.session_mgmt.session_ops import write_to
        write_to(terminal_session, command, press_enter=True)
        result["ok"] = True
        result["sent"] = True
    except Exception as e:
        result["ok"] = False
        result["error"] = str(e)

    return result


def main() -> int:
    """CLI entry point."""
    import argparse

    parser = argparse.ArgumentParser(
        description="Send a slash command to a CLI session.",
        epilog="Examples:\n"
               "  send_slash_command.py self /compact\n"
               "  send_slash_command.py prompt://claude-cli/Relay /color cyan\n"
               "  send_slash_command.py Relay /rename 'New Name'\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("identifier", help="prompt:// URI, tracking ID, CLI UUID, terminal name, or 'self'")
    parser.add_argument("command_parts", nargs="+", help="Slash command and its arguments")

    args = parser.parse_args()
    command = " ".join(args.command_parts)

    r = send_slash_command(args.identifier, command)
    print(json.dumps(r, indent=2))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
