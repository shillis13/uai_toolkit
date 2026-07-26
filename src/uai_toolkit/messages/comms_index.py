#!/usr/bin/env python3
"""
comms_index.py — SQLite-backed authoritative index for the ai_comms model.

This is the single store for conversations, messages, deliveries, obligations,
and body_refs. It mirrors the conventions of the sibling session_store.py:
module-level DDL, `_init_db()` with CREATE TABLE IF NOT EXISTS, stdlib sqlite3,
a DB_PATH resolved from AI_ROOT but overridable via the constructor for tests,
WAL journaling and foreign-key enforcement.

Task 1 scope: DB module + schema only. Write/read APIs, the send contract, and
backfill arrive in later tasks — do not add them here.

Library usage:
    from uai_toolkit.messages.comms_index import CommsIndex
    idx = CommsIndex()                      # uses DB_PATH under AI_ROOT
    idx = CommsIndex(db_path="/tmp/x.db")   # overridable for tests

Database location: {AI_ROOT}/ai_general/data/comms.db
Schema version tracked in the 'comms_meta' table for forward migration.
"""

from __future__ import annotations

import os
import secrets
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, Union

_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_ROOT  # noqa: E402

SCHEMA_VERSION = 1

# AI_ROOT resolution mirrors the workspace convention.
DB_PATH = AI_ROOT / "ai_general" / "data" / "comms.db"

# Body files referenced by body_refs.path are resolved relative to the comms
# root. Module-level so tests can monkeypatch it.
COMMS_ROOT = AI_ROOT / "ai_comms"


# =============================================================================
# Schema
# =============================================================================

SCHEMA_DDL = """
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY, topic TEXT, status TEXT NOT NULL DEFAULT 'open',
  created_at TEXT NOT NULL, last_activity TEXT NOT NULL, linked_work TEXT,
  root_count INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS messages (
  id TEXT PRIMARY KEY,
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  reply_to TEXT, subject TEXT, effective_subject TEXT,
  from_id TEXT NOT NULL, to_entity TEXT NOT NULL,
  delivery TEXT NOT NULL DEFAULT 'message',
  type TEXT, urgency TEXT, response_type TEXT,
  ttl_seconds INTEGER, response_required INTEGER NOT NULL DEFAULT 0,
  created_at TEXT NOT NULL, body TEXT, body_ref TEXT
);
CREATE INDEX IF NOT EXISTS idx_messages_convo ON messages(conversation_id);
CREATE INDEX IF NOT EXISTS idx_messages_from ON messages(from_id);
CREATE TABLE IF NOT EXISTS deliveries (
  message_id TEXT NOT NULL REFERENCES messages(id),
  recipient TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'queued',
  delivered_at TEXT, read_at TEXT, error TEXT,
  PRIMARY KEY (message_id, recipient)
);
CREATE INDEX IF NOT EXISTS idx_deliveries_recipient ON deliveries(recipient, status);
CREATE TABLE IF NOT EXISTS obligations (
  conversation_id TEXT NOT NULL REFERENCES conversations(id),
  message_id TEXT NOT NULL REFERENCES messages(id),
  participant TEXT NOT NULL, kind TEXT NOT NULL DEFAULT 'reply',
  created_at TEXT NOT NULL, cleared_at TEXT, cleared_by TEXT,
  PRIMARY KEY (message_id, participant)
);
CREATE INDEX IF NOT EXISTS idx_obligations_open ON obligations(conversation_id, participant) WHERE cleared_at IS NULL;
CREATE TABLE IF NOT EXISTS body_refs (
  id TEXT PRIMARY KEY, path TEXT NOT NULL, bytes INTEGER, sha256 TEXT,
  msg_count INTEGER NOT NULL DEFAULT 1, external INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS comms_meta (key TEXT PRIMARY KEY, value TEXT);
"""


