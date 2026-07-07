#!/usr/bin/env python3
"""
test_context_mgr_additions.py — Phase 1 engine additions for the UI tool (todo_0331).

Covers the four read/additive engine extensions the new Context Mgr UI needs,
layered on the renamed ``context_mgr`` module (was ``context_index``):

- ``content <id>`` — return an item's on-disk file text.
- ``loader`` — a derived per-kind attribute (mcp/command/auto/None) on item
  rows, plus a ``--loader`` list filter.
- ``resolve`` — each flattened leaf carries the contributing composition chains
  (``via``) and a ``count`` when more than one chain pulls it in.
- ``validate`` — each orphan entry carries a ``severity`` by kind (brief/memory
  = low, knowledge/instruction = warn).

The fixture builds a small tree with a deliberate **multi-path** leaf: a
profile composes a role that both references an instruction file directly AND
composes a skill that references the same instruction file — so the leaf is
reached by two distinct chains.
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
# Fixture tree
# ---------------------------------------------------------------------------

GLOSSARY_MD = """\
---
title: Glossary
summary: Term to file mapping.
---
# Glossary

UNIQUE_BODY_MARKER describing terms and concepts.
"""

CODING_YML = """\
metadata:
  title: Coding Standards
  description: How we write code.
rules:
  - use black
"""

LONELY_MD = """\
---
title: Lonely Note
summary: Nothing references this knowledge file.
---
# Lonely
"""

DEV_ROLE_YML = """\
name: Developer
description: Writes code.
context_files:
  knowledge:
    - ai_context_files/knowledge/reference/glossary
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
    - path: ai_context_files/knowledge/reference/glossary
      purpose: terms
"""

BRIEF_YML = """\
brief_meta:
  name: MyBrief
  description: A test brief.
  status: active
"""


@pytest.fixture
def tree(tmp_path):
    """Build a fixture context tree under tmp_path and return its ai_root."""
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
    # Point the module global at the fixture tree so the CLI path (main() opens
    # a ContextIndex with the default ai_root) reads file bodies from the same
    # tree the index was built from.
    monkeypatch.setattr(context_mgr, "AI_ROOT", tree)
    index = ContextIndex(db_path=tmp_path / "context.db", ai_root=tree)
    index.reindex()
    return index


def _cli(capsys, db, *args):
    rc = main(["--db", str(db), *args])
    out = capsys.readouterr().out
    return rc, json.loads(out)


# ---------------------------------------------------------------------------
# content
# ---------------------------------------------------------------------------

def test_content_returns_file_text(idx):
    d = idx.content("knowledge:reference/glossary")
    assert d is not None
    assert set(d) == {"id", "kind", "path", "content"}
    assert d["id"] == "knowledge:reference/glossary"
    assert d["kind"] == "knowledge"
    assert d["path"] == "ai_general/ai_context_files/knowledge/reference/glossary.md"
    # the actual on-disk body is returned, not just metadata
    assert "UNIQUE_BODY_MARKER" in d["content"]


def test_content_missing_item(idx):
    assert idx.content("knowledge:does_not_exist") is None


def test_content_cli_json(idx, capsys):
    rc, d = _cli(capsys, idx.db_path, "content", "knowledge:reference/glossary", "--json")
    assert rc == 0
    assert "UNIQUE_BODY_MARKER" in d["content"]


# ---------------------------------------------------------------------------
# loader (derived attribute + --loader filter)
# ---------------------------------------------------------------------------

def test_loader_field_per_kind(idx):
    by_id = {r["id"]: r for r in idx.list_items(status="all")}
    assert by_id["role:dev"]["loader"] == "mcp"
    assert by_id["profile:architect_developer"]["loader"] == "mcp"
    assert by_id["skill:helper"]["loader"] == "command"
    assert by_id["global:base"]["loader"] == "auto"
    # leaf content kinds carry no loader
    assert by_id["knowledge:reference/glossary"]["loader"] is None
    assert by_id["instruction:rules/coding"]["loader"] is None
    assert by_id["brief:MyBrief"]["loader"] is None


def test_loader_on_get_item(idx):
    assert idx.get_item("role:dev")["loader"] == "mcp"
    assert idx.get_item("knowledge:reference/glossary")["loader"] is None


def test_loader_filter_mcp(idx):
    rows = idx.list_items(loader="mcp", status="all")
    kinds = {r["kind"] for r in rows}
    assert kinds == {"role", "profile"}


def test_loader_filter_command(idx):
    rows = idx.list_items(loader="command", status="all")
    assert {r["id"] for r in rows} == {"skill:helper"}


def test_loader_filter_auto(idx):
    rows = idx.list_items(loader="auto", status="all")
    assert {r["id"] for r in rows} == {"global:base"}


def test_loader_filter_cli(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "list", "--loader", "command", "--status", "all", "--json")
    assert rc == 0
    assert {r["id"] for r in data} == {"skill:helper"}


def test_loader_invalid_choice_rejected(idx):
    with pytest.raises(SystemExit):
        main(["--db", str(idx.db_path), "list", "--loader", "bogus"])


# ---------------------------------------------------------------------------
# resolve — dedup `via` paths + count
# ---------------------------------------------------------------------------

def test_resolve_via_single_path(idx):
    res = idx.resolve("profile:architect_developer")
    by_id = {r["id"]: r for r in res["resolved"]}
    glossary = by_id["knowledge:reference/glossary"]
    # one contributing chain, no count badge
    assert glossary["via"] == [["profile:architect_developer", "role:dev"]]
    assert "count" not in glossary


def test_resolve_via_multi_path_and_count(idx):
    res = idx.resolve("profile:architect_developer")
    by_id = {r["id"]: r for r in res["resolved"]}
    coding = by_id["instruction:rules/coding"]
    # reached two ways: dev -> coding directly, and dev -> helper -> coding
    assert coding["count"] == 2
    assert ["profile:architect_developer", "role:dev"] in coding["via"]
    assert [
        "profile:architect_developer", "role:dev", "skill:helper"
    ] in coding["via"]
    assert len(coding["via"]) == 2


def test_resolve_top_level_shape_unchanged(idx):
    res = idx.resolve("profile:architect_developer")
    assert set(res) == {"id", "resolved", "unresolved", "total_size_bytes"}


def test_resolve_via_cli_json(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "resolve", "profile:architect_developer", "--json")
    assert rc == 0
    coding = next(r for r in data["resolved"] if r["id"] == "instruction:rules/coding")
    assert coding["count"] == 2


# ---------------------------------------------------------------------------
# validate — orphan severity
# ---------------------------------------------------------------------------

def test_validate_orphan_severity(idx):
    v = idx.validate()
    by_id = {o["id"]: o for o in v["orphans"]}
    # knowledge orphan -> warn
    assert by_id["knowledge:orphan/lonely"]["severity"] == "warn"
    assert by_id["knowledge:orphan/lonely"]["kind"] == "knowledge"
    # the brief is orphan-by-nature -> low
    assert by_id["brief:MyBrief"]["severity"] == "low"


def test_validate_orphan_severity_cli(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "validate", "--json")
    assert rc == 0
    by_id = {o["id"]: o for o in data["orphans"]}
    assert by_id["brief:MyBrief"]["severity"] == "low"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
