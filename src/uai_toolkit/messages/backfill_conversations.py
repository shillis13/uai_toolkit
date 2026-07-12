#!/usr/bin/env python3
"""backfill_conversations.py — non-destructive backfill of the comms index.

The SQLite index (`comms_index.CommsIndex`, file `comms.db`) is authoritative
for the v2 Conversations/Messaging model, but it is empty for all historical
data. This script reads the existing on-disk YAML messages and prompt-queue
entries and reconstructs conversations, messages, deliveries and obligations
*into the index only*. It NEVER modifies or deletes the YAML.

Design (spec §9 + §12.K):

  * READ-ONLY on the YAML tree; the only writes go to the index db.
  * REPLY-TREE ORDER: roots (no `replying_to`/`reply_to`) are inserted first,
    then replies are inserted breadth-first down the reply links so a parent
    row always precedes its replies (insert_message reads the parent's
    effective_subject from the db). Forward references — a reply scanned before
    its parent — are handled by building the tree before any insert.
  * CONVERSATION DERIVATION: a root mints a conversation (topic = its `subject`
    if present, else the first ~60 chars of `content`, else "(no subject)").
    A reply joins its parent's conversation.
  * CALLER-SUPPLIED conversation_id: if two or more UNLINKED roots carry the
    same caller-supplied `conversation_id` they are placed in ONE conversation
    with `root_count > 1` and a REPAIR WARNING is surfaced — unrelated threads
    are never silently merged.
  * DEDUP: the same message id appearing in both inbox and sent (hardlink) is
    collapsed by id. Near-identical messages with DIFFERENT ids are collapsed by
    a (normalized-content-hash, participants, created_at) signature.
  * DELIVERIES: the recipient is the inbox/archive dir owner the file was found
    under (plus the `to` field). Archived copies get status 'archived'.
  * PROMPTS: prompt-queue entries are folded in as messages with
    delivery='prompt' and a delivery row of status 'prompt'.
  * OBLIGATIONS: response_required (or a prompt) opens an obligation for the
    recipient. Obligations on historical data are APPROXIMATE — best effort.
  * IDEMPOTENT: a message already present in the index (by id) is skipped, so
    re-running creates no duplicates.
  * --dry-run reports the planned inserts and all repair warnings WITHOUT
    writing; a real run performs the inserts.

Terms:
  * root          — a message with no reply link (`replying_to`/`reply_to`).
  * reply link    — the `replying_to` field (legacy alias `reply_to`).
  * caller_cid    — a `conversation_id` value supplied in the YAML by whoever
                    sent the message (as opposed to the index-minted convo id).
  * dangling reply— a reply whose parent id is not present on disk.
"""

from __future__ import annotations

import hashlib
import os
import sqlite3
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT  # noqa: E402

import yaml

# Import CommsIndex whether run as a module or as a script.
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
from uai_toolkit.messages.comms_index import CommsIndex  # noqa: E402


TOPIC_PLACEHOLDER = "(no subject)"
TOPIC_LEN = 60


def _truthy_link(value) -> Optional[str]:
    """Normalize a reply-link / conversation-id value: None for null/empty."""
    if value is None:
        return None
    s = str(value).strip()
    return s or None


@dataclass
class MsgRecord:
    """One deduplicated logical message gathered from the YAML tree."""

    id: str
    data: dict
    reply_link: Optional[str] = None
    caller_cid: Optional[str] = None
    from_id: str = ""
    to_field: Optional[str] = None
    created_at: str = ""
    subject: Optional[str] = None
    content: str = ""
    response_required: bool = False
    delivery: str = "message"
    # recipient -> status (delivered | read | archived | prompt)
    recipients: Dict[str, str] = field(default_factory=dict)

    def topic(self) -> str:
        if self.subject:
            return self.subject
        body = (self.content or "").strip()
        if body:
            return body[:TOPIC_LEN]
        return TOPIC_PLACEHOLDER

    def signature(self) -> str:
        """Dedup signature for near-identical messages with differing ids."""
        norm = " ".join((self.content or "").split()).lower()
        h = hashlib.sha256(norm.encode("utf-8")).hexdigest()
        return f"{h}|{self.from_id}|{self.to_field}|{self.created_at}"


@dataclass
class Summary:
    conversations_created: int = 0
    messages_inserted: int = 0
    deliveries_inserted: int = 0
    obligations_opened: int = 0
    prompts_inserted: int = 0
    skipped_existing: int = 0
    duplicates_collapsed: int = 0
    warnings: List[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "conversations_created": self.conversations_created,
            "messages_inserted": self.messages_inserted,
            "deliveries_inserted": self.deliveries_inserted,
            "obligations_opened": self.obligations_opened,
            "prompts_inserted": self.prompts_inserted,
            "skipped_existing": self.skipped_existing,
            "duplicates_collapsed": self.duplicates_collapsed,
            "warnings": list(self.warnings),
        }


