#!/usr/bin/env python3
"""Tests for backfill_conversations.py (Task 8).

Build a fixture tree of on-disk YAML messages (inbox / sent / archive /
broadcasts) plus a prompt queue, point a throwaway CommsIndex at a tmp db,
and assert the backfill derives conversations, reply chains, deliveries,
obligations, dedup, the shared-conversation_id repair warning, prompt folding,
idempotency and dry-run-writes-nothing.
"""

import sqlite3
import sys
from pathlib import Path

import pytest
import yaml

# Make the parent (messages/) dir importable so `import backfill_conversations`
# and `import comms_index` work.
_MESSAGES_DIR = Path(__file__).resolve().parent.parent
if str(_MESSAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_MESSAGES_DIR))

from uai_toolkit.messages.comms_index import CommsIndex  # noqa: E402
import backfill_conversations as bc  # noqa: E402


# --------------------------------------------------------------------------- #
# Fixture-tree helpers
# --------------------------------------------------------------------------- #

def _write_msg(root: Path, box: str, owner: str, msg: dict) -> Path:
    """Write a message YAML under <root>/<box>/<owner>/<id>.yml."""
    d = root / box / owner
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{msg['id']}.yml"
    with p.open("w") as f:
        yaml.safe_dump(msg, f)
    return p


def _write_prompt(root: Path, owner: str, q: dict) -> Path:
    d = root / "prompts_inbox" / owner
    d.mkdir(parents=True, exist_ok=True)
    p = d / f"{q['id']}.yml"
    with p.open("w") as f:
        yaml.safe_dump(q, f)
    return p


def _msg(mid, frm, to, **over):
    m = {
        "id": mid,
        "type": "direct",
        "urgency": "normal",
        "response_type": "reply",
        "from": frm,
        "to": to,
        "created_at": "2026-06-23T10:00:00",
        "ttl_seconds": None,
        "replying_to": None,
        "conversation_id": None,
        "subject": None,
        "response_required": False,
        "content": f"content of {mid}",
        "body_file": None,
        "read_by": [],
        "acknowledgments": [],
    }
    m.update(over)
    return m


@pytest.fixture
def tree(tmp_path):
    """Returns (comms_root, messages_root)."""
    comms = tmp_path / "ai_comms"
    (comms / "messages").mkdir(parents=True, exist_ok=True)
    return comms


@pytest.fixture
def idx(tmp_path):
    return CommsIndex(db_path=tmp_path / "comms.db")


def _count(idx, table):
    con = sqlite3.connect(str(idx.db_path))
    try:
        return con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    finally:
        con.close()


def _run(idx, comms, **kw):
    bf = bc.Backfiller(comms_root=comms, index=idx)
    return bf.run(**kw)


# --------------------------------------------------------------------------- #
# Tests
# --------------------------------------------------------------------------- #

def test_root_mints_conversation_topic_from_subject(tree, idx):
    _write_msg(tree, "messages/inbox", "bob",
               _msg("msg_a", "alice", "bob", subject="Hello there"))
    summary = _run(idx, tree)
    assert summary["conversations_created"] == 1
    assert summary["messages_inserted"] == 1
    m = idx.get_message("msg_a")
    convo = idx.get_conversation(m["conversation_id"])
    assert convo["conversation"]["topic"] == "Hello there"


def test_root_topic_placeholder_from_content_when_no_subject(tree, idx):
    _write_msg(tree, "messages/inbox", "bob",
               _msg("msg_nosub", "alice", "bob", subject=None,
                    content="this is the body that becomes the topic"))
    _run(idx, tree)
    m = idx.get_message("msg_nosub")
    topic = idx.get_conversation(m["conversation_id"])["conversation"]["topic"]
    assert topic.startswith("this is the body")


def test_reply_chain_joins_parent_conversation(tree, idx):
    _write_msg(tree, "messages/inbox", "bob",
               _msg("msg_root", "alice", "bob", subject="Topic"))
    _write_msg(tree, "messages/inbox", "alice",
               _msg("msg_r1", "bob", "alice", replying_to="msg_root",
                    created_at="2026-06-23T10:01:00"))
    _write_msg(tree, "messages/inbox", "bob",
               _msg("msg_r2", "alice", "bob", replying_to="msg_r1",
                    created_at="2026-06-23T10:02:00"))
    summary = _run(idx, tree)
    assert summary["conversations_created"] == 1
    assert summary["messages_inserted"] == 3
    c0 = idx.get_message("msg_root")["conversation_id"]
    assert idx.get_message("msg_r1")["conversation_id"] == c0
    assert idx.get_message("msg_r2")["conversation_id"] == c0
    # Reply inherits parent's effective_subject.
    assert idx.get_message("msg_r2")["effective_subject"] == "Topic"


def test_reply_inserted_after_parent_regardless_of_scan_order(tree, idx):
    # Reply written/scanned first, parent second -> forward-ref handling.
    _write_msg(tree, "messages/inbox", "alice",
               _msg("zzz_reply", "bob", "alice", replying_to="aaa_root",
                    created_at="2026-06-23T10:05:00"))
    _write_msg(tree, "messages/inbox", "bob",
               _msg("aaa_root", "alice", "bob", subject="Root",
                    created_at="2026-06-23T10:00:00"))
    summary = _run(idx, tree)
    assert summary["conversations_created"] == 1
    assert summary["messages_inserted"] == 2
    assert (idx.get_message("zzz_reply")["conversation_id"]
            == idx.get_message("aaa_root")["conversation_id"])


