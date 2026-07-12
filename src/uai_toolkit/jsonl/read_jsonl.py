#!/usr/bin/env python3
"""
read_jsonl.py - Read and extract messages from CLI JSONL conversation files.

Supports Claude CLI, Codex CLI, Gemini CLI, and Anti-Gravity session formats.
Platform is auto-detected from file path or content; use --platform to override.

Used by: chat-pipeline, unified_cli app, claude_cli.py
Location: ~/bin/ai/cli/read_jsonl.py

Usage:
    # Interactive REPL mode
    read_jsonl.py

    # List all sessions for a project directory (Claude only)
    read_jsonl.py list [project_dir] [--limit N]

    # Read messages from a specific session UUID (searches all platforms)
    read_jsonl.py read <uuid> [--format json|text|markdown|memorex] [--platform claude|codex|gemini|agy]

    # Read messages from one or more JSONL files directly
    read_jsonl.py read-file <path> [path2 ...] [--format json|text|markdown|memorex] [--platform claude|codex|gemini|agy]

    # Extract scoped messages for briefing/Recall workflows
    read_jsonl.py extract <uuid|path> [--types user,response] [--interval 1-3] [--turns 40-55]

    # Find JSONL file for a UUID (prints path, searches all platforms)
    read_jsonl.py find <uuid>

    # Summary of a session
    read_jsonl.py summary <uuid> [--platform claude|codex|gemini|agy]
"""

from __future__ import annotations

import atexit
import json
import os
import re
import readline
import shlex
import sys
import warnings
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_SCRIPTS

# Import standard_colors
sys.path.insert(0, str(AI_SCRIPTS))
from uai_toolkit.common_utils.standard_colors import (
    CODES as _SC_CODES,
    c as _sc_c,
    colors_enabled as _sc_colors_enabled,
    set_color_mode as _sc_set_color_mode,
    format_help as _sc_format_help,
)

# Canonical compaction-interval + branch model (single source of truth). read_jsonl
# delegates its interval enumeration / SPEC selection here (see the thin aliases
# below) so context_stats / turn_digest share the exact same numbering.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from uai_toolkit.jsonl import lib_jsonl_archive as _lja  # noqa: E402


from uai_toolkit.jsonl.platform_adapters import adapter_for_platform, detect_platform as _detect_platform_adapter
from uai_toolkit.jsonl.standardized_session import load_standardized_session, is_standardized_session_file


CLAUDE_DIR = Path.home() / ".claude"
PROJECTS_DIR = CLAUDE_DIR / "projects"
HISTORY_FILE = CLAUDE_DIR / "history.jsonl"

CODEX_DIR = Path.home() / ".codex"
CODEX_SESSIONS_DIR = CODEX_DIR / "sessions"
CODEX_ARCHIVE_DIR = CODEX_DIR / "archived_sessions"
GEMINI_DIR = Path.home() / ".gemini"
GEMINI_HISTORY_DIR = GEMINI_DIR / "tmp"

VERSION = "3.0.0"
READLINE_HISTORY = Path.home() / ".read_jsonl_history"

class Colors:
    """ANSI color code constants — delegates to standard_colors for detection.

    Raw code attributes preserved for backward compatibility with callers that
    pass Colors.CONSTANT values into c(). Detection now routes through
    standard_colors.colors_enabled() so NO_COLOR, --no-color, and TTY detection
    all work consistently.
    """
    _enabled = None  # None = auto via standard_colors; True/False = override

    # Raw codes (backward compat — catjsonl.py passes these into c())
    RESET         = _SC_CODES["reset"]
    BOLD          = _SC_CODES["bold"]
    DIM           = _SC_CODES["dim"]
    ITALIC        = _SC_CODES["italic"]
    BLUE          = _SC_CODES["blue"]
    GREEN         = _SC_CODES["green"]
    YELLOW        = _SC_CODES["yellow"]
    CYAN          = _SC_CODES["cyan"]
    MAGENTA       = _SC_CODES["magenta"]
    RED           = _SC_CODES["red"]
    WHITE         = _SC_CODES["white"]
    BRIGHT_BLUE   = _SC_CODES["bright_blue"]
    BRIGHT_GREEN  = _SC_CODES["bright_green"]
    BRIGHT_YELLOW = _SC_CODES["bright_yellow"]
    BRIGHT_CYAN   = _SC_CODES["bright_cyan"]
    BRIGHT_MAGENTA = _SC_CODES["bright_magenta"]
    BRIGHT_WHITE  = _SC_CODES["bright_white"]

    @classmethod
    def enabled(cls) -> bool:
        if cls._enabled is not None:
            return cls._enabled
        return _sc_colors_enabled()


def c(text: str, *codes: str) -> str:
    """Apply raw ANSI codes or standard_colors style names to text.

    Accepts both Colors.CONSTANT raw escape strings (for backward compat with
    catjsonl.py) and named styles from standard_colors (e.g. 'red', 'bold').
    """
    if not Colors.enabled():
        return text
    # codes may be raw ANSI escape strings (e.g. "\033[1m") or style names
    combined = "".join(codes)
    return f"{combined}{text}{Colors.RESET}"


# ── Memorex shared presentation spec (sectioned/colored cards) ──────────────
# The "memorex" output format renders messages as colored, labeled, collapsible
# section cards that match the UAI Memorex live overlay. The look is shared with
# that overlay via an external palette file (so editing it restyles both); this
# embedded default keeps read_jsonl self-contained when the file is absent
# (e.g. ported standalone). See ai_general/data/memorex/palette.json.
_MEMOREX_PALETTE_DEFAULT = {
    "sections": {
        "user":      {"color": "#7aa2f7", "bg": "#213450", "label": "YOU",      "collapse": False},
        "inject":    {"color": "#2ac3de", "bg": "#103039", "label": "COMMS",    "collapse": False},
        "assistant": {"color": "#9ece6a", "bg": "#1c3a26", "label": "CLAUDE",   "collapse": False},
        "thinking":  {"color": "#bb9af7", "bg": "#2e2049", "label": "THINKING", "collapse": True, "textColor": "#e3ccff"},
        "tool":      {"color": "#e0af68", "bg": "#3a2c18", "label": "TOOL",     "collapse": True},
        "skill":     {"color": "#7dcfff", "bg": "#0e2a33", "label": "SKILL",    "collapse": True},
        "agent":     {"color": "#7dcfff", "bg": "#102a33", "label": "AGENT",    "collapse": True},
        "system":    {"color": "#565f89", "bg": "#181a20", "label": "SYSTEM",   "collapse": True},
        "meta":      {"color": "#565f89", "bg": "#181a20", "label": "META",     "collapse": True},
    },
    "typeToSection": {
        "user": "user", "response": "assistant", "thinking": "thinking",
        "tool_use": "tool", "tool_result": "tool", "injected": "inject",
        "skill": "skill", "agent_result": "agent", "system": "system", "meta": "meta",
    },
    "thinkingText": "#e3ccff",
}

_memorex_palette_cache = None

# Inter-session prompt envelope — matches the UAI Memorex overlay's INJECT_ENVELOPE_RE
# (TerminalFormatOverlay.tsx). A USER message whose body opens with this is a
# comms send_prompt injection (e.g. from Git Guardian), rendered as COMMS.
_MEMOREX_INJECT_RE = re.compile(r"^From\s+\S+\s+\(\S+\)\s+at\s+\d{4}-\d{2}-\d{2}\b")


def _load_memorex_palette() -> dict:
    """Load the shared Memorex palette: external file if present (keeps the look
    in sync with the UAI overlay), else the embedded default. Search order:
    $MEMOREX_PALETTE, $AI_ROOT/ai_general/data/memorex/palette.json, then a path
    relative to this script."""
    global _memorex_palette_cache
    if _memorex_palette_cache is not None:
        return _memorex_palette_cache
    candidates = []
    env = os.environ.get("MEMOREX_PALETTE")
    if env:
        candidates.append(Path(env))
    ai_root = os.environ.get("AI_ROOT")
    if ai_root:
        candidates.append(Path(ai_root) / "ai_general" / "data" / "memorex" / "palette.json")
    candidates.append(Path(__file__).resolve().parents[2] / "data" / "memorex" / "palette.json")
    for p in candidates:
        try:
            if p and p.is_file():
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("sections"):
                    _memorex_palette_cache = data
                    return data
        except Exception:
            continue
    _memorex_palette_cache = _MEMOREX_PALETTE_DEFAULT
    return _MEMOREX_PALETTE_DEFAULT


def _hex_to_ansi(hex_str: str, *, bg: bool = False) -> str:
    """'#7aa2f7' -> ANSI 24-bit SGR ('\\033[38;2;122;162;247m'). bg=True -> 48;2."""
    h = (hex_str or "").lstrip("#")
    if len(h) != 6:
        return ""
    try:
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    except ValueError:
        return ""
    return f"\033[{48 if bg else 38};2;{r};{g};{b}m"


def render_memorex(messages: "list[Message]", *, msg_num_offset: int = 0,
                   expand: "set[str] | None" = None) -> str:
    """Render messages as Memorex-style colored, labeled section cards (ANSI),
    matching the UAI Memorex live overlay's look via the shared palette.

    - Each message is one card: a colored left-border bar, a bold type label
      (YOU/COMMS/CLAUDE/THINKING/TOOL/...), and dim Turn#/Msg#/timestamp.
    - Collapse-default sections (thinking, tool, skill, agent, system, meta) are
      folded to a one-line summary unless their section name is in `expand`
      (or `expand` contains 'all').
    """
    palette = _load_memorex_palette()
    sections = palette.get("sections", {})
    type_to_section = palette.get("typeToSection", {})
    expand = expand or set()
    expand_all = "all" in expand
    enabled = Colors.enabled()
    BAR = "▎"  # left-border bar

    def paint(text: str, hexcolor: str, bold: bool = False) -> str:
        if not enabled:
            return text
        pre = _hex_to_ansi(hexcolor) + (Colors.BOLD if bold else "")
        return f"{pre}{text}{Colors.RESET}"

    meta_spec = sections.get("meta", {"color": "#565f89", "label": "META", "collapse": True})
    out: list[str] = []
    for i, m in enumerate(messages):
        sec = type_to_section.get(m.type.value, "meta")
        # Inter-session prompt (comms send_prompt): a USER record whose body opens
        # with the provenance envelope "From <id> (<id>) at YYYY-MM-DD ...". The
        # JSONL has no meta flag for these, so read_jsonl tags them USER — but the
        # UAI Memorex overlay shows them as COMMS. Remap here so both render alike.
        if sec == "user" and _MEMOREX_INJECT_RE.match((m.content or "").lstrip()):
            sec = "inject"
        spec = sections.get(sec, meta_spec)
        color = spec.get("color", "#565f89")
        label = spec.get("label", sec.upper())
        if sec == "assistant" and m.platform:
            label = m.platform.upper()
        if sec == "tool" and m.tool_name:
            label = f"{spec.get('label', 'TOOL')} · {m.tool_name}"

        num = msg_num_offset + i + 1
        turn_tag = "pre " if m.turn_number < 0 else f"Turn #{m.turn_number} "
        meta_str = f"{turn_tag}Msg #{num}  {_ts_to_local(m.timestamp)}"
        bar = paint(BAR, color)
        meta_painted = c(meta_str, Colors.DIM) if enabled else meta_str
        out.append(f"{bar} {paint(label, color, bold=True)}  {meta_painted}")

        body = m.content or ""
        if sec == "tool" and m.type == MessageType.TOOL_USE and m.tool_input:
            body = json.dumps(m.tool_input, indent=2, ensure_ascii=False)
        lines = body.splitlines() or [""]
        collapse = spec.get("collapse", False) and not expand_all and sec not in expand
        if collapse and len(lines) > 1:
            summary = lines[0][:100].rstrip()
            out.append(f"{bar} {summary}")
            fold = f"⟨{len(lines)} lines — --expand {sec} to unfold⟩"
            out.append(f"{bar} {c(fold, Colors.DIM) if enabled else fold}")
        else:
            text_color = spec.get("textColor")
            for ln in lines:
                if text_color and enabled:
                    out.append(f"{bar} {paint(ln, text_color)}")
                else:
                    out.append(f"{bar} {ln}")
        out.append("")  # blank line between cards
    return "\n".join(out)


def _parse_memorex_expand(value: "str | None") -> "set[str]":
    """Parse a --expand value (comma-separated section names, or 'all') into a set.
    Section names: user, inject, assistant, thinking, tool, skill, agent, system, meta."""
    if not value:
        return set()
    return {s.strip() for s in value.split(",") if s.strip()}


COMMAND_ALIASES = {
    "?": "help",
    "h": "help",
    "r": "read",
    "x": "extract",
    "rf": "read-file",
    "f": "find",
    "s": "summary",
    "st": "stats",
    "ls": "list",
    "cx": "compactions",
    "hg": "histo",
    "hist": "histo",
}


class MessageType(Enum):
    USER = "user"               # Human-typed user messages
    RESPONSE = "response"       # Assistant text responses
    THINKING = "thinking"       # Claude thinking blocks
    TOOL_USE = "tool_use"       # Tool/function calls
    TOOL_RESULT = "tool_result" # Tool results
    SYSTEM = "system"           # System/developer messages
    META = "meta"               # Session metadata
    SKILL = "skill"             # Skill expansion (isMeta + sourceToolUseID or skill-like content)
    AGENT_RESULT = "agent_result"  # Subagent/task notification (origin.kind == task-notification)
    INJECTED = "injected"       # Other non-human injected content (isMeta without skill/agent markers)

    # Backward compat: allow MessageType("text") to resolve to RESPONSE
    @classmethod
    def _missing_(cls, value):
        if value == "text":
            return cls.RESPONSE
        return None


@dataclass
class Message:
    role: str
    type: MessageType
    content: str
    timestamp: str
    platform: str = ""
    tool_name: str = ""
    tool_input: dict = field(default_factory=dict)
    tool_call_id: str = ""
    line_number: int = 0       # message ordinal: 1-based position in the parsed message stream — NOT the raw file line
    source_line: int = 0       # 1-indexed raw JSONL file line this message came from (0 if unknown)
    turn_number: int = 0       # conversation turn (first prompt = turn 0; -1 = `pre` prologue)
    on_chain: bool = True      # is this record on the active chain (in model context)? off-chain = dead retry/rewind fork
    is_compaction: bool = False  # isCompactSummary continuation record
    raw: dict = field(default_factory=dict, repr=False)

    def to_dict(self, include_raw: bool = False) -> dict:
        """Serialize to dict for JSON output."""
        d = {
            "role": self.role,
            "type": self.type.value,
            "content": self.content,
            "timestamp": self.timestamp,
            "platform": self.platform,
            "line_number": self.line_number,   # message ordinal
            "source_line": self.source_line,   # raw JSONL file line
            "turn_number": self.turn_number,   # conversation turn
        }
        if self.tool_name:
            d["tool_name"] = self.tool_name
        if self.tool_input:
            d["tool_input"] = self.tool_input
        if self.tool_call_id:
            d["tool_call_id"] = self.tool_call_id
        if include_raw:
            d["raw"] = self.raw
        return d


@dataclass
class Turn:
    """A turn: user message + all assistant/tool messages until next user message."""
    number: int                  # 1-indexed turn number
    messages: list[Message] = field(default_factory=list)

    @property
    def user_message(self) -> Message | None:
        return next((m for m in self.messages if m.type == MessageType.USER), None)

    @property
    def timestamp(self) -> str:
        return self.messages[0].timestamp if self.messages else ""

    def to_dict(self, include_raw: bool = False) -> dict:
        return {
            "number": self.number,
            "timestamp": self.timestamp,
            "messages": [m.to_dict(include_raw) for m in self.messages],
        }


@dataclass
class DayGroup:
    """Messages grouped by calendar day."""
    date: str                    # YYYY-MM-DD
    label: str                   # "Today", "Yesterday", or "YYYY-MM-DD — Wednesday"
    turns: list[Turn] = field(default_factory=list)

    def to_dict(self, include_raw: bool = False) -> dict:
        return {
            "date": self.date,
            "label": self.label,
            "turns": [t.to_dict(include_raw) for t in self.turns],
        }


# ---------------------------------------------------------------------------
# Grouping functions
# ---------------------------------------------------------------------------

def group_into_turns(messages: list[Message]) -> list[Turn]:
    """Group messages by their assigned turn_number (set in parse_session).

    turn_number is structural (a prompt with a promptSource on the active chain
    starts a turn; first prompt = turn 0, prologue = -1 `pre`). Grouping by it keeps
    turns consistent across read headers, t-ranges, and histo."""
    turns: list[Turn] = []
    current: list[Message] = []
    cur_num = None
    for msg in messages:
        if cur_num is not None and msg.turn_number != cur_num:
            turns.append(Turn(number=cur_num, messages=current))
            current = []
        cur_num = msg.turn_number
        current.append(msg)
    if current:
        turns.append(Turn(number=cur_num if cur_num is not None else 0, messages=current))
    return turns


def _date_label(date_str: str) -> str:
    """Human-readable label for a date string."""
    today = datetime.now().strftime("%Y-%m-%d")
    yesterday = datetime.fromtimestamp(
        datetime.now().timestamp() - 86400
    ).strftime("%Y-%m-%d")
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        day_name = dt.strftime("%A")
        if date_str == today:
            return f"Today — {day_name}"
        if date_str == yesterday:
            return f"Yesterday — {day_name}"
        return f"{date_str} — {day_name}"
    except ValueError:
        return date_str


def group_by_day(turns: list[Turn]) -> list[DayGroup]:
    """Group turns by calendar day based on first message timestamp."""
    day_map: dict[str, list[Turn]] = {}

    for turn in turns:
        ts = turn.timestamp
        date_key = "Unknown"
        if ts:
            try:
                cleaned = ts.replace("Z", "+00:00")
                dt = datetime.fromisoformat(cleaned).astimezone()
                date_key = dt.strftime("%Y-%m-%d")
            except (ValueError, TypeError):
                pass
        day_map.setdefault(date_key, []).append(turn)

    return [
        DayGroup(date=date, label=_date_label(date), turns=day_turns)
        for date, day_turns in sorted(day_map.items())
    ]


def structure_session(messages: list[Message]) -> list[DayGroup]:
    """Full pipeline: messages → turns → day groups."""
    turns = group_into_turns(messages)
    return group_by_day(turns)


def _strip_uri(identifier: str) -> str:
    """Extract session ID from a URI, or return as-is if not a URI.

    Handles uai://session/<id>[/<action>], prompt://target/<id>, and any
    scheme://path/<id>. Centralized, action-aware (see lib_uri) — an action
    suffix like /message is not mistaken for the id.
    """
    if "://" not in identifier:
        return identifier
    try:
        import sys as _sys
        _sm = str(AI_SCRIPTS / "session_mgmt")
        if _sm not in _sys.path:
            _sys.path.insert(0, _sm)
        from uai_toolkit.session_mgmt.lib_uri import session_id_of
        return session_id_of(identifier)
    except Exception:
        try:
            from urllib.parse import urlparse
            path_parts = urlparse(identifier).path.strip("/").split("/")
            return path_parts[-1] if path_parts else identifier
        except Exception:
            return identifier