class Backfiller:
    """Reconstructs the index from the YAML tree. Read YAML, write index only."""

    # Inbox/archive sub-dirs that are not entity mailboxes.
    _NON_OWNER_DIRS = {"broadcasts"}

    def __init__(self, comms_root, index: CommsIndex):
        self.comms_root = Path(comms_root)
        self.idx = index
        self.records: Dict[str, MsgRecord] = {}
        self.prompts: List[MsgRecord] = []
        self._by_signature: Dict[str, str] = {}  # signature -> kept id
        self._dup_collapsed = 0

    # ------------------------------------------------------------------ #
    # Scanning
    # ------------------------------------------------------------------ #

    @staticmethod
    def _load_yaml(path: Path) -> Optional[dict]:
        try:
            with path.open() as f:
                data = yaml.safe_load(f)
        except (OSError, yaml.YAMLError):
            return None
        return data if isinstance(data, dict) else None

    def _ingest_message_file(self, path: Path, owner: str, status: str) -> None:
        data = self._load_yaml(path)
        if not data or not data.get("id"):
            return
        mid = str(data["id"])

        rec = self.records.get(mid)
        if rec is None:
            rec = MsgRecord(
                id=mid,
                data=data,
                reply_link=_truthy_link(data.get("replying_to"))
                or _truthy_link(data.get("reply_to")),
                caller_cid=_truthy_link(data.get("conversation_id")),
                from_id=str(data.get("from") or ""),
                to_field=_truthy_link(data.get("to")),
                created_at=str(data.get("created_at") or ""),
                subject=_truthy_link(data.get("subject")),
                content=str(data.get("content") or ""),
                response_required=bool(data.get("response_required")),
            )
            sig = rec.signature()
            kept = self._by_signature.get(sig)
            if kept is not None and kept != mid:
                # Near-identical message under a different id -> collapse onto
                # the already-kept record; fold this one's delivery in.
                self._add_recipient(self.records[kept], owner, status, data)
                self._dup_collapsed += 1
                return
            self._by_signature[sig] = mid
            self.records[mid] = rec

        # Record the read-state / delivery for the dir owner + the `to` field.
        self._add_recipient(rec, owner, status, data)

    def _add_recipient(self, rec: MsgRecord, owner: str, status: str,
                       data: dict) -> None:
        # Resolve the recipient: dir owner if it is a real mailbox, else `to`.
        recip = owner if owner not in self._NON_OWNER_DIRS else None
        candidates = []
        if recip:
            candidates.append((recip, status))
        to_field = _truthy_link(data.get("to"))
        if to_field:
            candidates.append((to_field, status))
        for r, st in candidates:
            self._merge_recipient(rec, r, st, data)

    @staticmethod
    def _merge_recipient(rec: MsgRecord, recipient: str, status: str,
                        data: dict) -> None:
        # 'read' if the recipient appears in read_by; 'archived' is terminal.
        read_by = {
            (e.get("by") if isinstance(e, dict) else e)
            for e in (data.get("read_by") or [])
        }
        effective = status
        if status == "delivered" and recipient in read_by:
            effective = "read"
        cur = rec.recipients.get(recipient)
        # archived wins over delivered/read; otherwise upgrade delivered->read.
        if cur == "archived":
            return
        if effective == "archived" or cur is None or (
            cur == "delivered" and effective == "read"
        ):
            rec.recipients[recipient] = effective

    def _ingest_prompt_file(self, path: Path, owner: str) -> None:
        data = self._load_yaml(path)
        if not data:
            return
        mid = str(data.get("message_id") or data.get("id") or "")
        if not mid:
            return
        rec = MsgRecord(
            id=mid,
            data=data,
            reply_link=None,
            caller_cid=_truthy_link(data.get("conversation_id")),
            from_id=str(data.get("source") or data.get("from") or ""),
            to_field=_truthy_link(data.get("to")) or owner,
            created_at=str(data.get("queued_at") or data.get("created_at") or ""),
            subject=None,
            content=str(data.get("content") or ""),
            response_required=True,  # a prompt asks for action
            delivery="prompt",
        )
        rec.recipients[owner] = "prompt"
        self.prompts.append(rec)

    def scan(self) -> None:
        msg_root = self.comms_root / "messages"
        for box, status in (("inbox", "delivered"),
                            ("sent", "sent"),
                            ("archive", "archived")):
            box_dir = msg_root / box
            if not box_dir.is_dir():
                continue
            for owner_dir in sorted(box_dir.iterdir()):
                if not owner_dir.is_dir():
                    continue
                owner = owner_dir.name
                for f in sorted(owner_dir.glob("*.yml")):
                    self._ingest_message_file(f, owner, status)

        prompts_root = self.comms_root / "prompts_inbox"
        if prompts_root.is_dir():
            for owner_dir in sorted(prompts_root.iterdir()):
                if not owner_dir.is_dir():
                    continue
                owner = owner_dir.name
                for f in sorted(owner_dir.glob("*.yml")):
                    self._ingest_prompt_file(f, owner)

    # ------------------------------------------------------------------ #
    # Planning / execution
    # ------------------------------------------------------------------ #

    def run(self, dry_run: bool = False) -> dict:
        self.scan()
        summary = Summary()
        summary.duplicates_collapsed = self._dup_collapsed

        # Build reply tree. A reply whose parent is absent on disk is a
        # "dangling reply" and is treated as a root for ordering.
        children: Dict[str, List[MsgRecord]] = defaultdict(list)
        roots: List[MsgRecord] = []
        for rec in self.records.values():
            parent = rec.reply_link
            if parent and parent in self.records:
                children[parent].append(rec)
            else:
                roots.append(rec)
        for kids in children.values():
            kids.sort(key=lambda r: (r.created_at, r.id))
        roots.sort(key=lambda r: (r.created_at, r.id))

        # caller_cid -> minted/real conversation id (for shared-cid grouping).
        cid_for_caller: Dict[str, str] = {}
        # msg id -> conversation id (so children can join their parent's convo).
        convo_of: Dict[str, str] = {}
        # Track a synthetic id for dry-run minted conversations.
        self._dry_seq = 0

        # ---- roots first ------------------------------------------------- #
        for rec in roots:
            existing = self.idx.get_message(rec.id)
            if existing is not None:
                convo_of[rec.id] = existing["conversation_id"]
                if rec.caller_cid:
                    cid_for_caller.setdefault(
                        rec.caller_cid, existing["conversation_id"])
                summary.skipped_existing += 1
                continue

            convo_id = None
            is_extra_root = False
            if rec.caller_cid and rec.caller_cid in cid_for_caller:
                # Two unlinked roots sharing a caller conversation_id.
                convo_id = cid_for_caller[rec.caller_cid]
                is_extra_root = True
                summary.warnings.append(
                    f"REPAIR: unlinked roots share conversation_id "
                    f"'{rec.caller_cid}' (e.g. message {rec.id}); merged into "
                    f"one conversation with root_count>1 — verify they belong "
                    f"to the same thread."
                )
            else:
                convo_id = self._mint_conversation(rec.topic(), dry_run)
                summary.conversations_created += 1
                if rec.caller_cid:
                    cid_for_caller[rec.caller_cid] = convo_id

            convo_of[rec.id] = convo_id
            self._insert_message(rec, convo_id, dry_run, summary)
            if is_extra_root:
                self._bump_root_count(convo_id, dry_run)

        # ---- replies breadth-first -------------------------------------- #
        queue = list(roots)
        while queue:
            parent = queue.pop(0)
            for child in children.get(parent.id, []):
                convo_id = convo_of.get(parent.id)
                if convo_id is None:
                    # Parent was skipped/missing; fall back to caller_cid or
                    # mint a fresh conversation for this dangling subtree.
                    convo_id = self._dangling_convo(
                        child, cid_for_caller, dry_run, summary)
                existing = self.idx.get_message(child.id)
                if existing is not None:
                    convo_of[child.id] = existing["conversation_id"]
                    summary.skipped_existing += 1
                else:
                    convo_of[child.id] = convo_id
                    self._insert_message(child, convo_id, dry_run, summary)
                queue.append(child)

        # ---- prompts ----------------------------------------------------- #
        # Guard against a prompt message_id that collides with a real message
        # (or another prompt): a second row on the same id would violate the
        # messages PK on a real run. Today there are no collisions; this keeps
        # the backfill crash-proof if future data has them.
        seen_ids = set(convo_of)
        for rec in self.prompts:
            if rec.id in seen_ids:
                summary.skipped_existing += 1
                continue
            existing = self.idx.get_message(rec.id)
            if existing is not None:
                summary.skipped_existing += 1
                continue
            seen_ids.add(rec.id)
            convo_id = self._mint_conversation(rec.topic(), dry_run)
            summary.conversations_created += 1
            self._insert_message(rec, convo_id, dry_run, summary)
            summary.prompts_inserted += 1

        return summary.as_dict()

    # ------------------------------------------------------------------ #
    # Index-write helpers (no-ops under dry_run)
    # ------------------------------------------------------------------ #

    def _mint_conversation(self, topic: str, dry_run: bool) -> str:
        if dry_run:
            self._dry_seq += 1
            return f"convo_dryrun_{self._dry_seq}"
        return self.idx.create_conversation(topic)

    def _insert_message(self, rec: MsgRecord, convo_id: str, dry_run: bool,
                       summary: Summary) -> None:
        summary.messages_inserted += 1
        if not dry_run:
            self.idx.insert_message({
                "id": rec.id,
                "conversation_id": convo_id,
                "reply_to": rec.reply_link,
                "subject": rec.subject,
                "from_id": rec.from_id,
                "to_entity": rec.to_field or "",
                "delivery": rec.delivery,
                "type": rec.data.get("type"),
                "urgency": rec.data.get("urgency"),
                "response_type": rec.data.get("response_type"),
                "ttl_seconds": rec.data.get("ttl_seconds"),
                "response_required": 1 if rec.response_required else 0,
                "created_at": rec.created_at,
                "body": rec.content,
            })

        # Deliveries.
        for recipient, status in sorted(rec.recipients.items()):
            summary.deliveries_inserted += 1
            if not dry_run:
                self.idx.insert_delivery(rec.id, recipient, status)

        # Obligation for the recipient(s) when a response is required.
        if rec.response_required:
            recips = set(rec.recipients) or (
                {rec.to_field} if rec.to_field else set())
            for recipient in sorted(r for r in recips if r):
                summary.obligations_opened += 1
                if not dry_run:
                    self.idx.open_obligation(convo_id, rec.id, recipient)

    def _bump_root_count(self, convo_id: str, dry_run: bool) -> None:
        if dry_run:
            return
        con = sqlite3.connect(str(self.idx.db_path))
        try:
            con.execute(
                "UPDATE conversations SET root_count = root_count + 1 "
                "WHERE id = ?",
                (convo_id,),
            )
            con.commit()
        finally:
            con.close()

    def _dangling_convo(self, rec: MsgRecord, cid_for_caller: Dict[str, str],
                       dry_run: bool, summary: Summary) -> str:
        if rec.caller_cid and rec.caller_cid in cid_for_caller:
            return cid_for_caller[rec.caller_cid]
        summary.warnings.append(
            f"REPAIR: reply {rec.id} references missing parent "
            f"'{rec.reply_link}'; started a new conversation for it."
        )
        convo_id = self._mint_conversation(rec.topic(), dry_run)
        summary.conversations_created += 1
        if rec.caller_cid:
            cid_for_caller[rec.caller_cid] = convo_id
        return convo_id


