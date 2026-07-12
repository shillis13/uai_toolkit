#!/usr/bin/env python3
"""Read prompt area state and text from active CLI sessions.

Uses session_ops.py get-status to determine prompt_area_clear vs
prompt_area_occupied, and read-terminal to extract the actual typed text
when occupied.

Usage:
    get_prompt_area_texts.py --all-active
    get_prompt_area_texts.py --all-active --format flat
    get_prompt_area_texts.py <tracking_id> [<tracking_id> ...]
    get_prompt_area_texts.py --uri uai://session/<tracking_id>

Output formats:
    json    Pretty-printed JSON array (default)
    flat    Single-line JSON (one object per line, for piping)
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def get_ai_root():
    # type: () -> str
    if os.environ.get("AI_ROOT"):
        return os.environ["AI_ROOT"]
    for candidate in [
        Path.home() / "AI" / "ai_root",
        Path.home() / "AI" / "ai_root",
    ]:
        if candidate.is_dir():
            return str(candidate)
    return str(Path.home() / "AI" / "ai_root")


def _session_ops(ai_root):
    # type: (str) -> str
    return os.path.join(ai_root, "ai_general", "scripts", "session_mgmt", "session_ops.py")


def _session_store(ai_root):
    # type: (str) -> str
    return os.path.join(ai_root, "ai_general", "scripts", "session_mgmt", "session_store.py")


def _run(cmd, ai_root, timeout=10):
    # type: (list, str, int) -> str
    env = {**os.environ, "AI_ROOT": ai_root}
    env["PATH"] = ":".join([
        env.get("PATH", ""),
        "/opt/homebrew/bin", "/usr/local/bin",
    ])
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout, env=env,
        )
        return result.stdout if result.returncode == 0 else ""
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def list_active_sessions(ai_root):
    # type: (str) -> list
    """Get active sessions from session store (status='active')."""
    store = _session_store(ai_root)
    if not os.path.exists(store):
        return []
    out = _run(["python3", store, "list", "--status", "active", "--json"], ai_root)
    if not out.strip():
        return []
    try:
        data = json.loads(out.strip())
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def list_tmux_sessions(ai_root):
    # type: (str) -> dict
    """Get running tmux sessions as name->info dict via session_ops."""
    ops = _session_ops(ai_root)
    out = _run(["python3", ops, "list-sessions"], ai_root)
    if not out.strip():
        return {}
    try:
        data = json.loads(out.strip())
        return {s["name"]: s for s in data if s.get("running")}
    except (json.JSONDecodeError, ValueError):
        return {}


def get_session_status(terminal_session, platform, ai_root):
    # type: (str, str, str) -> dict
    """Get session status via session_ops get-status.

    Returns dict with 'state' (idle, prompt_occupied, responding, etc.),
    'context_percent', 'model', 'uuid'.
    """
    ops = _session_ops(ai_root)
    args = ["python3", ops, "get-status", terminal_session]
    if platform:
        args.extend(["--platform", platform])
    out = _run(args, ai_root, timeout=8)
    if not out.strip():
        return {"state": "unknown"}
    try:
        return json.loads(out.strip())
    except (json.JSONDecodeError, ValueError):
        return {"state": "unknown"}


def _is_hint_text(styled_line):
    # type: (str) -> bool
    """Detect if text after the prompt character is a CLI hint / auto-populated ghost.

    Auto-populated ghost text (the dimmed previous/suggested prompt shown in an EMPTY
    input) is rendered DIM (SGR 2); real user-typed input is rendered normally (not
    dim). This holds across Claude, Codex, and Gemini.

    Verified on live captures (2026-06-19): Claude's auto-populated suggestion shows
    every word wrapped in \x1b[2m with no reverse-video cursor, while the actual input
    buffer is empty —
      Claude: ❯\xa0\x1b[2mWrite\x1b[0m \x1b[2mthe\x1b[0m \x1b[2mdoc\x1b[0m   (ghost, buffer empty)
      Codex:  \x1b[0;1m›\x1b[0m \x1b[2mWrite tests for @filename\x1b[0m       (placeholder)
    A prior attempt to treat Claude dim as REAL text produced false-positive prompt
    indicators (Anvil/Timbre flagged occupied with empty buffers) — reverted.
    """
    import re
    m = re.search(r'[❯›>]', styled_line)
    if not m:
        return False
    after_prompt = styled_line[m.end():]
    # Dim (SGR 2 — possibly combined like 0;2) anywhere in the text ⇒ ghost/placeholder.
    if re.search(r'\x1b\[(?:[0-9;]*;)?2m', after_prompt):
        return True
    return False


def extract_prompt_text(terminal_session, platform, ai_root):
    # type: (str, str, str) -> str
    """Extract the typed prompt text from a session with prompt_occupied state.

    Reads terminal content (both plain and styled) and finds the text after
    the prompt character. Uses ANSI styling to distinguish real user input
    from CLI hint/placeholder text (hints use dim/faint rendering).
    """
    import re
    ops = _session_ops(ai_root)

    # Get both plain and styled output
    plain_out = _run(["python3", ops, "read-terminal", terminal_session], ai_root, timeout=8)
    styled_out = _run(["python3", ops, "read-terminal", terminal_session, "--styled"], ai_root, timeout=8)

    if not plain_out:
        return ""

    plain_lines = plain_out.rstrip("\n").split("\n")
    styled_lines = styled_out.rstrip("\n").split("\n") if styled_out else []

    # Platform-specific prompt char
    prompt_chars = {"claude_cli": "❯", "codex_cli": "›", "gemini_cli": ">"}
    pchar = prompt_chars.get(platform, "❯")
    pchar_pattern = "[❯›>]" if not platform else re.escape(pchar)

    # Find the last prompt line in plain output to get the text
    prompt_text = ""
    for line in reversed(plain_lines):
        m = re.match(r'^(' + pchar_pattern + r')\s*(.*)', line)
        if m:
            prompt_text = m.group(2).strip()
            break

    if not prompt_text:
        return ""

    # Check styled output for hint detection — find the LAST line containing
    # the prompt char in styled output (independent of plain line index)
    for styled_line in reversed(styled_lines):
        if re.search(pchar_pattern, styled_line):
            if _is_hint_text(styled_line):
                return ""  # It's a hint/placeholder, not user text
            break

    return prompt_text


def parse_uri(uri):
    # type: (str) -> dict
    """Parse URI to extract session identifier.

    Supports:
      uai://session/<tracking_id>
      uai://session/<platform>/<tracking_id>
      prompt://<platform>/<session_name>
    """
    if uri.startswith("uai://session/"):
        rest = uri[len("uai://session/"):]
        parts = rest.strip("/").split("/")
        if len(parts) == 1:
            return {"id": parts[0]}
        elif len(parts) >= 2:
            return {"platform": parts[0], "id": parts[1]}
    elif uri.startswith("prompt://"):
        rest = uri[len("prompt://"):]
        parts = rest.split("/", 1)
        if len(parts) >= 2:
            return {"platform": parts[0].replace("-", "_"), "name": parts[1]}
    return {}


def match_session(session, parsed_uri):
    # type: (dict, dict) -> bool
    tid = session.get("tracking_id", "")
    name = (session.get("display_name") or "").lower()
    term = (session.get("terminal_session") or "").lower()

    target_id = parsed_uri.get("id", "").lower()
    target_name = parsed_uri.get("name", "").lower()

    if target_id and (tid.lower() == target_id or term == target_id or name == target_id):
        return True
    if target_name and (name == target_name or term == target_name or tid.lower() == target_name):
        return True
    return False


def main():
    parser = argparse.ArgumentParser(
        description="Read prompt area state and text from active CLI sessions"
    )
    parser.add_argument(
        "tracking_ids", nargs="*",
        help="Specific tracking IDs or terminal session names to query",
    )
    parser.add_argument(
        "--all-active", action="store_true",
        help="Query all active sessions",
    )
    parser.add_argument(
        "--uri", type=str,
        help="Query by URI (uai://session/<id> or prompt://<platform>/<name>)",
    )
    parser.add_argument(
        "--format", "-f", choices=["json", "flat"], default="json",
        help="Output format: json (pretty, default) or flat (one JSON object per line)",
    )
    parser.add_argument(
        "--include-empty", action="store_true",
        help="Include sessions with empty/clear prompt areas (default: only occupied)",
    )
    args = parser.parse_args()

    if not args.all_active and not args.tracking_ids and not args.uri:
        parser.error("Specify --all-active, tracking IDs, or --uri")

    ai_root = get_ai_root()
    store_sessions = list_active_sessions(ai_root)
    tmux_sessions = list_tmux_sessions(ai_root)

    # Filter to requested sessions
    targets = []
    if args.all_active:
        targets = store_sessions
    elif args.uri:
        parsed = parse_uri(args.uri)
        if parsed:
            for s in store_sessions:
                if match_session(s, parsed):
                    targets.append(s)
                    break
    else:
        id_set = set(args.tracking_ids)
        for s in store_sessions:
            tid = s.get("tracking_id", "")
            term = s.get("terminal_session", "")
            name = s.get("display_name", "")
            if tid in id_set or term in id_set or name in id_set:
                targets.append(s)

    results = []
    for session in targets:
        tracking_id = session.get("tracking_id", "")
        terminal_session = session.get("terminal_session") or tracking_id
        platform = session.get("platform", "")

        # Verify the tmux session actually exists
        if terminal_session not in tmux_sessions:
            if tracking_id in tmux_sessions:
                terminal_session = tracking_id
            else:
                continue

        status = get_session_status(terminal_session, platform, ai_root)
        state = status.get("state", "unknown")

        # Occupancy is determined DIRECTLY from the terminal (bottom ❯ line holding
        # real, non-dim text), NOT from get-status's state. get-status misreports a
        # prompt that holds real typed text as 'idle' (observed: "❯ test 2" → idle),
        # which would hide a legitimate indicator. The presence of real (non-ghost)
        # prompt text IS the authoritative occupancy signal for this feature. We still
        # only look when the agent is at the prompt (idle / prompt_occupied), not mid-
        # response, so streamed output isn't mistaken for input.
        prompt_text = ""
        if state in ("idle", "prompt_occupied"):
            prompt_text = extract_prompt_text(terminal_session, platform, ai_root)

        if prompt_text:
            prompt_state = "prompt_area_occupied"
        elif state in ("idle", "prompt_occupied"):
            prompt_state = "prompt_area_clear"
        else:
            # responding, blocked, permission_prompt, exited, unknown → not at prompt
            prompt_state = state

        entry = {
            "tracking_id": tracking_id,
            "session_name": session.get("display_name") or "",
            "platform": platform,
            "terminal_session": terminal_session,
            "prompt_state": prompt_state,
            "prompt_text": prompt_text,
            "context_percent": status.get("context_percent"),
            "model": status.get("model"),
        }
        results.append(entry)

    # Filter: by default only return occupied prompt areas
    if not args.include_empty:
        results = [r for r in results if r["prompt_text"]]

    # Output
    if args.format == "flat":
        for entry in results:
            print(json.dumps(entry, ensure_ascii=False))
    else:
        json.dump(results, sys.stdout, indent=2, ensure_ascii=False)
        print()


if __name__ == "__main__":
    main()
