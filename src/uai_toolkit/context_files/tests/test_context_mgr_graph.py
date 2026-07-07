#!/usr/bin/env python3
"""
test_context_mgr_graph.py — the `graph` verb (todo_0331 Phase 1, Link Matrix).

``ContextIndex.graph()`` returns the WHOLE reference graph in one shot so the UI
(Link Matrix tab) can fetch once and compute connectivity client-side:

    {items:[{id,kind,name,title,loader,scope,status}], edges:[{src_id,dst_id,edge_type}]}

These tests build a small fixture tree (a profile -> role -> {instruction,
skill -> instruction} multi-path graph, plus an orphan, a global, and a brief)
and assert that:
  - item rows have exactly the documented lightweight shape (with derived loader),
  - item count == active-item total == sum of reindex's items_by_kind,
  - edge count == reindex's `edges` count, and edges carry the right edge_type,
  - dangling edges are still present (so the UI can flag dangling sources),
  - the CLI `graph --json` returns the same shape.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Make the parent module importable.
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from uai_toolkit.context_files import context_mgr  # noqa: E402
from uai_toolkit.context_files.context_mgr import ContextIndex, main  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture tree (mirrors test_context_mgr_additions; a multi-path leaf + a
# deliberate dangling reference to exercise the unresolved-edge path).
# ---------------------------------------------------------------------------

GLOSSARY_MD = """\
---
title: Glossary
summary: Term to file mapping.
---
# Glossary
"""

CODING_YML = """\
metadata:
  title: Coding Standards
  description: How we write code.
"""

LONELY_MD = """\
---
title: Lonely Note
summary: Nothing references this knowledge file.
---
# Lonely
"""

# dev references coding directly AND a missing knowledge file (dangling).
DEV_ROLE_YML = """\
name: Developer
description: Writes code.
context_files:
  knowledge:
    - ai_context_files/knowledge/reference/glossary
    - ai_context_files/knowledge/reference/missing_one
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
"""

GLOBAL_YML = """\
name: Global Base
description: Core traits for all agents.
context_files:
  knowledge:
    - ai_context_files/knowledge/reference/glossary
"""

BRIEF_YML = """\
brief_meta:
  name: MyBrief
  description: A test brief.
  status: active
"""


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "ai_root"

    def write(rel: str, content: str) -> None:
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)

    write("ai_general/ai_context_files/knowledge/reference/glossary.md", GLOSSARY_MD)
    write("ai_general/ai_context_files/knowledge/orphan/lonely.md", LONELY_MD)
    write("ai_general/ai_context_files/instructions/rules/coding.yml", CODING_YML)
    write("ai_general/ai_profiles/roles/dev.yml", DEV_ROLE_YML)
    write("ai_general/ai_profiles/skills/helper.yml", HELPER_SKILL_YML)
    write("ai_general/ai_profiles/architect_developer.yml", PROFILE_YML)
    write("ai_general/ai_profiles/globals/base.yml", GLOBAL_YML)
    write("ai_general/data/session_briefs/MyBrief.yml", BRIEF_YML)
    return root


@pytest.fixture
def idx(tmp_path, tree, monkeypatch):
    monkeypatch.setattr(context_mgr, "AI_ROOT", tree)
    index = ContextIndex(db_path=tmp_path / "context.db", ai_root=tree)
    index.reindex()
    return index


def _cli(capsys, db, *args):
    rc = main(["--db", str(db), *args])
    out = capsys.readouterr().out
    return rc, json.loads(out)


# ---------------------------------------------------------------------------
# graph() — shape + counts
# ---------------------------------------------------------------------------

def test_graph_top_level_shape(idx):
    g = idx.graph()
    assert set(g) == {"items", "edges"}
    assert isinstance(g["items"], list)
    assert isinstance(g["edges"], list)


def test_graph_item_row_shape(idx):
    g = idx.graph()
    for it in g["items"]:
        assert set(it) == {
            "id", "kind", "name", "title", "loader", "scope", "status",
            "provenance",
        }
        # provenance is object|null, never the raw `provenance_json` column
        assert "provenance_json" not in it
        assert it["provenance"] is None or isinstance(it["provenance"], dict)
    by_id = {it["id"]: it for it in g["items"]}
    # derived loader per kind
    assert by_id["role:dev"]["loader"] == "mcp"
    assert by_id["profile:architect_developer"]["loader"] == "mcp"
    assert by_id["skill:helper"]["loader"] == "command"
    assert by_id["global:base"]["loader"] == "auto"
    assert by_id["knowledge:reference/glossary"]["loader"] is None
    # the brief carries provenance (object); the leaf knowledge file does not
    assert isinstance(by_id["brief:MyBrief"]["provenance"], dict)
    assert by_id["knowledge:reference/glossary"]["provenance"] is None
    # all returned items are active
    assert all(it["status"] == "active" for it in g["items"])


def test_graph_edge_row_shape_and_types(idx):
    g = idx.graph()
    for e in g["edges"]:
        assert set(e) == {"src_id", "dst_id", "edge_type"}
    pairs = {(e["src_id"], e["dst_id"]): e["edge_type"] for e in g["edges"]}
    # bundle -> bundle is 'composes'; bundle -> leaf is 'references'
    assert pairs[("profile:architect_developer", "role:dev")] == "composes"
    assert pairs[("role:dev", "skill:helper")] == "composes"
    assert pairs[("role:dev", "instruction:rules/coding")] == "references"
    assert pairs[("skill:helper", "instruction:rules/coding")] == "references"


def test_graph_counts_match_reindex(idx):
    counts = idx.reindex()  # idempotent rebuild; returns the canonical counts
    g = idx.graph()
    # all fixture items are active, so item count == sum of items_by_kind
    assert len(g["items"]) == sum(counts["items_by_kind"].values())
    # graph emits every edge, dangling included
    assert len(g["edges"]) == counts["edges"]


def test_graph_includes_dangling_edge(idx):
    g = idx.graph()
    item_ids = {it["id"] for it in g["items"]}
    dangling = [e for e in g["edges"] if e["dst_id"] not in item_ids]
    # the deliberately-missing knowledge ref is present as a dangling edge
    assert any(
        e["src_id"] == "role:dev"
        and e["dst_id"] == "knowledge:reference/missing_one"
        for e in dangling
    )


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_graph_cli_json(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "graph", "--json")
    assert rc == 0
    assert set(data) == {"items", "edges"}
    by_id = {it["id"]: it for it in data["items"]}
    assert by_id["skill:helper"]["loader"] == "command"
    counts = idx.reindex()
    assert len(data["edges"]) == counts["edges"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