# ---------------------------------------------------------------------- #
# CLI
# ---------------------------------------------------------------------- #

def main(argv: Optional[list] = None) -> int:
    import argparse
    import json
    import os

    parser = argparse.ArgumentParser(
        prog="backfill_conversations.py",
        description="Non-destructively backfill the comms index from YAML.",
    )
    parser.add_argument("--db", help="override comms.db path")
    parser.add_argument(
        "--comms-root",
        help="override the ai_comms root (default: AI_ROOT/ai_comms)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="report planned inserts + repair warnings without writing",
    )
    parser.add_argument("--json", action="store_true", help="emit JSON")
    args = parser.parse_args(argv)

    idx = CommsIndex(db_path=args.db) if args.db else CommsIndex()
    if args.comms_root:
        comms_root = Path(args.comms_root)
    else:
        ai_root = AI_ROOT
        comms_root = ai_root / "ai_comms"

    bf = Backfiller(comms_root=comms_root, index=idx)
    summary = bf.run(dry_run=args.dry_run)

    if args.json:
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    else:
        mode = "DRY-RUN (no writes)" if args.dry_run else "WROTE TO INDEX"
        print(f"[backfill] {mode}  comms_root={comms_root}")
        print(f"  conversations_created : {summary['conversations_created']}")
        print(f"  messages_inserted     : {summary['messages_inserted']}")
        print(f"  deliveries_inserted   : {summary['deliveries_inserted']}")
        print(f"  obligations_opened    : {summary['obligations_opened']}")
        print(f"  prompts_inserted      : {summary['prompts_inserted']}")
        print(f"  skipped_existing      : {summary['skipped_existing']}")
        print(f"  duplicates_collapsed  : {summary['duplicates_collapsed']}")
        print(f"  warnings ({len(summary['warnings'])}):")
        for w in summary["warnings"]:
            print(f"    - {w}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
