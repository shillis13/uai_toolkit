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

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
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


# Commands that may NEVER be sent programmatically via this script. They must
# originate from the user's keyboard (a typed slash command). /self-compact is
# here because its sole job is to MINT a compaction authorization token — a
# session sending it to itself would be authorizing its own compaction.
#
# HONEST SCOPE — this is defense-in-depth, NOT airtight enforcement. This block
# closes the send-a-slash-command path; `disable-model-invocation: true` on the
# self-compact skill closes the Skill-tool path. Together those shut the two easy
# doors. But a session runs as the same user with full file access, so it can
# still hand-forge a <token>.auth file and call /compact directly — no local
# check can stop that (any signal we'd verify is itself a file the session can
# write). That path is a DELIBERATE circumvention of a safety control — a
# reportable violation, not a casual bypass. Real enforcement would have to live
# in the harness (which actually runs /compact), which we don't control.
NEVER_SEND_COMMANDS = {"self-compact"}

# Commands that require a valid one-time authorization_token when sent.
# A token is a <session_dir>/<token>.auth file (issuer + expiry JSON, or a legacy
# zero-byte file), minted by compact_auth.mint from a trusted issuer: the
# user-typed /self-compact path (UserPromptSubmit 07), the auto-threshold Stop
# hook, or the deferred self-compact timer. Validated (existence + TTL) and
# consumed on use. See the HONEST SCOPE note above: the token file is forgeable.
GUARDED_COMMANDS = {"compact"}


def _check_authorization(command, session_dir, authorization_token):
    """Check whether a command may be sent.

    Returns (authorized: bool, error_message: str or None).
    On success for a guarded command, the token file is consumed (deleted).
    """
    # Extract base command (e.g., "/compact --foo" -> "compact")
    base_cmd = command.strip("/").split()[0].lower()

    # Hard block: never sendable programmatically — must be user-typed.
    if base_cmd in NEVER_SEND_COMMANDS:
        return False, (
            f"/{base_cmd} cannot be sent programmatically. It must be typed by "
            f"the user — a session should not initiate its own compaction. "
            f"(Forging a token to route around this is a deliberate safety-control "
            f"violation, not a supported path.)"
        )

    if base_cmd not in GUARDED_COMMANDS:
        return True, None  # not guarded, always allowed

    if not authorization_token:
        return False, f"/{base_cmd} requires an authorization_token. Tokens are issued only by the user typing /self-compact or by the auto-threshold system. Do not fabricate."

    if not session_dir:
        return False, "Cannot validate token: no session directory"

    token_path = Path(session_dir) / f"{authorization_token}.auth"
    # Existence + TTL check via the shared token module — the TTL guards against a
    # stale token from an abandoned deferred-compact trigger authorizing a compaction
    # much later. Legacy zero-byte tokens stay valid-by-existence. Falls back to a
    # plain existence check if the module can't be imported.
    try:
        import sys as _sys
        _d = str(Path(__file__).resolve().parent)
        if _d not in _sys.path:
            _sys.path.insert(0, _d)
        from uai_toolkit.session_mgmt import compact_auth
        valid = compact_auth.is_valid(session_dir, authorization_token)
    except Exception:
        valid = token_path.exists()
    if not valid:
        return False, f"Authorization token not found, expired, or already used. /{base_cmd} requires a valid, unused token."

    # Valid — consume (delete) the token file
    try:
        token_path.unlink()
    except OSError:
        pass

    return True, None


def send_slash_command(
    identifier: str,
    command: str,
    authorization_token: str = "",
) -> dict:
    """Send a slash command to a session.

    Args:
        identifier: prompt:// URI, tracking ID, CLI UUID, terminal name,
            display name, or 'self'.
        command: Slash command to send (e.g. '/compact', '/color cyan').
            Prefixed with '/' if not already present.
        authorization_token: One-time token for guarded commands.
            Token files (<session_dir>/<token>.auth) are created by
            authorizing hook handlers and consumed on use.

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

    # Check authorization for guarded commands
    # Resolve session_dir from the target session
    target_session_dir = None
    target_tid = info.get("tracking_id")
    if target_tid:
        try:
            store = SessionStore()
            session = store.resolve(target_tid)
            if session:
                target_session_dir = session.get("session_dir")
        except Exception:
            pass

    authorized, auth_error = _check_authorization(command, target_session_dir, authorization_token)
    if not authorized:
        result["ok"] = False
        result["error"] = auth_error
        return result

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
    parser.add_argument("--token", default="", help="Authorization token for guarded commands")

    args = parser.parse_args()
    command = " ".join(args.command_parts)

    r = send_slash_command(args.identifier, command, authorization_token=args.token)
    print(json.dumps(r, indent=2))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
