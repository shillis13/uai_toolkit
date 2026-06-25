"""SQLite-backed file-access tracker for anti-clobbering.

Drop-in replacement for the original JSONL tracker, with the same public API
(log_read/log_write/log_deny/get_last_read/get_writes_since/check_conflict/
prune/ConflictInfo). SQLite transactions provide the concurrency safety the
JSONL version lacked:

  - JSONL appended without locking -> concurrent writers could interleave
    partial records on one line, silently corrupting state.
  - prune() did a non-atomic read-filter-rewrite -> a concurrent append during
    the rewrite window was lost.

Both are gone: every mutation is a single transaction, and prune is one DELETE.
Works identically on macOS, Linux, and Windows (stdlib sqlite3, WAL mode,
busy_timeout for cross-process contention).

State lives in $AI_ROOT/data/file_access/access.db (override via config key
file_access.db_path). Two logical tables: access_state (operational, pruned)
and access_log (durable audit, never pruned).
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import NamedTuple

from uai_toolkit.paths import ai_root, get

MAX_AGE_HOURS = 48
MAX_ROWS = 5000


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------

class ConflictInfo(NamedTuple):
    conflicting_session: str
    write_ts: float
    your_last_read_ts: float


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def _db_path() -> Path:
    override = get("file_access.db_path")
    if override:
        return Path(override).expanduser()
    return ai_root() / "data" / "file_access" / "access.db"


def _connect() -> sqlite3.Connection:
    """Open a connection, creating schema on first use. Caller closes."""
    path = _db_path()
    path.parent.mkdir(parents=True, exist_ok=True)  # first-run data dir
    conn = sqlite3.connect(str(path), timeout=5.0)
    conn.execute("PRAGMA journal_mode=WAL")     # concurrent readers + one writer
    conn.execute("PRAGMA busy_timeout=5000")    # wait out cross-process contention
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS access_state (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL, iso TEXT, session TEXT, op TEXT,
            file TEXT, mtime REAL, conflicting_session TEXT);
        CREATE TABLE IF NOT EXISTS access_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts REAL NOT NULL, iso TEXT, session TEXT, op TEXT,
            file TEXT, detail TEXT);
        CREATE INDEX IF NOT EXISTS idx_state_file_op_ts
            ON access_state(file, op, ts);
        CREATE INDEX IF NOT EXISTS idx_state_sess_file_op
            ON access_state(session, file, op);
        """
    )
    conn.commit()
    return conn


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _log_all_checks() -> bool:
    return bool(get("file_access.log_all_checks", True))


def _canonical(file_path: str) -> str:
    """Canonical path so hardlinks/symlinks compare equal.

    normcase folds case on Windows (case-insensitive FS) and is a no-op on
    POSIX, so the same physical file isn't tracked under two keys.
    """
    try:
        return os.path.normcase(os.path.realpath(file_path))
    except OSError:
        return os.path.normcase(file_path)


def _get_mtime(file_path: str) -> float:
    try:
        return os.path.getmtime(file_path)
    except OSError:
        return 0.0


def _iso_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _state(conn, ts, session, op, file, mtime=None, conflicting=None):
    conn.execute(
        "INSERT INTO access_state(ts, iso, session, op, file, mtime, conflicting_session)"
        " VALUES (?,?,?,?,?,?,?)",
        (ts, _iso_now(), session, op, file, mtime, conflicting),
    )


def _audit(conn, ts, session, op, file, detail: dict):
    conn.execute(
        "INSERT INTO access_log(ts, iso, session, op, file, detail) VALUES (?,?,?,?,?,?)",
        (ts, _iso_now(), session, op, file, json.dumps(detail)),
    )


# ---------------------------------------------------------------------------
# State operations
# ---------------------------------------------------------------------------

def log_read(session_id: str, file_path: str) -> None:
    canon = _canonical(file_path)
    ts = time.time()
    mtime = _get_mtime(canon)
    conn = _connect()
    try:
        with conn:
            _state(conn, ts, session_id, "read", canon, mtime)
            if _log_all_checks():
                _audit(conn, ts, session_id, "read", canon, {"mtime": mtime})
    finally:
        conn.close()


