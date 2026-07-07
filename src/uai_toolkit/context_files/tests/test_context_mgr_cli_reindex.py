#!/usr/bin/env python3
"""
test_context_mgr_cli_reindex.py — CLI ``reindex`` verb tests.

Phase 1 of the Context Mgr overhaul (todo_0331). The query CLI exposes only
read-only verbs; the index can only be built by calling ``ContextIndex.reindex``
in-process. This adds the one safe "write" verb: ``context_mgr.py reindex
[--dry-run] [--db PATH] [--json]`` rebuilds the (rebuildable) index from the
on-disk source tree and prints the returned counts dict as JSON.

The CLI constructs ``ContextIndex`` with the default ``ai_root`` (the module
global ``AI_ROOT``), so these tests monkeypatch ``context_mgr.AI_ROOT`` to a
small fixture tree under ``tmp_path`` and drive ``main()`` with argv.
"""

from __future__ import annotations

import json
import subprocess
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
# Fixture tree (a representative subset of the 8 item kinds)
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
def tree(tmp_path):
    """Build a small fixture context tree under tmp_path and return its ai_root."""
    root = tmp_path / "ai_root"

    def write(rel_to_root: str, content: str) -> Path:
        p = root / rel_to_root
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    write("ai_general/ai_context_files/knowledge/reference/glossary.md", GLOSSARY_MD)
    write("ai_general/ai_context_files/instructions/rules/coding.yml", CODING_YML)
    write("ai_general/ai_profiles/roles/dev.yml", DEV_ROLE_YML)
    return root


def _count_items(db_path) -> int:
    idx = ContextIndex(db_path=db_path)
    with idx._connect() as conn:
        return conn.execute("SELECT COUNT(*) AS n FROM items").fetchone()["n"]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_cli_reindex_writes_and_prints_counts(tmp_path, tree, monkeypatch, capsys):
    monkeypatch.setattr(context_mgr, "AI_ROOT", tree)
    db = tmp_path / "context.db"

    # --db is a parent-level argument and precedes the subcommand, consistent
    # with the other verbs (see test_context_mgr_read.py::_cli).
    rc = main(["--db", str(db), "reindex", "--json"])
    out = capsys.readouterr().out

    assert rc == 0
    data = json.loads(out)
    assert "items_by_kind" in data
    assert "edges" in data
    # The fixture role references a knowledge file and an instruction file.
    assert data["items_by_kind"].get("knowledge") == 1
    assert data["items_by_kind"].get("role") == 1
    assert data["edges"] >= 1

    # The index was actually written to disk.
    assert _count_items(db) == data["items_by_kind"]["knowledge"] \
        + data["items_by_kind"].get("instruction", 0) \
        + data["items_by_kind"]["role"]


def test_cli_reindex_dry_run_writes_nothing(tmp_path, tree, monkeypatch, capsys):
    monkeypatch.setattr(context_mgr, "AI_ROOT", tree)
    db = tmp_path / "context.db"

    rc = main(["--db", str(db), "reindex", "--dry-run", "--json"])
    out = capsys.readouterr().out

    assert rc == 0
    data = json.loads(out)
    # Counts are still computed for a dry run.
    assert data["items_by_kind"].get("knowledge") == 1
    assert data["edges"] >= 1
    # ...but nothing was written: the items table is empty.
    assert _count_items(db) == 0


def test_cli_reindex_subprocess_smoke(tmp_path, tree):
    """End-to-end: the module runs as a script and emits valid JSON counts."""
    import os

    db = tmp_path / "context.db"
    env = dict(os.environ, AI_ROOT=str(tree))
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT_DIR / "context_mgr.py"),
         "--db", str(db), "reindex", "--json"],
        capture_output=True, text=True, env=env,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["items_by_kind"].get("role") == 1


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
