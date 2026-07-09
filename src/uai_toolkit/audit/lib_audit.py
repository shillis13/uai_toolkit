"""Audit logging for AI communications and operations.

Usage:
    from uai_toolkit.audit import lib_audit as audit
    audit.emit(category="comms", action="session_write",
               target={...}, details={...})
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from uai_toolkit.audit.lib_audit_store import AuditStore

# Resolved lazily from AI_ROOT env var or default
_AI_ROOT: Path | None = None
_store_cache: dict[str, AuditStore] = {}
_PREVIEW_CAP = 512


def _get_ai_root() -> Path:
    global _AI_ROOT
    if _AI_ROOT is None:
        _AI_ROOT = Path(os.environ.get("AI_ROOT",
                        os.path.expanduser("~/AI/ai_root")))
    return _AI_ROOT


def _get_store(category: str) -> AuditStore:
    if category not in _store_cache:
        base = _get_ai_root() / "ai_general" / "data" / "audit" / category
        _store_cache[category] = AuditStore(base_dir=base)
    return _store_cache[category]


def _build_actor(label: str | None = None) -> dict:
    return {
        "tracking_id": os.environ.get("AI_TRACKING_ID"),
        "platform": os.environ.get("AI_SESSION_PLATFORM"),
        "label": label,
    }


def _build_caller() -> dict:
    return {
        "pid": os.getpid(),
        "ppid": os.getppid(),
        "process": Path(sys.argv[0]).name if sys.argv and sys.argv[0] else "unknown",
    }


def emit(
    category: str,
    action: str,
    target: dict[str, Any],
    details: dict[str, Any] | None = None,
    label: str | None = None,
) -> None:
    """Emit an audit event. Never raises."""
    try:
        # Cap text_preview in details
        if details and "text_preview" in details:
            details["text_preview"] = details["text_preview"][:_PREVIEW_CAP]

        now = datetime.now(timezone.utc)
        event = {
            "ts": now.strftime("%Y-%m-%dT%H:%M:%S.") +
                  f"{now.microsecond // 1000:03d}Z",
            "category": category,
            "action": action,
            "actor": _build_actor(label),
            "caller": _build_caller(),
            "target": target,
            "details": details or {},
            "v": 1,
        }
        store = _get_store(category)
        store.append(event)
    except Exception:
        import traceback
        print(f"[audit] emit failed: {traceback.format_exc()}", file=sys.stderr)


def query(category: str, **kwargs) -> list[dict]:
    """Query audit events. Delegates to AuditStore.query()."""
    return _get_store(category).query(**kwargs)


def rebuild_index(category: str) -> int:
    """Rebuild SQLite index from JSONL files."""
    return _get_store(category).rebuild_index()
