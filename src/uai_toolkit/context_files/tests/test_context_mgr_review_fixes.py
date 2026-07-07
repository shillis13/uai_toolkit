#!/usr/bin/env python3
"""
test_context_mgr_review_fixes.py — Codex review correctness fixes (todo_0331).

Phase 2 write-engine correctness bugs flagged by a Codex reviewer ("do not run
live until fixing"). Each test below REPRODUCES one finding, then guards the fix:

1. Basename-only ref matching — two items sharing a basename in different
   categories must NOT collide on unlink/move ref editing.
2. Archive-survives-reindex for ALL kinds — delete+reindex must yield
   status='archived' for profiles and memories (and roles/globals), not
   resurrect-as-active or lose them; restore brings them back active.
3. Parse-failure edge erasure — _refresh_edges on a malformed bundle must
   PRESERVE the existing edges (skip the refresh) and warn, not erase them.
4. YAML-safe title serialization — create() must serialize a title containing
   YAML-special chars so the stub's frontmatter parses back to the exact title.
5. Brief/memory link non-roundtrip — link must REJECT brief/memory dsts cleanly
   (reindex's _resolve_ref cannot map those refs back to a bundle edge).

SAFETY: every test builds against a TEMP fixture tree + temp DB. No real library
(``ai_general/ai_context_files/``, ``ai_profiles/``) or the real
``data/context.db`` is ever touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

try:
    import yaml
except ImportError:  # pragma: no cover
    yaml = None

_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from uai_toolkit.context_files.context_mgr import ContextIndex  # noqa: E402
from uai_toolkit.context_files import context_mgr as cm  # noqa: E402


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

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


def _status_of(idx, item_id):
    with idx._connect() as conn:
        row = conn.execute(
            "SELECT status FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return row["status"] if row else None


def _active_ids(idx):
    return {r["id"] for r in idx.list_items(status="active", limit=None)}


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


# ===========================================================================
# Finding 1 — basename-only ref matching (CRITICAL): two knowledge files with
# the SAME basename in DIFFERENT categories collide on unlink/move.
# ===========================================================================

# A role that references BOTH glossaries (same basename, different category).
ROLE_DEV_TWO_GLOSSARIES = """\
name: Dev
description: A developer role.

context_files:
  a:
    - ai_context_files/knowledge/a/glossary
  b:
    - ai_context_files/knowledge/b/glossary
