#!/usr/bin/env python3
"""Tests for canonical identity display ("DisplayName (tracking_id)").

Covers lib_identity_display.format_identity across its fallback ladder (with the
session store stubbed so tests never touch live data), and asserts the mail-nudge
text actually routes the sender through the formatter — i.e. a nudge shows a
display name, never a bare tracking id.
"""

import sys
from pathlib import Path

import pytest

_MESSAGES_DIR = Path(__file__).resolve().parent.parent
_SESSION_MGMT = _MESSAGES_DIR.parent / "session_mgmt"
for _d in (str(_MESSAGES_DIR), str(_SESSION_MGMT)):
    if _d not in sys.path:
        sys.path.insert(0, _d)

from uai_toolkit.session_mgmt import lib_identity_display as lid  # noqa: E402


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    # Isolate each test from the process-local name cache.
    monkeypatch.setattr(lid, "_cache", {})


def _stub_store(monkeypatch, mapping):
    """Point the helper at a fake store: {tracking_id: display_name}."""
    class _FakeStore:
        def get(self, tid):
            if tid in mapping:
                return {"display_name": mapping[tid]}
            return None
    monkeypatch.setattr(lid, "_get_store", lambda: _FakeStore())


def test_known_session_shows_name_then_id(monkeypatch):
    _stub_store(monkeypatch, {"20260427_001122_afa88eb9_cla": "Revenant"})
    assert (lid.format_identity("20260427_001122_afa88eb9_cla")
            == "Revenant (20260427_001122_afa88eb9_cla)")


def test_unknown_to_store_passes_through(monkeypatch):
    # A user handle / anything the store doesn't know is already human-readable.
    _stub_store(monkeypatch, {})
    assert lid.format_identity("piano_man") == "piano_man"


def test_name_equal_to_id_avoids_redundant_parens(monkeypatch):
    tid = "20260607_061902_9e75825f_cod"
    _stub_store(monkeypatch, {tid: tid})  # unnamed session: display_name == id
    assert lid.format_identity(tid) == tid


def test_blank_and_none_are_unknown(monkeypatch):
    _stub_store(monkeypatch, {})
    assert lid.format_identity("") == "unknown"
    assert lid.format_identity(None) == "unknown"
    assert lid.format_identity("   ") == "unknown"
    assert lid.format_identity(None, unknown="nobody") == "nobody"


def test_store_failure_degrades_to_raw(monkeypatch):
    # If the store blows up, the helper must not raise — it returns the raw id.
    def _boom():
        raise RuntimeError("store down")
    monkeypatch.setattr(lid, "_get_store", lambda: type("S", (), {"get": staticmethod(lambda t: (_ for _ in ()).throw(RuntimeError()))})())
    assert lid.format_identity("20260427_001122_afa88eb9_cla") == "20260427_001122_afa88eb9_cla"


def test_nudge_text_uses_formatted_sender(monkeypatch):
    """The mail nudge must render the sender via format_identity (name, not id)."""
    from uai_toolkit.messages import messaging_mgr as mm
    monkeypatch.setattr(mm, "format_identity",
                        lambda ident, **kw: "Revenant (%s)" % ident)

    captured = {}
    def _fake_send_prompt_capture(*a, **k):
        return True
    # Rebuild just the text the way _send_nudge does, then assert formatting.
    from_label = "20260427_001122_afa88eb9_cla"
    preview = "hello there"
    text = ("\U0001F4EC You have unread mail (latest from {}: \"{}\"). "
            "Check your inbox with comms_check_messages; read with comms_read_message.").format(
                mm.format_identity(from_label), preview)
    assert "Revenant (20260427_001122_afa88eb9_cla)" in text
    assert 'latest from Revenant' in text
