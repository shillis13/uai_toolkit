#!/usr/bin/env python3
"""
test_context_mgr_link.py — link/unlink (write graph edits) tests.

Phase 2 / Task 2 of the Context Mgr overhaul (todo_0331). This is the EDITING
CORE: ``link`` / ``unlink`` mutate a *bundle's* YAML (role/profile/skill/global)
to add or remove a reference edge, then incrementally refresh that bundle's
outbound edges in the index and record a ``changelog`` row.

``link(src_id, dst_id)``
  - validates: src exists + is a bundle; dst exists; not self; no cycle; not
    already linked (idempotent — reports already-linked, no dup);
  - edits ``src``'s YAML in the location reindex reads: a leaf dst
    (knowledge/instruction/brief/memory) → under ``context_files`` in the
    bucket for the dst's category; a bundle dst (role/skill) → into the
    ``roles``/``skills`` list, as the extension-less ref reindex resolves;
  - re-parses ONLY ``src``'s refs and replaces only its outbound edge rows
    (incremental — no full reindex); records ``changelog`` op="link".
  - ``dry_run`` returns the planned change WITHOUT writing.

``unlink(src_id, dst_id)`` is the inverse: drops the ref from ``src``'s YAML
(tidying now-empty buckets/lists), refreshes ``src``'s edges, records op="unlink";
rejects when not currently linked.

CRITICAL: the round-trip test is the correctness gate — after ``link`` then a
full reindex-from-scratch, the same edge must exist (proving the YAML written is
exactly what reindex parses back).

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
# Fixtures — a minimal bundle+leaf tree under tmp_path; never the real library.
# ---------------------------------------------------------------------------

ROLE_DEV = """\
name: Dev
description: A developer role.

context_files:
  methods:
    - ai_context_files/instructions/how_tos/instr_existing

skills:
  - peer_review
"""

ROLE_ARCHITECT = """\
name: Architect
description: An architect role.
"""

PROFILE_TEAM = """\
name: Team

roles:
  - ai_profiles/roles/dev
