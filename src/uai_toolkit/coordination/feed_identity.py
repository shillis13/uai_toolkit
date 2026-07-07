#!/usr/bin/env python3
"""Awareness feed — session identity helpers for the auto-floor announcements.

Used by the SessionStart announce shim (a session announces itself) and by the
roster seed (backfill all currently-active sessions). Pulls identity from
session_store; never the live terminal.
"""
from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

_SESSION_STORE = Path(__file__).resolve().parents[1] / "session_mgmt" / "session_store.py"
_PLATFORM = {"claude_cli": "Claude", "codex_cli": "Codex", "gemini_cli": "Gemini"}


def _store(*args, timeout=10):
    try:
        out = subprocess.run([sys.executable, str(_SESSION_STORE), *args],
                             capture_output=True, text=True, timeout=timeout)
        if out.returncode == 0 and out.stdout.strip():
            return json.loads(out.stdout)
    except Exception:
        pass
    return None


def active_records() -> list:
    """All currently-active session records."""
    data = _store("list", "--json")
    if not isinstance(data, list):
        return []
    return [r for r in data if r.get("status") == "active"]


def get_record(tracking_id: str):
    """One session record by tracking id."""
    return _store("get", tracking_id, timeout=5)


def name_of(rec: dict) -> str:
    return rec.get("display_name") or rec.get("tracking_id") or "?"


def _short_when(iso: str) -> str:
    if not iso:
        return ""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%m/%d %H:%M")
    except Exception:
        return ""


def _ident_tail(rec: dict) -> str:
    parts = [_PLATFORM.get(rec.get("platform", ""), rec.get("platform", "") or "?")]
    roles = rec.get("roles") or []
    if roles:
        parts.append("roles: " + ", ".join(roles))
    notes = rec.get("notes")
    if notes:
        parts.append(str(notes))
    return "; ".join(parts)


def roster_text(rec: dict) -> str:
    """Seed-time roster line: 'active since 06/11 21:22 — Claude; roles: assistant'."""
    when = _short_when(rec.get("created_at"))
    head = f"active since {when}" if when else "active"
    return f"{head} — {_ident_tail(rec)}"


def start_text(rec: dict, source: str = "startup") -> str:
    """SessionStart line; verb varies by source (startup/resume/compact)."""
    verb = {"startup": "started", "resume": "resumed",
            "compact": "compacted — still here"}.get(source, "started")
    return f"{verb} — {_ident_tail(rec)}"
