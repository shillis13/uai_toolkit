#!/usr/bin/env python3
"""
session_store.py — SQLite-backed session data store.

Replaces the file-per-session registry in lib_session.py with a single SQLite
database. Serves as both an importable Python library and a CLI tool.

Library usage:
    from uai_toolkit.session_mgmt.session_store import SessionStore
    store = SessionStore()
    store.create(tracking_id=..., terminal_session=..., ...)
    session = store.get(tracking_id)
    sessions = store.list(platform="claude_cli", status="running")
    sessions = store.list(filters={"cli_session_id": "abcd", "display_name": "chat"})

CLI usage:
    session_store.py list [--platform X] [--status X] [--text X] [--<field> X] [--json]
    session_store.py get <identifier>
    session_store.py create --tracking-id X --terminal-session X --platform X [...]
    session_store.py update <tracking_id> --set field=value [--set field=value ...]
    session_store.py delete <tracking_id>
    session_store.py import-registry    # one-time migration from JSON files
    session_store.py export [--format json|csv]

Database location: {AI_ROOT}/ai_general/data/sessions.db
Schema version tracked in 'metadata' table for forward migration.

Architecture: This module is the single authority for session data storage.
All readers and writers go through this API. The file format (SQLite) is an
implementation detail hidden behind the API.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure this dir and cli/ (for lib_paths) are importable
_SCRIPT_DIR = Path(__file__).resolve().parent
_CLI_DIR = _SCRIPT_DIR.parent / "cli"
for _d in (_SCRIPT_DIR, _CLI_DIR):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from uai_toolkit.cli.lib_paths import AI_ROOT
from uai_toolkit.session_mgmt.lib_session import instance_filename
from uai_toolkit.session_mgmt.lib_session_substrate import build_tmux_command, sanitize_tmux_server_name

# Add utils dir for standard_colors
_UTILS_DIR = AI_ROOT / "ai_general" / "scripts" / "utils"
if str(_UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(_UTILS_DIR))

from uai_toolkit.common_utils.standard_colors import c, format_help, bold, dim, heading

# Structured logging — best-effort; must never break the store if unavailable.
_SCRIPTS_DIR = _SCRIPT_DIR.parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))
try:
    from uai_toolkit.common_utils.lib_logging import get_logger
    log = get_logger(__name__)  # "session_mgmt.session_store" style name
except Exception:  # pragma: no cover - logging is auxiliary, never fatal
    import logging as _logging
    log = _logging.getLogger("session_store")


# =============================================================================
# Schema
# =============================================================================

SCHEMA_VERSION = 5

DB_PATH = AI_ROOT / "ai_general" / "data" / "sessions.db"
SIGNAL_FILE = AI_ROOT / "ai_general" / "data" / "sessions.changed"
SESSION_DATA_DIR = AI_ROOT / "ai_general" / "data" / "sessions"

PLATFORM_CODES = {
    "claude_cli": "cla",
    "codex_cli": "cod",
    "gemini_cli": "gem",
}

CODE_PLATFORMS = {v: k for k, v in PLATFORM_CODES.items()}

NEW_TRACKING_RE = re.compile(
    r"^(?P<date>\d{8})_(?P<time>\d{6})_(?P<uuid8>[0-9a-f]{8})_(?P<code>cla|cod|gem)$"
)


def compute_session_dir_path(tracking_id: str, platform: str) -> Path:
    """Compute v5.3 per-session directory path.

    New IDs use ai_general/data/sessions/{platform}/{YYYY}/{MM}/{tracking_id}.
    Legacy IDs are kept under ai_general/data/sessions/{platform}/legacy/{tracking_id}.
    """
    match = NEW_TRACKING_RE.match(tracking_id)
    if match:
        date = match.group("date")
        return SESSION_DATA_DIR / platform / date[:4] / date[4:6] / tracking_id
    return SESSION_DATA_DIR / platform / "legacy" / tracking_id


def _normalize_tmux_server(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return sanitize_tmux_server_name(text)


def _normalize_substrate_context(value: Any) -> str | None:
    """Generic alias for substrate runtime context normalization."""
    return _normalize_tmux_server(value)


def _first_path(value: Any) -> str | None:
    """Return first path from a JSON array/list/plain string path value."""
    if value is None:
        return None
    if isinstance(value, list):
        return str(value[0]) if value else None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            parsed = json.loads(text)
            if isinstance(parsed, list):
                return str(parsed[0]) if parsed else None
            if parsed:
                return str(parsed)
        except (json.JSONDecodeError, TypeError):
            pass
        return text
    return str(value)

SCHEMA_SQL = """
-- Session data store schema v1
-- Single source of truth for all session identity and metadata.
-- Replaces the per-file JSON registry from uai_toolkit.session_mgmt.lib_session.py.

CREATE TABLE IF NOT EXISTS metadata (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    -- Identity (immutable after creation)
    tracking_id         TEXT PRIMARY KEY,
    terminal_session    TEXT,
    cli_session_id      TEXT,                   -- NULL until discovered (Codex/Gemini)
    platform            TEXT NOT NULL,           -- claude_cli, codex_cli, gemini_cli
    session_dir         TEXT,                    -- v5.3 per-session state dir
    project_dir         TEXT,                    -- immutable project root
    history_file        TEXT,                    -- canonical primary history/transcript path

    -- Lineage
    parent_tracking_id  TEXT,                   -- NULL for top-level sessions

    -- Metadata
    display_name        TEXT,
    working_dir         TEXT,
    model               TEXT,
    substrate           TEXT,                    -- tmux, zellij, none; NULL = use global default
    tmux_server         TEXT,                    -- NULL = legacy/default tmux server
    roles               TEXT DEFAULT '[]',       -- JSON array
    notes               TEXT,                    -- free-text session annotations

    -- Transcript
    transcript_path     TEXT,                   -- JSON array of JSONL history file paths

    -- Lifecycle
    cli_pid             INTEGER,                -- Current CLI process PID
    status              TEXT DEFAULT 'running',  -- running, stopped, exited
    identity_status     TEXT DEFAULT 'confirmed', -- draft, pending, confirmed, failed, orphaned
    created_at          TEXT NOT NULL,           -- ISO 8601 UTC

    -- Schema
    schema_version      INTEGER DEFAULT 1
);

-- Change log — tracks every field modification
CREATE TABLE IF NOT EXISTS change_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp       TEXT NOT NULL,           -- ISO 8601 UTC
    tracking_id     TEXT NOT NULL,
    cli_session_id  TEXT,                    -- snapshot at time of change
    pid             INTEGER,                -- PID of process that made the change
    field           TEXT NOT NULL,
    old_value       TEXT,
    new_value       TEXT
);

CREATE INDEX IF NOT EXISTS idx_change_log_tracking
    ON change_log(tracking_id);

CREATE INDEX IF NOT EXISTS idx_change_log_timestamp
    ON change_log(timestamp);

-- Indexes for common lookups
CREATE INDEX IF NOT EXISTS idx_sessions_terminal
    ON sessions(terminal_session);

CREATE INDEX IF NOT EXISTS idx_sessions_cli_uuid
    ON sessions(cli_session_id)
    WHERE cli_session_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_platform_status
    ON sessions(platform, status);

CREATE INDEX IF NOT EXISTS idx_sessions_parent
    ON sessions(parent_tracking_id)
    WHERE parent_tracking_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_sessions_status
    ON sessions(status);

-- Session tags — flexible tagging keyed by tracking ID
CREATE TABLE IF NOT EXISTS session_tags (
    tracking_id TEXT NOT NULL,
    tag         TEXT NOT NULL,
    PRIMARY KEY(tracking_id, tag)
);

CREATE INDEX IF NOT EXISTS idx_session_tags_tag
    ON session_tags(tag);

-- Entity relationships — generic relationship graph between entities
CREATE TABLE IF NOT EXISTS entity_relationships (
    source_type   TEXT NOT NULL,
    source_id     TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    target_type   TEXT NOT NULL,
    target_id     TEXT NOT NULL,
    created_at    TEXT,
    metadata_json TEXT,
    PRIMARY KEY(source_type, source_id, relation_type, target_type, target_id)
);

CREATE INDEX IF NOT EXISTS idx_entity_rel_source
    ON entity_relationships(source_type, source_id);

CREATE INDEX IF NOT EXISTS idx_entity_rel_target
    ON entity_relationships(target_type, target_id);

-- Brief metadata — registry for brief documents
CREATE TABLE IF NOT EXISTS brief_metadata (
    name              TEXT PRIMARY KEY,
    display_name      TEXT,
    description       TEXT,
    status            TEXT DEFAULT 'active',
    created_at        TEXT,
    updated_at        TEXT,
    condenser_session TEXT,
    brief_path        TEXT,
    schema_version    INTEGER DEFAULT 1,
    content_hash      TEXT,
    archived_at       TEXT
);

CREATE INDEX IF NOT EXISTS idx_brief_metadata_status
    ON brief_metadata(status);

-- URI mappings — resolve team/project URIs to session tracking IDs
CREATE TABLE IF NOT EXISTS uri_mappings (
    uri             TEXT PRIMARY KEY,
    target_type     TEXT NOT NULL,        -- 'session', 'fan_out'
    target_value    TEXT NOT NULL,        -- tracking_id or JSON array of tracking_ids
    source_type     TEXT NOT NULL,        -- 'team', 'project', 'recipient_set'
    source_id       TEXT NOT NULL,        -- team/project/set ID
    updated_at      TEXT NOT NULL,
    expires_at      TEXT                  -- ISO local; NULL = never expires. Expired rows resolve to [] and are swept.
);

CREATE INDEX IF NOT EXISTS idx_uri_mappings_source
    ON uri_mappings(source_type, source_id);
