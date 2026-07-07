#!/usr/bin/env python3
"""
test_context_mgr_delete.py — delete/archive (soft-delete) write tests.

Phase 2 of the Context Mgr overhaul (todo_0331). ``delete`` is the LAST
destructive write op, implemented as a SOFT-DELETE / ARCHIVE — it never
hard-deletes a file by default. The item's file is moved into the kind's
``_archive/`` subtree, which is exactly the convention ``reindex`` already
classifies as ``status='archived'`` (``"_archive" in path.parts``). So the
archive survives a reindex-from-scratch: the item stays archived and drops out
of the default (active) listings rather than silently resurrecting as active.

``delete(item_id, *, force=False, by=None, dry_run=False) -> dict``
  - inbound-ref guard: if any item references this one and NOT ``force`` ->
    REJECT ``{ok:False, error:'referenced', referrers:[src_id,...]}`` (don't
    create danglers silently). With ``force=True`` -> proceed; the now-dangling
    refs are surfaced by ``validate``.
  - archive mechanism: move the file under the kind base's ``_archive/`` subtree
    (so reindex derives status='archived'); update the index + record a
    changelog op="delete" row.
  - ``dry_run=True`` returns the plan (what would be archived + blocking
    referrers) WITHOUT writing.
  - ``restore(item_id)`` moves the file back out of ``_archive/`` (round-trip).

CRITICAL — the ROUND-TRIP GATE: after ``delete`` then a full
reindex-from-scratch, the item is archived / not in the active listing (NOT
resurrected as active). This proves disk and index agree.

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
# Fixtures — two knowledge leaves: ``orphan`` (nothing references it) and
# ``glossary`` (referenced by role:dev). Under tmp_path; never the real library.
# ---------------------------------------------------------------------------

ROLE_DEV = """\
name: Dev
description: A developer role.

context_files:
  reference:
    - ai_context_files/knowledge/reference/glossary