def test_shared_conversation_id_unlinked_roots_merge_with_warning(tree, idx):
    _write_msg(tree, "messages/inbox", "bob",
               _msg("msg_x", "alice", "bob", conversation_id="shared_cid",
                    created_at="2026-06-23T10:00:00"))
    _write_msg(tree, "messages/inbox", "bob",
               _msg("msg_y", "carol", "bob", conversation_id="shared_cid",
                    created_at="2026-06-23T10:10:00"))
    summary = _run(idx, tree)
    assert summary["conversations_created"] == 1
    cx = idx.get_message("msg_x")["conversation_id"]
    cy = idx.get_message("msg_y")["conversation_id"]
    assert cx == cy
    convo = idx.get_conversation(cx)["conversation"]
    assert convo["root_count"] > 1
    assert any("shared_cid" in w for w in summary["warnings"])


def test_hardlink_duplicate_by_id_collapsed(tree, idx):
    # Same id present in both inbox (recipient) and sent (sender) dirs.
    m = _msg("msg_dup", "alice", "bob")
    _write_msg(tree, "messages/inbox", "bob", m)
    _write_msg(tree, "messages/sent", "alice", m)
    summary = _run(idx, tree)
    assert summary["messages_inserted"] == 1
    assert _count(idx, "messages") == 1


def test_near_identical_different_ids_deduped(tree, idx):
    base = dict(from_="alice")
    _write_msg(tree, "messages/inbox", "bob",
               _msg("msg_id1", "alice", "bob", content="identical text"))
    _write_msg(tree, "messages/inbox", "bob",
               _msg("msg_id2", "alice", "bob", content="identical text"))
    summary = _run(idx, tree)
    assert summary["messages_inserted"] == 1


def test_archived_copy_gets_archived_delivery(tree, idx):
    _write_msg(tree, "messages/archive", "bob",
               _msg("msg_arch", "alice", "bob"))
    _run(idx, tree)
    con = sqlite3.connect(str(idx.db_path))
    try:
        rows = con.execute(
            "SELECT recipient, status FROM deliveries WHERE message_id=?",
            ("msg_arch",),
        ).fetchall()
    finally:
        con.close()
    assert ("bob", "archived") in rows


def test_prompt_queue_folds_to_prompt_delivery(tree, idx):
    _write_prompt(tree, "bob", {
        "id": "queue_1",
        "message_id": "msg_prompt_1",
        "to": "bob",
        "content": "please do the thing",
        "urgency": "prompt",
        "source": "alice",
        "queued_at": "2026-06-23T09:00:00",
        "ttl_seconds": None,
    })
    summary = _run(idx, tree)
    assert summary["prompts_inserted"] == 1
    m = idx.get_message("msg_prompt_1")
    assert m is not None
    assert m["delivery"] == "prompt"
    con = sqlite3.connect(str(idx.db_path))
    try:
        row = con.execute(
            "SELECT status FROM deliveries WHERE message_id=? AND recipient=?",
            ("msg_prompt_1", "bob"),
        ).fetchone()
    finally:
        con.close()
    assert row == ("prompt",)


def test_response_required_opens_obligation(tree, idx):
    _write_msg(tree, "messages/inbox", "bob",
               _msg("msg_ob", "alice", "bob", response_required=True))
    _run(idx, tree)
    m = idx.get_message("msg_ob")
    assert idx.conversation_needs_input(m["conversation_id"]) is True


def test_idempotent_second_run_no_new_rows(tree, idx):
    _write_msg(tree, "messages/inbox", "bob",
               _msg("msg_root", "alice", "bob", subject="T"))
    _write_msg(tree, "messages/inbox", "alice",
               _msg("msg_rep", "bob", "alice", replying_to="msg_root",
                    created_at="2026-06-23T10:01:00"))
    s1 = _run(idx, tree)
    counts1 = {t: _count(idx, t) for t in
               ("conversations", "messages", "deliveries", "obligations")}
    s2 = _run(idx, tree)
    counts2 = {t: _count(idx, t) for t in
               ("conversations", "messages", "deliveries", "obligations")}
    assert counts1 == counts2
    assert s2["conversations_created"] == 0
    assert s2["messages_inserted"] == 0


def test_dry_run_writes_nothing(tree, idx):
    _write_msg(tree, "messages/inbox", "bob",
               _msg("msg_dry", "alice", "bob", subject="X"))
    _write_msg(tree, "messages/inbox", "alice",
               _msg("msg_dry2", "bob", "alice", replying_to="msg_dry",
                    created_at="2026-06-23T10:01:00"))
    summary = _run(idx, tree, dry_run=True)
    # Plan reports work...
    assert summary["messages_inserted"] == 2
    assert summary["conversations_created"] == 1
    # ...but nothing was written.
    assert _count(idx, "messages") == 0
    assert _count(idx, "conversations") == 0
    assert _count(idx, "deliveries") == 0


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
