#!/usr/bin/env python3
"""Schema tests for comms_index.CommsIndex (Task 1: DB + schema only)."""

import sqlite3
import sys
from pathlib import Path

import pytest

# Make the parent (messages/) dir importable so `import comms_index` works.
_MESSAGES_DIR = Path(__file__).resolve().parent.parent
if str(_MESSAGES_DIR) not in sys.path:
    sys.path.insert(0, str(_MESSAGES_DIR))

from uai_toolkit.messages.comms_index import CommsIndex  # noqa: E402


EXPECTED_TABLES = {
    "conversations",
    "messages",
    "deliveries",
    "obligations",
    "body_refs",
    "comms_meta",
}


def _table_names(db_path: Path) -> set:
    con = sqlite3.connect(str(db_path))
    try:
        rows = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
    finally:
        con.close()
    return {r[0] for r in rows}


def test_init_creates_all_tables(tmp_path):
    db_path = tmp_path / "comms.db"
    CommsIndex(db_path=db_path)

    assert db_path.exists()
    names = _table_names(db_path)
    for table in EXPECTED_TABLES:
        assert table in names, f"missing table: {table}"


def test_schema_version_row_present(tmp_path):
    db_path = tmp_path / "comms.db"
    CommsIndex(db_path=db_path)

    con = sqlite3.connect(str(db_path))
    try:
        row = con.execute(
            "SELECT value FROM comms_meta WHERE key = 'schema_version'"
        ).fetchone()
    finally:
        con.close()

    assert row is not None, "schema_version row missing from comms_meta"
    assert str(row[0]) != "", "schema_version value is empty"


def test_init_is_idempotent(tmp_path):
    db_path = tmp_path / "comms.db"
    CommsIndex(db_path=db_path)
    # Second open over the same path must not raise or duplicate.
    CommsIndex(db_path=db_path)

    con = sqlite3.connect(str(db_path))
    try:
        count = con.execute(
            "SELECT COUNT(*) FROM comms_meta WHERE key = 'schema_version'"
        ).fetchone()[0]
    finally:
        con.close()

    assert count == 1, "schema_version should appear exactly once"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
