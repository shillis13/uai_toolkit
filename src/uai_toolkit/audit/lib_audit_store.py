"""Low-level JSONL + SQLite storage for audit events."""
from __future__ import annotations

import fcntl
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    ts TEXT NOT NULL,
    action TEXT NOT NULL,
    actor_tracking_id TEXT,
    actor_label TEXT,
    caller_pid INTEGER,
    caller_ppid INTEGER,
    target_session TEXT,
    target_platform TEXT,
    text_length INTEGER,
    success INTEGER,
    jsonl_file TEXT NOT NULL,
    jsonl_line INTEGER NOT NULL,
    target_file TEXT
);
CREATE INDEX IF NOT EXISTS idx_ts ON events(ts);
CREATE INDEX IF NOT EXISTS idx_target_file ON events(target_file);
CREATE INDEX IF NOT EXISTS idx_target_session ON events(target_session);
CREATE INDEX IF NOT EXISTS idx_actor_pid ON events(caller_pid, ts);
CREATE INDEX IF NOT EXISTS idx_actor_tracking ON events(actor_tracking_id);
CREATE INDEX IF NOT EXISTS idx_ghost_detect ON events(action, caller_pid, ts);
"""


class AuditStore:
    """Manages JSONL event files and SQLite index for one audit category."""

    def __init__(self, base_dir: Path):
        self._base_dir = Path(base_dir)
        self._events_dir = self._base_dir / "events"
        self._db_path = self._base_dir / "index.db"
        self._conn: sqlite3.Connection | None = None

    def _ensure_dirs(self) -> None:
        self._events_dir.mkdir(parents=True, exist_ok=True)

    def _today_file(self) -> Path:
        return self._events_dir / f"audit_{datetime.now(timezone.utc).strftime('%Y-%m-%d')}.jsonl"

    def _get_conn(self) -> sqlite3.Connection:
        """Lazy-init SQLite connection with WAL mode and schema."""
        if self._conn is None:
            self._base_dir.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self._db_path))
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(_SCHEMA)
            conn.commit()
            self._conn = conn
        return self._conn

    def _index_event(self, event: dict, jsonl_file: str, jsonl_line: int) -> None:
        """Insert event into SQLite index. Silent failure on error."""
        try:
            actor = event.get("actor") or {}
            caller = event.get("caller") or {}
            target = event.get("target") or {}
            details = event.get("details") or {}
            success = {True: 1, False: 0}.get((event.get("details") or {}).get("success"))
            conn = self._get_conn()
            conn.execute(
                """INSERT INTO events
                   (ts, action, actor_tracking_id, actor_label,
                    caller_pid, caller_ppid,
                    target_session, target_platform,
                    text_length, success,
                    jsonl_file, jsonl_line,
                    target_file)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    event.get("ts", ""),
                    event.get("action", ""),
                    actor.get("tracking_id"),
                    actor.get("label"),
                    caller.get("pid"),
                    caller.get("ppid"),
                    target.get("session"),
                    target.get("platform"),
                    details.get("text_length"),
                    success,
                    jsonl_file,
                    jsonl_line,
                    target.get("file"),
                ),
            )
            conn.commit()
        except Exception:
            pass

    def append(self, event: dict) -> int | None:
        """Append event to today's JSONL file. Returns line number or None on error."""
        self._ensure_dirs()
        path = self._today_file()
        line = json.dumps(event, separators=(",", ":"), ensure_ascii=False) + "\n"
        try:
            with open(path, "a+") as f:
                fcntl.flock(f, fcntl.LOCK_EX)
                # Count existing lines BEFORE writing, while still holding lock
                f.seek(0, 2)  # Seek to end
                pos = f.tell()
                if pos > 0:
                    f.seek(0)
                    line_number = sum(1 for _ in f) + 1
                    f.seek(0, 2)  # Back to end
                else:
                    line_number = 1
                f.write(line)
                f.flush()
        except OSError:
            return None
        self._index_event(event, path.name, line_number)
        return line_number

    def read_line(self, jsonl_file: str, line_number: int) -> dict | None:
        """Read a specific line from a JSONL file. Lines are 1-indexed."""
        path = self._events_dir / jsonl_file
        if not path.exists():
            return None
        try:
            with open(path) as f:
                for i, raw in enumerate(f, 1):
                    if i == line_number:
                        return json.loads(raw)
        except (OSError, json.JSONDecodeError):
            pass
        return None

    def query(self, **kwargs) -> list[dict]:
        """Query events from SQLite index, returning full event dicts from JSONL.

        Supported kwargs: target_session, actor_tracking_id, caller_pid,
                          action, since, until, label
        """
        conditions: list[str] = []
        params: list = []

        mapping = {
            "target_session": "target_session",
            "actor_tracking_id": "actor_tracking_id",
            "caller_pid": "caller_pid",
            "action": "action",
            "label": "actor_label",
            "target_file": "target_file",
        }
        for kwarg, col in mapping.items():
            if kwarg in kwargs:
                conditions.append(f"{col} = ?")
                params.append(kwargs[kwarg])

        if "since" in kwargs:
            conditions.append("ts >= ?")
            params.append(kwargs["since"])
        if "until" in kwargs:
            conditions.append("ts <= ?")
            params.append(kwargs["until"])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        sql = f"SELECT jsonl_file, jsonl_line FROM events {where} ORDER BY id"

        try:
            conn = self._get_conn()
            rows = conn.execute(sql, params).fetchall()
        except Exception:
            return []

        results = []
        for jsonl_file, jsonl_line in rows:
            event = self.read_line(jsonl_file, jsonl_line)
            if event is not None:
                results.append(event)
        return results

    def rebuild_index(self) -> int:
        """Drop and recreate SQLite DB from all JSONL files. Returns event count."""
        # Close and remove existing DB
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception:
                pass
            self._conn = None
        if self._db_path.exists():
            self._db_path.unlink()

        count = 0
        if not self._events_dir.exists():
            return count

        for jsonl_path in sorted(self._events_dir.glob("audit_*.jsonl")):
            try:
                with open(jsonl_path) as f:
                    for line_number, raw in enumerate(f, 1):
                        raw = raw.strip()
                        if not raw:
                            continue
                        try:
                            event = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        self._index_event(event, jsonl_path.name, line_number)
                        count += 1
            except OSError:
                continue

        return count