"""

KNOW = "---\ntitle: Glossary\n---\n\n# Glossary\n"


@pytest.fixture
def collide_tree(tmp_path):
    """role:dev references knowledge:a/glossary AND knowledge:b/glossary."""
    root = tmp_path / "ai_root"
    _write(root, "ai_general/ai_profiles/roles/dev.yml", ROLE_DEV_TWO_GLOSSARIES)
    _write(root, "ai_general/ai_context_files/knowledge/a/glossary.md", KNOW)
    _write(root, "ai_general/ai_context_files/knowledge/b/glossary.md", KNOW)
    return root


def test_unlink_only_touches_targeted_basename_collision(tmp_path, collide_tree):
    idx = _make_index(tmp_path, collide_tree)
    # Both edges exist up front.
    assert _has_edge(idx, "role:dev", "knowledge:a/glossary")
    assert _has_edge(idx, "role:dev", "knowledge:b/glossary")

    # Unlink ONLY b/glossary (the SECOND occurrence; basename-only matching
    # would wrongly drop the FIRST line — a/glossary — instead).
    res = idx.unlink("role:dev", "knowledge:b/glossary")
    assert res["ok"] is True

    text = (collide_tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    # The targeted ref is gone; the SAME-basename sibling is untouched.
    assert "ai_context_files/knowledge/b/glossary" not in text
    assert "ai_context_files/knowledge/a/glossary" in text

    assert not _has_edge(idx, "role:dev", "knowledge:b/glossary")
    assert _has_edge(idx, "role:dev", "knowledge:a/glossary")

    # Round-trips through a full reindex (only a survives).
    idx.reindex()
    assert not _has_edge(idx, "role:dev", "knowledge:b/glossary")
    assert _has_edge(idx, "role:dev", "knowledge:a/glossary")


def test_move_only_repoints_targeted_basename_collision(tmp_path, collide_tree):
    idx = _make_index(tmp_path, collide_tree)
    # Rename b/glossary -> b/lexicon; a/glossary must be left alone. Under the
    # basename-only bug, _yaml_replace_ref repoints the FIRST 'glossary' line
    # (a/glossary), corrupting the wrong ref.
    res = idx.move("knowledge:b/glossary", new_name="b/lexicon")
    assert res["ok"] is True

    text = (collide_tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    assert "ai_context_files/knowledge/b/lexicon" in text
    assert "ai_context_files/knowledge/b/glossary" not in text
    # The a-category glossary ref is byte-for-byte untouched.
    assert "ai_context_files/knowledge/a/glossary" in text

    # Full reindex: both refs resolve to their correct, distinct targets.
    idx.reindex()
    assert _has_edge(idx, "role:dev", "knowledge:b/lexicon")
    assert _has_edge(idx, "role:dev", "knowledge:a/glossary")
    assert not _has_edge(idx, "role:dev", "knowledge:b/glossary")
    # No dangling refs introduced.
    assert idx.validate()["dangling"] == []


# ===========================================================================
# Finding 2 — archive-survives-reindex FALSE for profiles & memories
# (CRITICAL): delete+reindex must yield status='archived' for EVERY kind.
# ===========================================================================

GLOBAL_BASE = """\
name: Base
description: A global.
"""

PROFILE_SOLO = """\
name: Solo
description: A standalone profile (nothing references it).
"""

ROLE_SOLO = """\
name: Solo Role
description: A standalone role.
"""

MEM_SLOT = "slot: 99\nnotes: scratch\n"


@pytest.fixture
def kinds_tree(tmp_path):
    """One standalone item per archivable kind (no inbound refs)."""
    root = tmp_path / "ai_root"
    _write(root, "ai_general/ai_profiles/solo.yml", PROFILE_SOLO)
    _write(root, "ai_general/ai_profiles/roles/solo_role.yml", ROLE_SOLO)
    _write(root, "ai_general/ai_profiles/globals/base.yml", GLOBAL_BASE)
    _write(root, "ai_memories/80_working_memory/99.yml", MEM_SLOT)
    return root


@pytest.mark.parametrize(
    "item_id",
    [
        "profile:solo",
        "memory:99",
        "role:solo_role",
        "global:base",
    ],
)
def test_archive_removed_from_index_for_all_kinds(tmp_path, kinds_tree, item_id):
    idx = _make_index(tmp_path, kinds_tree)
    assert item_id in _active_ids(idx), "fixture item must index active first"

    res = idx.delete(item_id)
    assert res["ok"] is True, res

    # Archived items are NOT indexed: the discovery scan skips _archive/, so a
    # deleted item disappears from the tool entirely (its file stays on disk in
    # _archive/, but it is neither active nor listed anywhere). Restore was
    # dropped (2026-07-02, PianoMan) — bring an item back by moving the file.
    assert item_id not in _active_ids(idx)
    assert _status_of(idx, item_id) is None

    idx.reindex()
    assert item_id not in _active_ids(idx)
    assert _status_of(idx, item_id) is None


# ===========================================================================
# Finding 3 — parse-failure edge erasure (CRITICAL, data loss): _refresh_edges
# on a malformed bundle must PRESERVE existing edges, not erase them.
# ===========================================================================

ROLE_REF = """\
name: Dev
description: A developer role.

context_files:
  reference:
    - ai_context_files/knowledge/reference/glossary