def _resolve_via_session_store(query: str) -> Path | None:
    """Try to resolve a query via session_store (tracking ID, display name, etc.).

    Accepts URIs (uai://session/<id>, prompt://target/<id>), tracking IDs,
    display names, CLI UUIDs, and UUID prefixes.

    Returns the first existing transcript path, or falls back to CLI UUID
    for filesystem search. Returns None if session_store is unavailable or
    no match is found.
    """
    try:
        store_path = AI_SCRIPTS / "session_mgmt" / "session_store.py"
        if not store_path.exists():
            return None
        import importlib.util
        spec = importlib.util.spec_from_file_location("session_store", store_path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        store = mod.SessionStore()
        session = store.resolve(query)
        if not session:
            return None

        # Try transcript_path first (list of JSONL paths)
        paths = session.get("transcript_path", [])
        if isinstance(paths, str):
            paths = [paths]
        for tp in paths:
            p = Path(tp).expanduser()
            if p.exists():
                return p

        # Fall back to CLI UUID for filesystem search
        cli_uuid = session.get("cli_session_id")
        if cli_uuid:
            # Don't recurse — just check Claude project dirs directly
            for proj_dir in PROJECTS_DIR.iterdir():
                if not proj_dir.is_dir():
                    continue
                candidate = proj_dir / f"{cli_uuid}.jsonl"
                if candidate.exists():
                    return candidate
    except Exception:
        pass
    return None


def find_jsonl(query: str) -> Path | None:
    """Find a session file by full or partial UUID, or by direct file path.

    If query is an existing file path (absolute or relative), returns it directly.
    Otherwise searches: Claude projects -> Codex sessions -> Gemini history -> Codex archive.
    Partial matching: query is matched as a prefix or substring of the UUID
    portion of the filename or content.
    """
    # Strip URI wrapper if present (uai://session/<id>, prompt://target/<id>, etc.)
    query = _strip_uri(query)

    # Direct file path
    p = Path(query).expanduser()
    if p.exists() and p.is_file():
        return p

    # Try session_store: resolves tracking ID, display name, terminal session, CLI UUID
    resolved_path = _resolve_via_session_store(query)
    if resolved_path:
        return resolved_path

    candidates = []
    query = query.lower()

    # 1. Claude: {uuid}.jsonl in project dirs
    if PROJECTS_DIR.exists():
        for proj_dir in PROJECTS_DIR.iterdir():
            if not proj_dir.is_dir():
                continue
            for f in proj_dir.glob("*.jsonl"):
                stem = f.stem.lower()
                if stem == query or stem.startswith(query) or query in stem:
                    candidates.append(f)

    # 2. Codex: rollout-{date}-{uuid}.jsonl in date tree
    # 3. Gemini: session-{date}-{partial_uuid}.json in tmp/*/chats/
    search_paths = [
        (CODEX_SESSIONS_DIR, "*.jsonl"),
        (GEMINI_HISTORY_DIR, "session-*.json"),
        (CODEX_ARCHIVE_DIR, "*.jsonl"),
    ]

    for search_dir, pattern in search_paths:
        if not search_dir.exists():
            continue
        for f in search_dir.rglob(pattern):
            name = f.stem.lower()
            # Codex: last 36 chars are usually the UUID
            if f.suffix == ".jsonl" and len(name) >= 36:
                file_uuid = name[-36:]
                if file_uuid == query or file_uuid.startswith(query) or query in file_uuid:
                    candidates.append(f)
                    continue

            # Gemini: last 8 chars of stem are usually the partial UUID
            if f.suffix == ".json" and name.startswith("session-"):
                if len(name) >= 8:
                    partial_uuid = name[-8:]
                    if query == partial_uuid or query in name:
                        candidates.append(f)
                        continue
                    # For Gemini, if it's a long query, maybe it's the full UUID from inside
                    if len(query) >= 32:
                        try:
                            with open(f) as jf:
                                data = json.load(jf)
                                if str(data.get("sessionId", "")).lower() == query:
                                    candidates.append(f)
                        except (json.JSONDecodeError, OSError):
                            pass

    if len(candidates) == 1:
        return candidates[0]
    elif len(candidates) > 1:
        # Deduplicate candidates by path
        seen = set()
        unique_candidates = []
        for c in candidates:
            if c not in seen:
                unique_candidates.append(c)
                seen.add(c)
        
        if len(unique_candidates) == 1:
            return unique_candidates[0]
            
        print(f"Ambiguous match for '{query}' -- {len(unique_candidates)} files found:", file=sys.stderr)
        for c in unique_candidates[:10]:
            print(f"  {c}", file=sys.stderr)
        return None
    return None


def _normalize_timestamp(ts_raw) -> str:
    """Convert any timestamp format to ISO string."""
    if isinstance(ts_raw, (int, float)):
        return datetime.fromtimestamp(ts_raw / 1000 if ts_raw > 1e12 else ts_raw).isoformat()
    elif isinstance(ts_raw, str):
        return ts_raw
    return ""


def _ts_to_local(ts: str) -> str:
    """Convert a UTC ISO timestamp string to local time for display.

    Handles: '2026-04-10T00:32:13.509Z', '2026-04-10T00:32:13Z',
             '2026-04-10T00:32:13+00:00', and already-local strings.
    Returns 'YYYY-MM-DD HH:MM:SS' in local timezone, or the original string on failure.
    """
    if not ts:
        return ts
    try:
        from datetime import timezone
        # Try parsing with Z suffix
        cleaned = ts.replace("Z", "+00:00")
        dt = datetime.fromisoformat(cleaned)
        # Convert to local time
        local_dt = dt.astimezone()
        return local_dt.strftime("%Y-%m-%d %H:%M:%S")
    except (ValueError, TypeError):
        return ts


def detect_platform(jsonl_path: Path) -> str:
    """Detect which CLI platform produced a JSONL/JSON file.

    Returns one of: agy, claude, codex, gemini, standardized.
    """
    return _detect_platform_adapter(jsonl_path)



def _src_line(source_ids) -> int:
    """Raw 1-indexed JSONL file line from a record's source_ids (e.g. 'src-012711' -> 12711)."""
    if source_ids:
        s = source_ids[0]
        if isinstance(s, str) and s.startswith("src-"):
            try:
                return int(s[4:])
            except ValueError:
                pass
    return 0


def _standardized_to_messages(session) -> list[Message]:
    messages: list[Message] = []
    for record in session.message_records:
        if not record.visible:
            continue
        try:
            msg_type = MessageType(record.message_type)
        except ValueError:
            continue
        messages.append(
            Message(
                role=record.role,
                type=msg_type,
                content=record.content_text,
                timestamp=record.timestamp,
                platform=session.header.platform,
                tool_name=record.tool_name,
                tool_input=record.tool_input,
                tool_call_id=record.tool_call_id,
                line_number=record.sequence,
                source_line=_src_line(record.source_ids),
                raw={
                    "standardized_record": record.to_envelope(),
                    "session_header": session.header.to_envelope(),
                },
            )
        )
    return messages



OFFLOAD_ARCHIVE_SUFFIX = ".archive"


def resolve_archived_stubs(messages: list[Message], jsonl_path: Path) -> list[Message]:
    """Rehydrate offload stubs in place from their co-located archive (opt-in view).

    offload_tool_results.py replaces aged tool_result.content / tool_use.input with
    a stub carrying a portable ref:  '… → ref <uuid8>/<id>.<field>.txt …'.  The body
    lives at  <transcript_dir>/<transcript_stem>.<uuid8>.archive/<id>.<field>.txt.
    This resolves the ref against the CURRENT transcript (so a forked copy resolves to
    its own archive) and substitutes the body. Read-only and best-effort: a missing
    archive leaves the stub untouched. Off by default — callers opt in (e.g. `--resolve`)
    so summary/stats keep reflecting the lean on-disk reality.
    """
    import re
    ref_re = re.compile(r"→ ref (\S+/\S+\.txt)")
    jsonl_path = Path(jsonl_path)
    base, stem = jsonl_path.parent, jsonl_path.stem

    def _sub(text):
        if not isinstance(text, str):
            return text, False
        m = ref_re.search(text)
        if not m:
            return text, False
        uuid8, _, fname = m.group(1).partition("/")
        body = base / f"{stem}.{uuid8}{OFFLOAD_ARCHIVE_SUFFIX}" / fname
        try:
            return body.read_text(encoding="utf-8"), True
        except OSError:
            return text, False

    for msg in messages:
        new, ok = _sub(msg.content)
        if ok:
            msg.content = new
        if isinstance(msg.tool_input, dict):
            for k, v in list(msg.tool_input.items()):
                nv, ok2 = _sub(v)
                if ok2:
                    msg.tool_input[k] = nv
    return messages


def _chain_and_prompt_meta(jsonl_path: Path, *,
                           all_intervals: bool = False) -> tuple[set, set, set]:
    """Structural turn metadata from the ORIGINAL records (the standardized
    Message.raw drops promptSource/isCompactSummary, like it drops the signature).

    Returns (chain_lines, turnstart_lines, compaction_lines) as sets of 1-indexed
    raw file line numbers:
      chain_lines     — records on the active chain (leaf→root parentUuid walk).
      turnstart_lines — on-chain user records that carry promptSource (an actually
                        submitted prompt — typed/queued/system) and aren't
                        isMeta/isCompactSummary. These start a turn.
      compaction_lines— isCompactSummary continuation records.
    Empty sets ⇒ caller falls back to the legacy USER-based numbering (non-Claude).

    DEFAULT (all_intervals=False): the CURRENT-INTERVAL single-walk chain — only the
    tree containing the active conversational leaf. Each /compact writes a fresh
    parentUuid=None root, so this is what the model actually sees NOW; superseded
    pre-compaction intervals are excluded. Set all_intervals=True for the whole-FILE
    multi-root union (all intervals' live turns) — wanted only for file reduction /
    archival accounting (todo_0393)."""
    by_uuid: dict = {}
    order: list = []
    try:
        with open(jsonl_path, encoding="utf-8") as f:
            for i, ln in enumerate(f, 1):
                if not ln.strip():
                    continue
                try:
                    o = json.loads(ln)
                except Exception:
                    continue
                if not isinstance(o, dict):
                    continue
                order.append((i, o))
                u = o.get("uuid")
                if u:
                    by_uuid[u] = (i, o)
    except OSError:
        return set(), set(), set()

    # Active chain, multi-root. Each /compact starts a NEW tree (a system root with
    # parentUuid=None), so a single leaf→root walk only sees the current interval.
    # Instead: group records into trees by root, and for each tree walk back from its
    # LIVE tip (latest record in the tree) to the root. Union = all live turns across
    # all intervals, while dead-retry / rewind siblings (which end before their tree's
    # tip) drop out.
    parent_of = {u: o.get("parentUuid") for u, (i, o) in by_uuid.items()}

    def root_of(u):
        seen_r = set()
        while u in by_uuid and u not in seen_r:
            seen_r.add(u)
            p = parent_of.get(u)
            if p not in by_uuid:
                break
            u = p
        return u

    trees: dict = {}
    for u, (i, o) in by_uuid.items():
        trees.setdefault(root_of(u), []).append((i, u))

    # DEFAULT: current interval only — the single tree containing the active
    # conversational leaf (last non-sidechain user/assistant). all_intervals=True
    # unions every tree's live branch (whole-file, all compaction intervals).
    if all_intervals:
        selected = list(trees.items())
    else:
        leaf_uuid = None
        for _i, o in reversed(order):
            if o.get("isSidechain"):
                continue
            if o.get("type") in ("user", "assistant") and o.get("uuid"):
                leaf_uuid = o["uuid"]
                break
        if leaf_uuid is not None:
            lr = root_of(leaf_uuid)
            selected = [(lr, trees.get(lr, []))]
        else:
            selected = list(trees.items())   # no conversational leaf → fall back to union

    chain_lines: set = set()
    for _root, members in selected:
        if not members:
            continue
        tip_u = max(members)[1]          # latest record (by file line) = the live branch
        cur, seen = tip_u, set()
        while cur in by_uuid and cur not in seen:
            seen.add(cur)
            chain_lines.add(by_uuid[cur][0])
            p = parent_of.get(cur)
            if p not in by_uuid:
                break
            cur = p

    turnstart_lines: set = set()
    compaction_lines: set = set()
    for i, o in order:
        if o.get("type") != "user":
            continue
        if o.get("isCompactSummary"):
            compaction_lines.add(i)
        if (i in chain_lines and "promptSource" in o
                and not o.get("isMeta") and not o.get("isCompactSummary")):
            turnstart_lines.add(i)
    return chain_lines, turnstart_lines, compaction_lines


def _assign_turn_numbers(messages: list[Message], turnstart_lines: set | None = None,
                         chain_lines: set | None = None,
                         compaction_lines: set | None = None) -> list[Message]:
    """Stamp turn_number / on_chain / is_compaction.

    Structural mode (turnstart_lines given): a new turn begins at each turn-start
    record (a submitted prompt — promptSource). The FIRST prompt is turn 0; records
    before it (compact_boundary / isCompactSummary / continuation — the prologue)
    get turn_number -1, the `pre` sentinel (NOT a numbered turn). on_chain reflects
    active-chain membership. Fallback (no turnstart_lines — non-Claude): legacy
    increment-on-USER, 0-indexed, everything on_chain.
    """
    compaction_lines = compaction_lines or set()
    for m in messages:
        if m.source_line in compaction_lines:
            m.is_compaction = True

    if turnstart_lines:
        turn_num = -1                     # prologue (`pre`) until the first prompt
        for m in messages:
            if m.source_line in turnstart_lines:
                turn_num = turn_num + 1 if turn_num >= 0 else 0   # first prompt = T0
            m.turn_number = turn_num
            m.on_chain = (chain_lines is None) or (m.source_line in chain_lines)
        return messages

    # Fallback: legacy USER-based numbering (platforms without promptSource); the
    # first USER message is turn 0 (0-indexed, matching the structural mode).
    turn_num = 0
    started = False
    for m in messages:
        if m.type == MessageType.USER and started:
            turn_num += 1
            started = False
        m.turn_number = turn_num
        m.on_chain = True
        started = True
    return messages


def parse_session(jsonl_path: Path, platform: str | None = None, *,
                  all_intervals: bool = False) -> list[Message]:
    """Parse a session file into a list of Message objects.

    Native platform files are first converted into the standardized schema, then
    the rest of read_jsonl operates on the standardized message records.

    all_intervals=False (DEFAULT): turn/chain metadata scopes to the CURRENT
    compaction interval (single-walk chain = what the model sees now). Pass
    all_intervals=True for the whole-file, all-intervals view (file reduction).
    """
    if is_standardized_session_file(jsonl_path):
        msgs = _standardized_to_messages(load_standardized_session(jsonl_path))
    else:
        if platform is None:
            platform = detect_platform(jsonl_path)
        if platform == "standardized":
            msgs = _standardized_to_messages(load_standardized_session(jsonl_path))
        else:
            adapter = adapter_for_platform(platform)
            session = adapter.from_file(jsonl_path)
            msgs = _standardized_to_messages(session)
    chain_lines, turnstart_lines, compaction_lines = _chain_and_prompt_meta(
        jsonl_path, all_intervals=all_intervals)
    return _assign_turn_numbers(msgs, turnstart_lines, chain_lines, compaction_lines)



def _parse_codex(jsonl_path: Path) -> list[Message]:
    return parse_session(jsonl_path, platform="codex")



def _parse_gemini(jsonl_path: Path) -> list[Message]:
    return parse_session(jsonl_path, platform="gemini")



def _parse_claude(jsonl_path: Path) -> list[Message]:
    return parse_session(jsonl_path, platform="claude")



def extract_messages(jsonl_path: Path, platform: str | None = None) -> list[dict[str, Any]]:
    """Extract user/assistant text messages. Returns list[dict] for backward compatibility.
    Prefer parse_session() for new code.
    """
    msgs = parse_session(jsonl_path, platform=platform)
    result = []
    for m in msgs:
        if m.type in (MessageType.USER, MessageType.RESPONSE):
            result.append({"role": m.role, "content": m.content, "timestamp": m.timestamp})
    return result


def extract_tool_uses(jsonl_path: Path, platform: str | None = None) -> list[dict[str, Any]]:
    """Extract tool uses as list[dict]. Backward-compatible interface."""
    msgs = parse_session(jsonl_path, platform=platform)
    return [
        {"tool_name": m.tool_name, "tool_input": m.tool_input, "timestamp": m.timestamp}
        for m in msgs if m.type == MessageType.TOOL_USE
    ]


# Raw line `type` values that form the conversation stream (the basis of what is
# actually sent to the model, modulo the compaction boundary). Everything else is
# client-side bookkeeping that parse_session discards and the model never sees.
_CONVERSATION_LINE_TYPES = {"user", "assistant"}


def raw_line_breakdown(jsonl_path: Path) -> dict[str, Any]:
    """Categorize RAW JSONL lines by `type` into conversation (model-facing) vs
    client-only (never sent), with per-type line count + char size.

    Operates on raw lines, so it sees the client-only records (file-history
    snapshots, attachments, mode/title/agent state, progress, ...) that
    parse_session() drops. `conversation` + `client_only` sum exactly to `total`,
    so a client-only contribution is trivial to calculate out.

    NOTE: sizes are raw JSONL chars (incl. JSON overhead + base64 image data,
    which is char-huge but token-cheap), NOT tokens; and `conversation` still
    counts pre-compaction lines that aren't actually sent. Use as proportions.
    """
    by_type: dict[str, dict] = {}
    conv = {"count": 0, "chars": 0}
    client = {"count": 0, "chars": 0}
    total = {"count": 0, "chars": 0}
    # Attachment records (deferred_tools_delta et al.) are dropped by parse_session so
    # they land in `client`, but unlike true client-only bookkeeping they ARE re-sent
    # to the model each resume. Track them so the render can correct the "never sent"
    # impression (todo_0375). Kept inside `client` so conversation+client_only=total.
    mfa = {"count": 0, "chars": 0}
    # Sub-breakouts within the two conversation raw line types. `user` is split
    # LINE-wise (each user line is either a prompt or carries tool_result(s) —
    # mutually exclusive, so prompts+tool_results sum exactly to the user total).
    # `assistant` is split BLOCK-wise (one assistant line commonly mixes
    # text+thinking+tool_use), so counts are blocks and chars are block JSON
    # bytes — a within-line decomposition that does NOT sum to the line total
    # (the per-line envelope/metadata is excluded).
    sub = {
        "user": {"prompts": {"count": 0, "chars": 0},
                 "tool_results": {"count": 0, "chars": 0}},
        "assistant": {"replies": {"count": 0, "chars": 0},
                      "thinking": {"count": 0, "chars": 0},
                      "tool_use": {"count": 0, "chars": 0}},
    }
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                n = len(line)
                total["count"] += 1
                total["chars"] += n
                obj = None
                try:
                    obj = json.loads(line)
                    t = obj.get("type", "?") if isinstance(obj, dict) else "?"
                except Exception:
                    t = "<unparseable>"
                slot = by_type.setdefault(t, {"count": 0, "chars": 0})
                slot["count"] += 1
                slot["chars"] += n
                bucket = conv if t in _CONVERSATION_LINE_TYPES else client
                bucket["count"] += 1
                bucket["chars"] += n
                if t == "attachment":
                    mfa["count"] += 1
                    mfa["chars"] += n
                # ---- sub-breakouts ----
                if isinstance(obj, dict) and t in ("user", "assistant"):
                    msg = obj.get("message")
                    content = msg.get("content") if isinstance(msg, dict) else obj.get("content")
                    if t == "user":
                        has_tr = isinstance(content, list) and any(
                            isinstance(b, dict) and b.get("type") == "tool_result" for b in content)
                        key = "tool_results" if has_tr else "prompts"
                        sub["user"][key]["count"] += 1
                        sub["user"][key]["chars"] += n
                    else:  # assistant — block-wise
                        if isinstance(content, list):
                            for b in content:
                                if not isinstance(b, dict):
                                    continue
                                bt = b.get("type")
                                if bt == "text":
                                    k = "replies"
                                elif bt == "thinking":
                                    k = "thinking"
                                elif bt == "tool_use":
                                    k = "tool_use"
                                else:
                                    continue
                                sub["assistant"][k]["count"] += 1
                                sub["assistant"][k]["chars"] += len(
                                    json.dumps(b, ensure_ascii=False))
                        elif isinstance(content, str):
                            sub["assistant"]["replies"]["count"] += 1
                            sub["assistant"]["replies"]["chars"] += len(content)
    except OSError:
        return {}
    return {
        "total": total,
        "conversation": conv,
        "client_only": client,
        "model_facing_attachments": mfa,
        "client_only_pct": round(100 * client["chars"] / total["chars"], 1) if total["chars"] else 0,
        "by_type": dict(sorted(by_type.items(), key=lambda kv: -kv[1]["chars"])),
        "sub": sub,
    }


def _format_raw_line_breakdown(bd: dict) -> str:
    """Render raw_line_breakdown() as a text section for the stats command."""
    if not bd:
        return ""
    t, conv, cl = bd["total"], bd["conversation"], bd["client_only"]
    out = ["", c("RAW LINE BREAKDOWN", Colors.BOLD) + c("  (by raw line `type`; chars = file bytes, NOT tokens)", Colors.DIM)]
    # Same-term-different-meaning warning: 'user'/'assistant' here are RAW LINE TYPES,
    # which collide with the SEMANTIC User/AI/Tools/Think in the Totals block above.
    out.append(c("  [!] TERM COLLISION: 'user'/'assistant' below are raw line TYPES, NOT the semantic", Colors.YELLOW))
    out.append(c("      User/AI/Tools/Think in Totals above. A tool_result is a 'user'-type line; tool_use", Colors.DIM))
    out.append(c("      + thinking ride in 'assistant'-type lines. So raw 'user' = Totals(User + tool_results),", Colors.DIM))
    out.append(c("      and Totals(Tools) is split across both raw types. Same word, different axis.", Colors.DIM))
    out.append(f"  total         {t['count']:>6,} lines  {t['chars']:>12,} chars")
    out.append(f"  conversation  {conv['count']:>6,} lines  {conv['chars']:>12,} chars   " + c("(user+assistant role lines — model-facing stream)", Colors.DIM))
    out.append(f"  client-only   {cl['count']:>6,} lines  {cl['chars']:>12,} chars   " + c(f"({bd['client_only_pct']}% of file — dropped by parse_session; MOSTLY not sent, but see below)", Colors.DIM))
    mfa = bd.get("model_facing_attachments")
    if mfa and mfa["count"]:
        out.append("    of which attachments " + f"{mfa['count']:>5,} lines  {mfa['chars']:>12,} chars   "
                   + c("(deferred_tools_delta etc. — these DO reach the model, re-sent each resume; NOT free)", Colors.YELLOW))
    out.append(c("  per raw type:", Colors.DIM))
    _incl = {"user": c("  (role: prompts + tool_results)", Colors.YELLOW),
             "assistant": c("  (role: AI text + thinking + tool_use)", Colors.YELLOW)}
    sub = bd.get("sub", {})
    for typ, d in bd["by_type"].items():
        if typ in _CONVERSATION_LINE_TYPES:
            tag = _incl.get(typ, "")
        else:
            tag = c("  client-only", Colors.DIM)
        out.append(f"    {typ:<22}{d['count']:>6,} lines  {d['chars']:>12,} chars{tag}")
        # sub-breakouts beneath the user / assistant raw line types
        if typ == "user" and sub.get("user"):
            su = sub["user"]
            for sk, label in (("prompts", "user: prompts"),
                              ("tool_results", "user: tool_results")):
                sd = su[sk]
                out.append(c(f"      {label:<20}{sd['count']:>6,} lines  {sd['chars']:>12,} chars"
                             "  (line-wise; sums to user)", Colors.DIM))
        elif typ == "assistant" and sub.get("assistant"):
            sa = sub["assistant"]
            for sk, label in (("replies", "assistant: replies"),
                              ("thinking", "assistant: thinking"),
                              ("tool_use", "assistant: tool_use")):
                sd = sa[sk]
                out.append(c(f"      {label:<20}{sd['count']:>6,} blk    {sd['chars']:>12,} chars"
                             "  (block-wise; block JSON bytes)", Colors.DIM))
    out.append(c("  note: chars are raw JSONL bytes (incl. JSON overhead + base64 images, which are", Colors.DIM))
    out.append(c("        char-huge but token-cheap); 'conversation' still counts pre-compaction lines", Colors.DIM))
    out.append(c("        that aren't sent. Treat as proportions, not token counts.", Colors.DIM))
    return "\n".join(out)


# =============================================================================
# ADDITIVE STATS (2026-06): offload/engram stub accounting + per-line
# client-only FIELD accounting + a semantic/raw/model-facing reconciliation.
# All read-only; none of this touches parse_session / human_turn_indices / the
# public functions other tools import. Stub prefixes are pulled lazily from
# lib_jsonl_archive + lib_engram so there is no circular import at module load.
# =============================================================================

def _stub_prefixes() -> tuple[tuple[str, ...], str]:
    """(offload STUB_PREFIXES, engram stub prefix), loaded lazily/best-effort."""
    offload = ()
    engram = "[engram archived:"
    try:
        from uai_toolkit.jsonl import lib_jsonl_archive
        offload = tuple(lib_jsonl_archive.STUB_PREFIXES)
    except Exception:
        offload = (
            "[archived:", "[tool result stripped:", "[input archived:",
            "[input stripped:", "[embed archived:", "[embed stripped:",
        )
    try:
        from uai_toolkit.jsonl import lib_engram
        engram = lib_engram.ENGRAM_STUB_PREFIX
    except Exception:
        pass
    return offload, engram


def stub_accounting(jsonl_path: Path) -> dict[str, Any]:
    """Count and size the blocks CURRENTLY replaced by offload/engram stubs.

    Walks raw lines and inspects message.content blocks (and top-level content)
    for stub-prefixed strings, so already-offloaded content is visible as its own
    category instead of silently counting as normal content. A stub is detected
    by lib_jsonl_archive.STUB_PREFIXES (offload) or the '[engram archived:' prefix.

    Categorizes by where the stub sits:
      tool_result   — a tool_result block whose .content is a stub
      tool_use_input— a tool_use block whose .input[k] is a stub
      embed         — an embed-kind stub ('[embed …]') sitting as a text/content block
      engram        — an '[engram archived:' stub (whole-turn engram page-out)
    'bytes' = current on-disk stub text length (what the stub costs now, NOT the
    original it replaced). Returns counts + bytes per category and totals.
    """
    offload_prefixes, engram_prefix = _stub_prefixes()

    def _is_offload_stub(v) -> bool:
        return isinstance(v, str) and v.lstrip().startswith(offload_prefixes)

    def _offload_stub_text(v):
        """Return the stub string for an attachment.<key> value, or None.

        Attachment offload is shape-preserving: a list-typed field keeps its list
        container and holds the stub as its sole element ([stub]); a string-typed
        field holds the bare stub. Recognise both so offloaded attachments stay
        visible in the accounting regardless of the original container type."""
        if _is_offload_stub(v):
            return v
        if isinstance(v, list) and len(v) == 1 and _is_offload_stub(v[0]):
            return v[0]
        return None

    def _is_engram_stub(v) -> bool:
        return isinstance(v, str) and v.lstrip().startswith(engram_prefix)

    def _is_embed_stub(v) -> bool:
        return isinstance(v, str) and v.lstrip().startswith(("[embed archived:", "[embed stripped:"))

    cats = {k: {"count": 0, "bytes": 0}
            for k in ("tool_result", "tool_use_input", "embed", "engram", "attachment")}

    def _add(cat: str, text: str) -> None:
        cats[cat]["count"] += 1
        cats[cat]["bytes"] += len(text)

    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if not isinstance(o, dict):
                    continue
                # top-level `attachment` record: offloaded attachment.<key> payloads
                # (e.g. deferred_tools_delta.addedNames) sit as stub strings here, not
                # in message.content — inspect them so offloaded attachments are visible.
                if o.get("type") == "attachment" and isinstance(o.get("attachment"), dict):
                    for av in o["attachment"].values():
                        stub_text = _offload_stub_text(av)
                        if stub_text is not None:
                            _add("attachment", stub_text)
                    continue
                msg = o.get("message")
                content = msg.get("content") if isinstance(msg, dict) else o.get("content")
                # whole-turn engram stub can be a plain string content
                if isinstance(content, str):
                    if _is_engram_stub(content):
                        _add("engram", content)
                    continue
                if not isinstance(content, list):
                    continue
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt == "tool_result":
                        v = b.get("content")
                        # tool_result content can be str or list-of-text-blocks
                        if _is_engram_stub(v):
                            _add("engram", v)
                        elif _is_offload_stub(v):
                            _add("tool_result", v)
                        elif isinstance(v, list):
                            for sub in v:
                                if isinstance(sub, dict) and _is_offload_stub(sub.get("text")):
                                    _add("tool_result", sub["text"])
                    elif bt == "tool_use" and isinstance(b.get("input"), dict):
                        for vv in b["input"].values():
                            if _is_offload_stub(vv):
                                _add("tool_use_input", vv)
                    elif bt in ("text", "image"):
                        txt = b.get("text")
                        if _is_embed_stub(txt):
                            _add("embed", txt)
                        elif _is_engram_stub(txt):
                            _add("engram", txt)
                        elif _is_offload_stub(txt):
                            _add("embed", txt)
    except OSError:
        return {}

    total = {"count": sum(v["count"] for v in cats.values()),
             "bytes": sum(v["bytes"] for v in cats.values())}
    return {"categories": cats, "total": total}


def _format_stub_accounting(sa: dict) -> str:
    """Render stub_accounting() as a labeled additive stats section."""
    if not sa or not sa.get("total", {}).get("count"):
        out = ["", c("OFFLOADED / STUBBED ACCOUNTING", Colors.BOLD, Colors.BRIGHT_CYAN)]
        out.append(c("  (blocks already replaced by offload/engram stubs — detected via "
                     "lib_jsonl_archive.STUB_PREFIXES + '[engram archived:')", Colors.DIM))
        out.append(c("  none found — no offloaded/stubbed content in this transcript.", Colors.DIM))
        return "\n".join(out)
    cats, total = sa["categories"], sa["total"]
    out = ["", c("OFFLOADED / STUBBED ACCOUNTING", Colors.BOLD, Colors.BRIGHT_CYAN)]
    out.append(c("  (blocks already replaced by offload/engram stubs — detected via "
                 "lib_jsonl_archive.STUB_PREFIXES + '[engram archived:')", Colors.DIM))
    out.append(c("  'bytes' = CURRENT stub text size on disk, not the original it replaced.", Colors.DIM))
    labels = {
        "tool_result": "tool_result stubs",
        "tool_use_input": "tool_use-input stubs",
        "embed": "embed stubs",
        "engram": "engram stubs",
        "attachment": "attachment stubs",
    }
    for key in ("tool_result", "tool_use_input", "embed", "engram", "attachment"):
        d = cats[key]
        out.append(f"    {labels[key]:<22}{d['count']:>6,} stubs  {d['bytes']:>12,} stub bytes")
    out.append(f"    {'TOTAL':<22}{total['count']:>6,} stubs  {total['bytes']:>12,} stub bytes")
    return "\n".join(out)


# Top-level / sub fields that ride along inside user/assistant conversation lines
# but are NEVER sent to the model (client-side bookkeeping). The big one is the
# top-level `toolUseResult` — it duplicates the tool output already carried in the
# tool_result block and on a real transcript can be ~30% of the whole file.
def conversation_client_only_fields(jsonl_path: Path) -> dict[str, Any]:
    """Sum bytes of client-only FIELDS carried inside user/assistant lines.

    read_jsonl's RAW LINE BREAKDOWN classifies model-facing-ness by LINE TYPE,
    so a whole user/assistant line counts as 'conversation'. But those lines carry
    fat fields the model never sees. This measures them so 'conversation' can be
    corrected down to a real model-facing estimate.

    Fields measured (only on type in {user, assistant}):
      toolUseResult  — top-level; client-only (duplicates the tool_result block)
      message.usage  — token-accounting metadata; client-only
      signature      — thinking-block signature; PROBABLY API-REQUIRED, reported
                       separately as 'probably-required', NOT asserted client-only

    'conversation_raw_bytes' = raw byte length of all user/assistant lines (matches
    raw_line_breakdown's 'conversation' chars). 'model_facing_estimate' subtracts
    only the two genuinely client-only fields (toolUseResult + usage), leaving the
    probably-required signature inside the estimate.
    """
    tur_bytes = usage_bytes = sig_bytes = 0
    tur_count = usage_count = sig_count = 0
    conv_lines = 0
    conv_raw_bytes = 0
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                n = len(line)
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if not isinstance(o, dict):
                    continue
                if o.get("type") not in _CONVERSATION_LINE_TYPES:
                    continue
                conv_lines += 1
                conv_raw_bytes += n
                # top-level toolUseResult (str or json)
                if "toolUseResult" in o:
                    tur = o["toolUseResult"]
                    tur_bytes += len(tur) if isinstance(tur, str) else len(
                        json.dumps(tur, ensure_ascii=False))
                    tur_count += 1
                msg = o.get("message")
                if isinstance(msg, dict):
                    if isinstance(msg.get("usage"), (dict, list)):
                        usage_bytes += len(json.dumps(msg["usage"], ensure_ascii=False))
                        usage_count += 1
                    elif isinstance(msg.get("usage"), str):
                        usage_bytes += len(msg["usage"]); usage_count += 1
                    content = msg.get("content")
                    if isinstance(content, list):
                        for b in content:
                            if isinstance(b, dict) and isinstance(b.get("signature"), str):
                                sig_bytes += len(b["signature"]); sig_count += 1
    except OSError:
        return {}

    client_only_bytes = tur_bytes + usage_bytes  # signature deliberately excluded
    model_facing = conv_raw_bytes - client_only_bytes
    return {
        "conversation_lines": conv_lines,
        "conversation_raw_bytes": conv_raw_bytes,
        "toolUseResult": {"count": tur_count, "bytes": tur_bytes},
        "usage": {"count": usage_count, "bytes": usage_bytes},
        "signature": {"count": sig_count, "bytes": sig_bytes},
        "client_only_field_bytes": client_only_bytes,
        "model_facing_estimate": model_facing,
        "model_facing_pct_of_conv": (
            round(100 * model_facing / conv_raw_bytes, 1) if conv_raw_bytes else 0),
    }


def _format_conversation_client_only_fields(cf: dict, bd: dict | None = None) -> str:
    """Render conversation_client_only_fields() + a short reconciliation note."""
    if not cf:
        return ""
    out = ["", c("CLIENT-ONLY FIELDS WITHIN CONVERSATION LINES", Colors.BOLD, Colors.BRIGHT_CYAN)]
    out.append(c("  (fat fields riding inside user/assistant lines that the model NEVER sees —", Colors.DIM))
    out.append(c("   RAW LINE BREAKDOWN counts these lines whole as 'conversation', overstating it)", Colors.DIM))
    conv = cf["conversation_raw_bytes"]
    out.append(f"  conversation raw bytes        {conv:>12,}   " + c("(user+assistant lines, whole)", Colors.DIM))
    out.append(c("  client-only fields (subtracted):", Colors.DIM))
    tur = cf["toolUseResult"]
    out.append(f"    toolUseResult (top-level)   {tur['bytes']:>12,}  in {tur['count']:>5,} lines   "
               + c("CLIENT-ONLY — duplicates tool_result output", Colors.YELLOW))
    us = cf["usage"]
    out.append(f"    message.usage               {us['bytes']:>12,}  in {us['count']:>5,} lines   "
               + c("CLIENT-ONLY — token accounting", Colors.YELLOW))
    out.append(f"    = client-only field bytes   {cf['client_only_field_bytes']:>12,}")
    sig = cf["signature"]
    out.append(f"  thinking signature            {sig['bytes']:>12,}  in {sig['count']:>5,} blocks  "
               + c("probably API-REQUIRED — NOT subtracted", Colors.DIM))
    out.append("")
    out.append(c(f"  MODEL-FACING ESTIMATE         {cf['model_facing_estimate']:>12,}   "
                 f"(conv raw − client-only fields = {cf['model_facing_pct_of_conv']}% of conv)",
                 Colors.BOLD, Colors.BRIGHT_GREEN))
    # ---- reconciliation note: three axes ----
    out.append("")
    out.append(c("  RECONCILIATION — three different axes (why the numbers differ):", Colors.BOLD))
    out.append(c("    1. SEMANTIC text (Totals block): rendered message text only — chars/words of", Colors.DIM))
    out.append(c("       actual prose/tool I/O. Excludes ALL JSON envelope + metadata + duplicated fields.", Colors.DIM))
    out.append(c("    2. FULL-FILE bytes (RAW LINE BREAKDOWN): every byte on disk — JSON envelope,", Colors.DIM))
    out.append(c("       per-record metadata (uuid/cwd/gitBranch/version/…), base64 images, AND the", Colors.DIM))
    out.append(c("       client-only fields above (esp. toolUseResult, which alone can be ~30% of file).", Colors.DIM))
    out.append(c("    3. MODEL-FACING estimate (this section): conversation raw bytes minus the", Colors.DIM))
    out.append(c("       client-only toolUseResult + usage fields — the closest of the three to what", Colors.DIM))
    out.append(c("       is actually streamed to the model. So Totals << Model-facing << Full-file.", Colors.DIM))
    return "\n".join(out)


# =============================================================================
# MODEL-FACING — BOTTOM-UP computation + KEEP/OFFLOADABLE/THINKING ledger (2026-06)
# Additive: a more accurate, bottom-up model-facing byte figure (summing only the
# JSON bytes of message.content BLOCKS) plus a decision ledger that splits that
# payload into conversational memory (KEEP), offloadable tool data (OFFLOADABLE,
# with the sub-512B headroom called out), and thinking/signature (THINKING).
# Read-only; does not touch parse_session / human_turn_indices / public APIs.
# =============================================================================

def model_facing_ledger(jsonl_path: Path) -> dict[str, Any]:
    """Bottom-up model-facing bytes + a KEEP / OFFLOADABLE / THINKING ledger.

    Walks raw user/assistant lines and sums the JSON bytes of the message.content
    BLOCKS only (text + thinking[incl signature] + tool_use + tool_result) — the
    actual API-request payload. This is the BOTTOM-UP figure: unlike the top-down
    conversation_client_only_fields estimate (conv raw − toolUseResult − usage),
    it ALSO excludes per-record client metadata (parentUuid, cwd, sessionId, uuid,
    timestamp, requestId, slug, isSidechain, version, message.id/model/stop_reason/
    usage, …), so it lines up with reality instead of overstating. Image blocks are
    excluded (byte-huge, token-cheap; counted as vision tokens elsewhere).

    Decomposes that payload into a decision ledger, OVERALL and per compaction
    interval:
      KEEP        — user-prompt text + assistant text (conversational memory).
      OFFLOADABLE — tool_use.input + tool_result.content (non-memory tool data),
                    split: already-stubbed / inline ≥ floor / inline < floor.
                    The inline-<floor bucket is the untapped headroom skipped by a
                    normal offload run (it sits below --min-bytes).
      OFFLOADABLE attachments — deferred_tools_delta / mcp_instructions_delta /
                    agent_listing_delta / hook_additional_context / skill_listing.
                    Separate top-level `attachment` records (NOT message.content), so
                    ADDITIONAL to the bottom-up figure — but model-facing (re-sent
                    every session-start/resume) and offloadable, same 3-way split.
      THINKING    — signature (the billed cost: encrypted FULL chain-of-thought;
                    server decrypts it to reconstruct the real thinking for the
                    prompt, so it counts against context and grows with thinking
                    size) + thinking text (only a SUMMARY, empty under
                    display:omitted, droppable). On Opus 4.5+/Sonnet 4.6+ prior-turn
                    thinking is kept and billed as input tokens; reclaimable only by
                    routing the turn off-chain (consolidation), NOT offloadable.

    Category buckets use INNER payload bytes (the reclaimable/semantic content);
    the per-block JSON envelope is reported as the gap to the bottom-up block-JSON
    total. Approx tokens ≈ bytes / 4.
    """
    try:
        from uai_toolkit.jsonl import lib_jsonl_archive as _lja
        offload_prefixes = tuple(_lja.STUB_PREFIXES)
        min_floor = _lja.MIN_BYTES
        _wire = _lja.wire_size
        _is_stub = _lja.is_stub
    except Exception:
        offload_prefixes, _ = _stub_prefixes()

        def _wire(v):
            return len(v) if isinstance(v, str) else len(json.dumps(v, ensure_ascii=False))

        def _is_stub(v):
            return isinstance(v, str) and v.lstrip().startswith(offload_prefixes)
        min_floor = 512

    def _is_attachment_stub(v):
        # shape-preserving: list-typed attachment fields hold [stub], string-typed a bare stub
        if _is_stub(v):
            return True
        return isinstance(v, list) and len(v) == 1 and _is_stub(v[0])

    def _blank():
        return {
            "keep": {"user": 0, "assistant": 0},
            "offloadable": {
                "stubbed": {"count": 0, "bytes": 0},
                "inline_ge": {"count": 0, "bytes": 0},
                "inline_lt": {"count": 0, "bytes": 0},
            },
            # Attachment records (deferred_tools_delta / mcp_instructions_delta /
            # agent_listing_delta / hook_additional_context / skill_listing): separate
            # top-level records, NOT message.content, but model-facing (re-sent each
            # resume) and offloadable. Tracked in their own category (todo_0375).
            "attachment": {
                "stubbed": {"count": 0, "bytes": 0},
                "inline_ge": {"count": 0, "bytes": 0},
                "inline_lt": {"count": 0, "bytes": 0},
            },
            "thinking": {"text_bytes": 0, "sig_bytes": 0, "count": 0},
            "block_json_bytes": 0,   # bottom-up: Σ len(json.dumps(block))
            "inner_bytes": 0,        # Σ inner payloads attributed to categories
        }

    intervals = compaction_intervals(jsonl_path)
    iv_acc = {iv["index"]: _blank() for iv in intervals}
    overall = _blank()
    last_index = intervals[-1]["index"]

    def _which(lineno: int):
        for iv in intervals:
            if iv["start_line"] <= lineno <= iv["end_line"]:
                return iv["index"]
        return None

    def _result_is_stub(v) -> bool:
        if _is_stub(v):
            return True
        if isinstance(v, list):
            return any(isinstance(s, dict) and _is_stub(s.get("text")) for s in v)
        return False

    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                if not isinstance(o, dict):
                    continue
                ltype = o.get("type")
                idx = _which(i)
                accs = [overall] + ([iv_acc[idx]] if idx is not None else [])
                # Attachment records (deferred_tools_delta et al.): model-facing,
                # offloadable, but NOT message.content — bucket into the attachment
                # category (per attachment.<key> field) and skip the block walk below.
                # (todo_0375) Not added to block_json_bytes/inner_bytes, which remain
                # the message.content bottom-up figure.
                if ltype == "attachment":
                    att = o.get("attachment")
                    if isinstance(att, dict):
                        for _k, _v in att.items():
                            if _k == "type" or _v is None:
                                continue
                            _inner = _wire(_v)
                            if _is_attachment_stub(_v):
                                _bkt = "stubbed"
                            elif _inner >= min_floor:
                                _bkt = "inline_ge"
                            else:
                                _bkt = "inline_lt"
                            for a in accs:
                                a["attachment"][_bkt]["count"] += 1
                                a["attachment"][_bkt]["bytes"] += _inner
                    continue
                if ltype not in _CONVERSATION_LINE_TYPES:
                    continue
                role = "user" if ltype == "user" else "assistant"
                msg = o.get("message")
                content = msg.get("content") if isinstance(msg, dict) else o.get("content")

                if isinstance(content, str):
                    bj = len(json.dumps(content, ensure_ascii=False))
                    inner = len(content)
                    for a in accs:
                        a["block_json_bytes"] += bj
                        a["inner_bytes"] += inner
                        a["keep"][role] += inner
                    continue
                if not isinstance(content, list):
                    continue

                for b in content:
                    if not isinstance(b, dict):
                        continue
                    bt = b.get("type")
                    if bt not in ("text", "thinking", "tool_use", "tool_result"):
                        continue
                    bj = len(json.dumps(b, ensure_ascii=False))
                    for a in accs:
                        a["block_json_bytes"] += bj

                    if bt == "text":
                        inner = len(b.get("text") or "")
                        for a in accs:
                            a["keep"][role] += inner
                            a["inner_bytes"] += inner
                    elif bt == "thinking":
                        tt = len(b.get("thinking") or "")
                        sg = len(b.get("signature") or "")
                        for a in accs:
                            a["thinking"]["text_bytes"] += tt
                            a["thinking"]["sig_bytes"] += sg
                            a["thinking"]["count"] += 1
                            a["inner_bytes"] += tt + sg
                    else:  # tool_use / tool_result — OFFLOADABLE non-memory
                        if bt == "tool_use":
                            payload = b.get("input")
                            is_stub = isinstance(payload, dict) and any(
                                _is_stub(v) for v in payload.values())
                        else:
                            payload = b.get("content")
                            is_stub = _result_is_stub(payload)
                        inner = _wire(payload) if payload is not None else 0
                        if is_stub:
                            bucket = "stubbed"
                        elif inner >= min_floor:
                            bucket = "inline_ge"
                        else:
                            bucket = "inline_lt"
                        for a in accs:
                            a["offloadable"][bucket]["count"] += 1
                            a["offloadable"][bucket]["bytes"] += inner
                            a["inner_bytes"] += inner
    except OSError:
        return {}

    return {
        "min_floor": min_floor,
        "model_facing_bottom_up": overall["block_json_bytes"],
        "overall": overall,
        "live_index": last_index,
        "live": iv_acc.get(last_index),
        "intervals": iv_acc,
    }


def _format_model_facing_ledger(ml: dict, cf: dict | None = None,
                                semantic_chars: int | None = None,
                                show_intervals: list | None = None) -> str:
    """Render model_facing_ledger(): bottom-up figure + decision ledger.

    show_intervals: interval indices to render alongside OVERALL (from --interval).
    None (default) renders the LIVE (last) interval only.

    COLOR KEY (consistent): bytes/chars = normal · tokens = dim · SECTION header =
    cyan · totals = bold · YELLOW = untapped reclaim (below the --min-bytes floor,
    not captured today) — yellow means that one thing only."""
    if not ml or not ml.get("overall"):
        return ""
    floor = ml["min_floor"]
    bu = ml["model_facing_bottom_up"]
    ov = ml["overall"]

    def _n(x):
        return c(f"{x:>13,}", Colors.DIM)                       # bytes de-emphasized (dim)

    def _tok(x):
        return c(f"~{x // 4:>10,} tok", Colors.BRIGHT_WHITE)    # tokens undimmed

    out = ["", c("MODEL-FACING — BOTTOM-UP + LEDGER", Colors.BOLD, Colors.BRIGHT_GREEN)]
    out.append(c("  (bottom-up = Σ JSON bytes of message.content BLOCKS only [text+thinking+tool_use+", Colors.DIM))
    out.append(c("   tool_result] — the actual API request payload. Excludes per-record client metadata", Colors.DIM))
    out.append(c("   uuid/cwd/sessionId/timestamp/requestId/message.id/model/usage/… AND toolUseResult.)", Colors.DIM))
    out.append("")
    out.append(c(f"  MODEL-FACING BOTTOM-UP        {_n(bu)}   {_tok(bu)}", Colors.BOLD, Colors.BRIGHT_GREEN))
    if cf and cf.get("model_facing_estimate") is not None:
        td = cf["model_facing_estimate"]
        gap = td - bu
        out.append(f"  top-down estimate (old)       {_n(td)}   " + c("conv raw − toolUseResult − usage (OVERSTATES)", Colors.DIM))
        out.append(f"  gap (top-down − bottom-up)    {_n(gap)}   " + c("= per-record CLIENT METADATA, also NOT sent", Colors.DIM))
    if semantic_chars:
        ratio = bu / semantic_chars if semantic_chars else 0
        out.append(f"  Totals semantic chars         {_n(semantic_chars)}   "
                   + c(f"bottom-up / semantic = {ratio:.2f}x  (JSON-escaping/structure, not 8.5x)", Colors.DIM))
    env = ov["block_json_bytes"] - ov["inner_bytes"]
    out.append(f"  per-block JSON envelope       {_n(env)}   " + c("(block type tags/ids/braces; bottom-up − ledger payload)", Colors.DIM))

    # Semantic colors: GREEN = offloadable now · BLUE = not offloadable · LIGHT-BLUE =
    # sub-floor (could, but the stub would be bigger than the content — net-negative).
    STUB_BYTES = 265        # ≈ bytes a single offload stub leaves behind (ref/sha/sizes)
    LBL_W = 26
    GREEN, BLUE, LBLUE = Colors.BRIGHT_GREEN, Colors.BLUE, Colors.BRIGHT_BLUE

    def _row(label, bytes_, color, count=None, unit="blocks", note="", bold=False):
        codes = (Colors.BOLD, color) if bold else (color,)
        lbl = c(f"{label:<{LBL_W}}", *codes)
        by = c(f"{bytes_:>13,}", Colors.DIM)                        # bytes DIMMED (de-emphasized)
        tk = c(f"~{bytes_ // 4:>10,} tok", *codes)                 # tokens colored + undimmed
        cnt = f"  in {count:>6,} {unit}" if count is not None else ""
        nt = ("  " + c(note, Colors.DIM)) if note else ""
        return f"      {lbl} {by}   {tk}{cnt}{nt}"

    def _offload_group(st, ge, lt, unit):
        # st = already-stubbed (done) · ge = inline>=floor (OFFLOADABLE now) · lt = headroom (below floor)
        non_off = st["bytes"] + lt["bytes"]
        refs = ge["count"] * STUB_BYTES
        net = max(0, ge["bytes"] - refs)
        return [
            _row("already-stubbed", st["bytes"], BLUE, st["count"], unit, "already offloaded — residual stub cost"),
            _row(f"inline < {floor}B (headroom)", lt["bytes"], LBLUE, lt["count"], unit, "below floor — offloading = net-negative"),
            _row(f"inline >= {floor}B", ge["bytes"], GREEN, ge["count"], unit, "a normal run pages these out"),
            "      " + c("─" * 62, Colors.DIM),
            _row("= NON-OFFLOADABLE", non_off, BLUE, note="stubbed + sub-floor — a normal run won't reduce it", bold=True),
            _row("= OFFLOADABLE", ge["bytes"], GREEN, note="a normal run pages out this much…", bold=True),
            _row("−  offload stub refs", refs, Colors.DIM, note=f"…leaving ~{STUB_BYTES}B × {ge['count']:,} stubs behind"),
            _row("= NET SAVINGS", net, GREEN, note="ACTUAL reduction realized on next resume", bold=True),
        ]

    def _ledger_block(title: str, a: dict) -> list[str]:
        off, th, at = a["offloadable"], a["thinking"], a["attachment"]
        keep_u, keep_a = a["keep"]["user"], a["keep"]["assistant"]
        L = [c(f"  {title}", Colors.BOLD)]
        L.append(c("    KEEP  conversational memory (user prompts + assistant text) — never offloaded", Colors.BRIGHT_CYAN))
        L.append(_row("user prompts", keep_u, Colors.BRIGHT_WHITE))
        L.append(_row("assistant text", keep_a, Colors.BRIGHT_WHITE))
        L.append(_row("= KEEP total", keep_u + keep_a, Colors.BRIGHT_WHITE, bold=True))
        L.append(c("    OFFLOADABLE non-memory  tool_use.input + tool_result.content (inner payload)", Colors.BRIGHT_CYAN))
        L += _offload_group(off["stubbed"], off["inline_ge"], off["inline_lt"], "blocks")
        L.append(c("    THINKING  consolidation-only — NOT offloadable (route the turn off-chain to shed)", Colors.BRIGHT_CYAN))
        L.append(_row("thinking text", th["text_bytes"], BLUE, th["count"], "blocks", "SUMMARY only / often empty — droppable"))
        L.append(_row("signature", th["sig_bytes"], BLUE, note="the billed cost — encrypted full CoT, grows with thinking"))
        if at["stubbed"]["count"] or at["inline_ge"]["count"] or at["inline_lt"]["count"]:
            L.append(c("    OFFLOADABLE attachments  deferred_tools_delta / mcp / agent / hook_context  (ADDITIONAL to above)", Colors.BRIGHT_CYAN))
            L.append(c("      (separate top-level records, NOT message.content — model-facing, re-sent every resume)", Colors.DIM))
            L += _offload_group(at["stubbed"], at["inline_ge"], at["inline_lt"], "fields")
        return L

    out.append("")
    out.append(c("  COLOR KEY  bytes = dim (de-emphasized) · tokens = colored & undimmed (what matters) · SECTION = cyan", Colors.DIM))
    out.append(c("             GREEN = offloadable now · BLUE = not offloadable · LIGHT-BLUE = sub-floor (could, but net-negative)", Colors.DIM))
    out.append("")
    out.extend(_ledger_block("LEDGER — OVERALL (whole file)", ov))
    intervals = ml.get("intervals") or {}
    if show_intervals:
        for idx in show_intervals:
            a = intervals.get(idx)
            out.append("")
            if a is None:
                out.append(c(f"  LEDGER — interval {idx}: (no data for this interval)", Colors.YELLOW))
                continue
            tag = " LIVE" if idx == ml.get("live_index") else ""
            out.extend(_ledger_block(f"LEDGER —{tag} interval {idx}", a))
    else:
        live = ml.get("live")
        if live is not None and ml.get("live_index") not in (None, 0):
            out.append("")
            out.extend(_ledger_block(f"LEDGER — LIVE interval {ml['live_index']} (post-last-compaction, current context)", live))
    out.append("")
    out.append(c("  NOTE: THINKING is reclaimable ONLY by routing the turn off-chain (consolidation),", Colors.DIM))
    out.append(c("        NOT by offloading — the block cannot be stubbed while it stays on-chain.", Colors.DIM))
    out.append(c("  VERIFIED (Anthropic extended-thinking doc + our own experiment): the `signature`", Colors.DIM))
    out.append(c("        carries the ENCRYPTED FULL chain-of-thought; the server decrypts it to", Colors.DIM))
    out.append(c("        reconstruct the real thinking for prompt construction, so the SIGNATURE is", Colors.DIM))
    out.append(c("        the part that counts against context and it grows with thinking size. The", Colors.DIM))
    out.append(c("        visible `thinking` text is only a SUMMARY (empty under display:omitted) and", Colors.DIM))
    out.append(c("        can be dropped with impunity. On Opus 4.5+/Sonnet 4.6+ prior-turn thinking is", Colors.DIM))
    out.append(c("        kept by default and billed as input tokens; on pre-4.5 Opus/Sonnet + all", Colors.DIM))
    out.append(c("        Haiku it is instead stripped and not billed.", Colors.DIM))
    return "\n".join(out)


# =============================================================================
# Compaction detection + intervals + client-only line inclusion
# =============================================================================
#
# A "compaction event" is where the CLI summarized the prior conversation and
# replaced it with a fresh system message (the "new system messaging"). It is
# detected on a RAW line carrying the JSON field `isCompactSummary == true`.
# The `type=="system"` line with `subtype=="compact_boundary"` that immediately
# precedes the summary is part of the same event; the event's START LINE is the
# earliest of the two (the boundary line if present immediately before, else the
# summary line itself). These markers can live on RAW lines that parse_session
# drops, so detection scans the raw file directly.


def _raw_line_count(jsonl_path: Path) -> int:
    """Count raw lines in a JSONL file (1 line == 1 record)."""
    n = 0
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
            for _ in fh:
                n += 1
    except OSError:
        return 0
    return n


# Compaction-interval enumeration + SPEC selection are now the CANONICAL single
# source of truth in lib_jsonl_archive (next to is_turn_start / classify_record).
# read_jsonl was the origin of this logic and now DELEGATES to the canonical copies
# via thin aliases so the interval NUMBERING (0=prologue, 1..N, last/live=final)
# can never diverge from context_stats / turn_digest. These aliases keep every
# existing read_jsonl call site + test working unchanged.
find_compactions = _lja.find_compactions
compaction_intervals = _lja.compaction_intervals
_select_intervals = _lja.select_intervals


def _apply_interval_filter(msgs: list[Message], selected: list[dict]) -> list[Message]:
    """Keep only messages whose source_line falls within a selected interval.

    Membership is LINE-RANGE based (the canonical interval partition); reuses the
    shared lib_jsonl_archive helpers so read_jsonl and the reclaim tools apply the
    identical interval boundaries."""
    if not selected:
        return msgs
    ranges = _lja.interval_line_ranges(selected)
    return [m for m in msgs if _lja.line_in_intervals(m.source_line, ranges)]


def _meta_preview(obj: dict, limit: int = 200) -> str:
    """Compact one-line preview of a raw client-only record (sans `type`)."""
    payload = {k: v for k, v in obj.items() if k != "type"}
    try:
        s = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        s = str(payload)
    s = s.replace("\n", " ").replace("\r", " ")
    if len(s) > limit:
        s = s[:limit] + "…"
    return s


def client_only_meta_messages(jsonl_path: Path) -> list[Message]:
    """Build META Message objects for every RAW line whose `type` is NOT a
    conversation type (i.e. client-only: attachment, file-history-snapshot,
    system, mode, custom-title, agent-name, agent-color, permission-mode,
    bridge-session, last-prompt, queue-operation, progress, ...).

    parse_session drops these; this surfaces them so --include-client-only can
    merge them inline. Each carries source_line for sorting/filtering.
    """
    metas: list[Message] = []
    try:
        with open(jsonl_path, encoding="utf-8", errors="replace") as fh:
            for i, line in enumerate(fh, start=1):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if not isinstance(obj, dict):
                    continue
                ltype = obj.get("type", "?")
                if ltype in _CONVERSATION_LINE_TYPES:
                    continue
                metas.append(Message(
                    role="meta",
                    type=MessageType.META,
                    content=f"[{ltype}] {_meta_preview(obj)}",
                    timestamp=_normalize_timestamp(obj.get("timestamp", "")) if obj.get("timestamp") else "",
                    source_line=i,
                    raw=obj,
                ))
    except OSError:
        return []
    return metas


def session_summary(jsonl_path: Path, platform: str | None = None) -> dict[str, Any]:
    """Get summary info for a session file."""
    msgs = parse_session(jsonl_path, platform=platform)
    if not msgs:
        return {"message_count": 0, "raw_line_breakdown": raw_line_breakdown(jsonl_path)}

    text_msgs = [m for m in msgs if m.type in (MessageType.USER, MessageType.RESPONSE)]
    first_user = next((m for m in text_msgs if m.role == "user"), None)

    return {
        "message_count": len(msgs),
        "text_messages": len(text_msgs),
        "user_messages": sum(1 for m in text_msgs if m.role == "user"),
        "assistant_messages": sum(1 for m in text_msgs if m.role == "assistant"),
        "tool_calls": sum(1 for m in msgs if m.type == MessageType.TOOL_USE),
        "first_timestamp": msgs[0].timestamp,
        "last_timestamp": msgs[-1].timestamp,
        "platform": msgs[0].platform,
        "first_message_preview": (first_user.content[:120] + "...") if first_user else "",
        "file_size_bytes": jsonl_path.stat().st_size,
        "raw_line_breakdown": raw_line_breakdown(jsonl_path),
    }


def _count_words(text: str) -> int:
    return len(text.split()) if text else 0


def _size_str(chars: int, words: int) -> str:
    """Format chars | words for display."""
    return f"{chars:>8,} chars | {words:>6,} words"


def _tally_by_type(msgs: list[Message]) -> dict:
    """Per-type counts/chars/words for a list of Messages.

    Uses the EXACT same categorization as session_stats' day-loop so that
    interval tallies sum to the whole-session totals:
      USER -> user, RESPONSE -> ai, TOOL_USE+TOOL_RESULT -> tools,
      THINKING -> think (chars only). For TOOL_USE the JSON-serialized
      tool_input is added to the char/word counts (matching the day-loop).
    `chars`/`words` are the running totals across ALL message types (the value
    shown on the whole-session "Turns" line), so uncategorized types still
    contribute there. Returns a dict mirroring the `totals` per-type shape.
    """
    acc = {
        "messages": 0,
        "chars": 0, "words": 0,
        "user": {"count": 0, "chars": 0, "words": 0},
        "ai": {"count": 0, "chars": 0, "words": 0},
        "tools": {"count": 0, "chars": 0, "words": 0},
        "thinking": {"count": 0, "chars": 0},
    }
    for m in msgs:
        acc["messages"] += 1
        if m.type == MessageType.TOOL_USE and m.tool_input:
            input_str = json.dumps(m.tool_input) if isinstance(m.tool_input, dict) else str(m.tool_input)
            mc = len(m.content) + len(input_str)
            mw = _count_words(m.content) + _count_words(input_str)
        else:
            mc = len(m.content)
            mw = _count_words(m.content)
        acc["chars"] += mc
        acc["words"] += mw
        if m.type == MessageType.USER:
            acc["user"]["count"] += 1; acc["user"]["chars"] += mc; acc["user"]["words"] += mw
        elif m.type == MessageType.RESPONSE:
            acc["ai"]["count"] += 1; acc["ai"]["chars"] += mc; acc["ai"]["words"] += mw
        elif m.type in (MessageType.TOOL_USE, MessageType.TOOL_RESULT):
            acc["tools"]["count"] += 1; acc["tools"]["chars"] += mc; acc["tools"]["words"] += mw
        elif m.type == MessageType.THINKING:
            acc["thinking"]["count"] += 1; acc["thinking"]["chars"] += mc
    return acc


def session_stats(jsonl_path: Path, platform: str | None = None,
                  fmt: str = "text", show_tools: bool = False,
                  split_offloaded: bool = False) -> str | dict:
    """Generate detailed statistics for a session.

    Returns formatted text or a structured dict (fmt='json').

    When split_offloaded is True (text format only), a co-located Full/Stub
    breakout is inlined under each User/AI/Tools line in the per-Day, Totals,
    and per-compaction-interval sections.
    """
    msgs = parse_session(jsonl_path, platform=platform)
    if not msgs:
        return "No messages found." if fmt == "text" else {"error": "no messages"}

    turns = group_into_turns(msgs)
    days = group_by_day(turns)

    # Detect system prompt (first system/meta messages before first user)
    sys_chars = 0
    sys_words = 0
    for m in msgs:
        if m.type in (MessageType.USER, MessageType.RESPONSE):
            break
        if m.type in (MessageType.SYSTEM, MessageType.META):
            sys_chars += len(m.content)
            sys_words += _count_words(m.content)

    # Per-tool-name accumulator
    def _new_tool_acc():
        return {"count": 0, "chars": 0, "words": 0,
                "input_chars": 0, "result_chars": 0, "result_words": 0}

    def _merge_tool_acc(dst, src):
        for k in dst:
            dst[k] += src[k]

    # Per-day stats
    day_stats = []
    total_turns = 0
    total_chars = 0
    total_words = 0
    total_user_n = 0
    total_user_chars = 0
    total_user_words = 0
    total_ai_n = 0
    total_ai_chars = 0
    total_ai_words = 0
    total_tool_n = 0
    total_tool_chars = 0
    total_tool_words = 0
    total_thinking_n = 0
    total_thinking_chars = 0
    total_tool_detail: dict[str, dict] = {}

    # Build call_id → tool_name lookup from all messages
    call_id_to_name: dict[str, str] = {}
    for m in msgs:
        if m.type == MessageType.TOOL_USE and m.tool_call_id and m.tool_name:
            call_id_to_name[m.tool_call_id] = m.tool_name

    for day in days:
        d_turns = len(day.turns)
        d_user_n = d_user_chars = d_user_words = 0
        d_ai_n = d_ai_chars = d_ai_words = 0
        d_tool_n = d_tool_chars = d_tool_words = 0
        d_thinking_n = d_thinking_chars = 0
        d_chars = d_words = 0
        d_first_ts = d_last_ts = ""
        d_tool_detail: dict[str, dict] = {}

        for turn in day.turns:
            for m in turn.messages:
                # For tool messages, count tool_input content too
                if m.type == MessageType.TOOL_USE and m.tool_input:
                    input_str = json.dumps(m.tool_input) if isinstance(m.tool_input, dict) else str(m.tool_input)
                    mc = len(m.content) + len(input_str)
                    mw = _count_words(m.content) + _count_words(input_str)
                else:
                    mc = len(m.content)
                    mw = _count_words(m.content)
                d_chars += mc
                d_words += mw
                if not d_first_ts and m.timestamp:
                    d_first_ts = m.timestamp
                if m.timestamp:
                    d_last_ts = m.timestamp

                if m.type == MessageType.USER:
                    d_user_n += 1; d_user_chars += mc; d_user_words += mw
                elif m.type == MessageType.RESPONSE:
                    d_ai_n += 1; d_ai_chars += mc; d_ai_words += mw
                elif m.type == MessageType.TOOL_USE:
                    d_tool_n += 1; d_tool_chars += mc; d_tool_words += mw
                    tname = m.tool_name or "unknown"
                    if tname not in d_tool_detail:
                        d_tool_detail[tname] = _new_tool_acc()
                    d_tool_detail[tname]["count"] += 1
                    input_str = json.dumps(m.tool_input) if isinstance(m.tool_input, dict) else str(m.tool_input)
                    d_tool_detail[tname]["input_chars"] += len(input_str)
                    d_tool_detail[tname]["chars"] += mc
                    d_tool_detail[tname]["words"] += mw
                elif m.type == MessageType.TOOL_RESULT:
                    d_tool_n += 1; d_tool_chars += mc; d_tool_words += mw
                    tname = m.tool_name or call_id_to_name.get(m.tool_call_id, "") or "unknown"
                    if tname not in d_tool_detail:
                        d_tool_detail[tname] = _new_tool_acc()
                    d_tool_detail[tname]["result_chars"] += mc
                    d_tool_detail[tname]["result_words"] += mw
                elif m.type == MessageType.THINKING:
                    d_thinking_n += 1; d_thinking_chars += mc

        ds = {
            "date": day.date, "label": day.label,
            "time_range": [_ts_to_local(d_first_ts), _ts_to_local(d_last_ts)],
            "turns": d_turns, "chars": d_chars, "words": d_words,
            "user": {"count": d_user_n, "chars": d_user_chars, "words": d_user_words},
            "ai": {"count": d_ai_n, "chars": d_ai_chars, "words": d_ai_words},
            "tools": {"count": d_tool_n, "chars": d_tool_chars, "words": d_tool_words},
            "tool_detail": d_tool_detail,
            "thinking": {"count": d_thinking_n, "chars": d_thinking_chars},
        }
        day_stats.append(ds)
        total_turns += d_turns
        total_chars += d_chars; total_words += d_words
        total_user_n += d_user_n; total_user_chars += d_user_chars; total_user_words += d_user_words
        total_ai_n += d_ai_n; total_ai_chars += d_ai_chars; total_ai_words += d_ai_words
        total_tool_n += d_tool_n; total_tool_chars += d_tool_chars; total_tool_words += d_tool_words
        total_thinking_n += d_thinking_n; total_thinking_chars += d_thinking_chars
        for tname, tacc in d_tool_detail.items():
            if tname not in total_tool_detail:
                total_tool_detail[tname] = _new_tool_acc()
            _merge_tool_acc(total_tool_detail[tname], tacc)

    first_ts = _ts_to_local(msgs[0].timestamp) if msgs[0].timestamp else "?"
    last_ts = _ts_to_local(msgs[-1].timestamp) if msgs[-1].timestamp else "?"

    result = {
        "file": str(jsonl_path),
        "file_size_bytes": jsonl_path.stat().st_size,
        "platform": msgs[0].platform,
        "date_range": [first_ts, last_ts],
        "num_days": len(days),
        "system_prompt": {"chars": sys_chars, "words": sys_words},
        "days": day_stats,
        "totals": {
            "turns": total_turns, "chars": total_chars, "words": total_words,
            "user": {"count": total_user_n, "chars": total_user_chars, "words": total_user_words},
            "ai": {"count": total_ai_n, "chars": total_ai_chars, "words": total_ai_words},
            "tools": {"count": total_tool_n, "chars": total_tool_chars, "words": total_tool_words},
            "tool_detail": total_tool_detail,
            "thinking": {"count": total_thinking_n, "chars": total_thinking_chars},
            "messages": len(msgs),
        },
    }

    # ---- Per-compaction-interval breakdown ----
    # Same per-type tally (via _tally_by_type) applied to the messages whose
    # raw source_line falls inside each interval. Sums to the whole-session
    # totals (modulo any messages with source_line == 0, which can't be placed).
    intervals = compaction_intervals(jsonl_path)
    last_index = intervals[-1]["index"]
    interval_stats = []
    interval_splits: dict[int, dict] = {}
    for iv in intervals:
        idx, s, e = iv["index"], iv["start_line"], iv["end_line"]
        if e >= s:
            in_msgs = [m for m in msgs if m.source_line and s <= m.source_line <= e]
            in_turns = sum(
                1 for tn in turns
                if tn.messages and tn.messages[0].source_line
                and s <= tn.messages[0].source_line <= e
            )
        else:
            in_msgs, in_turns = [], 0
        if split_offloaded:
            interval_splits[idx] = split_offloaded_tally(in_msgs)
        interval_stats.append({
            "index": idx, "start_line": s, "end_line": e,
            "is_prologue": iv["is_prologue"], "is_live": (idx == last_index),
            "turns": in_turns, **_tally_by_type(in_msgs),
        })
    result["intervals"] = interval_stats

    if fmt == "json":
        return result

    # Text format
    S = _size_str

    # --split-offloaded: co-located Full/Stub breakouts (per-Day, Totals, interval)
    total_split = split_offloaded_tally(msgs) if split_offloaded else None
    day_splits = ([split_offloaded_tally([m for tn in day.turns for m in tn.messages])
                   for day in days] if split_offloaded else None)

    def _split_sub(cat: dict) -> list[str]:
        """Two indented sub-lines (Full / Stub) for one role's split tally."""
        f, st = cat["full"], cat["stub"]
        return [
            c(f"        Full: {f['count']:>4}  | {S(f['chars'], f['words'])}", Colors.DIM),
            c(f"        Stub: {st['count']:>4}  | {S(st['chars'], st['words'])}", Colors.YELLOW),
        ]

    lines = [
        c("Stats Summary", Colors.BOLD, Colors.BRIGHT_CYAN),
        f"  File:     {jsonl_path.name} ({result['file_size_bytes']:,} bytes)",
        f"  Platform: {result['platform']}",
        f"  Date Range: {first_ts}  —  {last_ts}",
        f"  Num Days:   {len(days)}",
        f"  System Prompt: {S(sys_chars, sys_words)}",
        "",
    ]

    def _render_tool_detail(detail: dict, indent: str = "        ") -> list[str]:
        """Render per-tool breakdown, sorted by total chars descending."""
        if not detail:
            return []
        sorted_tools = sorted(detail.items(), key=lambda kv: kv[1]["chars"] + kv[1].get("result_chars", 0), reverse=True)
        out = []
        for tname, ta in sorted_tools:
            total_c = ta["chars"] + ta.get("result_chars", 0)
            total_w = ta["words"] + ta.get("result_words", 0)
            calls = ta["count"]
            res_c = ta.get("result_chars", 0)
            label = c(f"{tname}", Colors.YELLOW)
            out.append(f"{indent}{label}: {calls:>4} calls | {S(total_c, total_w)}")
            if res_c:
                out.append(f"{indent}  input: {ta['input_chars']:>8,} chars  results: {res_c:>8,} chars")
        return out

    for i, ds in enumerate(day_stats):
        lines.append(c(f"  Day {i+1}: {ds['label']}", Colors.BOLD))
        lines.append(f"    {ds['time_range'][0]}  —  {ds['time_range'][1]}")
        lines.append(f"    Turns: {ds['turns']:>4}  | {S(ds['chars'], ds['words'])}")
        lines.append(f"      User:   {ds['user']['count']:>4}  | {S(ds['user']['chars'], ds['user']['words'])}")
        if split_offloaded:
            lines.extend(_split_sub(day_splits[i]['user']))
        lines.append(f"      AI:     {ds['ai']['count']:>4}  | {S(ds['ai']['chars'], ds['ai']['words'])}")
        if split_offloaded:
            lines.extend(_split_sub(day_splits[i]['ai']))
        lines.append(f"      Tools:  {ds['tools']['count']:>4}  | {S(ds['tools']['chars'], ds['tools']['words'])}")
        if split_offloaded:
            lines.extend(_split_sub(day_splits[i]['tools']))
        if ds['thinking']['count']:
            lines.append(f"      Think:  {ds['thinking']['count']:>4}  | {ds['thinking']['chars']:>8,} chars")
        if show_tools and ds.get('tool_detail'):
            lines.extend(_render_tool_detail(ds['tool_detail']))
        lines.append("")

    lines.append(c("  Totals:", Colors.BOLD, Colors.BRIGHT_CYAN)
                 + c("   (SEMANTIC roles: User=human prompts, Tools=tool_use+tool_result, AI=text, Think=thinking)", Colors.DIM))
    lines.append(c("    [!] 'User'/'AI' here are SEMANTIC; the RAW LINE BREAKDOWN below reuses 'user'/'assistant'", Colors.YELLOW))
    lines.append(c("        as raw line TYPES (tool_result is a 'user' line) — same words, different axis.", Colors.DIM))
    t = result['totals']
    lines.append(f"    Messages: {t['messages']:>4}")
    lines.append(f"    Turns:    {t['turns']:>4}  | {S(t['chars'], t['words'])}")
    lines.append(f"      User:   {t['user']['count']:>4}  | {S(t['user']['chars'], t['user']['words'])}")
    if split_offloaded:
        lines.extend(_split_sub(total_split['user']))
    lines.append(f"      AI:     {t['ai']['count']:>4}  | {S(t['ai']['chars'], t['ai']['words'])}")
    if split_offloaded:
        lines.extend(_split_sub(total_split['ai']))
    lines.append(f"      Tools:  {t['tools']['count']:>4}  | {S(t['tools']['chars'], t['tools']['words'])}")
    if split_offloaded:
        lines.extend(_split_sub(total_split['tools']))
    if t['thinking']['count']:
        lines.append(f"      Think:  {t['thinking']['count']:>4}  | {t['thinking']['chars']:>8,} chars")
    if show_tools and t.get('tool_detail'):
        lines.append(c("    Tool Breakdown:", Colors.BOLD))
        lines.extend(_render_tool_detail(t['tool_detail'], indent="      "))

    # ---- BY COMPACTION INTERVAL ----
    lines.append("")
    lines.append(c("  BY COMPACTION INTERVAL", Colors.BOLD, Colors.BRIGHT_CYAN))
    lines.append(c(
        f"    {len(interval_stats)} interval(s); Turns = user-prompt messages "
        f"whose source line falls in the interval", Colors.DIM))
    lines.append("")
    for istat in interval_stats:
        s, e = istat["start_line"], istat["end_line"]
        rng = f"{s}-{e}" if e >= s else "(empty)"
        tags = []
        if istat["is_prologue"]:
            tags.append("prologue")
        if istat["is_live"]:
            tags.append("LIVE")
        tag = (", " + ", ".join(tags)) if tags else ""
        lines.append(c(f"  Interval {istat['index']}  (lines {rng}{tag})", Colors.BOLD))
        lines.append(f"    Turns:  {istat['turns']:>4}  | {S(istat['chars'], istat['words'])}")
        lines.append(f"      User:   {istat['user']['count']:>4}  | {S(istat['user']['chars'], istat['user']['words'])}")
        if split_offloaded:
            lines.extend(_split_sub(interval_splits[istat['index']]['user']))
        lines.append(f"      AI:     {istat['ai']['count']:>4}  | {S(istat['ai']['chars'], istat['ai']['words'])}")
        if split_offloaded:
            lines.extend(_split_sub(interval_splits[istat['index']]['ai']))
        lines.append(f"      Tools:  {istat['tools']['count']:>4}  | {S(istat['tools']['chars'], istat['tools']['words'])}")
        if split_offloaded:
            lines.extend(_split_sub(interval_splits[istat['index']]['tools']))
        if istat['thinking']['count']:
            lines.append(f"      Think:  {istat['thinking']['count']:>4}  | {istat['thinking']['chars']:>8,} chars")
        lines.append("")

    lines.append(c("─" * 60, Colors.DIM))

    return "\n".join(lines)


def list_sessions(platform: str | None = None, limit: int = 20) -> list[dict[str, Any]]:
    """List recent sessions across one or all platforms."""
    sessions = []
    
    # Helper to add a session
    def add_session(path: Path, p_name: str, uuid: str):
        try:
            mtime = datetime.fromtimestamp(path.stat().st_mtime).isoformat()
            sessions.append({
                "uuid": uuid,
                "timestamp": mtime,
                "platform": p_name,
                "path": str(path),
                "has_file": True,
            })
        except: pass

    # 1. Claude
    if not platform or platform == "claude":
        if PROJECTS_DIR.exists():
            for f in PROJECTS_DIR.rglob("*.jsonl"):
                add_session(f, "claude", f.stem)

    # 2. Codex
    if not platform or platform == "codex":
        for d in [CODEX_SESSIONS_DIR, CODEX_ARCHIVE_DIR]:
            if d.exists():
                for f in d.rglob("*.jsonl"):
                    if len(f.stem) >= 36:
                        add_session(f, "codex", f.stem[-36:])

    # 3. Gemini
    if not platform or platform == "gemini":
        if GEMINI_HISTORY_DIR.exists():
            for f in GEMINI_HISTORY_DIR.rglob("session-*.json"):
                # We use the partial UUID from filename for speed, 
                # or read it if it's a small file.
                uuid = f.stem[-8:]
                if f.stat().st_size < 10000: # only read if small
                    try:
                        with open(f) as jf:
                            data = json.load(jf)
                            uuid = data.get("sessionId", uuid)
                    except: pass
                add_session(f, "gemini", uuid)

    # Sort by timestamp (mtime)
    sessions.sort(key=lambda x: x["timestamp"], reverse=True)
    return sessions[:limit]


def format_messages(messages: list[dict], fmt: str = "text") -> str:
    """Format messages for output."""
    if fmt == "json":
        return json.dumps(messages, indent=2)
    elif fmt == "markdown":
        parts = []
        for m in messages:
            prefix = "**User**" if m["role"] == "user" else "**Assistant**"
            parts.append(f"{prefix} ({_ts_to_local(m['timestamp'])}):\n\n{m['content']}\n")
        return "\n---\n\n".join(parts)
    else:  # text
        parts = []
        for m in messages:
            prefix = "USER" if m["role"] == "user" else "ASSISTANT"
            parts.append(f"[{_ts_to_local(m['timestamp'])}] {prefix}:\n{m['content']}\n")
        return "\n" + "=" * 60 + "\n\n".join(parts)


# =============================================================================
# Range parsing
# =============================================================================


def _parse_range(range_str: str, total: int) -> tuple[int, int]:
    """Parse a range string (1-based) into 0-based start/end indices.

    Formats:
        '1-10'  -> messages 1 through 10
        '5-'    -> messages 5 through end
        '-20'   -> last 20 messages
    Returns (start, end) as 0-based indices suitable for slicing.
    """
    range_str = range_str.strip()
    if range_str.startswith("-"):
        # Last N messages
        n = int(range_str[1:])
        return max(0, total - n), total
    elif range_str.endswith("-"):
        # From N to end
        start = int(range_str[:-1]) - 1
        return max(0, start), total
    elif "-" in range_str:
        parts = range_str.split("-", 1)
        start = int(parts[0]) - 1
        end = int(parts[1])
        return max(0, start), min(total, end)
    else:
        # Single message
        idx = int(range_str) - 1
        return max(0, idx), min(total, idx + 1)


def _apply_range(messages: list, range_str: str | None) -> tuple[list, int]:
    """Apply range filter to a list of messages.

    Supports message ranges and turn ranges:
        '1-10'    -> messages 1 through 10
        '-20'     -> last 20 messages
        't1-10'   -> turns 1 through 10 (all messages within those turns)
        't-4'     -> last 4 turns
        't125-'   -> turns 125 through end
        't30'     -> turn 30 only

    Returns (filtered_messages, start_index) where start_index is the
    0-based offset of the first returned message in the original list.
    """
    if not range_str:
        return messages, 0

    range_str = range_str.strip()

    # Turn-based range: prefix with 't'
    if range_str.lower().startswith("t"):
        turn_range = range_str[1:]  # strip the 't' prefix
        # Real turns only (number >= 0); the `pre` prologue (-1) is not t-addressable.
        turns = [t for t in group_into_turns(messages) if t.number >= 0]
        t_start, t_end = _parse_range(turn_range, len(turns))
        selected_turns = turns[t_start:t_end]
        if not selected_turns:
            return [], 0
        # Collect all messages from selected turns
        selected_msgs = []
        for t in selected_turns:
            selected_msgs.extend(t.messages)
        # Find the offset of the first selected message in the original list
        if selected_msgs:
            first_msg = selected_msgs[0]
            offset = next((i for i, m in enumerate(messages) if m is first_msg), 0)
        else:
            offset = 0
        return selected_msgs, offset

    # Message-based range (default)
    start, end = _parse_range(range_str, len(messages))
    return messages[start:end], start


# =============================================================================
# REPL/CLI helpers
# =============================================================================


def _parse_flag(args: list[str], flag: str, multi: bool = False) -> str | None:
    """Extract a --flag value from args list, return None if absent.

    If multi=True, collects consecutive non-flag values after the flag
    and joins them with commas. Handles: --type user, response → "user,response"
    """
    if flag not in args:
        return None
    idx = args.index(flag)
    if idx + 1 >= len(args):
        return None
    if not multi:
        return args[idx + 1]
    # Collect all consecutive non-flag values
    values = []
    for i in range(idx + 1, len(args)):
        arg = args[i]
        if arg.startswith("--"):
            break
        # Strip commas and whitespace, skip empty
        cleaned = arg.strip().strip(",").strip()
        if cleaned:
            # Could contain comma-separated values itself
            for part in cleaned.split(","):
                part = part.strip()
                if part:
                    values.append(part)
    return ",".join(values) if values else None


def _strip_flags(args: list[str], flags: list[str], multi_flags: list[str] | None = None) -> list[str]:
    """Remove --flag value pairs from args, return remaining positional args.

    multi_flags: flags that consume all consecutive non-flag values (e.g., --type user, response).
    """
    multi_flags = multi_flags or []
    result = []
    skip_next = False
    skip_multi = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if skip_multi:
            if arg.startswith("--"):
                skip_multi = False
                # Fall through to check this arg
            else:
                continue  # Skip this value (belongs to multi-flag)
        if arg in multi_flags:
            skip_multi = True
            continue
        if arg in flags:
            skip_next = True
            continue
        if not arg.startswith("--"):
            result.append(arg)
    return result


def _sort_messages_by_ts(msgs: list[Message], order: str) -> list[Message]:
    """Sort messages by timestamp. order: 'newest' or 'oldest'."""
    def _sort_key(m: Message):
        ts = m.timestamp
        if not ts:
            return datetime.min
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt
        except (ValueError, TypeError):
            return datetime.min
    return sorted(msgs, key=_sort_key, reverse=(order == "newest"))


_TYPE_FILTER_ALIASES: dict[str, tuple[str, ...]] = {
    # Human-friendly aliases. Values are canonical MessageType.value strings.
    "assistant": ("response",),
    "ai": ("response",),
    "text": ("response",),
    "tool": ("tool_use", "tool_result"),
    "tools": ("tool_use", "tool_result"),
    "conversation": ("user", "response"),
    "messages": ("user", "response"),
    "nonmeta": ("user", "response", "thinking", "tool_use", "tool_result"),
}


def _parse_type_filter(type_str: str | None) -> list[str] | None:
    """Parse comma-separated type filter into canonical MessageType.value names.

    Accepts the historical exact values plus a few operator-friendly aliases:
    assistant/ai/text -> response, tool/tools -> tool_use+tool_result, and
    conversation/messages -> user+response. Unknown tokens are preserved so old
    callers that passed a future type keep the old no-match behavior rather than
    failing at parse time.
    """
    if not type_str:
        return None
    values: list[str] = []
    seen: set[str] = set()
    for raw in type_str.split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if token == "all":
            return None
        expanded = _TYPE_FILTER_ALIASES.get(token, (token,))
        for value in expanded:
            if value not in seen:
                values.append(value)
                seen.add(value)
    return values or None


def _parse_message_types_arg(args: list[str]) -> list[str] | None:
    """Parse --type or --types; --types is the clearer extraction spelling."""
    raw = _parse_flag(args, "--type", multi=True)
    if raw is None:
        raw = _parse_flag(args, "--types", multi=True)
    return _parse_type_filter(raw)


def _apply_type_filter(msgs: list[Message], type_values: list[str] | None) -> list[Message]:
    """Filter messages by type value(s)."""
    if not type_values:
        return msgs
    wanted = set(type_values)
    return [m for m in msgs if m.type.value in wanted]


def _turn_numbers_in_scope(messages: list[Message]) -> list[int]:
    """Distinct real turn numbers (>= 0) in message order; the `pre` prologue (-1)
    is excluded (not a numbered, t-addressable turn)."""
    nums: list[int] = []
    seen: set[int] = set()
    for m in messages:
        n = m.turn_number
        if n is None or n < 0 or n in seen:
            continue
        nums.append(n)
        seen.add(n)
    return nums


def _select_turn_numbers(spec: str, messages: list[Message]) -> tuple[set[int] | None, str | None]:
    """Resolve a --turns SPEC against the visible/scoped messages.

    SPEC is absolute by Message.turn_number, matching the Tn shown in output headers.
    The grammar (N, N-M, N-, -N last-N, comma lists, optional leading 't', last/live)
    is the CANONICAL shared one in lib_cli_common.select_turn_numbers — this delegates
    to it (passing the turn numbers visible in scope) so context_stats / turn_digest
    interpret --turns identically."""
    from uai_toolkit.cli import lib_cli_common as _lcc
    return _lcc.select_turn_numbers(spec, _turn_numbers_in_scope(messages))


def _apply_turn_filter(messages: list[Message], turn_spec: str | None) -> tuple[list[Message], int, str | None]:
    """Filter by absolute turn_number. Returns (messages, offset, error)."""
    if not turn_spec:
        return messages, 0, None
    selected, err = _select_turn_numbers(turn_spec, messages)
    if err:
        return [], 0, err
    if not selected:
        return [], 0, None
    filtered = [m for m in messages if m.turn_number in selected]
    if not filtered:
        return [], 0, None
    first = filtered[0]
    offset = next((i for i, m in enumerate(messages) if m is first), 0)
    return filtered, offset, None


PRIVATE_MARKER = "[/PRIVATE]"

def _apply_private_filter(msgs: list[Message], *, show_private: bool = False) -> list[Message]:
    """Filter out thinking blocks marked as private.

    A thinking block containing [/PRIVATE] anywhere in its content is treated
    as private and excluded from output. Only the ending marker is needed --
    if present, the entire thinking block is private.

    Non-thinking messages are never filtered by this function.

    Args:
        msgs: List of messages to filter.
        show_private: If True, include private blocks (for auditing).
            Private blocks will have a [PRIVATE] prefix added to their content.
    """
    result = []
    for m in msgs:
        if m.type == MessageType.THINKING and PRIVATE_MARKER in m.content:
            if show_private:
                # Auditing mode: show but clearly mark
                marked = Message(
                    role=m.role, type=m.type,
                    content=f"[PRIVATE THINKING BLOCK]\n{m.content}",
                    timestamp=m.timestamp, platform=m.platform,
                    tool_name=m.tool_name, tool_input=m.tool_input,
                    tool_call_id=m.tool_call_id, line_number=m.line_number,
                )
                result.append(marked)
            # else: skip entirely
        else:
            result.append(m)
    return result


def format_messages_from_schema(messages: list[Message], fmt: str = "text",
                                 msg_num_offset: int = 0,
                                 expand: "set[str] | None" = None) -> str:
    """Format Message objects for display.

    Formats: text, json, flat, markdown, structured, raw, memorex.
    'structured' returns JSON with day > turn > message hierarchy.
    'flat' returns a flat JSON array using Message.to_dict() (all fields including line_number).
    'raw' returns the original JSONL entries as a JSON array (unprocessed).
    'memorex' renders Memorex-style colored, labeled, collapsible section cards
    (matches the UAI Memorex live overlay; `expand` unfolds collapse-default types).
    """
    if fmt == "memorex":
        return render_memorex(messages, msg_num_offset=msg_num_offset, expand=expand)

    if fmt == "raw":
        # Return original JSONL entries for messages that have raw data
        raw_entries = [m.raw for m in messages if m.raw]
        return json.dumps(raw_entries, indent=2)

    if fmt == "structured":
        days = structure_session(messages)
        return json.dumps([d.to_dict() for d in days], indent=2)

    if fmt == "flat":
        return json.dumps([m.to_dict() for m in messages], indent=2)

    if fmt == "json":
        return json.dumps([
            {"role": m.role, "type": m.type.value, "content": m.content,
             "timestamp": m.timestamp, "platform": m.platform,
             **({"tool_name": m.tool_name, "tool_input": m.tool_input} if m.type == MessageType.TOOL_USE else {}),
             **({"tool_call_id": m.tool_call_id} if m.tool_call_id else {}),
            } for m in messages
        ], indent=2)
    elif fmt == "markdown":
        parts = []
        for m in messages:
            prefix = f"**{m.role.title()}**"
            local_ts = _ts_to_local(m.timestamp)
            if m.type == MessageType.TOOL_USE:
                parts.append(f"{prefix} ({local_ts}) -- tool: `{m.tool_name}`\n\n```json\n{json.dumps(m.tool_input, indent=2, ensure_ascii=False)}\n```\n")
            elif m.type == MessageType.TOOL_RESULT:
                parts.append(f"{prefix} ({local_ts}) -- tool result:\n\n```\n{m.content[:500]}\n```\n")
            else:
                parts.append(f"{prefix} ({local_ts}):\n\n{m.content}\n")
        return "\n---\n\n".join(parts)
    else:  # text
        parts = []
        sep = c("=" * 60, Colors.DIM)
        for i, m in enumerate(messages):
            num = msg_num_offset + i + 1
            turn_tag = "pre " if m.turn_number < 0 else f"T{m.turn_number} "  # conversation turn
            line_tag = f" L{m.source_line}" if m.source_line else ""     # raw JSONL file line
            num_str = c(f"[{turn_tag}#{num}{line_tag}]", Colors.BRIGHT_CYAN, Colors.BOLD)
            ts = c(f"[{_ts_to_local(m.timestamp)}]", Colors.DIM)

            if m.type == MessageType.TOOL_USE:
                label = c("TOOL_USE", Colors.YELLOW)
                tool = c(m.tool_name, Colors.YELLOW, Colors.BOLD)
                content = c(json.dumps(m.tool_input, indent=2, ensure_ascii=False), Colors.DIM)
                parts.append(f"{num_str} {ts} {label} ({tool}):\n{content}\n")
            elif m.type == MessageType.TOOL_RESULT:
                label = c("TOOL_RESULT", Colors.DIM, Colors.YELLOW)
                content = c(m.content[:500], Colors.DIM)
                parts.append(f"{num_str} {ts} {label}:\n{content}\n")
            elif m.type == MessageType.META:
                label = c("META", Colors.DIM)
                content = c(m.content, Colors.DIM)
                parts.append(f"{num_str} {ts} {label}: {content}\n")
            elif m.type == MessageType.SYSTEM:
                label = c("SYSTEM", Colors.BRIGHT_MAGENTA, Colors.BOLD)
                content = c(m.content, Colors.DIM)
                parts.append(f"{num_str} {ts} {label}:\n{content}\n")
            elif m.type == MessageType.THINKING:
                label = c("THINKING", Colors.MAGENTA)
                content = c(m.content, Colors.DIM, Colors.ITALIC)
                parts.append(f"{num_str} {ts} {label}:\n{content}\n")
            elif m.type == MessageType.SKILL:
                label = c("SKILL", Colors.CYAN)
                content = c(m.content, Colors.DIM)
                parts.append(f"{num_str} {ts} {label}:\n{content}\n")
            elif m.type == MessageType.AGENT_RESULT:
                label = c("AGENT_RESULT", Colors.YELLOW, Colors.BOLD)
                content = c(m.content, Colors.DIM)
                parts.append(f"{num_str} {ts} {label}:\n{content}\n")
            elif m.type == MessageType.INJECTED:
                label = c("INJECTED", Colors.DIM, Colors.ITALIC)
                content = c(m.content, Colors.DIM)
                parts.append(f"{num_str} {ts} {label}:\n{content}\n")
            elif m.type == MessageType.USER:
                label = c("USER", Colors.BRIGHT_BLUE, Colors.BOLD)
                content = c(m.content, Colors.BRIGHT_WHITE)
                parts.append(f"{num_str} {ts} {label}:\n{content}\n")
            elif m.type == MessageType.RESPONSE:
                label = c("RESPONSE", Colors.BRIGHT_GREEN)
                content = c(m.content, Colors.BRIGHT_WHITE)
                parts.append(f"{num_str} {ts} {label}:\n{content}\n")
            else:
                label = c(m.type.value.upper(), Colors.DIM)
                parts.append(f"{num_str} {ts} {label}:\n{m.content}\n")
        return "\n" + (sep + "\n\n").join(parts)


# =============================================================================
# Command implementations
# =============================================================================


def _read_targets(
    targets: list[str], *, platform: str | None, resolve: bool,
    include_client_only: bool, interval_spec: str | None,
    all_intervals: bool, missing_label: str = "Session not found",
) -> tuple[list[Message] | None, str | None]:
    """Load messages for UUID/path targets and apply per-file interval selection."""
    all_msgs: list[Message] = []
    parse_all_intervals = all_intervals or bool(interval_spec)
    for target in targets:
        path = find_jsonl(target)
        if not path:
            return None, c(f"{missing_label}: {target}", Colors.RED)
        m = parse_session(path, platform=platform, all_intervals=parse_all_intervals)
        if resolve:
            m = resolve_archived_stubs(m, path)
        if include_client_only:
            m = sorted(m + client_only_meta_messages(path), key=lambda x: x.source_line)
        if interval_spec:
            selected, err = _select_intervals(interval_spec, compaction_intervals(path))
            if err:
                return None, c(err, Colors.YELLOW)
            m = _apply_interval_filter(m, selected)
        all_msgs.extend(m)
    return all_msgs, None


def _read_file_targets(
    paths: list[str], *, platform: str | None, resolve: bool,
    include_client_only: bool, interval_spec: str | None,
    all_intervals: bool,
) -> tuple[list[Message] | None, str | None]:
    """Load messages for explicit file paths and apply per-file interval selection."""
    all_msgs: list[Message] = []
    parse_all_intervals = all_intervals or bool(interval_spec)
    for p_str in paths:
        p = Path(p_str)
        if not p.exists():
            return None, c(f"File not found: {p}", Colors.RED)
        m = parse_session(p, platform=platform, all_intervals=parse_all_intervals)
        if resolve:
            m = resolve_archived_stubs(m, p)
        if include_client_only:
            m = sorted(m + client_only_meta_messages(p), key=lambda x: x.source_line)
        if interval_spec:
            selected, err = _select_intervals(interval_spec, compaction_intervals(p))
            if err:
                return None, c(err, Colors.YELLOW)
            m = _apply_interval_filter(m, selected)
        all_msgs.extend(m)
    return all_msgs, None


def _filter_and_format_messages(
    msgs: list[Message], *, fmt: str, type_filter: list[str] | None,
    range_str: str | None, turns_str: str | None, show_private: bool,
    sort_order: str | None = None, apply_toggles: bool = False,
    expand: set[str] | None = None,
) -> str:
    """Common post-load filter pipeline for read/read-file/extract."""
    if turns_str and range_str and range_str.lower().startswith("t"):
        return c("Use either --turns or --range t..., not both.", Colors.YELLOW)

    range_offset = 0
    if turns_str:
        msgs, range_offset, err = _apply_turn_filter(msgs, turns_str)
        if err:
            return c(err, Colors.YELLOW)
    else:
        # Apply --range before --type so t-ranges can still see USER turn starts.
        msgs, range_offset = _apply_range(msgs, range_str)

    msgs = _apply_type_filter(msgs, type_filter)
    msgs = _apply_private_filter(msgs, show_private=show_private)
    if apply_toggles:
        msgs = _apply_toggles(msgs)
    if sort_order:
        msgs = _sort_messages_by_ts(msgs, sort_order)
    return format_messages_from_schema(msgs, fmt, msg_num_offset=range_offset, expand=expand)


def cmd_read(args: list[str]) -> str:
    """Read messages from a session by UUID."""
    if not args:
        return "Usage: read <uuid> [--format F] [--platform P] [--type/--types T] [--range R|--turns R] [--interval SPEC]"
    query = args[0]
    fmt = _parse_flag(args, "--format") or "text"
    platform = _parse_flag(args, "--platform")
    type_filter = _parse_message_types_arg(args)
    range_str = _parse_flag(args, "--range")
    turns_str = _parse_flag(args, "--turns")
    interval_spec = _parse_flag(args, "--interval")
    show_private = "--show-private" in args
    resolve = "--resolve" in args
    include_client_only = "--include-client-only" in args
    all_intervals = "--all-intervals" in args

    loaded, err = _read_targets([query], platform=platform, resolve=resolve,
                                include_client_only=include_client_only,
                                interval_spec=interval_spec,
                                all_intervals=all_intervals)
    if err:
        return err
    return _filter_and_format_messages(loaded or [], fmt=fmt, type_filter=type_filter,
                                       range_str=range_str, turns_str=turns_str,
                                       show_private=show_private)


def cmd_read_file(args: list[str]) -> str:
    """Read messages from one or more file paths."""
    fmt = _parse_flag(args, "--format") or "text"
    platform = _parse_flag(args, "--platform")
    type_filter = _parse_message_types_arg(args)
    range_str = _parse_flag(args, "--range")
    turns_str = _parse_flag(args, "--turns")
    interval_spec = _parse_flag(args, "--interval")
    show_private = "--show-private" in args
    resolve = "--resolve" in args
    include_client_only = "--include-client-only" in args
    all_intervals = "--all-intervals" in args
    expand = _parse_memorex_expand(_parse_flag(args, "--expand"))
    paths = _strip_flags(args, ["--format", "--platform", "--range", "--turns", "--interval", "--expand"], multi_flags=["--type", "--types"])
    paths = [p for p in paths if p not in ("--include-client-only", "--all-intervals")]

    if not paths:
        return "Usage: read-file <path> [path2 ...] [--format F] [--platform P] [--type/--types T] [--range R|--turns R] [--interval SPEC] [--resolve] [--expand SECTIONS]"

    loaded, err = _read_file_targets(paths, platform=platform, resolve=resolve,
                                     include_client_only=include_client_only,
                                     interval_spec=interval_spec,
                                     all_intervals=all_intervals)
    if err:
        return err
    return _filter_and_format_messages(loaded or [], fmt=fmt, type_filter=type_filter,
                                       range_str=range_str, turns_str=turns_str,
                                       show_private=show_private, expand=expand)


def cmd_extract(args: list[str]) -> str:
    """Extract scoped message content for briefing/Recall workflows."""
    usage = ("Usage: extract <uuid|path> [target2 ...] [--types TYPE[,TYPE]] "
             "[--interval SPEC | --turns RANGE] [--format markdown|text|json|flat|structured|raw] "
             "[--resolve] [--include-client-only]")
    if not args:
        return usage
    fmt = _parse_flag(args, "--format") or "markdown"
    platform = _parse_flag(args, "--platform")
    type_filter = _parse_message_types_arg(args)
    range_str = _parse_flag(args, "--range")
    turns_str = _parse_flag(args, "--turns")
    interval_spec = _parse_flag(args, "--interval")
    show_private = "--show-private" in args
    resolve = "--resolve" in args
    include_client_only = "--include-client-only" in args
    # Extraction is archival/briefing oriented: preserve turn numbering across all
    # compaction intervals by default. read/read-file keep the live-context default.
    all_intervals = True
    expand = _parse_memorex_expand(_parse_flag(args, "--expand"))
    targets = _strip_flags(args, ["--format", "--platform", "--range", "--turns", "--interval", "--expand"], multi_flags=["--type", "--types"])
    targets = [t for t in targets if t not in ("--include-client-only", "--all-intervals")]
    if not targets:
        return usage

    # Targets can be UUIDs or direct files. Resolve each independently.
    loaded: list[Message] = []
    for target in targets:
        p = Path(target)
        if p.exists():
            msgs, err = _read_file_targets([target], platform=platform, resolve=resolve,
                                           include_client_only=include_client_only,
                                           interval_spec=interval_spec,
                                           all_intervals=all_intervals)
        else:
            msgs, err = _read_targets([target], platform=platform, resolve=resolve,
                                      include_client_only=include_client_only,
                                      interval_spec=interval_spec,
                                      all_intervals=all_intervals)
        if err:
            return err
        loaded.extend(msgs or [])

    return _filter_and_format_messages(loaded, fmt=fmt, type_filter=type_filter,
                                       range_str=range_str, turns_str=turns_str,
                                       show_private=show_private, expand=expand)

def cmd_find(args: list[str]) -> str:
    """Find session file by UUID."""
    if not args:
        return "Usage: find <uuid>"
    result = find_jsonl(args[0])
    if result:
        return str(result)
    return c(f"Not found: {args[0]}", Colors.RED)


def cmd_summary(args: list[str]) -> str:
    """Show session summary."""
    if not args:
        return "Usage: summary <uuid> [--platform claude|codex|gemini|agy]"
    platform = _parse_flag(args, "--platform")
    path = find_jsonl(args[0])
    if not path:
        return c(f"Session not found: {args[0]}", Colors.RED)
    summary = session_summary(path)
    return json.dumps(summary, indent=2)


# =============================================================================
# ADDITIVE STATS FLAGS (2026-06): --split-offloaded. Read-only; does not touch
# parse_session / human_turn_indices / the public functions other tools import.
# When set, co-located Full/Stub breakouts are inlined under each User/AI/Tools
# line (per-Day, Totals, and per compaction interval). Default OFF.
# =============================================================================

def _all_stub_prefixes() -> tuple[str, ...]:
    """Offload STUB_PREFIXES + the engram stub prefix, as one tuple."""
    off, eng = _stub_prefixes()
    return tuple(off) + (eng,)


def _value_is_stub(v, prefixes) -> bool:
    return isinstance(v, str) and v.lstrip().startswith(prefixes)


def _message_is_stub(m, prefixes) -> bool:
    """True if this Message's rendered content or any tool_input value is a stub."""
    if _value_is_stub(m.content, prefixes):
        return True
    if isinstance(m.tool_input, dict):
        return any(_value_is_stub(v, prefixes) for v in m.tool_input.values())
    return False


def _msg_chars_words(m) -> tuple[int, int]:
    """Char/word size of a Message under the SAME rule the Totals day-loop uses
    (tool_use adds its JSON-serialized input)."""
    if m.type == MessageType.TOOL_USE and m.tool_input:
        input_str = json.dumps(m.tool_input) if isinstance(m.tool_input, dict) else str(m.tool_input)
        return len(m.content) + len(input_str), _count_words(m.content) + _count_words(input_str)
    return len(m.content), _count_words(m.content)


def _msg_chars(m) -> int:
    """Char size of a Message under the SAME rule the Totals day-loop uses
    (tool_use adds its JSON-serialized input)."""
    return _msg_chars_words(m)[0]


def split_offloaded_tally(msgs: list[Message]) -> dict:
    """For User / AI / Tools, split each into stub vs full (count + chars + words).

    Stub = the Message's content / tool_input is currently an offload or engram
    stub (detected via lib_jsonl_archive.STUB_PREFIXES + '[engram archived:').
    Counts/chars/words for full+stub sum to the per-role Totals lines.
    """
    prefixes = _all_stub_prefixes()
    cats = {k: {"stub": {"count": 0, "chars": 0, "words": 0},
                "full": {"count": 0, "chars": 0, "words": 0}}
            for k in ("user", "ai", "tools")}
    for m in msgs:
        if m.type == MessageType.USER:
            cat = "user"
        elif m.type == MessageType.RESPONSE:
            cat = "ai"
        elif m.type in (MessageType.TOOL_USE, MessageType.TOOL_RESULT):
            cat = "tools"
        else:
            continue
        bucket = "stub" if _message_is_stub(m, prefixes) else "full"
        mc, mw = _msg_chars_words(m)
        cats[cat][bucket]["count"] += 1
        cats[cat][bucket]["chars"] += mc
        cats[cat][bucket]["words"] += mw
    return cats


def _format_context_caveat() -> str:
    """Always-on note: these stats are the TRANSCRIPT only, not total context."""
    out = ["", c("─" * 60, Colors.DIM),
           c("NOTE — what these numbers do and DON'T cover", Colors.BOLD, Colors.YELLOW)]
    out.append(c("  These statistics cover the TRANSCRIPT (the message stream in this JSONL) ONLY.", Colors.DIM))
    out.append(c("  The model's ACTUAL per-request context ALSO includes the preamble Claude Code", Colors.DIM))
    out.append(c("  builds from config and does NOT store in the JSONL: the system prompt, tool/MCP", Colors.DIM))
    out.append(c("  schemas, and injected CLAUDE.md / memory / context files. So 'model-facing' here", Colors.DIM))
    out.append(c("  = the conversation's contribution, NOT total context. Run /context for the true split.", Colors.DIM))
    return "\n".join(out)


def cmd_stats(args: list[str]) -> str:
    """Show detailed session statistics."""
    if not args:
        return ("Usage: stats <uuid> [--platform P] [--format text|json] [--tools] "
                "[--split-offloaded] [--interval SPEC]  (SPEC: N | live | last | 2-4; scopes the LEDGER)")
    fmt = _parse_flag(args, "--format") or "text"
    platform = _parse_flag(args, "--platform")
    interval_spec = _parse_flag(args, "--interval")
    show_tools = "--tools" in args
    split_offloaded = "--split-offloaded" in args
    bool_flags = {"--tools", "--split-offloaded"}
    args = [a for a in args if a not in bool_flags]
    _stripped = _strip_flags(args, ["--format", "--platform", "--interval"])
    query = _stripped[0] if _stripped else args[0]
    path = find_jsonl(query)
    if not path:
        return c(f"Session not found: {query}", Colors.RED)
    # --interval scopes the LEDGER to the requested compaction interval(s); default
    # (None) shows OVERALL + LIVE. Accepts a number, 'live'/'last', or a range.
    show_intervals = None
    if interval_spec:
        selected, err = _select_intervals(interval_spec, compaction_intervals(path))
        if err:
            return c(err, Colors.RED)
        show_intervals = [iv["index"] for iv in selected]
    result = session_stats(path, platform=platform, fmt=fmt, show_tools=show_tools,
                           split_offloaded=split_offloaded)
    bd = raw_line_breakdown(path)
    sa = stub_accounting(path)
    cf = conversation_client_only_fields(path)
    ml = model_facing_ledger(path)
    if isinstance(result, dict):
        result["raw_line_breakdown"] = bd
        result["stub_accounting"] = sa
        result["conversation_client_only_fields"] = cf
        result["model_facing_ledger"] = ml
        if split_offloaded:
            result["split_offloaded"] = split_offloaded_tally(parse_session(path, platform=platform))
        result["context_caveat"] = (
            "Stats cover the TRANSCRIPT only; the model's per-request context also "
            "includes the system prompt + tool/MCP schemas + injected "
            "CLAUDE.md/memory/context files (NOT stored in JSONL). "
            "Run /context for the true split.")
        return json.dumps(result, indent=2)
    # semantic-total chars (Totals block) for the bottom-up/semantic ratio
    semantic_chars = None
    try:
        _sd = session_stats(path, platform=platform, fmt="json")
        if isinstance(_sd, dict):
            semantic_chars = _sd.get("totals", {}).get("chars")
    except Exception:
        semantic_chars = None
    parts = [
        result,
        "\n" + _format_raw_line_breakdown(bd),
        "\n" + _format_stub_accounting(sa),
        "\n" + _format_conversation_client_only_fields(cf, bd),
        "\n" + _format_model_facing_ledger(ml, cf, semantic_chars, show_intervals=show_intervals),
    ]
    parts.append("\n" + _format_context_caveat())
    return "".join(parts)


_HISTO_CATS = ("user", "response", "thinking", "signature", "tool_use", "tool_result", "compaction", "other")


def _signatures_by_line(path: "Path") -> "dict":
    """Map raw 1-indexed JSONL line -> total thinking-block signature chars.

    The standardized Message.raw drops the `signature`, so read the original file
    to recover the encrypted-blob byte cost and key it by source_line.
    """
    out: dict = {}
    try:
        with open(path, encoding="utf-8") as f:
            for i, ln in enumerate(f):
                if not ln.strip():
                    continue
                try:
                    o = json.loads(ln)
                except Exception:
                    continue
                content = (o.get("message") or {}).get("content")
                if isinstance(content, list):
                    s = sum(len(b.get("signature") or "")
                            for b in content
                            if isinstance(b, dict) and b.get("type") == "thinking")
                    if s:
                        out[i + 1] = s
    except OSError:
        pass
    return out


def turn_histogram(messages: list, sig_by_line: "dict | None" = None,
                   include_off_chain: bool = False) -> "dict":
    """Per-turn char tally, broken out by category.

    By default counts only ACTIVE-CHAIN records (what's actually in the model's
    context); off-chain dead-retry/rewind records are skipped (set
    include_off_chain=True to count them). `thinking` = readable plaintext;
    `signature` = the encrypted thinking blob (recovered from the raw file via
    source_line); `compaction` = isCompactSummary continuations. Returns an
    ordered {turn: {cat: chars, ts, nmsg}} by absolute turn.
    """
    from collections import OrderedDict
    sig_by_line = sig_by_line or {}
    turns: "OrderedDict" = OrderedDict()
    seen_sig: set = set()
    for m in messages:
        if not include_off_chain and not getattr(m, "on_chain", True):
            continue
        t = m.turn_number if m.turn_number is not None else 0   # -1 = `pre` prologue
        d = turns.get(t)
        if d is None:
            d = {k: 0 for k in _HISTO_CATS}
            d["ts"] = m.timestamp
            d["nmsg"] = 0
            turns[t] = d
        d["nmsg"] += 1
        typ = m.type
        if getattr(m, "is_compaction", False):
            d["compaction"] += len(m.content or "")
        elif typ == MessageType.USER:
            d["user"] += len(m.content or "")
        elif typ == MessageType.RESPONSE:
            d["response"] += len(m.content or "")
        elif typ == MessageType.THINKING:
            d["thinking"] += len(m.content or "")
            sl = m.source_line
            if sl and sl not in seen_sig:                 # one record's sig counted once
                seen_sig.add(sl)
                d["signature"] += sig_by_line.get(sl, 0)
        elif typ == MessageType.TOOL_USE:
            try:
                d["tool_use"] += len(json.dumps(m.tool_input or {}, ensure_ascii=False))
            except Exception:
                d["tool_use"] += len(str(m.tool_input or ""))
        elif typ == MessageType.TOOL_RESULT:
            d["tool_result"] += len(m.content or "")
        else:
            d["other"] += len(m.content or "")
    return turns


def _format_histogram(turns: "dict", width: int = 24, other_breakdown: "dict | None" = None) -> str:
    """Render the per-turn char histogram: per-type columns, total, stacked bar."""
    def total(d):
        return sum(d[k] for k in _HISTO_CATS)
    maxtot = max((total(d) for d in turns.values()), default=0) or 1
    H = lambda s: c(s, Colors.BOLD, Colors.BRIGHT_CYAN)
    D = lambda s: c(s, Colors.DIM)
    # Column/segment order + colors match the message-type labels used elsewhere.
    # thinking includes its signature bytes; other = system/meta/skill/etc.
    segdef = [
        ("user", Colors.BRIGHT_BLUE, lambda d: d["user"]),
        ("tools", Colors.YELLOW, lambda d: d["tool_use"] + d["tool_result"]),
        ("thinking", Colors.MAGENTA, lambda d: d["thinking"] + d["signature"]),
        ("response", Colors.BRIGHT_GREEN, lambda d: d["response"]),
        ("compact", Colors.CYAN, lambda d: d["compaction"]),
        ("other", Colors.DIM, lambda d: d["other"]),
    ]
    cw = 10
    hdr = (f" {'turn':<5}"
           + "".join(c(f"{name:>{cw}}", col) for name, col, _ in segdef)
           + f"{'total':>12}  bar")
    lines = [
        H("TURN HISTOGRAM") + D("  chars per turn by message type (active chain only)"),
        hdr,
    ]
    grand = {k: 0 for k in _HISTO_CATS}
    for t, d in turns.items():
        tot = total(d)
        for k in _HISTO_CATS:
            grand[k] += d[k]
        vals = [fn(d) for _, _, fn in segdef]
        cols = "".join(f"{v:>{cw},}" for v in vals)
        nbar = max(1, round(width * tot / maxtot)) if tot else 0
        bar, acc, cum = "", 0, 0      # cumulative rounding → segments sum to nbar
        for (_, col, fn) in segdef:
            cum += fn(d)
            tgt = round(nbar * cum / tot) if tot else 0
            seg = max(0, tgt - acc)
            acc = tgt
            if seg:
                bar += c("█" * seg, col)
        t_label = "pre" if t < 0 else "T" + str(t)
        lines.append(f" {t_label:<5}{cols}{tot:>12,}  {bar}")
    # totals row
    gv = [fn(grand) for _, _, fn in segdef]
    gt = sum(gv)
    lines.append(" " + D("─" * (5 + cw * len(segdef) + 12)))
    lines.append(f" {'Σ':<5}" + "".join(f"{v:>{cw},}" for v in gv) + f"{gt:>12,}")
    lines.append("")
    lines.append(D(
        f" thinking total {grand['thinking']+grand['signature']:,} = "
        f"plaintext {grand['thinking']:,} + signature {grand['signature']:,} (encrypted blob)"))
    if other_breakdown:
        parts = " · ".join(f"{k} {v:,}" for k, v in
                           sorted(other_breakdown.items(), key=lambda kv: -kv[1]) if v)
        lines.append(D(f" other ({sum(other_breakdown.values()):,}) = "
                       + (parts or "none") + "  ← message types pooled into 'other'"))
    else:
        lines.append(D(" other = skill bodies / agent_result / injected / system / meta"))
    lines.append(D(
        " compact = compaction-summary continuations · "
        "off-chain dead-retry/rewind records excluded"))
    return "\n".join(lines)


def cmd_histo(args: list[str]) -> str:
    """Per-turn histogram of char usage (offload target highlighted)."""
    usage = "Usage: histo <uuid|path> [--platform P] [--format text|json] [--interval SPEC]"
    if not args:
        return usage
    fmt = _parse_flag(args, "--format") or "text"
    platform = _parse_flag(args, "--platform")
    interval_spec = _parse_flag(args, "--interval")
    queries = _strip_flags(args, ["--format", "--platform", "--interval"])
    if not queries:
        return usage
    path = find_jsonl(queries[0])
    if not path:
        return c(f"Session not found: {queries[0]}", Colors.RED)
    msgs = parse_session(path, platform=platform)
    if interval_spec:
        selected, err = _select_intervals(interval_spec, compaction_intervals(path))
        if err:
            return c(err, Colors.RED)
        msgs = _apply_interval_filter(msgs, selected)
    turns = turn_histogram(msgs, sig_by_line=_signatures_by_line(path))
    # Break down the 'other' bucket by message type (on-chain, non-compaction).
    _main = {MessageType.USER, MessageType.RESPONSE, MessageType.THINKING,
             MessageType.TOOL_USE, MessageType.TOOL_RESULT}
    other_breakdown: dict = {}
    for m in msgs:
        if not getattr(m, "on_chain", True) or getattr(m, "is_compaction", False):
            continue
        if m.type not in _main:
            other_breakdown[m.type.value] = other_breakdown.get(m.type.value, 0) + len(m.content or "")
    if fmt == "json":
        return json.dumps({"turns": {str(t): d for t, d in turns.items()},
                           "other_breakdown": other_breakdown}, indent=2)
    return _format_histogram(turns, other_breakdown=other_breakdown)


def cmd_compactions(args: list[str]) -> str:
    """List compaction events and their resulting intervals for a session."""
    platform = _parse_flag(args, "--platform")
    positionals = _strip_flags(args, ["--platform"])
    if not positionals:
        return "Usage: compactions <uuid|path> [--platform P]"
    path = find_jsonl(positionals[0])
    if not path:
        return c(f"Session not found: {positionals[0]}", Colors.RED)

    events = find_compactions(path)
    intervals = compaction_intervals(path)
    msgs = parse_session(path, platform=platform)

    def _count(s: int, e: int) -> int:
        return sum(1 for m in msgs if m.source_line and s <= m.source_line <= e)

    ev_by_index = {ev["index"]: ev for ev in events}

    header = c(f"COMPACTIONS — {path.name}", Colors.BOLD, Colors.BRIGHT_CYAN)
    n = len(events)
    sub = c(f"  {n} compaction event(s); {len(intervals)} interval(s); {len(msgs)} parsed messages", Colors.DIM)
    cols = c(
        f"  {'idx':>3}  {'start_line':>10}  {'timestamp':<19}  {'sum_chars':>9}  {'interval_lines':<16}  {'msgs':>6}  region",
        Colors.BOLD,
    )
    lines = [header, sub, "", cols, c("  " + "-" * 84, Colors.DIM)]

    for iv in intervals:
        idx = iv["index"]
        s, e = iv["start_line"], iv["end_line"]
        rng = f"{s}-{e}" if e >= s else "(empty)"
        cnt = _count(s, e) if e >= s else 0
        if iv["is_prologue"]:
            ts_disp, sum_chars = "-", "-"
            region = "prologue"
        else:
            ev = ev_by_index.get(idx, {})
            ts_disp = _ts_to_local(ev.get("timestamp", "")) or "-"
            sum_chars = f"{ev.get('summary_chars', 0):,}"
            region = "live" if idx == intervals[-1]["index"] else ""
        start_disp = "-" if iv["is_prologue"] else str(s)
        lines.append(
            f"  {idx:>3}  {start_disp:>10}  {ts_disp:<19}  {str(sum_chars):>9}  {rng:<16}  {cnt:>6}  {region}"
        )

    if not events:
        lines.append("")
        lines.append(c("  No compaction events found (interval 0 spans the whole file).", Colors.DIM))
    return "\n".join(lines)


def cmd_list_sessions(args: list[str]) -> str:
    """List sessions with optional platform filter."""
    platform = _parse_flag(args, "--platform")
    limit = int(_parse_flag(args, "--limit") or "20")
    
    sessions = list_sessions(platform, limit)
    if not sessions:
        return "No sessions found."
        
    lines = [f"{'TIMESTAMP':<20} | {'PLATFORM':<8} | {'UUID':<36}", "-" * 70]
    for s in sessions:
        ts = _ts_to_local(s.get("timestamp", "?"))
        p = s.get("platform", "???")
        u = s.get("uuid", "???")
        lines.append(f"{ts:<20} | {p:<8} | {u:<36}")
    return "\n".join(lines)


def _command_help_entries() -> dict[str, dict]:
    """Registry of all commands with help metadata.

    Each entry: {
        "usage":   str,            # one-line usage
        "summary": str,            # short description
        "detail":  list[str],      # longer explanation lines (plain text, colorized at render time)
        "options": list[tuple],    # [(flag, description), ...]
        "examples": list[str],     # example invocations
        "aliases": list[str],      # short aliases
        "repl_only": bool,         # True if only available inside the REPL
    }
    """
    types_list = "user, response, thinking, tool_use, tool_result, system, meta"
    return {
        "read": {
            "usage": "read <uuid|path> [uuid2 ...] [options]",
            "summary": "Read session by UUID or file path (multiple OK)",
            "detail": [
                "Accepts one or more UUIDs (partial match OK) or direct file paths.",
                "For UUIDs, searches Claude, Codex, and Gemini session directories.",
                "A partial UUID (e.g. '7edf') is enough if it uniquely identifies a session.",
                "Multiple targets: messages are grouped by file in order by default.",
                "Use --sort to flatten and sort all messages by timestamp across files.",
                "In REPL mode, toggle and range state are applied automatically.",
            ],
            "options": [
                ("--format json|text|markdown|memorex", "Output format (default: text). 'memorex' = colored, labeled, collapsible section cards matching the UAI Memorex overlay"),
                ("--expand SECTIONS", "memorex format: unfold collapse-by-default sections (e.g. --expand tool,thinking or --expand all)"),
                ("--platform claude|codex|gemini|agy", "Force platform detection (default: auto)"),
                ("--type/--types TYPE[,TYPE]", f"Filter by message type: {types_list}; aliases: assistant, tools, conversation"),
                ("--range RANGE", "Message range: 1-10, -20, 5-, t1-5, t-4"),
                ("--turns RANGE", "Absolute Tn turn range: 10-20, 10-, -5, 12"),
                ("--interval SPEC", "Keep only messages in compaction interval(s): 0=prologue, 1..N, last|live, -1, '1,3', '2-4'"),
                ("--all-intervals", "Parse all compaction intervals for whole-history turn numbering (default: off — only the selected interval(s))"),
                ("--include-client-only", "Merge client-only raw lines (attachment, file-history-snapshot, system, ...) inline as META (default: off)"),
                ("--sort newest|oldest", "Flatten multiple targets and sort all messages by timestamp (default: group by file, source order)"),
                ("--show-private", "Include private thinking blocks marked [/PRIVATE] (default: hidden)"),
                ("--resolve", "Rehydrate Offload/Engram stubs from their archive so you read the ORIGINAL content in place (default: off; disk is not modified — a Restore-for-reading)"),
                ("--no-color", "Disable ANSI color (default: color on a TTY) — use when piping to tools that choke on escape codes"),
            ],
            "examples": ["read 7edf", "read 7edf a1b2 --sort newest", "read 7edf --type user,response", "read 7edf --range t1-5 --format markdown", "read 7edf --interval last", "read 7edf --interval 0 --include-client-only", "read 7edf --resolve   # rehydrate offloaded tool_results for reading"],
            "aliases": ["r"],
            "repl_only": False,
        },
        "extract": {
            "usage": "extract <uuid|path> [target2 ...] [options]",
            "summary": "Extract scoped messages for briefing/Recall workflows",
            "detail": [
                "Briefing-oriented wrapper around read/read-file selection.",
                "Unlike read, extract preserves turn numbering across all compaction",
                "intervals by default, so already-compacted sessions can be mined for",
                "historical user/assistant/thinking/tool slices.",
                "Use --types to choose message kinds, --interval for compaction",
                "intervals, and --turns for absolute Tn ranges shown in read_jsonl",
                "headers. Default format is markdown for direct briefing input.",
                "Context-reclaim role: this is the 'read it back out' half — feed a summarized or",
                "offloaded region's turns into a briefing, or pull an archived slice for a manual",
                "Recall (surfacing remembered-not-current content into a live session).",
            ],
            "options": [
                ("--format markdown|text|json|flat|structured|raw|memorex", "Output format (default: markdown, for direct briefing input)"),
                ("--types TYPE[,TYPE] / --type TYPE[,TYPE]", f"Filter by message type: {types_list}; aliases: assistant=response, tools=tool_use+tool_result, conversation=user+response (default: all types)"),
                ("--interval SPEC", "Compaction intervals: 0=prologue, 1..N, last|live, -1, '1,3', '2-4' (default: all intervals — extract mines whole history)"),
                ("--turns RANGE", "Absolute turn-number range using Tn values from headers: 10-20, 10-, -5, 12"),
                ("--range RANGE", "Legacy message range or t-range; prefer --turns for briefing extraction"),
                ("--resolve", "Rehydrate Offload/Engram stubs to their original content before extracting (default: off)"),
                ("--include-client-only", "Merge client-only raw lines inline as META (default: off)"),
                ("--platform claude|codex|gemini|agy", "Force platform detection (default: auto)"),
            ],
            "examples": [
                "extract 7edf --types user,response --interval 1-3",
                "extract 7edf --types conversation --turns 40-55 --format markdown",
                "extract session.jsonl --types thinking,response --interval last --resolve",
            ],
            "aliases": ["x"],
            "repl_only": False,
        },
        "read-file": {
            "usage": "read-file <path> [path2 ...] [options]",
            "summary": "Read one or more JSONL/JSON files directly",
            "detail": [
                "Reads messages from explicit file paths instead of searching by UUID.",
                "Accepts multiple paths; messages are grouped by file in order by default.",
                "Use --sort to flatten and sort all messages by timestamp across files.",
                "Platform is auto-detected from path and file content.",
            ],
            "options": [
                ("--format json|text|markdown|memorex", "Output format (default: text). 'memorex' = colored, labeled, collapsible section cards matching the UAI Memorex overlay"),
                ("--expand SECTIONS", "memorex format: unfold collapse-by-default sections (e.g. --expand tool,thinking or --expand all)"),
                ("--platform claude|codex|gemini|agy", "Force platform detection (default: auto)"),
                ("--type/--types TYPE[,TYPE]", f"Filter by message type: {types_list}; aliases: assistant, tools, conversation"),
                ("--range RANGE", "Message range: 1-10, -20, 5-, t1-5, t-4"),
                ("--turns RANGE", "Absolute Tn turn range: 10-20, 10-, -5, 12"),
                ("--interval SPEC", "Keep only messages in compaction interval(s): 0=prologue, 1..N, last|live, -1, '1,3', '2-4'"),
                ("--all-intervals", "Parse all compaction intervals for whole-history turn numbering"),
                ("--include-client-only", "Merge client-only raw lines (attachment, file-history-snapshot, system, ...) inline as META"),
                ("--sort newest|oldest", "Sort all messages by timestamp across files"),
                ("--show-private", "Include private thinking blocks"),
            ],
            "examples": ["read-file session.jsonl", "read-file f1.jsonl f2.jsonl --sort newest --type user,response", "read-file session.jsonl --interval last --include-client-only"],
            "aliases": ["rf"],
            "repl_only": False,
        },
        "find": {
            "usage": "find <uuid>",
            "summary": "Print the file path for a session UUID",
            "detail": [
                "Searches all platform session directories and prints the absolute path",
                "of the JSONL file matching the given UUID (partial match OK).",
                "Useful for scripting and piping into other tools.",
            ],
            "options": [],
            "examples": ["find 7edf", "find e0954f5d-fae8-49ff-8e91-c77db0d73227"],
            "aliases": ["f"],
            "repl_only": False,
        },
        "summary": {
            "usage": "summary <uuid|path> [--platform P]",
            "summary": "Show session summary as JSON (msg counts, timestamps, platform)",
            "detail": [
                "Accepts a UUID (partial match OK) or a direct file path.",
                "Outputs a JSON object with session metadata: message counts by type,",
                "first and last timestamps, platform, and total message count.",
            ],
            "options": [
                ("--platform claude|codex|gemini|agy", "Force platform detection"),
            ],
            "examples": ["summary 7edf"],
            "aliases": ["s"],
            "repl_only": False,
        },
        "stats": {
            "usage": "stats <uuid|path> [options]",
            "summary": "Detailed session statistics (types, tools, timing) — the 'what's sheddable' surface",
            "detail": [
                "Accepts a UUID (partial match OK) or a direct file path.",
                "Shows comprehensive session statistics including message counts and BYTES by",
                "type, tool usage breakdown (with --tools), timing, and token estimates.",
                "In the context-reclaim ladder this is the primary read-side gauge: it tells you",
                "how heavy a transcript is and where the bytes live, so you can decide whether to",
                "Offload / Bounce / Summarize. --split-offloaded further separates bytes still Full",
                "(reclaimable) from bytes already relocated to a Stub (already offloaded).",
            ],
            "options": [
                ("--format text|json", "Output format (default: text; json is model-readable, no ANSI)"),
                ("--platform claude|codex|gemini|agy", "Force platform detection (default: auto from path/content)"),
                ("--tools", "Include per-tool usage breakdown (default: off)"),
                ("--split-offloaded", "Inline a Full/Stub byte breakout under each User/AI/Tools line — Full = still reclaimable, Stub = already Offloaded (default: off)"),
            ],
            "examples": ["stats 7edf", "stats 7edf --tools", "stats 7edf --format json",
                         "stats 7edf --split-offloaded"],
            "aliases": ["st"],
            "repl_only": False,
        },
        "histo": {
            "usage": "histo <uuid|path> [options]",
            "summary": "Per-turn char histogram, stacked by message type — locate the heavy turns",
            "detail": [
                "One row per conversation turn with per-type char columns, total, and",
                "a compact stacked bar scaled to the heaviest turn:",
                "  blue=user  yellow=tools(tool_use+tool_result)  magenta=thinking(+signature)  green=response.",
                "Counts transcript chars (not tokens); thinking includes its encrypted",
                "signature bytes. 'other' = system/meta/skill/etc.",
                "Reclaim use: the bar instantly shows WHICH turns and WHICH types dominate — a",
                "tools-heavy turn is Offload fodder (lossless); a thinking/response-heavy turn can",
                "only be shed by Summarize (lossy, reversible). Pairs with 'stats' for the totals.",
                "--format json emits {turns: {N: {user,response,thinking,signature,tool_use,",
                "tool_result,compaction,other,ts,nmsg}}, other_breakdown: {type: chars}}",
                "— model-readable, no bars/ANSI.",
            ],
            "options": [
                ("--format text|json", "Output format (default: text; json is model-readable, no bars/ANSI)"),
                ("--platform claude|codex|gemini|agy", "Force platform detection (default: auto)"),
                ("--interval SPEC", "Limit to compaction interval(s): 0=prologue, 1..N, last|live, -1, '1,3', '2-4' (default: all turns)"),
            ],
            "examples": ["histo 7edf", "hist 004c1360", "histo 7edf --format json",
                         "histo 7edf --interval last"],
            "aliases": ["hg", "hist"],
            "repl_only": False,
        },
        "compactions": {
            "usage": "compactions <uuid|path> [--platform P]",
            "summary": "List compaction events and their intervals",
            "detail": [
                "Scans RAW lines for compaction events (lines with isCompactSummary==true,",
                "plus any immediately-preceding compact_boundary system line).",
                "Prints a table of intervals: index, start line, timestamp, summary size,",
                "raw-line range, and how many parsed messages fall in each interval.",
                "Interval 0 is the prologue; the last interval is the live/current region.",
                "Use the interval indexes here with 'read --interval'.",
            ],
            "options": [
                ("--platform claude|codex|gemini|agy", "Force platform detection"),
            ],
            "examples": ["compactions 7edf", "cx 004c1360"],
            "aliases": ["cx"],
            "repl_only": False,
        },
        "list": {
            "usage": "list [--platform P] [--limit N]",
            "summary": "List recent sessions across all platforms",
            "detail": [
                "Shows recent sessions sorted by timestamp.",
                "By default searches Claude, Codex, and Gemini session directories.",
            ],
            "options": [
                ("--platform claude|codex|gemini|agy", "Show only sessions for one platform"),
                ("--limit N", "Number of sessions to show (default: 20)"),
            ],
            "examples": ["list", "list --platform claude --limit 50"],
            "aliases": ["ls"],
            "repl_only": False,
        },
        "toggle": {
            "usage": "toggle <type>",
            "summary": "Toggle visibility of a message type on/off",
            "detail": [
                "Toggles whether messages of the given type are shown in subsequent",
                "read/read-file output. Default state: tool_use and tool_result are OFF,",
                "all others are ON. Use 'show' to see current state.",
                f"Valid types: {types_list}, skill, agent_result, injected",
            ],
            "options": [],
            "examples": ["toggle tool_use", "toggle thinking"],
            "aliases": [],
            "repl_only": True,
        },
        "show": {
            "usage": "show",
            "summary": "Show current type visibility and range filter state",
            "detail": [
                "Displays which message types are ON/OFF and the active range filter.",
                "Types toggled OFF will be hidden from read/read-file output.",
            ],
            "options": [],
            "examples": ["show"],
            "aliases": [],
            "repl_only": True,
        },
        "range": {
            "usage": "range <range> | range off",
            "summary": "Set or clear the persistent range filter",
            "detail": [
                "Sets a range filter that persists across read commands in the REPL.",
                "Message ranges are 1-based. Turn ranges use a 't' prefix.",
                "  1-10    messages 1 through 10",
                "  -20     last 20 messages",
                "  5-      message 5 to end",
                "  t1-5    turns 1 through 5 (a turn = one user + one assistant exchange)",
                "  t-4     last 4 turns",
                "'range off' clears the filter. 'range' with no args shows current state.",
            ],
            "options": [],
            "examples": ["range 1-10", "range -20", "range t1-5", "range off"],
            "aliases": [],
            "repl_only": True,
        },
        "help": {
            "usage": "help [command]",
            "summary": "Show this help, or detailed help for a specific command",
            "detail": [
                "With no arguments, shows a summary of all commands.",
                "With a command name, shows detailed help for that command.",
            ],
            "options": [],
            "examples": ["help", "help read", "help toggle"],
            "aliases": ["?", "h"],
            "repl_only": False,
        },
    }


def _render_command_help(cmd_name: str, entry: dict) -> str:
    """Render detailed help for a single command."""
    H = lambda t: c(t, Colors.BOLD, Colors.BRIGHT_CYAN)
    C = lambda t: c(t, Colors.BRIGHT_GREEN)
    D = lambda t: c(t, Colors.DIM)
    F = lambda t: c(t, Colors.YELLOW)

    lines = [
        H(cmd_name) + ("  " + D("(REPL only)") if entry.get("repl_only") else ""),
        f"  {C(entry['usage'])}",
        "",
    ]
    for line in entry["detail"]:
        lines.append(f"  {line}")

    if entry["options"]:
        lines.append("")
        lines.append(f"  {H('Options:')}")
        for flag, desc in entry["options"]:
            lines.append(f"    {F(flag)}")
            lines.append(f"      {D(desc)}")

    if entry["examples"]:
        lines.append("")
        lines.append(f"  {H('Examples:')}")
        for ex in entry["examples"]:
            lines.append(f"    {C(ex)}")

    if entry["aliases"]:
        lines.append("")
        lines.append(f"  {D('Aliases: ' + ', '.join(entry['aliases']))}")

    return "\n".join(lines)


def cmd_help(args: list[str]) -> str:
    """Show help overview or per-command help."""
    entries = _command_help_entries()

    # Per-command help: help read, help toggle, etc.
    if args:
        cmd_name = args[0].lower()
        cmd_name = COMMAND_ALIASES.get(cmd_name, cmd_name)
        if cmd_name in entries:
            return _render_command_help(cmd_name, entries[cmd_name])
        return c(f"Unknown command: {cmd_name}. Type 'help' for a list of commands.", Colors.YELLOW)

    H = lambda t: c(t, Colors.BOLD, Colors.BRIGHT_CYAN)
    C = lambda t: c(t, Colors.BRIGHT_GREEN)
    D = lambda t: c(t, Colors.DIM)
    F = lambda t: c(t, Colors.YELLOW)

    lines = [
        c("read_jsonl", Colors.BOLD) + f" v{VERSION}" + D(" -- multi-platform CLI session reader"),
        "",
        H("OVERVIEW"),
        D("  read_jsonl is the canonical READER of Claude Code / Codex / Gemini session"),
        D("  transcripts (the append-only .jsonl files each CLI writes). It walks a transcript,"),
        D("  classifies every record (user, response, thinking, tool_use, tool_result, system,"),
        D("  meta, skill, agent_result, injected, compaction-summary, and off-chain client-only"),
        D("  lines), and renders the slice you ask for in text / markdown / json / memorex."),
        "",
        D("  It is the ANALYSIS layer of the context-reclaim ladder (see DESIGN_context_reclaim.md):"),
        D("  it does not itself shed context -- the write/reclaim levers live in sibling tools"),
        D("  (chain_skip.py = Offload, memory_manager = Summarize/Recall, session_bounce = Bounce)."),
        D("  read_jsonl feeds those decisions: 'stats' and 'histo' show WHAT is sheddable and where"),
        D("  the bytes are; 'extract' mines already-compacted history for briefings and Recall;"),
        D("  'compactions' + --interval navigate compaction boundaries; and --resolve rehydrates"),
        D("  Offload/Engram stubs so you read the ORIGINAL archived content in place (a live Restore-"),
        D("  for-reading, disk untouched)."),
        "",
        D("  WHEN to reach for it: inspect any past or current session by UUID / display-name / path,"),
        D("  audit a transcript before or after a reclaim op, or extract a turn-range to brief another"),
        D("  session. Run with NO arguments to enter the interactive REPL (persistent toggle + range)."),
        "",
        H("USAGE"),
        f"  {C('read_jsonl.py')}                                   {D('Start interactive REPL')}",
        f"  {C('read_jsonl.py')} {F('<command>')} {D('[target]')} {D('[options]')}     {D('Run a single command')}",
        f"  {C('read_jsonl.py')} {F('--help')} | {F('help')} {D('[command]')}          {D('Show help')}",
        "",
        H("COMMANDS"),
    ]
    for name, entry in entries.items():
        if entry.get("repl_only") or name == "help":
            continue
        alias_str = ""
        if entry["aliases"]:
            alias_str = D(f"  ({', '.join(entry['aliases'])})")
        lines.append(f"  {C(name):<30s} {D(entry['summary'])}{alias_str}")

    lines.append("")
    lines.append(H("REPL COMMANDS") + D(" (interactive mode only)"))
    for name, entry in entries.items():
        if not entry.get("repl_only"):
            continue
        lines.append(f"  {C(name):<30s} {D(entry['summary'])}")

    lines.append("")
    lines.append(f"  {C('help'):<30s} {D(entries['help']['summary'])}")
    lines.append(f"  {C('quit'):<30s} {D('Exit the REPL')}")

    lines.append("")
    lines.append(H("OPTIONS") + D(" (available on read, read-file, extract, and list)"))
    lines.append(f"  {F('--platform')} {D('claude|codex|gemini|agy')}  {D('Filter or force platform (default: all/auto)')}")
    lines.append(f"  {F('--format')} {D('json|text|markdown|memorex')}    {D('Output format (default: text). memorex = colored Memorex-style cards')}")
    lines.append(f"  {F('--type/--types')} {D('user,response,...')} {D('Filter by message type (comma-separated); aliases: tools, conversation, assistant')}")
    lines.append(f"          {D('Types: user, response, thinking, tool_use, tool_result, system, meta, skill, agent_result, injected')}")
    lines.append(f"  {F('--range')} {D('1-10 | -20 | t1-5 | t-4')}  {D('Message range (1-based) or legacy t-range')}")
    lines.append(f"  {F('--turns')} {D('10-20 | 10- | -5')}       {D('Absolute Tn turn range; useful with extract/--interval')}")
    lines.append(f"  {F('--limit')} {D('N')}                  {D('Limit number of sessions shown (default: 20)')}")
    lines.append(f"  {F('--no-color')}                    {D('Disable color output (for piping to tools that choke on ANSI)')}")
    lines.append(f"  {F('--resolve')}                     {D('Rehydrate offload stubs from their archive (read/read-file; off by default)')}")
    lines.append(f"  {F('--interval')} {D('SPEC')}               {D('Filter to compaction interval(s): 0=prologue, 1..N, last|live, -1, 1,3, 2-4')}")
    lines.append(f"  {F('--all-intervals')}              {D('Whole-history parse for compacted sessions (extract uses this by default)')}")
    lines.append(f"  {F('--include-client-only')}         {D('Merge client-only raw lines inline as META (read/read-file/extract). See: compactions')}")

    lines.append("")
    lines.append(H("OUTPUT FIELDS"))
    lines.append(f"  {D('Message header is')} {c('[Tt #N LMMM]', Colors.BRIGHT_CYAN, Colors.BOLD)}{D(':')}")
    lines.append(f"    {F('Tt')}   {D('= conversation turn number (first submitted prompt = T0; `pre` = the pre-first-prompt prologue)')}")
    lines.append(f"    {F('#N')}   {D('= message number (1-based ordinal over CONVERSATION messages only)')}")
    lines.append(f"    {F('LMMM')} {D('= raw JSONL file line this message came from')}")
    lines.append(f"  {D('json fields: turn_number=Tt, line_number=#N, source_line=LMMM')}")
    lines.append(f"  {D('WHY #N != LMMM: one JSONL line can yield several messages (an assistant line may hold a')}")
    lines.append(f"  {D('thinking + a tool_use + text → 3 messages, 1 line), and most JSONL lines are not messages at')}")
    lines.append(f"  {D('all (file-history snapshots, progress, attachments, mode/title/agent state). So #N << LMMM.')}")

    lines.append("")
    lines.append(H("EXAMPLES"))
    lines.append(f"  {C('read_jsonl.py 7edf')}                        {D('read session 7edf (partial UUID) in default text')}")
    lines.append(f"  {C('read_jsonl.py 7edf --type user,response')}   {D('just the conversation, drop tools/thinking')}")
    lines.append(f"  {C('read_jsonl.py read 7edf --resolve')}         {D('read with Offload/Engram stubs rehydrated (Restore-for-reading)')}")
    lines.append(f"  {C('read_jsonl.py stats 7edf --split-offloaded')} {D('byte stats + Full/Stub breakout: what is still sheddable')}")
    lines.append(f"  {C('read_jsonl.py histo 7edf --interval last')}  {D('per-turn byte histogram of the live region')}")
    lines.append(f"  {C('read_jsonl.py compactions 7edf')}            {D('list compaction boundaries + interval indexes')}")
    lines.append(f"  {C('read_jsonl.py extract 7edf --types conversation --turns 40-55')}")
    lines.append(f"      {D('mine turns 40-55 across all intervals as markdown for a briefing / Recall')}")
    lines.append(f"  {C('read_jsonl.py list --platform claude --limit 50')} {D('recent sessions, newest first')}")
    lines.append("")
    lines.append(D("Type 'help <command>' for detailed help on any command."))

    return "\n".join(lines)


def _help_examples() -> str:
    """Show help with sample output for key commands."""
    H = lambda t: c(t, Colors.BOLD, Colors.BRIGHT_CYAN)
    C = lambda t: c(t, Colors.BRIGHT_GREEN)
    D = lambda t: c(t, Colors.DIM)
    F = lambda t: c(t, Colors.YELLOW)

    # Build sample output snippets
    _sample_tool_input = '{"file_path": "/deploy.sh"}'
    _sample_json_output = '[{"role": "user", "type": "user", "content": "...", ...}]'
    # Header format is [Tt #N LMMM]: turn / message-ordinal / raw file line.
    # All four below are one turn (T1): a user prompt + the assistant's reply blocks.
    sample_num1 = c("[T1 #1 L13]", Colors.BRIGHT_CYAN, Colors.BOLD)
    sample_num2 = c("[T1 #2 L14]", Colors.BRIGHT_CYAN, Colors.BOLD)
    sample_num3 = c("[T1 #3 L14]", Colors.BRIGHT_CYAN, Colors.BOLD)
    sample_num4 = c("[T1 #4 L14]", Colors.BRIGHT_CYAN, Colors.BOLD)
    sample_ts = c("[2026-03-31T14:22:05]", Colors.DIM)
    sample_user = c("USER", Colors.BRIGHT_BLUE, Colors.BOLD)
    sample_resp = c("RESPONSE", Colors.BRIGHT_GREEN)
    sample_think = c("THINKING", Colors.MAGENTA)
    sample_tool = c("TOOL_USE", Colors.YELLOW)
    sample_sep = c("=" * 40, Colors.DIM)

    lines = [
        c("read_jsonl", Colors.BOLD) + " -- Examples with sample output",
        "",
        H("READING A SESSION"),
        f"  $ {C('read_jsonl.py read 7edf')}",
        "",
        f"  {sample_sep}",
        f"  {sample_num1} {sample_ts} {sample_user}:",
        f"  {c('List all Python files in the project', Colors.BRIGHT_WHITE)}",
        f"  {sample_sep}",
        f"  {sample_num2} {sample_ts} {sample_resp}:",
        f"  {c('I will search for Python files in the project directory.', Colors.BRIGHT_WHITE)}",
        "",
        H("FILTERING BY TYPE"),
        f"  $ {C('read_jsonl.py read 7edf')} {F('--type user,response')}",
        f"  {D('Shows only user messages and assistant text responses (no tools)')}",
        "",
        f"  $ {C('read_jsonl.py read 7edf')} {F('--type thinking')}",
        f"  {D('Shows only Claude thinking blocks')}",
        "",
        H("RANGE SELECTION"),
        f"  $ {C('read_jsonl.py read 7edf')} {F('--range 1-5')}",
        f"  {D('First 5 messages only')}",
        "",
        f"  $ {C('read_jsonl.py read 7edf')} {F('--range -10')}",
        f"  {D('Last 10 messages')}",
        "",
        H("REPL MODE WITH TOGGLES"),
        f"  $ {C('read_jsonl.py')}",
        f"  {c('jsonl>', Colors.CYAN)} read 7edf",
        f"  {D('...(messages displayed)...')}",
        f"  {c('jsonl>', Colors.CYAN)} toggle tool_use",
        f"  {D('tool_use: OFF')}",
        f"  {c('jsonl>', Colors.CYAN)} toggle tool_result",
        f"  {D('tool_result: OFF')}",
        f"  {c('jsonl>', Colors.CYAN)} show",
        f"    user: {c('ON', Colors.GREEN)}  response: {c('ON', Colors.GREEN)}  thinking: {c('ON', Colors.GREEN)}",
        f"    tool_use: {c('OFF', Colors.RED)}  tool_result: {c('OFF', Colors.RED)}  system: {c('ON', Colors.GREEN)}  meta: {c('ON', Colors.GREEN)}",
        "",
        H("TEXT OUTPUT FORMAT"),
        f"  {sample_num1} {sample_ts} {sample_user}:",
        f"  {c('What does the deploy script do?', Colors.BRIGHT_WHITE)}",
        f"  {sample_sep}",
        f"  {sample_num2} {sample_ts} {sample_think}:",
        f"  {c('Let me look at the deploy script to understand its purpose...', Colors.DIM, Colors.ITALIC)}",
        f"  {sample_sep}",
        f"  {sample_num3} {sample_ts} {sample_tool} ({c('Read', Colors.YELLOW, Colors.BOLD)}):",
        f"  {c(_sample_tool_input, Colors.DIM)}",
        f"  {sample_sep}",
        f"  {sample_num4} {sample_ts} {sample_resp}:",
        f"  {c('The deploy script runs database migrations then restarts services.', Colors.BRIGHT_WHITE)}",
        "",
        H("JSON OUTPUT"),
        f"  $ {C('read_jsonl.py read 7edf')} {F('--format json')}",
        f"  {D(_sample_json_output)}",
    ]
    return "\n".join(lines)


# =============================================================================
# REPL toggle state
# =============================================================================

_repl_toggles: dict[str, bool] = {
    "user": True,
    "response": True,
    "thinking": True,
    "tool_use": False,
    "tool_result": False,
    "system": True,
    "meta": True,
    "skill": True,
    "agent_result": True,
    "injected": True,
}

_repl_range: str | None = None


def _apply_toggles(msgs: list[Message]) -> list[Message]:
    """Filter messages based on current REPL toggle state."""
    return [m for m in msgs if _repl_toggles.get(m.type.value, True)]


def cmd_toggle(args: list[str]) -> str:
    """Toggle visibility of a message type."""
    if not args:
        return "Usage: toggle <type>  (types: user, response, thinking, tool_use, tool_result, system, meta)"
    type_name = args[0].lower()
    if type_name not in _repl_toggles:
        return c(f"Unknown type: {type_name}. Valid: {', '.join(_repl_toggles.keys())}", Colors.YELLOW)
    _repl_toggles[type_name] = not _repl_toggles[type_name]
    state = c("ON", Colors.GREEN) if _repl_toggles[type_name] else c("OFF", Colors.RED)
    return f"{type_name}: {state}"


def cmd_show(args: list[str]) -> str:
    """Show current toggle state."""
    parts = []
    for t, on in _repl_toggles.items():
        state = c("ON", Colors.GREEN) if on else c("OFF", Colors.RED)
        parts.append(f"  {t}: {state}")
    result = "\n".join(parts)
    if _repl_range:
        result += f"\n  range: {c(_repl_range, Colors.YELLOW)}"
    else:
        result += f"\n  range: {c('(all)', Colors.DIM)}"
    return result


def run_command(line: str, interactive: bool = True) -> str | None:
    """Parse and execute a command. Returns output string or None."""
    global _repl_range

    try:
        parts = shlex.split(line)
    except ValueError as e:
        return f"Parse error: {e}"

    if not parts:
        return None

    cmd = parts[0].lower().lstrip("-")
    args = parts[1:]
    cmd = COMMAND_ALIASES.get(cmd, cmd)

    # Per-command help: "read help", "toggle help", etc.
    if args and args[0].lower() == "help" and cmd != "help":
        return cmd_help([cmd])

    # REPL-only commands
    if interactive:
        if cmd == "toggle":
            return cmd_toggle(args)
        if cmd == "show":
            return cmd_show(args)
        if cmd == "range":
            if args and args[0].lower() == "off":
                _repl_range = None
                return c("Range filter cleared.", Colors.DIM)
            elif args:
                _repl_range = args[0]
                return c(f"Range set to: {_repl_range}", Colors.YELLOW)
            else:
                if _repl_range:
                    return c(f"Current range: {_repl_range}", Colors.YELLOW)
                return c("No range set. Usage: range 1-10 | range 5- | range -20 | range off", Colors.DIM)

    commands = {
        "read": lambda: _cmd_read_with_repl(args, interactive),
        "extract": lambda: cmd_extract(args),
        "read-file": lambda: _cmd_read_file_with_repl(args, interactive),
        "find": lambda: cmd_find(args),
        "summary": lambda: cmd_summary(args),
        "stats": lambda: cmd_stats(args),
        "histo": lambda: cmd_histo(args),
        "compactions": lambda: cmd_compactions(args),
        "list": lambda: cmd_list_sessions(args),
        "help": lambda: cmd_help(args),
    }

    if cmd in commands:
        return commands[cmd]()

    if interactive and cmd in ("quit", "exit", "q"):
        return None

    return c(f"Unknown command: {cmd}. Type 'help' for options.", Colors.YELLOW)


def _cmd_read_with_repl(args: list[str], interactive: bool) -> str:
    """Read with REPL toggles and range applied. Supports multiple UUIDs/paths."""
    if not args:
        return "Usage: read <uuid|path> [uuid2 ...] [--format F] [--platform P] [--type T] [--range R] [--interval SPEC] [--include-client-only] [--sort newest|oldest] [--show-private]"
    include_client_only = "--include-client-only" in args
    args = [a for a in args if a != "--include-client-only"]
    fmt = _parse_flag(args, "--format") or "text"
    platform = _parse_flag(args, "--platform")
    type_filter = _parse_message_types_arg(args)
    range_str = _parse_flag(args, "--range") or (_repl_range if interactive else None)
    turns_str = _parse_flag(args, "--turns")
    interval_spec = _parse_flag(args, "--interval")
    sort_order = _parse_flag(args, "--sort")
    show_private = "--show-private" in args
    resolve = "--resolve" in args
    all_intervals = "--all-intervals" in args
    expand = _parse_memorex_expand(_parse_flag(args, "--expand"))
    queries = _strip_flags(args, ["--format", "--platform", "--range", "--turns", "--interval", "--sort", "--show-private", "--resolve", "--expand"], multi_flags=["--type", "--types"])
    queries = [q for q in queries if q != "--all-intervals"]

    if not queries:
        return "Usage: read <uuid|path> [uuid2 ...] [--format F] [--platform P] [--type T] [--range R] [--interval SPEC] [--include-client-only] [--sort newest|oldest] [--show-private] [--resolve]"

    all_msgs = []
    for query in queries:
        path = find_jsonl(query)
        if not path:
            return c(f"Session not found: {query}", Colors.RED)
        m = parse_session(path, platform=platform, all_intervals=(all_intervals or bool(interval_spec)))
        if resolve:
            m = resolve_archived_stubs(m, path)
        if include_client_only:
            m = sorted(m + client_only_meta_messages(path), key=lambda x: x.source_line)
        if interval_spec:
            selected, err = _select_intervals(interval_spec, compaction_intervals(path))
            if err:
                return c(err, Colors.YELLOW)
            m = _apply_interval_filter(m, selected)
        all_msgs.extend(m)

    # Apply --range FIRST, on the full chronological list, so turn-grouping (t-ranges)
    # can see USER messages for boundaries. Filtering to e.g. response,thinking strips
    # USER msgs, which collapses everything into ONE turn and makes t-N select the whole
    # file. Range selects the window; type/private/sort then apply within it.
    return _filter_and_format_messages(all_msgs, fmt=fmt, type_filter=type_filter,
                                       range_str=range_str, turns_str=turns_str,
                                       show_private=show_private, sort_order=sort_order,
                                       apply_toggles=interactive, expand=expand)


def _cmd_read_file_with_repl(args: list[str], interactive: bool) -> str:
    """Read-file with REPL toggles and range applied."""
    include_client_only = "--include-client-only" in args
    args = [a for a in args if a != "--include-client-only"]
    fmt = _parse_flag(args, "--format") or "text"
    platform = _parse_flag(args, "--platform")
    type_filter = _parse_message_types_arg(args)
    range_str = _parse_flag(args, "--range") or (_repl_range if interactive else None)
    turns_str = _parse_flag(args, "--turns")
    interval_spec = _parse_flag(args, "--interval")
    sort_order = _parse_flag(args, "--sort")
    show_private = "--show-private" in args
    resolve = "--resolve" in args
    all_intervals = "--all-intervals" in args
    expand = _parse_memorex_expand(_parse_flag(args, "--expand"))
    paths = _strip_flags(args, ["--format", "--platform", "--range", "--turns", "--interval", "--sort", "--show-private", "--resolve", "--expand"], multi_flags=["--type", "--types"])
    paths = [p for p in paths if p != "--all-intervals"]

    if not paths:
        return "Usage: read-file <path> [path2 ...] [--format F] [--platform P] [--type T] [--range R] [--interval SPEC] [--include-client-only] [--sort newest|oldest] [--show-private] [--resolve]"

    all_msgs = []
    for p_str in paths:
        p = Path(p_str)
        if not p.exists():
            return c(f"File not found: {p}", Colors.RED)
        m = parse_session(p, platform=platform, all_intervals=(all_intervals or bool(interval_spec)))
        if resolve:
            m = resolve_archived_stubs(m, p)
        if include_client_only:
            m = sorted(m + client_only_meta_messages(p), key=lambda x: x.source_line)
        if interval_spec:
            selected, err = _select_intervals(interval_spec, compaction_intervals(p))
            if err:
                return c(err, Colors.YELLOW)
            m = _apply_interval_filter(m, selected)
        all_msgs.extend(m)

    # Apply --range FIRST, on the full chronological list, so turn-grouping (t-ranges)
    # can see USER messages for boundaries. Filtering to e.g. response,thinking strips
    # USER msgs, which collapses everything into ONE turn and makes t-N select the whole
    # file. Range selects the window; type/private/sort then apply within it.
    return _filter_and_format_messages(all_msgs, fmt=fmt, type_filter=type_filter,
                                       range_str=range_str, turns_str=turns_str,
                                       show_private=show_private, sort_order=sort_order,
                                       apply_toggles=interactive, expand=expand)


def repl():
    """Interactive REPL mode."""
    from uai_toolkit.common_utils.lib_readline import setup_readline
    setup_readline(history_file=READLINE_HISTORY, history_length=500)

    print(c(f"read_jsonl v{VERSION}", Colors.BOLD) + " -- multi-platform CLI session reader")
    print(c("Type 'help' for commands, 'quit' to exit.", Colors.DIM))
    print(c("Default: tool_use and tool_result hidden. Use 'toggle' to change.", Colors.DIM) + "\n")

    while True:
        try:
            if Colors.enabled():
                prompt = f"\001{Colors.CYAN}\002jsonl>\001{Colors.RESET}\002 "
            else:
                prompt = "jsonl> "
            line = input(prompt).strip()
        except (EOFError, KeyboardInterrupt):
            print("\nExiting.")
            break

        if not line:
            continue
        if line.lower() in ("quit", "exit", "q"):
            break

        result = run_command(line, interactive=True)
        if result:
            print(result)


# =============================================================================
# CLI Interface
# =============================================================================
def main():
    args = sys.argv[1:]

    # --no-color is handled early by Colors.enabled() via sys.argv check.
    # Strip it so downstream command parsing doesn't choke on it.
    args = [a for a in args if a != "--no-color"]

    # Handle --help-examples before anything else
    if "--help-examples" in args:
        Colors._enabled = None
        print(_help_examples())
        return 0

    # --help or -h with no command → show overview help
    if not args or args == ["--help"] or args == ["-h"]:
        if not args:
            repl()
            return 0
        Colors._enabled = None
        print(cmd_help([]))
        return 0

    # --help after a command: read --help → help read
    if "--help" in args or "-h" in args:
        cmd_name = args[0].lower().lstrip("-")
        cmd_name = COMMAND_ALIASES.get(cmd_name, cmd_name)
        Colors._enabled = None
        print(cmd_help([cmd_name]))
        return 0

    # If the first arg isn't a known command, treat it as a session identifier
    # and prepend "read" — so `read_jsonl.py Cortex` means `read Cortex`
    _KNOWN_CMDS = set(COMMAND_ALIASES.keys()) | set(COMMAND_ALIASES.values()) | {
        "read", "extract", "read-file", "find", "summary", "stats", "histo", "compactions", "list", "help",
        "toggle", "set", "grep",
    }
    if args and args[0].lower().lstrip("-") not in _KNOWN_CMDS:
        args = ["read"] + args

    command_line = " ".join(shlex.quote(a) for a in args)
    result = run_command(command_line, interactive=False)
    if result:
        print(result)
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
