#!/usr/bin/env python3
"""
hook_prompt_submit.py — Claude Code UserPromptSubmit hook.

Caches context usage data from the statusline file into the session state
store. This runs before every AI response, making context data available
to the AI throughout the turn (e.g., for deciding whether to compact).

Exit 0 always — never block the prompt.

Usage (invoked by Claude Code hook system):
    echo '{"session_id": "..."}' | python3 hook_prompt_submit.py

Env vars:
    AI_TRACKING_ID  — session tracking ID
    AI_SESSION_DIR  — session data directory
"""

from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def _find_statusline(session_dir):
    # type: (str) -> str | None
    """Find the statusline file using discriminated name, then legacy.

    Checks for .jsonl (current v5.3 append-only format) first, then
    .json (snapshot format), both discriminated and legacy names.
    """
    dir_name = os.path.basename(session_dir)
    parts = dir_name.split("_")
    if len(parts) >= 4 and len(parts[2]) == 8:
        uuid8 = parts[2]
    else:
        uuid8 = dir_name[:8]

    # Try in priority order: discriminated .jsonl, legacy .jsonl,
    # discriminated .json, legacy .json
    candidates = [
        os.path.join(session_dir, "statusline.{}.jsonl".format(uuid8)),
        os.path.join(session_dir, "statusline.jsonl"),
        os.path.join(session_dir, "statusline.{}.json".format(uuid8)),
        os.path.join(session_dir, "statusline.json"),
    ]
    for path in candidates:
        if os.path.exists(path):
            return path

    return None


def _read_statusline(filepath):
    # type: (str) -> dict | None
    """Read statusline data. Supports both .jsonl (last line) and .json (single object).

    For .jsonl files: reads the last non-empty line and parses as JSON.
    For .json files: reads the entire file as a single JSON object.
    Returns None on any error.
    """
    try:
        if filepath.endswith(".jsonl"):
            # Read last non-empty line from append-only JSONL
            last_line = None
            with open(filepath, "r") as f:
                for line in f:
                    stripped = line.strip()
                    if stripped:
                        last_line = stripped
            if last_line:
                return json.loads(last_line)
            return None
        else:
            with open(filepath, "r") as f:
                return json.load(f)
    except (json.JSONDecodeError, OSError, IOError, ValueError):
        return None


def _extract_context(statusline):
    # type: (dict) -> dict | None
    """Extract context fields from statusline data.

    Returns dict with used_pct, tokens, cost_usd, or None if data is missing.
    """
    ctx = statusline.get("context_window")
    if not ctx or not isinstance(ctx, dict):
        return None

    used_pct = ctx.get("used_percentage")
    if used_pct is None:
        return None

    # Sum all token types in current_usage
    usage = ctx.get("current_usage", {})
    if not isinstance(usage, dict):
        usage = {}
    total_tokens = 0
    for val in usage.values():
        if isinstance(val, (int, float)) and not isinstance(val, bool):
            total_tokens += val

    # Cost
    cost = statusline.get("cost", {})
    if not isinstance(cost, dict):
        cost = {}
    cost_usd = cost.get("total_cost_usd")

    return {
        "used_pct": used_pct,
        "tokens": total_tokens,
        "cost_usd": cost_usd,
    }


def main():
    # type: () -> None
    """Main hook entry point."""
    try:
        # 1. Read stdin (handle missing/empty gracefully)
        try:
            _stdin = sys.stdin.read()
        except Exception:
            _stdin = ""

        # 2. Get env vars — bail if missing
        tracking_id = os.environ.get("AI_TRACKING_ID")
        session_dir = os.environ.get("AI_SESSION_DIR")

        if not tracking_id or not session_dir:
            return

        if not os.path.isdir(session_dir):
            return

        # 3. Find statusline file
        statusline_path = _find_statusline(session_dir)
        if not statusline_path:
            return

        # 4. Read statusline
        statusline = _read_statusline(statusline_path)
        if not statusline:
            return

        # 5. Extract context data
        context = _extract_context(statusline)
        if not context:
            return

        # 6. Write to session state store
        # Add store.py's directory to sys.path for import
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if script_dir not in sys.path:
            sys.path.insert(0, script_dir)

        from uai_toolkit.session_mgmt.store import SessionStore

        store = SessionStore(
            tracking_id=tracking_id,
            session_data_dir=session_dir,
        )

        # Ensure state file exists (creates with defaults if not)
        store.persist()

        # Write context keys
        now = datetime.now(timezone.utc).astimezone()
        store.set("context.used_pct", context["used_pct"])
        store.set("context.tokens", context["tokens"])
        if context["cost_usd"] is not None:
            store.set("context.cost_usd", context["cost_usd"])
        store.set("context.updated_at", now.isoformat())

    except Exception:
        # Never block the prompt — swallow all errors
        pass


if __name__ == "__main__":
    main()
    sys.exit(0)