"""

KNOW_GLOSSARY = "---\ntitle: Glossary\n---\n\n# Glossary\n"


@pytest.fixture
def refresh_tree(tmp_path):
    root = tmp_path / "ai_root"
    _write(root, "ai_general/ai_profiles/roles/dev.yml", ROLE_REF)
    _write(
        root,
        "ai_general/ai_context_files/knowledge/reference/glossary.md",
        KNOW_GLOSSARY,
    )
    return root


def test_refresh_edges_preserves_on_parse_failure(tmp_path, refresh_tree):
    idx = _make_index(tmp_path, refresh_tree)
    assert _has_edge(idx, "role:dev", "knowledge:reference/glossary")

    # Corrupt the bundle file so YAML parsing fails.
    bad = "name: Dev\ncontext_files: : : [unbalanced\n  - oops\n}{"
    (refresh_tree / "ai_general/ai_profiles/roles/dev.yml").write_text(bad)

    # _refresh_edges must NOT erase the existing edges on a parse failure.
    warning = idx._refresh_edges("role:dev")

    assert _has_edge(idx, "role:dev", "knowledge:reference/glossary"), (
        "existing edges were erased on parse failure"
    )
    # A warning is surfaced (truthy) rather than silently dropping edges.
    assert warning


# ===========================================================================
# Finding 4 — YAML-safe title serialization: a title with YAML-special chars
# must round-trip through the stub frontmatter.
# ===========================================================================

@pytest.fixture
def empty_tree(tmp_path):
    root = tmp_path / "ai_root"
    # Need the dir to exist for reindex; create one throwaway file.
    _write(root, "ai_general/ai_context_files/knowledge/reference/seed.md",
           "---\ntitle: Seed\n---\n\n# Seed\n")
    return root


@pytest.mark.parametrize(
    "title",
    [
        'Foo: bar "baz" #1',
        "- leading dash",
        "trailing colon:",
        "value: with: colons",
        "He said \"hi\" & {braces}",
    ],
)
def test_create_title_is_yaml_safe(tmp_path, empty_tree, title):
    idx = _make_index(tmp_path, empty_tree)
    res = idx.create(kind="knowledge", title=title, category="reference",
                     name="yaml_safe_case")
    assert res["ok"] is True, res

    f = empty_tree / res["path"]
    text = f.read_text()

    # The frontmatter must parse, and title must round-trip exactly.
    assert text.startswith("---\n")
    fm_end = text.index("\n---", 4)
    fm_block = text[4:fm_end]
    parsed = yaml.safe_load(fm_block)
    assert isinstance(parsed, dict), "frontmatter did not parse to a mapping"
    assert parsed.get("title") == title


def test_create_simple_title_stays_unquoted(tmp_path, empty_tree):
    """Regression guard: plain titles keep the human-readable raw form."""
    idx = _make_index(tmp_path, empty_tree)
    res = idx.create(kind="knowledge", title="My New Topic", category="reference")
    assert res["ok"] is True
    text = (empty_tree / res["path"]).read_text()
    assert "title: My New Topic" in text


# ===========================================================================
# Finding 5 — brief/memory link non-roundtrip: link must REJECT brief/memory
# dsts cleanly (reindex's _resolve_ref cannot map those refs to a bundle edge).
# ===========================================================================

ROLE_EMPTY = """\
name: Dev
description: A developer role.
"""

BRIEF_DOC = "brief_meta:\n  name: A Brief\n  description: a session brief.\n"


@pytest.fixture
def link_tree(tmp_path):
    root = tmp_path / "ai_root"
    _write(root, "ai_general/ai_profiles/roles/dev.yml", ROLE_EMPTY)
    _write(root, "ai_general/data/session_briefs/sb.yml", BRIEF_DOC)
    _write(root, "ai_memories/80_working_memory/05.yml", "slot: 5\n")
    return root


@pytest.mark.parametrize("dst_id", ["brief:sb", "memory:05"])
def test_link_rejects_brief_and_memory(tmp_path, link_tree, dst_id):
    idx = _make_index(tmp_path, link_tree)
    assert dst_id in {r["id"] for r in idx.list_items(status="all", limit=None)}, (
        "fixture dst must exist"
    )

    res = idx.link("role:dev", dst_id)
    assert res["ok"] is False
    assert "error" in res
    # Clear, kind-specific rejection.
    assert "brief" in res["error"].lower() or "memory" in res["error"].lower() \
        or "not linkable" in res["error"].lower()

    # No edge written, file untouched.
    assert not _has_edge(idx, "role:dev", dst_id)
    text = (link_tree / "ai_general/ai_profiles/roles/dev.yml").read_text()
    assert text == ROLE_EMPTY


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
