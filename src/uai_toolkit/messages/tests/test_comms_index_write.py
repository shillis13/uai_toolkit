#!/usr/bin/env python3
"""Write-API tests for comms_index.CommsIndex (Task 2: write API + obligations)."""

import sqlite3
import sys
from pathlib import Path

import pytest

# Make the parent (messages/) dir importable so `import comms_index` works.
_MESSAGES_DIR = Path(__file__).resolve().parent.parent
if str(_MESSAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_MESSAGES_DIR))

from uai_toolkit.messages.comms_index import CommsIndex  # noqa: E402


@pytest.fixture
def idx(tmp_path):
    return CommsIndex(db_path=tmp_path / "comms.db")


def _row(idx, sql, params=()):
    con = sqlite3.connect(str(idx.db_path))
    try:
        return con.execute(sql, params).fetchone()
    finally:
        con.close()


# --- create_conversation ----------------------------------------------------

def test_create_conversation_inserts_row(idx):
    cid = idx.create_conversation("topic A")
    assert cid.startswith("convo_")
    row = _row(
        idx,
        "SELECT topic, status, created_at, last_activity, linked_work "
        "FROM conversations WHERE id = ?",
        (cid,),
    )
    assert row is not None
    topic, status, created_at, last_activity, linked_work = row
    assert topic == "topic A"
    assert status == "open"
    assert created_at == last_activity
    assert linked_work is None


def test_create_conversation_with_status_and_linked_work(idx):
    cid = idx.create_conversation("t", status="closed", linked_work="todo_0001")
    row = _row(
        idx,
        "SELECT status, linked_work FROM conversations WHERE id = ?",
        (cid,),
    )
    assert row == ("closed", "todo_0001")


# --- insert_message ----------------------------------------------------------

def _make_msg(cid, mid, **over):
    msg = {
        "id": mid,
        "conversation_id": cid,
        "reply_to": None,
        "subject": "Hello",
        "from_id": "alice",
        "to_entity": "bob",
        "delivery": "message",
        "type": "direct",
        "urgency": "normal",
        "response_type": None,
        "ttl_seconds": None,
        "response_required": 0,
        "created_at": "2026-06-23T10:00:00",
        "body": "inline body",
    }
    msg.update(over)
    return msg


def test_insert_message_effective_subject_from_subject(idx):
    cid = idx.create_conversation("t")
    mid = idx.insert_message(_make_msg(cid, "msg_1", subject="My Subject"))
    assert mid == "msg_1"
    row = _row(
        idx,
        "SELECT effective_subject, body, body_ref FROM messages WHERE id = ?",
        (mid,),
    )
    assert row[0] == "My Subject"
    assert row[1] == "inline body"
    assert row[2] is None


def test_insert_message_no_subject_no_reply_gives_null_effective_subject(idx):
    cid = idx.create_conversation("t")
    idx.insert_message(_make_msg(cid, "msg_root", subject=None, reply_to=None))
    row = _row(idx, "SELECT effective_subject FROM messages WHERE id = ?", ("msg_root",))
    assert row[0] is None


def test_reply_inherits_parent_effective_subject(idx):
    cid = idx.create_conversation("t")
    idx.insert_message(_make_msg(cid, "msg_parent", subject="Original Topic"))
    # Reply carries no subject -> inherits parent's effective_subject.
    idx.insert_message(
        _make_msg(cid, "msg_reply", subject=None, reply_to="msg_parent")
    )
    row = _row(idx, "SELECT effective_subject FROM messages WHERE id = ?", ("msg_reply",))
    assert row[0] == "Original Topic"


def test_insert_message_updates_last_activity(idx):
    cid = idx.create_conversation("t")
    before = _row(idx, "SELECT last_activity FROM conversations WHERE id = ?", (cid,))[0]
    idx.insert_message(
        _make_msg(cid, "msg_la", created_at="2026-06-23T12:34:56")
    )
    after = _row(idx, "SELECT last_activity FROM conversations WHERE id = ?", (cid,))[0]
    assert after == "2026-06-23T12:34:56"
    assert after != before


def test_insert_message_with_body_ref(idx):
    cid = idx.create_conversation("t")
    msg = _make_msg(cid, "msg_ref", subject="Ref")
    del msg["body"]
    msg["body_ref"] = "bodyref_123"
    idx.insert_message(msg)
    row = _row(idx, "SELECT body, body_ref FROM messages WHERE id = ?", ("msg_ref",))
    assert row[0] is None
    assert row[1] == "bodyref_123"


