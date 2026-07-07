#!/usr/bin/env python3
"""
test_context_mgr_tier1_fixes.py — Codex 2nd-tier integrity fixes (todo_0331).

Codex's full review flagged a set of "fold before live writes" integrity items
on top of the 5 correctness fixes already in test_context_mgr_review_fixes.py.
Each test below REPRODUCES one finding, then guards the fix.

T1-3  link/unlink must SURFACE the _refresh_edges warning. _refresh_edges()
      already preserves edges + returns a warning on a parse failure, but link()
      and unlink() discarded the return value — so a caller saw ok:true with no
      hint the source was malformed and the index was NOT refreshed.

SAFETY: every test builds against a TEMP fixture tree + temp DB. No real library
or the real data/context.db is ever touched.
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


def _make_index(tmp_path, root) -> ContextIndex:
    idx = ContextIndex(db_path=tmp_path / "context.db", ai_root=root)
    idx.reindex()
    return idx


def _write(root, rel, text):
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


def _has_edge(idx, src_id, dst_id):
    with idx._connect() as conn:
        return conn.execute(
            "SELECT 1 FROM edges WHERE src_id=? AND dst_id=?", (src_id, dst_id)
        ).fetchone() is not None


# ===========================================================================
# T1-3 — link/unlink surface the _refresh_edges parse-failure warning.
# ===========================================================================

ROLE_ONE_REF = """\
name: Dev
description: A developer role.

context_files:
  reference:
    - ai_context_files/knowledge/reference/glossary
