#!/usr/bin/env python3
"""
test_context_mgr_repl.py — Phase 1 interactive REPL (todo_0331).

The REPL is a thin, read-only convenience layer over the existing query CLI.
It reuses the SAME argparse verb dispatch as ``main()`` (no duplicated verb
logic) and keeps ONE ``ContextIndex`` open for the session. These tests feed a
scripted list of input lines and capture output via injected streams, so no TTY
is needed. They also cover the ``--status all`` parser fix.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path

import pytest

# Make the parent module importable.
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from uai_toolkit.context_files import context_mgr  # noqa: E402
from uai_toolkit.context_files.context_mgr import ContextIndex, main, repl  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture tree: profile -> role -> knowledge + instruction, plus one archived
# knowledge file (path under _archive) to exercise --status all.
# ---------------------------------------------------------------------------

GLOSSARY_MD = """\
---
title: Glossary
summary: Term to file mapping for orientation.
---
# Glossary

Body text describing terms.
"""

CODING_YML = """\
metadata:
  title: Coding Standards
  description: How we write code.
rules:
  - use black
"""

OLD_MD = """\
---
title: Old Note
summary: Archived knowledge that should only show with --status all.
---
# Old Note
"""

DEV_ROLE_YML = """\
name: Developer
description: Writes code.
context_files:
  knowledge:
    - ai_context_files/knowledge/reference/glossary
  procedures:
    - ai_context_files/instructions/rules/coding
"""

DEV_PROFILE_YML = """\
name: Dev Profile
description: A profile that loads the developer role.
roles:
  - ai_profiles/roles/dev
"""


@pytest.fixture
def db(tmp_path, monkeypatch):
    """Build a small fixture tree, reindex it, and return the populated DB path."""
    root = tmp_path / "ai_root"

    def write(rel: str, content: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    write("ai_general/ai_context_files/knowledge/reference/glossary.md", GLOSSARY_MD)
    write("ai_general/ai_context_files/instructions/rules/coding.yml", CODING_YML)
    write("ai_general/ai_context_files/knowledge/_archive/old.md", OLD_MD)
    write("ai_general/ai_profiles/roles/dev.yml", DEV_ROLE_YML)
    write("ai_general/ai_profiles/dev_profile.yml", DEV_PROFILE_YML)

    monkeypatch.setattr(context_mgr, "AI_ROOT", root)
    db_path = tmp_path / "context.db"
    ContextIndex(db_path=db_path, ai_root=root).reindex()
    return db_path


def _repl(db, lines):
    """Run the REPL over a scripted line list; return captured output text."""
    out = io.StringIO()
    repl(db=db, input_lines=lines, out=out)
    return out.getvalue()


# ---------------------------------------------------------------------------
# 1. Scripted session: verbs dispatch, bad input is a hint, quit exits.
# ---------------------------------------------------------------------------

def test_repl_scripted_session(db):
    out = _repl(db, [
        "list --kind role",
        "resolve profile:dev_profile",
        "bogus",
        "quit",
    ])
    # A role appears in the human-readable list output.
    assert "role:dev" in out
    # resolve output appears (flat leaf files + summary line).
    assert "resolves to" in out
    assert "glossary" in out
    # The bogus line yields a hint and does NOT crash the loop.
    assert "bogus" in out
    low = out.lower()
    assert "help" in low  # the hint points the user at `help`


def test_repl_banner_mentions_count_and_help(db):
    out = _repl(db, ["quit"])
    low = out.lower()
    assert "repl" in low or "context_mgr" in low
    assert "help" in low
    assert "quit" in low
    # Banner names how many items are indexed.
    assert any(ch.isdigit() for ch in out)


def test_repl_bogus_does_not_exit_loop(db):
    # A bad line is followed by a good one; the good one must still run.
    out = _repl(db, ["bogus", "list --kind role", "quit"])
    assert "role:dev" in out


def test_repl_empty_line_then_eof_exits_cleanly(db):
    # Empty line is ignored; exhausting the script (EOF) exits without error.
    out = _repl(db, ["", "list --kind role"])
    assert "role:dev" in out  # ran before EOF


def test_repl_eof_exits_cleanly(db):
    # No quit at all: the loop returns when the scripted lines run out.
    out = _repl(db, [])
    # Just the banner; no exception raised.
    assert out  # banner printed


def test_repl_help_lists_verbs(db):
    out = _repl(db, ["help", "quit"])
    low = out.lower()
    for verb in ("list", "resolve", "tree", "refs", "search", "validate", "reindex"):
        assert verb in low


def test_repl_help_examples(db):
    out = _repl(db, ["help-examples", "quit"])
    assert "list --kind role" in out


def test_repl_json_per_line(db):
    out = _repl(db, ["list --kind role --json", "quit"])
    # The --json line should emit valid JSON somewhere in the transcript.
    # Find the JSON array block.
    start = out.index("[")
    # crude: parse from first '[' to matching ']' at column 0-ish; rely on
    # json.loads tolerating trailing prompt lines by slicing to last ']'.
    end = out.rindex("]")
    parsed = json.loads(out[start:end + 1])
    assert any(r["id"] == "role:dev" for r in parsed)


def test_repl_oneline_honored(db):
    out = _repl(db, ["list --kind role --oneline", "quit"])
    assert "role:dev" in out


# ---------------------------------------------------------------------------
# 2. --status all parser fix.
# ---------------------------------------------------------------------------

def test_status_all_in_choices():
    parser = context_mgr._build_parser()
    args = parser.parse_args(["list", "--status", "all"])
    assert args.status == "all"


def test_status_all_returns_only_active_now(capsys, db):
    # Archived items are no longer indexed (discovery skips _archive/), so
    # --status all returns only active items — there is nothing archived to add.
    rc = main(["--db", str(db), "list", "--status", "all", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    ids = {r["id"] for r in json.loads(out)}
    assert "knowledge:reference/glossary" in ids
    assert "knowledge:_archive/old" not in ids


def test_status_active_excludes_archived(capsys, db):
    rc = main(["--db", str(db), "list", "--kind", "knowledge", "--json"])
    out = capsys.readouterr().out
    assert rc == 0
    ids = {r["id"] for r in json.loads(out)}
    assert "knowledge:reference/glossary" in ids
    assert "knowledge:_archive/old" not in ids


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