def log_write(session_id: str, file_path: str) -> None:
    canon = _canonical(file_path)
    ts = time.time()
    mtime = _get_mtime(canon)
    conn = _connect()
    try:
        with conn:
            _state(conn, ts, session_id, "write", canon, mtime)
            if _log_all_checks():
                _audit(conn, ts, session_id, "write", canon, {"mtime": mtime})
    finally:
        conn.close()


def log_deny(session_id: str, file_path: str, conflicting_session: str) -> None:
    """Record that an edit was BLOCKED due to conflict. Always audited."""
    canon = _canonical(file_path)
    ts = time.time()
    conn = _connect()
    try:
        with conn:
            _state(conn, ts, session_id, "deny", canon, conflicting=conflicting_session)
            _audit(conn, ts, session_id, "deny", canon,
                   {"conflicting_session": conflicting_session})
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Conflict detection
# ---------------------------------------------------------------------------

def get_last_read(session_id: str, file_path: str) -> float | None:
    canon = _canonical(file_path)
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT MAX(ts) FROM access_state"
            " WHERE session=? AND file=? AND op='read'",
            (session_id, canon),
        ).fetchone()
        return row[0] if row and row[0] is not None else None
    finally:
        conn.close()


def get_writes_since(file_path: str, since_ts: float, exclude_session: str = "") -> list[dict]:
    canon = _canonical(file_path)
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT ts, session, file, mtime FROM access_state"
            " WHERE file=? AND op='write' AND ts>? AND session!=?"
            " ORDER BY ts",
            (canon, since_ts, exclude_session),
        ).fetchall()
        return [{"ts": r[0], "session": r[1], "file": r[2], "mtime": r[3]} for r in rows]
    finally:
        conn.close()


def check_conflict(session_id: str, file_path: str) -> ConflictInfo | None:
    """Return None if safe, or ConflictInfo if another session wrote since our
    last read. Canonicalizes paths; audits the result per log_all_checks."""
    canon = _canonical(file_path)
    last_read = get_last_read(session_id, canon)
    if last_read is None:
        if _log_all_checks():
            _audit_standalone(session_id, "check_pass", canon, {"reason": "no_prior_read"})
        return None

    writes = get_writes_since(canon, last_read, exclude_session=session_id)
    if not writes:
        if _log_all_checks():
            _audit_standalone(session_id, "check_pass", canon,
                              {"reason": "no_conflicting_writes", "last_read_ts": last_read})
        return None

    latest = max(writes, key=lambda w: w["ts"])
    conflict = ConflictInfo(
        conflicting_session=latest["session"],
        write_ts=latest["ts"],
        your_last_read_ts=last_read,
    )
    _audit_standalone(session_id, "check_conflict", canon, {  # always audited
        "conflicting_session": conflict.conflicting_session,
        "write_ts": conflict.write_ts,
        "last_read_ts": conflict.your_last_read_ts,
    })
    return conflict


def _audit_standalone(session_id: str, op: str, file: str, detail: dict) -> None:
    conn = _connect()
    try:
        with conn:
            _audit(conn, time.time(), session_id, op, file, detail)
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Pruning (state only; log is never pruned) — now atomic
# ---------------------------------------------------------------------------

def prune(max_age_hours: int = MAX_AGE_HOURS) -> None:
    """Drop state rows older than max_age_hours, then cap to MAX_ROWS newest.

    Both are single DELETE statements in one transaction — no read-rewrite
    window for a concurrent append to fall into.
    """
    cutoff = time.time() - (max_age_hours * 3600)
    conn = _connect()
    try:
        with conn:
            conn.execute("DELETE FROM access_state WHERE ts < ?", (cutoff,))
            conn.execute(
                "DELETE FROM access_state WHERE id NOT IN "
                "(SELECT id FROM access_state ORDER BY ts DESC LIMIT ?)",
                (MAX_ROWS,),
            )
    finally:
        conn.close()
