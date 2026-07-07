#!/usr/bin/env python3
"""Shared compaction-authorization tokens.

A /compact authorization is a one-time `<token>.auth` file in the session dir.
Trusted issuers: the user-typed /self-compact path (UserPromptSubmit/07) and the
auto-threshold deferred self-compact timer (deferred_self_compact.py). Both mint
via mint() here, so there is ONE trusted path. Tokens carry an issuer + TTL, so a
stale token from an abandoned trigger cannot authorize a compaction much later.

Consumption (delete-on-use) stays in send_slash_command._check_authorization,
which also calls is_valid() here to enforce the TTL before consuming.

Note: the TTL is token expiry, not session-identity time-matching — this module
does not touch session identity or session_store.
"""
from __future__ import annotations

import json
import time
import uuid
from pathlib import Path

DEFAULT_TTL_S = 1800  # 30 minutes — a token unused this long is treated as stale.


def mint(session_dir, issuer: str, ttl_s: int = DEFAULT_TTL_S) -> str | None:
    """Create a one-time <token>.auth file carrying issuer + expiry.

    Returns the token string, or None if session_dir is unusable.
    """
    if not session_dir:
        return None
    token = uuid.uuid4().hex[:16]
    p = Path(session_dir) / f"{token}.auth"
    payload = {"issuer": str(issuer), "created": time.time(), "ttl_s": int(ttl_s)}
    try:
        p.write_text(json.dumps(payload))
    except OSError:
        try:
            p.touch()  # fall back to a zero-byte token (still valid by existence)
        except OSError:
            return None
    return token


def is_valid(session_dir, token: str, now: float | None = None) -> bool:
    """True if <token>.auth exists and is not past its TTL. Does NOT consume.

    Legacy/zero-byte tokens (no JSON payload) are valid by existence — backward
    compatible with tokens minted before this module.
    """
    if not session_dir or not token:
        return False
    p = Path(session_dir) / f"{token}.auth"
    if not p.exists():
        return False
    now = time.time() if now is None else now
    try:
        raw = p.read_text()
        if raw.strip():
            data = json.loads(raw)
            created = data.get("created")
            ttl = data.get("ttl_s")
            if isinstance(created, (int, float)) and isinstance(ttl, (int, float)):
                if now > created + ttl:
                    return False
    except (OSError, ValueError):
        pass  # unreadable / legacy zero-byte -> fall through to valid-by-existence
    return True
