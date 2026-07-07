#!/usr/bin/env python3
"""Task 9: MCP/CLI send contract v2 + transition shim (§12.L).

Two surfaces are covered:

1. **MCP schema** (`apps/mcps/comms/tools.yml`): `comms_message` no longer
   exposes `from`/`from_sender`, makes `reply_to` REQUIRED + nullable, and adds
   `subject`. `comms_send_prompt` mirrors `reply_to`/`subject`.

2. **CLI transition shim** (`messaging_mgr._run_subcommand`): during the
   deprecation window the `send` CLI still ACCEPTS legacy `--from` and
   `--conversation-id` (ignored, with a stderr warning) and a MISSING
   `--reply-to` warns + defaults to `none` (new conversation). `--reply-to none`
   normalizes to a new conversation end-to-end (returns conversationId +
   messageId); a new conversation with no subject surfaces SubjectRequired.

The CLI tests inject a tmp comms tree + tmp comms.db and stub the session store,
mirroring the Task 6/7 v2 tests so nothing touches live sessions.
"""

import io
import json
import sqlite3
import sys
from contextlib import redirect_stdout, redirect_stderr
from pathlib import Path

import pytest
import yaml

# Make the parent (messages/) dir importable.
_MESSAGES_DIR = Path(__file__).resolve().parent.parent
if str(_MESSAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_MESSAGES_DIR))

from uai_toolkit.messages import comms_index  # noqa: E402
from uai_toolkit.messages import lib_identity_resolve as ir  # noqa: E402
from uai_toolkit.messages import messaging_mgr as mm  # noqa: E402

# ai_general/scripts/messages -> ai_general
_AI_GENERAL = _MESSAGES_DIR.parents[1]
_TOOLS_YML = _AI_GENERAL / "apps" / "mcps" / "comms" / "tools.yml"


# =============================================================================
# MCP schema (tools.yml) contract
# =============================================================================

def _load_tools():
    with open(_TOOLS_YML) as f:
        data = yaml.safe_load(f)
    return {t["name"]: t for t in data["tools"]}


def _types(prop):
    """Return the declared type(s) of a property as a set of strings."""
    t = prop.get("type")
    if isinstance(t, str):
        return {t}
    if isinstance(t, list):
        return set(t)
    return set()


def test_comms_message_schema_drops_from():
    t = _load_tools()["comms_message"]
    props = t["inputSchema"]["properties"]
    required = t["inputSchema"].get("required", [])
    # sender is the trusted resolved session — no `from`/`from_sender` param
    assert "from" not in props and "from_sender" not in props
    assert "from" not in required and "from_sender" not in required


def test_comms_message_reply_to_required_and_nullable():
    t = _load_tools()["comms_message"]
    props = t["inputSchema"]["properties"]
    required = t["inputSchema"].get("required", [])
    assert "reply_to" in props, "reply_to must be exposed"
    assert "reply_to" in required, "reply_to must be REQUIRED"
    assert _types(props["reply_to"]) >= {"string", "null"}, "reply_to must be nullable"


def test_comms_message_has_subject():
    t = _load_tools()["comms_message"]
    props = t["inputSchema"]["properties"]
    assert "subject" in props, "subject must be exposed (required when reply_to is null)"


def test_comms_send_prompt_mirrors_reply_to_and_subject():
    t = _load_tools()["comms_send_prompt"]
    props = t["inputSchema"]["properties"]
    assert "reply_to" in props
    assert "subject" in props


