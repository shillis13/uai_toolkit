#!/usr/bin/env python3
"""
sweep_expired.py — Remove expired messages and queue entries.

Sweeps:
  - ai_comms/messages/inbox/ (recursive) — YAML files with expires_at
  - ai_comms/prompts_inbox/ (recursive) — YAML files with expires_at
  - ai_general/data/standing_messages/ (recursive) — YAML files with expires_at
  - ai_general/data/hooks/data/prompt_queue/delivered/ — files older than 7 days (mtime)

Usage:
    sweep_expired.py [--dry-run]
"""

import argparse
import os
import sys
import time
import yaml
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Tuple

_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_ROOT  # noqa: E402


def _get_ai_root() -> Path:
    """Resolve AI_ROOT from env or default."""
    return AI_ROOT


AI_ROOT = _get_ai_root()

SWEEP_DIRS = {
    "messages/inbox": AI_ROOT / "ai_comms" / "messages" / "inbox",
    "prompts_inbox": AI_ROOT / "ai_comms" / "prompts_inbox",
    "standing_messages": AI_ROOT / "ai_general" / "data" / "standing_messages",
    "pending_replies": AI_ROOT / "ai_general" / "data" / "comms" / "pending_replies",
}

DELIVERED_DIR = AI_ROOT / "ai_general" / "data" / "hooks" / "data" / "prompt_queue" / "delivered"
DELIVERED_MAX_AGE_DAYS = 7


def _read_yaml(filepath: Path) -> dict:
    """Read a YAML file, returning empty dict on failure."""
    try:
        with open(filepath, "r") as f:
            data = yaml.safe_load(f)
            return data if isinstance(data, dict) else {}
    except (yaml.YAMLError, IOError):
        return {}


# Git Guardian change kinds — a request that mutates a repo. An expired one that was
# never acknowledged means work that may never have been committed, so it must be
# SURFACED, not silently deleted at the 3-day TTL (todo_0626). Advisories are exempt.
_GG_CHANGE_KINDS = {"commit_request", "sync_request", "recovery_request", "sweep_request"}
_GG_MARKER = "Git Guardian request:"


def _gg_request_kind(content: str) -> str:
    """Parse the embedded Git Guardian payload's `type` from a message/queue body,
    or '' if this isn't a Git Guardian request. Best-effort; never raises."""
    idx = content.find(_GG_MARKER)
    if idx == -1:
        return ""
    try:
        payload = yaml.safe_load(content[idx + len(_GG_MARKER):])
    except yaml.YAMLError:
        return ""
    return str(payload.get("type") or "") if isinstance(payload, dict) else ""


def _entry_content(data: dict) -> str:
    """Return full entry content, following messaging_mgr's body_file externalization.

    Git Guardian requests are usually large enough to be externalized; inspecting
    only the short wire placeholder would misclassify them as ordinary messages and
    TTL-delete the very requests Stage 1 promises to preserve.
    """
    content = str(data.get("content") or "")
    if _GG_MARKER in content:
        return content
    body_file = data.get("body_file")
    if body_file:
        try:
            return Path(str(body_file)).read_text()
        except OSError:
            pass
    return content


def _pending_request_message(data: dict) -> dict:
    """Find the request message referenced by a pending-reply entry.

    Pending entries carry the request id, not the request payload. Look in the
    live inbox first, then sender retention/archive, so expired Git Guardian
    obligations can be identified and preserved instead of being swept before
    recovery sees them.
    """
    msg_id = str(data.get("message_id") or data.get("responding_to_msg_id") or "")
    if not msg_id:
        return {}
    roots = [
        SWEEP_DIRS.get("messages/inbox"),
        _get_ai_root() / "ai_comms" / "messages" / "sent",
        _get_ai_root() / "ai_comms" / "messages" / "archive",
    ]
    filename = f"{msg_id}.yml"
    for root in roots:
        if not root or not root.exists():
            continue
        try:
            for path in root.rglob(filename):
                message = _read_yaml(path)
                if message:
                    return message
        except OSError:
            continue
    return {}


