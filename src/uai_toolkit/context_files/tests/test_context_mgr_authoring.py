#!/usr/bin/env python3
"""
test_context_mgr_authoring.py — Write-path (authoring) tests for the Context Mgr.

Phase 2 / Task 1 of the Context Mgr overhaul (todo_0331). This is the FIRST
write-side capability. It verifies the AUTHORING write path for context files
(kinds ``knowledge`` and ``instruction`` — the .md-with-frontmatter case):

- ``create(kind, title, category)`` derives a name slug, computes the path under
  the kind's category dir, rejects collisions, writes a minimal stub (YAML
  frontmatter + a body heading), indexes the item row, and records a
  ``changelog`` op="create" row. ``dry_run`` computes the planned id/path WITHOUT
  writing the file or any row.
- ``update_content(item_id, content)`` replaces the BODY of an existing
  context-file item (preserving its frontmatter), reindexes (size/hash/summary
  refresh), and records a ``changelog`` op="update" field="content" row.
- ``edit_command(item_id)`` resolves the editor (``$EDITOR``/``vi``) + path
  without launching anything.

CRITICAL SAFETY: every test builds against a TEMP fixture tree + a temp DB. No
real library (``ai_general/ai_context_files/``, ``ai_profiles/``) or the real
``data/context.db`` is ever touched.
"""

from __future__ import annotations

import hashlib
import os
import sys
from pathlib import Path

import pytest

# Make the parent module importable.
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from uai_toolkit.context_files.context_mgr import ContextIndex


# ---------------------------------------------------------------------------
# Fixtures — a minimal context tree under tmp_path; never the real library.
# ---------------------------------------------------------------------------

EXISTING_MD = """\
---
title: Existing Note
summary: A pre-existing note.
---

# Existing Note

Original body content.
"""


@pytest.fixture
def tree(tmp_path):
    """Build a minimal fixture context tree and return its ai_root."""
    root = tmp_path / "ai_root"
    # One pre-existing knowledge file so collision + update tests have a target.
    p = root / "ai_general/ai_context_files/knowledge/reference/existing.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(EXISTING_MD)
    return root


def _make_index(tmp_path, root) -> ContextIndex:
    return ContextIndex(db_path=tmp_path / "context.db", ai_root=root)


def _rows(idx, sql, params=()):
    with idx._connect() as conn:
        return conn.execute(sql, params).fetchall()


# ---------------------------------------------------------------------------
# create — happy path
# ---------------------------------------------------------------------------

