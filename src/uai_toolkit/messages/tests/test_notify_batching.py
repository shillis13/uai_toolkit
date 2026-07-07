#!/usr/bin/env python3
"""Regression tests for batched notification (Codex-enumerated).

Covers: centralized action-aware URI parsing (lib_uri), the atomic nudge-lease
(notify_lib), notify_recipient result modes across policies (primitives
monkeypatched so tests never touch live sessions), and callback_lib refusing to
silently downgrade a delivery action to a prompt.
"""

import sqlite3
import sys
import time
from pathlib import Path

import pytest

_MESSAGES_DIR = Path(__file__).resolve().parent.parent
_SESSION_MGMT = _MESSAGES_DIR.parent / "session_mgmt"
for _d in (_MESSAGES_DIR, str(_SESSION_MGMT)):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from uai_toolkit.session_mgmt import lib_uri  # noqa: E402
from uai_toolkit.messages import notify_lib  # noqa: E402


# ── lib_uri: action-aware parsing ───────────────────────────────────────────

@pytest.mark.parametrize("ref,eid,action", [
    ("uai://session/20260703_012505_afa88eb9_cla", "20260703_012505_afa88eb9_cla", None),
    ("uai://session/20260703_012505_afa88eb9_cla/message", "20260703_012505_afa88eb9_cla", "message"),
    ("uai://session/20260703_012505_afa88eb9_cla/notify-batched", "20260703_012505_afa88eb9_cla", "notify-batched"),
    ("uai://session/claude_cli/20260703_012505_afa88eb9_cla", "20260703_012505_afa88eb9_cla", None),  # legacy shape
    ("uai://user/piano_man", "piano_man", None),
    ("uai://team/relay/message", "relay", "message"),
    ("prompt://claude-cli/some_terminal?submit=true", "some_terminal", None),
    ("bob", "bob", None),
    ("uai://session/x/transcript", "x", "transcript"),  # deep-link action passes through the id
])
def test_parse_uri(ref, eid, action):
    p = lib_uri.parse_uri(ref)
    assert lib_uri.session_id_of(ref) == eid
    assert p.action == action


def test_known_delivery_action():
    assert lib_uri.is_known_delivery_action("notify-batched")
    assert lib_uri.is_known_delivery_action("message")
    assert not lib_uri.is_known_delivery_action("transcript")
    assert not lib_uri.is_known_delivery_action(None)


# ── notify_lib: the atomic nudge-lease ──────────────────────────────────────

def _clean(recipient):
    conn = sqlite3.connect(str(notify_lib.COMMS_DB))
    conn.execute("DELETE FROM notification_state WHERE recipient=?", (recipient,))
    conn.commit()
    conn.close()


def test_lease_leading_edge_suppression():
    r = "__t_lead_" + str(time.time())
    try:
        grants = [notify_lib._acquire_nudge_lease(r, "batched") for _ in range(5)]
        assert grants == [True, False, False, False, False]
    finally:
        _clean(r)


def test_lease_reopens_after_success_outside_window(monkeypatch):
    r = "__t_reopen_" + str(time.time())
    monkeypatch.setattr(notify_lib, "_window", lambda: 0)  # W=0: never within window
    try:
        assert notify_lib._acquire_nudge_lease(r, "batched") is True
        notify_lib._record_nudge_result(r, "batched", True)
        # With W=0, last_success is immediately outside the window -> new lease.
        assert notify_lib._acquire_nudge_lease(r, "batched") is True
    finally:
        _clean(r)


