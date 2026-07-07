#!/usr/bin/env python3
"""
session_ops.py — High-level session operations.

Composes substrate primitives (send_keys, dump_screen) with platform-specific
parsing to provide semantic operations like "discover UUID" and "get AI status."

CLI usage:
    session_ops.py list-sessions
    session_ops.py read-terminal <session_name>
    session_ops.py get-status <session_name> [--platform claude_cli]
    session_ops.py discover-uuid <session_name> --platform <platform>
    session_ops.py write-to <session_name> --text "hello"
    session_ops.py write-to <session_name> --text "hello" --enter
    session_ops.py write-to <session_name> --text-file /tmp/prompt.txt --enter

All output is JSON to stdout for app consumption.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
_CLI_DIR = _SCRIPT_DIR.parent / "cli"
_AI_SCRIPTS = _SCRIPT_DIR.parent  # ~/bin/ai/ (ai_general/scripts/)
for _d in (_SCRIPT_DIR, _CLI_DIR, _AI_SCRIPTS):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

from uai_toolkit.session_mgmt.lib_session_substrate import build_tmux_command, get_substrate, SubstrateError
from uai_toolkit.common_utils.lib_clean_text import clean_text

try:
    from uai_toolkit.session_mgmt.lib_session_activity import set_activity_state
except Exception:  # pragma: no cover - status reads must never break on this
    set_activity_state = None

# Structured logging — best-effort; must never break session ops if unavailable.
try:
    from uai_toolkit.common_utils.lib_logging import get_logger
    log = get_logger(__name__)
except Exception:  # pragma: no cover - logging is auxiliary, never fatal
    import logging as _logging
    log = _logging.getLogger("session_ops")

# Path for common_utils (lib_readline, etc.)
_PY_SRC = Path.home() / "bin" / "all_languages" / "python" / "src"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))

# Path for standard_colors
_UTILS_DIR = _AI_SCRIPTS / "utils"
if str(_UTILS_DIR) not in sys.path:
    sys.path.insert(0, str(_UTILS_DIR))

HISTORY_FILE = Path.home() / ".session_ops_history"

# Lazy-loaded to avoid import cost on write-to / list-sessions paths
_session_store = None

def _get_store():
    """Lazy-load SessionStore singleton."""
    global _session_store
    if _session_store is None:
        from uai_toolkit.session_mgmt.session_store import SessionStore
        _session_store = SessionStore()
    return _session_store


def _normalize_identifier(identifier: str) -> str:
    """Extract the session id from any ref (centralized, action-aware — see lib_uri).

    Accepts uai://session/<id>, uai://session/<id>/<action>, prompt://…, or raw id.
    Fixes the prior bug where uai://session/<id>/message returned '<id>/message'.
    """
    if '://' in identifier:
        try:
            from uai_toolkit.session_mgmt.lib_uri import session_id_of
            return session_id_of(identifier)
        except Exception:
            pass
    return identifier


def _diagnose_session_reference(identifier: str) -> dict:
    """Explain WHY a session op found no live session — store-aware.

    The substrate only sees one tmux/zellij server and reports a bare
    "Session 'X' does not exist". This inspects the store to name the real cause:
      - the name resolves to a record whose terminal isn't live (it exited);
      - the name is shared by several records (collision / shadowing) — the exact
        failure behind the 'Relay' incident;
      - a session IS live, but under a different server than the one addressed.
    Returns {'hint': str, 'records': [...]}; empty on any failure (never raises).
    """
    ident = _normalize_identifier(identifier)
    try:
        store = _get_store()
        with store._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM sessions WHERE terminal_session = ? OR display_name = ? "
                "OR tracking_id = ? OR cli_session_id = ?",
                (ident, ident, ident, ident),
            ).fetchall()
        records = [store._row_to_dict(r) for r in rows]
        live_probe = store._get_live_terminal_sessions()
    except Exception:
        return {}

    rec_info, live_records = [], []
    for r in records:
        try:
            is_live = store._session_is_live(r, live_probe)
        except Exception:
            is_live = False
        rec_info.append({
            "tracking_id": r.get("tracking_id"),
            "terminal_session": r.get("terminal_session"),
            "tmux_server": r.get("tmux_server"),
            "substrate": r.get("substrate"),
            "stored_status": r.get("status"),
            "live": is_live,
        })
        if is_live:
            live_records.append(r)

    if not rec_info:
        hint = (f"No session-store record matches {identifier!r}; the name/id is "
                "unknown. Run `session_ops.py list-sessions`.")
    elif live_records:
        r = live_records[0]
        hint = (f"{identifier!r} IS live as {r.get('tracking_id')} on "
                f"{r.get('substrate')} server {r.get('tmux_server')!r}; the op targeted "
                "a different server. Address it by tracking id or pass the matching "
                "--substrate.")
        if len(rec_info) > 1:
            hint += (f" WARNING: {len(rec_info)} records share this name — a collision "
                     "may resolve to the wrong one.")
    else:
        servers = ", ".join(sorted({str(r["tmux_server"]) for r in rec_info}))
        hint = (f"{identifier!r} matches {len(rec_info)} store record(s) (server(s): "
                f"{servers}) but none has a LIVE terminal — the session has exited and "
                "its stored status is stale. Reconcile with "
                "`session_store.py validate-running --fix`, or delete the record.")
        if len(rec_info) > 1:
            hint += " Multiple stale records share this name (collision)."
    return {"hint": hint, "records": rec_info}


def _resolve_session(identifier: str) -> dict | None:
    """Resolve any session identifier via SessionStore.

    Accepts URIs (uai://session/<id>) or raw identifiers.
    Tries tracking_id, terminal_session, cli_uuid (exact match).
    Returns the session dict or None.
    """
    try:
        return _get_store().resolve(_normalize_identifier(identifier))
    except Exception:
        return None


def _resolve_terminal_name(identifier: str) -> str:
    """Map any session identifier — tracking_id, cli_uuid, display name, or a
    uai://session/<id> URI — to the *terminal-session* name the substrate actually
    addresses (the tmux session name, == tracking_id for managed sessions).

    The substrate only knows terminal names; handed a cli_uuid it finds nothing
    ("Session '<uuid>' does not exist"). This resolves via the store first so the
    ops below accept any identifier. Falls back to the (URI-normalized) identifier
    when the store can't resolve it — e.g. an unmanaged session — so existing
    tracking-id/terminal-name callers are unaffected."""
    ident = _normalize_identifier(identifier)
    stored = _resolve_session(ident)
    if stored:
        return stored.get("terminal_session") or stored.get("tracking_id") or ident
    return ident


def _resolve_substrate_for_session(
    session_name: str | None,
    substrate: str | None = None,
):
    """Resolve substrate with session-aware server selection.

    Accepts URIs (uai://session/<id>) or raw session names.
    If the session exists in SessionStore and records a substrate/server,
    use that so sessions under isolated servers remain addressable.
    """
    from uai_toolkit.session_mgmt.lib_session_substrate import get_substrate

    if session_name:
        session_name = _normalize_identifier(session_name)

    stored = _resolve_session(session_name) if session_name else None
    platform_substrate = stored.get("substrate") if stored else None
    stored_server = stored.get("tmux_server") if stored else None

    effective_substrate = substrate or platform_substrate
    if effective_substrate == "tmux" or (effective_substrate is None and stored_server):
        return get_substrate(override=effective_substrate, tmux_server_name=stored_server)
    return get_substrate(override=effective_substrate)


# =============================================================================
# Platform-specific screen parsers
# =============================================================================

# UUID pattern — standard 36-char UUID
UUID_RE = re.compile(r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', re.IGNORECASE)

# Claude Code status patterns
CLAUDE_SESSION_ID_RE = re.compile(r'Session ID[:\s]+([0-9a-f-]{36})', re.IGNORECASE)
CLAUDE_UUID_RE = re.compile(r'UUID[:\s]+([0-9a-f-]{36})', re.IGNORECASE)
# Active-response spinner line, e.g. "✽ Composing… (1m 9s · ↓ 2.4k tokens)".
# Duration may lead with any unit (5s / 1m 9s / 2h 3m), so anchor on \(\d+[hms]
# — NOT \(\d+s, which silently misses every response running over a minute.
CLAUDE_THINKING_RE = re.compile(r'[✻✳✢✽✶·⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏⏺]\s+\w+.*?\(\d+[hms]')
CLAUDE_QUEUED_RE = re.compile(r'Press up to edit queued messages', re.IGNORECASE)
CLAUDE_PROMPT_RE = re.compile(r'^❯\s*$', re.MULTILINE)
CLAUDE_PROMPT_OCCUPIED_RE = re.compile(r'^❯\s*\S', re.MULTILINE)
CLAUDE_CTX_RE = re.compile(r'(?:ctx|avail|used)[:\s]*(\d+)%', re.IGNORECASE)
CLAUDE_PERMISSION_RE = re.compile(r'(?:Do you want to|Allow .+ to|proceed\? \[Y/n\])', re.IGNORECASE)

# Codex patterns — /stats shows "Session: UUID" and "Context window: N% left"
CODEX_SESSION_RE = re.compile(r'Session[:\s]+([0-9a-f-]{36})', re.IGNORECASE)
CODEX_CTX_RE = re.compile(r'Context window[:\s]+(\d+)%\s+left', re.IGNORECASE)
# Codex footer (status bar) — "… · ~/AI/ai_root · Ready ·…" (idle/occupied) vs
# "… · Working · …" (responding). The footer line carries the UUID + " · gpt…"
# + " · Context N% used/left". Status word after the cwd is the cheap, reliable
# Codex-specific responding signal.
CODEX_FOOTER_RE = re.compile(r'·\s*(?:Context\s+\d+%\s+(?:left|used)|Ctx\s+\d+%)', re.IGNORECASE)
CODEX_CTX_FOOTER_RE = re.compile(r'Context\s+(\d+)%\s+(left|used)', re.IGNORECASE)
CODEX_WORKING_RE = re.compile(r'·\s*Working\b')
CODEX_READY_RE = re.compile(r'·\s*Ready\b')
CODEX_INTERRUPT_RE = re.compile(r'esc to interrupt', re.IGNORECASE)
# Memorex canonical verb-line (cross-CLI active-response tell): a single glyph,
# whitespace, a single word, then a gerund-tied ellipsis — anchored at the TRUE
# (untrimmed) start of line. Source: memorex.md §2.5 (impl /^\S\s+\S+…/).
MEMOREX_ACTIVE_VERB_RE = re.compile(r'^\S\s+\S+…')
# When the Codex footer status word is absent/ambiguous, the live "esc to
# interrupt"/verb-line signals are only meaningful at the bottom of the
# viewport — never deep in scrollback. Bound the fallback scan to this many
# trailing lines so historical/quoted occurrences can't false-positive.
CODEX_LIVE_TAIL_LINES = 15

# ANSI SGR stripper — for parsing styled (color/attr-preserving) terminal dumps.
_ANSI_SGR_RE = re.compile(r'\x1b\[[0-9;:?]*[ -/]*[@-~]')


def _strip_ansi(s: str) -> str:
    """Remove ANSI escape sequences, returning visible text."""
    return _ANSI_SGR_RE.sub('', s)

# Gemini patterns — session ID appears as "Session ID: UUID" in /stats output
# and as short hex in the status bar footer
GEMINI_SESSION_ID_RE = re.compile(r'Session ID[:\s]+([0-9a-f-]{36})', re.IGNORECASE)
GEMINI_SESSION_SHORT_RE = re.compile(r'\s([0-9a-f]{8})\s', re.MULTILINE)
GEMINI_CTX_RE = re.compile(r'(\d+)%\s+used', re.IGNORECASE)
GEMINI_MODEL_RE = re.compile(r'gemini-[\w.-]+', re.IGNORECASE)


def parse_ai_status(platform: str, screen_text: str) -> dict:
    """Parse terminal screen content into structured AI status.

    Returns:
        {
            "state": "idle" | "prompt_occupied" | "responding" | "blocked" | "permission_prompt" | "exited" | "unknown",
            "context_percent": int | null,
            "uuid": str | null,
            "model": str | null,
            "raw_lines": int
        }
    """
    lines = screen_text.strip().split('\n')
    last_lines = lines[-15:] if len(lines) > 15 else lines
    bottom_text = '\n'.join(last_lines)
    full_text = screen_text

    result = {
        "state": "unknown",
        "context_percent": None,
        "uuid": None,
        "model": None,
        "raw_lines": len(lines),
    }

    if platform == "claude_cli":
        _parse_claude_status(result, full_text, bottom_text)
    elif platform == "codex_cli":
        _parse_codex_status(result, full_text, bottom_text)
    elif platform == "gemini_cli":
        _parse_gemini_status(result, full_text, bottom_text)

    return result


def _parse_claude_status(result: dict, full_text: str, bottom_text: str) -> None:
    """Parse Claude Code terminal output. Expects STYLED (ANSI-preserving) text.

    Text signals (UUID, context, model, spinner, permission) run on the visible
    (ANSI-stripped) text. The prompt-occupancy distinction needs the ANSI: an
    empty input box renders a DIMMED ghost suggestion (SGR 2, e.g.
    "❯ Write the doc") that must NOT read as typed text — real input is not dim.
    """
    vis_full = _strip_ansi(full_text)
    vis_bottom = _strip_ansi(bottom_text)
    raw_bottom_lines = bottom_text.split('\n')

    # UUID from status bar
    m = CLAUDE_UUID_RE.search(vis_full)
    if m:
        result["uuid"] = m.group(1)

    # Session ID (alternative pattern)
    if not result["uuid"]:
        m = CLAUDE_SESSION_ID_RE.search(vis_full)
        if m:
            result["uuid"] = m.group(1)

    # Context % — normalize to % USED (not available/remaining)
    m = CLAUDE_CTX_RE.search(vis_full)
    if m:
        label = vis_full[m.start():m.start()+5].lower()
        pct = int(m.group(1))
        if "avail" in label:
            result["context_percent"] = 100 - pct  # available → used
        elif "used" in label:
            result["context_percent"] = pct  # already used
        elif "ctx" in label:
            result["context_percent"] = pct  # treat as used

    # Model. Match a canonical dashed id (claude-opus-4-8[1m]) OR the 2.1.x
    # friendly statusline form ("Opus 4.8 (1M context)") — never a bare "Opus",
    # which is a useless fragment that would shadow the authoritative store
    # value (see get_ai_status). No IGNORECASE: dashed ids are lowercase and
    # friendly names are capitalized, so we avoid matching "opus" in prose.
    # Search the statusline region only — the model legitimately appears in the
    # statusline, never in conversation scrollback. Searching full_text would
    # false-match model-ish strings the session itself printed (e.g. a grep for
    # "claude-3" in its own output).
    model_re = re.search(
        r'(claude-[\w.\[\]-]+|(?:Opus|Sonnet|Haiku|Fable)\s+[\d.]+(?:\s*\([^)]*\))?)',
        vis_bottom,
    )
    if model_re:
        result["model"] = model_re.group(1).strip()

    # State detection (check bottom of screen)
    # Order matters: check responding indicators first, then prompt state
    if CLAUDE_THINKING_RE.search(vis_bottom):
        result["state"] = "responding"
    elif CLAUDE_QUEUED_RE.search(vis_bottom):
        result["state"] = "responding"
    elif CLAUDE_PERMISSION_RE.search(vis_bottom):
        result["state"] = "permission_prompt"
    else:
        # Find the LAST ❯ prompt line in the visible bottom — that's the live
        # input box. Pair it with the matching RAW line to read the dim
        # attribute: a dimmed (SGR 2) ghost suggestion is NOT typed text.
        prompt_idx = None
        for i, vline in enumerate(_strip_ansi(rb) for rb in raw_bottom_lines):
            if re.match(r'^❯', vline):
                prompt_idx = i
        if prompt_idx is not None:
            raw_line = raw_bottom_lines[prompt_idx]
            after_prompt = _strip_ansi(raw_line)[1:].strip()
            is_dim = bool(re.search(r'\x1b\[(?:[0-9;]*;)?2m', raw_line))
            if after_prompt and not is_dim:
                result["state"] = "prompt_occupied"
            else:
                # empty box, or a dimmed ghost suggestion → at-prompt, clear
                result["state"] = "idle"
        else:
            result["state"] = "unknown"


def _parse_codex_status(result: dict, full_text: str, bottom_text: str) -> None:
    """Parse Codex terminal output. Expects STYLED (ANSI-preserving) text.

    Codex /stats output:
      Session: 019d5a84-a127-7ed0-a63d-4f01a2b2cb1f
      Context window: 40% left (160K used / 258K)

    Codex footer (one-line status bar):
      019edd69-… · gpt-5.5 medium · Context 65% used · 258K window · … ·
      ~/AI/ai_root · Ready ·…          (idle / typed-but-unsent)
      …                  · Working · … (responding)

    State signals (confirmed against captured styled samples):
      * RESPONDING — footer status word "Working" (idle/occupied show "Ready");
        also the "esc to interrupt" live line or the Memorex anchored verb-line.
        The footer word is the cheap Codex-specific signal; the verb-line is the
        cross-CLI robust one.
      * IDLE vs PROMPT_OCCUPIED — the live prompt is the FIRST ›/> line ABOVE the
        footer. An empty box renders a DIMMED placeholder (ANSI ESC[2m, e.g.
        "› Implement {feature}"); real typed text is NOT dim. So dim/empty → idle,
        non-dim text → prompt_occupied. Scrollback ›-lines are ignored (only the
        first marker above the footer is live).
    """
    raw_lines = full_text.split('\n')
    vis_lines = [_strip_ansi(ln) for ln in raw_lines]
    vis_full = '\n'.join(vis_lines)

    # UUID — /stats "Session: UUID" first, then footer-leading UUID
    m = CODEX_SESSION_RE.search(vis_full)
    if m:
        result["uuid"] = m.group(1)
    if not result.get("uuid"):
        m = re.search(
            r'^\s*([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})\s+·',
            vis_full, re.MULTILINE | re.IGNORECASE)
        if m:
            result["uuid"] = m.group(1)

    # Context % — /stats "N% left" first, then footer "Context N% used|left"
    m = CODEX_CTX_RE.search(vis_full)
    if m:
        result["context_percent"] = 100 - int(m.group(1))  # "40% left" → 60% used
    if not result.get("context_percent"):
        m = CODEX_CTX_FOOTER_RE.search(vis_full)
        if m:
            pct = int(m.group(1))
            result["context_percent"] = pct if m.group(2).lower() == "used" else 100 - pct

    # Locate the footer (status-bar) line: carries " · Context N% used/left".
    footer_idx = None
    for i, v in enumerate(vis_lines):
        if ' · ' in v and CODEX_FOOTER_RE.search(v):
            footer_idx = i  # take the LAST such line (the live footer)
    # Fallback: a line with a leading UUID + " · " (footer without the ctx token)
    if footer_idx is None:
        for i, v in enumerate(vis_lines):
            if ' · ' in v and re.search(r'[0-9a-f]{8}-[0-9a-f]{4}.*·', v):
                footer_idx = i

    footer_vis = vis_lines[footer_idx] if footer_idx is not None else bottom_text

    # --- RESPONDING detection ---
    # The Codex footer status word is authoritative: "Working" while responding,
    # "Ready" when idle/occupied. Trust it whenever it's present. Only fall back
    # to the live-line heuristics when the footer word is absent/ambiguous — and
    # even then scan ONLY the live tail (viewport bottom), never the full
    # scrollback. Previously these signals were matched against ALL of `above`
    # (the entire scrollback), so any historical/quoted "esc to interrupt" or
    # "<glyph> <word>…" line — e.g. source/docs about this very detector sitting
    # in a session's scrollback — falsely pinned an idle session as "responding"
    # (which made it look "busy", so queued prompts were never delivered).
    responding = False
    if CODEX_WORKING_RE.search(footer_vis):
        responding = True                       # footer status word = Working
    elif not CODEX_READY_RE.search(footer_vis):
        # No clear footer word — fall back to live-tail signals only.
        for raw in raw_lines[-CODEX_LIVE_TAIL_LINES:]:
            v = _strip_ansi(raw)
            if CODEX_INTERRUPT_RE.search(v):     # "(…s • esc to interrupt)" live line
                responding = True
                break
            if MEMOREX_ACTIVE_VERB_RE.match(v):  # cross-CLI gerund-tied ellipsis
                responding = True
                break

    if responding:
        result["state"] = "responding"
        return

    # --- IDLE vs PROMPT_OCCUPIED: the live prompt = first ›/> line ABOVE footer ---
    prompt_raw = None
    scan = range((footer_idx - 1) if footer_idx is not None else len(raw_lines) - 1, -1, -1)
    for i in scan:
        v = vis_lines[i].lstrip()
        if v[:1] in ('›', '>'):
            prompt_raw = raw_lines[i]
            break

    if prompt_raw is None:
        # No live prompt line found (footer says Ready) — empty box → idle.
        result["state"] = "idle"
        return

    # Text after the glyph: dimmed (ESC[2m) placeholder → idle; real typed → occupied.
    after_glyph_vis = _strip_ansi(prompt_raw).lstrip()[1:].strip()
    is_dim = '\x1b[2m' in prompt_raw
    if is_dim or not after_glyph_vis:
        result["state"] = "idle"
    else:
        result["state"] = "prompt_occupied"


def _resolve_gemini_uuid8(uuid8: str) -> str | None:
    """Resolve a Gemini 8-char short UUID to the full UUID.

    Scans ~/.gemini/tmp/*/chats/session-*-{uuid8}.json and reads sessionId.
    Returns full UUID or None.
    """
    try:
        gemini_tmp = Path.home() / ".gemini" / "tmp"
        if not gemini_tmp.exists():
            return None
        for session_file in gemini_tmp.rglob(f"session-*-{uuid8}.json"):
            try:
                data = json.loads(session_file.read_text())
                full_uuid = data.get("sessionId", "")
                if full_uuid and len(full_uuid) == 36 and full_uuid.startswith(uuid8):
                    return full_uuid
            except (json.JSONDecodeError, OSError):
                continue
    except Exception:
        pass
    return None


def _parse_gemini_status(result: dict, full_text: str, bottom_text: str) -> None:
    """Parse Gemini terminal output.

    Gemini status bar format (at bottom of screen):
    session  |  workspace  |  model  |  context  |  memory  |  tokens
    8cb11e7b    ~/dir         gemini-2.5-flash   2% used    285.2 MB   46.6k tokens
    """
    # Session ID — try full UUID first (from /stats output), then short hex from status bar
    m = GEMINI_SESSION_ID_RE.search(full_text)
    if m:
        result["uuid"] = m.group(1)
    else:
        m = GEMINI_SESSION_SHORT_RE.search(full_text)
        if m:
            uuid8 = m.group(1)
            # Resolve short UUID to full UUID via session file
            full_uuid = _resolve_gemini_uuid8(uuid8)
            result["uuid"] = full_uuid or uuid8

    # Context %
    m = GEMINI_CTX_RE.search(full_text)
    if m:
        result["context_percent"] = int(m.group(1))  # "2% used" → 2% used

    # Model
    m = GEMINI_MODEL_RE.search(full_text)
    if m:
        result["model"] = m.group(0)

    # State — Gemini shows ">" prompt when idle, "? for shortcuts" in status area
    # Check for prompt with text after it (prompt_occupied) vs empty prompt (idle)
    if re.search(r'>\s+Type your message', bottom_text):
        result["state"] = "idle"
    elif re.search(r'[>❯]\s*$', bottom_text, re.MULTILINE):
        result["state"] = "idle"
    elif re.search(r'[>❯]\s*\S', bottom_text):
        result["state"] = "prompt_occupied"
    else:
        result["state"] = "unknown"


# =============================================================================
# High-level operations
# =============================================================================

def _discover_tmux_servers() -> list[str | None]:
    """Discover all running tmux servers from socket directory.

    Returns a list of server names. None represents the default (unnamed) server.
    """
    uid = os.getuid()
    socket_dir = Path("/tmp") / "tmux-{}".format(uid)
    if not socket_dir.is_dir():
        return [None]
    servers = []
    for entry in sorted(socket_dir.iterdir()):
        name = entry.name
        if name == "default":
            servers.append(None)  # default server = no -L flag
        else:
            servers.append(name)
    return servers or [None]


def list_sessions(substrate: str | None = None) -> list[dict]:
    """List all terminal sessions across all tmux servers."""
    from uai_toolkit.session_mgmt.lib_session_substrate import TmuxSubstrate

    # For non-tmux substrates, fall back to single-server query
    sub = get_substrate(override=substrate)
    if not isinstance(sub, TmuxSubstrate):
        sessions = sub.list_sessions()
        return [
            {
                "name": s.name,
                "running": s.running,
                "attached": s.attached,
                "created": s.created.isoformat() if s.created else None,
                "server": None,
            }
            for s in sessions
        ]

    # Query all tmux servers
    all_sessions = []
    seen = set()
    for server_name in _discover_tmux_servers():
        try:
            tsub = TmuxSubstrate(server_name=server_name)
            for s in tsub.list_sessions():
                if s.name not in seen:
                    seen.add(s.name)
                    all_sessions.append({
                        "name": s.name,
                        "running": s.running,
                        "attached": s.attached,
                        "created": s.created.isoformat() if s.created else None,
                        "server": server_name or "default",
                    })
        except Exception:
            continue  # server socket exists but tmux not responding

    return all_sessions


def read_terminal(session_name: str, full: bool = False, substrate: str | None = None,
                   raw: bool = False, styled: bool = False) -> str:
    """Read current terminal screen content, cleaned for parsing.

    Args:
        session_name: Session identifier. Accepts URIs (uai://session/<id>).
        substrate: Override substrate name (e.g. "tmux"). None = use global default.
        raw: If True, return raw dump without cleaning.
        styled: If True, preserve terminal formatting (colors, bold, etc.).
    """
    session_name = _resolve_terminal_name(session_name)
    sub = _resolve_substrate_for_session(session_name, substrate)
    if full:
        try:
            text = sub.dump_screen(session_name, full=True, plain_text=not styled)
        except TypeError:
            text = sub.dump_screen(session_name, plain_text=not styled)
    else:
        text = sub.dump_screen(session_name, plain_text=not styled)

    if raw or styled:
        return text

    return clean_text(
        text,
        remove_ansi=True,
        collapse_blanks=True,
        max_blank_lines=1,
        strip_trailing=True,
    )


def _infer_platform(session_name: str) -> str:
    """Infer platform from session/tracking ID prefix."""
    for prefix in ("codex_cli", "gemini_cli", "claude_cli"):
        if session_name.startswith(prefix):
            return prefix
    return "claude_cli"


def _read_activity_state(session_dir):
    """Return 'idle' | 'busy' from {session_dir}/activity_state.json, or None.

    Recorded event-driven by the Stop (idle) and UserPromptSubmit (busy) hooks —
    an authoritative lifecycle signal, unlike scraping the terminal prompt.
    """
    if not session_dir:
        return None
    try:
        p = Path(session_dir) / "activity_state.json"
        if p.exists():
            return json.loads(p.read_text()).get("state")
    except (OSError, ValueError):
        pass
    return None


def get_ai_status(session_name: str, platform: str = "", substrate: str | None = None) -> dict:
    """Get AI status by reading and parsing the terminal screen.

    Enriches with store metadata (platform, uuid, model) when available,
    then overlays live state from screen parsing.

    Cross-references the UUID parsed from the live terminal footer with
    the UUID stored in the session registry. If they differ, adds a
    uuid_mismatch warning with the fix command.
    """
    session_name = _normalize_identifier(session_name)
    # Resolve session from uai_toolkit.session_mgmt.store for authoritative metadata
    stored = _resolve_session(session_name)

    if not platform:
        if stored and stored.get("platform"):
            platform = stored["platform"]
        else:
            platform = _infer_platform(session_name)

    # Claude and Codex state detection needs ANSI attributes: a dimmed ghost
    # suggestion / placeholder (SGR 2) in the input box must not read as typed
    # text, and Codex carries its responding signal in the footer status word.
    # Gemini still parses cleaned text.
    styled = platform in ("claude_cli", "codex_cli")
    screen = read_terminal(session_name, substrate=substrate, styled=styled)
    result = parse_ai_status(platform, screen)

    # Backfill from uai_toolkit.session_mgmt.store — screen parse wins for live state, but the STORE is
    # authoritative for model. The 2.1.x statusline only renders a friendly name
    # the scrape can't normalize to a canonical id, so a stored model always
    # wins; the scrape supplies model only for sessions absent from the store.
    # Tradeoff: a mid-session /model switch isn't reflected until the store is
    # updated — acceptable for launch-pinned managed sessions.
    if stored:
        if stored.get("model"):
            result["model"] = stored["model"]
        # Add store-only fields
        result["tracking_id"] = stored.get("tracking_id")
        result["platform"] = platform
        result["display_name"] = stored.get("display_name")

        # Activity-state overlay — the hook-written busy/idle flag is a TIEBREAKER
        # for an UNREADABLE screen only; a confident screen read always wins.
        #
        # Why not let "busy" override a confident idle? During a real response the
        # input box shows the spinner/streaming line (caught by CLAUDE_THINKING_RE →
        # "responding"), NEVER an empty "❯". So a confident idle (empty, dim-aware
        # prompt box) unambiguously means the turn ended. A "busy" flag whose matching
        # Stop hook never fired — Esc-interrupt, crash, a detached/bounced session, or
        # an injected prompt that never ran — would otherwise pin the session
        # "responding" indefinitely (observed: sessions stuck "breathing" idle for
        # hours/days). prompt_occupied likewise reflects a real, done-responding state
        # with a typed draft and must never be downgraded.
        #
        # When the screen is genuinely "unknown" (mid-redraw, a full-screen tool UI),
        # fall back to the flag: busy → responding, idle → idle. The unambiguous
        # states (permission_prompt/blocked/exited) always keep their parsed value.
        if result.get("state") == "unknown":
            _act = _read_activity_state(stored.get("session_dir"))
            if _act == "busy":
                result["state"] = "responding"
            elif _act == "idle":
                result["state"] = "idle"

        # Cross-reference UUIDs: live terminal vs. store
        live_uuid = result.get("uuid")
        store_uuid = stored.get("cli_session_id")
        tracking_id = stored.get("tracking_id", session_name)

        if live_uuid and store_uuid:
            # For Gemini short UUIDs (8 chars), compare prefix
            if len(live_uuid) == 8:
                match = store_uuid.startswith(live_uuid)
            else:
                match = live_uuid == store_uuid
            if not match:
                ai_root = os.environ.get("AI_ROOT",
                    os.path.expanduser("~/AI/ai_root"))
                fix_cmd = (f"{ai_root}/ai_general/scripts/session_mgmt/"
                           f"session_store.py update {tracking_id} "
                           f"--set cli_session_id={live_uuid}")
                result["uuid_mismatch"] = {
                    "store_uuid": store_uuid,
                    "live_uuid": live_uuid,
                    "fix_command": fix_cmd,
                }
        elif live_uuid and not store_uuid:
            # Store has no UUID but live terminal does — backfill opportunity
            ai_root = os.environ.get("AI_ROOT",
                os.path.expanduser("~/AI/ai_root"))
            fix_cmd = (f"{ai_root}/ai_general/scripts/session_mgmt/"
                       f"session_store.py update {tracking_id} "
                       f"--set cli_session_id={live_uuid}")
            result["uuid_missing_from_store"] = {
                "live_uuid": live_uuid,
                "fix_command": fix_cmd,
            }

        # Backfill uuid: prefer live, fall back to store
        if not result.get("uuid") and store_uuid:
            result["uuid"] = store_uuid

        # Persist the reconciled ground-truth state so consumers (the UAI app) can
        # read it without calling get-status themselves. This is the on-demand
        # reconciler-writer: it catches prompt_occupied / permission / blocked AND
        # corrects a stale "responding" left by an interrupted turn (no Stop hook
        # fires on Esc, but the terminal — and thus this parse — reflects idle).
        # Change-guarded (only writes + signals on a real transition); never writes
        # "unknown" over a known state.
        if set_activity_state:
            set_activity_state(stored.get("session_dir"), stored.get("tracking_id"), result.get("state"))

    return result


def _audit_emit_session_write(session_name, text, delivery, press_enter, success, substrate_name):
    """Emit audit event for session write. Never raises."""
    try:
        import sys as _sys
        _src = str(Path.home() / "bin" / "ai")
        if _src not in _sys.path:
            _sys.path.insert(0, _src)
        from audit import lib_audit
        lib_audit.emit(
            category="comms",
            action="session_write",
            target={"type": "cli_session", "session": session_name, "substrate": substrate_name},
            details={
                "text_length": len(text),
                "text_preview": text[:512],
                "delivery": delivery,
                "submit": press_enter,
                "success": success,
            },
        )
    except Exception:
        pass  # Silent failure per spec


def write_to(
    session_name: str,
    text: str,
    press_enter: bool = False,
    substrate: str | None = None,
    delivery: str = "paste",
) -> None:
    """Write text to a terminal session. Optionally press Enter after.

    Args:
        substrate: Override substrate name (e.g. "tmux"). None = use global default.
        delivery: "paste" uses substrate default write_chars; "typed" uses a
            literal typed-character path where available.
    """
    session_name = _resolve_terminal_name(session_name)
    sub = _resolve_substrate_for_session(session_name, substrate)
    substrate_name = getattr(sub, "substrate_name", type(sub).__name__)
    success = True
    try:
        if delivery == "typed":
            typed_writer = getattr(sub, "write_chars_typed", None)
            if callable(typed_writer):
                typed_writer(session_name, text)
            else:
                sub.write_chars(session_name, text)
            if press_enter:
                sub.send_keys(session_name, "")
            return

        if press_enter:
            sub.send_keys(session_name, text)  # send_keys appends Enter
        else:
            sub.write_chars(session_name, text)
    except Exception:
        success = False
        raise
    finally:
        _audit_emit_session_write(session_name, text, delivery, press_enter, success, substrate_name)


def send_raw(session_name: str, text: str, *, substrate: str | None = None) -> None:
    """Deliver RAW turn-triggering text to a session — NO sender wrapper, NOT a
    slash command. The third TTY lane (see instr_session_messaging two-axis model):

        send_prompt  → wraps with sender attribution (agent↔agent communication)
        send_slash   → carries a /command the CLI executes (gated by allowlist/token)
        send_raw     → raw, non-command text the model processes as a turn (this)

    Use for SYSTEM-originated turn-triggers like the launcher's <<<SESSION RESUMED>>>
    wake marker: the raw text both wakes the idle session AND self-describes.

    INFRA / ORCHESTRATION ONLY — not an agent comms tool. Raw unattributed injection
    can make a session act as if the USER typed, which is exactly the impersonation
    risk `wrap_with_sender` exists to prevent; so agents send communication via the
    wrapped `send_prompt` path, never this.

    Refuses payloads that would be parsed as a CLI command (leading '/'), so it can
    never be a backdoor around send_slash_command's allowlist/token gate.

    Raises ValueError on a command-like payload. Submits the text (presses Enter).
    """
    if text.lstrip().startswith("/"):
        raise ValueError(
            "send_raw refuses command-like payloads (leading '/'); slash commands "
            "must go through send_slash_command (allowlist + token gate)")
    write_to(session_name, text, press_enter=True, substrate=substrate)


def discover_uuid(session_name: str, platform: str, timeout: float = 10.0) -> str | None:
    """Discover a session's CLI UUID.

    Strategy:
    1. Read screen — UUID may already be visible (status bar, /stats output)
    2. If not found, send /status (Claude) or /stats (Codex/Gemini)
    3. Wait, read screen again, parse
    4. Dismiss status overlay (Escape)

    Returns UUID string or None.
    """
    session_name = _resolve_terminal_name(session_name)
    substrate = _resolve_substrate_for_session(session_name)

    # Strategy 1: Check if UUID is already visible on screen
    try:
        screen = substrate.dump_screen(session_name)
        status = parse_ai_status(platform, screen)
        if status.get("uuid"):
            return status["uuid"]
    except SubstrateError:
        return None

    # Strategy 2: Send status command and parse the response
    # Platform-specific status commands (verified against real sessions)
    status_cmds = {
        "claude_cli": "/status",
        "codex_cli": "/status",
        "gemini_cli": "/stats session",
    }
    status_cmd = status_cmds.get(platform, "/status")

    try:
        substrate.send_keys(session_name, status_cmd)
    except SubstrateError:
        return None

    # Wait for the status output to render
    time.sleep(3)

    try:
        screen = substrate.dump_screen(session_name)
    except SubstrateError:
        return None

    status = parse_ai_status(platform, screen)
    uuid = status.get("uuid")

    # Dismiss status overlay (Escape key = byte 27)
    _send_escape(substrate, session_name)

    return uuid


def send_key_names(session_name: str, keys, substrate=None) -> None:
    """Send true NAMED key-presses to a session (e.g. ['Up','Up','Enter'] or 'Escape').

    The sanctioned interface for driving interactive TUIs (e.g. the /rewind picker)
    — a literal text paste cannot operate them. Goes through the substrate
    (DESIGN: session_ops is the only sender; the substrate owns the multiplexer).
    Raises SubstrateError on substrates without named-key support (non-tmux).
    """
    session_name = _resolve_terminal_name(session_name)
    sub = substrate or get_substrate()
    sub.send_key_names(session_name, keys)


def _send_escape(substrate, session_name: str) -> None:
    """Send Escape key to dismiss status overlays (best effort)."""
    try:
        substrate.send_key_names(session_name, "Escape")
    except Exception:
        pass  # best effort


def _collect_descendant_pids(root_pid: int) -> list[int]:
    """Return root_pid plus all descendant PIDs, deepest-first.

    Walks the process tree via `ps -eo pid=,ppid=`. Deepest-first ordering so
    children are killed before parents. Used only to SIGKILL a tmux pane's
    process subtree — root_pid must be a pane_pid, never the tmux server PID.
    """
    import subprocess as _sp
    children: dict[int, list[int]] = {}
    try:
        out = _sp.run(
            ["ps", "-eo", "pid=,ppid="],
            capture_output=True, text=True, timeout=5,
        ).stdout
    except Exception:
        return [root_pid]
    for ln in out.splitlines():
        fields = ln.split()
        if len(fields) != 2:
            continue
        try:
            pid, ppid = int(fields[0]), int(fields[1])
        except ValueError:
            continue
        children.setdefault(ppid, []).append(pid)

    ordered: list[int] = []

    def _walk(pid: int) -> None:
        for child in children.get(pid, []):
            _walk(child)
        ordered.append(pid)

    _walk(root_pid)
    return ordered


def force_kill_session(session_name: str, substrate: str | None = None) -> dict:
    """Graceful kill, then SIGKILL the pane process tree if still alive.

    Escalation is strictly scoped to the one session's pane process and its
    descendants. The pane PID comes from the substrate's _get_session_pid
    (tmux list-panes -F '#{pane_pid}') — the shell/agent process inside the
    pane, which is a child of (never equal to) the tmux server. So this can
    never SIGKILL the tmux server or any other session's processes.
    """
    import signal as _signal

    session_name = _resolve_terminal_name(session_name)
    sub = _resolve_substrate_for_session(session_name, substrate)

    # Capture pane PID(s) BEFORE the graceful kill tears the session down.
    pane_pids: list[int] = []
    get_pid = getattr(sub, "_get_session_pid", None)
    if callable(get_pid):
        try:
            pid = get_pid(session_name)
            if pid:
                pane_pids.append(int(pid))
        except Exception:
            pass

    # Step 1: graceful kill (tmux kill-session sends SIGHUP to pane processes).
    sub.kill_session(session_name)

    # Step 2: if the session still exists, SIGKILL the pane process tree.
    # Scoped to descendants of pane_pids only — never the tmux server.
    killed: list[int] = []
    try:
        still_running = sub.session_is_running(session_name)
    except Exception:
        still_running = False

    if still_running and pane_pids:
        for pane_pid in pane_pids:
            for pid in _collect_descendant_pids(pane_pid):
                try:
                    os.kill(pid, _signal.SIGKILL)
                    killed.append(pid)
                except ProcessLookupError:
                    pass  # already gone
                except PermissionError:
                    pass  # not ours to kill; skip
        # Reap the now-defunct session entry, best effort.
        try:
            if sub.session_is_running(session_name):
                sub.kill_session(session_name)
        except Exception:
            pass

    return {
        "ok": True,
        "session": session_name,
        "forced": bool(killed),
        "killed_pids": killed,
    }


# =============================================================================
# REPL — Interactive session operations
# =============================================================================

def repl() -> int:
    """Interactive session operations REPL.

    Commands:
      list                           List all terminal sessions
      read [session]                 Read terminal screen content
      status [session]               Get AI session status
      write [session] <text>         Write text to session (press Enter after)
      attach [session]               Attach to a terminal session
      uuid [session]                 Discover session UUID
      kill [session]                 Kill a terminal session
      rename [session] <new_name>    Rename a terminal session
      as <session>                   Set default target session
      whoami                         Show current target session
      help                           Show commands
      q / quit / exit                Exit REPL
    """
    from uai_toolkit.common_utils.lib_readline import setup_readline, make_session_completer
    from standard_colors import c, bold, dim, heading, format_help

    setup_readline(history_file=HISTORY_FILE, history_length=200,
                   completer=make_session_completer())

    current_session = ""

    def _display_label(name: str) -> str:
        """Get a short display label for a session name."""
        # Try to get a display name from the store
        stored = _resolve_session(name)
        if stored and stored.get("display_name"):
            return stored["display_name"]
        # Truncate long tracking IDs
        if len(name) > 30:
            return name[:27] + "..."
        return name

    def prompt_str() -> str:
        if not current_session:
            return c("ops", "dim") + c(":*>", "bright_yellow") + " "
        label = _display_label(current_session)
        return c("ops:", "dim") + c(label, "bright_yellow", "bold") + c(">", "dim") + " "

    def _effective_session(args_session: str) -> str:
        """Return the explicit session arg or the current default."""
        if args_session:
            return args_session
        if current_session:
            return current_session
        return ""

    def _require_session(args_session: str, usage: str) -> str | None:
        """Return effective session or print error and return None."""
        s = _effective_session(args_session)
        if not s:
            print(f"  {c('No session specified.', 'warning')} Use {c('as <session>', 'command')} first, or: {c(usage, 'dim')}")
            return None
        return s

    # Welcome
    print(f"{heading('Session Ops REPL')} -- type {c('help', 'command')} for commands, {c('q', 'command')} to quit")
    count = len(list_sessions())
    print(f"{c('Sessions:', 'label')} {bold(str(count))}\n")

    while True:
        try:
            line = input(prompt_str()).strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break

        if not line:
            continue

        parts = line.split(None, 1)
        cmd = parts[0].lower()
        rest = parts[1].strip() if len(parts) > 1 else ""

        if cmd in ("quit", "exit", "q"):
            break

        elif cmd == "help":
            print(format_help("""
Commands:
  list                           List all terminal sessions
  read [session]                 Read terminal screen content
  status [session]               Get AI session status
  write [session] <text>         Write text to session (sends Enter)
  attach [session]               Attach to session (blocks until detach)
  uuid [session]                 Discover session UUID via /status
  kill [session]                 Kill a terminal session
  rename [session] <new_name>    Rename a terminal session
  as <session>                   Set default target session
  whoami                         Show current target session
  help                           This help
  q / quit / exit                Exit

When a default session is set via 'as', commands use it if no session is given.
"""))

        elif cmd == "as":
            if not rest:
                print(f"  {dim('Usage:')} {c('as <session_name_or_tracking_id>', 'command')}")
                continue
            if rest.lower() in ("none", "clear", "*"):
                current_session = ""
                print(f"  {c('Session scope cleared.', 'warning')}")
            else:
                # Try to resolve via store — use terminal_session as the
                # effective name since substrate operations need it
                stored = _resolve_session(rest)
                if stored:
                    current_session = stored.get("terminal_session") or stored.get("tracking_id") or rest
                    dname = stored.get("display_name") or current_session
                    print(f"  {dim('Now targeting:')} {c(dname, 'bright_green')} ({dim(current_session)})")
                else:
                    # Accept raw name even if not in store (could be a raw tmux session)
                    current_session = rest
                    print(f"  {dim('Now targeting:')} {c(rest, 'bright_green')} {dim('(not in store)')}")

        elif cmd == "whoami":
            if current_session:
                label = _display_label(current_session)
                print(f"  {c('Target:', 'label')} {c(label, 'bright_green')} ({dim(current_session)})")
            else:
                print(f"  {c('No target set.', 'warning')} Use {c('as <session>', 'command')} to set one.")

        elif cmd == "list":
            try:
                sessions = list_sessions()
                if not sessions:
                    print(f"  {dim('(no sessions)')}")
                else:
                    for s in sessions:
                        name = s.get("name", "")
                        running = c("running", "bright_green") if s.get("running") else c("stopped", "dim")
                        attached = c("attached", "bright_cyan") if s.get("attached") else ""
                        parts_out = [f"  {c(name, 'bold')}", running]
                        if attached:
                            parts_out.append(attached)
                        print("  ".join(parts_out))
                    print(f"\n  {dim(str(len(sessions)) + ' session(s)')}")
            except Exception as e:
                print(f"  {c('Error:', 'error')} {e}")

        elif cmd == "read":
            session = _require_session(rest, "read <session>")
            if not session:
                continue
            try:
                text = read_terminal(session)
                if text.strip():
                    print(text)
                else:
                    print(f"  {dim('(empty screen)')}")
            except Exception as e:
                print(f"  {c('Error:', 'error')} {e}")

        elif cmd == "status":
            session = _require_session(rest, "status <session>")
            if not session:
                continue
            try:
                result = get_ai_status(session)
                state = result.get("state", "unknown")
                state_colors = {
                    "idle": "bright_green",
                    "responding": "bright_yellow",
                    "prompt_occupied": "yellow",
                    "permission_prompt": "bright_red",
                    "blocked": "red",
                    "exited": "dim",
                    "unknown": "dim",
                }
                state_style = state_colors.get(state, "dim")
                print(f"  {c('State:', 'label')}    {c(state, state_style)}")
                ctx = result.get("context_percent")
                if ctx is not None:
                    print(f"  {c('Context:', 'label')}  {ctx}% used")
                uuid_val = result.get("uuid")
                if uuid_val:
                    print(f"  {c('UUID:', 'label')}     {dim(uuid_val)}")
                model = result.get("model")
                if model:
                    print(f"  {c('Model:', 'label')}    {model}")
                platform = result.get("platform")
                if platform:
                    print(f"  {c('Platform:', 'label')} {platform}")
                dname = result.get("display_name")
                if dname:
                    print(f"  {c('Name:', 'label')}     {dname}")
                # Warnings
                if result.get("uuid_mismatch"):
                    mm = result["uuid_mismatch"]
                    print(f"  {c('UUID mismatch!', 'warning')} store={dim(mm['store_uuid'])} live={dim(mm['live_uuid'])}")
            except Exception as e:
                print(f"  {c('Error:', 'error')} {e}")

        elif cmd == "write":
            if not rest:
                session = _require_session("", "write [session] <text>")
                if session:
                    print(f"  {dim('Usage:')} {c('write [session] <text>', 'command')}")
                continue
            # Determine if first token is a session name or text
            tokens = rest.split(None, 1)
            if current_session:
                # If we have a default session, treat everything as text
                session = current_session
                text_to_send = rest
            elif len(tokens) >= 2:
                session = tokens[0]
                text_to_send = tokens[1]
            else:
                print(f"  {dim('Usage:')} {c('write <session> <text>', 'command')} (or set default with {c('as', 'command')})")
                continue
            try:
                write_to(session, text_to_send, press_enter=True)
                print(f"  {c('Sent', 'ok')} {len(text_to_send)} chars to {c(session, 'bold')}")
            except Exception as e:
                print(f"  {c('Error:', 'error')} {e}")

        elif cmd == "attach":
            session = _require_session(rest, "attach <session>")
            if not session:
                continue
            try:
                sub_obj = _resolve_substrate_for_session(session)
                sub_obj.attach(session)
            except Exception as e:
                print(f"  {c('Error:', 'error')} {e}")

        elif cmd == "uuid":
            session = _require_session(rest, "uuid <session>")
            if not session:
                continue
            try:
                # Infer platform
                stored = _resolve_session(session)
                platform = ""
                if stored and stored.get("platform"):
                    platform = stored["platform"]
                else:
                    platform = _infer_platform(session)
                uuid_val = discover_uuid(session, platform)
                if uuid_val:
                    print(f"  {c('UUID:', 'label')} {uuid_val}")
                else:
                    print(f"  {c('UUID not found', 'warning')}")
            except Exception as e:
                print(f"  {c('Error:', 'error')} {e}")

        elif cmd == "kill":
            session = _require_session(rest, "kill <session>")
            if not session:
                continue
            try:
                sub_obj = _resolve_substrate_for_session(session)
                sub_obj.kill_session(session)
                print(f"  {c('Killed', 'ok')} {c(session, 'bold')}")
                # Clear default if we just killed it
                if session == current_session:
                    current_session = ""
            except Exception as e:
                print(f"  {c('Error:', 'error')} {e}")

        elif cmd == "rename":
            if not rest:
                session = _require_session("", "rename [session] <new_name>")
                if session:
                    print(f"  {dim('Usage:')} {c('rename [session] <new_name>', 'command')}")
                continue
            tokens = rest.split(None, 1)
            if current_session and len(tokens) == 1:
                # rename <new_name> (using default session)
                session = current_session
                new_name = tokens[0]
            elif len(tokens) >= 2:
                session = tokens[0]
                new_name = tokens[1]
            else:
                print(f"  {dim('Usage:')} {c('rename <session> <new_name>', 'command')} (or set default with {c('as', 'command')})")
                continue
            try:
                sub_obj = _resolve_substrate_for_session(session)
                sub_obj.rename_session(session, new_name)
                print(f"  {c('Renamed', 'ok')} {c(session, 'dim')} -> {c(new_name, 'bold')}")
                # Update default if we renamed it
                if session == current_session:
                    current_session = new_name
            except Exception as e:
                print(f"  {c('Error:', 'error')} {e}")

        else:
            print(f"  {c('Unknown command:', 'warning')} {cmd} — type {c('help', 'command')} for commands")

    return 0


# =============================================================================
# CLI interface
# =============================================================================

def main() -> int:
    parser = argparse.ArgumentParser(
        prog="session_ops",
        description="High-level session operations — read, status, discover, write.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""commands:
  list-sessions          List all terminal sessions [--substrate] [--oneline]
  read-terminal NAME     Read terminal screen content [--full] [--json] [--no-clean] [--substrate]
  get-status NAME        Get AI session status [--platform] [--oneline]
  discover-uuid NAME     Discover session UUID via /status [--platform] [--timeout]
  attach NAME            Attach to a terminal session (interactive) [--substrate]
  write-to NAME          Write text to a session (--text | --text-file) [--enter] [--delivery] [--substrate]

Use 'session_ops <command> --help' for full details on each command.""",
    )
    sub = parser.add_subparsers(dest="command")

    # list-sessions
    p_list = sub.add_parser("list-sessions", help="List all terminal sessions")
    p_list.add_argument("--substrate", help="Override substrate (tmux, zellij, none)")
    p_list.add_argument("--oneline", action="store_true",
                        help="Print each session on a single tab-separated line: name, running, attached, created")

    # read-terminal
    p_read = sub.add_parser("read-terminal", help="Read terminal screen content")
    p_read.add_argument("session_name")
    p_read.add_argument("--full", action="store_true", help="Include scrollback")
    p_read.add_argument("--json", action="store_true", help="Output as JSON object with content and line count")
    p_read.add_argument("--raw", action="store_true", help="Alias for text output (default)")
    p_read.add_argument("--no-clean", action="store_true", help="Skip text cleaning (return raw terminal dump)")
    p_read.add_argument("--styled", action="store_true", help="Preserve terminal formatting (colors, bold, etc.)")
    p_read.add_argument("--substrate", help="Override substrate (tmux, zellij, none)")

    # get-status
    p_status = sub.add_parser("get-status", help="Get AI session status")
    p_status.add_argument("session_name")
    p_status.add_argument("--platform", default="", help="Platform (auto-detected from session name if omitted)")
    p_status.add_argument("--oneline", action="store_true",
                          help="Print status on a single tab-separated line: state, context%%, uuid, model, platform, display_name")

    # discover-uuid
    p_discover = sub.add_parser("discover-uuid", help="Discover session UUID via /status command")
    p_discover.add_argument("session_name")
    p_discover.add_argument("--platform", required=True, help="Platform (claude_cli, codex_cli, gemini_cli)")
    p_discover.add_argument("--timeout", type=float, default=10.0)

    # attach
    p_attach = sub.add_parser("attach", help="Attach to a terminal session (interactive, blocks until detached)")
    p_attach.add_argument("session_name")
    p_attach.add_argument("--substrate", help="Override substrate (tmux, zellij, none)")

    # write-to
    p_write = sub.add_parser("write-to", help="Write text to a terminal session")
    p_write.add_argument("session_name")
    text_src = p_write.add_mutually_exclusive_group(required=True)
    text_src.add_argument("--text", help="Text to send")
    text_src.add_argument("--text-file", help="Read text to send from a file")
    p_write.add_argument("--enter", action="store_true", help="Press Enter after text")
    p_write.add_argument("--delivery", choices=["paste", "typed"], default="paste",
                         help="Delivery mode: paste (default) or typed literal characters")
    p_write.add_argument("--substrate", help="Override substrate (tmux, zellij, none)")

    # kill
    p_kill = sub.add_parser("kill", help="Kill a terminal session")
    p_kill.add_argument("session_name", help="Session to kill")
    p_kill.add_argument("--substrate", help="Override substrate (tmux, zellij, none)")
    p_kill.add_argument("--force", action="store_true",
                        help="Escalate to SIGKILL of the pane process tree if the "
                             "session survives a graceful kill (scoped to that session, "
                             "never the tmux server)")

    # rename
    p_rename = sub.add_parser("rename", help="Rename a terminal session")
    p_rename.add_argument("session_name", help="Current session name")
    p_rename.add_argument("new_name", help="New session name")
    p_rename.add_argument("--substrate", help="Override substrate (tmux, zellij, none)")

    args = parser.parse_args()

    if not args.command:
        return repl()

    # Normalize URI identifiers (uai://session/<id> → <id>)
    if hasattr(args, 'session_name') and args.session_name:
        args.session_name = _normalize_identifier(args.session_name)

    try:
        if args.command == "list-sessions":
            result = list_sessions(substrate=getattr(args, 'substrate', None))
            if getattr(args, 'oneline', False):
                for s in result:
                    fields = [
                        s.get("name", ""),
                        "running" if s.get("running") else "stopped",
                        "attached" if s.get("attached") else "detached",
                        s.get("created") or "",
                    ]
                    print("\t".join(fields))
            else:
                print(json.dumps(result, indent=2))

        elif args.command == "read-terminal":
            text = read_terminal(args.session_name, full=args.full,
                                 substrate=getattr(args, 'substrate', None),
                                 raw=getattr(args, 'no_clean', False),
                                 styled=getattr(args, 'styled', False))
            if getattr(args, 'json', False):
                print(json.dumps({"content": text, "lines": len(text.split('\n'))},
                                 ensure_ascii=False))
            else:
                print(text)

        elif args.command == "get-status":
            result = get_ai_status(args.session_name, args.platform)
            if getattr(args, 'oneline', False):
                print(json.dumps(result))
            else:
                print(json.dumps(result, indent=2))

        elif args.command == "discover-uuid":
            uuid = discover_uuid(args.session_name, args.platform, timeout=args.timeout)
            print(json.dumps({"uuid": uuid, "discovered": uuid is not None}))

        elif args.command == "attach":
            sub_obj = _resolve_substrate_for_session(args.session_name, getattr(args, 'substrate', None))
            sub_obj.attach(args.session_name, replace_process=True)

        elif args.command == "write-to":
            text = args.text
            if args.text_file:
                text = Path(args.text_file).read_text()
            write_to(args.session_name, text or "", press_enter=args.enter,
                     substrate=getattr(args, 'substrate', None),
                     delivery=args.delivery)
            print(json.dumps({"ok": True}))

        elif args.command == "kill":
            if getattr(args, 'force', False):
                result = force_kill_session(
                    args.session_name, substrate=getattr(args, 'substrate', None),
                )
                print(json.dumps(result))
            else:
                sub_obj = _resolve_substrate_for_session(
                    args.session_name, getattr(args, 'substrate', None),
                )
                sub_obj.kill_session(args.session_name)
                print(json.dumps({"ok": True, "session": args.session_name}))

        elif args.command == "rename":
            sub_obj = _resolve_substrate_for_session(
                args.session_name, getattr(args, 'substrate', None),
            )
            sub_obj.rename_session(args.session_name, args.new_name)
            print(json.dumps({"ok": True, "old_name": args.session_name, "new_name": args.new_name}))

    except SubstrateError as e:
        payload = {"ok": False, "error": str(e)}
        ident = getattr(args, "session_name", None)
        # A bare "does not exist" is often a stale/collided store record or a
        # server mismatch, not a truly-unknown session. Enrich + log so the next
        # 'Relay'-style incident is self-explaining instead of a dead end.
        if ident and ("does not exist" in str(e)
                      or getattr(e, "code", None) == "SESSION_NOT_FOUND"):
            diag = _diagnose_session_reference(ident)
            if diag.get("hint"):
                payload["diagnosis"] = diag["hint"]
                payload["records"] = diag.get("records")
                log.warning("session op %r on %r failed: %s | %s",
                            getattr(args, "command", "?"), ident, str(e), diag["hint"])
        print(json.dumps(payload), file=sys.stderr)
        return 1
    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
