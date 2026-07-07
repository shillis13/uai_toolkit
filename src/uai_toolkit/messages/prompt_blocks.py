#!/usr/bin/env python3
"""prompt_blocks.py — manually block a session from receiving prompts from anyone
but the user (PianoMan), indefinitely / until a time / for N turns.

A *prompt block* is a richer cousin of the conversation lock: where a lock is
binary + advisory, a block carries a duration model and a sender-exemption, and
the live send paths consult it. The user's own keystrokes go straight into the
terminal and never touch this code, so they are exempt for free — only
*programmatic* prompts (sibling sessions, the idle-mail nudge, broadcasts,
scheduled prompts) pass through the send path and get gated.

Behaviour when a session is blocked and a non-exempt sender tries to prompt it:
  - the prompt is HELD, not dropped — queued under prompts_inbox/<tid>/ with
    ready_for_delivery=False (so the existing drain hooks skip it via
    filter_ready). On unblock / expiry, held entries flip ready and the next
    drain delivers them in order. (Same hold-and-deliver the busy-prompt-area
    case already uses.)
  - an `interrupt`-urgency prompt is STILL blocked (it does not punch through),
    but a user notification fires so PianoMan knows an urgent prompt is waiting.

Duration models (`mode`):
  - "indefinite" : until explicitly unblocked.
  - "until"      : auto-clears once `expires_at` passes (lazy, checked on read).
  - "turns"      : `turns_remaining` decremented once per completed turn of the
                   blocked session (Stop hook); auto-clears at 0.

State: one YAML file per blocked session at
  ai_general/data/locks/prompt_blocks/<tracking_id>.yml

This module is intentionally dependency-light (stdlib + optional pyyaml) so the
hooks, the footer builder, and messaging_mgr can all import it cheaply.
"""
from __future__ import annotations

import os
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import yaml  # type: ignore
    _HAVE_YAML = True
except Exception:  # pragma: no cover - fallback
    import json as _json
    _HAVE_YAML = False

AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI/ai_root"))
BLOCKS_DIR = AI_ROOT / "ai_general" / "data" / "locks" / "prompt_blocks"
PROMPTS_INBOX = AI_ROOT / "ai_comms" / "prompts_inbox"

DEFAULT_ALLOW_FROM = ("user",)
VALID_MODES = ("indefinite", "until", "turns")


# ── tiny YAML I/O (flat dicts) ──────────────────────────────────────────────
def _read(path: Path) -> Optional[Dict[str, Any]]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    if _HAVE_YAML:
        try:
            return yaml.safe_load(text) or {}
        except Exception:
            return None
    try:
        return _json.loads(text)
    except Exception:
        return None


def _write(path: Path, data: Dict[str, Any]) -> None:
    if _HAVE_YAML:
        text = yaml.safe_dump(data, default_flow_style=False, sort_keys=False)
    else:
        text = _json.dumps(data, indent=2)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _block_path(tid: str) -> Path:
    return BLOCKS_DIR / "{}.yml".format(tid)


def _ensure_dir() -> None:
    # Parent (ai_general/data/locks/) already exists (conversations/ lives there).
    if not BLOCKS_DIR.exists():
        BLOCKS_DIR.mkdir()


# ── core API ────────────────────────────────────────────────────────────────
def block(
    tid: str,
    *,
    mode: str = "indefinite",
    turns: Optional[int] = None,
    until: Optional[str] = None,
    blocked_by: str = "user",
    reason: Optional[str] = None,
    allow_from=DEFAULT_ALLOW_FROM,
) -> Dict[str, Any]:
    """Create/replace a prompt block for `tid`. Returns the stored record."""
    if mode not in VALID_MODES:
        raise ValueError("mode must be one of {}".format(VALID_MODES))
    if mode == "turns" and (turns is None or turns <= 0):
        raise ValueError("mode 'turns' requires turns > 0")
    if mode == "until" and not until:
        raise ValueError("mode 'until' requires an ISO 'until' timestamp")
    _ensure_dir()
    rec = {
        "tracking_id": tid,
        "mode": mode,
        "blocked_by": blocked_by,
        "reason": reason,
        "allow_from": list(allow_from),
        "created_at": datetime.now().isoformat(timespec="seconds"),
    }
    if mode == "turns":
        rec["turns_remaining"] = int(turns)
    if mode == "until":
        rec["expires_at"] = until
    _write(_block_path(tid), rec)
    return rec