def test_lease_concurrent_exactly_one():
    """Threaded race: exactly one caller wins the lease (the anti-flood core)."""
    import threading
    r = "__t_conc_" + str(time.time())
    results = []
    lock = threading.Lock()

    def worker():
        got = notify_lib._acquire_nudge_lease(r, "batched")
        with lock:
            results.append(got)

    try:
        threads = [threading.Thread(target=worker) for _ in range(12)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert results.count(True) == 1, results
    finally:
        _clean(r)


# ── notify_recipient: result modes (primitives monkeypatched) ───────────────

class _FakeStore:
    def __init__(self, sess):
        self._sess = sess

    def resolve(self, tid):
        return self._sess


@pytest.fixture
def patched(monkeypatch):
    """Monkeypatch messaging_mgr primitives; return a mutable knobs dict."""
    from uai_toolkit.messages import messaging_mgr as mm
    knobs = {
        "sess": {"tracking_id": "r1", "platform": "claude_cli",
                 "terminal_session": "term1", "session_dir": "/tmp/x"},
        "busy": False, "blocked": False, "notify_user": False,
        "nudge_ok": True, "ref_ok": True,
        "staged": [], "nudged": [], "user_notified": [],
    }
    monkeypatch.setattr(mm, "_load_store", lambda: _FakeStore(knobs["sess"]))
    monkeypatch.setattr(mm, "_stage_inbox_ref",
                        lambda sd, tid: (knobs["staged"].append(tid) or knobs["ref_ok"]))
    monkeypatch.setattr(mm, "_prompt_block_check",
                        lambda tid, s, u=None: {"blocked": knobs["blocked"],
                                                "notify_user": knobs["notify_user"],
                                                "reason": "blk"})
    monkeypatch.setattr(mm, "_recipient_is_busy", lambda target, term: knobs["busy"])
    monkeypatch.setattr(mm, "_send_nudge",
                        lambda p, term, lbl, pv: (knobs["nudged"].append(term) or knobs["nudge_ok"]))
    monkeypatch.setattr(mm, "_notify_user_blocked_interrupt",
                        lambda tid, s, pv, blk: knobs["user_notified"].append(tid))
    monkeypatch.setattr(mm, "_PLATFORM_TARGET", {"claude_cli": "claude-cli"})
    return knobs


def test_not_found():
    from uai_toolkit.messages import messaging_mgr as mm
    r = mm.deliver_to_recipient("__nope__", "s", "hi", policy="immediate")
    assert r["mode"] == "error"


def test_immediate_idle_nudges(patched):
    r = notify_lib.notify_recipient("r1", "s", "hi", policy="immediate")
    assert r["mode"] == "nudge_sent"
    assert patched["staged"] == ["r1"]      # ref ALWAYS staged, even before nudge
    assert patched["nudged"] == ["term1"]


def test_immediate_busy_ref_only(patched):
    patched["busy"] = True
    r = notify_lib.notify_recipient("r1", "s", "hi", policy="immediate")
    assert r["mode"] == "inbox_ref_staged"
    assert patched["staged"] == ["r1"]
    assert patched["nudged"] == []


def test_silent_stages_ref_no_nudge_no_lease(patched):
    r = notify_lib.notify_recipient("r1", "s", "hi", policy="silent")
    assert r["mode"] == "silent"
    assert patched["staged"] == ["r1"]
    assert patched["nudged"] == []


def test_blocked_no_prompt_but_user_notified_on_interrupt(patched):
    patched["blocked"] = True
    patched["notify_user"] = True
    r = notify_lib.notify_recipient("r1", "s", "hi", policy="immediate", urgency="interrupt")
    assert r["mode"] == "blocked"
    assert patched["nudged"] == []           # a blocked recipient is NEVER prompted
    assert patched["staged"] == ["r1"]       # message still discoverable
    assert patched["user_notified"] == ["r1"]  # blocked interrupt -> user notified


def test_nudge_failure_ref_staged(patched):
    patched["nudge_ok"] = False
    r = notify_lib.notify_recipient("r1", "s", "hi", policy="immediate")
    assert r["mode"] == "nudge_failed_ref_staged"
    assert patched["staged"] == ["r1"]       # no storm: ref staged, caller can see it failed


def test_batched_second_within_window_suppressed(patched):
    _clean("r1")
    try:
        r1 = notify_lib.notify_recipient("r1", "s", "hi", policy="batched")
        r2 = notify_lib.notify_recipient("r1", "s", "hi2", policy="batched")
        assert r1["mode"] == "nudge_sent"
        assert r2["mode"] == "batched_suppressed"
        assert patched["staged"] == ["r1", "r1"]  # BOTH messages staged the ref
        assert patched["nudged"] == ["term1"]     # but only ONE nudge fired
    finally:
        _clean("r1")


# ── callback_lib: no silent downgrade of a delivery action ──────────────────

def test_callback_rejects_notify_batched_action():
    cb_dir = str(_MESSAGES_DIR.parent / "callbacks")
    if cb_dir not in sys.path:
        sys.path.insert(0, cb_dir)
    from uai_toolkit.callbacks import callback_lib
    tid = "20260703_012505_afa88eb9_cla"
    # A delivery action must be rejected at the ACTION check (before any session
    # resolution) — never silently resolved to an immediate prompt endpoint.
    with pytest.raises(ValueError) as exc:
        callback_lib.parse_endpoint("uai://session/%s/notify-batched" % tid)
    assert "delivery action" in str(exc.value).lower(), str(exc.value)
