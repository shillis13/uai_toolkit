#!/usr/bin/env python3
"""
test_context_mgr_schema.py — Schema tests for the Context Mgr SQLite index.

Phase 1 of the Context Mgr overhaul (todo_0331). Verifies that opening a
ContextIndex creates the full schema (items, edges, changelog, items_fts,
context_meta), records a schema_version, is idempotent on re-open, and that
the FTS table exists (fts5 preferred, plain-table fallback otherwise).
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

# Make the parent module importable
_SCRIPT_DIR = Path(__file__).resolve().parent.parent
if str(_SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPT_DIR))

from uai_toolkit.context_files.context_mgr import ContextIndex, SCHEMA_VERSION


EXPECTED_TABLES = {"items", "edges", "changelog", "items_fts", "context_meta"}


def _table_names(db_path: Path) -> set:
    conn = sqlite3.connect(str(db_path))
    try:
        rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table','view')"
        ).fetchall()
    finally:
        conn.close()
    return {r[0] for r in rows}


def test_creates_all_tables(tmp_path):
    db = tmp_path / "context.db"
    ContextIndex(db_path=db)
    names = _table_names(db)
    assert EXPECTED_TABLES.issubset(names), f"missing: {EXPECTED_TABLES - names}"


def test_schema_version_recorded(tmp_path):
    db = tmp_path / "context.db"
    idx = ContextIndex(db_path=db)
    with idx._connect() as conn:
        rows = conn.execute(
            "SELECT value FROM context_meta WHERE key='schema_version'"
        ).fetchall()
    assert len(rows) == 1
    assert int(rows[0][0]) == SCHEMA_VERSION


def test_idempotent_reopen(tmp_path):
    db = tmp_path / "context.db"
    ContextIndex(db_path=db)
    # Re-open should not error and must not duplicate the schema_version row.
    idx = ContextIndex(db_path=db)
    with idx._connect() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM context_meta WHERE key='schema_version'"
        ).fetchone()[0]
    assert count == 1


def test_fts_table_exists(tmp_path):
    db = tmp_path / "context.db"
    idx = ContextIndex(db_path=db)
    names = _table_names(db)
    assert "items_fts" in names
    # Whether fts5 or fallback, the attribute should report which one is active.
    assert idx.fts5_available in (True, False)


def test_indexes_created(tmp_path):
    db = tmp_path / "context.db"
    ContextIndex(db_path=db)
    conn = sqlite3.connect(str(db))
    try:
        idx_names = {
            r[0]
            for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index'"
            ).fetchall()
        }
    finally:
        conn.close()
    for expected in (
        "idx_items_kind",
        "idx_items_name",
        "idx_edges_dst",
        "idx_changelog_item",
    ):
        assert expected in idx_names, f"missing index {expected}"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