# --- deliveries --------------------------------------------------------------

def test_insert_delivery_and_set_status_roundtrip(idx):
    cid = idx.create_conversation("t")
    idx.insert_message(_make_msg(cid, "msg_d"))
    idx.insert_delivery("msg_d", "bob")
    row = _row(
        idx,
        "SELECT status, delivered_at, read_at FROM deliveries "
        "WHERE message_id = ? AND recipient = ?",
        ("msg_d", "bob"),
    )
    assert row == ("queued", None, None)

    idx.set_delivery_status(
        "msg_d", "bob", "read",
        delivered_at="2026-06-23T10:01:00",
        read_at="2026-06-23T10:02:00",
    )
    row = _row(
        idx,
        "SELECT status, delivered_at, read_at, error FROM deliveries "
        "WHERE message_id = ? AND recipient = ?",
        ("msg_d", "bob"),
    )
    assert row == ("read", "2026-06-23T10:01:00", "2026-06-23T10:02:00", None)


def test_insert_delivery_idempotent(idx):
    cid = idx.create_conversation("t")
    idx.insert_message(_make_msg(cid, "msg_d2"))
    idx.insert_delivery("msg_d2", "bob")
    idx.insert_delivery("msg_d2", "bob")  # must not raise
    count = _row(
        idx,
        "SELECT COUNT(*) FROM deliveries WHERE message_id = ? AND recipient = ?",
        ("msg_d2", "bob"),
    )[0]
    assert count == 1


def test_set_delivery_status_error_field(idx):
    cid = idx.create_conversation("t")
    idx.insert_message(_make_msg(cid, "msg_d3"))
    idx.insert_delivery("msg_d3", "bob")
    idx.set_delivery_status("msg_d3", "bob", "failed", error="boom")
    row = _row(
        idx,
        "SELECT status, error FROM deliveries WHERE message_id = ? AND recipient = ?",
        ("msg_d3", "bob"),
    )
    assert row == ("failed", "boom")


# --- obligations -------------------------------------------------------------

def test_open_obligation_then_needs_input_true(idx):
    cid = idx.create_conversation("t")
    idx.insert_message(_make_msg(cid, "msg_o"))
    assert idx.conversation_needs_input(cid) is False
    idx.open_obligation(cid, "msg_o", "bob")
    assert idx.conversation_needs_input(cid) is True


def test_open_obligation_idempotent(idx):
    cid = idx.create_conversation("t")
    idx.insert_message(_make_msg(cid, "msg_o2"))
    idx.open_obligation(cid, "msg_o2", "bob")
    idx.open_obligation(cid, "msg_o2", "bob")  # must not raise
    count = _row(
        idx,
        "SELECT COUNT(*) FROM obligations WHERE message_id = ? AND participant = ?",
        ("msg_o2", "bob"),
    )[0]
    assert count == 1


def test_clear_obligations_clears_and_needs_input_false(idx):
    cid = idx.create_conversation("t")
    idx.insert_message(_make_msg(cid, "msg_o3"))
    idx.open_obligation(cid, "msg_o3", "bob")
    cleared = idx.clear_obligations(cid, "bob", by="bob")
    assert cleared == 1
    assert idx.conversation_needs_input(cid) is False
    row = _row(
        idx,
        "SELECT cleared_at, cleared_by FROM obligations "
        "WHERE message_id = ? AND participant = ?",
        ("msg_o3", "bob"),
    )
    assert row[0] is not None
    assert row[1] == "bob"


def test_clear_obligations_only_affects_named_participant(idx):
    cid = idx.create_conversation("t")
    idx.insert_message(_make_msg(cid, "msg_o4"))
    idx.open_obligation(cid, "msg_o4", "bob")
    idx.open_obligation(cid, "msg_o4", "carol")
    cleared = idx.clear_obligations(cid, "bob", by="bob")
    assert cleared == 1
    # carol's obligation is still open -> conversation still needs input.
    assert idx.conversation_needs_input(cid) is True
    carol = _row(
        idx,
        "SELECT cleared_at FROM obligations WHERE message_id = ? AND participant = ?",
        ("msg_o4", "carol"),
    )
    assert carol[0] is None


def test_clear_obligations_returns_zero_when_none_open(idx):
    cid = idx.create_conversation("t")
    cleared = idx.clear_obligations(cid, "nobody", by="x")
    assert cleared == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
