"""
store.py — DEPRECATED shim. Kept only for backward compatibility.

The per-session key-value state store moved to **session_key_values.py**, and its
class was renamed **SessionStore → SessionKeyValues** to stop colliding with the
identity store's class of the same name. (This module holds a session's mutable
*variables*; identity lives in session_store.py, soon session_registry.py.)

This shim keeps existing `from uai_toolkit.session_mgmt.store import SessionStore` imports working during the
grace period. It is scheduled for removal at the session-scripts cutover
(2026-07-19). New code should use:

    from uai_toolkit.session_mgmt.session_key_values import SessionKeyValues
"""
from __future__ import annotations

from uai_toolkit.session_mgmt.session_key_values import *  # noqa: F401,F403  (re-export public names)
from uai_toolkit.session_mgmt.session_key_values import SessionKeyValues  # noqa: F401

# Back-compat: this module's class used to be named SessionStore.
SessionStore = SessionKeyValues
