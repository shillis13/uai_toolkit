#!/usr/bin/env python3
"""
test_context_mgr_read.py — Read-side query API + JSON CLI tests.

Phase 1 / Task 3 of the Context Mgr overhaul (todo_0331). Exercises the
read-only query surface that the future UI and sessions consume:
``list_items``, ``get_item``, ``search``, ``refs``, ``tree``, ``resolve``,
``validate`` and ``history`` on ``ContextIndex`` plus the argparse ``main()``
CLI (every verb emits JSON with ``--json`` and honours ``--db``).

The fixture builds a representative tree under ``tmp_path`` (see ``tree``):
a profile -> role -> knowledge/instruction chain, a composed skill, a dangling
role ref, a global-scoped knowledge file, an orphan knowledge file, and a
two-node role cycle.
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

from uai_toolkit.context_files.context_mgr import ContextIndex  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture tree
# ---------------------------------------------------------------------------

GLOSSARY_MD = """\
---
title: Glossary
summary: Term to file mapping for orientation.
---
# Glossary

Body text describing terms and concepts.
"""

OVERVIEW_MD = """\
# Architecture Overview

The system is layered into discrete tiers.
"""

LONELY_MD = """\
---
title: Lonely Note
summary: Nothing references this knowledge file.
---
# Lonely

Orphaned content.
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

CYCLE_A_ROLE_YML = """\
name: Cycle A
description: Points at B.
roles:
  - ai_profiles/roles/cycleb
"""

