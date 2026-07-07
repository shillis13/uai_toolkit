#!/usr/bin/env python3
"""
test_context_mgr_reindex.py — Reindex tests for the Context Mgr SQLite index.

Phase 1 / Task 2 of the Context Mgr overhaul (todo_0331). Verifies that
``ContextIndex.reindex`` scans an on-disk context tree, classifies items into
the 8 kinds, populates ``items`` with stable ``<kind>:<name>`` ids + content
hashes, and rebuilds the ``edges`` reference graph (composes vs references,
ordered, with dangling refs detectable as unresolved). ``dry_run`` must write
nothing, and re-running must be idempotent.

The fixture builds a small but representative tree under ``tmp_path``:
- two knowledge files + one instruction file (leaf content),
- a role that references them (and a skill),
- a profile that composes the role (plus a dangling role ref),
- a global that references a knowledge file (so it gets scope='global'),
- a session brief, and a working-memory manifest + slot.
"""

from __future__ import annotations

import hashlib
import sqlite3
import sys
from pathlib import Path

import pytest

# Make the parent module importable
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from uai_toolkit.context_files.context_mgr import ContextIndex


# ---------------------------------------------------------------------------
# Fixture tree
# ---------------------------------------------------------------------------

GLOSSARY_MD = """\
---
title: Glossary
summary: Term to file mapping for orientation.
---
# Glossary

Body text describing terms.
"""

OVERVIEW_MD = """\
# Architecture Overview

The system is layered.
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
    - ai_context_files/knowledge/architecture/overview
  procedures:
    - ai_context_files/instructions/rules/coding
skills:
  - helper
"""

HELPER_SKILL_YML = """\
metadata:
  name: helper
  description: A helper skill.
context_files:
  procedures:
    - ai_context_files/instructions/rules/coding
"""

PROFILE_YML = """\
name: Architect Developer
description: Designs and builds.
roles:
  - ai_profiles/roles/dev
  - ai_profiles/roles/ghost
"""

GLOBAL_YML = """\
name: Global Base
description: Core traits for all agents.
context_files:
  knowledge:
    - path: ai_context_files/knowledge/reference/glossary
      purpose: terms
"""

BRIEF_YML = """\
brief_meta:
  name: MyBrief
  description: A test brief.
  sources:
    - 019ea0bc-1d19-7232-aed5-fe71bab78599
  condenser_session: 20260509_230700_e269cf39_cod
  created: '2026-06-01T00:00:00+00:00'
  status: active
"""

MANIFEST_YML = """\
metadata:
  title: Working Memory Manifest
slot_structure:
  3:
    name: user_model
    purpose: Who the user is.
"""

SLOT_03_YML = """\
observations:
  - ts: 2026-01-01
    content: hello
"""


@pytest.fixture
def tree(tmp_path):
    """Build a fixture context tree under tmp_path and return its ai_root."""
    root = tmp_path / "ai_root"
    g = root / "ai_general"

    def write(rel_to_root: str, content: str) -> Path:
        p = root / rel_to_root
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    write("ai_general/ai_context_files/knowledge/reference/glossary.md", GLOSSARY_MD)
    write("ai_general/ai_context_files/knowledge/architecture/overview.md", OVERVIEW_MD)
    write("ai_general/ai_context_files/instructions/rules/coding.yml", CODING_YML)
    write("ai_general/ai_profiles/roles/dev.yml", DEV_ROLE_YML)
    write("ai_general/ai_profiles/skills/helper.yml", HELPER_SKILL_YML)
    write("ai_general/ai_profiles/architect_developer.yml", PROFILE_YML)
    write("ai_general/ai_profiles/globals/base.yml", GLOBAL_YML)
    write("ai_general/data/session_briefs/MyBrief.yml", BRIEF_YML)
    write("ai_memories/80_working_memory/manifest.yml", MANIFEST_YML)
    write("ai_memories/80_working_memory/03.yml", SLOT_03_YML)
    return root


def _make_index(tmp_path, root) -> ContextIndex:
    return ContextIndex(db_path=tmp_path / "context.db", ai_root=root)