def _is_unacked_gg_request(data: dict) -> bool:
    """True iff this entry is a Git Guardian CHANGE request that was never acked —
    the class that must be preserved + surfaced instead of TTL-deleted (todo_0626).
    An acked request (committer positively acknowledged) sweeps normally."""
    if data.get("acknowledgments"):
        return False
    kind = _gg_request_kind(_entry_content(data))
    if not kind and data.get("response_required"):
        kind = _gg_request_kind(_entry_content(_pending_request_message(data)))
    return kind in _GG_CHANGE_KINDS


def _is_expired(expires_at: object, now: datetime) -> bool:
    """Compare naive local or timezone-aware ISO expiries without mixing them."""
    try:
        exp_dt = datetime.fromisoformat(str(expires_at))
        if exp_dt.tzinfo is None:
            cmp_now = now.astimezone().replace(tzinfo=None) if now.tzinfo else now
        else:
            cmp_now = now.astimezone(exp_dt.tzinfo)
        return exp_dt <= cmp_now
    except (ValueError, TypeError):
        return False


def _collect_expired_yaml(directory: Path, now: datetime,
                          preserve_gg: bool = False) -> Tuple[List[Path], List[Path]]:
    """Recursively find YAML files with an expired expires_at field.

    Returns (to_delete, preserved). When preserve_gg is set (the inbox/prompt dirs),
    an expired un-acked Git Guardian change request is diverted to `preserved` — it is
    NOT deleted, so uncommitted work is never silently swept (todo_0626)."""
    to_delete = []  # type: List[Path]
    preserved = []  # type: List[Path]
    if not directory.exists():
        return to_delete, preserved

    for filepath in directory.rglob("*.yml"):
        data = _read_yaml(filepath)
        expires_at = data.get("expires_at")
        if expires_at is None:
            continue
        if not _is_expired(expires_at, now):
            continue
        if preserve_gg and _is_unacked_gg_request(data):
            preserved.append(filepath)
        else:
            to_delete.append(filepath)

    return to_delete, preserved


def _collect_old_delivered(directory: Path, cutoff_time: float) -> List[Path]:
    """Find files in delivered/ older than cutoff_time (epoch seconds)."""
    old = []  # type: List[Path]
    if not directory.exists():
        return old

    for filepath in directory.iterdir():
        if filepath.is_file():
            try:
                if filepath.stat().st_mtime < cutoff_time:
                    old.append(filepath)
            except OSError:
                pass

    return old