CYCLE_B_ROLE_YML = """\
name: Cycle B
description: Points back at A.
roles:
  - ai_profiles/roles/cyclea
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

    def write(rel_to_root: str, content: str) -> Path:
        p = root / rel_to_root
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)
        return p

    write("ai_general/ai_context_files/knowledge/reference/glossary.md", GLOSSARY_MD)
    write("ai_general/ai_context_files/knowledge/architecture/overview.md", OVERVIEW_MD)
    write("ai_general/ai_context_files/knowledge/orphan/lonely.md", LONELY_MD)
    write("ai_general/ai_context_files/instructions/rules/coding.yml", CODING_YML)
    write("ai_general/ai_profiles/roles/dev.yml", DEV_ROLE_YML)
    write("ai_general/ai_profiles/roles/cyclea.yml", CYCLE_A_ROLE_YML)
    write("ai_general/ai_profiles/roles/cycleb.yml", CYCLE_B_ROLE_YML)
    write("ai_general/ai_profiles/skills/helper.yml", HELPER_SKILL_YML)
    write("ai_general/ai_profiles/architect_developer.yml", PROFILE_YML)
    write("ai_general/ai_profiles/globals/base.yml", GLOBAL_YML)
    write("ai_general/data/session_briefs/MyBrief.yml", BRIEF_YML)
    write("ai_memories/80_working_memory/manifest.yml", MANIFEST_YML)
    write("ai_memories/80_working_memory/03.yml", SLOT_03_YML)
    return root


@pytest.fixture
def idx(tmp_path, tree):
    """A reindexed ContextIndex over the fixture tree."""
    index = ContextIndex(db_path=tmp_path / "context.db", ai_root=tree)
    index.reindex()
    return index


# ---------------------------------------------------------------------------
# list_items
# ---------------------------------------------------------------------------

def test_list_items_filter_by_kind(idx):
    rows = idx.list_items(kind="role")
    ids = {r["id"] for r in rows}
    assert ids == {"role:dev", "role:cyclea", "role:cycleb"}
    # documented shape (includes the derived `loader` field)
    keys = set(rows[0].keys())
    assert keys == {
        "id", "kind", "name", "title", "summary",
        "status", "scope", "path", "size_bytes", "updated_at", "loader",
        "provenance",
    }
    # roles are MCP-loaded bundles
    assert rows[0]["loader"] == "mcp"
    # provenance is normalized to an object|null, never a raw json string
    assert rows[0]["provenance"] is None
    # the raw DB column name never leaks into API output
    assert "provenance_json" not in rows[0]


def test_list_items_filter_by_scope(idx):
    rows = idx.list_items(scope="global")
    ids = {r["id"] for r in rows}
    assert ids == {"knowledge:reference/glossary"}


def test_list_items_limit_offset(idx):
    all_k = idx.list_items(kind="knowledge")
    assert len(all_k) == 3
    page = idx.list_items(kind="knowledge", limit=1, offset=1)
    assert len(page) == 1
    assert page[0]["id"] == all_k[1]["id"]


# ---------------------------------------------------------------------------
# get_item
# ---------------------------------------------------------------------------

def test_get_item_counts(idx):
    item = idx.get_item("role:dev")
    assert item is not None
    assert item["id"] == "role:dev"
    # dev references glossary, overview, coding, helper -> 4 outbound
    assert item["counts"]["outbound"] == 4
    # dev is referenced by the profile -> 1 inbound
    assert item["counts"]["inbound"] == 1


def test_get_item_provenance_parsed(idx):
    item = idx.get_item("brief:MyBrief")
    assert item is not None
    # provenance is exposed as a parsed object under `provenance` (not the raw
    # `provenance_json` TEXT column, which must not leak into API output).
    assert "provenance_json" not in item
    assert isinstance(item["provenance"], dict)
    assert item["provenance"].get("condenser_session")


def test_get_item_missing(idx):
    assert idx.get_item("role:does_not_exist") is None


# ---------------------------------------------------------------------------
# provenance contract — uniform across every read path (todo_0331)
# ---------------------------------------------------------------------------

def _assert_provenance_contract(row: dict) -> None:
    """A returned item row exposes `provenance` (object|null), never raw text."""
    assert "provenance_json" not in row, "raw DB column leaked into API output"
    assert "provenance" in row
    prov = row["provenance"]
    assert prov is None or isinstance(prov, dict), (
        "provenance must be a parsed object or None, never a raw json string: "
        "{!r}".format(prov)
    )


def test_provenance_contract_get_item(idx):
    # brief has provenance -> object; leaf knowledge file -> None.
    brief = idx.get_item("brief:MyBrief")
    _assert_provenance_contract(brief)
    assert isinstance(brief["provenance"], dict)
    assert brief["provenance"].get("condenser_session")

    leaf = idx.get_item("knowledge:reference/glossary")
    _assert_provenance_contract(leaf)
    assert leaf["provenance"] is None


def test_provenance_contract_list_items(idx):
    rows = idx.list_items(status="all")
    assert rows
    for r in rows:
        _assert_provenance_contract(r)
    by_id = {r["id"]: r for r in rows}
    assert isinstance(by_id["brief:MyBrief"]["provenance"], dict)
    assert by_id["knowledge:reference/glossary"]["provenance"] is None


def test_provenance_contract_children(idx):
    # dev's children are non-brief leaves/bundles -> all provenance None.
    kids = idx.children("role:dev")
    assert kids
    for c in kids:
        _assert_provenance_contract(c)
        assert c["provenance"] is None


def test_provenance_contract_graph(idx):
    g = idx.graph()
    assert g["items"]
    for it in g["items"]:
        _assert_provenance_contract(it)
    by_id = {it["id"]: it for it in g["items"]}
    assert isinstance(by_id["brief:MyBrief"]["provenance"], dict)
    assert by_id["knowledge:reference/glossary"]["provenance"] is None


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------

def test_search_by_title(idx):
    rows = idx.search("Glossary")
    ids = {r["id"] for r in rows}
    assert "knowledge:reference/glossary" in ids


def test_search_by_content(idx):
    rows = idx.search("layered")
    ids = {r["id"] for r in rows}
    assert "knowledge:architecture/overview" in ids


def test_search_kind_filter(idx):
    rows = idx.search("code", kind="instruction")
    assert all(r["kind"] == "instruction" for r in rows)


# ---------------------------------------------------------------------------
# refs
# ---------------------------------------------------------------------------

def test_refs_out_with_resolved_flag(idx):
    rows = idx.refs("profile:architect_developer", direction="out")
    by_dst = {r["dst_id"]: r for r in rows}
    assert by_dst["role:dev"]["resolved"] is True
    assert by_dst["role:dev"]["edge_type"] == "composes"
    # ghost is a dangling ref -> unresolved
    assert by_dst["role:ghost"]["resolved"] is False


def test_refs_in(idx):
    rows = idx.refs("knowledge:reference/glossary", direction="in")
    srcs = {r["src_id"] for r in rows}
    assert "role:dev" in srcs
    assert "global:base" in srcs


def test_refs_both(idx):
    rows = idx.refs("role:dev", direction="both")
    srcs = {r["src_id"] for r in rows}
    dsts = {r["dst_id"] for r in rows}
    # outbound dst + inbound src both present
    assert "knowledge:reference/glossary" in dsts
    assert "profile:architect_developer" in srcs


# ---------------------------------------------------------------------------
# tree
# ---------------------------------------------------------------------------

def test_tree_nests_composes_then_references(idx):
    t = idx.tree("profile:architect_developer")
    assert t["id"] == "profile:architect_developer"
    children = {c["id"]: c for c in t["children"]}
    assert "role:dev" in children
    # ghost is unresolved
    assert children["role:ghost"].get("unresolved") is True
    # dev expands into knowledge/instruction leaves
    dev_kids = {c["id"] for c in children["role:dev"]["children"]}
    assert "knowledge:reference/glossary" in dev_kids
    assert "skill:helper" in dev_kids


def test_tree_depth_cap(idx):
    t = idx.tree("role:dev", max_depth=1)
    # depth 1 -> direct children present, but their children truncated
    helper = next(c for c in t["children"] if c["id"] == "skill:helper")
    assert helper.get("truncated") is True
    assert helper["children"] == []


def test_tree_cycle_guard(idx):
    t = idx.tree("role:cyclea")
    b = next(c for c in t["children"] if c["id"] == "role:cycleb")
    a_again = next(c for c in b["children"] if c["id"] == "role:cyclea")
    assert a_again.get("cycle") is True


# ---------------------------------------------------------------------------
# resolve
# ---------------------------------------------------------------------------

def test_resolve_flattens_dedups_orders(idx):
    res = idx.resolve("profile:architect_developer")
    resolved_ids = [r["id"] for r in res["resolved"]]
    # order: glossary, overview, coding (helper re-references coding -> deduped)
    assert resolved_ids == [
        "knowledge:reference/glossary",
        "knowledge:architecture/overview",
        "instruction:rules/coding",
    ]
    # leaf entry shape now carries the contributing composition chains (`via`)
    assert set(res["resolved"][0].keys()) == {"id", "kind", "name", "path", "via"}
    # glossary is reached by a single chain: profile -> role:dev
    assert res["resolved"][0]["via"] == [["profile:architect_developer", "role:dev"]]
    # coding is reached by TWO chains (dev directly + via skill:helper) -> count 2
    coding = next(r for r in res["resolved"] if r["id"] == "instruction:rules/coding")
    assert coding["count"] == 2
    assert ["profile:architect_developer", "role:dev"] in coding["via"]
    assert ["profile:architect_developer", "role:dev", "skill:helper"] in coding["via"]
    # ghost was a dangling composition ref -> unresolved
    assert "role:ghost" in res["unresolved"]
    assert res["total_size_bytes"] > 0


# ---------------------------------------------------------------------------
# validate
# ---------------------------------------------------------------------------

def test_validate_dangling_and_orphans(idx):
    v = idx.validate()
    dangling = {(d["src_id"], d["dst_id"]) for d in v["dangling"]}
    assert ("profile:architect_developer", "role:ghost") in dangling
    # orphan entries are now {id, kind, severity} dicts
    orphans = {o["id"]: o for o in v["orphans"]}
    # lonely knowledge has zero inbound and is not global-scoped -> orphan
    assert "knowledge:orphan/lonely" in orphans
    assert orphans["knowledge:orphan/lonely"]["severity"] == "warn"
    # glossary is global-scoped -> NOT an orphan even with refs
    assert "knowledge:reference/glossary" not in orphans


# ---------------------------------------------------------------------------
# history
# ---------------------------------------------------------------------------

def test_history_empty_for_fresh_item(idx):
    assert idx.history("role:dev") == []


# ---------------------------------------------------------------------------
# CLI — invoke main() with argv, capture JSON from stdout
# ---------------------------------------------------------------------------

def _cli(capsys, db, *args):
    from uai_toolkit.context_files.context_mgr import main
    rc = main(["--db", str(db), *args])
    out = capsys.readouterr().out
    return rc, json.loads(out)


def test_cli_list_json(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "list", "--kind", "role", "--json")
    assert rc == 0
    assert isinstance(data, list)
    assert {r["id"] for r in data} == {"role:dev", "role:cyclea", "role:cycleb"}


def test_cli_get_json(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "get", "role:dev", "--json")
    assert rc == 0
    assert data["id"] == "role:dev"
    assert "counts" in data


def test_cli_search_json(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "search", "Glossary", "--json")
    assert rc == 0
    assert any(r["id"] == "knowledge:reference/glossary" for r in data)


def test_cli_refs_json(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "refs", "profile:architect_developer", "--out", "--json")
    assert rc == 0
    assert any(r["dst_id"] == "role:ghost" and r["resolved"] is False for r in data)


def test_cli_tree_json(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "tree", "profile:architect_developer", "--json")
    assert rc == 0
    assert data["id"] == "profile:architect_developer"
    assert "children" in data


def test_cli_resolve_json(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "resolve", "profile:architect_developer", "--json")
    assert rc == 0
    assert [r["id"] for r in data["resolved"]] == [
        "knowledge:reference/glossary",
        "knowledge:architecture/overview",
        "instruction:rules/coding",
    ]


def test_cli_preview_alias(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "preview", "profile:architect_developer", "--json")
    assert rc == 0
    assert "resolved" in data


def test_cli_validate_json(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "validate", "--json")
    assert rc == 0
    assert "dangling" in data and "orphans" in data
    orphan_ids = {o["id"] for o in data["orphans"]}
    assert "knowledge:orphan/lonely" in orphan_ids


def test_cli_history_json(idx, capsys):
    rc, data = _cli(capsys, idx.db_path, "history", "role:dev", "--json")
    assert rc == 0
    assert data == []


def test_cli_subprocess_smoke(idx):
    """End-to-end: the module runs as a script and emits valid JSON."""
    proc = subprocess.run(
        [sys.executable, str(_SCRIPT_DIR / "context_mgr.py"),
         "--db", str(idx.db_path), "list", "--kind", "profile", "--json"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert any(r["id"] == "profile:architect_developer" for r in data)
