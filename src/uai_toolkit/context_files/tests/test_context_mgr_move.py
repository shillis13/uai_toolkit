#!/usr/bin/env python3
"""
test_context_mgr_move.py — move/rename (referential-integrity write) tests.

Phase 2 / Task 3 of the Context Mgr overhaul (todo_0331). This is the
DESTRUCTIVE CENTERPIECE: ``move`` renames and/or relocates an item on disk and
then repoints EVERY inbound reference (every bundle whose YAML referenced the
item) to the item's new path, updates the item row id old→new, and updates every
edge row's ``src_id``/``dst_id`` that referenced the old id.

``move(item_id, *, new_category=None, new_name=None, by=None, dry_run=False)``
  - rename (``new_name``) and/or relocate (``new_category``); either or both;
  - computes the new path + new id (id = ``kind:new_name`` when name changes;
    for a context file the path also changes with category/name; for a bundle a
    name change moves the .yml);
  - rejects when the target path or new id already exists (collision);
  - finds ALL inbound edges (every item referencing this one) and repoints them;
  - ``dry_run=True`` returns a PLAN ``{ok, from:{id,path}, to:{id,path},
    inbound:[{src_id, ref_old, ref_new}], dry_run:true}`` and writes NOTHING;
  - apply: writes every inbound bundle's YAML, moves the file (and any
    ``*_latest`` symlink that points to it), then updates the index (rename the
    item row id + repoint every edge src/dst), records a changelog op="move".

CRITICAL — the round-trip test is the correctness GATE: after ``move`` then a
full reindex-from-scratch, the edge set is IDENTICAL with ZERO dangling refs.
This proves disk and index agree (every previously-resolving inbound ref now
resolves to the new location).

SAFETY: every test builds against a TEMP fixture tree + temp DB. No real library
(``ai_general/ai_context_files/``, ``ai_profiles/``) or the real
``data/context.db`` is ever touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from uai_toolkit.context_files.context_mgr import ContextIndex  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures — a knowledge file referenced by 2 roles + a role referenced by a
# profile, under tmp_path. Never the real library.
# ---------------------------------------------------------------------------

# Two roles both reference the same knowledge leaf (glossary). Repointing it
# must touch BOTH roles' YAML.
ROLE_DEV = """\
name: Dev
description: A developer role.

context_files:
  reference:
    - ai_context_files/knowledge/reference/glossary
"""

ROLE_ARCHITECT = """\
name: Architect
description: An architect role.

context_files:
  reference:
    - ai_context_files/knowledge/reference/glossary
"""

# A profile references the dev role (so renaming the role repoints the profile).
PROFILE_TEAM = """\
name: Team
description: A team profile.

roles:
  - ai_profiles/roles/dev
