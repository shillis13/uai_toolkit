#!/usr/bin/env python3
"""Tests for messaging_mgr.send_message (Task 6: the v2 send contract).

These wire the previously-built pieces together: trusted sender resolution
(lib_identity_resolve), enforced reply_to / subject (lib_reply_rule), and the
SQLite index (comms_index). Every test injects a tmp CommsIndex and tmp comms
directories, and stubs the session-store seam so nothing touches live sessions.
"""

import sqlite3
import sys
from pathlib import Path

import pytest

# Make the parent (messages/) dir importable.
_MESSAGES_DIR = Path(__file__).resolve().parent.parent
if str(_MESSAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_MESSAGES_DIR))

from uai_toolkit.messages import comms_index  # noqa: E402
from uai_toolkit.messages import lib_identity_resolve as ir  # noqa: E402
from uai_toolkit.messages import lib_reply_rule as rr  # noqa: E402
from uai_toolkit.messages import messaging_mgr as mm  # noqa: E402
from uai_toolkit.messages.comms_index import CommsIndex  # noqa: E402


def _rec(tid, **kw):
    d = {
        "tracking_id": tid,
        "display_name": tid,
        "status": "running",
        "platform": "claude_cli",
        "archived": 0,
    }
    d.update(kw)
    return d


@pytest.fixture
def env(tmp_path, monkeypatch):
    """Tmp comms tree + injected CommsIndex + a controllable session store.

    Returns a small namespace with `index`, the canned-session map `sessions`,
    and the tmp directory roots so assertions can hit the filesystem.
    """
    comms_root = tmp_path / "ai_comms"
    messages_dir = comms_root / "messages"
    inbox = messages_dir / "inbox"
    bodies = messages_dir / "bodies"
    sent = messages_dir / "sent"

    monkeypatch.setattr(mm, "COMMS_DIR", comms_root)
    monkeypatch.setattr(mm, "MESSAGES_DIR", messages_dir)
    monkeypatch.setattr(mm, "MESSAGES_INBOX", inbox)
    monkeypatch.setattr(mm, "MESSAGE_BODIES", bodies)
    monkeypatch.setattr(mm, "MESSAGES_SENT", sent)
    monkeypatch.setattr(comms_index, "COMMS_ROOT", comms_root)

    # Canned session store: query -> list of records. Tests mutate `sessions`.
    sessions = {
        "alice": [_rec("alice")],
        "bob": [_rec("bob")],
    }

    def fake_search(query):
        return list(sessions.get(query, []))

    monkeypatch.setattr(ir, "_search_sessions", fake_search)

    index = CommsIndex(db_path=tmp_path / "comms.db")

    class Env:
        pass

    e = Env()
    e.index = index
    e.sessions = sessions
    e.comms_root = comms_root
    e.inbox = inbox
    e.bodies = bodies
    return e


def _q(index, sql, params=()):
    con = sqlite3.connect(str(index.db_path))
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


# --- new-conversation send ---------------------------------------------------

def test_new_conversation_send(env):
    out = mm.send_message(
        to="bob",
        content="hello there",
        reply_to=None,
        subject="Kickoff",
        sender_ctx="alice",
        index=env.index,
    )
    # Core return contract. A prompt-urgency session send also attempts active
    # delivery (pre-existing behavior) and annotates the result with an optional
    # 'delivery' key (per-recipient notify outcome), so assert the contract keys
    # are present rather than exact set-equality.
    assert {"conversationId", "messageId"}.issubset(out)
    cid, mid = out["conversationId"], out["messageId"]
    assert cid.startswith("convo_")
    assert mid.startswith("msg_")

    # conversation + message rows exist
    convo = _q(env.index, "SELECT topic FROM conversations WHERE id=?", (cid,))
    assert convo and convo[0][0] == "Kickoff"
    msg = _q(
        env.index,
        "SELECT conversation_id, from_id, to_entity, subject, reply_to, body "
        "FROM messages WHERE id=?",
        (mid,),
    )
    assert msg
    conversation_id, from_id, to_entity, subject, reply_to, body = msg[0]
    assert conversation_id == cid
    assert from_id == "alice"
    assert to_entity == "uai://session/bob/message"
    assert subject == "Kickoff"
    assert reply_to is None
    assert body == "hello there"

    # exactly one delivery, to the resolved recipient
    deliv = _q(env.index, "SELECT recipient FROM deliveries WHERE message_id=?", (mid,))
    assert [r[0] for r in deliv] == ["bob"]

    # YAML artifact written into the recipient's inbox dir
    yml = env.inbox / "bob" / "{}.yml".format(mid)
    assert yml.exists()
    data = mm._read_yaml(yml)
    assert data["conversation_id"] == cid
    assert data["from"] == "alice"
    assert data.get("replying_to") in (None,)  # mirror present for old readers