# =============================================================================
# CLI transition shim — end-to-end against a tmp comms.db
# =============================================================================

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
def cli_env(tmp_path, monkeypatch):
    comms_root = tmp_path / "ai_comms"
    messages_dir = comms_root / "messages"
    db_path = tmp_path / "comms.db"

    monkeypatch.setattr(mm, "COMMS_DIR", comms_root)
    monkeypatch.setattr(mm, "MESSAGES_DIR", messages_dir)
    monkeypatch.setattr(mm, "MESSAGES_INBOX", messages_dir / "inbox")
    monkeypatch.setattr(mm, "MESSAGE_BODIES", messages_dir / "bodies")
    monkeypatch.setattr(mm, "MESSAGES_SENT", messages_dir / "sent")
    monkeypatch.setattr(comms_index, "COMMS_ROOT", comms_root)
    # send_message() with no injected index builds CommsIndex(), which reads
    # the module-level DB_PATH — point it at the tmp db.
    monkeypatch.setattr(comms_index, "DB_PATH", db_path)

    sessions = {"alice": [_rec("alice")], "bob": [_rec("bob")]}
    monkeypatch.setattr(ir, "_search_sessions", lambda q: list(sessions.get(q, [])))
    # Trusted sender resolves from $AI_TRACKING_ID.
    monkeypatch.setenv("AI_TRACKING_ID", "alice")

    class Env:
        pass

    e = Env()
    e.db = db_path
    e.sessions = sessions
    return e


def _q(db_path, sql, params=()):
    con = sqlite3.connect(str(db_path))
    try:
        return con.execute(sql, params).fetchall()
    finally:
        con.close()


def _run_cli(argv):
    parser = mm._build_parser()
    args = parser.parse_args(argv)
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        code = mm._run_subcommand(args)
    return code, out.getvalue(), err.getvalue()


def test_cli_reply_to_none_starts_new_conversation(cli_env):
    code, out, err = _run_cli([
        "send", "--to", "bob", "--content", "hi",
        "--reply-to", "none", "--subject", "Kickoff",
    ])
    assert code == 0, err
    res = json.loads(out)
    assert res["conversationId"].startswith("convo_")
    assert res["messageId"].startswith("msg_")
    rows = _q(cli_env.db, "SELECT topic FROM conversations WHERE id=?",
              (res["conversationId"],))
    assert rows and rows[0][0] == "Kickoff"


def test_cli_missing_reply_to_warns_and_defaults_to_new_conversation(cli_env):
    code, out, err = _run_cli([
        "send", "--to", "bob", "--content", "hi", "--subject", "NoReplyTo",
    ])
    assert code == 0, err
    res = json.loads(out)
    assert res["conversationId"].startswith("convo_")
    # shim emitted a deprecation warning about the missing --reply-to
    low = err.lower()
    assert "reply-to" in low or "reply_to" in low
    assert "deprecat" in low


def test_cli_legacy_from_is_ignored_with_warning(cli_env):
    # --from ghost must NOT win — the trusted sender is alice ($AI_TRACKING_ID).
    code, out, err = _run_cli([
        "send", "--from", "ghost", "--to", "bob", "--content", "hi",
        "--reply-to", "none", "--subject", "S",
    ])
    assert code == 0, err
    res = json.loads(out)
    rows = _q(cli_env.db, "SELECT from_id FROM messages WHERE id=?",
              (res["messageId"],))
    assert rows[0][0] == "alice", "legacy --from must be ignored, sender resolved"
    assert "--from" in err and "deprecat" in err.lower()


def test_cli_conversation_id_ignored_with_warning(cli_env):
    code, out, err = _run_cli([
        "send", "--to", "bob", "--content", "hi",
        "--reply-to", "none", "--subject", "S",
        "--conversation-id", "convo_legacy_xyz",
    ])
    assert code == 0, err
    res = json.loads(out)
    # v2 derives the conversation; the supplied id is NOT honored.
    assert res["conversationId"] != "convo_legacy_xyz"
    assert "conversation-id" in err.lower() and "deprecat" in err.lower()


def test_cli_new_conversation_without_subject_surfaces_subject_required(cli_env):
    code, out, err = _run_cli([
        "send", "--to", "bob", "--content", "hi", "--reply-to", "none",
    ])
    assert code == 1
    res = json.loads(out)
    assert res.get("error_type") == "SubjectRequired"