def _rows(idx, sql, params=()):
    with idx._connect() as conn:
        return conn.execute(sql, params).fetchall()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_items_by_kind(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    counts = idx.reindex()
    by_kind = counts["items_by_kind"]
    assert by_kind.get("knowledge") == 2
    assert by_kind.get("instruction") == 1
    assert by_kind.get("role") == 1
    assert by_kind.get("skill") == 1
    assert by_kind.get("profile") == 1
    assert by_kind.get("global") == 1
    assert by_kind.get("brief") == 1
    assert by_kind.get("memory") == 1


def test_item_ids_and_fields(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.reindex()
    rows = {r["id"]: r for r in _rows(idx, "SELECT * FROM items")}
    assert "knowledge:reference/glossary" in rows
    g = rows["knowledge:reference/glossary"]
    assert g["kind"] == "knowledge"
    assert g["name"] == "reference/glossary"
    # path is relative to AI_ROOT
    assert g["path"] == "ai_general/ai_context_files/knowledge/reference/glossary.md"
    assert g["title"] == "Glossary"
    assert g["summary"] == "Term to file mapping for orientation."
    assert g["content_hash"]
    # memory slot picks up its name/purpose from the manifest
    m = rows["memory:03"]
    assert m["title"] == "user_model"
    assert m["summary"] == "Who the user is."
    # brief carries provenance
    b = rows["brief:MyBrief"]
    assert b["provenance_json"]
    assert "condenser_session" in b["provenance_json"]


def test_edges_role_to_knowledge_and_profile_to_role(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.reindex()
    edges = _rows(idx, "SELECT * FROM edges")
    e = {(r["src_id"], r["dst_id"]): r for r in edges}

    # role -> knowledge is a 'references' edge
    key = ("role:dev", "knowledge:reference/glossary")
    assert key in e
    assert e[key]["edge_type"] == "references"

    # role -> skill is a 'composes' edge
    assert e[("role:dev", "skill:helper")]["edge_type"] == "composes"

    # profile -> role is a 'composes' edge, ordered (dev=0, ghost=1)
    pk = ("profile:architect_developer", "role:dev")
    assert pk in e
    assert e[pk]["edge_type"] == "composes"
    assert e[pk]["order_idx"] == 0
    assert e[("profile:architect_developer", "role:ghost")]["order_idx"] == 1


def test_global_scope_applied(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.reindex()
    rows = {r["id"]: r for r in _rows(idx, "SELECT * FROM items")}
    # glossary is referenced by the global -> scope global
    assert rows["knowledge:reference/glossary"]["scope"] == "global"
    # overview is NOT referenced by a global
    assert rows["knowledge:architecture/overview"]["scope"] != "global"


def test_content_hash_stable(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.reindex()
    p = tree / "ai_general/ai_context_files/knowledge/reference/glossary.md"
    expected = hashlib.sha256(p.read_bytes()).hexdigest()
    row = _rows(idx, "SELECT content_hash FROM items WHERE id=?", ("knowledge:reference/glossary",))[0]
    assert row["content_hash"] == expected
    # Re-running yields the same hash.
    idx.reindex()
    row2 = _rows(idx, "SELECT content_hash FROM items WHERE id=?", ("knowledge:reference/glossary",))[0]
    assert row2["content_hash"] == expected


def test_dry_run_writes_nothing(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    counts = idx.reindex(dry_run=True)
    # counts are still computed
    assert counts["items_by_kind"].get("knowledge") == 2
    assert counts["edges"] > 0
    # but nothing was written
    assert _rows(idx, "SELECT COUNT(*) AS n FROM items")[0]["n"] == 0
    assert _rows(idx, "SELECT COUNT(*) AS n FROM edges")[0]["n"] == 0


def test_idempotent(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    c1 = idx.reindex()
    items1 = _rows(idx, "SELECT COUNT(*) AS n FROM items")[0]["n"]
    edges1 = _rows(idx, "SELECT COUNT(*) AS n FROM edges")[0]["n"]
    c2 = idx.reindex()
    items2 = _rows(idx, "SELECT COUNT(*) AS n FROM items")[0]["n"]
    edges2 = _rows(idx, "SELECT COUNT(*) AS n FROM edges")[0]["n"]
    assert items1 == items2
    assert edges1 == edges2
    assert dict(c1["items_by_kind"]) == dict(c2["items_by_kind"])
    assert c1["edges"] == c2["edges"]
    assert c1["unresolved"] == c2["unresolved"]


def test_dangling_ref_is_unresolved(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    counts = idx.reindex()
    assert counts["unresolved"] >= 1
    # the dangling role edge exists with a best-effort dst id
    e = {(r["src_id"], r["dst_id"]) for r in _rows(idx, "SELECT * FROM edges")}
    assert ("profile:architect_developer", "role:ghost") in e
    # but no item was created for it
    ids = {r["id"] for r in _rows(idx, "SELECT id FROM items")}
    assert "role:ghost" not in ids


def test_fts_populated(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.reindex()
    n = _rows(idx, "SELECT COUNT(*) AS n FROM items_fts")[0]["n"]
    assert n == _rows(idx, "SELECT COUNT(*) AS n FROM items")[0]["n"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