"""

KNOW = "---\ntitle: Glossary\n---\n\n# Glossary\n"
KNOW2 = "---\ntitle: Lexicon\n---\n\n# Lexicon\n"


@pytest.fixture
def warn_tree(tmp_path):
    root = tmp_path / "ai_root"
    _write(root, "ai_general/ai_profiles/roles/dev.yml", ROLE_ONE_REF)
    _write(root, "ai_general/ai_context_files/knowledge/reference/glossary.md", KNOW)
    _write(root, "ai_general/ai_context_files/knowledge/reference/lexicon.md", KNOW2)
    return root


def test_link_surfaces_refresh_warning(tmp_path, warn_tree, monkeypatch):
    """A parse-failure on refresh must reach the link() result as `warning`."""
    idx = _make_index(tmp_path, warn_tree)

    sentinel = "could not parse roles/dev.yml (role:dev); preserved existing edges"
    monkeypatch.setattr(idx, "_refresh_edges", lambda src_id: sentinel)

    res = idx.link("role:dev", "knowledge:reference/lexicon")
    assert res["ok"] is True
    assert res.get("warning") == sentinel, (
        "link() dropped the _refresh_edges warning"
    )


def test_unlink_surfaces_refresh_warning(tmp_path, warn_tree, monkeypatch):
    idx = _make_index(tmp_path, warn_tree)

    sentinel = "could not parse roles/dev.yml (role:dev); preserved existing edges"
    monkeypatch.setattr(idx, "_refresh_edges", lambda src_id: sentinel)

    res = idx.unlink("role:dev", "knowledge:reference/glossary")
    assert res["ok"] is True
    assert res.get("warning") == sentinel, (
        "unlink() dropped the _refresh_edges warning"
    )


def test_link_clean_refresh_has_no_warning(tmp_path, warn_tree):
    """Regression: a clean refresh must NOT add a spurious warning key."""
    idx = _make_index(tmp_path, warn_tree)
    res = idx.link("role:dev", "knowledge:reference/lexicon")
    assert res["ok"] is True
    assert "warning" not in res
    assert _has_edge(idx, "role:dev", "knowledge:reference/lexicon")


def test_unlink_clean_refresh_has_no_warning(tmp_path, warn_tree):
    idx = _make_index(tmp_path, warn_tree)
    res = idx.unlink("role:dev", "knowledge:reference/glossary")
    assert res["ok"] is True
    assert "warning" not in res
    assert not _has_edge(idx, "role:dev", "knowledge:reference/glossary")


# ===========================================================================
# T1-2 — atomic writes: temp-in-same-dir + fsync + os.replace, exclusive create
# for new files, and symlink-follow preserved (writing through a *_latest
# symlink must update the real target, not clobber the link with a regular file).
# ===========================================================================


def test_atomic_write_creates_correct_content(tmp_path):
    p = tmp_path / "sub" / "f.md"
    cm._atomic_write(p, "hello\n")
    assert p.read_text() == "hello\n"


def test_atomic_write_overwrites_existing(tmp_path):
    p = tmp_path / "f.md"
    p.write_text("old\n")
    cm._atomic_write(p, "new\n")
    assert p.read_text() == "new\n"


def test_atomic_write_exclusive_rejects_existing(tmp_path):
    p = tmp_path / "f.md"
    p.write_text("here\n")
    with pytest.raises(FileExistsError):
        cm._atomic_write(p, "nope\n", exclusive=True)
    # The pre-existing file is left intact.
    assert p.read_text() == "here\n"


def test_atomic_write_leaves_no_temp_files(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    p = d / "f.md"
    cm._atomic_write(p, "a\n")
    cm._atomic_write(p, "b\n")
    leftovers = [x.name for x in d.iterdir() if x.name != "f.md"]
    assert leftovers == [], "atomic write left temp files: {}".format(leftovers)


def test_atomic_write_exclusive_collision_leaves_no_temp(tmp_path):
    d = tmp_path / "d"
    d.mkdir()
    p = d / "f.md"
    p.write_text("x\n")
    with pytest.raises(FileExistsError):
        cm._atomic_write(p, "y\n", exclusive=True)
    leftovers = [x.name for x in d.iterdir() if x.name != "f.md"]
    assert leftovers == [], "failed exclusive write left temp files: {}".format(leftovers)


def test_atomic_write_through_symlink_preserves_link(tmp_path):
    """Writing through a symlink updates the real target, keeps the symlink."""
    real = tmp_path / "f_v1.md"
    real.write_text("v1\n")
    link = tmp_path / "f_latest.md"
    link.symlink_to(real.name)

    cm._atomic_write(link, "v2\n")

    assert link.is_symlink(), "atomic write clobbered the symlink with a regular file"
    assert real.read_text() == "v2\n", "content did not write through to the real target"
    assert link.read_text() == "v2\n"


def test_update_content_writes_real_file_visible_through_symlink(tmp_path):
    """reindex resolves symlinks, so the index records the REAL file path; an
    atomic update of that real file is naturally visible through a *_latest
    symlink (the link is never the write target, so it is never clobbered)."""
    root = tmp_path / "ai_root"
    base = root / "ai_general/ai_context_files/knowledge/reference"
    base.mkdir(parents=True)
    real = base / "topic_v1.md"
    real.write_text("---\ntitle: Topic\n---\n\n# Topic\n\nold body\n")
    latest = base / "topic_latest.md"
    latest.symlink_to(real.name)

    idx = ContextIndex(db_path=tmp_path / "context.db", ai_root=root)
    idx.reindex()

    # The indexed id is the resolved real-file name, not the symlink alias.
    res = idx.update_content("knowledge:reference/topic_v1", "new body")
    assert res["ok"] is True, res
    assert latest.is_symlink(), "the *_latest symlink must remain a symlink"
    assert "new body" in real.read_text()
    assert "new body" in latest.read_text()


# ===========================================================================
# T1-6 — graph()/validate() must ignore edges from ARCHIVED sources. graph
# returns only active items, so an edge whose src is archived would point from a
# node the UI never renders (a phantom source); and an archived item's dangling
# refs are not an active-tree defect.
# ===========================================================================

ROLE_DEV_G = """\
name: Dev
description: active role.

context_files:
  reference:
    - ai_context_files/knowledge/reference/glossary
"""

# An about-to-be-archived role that references a live leaf AND a missing one.
ROLE_OLD_G = """\
name: Old
description: soon archived.

context_files:
  reference:
    - ai_context_files/knowledge/reference/glossary
    - ai_context_files/knowledge/reference/ghost