"""

KNOW_GLOSSARY = "---\ntitle: Glossary\n---\n\n# Glossary\n"


@pytest.fixture
def tree(tmp_path):
    """Build a minimal fixture context tree and return its ai_root.

    Graph:
      role:dev       --references--> knowledge:reference/glossary
      role:architect --references--> knowledge:reference/glossary
      profile:team   --composes-->   role:dev
    """
    root = tmp_path / "ai_root"

    def write(rel, text):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    write("ai_general/ai_profiles/roles/dev.yml", ROLE_DEV)
    write("ai_general/ai_profiles/roles/architect.yml", ROLE_ARCHITECT)
    write("ai_general/ai_profiles/team.yml", PROFILE_TEAM)
    write(
        "ai_general/ai_context_files/knowledge/reference/glossary.md", KNOW_GLOSSARY
    )
    return root


def _make_index(tmp_path, root) -> ContextIndex:
    idx = ContextIndex(db_path=tmp_path / "context.db", ai_root=root)
    idx.reindex()
    return idx


def _all_edges(idx):
    """Return the FULL edge set as a sorted set of (src, dst, etype) tuples."""
    with idx._connect() as conn:
        return {
            (r["src_id"], r["dst_id"], r["edge_type"])
            for r in conn.execute(
                "SELECT src_id, dst_id, edge_type FROM edges"
            ).fetchall()
        }


def _item_ids(idx):
    with idx._connect() as conn:
        return {r["id"] for r in conn.execute("SELECT id FROM items").fetchall()}


def _changelog(idx, op=None):
    sql = "SELECT * FROM changelog"
    params = []
    if op is not None:
        sql += " WHERE op=?"
        params.append(op)
    with idx._connect() as conn:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]


def _roundtrip_edges(idx, root, tmp_path):
    """Build a fresh index from scratch over the same disk; return its edges."""
    fresh = ContextIndex(db_path=tmp_path / "context_fresh.db", ai_root=root)
    fresh.reindex()
    return _all_edges(fresh), fresh.validate()


# ---------------------------------------------------------------------------
# rename a knowledge leaf -> 2 inbound roles repointed, round-trips.
# ---------------------------------------------------------------------------

def test_rename_knowledge_repoints_both_roles_and_roundtrips(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    old_id = "knowledge:reference/glossary"
    assert old_id in _item_ids(idx)
    # Both roles reference it.
    edges = _all_edges(idx)
    assert ("role:dev", old_id, "references") in edges
    assert ("role:architect", old_id, "references") in edges

    res = idx.move(old_id, new_name="reference/lexicon")
    assert res["ok"] is True, res
    new_id = "knowledge:reference/lexicon"
    assert res["to"]["id"] == new_id

    # File moved on disk.
    assert not (tree / "ai_general/ai_context_files/knowledge/reference/glossary.md").exists()
    assert (tree / "ai_general/ai_context_files/knowledge/reference/lexicon.md").exists()

    # Item id updated in the index.
    ids = _item_ids(idx)
    assert new_id in ids
    assert old_id not in ids

    # BOTH roles' edges repointed; no edge still points at the old id.
    edges = _all_edges(idx)
    assert ("role:dev", new_id, "references") in edges
    assert ("role:architect", new_id, "references") in edges
    assert not any(dst == old_id for (_s, dst, _t) in edges)

    # Both roles' YAML on disk now reference the new path.
    dev_yaml = (tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    arch_yaml = (tree / "ai_general/ai_profiles/roles/architect.yml").read_text()
    assert "ai_context_files/knowledge/reference/lexicon" in dev_yaml
    assert "glossary" not in dev_yaml
    assert "ai_context_files/knowledge/reference/lexicon" in arch_yaml
    assert "glossary" not in arch_yaml

    # ROUND-TRIP GATE: fresh reindex yields the SAME edges, no dangling.
    rt_edges, rt_validate = _roundtrip_edges(idx, tree, tmp_path)
    assert rt_edges == _all_edges(idx)
    assert rt_validate["dangling"] == []


# ---------------------------------------------------------------------------
# recategorize a knowledge leaf (move to a new category dir) -> repoint + RT.
# ---------------------------------------------------------------------------

def test_recategorize_knowledge_repoints_and_roundtrips(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    old_id = "knowledge:reference/glossary"

    res = idx.move(old_id, new_category="terminology")
    assert res["ok"] is True, res
    # name stays glossary; category dir changes -> id = kind:terminology/glossary
    new_id = "knowledge:terminology/glossary"
    assert res["to"]["id"] == new_id

    assert not (tree / "ai_general/ai_context_files/knowledge/reference/glossary.md").exists()
    assert (tree / "ai_general/ai_context_files/knowledge/terminology/glossary.md").exists()

    edges = _all_edges(idx)
    assert ("role:dev", new_id, "references") in edges
    assert ("role:architect", new_id, "references") in edges
    assert not any(dst == old_id for (_s, dst, _t) in edges)

    dev_yaml = (tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    assert "ai_context_files/knowledge/terminology/glossary" in dev_yaml
    assert "reference/glossary" not in dev_yaml

    rt_edges, rt_validate = _roundtrip_edges(idx, tree, tmp_path)
    assert rt_edges == _all_edges(idx)
    assert rt_validate["dangling"] == []


# ---------------------------------------------------------------------------
# rename a role (bundle) -> inbound profile repointed + own outbound preserved.
# ---------------------------------------------------------------------------

def test_rename_role_repoints_profile_and_preserves_outbound(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    old_id = "role:dev"
    # role:dev references the glossary (outbound) and profile:team composes it (inbound).
    edges = _all_edges(idx)
    assert ("profile:team", old_id, "composes") in edges
    assert (old_id, "knowledge:reference/glossary", "references") in edges

    res = idx.move(old_id, new_name="engineer")
    assert res["ok"] is True, res
    new_id = "role:engineer"
    assert res["to"]["id"] == new_id

    # Bundle .yml moved.
    assert not (tree / "ai_general/ai_profiles/roles/dev.yml").exists()
    assert (tree / "ai_general/ai_profiles/roles/engineer.yml").exists()

    ids = _item_ids(idx)
    assert new_id in ids and old_id not in ids

    edges = _all_edges(idx)
    # Inbound profile edge repointed (src unchanged, dst now new_id).
    assert ("profile:team", new_id, "composes") in edges
    # Outbound edge PRESERVED under the new src id.
    assert (new_id, "knowledge:reference/glossary", "references") in edges
    # No edge references the old id at all.
    assert not any(old_id in (s, d) for (s, d, _t) in edges)

    team_yaml = (tree / "ai_general/ai_profiles/team.yml").read_text()
    assert "ai_profiles/roles/engineer" in team_yaml
    assert "ai_profiles/roles/dev" not in team_yaml

    rt_edges, rt_validate = _roundtrip_edges(idx, tree, tmp_path)
    assert rt_edges == _all_edges(idx)
    assert rt_validate["dangling"] == []


# ---------------------------------------------------------------------------
# dry_run returns the correct plan and writes NOTHING.
# ---------------------------------------------------------------------------

def test_dry_run_plan_writes_nothing(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    old_id = "knowledge:reference/glossary"

    before_edges = _all_edges(idx)
    before_dev = (tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    before_arch = (tree / "ai_general/ai_profiles/roles/architect.yml").read_text()

    plan = idx.move(old_id, new_name="reference/lexicon", dry_run=True)
    assert plan["ok"] is True
    assert plan["dry_run"] is True
    assert plan["from"]["id"] == old_id
    assert plan["from"]["path"] == "ai_general/ai_context_files/knowledge/reference/glossary.md"
    assert plan["to"]["id"] == "knowledge:reference/lexicon"
    assert plan["to"]["path"] == "ai_general/ai_context_files/knowledge/reference/lexicon.md"

    # inbound plan: 2 referrers, with old + new ref strings.
    inbound = {(e["src_id"], e["ref_old"], e["ref_new"]) for e in plan["inbound"]}
    assert ("role:dev",
            "ai_context_files/knowledge/reference/glossary",
            "ai_context_files/knowledge/reference/lexicon") in inbound
    assert ("role:architect",
            "ai_context_files/knowledge/reference/glossary",
            "ai_context_files/knowledge/reference/lexicon") in inbound

    # NOTHING changed: edges, files, item ids all intact.
    assert _all_edges(idx) == before_edges
    assert (tree / "ai_general/ai_profiles/roles/dev.yml").read_text() == before_dev
    assert (tree / "ai_general/ai_profiles/roles/architect.yml").read_text() == before_arch
    assert (tree / "ai_general/ai_context_files/knowledge/reference/glossary.md").exists()
    assert not (tree / "ai_general/ai_context_files/knowledge/reference/lexicon.md").exists()
    assert old_id in _item_ids(idx)
    assert not _changelog(idx, op="move")


# ---------------------------------------------------------------------------
# rejects: missing item, target-path collision, new-id collision.
# ---------------------------------------------------------------------------

def test_reject_missing_item(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.move("knowledge:does/not_exist", new_name="reference/x")
    assert res["ok"] is False
    assert "no such item" in res["error"]


def test_reject_target_path_exists(tmp_path, tree):
    # Add a second knowledge file; renaming glossary onto it must be rejected.
    (tree / "ai_general/ai_context_files/knowledge/reference/other.md").write_text(
        "---\ntitle: Other\n---\n\n# Other\n"
    )
    idx = _make_index(tmp_path, tree)
    res = idx.move("knowledge:reference/glossary", new_name="reference/other")
    assert res["ok"] is False
    assert "exist" in res["error"].lower()
    # Nothing moved.
    assert (tree / "ai_general/ai_context_files/knowledge/reference/glossary.md").exists()


def test_reject_no_change(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.move("knowledge:reference/glossary")
    assert res["ok"] is False
    assert "new_name" in res["error"] or "new_category" in res["error"]


# ---------------------------------------------------------------------------
# a *_latest symlink pointing at the moved file is updated.
# ---------------------------------------------------------------------------

def test_latest_symlink_updated(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    kdir = tree / "ai_general/ai_context_files/knowledge/reference"
    link = kdir / "glossary_latest.md"
    # Relative symlink pointing at the target file.
    link.symlink_to("glossary.md")
    assert link.is_symlink()

    res = idx.move("knowledge:reference/glossary", new_name="reference/lexicon")
    assert res["ok"] is True, res

    # The symlink now points at the new filename (and still resolves).
    assert link.is_symlink()
    assert Path(link.readlink()).name == "lexicon.md"
    assert link.resolve() == (kdir / "lexicon.md").resolve()


# ---------------------------------------------------------------------------
# changelog records the move op.
# ---------------------------------------------------------------------------

def test_changelog_records_move(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.move("knowledge:reference/glossary", new_name="reference/lexicon", by="tester")
    rows = _changelog(idx, op="move")
    assert rows, "expected a move changelog row"
    # The primary move row is keyed by the NEW id and records old->new.
    primary = [r for r in rows if r["item_id"] == "knowledge:reference/lexicon"]
    assert primary
    assert primary[0]["changed_by"] == "tester"
    assert "glossary" in (primary[0]["old_value"] or "")
    assert "lexicon" in (primary[0]["new_value"] or "")
