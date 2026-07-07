#!/usr/bin/env python3
"""Awareness feed — core library.

Append-only shared channels that give every session near-zero-effort ambient
awareness of what the other AIs are doing. This module is the pure core: append,
read-since-index, and render-the-injected-block. No hook/CLI policy lives here.

Design: ai_general/work/todos/todo_0313_awareness_feed_shared_session_activity_channel/2026-06-15-awareness-feed-design.md

Used by:
  - the inject hook (read side): read_since() + render_block()
  - the feed CLI / MCP wrapper (write side): append()
Concurrency: append() is O_APPEND-atomic, one line per entry, no lock.
"""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

# Channels live comms-adjacent. AI_ROOT is the canonical workspace root.
AI_ROOT = os.environ.get("AI_ROOT") or os.path.expanduser("~/AI/ai_root")
FEED_DIR = Path(AI_ROOT) / "ai_comms" / "feed"

DEFAULT_CHANNEL = "activity"


def channel_path(channel: str = DEFAULT_CHANNEL) -> Path:
    return FEED_DIR / f"{channel}.jsonl"


def append(session: str, name: str, text: str,
           channel: str = DEFAULT_CHANNEL, kind: str = "report",
           refs=None) -> dict:
    """Append one entry to a channel. Atomic via O_APPEND (no lock).

    The channel dir is created once at setup, not here — a missing dir is an
    install error and is allowed to raise.
    """
    entry = {
        "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
        "session": session,
        "name": name,
        "channel": channel,
        "kind": kind if kind in ("report", "event") else "report",
        "text": text.strip(),
    }
    if refs:
        entry["refs"] = list(refs)
    line = json.dumps(entry, ensure_ascii=False) + "\n"
    fd = os.open(str(channel_path(channel)), os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line.encode("utf-8"))
    finally:
        os.close(fd)
    return entry


def read_all(channel: str = DEFAULT_CHANNEL) -> list:
    """All entries on a channel. Malformed lines are skipped, not fatal."""
    path = channel_path(channel)
    if not path.exists():
        return []
    out = []
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except (json.JSONDecodeError, ValueError):
                continue
    return out


def read_since(channel: str, index):
    """Entries newer than `index`. Returns (unread_list, total_count).

    index None or negative -> first wake: start at `now` (no history replay).
    index past end-of-file -> clamp (file shrank/rotated).
    """
    entries = read_all(channel)
    total = len(entries)
    if index is None or index < 0:
        index = total
    if index > total:
        index = total
    return entries[index:], total


def _fmt_time(ts: str) -> str:
    """ISO ts -> 'HH:MM' (or 'MM/DD HH:MM' when not today). Absolute local clock."""
    try:
        dt = datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return "--:--"
    now = datetime.now().astimezone()
    local = dt.astimezone() if dt.tzinfo else dt
    if local.date() == now.date():
        return local.strftime("%H:%M")
    return local.strftime("%m/%d %H:%M")


def render_block(unread: list, total: int, exclude_session=None,
                 volume: int = 12, skipped: int = 0):
    """Render the injected awareness block, or None if nothing to show.

    - excludes the reader's own entries
    - collapses repeated identical events (same session + kind + text) into one
      line with a count and a first→last time span; real self-reports have unique
      text so they never collapse, only the repetitive auto-floor events do
    - recency-first: if more than `volume` distinct lines, keep the most recent
      `volume` and note the rest as skipped
    """
    if exclude_session:
        unread = [e for e in unread if e.get("session") != exclude_session]
    if not unread:
        return None

    # Collapse identical events into groups: count + first/last ts + latest entry.
    groups = {}
    order = []
    for e in unread:
        key = (e.get("session"), e.get("kind"), e.get("text"))
        ts = e.get("ts", "")
        g = groups.get(key)
        if g is None:
            g = {"entry": e, "count": 0, "first": ts, "last": ts}
            groups[key] = g
            order.append(key)
        g["count"] += 1
        g["entry"] = e  # keep the latest representative (name/refs)
        if ts:
            if not g["first"] or ts < g["first"]:
                g["first"] = ts
            if not g["last"] or ts > g["last"]:
                g["last"] = ts
    grouped = sorted((groups[k] for k in order), key=lambda g: g["last"] or "")

    extra = skipped
    if len(grouped) > volume:
        dropped = grouped[:len(grouped) - volume]
        extra += sum(g["count"] for g in dropped)
        grouped = grouped[len(grouped) - volume:]

    header = f"═══ AWARENESS · {len(grouped)} new " + "═" * 28
    lines = [
        header,
        "Recent activity from the other AIs working alongside you — for your awareness and edification. "
        "Peruse or not, at your leisure.",
        "Post your own when you finish something: feed post \"<what you did>\"",
        "",
    ]
    for g in grouped:
        e = g["entry"]
        marker = " · " if e.get("kind") == "event" else "   "
        name = str(e.get("name") or e.get("session") or "?")
        if g["count"] > 1:
            when = _fmt_time(g["first"])
            if g["last"] != g["first"]:
                try:
                    fd = datetime.fromisoformat(g["first"])
                    ld = datetime.fromisoformat(g["last"])
                    # share the date prefix when the span is within one day
                    end = (ld.astimezone().strftime("%H:%M")
                           if fd.astimezone().date() == ld.astimezone().date()
                           else _fmt_time(g["last"]))
                except (ValueError, TypeError):
                    end = _fmt_time(g["last"])
                when = f"{when}–{end}"
            suffix = f"  (×{g['count']})"
        else:
            when = _fmt_time(g["last"])
            suffix = ""
        lines.append(f"  {when}  {name}{marker}{e.get('text', '')}{suffix}")
        for ref in e.get("refs", []) or []:
            lines.append(f"                  ref: {ref}")
    if extra > 0:
        lines.append(f"  (+{extra} older — feed log to replay)")
    lines.append("═" * len(header))
    return "\n".join(lines)
