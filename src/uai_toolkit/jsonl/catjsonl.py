#!/usr/bin/env python3
"""
catjsonl.py — Unix pipeline tools for JSONL session messages.

Busybox-style: behavior determined by argv[0] via symlinks.
    jcat   — emit messages from files/UUIDs (like cat)
    jgrep  — filter messages by content pattern (like grep)
    jhead  — first N messages (like head)
    jtail  — last N messages (like tail)
    jwc    — count messages (like wc)
    jfmt   — render structured messages for display

Pipe format: one JSON object per line (Message schema + msg_num + source).
When stdout is a TTY, auto-renders colored display output.

Imports all parsing from read_jsonl.py — no duplication.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import unicodedata
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable

from uai_toolkit.jsonl.read_jsonl import (
    Message, MessageType, Colors, c,
    parse_session, find_jsonl, detect_platform,
    format_messages_from_schema, _ts_to_local,
)
from uai_toolkit.common_utils.standard_colors import set_color_mode as _sc_set_color_mode
from uai_toolkit.jsonl.discovery import discover_files


@dataclass
class PipeMessage:
    """Message with pipeline metadata (msg_num, source)."""
    role: str
    type: MessageType
    content: str
    timestamp: str
    platform: str
    tool_name: str
    tool_input: dict
    tool_call_id: str
    msg_num: int
    source: str
    line_number: int = 0

    def to_message(self) -> Message:
        """Convert back to read_jsonl.Message for formatting."""
        return Message(
            role=self.role, type=self.type, content=self.content,
            timestamp=self.timestamp, platform=self.platform,
            tool_name=self.tool_name, tool_input=self.tool_input,
            tool_call_id=self.tool_call_id,
            line_number=self.line_number,
        )


# =============================================================================
# Message I/O
# =============================================================================

def read_messages(sources: list[str], platform: str | None = None) -> list[PipeMessage]:
    """Read messages from file paths or UUIDs. Assigns msg_num per file."""
    messages = []
    for src in sources:
        path = Path(src)
        if not path.exists():
            resolved = find_jsonl(src)
            if resolved is None:
                print(f"Not found: {src}", file=sys.stderr)
                continue
            path = resolved

        raw_msgs = parse_session(path, platform=platform)
        source_name = str(path)
        for num, m in enumerate(raw_msgs):
            messages.append(PipeMessage(
                role=m.role, type=m.type, content=m.content,
                timestamp=m.timestamp, platform=m.platform,
                tool_name=m.tool_name, tool_input=m.tool_input,
                tool_call_id=m.tool_call_id,
                msg_num=num, source=source_name, line_number=m.line_number,
            ))
    return messages




def iter_messages_from_files(
    paths: list[Path],
    platform: str | None = None,
    type_filter: str | list[str] | None = None,
    role_filter: str | list[str] | None = None,
    since: str | None = None,
    before: str | None = None,
    progress: bool = False,
) -> "Generator[PipeMessage, None, None]":
    """Yield messages from multiple files, streaming. Assigns msg_num per file."""
    total_files = len(paths)
    type_filters = _normalize_filter_values(type_filter)
    role_filters = _normalize_filter_values(role_filter)
    since_dt = _parse_time_spec(since) if since else None
    before_dt = _parse_time_spec(before) if before else None
    for file_idx, path in enumerate(paths):
        if progress and sys.stderr.isatty():
            print(f"\r[{file_idx + 1}/{total_files}] {path.name}                    ", end="", file=sys.stderr)

        try:
            raw_msgs = parse_session(path, platform=platform)
        except Exception as e:
            print(f"\nSkipping {path}: {e}", file=sys.stderr)
            continue

        source_name = str(path)
        num = 0
        for m in raw_msgs:
            pm = PipeMessage(
                role=m.role, type=m.type, content=m.content,
                timestamp=m.timestamp, platform=m.platform,
                tool_name=m.tool_name, tool_input=m.tool_input,
                tool_call_id=m.tool_call_id,
                msg_num=num, source=source_name, line_number=m.line_number,
            )
            # Apply filters inline to avoid materializing full list
            if type_filters and pm.type.value not in type_filters:
                num += 1
                continue
            if role_filters and pm.role not in role_filters:
                num += 1
                continue
            if since_dt or before_dt:
                msg_dt = _parse_msg_timestamp(pm.timestamp)
                if msg_dt:
                    if since_dt and msg_dt < since_dt:
                        num += 1
                        continue
                    if before_dt and msg_dt > before_dt:
                        num += 1
                        continue
            num += 1
            yield pm

    if progress and sys.stderr.isatty():
        print(f"\r[{total_files}/{total_files}] done.                              ", file=sys.stderr)


def read_stdin() -> list[PipeMessage]:
    """Read PipeMessages from stdin (structured JSON lines from upstream tool)."""
    messages = []
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            messages.append(deserialize_message(line))
        except (json.JSONDecodeError, KeyError):
            continue
    return messages


def serialize_message(m: PipeMessage) -> str:
    """Serialize a PipeMessage to a single JSON line."""
    return json.dumps({
        "role": m.role, "type": m.type.value, "content": m.content,
        "timestamp": m.timestamp, "platform": m.platform,
        "tool_name": m.tool_name, "tool_input": m.tool_input,
        "tool_call_id": m.tool_call_id,
        "msg_num": m.msg_num, "source": m.source,
        "line_number": m.line_number,
    })


def deserialize_message(line: str) -> PipeMessage:
    """Deserialize a JSON line back to a PipeMessage."""
    d = json.loads(line)
    return PipeMessage(
        role=d["role"], type=MessageType(d["type"]), content=d["content"],
        timestamp=d["timestamp"], platform=d.get("platform", ""),
        tool_name=d.get("tool_name", ""), tool_input=d.get("tool_input", {}),
        tool_call_id=d.get("tool_call_id", ""),
        msg_num=d.get("msg_num", 0), source=d.get("source", ""),
        line_number=d.get("line_number", 0),
    )


def _parse_multi_value_filter(value: str, valid_values: Iterable[str], label: str) -> list[str]:
    """Parse comma-separated or repeated CLI filter values."""
    valid_set = set(valid_values)
    parts = [part.strip() for part in value.split(",")]
    parsed = [part for part in parts if part]
    invalid = [part for part in parsed if part not in valid_set]
    if invalid:
        valid_display = ", ".join(sorted(valid_set))
        invalid_display = ", ".join(invalid)
        raise argparse.ArgumentTypeError(
            f"invalid {label} choice(s): {invalid_display} (choose from {valid_display})"
        )
    return parsed


def _looks_like_source(value: str) -> bool:
    """Heuristic: does this string look like a file path, glob, or UUID rather than a regex?"""
    if ".jsonl" in value or "/" in value or "~" in value:
        return True
    if "*" in value or "?" in value:
        return True
    # Short hex string → likely a UUID prefix (e.g. "7edf")
    if re.fullmatch(r'[0-9a-fA-F-]{4,}', value):
        return True
    # Existing file on disk
    if os.path.exists(os.path.expanduser(value)):
        return True
    return False


def _normalize_filter_argv(argv: list[str]) -> list[str]:
    """Normalize multi-value filter args before argparse sees them.

    Supports both comma-separated and shell-split forms such as:
      --type tool_use,tool_result
      --type tool_use, tool_result
      --type tool_use tool_result
    """
    valid_by_flag = {
        "--type": {"user", "response", "thinking", "tool_use", "tool_result", "system", "meta", "skill", "agent_result", "injected"},
        "--role": {"user", "assistant", "system", "tool"},
    }

    normalized: list[str] = []
    index = 0
    while index < len(argv):
        token = argv[index]
        if token not in valid_by_flag:
            normalized.append(token)
            index += 1
            continue

        normalized.append(token)
        index += 1
        if index >= len(argv):
            break

        collected: list[str] = []
        while index < len(argv):
            candidate = argv[index]
            if candidate.startswith("-"):
                break

            stripped = candidate.strip().strip(",")
            if not stripped:
                index += 1
                continue

            if stripped not in valid_by_flag[token]:
                break

            collected.append(stripped)
            index += 1

            if "," not in candidate:
                break

        if collected:
            normalized.append(",".join(collected))

    return normalized


def _normalize_filter_values(values: str | list[str] | None) -> set[str]:
    """Flatten parser results into a set of filter values."""
    if not values:
        return set()
    if isinstance(values, str):
        return {values}

    normalized: set[str] = set()
    for value in values:
        if isinstance(value, list):
            normalized.update(value)
        elif value:
            normalized.add(value)
    return normalized


def _parse_time_spec(spec: str) -> datetime:
    """Parse a time specification into a UTC datetime.

    Supports:
        Relative: '1d', '7d', '2h', '30m', '1w'
        Absolute: '2026-04-09', '2026-04-09T14:30:00'
    """
    spec = spec.strip()
    # Relative: number + unit
    match = re.match(r'^(\d+)\s*([mhdw])$', spec, re.IGNORECASE)
    if match:
        n = int(match.group(1))
        unit = match.group(2).lower()
        delta = {'m': timedelta(minutes=n), 'h': timedelta(hours=n),
                 'd': timedelta(days=n), 'w': timedelta(weeks=n)}[unit]
        return datetime.now(timezone.utc) - delta
    # Absolute: try ISO parse
    try:
        dt = datetime.fromisoformat(spec.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        raise argparse.ArgumentTypeError(f"Cannot parse time spec: {spec!r}. Use e.g. '1d', '7d', '2h', or '2026-04-09'")


def _parse_msg_timestamp(ts: str) -> datetime | None:
    """Parse a message timestamp string to a UTC-aware datetime, or None on failure."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def sort_messages(msgs: list, sort_order: str) -> list:
    """Sort messages by timestamp across files."""
    def _msg_sort_key(m):
        ts = m.timestamp
        if not ts:
            return datetime.min.replace(tzinfo=timezone.utc)
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            return datetime.min.replace(tzinfo=timezone.utc)

    reverse = (sort_order == "newest")
    return sorted(msgs, key=_msg_sort_key, reverse=reverse)