"""


@pytest.fixture
def archive_graph_tree(tmp_path):
    root = tmp_path / "ai_root"
    _write(root, "ai_general/ai_profiles/roles/dev.yml", ROLE_DEV_G)
    _write(root, "ai_general/ai_profiles/roles/old.yml", ROLE_OLD_G)
    _write(root, "ai_general/ai_context_files/knowledge/reference/glossary.md", KNOW)
    return root


def test_graph_excludes_archived_source_edges(tmp_path, archive_graph_tree):
    idx = _make_index(tmp_path, archive_graph_tree)
    # role:old contributes edges up front.
    assert any(e["src_id"] == "role:old" for e in idx.graph()["edges"])

    res = idx.delete("role:old")
    assert res["ok"] is True, res
    archived_id = res["id"]  # role:_archive/old

    g = idx.graph()
    item_ids = {i["id"] for i in g["items"]}
    assert archived_id not in item_ids, "archived item must not appear in graph items"
    assert "role:old" not in item_ids

    # No edge may originate from the archived source (old id OR archived id).
    bad = [e for e in g["edges"] if e["src_id"] in ("role:old", archived_id)]
    assert bad == [], "graph emitted edges from an archived source: {}".format(bad)

    # The active role's edge is still present.
    assert any(e["src_id"] == "role:dev" for e in g["edges"])


def test_validate_dangling_ignores_archived_source(tmp_path, archive_graph_tree):
    idx = _make_index(tmp_path, archive_graph_tree)
    # Before archiving, role:old's ghost ref is a real dangling edge.
    pre = idx.validate()["dangling"]
    assert any(d["src_id"] == "role:old" for d in pre)

    res = idx.delete("role:old")
    assert res["ok"] is True
    archived_id = res["id"]

    dangling = idx.validate()["dangling"]
    bad = [d for d in dangling if d["src_id"] in ("role:old", archived_id)]
    assert bad == [], "validate reported dangling from an archived source: {}".format(bad)


# An active leaf referenced ONLY by a bundle that gets archived: once that
# bundle is archived, the leaf has no ACTIVE inbound edge and must be reported
# as an orphan. (Codex re-review regression: orphan query missed the active-
# source join that the dangling query got.)
ROLE_ONLY_REF = """\
name: Solo
description: the only thing referencing orphanish.

context_files:
  reference:
    - ai_context_files/knowledge/reference/orphanish
"""


@pytest.fixture
def orphan_after_archive_tree(tmp_path):
    root = tmp_path / "ai_root"
    _write(root, "ai_general/ai_profiles/roles/solo.yml", ROLE_ONLY_REF)
    _write(root, "ai_general/ai_context_files/knowledge/reference/orphanish.md", KNOW)
    return root


def test_validate_orphans_ignores_archived_source(tmp_path, orphan_after_archive_tree):
    idx = _make_index(tmp_path, orphan_after_archive_tree)
    # While role:solo is active, the leaf is NOT an orphan.
    assert "knowledge:reference/orphanish" not in {
        o["id"] for o in idx.validate()["orphans"]
    }

    res = idx.delete("role:solo")
    assert res["ok"] is True

    # Now its only referrer is archived -> the leaf is an orphan.
    orphans = {o["id"] for o in idx.validate()["orphans"]}
    assert "knowledge:reference/orphanish" in orphans, (
        "an archived-source edge wrongly suppressed orphan detection"
    )


# ===========================================================================
# T1-1 — `edit` must reindex + audit after $EDITOR exits. The interactive launch
# stays in main(), but the reconciliation (detect change via hash -> reindex +
# changelog) is a unit-testable apply_edit() method.
# ===========================================================================

KNOW_EDIT = "---\ntitle: Topic\n---\n\n# Topic\n\noriginal body\n"


@pytest.fixture
def edit_tree(tmp_path):
    root = tmp_path / "ai_root"
    _write(root, "ai_general/ai_context_files/knowledge/reference/topic.md", KNOW_EDIT)
    return root


def _history_ops(idx, item_id):
    return [r["op"] for r in idx.history(item_id)]


def test_edit_command_returns_content_hash(tmp_path, edit_tree):
    idx = _make_index(tmp_path, edit_tree)
    res = idx.edit_command("knowledge:reference/topic")
    assert res["ok"] is True
    assert res.get("content_hash"), "edit_command must return a pre-edit hash"


def test_apply_edit_reindexes_and_audits_on_change(tmp_path, edit_tree):
    idx = _make_index(tmp_path, edit_tree)
    before = idx.edit_command("knowledge:reference/topic")["content_hash"]

    # Simulate the human editing the file in $EDITOR.
    f = edit_tree / "ai_general/ai_context_files/knowledge/reference/topic.md"
    f.write_text("---\ntitle: Topic\n---\n\n# Topic\n\nEDITED body now\n")

    res = idx.apply_edit("knowledge:reference/topic", before_hash=before)
    assert res["ok"] is True
    assert res["changed"] is True
    # The change was audited.
    assert "update" in _history_ops(idx, "knowledge:reference/topic")
    # And the index reflects the new content (searchable).
    hits = {h["id"] for h in idx.search("EDITED")}
    assert "knowledge:reference/topic" in hits


def test_apply_edit_noop_when_unchanged(tmp_path, edit_tree):
    idx = _make_index(tmp_path, edit_tree)
    before = idx.edit_command("knowledge:reference/topic")["content_hash"]
    ops_before = _history_ops(idx, "knowledge:reference/topic")

    res = idx.apply_edit("knowledge:reference/topic", before_hash=before)
    assert res["ok"] is True
    assert res["changed"] is False
    # No spurious changelog row on a no-op edit.
    assert _history_ops(idx, "knowledge:reference/topic") == ops_before


def test_apply_edit_missing_item(tmp_path, edit_tree):
    idx = _make_index(tmp_path, edit_tree)
    res = idx.apply_edit("knowledge:reference/nope", before_hash="deadbeef")
    assert res["ok"] is False
    assert "error" in res


# ===========================================================================
# T1-5 — destructive ops must refresh the index from disk first. The inbound-ref
# guard reads the edges table; if a referrer was added on disk since the last
# reindex, a stale table would let delete() archive a still-referenced item
# WITHOUT --force, silently creating danglers.
# ===========================================================================

KNOW_TARGET = "---\ntitle: Glossary\n---\n\n# Glossary\n"
ROLE_NO_REF = """\
name: Dev
description: references nothing yet.
"""
ROLE_NEW_REF = """\
name: NewRef
description: a referrer added on disk after indexing.

