#!/usr/bin/env python3
"""Read/query-API + CLI tests for comms_index.CommsIndex (Task 3).

Seeds data via the Task-2 write API, then exercises:
  - list_conversations (derived needs_input, participants OR filter,
    linked_work filter, last_message_preview truncation, pagination)
  - get_conversation (messages asc + deliveries + obligations, resolved body,
    effective_subject, `from` key)
  - view inbox/sent/archive (incl. archived exclusion from inbox)
  - the argparse JSON CLI (via subprocess) for each verb.
"""

import json
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

# Make the parent (messages/) dir importable so `import comms_index` works.
_MESSAGES_DIR = Path(__file__).resolve().parent.parent
if str(_MESSAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_MESSAGES_DIR))

from uai_toolkit.messages import comms_index  # noqa: E402
from uai_toolkit.messages.comms_index import CommsIndex  # noqa: E402

_MODULE_PATH = _MESSAGES_DIR / "comms_index.py"


@pytest.fixture
def idx(tmp_path):
    return CommsIndex(db_path=tmp_path / "comms.db")


def _msg(cid, mid, frm, to, created_at, **over):
    msg = {
        "id": mid,
        "conversation_id": cid,
        "reply_to": None,
        "subject": "Hello",
        "from_id": frm,
        "to_entity": to,
        "delivery": "message",
        "type": "direct",
        "urgency": "normal",
        "response_type": None,
        "ttl_seconds": None,
        "response_required": 0,
        "created_at": created_at,
        "body": "inline body",
    }
    msg.update(over)
    return msg


def _cli(db_path, *args):
    """Invoke the CLI as a subprocess; return parsed JSON from stdout."""
    cmd = [sys.executable, str(_MODULE_PATH), *args, "--db", str(db_path), "--json"]
    out = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


# --- list_conversations ------------------------------------------------------

def test_list_needs_input_true_and_false(idx):
    c1 = idx.create_conversation("needs input convo")
    idx.insert_message(_msg(c1, "m1", "alice", "bob", "2026-06-23T10:00:00"))
    idx.insert_delivery("m1", "bob")
    idx.open_obligation(c1, "m1", "bob")

    c2 = idx.create_conversation("settled convo")
    idx.insert_message(_msg(c2, "m2", "alice", "carol", "2026-06-23T11:00:00"))
    idx.insert_delivery("m2", "carol")

    rows = {r["id"]: r for r in idx.list_conversations()}
    assert rows[c1]["needs_input"] is True
    assert rows[c2]["needs_input"] is False


def test_list_participants_or_filter(idx):
    c1 = idx.create_conversation("a")
    idx.insert_message(_msg(c1, "m1", "alice", "bob", "2026-06-23T10:00:00"))
    idx.insert_delivery("m1", "bob")

    c2 = idx.create_conversation("b")
    idx.insert_message(_msg(c2, "m2", "carol", "dave", "2026-06-23T10:05:00"))
    idx.insert_delivery("m2", "dave")

    c3 = idx.create_conversation("c")
    idx.insert_message(_msg(c3, "m3", "erin", "frank", "2026-06-23T10:10:00"))
    idx.insert_delivery("m3", "frank")

    # OR over two ids: alice (c1) or dave (c2) -> c1 and c2, not c3.
    ids = {r["id"] for r in idx.list_conversations(participants=["alice", "dave"])}
    assert ids == {c1, c2}


def test_list_participants_includes_from_and_recipients(idx):
    c1 = idx.create_conversation("a")
    idx.insert_message(_msg(c1, "m1", "alice", "bob", "2026-06-23T10:00:00"))
    idx.insert_delivery("m1", "bob")
    idx.insert_delivery("m1", "carol")
    row = idx.list_conversations()[0]
    assert set(row["participants"]) == {"alice", "bob", "carol"}


def test_list_linked_work_filter(idx):
    c1 = idx.create_conversation("a", linked_work="todo_0315")
    idx.insert_message(_msg(c1, "m1", "alice", "bob", "2026-06-23T10:00:00"))
    c2 = idx.create_conversation("b", linked_work="todo_9999")
    idx.insert_message(_msg(c2, "m2", "alice", "bob", "2026-06-23T10:05:00"))

    ids = {r["id"] for r in idx.list_conversations(linked_work="0315")}
    assert ids == {c1}