def apply_filters(
    msgs: list[PipeMessage],
    type_filter: str | list[str] | None = None,
    role_filter: str | list[str] | None = None,
    since: str | None = None,
    before: str | None = None,
) -> list[PipeMessage]:
    """Apply --type, --role, --since, and --before filters."""
    type_filters = _normalize_filter_values(type_filter)
    role_filters = _normalize_filter_values(role_filter)

    if type_filters:
        msgs = [m for m in msgs if m.type.value in type_filters]
    if role_filters:
        msgs = [m for m in msgs if m.role in role_filters]
    if since:
        since_dt = _parse_time_spec(since)
        msgs = [m for m in msgs if (_parse_msg_timestamp(m.timestamp) or datetime.min.replace(tzinfo=timezone.utc)) >= since_dt]
    if before:
        before_dt = _parse_time_spec(before)
        msgs = [m for m in msgs if (_parse_msg_timestamp(m.timestamp) or datetime.max.replace(tzinfo=timezone.utc)) <= before_dt]
    return msgs


def output_messages(msgs: list[PipeMessage], force_json: bool = False,
                    format: str = "text", no_color: bool = False,
                    show_ts: bool = False):
    """Write messages to stdout — structured JSON if piped, display if TTY."""
    if no_color:
        Colors._enabled = False
        _sc_set_color_mode(False)

    if force_json or not sys.stdout.isatty():
        for m in msgs:
            print(serialize_message(m))
    elif show_ts:
        # Compact one-line-per-message with timestamp
        for m in msgs:
            first_line = m.content.split("\n", 1)[0][:120] if m.content else m.tool_name
            ts = c(f"[{_ts_to_local(m.timestamp)}]", Colors.YELLOW)
            print(f"{ts} {m.role}:{m.type.value}: {first_line}")
    else:
        display_msgs = [m.to_message() for m in msgs]
        print(format_messages_from_schema(display_msgs, format))


# =============================================================================
# Input helpers
# =============================================================================

def resolve_sources(args) -> list[str]:
    """Resolve args.sources — expand directories if -r flag is set.
    Applies --since/--before filtering and --sort ordering to all sources.
    Returns list of file path strings.
    """
    if not hasattr(args, "sources") or not args.sources:
        return []

    resolved = []
    recursive = getattr(args, "recursive", False)
    since = getattr(args, "since", None)
    before = getattr(args, "before", None)
    sort = getattr(args, "sort_order", "newest")

    for src in args.sources:
        path = Path(src)
        if path.is_dir():
            if not recursive:
                print(f"{src} is a directory. Use -r for recursive search.", file=sys.stderr)
                continue
            found = discover_files(str(path), since=since, before=before, sort=sort)
            resolved.extend(str(f) for f in found)
        elif path.exists():
            resolved.append(src)
        else:
            # Not a literal path — try resolving as a session UUID so the mtime
            # sort below has a real file to stat (else stat() throws a traceback).
            uuid_path = find_jsonl(src)
            if uuid_path is None:
                print(f"Not found: {src}", file=sys.stderr)
                continue
            resolved.append(str(uuid_path))

    # Apply --sort ordering by file mtime (controls file processing order).
    # Guard the stat so a vanished/unstattable path can't crash the sort.
    def _mtime(f: str) -> float:
        try:
            return Path(f).stat().st_mtime
        except OSError:
            return 0.0

    resolved.sort(key=_mtime, reverse=(sort != "oldest"))

    return resolved


def get_messages(args) -> list[PipeMessage]:
    """Get messages from args.sources (files/UUIDs) or stdin if no sources."""
    sources = resolve_sources(args)
    if sources:
        return read_messages(sources, platform=args.platform)
    elif not sys.stdin.isatty():
        return read_stdin()
    else:
        if hasattr(args, "sources") and args.sources:
            return []  # resolve_sources already printed errors
        print("No input. Provide files/UUIDs or pipe structured messages.", file=sys.stderr)
        return []


