#!/usr/bin/env python3
"""Canonical human-facing identity formatting.

Single source of truth for turning a session/sender identity into the string a
human or AI reader should see: **"DisplayName (tracking_id)"** — display name
first, tracking id in parentheses for disambiguation. Everything that stamps a
"from", a nudge, or any notification should route through `format_identity()`
so we never surface a bare tracking id when a display name is known.

Design notes
------------
* This changes only how identity is *displayed*, never how it is *stored* — the
  message store keeps the raw ``tracking_id`` as the canonical key.
* Identity resolution goes through ``session_store.py`` (the authoritative source
  for session data — see session_mgmt/DESIGN.md). We do not read ``sessions.db``
  directly, and we do not parse the tracking-id format: the store is the arbiter
  of what is a known session. Anything the store doesn't know is treated as
  already human-readable (e.g. a user handle like ``piano_man``) and passed
  through unchanged.
* Pure / read-only / crash-proof: a failed or unavailable lookup degrades to the
  raw identity and never raises. A display helper must never break delivery.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Optional

_SELF_DIR = Path(__file__).resolve().parent
if str(_SELF_DIR) not in sys.path:
    sys.path.insert(0, str(_SELF_DIR))

# Cached SessionStore singleton (per process). SessionStore.__init__ ensures the
# schema idempotently, so we build it at most once and reuse `.get()`.
_store = None
_store_failed = False

# display names are stable within a run; avoid a store hit per nudge/stamp.
_cache: Dict[str, Optional[str]] = {}


def _get_store():
    global _store, _store_failed
    if _store is not None or _store_failed:
        return _store
    try:
        from uai_toolkit.session_mgmt.session_store import SessionStore  # authoritative session data
        _store = SessionStore()
    except Exception:
        _store_failed = True
        _store = None
    return _store


def display_name_for(identity: str) -> Optional[str]:
    """The session's ``display_name`` for *identity*, or None if the store does
    not know it (not a session, unnamed, or store unavailable).

    Crash-proof: any error returns None rather than raising.
    """
    if not identity:
        return None
    if identity in _cache:
        return _cache[identity]
    name: Optional[str] = None
    store = _get_store()
    if store is not None:
        try:
            rec = store.get(identity)
            if rec:
                dn = (rec.get("display_name") or "").strip()
                if dn:
                    name = dn
        except Exception:
            name = None
    _cache[identity] = name
    return name


def format_identity(identity: Optional[str], *, unknown: str = "unknown") -> str:
    """Render *identity* as ``DisplayName (tracking_id)`` for human/AI display.

    - blank / None              -> ``unknown``
    - known session w/ name      -> ``"Name (tracking_id)"``
    - known session, name == id  -> the tracking id alone (avoid ``"id (id)"``)
    - unknown to the store       -> returned as-is (already human-readable, e.g. a
                                    user handle like ``piano_man`` or a system label)
    """
    if not identity or not str(identity).strip():
        return unknown
    identity = str(identity).strip()
    name = display_name_for(identity)
    if name and name != identity:
        return "{} ({})".format(name, identity)
    return identity


if __name__ == "__main__":  # tiny manual smoke: `lib_identity_display.py <identity> ...`
    for arg in sys.argv[1:] or ["unknown"]:
        print("{!r} -> {!r}".format(arg, format_identity(arg)))