class CommsIndex:
    """Authoritative SQLite index for conversations and messaging.

    The SQLite file format is an implementation detail hidden behind this API.
    """

    def __init__(self, db_path: Optional[Union[str, Path]] = None):
        self.db_path = Path(db_path) if db_path is not None else DB_PATH
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path))
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA foreign_keys=ON")
        return con

    def _init_db(self) -> None:
        con = self._connect()
        try:
            con.executescript(SCHEMA_DDL)
            # Insert schema_version only if absent so reopening is idempotent.
            con.execute(
                "INSERT OR IGNORE INTO comms_meta (key, value) VALUES (?, ?)",
                ("schema_version", str(SCHEMA_VERSION)),
            )
            con.commit()
        finally:
            con.close()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    @staticmethod
    def _now() -> str:
        """ISO-8601 timestamp (seconds resolution), local time."""
        return datetime.now().strftime("%Y-%m-%dT%H:%M:%S")

    @staticmethod
    def _gen_id(prefix: str) -> str:
        """Mint an id of the form `<prefix>_<YYYYMMDD>_<HHMMSS>_<8 hex>`."""
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return f"{prefix}_{ts}_{secrets.token_hex(4)}"

    # -------------------------------------------------------------------------
    # Write API
    # -------------------------------------------------------------------------

    def create_conversation(
        self,
        topic: Optional[str],
        status: str = "open",
        linked_work: Optional[str] = None,
    ) -> str:
        """Create a conversation row; created_at == last_activity == now."""
        cid = self._gen_id("convo")
        now = self._now()
        con = self._connect()
        try:
            con.execute(
                "INSERT INTO conversations "
                "(id, topic, status, created_at, last_activity, linked_work) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (cid, topic, status, now, now, linked_work),
            )
            con.commit()
        finally:
            con.close()
        return cid

    def insert_message(self, msg: dict) -> str:
        """Insert a message row, computing effective_subject, and bump the
        conversation's last_activity to the message's created_at.

        `msg` carries either an inline `body` or an externalized `body_ref`.
        body_refs.msg_count is intentionally not touched here.
        """
        subject = msg.get("subject")
        reply_to = msg.get("reply_to")
        con = self._connect()
        try:
            # effective_subject: explicit subject wins; else inherit from the
            # parent message; else NULL.
            if subject:
                effective_subject = subject
            elif reply_to:
                parent = con.execute(
                    "SELECT effective_subject FROM messages WHERE id = ?",
                    (reply_to,),
                ).fetchone()
                effective_subject = parent[0] if parent else None
            else:
                effective_subject = None

            con.execute(
                "INSERT INTO messages "
                "(id, conversation_id, reply_to, subject, effective_subject, "
                " from_id, to_entity, delivery, type, urgency, response_type, "
                " ttl_seconds, response_required, created_at, body, body_ref) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    msg["id"],
                    msg["conversation_id"],
                    reply_to,
                    subject,
                    effective_subject,
                    msg["from_id"],
                    msg["to_entity"],
                    msg.get("delivery", "message"),
                    msg.get("type"),
                    msg.get("urgency"),
                    msg.get("response_type"),
                    msg.get("ttl_seconds"),
                    msg.get("response_required", 0),
                    msg["created_at"],
                    msg.get("body"),
                    msg.get("body_ref"),
                ),
            )
            con.execute(
                "UPDATE conversations SET last_activity = ? WHERE id = ?",
                (msg["created_at"], msg["conversation_id"]),
            )
            con.commit()
        finally:
            con.close()
        return msg["id"]

    def insert_delivery(
        self, message_id: str, recipient: str, status: str = "queued"
    ) -> None:
        """Insert a delivery row. Idempotent on PK (message_id, recipient):
        a duplicate insert is ignored, leaving the existing row untouched."""
        con = self._connect()
        try:
            con.execute(
                "INSERT OR IGNORE INTO deliveries "
                "(message_id, recipient, status) VALUES (?, ?, ?)",
                (message_id, recipient, status),
            )
            con.commit()
        finally:
            con.close()

    def set_delivery_status(
        self,
        message_id: str,
        recipient: str,
        status: str,
        *,
        read_at: Optional[str] = None,
        delivered_at: Optional[str] = None,
        error: Optional[str] = None,
    ) -> None:
        """Update a delivery's status plus any provided timestamps/error.

        Only fields that are explicitly passed are written; omitted timestamp
        and error fields are left at their current values.
        """
        sets = ["status = ?"]
        params: list = [status]
        if delivered_at is not None:
            sets.append("delivered_at = ?")
            params.append(delivered_at)
        if read_at is not None:
            sets.append("read_at = ?")
            params.append(read_at)
        if error is not None:
            sets.append("error = ?")
            params.append(error)
        params.extend([message_id, recipient])
        con = self._connect()
        try:
            con.execute(
                "UPDATE deliveries SET " + ", ".join(sets)
                + " WHERE message_id = ? AND recipient = ?",
                params,
            )
            con.commit()
        finally:
            con.close()

    def open_obligation(
        self,
        conversation_id: str,
        message_id: str,
        participant: str,
        kind: str = "reply",
    ) -> None:
        """Open an obligation (cleared_at NULL). Idempotent on PK
        (message_id, participant)."""
        con = self._connect()
        try:
            con.execute(
                "INSERT OR IGNORE INTO obligations "
                "(conversation_id, message_id, participant, kind, created_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (conversation_id, message_id, participant, kind, self._now()),
            )
            con.commit()
        finally:
            con.close()

    def clear_obligations(
        self, conversation_id: str, participant: str, by: str
    ) -> int:
        """Clear the participant's OPEN obligations in a conversation.

        Returns the number of obligations cleared.
        """
        now = self._now()
        con = self._connect()
        try:
            cur = con.execute(
                "UPDATE obligations SET cleared_at = ?, cleared_by = ? "
                "WHERE conversation_id = ? AND participant = ? "
                "AND cleared_at IS NULL",
                (now, by, conversation_id, participant),
            )
            con.commit()
            return cur.rowcount
        finally:
            con.close()

    def conversation_needs_input(self, conversation_id: str) -> bool:
        """True iff an open obligation exists for the conversation."""
        con = self._connect()
        try:
            row = con.execute(
                "SELECT 1 FROM obligations "
                "WHERE conversation_id = ? AND cleared_at IS NULL LIMIT 1",
                (conversation_id,),
            ).fetchone()
        finally:
            con.close()
        return row is not None

    # -------------------------------------------------------------------------
    # Read API — body resolution
    # -------------------------------------------------------------------------

    def _resolve_body(self, row, con: Optional[sqlite3.Connection] = None) -> str:
        """Resolve a message's body: inline `body` wins; else read the
        `body_ref` file under COMMS_ROOT; else ''. Missing files yield ''.

        `row` is any mapping/Row exposing `body` and `body_ref`.
        """
        body = row["body"]
        if body is not None:
            return body
        ref_id = row["body_ref"]
        if not ref_id:
            return ""
        owns = con is None
        if owns:
            con = self._connect()
            con.row_factory = sqlite3.Row
        try:
            ref = con.execute(
                "SELECT path FROM body_refs WHERE id = ?", (ref_id,)
            ).fetchone()
        finally:
            if owns:
                con.close()
        if not ref or not ref["path"]:
            return ""
        try:
            return (COMMS_ROOT / ref["path"]).read_text()
        except OSError:
            return ""

    # -------------------------------------------------------------------------
    # Read API — row builders
    # -------------------------------------------------------------------------

    def _message_dict(self, row, con: sqlite3.Connection) -> dict:
        """Shape a messages row for the UI contract (note: `from` key)."""
        return {
            "id": row["id"],
            "conversation_id": row["conversation_id"],
            "reply_to": row["reply_to"],
            "subject": row["subject"],
            "effective_subject": row["effective_subject"],
            "from": row["from_id"],
            "to_entity": row["to_entity"],
            "delivery": row["delivery"],
            "type": row["type"],
            "urgency": row["urgency"],
            "response_required": row["response_required"],
            "created_at": row["created_at"],
            "body": self._resolve_body(row, con),
        }

    @staticmethod
    def _delivery_dict(row) -> dict:
        return {
            "message_id": row["message_id"],
            "recipient": row["recipient"],
            "status": row["status"],
            "delivered_at": row["delivered_at"],
            "read_at": row["read_at"],
            "error": row["error"],
        }

    @staticmethod
    def _conversation_participants(con: sqlite3.Connection, cid: str) -> list:
        """Tracking ids = senders ∪ delivery recipients across the
        conversation's messages, sorted for stable output."""
        rows = con.execute(
            "SELECT from_id AS p FROM messages WHERE conversation_id = ? "
            "UNION "
            "SELECT d.recipient AS p FROM deliveries d "
            "JOIN messages m ON d.message_id = m.id "
            "WHERE m.conversation_id = ?",
            (cid, cid),
        ).fetchall()
        return sorted({r["p"] for r in rows})

    def _needs_input(self, con: sqlite3.Connection, cid: str) -> bool:
        row = con.execute(
            "SELECT 1 FROM obligations "
            "WHERE conversation_id = ? AND cleared_at IS NULL LIMIT 1",
            (cid,),
        ).fetchone()
        return row is not None

    # -------------------------------------------------------------------------
    # Read API — queries
    # -------------------------------------------------------------------------

    def list_conversations(
        self,
        *,
        status: Optional[str] = None,
        participants: Optional[list] = None,
        linked_work: Optional[str] = None,
        needs_input: Optional[bool] = None,
        limit: Optional[int] = None,
        offset: int = 0,
        order: str = "last_activity",
    ) -> list:
        """List conversations with derived fields, filters, and pagination."""
        if order not in ("last_activity", "created_at"):
            order = "last_activity"
        where, params = [], []
        if status is not None:
            where.append("status = ?")
            params.append(status)
        if linked_work is not None:
            where.append("linked_work LIKE ?")
            params.append(f"%{linked_work}%")
        sql = "SELECT * FROM conversations"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += f" ORDER BY {order} DESC, id DESC"

        pset = set(participants) if participants else None
        con = self._connect()
        con.row_factory = sqlite3.Row
        try:
            result = []
            for r in con.execute(sql, params).fetchall():
                cid = r["id"]
                parts = self._conversation_participants(con, cid)
                ni = self._needs_input(con, cid)
                if pset is not None and not (pset & set(parts)):
                    continue
                if needs_input is not None and ni != needs_input:
                    continue
                mc = con.execute(
                    "SELECT COUNT(*) FROM messages WHERE conversation_id = ?",
                    (cid,),
                ).fetchone()[0]
                last = con.execute(
                    "SELECT body, body_ref FROM messages "
                    "WHERE conversation_id = ? ORDER BY created_at DESC, id DESC "
                    "LIMIT 1",
                    (cid,),
                ).fetchone()
                preview = ""
                if last is not None:
                    body = self._resolve_body(last, con)
                    preview = body[:120] + "…" if len(body) > 120 else body
                result.append({
                    "id": cid,
                    "topic": r["topic"],
                    "status": r["status"],
                    "needs_input": ni,
                    "participants": parts,
                    "last_activity": r["last_activity"],
                    "created_at": r["created_at"],
                    "linked_work": r["linked_work"],
                    "message_count": mc,
                    "last_message_preview": preview,
                })
        finally:
            con.close()

        if offset:
            result = result[offset:]
        if limit is not None:
            result = result[:limit]
        return result

    def get_conversation(self, conversation_id: str) -> dict:
        """Return a conversation with its messages (asc), deliveries, and
        obligations. Bodies are resolved; messages use the `from` key."""
        con = self._connect()
        con.row_factory = sqlite3.Row
        try:
            c = con.execute(
                "SELECT * FROM conversations WHERE id = ?", (conversation_id,)
            ).fetchone()
            if c is None:
                return {}
            conversation = {
                "id": c["id"],
                "topic": c["topic"],
                "status": c["status"],
                "needs_input": self._needs_input(con, conversation_id),
                "created_at": c["created_at"],
                "last_activity": c["last_activity"],
                "linked_work": c["linked_work"],
                "root_count": c["root_count"],
            }
            msg_rows = con.execute(
                "SELECT * FROM messages WHERE conversation_id = ? "
                "ORDER BY created_at ASC, id ASC",
                (conversation_id,),
            ).fetchall()
            messages = [self._message_dict(m, con) for m in msg_rows]
            deliveries = [
                self._delivery_dict(d)
                for d in con.execute(
                    "SELECT d.* FROM deliveries d "
                    "JOIN messages m ON d.message_id = m.id "
                    "WHERE m.conversation_id = ? "
                    "ORDER BY d.message_id, d.recipient",
                    (conversation_id,),
                ).fetchall()
            ]
            obligations = [
                {
                    "message_id": o["message_id"],
                    "participant": o["participant"],
                    "kind": o["kind"],
                    "created_at": o["created_at"],
                    "cleared_at": o["cleared_at"],
                }
                for o in con.execute(
                    "SELECT * FROM obligations WHERE conversation_id = ? "
                    "ORDER BY created_at, message_id, participant",
                    (conversation_id,),
                ).fetchall()
            ]
        finally:
            con.close()
        return {
            "conversation": conversation,
            "messages": messages,
            "deliveries": deliveries,
            "obligations": obligations,
        }

    def get_message(self, message_id: str) -> Optional[dict]:
        """Return a single message's raw columns as a dict, or None.

        Unlike `_message_dict` (UI contract, `from` key, resolved body) this
        returns the stored columns verbatim — `from_id`, `conversation_id`,
        `reply_to`, `effective_subject`, etc. The reply rule relies on it.
        """
        con = self._connect()
        con.row_factory = sqlite3.Row
        try:
            r = con.execute(
                "SELECT * FROM messages WHERE id = ?", (message_id,)
            ).fetchone()
        finally:
            con.close()
        if r is None:
            return None
        return {k: r[k] for k in r.keys()}

    def conversation_participants(self, conversation_id: str) -> list:
        """Public wrapper: tracking ids that are senders ∪ delivery recipients
        across the conversation's messages, sorted."""
        con = self._connect()
        con.row_factory = sqlite3.Row
        try:
            return self._conversation_participants(con, conversation_id)
        finally:
            con.close()

    def view(
        self,
        box: str,
        entity_id: str,
        *,
        limit: Optional[int] = None,
        offset: int = 0,
    ) -> list:
        """Return messages for a mailbox view (inbox|sent|archive), newest
        first. Each row merges the message dict with the entity's delivery."""
        if box not in ("inbox", "sent", "archive"):
            raise ValueError(f"unknown box: {box!r}")
        con = self._connect()
        con.row_factory = sqlite3.Row
        try:
            rows = []
            if box == "sent":
                msgs = con.execute(
                    "SELECT * FROM messages WHERE from_id = ?", (entity_id,)
                ).fetchall()
                for m in msgs:
                    d = con.execute(
                        "SELECT * FROM deliveries "
                        "WHERE message_id = ? AND recipient = ?",
                        (m["id"], entity_id),
                    ).fetchone()
                    rows.append(self._view_row(m, d, entity_id, con))
            else:
                status_clause = (
                    "d.status = 'archived'"
                    if box == "archive"
                    else "d.status != 'archived'"
                )
                joined = con.execute(
                    "SELECT m.id AS mid FROM messages m "
                    "JOIN deliveries d ON d.message_id = m.id "
                    f"WHERE d.recipient = ? AND {status_clause}",
                    (entity_id,),
                ).fetchall()
                for j in joined:
                    m = con.execute(
                        "SELECT * FROM messages WHERE id = ?", (j["mid"],)
                    ).fetchone()
                    d = con.execute(
                        "SELECT * FROM deliveries "
                        "WHERE message_id = ? AND recipient = ?",
                        (j["mid"], entity_id),
                    ).fetchone()
                    rows.append(self._view_row(m, d, entity_id, con))
        finally:
            con.close()
        # Newest first by message created_at, tiebreak id desc.
        rows.sort(key=lambda r: (r["created_at"], r["id"]), reverse=True)
        if offset:
            rows = rows[offset:]
        if limit is not None:
            rows = rows[:limit]
        return rows

    def _view_row(self, m, d, entity_id: str, con: sqlite3.Connection) -> dict:
        """Merge a message dict with the entity's delivery dict (None-filled
        when the entity has no delivery, e.g. sent items)."""
        row = self._message_dict(m, con)
        if d is not None:
            delivery = self._delivery_dict(d)
        else:
            delivery = {
                "message_id": m["id"],
                "recipient": entity_id,
                "status": None,
                "delivered_at": None,
                "read_at": None,
                "error": None,
            }
        row.update(delivery)
        return row