"""

KNOW_GLOSSARY = "---\ntitle: Glossary\n---\n\n# Glossary\n"
KNOW_ORPHAN = "---\ntitle: Orphan\n---\n\n# Orphan\n"


@pytest.fixture
def tree(tmp_path):
    """Build a minimal fixture context tree and return its ai_root.

    Graph:
      role:dev --references--> knowledge:reference/glossary
      knowledge:reference/orphan  (unreferenced)
    """
    root = tmp_path / "ai_root"

    def write(rel, text):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)

    write("ai_general/ai_profiles/roles/dev.yml", ROLE_DEV)
    write("ai_general/ai_context_files/knowledge/reference/glossary.md", KNOW_GLOSSARY)
    write("ai_general/ai_context_files/knowledge/reference/orphan.md", KNOW_ORPHAN)
    return root


def _make_index(tmp_path, root) -> ContextIndex:
    idx = ContextIndex(db_path=tmp_path / "context.db", ai_root=root)
    idx.reindex()
    return idx


def _active_ids(idx):
    """Ids in the default (active) listing."""
    return {r["id"] for r in idx.list_items(status="active", limit=None)}


def _status_of(idx, item_id):
    with idx._connect() as conn:
        row = conn.execute(
            "SELECT status FROM items WHERE id = ?", (item_id,)
        ).fetchone()
        return row["status"] if row else None


def _changelog(idx, *, op=None):
    sql = "SELECT * FROM changelog"
    params = []
    if op:
        sql += " WHERE op=?"
        params.append(op)
    with idx._connect() as conn:
        return conn.execute(sql, params).fetchall()


# ---------------------------------------------------------------------------
# delete an UNreferenced item -> archived
# ---------------------------------------------------------------------------

def test_delete_unreferenced_archives_file_and_index(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.delete("knowledge:reference/orphan", by="tester")
    assert res["ok"] is True
    assert res["dry_run"] is False

    # File moved into the kind's _archive/ subtree; original gone.
    assert not (
        tree / "ai_general/ai_context_files/knowledge/reference/orphan.md"
    ).exists()
    archived = (
        tree
        / "ai_general/ai_context_files/knowledge/_archive/reference/orphan.md"
    )
    assert archived.exists()

    # delete returns the _archive/ path id, but that item is NO LONGER indexed
    # (discovery skips _archive/), so it has no status.
    new_id = "knowledge:_archive/reference/orphan"
    assert res["id"] == new_id
    assert _status_of(idx, new_id) is None

    # Drops out of the default (active) listing.
    assert "knowledge:reference/orphan" not in _active_ids(idx)
    assert new_id not in _active_ids(idx)

    # Changelog op="delete" recorded.
    log = _changelog(idx, op="delete")
    assert len(log) == 1
    assert log[0]["changed_by"] == "tester"


# ---------------------------------------------------------------------------
# ROUND-TRIP GATE: after delete + full reindex-from-scratch the item is still
# archived / not active (NOT resurrected as active).
# ---------------------------------------------------------------------------

def test_delete_survives_reindex_from_scratch(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.delete("knowledge:reference/orphan")
    assert res["ok"] is True
    new_id = res["id"]

    # Full reindex-from-scratch over the on-disk tree.
    idx.reindex()

    # The archived item is not indexed at all (discovery skips _archive/).
    assert _status_of(idx, new_id) is None
    assert new_id not in _active_ids(idx)
    # The old active id was not resurrected.
    assert "knowledge:reference/orphan" not in _active_ids(idx)
    with idx._connect() as conn:
        assert conn.execute(
            "SELECT 1 FROM items WHERE id = ? AND status='active'",
            ("knowledge:reference/orphan",),
        ).fetchone() is None


# ---------------------------------------------------------------------------
# delete a REFERENCED item -> rejected with referrers, nothing changed
# ---------------------------------------------------------------------------

def test_delete_referenced_rejected(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.delete("knowledge:reference/glossary", by="tester")
    assert res["ok"] is False
    assert res["error"] == "referenced"
    assert res["referrers"] == ["role:dev"]

    # Nothing changed: file still at original path, still active, no changelog.
    assert (
        tree / "ai_general/ai_context_files/knowledge/reference/glossary.md"
    ).exists()
    assert _status_of(idx, "knowledge:reference/glossary") == "active"
    assert len(_changelog(idx, op="delete")) == 0


# ---------------------------------------------------------------------------
# delete --force a referenced item -> archived; validate reports the dangling
# ref from the (now-pointing-at-nothing) referrer.
# ---------------------------------------------------------------------------

def test_delete_force_referenced_archives_and_dangles(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.delete("knowledge:reference/glossary", force=True, by="tester")
    assert res["ok"] is True
    new_id = res["id"]
    assert new_id == "knowledge:_archive/reference/glossary"
    # The result notes the now-dangling referrers.
    assert res.get("referrers") == ["role:dev"]

    # File archived on disk, but not indexed (discovery skips _archive/).
    assert _status_of(idx, new_id) is None

    # validate now reports a dangling ref from role:dev to the old id.
    issues = idx.validate()
    dangling = {(d["src_id"], d["dst_id"]) for d in issues["dangling"]}
    assert ("role:dev", "knowledge:reference/glossary") in dangling


# ---------------------------------------------------------------------------
# dry_run writes nothing + returns plan
# ---------------------------------------------------------------------------

def test_delete_dry_run_writes_nothing(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.delete("knowledge:reference/orphan", dry_run=True)
    assert res["ok"] is True
    assert res["dry_run"] is True
    # Plan reports the from/to paths and (empty) blocking referrers.
    assert res["from"]["id"] == "knowledge:reference/orphan"
    assert res["to"]["id"] == "knowledge:_archive/reference/orphan"
    assert res["referrers"] == []

    # Nothing written: file still at original path, still active, no changelog.
    assert (
        tree / "ai_general/ai_context_files/knowledge/reference/orphan.md"
    ).exists()
    assert not (
        tree
        / "ai_general/ai_context_files/knowledge/_archive/reference/orphan.md"
    ).exists()
    assert _status_of(idx, "knowledge:reference/orphan") == "active"
    assert len(_changelog(idx, op="delete")) == 0


def test_delete_dry_run_referenced_reports_blockers(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.delete("knowledge:reference/glossary", dry_run=True)
    # dry_run still surfaces the blocking referrers (so the UI can warn).
    assert res["referrers"] == ["role:dev"]


# ---------------------------------------------------------------------------
# missing item -> error
# ---------------------------------------------------------------------------

def test_delete_missing_item(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.delete("knowledge:does/not_exist")
    assert res["ok"] is False
    assert "no such item" in res["error"]


# ---------------------------------------------------------------------------
# delete moves a file into _archive/ (which is no longer indexed → item is gone)
# ---------------------------------------------------------------------------

def test_delete_archives_file_and_drops_from_index(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.delete("knowledge:reference/orphan")
    assert res["ok"] is True

    # File moved into _archive/ on disk (soft delete)...
    assert not (
        tree / "ai_general/ai_context_files/knowledge/reference/orphan.md"
    ).exists()
    assert (
        tree
        / "ai_general/ai_context_files/knowledge/_archive/reference/orphan.md"
    ).exists()

    # ...but it is no longer indexed (discovery skips _archive/; restore dropped).
    assert "knowledge:reference/orphan" not in _active_ids(idx)
    idx.reindex()
    assert "knowledge:reference/orphan" not in _active_ids(idx)
    assert _status_of(idx, "knowledge:reference/orphan") is None


# ---------------------------------------------------------------------------
# CLI: delete + archive alias
# ---------------------------------------------------------------------------

def test_cli_delete_and_archive_alias(tmp_path, tree, monkeypatch):
    from uai_toolkit.context_files import context_mgr as cm

    # The CLI builds ContextIndex from the module-global AI_ROOT; point it at
    # the fixture tree so reindex sees the fixture (never the real library).
    monkeypatch.setattr(cm, "AI_ROOT", tree)

    db = tmp_path / "context.db"
    idx = _make_index(tmp_path, tree)
    del idx  # the CLI opens its own index against the same db + tree.

    # delete verb archives the unreferenced item.
    rc = cm.main(["--db", str(db), "delete", "knowledge:reference/orphan",
                  "--json"])
    assert rc == 0

    # archive alias resolves to the same handler (referenced item rejected
    # cleanly rather than crashing).
    rc2 = cm.main(["--db", str(db), "archive", "knowledge:reference/glossary",
                   "--json"])
    assert rc2 == 0