def get_messages_streaming(args):
    """Get messages as a generator for streaming output (used with -r)."""
    sources = resolve_sources(args)
    if sources:
        paths = []
        for src in sources:
            p = Path(src)
            if p.exists():
                paths.append(p)
            else:
                resolved = find_jsonl(src)
                if resolved:
                    paths.append(resolved)
        return iter_messages_from_files(
            paths,
            platform=args.platform,
            type_filter=args.type_filter,
            role_filter=args.role_filter,
            since=args.since,
            before=args.before,
            progress=getattr(args, "progress", False),
        )
    elif not sys.stdin.isatty():
        return read_stdin()
    else:
        return iter([])


# =============================================================================
# Tool dispatch
# =============================================================================

def detect_tool(argv0: str) -> str:
    """Determine which tool to run from argv[0]."""
    name = Path(argv0).stem
    if name in ("jcat", "jgrep", "jhead", "jtail", "jwc", "jfmt"):
        return name
    return "catjsonl"


_TOOL_DESCRIPTIONS = {
    "jcat": (
        "Read and display messages from AI CLI session files (JSONL).\n"
        "Accepts file paths, session UUIDs, or piped stdin. Auto-detects\n"
        "the source platform (Claude, Codex, Gemini, Anti-Gravity).\n"
        "When stdout is a terminal, renders colored human-readable output;\n"
        "when piped, emits one JSON object per line for downstream tools."
    ),
    "jgrep": (
        "Search AI CLI session messages by regex pattern, message type, or role.\n"
        "Works like grep but operates on parsed session messages instead of raw\n"
        "text lines. Supports case-insensitive search, inverted matches, context\n"
        "lines, match counting, and recursive directory scanning."
    ),
    "jhead": (
        "Show the first N messages from AI CLI session files.\n"
        "Works like head but operates on parsed messages. Default: 10 messages."
    ),
    "jtail": (
        "Show the last N messages from AI CLI session files.\n"
        "Works like tail but operates on parsed messages. Default: 10 messages."
    ),
    "jwc": (
        "Count messages in AI CLI session files.\n"
        "Works like wc but counts parsed messages. Can break down counts\n"
        "by message type (--by-type) or role (--by-role)."
    ),
    "jfmt": (
        "Format and render AI CLI session messages for display.\n"
        "Reads structured JSON messages from stdin or files and renders\n"
        "them as colored text, markdown, or re-formatted JSON."
    ),
    "catjsonl": (
        "Busybox-style JSONL session tools. Invoke as jcat, jgrep, jhead,\n"
        "jtail, jwc, or jfmt via symlink or as a subcommand argument.\n"
        "Use --help-examples for a full usage guide with examples."
    ),
}