def unblock(tid: str) -> Dict[str, Any]:
    """Lift a block and release any held prompts. Returns {ok, released}."""
    path = _block_path(tid)
    existed = path.exists()
    if existed:
        try:
            path.unlink()
        except OSError:
            pass
    released = flush_held(tid)
    return {"ok": existed, "released": released, "tracking_id": tid}


def get_block(tid: str) -> Optional[Dict[str, Any]]:
    """Return the live block record, or None. Lazily auto-clears an expired
    'until' block (and releases its held prompts). 'turns' reaching 0 is handled
    by decrement_turn, but a 0/negative value here is also treated as expired."""
    rec = _read(_block_path(tid))
    if not rec:
        return None
    mode = rec.get("mode")
    if mode == "until":
        exp = rec.get("expires_at")
        if exp and _passed(exp):
            unblock(tid)
            return None
    if mode == "turns" and int(rec.get("turns_remaining", 0)) <= 0:
        unblock(tid)
        return None
    return rec


def is_blocked(tid: str, sender: Optional[str] = None,
               urgency: Optional[str] = None) -> Dict[str, Any]:
    """Decision for the send paths. Returns:
        {blocked: bool, reason, mode, remaining, until, notify_user: bool}
    `blocked` is True only when a live block exists AND `sender` is not exempt
    (not in allow_from). `notify_user` is True when a blocked send was urgency
    'interrupt' (so the caller fires a user notification)."""
    rec = get_block(tid)
    if not rec:
        return {"blocked": False}
    allow = rec.get("allow_from") or list(DEFAULT_ALLOW_FROM)
    if sender is not None and sender in allow:
        return {"blocked": False, "exempt": True}
    return {
        "blocked": True,
        "mode": rec.get("mode"),
        "reason": rec.get("reason"),
        "remaining": rec.get("turns_remaining"),
        "until": rec.get("expires_at"),
        "notify_user": (urgency == "interrupt"),
    }


def decrement_turn(tid: str) -> Optional[Dict[str, Any]]:
    """Called once per completed turn of the blocked session (Stop hook). Only
    affects 'turns' mode. Clears + flushes when it hits 0. Returns the updated
    record, or None if there was no turns-block (or it just cleared)."""
    rec = _read(_block_path(tid))
    if not rec or rec.get("mode") != "turns":
        return None
    rec["turns_remaining"] = int(rec.get("turns_remaining", 0)) - 1
    if rec["turns_remaining"] <= 0:
        unblock(tid)
        return None
    _write(_block_path(tid), rec)
    return rec


def list_blocks() -> List[Dict[str, Any]]:
    """All live blocks (auto-clearing expired ones as a side effect)."""
    out: List[Dict[str, Any]] = []
    if not BLOCKS_DIR.exists():
        return out
    for p in sorted(BLOCKS_DIR.glob("*.yml")):
        tid = p.stem
        rec = get_block(tid)
        if rec:
            out.append(rec)
    return out


def indicator(tid: str) -> Optional[str]:
    """Short status-line string for a blocked session, or None.
    e.g. '🔒 blocked', '🔒 blocked·2t', '🔒 blocked·til 23:00'."""
    rec = get_block(tid)
    if not rec:
        return None
    mode = rec.get("mode")
    if mode == "turns":
        return "🔒 blocked·{}t".format(rec.get("turns_remaining"))
    if mode == "until":
        exp = rec.get("expires_at") or ""
        hhmm = exp[11:16] if len(exp) >= 16 else exp
        return "🔒 blocked·til {}".format(hhmm)
    return "🔒 blocked"


# ── held-prompt plumbing (hold-and-deliver-on-unblock) ──────────────────────
def hold_prompt_entry(tid: str) -> Dict[str, Any]:
    """Metadata stamped onto a queued prompt so it is HELD (skipped by the
    drain's filter_ready) until the block lifts. Callers merge this into the
    queue_prompt entry they write."""
    return {"ready_for_delivery": False, "held_by_block": True}


