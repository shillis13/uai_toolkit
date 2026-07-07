#!/usr/bin/env python3
"""Tests for lib_reply_rule (Task 4: reply sentinel + conversation derivation
+ reply-target validation). Seeds via the CommsIndex write API."""

import sys
from pathlib import Path

import pytest

# Make the parent (messages/) dir importable so the modules resolve.
_MESSAGES_DIR = Path(__file__).resolve().parent.parent
if str(_MESSAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_MESSAGES_DIR))

from uai_toolkit.messages.comms_index import CommsIndex  # noqa: E402
from uai_toolkit.messages import lib_reply_rule as rr  # noqa: E402


@pytest.fixture
def idx(tmp_path):
    return CommsIndex(db_path=tmp_path / "comms.db")


VALID_ID = "msg_20260622_085514_j1d1gusq"


def _seed_message(idx, *, cid, mid, from_id, to, reply_to=None, subject="Hi",
                  created_at="2026-06-22T08:00:00"):
    """Insert a message + a delivery row for `to` so `to` is a participant."""
    idx.insert_message({
        "id": mid,
        "conversation_id": cid,
        "reply_to": reply_to,
        "subject": subject,
        "from_id": from_id,
        "to_entity": to,
        "delivery": "message",
        "created_at": created_at,
        "body": "body",
    })
    idx.insert_delivery(mid, to)
    return mid


# --- normalize_reply_to ------------------------------------------------------

@pytest.mark.parametrize("raw", [None, "", "   ", "\t\n ", "none", "None",
                                 "NONE", "null", "Null", "NULL"])
def test_normalize_sentinels_return_none(raw):
    assert rr.normalize_reply_to(raw) is None


def test_normalize_valid_id_returned_unchanged():
    assert rr.normalize_reply_to(VALID_ID) == VALID_ID


def test_normalize_valid_id_with_surrounding_whitespace():
    assert rr.normalize_reply_to(f"  {VALID_ID}  ") == VALID_ID


@pytest.mark.parametrize("raw", ["garbage", "msg_bad", "msg_2026_1_x",
                                 "convo_20260622_085514_j1d1gusq", 123, 1.5,
                                 ["msg_x"]])
def test_normalize_ambiguous_raises(raw):
    with pytest.raises(rr.ReplyToAmbiguous):
        rr.normalize_reply_to(raw)


# --- resolve_conversation ----------------------------------------------------

def test_resolve_mints_conversation_on_none_with_subject(idx):
    cid, eff = rr.resolve_conversation(idx, None, "Project Kickoff")
    assert cid.startswith("convo_")
    assert eff == "Project Kickoff"
    convo = idx.get_conversation(cid)
    assert convo["conversation"]["topic"] == "Project Kickoff"


@pytest.mark.parametrize("subject", [None, "", "   "])
def test_resolve_subject_required_when_none(idx, subject):
    with pytest.raises(rr.SubjectRequired):
        rr.resolve_conversation(idx, None, subject)


def test_resolve_inherits_conversation_on_reply(idx):
    cid = idx.create_conversation("Topic")
    _seed_message(idx, cid=cid, mid="msg_20260622_085514_aaaaaaaa",
                  from_id="alice", to="bob")
    got_cid, eff = rr.resolve_conversation(
        idx, "msg_20260622_085514_aaaaaaaa", None)
    assert got_cid == cid
    assert eff is None


def test_resolve_reply_keeps_explicit_subject(idx):
    cid = idx.create_conversation("Topic")
    _seed_message(idx, cid=cid, mid="msg_20260622_085514_bbbbbbbb",
                  from_id="alice", to="bob")
    got_cid, eff = rr.resolve_conversation(
        idx, "msg_20260622_085514_bbbbbbbb", "New Subject")
    assert got_cid == cid
    assert eff == "New Subject"


def test_resolve_reply_missing_parent_raises(idx):
    with pytest.raises(rr.ReplyTargetNotFound):
        rr.resolve_conversation(idx, "msg_20260622_085514_dddddddd", None)


# --- validate_reply_target ---------------------------------------------------

def test_validate_noop_when_reply_to_none(idx):
    assert rr.validate_reply_target(idx, None, "alice") is None


def test_validate_missing_target_raises(idx):
    with pytest.raises(rr.ReplyTargetNotFound):
        rr.validate_reply_target(idx, "msg_20260622_085514_eeeeeeee", "alice")


def test_validate_self_reply_raises(idx):
    mid = "msg_20260622_085514_ffffffff"
    with pytest.raises(rr.ReplyCycle):
        rr.validate_reply_target(idx, mid, "alice", new_message_id=mid)


def test_validate_cycle_raises(idx):
    cid = idx.create_conversation("Topic")
    a = "msg_20260622_085514_a1a1a1a1"
    b = "msg_20260622_085514_b1b1b1b1"
    # a -> b and b -> a form a loop (reply_to has no FK, so order is free).
    _seed_message(idx, cid=cid, mid=a, from_id="alice", to="bob", reply_to=b)
    _seed_message(idx, cid=cid, mid=b, from_id="bob", to="alice", reply_to=a)
    with pytest.raises(rr.ReplyCycle):
        rr.validate_reply_target(idx, a, "alice")


def test_validate_non_participant_raises(idx):
    cid = idx.create_conversation("Topic")
    parent = "msg_20260622_085514_c1c1c1c1"
    _seed_message(idx, cid=cid, mid=parent, from_id="alice", to="bob")
    with pytest.raises(rr.ReplyNotAuthorized):
        rr.validate_reply_target(idx, parent, "carol")


def test_validate_participant_sender_ok(idx):
    cid = idx.create_conversation("Topic")
    parent = "msg_20260622_085514_d1d1d1d1"
    _seed_message(idx, cid=cid, mid=parent, from_id="alice", to="bob")
    # Both the sender (alice) and the recipient (bob) are participants.
    assert rr.validate_reply_target(idx, parent, "alice") is None
    assert rr.validate_reply_target(idx, parent, "bob") is None


def test_validate_orphan_parent_no_conversation_raises(idx):
    # Insert a message whose conversation row is then removed -> orphan.
    cid = idx.create_conversation("Topic")
    parent = "msg_20260622_085514_e1e1e1e1"
    _seed_message(idx, cid=cid, mid=parent, from_id="alice", to="bob")
    import sqlite3
    con = sqlite3.connect(str(idx.db_path))
    con.execute("PRAGMA foreign_keys=OFF")
    con.execute("DELETE FROM conversations WHERE id = ?", (cid,))
    con.commit()
    con.close()
    with pytest.raises(rr.ReplyTargetNotFound):
        rr.validate_reply_target(idx, parent, "alice")


def test_validate_archived_blocked_without_flag(idx):
    cid = idx.create_conversation("Topic", status="archived")
    parent = "msg_20260622_085514_f1f1f1f1"
    _seed_message(idx, cid=cid, mid=parent, from_id="alice", to="bob")
    with pytest.raises(rr.ReplyTargetNotFound):
        rr.validate_reply_target(idx, parent, "alice")


def test_validate_archived_allowed_with_flag(idx):
    cid = idx.create_conversation("Topic", status="archived")
    parent = "msg_20260622_085514_a2a2a2a2"
    _seed_message(idx, cid=cid, mid=parent, from_id="alice", to="bob")
    assert rr.validate_reply_target(
        idx, parent, "alice", allow_archived=True) is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
