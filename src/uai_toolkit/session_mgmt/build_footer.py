#!/usr/bin/env python3
"""build_footer.py — Assemble formatted response footers.

Standalone script + library. Gathers data from session state (store),
transcript stats (read_jsonl.py summary), and statusline fallback.

Implements protocol_response_footer v2.0.

Python 3.9 compatible.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Bootstrap: ensure this script's directory is on sys.path
_SCRIPT_DIR = str(Path(__file__).resolve().parent)
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

from uai_toolkit.session_mgmt.store import SessionStore


# ---------------------------------------------------------------------------
# Default format templates
# ---------------------------------------------------------------------------

FOOTER_SEPARATOR = "\u2550\u2550\u2550"

# NOTE (2026-06-12): Ctx Used / Tokens removed from model-visible footers —
# context-anxiety mitigation (premature self-compaction, work avoidance).
# Context monitoring is infrastructure's job (statusline, UAI, threshold
# hooks). See spec_response_footer v1.5. Human-facing statusline is unaffected.
DEFAULT_BRIEF = (
    FOOTER_SEPARATOR + "\n"
    "{timestamp} | {display_name} | {tracking_id}"
    " | Turn:{turns}\n"
    "Tags: {tags}"
)

DEFAULT_FULL = (
    FOOTER_SEPARATOR + "\n"
    "{timestamp} | {display_name} | {tracking_id} | {cli_uuid}\n"
    "{platform} | {project} | Roles:{roles} | Turn:{turns}"
    " | Msgs:{msgs}\n"
    "{_optional_line3}Tags: {tags}"
)

DEFAULT_FULL_EVERY = 5


# ---------------------------------------------------------------------------
# Data gathering helpers
# ---------------------------------------------------------------------------

def _resolve_ai_root():
    # type: () -> str
    """Resolve AI_ROOT via the shared resolver (loaded by file path — immune to the
    utils-package name collision with the common_utils shim)."""
    import importlib.util as _ilu
    _pp = Path(os.environ.get("AI_SCRIPTS") or Path(__file__).resolve().parents[1]) / "utils" / "paths.py"
    _ps = _ilu.spec_from_file_location("ai_paths", str(_pp))
    _m = _ilu.module_from_spec(_ps); _ps.loader.exec_module(_m)
    return str(_m.AI_ROOT)


def _get_transcript_stats(cli_uuid):
    # type: (Optional[str]) -> Dict[str, Any]
    """Call read_jsonl.py summary <uuid> and return parsed JSON.

    Returns dict with user_messages, message_count, etc.
    On any failure, returns empty dict.
    """
    if not cli_uuid or cli_uuid == "NA":
        return {}

    ai_root = _resolve_ai_root()
    script = os.path.join(ai_root, "ai_general", "scripts", "jsonl", "read_jsonl.py")

    try:
        result = subprocess.run(
            [sys.executable, script, "summary", cli_uuid],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if result.returncode != 0:
            return {}
        data = json.loads(result.stdout)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, FileNotFoundError, subprocess.TimeoutExpired,
            OSError, ValueError):
        return {}


def _read_statusline(session_data_dir, tracking_id):
    # type: (str, str) -> Dict[str, Any]
    """Read statusline file directly (fallback when store has no context data).

    Supports both .jsonl (current v5.3 append-only, reads last line) and
    .json (snapshot format). Returns dict with used_pct and tokens keys,
    or empty dict.
    """
    if not session_data_dir or not os.path.isdir(session_data_dir):
        return {}

    # Try discriminated filename first, then legacy. JSONL before JSON.
    parts = os.path.basename(session_data_dir).split("_")
    uuid8 = parts[2] if len(parts) >= 4 and len(parts[2]) == 8 else os.path.basename(session_data_dir)[:8]

    candidates = [
        "statusline.{}.jsonl".format(uuid8),
        "statusline.jsonl",
        "statusline.{}.json".format(uuid8),
        "statusline.json",
    ]

    for name in candidates:
        filepath = os.path.join(session_data_dir, name)
        if os.path.exists(filepath):
            try:
                data = None
                if filepath.endswith(".jsonl"):
                    # Read last non-empty line from append-only JSONL
                    last_line = None
                    with open(filepath, "r") as f:
                        for line in f:
                            stripped = line.strip()
                            if stripped:
                                last_line = stripped
                    if last_line:
                        data = json.loads(last_line)
                else:
                    with open(filepath) as f:
                        data = json.load(f)

                if data:
                    ctx = data.get("context_window", {})
                    # Sum token counts from current_usage (v5.3 format)
                    usage = ctx.get("current_usage", {})
                    tokens = sum(
                        usage.get(k, 0) for k in (
                            "input_tokens", "output_tokens",
                            "cache_creation_input_tokens",
                            "cache_read_input_tokens",
                        )
                    )
                    # Fall back to total_tokens for legacy/snapshot format
                    if not tokens:
                        tokens = ctx.get("total_tokens")
                    return {
                        "used_pct": ctx.get("used_percentage"),
                        "tokens": tokens,
                    }
            except (json.JSONDecodeError, OSError, IOError):
                pass

    return {}


def _derive_project_name(project_dir):
    # type: (Optional[str]) -> Optional[str]
    """Derive project name from AI_PROJECT_DIR (last path component)."""
    if not project_dir:
        return None
    return os.path.basename(project_dir.rstrip("/"))


def _format_optional_fields(docs, mslots, artifacts):
    # type: (Optional[str], Optional[str], Optional[str]) -> str
    """Build the optional portion of line 3 in full footer.

    Only includes fields that have values. Returns empty string or
    'Docs:X | MSlots:Y | Artifacts:Z | ' format.
    """
    parts = []
    if docs is not None:
        parts.append("Docs:{}".format(docs))
    if mslots is not None:
        parts.append("MSlots:{}".format(mslots))
    if artifacts is not None:
        parts.append("Artifacts:{}".format(artifacts))
    if parts:
        return " | ".join(parts) + " | "
    return ""


# ---------------------------------------------------------------------------
# Core footer builder
# ---------------------------------------------------------------------------

def build_footer(tracking_id, tags, mode=None, session_data_dir=None):
    # type: (str, str, Optional[str], Optional[str]) -> str
    """Assemble a formatted response footer.

    Args:
        tracking_id: Session tracking ID.
        tags: Comma-separated tags describing the response content.
        mode: "brief", "full", or None for auto-cadence.
        session_data_dir: Session data directory path. If None, tries SQLite.

    Returns:
        Formatted footer string.
    """
    # --- Resolve session data dir ---
    if not session_data_dir:
        session_data_dir = _resolve_session_dir(tracking_id)

    # --- Read session state ---
    store = SessionStore(tracking_id=tracking_id, session_data_dir=session_data_dir)

    # Fall back to process env vars when store keys aren't seeded yet (pre-Task 7)
    display_name = store.get("session.display_name")
    env_tracking_id = store.get("env.AI_TRACKING_ID") or os.environ.get("AI_TRACKING_ID") or tracking_id
    cli_uuid = store.get("env.AI_CLI_SESSION_ID") or os.environ.get("AI_CLI_SESSION_ID")
    platform = store.get("env.AI_SESSION_PLATFORM") or os.environ.get("AI_SESSION_PLATFORM")
    project_dir = store.get("env.AI_PROJECT_DIR") or os.environ.get("AI_PROJECT_DIR")
    roles = store.get("role")
    ctx_used_pct = store.get("context.used_pct")
    ctx_tokens = store.get("context.tokens")
    docs = store.get("loaded.docs")
    mslots = store.get("loaded.mslots")
    artifacts = store.get("conversation.artifacts")

    # --- Read format config from uai_toolkit.session_mgmt.store ---
    format_brief = store.get("footer.format_brief") or DEFAULT_BRIEF
    format_full = store.get("footer.format_full") or DEFAULT_FULL
    full_every_raw = store.get("footer.full_every")
    full_every = int(full_every_raw) if full_every_raw is not None else DEFAULT_FULL_EVERY

    # --- Get transcript stats ---
    transcript = _get_transcript_stats(cli_uuid)
    turns = transcript.get("user_messages")
    msgs = transcript.get("message_count")

    # --- Statusline fallback for context data ---
    if ctx_used_pct is None or ctx_tokens is None:
        sl = _read_statusline(session_data_dir, tracking_id)
        if ctx_used_pct is None:
            ctx_used_pct = sl.get("used_pct")
        if ctx_tokens is None:
            ctx_tokens = sl.get("tokens")

    # --- Compute derived values ---
    timestamp = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M")

    # Display name fallback: platform name, then "NA"
    if not display_name:
        display_name = platform or "NA"

    # Project name from path
    project = _derive_project_name(project_dir) or "NA"

    # Roles as comma-joined string
    if isinstance(roles, list):
        roles_str = ",".join(roles)
    elif roles:
        roles_str = str(roles)
    else:
        roles_str = "NA"

    # Stringify with NA fallback for required fields
    turns_str = str(turns) if turns is not None else "NA"
    msgs_str = str(msgs) if msgs is not None else "NA"
    ctx_used_str = str(ctx_used_pct) if ctx_used_pct is not None else "NA"
    tokens_str = str(ctx_tokens) if ctx_tokens is not None else "NA"
    cli_uuid_str = str(cli_uuid) if cli_uuid else "NA"
    platform_str = str(platform) if platform else "NA"

    # --- Determine mode ---
    effective_mode = mode  # explicit override
    if not effective_mode:
        # Auto-cadence: full when turns % full_every == 0
        if turns is not None and full_every > 0 and turns % full_every == 0:
            effective_mode = "full"
        else:
            effective_mode = "brief"

    # --- Build optional fields string for full footer ---
    optional_line3 = _format_optional_fields(
        str(docs) if docs is not None else None,
        str(mslots) if mslots is not None else None,
        str(artifacts) if artifacts is not None else None,
    )

    # --- Prompt-block indicator (prepended to tags; fail-open) ---
    try:
        ai_root_pb = _resolve_ai_root()
        msgs_dir = os.path.join(ai_root_pb, "ai_general", "scripts", "messages")
        if msgs_dir not in sys.path:
            sys.path.insert(0, msgs_dir)
        from uai_toolkit.messages import prompt_blocks as _pb  # noqa: WPS433
        _ind = _pb.indicator(env_tracking_id)
        if _ind:
            tags = "{} {}".format(_ind, tags) if tags else _ind
    except Exception:  # noqa: BLE001 — indicator must never break footer rendering
        pass

    # --- Variable map ---
    variables = {
        "timestamp": timestamp,
        "display_name": display_name,
        "tracking_id": env_tracking_id,
        "cli_uuid": cli_uuid_str,
        "platform": platform_str,
        "project": project,
        "roles": roles_str,
        "turns": turns_str,
        "msgs": msgs_str,
        "ctx_used_pct": ctx_used_str,
        "tokens": tokens_str,
        "docs": str(docs) if docs is not None else "NA",
        "mslots": str(mslots) if mslots is not None else "NA",
        "artifacts": str(artifacts) if artifacts is not None else "NA",
        "tags": tags,
        "_optional_line3": optional_line3,
    }

    # --- Format ---
    template = format_full if effective_mode == "full" else format_brief

    # Replace {variable} tokens
    result = template
    for key, value in variables.items():
        result = result.replace("{" + key + "}", str(value))

    return result


def _resolve_session_dir(tracking_id):
    # type: (str) -> Optional[str]
    """Try to resolve session data dir via SQLite lookup."""
    try:
        from uai_toolkit.session_mgmt.session_store import SessionStore as SQLiteStore
        sqlite_store = SQLiteStore()
        row = sqlite_store.resolve(tracking_id)
        if row and row.get("session_dir"):
            return row["session_dir"]
    except Exception:
        pass
    return None


# ---------------------------------------------------------------------------
# CLI entrypoint
# ---------------------------------------------------------------------------

def main():
    # type: () -> None
    parser = argparse.ArgumentParser(
        prog="build_footer.py",
        description="Assemble a formatted response footer.",
    )
    parser.add_argument(
        "tracking_id",
        help="Session tracking ID",
    )
    parser.add_argument(
        "--tags",
        required=True,
        help="Comma-separated tags for the footer",
    )
    parser.add_argument(
        "--mode",
        choices=["brief", "full"],
        default=None,
        help="Footer mode (brief or full). Omit for auto-cadence.",
    )
    parser.add_argument(
        "--data-dir",
        default=None,
        help="Session data directory (bypasses SQLite lookup)",
    )

    args = parser.parse_args()

    result = build_footer(
        tracking_id=args.tracking_id,
        tags=args.tags,
        mode=args.mode,
        session_data_dir=args.data_dir,
    )
    print(result)


if __name__ == "__main__":
    main()