def test_list_last_message_preview_truncation_and_latest(idx):
    c1 = idx.create_conversation("a")
    idx.insert_message(_msg(c1, "m1", "alice", "bob", "2026-06-23T10:00:00",
                            body="first message"))
    long_body = "x" * 200
    idx.insert_message(_msg(c1, "m2", "bob", "alice", "2026-06-23T11:00:00",
                            body=long_body))
    row = idx.list_conversations()[0]
    preview = row["last_message_preview"]
    assert preview.endswith("…")
    assert len(preview) == 121  # 120 chars + ellipsis
    assert preview[:120] == "x" * 120


def test_list_pagination(idx):
    for i in range(5):
        c = idx.create_conversation(f"c{i}")
        idx.insert_message(_msg(c, f"m{i}", "alice", "bob",
                                f"2026-06-23T10:0{i}:00"))
    full = idx.list_conversations(order="created_at")
    assert len(full) == 5
    page = idx.list_conversations(limit=2, offset=1, order="created_at")
    # Pagination is a deterministic slice of the full ordered result.
    assert [r["id"] for r in page] == [r["id"] for r in full[1:3]]


# --- get_conversation --------------------------------------------------------

def test_get_conversation_full_shape(idx):
    c1 = idx.create_conversation("Topic", linked_work="todo_1")
    idx.insert_message(_msg(c1, "m1", "alice", "bob", "2026-06-23T10:00:00",
                            subject="Root Subject"))
    idx.insert_message(_msg(c1, "m2", "bob", "alice", "2026-06-23T11:00:00",
                            subject=None, reply_to="m1", body="reply body"))
    idx.insert_delivery("m1", "bob")
    idx.set_delivery_status("m1", "bob", "read",
                            delivered_at="2026-06-23T10:01:00",
                            read_at="2026-06-23T10:02:00")
    idx.open_obligation(c1, "m1", "bob")

    res = idx.get_conversation(c1)
    conv = res["conversation"]
    assert conv["id"] == c1
    assert conv["topic"] == "Topic"
    assert conv["needs_input"] is True
    assert conv["linked_work"] == "todo_1"
    assert conv["root_count"] == 1

    msgs = res["messages"]
    assert [m["id"] for m in msgs] == ["m1", "m2"]  # asc
    assert msgs[0]["from"] == "alice"               # `from` key
    assert msgs[0]["effective_subject"] == "Root Subject"
    assert msgs[1]["effective_subject"] == "Root Subject"  # inherited
    assert msgs[1]["body"] == "reply body"          # resolved

    dels = res["deliveries"]
    assert any(d["recipient"] == "bob" and d["status"] == "read" for d in dels)
    obls = res["obligations"]
    assert obls[0]["participant"] == "bob"
    assert obls[0]["cleared_at"] is None


def test_get_conversation_resolves_body_ref_missing_file(idx):
    c1 = idx.create_conversation("a")
    msg = _msg(c1, "m1", "alice", "bob", "2026-06-23T10:00:00")
    del msg["body"]
    msg["body_ref"] = "bodyref_missing"
    idx.insert_message(msg)
    # body_refs row pointing at a non-existent file -> body resolves to ''.
    con = sqlite3.connect(str(idx.db_path))
    con.execute("INSERT INTO body_refs (id, path, bytes) VALUES (?, ?, ?)",
                ("bodyref_missing", "no/such/file.md", 0))
    con.commit()
    con.close()
    res = idx.get_conversation(c1)
    assert res["messages"][0]["body"] == ""


def test_resolve_body_ref_reads_file(idx, tmp_path, monkeypatch):
    monkeypatch.setattr(comms_index, "COMMS_ROOT", tmp_path)
    target = tmp_path / "msgs" / "body.md"
    target.parent.mkdir()
    target.write_text("resolved from file")
    c1 = idx.create_conversation("a")
    msg = _msg(c1, "m1", "alice", "bob", "2026-06-23T10:00:00")
    del msg["body"]
    msg["body_ref"] = "bodyref_real"
    idx.insert_message(msg)
    con = sqlite3.connect(str(idx.db_path))
    con.execute("INSERT INTO body_refs (id, path, bytes) VALUES (?, ?, ?)",
                ("bodyref_real", "msgs/body.md", 0))
    con.commit()
    con.close()
    res = idx.get_conversation(c1)
    assert res["messages"][0]["body"] == "resolved from file"