"""

SESSION_FIELDS = (
    "tracking_id",
    "terminal_session",
    "cli_session_id",
    "platform",
    "session_dir",
    "project_dir",
    "history_file",
    "parent_tracking_id",
    "display_name",
    "working_dir",
    "model",
    "substrate",
    "tmux_server",
    "roles",
    "notes",
    "transcript_path",
    "cli_pid",
    "status",
    "identity_status",
    "created_at",
    "schema_version",
)

TEXT_SEARCH_FIELDS = tuple(field for field in SESSION_FIELDS if field != "schema_version")

LIST_FILTER_ALIASES = {
    "tracking_id": "tracking_id",
    "terminal_session": "terminal_session",
    "cli_session_id": "cli_session_id",
    "platform": "platform",
    "session_dir": "session_dir",
    "project_dir": "project_dir",
    "history_file": "history_file",
    "history": "history_file",
    "parent_tracking_id": "parent_tracking_id",
    "display_name": "display_name",
    "working_dir": "working_dir",
    "model": "model",
    "substrate": "substrate",
    "tmux_server": "tmux_server",
    "tmuxserver": "tmux_server",
    "tmux_server_name": "tmux_server",
    "sub": "substrate",
    "roles": "roles",
    "cli_pid": "cli_pid",
    "status": "status",
    "created_at": "created_at",
    "schema_version": "schema_version",
    "tracking": "tracking_id",
    "trackingid": "tracking_id",
    "terminal": "terminal_session",
    "session": "terminal_session",
    "uuid": "cli_session_id",
    "cli_uuid": "cli_session_id",
    "name": "display_name",
    "display": "display_name",
    "parent": "parent_tracking_id",
    "pid": "cli_pid",
}


# =============================================================================
# Store class
# =============================================================================

class SessionStore:
    """SQLite-backed session data store.

    Thread-safe for reads. Writes use WAL mode for concurrent reader support.
    All public methods return plain dicts — no ORM, no magic.
    """

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path) if db_path else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        """Create tables if they don't exist. Run migrations if needed."""
        # WAL mode must be set outside a transaction
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.close()

        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)

            # Migrate: add pid column to change_log if missing (schema v1 → v1+pid)
            try:
                conn.execute("SELECT pid FROM change_log LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE change_log ADD COLUMN pid INTEGER")

            # Migrate: add transcript_path column if missing
            try:
                conn.execute("SELECT transcript_path FROM sessions LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE sessions ADD COLUMN transcript_path TEXT")

            # Migrate: add substrate column if missing
            try:
                conn.execute("SELECT substrate FROM sessions LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE sessions ADD COLUMN substrate TEXT")

            # Migrate: add expires_at to uri_mappings if missing (temporary registrations)
            try:
                conn.execute("SELECT expires_at FROM uri_mappings LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE uri_mappings ADD COLUMN expires_at TEXT")

            # Migrate: add tmux_server column if missing
            try:
                conn.execute("SELECT tmux_server FROM sessions LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE sessions ADD COLUMN tmux_server TEXT")

            # Migrate: add v5.3 pointer columns if missing. Kept nullable in the
            # live compatibility table; create()/backfill populate them.
            for column in ("session_dir", "project_dir", "history_file"):
                try:
                    conn.execute(f"SELECT {column} FROM sessions LIMIT 0")
                except sqlite3.OperationalError:
                    conn.execute(f"ALTER TABLE sessions ADD COLUMN {column} TEXT")

            # Migrate: add archived column to sessions if missing (schema v4)
            try:
                conn.execute("SELECT archived FROM sessions LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE sessions ADD COLUMN archived BOOLEAN DEFAULT 0")

            # Migrate: add identity_status column if missing (v5.4 draft lifecycle)
            try:
                conn.execute("SELECT identity_status FROM sessions LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE sessions ADD COLUMN identity_status TEXT DEFAULT 'confirmed'")

            # Migrate: add last_activity column if missing
            try:
                conn.execute("SELECT last_activity FROM sessions LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE sessions ADD COLUMN last_activity TEXT")

            # Migrate: add notes column if missing
            try:
                conn.execute("SELECT notes FROM sessions LIMIT 0")
            except sqlite3.OperationalError:
                conn.execute("ALTER TABLE sessions ADD COLUMN notes TEXT")

            # Migrate: card_tags → session_tags (strip session: prefix from card_id)
            try:
                conn.execute("SELECT 1 FROM card_tags LIMIT 0")
                # card_tags exists — migrate data
                rows = conn.execute("SELECT card_id, tag FROM card_tags").fetchall()
                for row in rows:
                    cid = row["card_id"]
                    # Strip legacy session: prefix
                    if cid.startswith("session:"):
                        tid = cid[len("session:"):]
                    else:
                        tid = cid
                    conn.execute(
                        "INSERT OR IGNORE INTO session_tags (tracking_id, tag) VALUES (?, ?)",
                        (tid, row["tag"]),
                    )
                conn.execute("DROP TABLE card_tags")
                # Recreate index since we dropped the old table
                conn.execute(
                    "CREATE INDEX IF NOT EXISTS idx_session_tags_tag ON session_tags(tag)"
                )
            except sqlite3.OperationalError:
                pass  # card_tags doesn't exist, nothing to migrate

            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_sessions_platform_project "
                "ON sessions(platform, project_dir)"
            )

            self._backfill_v53_pointers(conn)

            # Set schema version
            conn.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )

    def _backfill_v53_pointers(self, conn: sqlite3.Connection) -> None:
        """Backfill session_dir/project_dir/history_file for legacy rows."""
        rows = conn.execute(
            """SELECT tracking_id, platform, session_dir, project_dir,
                      history_file, working_dir, transcript_path
               FROM sessions
               WHERE session_dir IS NULL
                  OR session_dir = ''
                  OR project_dir IS NULL
                  OR project_dir = ''
                  OR (history_file IS NULL AND transcript_path IS NOT NULL)"""
        ).fetchall()

        for row in rows:
            tracking_id = row["tracking_id"]
            platform = row["platform"] or "claude_cli"
            session_dir = row["session_dir"] or str(compute_session_dir_path(tracking_id, platform))
            project_dir = row["project_dir"] or row["working_dir"] or str(AI_ROOT)
            history_file = row["history_file"] or _first_path(row["transcript_path"])
            conn.execute(
                """UPDATE sessions
                   SET session_dir = ?, project_dir = ?, history_file = ?
                   WHERE tracking_id = ?""",
                (session_dir, project_dir, history_file, tracking_id),
            )

    # -------------------------------------------------------------------------
    # Derived lifecycle status
    # -------------------------------------------------------------------------

    def _known_tmux_servers(self, conn: sqlite3.Connection | None = None) -> set[str | None]:
        """Return distinct tmux server names known to the store.

        Includes None to represent the legacy/default tmux server.
        """
        close_conn = False
        if conn is None:
            conn = sqlite3.connect(str(self.db_path), timeout=10)
            conn.row_factory = sqlite3.Row
            close_conn = True

        servers: set[str | None] = {None}
        try:
            rows = conn.execute(
                "SELECT DISTINCT tmux_server FROM sessions WHERE substrate = 'tmux'"
            ).fetchall()
            for row in rows:
                servers.add(_normalize_tmux_server(row["tmux_server"]))
        finally:
            if close_conn:
                conn.close()
        return servers

    def _get_live_tmux_sessions(self, tmux_servers: set[str | None] | None = None) -> set[tuple[str | None, str]]:
        """Enumerate live tmux sessions across the requested tmux servers."""
        servers = tmux_servers or {None}
        live: set[tuple[str | None, str]] = set()
        for server_name in servers:
            try:
                result = subprocess.run(
                    build_tmux_command(
                        ["list-sessions", "-F", "#{session_name}"],
                        server_name=server_name,
                    ),
                    capture_output=True,
                    text=True,
                    timeout=5,
                )
                if result.returncode != 0:
                    continue
                for line in result.stdout.strip().splitlines():
                    session_name = line.strip()
                    if session_name:
                        live.add((server_name, session_name))
            except (OSError, subprocess.TimeoutExpired):
                continue
        return live

    @staticmethod
    def _get_live_zellij_sessions() -> set[str]:
        live: set[str] = set()
        try:
            result = subprocess.run(
                ["zellij", "list-sessions"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                for line in result.stdout.strip().splitlines():
                    name = line.strip().split()[0] if line.strip() else ""
                    if name:
                        live.add(name)
        except (OSError, subprocess.TimeoutExpired):
            pass
        return live

    def _get_live_terminal_sessions(self) -> dict[str, set[Any]]:
        """Get all currently live terminal sessions keyed by substrate/server."""
        with self._connect() as conn:
            tmux_servers = self._known_tmux_servers(conn)
        return {
            "tmux": self._get_live_tmux_sessions(tmux_servers),
            "zellij": self._get_live_zellij_sessions(),
        }

    def _session_is_live(self, session: dict, live: dict[str, set[Any]] | None = None) -> bool:
        """True iff this session's terminal is ACTUALLY live in tmux/zellij.

        Uses the live probe (ground truth), never the stored `status` field —
        which goes stale when a session dies without reconciliation.
        """
        term = session.get("terminal_session") or ""
        if not term:
            return False
        live = live if live is not None else self._get_live_terminal_sessions()
        live_tmux = live.get("tmux", set())
        live_zellij = live.get("zellij", set())
        substrate = str(session.get("substrate") or "").lower()
        tmux_server = _normalize_tmux_server(session.get("tmux_server"))
        if substrate == "tmux":
            return (tmux_server, term) in live_tmux
        if substrate == "zellij":
            return term in live_zellij
        return any(name == term for _, name in live_tmux) or term in live_zellij

    def live_name_conflicts(
        self,
        *,
        terminal_session: str | None = None,
        display_name: str | None = None,
        exclude_tracking_id: str | None = None,
    ) -> list[dict]:
        """Return sessions that are ACTUALLY LIVE and collide on terminal_session
        and/or display_name (excluding `exclude_tracking_id`).

        Liveness is probed from tmux/zellij, not the stored `status` field — the
        stored status is unreliable (a dead session lingers as 'running' until
        reconciled), which is exactly how two 'Relay' records both read active
        and shadowed each other. Cheap SQL narrows candidates first, so the
        (slower) live probe only runs when a name is actually reused.
        """
        names = {n for n in (terminal_session, display_name) if n}
        if not names:
            return []
        placeholders = ",".join("?" * len(names))
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM sessions WHERE terminal_session IN ({placeholders}) "
                f"OR display_name IN ({placeholders})",
                (*names, *names),
            ).fetchall()
        candidates = [self._row_to_dict(r) for r in rows]
        candidates = [
            s for s in candidates
            if not (exclude_tracking_id and s.get("tracking_id") == exclude_tracking_id)
        ]
        if not candidates:
            return []
        live = self._get_live_terminal_sessions()
        return [s for s in candidates if self._session_is_live(s, live)]

    def _derive_status(self, session: dict, live_sessions: dict[str, set[Any]] | None = None) -> str:
        """Derive lifecycle status from live system state.

        Priority:
          1. Terminal session exists in tmux/zellij → "active"
          2. .archived marker in session_dir → "archived"
          3. JSONL history file missing → "deleted"
          4. Otherwise → "stopped"
        """
        terminal = session.get("terminal_session") or ""
        if terminal:
            substrate = str(session.get("substrate") or "").lower()
            tmux_server = _normalize_tmux_server(session.get("tmux_server"))
            if live_sessions is not None:
                live_tmux = live_sessions.get("tmux", set())
                live_zellij = live_sessions.get("zellij", set())
                if substrate == "tmux":
                    is_live = (tmux_server, terminal) in live_tmux
                elif substrate == "zellij":
                    is_live = terminal in live_zellij
                else:
                    is_live = any(name == terminal for _, name in live_tmux) or terminal in live_zellij
            else:
                # Single-session probe (used by get() etc.)
                current_live = self._get_live_terminal_sessions()
                live_tmux = current_live.get("tmux", set())
                live_zellij = current_live.get("zellij", set())
                if substrate == "tmux":
                    is_live = (tmux_server, terminal) in live_tmux
                elif substrate == "zellij":
                    is_live = terminal in live_zellij
                else:
                    is_live = any(name == terminal for _, name in live_tmux) or terminal in live_zellij
            if is_live:
                return "active"

        session_dir = session.get("session_dir")
        if session_dir:
            archived_marker = Path(session_dir) / ".archived"
            if archived_marker.exists():
                return "archived"

        history_file = session.get("history_file") or _first_path(session.get("transcript_path"))
        if history_file and not Path(history_file).exists():
            return "deleted"

        return "stopped"

    @contextmanager
    def _connect(self):
        """Context manager for database connections."""
        conn = sqlite3.connect(str(self.db_path), timeout=10)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # -------------------------------------------------------------------------
    # Change signal (notifies watchers like the UCI app)
    # -------------------------------------------------------------------------

    @staticmethod
    def _signal_change() -> None:
        """Touch the signal file so fs.watch consumers know data changed."""
        try:
            SIGNAL_FILE.parent.mkdir(parents=True, exist_ok=True)
            SIGNAL_FILE.touch()
        except OSError:
            pass  # best effort

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    def _write_session_info(self, session: dict | None) -> None:
        """Write per-session sessionInfo.json atomically.

        The SQLite table remains a compatibility superset during migration.
        sessionInfo.json is the v5.3 home for mutable runtime state.
        """
        if not session:
            return

        session_dir_text = session.get("session_dir")
        if not session_dir_text:
            return

        session_dir = Path(str(session_dir_text))
        try:
            session_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return

        info = {
            "schema_version": SCHEMA_VERSION,
            "tracking_id": session.get("tracking_id"),
            "cli_session_id": session.get("cli_session_id"),
            "platform": session.get("platform"),
            "terminal_session": session.get("terminal_session"),
            "session_dir": str(session_dir),
            "project_dir": session.get("project_dir") or session.get("working_dir") or str(AI_ROOT),
            "working_dir": session.get("working_dir") or session.get("project_dir") or str(AI_ROOT),
            "history_file": session.get("history_file") or _first_path(session.get("transcript_path")),
            "display_name": session.get("display_name"),
            "parent_tracking_id": session.get("parent_tracking_id"),
            "model": session.get("model"),
            "roles": session.get("roles") or [],
            "cli_pid": session.get("cli_pid"),
            "substrate": session.get("substrate"),
            "substrate_context": session.get("substrate_context") or session.get("tmux_server"),
            "tmux_server": session.get("tmux_server"),
            "status": session.get("status"),
            "created_at": session.get("created_at"),
            "updated_at": self._now_iso(),
        }

        path = session_dir / instance_filename("sessionInfo", "json", session_dir)
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            tmp.write_text(json.dumps(info, indent=2, sort_keys=True) + "\n")
            tmp.replace(path)
        except OSError:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass

    # -------------------------------------------------------------------------
    # CRUD
    # -------------------------------------------------------------------------

    def create(
        self,
        tracking_id: str,
        terminal_session: str,
        platform: str,
        *,
        cli_session_id: str | None = None,
        parent_tracking_id: str | None = None,
        display_name: str | None = None,
        working_dir: str | None = None,
        project_dir: str | None = None,
        session_dir: str | None = None,
        model: str | None = None,
        substrate: str | None = None,
        tmux_server: str | None = None,
        substrate_context: str | None = None,
        roles: list[str] | None = None,
        transcript_path: str | None = None,
        history_file: str | None = None,
        cli_pid: int | None = None,
        status: str = "running",
        identity_status: str = "confirmed",
        notes: str | None = None,
        created_at: str | None = None,
    ) -> dict:
        """Create a new session, or update an existing draft.

        If a row with this tracking_id already exists (app-created draft),
        updates it with the launcher's runtime data instead of inserting.
        """
        ts = created_at or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        roles_json = json.dumps(roles or [])
        project_dir = str(Path(project_dir or working_dir or AI_ROOT).expanduser())
        session_dir = session_dir or str(compute_session_dir_path(tracking_id, platform))
        history_file = history_file or _first_path(transcript_path)
        if substrate_context is not None and tmux_server is None:
            tmux_server = substrate_context
        tmux_server = _normalize_substrate_context(tmux_server)
        Path(session_dir).mkdir(parents=True, exist_ok=True)

        # Detect name collisions with genuinely-live sessions and log loudly.
        # Non-fatal by design: enforcement (block/rename) belongs to the launcher
        # (ai_launcher owns identity creation); the store surfaces the collision so
        # a shadowing duplicate — like the historical two-'Relay' case — is never
        # silent. Probes live state only when the name is actually reused.
        try:
            for _cf in self.live_name_conflicts(
                terminal_session=terminal_session,
                display_name=display_name or terminal_session,
                exclude_tracking_id=tracking_id,
            ):
                log.warning(
                    "session-name collision: new session %s wants name %r, but it "
                    "is already LIVE as %s (terminal=%r, server=%s, platform=%s). Two "
                    "live sessions sharing a name shadow each other during resolution; "
                    "the newer one can become unaddressable. Use a unique display name.",
                    tracking_id, display_name or terminal_session,
                    _cf.get("tracking_id"), _cf.get("terminal_session"),
                    _cf.get("tmux_server"), _cf.get("platform"),
                )
        except Exception:  # never let collision-logging break a launch
            pass

        with self._connect() as conn:
            # Check if this is an app-created draft that needs updating
            existing = conn.execute(
                "SELECT tracking_id FROM sessions WHERE tracking_id = ?",
                (tracking_id,),
            ).fetchone()

            if existing:
                # Update the draft row with launcher runtime data
                conn.execute(
                    """UPDATE sessions SET
                        terminal_session = ?, cli_session_id = ?,
                        session_dir = ?, project_dir = ?, history_file = ?,
                        display_name = COALESCE(?, display_name),
                        working_dir = ?, model = ?, substrate = ?, tmux_server = ?,
                        roles = ?, transcript_path = ?, cli_pid = ?,
                        status = ?, identity_status = ?,
                        notes = COALESCE(?, notes)
                    WHERE tracking_id = ?""",
                    (
                        terminal_session, cli_session_id,
                        session_dir, project_dir, history_file,
                        display_name,
                        working_dir, model, substrate, tmux_server, roles_json, transcript_path, cli_pid,
                        status, identity_status,
                        notes,
                        tracking_id,
                    ),
                )
            else:
                conn.execute(
                    """INSERT INTO sessions (
                        tracking_id, terminal_session, cli_session_id, platform,
                        session_dir, project_dir, history_file,
                        parent_tracking_id, display_name, working_dir, model,
                        substrate, tmux_server, roles, transcript_path, cli_pid, status,
                        identity_status, notes, created_at, schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        tracking_id, terminal_session, cli_session_id, platform,
                        session_dir, project_dir, history_file,
                        parent_tracking_id, display_name or terminal_session,
                        working_dir, model, substrate, tmux_server, roles_json, transcript_path, cli_pid, status,
                        identity_status, notes, ts, SCHEMA_VERSION,
                    ),
                )

        self._signal_change()
        created = self.get(tracking_id)
        self._write_session_info(created)
        return created  # type: ignore

    def get(self, tracking_id: str) -> dict | None:
        """Get a session by tracking ID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE tracking_id = ?",
                (tracking_id,),
            ).fetchone()
            return self._row_to_dict(row) if row else None

    def get_by_terminal(self, terminal_session: str) -> dict | None:
        """Get a session by terminal session name."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE terminal_session = ? ORDER BY created_at DESC LIMIT 1",
                (terminal_session,),
            ).fetchone()
            return self._row_to_dict(row) if row else None

    def get_by_cli_uuid(self, cli_uuid: str) -> dict | None:
        """Get a session by CLI UUID."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM sessions WHERE cli_session_id = ?",
                (cli_uuid,),
            ).fetchone()
            return self._row_to_dict(row) if row else None

    def list(
        self,
        platform: str | None = None,
        status: str | None = None,
        parent: str | None = None,
        limit: int | None = None,
        *,
        text: str | None = None,
        filters: dict[str, Any] | None = None,
    ) -> list[dict]:
        """List sessions with optional filters.

        Status is derived from live system state (tmux/zellij, filesystem),
        not from the stored column. The status parameter is applied as a
        post-filter after derivation. Other field filters use SQL-level
        case-insensitive substring matching.
        """
        clauses = []
        params: list[Any] = []

        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        # Status is NOT filtered in SQL — it's derived and post-filtered below
        if parent is not None:
            if parent == "none":
                clauses.append("parent_tracking_id IS NULL")
            else:
                clauses.append("parent_tracking_id = ?")
                params.append(parent)
        if filters:
            for field, value in filters.items():
                if field not in SESSION_FIELDS:
                    raise ValueError(f"Unknown session field: {field}")
                if value is None:
                    continue
                # Skip status in field filters — handled by post-filter
                if field == "status":
                    continue

                value_text = str(value).strip()
                if field == "parent_tracking_id" and value_text.lower() in ("none", "null"):
                    clauses.append("parent_tracking_id IS NULL")
                    continue

                clauses.append(f"LOWER(COALESCE(CAST({field} AS TEXT), '')) LIKE ?")
                params.append(f"%{value_text.lower()}%")
        if text:
            # Strip URI prefix for search
            if text.startswith('uai://session/'):
                text = text[len('uai://session/'):]
            text_pattern = f"%{text.lower()}%"
            text_clauses = [
                f"LOWER(COALESCE(CAST({field} AS TEXT), '')) LIKE ?"
                for field in TEXT_SEARCH_FIELDS
            ]
            clauses.append("(" + " OR ".join(text_clauses) + ")")
            params.extend([text_pattern] * len(TEXT_SEARCH_FIELDS))

        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        order = " ORDER BY created_at DESC"

        # Fetch live terminal sessions once for the whole batch
        live_sessions = self._get_live_terminal_sessions()

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM sessions{where}{order}",
                params,
            ).fetchall()
            sessions = [self._row_to_dict(row, live_sessions=live_sessions) for row in rows]

        # Post-filter by derived status
        if status:
            status_lower = status.lower()
            sessions = [s for s in sessions if s["status"] == status_lower]

        # Apply limit after status post-filter
        if limit:
            sessions = sessions[:limit]

        return sessions

    # Editable fields (mutable after creation)
    EDITABLE_FIELDS = (
        "terminal_session", "cli_session_id", "cli_pid", "display_name",
        "working_dir", "model", "substrate", "tmux_server", "roles", "notes", "status",
        "transcript_path", "history_file", "identity_status", "last_activity", "archived",
    )

    def update(self, tracking_id: str, **fields) -> dict | None:
        """Update specific fields on a session. Logs each change. Returns updated session."""
        if not fields:
            return self.get(tracking_id)

        # Validate field names
        alias_fields = {"substrate_context"}
        invalid = (set(fields.keys()) - alias_fields) - set(self.EDITABLE_FIELDS)
        if invalid:
            raise ValueError(f"Cannot update immutable or unknown fields: {invalid}")

        # Get current state for change log
        current = self.get(tracking_id)
        if not current:
            return None

        if "substrate_context" in fields and "tmux_server" not in fields:
            fields["tmux_server"] = fields.pop("substrate_context")
        # Serialize roles if present
        if "roles" in fields and isinstance(fields["roles"], list):
            fields["roles"] = json.dumps(fields["roles"])
        if "tmux_server" in fields:
            fields["tmux_server"] = _normalize_substrate_context(fields["tmux_server"])
        if "transcript_path" in fields and "history_file" not in fields:
            fields["history_file"] = _first_path(fields["transcript_path"])

        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [tracking_id]

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        cli_uuid = current.get("cli_session_id")

        with self._connect() as conn:
            conn.execute(
                f"UPDATE sessions SET {set_clause} WHERE tracking_id = ?",
                values,
            )

            # Log each changed field (with PID of the changing process)
            my_pid = os.getpid()
            for field_name, new_value in fields.items():
                old_value = current.get(field_name)
                # Normalize for comparison
                old_str = json.dumps(old_value) if isinstance(old_value, (list, dict)) else str(old_value) if old_value is not None else None
                new_str = str(new_value) if new_value is not None else None
                if old_str != new_str:
                    conn.execute(
                        """INSERT INTO change_log (timestamp, tracking_id, cli_session_id, pid, field, old_value, new_value)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (ts, tracking_id, cli_uuid, my_pid, field_name, old_str, new_str),
                    )

        self._signal_change()
        updated = self.get(tracking_id)
        self._write_session_info(updated)
        return updated

    def delete(self, tracking_id: str) -> bool:
        """Delete a session. Returns True if deleted."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM sessions WHERE tracking_id = ?",
                (tracking_id,),
            )
            deleted = cursor.rowcount > 0
        if deleted:
            self._signal_change()
        return deleted

    # -------------------------------------------------------------------------
    # Queries
    # -------------------------------------------------------------------------

    def get_children(self, tracking_id: str) -> list[dict]:
        """Get direct children of a session."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE parent_tracking_id = ? ORDER BY created_at",
                (tracking_id,),
            ).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def get_ancestors(self, tracking_id: str) -> list[dict]:
        """Walk parent chain upward. Returns [parent, grandparent, ...]."""
        ancestors = []
        current = tracking_id
        seen = set()  # guard against cycles

        while current and current not in seen:
            seen.add(current)
            session = self.get(current)
            if not session:
                break
            parent_id = session.get("parent_tracking_id")
            if not parent_id:
                break
            parent = self.get(parent_id)
            if parent:
                ancestors.append(parent)
            current = parent_id

        return ancestors

    def resolve(self, identifier: str) -> dict | None:
        """Resolve a session by any identifier type (exact match only).

        Accepts URIs (uai://session/<id>) or raw identifiers.
        Resolution order:
        1. Exact tracking ID
        2. Exact terminal session name
        3. Exact CLI UUID
        """
        # Strip URI prefix if present (uai://session/<id>[/<action>], prompt://target/<id>, etc.)
        # Centralized, action-aware: extracts the id and never mistakes an action
        # suffix (e.g. /message) for the identifier. See lib_uri.
        if '://' in identifier:
            try:
                from uai_toolkit.session_mgmt.lib_uri import session_id_of
                identifier = session_id_of(identifier)
            except Exception:
                pass

        # 1. Tracking ID
        result = self.get(identifier)
        if result:
            return result

        # 2. Terminal session name
        result = self.get_by_terminal(identifier)
        if result:
            return result

        # 3. CLI UUID
        result = self.get_by_cli_uuid(identifier)
        if result:
            return result

        # 4. UUID prefix (8+ hex chars)
        if len(identifier) >= 8 and all(c in '0123456789abcdef-' for c in identifier.lower()):
            with self._connect() as conn:
                results = conn.execute(
                    "SELECT * FROM sessions WHERE cli_session_id LIKE ? LIMIT 2",
                    (identifier.lower() + "%",)
                ).fetchall()
            if len(results) == 1:
                return self._row_to_dict(results[0])

        # 5. Display name (exact)
        with self._connect() as conn:
            results = conn.execute(
                "SELECT * FROM sessions WHERE display_name = ? LIMIT 2",
                (identifier,)
            ).fetchall()
        if len(results) == 1:
            return self._row_to_dict(results[0])

        return None

    def find_orphans(self, max_age_hours: int = 2) -> list[dict]:
        """Find orphaned sessions — tracking IDs with no meaningful pairings.

        A session is orphaned if it has:
        - No CLI UUID (entity identity never established)
        - No terminal session (no way to reach it)
        - No PID (nothing running)
        - Older than max_age_hours (grace period for bootstrap)

        These represent failed creations, not valid sessions.
        """
        cutoff = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Calculate cutoff by subtracting hours (approximate via string comparison)
        from datetime import timedelta
        cutoff_dt = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        cutoff = cutoff_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        with self._connect() as conn:
            rows = conn.execute(
                """SELECT * FROM sessions
                   WHERE cli_session_id IS NULL
                     AND (terminal_session IS NULL OR terminal_session = '')
                     AND (cli_pid IS NULL OR cli_pid = 0)
                     AND created_at < ?
                   ORDER BY created_at""",
                (cutoff,),
            ).fetchall()
            return [self._row_to_dict(row) for row in rows]

    def prune_orphans(self, max_age_hours: int = 2) -> int:
        """Remove orphaned sessions. Returns count removed."""
        orphans = self.find_orphans(max_age_hours)
        removed = 0
        for o in orphans:
            if self.delete(o["tracking_id"]):
                removed += 1
        return removed

    def validate(self, tracking_id: str) -> dict:
        """Check a session's identity validity. Returns status dict."""
        session = self.get(tracking_id)
        if not session:
            return {"valid": False, "reason": "not_found"}

        has_uuid = bool(session.get("cli_session_id"))
        has_terminal = bool(session.get("terminal_session"))
        has_pid = bool(session.get("cli_pid"))
        has_parent = bool(session.get("parent_tracking_id"))

        pairings = []
        if has_uuid: pairings.append("cli_uuid")
        if has_terminal: pairings.append("terminal")
        if has_pid: pairings.append("pid")
        if has_parent: pairings.append("parent")

        if not pairings:
            return {"valid": False, "reason": "orphaned", "pairings": []}

        if not has_uuid and session.get("status") == "stopped":
            return {"valid": False, "reason": "stopped_without_uuid", "pairings": pairings}

        return {"valid": True, "pairings": pairings, "has_uuid": has_uuid}

    def validate_running_sessions(self, *, fix: bool = False) -> dict:
        """Check all sessions with status=running against live terminal sessions.

        For each running session, checks whether its terminal session actually
        exists by probing tmux and zellij. Sessions whose terminal is gone are
        classified as stale.

        Args:
            fix: If True, update stale sessions' status to "stopped".

        Returns:
            Dict with keys: total, confirmed, stale, stale_sessions, fixed.
        """
        running = self.list(status="running")
        total = len(running)

        live_sessions = self._get_live_terminal_sessions()
        live_tmux = live_sessions.get("tmux", set())
        live_zellij = live_sessions.get("zellij", set())

        confirmed: list[dict] = []
        stale: list[dict] = []

        for session in running:
            # The terminal_session field is the session name to check
            session_name = session.get("terminal_session") or session.get("tracking_id") or ""
            substrate = (session.get("substrate") or "").lower()
            tmux_server = _normalize_tmux_server(session.get("tmux_server"))

            is_alive = False
            if substrate == "zellij":
                is_alive = session_name in live_zellij
            elif substrate == "tmux":
                is_alive = (tmux_server, session_name) in live_tmux
            else:
                # Unknown substrate — check both
                is_alive = any(name == session_name for _, name in live_tmux) or session_name in live_zellij

            if is_alive:
                confirmed.append(session)
            else:
                stale.append(session)

        fixed = 0
        if fix and stale:
            for session in stale:
                tid = session["tracking_id"]
                self.update(tid, status="stopped")
                fixed += 1

        return {
            "total": total,
            "confirmed": len(confirmed),
            "stale": len(stale),
            "stale_sessions": stale,
            "fixed": fixed,
        }

    def count(self, platform: str | None = None, status: str | None = None) -> int:
        """Count sessions with optional filters.

        When status is specified, uses derived lifecycle status (not the stored
        column), so this delegates to list() for accurate counting.
        """
        if status:
            return len(self.list(platform=platform, status=status))

        # No status filter — pure SQL count is fine
        clauses = []
        params: list[Any] = []
        if platform:
            clauses.append("platform = ?")
            params.append(platform)
        where = " WHERE " + " AND ".join(clauses) if clauses else ""
        with self._connect() as conn:
            row = conn.execute(f"SELECT COUNT(*) FROM sessions{where}", params).fetchone()
            return row[0] if row else 0

    # -------------------------------------------------------------------------
    # Change history
    # -------------------------------------------------------------------------

    def history(
        self,
        tracking_id: str | None = None,
        since: str | None = None,
        until: str | None = None,
        limit: int = 50,
    ) -> list[dict]:
        """Get change history with optional filters.

        Args:
            tracking_id: Filter to one session.
            since: ISO date/datetime string — only changes at or after this time.
            until: ISO date/datetime string — only changes at or before this time.
            limit: Max entries returned.
        """
        clauses = []
        params: list[Any] = []

        if tracking_id:
            clauses.append("tracking_id = ?")
            params.append(tracking_id)
        if since:
            clauses.append("timestamp >= ?")
            params.append(since)
        if until:
            clauses.append("timestamp <= ?")
            params.append(until)

        where = " WHERE " + " AND ".join(clauses) if clauses else ""

        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM change_log{where} ORDER BY timestamp DESC LIMIT ?",
                params + [limit],
            ).fetchall()
            return [dict(row) for row in rows]

    # -------------------------------------------------------------------------
    # Historical names
    # -------------------------------------------------------------------------

    def get_historical_names(
        self,
        unique: bool = False,
        include_count: bool = False,
        sort: str = "date",
    ) -> list[dict]:
        """Get display names from rename history (change_log), not default names.

        Args:
            unique: Deduplicate names (return each name once).
            include_count: Include per-name usage count and active session count.
            sort: 'date' (most recent first), 'name' (alpha), 'count' (most used; implies unique).

        Returns list of dicts with keys:
            name, last_used, [count, active_count] (if include_count or sort=count),
            [tracking_id] (if not unique)
        """
        if sort == "count":
            unique = True
            include_count = True

        with self._connect() as conn:
            if unique or include_count:
                rows = conn.execute(
                    """SELECT new_value AS name,
                              MAX(timestamp) AS last_used,
                              COUNT(*) AS count
                       FROM change_log
                       WHERE field = 'display_name' AND new_value IS NOT NULL
                       GROUP BY new_value
                       ORDER BY CASE WHEN ? = 'count' THEN -COUNT(*)
                                     WHEN ? = 'name'  THEN 0
                                     ELSE 0 END,
                                CASE WHEN ? = 'name' THEN LOWER(new_value)
                                     ELSE NULL END,
                                MAX(timestamp) DESC""",
                    (sort, sort, sort),
                ).fetchall()

                results = []
                for row in rows:
                    entry: dict = {"name": row["name"], "last_used": row["last_used"]}
                    if include_count:
                        entry["count"] = row["count"]
                        active = conn.execute(
                            "SELECT COUNT(*) FROM sessions "
                            "WHERE display_name = ? AND status = 'running'",
                            (row["name"],),
                        ).fetchone()
                        entry["active_count"] = active[0] if active else 0
                    results.append(entry)
                return results
            else:
                order = {
                    "date": "timestamp DESC",
                    "name": "LOWER(new_value), timestamp DESC",
                }.get(sort, "timestamp DESC")
                rows = conn.execute(
                    f"""SELECT new_value AS name, timestamp AS last_used, tracking_id
                        FROM change_log
                        WHERE field = 'display_name' AND new_value IS NOT NULL
                        ORDER BY {order}""",
                ).fetchall()
                return [dict(row) for row in rows]

    def check_name_usage(self, name: str) -> dict:
        """Check how many times a name has been used and how many are currently active.

        Returns dict with: name, total_uses, active_count, live_active_count.

        `active_count` counts stored status = 'running' (fast, but stale once a
        session dies without reconciliation). `live_active_count` probes tmux/zellij
        for ground truth — prefer it when the distinction matters (e.g. deciding a
        name is genuinely in use). None if the live probe failed.
        """
        with self._connect() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM change_log "
                "WHERE field = 'display_name' AND new_value = ?",
                (name,),
            ).fetchone()
            active = conn.execute(
                "SELECT COUNT(*) FROM sessions "
                "WHERE display_name = ? AND status = 'running'",
                (name,),
            ).fetchone()
        try:
            live_active = len(self.live_name_conflicts(display_name=name, terminal_session=name))
        except Exception:
            live_active = None
        return {
            "name": name,
            "total_uses": total[0] if total else 0,
            "active_count": active[0] if active else 0,
            "live_active_count": live_active,
        }

    # -------------------------------------------------------------------------
    # Session tags
    # -------------------------------------------------------------------------

    @staticmethod
    def _normalize_tag_id(identifier: str) -> str:
        """Normalize a tag identifier to a bare tracking ID.

        Accepts:
          - bare tracking ID: 20260521_043029_6784ebe3_cla
          - session: prefix: session:20260521_043029_6784ebe3_cla
          - URI: uai://session/20260521_043029_6784ebe3_cla
        Returns the bare tracking ID in all cases.
        """
        s = identifier.strip()
        if s.startswith("uai://session/"):
            s = s[len("uai://session/"):]
        elif s.startswith("session:"):
            s = s[len("session:"):]
        return s

    def add_tag(self, tracking_id: str, tag: str) -> None:
        """Add a tag to a session. No-op if already tagged."""
        tid = self._normalize_tag_id(tracking_id)
        with self._connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO session_tags (tracking_id, tag) VALUES (?, ?)",
                (tid, tag),
            )
        self._signal_change()

    def remove_tag(self, tracking_id: str, tag: str) -> bool:
        """Remove a tag from a session. Returns True if removed."""
        tid = self._normalize_tag_id(tracking_id)
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM session_tags WHERE tracking_id = ? AND tag = ?",
                (tid, tag),
            )
            removed = cursor.rowcount > 0
        if removed:
            self._signal_change()
        return removed

    def get_tags(self, tracking_id: str) -> list[str]:
        """Get all tags for a session."""
        tid = self._normalize_tag_id(tracking_id)
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tag FROM session_tags WHERE tracking_id = ? ORDER BY tag",
                (tid,),
            ).fetchall()
            return [row["tag"] for row in rows]

    def get_all_session_tags(self) -> dict[str, list[str]]:
        """Get all tags grouped by tracking_id. Returns {tracking_id: [tag1, tag2, ...]}."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tracking_id, tag FROM session_tags ORDER BY tracking_id, tag"
            ).fetchall()
            result: dict[str, list[str]] = {}
            for row in rows:
                tid = row["tracking_id"]
                if tid not in result:
                    result[tid] = []
                result[tid].append(row["tag"])
            return result

    # Backward-compat alias
    get_all_card_tags = get_all_session_tags

    def find_by_tag(self, tag: str) -> list[str]:
        """Find all tracking IDs with a given tag."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT tracking_id FROM session_tags WHERE tag = ? ORDER BY tracking_id",
                (tag,),
            ).fetchall()
            return [row["tracking_id"] for row in rows]

    # -------------------------------------------------------------------------
    # Entity relationships
    # -------------------------------------------------------------------------

    def add_relationship(
        self,
        source_type: str,
        source_id: str,
        relation_type: str,
        target_type: str,
        target_id: str,
        *,
        metadata: dict | None = None,
    ) -> None:
        """Add a relationship between two entities. No-op if already exists."""
        ts = self._now_iso()
        metadata_json = json.dumps(metadata) if metadata else None
        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO entity_relationships
                   (source_type, source_id, relation_type, target_type, target_id, created_at, metadata_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (source_type, source_id, relation_type, target_type, target_id, ts, metadata_json),
            )
        self._signal_change()

    def remove_relationship(
        self,
        source_type: str,
        source_id: str,
        relation_type: str,
        target_type: str,
        target_id: str,
    ) -> bool:
        """Remove a relationship. Returns True if removed."""
        with self._connect() as conn:
            cursor = conn.execute(
                """DELETE FROM entity_relationships
                   WHERE source_type = ? AND source_id = ? AND relation_type = ?
                     AND target_type = ? AND target_id = ?""",
                (source_type, source_id, relation_type, target_type, target_id),
            )
            removed = cursor.rowcount > 0
        if removed:
            self._signal_change()
        return removed

    def get_relationships(
        self,
        entity_type: str,
        entity_id: str,
        *,
        relation_type: str | None = None,
    ) -> list[dict]:
        """Get all relationships where entity is source or target."""
        clauses_src = ["source_type = ?", "source_id = ?"]
        params_src: list[Any] = [entity_type, entity_id]
        clauses_tgt = ["target_type = ?", "target_id = ?"]
        params_tgt: list[Any] = [entity_type, entity_id]

        if relation_type:
            clauses_src.append("relation_type = ?")
            params_src.append(relation_type)
            clauses_tgt.append("relation_type = ?")
            params_tgt.append(relation_type)

        where_src = " AND ".join(clauses_src)
        where_tgt = " AND ".join(clauses_tgt)

        with self._connect() as conn:
            rows = conn.execute(
                f"""SELECT * FROM entity_relationships WHERE ({where_src}) OR ({where_tgt})
                    ORDER BY created_at""",
                params_src + params_tgt,
            ).fetchall()
            return [self._rel_row_to_dict(row) for row in rows]

    def find_related(
        self,
        entity_type: str,
        entity_id: str,
        *,
        relation_type: str | None = None,
    ) -> list[dict]:
        """Find entities related to the given entity. Returns list of {type, id, relation_type, direction}."""
        rels = self.get_relationships(entity_type, entity_id, relation_type=relation_type)
        results = []
        for r in rels:
            if r["source_type"] == entity_type and r["source_id"] == entity_id:
                results.append({
                    "type": r["target_type"],
                    "id": r["target_id"],
                    "relation_type": r["relation_type"],
                    "direction": "outgoing",
                })
            if r["target_type"] == entity_type and r["target_id"] == entity_id:
                results.append({
                    "type": r["source_type"],
                    "id": r["source_id"],
                    "relation_type": r["relation_type"],
                    "direction": "incoming",
                })
        return results

    @staticmethod
    def _rel_row_to_dict(row: sqlite3.Row) -> dict:
        d = dict(row)
        if d.get("metadata_json"):
            try:
                d["metadata"] = json.loads(d["metadata_json"])
            except (json.JSONDecodeError, TypeError):
                d["metadata"] = None
        else:
            d["metadata"] = None
        return d

    # -------------------------------------------------------------------------
    # Brief metadata
    # -------------------------------------------------------------------------

    def register_brief(
        self,
        name: str,
        *,
        display_name: str | None = None,
        description: str | None = None,
        status: str = "active",
        brief_path: str | None = None,
        content_hash: str | None = None,
        condenser_session: str | None = None,
    ) -> dict:
        """Register a new brief. Returns the created brief as a dict."""
        ts = self._now_iso()
        with self._connect() as conn:
            conn.execute(
                """INSERT INTO brief_metadata
                   (name, display_name, description, status, created_at, updated_at,
                    condenser_session, brief_path, schema_version, content_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (name, display_name, description, status, ts, ts,
                 condenser_session, brief_path, SCHEMA_VERSION, content_hash),
            )
        self._signal_change()
        return self.get_brief(name)  # type: ignore

    def update_brief(self, name: str, **fields) -> dict | None:
        """Update specific fields on a brief. Returns updated brief."""
        if not fields:
            return self.get_brief(name)

        BRIEF_EDITABLE = {
            "display_name", "description", "status", "condenser_session",
            "brief_path", "content_hash", "archived_at",
        }
        invalid = set(fields.keys()) - BRIEF_EDITABLE
        if invalid:
            raise ValueError(f"Cannot update fields: {invalid}")

        fields["updated_at"] = self._now_iso()
        set_clause = ", ".join(f"{k} = ?" for k in fields)
        values = list(fields.values()) + [name]

        with self._connect() as conn:
            cursor = conn.execute(
                f"UPDATE brief_metadata SET {set_clause} WHERE name = ?",
                values,
            )
            if cursor.rowcount == 0:
                return None

        self._signal_change()
        return self.get_brief(name)

    def get_brief(self, name: str) -> dict | None:
        """Get a brief by name."""
        with self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM brief_metadata WHERE name = ?",
                (name,),
            ).fetchone()
            return dict(row) if row else None

    def list_briefs(self, status: str | None = None) -> list[dict]:
        """List briefs, optionally filtered by status."""
        if status:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM brief_metadata WHERE status = ? ORDER BY updated_at DESC",
                    (status,),
                ).fetchall()
        else:
            with self._connect() as conn:
                rows = conn.execute(
                    "SELECT * FROM brief_metadata ORDER BY updated_at DESC",
                ).fetchall()
        return [dict(row) for row in rows]

    # -------------------------------------------------------------------------
    # URI mappings
    # -------------------------------------------------------------------------

    def set_uri_mapping(
        self,
        uri: str,
        target_type: str,
        target_value: str,
        source_type: str,
        source_id: str,
        expires_at: str | None = None,
    ) -> None:
        """Create or update a URI mapping. expires_at (ISO local) makes it a
        temporary registration: it resolves to [] once past, and is swept."""
        ts = self._now_iso()
        with self._connect() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO uri_mappings
                   (uri, target_type, target_value, source_type, source_id, updated_at, expires_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (uri, target_type, target_value, source_type, source_id, ts, expires_at),
            )
        self._signal_change()

    @staticmethod
    def _iso_is_past(exp_iso: str | None) -> bool:
        """True if `exp_iso` is a valid timestamp in the past. Naive values are
        treated as LOCAL time; tz-aware (…Z / ±offset) honored. Robust to the
        UTC-vs-local mismatch that a lexical string compare would get wrong."""
        if not exp_iso:
            return False
        import datetime as _dt
        s = str(exp_iso).strip().replace("Z", "+00:00")
        try:
            dt = _dt.datetime.fromisoformat(s)
        except ValueError:
            return False
        if dt.tzinfo is None:
            dt = dt.astimezone()  # interpret naive as local
        return dt.timestamp() < time.time()

    def delete_expired_uri_mappings(self) -> int:
        """Sweep temporary URI registrations whose expires_at is in the past."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT uri, expires_at FROM uri_mappings WHERE expires_at IS NOT NULL"
            ).fetchall()
            expired = [r["uri"] for r in rows if self._iso_is_past(r["expires_at"])]
            for uri in expired:
                conn.execute("DELETE FROM uri_mappings WHERE uri = ?", (uri,))
        if expired:
            self._signal_change()
        return len(expired)

    def delete_uri_mappings(self, source_type: str, source_id: str) -> int:
        """Delete all URI mappings for a source entity. Returns count deleted."""
        with self._connect() as conn:
            cursor = conn.execute(
                "DELETE FROM uri_mappings WHERE source_type = ? AND source_id = ?",
                (source_type, source_id),
            )
            count = cursor.rowcount
        if count:
            self._signal_change()
        return count

    def list_uri_mappings(self, source_type: str | None = None,
                          source_id: str | None = None) -> list[dict]:
        """List uri_mappings, optionally filtered by owning source entity."""
        q = "SELECT uri, target_type, target_value, source_type, source_id, updated_at, expires_at FROM uri_mappings"
        clauses, params = [], []
        if source_type:
            clauses.append("source_type = ?"); params.append(source_type)
        if source_id:
            clauses.append("source_id = ?"); params.append(source_id)
        if clauses:
            q += " WHERE " + " AND ".join(clauses)
        q += " ORDER BY uri"
        with self._connect() as conn:
            return [dict(r) for r in conn.execute(q, params).fetchall()]

    def resolve_uri(self, uri: str) -> list[str]:
        """Resolve a URI to tracking ID(s). Returns list of tracking_ids.

        For target_type='session', returns [target_value].
        For target_type='fan_out', parses JSON array from target_value.
        Returns empty list if URI not found.
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT target_type, target_value, expires_at FROM uri_mappings WHERE uri = ?",
                (uri,),
            ).fetchone()
        if not row:
            return []
        exp = row["expires_at"] if "expires_at" in row.keys() else None
        if self._iso_is_past(exp):
            return []  # temporary registration has expired
        if row["target_type"] == "fan_out":
            try:
                parsed = json.loads(row["target_value"])
                if isinstance(parsed, list):
                    return [str(v) for v in parsed]
            except (json.JSONDecodeError, TypeError):
                pass
            return []
        # Default: single session
        return [row["target_value"]]

    # -------------------------------------------------------------------------
    # Migration from JSON registry
    # -------------------------------------------------------------------------

    def import_from_registry(self, registry_dir: Path) -> int:
        """Import sessions from the JSON file registry (one-time migration).

        Reads all JSON files from session_registry/{platform}/{yyyy}/*.json
        and inserts them into the SQLite database. Skips duplicates.

        Returns count of sessions imported.
        """
        imported = 0

        if not registry_dir.exists():
            return 0

        for plat_dir in sorted(registry_dir.iterdir()):
            if not plat_dir.is_dir() or plat_dir.name.startswith("."):
                continue
            for yr_dir in sorted(plat_dir.iterdir()):
                if not yr_dir.is_dir():
                    continue
                for f in sorted(yr_dir.iterdir()):
                    if f.suffix != ".json" or f.is_symlink():
                        continue
                    try:
                        data = json.loads(f.read_text())
                        self._import_entry(data)
                        imported += 1
                    except (json.JSONDecodeError, OSError, sqlite3.IntegrityError):
                        continue  # skip malformed or duplicate

        return imported

    def _import_entry(self, data: dict) -> None:
        """Import a single registry entry."""
        tracking_id = (
            data.get("tracking_id")
            or data.get("zellij_session")
            or data.get("terminal_session")
        )
        if not tracking_id:
            return

        terminal = (
            data.get("terminal_session")
            or data.get("zellij_session")
            or tracking_id
        )
        platform = data.get("platform", "claude_cli")
        session_dir = data.get("session_dir") or str(compute_session_dir_path(tracking_id, platform))
        project_dir = data.get("project_dir") or data.get("working_dir") or str(AI_ROOT)
        history_file = data.get("history_file") or _first_path(data.get("transcript_path"))

        with self._connect() as conn:
            conn.execute(
                """INSERT OR IGNORE INTO sessions (
                    tracking_id, terminal_session, cli_session_id, platform,
                    session_dir, project_dir, history_file,
                    parent_tracking_id, display_name, working_dir, model,
                    roles, cli_pid, status, created_at, schema_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    tracking_id,
                    terminal,
                    data.get("cli_session_id"),
                    platform,
                    session_dir,
                    project_dir,
                    history_file,
                    data.get("parent_tracking_id") or data.get("parent_zellij"),
                    data.get("display_name") or terminal,
                    data.get("working_dir"),
                    data.get("model"),
                    json.dumps(data.get("roles", [])),
                    data.get("cli_pid"),
                    data.get("status", "stopped"),
                    data.get("created_at", datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")),
                    SCHEMA_VERSION,
                ),
            )
        self._write_session_info(self.get(tracking_id))

    # -------------------------------------------------------------------------
    # Test support
    # -------------------------------------------------------------------------

    def clear(self) -> int:
        """Delete all sessions. Returns count deleted. Use with --db for test isolation."""
        with self._connect() as conn:
            cursor = conn.execute("DELETE FROM sessions")
            return cursor.rowcount

    def load_fixtures(self) -> int:
        """Load a deterministic set of test sessions covering all states.

        Creates 8 sessions exercising: all platforms, running/stopped/exited,
        parent-child, null cli_uuid, roles, models, --no-mux.

        Returns count created. Clears existing data first.
        """
        self.clear()

        fixtures = [
            # 1. Claude chat — running, has UUID, at prompt
            dict(
                tracking_id="claude_cli_20260401_100000",
                terminal_session="test_claude_chat",
                cli_session_id="aaaaaaaa-1111-4000-8000-000000000001",
                platform="claude_cli",
                display_name="Test Claude Chat",
                working_dir="/Users/test/project",
                model="claude-opus-4-6",
                roles=["chat"],
                cli_pid=10001,
                status="running",
                created_at="2026-04-01T10:00:00Z",
            ),
            # 2. Claude worker — running, child of #1, dev-lead role
            dict(
                tracking_id="claude_cli_20260401_100100",
                terminal_session="test_claude_worker",
                cli_session_id="aaaaaaaa-1111-4000-8000-000000000002",
                platform="claude_cli",
                parent_tracking_id="claude_cli_20260401_100000",
                display_name="Test Worker (dev-lead)",
                working_dir="/Users/test/project",
                model="claude-opus-4-6",
                roles=["dev_lead"],
                cli_pid=10002,
                status="running",
                created_at="2026-04-01T10:01:00Z",
            ),
            # 3. Claude stopped — no PID, has history
            dict(
                tracking_id="claude_cli_20260401_090000",
                terminal_session="test_claude_stopped",
                cli_session_id="aaaaaaaa-1111-4000-8000-000000000003",
                platform="claude_cli",
                display_name="Test Stopped Session",
                working_dir="/Users/test/project",
                roles=["chat"],
                status="stopped",
                created_at="2026-04-01T09:00:00Z",
            ),
            # 4. Codex — running, UUID pending (null)
            dict(
                tracking_id="codex_cli_20260401_100200",
                terminal_session="test_codex_review",
                cli_session_id=None,
                platform="codex_cli",
                display_name="Test Codex Reviewer",
                working_dir="/Users/test/project",
                roles=["peer_review"],
                cli_pid=10004,
                status="running",
                created_at="2026-04-01T10:02:00Z",
            ),
            # 5. Codex — stopped, has UUID (discovered)
            dict(
                tracking_id="codex_cli_20260401_080000",
                terminal_session="test_codex_done",
                cli_session_id="bbbbbbbb-2222-7000-8000-000000000005",
                platform="codex_cli",
                display_name="Test Codex Complete",
                roles=["dev_lead"],
                status="stopped",
                created_at="2026-04-01T08:00:00Z",
            ),
            # 6. Gemini — running
            dict(
                tracking_id="gemini_cli_20260401_100300",
                terminal_session="test_gemini_chat",
                cli_session_id=None,
                platform="gemini_cli",
                display_name="Test Gemini Chat",
                working_dir="/Users/test/project",
                roles=["chat"],
                cli_pid=10006,
                status="running",
                created_at="2026-04-01T10:03:00Z",
            ),
            # 7. Claude exited (error state)
            dict(
                tracking_id="claude_cli_20260401_070000",
                terminal_session="test_claude_error",
                cli_session_id="aaaaaaaa-1111-4000-8000-000000000007",
                platform="claude_cli",
                display_name="Test Error Session",
                roles=["chat"],
                status="exited",
                created_at="2026-04-01T07:00:00Z",
            ),
            # 8. Claude --no-mux (no terminal session)
            dict(
                tracking_id="claude_cli_20260401_060000",
                terminal_session="direct_claude_cli_20260401_060000",
                cli_session_id="aaaaaaaa-1111-4000-8000-000000000008",
                platform="claude_cli",
                display_name="Test No-Mux Session",
                roles=["chat"],
                status="stopped",
                created_at="2026-04-01T06:00:00Z",
            ),
        ]

        for f in fixtures:
            self.create(**f)

        return len(fixtures)

    # -------------------------------------------------------------------------
    # Internal helpers
    # -------------------------------------------------------------------------

    def _row_to_dict(self, row: sqlite3.Row, live_sessions: set[str] | None = None) -> dict:
        """Convert a sqlite3.Row to a plain dict with parsed JSON fields.

        Status is always derived from live system state, not from the stored
        column. The stored status column is kept for backward compatibility
        but is overridden here.
        """
        d = dict(row)
        # Parse roles JSON string back to list
        if "roles" in d and isinstance(d["roles"], str):
            try:
                d["roles"] = json.loads(d["roles"])
            except (json.JSONDecodeError, TypeError):
                d["roles"] = []
        if "tmux_server" in d:
            d["tmux_server"] = _normalize_substrate_context(d["tmux_server"])
            d["substrate_context"] = d["tmux_server"]
        # Parse transcript_path — stored as JSON array or plain string
        if "transcript_path" in d and isinstance(d["transcript_path"], str):
            try:
                parsed = json.loads(d["transcript_path"])
                if isinstance(parsed, list):
                    d["transcript_path"] = parsed
                else:
                    d["transcript_path"] = [parsed] if parsed else []
            except (json.JSONDecodeError, TypeError):
                # Plain string (legacy) — wrap in list
                d["transcript_path"] = [d["transcript_path"]] if d["transcript_path"] else []
        elif "transcript_path" in d:
            d["transcript_path"] = []
        if not d.get("history_file"):
            d["history_file"] = _first_path(d.get("transcript_path"))
        # Override stored status with derived lifecycle state
        d["status"] = self._derive_status(d, live_sessions)
        # Surface live activity_state (responding / idle / prompt_occupied /
        # blocked / permission_prompt / exited), written into the per-session state
        # file by scaffolding (UserPromptSubmit→responding, Stop→idle, get-status→
        # reconciled ground truth). Lets shell-out consumers (sess-mgr list --json)
        # read the reconciled state without a terminal scrape. 'unknown' when never
        # set. `activity_state_at` (ISO) lets a consumer apply its own freshness rule.
        d["activity_state"] = "unknown"
        # Session start history — local-time ISO timestamps appended by the
        # SessionStart hook (05_record_session_start_async). Surfaced so the UAI
        # app can show the most recent start plus the full list on expand.
        d["start_history"] = []
        _sdir, _tid = d.get("session_dir"), d.get("tracking_id")
        if _sdir and _tid:
            try:
                _sp = Path(_sdir) / f"{_tid}_state.json"
                if _sp.exists():
                    _st = json.loads(_sp.read_text())
                    d["activity_state"] = _st.get("session.activity_state") or "unknown"
                    _at = _st.get("session.activity_state_at")
                    if _at:
                        d["activity_state_at"] = _at
                    _sh = _st.get("session.start_history")
                    if isinstance(_sh, list):
                        d["start_history"] = _sh
            except (OSError, ValueError):
                pass
        return d


# =============================================================================
# Shared table printer (used by CLI list and REPL)
# =============================================================================

def _table_header() -> str:
    return (
        f"  {c('IDX', 'heading'):<17} {c('PLATFORM', 'heading'):<20} {c('STATUS', 'heading'):<20} "
        f"{c('CLI_UUID', 'heading'):<49} {c('TRACKING_ID', 'heading'):<51} "
        f"{c('CREATED_AT', 'heading'):<33} {c('DISPLAY_NAME', 'heading')}"
    )

def _table_sep() -> str:
    return c(f"  {'---':<6} {'--------':<9} {'------':<9} {'--------':<38} {'-----------':<40} {'----------':<22} {'------------'}", "dim")


def _utc_to_local(utc_str: str | None) -> str:
    """Convert a UTC ISO 8601 timestamp to a local-time display string.

    Returns a compact 'YYYY-MM-DD HH:MM:SS' in the user's local timezone.
    If parsing fails, returns the original string (or empty).
    """
    if not utc_str:
        return ""
    try:
        # Parse the stored UTC timestamp
        dt = datetime.fromisoformat(utc_str.replace("Z", "+00:00"))
        local_tz = datetime.now().astimezone().tzinfo
        local_dt = dt.astimezone(local_tz)
        return local_dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return utc_str or ""


def _print_table(
    sessions: list[dict],
    no_trunc: bool = False,
    page_size: int = 0,
    interactive: bool = False,
) -> None:
    """Print sessions as a formatted table with 3-digit indices and aligned columns.

    Args:
        sessions: List of session dicts to display.
        no_trunc: If True, don't truncate field values.
        page_size: If >0, pause every N rows and reprint header. 0 = no pagination.
        interactive: If True, prompt "-- more --" between pages (REPL mode).
    """
    if not sessions:
        print(dim("  (no results)"))
        return

    def _trunc(text: str, width: int) -> str:
        if no_trunc or len(text) <= width:
            return text
        return text[:width - 1] + "…"

    _STATUS_COLORS = {
        "running": "green",
        "active": "green",
        "stopped": "yellow",
        "exited": "red",
    }

    _PLATFORM_COLORS = {
        "claude": "bright_cyan",
        "codex": "bright_green",
        "gemini": "bright_magenta",
    }

    def _print_header() -> None:
        print(_table_header())
        print(_table_sep())

    _print_header()

    for i, s in enumerate(sessions):
        # Pagination: reprint header every page_size rows
        if page_size > 0 and i > 0 and i % page_size == 0:
            if interactive:
                try:
                    resp = input(dim(f"  -- {i}/{len(sessions)} -- Enter for more, q to stop: "))
                    if resp.strip().lower() == 'q':
                        print(dim(f"\n  (showing {i} of {len(sessions)})"))
                        return
                except (EOFError, KeyboardInterrupt):
                    print(dim(f"\n  (showing {i} of {len(sessions)})"))
                    return
            _print_header()

        idx = c(f"[{i + 1:03d}]", "dim")
        platform_short = s.get("platform", "?").replace("_cli", "")
        plat_color = _PLATFORM_COLORS.get(platform_short, "white")
        status = s.get("status", "?")
        stat_color = _STATUS_COLORS.get(status, "dim")
        cli_uuid = s.get("cli_session_id") or "--------"
        tracking_id = s.get("tracking_id", "?")
        created_at = _utc_to_local(s.get("created_at"))
        name = s.get("display_name") or s.get("terminal_session") or tracking_id

        print(
            f"  {idx}  "
            f"{c(_trunc(platform_short, 8), plat_color):<20} "
            f"{c(_trunc(status, 8), stat_color):<20} "
            f"{dim(_trunc(cli_uuid, 36)):<49} "
            f"{_trunc(tracking_id, 38):<40} "
            f"{dim(_trunc(created_at, 20)):<33} "
            f"{bold(_trunc(name, 40) if not no_trunc else name)}"
        )

    print(dim(f"\n  {len(sessions)} session(s)"))


# =============================================================================
# Interactive edit mode (shared by CLI and REPL)
# =============================================================================

def _interactive_edit(store: 'SessionStore', tracking_id: str) -> None:
    """Interactive edit with draft/commit workflow.

    Edits are staged locally. 'commit' writes them, 'cancel' discards.
    Used by both CLI (sess_mgr edit <id>) and REPL (edit <ref>).
    """
    session = store.get(tracking_id)
    if not session:
        print(f"  Not found: {tracking_id}")
        return

    editable = list(store.EDITABLE_FIELDS)
    drafts: dict[str, object] = {}  # field -> new value

    def _display_val(fname: str) -> str:
        # Show draft value if staged, otherwise current
        if fname in drafts:
            val = drafts[fname]
            suffix = " *"  # mark as staged
        else:
            val = session.get(fname)
            suffix = ""
        if isinstance(val, list):
            return (", ".join(val) if val else "(empty list)") + suffix
        elif val is None:
            return "(null)" + suffix
        return str(val) + suffix

    def _show_fields() -> None:
        print(f"\n  {heading('Editing:')} {bold(tracking_id)}")
        if drafts:
            print(c(f"  ({len(drafts)} uncommitted change{'s' if len(drafts) != 1 else ''})", "yellow"))
        print(f"  {c('#', 'heading'):<15} {c('FIELD', 'heading'):<33} {c('VALUE', 'heading')}")
        print(c(f"  {'--':<4} {'-----':<22} {'-----'}", "dim"))
        for fi, fname in enumerate(editable, 1):
            print(f"  {c(str(fi), 'dim'):<15} {c(fname, 'label'):<33} {_display_val(fname)}")
        print()
        print(f"  Commands: {c('<#>', 'flag')} edit field, {c('review', 'command')}, {c('commit', 'command')}, {c('cancel', 'command')}")

    def _show_review() -> None:
        if not drafts:
            print(dim("  No uncommitted changes"))
            return
        print(f"\n  {c('Staged changes', 'yellow')} ({len(drafts)}):")
        for fname, new_val in drafts.items():
            old_val = session.get(fname)
            old_display = dim("(null)") if old_val is None else str(old_val)
            new_display = c("(null)", "yellow") if new_val is None else c(str(new_val), "green")
            print(f"    {c(fname, 'label')}: {old_display} {dim('->')} {new_display}")

    def _do_commit() -> bool:
        if not drafts:
            print(dim("  Nothing to commit"))
            return True
        try:
            updated = store.update(tracking_id, **drafts)
            if updated:
                print(c(f"  Committed {len(drafts)} change(s)", "green"))
                # Refresh session state
                session.update(updated)
                drafts.clear()
                return True
            else:
                print(c("  Commit failed", "red"))
                return False
        except ValueError as e:
            print(c(f"  Error: {e}", "red"))
            return False

    _show_fields()

    while True:
        try:
            cmd_input = input("  edit> ").strip()
        except (EOFError, KeyboardInterrupt):
            cmd_input = "cancel"

        if not cmd_input:
            _show_fields()
            continue

        if cmd_input in ("cancel", "0"):
            if drafts:
                print(f"  {len(drafts)} uncommitted change(s). Commit? (y)es / (n)o / (m)aybe")
                try:
                    resp = input("  ").strip().lower()
                except (EOFError, KeyboardInterrupt):
                    resp = "n"
                if resp in ("y", "yes"):
                    _do_commit()
                    return
                elif resp in ("m", "maybe"):
                    continue  # back to edit prompt
                else:
                    print("  Discarded")
                    return
            return

        if cmd_input in ("done", "quit", "exit"):
            if drafts:
                _do_commit()
            return

        if cmd_input == "commit":
            _do_commit()
            continue

        if cmd_input == "review":
            _show_review()
            continue

        if cmd_input.startswith("drop "):
            fname = cmd_input[5:].strip()
            if fname in drafts:
                del drafts[fname]
                print(f"  Dropped staged change for {fname}")
            else:
                print(f"  No staged change for: {fname}")
            continue

        # Field selection by number
        try:
            fi = int(cmd_input) - 1
            if fi < 0 or fi >= len(editable):
                print(f"  Invalid selection: {cmd_input}")
                continue
        except ValueError:
            print(f"  Unknown command: {cmd_input}. Try <#>, review, commit, cancel")
            continue

        fname = editable[fi]
        print(f"  Current: {_display_val(fname)}")

        try:
            new_val_str = input(f"  New value for {fname}: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n  Cancelled field edit")
            continue

        if not new_val_str:
            print("  Cancelled (empty input)")
            continue

        # Type coercion
        if fname == "cli_pid":
            new_val = int(new_val_str) if new_val_str != "null" else None
        elif new_val_str == "null":
            new_val = None
        else:
            new_val = new_val_str

        drafts[fname] = new_val
        print(f"  Staged: {fname} = {new_val_str}")


# =============================================================================
# Date range parsing and history display
# =============================================================================

def _parse_date_range(range_str: str | None) -> tuple[str | None, str | None]:
    """Parse date range string into (since, until).

    Formats:
        SINCE-UNTIL   e.g., 2026-04-01-2026-04-04
        SINCE-        e.g., 2026-04-01-  (from SINCE to now)
        -UNTIL        e.g., -2026-04-04  (from beginning to UNTIL)

    Dates can be YYYY-MM-DD (expanded to start/end of day) or full ISO datetime.
    """
    if not range_str:
        return None, None

    # Split on the separator — but dates contain hyphens too.
    # Strategy: find the boundary between two dates by looking for the
    # pattern YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS
    # A bare trailing/leading hyphen means open-ended.
    s = range_str.strip()

    if s.startswith("-"):
        # -UNTIL
        until = s[1:]
        return None, _normalize_date(until, end_of_day=True)

    if s.endswith("-"):
        # SINCE-
        since = s[:-1]
        return _normalize_date(since, end_of_day=False), None

    # SINCE-UNTIL: find the split point. Dates are at least 10 chars (YYYY-MM-DD).
    # Look for a hyphen that separates two date-like strings.
    # Try splitting after the first complete date (10+ chars).
    for split_pos in range(10, len(s)):
        if s[split_pos] == "-" and split_pos + 1 < len(s):
            left = s[:split_pos]
            right = s[split_pos + 1:]
            # Validate both look like dates
            if (len(left) >= 10 and left[4] == "-" and left[7] == "-" and
                len(right) >= 10 and right[4] == "-" and right[7] == "-"):
                return (
                    _normalize_date(left, end_of_day=False),
                    _normalize_date(right, end_of_day=True),
                )

    # Couldn't parse — treat whole thing as since
    return _normalize_date(s, end_of_day=False), None


def _normalize_date(d: str, end_of_day: bool) -> str:
    """Normalize a date string. If just YYYY-MM-DD, expand to full ISO."""
    if len(d) == 10:  # YYYY-MM-DD
        return f"{d}T23:59:59Z" if end_of_day else f"{d}T00:00:00Z"
    return d


def _print_history(entries: list[dict], as_json: bool = False) -> None:
    """Print change history entries."""
    if as_json:
        print(json.dumps(entries, indent=2))
        return
    if not entries:
        print(dim("  (no changes recorded)"))
        return

    print(
        f"  {c('TIMESTAMP', 'heading'):<37} {c('PID', 'heading'):<19} {c('FIELD', 'heading'):<31} "
        f"{c('OLD', 'heading'):<36} {c('NEW', 'heading'):<36} {c('TRACKING ID', 'heading')}"
    )
    print(c(f"  {'-'*24:<26} {'-'*6:<8} {'-'*18:<20} {'-'*23:<25} {'-'*23:<25} {'-'*20}", "dim"))
    for e in entries:
        old = (e.get("old_value") or "(null)")[:23]
        new = (e.get("new_value") or "(null)")[:23]
        pid = str(e.get("pid") or "?")
        print(
            f"  {dim(e['timestamp']):<37} "
            f"{dim(pid):<19} "
            f"{c(e['field'], 'label'):<31} "
            f"{old:<25} "
            f"{c(new, 'green'):<36} "
            f"{e['tracking_id']}"
        )
    print(dim(f"\n  {len(entries)} change(s)"))


def _print_historical_names(
    entries: list[dict],
    unique: bool = False,
    include_count: bool = False,
) -> None:
    """Print historical name entries in a human-readable table."""
    if not entries:
        print(dim("  (no rename history found)"))
        return

    if include_count:
        print(f"  {c('NAME', 'heading'):<36} {c('LAST USED', 'heading'):<37} {c('USES', 'heading'):>16} {c('ACTIVE', 'heading'):>17}")
        print(c(f"  {'-'*23:<25} {'-'*24:<26} {'-'*5:>5} {'-'*6:>6}", "dim"))
        for e in entries:
            name = (e.get("name") or "?")[:23]
            active = e.get('active_count', 0)
            print(
                f"  {bold(name):<36} "
                f"{dim(e.get('last_used', '?')):<37} "
                f"{e.get('count', 0):>5} "
                f"{c(str(active), 'green' if active > 0 else 'dim'):>17}"
            )
    elif unique:
        print(f"  {c('NAME', 'heading'):<36} {c('LAST USED', 'heading'):<37}")
        print(c(f"  {'-'*23:<25} {'-'*24:<26}", "dim"))
        for e in entries:
            name = (e.get("name") or "?")[:23]
            print(f"  {bold(name):<36} {dim(e.get('last_used', '?')):<37}")
    else:
        print(f"  {c('NAME', 'heading'):<36} {c('TIMESTAMP', 'heading'):<37} {c('TRACKING ID', 'heading')}")
        print(c(f"  {'-'*23:<25} {'-'*24:<26} {'-'*20}", "dim"))
        for e in entries:
            name = (e.get("name") or "?")[:23]
            print(
                f"  {bold(name):<36} "
                f"{dim(e.get('last_used', '?')):<37} "
                f"{e.get('tracking_id', '?')}"
            )

    print(dim(f"\n  {len(entries)} name(s)"))


def _normalize_list_filter_name(name: str) -> str | None:
    """Normalize a list-filter CLI flag name to a session field."""
    normalized = name.strip().lower().replace("-", "_")
    return LIST_FILTER_ALIASES.get(normalized, normalized if normalized in SESSION_FIELDS else None)


def _parse_dynamic_list_filters(tokens: list[str]) -> dict[str, str]:
    """Parse unknown list-command tokens like --uuid abc or --display-name=chat."""
    filters: dict[str, str] = {}
    index = 0

    while index < len(tokens):
        token = tokens[index]
        if not token.startswith("--"):
            raise ValueError(f"Unexpected argument: {token}")

        raw = token[2:]
        if not raw:
            raise ValueError("Invalid empty option name")

        if "=" in raw:
            raw_name, value = raw.split("=", 1)
            index += 1
        else:
            raw_name = raw
            if index + 1 >= len(tokens):
                raise ValueError(f"Missing value for --{raw_name}")
            value = tokens[index + 1]
            if value.startswith("--"):
                raise ValueError(f"Missing value for --{raw_name}")
            index += 2

        field_name = _normalize_list_filter_name(raw_name)
        if not field_name:
            raise ValueError(
                f"Unknown list filter '--{raw_name}'. Use a session field name, alias, or --text."
            )

        filters[field_name] = value

    return filters


# =============================================================================
# CLI interface
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="session_store",
        description="Session data store — query and manage CLI sessions.",
        epilog=format_help(
            "Quick examples:\n"
            "  session_store list                              # all sessions\n"
            "  session_store list --platform claude --status run\n"
            "  session_store list --text guidance              # search all fields\n"
            "  session_store view 20260419_070420_59da2152_cla # by tracking ID\n"
            "  session_store view c15b8645                     # by UUID prefix\n"
            "  session_store edit <tracking_id> --set display_name=NewName\n"
            "  session_store history <tracking_id>             # change log\n"
            "  session_store search 'guidance'                 # full-text search\n"
            "  session_store count --platform claude --status running\n"
            "  session_store children <tracking_id>            # child sessions\n"
            "  session_store validate                          # check running sessions are alive\n"
            "  session_store validate --fix                    # mark stale as stopped\n"
            "  session_store orphans --prune                   # cleanup\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--db", default=None,
        help=f"Database path (default: {DB_PATH})",
    )
    sub = parser.add_subparsers(dest="command")

    # list
    p_list = sub.add_parser(
        "list",
        help="List sessions",
        description=(
            "List sessions. Supports case-insensitive partial matching on any "
            "session field via --<field> VALUE, plus --text for all-field search."
        ),
        epilog=format_help(
            "Examples:\n"
            "  session_store list --uuid 7f3c\n"
            "  session_store list --display-name reviewer\n"
            "  session_store list --working-dir project --status run\n"
            "  session_store list --text gemini\n\n"
            "Field aliases:\n"
            "  --uuid -> cli_session_id\n"
            "  --display-name / --name -> display_name\n"
            "  --terminal / --session -> terminal_session\n"
            "  --tracking -> tracking_id\n"
            "  --parent -> parent_tracking_id\n"
            "  --pid -> cli_pid"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_list.add_argument("--platform", help="Filter by platform (partial, case-insensitive)")
    p_list.add_argument("--status", help="Filter by status (partial, case-insensitive)")
    p_list.add_argument("--parent", help="Filter by parent_tracking_id ('none' for top-level)")
    p_list.add_argument("--text", help="Search across all session fields (partial, case-insensitive)")
    p_list.add_argument("--limit", type=int, help="Max results")
    p_list.add_argument("--json", action="store_true", help="Output as JSON array")
    p_list.add_argument("--no-trunc", action="store_true", help="Don't truncate field values")

    # view (was: get)
    p_view = sub.add_parser(
        "view",
        help="View a session by any identifier",
        description="Look up a session by tracking ID, terminal session name, or CLI UUID (prefix match OK).",
        epilog=format_help(
            "Examples:\n"
            "  session_store view 20260419_070420_59da2152_cla   # by tracking ID\n"
            "  session_store view 59da2152                        # by UUID prefix\n"
            "  session_store view 20260419_070420_59da2152_cla   # by terminal name\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_view.add_argument("identifier", help="Tracking ID, terminal name, or CLI UUID (prefix match OK)")
    # Keep 'get' as hidden alias
    p_get = sub.add_parser("get", help=argparse.SUPPRESS)
    p_get.add_argument("identifier")

    # create
    p_create = sub.add_parser(
        "create",
        help="Create a session",
        description="Register a new session in the store. Typically called by ai_launcher.py.",
        epilog=format_help(
            "Example:\n"
            "  session_store create \\\n"
            "    --tracking-id 20260419_070420_59da2152_cla \\\n"
            "    --terminal-session 20260419_070420_59da2152_cla \\\n"
            "    --platform claude_cli \\\n"
            "    --cli-session-id 59da2152-4f50-4eb5-906f-b7cc361dab51 \\\n"
            "    --display-name 'My Session' \\\n"
            "    --model claude-opus-4-8\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_create.add_argument("--tracking-id", required=True, help="Unique tracking ID (format: YYYYMMDD_HHMMSS_uuid8_plat)")
    p_create.add_argument("--terminal-session", required=True, help="tmux/zellij session name")
    p_create.add_argument("--platform", required=True, help="claude_cli, codex_cli, or gemini_cli")
    p_create.add_argument("--cli-session-id", help="CLI UUID (pre-assigned for Claude, discovered for others)")
    p_create.add_argument("--parent-tracking-id", help="Parent session tracking ID (for forks)")
    p_create.add_argument("--display-name", help="User-facing session name")
    p_create.add_argument("--working-dir", help="Current working directory")
    p_create.add_argument("--project-dir", help="Immutable project root")
    p_create.add_argument("--session-dir", help="Per-session state directory")
    p_create.add_argument("--history-file", help="Primary history/transcript file path")
    p_create.add_argument("--transcript-path", help="JSON array of transcript file paths")
    p_create.add_argument("--model", help="Model ID (e.g. claude-opus-4-8)")
    p_create.add_argument("--substrate", help="tmux, zellij, or none")
    p_create.add_argument("--cli-pid", type=int, help="CLI process PID")
    p_create.add_argument("--status", default="running", help="Initial status (default: running)")

    # edit (was: update)
    p_edit = sub.add_parser(
        "edit",
        help="Edit session fields",
        description="Update one or more fields on a session. Use --set field=value (repeatable).",
        epilog=format_help(
            "Editable fields:\n"
            "  display_name        User-facing session name\n"
            "  status              running, stopped, exited\n"
            "  cli_session_id      CLI UUID (typically auto-discovered)\n"
            "  terminal_session    tmux/zellij session name\n"
            "  cli_pid             CLI process PID\n"
            "  model               Model ID (e.g. claude-opus-4-8)\n"
            "  substrate           tmux, zellij, or none\n"
            "  working_dir         Current working directory\n"
            "  project_dir         Immutable project root\n"
            "  session_dir         Per-session state directory\n"
            "  transcript_path     JSON array of transcript file paths\n"
            "  history_file        Primary history/transcript file path\n"
            "  parent_tracking_id  Parent session tracking ID\n"
            "  roles               JSON array of roles (e.g. '[\"worker\",\"dev\"]')\n"
            "  notes               Free-text session annotations\n"
            "  last_activity       ISO timestamp of last session activity\n"
            "\n"
            "Examples:\n"
            "  session_store edit 20260419_070420_59da2152_cla --set display_name=MySession\n"
            "  session_store edit 20260419_070420_59da2152_cla --set status=stopped\n"
            "  session_store edit 20260419_070420_59da2152_cla --set display_name=Foo --set model=claude-opus-4-8\n"
            "  session_store edit 20260419_070420_59da2152_cla --set roles='[\"worker\"]'\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_edit.add_argument("tracking_id", help="Tracking ID of session to edit")
    p_edit.add_argument("--set", action="append", dest="sets", metavar="field=value",
                        help="Field to update (repeatable, e.g. --set display_name=Foo)")
    # Keep 'update' as hidden alias
    p_update = sub.add_parser("update", help=argparse.SUPPRESS)
    p_update.add_argument("tracking_id")
    p_update.add_argument("--set", action="append", dest="sets", metavar="field=value")

    # history
    p_history = sub.add_parser(
        "history",
        help="Show change history",
        description="Show the change log for a session or all sessions.",
        epilog=format_help(
            "Examples:\n"
            "  session_store history                                    # all recent changes\n"
            "  session_store history 20260419_070420_59da2152_cla       # changes to one session\n"
            "  session_store history --range 2026-04-18-2026-04-19      # date range\n"
            "  session_store history --range 2026-04-18-                # since date\n"
            "  session_store history 20260419_070420_59da2152_cla --json\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_history.add_argument("tracking_id", nargs="?", default=None, help="Filter by tracking ID")
    p_history.add_argument("--range", metavar="DATES",
                           help="Date range: SINCE-UNTIL, SINCE-, or -UNTIL (ISO dates, e.g. 2026-04-01-2026-04-04)")
    p_history.add_argument("--limit", type=int, default=50, help="Max entries")
    p_history.add_argument("--json", action="store_true", help="Output as JSON")

    # get-historical-names
    p_names = sub.add_parser(
        "get-historical-names",
        help="List display names from rename history",
        description=(
            "Query the change log for all display_name renames. "
            "Excludes default/auto-assigned names — only names explicitly set via rename."
        ),
        epilog=format_help(
            "Examples:\n"
            "  session_store get-historical-names                     # all renames, newest first\n"
            "  session_store get-historical-names --unique            # deduplicated\n"
            "  session_store get-historical-names --unique --count    # with usage counts\n"
            "  session_store get-historical-names --sort count        # most-used first\n"
            "  session_store get-historical-names --sort name --json  # alpha, JSON output\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_names.add_argument("--unique", "-u", action="store_true",
                         help="Deduplicate — show each name once")
    p_names.add_argument("--count", "-c", action="store_true",
                         help="Include per-name usage count and active session count")
    p_names.add_argument("--sort", choices=["date", "name", "count"], default="date",
                         help="Sort order: date (default), name (alpha), count (most-used; implies --unique)")
    p_names.add_argument("--json", action="store_true", help="Output as JSON")

    # delete
    p_delete = sub.add_parser("delete", help="Delete a session from the store")
    p_delete.add_argument("tracking_id", help="Tracking ID of session to delete")

    # import
    p_import = sub.add_parser("import-registry", help="Import from JSON file registry")
    p_import.add_argument("--registry-dir", default=None,
                          help="Registry directory (default: AI_ROOT/ai_general/data/session_registry)")

    # export
    p_export = sub.add_parser("export", help="Export all sessions")
    p_export.add_argument("--format", choices=["json", "csv"], default="json")

    # count
    p_count = sub.add_parser("count", help="Count sessions")
    p_count.add_argument("--platform", help="Filter by platform")
    p_count.add_argument("--status", help="Filter by status")

    # children
    p_children = sub.add_parser("children", help="Get children of a session")
    p_children.add_argument("tracking_id")

    # resolve-uri
    p_resolve_uri = sub.add_parser(
        "resolve-uri",
        help="Resolve a uai:// URI to its target id(s) via uri_mappings (JSON list; [] if unregistered)",
    )
    p_resolve_uri.add_argument("uri", help="URI to resolve, e.g. uai://user/piano_man")

    # set-uri-mapping — register any uai://<type>/<id> -> target(s). <type> is open.
    p_set_uri = sub.add_parser(
        "set-uri-mapping",
        help="Register/replace a uai://<type>/<id> mapping (target_type session|fan_out)",
    )
    p_set_uri.add_argument("uri", help="e.g. uai://myfavs/relay-crew")
    p_set_uri.add_argument("--target-type", choices=["session", "fan_out"], required=True)
    p_set_uri.add_argument("--target-value", required=True,
                           help="a tracking_id (session) OR a JSON array of tracking_ids (fan_out)")
    p_set_uri.add_argument("--source-type", default="recipient_set")
    p_set_uri.add_argument("--source-id", required=True)
    p_set_uri.add_argument("--expires-at", help="ISO local time; makes it a temporary registration (resolves to [] once past, then swept)")

    sub.add_parser("prune-expired-uris", help="Delete temporary uri_mappings past their expires_at")

    p_list_uri = sub.add_parser("list-uri-mappings", help="List uri_mappings (optionally by source)")
    p_list_uri.add_argument("--source-type")
    p_list_uri.add_argument("--source-id")

    p_del_uri = sub.add_parser("delete-uri-mapping", help="Delete uri_mappings for a source entity")
    p_del_uri.add_argument("--source-type", required=True)
    p_del_uri.add_argument("--source-id", required=True)

    # clear
    sub.add_parser("clear", help="Delete all sessions (use with --db for test isolation)")

    # load-fixtures
    sub.add_parser("load-fixtures", help="Load deterministic test data (clears first, use with --db)")

    # orphans
    p_orphans = sub.add_parser("orphans", help="Find or prune orphaned sessions (no UUID, no terminal, no PID)")
    p_orphans.add_argument("--prune", action="store_true", help="Remove orphans (default: list only)")
    p_orphans.add_argument("--max-age", type=int, default=2, help="Grace period in hours (default: 2)")

    # validate — bulk liveness check for running sessions
    p_validate = sub.add_parser(
        "validate",
        help="Check running sessions against live terminal sessions",
        description=(
            "Query all sessions with status=running and verify each one has a "
            "live terminal session (tmux or zellij). Sessions whose terminal is "
            "gone are reported as stale. Use --fix to update them to stopped."
        ),
        epilog=format_help(
            "Examples:\n"
            "  session_store validate             # dry-run: report stale sessions\n"
            "  session_store validate --fix        # fix: mark stale as stopped\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_validate.add_argument("--fix", action="store_true",
                            help="Update stale sessions from running to stopped")

    # validate-identity — single-session identity check (old validate behavior)
    p_validate_id = sub.add_parser("validate-identity", help=argparse.SUPPRESS)
    p_validate_id.add_argument("tracking_id")

    # search
    p_search = sub.add_parser(
        "search",
        help="Search all session fields for a substring",
        description="Full-text search across all fields of all sessions.",
        epilog=format_help(
            "Examples:\n"
            "  session_store search guidance          # find sessions mentioning 'guidance'\n"
            "  session_store search opus --json       # JSON output\n"
            "  session_store search devtree --limit 5\n"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p_search.add_argument("query", help="Search term (case-insensitive, matches any field)")
    p_search.add_argument("--limit", type=int, help="Max results")
    p_search.add_argument("--json", action="store_true", help="Output as JSON array")
    p_search.add_argument("--no-trunc", action="store_true", help="Don't truncate field values")

    # repl
    # repl: hidden alias — no-args already enters REPL
    sub.add_parser("repl", help=argparse.SUPPRESS)

    # -- Session tags --
    p_add_tag = sub.add_parser("add_tag", help="Add a tag to a session")
    p_add_tag.add_argument("tracking_id", help="Tracking ID, session:ID, or uai://session/ID")
    p_add_tag.add_argument("tag", help="Tag to add")

    p_remove_tag = sub.add_parser("remove_tag", help="Remove a tag from a session")
    p_remove_tag.add_argument("tracking_id")
    p_remove_tag.add_argument("tag")

    p_get_tags = sub.add_parser("get_tags", help="Get tags for a session (JSON array)")
    p_get_tags.add_argument("tracking_id")

    sub.add_parser("get_all_session_tags", help="Get all tags grouped by tracking_id (JSON object)")
    sub.add_parser("get_all_card_tags", help=argparse.SUPPRESS)  # backward-compat alias

    p_find_by_tag = sub.add_parser("find_by_tag", help="Find tracking IDs by tag (JSON array)")
    p_find_by_tag.add_argument("tag")

    # -- Entity relationships --
    p_add_rel = sub.add_parser("add_relationship", help="Add a relationship between entities")
    p_add_rel.add_argument("source_type")
    p_add_rel.add_argument("source_id")
    p_add_rel.add_argument("relation_type")
    p_add_rel.add_argument("target_type")
    p_add_rel.add_argument("target_id")
    p_add_rel.add_argument("--metadata", default=None, help="JSON metadata string")

    p_rm_rel = sub.add_parser("remove_relationship", help="Remove a relationship")
    p_rm_rel.add_argument("source_type")
    p_rm_rel.add_argument("source_id")
    p_rm_rel.add_argument("relation_type")
    p_rm_rel.add_argument("target_type")
    p_rm_rel.add_argument("target_id")

    p_get_rels = sub.add_parser("get_relationships", help="Get relationships for an entity (JSON)")
    p_get_rels.add_argument("entity_type")
    p_get_rels.add_argument("entity_id")
    p_get_rels.add_argument("--relation-type", default=None, help="Filter by relation type")

    p_find_rel = sub.add_parser("find_related", help="Find entities related to a given entity (JSON)")
    p_find_rel.add_argument("entity_type")
    p_find_rel.add_argument("entity_id")
    p_find_rel.add_argument("--relation-type", default=None, help="Filter by relation type")

    # -- Brief metadata --
    p_reg_brief = sub.add_parser("register_brief", help="Register a new brief")
    p_reg_brief.add_argument("name")
    p_reg_brief.add_argument("--display-name", default=None)
    p_reg_brief.add_argument("--description", default=None)
    p_reg_brief.add_argument("--brief-path", default=None)
    p_reg_brief.add_argument("--content-hash", default=None)
    p_reg_brief.add_argument("--condenser-session", default=None)

    p_upd_brief = sub.add_parser("update_brief", help="Update a brief field")
    p_upd_brief.add_argument("name")
    p_upd_brief.add_argument("--set", action="append", dest="sets", metavar="field=value",
                             help="Field to update (repeatable)")

    p_get_brief = sub.add_parser("get_brief", help="Get a brief by name (JSON)")
    p_get_brief.add_argument("name")

    p_list_briefs = sub.add_parser("list_briefs", help="List briefs (JSON array)")
    p_list_briefs.add_argument("--status", default=None,
                               help="Filter by status (active, superseded, archived)")

    args, unknown = parser.parse_known_args()

    if args.command == "list":
        try:
            args.filters = _parse_dynamic_list_filters(unknown)
        except ValueError as exc:
            p_list.error(str(exc))
        unknown = []
    else:
        args.filters = {}

    if unknown:
        parser.error(f"unrecognized arguments: {' '.join(unknown)}")

    if not args.command:
        # No command = launch REPL by default
        store = SessionStore(db_path=args.db)
        return repl(store)

    store = SessionStore(db_path=args.db)

    if args.command == "list":
        cli_filters = dict(args.filters)
        if args.platform is not None:
            cli_filters["platform"] = args.platform
        # Status is passed as a top-level parameter (derived, not SQL-filtered)
        if args.parent is not None:
            cli_filters["parent_tracking_id"] = args.parent

        sessions = store.list(
            status=args.status,
            limit=args.limit,
            text=args.text,
            filters=cli_filters,
        )
        if args.json:
            print(json.dumps(sessions, indent=2))
        else:
            _print_table(sessions, no_trunc=getattr(args, 'no_trunc', False))

    elif args.command in ("view", "get"):
        session = store.resolve(args.identifier)
        if session:
            print(json.dumps(session, indent=2))
        else:
            print(f"No session found for '{args.identifier}'", file=sys.stderr)
            return 1

    elif args.command == "create":
        session = store.create(
            tracking_id=args.tracking_id,
            terminal_session=args.terminal_session,
            platform=args.platform,
            cli_session_id=args.cli_session_id,
            parent_tracking_id=args.parent_tracking_id,
            display_name=args.display_name,
            working_dir=args.working_dir,
            project_dir=args.project_dir,
            session_dir=args.session_dir,
            history_file=args.history_file,
            transcript_path=args.transcript_path,
            model=args.model,
            substrate=args.substrate,
            cli_pid=args.cli_pid,
            status=args.status,
        )
        print(json.dumps(session, indent=2))

    elif args.command in ("edit", "update"):
        # Resolve identifier (tracking_id, terminal name, or CLI UUID)
        resolved = store.resolve(args.tracking_id)
        if not resolved:
            print(f"No session found: {args.tracking_id}", file=sys.stderr)
            return 1
        tid = resolved["tracking_id"]

        if not args.sets:
            # No --set: drop into interactive edit mode
            _interactive_edit(store, tid)
        else:
            fields = {}
            for s in args.sets:
                if "=" not in s:
                    print(f"Error: invalid --set format '{s}' (expected field=value)", file=sys.stderr)
                    return 1
                key, value = s.split("=", 1)
                if key == "cli_pid":
                    value = int(value) if value else None
                elif value == "null":
                    value = None
                fields[key] = value
            session = store.update(tid, **fields)
            if session:
                print(json.dumps(session, indent=2))
            else:
                print(f"Update failed: {tid}", file=sys.stderr)
                return 1

    elif args.command == "history":
        since, until = _parse_date_range(getattr(args, 'range', None))
        entries = store.history(
            tracking_id=args.tracking_id,
            since=since, until=until,
            limit=args.limit,
        )
        _print_history(entries, as_json=args.json)

    elif args.command == "get-historical-names":
        entries = store.get_historical_names(
            unique=args.unique,
            include_count=args.count,
            sort=args.sort,
        )
        if args.json:
            print(json.dumps(entries, indent=2))
        else:
            _print_historical_names(entries, unique=args.unique, include_count=args.count)

    elif args.command == "delete":
        if store.delete(args.tracking_id):
            print(f"Deleted: {args.tracking_id}")
        else:
            print(f"Not found: {args.tracking_id}", file=sys.stderr)
            return 1

    elif args.command == "import-registry":
        from uai_toolkit.cli.lib_paths import SESSION_REGISTRY_DIR
        registry_dir = Path(args.registry_dir) if args.registry_dir else SESSION_REGISTRY_DIR
        count = store.import_from_registry(registry_dir)
        print(f"Imported {count} sessions from {registry_dir}")

    elif args.command == "export":
        sessions = store.list()
        if args.format == "json":
            print(json.dumps(sessions, indent=2))
        elif args.format == "csv":
            if sessions:
                keys = sessions[0].keys()
                print(",".join(keys))
                for s in sessions:
                    print(",".join(str(s.get(k, "")) for k in keys))

    elif args.command == "count":
        cnt = store.count(platform=args.platform, status=args.status)
        print(cnt)

    elif args.command == "children":
        children = store.get_children(args.tracking_id)
        print(json.dumps(children, indent=2))

    elif args.command == "resolve-uri":
        print(json.dumps(store.resolve_uri(args.uri)))

    elif args.command == "set-uri-mapping":
        store.set_uri_mapping(args.uri, args.target_type, args.target_value,
                              args.source_type, args.source_id,
                              expires_at=getattr(args, "expires_at", None))
        print(json.dumps({"ok": True, "uri": args.uri, "expires_at": getattr(args, "expires_at", None)}))

    elif args.command == "prune-expired-uris":
        print(json.dumps({"deleted": store.delete_expired_uri_mappings()}))

    elif args.command == "list-uri-mappings":
        print(json.dumps(store.list_uri_mappings(args.source_type, args.source_id), indent=2))

    elif args.command == "delete-uri-mapping":
        n = store.delete_uri_mappings(args.source_type, args.source_id)
        print(json.dumps({"deleted": n}))

    elif args.command == "clear":
        count = store.clear()
        print(f"Cleared {count} sessions")

    elif args.command == "load-fixtures":
        count = store.load_fixtures()
        print(f"Loaded {count} test sessions")

    elif args.command == "orphans":
        orphans = store.find_orphans(max_age_hours=args.max_age)
        if not orphans:
            print("  No orphaned sessions found")
        else:
            _print_table(orphans)
            if args.prune:
                removed = store.prune_orphans(max_age_hours=args.max_age)
                print(f"\n  Pruned {removed} orphaned session(s)")

    elif args.command == "validate":
        result = store.validate_running_sessions(fix=args.fix)
        total = result["total"]
        confirmed = result["confirmed"]
        stale_count = result["stale"]
        stale_sessions = result["stale_sessions"]

        print(f"{heading('Validating')} {total} sessions with status=running...")
        _check = '✓'
        print(f"  {c(_check, 'green')} {c(str(confirmed), 'green')} sessions confirmed running")
        _cross = '✗'
        print(f"  {c(_cross, 'red')} {c(str(stale_count), 'red' if stale_count else 'dim')} sessions stale (terminal session not found)")

        if stale_sessions:
            print()
            print(c("Stale sessions:", "yellow"))
            for s in stale_sessions:
                created = (s.get("created_at") or "")[:10]
                tid = s.get("tracking_id", "?")
                name = s.get("display_name") or ""
                name_suffix = f"  ({bold(name)})" if name and name != tid else ""
                print(f"  {tid}  {dim(f'(last seen: {created})')}{name_suffix}")

            if args.fix:
                print()
                print(c(f"Fixed {result['fixed']} stale sessions: running \u2192 stopped", "green"))
            else:
                print()
                print(f"Run with {c('--fix', 'flag')} to update stale sessions to status=stopped")

    elif args.command == "validate-identity":
        result = store.validate(args.tracking_id)
        print(json.dumps(result, indent=2))

    elif args.command == "search":
        sessions = store.list(text=args.query, limit=args.limit)
        if args.json:
            print(json.dumps(sessions, indent=2))
        else:
            _print_table(sessions, no_trunc=getattr(args, 'no_trunc', False))

    # -- Session tags --
    elif args.command == "add_tag":
        tid = store._normalize_tag_id(args.tracking_id)
        store.add_tag(tid, args.tag)
        print(json.dumps({"tracking_id": tid, "tag": args.tag, "action": "added"}))

    elif args.command == "remove_tag":
        tid = store._normalize_tag_id(args.tracking_id)
        removed = store.remove_tag(tid, args.tag)
        if removed:
            print(json.dumps({"tracking_id": tid, "tag": args.tag, "action": "removed"}))
        else:
            print("Tag '{}' not found on '{}'".format(args.tag, tid), file=sys.stderr)
            return 1

    elif args.command == "get_tags":
        print(json.dumps(store.get_tags(args.tracking_id)))

    elif args.command in ("get_all_session_tags", "get_all_card_tags"):
        print(json.dumps(store.get_all_session_tags()))

    elif args.command == "find_by_tag":
        print(json.dumps(store.find_by_tag(args.tag)))

    # -- Entity relationships --
    elif args.command == "add_relationship":
        metadata = json.loads(args.metadata) if args.metadata else None
        store.add_relationship(
            args.source_type, args.source_id, args.relation_type,
            args.target_type, args.target_id, metadata=metadata,
        )
        print(json.dumps({
            "source": f"{args.source_type}:{args.source_id}",
            "relation": args.relation_type,
            "target": f"{args.target_type}:{args.target_id}",
            "action": "added",
        }))

    elif args.command == "remove_relationship":
        removed = store.remove_relationship(
            args.source_type, args.source_id, args.relation_type,
            args.target_type, args.target_id,
        )
        if removed:
            print(json.dumps({"action": "removed"}))
        else:
            print("Relationship not found", file=sys.stderr)
            return 1

    elif args.command == "get_relationships":
        rels = store.get_relationships(
            args.entity_type, args.entity_id,
            relation_type=getattr(args, 'relation_type', None),
        )
        print(json.dumps(rels, indent=2))

    elif args.command == "find_related":
        related = store.find_related(
            args.entity_type, args.entity_id,
            relation_type=getattr(args, 'relation_type', None),
        )
        print(json.dumps(related, indent=2))

    # -- Brief metadata --
    elif args.command == "register_brief":
        brief = store.register_brief(
            args.name,
            display_name=args.display_name,
            description=args.description,
            brief_path=args.brief_path,
            content_hash=args.content_hash,
            condenser_session=args.condenser_session,
        )
        print(json.dumps(brief, indent=2))

    elif args.command == "update_brief":
        if not args.sets:
            print("Error: --set required", file=sys.stderr)
            return 1
        fields = {}
        for s in args.sets:
            if "=" not in s:
                print(f"Error: invalid --set format '{s}' (expected field=value)", file=sys.stderr)
                return 1
            key, value = s.split("=", 1)
            if value == "null":
                value = None
            fields[key] = value
        brief = store.update_brief(args.name, **fields)
        if brief:
            print(json.dumps(brief, indent=2))
        else:
            print(f"Brief not found: {args.name}", file=sys.stderr)
            return 1

    elif args.command == "get_brief":
        brief = store.get_brief(args.name)
        if brief:
            print(json.dumps(brief, indent=2))
        else:
            print(f"Brief not found: {args.name}", file=sys.stderr)
            return 1

    elif args.command == "list_briefs":
        briefs = store.list_briefs(status=args.status)
        print(json.dumps(briefs, indent=2))

    elif args.command == "repl":
        return repl(store)

    return 0


# =============================================================================
# REPL — Interactive session registry editor
# =============================================================================

def repl(store: SessionStore) -> int:
    """Interactive session registry editor.

    Commands:
      list [--platform X] [--status X] [--text X] [--field X]   List sessions (assigns temp indices)
      search <query>                     Search any field for substring match
      view <index_or_id>                 View full session details
      edit <index_or_id> field=value     Edit a session field
      create                             Interactive session creation
      delete <index_or_id>               Delete a session
      count [--platform X] [--status X]  Count sessions
      help                               Show commands
      quit / exit / q                    Exit REPL
    """
    import readline  # enables arrow keys, history in input()

    # Temporary index → tracking_id mapping from last list/search
    index_map: list[str] = []

    def resolve_ref(ref: str) -> str | None:
        """Resolve a user reference to a tracking_id.

        Accepts: URI (uai://session/<id>), temp index (#N or just N), tracking_id, terminal_session, CLI UUID.
        """
        ref = ref.strip().lstrip('#')
        if ref.startswith('uai://session/'):
            ref = ref[len('uai://session/'):]

        # Try as temp index
        try:
            idx = int(ref) - 1  # 1-based display
            if 0 <= idx < len(index_map):
                return index_map[idx]
        except ValueError:
            pass

        # Try as tracking_id, terminal_session, or CLI UUID
        session = store.resolve(ref)
        if session:
            return session["tracking_id"]

        return None

    # State: truncation mode (toggled by --no-trunc on list/search)
    no_trunc = False

    PAGE_SIZE = 20  # rows per page in REPL

    def print_session_list(sessions: list[dict]) -> None:
        """Print sessions with indices, update index_map for ref resolution."""
        nonlocal index_map
        index_map = [s["tracking_id"] for s in sessions]
        _print_table(sessions, no_trunc=no_trunc, page_size=PAGE_SIZE, interactive=True)

    def print_session_detail(session: dict) -> None:
        """Print full session details."""
        print()
        for key, value in session.items():
            if key == "roles" and isinstance(value, list):
                value = ", ".join(value) if value else dim("(none)")
            elif value is None:
                value = dim("(null)")
            print(f"  {c(key, 'label'):.<36} {value}")
        print()

    def do_search(query: str) -> None:
        """Search all fields for substring match."""
        print_session_list(store.list(text=query))

    print(f"{heading('Session Store REPL')} — type {c('help', 'command')} for commands, {c('q', 'command')} to quit")
    print(f"{c('Database:', 'label')} {dim(str(store.db_path))}")
    print(f"{c('Sessions:', 'label')} {bold(str(store.count()))}\n")

    while True:
        try:
            line = input("sessions> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        parts = line.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1] if len(parts) > 1 else ""

        if cmd in ("quit", "exit", "q"):
            break

        elif cmd == "help":
            print(format_help("""
Commands:
  list [--platform X] [--status X] [--text X] [--field X] [--no-trunc]   List sessions (3-digit indices)
  search <query> [--no-trunc]                     Search any field for substring match
  view <ref>                         View full session (#N, tracking_id, UUID, terminal name)
  edit <ref> [field=value ...]       Edit session (interactive menu if no field=value given)
  create                             Interactive session creation
  delete <ref>                       Delete a session
  history [ref] [--json]             Show change history (all or for one session)
  count [--platform X] [--status X]  Count sessions
  sql <query>                        Run raw SQL (read-only SELECT only)
  help                               This help
  quit / exit / q                    Exit

Shortcuts:
  Indices (#N or just N) can be used as shortcuts: view 34, edit 12, delete 5
"""))

        elif cmd == "list":
            kwargs: dict[str, Any] = {}
            tokens = rest.split()
            i = 0
            no_trunc = False  # reset per command
            filters: dict[str, Any] = {}
            dynamic_tokens: list[str] = []
            while i < len(tokens):
                if tokens[i] == "--platform" and i + 1 < len(tokens):
                    filters["platform"] = tokens[i + 1]
                    i += 2
                elif tokens[i] == "--status" and i + 1 < len(tokens):
                    kwargs["status"] = tokens[i + 1]
                    i += 2
                elif tokens[i] == "--parent" and i + 1 < len(tokens):
                    filters["parent_tracking_id"] = tokens[i + 1]
                    i += 2
                elif tokens[i] == "--text" and i + 1 < len(tokens):
                    kwargs["text"] = tokens[i + 1]
                    i += 2
                elif tokens[i] == "--limit" and i + 1 < len(tokens):
                    kwargs["limit"] = int(tokens[i + 1])
                    i += 2
                elif tokens[i] == "--no-trunc":
                    no_trunc = True
                    i += 1
                else:
                    dynamic_tokens.append(tokens[i])
                    if "=" not in tokens[i] and i + 1 < len(tokens):
                        dynamic_tokens.append(tokens[i + 1])
                        i += 2
                    else:
                        i += 1
            if dynamic_tokens:
                try:
                    filters.update(_parse_dynamic_list_filters(dynamic_tokens))
                except ValueError as e:
                    print(f"  Error: {e}")
                    continue
            if filters:
                kwargs["filters"] = filters
            sessions = store.list(**kwargs)
            print_session_list(sessions)

        elif cmd == "search":
            if not rest:
                print("  Usage: search <query>")
            else:
                # Check for --no-trunc at end of search
                if rest.endswith("--no-trunc"):
                    no_trunc = True
                    rest = rest.rsplit("--no-trunc", 1)[0].strip()
                else:
                    no_trunc = False
                do_search(rest)

        elif cmd == "view":
            if not rest:
                print("  Usage: view <#N or identifier>")
            else:
                tid = resolve_ref(rest)
                if tid:
                    session = store.get(tid)
                    if session:
                        print_session_detail(session)
                    else:
                        print(f"  Not found: {rest}")
                else:
                    print(f"  Not found: {rest}")

        elif cmd == "edit":
            edit_parts = rest.split(None, 1)
            if not edit_parts:
                print("  Usage: edit <#N or identifier> [field=value ...]")
                continue

            ref = edit_parts[0]
            field_str = edit_parts[1] if len(edit_parts) > 1 else ""
            tid = resolve_ref(ref)
            if not tid:
                print(f"  Not found: {ref}")
                continue

            if field_str:
                # Inline edit: edit <ref> field=value [field=value ...]
                # Commits immediately (same as CLI --set behavior)
                fields: dict[str, Any] = {}
                for token in field_str.split():
                    if "=" not in token:
                        print(f"  Invalid: '{token}' (expected field=value)")
                        continue
                    key, value = token.split("=", 1)
                    if key == "cli_pid":
                        value = int(value) if value and value != "null" else None
                    elif value == "null":
                        value = None
                    fields[key] = value

                if fields:
                    try:
                        updated = store.update(tid, **fields)
                        if updated:
                            print(f"  Updated {tid}")
                            print_session_detail(updated)
                        else:
                            print(f"  Not found: {tid}")
                    except ValueError as e:
                        print(f"  Error: {e}")
            else:
                # Interactive edit with draft/commit
                _interactive_edit(store, tid)

        elif cmd == "create":
            print("  Interactive session creation:")
            try:
                tracking_id = input("    tracking_id: ").strip()
                if not tracking_id:
                    print("  Cancelled (tracking_id required)")
                    continue
                terminal = input(f"    terminal_session [{tracking_id}]: ").strip() or tracking_id
                platform = input("    platform (claude_cli/codex_cli/gemini_cli) [claude_cli]: ").strip() or "claude_cli"
                cli_uuid = input("    cli_session_id (or empty): ").strip() or None
                display = input(f"    display_name [{terminal}]: ").strip() or terminal
                status = input("    status [running]: ").strip() or "running"

                session = store.create(
                    tracking_id=tracking_id,
                    terminal_session=terminal,
                    platform=platform,
                    cli_session_id=cli_uuid,
                    display_name=display,
                    status=status,
                )
                print(f"  Created:")
                print_session_detail(session)
            except (EOFError, KeyboardInterrupt):
                print("\n  Cancelled")

        elif cmd == "delete":
            if not rest:
                print("  Usage: delete <#N or identifier>")
                continue
            tid = resolve_ref(rest)
            if not tid:
                print(f"  Not found: {rest}")
                continue
            confirm = input(f"  Delete {tid}? (y/N): ").strip().lower()
            if confirm == "y":
                if store.delete(tid):
                    print(f"  Deleted: {tid}")
                else:
                    print(f"  Not found: {tid}")
            else:
                print("  Cancelled")

        elif cmd == "count":
            kwargs = {}
            tokens = rest.split()
            i = 0
            while i < len(tokens):
                if tokens[i] == "--platform" and i + 1 < len(tokens):
                    kwargs["platform"] = tokens[i + 1]
                    i += 2
                elif tokens[i] == "--status" and i + 1 < len(tokens):
                    kwargs["status"] = tokens[i + 1]
                    i += 2
                else:
                    i += 1
            print(f"  {store.count(**kwargs)}")

        elif cmd == "sql":
            if not rest:
                print("  Usage: sql <SELECT query>")
                continue
            if not rest.strip().upper().startswith("SELECT"):
                print("  Only SELECT queries allowed in REPL")
                continue
            try:
                with store._connect() as conn:
                    rows = conn.execute(rest).fetchall()
                    if not rows:
                        print("  (no rows)")
                    else:
                        # Print column headers
                        cols = [desc[0] for desc in rows[0].keys()] if hasattr(rows[0], 'keys') else []
                        if cols:
                            print("  " + " | ".join(cols))
                            print("  " + "-+-".join("-" * len(c) for c in cols))
                        for row in rows:
                            print("  " + " | ".join(str(v) for v in row))
                        print(f"\n  {len(rows)} row(s)")
            except Exception as e:
                print(f"  SQL error: {e}")

        elif cmd == "history":
            h_parts = rest.split()
            h_json = "--json" in h_parts
            h_parts = [p for p in h_parts if p != "--json"]
            # Check for --range
            h_range = None
            for hi, hp in enumerate(h_parts):
                if hp == "--range" and hi + 1 < len(h_parts):
                    h_range = h_parts[hi + 1]
                    h_parts = h_parts[:hi] + h_parts[hi + 2:]
                    break
            h_ref = h_parts[0] if h_parts else None
            h_tid = resolve_ref(h_ref) if h_ref else None
            h_since, h_until = _parse_date_range(h_range)

            entries = store.history(tracking_id=h_tid, since=h_since, until=h_until)
            _print_history(entries, as_json=h_json)

        else:
            # Try as a bare index → view shortcut (e.g., "34" → "view 34")
            try:
                idx = int(cmd) - 1
                if 0 <= idx < len(index_map):
                    session = store.get(index_map[idx])
                    if session:
                        print_session_detail(session)
                    continue
            except ValueError:
                pass

            # Otherwise try as a search
            do_search(line)

    return 0


if __name__ == "__main__":
    sys.exit(main())