def test_new_conversation_requires_subject(env):
    with pytest.raises(rr.SubjectRequired):
        mm.send_message(
            to="bob", content="x", reply_to=None, subject=None,
            sender_ctx="alice", index=env.index,
        )
    # no message rows leaked
    assert _q(env.index, "SELECT COUNT(*) FROM messages")[0][0] == 0
    assert _q(env.index, "SELECT COUNT(*) FROM conversations")[0][0] == 0


def test_large_body_externalized(env):
    big = "x" * 1200
    out = mm.send_message(
        to="bob", content=big, reply_to=None, subject="Big",
        sender_ctx="alice", index=env.index,
    )
    mid = out["messageId"]
    row = _q(env.index, "SELECT body, body_ref FROM messages WHERE id=?", (mid,))
    body, body_ref = row[0]
    assert body is None
    assert body_ref  # a body_refs id was recorded

    refs = _q(
        env.index, "SELECT path, bytes FROM body_refs WHERE id=?", (body_ref,)
    )
    assert refs
    path, nbytes = refs[0]
    assert nbytes == 1200
    # the bodies file exists and round-trips through the index read path
    assert (env.comms_root / path).read_text() == big
    full = env.index.get_message(mid)
    assert env.index._resolve_body(full) == big


# --- reply send --------------------------------------------------------------

def _seed_parent(env):
    """alice opens a thread to bob; returns (conversation_id, parent_msg_id)."""
    out = mm.send_message(
        to="bob", content="parent", reply_to=None, subject="Thread",
        sender_ctx="alice", index=env.index,
    )
    return out["conversationId"], out["messageId"]


def test_reply_reuses_conversation(env):
    cid, parent = _seed_parent(env)
    # bob replies; subject is optional on a reply
    out = mm.send_message(
        to="alice", content="re: parent", reply_to=parent, subject=None,
        sender_ctx="bob", index=env.index,
    )
    assert out["conversationId"] == cid
    row = _q(
        env.index,
        "SELECT reply_to, conversation_id FROM messages WHERE id=?",
        (out["messageId"],),
    )
    assert row[0][0] == parent
    assert row[0][1] == cid


# --- error propagation / transaction integrity ------------------------------

def test_ambiguous_recipient_writes_nothing(env):
    env.sessions["dup"] = [_rec("d1"), _rec("d2")]
    with pytest.raises(ir.RecipientAmbiguous):
        mm.send_message(
            to="dup", content="x", reply_to=None, subject="S",
            sender_ctx="alice", index=env.index,
        )
    # transaction integrity: nothing was written to the index
    assert _q(env.index, "SELECT COUNT(*) FROM conversations")[0][0] == 0
    assert _q(env.index, "SELECT COUNT(*) FROM messages")[0][0] == 0
    assert _q(env.index, "SELECT COUNT(*) FROM deliveries")[0][0] == 0


def test_unresolvable_sender(env):
    with pytest.raises(ir.SenderUnresolved):
        mm.send_message(
            to="bob", content="x", reply_to=None, subject="S",
            sender_ctx="ghost", index=env.index,
        )
    assert _q(env.index, "SELECT COUNT(*) FROM messages")[0][0] == 0


# --- obligations -------------------------------------------------------------

def test_response_required_opens_obligation(env):
    out = mm.send_message(
        to="bob", content="answer me", reply_to=None, subject="Q",
        sender_ctx="alice", response_required=True, index=env.index,
    )
    cid, mid = out["conversationId"], out["messageId"]
    obs = _q(
        env.index,
        "SELECT participant, message_id, cleared_at FROM obligations "
        "WHERE conversation_id=?",
        (cid,),
    )
    open_obs = [o for o in obs if o[2] is None]
    assert any(o[0] == "bob" and o[1] == mid for o in open_obs)


def test_reply_clears_senders_obligation(env):
    # alice asks bob a question (obligation opens for bob)
    out = mm.send_message(
        to="bob", content="answer me", reply_to=None, subject="Q",
        sender_ctx="alice", response_required=True, index=env.index,
    )
    cid, parent = out["conversationId"], out["messageId"]
    # bob's obligation is open
    assert env.index.conversation_needs_input(cid) is True

    # bob replies -> his own obligation in this conversation is discharged
    mm.send_message(
        to="alice", content="here you go", reply_to=parent, subject=None,
        sender_ctx="bob", index=env.index,
    )
    bob_open = _q(
        env.index,
        "SELECT COUNT(*) FROM obligations "
        "WHERE conversation_id=? AND participant='bob' AND cleared_at IS NULL",
        (cid,),
    )[0][0]
    assert bob_open == 0