context_files:
  reference:
    - ai_context_files/knowledge/reference/glossary
"""


@pytest.fixture
def stale_tree(tmp_path):
    root = tmp_path / "ai_root"
    _write(root, "ai_general/ai_profiles/roles/dev.yml", ROLE_NO_REF)
    _write(root, "ai_general/ai_context_files/knowledge/reference/glossary.md", KNOW_TARGET)
    return root


def test_delete_refreshes_index_and_rejects_disk_added_referrer(tmp_path, stale_tree):
    idx = _make_index(tmp_path, stale_tree)
    # At index time, glossary has NO inbound refs.
    assert idx.get_item("knowledge:reference/glossary")["counts"]["inbound"] == 0

    # A new referrer appears ON DISK but the index is NOT refreshed.
    _write(stale_tree, "ai_general/ai_profiles/roles/newref.yml", ROLE_NEW_REF)

    # delete must refresh from disk and REJECT (don't archive a referenced item).
    res = idx.delete("knowledge:reference/glossary")
    assert res["ok"] is False, "stale index let a referenced item be archived"
    assert res["error"] == "referenced"
    assert "role:newref" in res["referrers"]

    # The file was NOT moved into _archive/.
    assert (stale_tree / "ai_general/ai_context_files/knowledge/reference/glossary.md").exists()
    archived = (stale_tree
                / "ai_general/ai_context_files/knowledge/_archive/reference/glossary.md")
    assert not archived.exists()


def test_delete_dry_run_reflects_disk_added_referrer(tmp_path, stale_tree):
    idx = _make_index(tmp_path, stale_tree)
    _write(stale_tree, "ai_general/ai_profiles/roles/newref.yml", ROLE_NEW_REF)

    plan = idx.delete("knowledge:reference/glossary", dry_run=True)
    # Plan must surface the freshly-added referrer.
    assert "role:newref" in plan.get("referrers", [])


# ===========================================================================
# T1-4 — move atomicity cluster:
#   (a) cross-dir *_latest symlink repoint uses a correct relative target,
#   (b) staged-YAML postconditions abort a no-op/failed referrer repoint,
#   (c) copy-first ordering: a referrer-write failure rolls back cleanly
#       (old file intact, new copy removed, referrer + DB unchanged).
# ===========================================================================

import os as _os

ROLE_REF_GLOSS = """\
name: Dev
description: references the glossary.

context_files:
  reference:
    - ai_context_files/knowledge/reference/glossary