def sweep(dry_run: bool = False) -> None:
    """Sweep expired entries and print summary."""
    now = datetime.now()
    cutoff_epoch = time.time() - (DELIVERED_MAX_AGE_DAYS * 86400)

    counts = {}  # type: dict[str, int]
    total = 0
    preserved_gg = []  # type: List[Tuple[str, Path, dict]]

    # Sweep YAML directories with expires_at. The two committer inbox dirs preserve
    # un-acked Git Guardian change requests instead of deleting them (todo_0626).
    for label, directory in SWEEP_DIRS.items():
        preserve = label in ("messages/inbox", "prompts_inbox", "pending_replies")
        expired, preserved = _collect_expired_yaml(directory, now, preserve_gg=preserve)
        counts[label] = len(expired)
        total += len(expired)
        for fp in preserved:
            preserved_gg.append((label, fp, _read_yaml(fp)))

        if not dry_run:
            for fp in expired:
                fp.unlink()

    # Sweep delivered queue (mtime-based)
    old_delivered = _collect_old_delivered(DELIVERED_DIR, cutoff_epoch)
    delivered_count = len(old_delivered)
    counts["delivered (>7d)"] = delivered_count
    total += delivered_count

    if not dry_run:
        for fp in old_delivered:
            fp.unlink()

    # Sweep expired temporary uri_mappings (recipient sets with a past expires_at)
    uri_swept = 0
    try:
        import subprocess as _sp
        ss = _get_ai_root() / "ai_general" / "scripts" / "session_mgmt" / "session_store.py"
        if dry_run:
            out = _sp.run(["python3", str(ss), "list-uri-mappings"],
                          capture_output=True, text=True, timeout=20).stdout
            import json as _json, sys as _sys
            _sys.path.insert(0, str(ss.parent))
            from uai_toolkit.session_mgmt.session_store import SessionStore  # type: ignore
            rows = _json.loads(out or "[]")
            uri_swept = sum(1 for r in rows if SessionStore._iso_is_past(r.get("expires_at")))
        else:
            out = _sp.run(["python3", str(ss), "prune-expired-uris"],
                          capture_output=True, text=True, timeout=20).stdout
            import json as _json
            uri_swept = _json.loads(out or "{}").get("deleted", 0)
    except Exception:
        pass
    counts["uri_mappings (expired)"] = uri_swept
    total += uri_swept

    # Print summary
    prefix = "[DRY RUN] " if dry_run else ""
    print("{}Swept expired entries:".format(prefix))
    print("  messages/inbox: {} expired".format(counts.get("messages/inbox", 0)))
    print("  prompts_inbox: {} expired".format(counts.get("prompts_inbox", 0)))
    print("  standing_messages: {} expired".format(counts.get("standing_messages", 0)))
    print("  pending_replies: {} expired".format(counts.get("pending_replies", 0)))
    print("  delivered (>7d): {} cleaned".format(counts.get("delivered (>7d)", 0)))
    print("  uri_mappings (expired): {} swept".format(counts.get("uri_mappings (expired)", 0)))
    print("Total: {} removed".format(total))

    # Surface (do NOT delete) any expired un-acked Git Guardian change requests. An
    # expired un-acked request means work that may never have been committed — the
    # exact silent-drop this guards against (todo_0626). Loud WARN so a UI/human can
    # scan for it; the files are left in place for recovery/re-route (Stage 3).
    if preserved_gg:
        print("", file=sys.stderr)
        print("WARNING: {} expired un-acked Git Guardian request(s) PRESERVED "
              "(not deleted) — possible uncommitted work:".format(len(preserved_gg)),
              file=sys.stderr)
        for label, fp, data in preserved_gg:
            kind = _gg_request_kind(_entry_content(data))
            if not kind and label == "pending_replies":
                kind = _gg_request_kind(_entry_content(_pending_request_message(data)))
            kind = kind or "gg_request"
            requester = data.get("from") or data.get("source") or "?"
            recipient = data.get("to") or "?"
            exp = data.get("expires_at") or "?"
            print("  - [{}] {} from {} → {} (expired {}) : {}".format(
                label, kind, requester, recipient, exp, fp), file=sys.stderr)

    # Orphan recovery piggyback (todo_0626 Stage 4a): re-route commit requests whose
    # committer went dark to a live Guardian, reusing THIS already-scheduled run
    # (Hamilton's steer — no new daemon / polling loop). Best-effort; never blocks the
    # sweep. In a dry-run sweep, recovery is dry-run too.
    _run_orphan_recovery(dry_run)


def _run_orphan_recovery(dry_run: bool) -> None:
    """Shell out to `git_guardian.py recover` (best-effort, time-bounded) and surface
    what it re-routed. Isolated so a recovery failure can never break the sweep."""
    try:
        import json as _json
        import subprocess as _sp
        gg = _get_ai_root() / "ai_general" / "scripts" / "git_guardian" / "git_guardian.py"
        if not gg.exists():
            return
        cmd = ["python3", str(gg), "recover", "--json"]
        if dry_run:
            cmd.append("--dry-run")
        out = _sp.run(cmd, capture_output=True, text=True, timeout=60)
        data = _json.loads(out.stdout or "{}")
        found = int(data.get("orphans_found") or 0)
        rerouted = data.get("rerouted") or []
        if found:
            verb = "would re-route" if dry_run else "re-routed"
            print("", file=sys.stderr)
            print("Git Guardian orphan recovery: {} orphan(s), {} {}.".format(
                found, len(rerouted), verb), file=sys.stderr)
            for r in rerouted:
                print("  {}: {} -> {}".format(verb, r.get("request"), r.get("to")),
                      file=sys.stderr)
            for item in data.get("skipped") or []:
                print("  skipped: {} ({})".format(
                    item.get("request"), item.get("reason")), file=sys.stderr)
        if out.returncode != 0 or data.get("ok") is False:
            detail = (out.stderr or "").strip() or "see skipped recovery entries above"
            print("WARNING: Git Guardian orphan recovery was incomplete: {}".format(
                detail), file=sys.stderr)
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="sweep_expired",
        description="Remove expired messages and queue entries.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report expired entries without deleting them",
    )
    args = parser.parse_args()

    sweep(dry_run=args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
