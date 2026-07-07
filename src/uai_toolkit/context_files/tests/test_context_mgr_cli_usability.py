#!/usr/bin/env python3
"""
test_context_mgr_cli_usability.py — Phase 1 CLI usability polish (todo_0331).

This is a READ-ONLY usability layer over the existing query CLI. It must NOT
change engine semantics, and the ``--json`` output shapes must stay identical
to the prior contract (a future UI consumes them). These tests cover:

- documented enum choices (``--kind bogus`` is rejected by argparse),
- ``list <id>`` listing a node's *direct children* (outbound-edge targets),
- three distinct output formats: human (default), ``--oneline``, ``--json``,
  with ``--json`` preserving the prior machine shape,
- the top-level ``--help-examples`` walkthrough,
- the ``resolve`` description documenting resolved-vs-unresolved.

Tests drive ``main(argv)`` directly and build a tiny fixture tree, mirroring
``test_context_mgr_cli_reindex.py``.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the parent module importable
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from uai_toolkit.context_files import context_mgr  # noqa: E402
from uai_toolkit.context_files.context_mgr import ContextIndex, main  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture tree: role -> knowledge + instruction
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

DEV_ROLE_YML = """\
name: Developer
description: Writes code.
context_files:
  knowledge:
    - ai_context_files/knowledge/reference/glossary
  procedures:
    - ai_context_files/instructions/rules/coding
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
    write("ai_general/ai_profiles/roles/dev.yml", DEV_ROLE_YML)

    monkeypatch.setattr(context_mgr, "AI_ROOT", root)
    db_path = tmp_path / "context.db"
    ContextIndex(db_path=db_path, ai_root=root).reindex()
    return db_path


def _run(capsys, db, *args):
    rc = main(["--db", str(db), *args])
    return rc, capsys.readouterr().out


# ---------------------------------------------------------------------------
# 1. Documented enum choices
# ---------------------------------------------------------------------------

def test_invalid_kind_choice_exits_nonzero(db):
    with pytest.raises(SystemExit) as exc:
        main(["--db", str(db), "list", "--kind", "bogus"])
    assert exc.value.code != 0


def test_valid_kind_choice_accepted(capsys, db):
    rc, out = _run(capsys, db, "list", "--kind", "role", "--json")
    assert rc == 0
    assert any(r["id"] == "role:dev" for r in json.loads(out))


# ---------------------------------------------------------------------------
# 2. list <id> -> the node's direct children
# ---------------------------------------------------------------------------

def test_list_with_id_returns_direct_children(capsys, db):
    rc, out = _run(capsys, db, "list", "role:dev", "--json")
    assert rc == 0
    rows = json.loads(out)
    ids = {r["id"] for r in rows}
    assert ids == {"knowledge:reference/glossary", "instruction:rules/coding"}
    # children rows carry the same lightweight item-row shape as `list`.
    for r in rows:
        assert {"id", "kind", "name", "title", "path"} <= set(r)


def test_children_helper_edge_order(db):
    idx = ContextIndex(db_path=db)
    rows = idx.children("role:dev")
    # Edge order is preserved (glossary referenced before coding).
    assert [r["id"] for r in rows] == [
        "knowledge:reference/glossary",
        "instruction:rules/coding",
    ]


def test_list_without_id_unchanged(capsys, db):
    rc, out = _run(capsys, db, "list", "--kind", "knowledge", "--json")
    assert rc == 0
    rows = json.loads(out)
    assert {r["id"] for r in rows} == {"knowledge:reference/glossary"}


# ---------------------------------------------------------------------------
# 3. Three distinct formats; --json preserves the prior shape
# ---------------------------------------------------------------------------

def test_formats_are_distinct(capsys, db):
    _, human = _run(capsys, db, "list", "--kind", "role")
    _, oneline = _run(capsys, db, "list", "--kind", "role", "--oneline")
    _, js = _run(capsys, db, "list", "--kind", "role", "--json")

    # All three differ from each other.
    assert human != oneline != js
    assert human != js

    # Human + oneline are NOT JSON; they mention the item id readably.
    for txt in (human, oneline):
        with pytest.raises(json.JSONDecodeError):
            json.loads(txt)
        assert "role:dev" in txt

    # oneline is a single line per item (one role -> one line).
    assert len([ln for ln in oneline.strip().splitlines() if ln.strip()]) == 1


def test_json_shape_unchanged(capsys, db):
    """--json must match the library shape byte-for-byte (back-compat for UI)."""
    rc, out = _run(capsys, db, "list", "--kind", "role", "--json")
    assert rc == 0
    parsed = json.loads(out)
    expected = ContextIndex(db_path=db).list_items(kind="role", status="active")
    assert parsed == expected


def test_json_resolve_shape_unchanged(capsys, db):
    rc, out = _run(capsys, db, "resolve", "role:dev", "--json")
    assert rc == 0
    parsed = json.loads(out)
    expected = ContextIndex(db_path=db).resolve("role:dev")
    assert parsed == expected
    assert set(parsed) == {"id", "resolved", "unresolved", "total_size_bytes"}


def test_human_default_is_not_json(capsys, db):
    _, out = _run(capsys, db, "resolve", "role:dev")
    with pytest.raises(json.JSONDecodeError):
        json.loads(out)


# ---------------------------------------------------------------------------
# 4. --help-examples walkthrough
# ---------------------------------------------------------------------------

def test_help_examples_prints_walkthrough(capsys):
    rc = main(["--help-examples"])
    out = capsys.readouterr().out
    assert rc == 0
    # Covers the documented use cases with real, copy-pasteable commands.
    for needle in (
        "list --kind role",
        "resolve profile:",
        "refs ",
        "tree ",
        "search ",
        "validate",
        "reindex",
    ):
        assert needle in out


# ---------------------------------------------------------------------------
# 5. resolve description documents resolved-vs-unresolved
# ---------------------------------------------------------------------------

def test_resolve_help_explains_resolved_unresolved(capsys):
    with pytest.raises(SystemExit):
        main(["resolve", "--help"])
    out = capsys.readouterr().out
    low = out.lower()
    assert "resolved" in low and "unresolved" in low
    assert "leaf" in low  # the flat, de-duplicated leaf context-files


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
