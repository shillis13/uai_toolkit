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


def _get_ai_root() -> Path:
    """Resolve AI_ROOT from env or default."""
    return Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))


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


def _collect_expired_yaml(directory: Path, now: datetime) -> List[Path]:
    """Recursively find YAML files with an expired expires_at field."""
    expired = []  # type: List[Path]
    if not directory.exists():
        return expired

    for filepath in directory.rglob("*.yml"):
        data = _read_yaml(filepath)
        expires_at = data.get("expires_at")
        if expires_at is None:
            continue
        try:
            exp_dt = datetime.fromisoformat(str(expires_at))
            if exp_dt <= now:
                expired.append(filepath)
        except (ValueError, TypeError):
            pass

    return expired


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

    # Sweep YAML directories with expires_at
    for label, directory in SWEEP_DIRS.items():
        expired = _collect_expired_yaml(directory, now)
        counts[label] = len(expired)
        total += len(expired)

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
