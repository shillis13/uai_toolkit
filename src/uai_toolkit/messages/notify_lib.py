"""Shared notification layer for AI-comms delivery.

ONE `notify_recipient()` that every send path (v2 send_message, legacy send_direct
/ reply / reply-all, and broadcast_mgr) calls AFTER a message is durable. It owns
the nudge decision so batching/throttle is a property of the delivery pipe, not of
each producer.

Design (per spec work/notes/batched_notification_endpoints.md + Codex review):
  - The inbox-ref is ALWAYS staged first (even for an idle recipient) so a message
    is never lost, regardless of the nudge outcome. (Fixes the idle-path gap.)
  - Prompt-block safety: a blocked recipient is never nudged -> mode='blocked'.
  - policy='immediate' : nudge if idle (today's behavior).
  - policy='batched'   : nudge at most once per (recipient, policy) per window W,
    gated by an ATOMIC SQLite lease (BEGIN IMMEDIATE) so concurrent senders can't
    all fire — exactly one wins the lease. Leading-edge; later messages in the
    window ride the always-staged inbox-ref (read on the recipient's next turn).
    (Trailing/dirty flush is a documented follow-up; batched is intentionally
    slightly lower-reachability than immediate — never lossy, since the ref is staged.)
  - policy='silent'    : stage the ref, never nudge.

Result modes: nudge_sent | batched_suppressed | inbox_ref_staged | blocked |
              silent | nudge_failed_ref_staged | error
"""
from __future__ import annotations

import os
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, Optional


def _ai_root() -> Path:
    env = os.environ.get("AI_ROOT")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[3]


COMMS_DB = _ai_root() / "ai_general" / "data" / "comms.db"
_LEASE_TTL_SEC = 30          # a granted-but-unfinished nudge lease expires after this
_DEFAULT_WINDOW_SEC = 10     # W: at most one batched nudge per recipient per window

VALID_POLICIES = ("immediate", "batched", "silent")


def _window() -> int:
    try:
        return int(os.environ.get("AI_COMMS_BATCH_NUDGE_WINDOW_SEC", _DEFAULT_WINDOW_SEC))
    except (TypeError, ValueError):
        return _DEFAULT_WINDOW_SEC


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(str(COMMS_DB), timeout=10)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS notification_state ("
        " recipient TEXT NOT NULL, policy TEXT NOT NULL,"
        " last_attempt REAL, last_success REAL, in_flight_until REAL,"
        " PRIMARY KEY (recipient, policy))")
    return conn


def _acquire_nudge_lease(recipient_tid: str, policy: str) -> bool:
    """Atomically decide whether THIS caller may nudge now. Returns True to exactly
    one concurrent caller per window; others get False (suppressed). Uses a
    BEGIN IMMEDIATE write lock so simultaneous senders serialize — the core of the
    anti-flood guarantee."""
    W = _window()
    now = time.time()
    conn = _connect()
    try:
        conn.isolation_level = None  # manual transaction control
        conn.execute("BEGIN IMMEDIATE")
        row = conn.execute(
            "SELECT last_success, in_flight_until FROM notification_state"
            " WHERE recipient=? AND policy=?", (recipient_tid, policy)).fetchone()
        last_success = (row[0] if row and row[0] else 0.0)
        in_flight = (row[1] if row and row[1] else 0.0)
        if now < in_flight or (now - last_success) < W:
            conn.execute("COMMIT")
            return False  # another sender is mid-nudge, or we nudged within W
        conn.execute(
            "INSERT INTO notification_state (recipient, policy, last_attempt, in_flight_until)"
            " VALUES (?,?,?,?)"
            " ON CONFLICT(recipient, policy) DO UPDATE SET last_attempt=?, in_flight_until=?",
            (recipient_tid, policy, now, now + _LEASE_TTL_SEC, now, now + _LEASE_TTL_SEC))
        conn.execute("COMMIT")
        return True
    except sqlite3.OperationalError:
        # Could not get the write lock in time — treat as suppressed (someone else
        # holds it); the message is still discoverable via the staged inbox-ref.
        return False
    finally:
        conn.close()


def _record_nudge_result(recipient_tid: str, policy: str, ok: bool) -> None:
    """Close the lease: on success stamp last_success (starts the window); on
    failure clear in_flight so the next sender may retry."""
    now = time.time()
    conn = _connect()
    try:
        conn.execute(
            "UPDATE notification_state SET last_success=?, in_flight_until=0"
            " WHERE recipient=? AND policy=?",
            ((now if ok else 0.0), recipient_tid, policy))
        conn.commit()
    finally:
        conn.close()


def notify_recipient(recipient_tid: str, from_label: str, preview: str,
                     policy: str = "immediate", urgency: Optional[str] = None,
                     sender: Optional[str] = None) -> Dict[str, Any]:
    """Notify one recipient of already-durable mail. See module docstring for modes."""
    if policy not in VALID_POLICIES:
        policy = "immediate"
    from uai_toolkit.messages import messaging_mgr as mm  # lazy: avoids import-time circularity

    store = mm._load_store()
    sess = store.resolve(recipient_tid) if store else None
    if not sess:
        return {"mode": "error", "delivered": False, "reason": "recipient session not found"}

    # 1. ALWAYS stage the idempotent inbox-ref first — never lose a message.
    ref_ok = mm._stage_inbox_ref(sess.get("session_dir"), recipient_tid)

    # 2. Prompt-block gate: a blocked recipient is never nudged. A blocked
    #    interrupt still notifies the user so an urgent one isn't lost.
    blk = mm._prompt_block_check(recipient_tid, sender, urgency)
    if blk.get("blocked"):
        if blk.get("notify_user"):
            try:
                mm._notify_user_blocked_interrupt(recipient_tid, sender or from_label, preview, blk)
            except Exception:
                pass
        return {"mode": "blocked", "delivered": ref_ok, "reason": blk.get("reason")}

    # 3. Silent policy: ref staged, no nudge.
    if policy == "silent":
        return {"mode": "silent", "delivered": ref_ok}

    # 4. Batched: at most one nudge per (recipient, policy) per window.
    if policy == "batched" and not _acquire_nudge_lease(recipient_tid, policy):
        return {"mode": "batched_suppressed", "delivered": ref_ok}

    # 5. Nudge only a verifiably-idle recipient; a busy one already has the ref.
    terminal = sess.get("terminal_session")
    platform = sess.get("platform", "")
    target = mm._PLATFORM_TARGET.get(platform)
    if terminal and not mm._recipient_is_busy(target, terminal):
        ok = mm._send_nudge(platform, terminal, from_label, preview)
        if policy == "batched":
            _record_nudge_result(recipient_tid, policy, ok)
        return {"mode": ("nudge_sent" if ok else "nudge_failed_ref_staged"),
                "delivered": ref_ok}

    # Busy recipient: the staged ref is the signal.
    if policy == "batched":
        _record_nudge_result(recipient_tid, policy, True)  # ref-staged counts as notified for the window
    return {"mode": "inbox_ref_staged", "delivered": ref_ok, "reason": "recipient busy/occupied"}
