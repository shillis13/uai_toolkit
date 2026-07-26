"""
session_store.py — DEPRECATED shim → session_registry.py.

The authoritative SQLite session-identity store was renamed
session_store.py → session_registry.py (it IS the identity *registry*; "store"
was overloaded — the separate per-session key/value state now lives in
session_key_values.py). This shim keeps existing `from uai_toolkit.session_mgmt.session_store import …`
imports and the `session_store.py` command line working during the grace period.
Scheduled for removal at the session-scripts cutover (2026-07-19).

New code should use:  from session_registry import SessionStore   (and friends)
"""
from __future__ import annotations

from uai_toolkit.session_mgmt.session_registry import *  # noqa: F401,F403  (re-export all public names)

if __name__ == "__main__":
    import sys
    from uai_toolkit.session_mgmt.session_registry import main
    sys.exit(main())