def hold_prompt(tid: str, content: str, *, source: Optional[str] = None,
                urgency: str = "prompt", ttl_seconds: int = 259200,
                message_id: Optional[str] = None) -> Dict[str, Any]:
    """Write a HELD prompt into prompts_inbox/<tid>/ — same schema queue_prompt
    uses, but ready_for_delivery=False + held_by_block=True so the drain hooks
    skip it until the block lifts (flush_held flips it). Returns {queue_id,file}."""
    from datetime import timedelta
    qdir = PROMPTS_INBOX / tid
    if not PROMPTS_INBOX.exists():
        PROMPTS_INBOX.mkdir(parents=True)
    if not qdir.exists():
        qdir.mkdir()
    now = datetime.now()
    qid = "queue_{}".format(now.strftime("%Y%m%d_%H%M%S_%f"))
    entry = {
        "id": qid,
        "message_id": message_id or qid.replace("queue_", "msg_"),
        "to": tid,
        "content": content,
        "urgency": urgency,
        "delivery": "pre-prompt",
        "ready_for_delivery": False,   # ← held; drain's filter_ready skips it
        "held_by_block": True,
        "queued_at": now.isoformat(),
        "ttl_seconds": ttl_seconds,
        "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        "source": source,
        "callback_endpoint": None,
    }
    path = qdir / "{}.yml".format(qid)
    _write(path, entry)
    return {"queue_id": qid, "file": str(path)}


def flush_held(tid: str) -> int:
    """Flip every block-held queue entry for `tid` to ready_for_delivery=True so
    the next drain delivers it. Returns the count released."""
    qdir = PROMPTS_INBOX / tid
    if not qdir.exists():
        return 0
    n = 0
    for p in sorted(qdir.glob("*.yml")):
        rec = _read(p)
        if rec and rec.get("held_by_block") and not rec.get("ready_for_delivery"):
            rec["ready_for_delivery"] = True
            _write(p, rec)
            n += 1
    return n


def _passed(iso_ts: str) -> bool:
    try:
        return datetime.now() >= datetime.fromisoformat(iso_ts)
    except Exception:
        return False


# ── CLI ──────────────────────────────────────────────────────────────────────
def _parse_until(s: str) -> str:
    """Accept an ISO timestamp, or a relative '+90m' / '+2h' / '+45' (minutes)."""
    s = s.strip()
    if s.startswith("+"):
        from datetime import timedelta
        body, unit = s[1:], "m"
        if body and body[-1] in "mhd":
            body, unit = body[:-1], body[-1]
        n = int(body)
        delta = {"m": timedelta(minutes=n), "h": timedelta(hours=n), "d": timedelta(days=n)}[unit]
        return (datetime.now() + delta).isoformat(timespec="seconds")
    return datetime.fromisoformat(s).isoformat(timespec="seconds")


def main(argv=None) -> int:
    import argparse
    import json as _j
    ap = argparse.ArgumentParser(
        description="Block a session from receiving prompts from anyone but the user.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pb_ = sub.add_parser("block", help="block a session's incoming prompts")
    pb_.add_argument("tid", help="target session tracking id ('self' = $AI_TRACKING_ID)")
    g = pb_.add_mutually_exclusive_group()
    g.add_argument("--turns", type=int, help="auto-lift after N completed turns")
    g.add_argument("--until", help="auto-lift at ISO time, or relative +90m/+2h/+1d")
    g.add_argument("--indefinite", action="store_true", help="until manually unblocked (default)")
    pb_.add_argument("--reason")
    pb_.add_argument("--allow", action="append", default=None,
                     help="extra exempt sender(s) beyond 'user' (repeatable)")

    pu = sub.add_parser("unblock", help="lift a block + release held prompts")
    pu.add_argument("tid", help="target session tracking id ('self')")

    sub.add_parser("list", help="list all live blocks")
    ps = sub.add_parser("status", help="show one session's block state")
    ps.add_argument("tid")

    a = ap.parse_args(argv)

    def _resolve(t):
        return os.environ.get("AI_TRACKING_ID", "") if t == "self" else t

    if a.cmd == "block":
        tid = _resolve(a.tid)
        if not tid:
            print(_j.dumps({"ok": False, "error": "no tracking id (self unset?)"})); return 1
        mode = "turns" if a.turns else "until" if a.until else "indefinite"
        allow = list(DEFAULT_ALLOW_FROM) + (a.allow or [])
        rec = block(tid, mode=mode, turns=a.turns,
                    until=_parse_until(a.until) if a.until else None,
                    reason=a.reason, allow_from=allow)
        print(_j.dumps({"ok": True, "blocked": rec, "indicator": indicator(tid)}, indent=2))
    elif a.cmd == "unblock":
        print(_j.dumps(unblock(_resolve(a.tid)), indent=2))
    elif a.cmd == "list":
        print(_j.dumps({"count": len(list_blocks()), "blocks": list_blocks()}, indent=2))
    elif a.cmd == "status":
        tid = _resolve(a.tid)
        print(_j.dumps({"tracking_id": tid, "block": get_block(tid),
                        "indicator": indicator(tid)}, indent=2))
    return 0


if __name__ == "__main__":
    import sys as _sys
    _sys.exit(main())
