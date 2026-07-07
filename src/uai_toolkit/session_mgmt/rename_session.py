#!/usr/bin/env python3
"""
rename_session.py — Rename a CLI session and optionally set its color.

Updates display_name in session_store.py (SQLite) and sends /rename (and
optionally /color) to the terminal via session_ops.py so Claude Code's
own UI also reflects the change.

Usage:
    rename_session.py <identifier> <new_name> [--color <color>] [--allow-repeat]

    identifier:     Tracking ID, CLI UUID (prefix OK), or terminal session name.
    new_name:       New display name for the session.
    --color:        Optional color for the session prompt bar (Claude Code only).
    --allow-repeat: Allow reusing a name that has been used before (default: fail on duplicate).

Supported colors:
    red, blue, green, yellow, purple, orange, pink, cyan, default

Examples:
    rename_session.py 20260419_070420_59da2152_cla "My Session"
    rename_session.py 59da2152 "Guidance Test" --color blue
    rename_session.py c15b8645-8ace-466f-b1e5-6bb43c26bc36 Canoodle --color green
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_CLI_DIR = _SCRIPT_DIR.parent / "cli"
for _d in (_SCRIPT_DIR, _CLI_DIR):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from uai_toolkit.session_mgmt.session_store import SessionStore

SUPPORTED_COLORS = ["red", "blue", "green", "yellow", "purple", "orange", "pink", "cyan", "default"]


def rename_session(
    identifier: str,
    new_name: str,
    color: str | None = None,
    allow_repeat: bool = False,
) -> dict:
    """Rename a session in both the store and the CLI app.

    Args:
        identifier: Tracking ID, CLI UUID, or terminal session name.
        new_name: New display name.
        color: Optional color (Claude Code only). One of SUPPORTED_COLORS.
        allow_repeat: If False (default), fail when the name has been used before.

    Returns dict with results of both operations.
    """
    store = SessionStore()
    result: dict = {"identifier": identifier, "new_name": new_name}

    # Validate color
    if color and color not in SUPPORTED_COLORS:
        result["error"] = (
            f"Unsupported color: '{color}'. "
            f"Supported colors: {', '.join(SUPPORTED_COLORS)}"
        )
        result["ok"] = False
        return result

    # Check for duplicate name usage
    if not allow_repeat:
        usage = store.check_name_usage(new_name)
        if usage["total_uses"] > 0 or usage["active_count"] > 0:
            active_msg = (
                f" ({usage['active_count']} currently active)"
                if usage["active_count"] > 0 else ""
            )
            result["error"] = (
                f'Name "{new_name}" has been used {usage["total_uses"]} time(s){active_msg}. '
                f"Use --allow-repeat to proceed anyway."
            )
            result["ok"] = False
            result["name_usage"] = usage
            return result

    # Resolve the session — try exact match first, then prefix search
    session = store.resolve(identifier)
    if not session:
        matches = store.list(filters={"cli_session_id": identifier})
        if not matches:
            matches = store.list(filters={"tracking_id": identifier})
        if len(matches) == 1:
            session = matches[0]
        elif len(matches) > 1:
            result["error"] = f"Ambiguous identifier: {identifier} matches {len(matches)} sessions"
            result["ok"] = False
            return result
    if not session:
        result["error"] = f"Session not found: {identifier}"
        result["ok"] = False
        return result

    tracking_id = session["tracking_id"]
    terminal_session = session.get("terminal_session")
    platform = session.get("platform", "")
    old_name = session.get("display_name")

    result["tracking_id"] = tracking_id
    result["terminal_session"] = terminal_session
    result["platform"] = platform
    result["old_name"] = old_name

    # 1. Update display_name in session store
    try:
        store.update(tracking_id, display_name=new_name)
        result["store_updated"] = True
    except Exception as e:
        result["store_updated"] = False
        result["store_error"] = str(e)

    # 2. Rename the terminal session via substrate and update store
    result["terminal_renamed"] = False
    if terminal_session:
        try:
            session_ops = _SCRIPT_DIR / "session_ops.py"
            proc = subprocess.run(
                [sys.executable, str(session_ops), "rename",
                 terminal_session, new_name],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                result["terminal_renamed"] = True
                result["old_terminal_session"] = terminal_session
                result["new_terminal_session"] = new_name
                # Update terminal_session in store to match
                try:
                    store.update(tracking_id, terminal_session=new_name)
                    result["store_terminal_updated"] = True
                except Exception as e:
                    result["store_terminal_updated"] = False
                    result["store_terminal_error"] = str(e)
            else:
                result["terminal_error"] = proc.stderr.strip() or proc.stdout.strip()
        except subprocess.TimeoutExpired:
            result["terminal_error"] = "Timed out renaming terminal session"
        except Exception as e:
            result["terminal_error"] = str(e)
    else:
        result["terminal_error"] = "No terminal session — cannot rename"

    # Use the current terminal session name for write-to (may have been renamed)
    current_terminal = new_name if result.get("terminal_renamed") else terminal_session

    # 3. Send /rename to the CLI terminal
    result["cli_renamed"] = False
    if current_terminal and platform in ("claude_cli", "codex_cli"):
        try:
            session_ops = _SCRIPT_DIR / "session_ops.py"
            proc = subprocess.run(
                [sys.executable, str(session_ops), "write-to", current_terminal,
                 "--text", f"/rename {new_name}", "--enter", "--delivery", "typed"],
                capture_output=True, text=True, timeout=10,
            )
            if proc.returncode == 0:
                result["cli_renamed"] = True
            else:
                result["cli_error"] = proc.stderr.strip() or proc.stdout.strip()
        except subprocess.TimeoutExpired:
            result["cli_error"] = "Timed out sending /rename to terminal"
        except Exception as e:
            result["cli_error"] = str(e)
    elif not current_terminal:
        result["cli_error"] = "No terminal session — cannot send /rename"
    elif platform not in ("claude_cli", "codex_cli"):
        result["cli_error"] = f"Platform {platform} does not support /rename — store updated only"

    # 4. Send /color if specified (Claude Code only)
    result["color_set"] = False
    if color:
        result["color"] = color
        if platform == "claude_cli" and current_terminal:
            try:
                import time
                time.sleep(0.5)  # Brief pause between /rename and /color
                session_ops = _SCRIPT_DIR / "session_ops.py"
                proc = subprocess.run(
                    [sys.executable, str(session_ops), "write-to", current_terminal,
                     "--text", f"/color {color}", "--enter", "--delivery", "typed"],
                    capture_output=True, text=True, timeout=10,
                )
                if proc.returncode == 0:
                    result["color_set"] = True
                else:
                    result["color_error"] = proc.stderr.strip() or proc.stdout.strip()
            except subprocess.TimeoutExpired:
                result["color_error"] = "Timed out sending /color to terminal"
            except Exception as e:
                result["color_error"] = str(e)
        elif platform != "claude_cli":
            result["color_note"] = f"Color not supported on {platform} — ignored"
        elif not current_terminal:
            result["color_error"] = "No terminal session — cannot send /color"

    result["ok"] = result.get("store_updated", False)
    return result


def main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        description="Rename a CLI session and optionally set its color.",
        epilog=f"Supported colors: {', '.join(SUPPORTED_COLORS)}",
    )
    parser.add_argument("identifier", help="Tracking ID, CLI UUID (prefix OK), or terminal session name")
    parser.add_argument("new_name", nargs="+", help="New display name (multi-word OK without quotes)")
    parser.add_argument(
        "--color", "-c",
        choices=SUPPORTED_COLORS,
        help=f"Set session color (Claude Code only). Choices: {', '.join(SUPPORTED_COLORS)}",
    )
    parser.add_argument(
        "--allow-repeat", action="store_true",
        help="Allow reusing a name that has been used before",
    )

    args = parser.parse_args()
    new_name = " ".join(args.new_name)

    result = rename_session(
        args.identifier, new_name,
        color=args.color,
        allow_repeat=args.allow_repeat,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
