#!/usr/bin/env python3
"""lib_identity_resolve.py — trusted sender + recipient resolution for the v2
Conversations/Messaging send contract (used by `send_message` / `send_prompt`).

Two responsibilities, both anti-spoof and fail-closed:

  * `resolve_sender(...)` derives the TRUSTED sender identity. The sender is
    never taken from an untrusted "from" field on the wire — it is derived from
    a trusted source and must verify against the session store, OR be a system
    identity. An unresolvable sender on a normal send is a REJECT, never an
    'unknown' fallback (design rule §12.D).

      Precedence for the trusted source (highest first):
        1. `explicit`            — an authenticated / known identity the caller
                                   has already vouched for (e.g. resolved from
                                   the live terminal/PID, not the message body).
        2. `AI_TRACKING_ID`      — read from `env` (defaults to `os.environ`).

      A candidate that is a system identity (`uai://system/<x>` or `system:<x>`)
      is returned as-is — the only path allowed to send without a resolvable
      session. Any other candidate must resolve to a real, non-archived session
      via the store; on success the canonical tracking id is returned, on
      failure `SenderUnresolved` is raised.

  * `resolve_recipient(to)` classifies a recipient address into a delivery
    target. A single live session resolves to that session; zero matches is
    `RecipientNotFound`; more than one is `RecipientAmbiguous` (the caller
    surfaces all candidates — no silent mis-delivery, §5.3). `user` and
    `uai://user/<id>` resolve to the user endpoint. Other entity addresses
    (`uai://team/...`, `uai://project/...`) are stored as a deferred fan-out
    target — the first slice does NOT fan out (0 deliveries).

Recipient lookups shell out to the session store via `_search_sessions`, which
is the single seam tests monkeypatch. Archived / deleted records are filtered
out before any counting happens.

Terms:
  * trusted source   — an identity input the caller has authenticated; never
                       the self-asserted "from" on an inbound message.
  * canonical id      — the `tracking_id` field as stored in the session store.
  * deferred_fanout   — marker that an entity target is recorded but expanded
                        to concrete recipients in a later slice, not now.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Mapping, Optional

_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_ROOT  # noqa: E402


# =============================================================================
# Locating the session store
# =============================================================================

def _ai_root() -> Path:
    root = os.environ.get("AI_ROOT")
    if root:
        return Path(root)
    return AI_ROOT


SESSION_STORE = (
    _ai_root() / "ai_general" / "scripts" / "session_mgmt" / "session_store.py"
)


# =============================================================================
# Typed errors
# =============================================================================

class SenderUnresolved(Exception):
    """No trusted, resolvable sender identity could be derived.

    Raised instead of falling back to any 'unknown' sender (design rule §12.D).
    """

    def __init__(self, candidate: Optional[str] = None,
                 message: Optional[str] = None):
        self.candidate = candidate
        if message is None:
            if candidate:
                message = (
                    f"sender {candidate!r} did not resolve to a live "
                    f"(non-archived) session"
                )
            else:
                message = "no trusted sender identity available"
        super().__init__(message)


class RecipientNotFound(Exception):
    """The recipient address matched zero live sessions / endpoints."""

    def __init__(self, to: Optional[str] = None):
        self.to = to
        super().__init__(f"no recipient matched {to!r}")


class RecipientAmbiguous(Exception):
    """The recipient address matched more than one live session.

    `matches` carries the full candidate list so the caller can surface every
    option rather than silently picking one (§5.3).
    """

    def __init__(self, matches: List[Dict]):
        self.matches = list(matches or [])
        ids = [m.get("tracking_id") for m in self.matches]
        super().__init__(f"recipient is ambiguous; {len(ids)} matches: {ids}")


# =============================================================================
# Session-store seam
# =============================================================================

def _search_sessions(query: str) -> List[Dict]:
    """Run `session_store search <query> --json` and return the records.

    This is the single subprocess seam; tests monkeypatch it to return canned
    match lists. Returns [] on any failure (missing store, bad JSON, non-zero
    exit) — callers treat an empty list as "no match" / unresolved.
    """
    try:
        result = subprocess.run(
            [sys.executable, str(SESSION_STORE), "search", query, "--json"],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def _resolve_uri(uri: str) -> List[str]:
    """Run `session_store resolve-uri <uri>` and return the target id list.

    Second subprocess seam (parallels _search_sessions; tests monkeypatch it).
    The store's uri_mappings is the cross-entity URI authority projects/teams/
    users register into. Returns [] on any failure or an unregistered URI —
    callers treat empty as "unregistered" / RecipientNotFound.
    """
    try:
        result = subprocess.run(
            [sys.executable, str(SESSION_STORE), "resolve-uri", uri],
            capture_output=True, text=True, timeout=15,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if result.returncode != 0:
        return []
    try:
        data = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        return []
    return [str(v) for v in data] if isinstance(data, list) else []


def _is_active(rec: Dict) -> bool:
    """True if a session record is neither archived nor deleted."""
    if rec.get("archived"):
        return False
    if (rec.get("status") or "").lower() in {"deleted", "archived"}:
        return False
    return True


def _active_matches(query: str) -> List[Dict]:
    return [r for r in _search_sessions(query) if _is_active(r)]


# =============================================================================
# uai:// URI parsing
# =============================================================================

def _parse_uai(addr: str) -> Optional[tuple]:
    """Extract `(entity_type, entity_id)` from a `uai://<type>/<id>/...` URI.

    Returns None if `addr` is not a uai:// URI. `entity_id` may be "" for a
    type-only URI (e.g. `uai://user`).
    """
    if not addr.startswith("uai://"):
        return None
    rest = addr[len("uai://"):]
    parts = rest.split("/")
    entity_type = parts[0].strip()
    entity_id = parts[1].strip() if len(parts) > 1 else ""
    return (entity_type, entity_id)


def _is_system_identity(candidate: str) -> bool:
    return (
        candidate.startswith("uai://system/")
        or candidate.startswith("system:")
    )


# =============================================================================
# Sender resolution
# =============================================================================

def resolve_sender(*, explicit: Optional[str] = None,
                    env: Optional[Mapping[str, str]] = None) -> str:
    """Derive the trusted sender identity (a tracking id or a system identity).

    Precedence: `explicit` > `AI_TRACKING_ID` (from `env`, default os.environ).
    System identities pass through unverified; everything else must resolve to
    a live, non-archived session or `SenderUnresolved` is raised. See the module
    docstring for the full contract.
    """
    candidate: Optional[str] = None
    if explicit is not None and str(explicit).strip():
        candidate = str(explicit).strip()
    else:
        source = os.environ if env is None else env
        raw = source.get("AI_TRACKING_ID")
        if raw is not None and str(raw).strip():
            candidate = str(raw).strip()

    if not candidate:
        raise SenderUnresolved(None)

    # System identities are the only senders allowed without a session.
    if _is_system_identity(candidate):
        return candidate

    # A REGISTERED user (users_mgr) is a trusted first-class sender — validated
    # against uri_mappings exactly like a user recipient, so PianoMan can reply
    # from uai://user/<id>. Complements the recipient-side fix (todo_0367); both
    # ends of user identity now go through the same registry.
    user_id = candidate
    if candidate.startswith("uai://user/"):
        user_id = candidate[len("uai://user/"):].strip("/")
    if user_id and _resolve_uri("uai://user/{}".format(user_id)):
        return user_id

    matches = _active_matches(candidate)
    # Anti-spoof: prefer an exact tracking-id match (the trusted source IS a
    # tracking id); otherwise accept a single unambiguous match.
    exact = [m for m in matches if m.get("tracking_id") == candidate]
    if exact:
        return exact[0]["tracking_id"]
    if len(matches) == 1:
        return matches[0]["tracking_id"]

    raise SenderUnresolved(candidate)


# =============================================================================
# Recipient resolution
# =============================================================================

def _resolve_session(query: str) -> Dict:
    matches = _active_matches(query)
    if not matches:
        raise RecipientNotFound(query)
    # An EXACT tracking-id must short-circuit to exactly that session, even when the
    # query also fuzzy-matches sibling sessions by name/group (todo_0530). A tracking
    # id is unique + authoritative; it must never collide into RecipientAmbiguous.
    exact = [m for m in matches if m.get("tracking_id") == query]
    if len(exact) == 1:
        return {"kind": "session", "tracking_id": exact[0]["tracking_id"]}
    if len(matches) > 1:
        raise RecipientAmbiguous(matches)
    return {"kind": "session", "tracking_id": matches[0]["tracking_id"]}


def _resolve_user(uri: str, raw: str) -> Dict:
    """Resolve a user address against the uri_mappings authority.

    A user must be REGISTERED (users_mgr writes a uai://user/<id> mapping). An
    unregistered user URI resolves to nothing → RecipientNotFound, instead of the
    old free pass that silently delivered to a phantom inbox (todo_0367). Mirrors
    _resolve_session's validate-or-raise contract.
    """
    targets = _resolve_uri(uri)
    if not targets:
        raise RecipientNotFound(raw)
    return {"kind": "user", "entity_id": targets[0]}


def resolve_recipient(to: Optional[str]) -> Dict:
    """Classify a recipient address into a delivery target.

    Returns one of:
      * {"kind": "session", "tracking_id": <id>}                — single match
      * {"kind": "user",    "entity_id": <id>}                  — user endpoint
      * {"kind": "entity",  "to_entity": <uri>,
                            "deferred_fanout": True}            — team/project/…
    Raises `RecipientNotFound` (0 matches) or `RecipientAmbiguous` (>1 match)
    for session lookups. See the module docstring for the full contract.
    """
    raw = (to or "").strip()
    if not raw:
        raise RecipientNotFound(to)

    # Literal user endpoint → the bare `uai://user` mapping (the primary user).
    # Validated against uri_mappings, same as any user URI (no free pass).
    if raw == "user":
        return _resolve_user("uai://user", raw)

    parsed = _parse_uai(raw)
    if parsed is not None:
        entity_type, entity_id = parsed
        if entity_type == "user":
            uri = "uai://user/{}".format(entity_id) if entity_id else "uai://user"
            return _resolve_user(uri, raw)
        if entity_type == "session":
            return _resolve_session(entity_id or raw)
        # team / project / any other entity address: record, do not fan out yet.
        return {"kind": "entity", "to_entity": raw, "deferred_fanout": True}

    # Bare id or display name. Try a session first; if nothing matches, fall
    # back to the user registry so a bare REGISTERED-user id (e.g. "piano_man")
    # resolves to the user endpoint — symmetric with resolve_sender's bare-user
    # path (todo_0367). This is why addressing the user by their bare handle
    # previously failed RecipientNotFound: sessions could reply FROM a bare user
    # id but nobody could send/reply TO one. Additive — only reached on a session
    # miss, so it never changes an existing session delivery. RecipientAmbiguous
    # (>1 session) is NOT caught, so it still surfaces.
    try:
        return _resolve_session(raw)
    except RecipientNotFound:
        if _resolve_uri("uai://user/{}".format(raw)):
            return _resolve_user("uai://user/{}".format(raw), raw)
        raise