"""

KNOW_GLOSSARY = "---\ntitle: Glossary\n---\n\n# Glossary\n"
KNOW_OTHER = "---\ntitle: Other\n---\n\n# Other\n"
INSTR_EXISTING = "---\ntitle: Existing How-To\n---\n\n# Existing\n"
SKILL_PEER = "name: Peer Review\ndescription: A skill.\n"


@pytest.fixture
def tree(tmp_path):
    """Build a minimal fixture context tree and return its ai_root."""
    root = tmp_path / "ai_root"

    def write(rel, text):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    write("ai_general/ai_profiles/roles/dev.yml", ROLE_DEV)
    write("ai_general/ai_profiles/roles/architect.yml", ROLE_ARCHITECT)
    write("ai_general/ai_profiles/team.yml", PROFILE_TEAM)
    write("ai_general/ai_profiles/skills/peer_review.yml", SKILL_PEER)
    write(
        "ai_general/ai_context_files/knowledge/reference/glossary.md", KNOW_GLOSSARY
    )
    write("ai_general/ai_context_files/knowledge/reference/other.md", KNOW_OTHER)
    write(
        "ai_general/ai_context_files/instructions/how_tos/instr_existing.md",
        INSTR_EXISTING,
    )
    return root


def _make_index(tmp_path, root) -> ContextIndex:
    idx = ContextIndex(db_path=tmp_path / "context.db", ai_root=root)
    idx.reindex()
    return idx


def _edges(idx, src_id):
    with idx._connect() as conn:
        return [
            (r["dst_id"], r["edge_type"])
            for r in conn.execute(
                "SELECT dst_id, edge_type FROM edges WHERE src_id=? ORDER BY order_idx",
                (src_id,),
            ).fetchall()
        ]


def _has_edge(idx, src_id, dst_id):
    return any(d == dst_id for (d, _t) in _edges(idx, src_id))


def _changelog(idx, item_id, op=None):
    sql = "SELECT * FROM changelog WHERE item_id=?"
    params = [item_id]
    if op:
        sql += " AND op=?"
        params.append(op)
    with idx._connect() as conn:
        return conn.execute(sql, params).fetchall()


# ---------------------------------------------------------------------------
# link — role -> knowledge (context_files bucket by category)
# ---------------------------------------------------------------------------

def test_link_role_to_knowledge_adds_context_file_and_edge(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.link("role:dev", "knowledge:reference/glossary", by="tester")
    assert res["ok"] is True
    assert res["dry_run"] is False

    # YAML: the ref appears under context_files in the dst's category bucket.
    text = (tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    assert "ai_context_files/knowledge/reference/glossary" in text

    # Edge present in the index (references — leaf dst).
    assert _has_edge(idx, "role:dev", "knowledge:reference/glossary")

    # Changelog op="link" recorded.
    log = _changelog(idx, "role:dev", op="link")
    assert len(log) == 1
    assert log[0]["changed_by"] == "tester"


def test_link_creates_bucket_when_absent(tmp_path, tree):
    """dst category 'reference' has no bucket on the role yet -> created."""
    idx = _make_index(tmp_path, tree)
    res = idx.link("role:dev", "knowledge:reference/glossary")
    assert res["ok"] is True
    # Round-trips through a fresh reindex.
    idx.reindex()
    assert _has_edge(idx, "role:dev", "knowledge:reference/glossary")


# ---------------------------------------------------------------------------
# link — profile -> role (roles list)
# ---------------------------------------------------------------------------

def test_link_profile_to_role_adds_roles_entry(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.link("profile:team", "role:architect", by="tester")
    assert res["ok"] is True

    text = (tree / "ai_general/ai_profiles/team.yml").read_text()
    assert "ai_profiles/roles/architect" in text

    # composes edge (bundle dst).
    edges = _edges(idx, "profile:team")
    assert ("role:architect", "composes") in edges


def test_link_role_to_skill_adds_skills_entry(tmp_path, tree):
    # Add a second skill the role does not yet have.
    sp = tree / "ai_general/ai_profiles/skills/research.yml"
    sp.write_text("name: Research\ndescription: skill.\n")
    idx = _make_index(tmp_path, tree)
    res = idx.link("role:dev", "skill:research")
    assert res["ok"] is True
    text = (tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    assert "research" in text
    assert _has_edge(idx, "role:dev", "skill:research")


# ---------------------------------------------------------------------------
# link — idempotent
# ---------------------------------------------------------------------------

def test_link_idempotent_no_dup(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    first = idx.link("role:dev", "knowledge:reference/glossary")
    assert first["ok"] is True
    second = idx.link("role:dev", "knowledge:reference/glossary")
    assert second["ok"] is True
    assert second.get("already_linked") is True

    # No duplicate edge, no duplicate ref line in the file.
    edges = _edges(idx, "role:dev")
    assert edges.count(("knowledge:reference/glossary", "references")) == 1
    text = (tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    assert text.count("ai_context_files/knowledge/reference/glossary") == 1

    # The second (already-linked) call records no new link changelog row.
    log = _changelog(idx, "role:dev", op="link")
    assert len(log) == 1


# ---------------------------------------------------------------------------
# link — rejections
# ---------------------------------------------------------------------------

def test_link_rejects_self(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.link("role:dev", "role:dev")
    assert res["ok"] is False
    assert "error" in res


def test_link_rejects_missing_dst(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.link("role:dev", "knowledge:reference/nope")
    assert res["ok"] is False
    assert "error" in res


def test_link_rejects_missing_src(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.link("role:nope", "knowledge:reference/glossary")
    assert res["ok"] is False
    assert "error" in res


def test_link_rejects_non_bundle_src(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.link("knowledge:reference/glossary", "knowledge:reference/other")
    assert res["ok"] is False
    assert "error" in res


def test_link_rejects_cycle(tmp_path, tree):
    """profile:team -> role:dev already; linking role:dev -> profile:team cycles."""
    idx = _make_index(tmp_path, tree)
    # team -> dev exists from the fixture. dev -> team would close a cycle.
    res = idx.link("role:dev", "profile:team")
    assert res["ok"] is False
    assert "error" in res
    assert "cycle" in res["error"].lower()
    # Nothing written.
    assert not _has_edge(idx, "role:dev", "profile:team")


def test_link_rejects_indirect_cycle(tmp_path, tree):
    """A -> B -> C; linking C -> A must be rejected (walks existing edges)."""
    idx = _make_index(tmp_path, tree)
    # profile:team -> role:dev (fixture). Link role:dev -> role:architect.
    assert idx.link("role:dev", "role:architect")["ok"] is True
    # Now team -> dev -> architect. Linking architect -> team closes the loop.
    res = idx.link("role:architect", "profile:team")
    assert res["ok"] is False
    assert "cycle" in res["error"].lower()


# ---------------------------------------------------------------------------
# link — dry_run
# ---------------------------------------------------------------------------

def test_link_dry_run_writes_nothing(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    before = (tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    res = idx.link("role:dev", "knowledge:reference/glossary", dry_run=True)
    assert res["ok"] is True
    assert res["dry_run"] is True
    # planned ref reported
    assert res.get("ref")
    # File untouched, no edge, no changelog.
    assert (tree / "ai_general/ai_profiles/roles/dev.yml").read_text() == before
    assert not _has_edge(idx, "role:dev", "knowledge:reference/glossary")
    assert len(_changelog(idx, "role:dev", op="link")) == 0


# ---------------------------------------------------------------------------
# unlink
# ---------------------------------------------------------------------------

def test_unlink_removes_ref_and_edge(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    # dev -> instr_existing exists from the fixture.
    assert _has_edge(idx, "role:dev", "instruction:how_tos/instr_existing")
    res = idx.unlink("role:dev", "instruction:how_tos/instr_existing", by="tester")
    assert res["ok"] is True

    text = (tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    assert "instr_existing" not in text
    assert not _has_edge(idx, "role:dev", "instruction:how_tos/instr_existing")

    log = _changelog(idx, "role:dev", op="unlink")
    assert len(log) == 1
    assert log[0]["changed_by"] == "tester"


def test_unlink_removes_skill_entry(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    assert _has_edge(idx, "role:dev", "skill:peer_review")
    res = idx.unlink("role:dev", "skill:peer_review")
    assert res["ok"] is True
    assert not _has_edge(idx, "role:dev", "skill:peer_review")


def test_unlink_tidies_empty_bucket(tmp_path, tree):
    """Removing the only entry in a context_files bucket drops the bucket."""
    idx = _make_index(tmp_path, tree)
    idx.unlink("role:dev", "instruction:how_tos/instr_existing")
    text = (tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    # The 'methods' bucket had a single entry; it should be gone now.
    assert "methods" not in text


def test_unlink_rejects_when_not_linked(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.unlink("role:dev", "knowledge:reference/other")
    assert res["ok"] is False
    assert "error" in res


def test_unlink_dry_run_writes_nothing(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    before = (tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    res = idx.unlink(
        "role:dev", "instruction:how_tos/instr_existing", dry_run=True
    )
    assert res["ok"] is True
    assert res["dry_run"] is True
    assert (tree / "ai_general/ai_profiles/roles/dev.yml").read_text() == before
    assert _has_edge(idx, "role:dev", "instruction:how_tos/instr_existing")


# ---------------------------------------------------------------------------
# ROUND-TRIP — the correctness gate. The YAML link writes must be exactly what
# reindex parses back: link, then a full reindex-from-scratch, same edge holds.
# ---------------------------------------------------------------------------

def test_link_roundtrip_knowledge_survives_full_reindex(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.link("role:dev", "knowledge:reference/glossary")
    # Full reindex-from-scratch reads ONLY the on-disk YAML.
    idx.reindex()
    assert _has_edge(idx, "role:dev", "knowledge:reference/glossary")


def test_link_roundtrip_role_survives_full_reindex(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.link("profile:team", "role:architect")
    idx.reindex()
    edges = _edges(idx, "profile:team")
    assert ("role:architect", "composes") in edges


def test_link_roundtrip_skill_survives_full_reindex(tmp_path, tree):
    sp = tree / "ai_general/ai_profiles/skills/research.yml"
    sp.write_text("name: Research\ndescription: skill.\n")
    idx = _make_index(tmp_path, tree)
    idx.link("role:dev", "skill:research")
    idx.reindex()
    assert _has_edge(idx, "role:dev", "skill:research")


def test_unlink_roundtrip_survives_full_reindex(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.unlink("role:dev", "skill:peer_review")
    idx.reindex()
    assert not _has_edge(idx, "role:dev", "skill:peer_review")


# ---------------------------------------------------------------------------
# Incremental edge update — link/unlink touch ONLY src's edges, not others'.
# ---------------------------------------------------------------------------

def test_link_only_updates_src_edges(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    team_before = _edges(idx, "profile:team")
    idx.link("role:dev", "knowledge:reference/glossary")
    # profile:team's edges are unchanged by a link on role:dev.
    assert _edges(idx, "profile:team") == team_before


# ---------------------------------------------------------------------------
# Safety
# ---------------------------------------------------------------------------

def test_index_uses_tmp_db_and_tmp_root(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    assert str(idx.db_path).startswith(str(tmp_path))
    assert str(idx.ai_root).startswith(str(tmp_path))


# ---------------------------------------------------------------------------
# REGRESSION (2026-07-02): compact block-sequence buckets of {path, purpose}
# maps — the real `ai_profiles/globals/base.yml` shape. This structure broke
# link/unlink three ways before the fix:
#   1) unlink deleted only the `- path:` line, orphaning its `purpose:` line
#      → invalid YAML → parse failure → the index kept the stale edge.
#   2) _tidy_empty_blocks treated a bucket whose list items sit at the SAME
#      indent as the key as "empty" and deleted the bucket header → every
#      bucket flattened into one list → context_files became a list → reindex
#      parsed ZERO refs (all edges silently lost).
#   3) link added a bare string into a spuriously pluralized new bucket instead
#      of the existing same-directory bucket, in the wrong entry shape.
# These assert the file stays STRUCTURALLY valid and the index tracks it.
# ---------------------------------------------------------------------------

GLOBAL_BASE = """\
name: Global Base
description: Core traits.