# =============================================================================
# JSON CLI
# =============================================================================

def main(argv: Optional[list] = None) -> int:
    import argparse
    import json

    common = argparse.ArgumentParser(add_help=False)
    common.add_argument("--db", help="override comms.db path")
    common.add_argument("--json", action="store_true", help="emit JSON")

    parser = argparse.ArgumentParser(
        prog="comms_index.py",
        description="Read/query API for the comms index (UI contract).",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_conv = sub.add_parser("conversations", parents=[common])
    p_conv.add_argument("--status")
    p_conv.add_argument("--participant", action="append", dest="participants")
    p_conv.add_argument("--linked-work", dest="linked_work")
    p_conv.add_argument("--needs-input", action="store_true")
    p_conv.add_argument("--limit", type=int)
    p_conv.add_argument("--offset", type=int, default=0)
    p_conv.add_argument(
        "--order", choices=["last_activity", "created_at"],
        default="last_activity",
    )

    p_one = sub.add_parser("conversation", parents=[common])
    p_one.add_argument("id")

    p_view = sub.add_parser("view", parents=[common])
    p_view.add_argument("box", choices=["inbox", "sent", "archive"])
    p_view.add_argument("entity_id")
    p_view.add_argument("--limit", type=int)
    p_view.add_argument("--offset", type=int, default=0)

    args = parser.parse_args(argv)
    idx = CommsIndex(db_path=args.db) if args.db else CommsIndex()

    if args.cmd == "conversations":
        result = idx.list_conversations(
            status=args.status,
            participants=args.participants,
            linked_work=args.linked_work,
            needs_input=True if args.needs_input else None,
            limit=args.limit,
            offset=args.offset,
            order=args.order,
        )
    elif args.cmd == "conversation":
        result = idx.get_conversation(args.id)
    elif args.cmd == "view":
        result = idx.view(
            args.box, args.entity_id, limit=args.limit, offset=args.offset
        )
    else:  # pragma: no cover
        parser.error(f"unknown command {args.cmd!r}")

    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