def build_parser(tool: str) -> argparse.ArgumentParser:
    """Build argument parser for the given tool."""
    desc = _TOOL_DESCRIPTIONS.get(tool, f"j-tools: {tool}")
    p = argparse.ArgumentParser(
        prog=tool,
        description=desc,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Shared flags
    message_types = ["user", "response", "thinking", "tool_use", "tool_result", "system", "meta", "skill", "agent_result", "injected"]
    roles = ["user", "assistant", "system"]
    p.add_argument(
        "--type",
        dest="type_filter",
        action="append",
        type=lambda value: _parse_multi_value_filter(value, message_types, "--type"),
        metavar="TYPE[,TYPE...]",
        help=f"Filter by message type: {', '.join(message_types)}. Repeatable and comma-separated.",
    )
    p.add_argument(
        "--role",
        dest="role_filter",
        action="append",
        type=lambda value: _parse_multi_value_filter(value, roles, "--role"),
        metavar="ROLE[,ROLE...]",
        help=f"Filter by role: {', '.join(roles)}. Repeatable and comma-separated.",
    )
    p.add_argument("--platform", choices=["claude", "codex", "gemini", "agy"])
    p.add_argument("--json", dest="force_json", action="store_true", help="Force JSON output")
    p.add_argument("--ts", dest="show_ts", action="store_true", help="Show message timestamp")
    p.add_argument("--no-color", dest="no_color", action="store_true")

    # Recursive / file discovery flags
    p.add_argument("-r", dest="recursive", action="store_true", help="Recurse into directories")
    p.add_argument("--since", dest="since", help="Only files modified after (e.g., 7d, 2026-03-25)")
    p.add_argument("--before", dest="before", help="Only files modified before")
    p.add_argument("--sort", dest="sort_order", default="newest", choices=["newest", "oldest"], help="File processing order (default: newest)")
    p.add_argument("--progress", dest="progress", action="store_true", help="Show progress on stderr")

    if tool in ("jcat", "catjsonl"):
        p.add_argument("sources", nargs="*", help="Files or UUIDs")

    elif tool == "jgrep":
        p.add_argument("pattern", nargs="?", default=None, help="Regex pattern to match (optional when --type or --role is given)")
        p.add_argument("sources", nargs="*", help="Files or UUIDs")
        p.add_argument("-i", dest="ignore_case", action="store_true", help="Case-insensitive")
        p.add_argument("-F", "--fixed-strings", dest="fixed_strings", action="store_true", help="Treat pattern as a literal string, not a regex")
        p.add_argument("-v", "--verbose", dest="verbose", action="store_true", help="Print files as they are searched")
        p.add_argument("--invert", "--inverse-match", dest="invert", action="store_true", help="Invert match")
        p.add_argument("-n", dest="show_nums", action="store_true", help="Show source:msg:line:type prefix")
        p.add_argument("-c", dest="count_only", action="store_true", help="Print source:count match counts")
        p.add_argument("-C", "--context", dest="context", type=int, default=2, help="Lines of context around each in-message match (default: 2)")
        p.add_argument("--msg-context", dest="msg_context", type=int, default=0, help="Messages of context around matching messages")
        p.add_argument("--no-file-headers", dest="no_file_headers", action="store_true", help="Do not print per-file search headers in human output")
        p.add_argument("--pager", dest="pager", action="store_true", help="Page human output through less -RX with color forced")

    elif tool in ("jhead", "jtail"):
        p.add_argument("sources", nargs="*", help="Files or UUIDs")
        p.add_argument("-n", dest="count", type=int, default=10, help="Number of messages")

    elif tool == "jwc":
        p.add_argument("sources", nargs="*", help="Files or UUIDs")
        p.add_argument("--by-type", dest="by_type", action="store_true")
        p.add_argument("--by-role", dest="by_role", action="store_true")

    elif tool == "jfmt":
        p.add_argument("sources", nargs="*", help="Files or UUIDs (usually reads stdin)")
        p.add_argument("--format", dest="fmt", default="text", choices=["text", "json", "markdown"])
        p.add_argument("--collapse-tools", dest="collapse_tools", action="store_true")

    return p


def _help_examples() -> str:
    """Build colorized help examples."""
    H = lambda t: c(t, Colors.BOLD, Colors.BRIGHT_CYAN)    # section headers
    C = lambda t: c(t, Colors.BRIGHT_GREEN)                 # commands
    D = lambda t: c(t, Colors.DIM)                          # descriptions
    F = lambda t: c(t, Colors.YELLOW)                       # flags
    P = lambda t: c(t, Colors.BRIGHT_MAGENTA)               # pipe symbols
    B = lambda t: c(t, Colors.CYAN)                         # box drawing

    p = P("|")
    q = '"'  # double-quote char for use inside f-string expressions (Python 3.9 compat)
    lines = [
        c("j-tools", Colors.BOLD) + ": Unix pipeline tools for JSONL CLI sessions (Claude, Codex, Gemini, Anti-Gravity)",
        "",
        B("╔══════════════════════════════════════════════════════════════╗"),
        B("║") + f"  {C('jcat')}   — emit messages       {C('jgrep')}  — search messages      " + B("║"),
        B("║") + f"  {C('jhead')}  — first N messages    {C('jtail')}  — last N messages       " + B("║"),
        B("║") + f"  {C('jwc')}    — count messages      {C('jfmt')}   — format for display    " + B("║"),
        B("╚══════════════════════════════════════════════════════════════╝"),
        "",
        H("READING SESSIONS"),
        f"  {C('jcat 7edf')}                          {D('Read session by partial UUID (colored)')}",
        f"  {C('jcat session.jsonl')}                 {D('Read a JSONL file directly')}",
        f"  {C('jcat f1.jsonl f2.jsonl')}             {D('Concatenate multiple files')}",
        f"  {C('jcat 7edf')} {F('--platform codex')}         {D('Force platform detection')}",
        "",
        H("FILTERING BY TYPE AND ROLE"),
        f"  {D('Types:')} {F('user, response, thinking, tool_use, tool_result, system, meta, skill, agent_result, injected')}",
        f"  {D('Roles:')} {F('user, assistant, system')}",
        "",
        f"  {C('jcat 7edf')} {F('--type response')}          {D('Only assistant response messages')}",
        f"  {C('jcat 7edf')} {F('--type tool_use')}          {D('Only tool/function calls')}",
        f"  {C('jcat 7edf')} {F('--role user')}              {D('Only user messages')}",
        f"  {C('jcat 7edf')} {F('--role assistant')}         {D('Only assistant messages')}",
        "",
        H("SEARCHING"),
        f"  {C('jgrep')} {F(q+'error'+q)} {C('7edf')}                 {D('Messages containing '+q+'error'+q)}",
        f"  {C('jgrep')} {F('-i')} {F(q+'error'+q)} {C('7edf')}              {D('Case-insensitive search')}",
        f"  {C('jgrep')} {F('-v')} {F(q+'error'+q)} {C('*.jsonl')}           {D('Verbose: print files as searched')}",
        f"  {C('jgrep')} {F('--invert')} {F(q+'system'+q)} {C('7edf')}       {D('Messages NOT matching '+q+'system'+q)}",
        f"  {C('jgrep')} {F('-c')} {F(q+'error'+q)} {C('7edf')}              {D('Print source:count match counts')}",
        f"  {C('jgrep')} {F('-n')} {F(q+'error'+q)} {C('7edf')}              {D('Show source:msg:line:type prefix')}",
        f"  {C('jgrep')} {F('-C 2')} {F(q+'deploy'+q)} {C('7edf')}          {D('2 content lines around each match')}",
        f"  {C('jgrep')} {F(q+'Read|Write'+q)} {C('7edf')}            {D('Regex: messages with Read or Write tools')}",
        f"  {C('jgrep')} {F('-F')} {F(q+'(ans:'+q)} {C('7edf')}            {D('Literal search (no regex) — for text with ()[]*?| etc.')}",
        "",
        H("HEAD AND TAIL"),
        f"  {C('jhead 7edf')}                         {D('First 10 messages (default)')}",
        f"  {C('jhead')} {F('-n 5')} {C('7edf')}                    {D('First 5 messages')}",
        f"  {C('jtail')} {F('-n 3')} {C('7edf')}                    {D('Last 3 messages')}",
        f"  {C('jtail')} {F('-n 1')} {C('7edf')} {F('--type response')}    {D('Last response message only')}",
        "",
        H("COUNTING"),
        f"  {C('jwc 7edf')}                           {D('Total message count')}",
        f"  {C('jwc')} {F('--by-type')} {C('7edf')}                 {D('Count per message type')}",
        f"  {C('jwc')} {F('--by-role')} {C('7edf')}                 {D('Count per role')}",
        "",
        H("PIPELINES") + D(" (use --json between tools)"),
        f"  {C('jcat')} {C('7edf')} {F('--json')} {p} {C('jgrep')} {F(q+'error'+q+' -i')} {F('--json')} {p} {C('jfmt')}",
        f"      {D('Find error messages, render colored')}",
        "",
        f"  {C('jcat')} {C('7edf')} {F('--json')} {p} {C('jgrep')} {F(q+'deploy'+q+' -i -C 1')} {F('--json')} {p} {C('jtail')} {F('-n 5')} {p} {C('jfmt')}",
        f"      {D('Last 5 deploy-related messages with context')}",
        "",
        f"  {C('jcat')} {C('7edf')} {F('--json')} {p} {C('jgrep')} {F(q+'error'+q+' -c')}",
        f"      {D('Count error messages')}",
        "",
        f"  {C('jcat')} {C('7edf')} {F('--json --type tool_use')} {p} {C('jwc')}",
        f"      {D('Count tool calls')}",
        "",
        f"  {C('jcat')} {C('f1.jsonl f2.jsonl')} {F('--json')} {p} {C('jgrep')} {F('-n')} {F(q+'pattern'+q)}",
        f"      {D('Search across multiple files with location info')}",
        "",
        f"  {C('jcat')} {C('7edf')} {F('--json --role user')} {p} {C('jwc')}",
        f"      {D('Count user messages')}",
        "",
        H("DISPLAY FORMATTING"),
        f"  {C('jfmt')}                               {D('Render stdin as colored text (default)')}",
        f"  {C('jfmt')} {F('--format markdown')}             {D('Render as markdown')}",
        f"  {C('jfmt')} {F('--format json')}                 {D('Re-emit as formatted JSON')}",
        f"  {C('jfmt')} {F('--collapse-tools')}              {D('Truncate long tool results to 3 lines')}",
        "",
        H("RECURSIVE SEARCH"),
        f"  {C('jgrep')} {F('-r')} {F(q+'error'+q)} {C('~/.claude/projects/')}          {D('Search all Claude sessions')}",
        f"  {C('jgrep')} {F('-r -i')} {F(q+'deploy'+q)} {C('~/.codex/sessions/')}       {D('Search all Codex sessions')}",
        f"  {C('jgrep')} {F('-r -n')} {F(q+'bug'+q)} {C('~/.claude/projects/')} {F('--since 7d')}",
        f"      {D('Last 7 days, with file:msg:line:type locations')}",
        "",
        f"  {C('jcat')} {F('-r')} {C('~/.codex/sessions/2026/03/')} {F('--type user --role user')}",
        f"      {D('All user text messages from March Codex sessions')}",
        "",
        f"  {C('jwc')} {F('-r')} {C('~/.claude/projects/')} {F('--since 30d --by-type')}",
        f"      {D('Message type breakdown across last 30 days')}",
        "",
        f"  {C('jgrep')} {F('-r')} {F(q+'error'+q)} {C('~/.claude/projects/')} {F('--sort oldest --progress')}",
        f"      {D('Search oldest first with progress indicator')}",
        "",
        H("CODEX SESSIONS"),
        f"  {C('jcat')} {C('~/.codex/sessions/2026/03/25/rollout-*.jsonl')}",
        f"      {D('Read a Codex session file')}",
        "",
        f"  {C('jwc')} {F('--by-type')} {C('~/.codex/sessions/2026/03/25/rollout-*.jsonl')}",
        f"      {D('Count Codex message types')}",
        "",
        H("OUTPUT MODES"),
        f"  Stdout is TTY  {D('→')} colored human-readable output {D('(default)')}",
        f"  Stdout is pipe {D('→')} one JSON object per line {D('(automatic)')}",
        f"  {F('--json')}         {D('→')} force JSON output even on TTY",
        f"  {F('--no-color')}     {D('→')} disable colors in display mode",
        f"  Color is emitted by default in human output, including when piped",
        f"  {F('jgrep --pager')}  {D('→')} run jgrep through less -RX; keeps color and screen contents",
    ]
    return "\n".join(lines)


def main(tool=None):
    # Handle --help-examples before argparse
    if "--help-examples" in sys.argv:
        # Force color detection before generating help
        Colors._enabled = None
        _sc_set_color_mode(None)
        print(_help_examples())
        return

    if tool is None:
        tool = detect_tool(sys.argv[0])

    # Allow `catjsonl.py jcat ...` as alternative to symlinks
    if tool == "catjsonl" and len(sys.argv) > 1 and sys.argv[1] in ("jcat", "jgrep", "jhead", "jtail", "jwc", "jfmt", "--help-examples"):
        tool = sys.argv[1]
        sys.argv = [tool] + sys.argv[2:]

    parser = build_parser(tool)
    args = parser.parse_args(_normalize_filter_argv(sys.argv[1:]))
    _apply_color_setting(args)

    # jgrep: when filters make pattern optional, argparse may consume a
    # file/UUID as the pattern.  Detect and fix.  This happens with both
    # single files and globs (*.jsonl expands, first file becomes pattern).
    if tool == "jgrep" and args.pattern is not None and (args.type_filter or args.role_filter):
        if _looks_like_source(args.pattern):
            args.sources.insert(0, args.pattern)
            args.pattern = None

    if tool in ("jcat", "catjsonl"):
        run_jcat(args)
    elif tool == "jgrep":
        run_jgrep(args)
    elif tool == "jhead":
        run_jhead(args)
    elif tool == "jtail":
        run_jtail(args)
    elif tool == "jwc":
        run_jwc(args)
    elif tool == "jfmt":
        run_jfmt(args)


# =============================================================================
# Tool implementations
# =============================================================================

def _apply_color_setting(args):
    """Apply explicit color policy before any output is formatted."""
    if getattr(args, "no_color", False):
        Colors._enabled = False
        _sc_set_color_mode(False)
    else:
        Colors._enabled = None  # restore auto-detection
        _sc_set_color_mode(None)


def _pager_command() -> list[str]:
    """Return pager command for jgrep --pager.

    Default is less -RX:
      -R keeps ANSI SGR color.
      -X disables alternate-screen init/deinit so output remains after exit.
    Override the whole command with JGREP_PAGER if needed.
    """
    configured = os.environ.get("JGREP_PAGER")
    if configured:
        return shlex.split(configured)
    if os.name == "nt":
        return ["more"]
    return ["less", "-RX"]


def _run_with_pager(run_func) -> int:
    """Run a printer function with stdout connected to the configured pager."""
    try:
        proc = subprocess.Popen(_pager_command(), stdin=subprocess.PIPE, text=True)
    except (FileNotFoundError, OSError):
        # No pager available (common on Windows) — print directly.
        return run_func() or 0
    old_stdout = sys.stdout
    assert proc.stdin is not None
    sys.stdout = proc.stdin
    try:
        run_func()
    except BrokenPipeError:
        return 0
    finally:
        sys.stdout = old_stdout
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
    return proc.wait()


def run_jcat(args):
    """Emit messages from files or UUIDs."""
    msgs = get_messages(args)
    msgs = apply_filters(msgs, type_filter=args.type_filter, role_filter=args.role_filter, since=args.since, before=args.before)
    msgs = sort_messages(msgs, args.sort_order)
    output_messages(msgs, force_json=args.force_json, no_color=args.no_color, show_ts=args.show_ts)


# --- grep helpers ---

def _compile_user_pattern(pattern: str, flags: int = 0):
    """Compile a user-supplied regex, exiting cleanly on a bad pattern.

    A raw re.error here used to dump a Python traceback (e.g. an unescaped '('
    in the search term). Emit a one-line diagnostic and point at -F instead.
    """
    try:
        return re.compile(pattern, flags)
    except re.error as e:
        print(
            f"jgrep: invalid regex pattern {pattern!r}: {e}\n"
            f"  to search for literal text, use -F/--fixed-strings "
            f"(or escape regex metacharacters, e.g. '\\(ans:')",
            file=sys.stderr,
        )
        sys.exit(2)


def grep_messages(
    msgs: list[PipeMessage],
    pattern: str,
    ignore_case: bool = False,
    invert: bool = False,
    context: int = 0,
) -> list[PipeMessage]:
    """Filter messages whose cleaned display/search text matches pattern.

    The ``context`` parameter is message-level context for programmatic callers.
    Human jgrep output uses line-level context controlled by ``-C/--context``.
    """
    flags = re.IGNORECASE if ignore_case else 0
    compiled = _compile_user_pattern(pattern, flags)

    match_indices = _grep_match_indices(msgs, compiled, invert=invert)

    # Expand with context (disabled for invert — context would re-include excluded matches)
    if context > 0 and not invert:
        expanded = set()
        for i in match_indices:
            for offset in range(-context, context + 1):
                expanded.add(i + offset)
        match_indices = expanded

    return [msgs[i] for i in sorted(match_indices) if 0 <= i < len(msgs)]


_ESCAPED_TEXT_RE = re.compile(r"\\(u[0-9a-fA-F]{4}|U[0-9a-fA-F]{8}|x[0-9a-fA-F]{2}|n|r|t)")


def clean_display_text(value) -> str:
    """Return readable display/search text with common JSON escapes decoded.

    JSONL content is already decoded most of the time, but grep output often
    becomes unreadable when text has literal ``\\n``/``\\uNNNN`` sequences or
    invisible control/format characters. Keep real newlines/tabs; make other
    non-printing chars explicit instead of emitting terminal garbage.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        value = json.dumps(value, ensure_ascii=False, default=str)

    text = value.replace("\r\n", "\n").replace("\r", "\n")

    def _decode_escape(match: re.Match) -> str:
        token = match.group(1)
        if token == "n":
            return "\n"
        if token == "r":
            return "\n"
        if token == "t":
            return "\t"
        if token.startswith("u"):
            return chr(int(token[1:], 16))
        if token.startswith("U"):
            return chr(int(token[1:], 16))
        if token.startswith("x"):
            return chr(int(token[1:], 16))
        return match.group(0)

    text = _ESCAPED_TEXT_RE.sub(_decode_escape, text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")

    cleaned: list[str] = []
    for ch in text:
        if ch in ("\n", "\t"):
            cleaned.append(ch)
            continue
        category = unicodedata.category(ch)
        if category.startswith("C"):
            codepoint = ord(ch)
            if codepoint <= 0xFF:
                cleaned.append(f"\\x{codepoint:02x}")
            elif codepoint <= 0xFFFF:
                cleaned.append(f"\\u{codepoint:04x}")
            else:
                cleaned.append(f"\\U{codepoint:08x}")
            continue
        cleaned.append(ch)
    return "".join(cleaned)


def message_display_text(m: PipeMessage) -> str:
    """Build the text jgrep should search and display for a message."""
    if m.type == MessageType.TOOL_USE:
        pieces = []
        if m.tool_name:
            pieces.append(f"tool: {m.tool_name}")
        if m.tool_input:
            pieces.append(json.dumps(m.tool_input, indent=2, ensure_ascii=False, default=str))
        if m.content:
            pieces.append(str(m.content))
        return clean_display_text("\n".join(pieces))
    if m.content:
        return clean_display_text(m.content)
    return clean_display_text(m.tool_name)


def _grep_match_indices(msgs: list[PipeMessage], compiled: re.Pattern, invert: bool = False) -> set[int]:
    """Return message indexes matching compiled regex after display cleaning."""
    match_indices: set[int] = set()
    for i, m in enumerate(msgs):
        searchable = message_display_text(m)
        hit = compiled.search(searchable or "") is not None
        if hit != invert:
            match_indices.add(i)
    return match_indices


def _grep_selected_indices(
    msgs: list[PipeMessage],
    compiled: re.Pattern,
    invert: bool = False,
    msg_context: int = 0,
) -> list[tuple[int, bool]]:
    """Return ``(index, is_direct_match)`` pairs, expanding message context."""
    direct = _grep_match_indices(msgs, compiled, invert=invert)
    selected = set(direct)
    if msg_context > 0 and not invert:
        for i in direct:
            for offset in range(-msg_context, msg_context + 1):
                selected.add(i + offset)
    return [(i, i in direct) for i in sorted(selected) if 0 <= i < len(msgs)]


def _match_line_indices(text: str, compiled: re.Pattern) -> set[int]:
    """Find 0-indexed content lines containing regex matches."""
    lines = text.splitlines() or [""]
    indexes = {i for i, line in enumerate(lines) if compiled.search(line)}
    if indexes:
        return indexes

    # Fallback for unusual multi-line regexes.
    for match in compiled.finditer(text):
        indexes.add(text.count("\n", 0, match.start()))
    return indexes


def _merged_ranges(indexes: set[int], context: int, total_lines: int) -> list[tuple[int, int]]:
    """Merge line-context ranges around match lines."""
    if not indexes:
        return []
    ranges = []
    for idx in sorted(indexes):
        start = max(0, idx - context)
        end = min(total_lines - 1, idx + context)
        if ranges and start <= ranges[-1][1] + 1:
            ranges[-1] = (ranges[-1][0], max(ranges[-1][1], end))
        else:
            ranges.append((start, end))
    return ranges


def _highlight_line(line: str, compiled: re.Pattern) -> str:
    """Highlight regex matches with ANSI color when available, brackets otherwise."""
    def repl(match: re.Match) -> str:
        text = match.group(0)
        if not text:
            return text
        if Colors.enabled():
            return c(text, Colors.BOLD, Colors.BRIGHT_YELLOW)
        return f"[[{text}]]"

    return compiled.sub(repl, line)


def _truncate_line(line: str, width: int = 240) -> str:
    """Trim very long display lines."""
    if len(line) <= width:
        return line
    return line[:width - 1] + "…"


def _snippet_for_match(line: str, compiled: re.Pattern | None, width: int = 240) -> str:
    """Trim a line while keeping the first match visible when possible."""
    if len(line) <= width:
        return line
    if compiled is None:
        return _truncate_line(line, width=width)

    match = compiled.search(line)
    if match is None:
        return _truncate_line(line, width=width)

    ellipsis_left = "…"
    ellipsis_right = "…"
    match_width = max(1, match.end() - match.start())
    side_context = max(20, (width - match_width - len(ellipsis_left) - len(ellipsis_right)) // 2)
    start = max(0, match.start() - side_context)
    end = min(len(line), start + width)
    if end == len(line):
        start = max(0, end - width)

    snippet = line[start:end]
    if start > 0:
        snippet = ellipsis_left + snippet[1:]
    if end < len(line):
        snippet = snippet[:-1] + ellipsis_right
    return snippet


def _highlight_line_with_base(line: str, compiled: re.Pattern | None, *base_codes: str) -> str:
    """Color a whole line with base_codes and highlight matches."""
    if compiled is None:
        return c(line, *base_codes) if Colors.enabled() else line

    if not Colors.enabled():
        return _highlight_line(line, compiled)

    out: list[str] = []
    pos = 0
    for match in compiled.finditer(line):
        if match.start() > pos:
            out.append(c(line[pos:match.start()], *base_codes))
        text = match.group(0)
        if text:
            out.append(c(text, Colors.BOLD, Colors.BRIGHT_YELLOW))
        pos = match.end()
    if pos < len(line):
        out.append(c(line[pos:], *base_codes))
    return "".join(out) if out else c(line, *base_codes)


def _format_msg_location(m: PipeMessage, show_ts: bool = False) -> str:
    """Human-readable source/message/line location."""
    line_part = str(m.line_number) if m.line_number else "?"
    ts_part = " " + c(f"ts={_ts_to_local(m.timestamp)}", Colors.YELLOW) if show_ts else ""
    return f"{m.source}:msg={m.msg_num}:line={line_part}:type={m.type.value}:role={m.role}{ts_part}"


def format_numbered(
    msgs: list[PipeMessage],
    show_ts: bool = False,
    pattern: str | None = None,
    ignore_case: bool = False,
) -> list[str]:
    """Format messages with colorized source/msg-line/type-role/match-line fields."""
    compiled = None
    if pattern is not None:
        flags = re.IGNORECASE if ignore_case else 0
        compiled = _compile_user_pattern(pattern, flags)

    lines = []
    for m in msgs:
        text = message_display_text(m)
        content_lines = text.splitlines() or [""]
        selected_line = content_lines[0]
        if compiled is not None:
            match_lines = _match_line_indices(text, compiled)
            if match_lines:
                selected_line = content_lines[min(match_lines)]
        selected_line = _snippet_for_match(selected_line, compiled)
        selected_line = _highlight_line_with_base(selected_line, compiled, Colors.BRIGHT_WHITE)

        line_part = str(m.line_number) if m.line_number else "?"
        filename = c(m.source, Colors.BRIGHT_MAGENTA, Colors.BOLD)
        msg_line = c(f"msg={m.msg_num}:line={line_part}", Colors.BRIGHT_CYAN)
        type_role = c(f"type={m.type.value}:role={m.role}", Colors.BRIGHT_GREEN)
        ts_part = c(f":ts={_ts_to_local(m.timestamp)}", Colors.YELLOW) if show_ts else ""
        lines.append(f"{filename}:{msg_line}:{type_role}{ts_part}: {selected_line}")
    return lines


def format_grep_block(
    m: PipeMessage,
    compiled: re.Pattern,
    line_context: int = 2,
    show_ts: bool = False,
    is_direct_match: bool = True,
) -> str:
    """Format one jgrep human-readable result block."""
    text = message_display_text(m)
    content_lines = text.splitlines() or [""]
    match_lines = _match_line_indices(text, compiled) if is_direct_match else set()
    ranges = _merged_ranges(match_lines, max(0, line_context), len(content_lines))

    marker = "MATCH" if is_direct_match else "CONTEXT"
    header = f"{marker} {_format_msg_location(m, show_ts=show_ts)}"
    out = [c(header, Colors.BRIGHT_CYAN, Colors.BOLD)]

    preview_limit = min(3, len(content_lines))
    preview_chars = 0
    out.append(c("  start:", Colors.DIM))
    for idx in range(preview_limit):
        line = _truncate_line(content_lines[idx])
        preview_chars += len(line)
        out.append(f"    {idx + 1:>4}| {line}")
        if preview_chars >= 360:
            out.append("         …")
            break

    if not is_direct_match:
        return "\n".join(out)

    if not ranges and compiled.search(text or ""):
        out.append(c("  match: <regex matched across line boundaries>", Colors.DIM))
        return "\n".join(out)

    if ranges:
        out.append(c("  match:", Colors.DIM))
        previous_end = -1
        for start, end in ranges:
            if previous_end >= 0 and start > previous_end + 1:
                out.append("         …")
            for idx in range(start, end + 1):
                mark = ":" if idx in match_lines else "-"
                line = content_lines[idx]
                if idx in match_lines:
                    line = _highlight_line(line, compiled)
                out.append(f"    {idx + 1:>4}{mark} {_truncate_line(line)}")
            previous_end = end

    return "\n".join(out)


def run_jgrep(args):
    """Filter messages by content pattern."""
    if getattr(args, "pager", False) and not args.force_json and not args.count_only:
        args.no_color = False
        _apply_color_setting(args)
        _run_with_pager(lambda: _run_jgrep_inner(args))
        return

    _run_jgrep_inner(args)


def _run_jgrep_inner(args):
    """Filter messages by content pattern without pager wrapping."""
    if args.pattern is None and not args.type_filter and not args.role_filter:
        print("jgrep: pattern required when no --type or --role filter is given", file=sys.stderr)
        sys.exit(1)
    if getattr(args, "fixed_strings", False) and args.pattern:
        args.pattern = re.escape(args.pattern)
    sources = resolve_sources(args)
    if sources:
        _run_jgrep_streaming(args, sources)
        return

    # Stdin path: consume structured PipeMessages from upstream j-tools.
    msgs = get_messages(args)
    msgs = apply_filters(msgs, type_filter=args.type_filter, role_filter=args.role_filter, since=args.since, before=args.before)
    msgs = sort_messages(msgs, args.sort_order)
    _emit_jgrep_matches(args, msgs)


def _passes_msg_time_filters(
    m: PipeMessage,
    since_dt: datetime | None,
    before_dt: datetime | None,
) -> bool:
    """Apply parsed message timestamp bounds."""
    if not since_dt and not before_dt:
        return True
    msg_dt = _parse_msg_timestamp(m.timestamp)
    if not msg_dt:
        return True
    if since_dt and msg_dt < since_dt:
        return False
    if before_dt and msg_dt > before_dt:
        return False
    return True


def _messages_for_path(
    path: Path,
    args,
    type_filters: set[str],
    role_filters: set[str],
    since_dt: datetime | None,
    before_dt: datetime | None,
) -> list[PipeMessage]:
    """Parse one session file into filtered PipeMessages."""
    raw_msgs = parse_session(path, platform=args.platform)
    file_msgs = []
    for i, m in enumerate(raw_msgs):
        pm = PipeMessage(
            role=m.role, type=m.type, content=m.content,
            timestamp=m.timestamp, platform=m.platform,
            tool_name=m.tool_name, tool_input=m.tool_input,
            tool_call_id=m.tool_call_id,
            msg_num=i, source=str(path), line_number=m.line_number,
        )
        if type_filters and pm.type.value not in type_filters:
            continue
        if role_filters and pm.role not in role_filters:
            continue
        if not _passes_msg_time_filters(pm, since_dt, before_dt):
            continue
        file_msgs.append(pm)
    return file_msgs


def _print_file_header(path: Path, file_idx: int | None = None, total_files: int | None = None):
    """Print a per-file human output header."""
    if file_idx is not None and total_files is not None:
        prefix = f"==> [{file_idx + 1}/{total_files}] {path} <=="
    else:
        prefix = f"==> {path} <=="
    print(c(prefix, Colors.BOLD, Colors.BRIGHT_MAGENTA))


def _emit_jgrep_matches(args, msgs: list[PipeMessage], show_header: bool = False):
    """Emit grep matches for an already-loaded message list."""
    flags = re.IGNORECASE if args.ignore_case else 0
    compiled = _compile_user_pattern(args.pattern, flags) if args.pattern else None
    if compiled is None:
        selected = [(i, True) for i in range(len(msgs))]
    else:
        selected = _grep_selected_indices(
            msgs,
            compiled,
            invert=args.invert,
            msg_context=max(0, getattr(args, "msg_context", 0)),
        )
    direct_count = sum(1 for _, is_direct in selected if is_direct)

    if args.count_only:
        source_order: list[str] = []
        source_counts: dict[str, int] = {}
        for m in msgs:
            if not m.source:
                continue
            if m.source not in source_counts:
                source_order.append(m.source)
                source_counts[m.source] = 0
        for i, is_direct in selected:
            if not is_direct:
                continue
            source = msgs[i].source
            if not source:
                continue
            if source not in source_counts:
                source_order.append(source)
                source_counts[source] = 0
            source_counts[source] += 1
        if source_order:
            for source in source_order:
                print(f"{source}:{source_counts[source]}")
        else:
            print(direct_count)
        return

    matched = [msgs[i] for i, _ in selected]
    if args.force_json:
        for m in matched:
            print(serialize_message(m))
        return

    if args.no_color:
        Colors._enabled = False
        _sc_set_color_mode(False)

    if args.show_nums:
        direct_msgs = [msgs[i] for i, is_direct in selected if is_direct]
        for line in format_numbered(direct_msgs, show_ts=args.show_ts, pattern=args.pattern, ignore_case=args.ignore_case):
            print(line)
        return

    if compiled is None:
        output_messages(matched, force_json=False, no_color=args.no_color, show_ts=args.show_ts)
        return

    first = True
    for i, is_direct in selected:
        if not first:
            print()
        first = False
        print(format_grep_block(
            msgs[i],
            compiled,
            line_context=max(0, args.context),
            show_ts=args.show_ts,
            is_direct_match=is_direct,
        ))


def _run_jgrep_streaming(args, sources: list[str]):
    """Streaming grep over multiple files — emit matches as found."""
    flags = re.IGNORECASE if args.ignore_case else 0
    type_filters = _normalize_filter_values(args.type_filter)
    role_filters = _normalize_filter_values(args.role_filter)
    compiled = _compile_user_pattern(args.pattern, flags) if args.pattern else None
    force_json = args.force_json
    total_files = len(sources)
    since_dt = _parse_time_spec(args.since) if args.since else None
    before_dt = _parse_time_spec(args.before) if args.before else None

    if args.no_color:
        Colors._enabled = False
        _sc_set_color_mode(False)

    # Collect all matched messages across files for cross-file sorting.
    all_matched: list[tuple[PipeMessage, bool]] = []  # (msg, is_direct_match)

    for file_idx, src in enumerate(sources):
        path = Path(src)
        if not path.exists():
            resolved = find_jsonl(src)
            if not resolved:
                continue
            path = resolved

        if args.progress and sys.stderr.isatty():
            print(f"\r[{file_idx + 1}/{total_files}] {path.name}                    ", end="", file=sys.stderr)
        if (
            getattr(args, "verbose", False)
            and not force_json
            and not args.count_only
            and not getattr(args, "no_file_headers", False)
        ):
            _print_file_header(path, file_idx=file_idx, total_files=total_files)

        try:
            file_msgs = _messages_for_path(path, args, type_filters, role_filters, since_dt, before_dt)
        except Exception as e:
            print(f"\nSkipping {path}: {e}", file=sys.stderr)
            continue

        if compiled is None:
            selected = [(i, True) for i in range(len(file_msgs))]
        else:
            selected = _grep_selected_indices(
                file_msgs,
                compiled,
                invert=args.invert,
                msg_context=max(0, getattr(args, "msg_context", 0)),
            )
        direct_count = sum(1 for _, is_direct in selected if is_direct)

        if args.count_only:
            print(f"{path}:{direct_count}")
            continue

        if not selected:
            continue

        for i, is_direct in selected:
            all_matched.append((file_msgs[i], is_direct))

    if args.progress and sys.stderr.isatty():
        print(f"\r[{total_files}/{total_files}] done.                              ", file=sys.stderr)

    if args.count_only or not all_matched:
        return

    # Sort collected messages by timestamp
    sorted_matched = sort_messages([m for m, _ in all_matched], args.sort_order)
    # Rebuild is_direct lookup
    direct_ids = {id(m) for m, is_direct in all_matched if is_direct}
    sorted_pairs = [(m, id(m) in direct_ids) for m in sorted_matched]

    if args.show_nums:
        direct_msgs = [m for m, is_direct in sorted_pairs if is_direct]
        for line in format_numbered(direct_msgs, show_ts=args.show_ts, pattern=args.pattern, ignore_case=args.ignore_case):
            print(line)
    elif force_json:
        for m, _ in sorted_pairs:
            print(serialize_message(m))
    elif compiled is None:
        matched_msgs = [m for m, _ in sorted_pairs]
        output_messages(matched_msgs, force_json=False, no_color=args.no_color, show_ts=args.show_ts)
    else:
        first = True
        for m, is_direct in sorted_pairs:
            if not first:
                print()
            first = False
            print(format_grep_block(
                m,
                compiled,
                line_context=max(0, args.context),
                show_ts=args.show_ts,
                is_direct_match=is_direct,
            ))


def run_jhead(args):
    """First N messages."""
    msgs = get_messages(args)
    msgs = apply_filters(msgs, type_filter=args.type_filter, role_filter=args.role_filter, since=args.since, before=args.before)
    msgs = sort_messages(msgs, args.sort_order)
    msgs = msgs[:args.count]
    output_messages(msgs, force_json=args.force_json, no_color=args.no_color, show_ts=args.show_ts)


def run_jtail(args):
    """Last N messages."""
    msgs = get_messages(args)
    msgs = apply_filters(msgs, type_filter=args.type_filter, role_filter=args.role_filter, since=args.since, before=args.before)
    msgs = sort_messages(msgs, args.sort_order)
    msgs = msgs[-args.count:]
    output_messages(msgs, force_json=args.force_json, no_color=args.no_color, show_ts=args.show_ts)


# --- count/collapse helpers ---

def count_by_type(msgs: list[PipeMessage]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in msgs:
        key = m.type.value
        counts[key] = counts.get(key, 0) + 1
    return counts


def count_by_role(msgs: list[PipeMessage]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for m in msgs:
        counts[m.role] = counts.get(m.role, 0) + 1
    return counts


def collapse_tool_content(m: PipeMessage, max_lines: int = 3) -> str:
    """Truncate tool_result content to max_lines."""
    if m.type == MessageType.TOOL_RESULT and m.content:
        lines = m.content.split("\n")
        if len(lines) > max_lines:
            return "\n".join(lines[:max_lines]) + f"\n... ({len(lines) - max_lines} more lines)"
    return m.content


def run_jwc(args):
    """Count messages."""
    msgs = get_messages(args)
    msgs = apply_filters(msgs, type_filter=args.type_filter, role_filter=args.role_filter, since=args.since, before=args.before)

    if args.by_type:
        counts = count_by_type(msgs)
        for k, v in sorted(counts.items()):
            print(f"{v:>6}  {k}")
        print(f"{len(msgs):>6}  total")
    elif args.by_role:
        counts = count_by_role(msgs)
        for k, v in sorted(counts.items()):
            print(f"{v:>6}  {k}")
        print(f"{len(msgs):>6}  total")
    else:
        print(len(msgs))


def run_jfmt(args):
    """Render structured messages for display."""
    msgs = get_messages(args)
    msgs = apply_filters(msgs, type_filter=args.type_filter, role_filter=args.role_filter, since=args.since, before=args.before)

    if args.collapse_tools:
        for m in msgs:
            m.content = collapse_tool_content(m)

    if args.no_color:
        Colors._enabled = False
        _sc_set_color_mode(False)

    display_msgs = [m.to_message() for m in msgs]
    print(format_messages_from_schema(display_msgs, args.fmt))


def jcat():  return main("jcat")
def jgrep(): return main("jgrep")
def jhead(): return main("jhead")
def jtail(): return main("jtail")
def jwc():   return main("jwc")
def jfmt():  return main("jfmt")


if __name__ == "__main__":
    main()