context_files:
  perspective:
  - path: ai_context_files/instructions/perspectives/perspective_operating_principles
    purpose: Core operating principles
  - path: ai_context_files/instructions/perspectives/perspective_user_profile
    purpose: User profile
  knowledge:
  - path: ai_context_files/knowledge/reference/glossary
    purpose: Term mapping
_registry:
  id: global
  status: active
"""


@pytest.fixture
def compact_tree(tmp_path):
    """A bundle using compact `{path, purpose}` buckets (base.yml shape)."""
    root = tmp_path / "ai_root"

    def write(rel, text):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    write("ai_general/ai_profiles/globals/base.yml", GLOBAL_BASE)
    write(
        "ai_general/ai_context_files/instructions/perspectives/"
        "perspective_operating_principles.md",
        "---\ntitle: Ops\n---\n# Ops\n",
    )
    write(
        "ai_general/ai_context_files/instructions/perspectives/"
        "perspective_user_profile.md",
        "---\ntitle: Profile\n---\n# Profile\n",
    )
    write(
        "ai_general/ai_context_files/knowledge/reference/glossary.md",
        KNOW_GLOSSARY,
    )
    return root


def _cf(root):
    """Parse base.yml's context_files back into a dict for structural asserts."""
    import yaml as _yaml
    data = _yaml.safe_load(
        (root / "ai_general/ai_profiles/globals/base.yml").read_text()
    )
    return data["context_files"]


