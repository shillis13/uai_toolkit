#!/usr/bin/env python3
"""Tests for messaging_mgr.send_prompt (Task 7: prompts persisted like messages).

Design §6: "Prompts persisted like messages (delivery: 'prompt'); sent prompts
must be WRITTEN, not evaporate." A prompt send must create a durable record via
the same v2 path as a message — a canonical message row (delivery='prompt'), a
queued delivery row, and an obligation for the recipient (a prompt implies a
response) — while ADDITIVELY preserving the legacy queue-file write that the
UserPromptSubmit hook consumes.

Design §5.9: `send_prompt --help` references only the substrate (`session_ops`),
no `zellij`/`tmux`.

Every test injects a tmp CommsIndex and tmp comms directories and stubs the
session-store seam so nothing touches live sessions.
"""

import subprocess
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
    """Tmp comms tree + injected CommsIndex + a controllable session store."""
    comms_root = tmp_path / "ai_comms"
    messages_dir = comms_root / "messages"
    inbox = messages_dir / "inbox"
    bodies = messages_dir / "bodies"
    sent = messages_dir / "sent"
    broadcasts = comms_root / "broadcasts"
    prompts_inbox = comms_root / "prompts_inbox"

    monkeypatch.setattr(mm, "COMMS_DIR", comms_root)
    monkeypatch.setattr(mm, "MESSAGES_DIR", messages_dir)
    monkeypatch.setattr(mm, "MESSAGES_INBOX", inbox)
    monkeypatch.setattr(mm, "MESSAGE_BODIES", bodies)
    monkeypatch.setattr(mm, "MESSAGES_SENT", sent)
    monkeypatch.setattr(mm, "BROADCASTS_DIR", broadcasts)
    monkeypatch.setattr(mm, "PROMPTS_INBOX", prompts_inbox)
    monkeypatch.setattr(comms_index, "COMMS_ROOT", comms_root)

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
    e.prompts_inbox = prompts_inbox
    return e


def _q(index, sql, params=()):
    con = sqlite3.connect(str(index.db_path))
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


# --- durable persistence -----------------------------------------------------

def test_prompt_persists_as_delivery_prompt(env):
    out = mm.send_prompt(
        to="bob",
        content="run the tests",
        reply_to=None,
        subject="Task",
        sender_ctx="alice",
        index=env.index,
    )
    # returns the v2 handle
    assert set(out) >= {"conversationId", "messageId"}
    cid, mid = out["conversationId"], out["messageId"]
    assert cid.startswith("convo_")
    assert mid.startswith("msg_")

    # canonical message row exists with delivery='prompt' (does NOT evaporate)
    row = _q(
        env.index,
        "SELECT delivery, from_id, to_entity, subject, body FROM messages WHERE id=?",
        (mid,),
    )
    assert row, "prompt evaporated: no message row in index"
    delivery, from_id, to_entity, subject, body = row[0]
    assert delivery == "prompt"
    assert from_id == "alice"
    assert to_entity == "uai://session/bob/message"
    assert subject == "Task"
    assert body == "run the tests"


def test_prompt_creates_queued_delivery_row(env):
    out = mm.send_prompt(
        to="bob", content="x", reply_to=None, subject="S",
        sender_ctx="alice", index=env.index,
    )
    mid = out["messageId"]
    deliv = _q(
        env.index,
        "SELECT recipient, status FROM deliveries WHERE message_id=?",
        (mid,),
    )
    assert deliv == [("bob", "queued")]


def test_prompt_opens_obligation_for_recipient(env):
    out = mm.send_prompt(
        to="bob", content="answer", reply_to=None, subject="Q",
        sender_ctx="alice", index=env.index,
    )
    cid, mid = out["conversationId"], out["messageId"]
    obs = _q(
        env.index,
        "SELECT participant, message_id FROM obligations "
        "WHERE conversation_id=? AND cleared_at IS NULL",
        (cid,),
    )
    assert any(p == "bob" and m == mid for (p, m) in obs)


def test_prompt_also_writes_queue_file(env):
    # Back-compat: the legacy queue-file write is preserved (additive).
    out = mm.send_prompt(
        to="bob", content="queued work", reply_to=None, subject="S",
        sender_ctx="alice", index=env.index,
    )
    session_dir = env.prompts_inbox / "bob"
    assert session_dir.exists()
    ymls = list(session_dir.glob("*.yml"))
    assert ymls, "no legacy queue-file written"
    data = mm._read_yaml(ymls[0])
    assert data["to"] == "bob"
    assert data["content"] == "queued work"
    # the queue entry references the same canonical message id
    assert data["message_id"] == out["messageId"]


def test_prompt_requires_subject_for_new_thread(env):
    with pytest.raises(rr.SubjectRequired):
        mm.send_prompt(
            to="bob", content="x", reply_to=None, subject=None,
            sender_ctx="alice", index=env.index,
        )
    # nothing leaked into the index
    assert _q(env.index, "SELECT COUNT(*) FROM messages")[0][0] == 0
    # and no queue file evaporated either way
    assert not (env.prompts_inbox / "bob").exists() or not list(
        (env.prompts_inbox / "bob").glob("*.yml")
    )


def test_prompt_reply_reuses_conversation(env):
    parent = mm.send_message(
        to="bob", content="parent", reply_to=None, subject="Thread",
        sender_ctx="alice", index=env.index,
    )
    out = mm.send_prompt(
        to="alice", content="prod", reply_to=parent["messageId"], subject=None,
        sender_ctx="bob", index=env.index,
    )
    assert out["conversationId"] == parent["conversationId"]
    row = _q(env.index, "SELECT delivery FROM messages WHERE id=?", (out["messageId"],))
    assert row[0][0] == "prompt"


# --- help scrub (§5.9) -------------------------------------------------------

_SEND_PROMPT_SCRIPT = (
    _MESSAGES_DIR.parent / "prompting" / "send_prompt.py"
)


def _help_text():
    out = []
    for flag in ("--help", "--help-examples"):
        p = subprocess.run(
            [sys.executable, str(_SEND_PROMPT_SCRIPT), flag],
            capture_output=True, text=True,
        )
        out.append(p.stdout + p.stderr)
    return "\n".join(out)


def test_send_prompt_help_has_no_multiplexer_names():
    text = _help_text().lower()
    assert "zellij" not in text, "send_prompt --help leaks 'zellij'"
    assert "tmux" not in text, "send_prompt --help leaks 'tmux'"
