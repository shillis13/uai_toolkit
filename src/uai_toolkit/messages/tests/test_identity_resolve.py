#!/usr/bin/env python3
"""Tests for lib_identity_resolve (Task 5: trusted sender + recipient
resolution for the v2 send contract).

The session_store subprocess helper (`_search_sessions`) is monkeypatched in
every test that needs lookups, so these tests never depend on live sessions.
"""

import sys
from pathlib import Path

import pytest

# Make the parent (messages/) dir importable so the module resolves.
_MESSAGES_DIR = Path(__file__).resolve().parent.parent
if str(_MESSAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_MESSAGES_DIR))

from uai_toolkit.messages import lib_identity_resolve as ir  # noqa: E402


def _rec(tid, **kw):
    """A minimal session-store record, active by default."""
    d = {
        "tracking_id": tid,
        "display_name": tid,
        "status": "running",
        "platform": "claude_cli",
        "archived": 0,
    }
    d.update(kw)
    return d


def _boom(_q):
    raise AssertionError("_search_sessions should not be called here")


# --- resolve_sender ----------------------------------------------------------

def test_sender_from_explicit(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", lambda q: [_rec(q)])
    assert ir.resolve_sender(
        explicit="20260618_120833_64093ef8_cla", env={}
    ) == "20260618_120833_64093ef8_cla"


def test_sender_explicit_beats_env(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", lambda q: [_rec(q)])
    assert ir.resolve_sender(
        explicit="AAA", env={"AI_TRACKING_ID": "BBB"}
    ) == "AAA"


def test_sender_from_env(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", lambda q: [_rec(q)])
    assert ir.resolve_sender(env={"AI_TRACKING_ID": "BBB"}) == "BBB"


def test_sender_system_bypass_uai(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", _boom)
    assert ir.resolve_sender(explicit="uai://system/cron") == "uai://system/cron"


def test_sender_system_bypass_prefix(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", _boom)
    assert ir.resolve_sender(explicit="system:scheduler") == "system:scheduler"


def test_sender_unresolved_when_nothing_trusted(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", lambda q: [])
    with pytest.raises(ir.SenderUnresolved):
        ir.resolve_sender(env={})


def test_sender_unresolved_no_match(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", lambda q: [])
    with pytest.raises(ir.SenderUnresolved):
        ir.resolve_sender(explicit="ghost")


def test_sender_unresolved_when_only_archived(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", lambda q: [_rec(q, archived=1)])
    with pytest.raises(ir.SenderUnresolved):
        ir.resolve_sender(explicit="archived_one")


def test_sender_returns_canonical_tracking_id(monkeypatch):
    # Search may return extra near-matches; the exact tracking-id wins.
    cid = "20260101_000000_abc12345_cla"
    monkeypatch.setattr(
        ir, "_search_sessions",
        lambda q: [_rec("20260101_000000_zzz99999_cla"), _rec(cid)],
    )
    assert ir.resolve_sender(explicit=cid) == cid


# --- resolve_recipient -------------------------------------------------------

def test_recipient_single_session(monkeypatch):
    cid = "20260101_000000_abc12345_cla"
    monkeypatch.setattr(ir, "_search_sessions", lambda q: [_rec(cid)])
    assert ir.resolve_recipient("Noctis") == {
        "kind": "session", "tracking_id": cid,
    }


def test_recipient_zero_notfound(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", lambda q: [])
    with pytest.raises(ir.RecipientNotFound):
        ir.resolve_recipient("ghost")


def test_recipient_multi_ambiguous(monkeypatch):
    matches = [_rec("AAA"), _rec("BBB")]
    monkeypatch.setattr(ir, "_search_sessions", lambda q: matches)
    with pytest.raises(ir.RecipientAmbiguous) as ei:
        ir.resolve_recipient("cla")
    assert len(ei.value.matches) == 2
    assert {m["tracking_id"] for m in ei.value.matches} == {"AAA", "BBB"}


def test_recipient_archived_filtered_then_single(monkeypatch):
    monkeypatch.setattr(
        ir, "_search_sessions",
        lambda q: [_rec("AAA"), _rec("BBB", archived=1)],
    )
    assert ir.resolve_recipient("cla") == {"kind": "session", "tracking_id": "AAA"}


def test_recipient_deleted_filtered(monkeypatch):
    monkeypatch.setattr(
        ir, "_search_sessions",
        lambda q: [_rec("AAA"), _rec("BBB", status="deleted")],
    )
    assert ir.resolve_recipient("cla") == {"kind": "session", "tracking_id": "AAA"}


def test_recipient_user_literal_registered(monkeypatch):
    # Bare `user` resolves to the primary user via the `uai://user` mapping.
    monkeypatch.setattr(ir, "_search_sessions", _boom)
    monkeypatch.setattr(
        ir, "_resolve_uri",
        lambda uri: ["piano_man"] if uri == "uai://user" else [],
    )
    assert ir.resolve_recipient("user") == {"kind": "user", "entity_id": "piano_man"}


def test_recipient_user_uri_registered(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", _boom)
    monkeypatch.setattr(
        ir, "_resolve_uri",
        lambda uri: ["shawn"] if uri == "uai://user/shawn" else [],
    )
    assert ir.resolve_recipient("uai://user/shawn") == {
        "kind": "user", "entity_id": "shawn",
    }


def test_recipient_user_unregistered_raises(monkeypatch):
    # todo_0367: an UNREGISTERED user URI must not resolve (no phantom delivery).
    monkeypatch.setattr(ir, "_search_sessions", _boom)
    monkeypatch.setattr(ir, "_resolve_uri", lambda uri: [])
    with pytest.raises(ir.RecipientNotFound):
        ir.resolve_recipient("uai://user/nobody")
    with pytest.raises(ir.RecipientNotFound):
        ir.resolve_recipient("user")


def test_sender_registered_user_accepted(monkeypatch):
    # A registered user is a trusted first-class sender (reply-from-user path).
    monkeypatch.setattr(ir, "_search_sessions", _boom)
    monkeypatch.setattr(
        ir, "_resolve_uri",
        lambda uri: ["piano_man"] if uri == "uai://user/piano_man" else [],
    )
    assert ir.resolve_sender(explicit="piano_man") == "piano_man"
    assert ir.resolve_sender(explicit="uai://user/piano_man") == "piano_man"


def test_sender_unregistered_user_rejected(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", lambda q: [])
    monkeypatch.setattr(ir, "_resolve_uri", lambda uri: [])
    with pytest.raises(ir.SenderUnresolved):
        ir.resolve_sender(explicit="uai://user/nobody")


def test_recipient_entity_team_deferred(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", _boom)
    assert ir.resolve_recipient("uai://team/comms/message") == {
        "kind": "entity",
        "to_entity": "uai://team/comms/message",
        "deferred_fanout": True,
    }


def test_recipient_entity_project_deferred(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", _boom)
    assert ir.resolve_recipient("uai://project/uai") == {
        "kind": "entity",
        "to_entity": "uai://project/uai",
        "deferred_fanout": True,
    }


def test_recipient_session_uri_parsing(monkeypatch):
    cid = "20260101_000000_abc12345_cla"
    seen = {}

    def fake(q):
        seen["q"] = q
        return [_rec(cid)]

    monkeypatch.setattr(ir, "_search_sessions", fake)
    out = ir.resolve_recipient(f"uai://session/{cid}/message")
    assert out == {"kind": "session", "tracking_id": cid}
    # The session entity id was extracted from the URI before searching.
    assert seen["q"] == cid


def test_recipient_empty_notfound(monkeypatch):
    monkeypatch.setattr(ir, "_search_sessions", _boom)
    with pytest.raises(ir.RecipientNotFound):
        ir.resolve_recipient("   ")