def test_compact_unlink_removes_whole_map_item_keeps_buckets(tmp_path, compact_tree):
    idx = _make_index(tmp_path, compact_tree)
    dst = "instruction:perspectives/perspective_operating_principles"
    assert _has_edge(idx, "global:base", dst)

    res = idx.unlink("global:base", dst)
    assert res["ok"] is True and not res.get("warning")

    cf = _cf(compact_tree)
    # context_files stays a dict of buckets — NOT flattened into a list.
    assert isinstance(cf, dict)
    assert set(cf.keys()) == {"perspective", "knowledge"}
    # The removed entry (and its purpose line) is gone; the sibling remains.
    persp = [e["path"] if isinstance(e, dict) else e for e in cf["perspective"]]
    assert persp == ["ai_context_files/instructions/perspectives/perspective_user_profile"]
    # Index tracks the file WITHOUT a full reindex.
    assert not _has_edge(idx, "global:base", dst)


def test_compact_unlink_index_survives_reindex(tmp_path, compact_tree):
    idx = _make_index(tmp_path, compact_tree)
    dst = "instruction:perspectives/perspective_operating_principles"
    idx.unlink("global:base", dst)
    idx.reindex()  # rebuild from the file — the other edges must survive.
    assert not _has_edge(idx, "global:base", dst)
    # The other two refs are still parsed (no flattening / total edge loss).
    assert _has_edge(idx, "global:base", "instruction:perspectives/perspective_user_profile")
    assert _has_edge(idx, "global:base", "knowledge:reference/glossary")


