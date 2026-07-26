#!/usr/bin/env python3
"""
schedule_prompt.py — Schedule prompts via crontab (periodic) or at (one-shot).

Thin wrapper: creates crontab/at entries that call send_prompt.py.
No daemon, no polling, no lock files.

Usage:
  schedule_prompt.py create <id> --target <t> --message <m> --every <interval>
  schedule_prompt.py create <id> --target <t> --message <m> --at <datetime>
  schedule_prompt.py create <id> --target <t> --message <m> --delay <seconds>
  schedule_prompt.py list [--json]
  schedule_prompt.py cancel <id>
  schedule_prompt.py cancel --at-job <job_id>
  schedule_prompt.py cancel --all
  schedule_prompt.py prune
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_ROOT, AI_SCRIPTS  # noqa: E402

sys.path.insert(0, str(AI_SCRIPTS))
from uai_toolkit.common_utils.standard_colors import c, error as sc_error, warn, success, info, dim, bold, heading

SEND_PROMPT = Path(__file__).resolve().parent / "send_prompt.py"
MARKER = "# schedule_prompt:"
LOG_DIR = AI_ROOT / "ai_general" / "logs" / "scheduled_prompts"
SCHEDULE_FILE = AI_ROOT / "ai_general" / "data" / "scheduled_prompts" / "scheduled_prompts.json"
MAX_DELAY_SECONDS = 86400  # 24 hours


# ---------------------------------------------------------------------------
# JSON store for one-shot (at) jobs
# ---------------------------------------------------------------------------

def load_schedule() -> list[dict]:
    """Load scheduled prompts from persistent JSON store."""
    if not SCHEDULE_FILE.exists():
        return []
    try:
        with open(SCHEDULE_FILE) as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return []


def save_schedule(entries: list[dict]) -> None:
    """Save scheduled prompts to persistent JSON store."""
    SCHEDULE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SCHEDULE_FILE, "w") as f:
        json.dump(entries, f, indent=2, default=str)


def prune_schedule() -> list[dict]:
    """Remove entries whose at jobs no longer exist in atq."""
    entries = load_schedule()
    if not entries:
        return entries
    try:
        result = subprocess.run(["atq"], capture_output=True, text=True, timeout=5)
        active_ids = set()
        for line in result.stdout.strip().split("\n"):
            if line.strip():
                active_ids.add(line.split()[0])
    except Exception:
        return entries  # Can't check, keep all

    pruned = [e for e in entries if str(e.get("at_job_id")) in active_ids]
    if len(pruned) != len(entries):
        save_schedule(pruned)
    return pruned


# ---------------------------------------------------------------------------
# Crontab helpers
# ---------------------------------------------------------------------------

def read_crontab() -> list[str]:
    """Read current crontab lines."""
    result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return result.stdout.splitlines()


def write_crontab(lines: list[str]) -> None:
    """Write lines as the new crontab."""
    content = "\n".join(lines) + "\n"
    subprocess.run(["crontab", "-"], input=content, text=True, check=True)


def find_cron_entries(lines: list[str], schedule_id: str | None = None) -> list[tuple[int, int]]:
    """Find (marker_line_idx, command_line_idx) pairs for scheduled prompts.

    If schedule_id is given, only return matches for that ID.
    """
    entries = []
    for i, line in enumerate(lines):
        if line.startswith(MARKER):
            tag_id = line[len(MARKER):].strip()
            if schedule_id is None or tag_id == schedule_id:
                if i + 1 < len(lines):
                    entries.append((i, i + 1))
    return entries


# ---------------------------------------------------------------------------
# Interval parsing
# ---------------------------------------------------------------------------

INTERVAL_RE = re.compile(r"^(\d+)\s*(m|min|h|hr|d|s|sec)$", re.IGNORECASE)


def interval_to_cron(spec: str) -> str:
    """Convert human interval like '10m', '2h', '1d' to cron expression."""
    m = INTERVAL_RE.match(spec.strip())
    if not m:
        raise ValueError(f"Invalid interval: {spec!r}  (expected e.g. 10m, 2h, 1d)")
    value, unit = int(m.group(1)), m.group(2).lower()[0]

    if unit == "m":
        if value < 1 or value > 59:
            raise ValueError(f"Minute interval must be 1-59, got {value}")
        return f"*/{value} * * * *"
    elif unit == "h":
        if value < 1 or value > 23:
            raise ValueError(f"Hour interval must be 1-23, got {value}")
        return f"0 */{value} * * *"
    elif unit == "d":
        return f"0 0 */{value} * *"
    raise ValueError(f"Unknown unit: {unit}")


def parse_at_time(spec: str) -> datetime:
    """Parse an absolute datetime or relative offset for one-shot scheduling."""
    spec = spec.strip()

    # Relative: +30m, +2h, +90s
    rel_match = re.match(r"^\+(\d+)\s*(m|min|h|hr|d|s|sec)$", spec, re.IGNORECASE)
    if rel_match:
        value, unit = int(rel_match.group(1)), rel_match.group(2).lower()[0]
        delta = {"m": timedelta(minutes=value),
                 "h": timedelta(hours=value),
                 "d": timedelta(days=value),
                 "s": timedelta(seconds=value)}[unit]
        return datetime.now() + delta

    # ISO datetime: 2026-04-05T09:00:00
    try:
        return datetime.fromisoformat(spec)
    except ValueError:
        pass

    # Absolute: various formats
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%H:%M:%S", "%H:%M"):
        try:
            dt = datetime.strptime(spec, fmt)
            if dt.year == 1900:
                # Time-only: use today (or tomorrow if already passed)
                now = datetime.now()
                dt = dt.replace(year=now.year, month=now.month, day=now.day)
                if dt <= now:
                    dt += timedelta(days=1)
            return dt
        except ValueError:
            continue

    raise ValueError(f"Cannot parse datetime: {spec!r}")


# ---------------------------------------------------------------------------
# Build send_prompt.py command
# ---------------------------------------------------------------------------

def build_send_cmd(target: str, message: str, convo_id: str | None = None,
                   session: str | None = None) -> str:
    """Build the send_prompt.py command string."""
    parts = [str(SEND_PROMPT), "--target", target, "--message", message, "--submit"]
    if convo_id:
        parts.extend(["--convo_id", convo_id])
    if session:
        parts.extend(["--session", session])
    return " ".join(shlex.quote(p) for p in parts)


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_create(args: argparse.Namespace) -> int:
    """Create a scheduled prompt."""
    schedule_id = args.id

    send_cmd = build_send_cmd(args.target, args.message, args.convo_id, args.session)

    # Ensure log dir
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = LOG_DIR / f"{schedule_id}.log"

    if args.every:
        # --- Periodic via crontab ---
        # Check for duplicate in crontab
        lines = read_crontab()
        if find_cron_entries(lines, schedule_id):
            msg = f"Schedule '{schedule_id}' already exists in crontab. Cancel it first."
            if args.json:
                print(json.dumps({"error": msg}))
            else:
                sc_error(msg)
            return 1

        cron_expr = interval_to_cron(args.every)
        cron_line = f"{cron_expr}  {send_cmd} >> {shlex.quote(str(log_file))} 2>&1"

        lines.append(f"{MARKER}{schedule_id}")
        lines.append(cron_line)
        write_crontab(lines)

        result = {
            "success": True,
            "type": "periodic",
            "tag": schedule_id,
            "cron": cron_expr,
            "target": args.target,
            "session": args.session,
            "log": str(log_file),
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"{c('Created', 'success')} periodic schedule {c(repr(schedule_id), 'value')}")
            print(f"  {c('Cron:', 'label')}    {cron_expr}")
            print(f"  {c('Target:', 'label')}  {args.target}")
            if args.session:
                print(f"  {c('Session:', 'label')} {args.session}")
            print(f"  {c('Log:', 'label')}     {log_file}")

    elif args.at or args.delay:
        # --- One-shot via 'at' ---
        # Resolve fire time
        if args.delay:
            delay = int(args.delay)
            if delay < 1 or delay > MAX_DELAY_SECONDS:
                msg = f"delay must be 1-{MAX_DELAY_SECONDS} seconds"
                if args.json:
                    print(json.dumps({"error": msg}))
                else:
                    sc_error(msg)
                return 1
            fire_time = datetime.now() + timedelta(seconds=delay)
        else:
            fire_time = parse_at_time(args.at)

        # Validate not in the past
        if fire_time <= datetime.now():
            msg = "Scheduled time must be in the future"
            if args.json:
                print(json.dumps({"error": msg}))
            else:
                sc_error(msg)
            return 1

        # Validate within max delay
        if (fire_time - datetime.now()).total_seconds() > MAX_DELAY_SECONDS:
            msg = f"Scheduled time must be within {MAX_DELAY_SECONDS}s ({MAX_DELAY_SECONDS // 3600}h)"
            if args.json:
                print(json.dumps({"error": msg}))
            else:
                sc_error(msg)
            return 1

        # Check for duplicate tag in JSON store
        existing = load_schedule()
        for entry in existing:
            if entry.get("tag") == schedule_id:
                msg = f"Tag '{schedule_id}' already in use. Cancel it first or choose a different tag."
                if args.json:
                    print(json.dumps({"error": msg}))
                else:
                    sc_error(msg)
                return 1

        # Submit to 'at'
        full_cmd = f"{send_cmd} >> {shlex.quote(str(log_file))} 2>&1"
        at_result = subprocess.run(
            ["at", "-t", fire_time.strftime("%Y%m%d%H%M.%S")],
            input=full_cmd + "\n",
            text=True,
            capture_output=True,
        )
        if at_result.returncode != 0:
            stderr = at_result.stderr.strip()
            if "atrun" in stderr or "not loaded" in stderr:
                msg = "'at' daemon not enabled. Enable with: sudo launchctl load -w /System/Library/LaunchDaemons/com.apple.atrun.plist"
            else:
                msg = f"at command failed: {stderr}"
            if args.json:
                print(json.dumps({"error": msg}))
            else:
                sc_error(msg)
            return 1

        # Extract job number from stderr (at outputs "job N at ...")
        job_match = re.search(r"job\s+(\d+)", at_result.stderr)
        job_num = job_match.group(1) if job_match else None

        if job_num is None:
            msg = f"Failed to parse at job ID from: {at_result.stderr.strip()}"
            if args.json:
                print(json.dumps({"error": msg}))
            else:
                sc_error(msg)
            return 1

        # Persist to JSON store
        message_preview = args.message[:100] + "..." if len(args.message) > 100 else args.message
        entry = {
            "at_job_id": job_num,
            "tag": schedule_id,
            "target": args.target,
            "session": args.session,
            "message_preview": message_preview,
            "scheduled_for": fire_time.isoformat(),
            "created_at": datetime.now().isoformat(),
        }
        existing.append(entry)
        save_schedule(existing)

        result = {
            "success": True,
            "type": "one-shot",
            "at_job_id": job_num,
            "tag": schedule_id,
            "target": args.target,
            "session": args.session,
            "scheduled_for": fire_time.isoformat(),
            "message_preview": message_preview,
        }
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(f"{c('Created', 'success')} one-shot schedule {c(repr(schedule_id), 'value')}")
            print(f"  {c('Fires:', 'label')}   {fire_time.strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"  {c('At job:', 'label')}  #{job_num}")
            print(f"  {c('Target:', 'label')}  {args.target}")
            if args.session:
                print(f"  {c('Session:', 'label')} {args.session}")
            print(f"  {c('Log:', 'label')}     {log_file}")

    else:
        msg = "Specify --every <interval>, --at <datetime>, or --delay <seconds>"
        if args.json:
            print(json.dumps({"error": msg}))
        else:
            sc_error(msg)
        return 1

    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """List scheduled prompts (both periodic crontab and one-shot at)."""
    now = datetime.now()

    # --- Periodic entries from crontab ---
    cron_lines = read_crontab()
    cron_entries_idx = find_cron_entries(cron_lines)
    periodic_entries = []
    for marker_idx, cmd_idx in cron_entries_idx:
        tag_id = cron_lines[marker_idx][len(MARKER):].strip()
        cmd_line = cron_lines[cmd_idx]

        # Extract cron schedule (first 5 fields)
        parts = cmd_line.split()
        cron = " ".join(parts[:5])

        # Extract target and message
        target_match = (re.search(r"--target\s+'([^']+)'", cmd_line)
                        or re.search(r"--target\s+(\S+)", cmd_line))
        msg_match = (re.search(r"--message\s+'([^']*(?:''[^']*)*)'", cmd_line)
                     or re.search(r'--message\s+"([^"]*)"', cmd_line))
        session_match = (re.search(r"--session\s+'([^']+)'", cmd_line)
                         or re.search(r"--session\s+(\S+)", cmd_line))

        target = target_match.group(1) if target_match else "?"
        message = msg_match.group(1).replace("''", "'") if msg_match else "?"
        session = session_match.group(1) if session_match else None

        periodic_entries.append({
            "type": "periodic",
            "tag": tag_id,
            "cron": cron,
            "target": target,
            "session": session,
            "message_preview": message[:100] + "..." if len(message) > 100 else message,
        })

    # --- One-shot entries from JSON store (pruned) ---
    at_entries = prune_schedule()
    oneshot_entries = []
    for entry in at_entries:
        scheduled = datetime.fromisoformat(entry["scheduled_for"])
        remaining = (scheduled - now).total_seconds()
        oneshot_entries.append({
            "type": "one-shot",
            "at_job_id": entry.get("at_job_id"),
            "tag": entry.get("tag"),
            "target": entry.get("target"),
            "session": entry.get("session"),
            "message_preview": entry.get("message_preview", ""),
            "scheduled_for": entry.get("scheduled_for"),
            "created_at": entry.get("created_at"),
            "remaining_seconds": max(0, int(remaining)),
            "remaining_human": f"{int(remaining // 60)}m {int(remaining % 60)}s" if remaining > 0 else "imminent",
        })

    all_entries = periodic_entries + oneshot_entries

    if args.json:
        print(json.dumps({
            "periodic": periodic_entries,
            "one_shot": oneshot_entries,
            "count_periodic": len(periodic_entries),
            "count_one_shot": len(oneshot_entries),
            "count": len(all_entries),
        }, indent=2))
        return 0

    # Human-readable output
    if not all_entries:
        print(dim("No scheduled prompts."))
        return 0

    if periodic_entries:
        print(c(f"{'Tag':<25} {'Schedule':<20} {'Target':<18} {'Message'}", "heading"))
        print(c("-" * 90, "dim"))
        for e in periodic_entries:
            msg = e["message_preview"]
            if len(msg) > 40:
                msg = msg[:37] + "..."
            print(f"{c(e['tag'], 'value'):<25} {c(e['cron'], 'cyan'):<20} {e['target']:<18} {dim(msg)}")

    if oneshot_entries:
        if periodic_entries:
            print()
        print(c(f"{'Tag':<25} {'At Job':<8} {'Remaining':<12} {'Target':<18} {'Message'}", "heading"))
        print(c("-" * 90, "dim"))
        for e in oneshot_entries:
            tag = e["tag"] or "-"
            job = f"#{e['at_job_id']}" if e["at_job_id"] else "?"
            msg = e["message_preview"]
            if len(msg) > 35:
                msg = msg[:32] + "..."
            print(f"{c(tag, 'value'):<25} {c(job, 'cyan'):<8} {e['remaining_human']:<12} {e['target']:<18} {dim(msg)}")

    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    """Cancel a scheduled prompt by tag, at-job ID, or all."""
    cancelled = []

    if args.all:
        # Cancel all crontab entries
        lines = read_crontab()
        entries = find_cron_entries(lines)
        for marker_idx, cmd_idx in reversed(entries):
            tag_id = lines[marker_idx][len(MARKER):].strip()
            del lines[cmd_idx]
            del lines[marker_idx]
            cancelled.append({"type": "periodic", "tag": tag_id})
        if entries:
            write_crontab(lines)

        # Cancel all at entries
        at_entries = load_schedule()
        for entry in at_entries:
            try:
                subprocess.run(["atrm", str(entry["at_job_id"])],
                               capture_output=True, text=True, timeout=5)
            except Exception:
                pass
            cancelled.append({"type": "one-shot", "tag": entry.get("tag"),
                              "at_job_id": entry.get("at_job_id")})
        if at_entries:
            save_schedule([])

        if args.json:
            print(json.dumps({"success": True, "cancelled": cancelled,
                              "count": len(cancelled)}))
        elif not cancelled:
            print(dim("No scheduled prompts to cancel."))
        else:
            for entry in cancelled:
                print(f"  {c('Cancelled:', 'success')} {entry.get('tag', entry.get('at_job_id', '?'))}")
        return 0

    # Cancel by at-job ID
    if args.at_job:
        at_entries = load_schedule()
        to_cancel = None
        for entry in at_entries:
            if str(entry.get("at_job_id")) == str(args.at_job):
                to_cancel = entry
                break
        if not to_cancel:
            msg = f"No scheduled prompt found for at_job_id='{args.at_job}'"
            if args.json:
                print(json.dumps({"error": msg}))
            else:
                sc_error(msg)
            return 1

        try:
            subprocess.run(["atrm", str(to_cancel["at_job_id"])],
                           capture_output=True, text=True, timeout=5)
        except Exception:
            pass
        at_entries = [e for e in at_entries if e is not to_cancel]
        save_schedule(at_entries)

        if args.json:
            print(json.dumps({"success": True, "cancelled": to_cancel}))
        else:
            print(f"{c('Cancelled', 'success')} at job {c('#' + str(to_cancel['at_job_id']), 'value')} (tag: {to_cancel.get('tag', '-')})")
        return 0

    # Cancel by tag/id
    schedule_id = args.id
    if not schedule_id:
        msg = "Specify a schedule ID, --at-job <id>, or --all"
        if args.json:
            print(json.dumps({"error": msg}))
        else:
            sc_error(msg)
        return 1

    found = False

    # Check crontab
    lines = read_crontab()
    cron_entries = find_cron_entries(lines, schedule_id)
    if cron_entries:
        for marker_idx, cmd_idx in reversed(cron_entries):
            del lines[cmd_idx]
            del lines[marker_idx]
        write_crontab(lines)
        cancelled.append({"type": "periodic", "tag": schedule_id})
        found = True

    # Check JSON store
    at_entries = load_schedule()
    to_cancel = None
    for entry in at_entries:
        if entry.get("tag") == schedule_id:
            to_cancel = entry
            break
    if to_cancel:
        try:
            subprocess.run(["atrm", str(to_cancel["at_job_id"])],
                           capture_output=True, text=True, timeout=5)
        except Exception:
            pass
        at_entries = [e for e in at_entries if e is not to_cancel]
        save_schedule(at_entries)
        cancelled.append({"type": "one-shot", "tag": schedule_id,
                          "at_job_id": to_cancel.get("at_job_id")})
        found = True

    if not found:
        msg = f"Schedule '{schedule_id}' not found"
        if args.json:
            print(json.dumps({"error": msg}))
        else:
            sc_error(msg)
        return 1

    if args.json:
        print(json.dumps({"success": True, "cancelled": cancelled}))
    else:
        print(f"{c('Cancelled', 'success')} schedule {c(repr(schedule_id), 'value')}")
    return 0


def cmd_prune(args: argparse.Namespace) -> int:
    """Remove expired at-job entries from JSON store."""
    before = load_schedule()
    after = prune_schedule()
    removed = len(before) - len(after)
    if args.json:
        print(json.dumps({"pruned": removed, "remaining": len(after)}))
    else:
        print(f"Pruned {c(str(removed), 'value')} expired entries, {c(str(len(after)), 'value')} remaining")
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Schedule prompts via crontab/at — thin wrapper around send_prompt.py",
    )
    parser.add_argument("--json", action="store_true",
                        help="Output JSON (for programmatic consumption)")
    sub = parser.add_subparsers(dest="command")

    # create
    p_create = sub.add_parser("create", help="Create a scheduled prompt")
    p_create.add_argument("id", help="Unique schedule identifier (tag)")
    p_create.add_argument("--target", "-t", required=True,
                          help="Target: claude-desktop, claude-cli, codex-cli, gemini-cli, etc.")
    p_create.add_argument("--message", "-m", required=True, help="Prompt message text")
    p_create.add_argument("--convo_id", help="Conversation ID or URL")
    p_create.add_argument("--session", help="Terminal session name (CLI targets) or chat URL")
    timing = p_create.add_mutually_exclusive_group(required=True)
    timing.add_argument("--every", help="Periodic interval: 10m, 2h, 1d")
    timing.add_argument("--at", help="One-shot: +30m, +2h, 15:00, 2026-04-05T09:00")
    timing.add_argument("--delay", type=int,
                         help="One-shot delay in seconds (1-86400)")

    # list
    sub.add_parser("list", help="List scheduled prompts")

    # cancel
    p_cancel = sub.add_parser("cancel", help="Cancel a scheduled prompt")
    p_cancel.add_argument("id", nargs="?", help="Schedule ID (tag) to cancel")
    p_cancel.add_argument("--at-job", help="Cancel by at job ID")
    p_cancel.add_argument("--all", action="store_true", help="Cancel all scheduled prompts")

    # prune
    sub.add_parser("prune", help="Remove expired at-job entries from uai_toolkit.session_mgmt.store")

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    if args.command == "create":
        return cmd_create(args)
    elif args.command == "list":
        return cmd_list(args)
    elif args.command == "cancel":
        return cmd_cancel(args)
    elif args.command == "prune":
        return cmd_prune(args)

    return 0


if __name__ == "__main__":
    sys.exit(main())
