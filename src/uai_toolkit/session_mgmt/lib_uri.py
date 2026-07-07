"""Centralized URI parsing for session / entity references.

Single source of truth for interpreting references, replacing the divergent
ad-hoc strippers that previously lived in lib_session, session_mgr, session_ops,
session_store, read_jsonl, condense, callback_lib, and lib_identity_resolve.

Forms handled:
  uai://<type>/<id>[/<action>[/...]]   e.g. uai://session/<tid>/notify-batched
  uai://session/<platform>/<tid>       legacy 3-segment shape (get_prompt_area_texts)
  prompt://<target>/<terminal>[?...]   substrate delivery endpoint
  fifo://..., file://..., other://...  substrate schemes (id = last path segment)
  <bare id / display name>             passthrough

Contract (per Codex review reconciliation, 2026-07-03):
  - IDENTITY resolution uses session_id_of(): extract the id, NEVER reject an
    unknown suffix (deep-links like /transcript, /details must pass through).
  - DELIVERY / NOTIFICATION code uses parse_uri().action and validates the action
    in-context (is_known_delivery_action) — rejecting unknown *delivery* actions,
    never becoming a silent immediate send.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional

# A tracking id looks like: 20260703_012505_afa88eb9_cla
_TID_RE = re.compile(r"^\d{8}_\d{6}_[0-9a-f]{8}_[a-z]{2,4}$")
_PLATFORMS = {
    "claude_cli", "codex_cli", "gemini_cli",
    "claude_desktop", "claude_web", "chatgpt_web", "chatgpt_app",
}
# Actions the delivery/notification layer knows how to route.
_DELIVERY_ACTIONS = {
    "message", "prompt", "inbox",
    "notify", "notify-batched", "notify-silent", "notify-digest",
}


class ParsedUri(NamedTuple):
    scheme: Optional[str]        # 'uai' | 'prompt' | 'fifo' | ... | None (bare ref)
    entity_type: Optional[str]  # 'session','user','team','project',... (uai only)
    entity_id: str              # the id: tracking id / display name / terminal / target
    action: Optional[str]       # first segment after id (e.g. 'message','notify-batched')
    raw: str


def parse_uri(ref: str) -> ParsedUri:
    """Parse any reference into (scheme, entity_type, entity_id, action, raw).

    Pure/total: never raises; a bare ref returns entity_id=ref with everything
    else None.
    """
    raw = ref or ""
    ref = raw.strip()
    if "://" not in ref:
        return ParsedUri(None, None, ref, None, raw)

    scheme, rest = ref.split("://", 1)
    scheme = scheme.lower()
    path = rest.split("?", 1)[0].split("#", 1)[0]
    parts = [p for p in path.split("/") if p != ""]

    if scheme == "uai":
        etype = parts[0] if parts else None
        # Legacy uai://session/<platform>/<tid>: disambiguate from <id>/<action>.
        if (etype == "session" and len(parts) >= 3
                and parts[1] in _PLATFORMS and _TID_RE.match(parts[2] or "")):
            action = parts[3] if len(parts) > 3 else None
            return ParsedUri("uai", "session", parts[2], action, raw)
        eid = parts[1] if len(parts) > 1 else ""
        action = parts[2] if len(parts) > 2 else None
        return ParsedUri("uai", etype, eid, action, raw)

    # Substrate schemes (prompt://target/terminal, fifo://..., file://...):
    # the meaningful id is the last path segment (terminal / target ref).
    eid = parts[-1] if parts else ""
    return ParsedUri(scheme, None, eid, None, raw)


def session_id_of(ref: str) -> str:
    """Extract the id from any ref for IDENTITY resolution.

    Never rejects; a bare ref (or one with an unknown suffix) passes through as
    its id. This is the drop-in replacement for the old last-segment strippers,
    and it fixes the bug where uai://session/<id>/message resolved to 'message'.
    """
    p = parse_uri(ref)
    return p.entity_id or ref.strip()


def action_of(ref: str) -> Optional[str]:
    """The action segment of a ref, or None."""
    return parse_uri(ref).action


def is_known_delivery_action(action: Optional[str]) -> bool:
    """True if `action` is a delivery/notification action the router understands.

    Delivery code uses this to reject unknown actions instead of silently
    downgrading to an immediate send. Identity code must NOT call this.
    """
    return action in _DELIVERY_ACTIONS


if __name__ == "__main__":
    # Self-tests: the reconciliation's correctness cases.
    T = [
        # (ref, expect_id, expect_action)
        ("uai://session/20260703_012505_afa88eb9_cla", "20260703_012505_afa88eb9_cla", None),
        ("uai://session/20260703_012505_afa88eb9_cla/message", "20260703_012505_afa88eb9_cla", "message"),
        ("uai://session/20260703_012505_afa88eb9_cla/notify-batched", "20260703_012505_afa88eb9_cla", "notify-batched"),
        ("uai://session/claude_cli/20260703_012505_afa88eb9_cla", "20260703_012505_afa88eb9_cla", None),   # legacy
        ("uai://session/claude_cli/20260703_012505_afa88eb9_cla/inbox", "20260703_012505_afa88eb9_cla", "inbox"),  # legacy+action
        ("uai://user/piano_man", "piano_man", None),
        ("uai://team/relay/message", "relay", "message"),
        ("prompt://claude-cli/some_terminal?submit=true", "some_terminal", None),
        ("bob", "bob", None),
        ("uai://session/x/transcript", "x", "transcript"),  # deep-link action passes through id
    ]
    ok = True
    for ref, eid, act in T:
        p = parse_uri(ref)
        got = (session_id_of(ref), p.action)
        if got != (eid, act):
            ok = False
            print(f"FAIL {ref}\n  expected id={eid!r} action={act!r}\n  got      id={got[0]!r} action={got[1]!r}")
    # action validation
    assert is_known_delivery_action("notify-batched")
    assert is_known_delivery_action("message")
    assert not is_known_delivery_action("transcript")
    assert not is_known_delivery_action(None)
    print("lib_uri self-tests:", "PASS" if ok else "FAIL")