"""
KNOW_GLOSS = "---\ntitle: Glossary\n---\n\n# Glossary\n\nbody\n"


@pytest.fixture
def move_tree(tmp_path):
    root = tmp_path / "ai_root"
    _write(root, "ai_general/ai_profiles/roles/dev.yml", ROLE_REF_GLOSS)
    _write(root, "ai_general/ai_context_files/knowledge/reference/glossary.md", KNOW_GLOSS)
    return root


def test_move_repoints_cross_dir_latest_symlink(tmp_path, move_tree):
    """A sibling *_latest symlink must resolve to the moved file across dirs."""
    refdir = move_tree / "ai_general/ai_context_files/knowledge/reference"
    latest = refdir / "glossary_latest.md"
    latest.symlink_to("glossary.md")  # relative, points at the real file

    idx = _make_index(tmp_path, move_tree)
    # Move to a DIFFERENT category dir (cross-directory).
    res = idx.move("knowledge:reference/glossary", new_category="archived_refs")
    assert res["ok"] is True, res

    new_abs = move_tree / "ai_general/ai_context_files/knowledge/archived_refs/glossary.md"
    assert new_abs.exists()
    # The symlink still lives in the old dir but must resolve to the NEW file.
    assert latest.is_symlink(), "the *_latest symlink was lost"
    assert Path(_os.path.realpath(latest)) == new_abs.resolve(), (
        "symlink did not repoint across directories"
    )
    assert latest.read_text() == KNOW_GLOSS


def test_move_aborts_on_noop_referrer_repoint(tmp_path, move_tree, monkeypatch):
    """If the YAML repoint no-ops (old ref left in place), move must abort and
    leave the file + index untouched — never claim success with a stale ref."""
    idx = _make_index(tmp_path, move_tree)

    # Simulate a broken/no-op replacement: return the original text unchanged.
    monkeypatch.setattr(cm, "_yaml_replace_ref", lambda text, a, b: text)

    res = idx.move("knowledge:reference/glossary", new_name="reference/lexicon")
    assert res["ok"] is False, "move succeeded despite a no-op referrer repoint"

    # File NOT moved; original id still indexed; referrer YAML untouched.
    assert (move_tree / "ai_general/ai_context_files/knowledge/reference/glossary.md").exists()
    assert not (move_tree
                / "ai_general/ai_context_files/knowledge/reference/lexicon.md").exists()
    assert idx.get_item("knowledge:reference/glossary") is not None
    assert idx.get_item("knowledge:reference/lexicon") is None
    assert (move_tree / "ai_general/ai_profiles/roles/dev.yml").read_text() == ROLE_REF_GLOSS


def test_move_referrer_write_failure_rolls_back(tmp_path, move_tree, monkeypatch):
    """Copy-first ordering: a referrer-write failure must undo the new copy and
    leave the old file, the referrer, and the DB exactly as before."""
    idx = _make_index(tmp_path, move_tree)

    real_aw = cm._atomic_write

    def flaky(path, text, *, exclusive=False):
        if str(path).endswith("dev.yml"):
            raise OSError("simulated referrer write failure")
        return real_aw(path, text, exclusive=exclusive)

    monkeypatch.setattr(cm, "_atomic_write", flaky)

    res = idx.move("knowledge:reference/glossary", new_name="reference/lexicon")
    assert res["ok"] is False

    old_abs = move_tree / "ai_general/ai_context_files/knowledge/reference/glossary.md"
    new_abs = move_tree / "ai_general/ai_context_files/knowledge/reference/lexicon.md"
    assert old_abs.exists(), "old file was lost on a rolled-back move"
    assert not new_abs.exists(), "new copy was left behind after rollback"
    assert (move_tree / "ai_general/ai_profiles/roles/dev.yml").read_text() == ROLE_REF_GLOSS
    # DB unchanged: original id present, new id absent.
    assert idx.get_item("knowledge:reference/glossary") is not None
    assert idx.get_item("knowledge:reference/lexicon") is None


def test_move_happy_path_still_works(tmp_path, move_tree):
    """Regression: a normal move repoints the referrer, no danglers, old gone."""
    idx = _make_index(tmp_path, move_tree)
    res = idx.move("knowledge:reference/glossary", new_name="reference/lexicon")
    assert res["ok"] is True

    assert not (move_tree
                / "ai_general/ai_context_files/knowledge/reference/glossary.md").exists()
    assert (move_tree
            / "ai_general/ai_context_files/knowledge/reference/lexicon.md").exists()
    assert _has_edge(idx, "role:dev", "knowledge:reference/lexicon")
    assert not _has_edge(idx, "role:dev", "knowledge:reference/glossary")
    idx.reindex()
    assert idx.validate()["dangling"] == []
    assert _has_edge(idx, "role:dev", "knowledge:reference/lexicon")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
