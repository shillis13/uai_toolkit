#!/usr/bin/env python3
"""
test_context_mgr_tier2_fixes.py — Codex tier-2 hardening folds (todo_0331).

T2-9   delete's result must be REPAIR-READY: alongside the bare ``referrers``
       id list, carry ``repair`` = [{src_id, old_ref, old_dst_id}] so a tool can
       reconstruct/repoint the now-dangling refs a --force archive leaves.
T2-11  ``restore`` must be reachable from the CLI (the engine method existed but
       no subcommand was wired), and round-trip a delete.

SAFETY: every test builds against a TEMP fixture tree + temp DB. No real library
or the real data/context.db is ever touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

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


ROLE_REF = """\
name: Dev
description: references the glossary.

context_files:
  reference:
    - ai_context_files/knowledge/reference/glossary
"""
KNOW = "---\ntitle: Glossary\n---\n\n# Glossary\n"


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "ai_root"
    _write(root, "ai_general/ai_profiles/roles/dev.yml", ROLE_REF)
    _write(root, "ai_general/ai_context_files/knowledge/reference/glossary.md", KNOW)
    return root


# ===========================================================================
# T2-9 — repair-ready force-delete result
# ===========================================================================

def test_force_delete_result_is_repair_ready(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.delete("knowledge:reference/glossary", force=True)
    assert res["ok"] is True
    # Backward-compatible id list still present.
    assert res["referrers"] == ["role:dev"]
    # Rich repair detail: enough to repoint each now-dangling referrer.
    repair = res.get("repair")
    assert isinstance(repair, list) and repair, "missing repair detail"
    entry = repair[0]
    assert entry["src_id"] == "role:dev"
    assert entry["old_dst_id"] == "knowledge:reference/glossary"
    assert entry["old_ref"] == "ai_context_files/knowledge/reference/glossary"


def test_referenced_rejection_also_carries_repair(tmp_path, tree):
    idx = _make_index(tmp_path, tree)
    res = idx.delete("knowledge:reference/glossary")  # not forced -> rejected
    assert res["ok"] is False and res["error"] == "referenced"
    assert {e["src_id"] for e in res.get("repair", [])} == {"role:dev"}


def test_unreferenced_delete_has_empty_or_no_repair(tmp_path, tree):
    _write(tree, "ai_general/ai_context_files/knowledge/reference/orphan.md", KNOW)
    idx = _make_index(tmp_path, tree)
    res = idx.delete("knowledge:reference/orphan")
    assert res["ok"] is True
    assert not res.get("repair")  # None or []


# (T2-11 restore tests removed — the restore feature was dropped 2026-07-02;
#  archived items are no longer indexed, so there is nothing to restore via the
#  tool. Bring an item back by moving its file out of _archive/ on disk.)


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