def test_create_writes_stub_and_indexes(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.create(
        kind="knowledge", title="My New Topic", category="reference", by="tester"
    )
    assert res["ok"] is True
    assert res["dry_run"] is False
    assert res["id"] == "knowledge:reference/my_new_topic"
    assert res["path"] == (
        "ai_general/ai_context_files/knowledge/reference/my_new_topic.md"
    )

    # File written on disk with frontmatter + heading.
    f = tree / res["path"]
    assert f.exists()
    text = f.read_text()
    assert text.startswith("---\n")
    assert "title: My New Topic" in text
    assert "# My New Topic" in text

    # Indexed: an items row exists with the right kind/path.
    rows = {r["id"]: r for r in _rows(idx, "SELECT * FROM items")}
    assert res["id"] in rows
    row = rows[res["id"]]
    assert row["kind"] == "knowledge"
    assert row["name"] == "reference/my_new_topic"
    assert row["path"] == res["path"]
    assert row["content_hash"]


def test_create_records_changelog(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.create(
        kind="knowledge", title="Audit Me", category="reference", by="tester"
    )
    log = _rows(
        idx, "SELECT * FROM changelog WHERE item_id=?", (res["id"],)
    )
    assert len(log) == 1
    assert log[0]["op"] == "create"
    assert log[0]["changed_by"] == "tester"
    assert log[0]["changed_at"]


def test_create_instruction_kind_path(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.create(kind="instruction", title="Do The Thing", category="rules")
    assert res["ok"] is True
    assert res["path"] == (
        "ai_general/ai_context_files/instructions/rules/do_the_thing.md"
    )
    assert (tree / res["path"]).exists()


def test_create_changed_by_defaults_to_env(tmp_path, tree, monkeypatch):
    monkeypatch.setenv("AI_TRACKING_ID", "session_xyz")
    idx = _make_index(tmp_path, tree)
    res = idx.create(kind="knowledge", title="Env By", category="reference")
    log = _rows(idx, "SELECT * FROM changelog WHERE item_id=?", (res["id"],))
    assert log[0]["changed_by"] == "session_xyz"


def test_create_changed_by_unknown_without_env(tmp_path, tree, monkeypatch):
    monkeypatch.delenv("AI_TRACKING_ID", raising=False)
    idx = _make_index(tmp_path, tree)
    res = idx.create(kind="knowledge", title="No Env", category="reference")
    log = _rows(idx, "SELECT * FROM changelog WHERE item_id=?", (res["id"],))
    assert log[0]["changed_by"] == "unknown"


# ---------------------------------------------------------------------------
# create — slug derivation + explicit name
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "title,expected_name",
    [
        ("Hello World", "hello_world"),
        ("  Spaced  Out  ", "spaced_out"),
        ("Weird!@#Chars Here", "weird_chars_here"),
        ("Mixed-Case_Name", "mixed-case_name"),
        ("UPPER lower", "upper_lower"),
    ],
)
def test_create_slug_derivation(tmp_path, tree, title, expected_name):
    idx = _make_index(tmp_path, tree)
    res = idx.create(kind="knowledge", title=title, category="reference")
    assert res["id"] == "knowledge:reference/{}".format(expected_name)


def test_create_explicit_name_overrides_slug(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.create(
        kind="knowledge", title="A Long Title", category="reference",
        name="short",
    )
    assert res["id"] == "knowledge:reference/short"
    assert res["path"].endswith("/reference/short.md")


# ---------------------------------------------------------------------------
# create — dry_run writes nothing
# ---------------------------------------------------------------------------

def test_create_dry_run_writes_nothing(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.create(
        kind="knowledge", title="Planned Only", category="reference",
        dry_run=True,
    )
    assert res["ok"] is True
    assert res["dry_run"] is True
    # Planned id/path are still computed.
    assert res["id"] == "knowledge:reference/planned_only"
    assert res["path"].endswith("/reference/planned_only.md")
    # But nothing was written: no file, no item row, no changelog row.
    assert not (tree / res["path"]).exists()
    assert _rows(idx, "SELECT COUNT(*) AS n FROM items")[0]["n"] == 0
    assert _rows(idx, "SELECT COUNT(*) AS n FROM changelog")[0]["n"] == 0


# ---------------------------------------------------------------------------
# create — rejections
# ---------------------------------------------------------------------------

def test_create_rejects_existing_path(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    # existing.md already on disk in the fixture.
    res = idx.create(kind="knowledge", title="Existing", category="reference")
    assert res["ok"] is False
    assert "error" in res
    # The pre-existing file is untouched.
    f = tree / "ai_general/ai_context_files/knowledge/reference/existing.md"
    assert f.read_text() == EXISTING_MD


def test_create_rejects_existing_id(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    first = idx.create(kind="knowledge", title="Dup Topic", category="cat")
    assert first["ok"] is True
    # Second create with same kind/category/name -> id collision -> reject.
    second = idx.create(kind="knowledge", title="Dup Topic", category="cat")
    assert second["ok"] is False
    assert "error" in second
    # Only one changelog row for that id (the first create).
    log = _rows(idx, "SELECT * FROM changelog WHERE item_id=?", (first["id"],))
    assert len(log) == 1


def test_create_rejects_bad_kind(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    for bad in ("role", "profile", "brief", "memory", "nonsense"):
        res = idx.create(kind=bad, title="X", category="reference")
        assert res["ok"] is False
        assert "error" in res


def test_create_rejects_empty_title(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.create(kind="knowledge", title="   ", category="reference")
    assert res["ok"] is False
    assert "error" in res


def test_create_rejects_path_traversal(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    for bad_cat in ("../escape", "a/../../b", "..", "/abs"):
        res = idx.create(kind="knowledge", title="X", category=bad_cat)
        assert res["ok"] is False, "category {!r} should be rejected".format(bad_cat)
        assert "error" in res
    # A traversal attempt via name is also rejected.
    res = idx.create(
        kind="knowledge", title="X", category="reference", name="../../evil"
    )
    assert res["ok"] is False


def test_create_dry_run_rejects_collision(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.create(
        kind="knowledge", title="Existing", category="reference", dry_run=True
    )
    assert res["ok"] is False
    assert "error" in res


# ---------------------------------------------------------------------------
# update_content
# ---------------------------------------------------------------------------

def test_update_content_replaces_body_keeps_frontmatter(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.reindex()
    item_id = "knowledge:reference/existing"
    res = idx.update_content(item_id, "Brand new body line.\n", by="editor")
    assert res["ok"] is True

    text = (tree / "ai_general/ai_context_files/knowledge/reference/existing.md").read_text()
    # Frontmatter preserved.
    assert "title: Existing Note" in text
    assert "summary: A pre-existing note." in text
    # Old body gone, new body present.
    assert "Original body content." not in text
    assert "Brand new body line." in text


def test_update_content_reindexes_hash(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.reindex()
    item_id = "knowledge:reference/existing"
    before = _rows(idx, "SELECT content_hash FROM items WHERE id=?", (item_id,))[0][
        "content_hash"
    ]
    idx.update_content(item_id, "Different content entirely.\n", by="editor")
    f = tree / "ai_general/ai_context_files/knowledge/reference/existing.md"
    expected = hashlib.sha256(f.read_bytes()).hexdigest()
    after = _rows(idx, "SELECT content_hash FROM items WHERE id=?", (item_id,))[0][
        "content_hash"
    ]
    assert after == expected
    assert after != before


def test_update_content_records_changelog(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.reindex()
    item_id = "knowledge:reference/existing"
    idx.update_content(item_id, "New body.\n", by="editor")
    log = _rows(
        idx,
        "SELECT * FROM changelog WHERE item_id=? AND op='update'",
        (item_id,),
    )
    assert len(log) == 1
    assert log[0]["field"] == "content"
    assert log[0]["changed_by"] == "editor"


def test_update_content_rejects_missing_item(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.reindex()
    res = idx.update_content("knowledge:reference/nope", "x", by="editor")
    assert res["ok"] is False
    assert "error" in res


def test_update_content_rejects_non_context_file(tmp_path, tree):
    # Build a tree with a role (composition kind), reindex, try to update it.
    root = tree
    rp = root / "ai_general/ai_profiles/roles/dev.yml"
    rp.parent.mkdir(parents=True, exist_ok=True)
    rp.write_text("name: Dev\ndescription: A role.\n")
    idx = _make_index(tmp_path, root)
    idx.reindex()
    res = idx.update_content("role:dev", "anything", by="editor")
    assert res["ok"] is False
    assert "error" in res
    # The role file is untouched.
    assert rp.read_text() == "name: Dev\ndescription: A role.\n"


# ---------------------------------------------------------------------------
# edit_command
# ---------------------------------------------------------------------------

def test_edit_command_resolves_editor_and_path(tmp_path, tree, monkeypatch):
    monkeypatch.setenv("EDITOR", "nano")
    idx = _make_index(tmp_path, tree)
    idx.reindex()
    res = idx.edit_command("knowledge:reference/existing")
    assert res["ok"] is True
    assert res["editor"] == "nano"
    assert res["path"].endswith("/reference/existing.md")
    # Path is absolute / resolvable to a real file (so the CLI can launch it).
    assert Path(res["path"]).exists()


def test_edit_command_default_editor(tmp_path, tree, monkeypatch):
    monkeypatch.delenv("EDITOR", raising=False)
    idx = _make_index(tmp_path, tree)
    idx.reindex()
    res = idx.edit_command("knowledge:reference/existing")
    assert res["ok"] is True
    assert res["editor"] == "vi"


def test_edit_command_rejects_missing(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    idx.reindex()
    res = idx.edit_command("knowledge:reference/nope")
    assert res["ok"] is False
    assert "error" in res


# ---------------------------------------------------------------------------
# Safety: the real library is never used (defaults are overridden in tests).
# ---------------------------------------------------------------------------

def test_index_uses_tmp_db_and_tmp_root(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    assert str(idx.db_path).startswith(str(tmp_path))
    assert str(idx.ai_root).startswith(str(tmp_path))


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