def test_compact_link_reuses_same_dir_bucket_and_path_shape(tmp_path, compact_tree):
    idx = _make_index(tmp_path, compact_tree)
    dst = "instruction:perspectives/perspective_operating_principles"
    idx.unlink("global:base", dst)
    res = idx.link("global:base", dst)
    assert res["ok"] is True and not res.get("warning")

    cf = _cf(compact_tree)
    # No spurious pluralized bucket ('perspectives'); the ref rejoins 'perspective'.
    assert set(cf.keys()) == {"perspective", "knowledge"}
    persp = [e["path"] if isinstance(e, dict) else e for e in cf["perspective"]]
    assert "ai_context_files/instructions/perspectives/perspective_operating_principles" in persp
    # Written in the bucket's {path: ...} map shape, not a bare string.
    assert all(isinstance(e, dict) and "path" in e for e in cf["perspective"])
    # Edge restored, and it round-trips through a full reindex.
    assert _has_edge(idx, "global:base", dst)
    idx.reindex()
    assert _has_edge(idx, "global:base", dst)


# ---------------------------------------------------------------------------
# REGRESSION (2026-07-03): `context_files` as a FLAT LIST (not a dict of
# category buckets) — the real `role:condenser` shape. _iter_ref_strings only
# handled the dict form, so a flat-list role produced ZERO outbound edges and
# showed no links in the Link Matrix.
# ---------------------------------------------------------------------------

ROLE_FLAT_CF = """\
name: Condenser
description: Uses a flat context_files list.

context_files:
- ai_context_files/instructions/how_tos/instr_existing
- ai_context_files/knowledge/reference/glossary
"""


def test_flat_list_context_files_yields_edges(tmp_path, tree):
    # Add a role whose context_files is a bare list of refs (both targets exist
    # in the shared `tree` fixture).
    (tree / "ai_general/ai_profiles/roles/condenser.yml").write_text(ROLE_FLAT_CF)
    idx = _make_index(tmp_path, tree)
    assert _has_edge(idx, "role:condenser", "instruction:how_tos/instr_existing")
    assert _has_edge(idx, "role:condenser", "knowledge:reference/glossary")
    # Survives a reindex-from-scratch (parser, not just incremental refresh).
    idx.reindex()
    assert _has_edge(idx, "role:condenser", "instruction:how_tos/instr_existing")
    assert _has_edge(idx, "role:condenser", "knowledge:reference/glossary")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