# --- view --------------------------------------------------------------------

def _seed_view(idx):
    c1 = idx.create_conversation("a")
    # m1: alice -> bob (delivered/read), also archived copy via separate msg
    idx.insert_message(_msg(c1, "m1", "alice", "bob", "2026-06-23T10:00:00",
                            body="to bob inbox"))
    idx.insert_delivery("m1", "bob")
    idx.set_delivery_status("m1", "bob", "read")
    # m2: alice -> bob but archived
    idx.insert_message(_msg(c1, "m2", "alice", "bob", "2026-06-23T11:00:00",
                            body="to bob archived"))
    idx.insert_delivery("m2", "bob")
    idx.set_delivery_status("m2", "bob", "archived")
    # m3: bob -> alice (so bob is sender)
    idx.insert_message(_msg(c1, "m3", "bob", "alice", "2026-06-23T12:00:00",
                            body="from bob"))
    idx.insert_delivery("m3", "alice")
    return c1


def test_view_inbox_excludes_archived(idx):
    _seed_view(idx)
    inbox = idx.view("inbox", "bob")
    ids = {r["id"] for r in inbox}
    assert "m1" in ids
    assert "m2" not in ids  # archived excluded
    row = next(r for r in inbox if r["id"] == "m1")
    assert row["status"] == "read"        # delivery dict merged
    assert row["body"] == "to bob inbox"  # resolved body
    assert row["from"] == "alice"


def test_view_archive(idx):
    _seed_view(idx)
    arch = idx.view("archive", "bob")
    ids = {r["id"] for r in arch}
    assert ids == {"m2"}
    assert arch[0]["status"] == "archived"


def test_view_sent(idx):
    _seed_view(idx)
    sent = idx.view("sent", "bob")
    ids = {r["id"] for r in sent}
    assert ids == {"m3"}  # only message bob sent
    assert sent[0]["from"] == "bob"


def test_view_newest_first_and_pagination(idx):
    c1 = idx.create_conversation("a")
    for i in range(4):
        mid = f"m{i}"
        idx.insert_message(_msg(c1, mid, "alice", "bob",
                                f"2026-06-23T10:0{i}:00"))
        idx.insert_delivery(mid, "bob")
    inbox = idx.view("inbox", "bob")
    assert [r["id"] for r in inbox] == ["m3", "m2", "m1", "m0"]  # newest first
    page = idx.view("inbox", "bob", limit=2, offset=1)
    assert [r["id"] for r in page] == ["m2", "m1"]


# --- CLI ---------------------------------------------------------------------

def test_cli_conversations(idx):
    c1 = idx.create_conversation("cli convo", linked_work="todo_1")
    idx.insert_message(_msg(c1, "m1", "alice", "bob", "2026-06-23T10:00:00"))
    idx.insert_delivery("m1", "bob")
    idx.open_obligation(c1, "m1", "bob")

    data = _cli(idx.db_path, "conversations")
    assert isinstance(data, list)
    row = data[0]
    for key in ("id", "topic", "status", "needs_input", "participants",
                "last_activity", "created_at", "linked_work", "message_count",
                "last_message_preview"):
        assert key in row
    assert row["needs_input"] is True

    # participant filter (repeatable)
    data = _cli(idx.db_path, "conversations", "--participant", "alice")
    assert {r["id"] for r in data} == {c1}
    data = _cli(idx.db_path, "conversations", "--participant", "nobody")
    assert data == []


def test_cli_conversation(idx):
    c1 = idx.create_conversation("cli convo")
    idx.insert_message(_msg(c1, "m1", "alice", "bob", "2026-06-23T10:00:00"))
    data = _cli(idx.db_path, "conversation", c1)
    assert set(data.keys()) == {"conversation", "messages", "deliveries",
                                "obligations"}
    assert data["messages"][0]["from"] == "alice"
    assert data["conversation"]["id"] == c1


def test_cli_view(idx):
    _seed_view(idx)
    data = _cli(idx.db_path, "view", "inbox", "bob")
    ids = {r["id"] for r in data}
    assert "m1" in ids and "m2" not in ids
    data = _cli(idx.db_path, "view", "sent", "bob")
    assert {r["id"] for r in data} == {"m3"}


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
