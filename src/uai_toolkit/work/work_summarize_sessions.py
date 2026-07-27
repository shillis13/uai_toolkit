#!/usr/bin/env python3
"""Summarize AI session activity using a per-feature configured model.

Reads recent turns from JSONL transcripts or terminal scrollback for running
sessions, sends them to the ``session_summarize`` endpoint, and appends the
result to {session_dir}/{tracking_id}_lllmSummary.log.

Usage:
    work_summarize_sessions.py                           # all running, last 3 JSONL turns
    work_summarize_sessions.py --sessions id1,id2        # specific sessions
    work_summarize_sessions.py --jsonl 5                 # last 5 JSONL turns
    work_summarize_sessions.py --terminal 200            # last 200 terminal lines instead
"""
from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path
from textwrap import dedent

from uai_toolkit.session_mgmt.session_ops import list_sessions, read_terminal
from uai_toolkit.session_mgmt.session_store import SessionStore
from uai_toolkit.jsonl.read_jsonl import find_jsonl, parse_session


SUMMARY_PROMPT = dedent("""\
    You are summarizing the recent activity of an AI CLI session.

    Given the recent conversation turns below, produce a concise summary that includes:

    1. **Current date/time:** {now}
    2. **Session identity:** {tracking_id} ({display_name})
    3. **What the AI is working on:** The current task or topic in 1-2 sentences.
    4. **Status:** One of: idle, busy, waiting-blocked, waiting-not-blocked, error, unknown.
       - idle: no active work, waiting for user input
       - busy: actively working on a task
       - waiting-blocked: waiting for something external (download, other session, user decision)
       - waiting-not-blocked: paused but could continue (e.g., asked user a question)
       - error: in an error state or stuck
       - unknown: can't determine from the data
    5. **Last meaningful action:** What was the most recent thing done or said.
    6. **Context for coordinator:** Anything a coordination session should know.

    Keep the summary under 200 words. Be factual, not speculative.
""")


def _gather_jsonl(tracking_id: str, cli_uuid: str, n_turns: int) -> str:
    """Grab the last n_turns from the session's JSONL transcript."""
    # Try cli_uuid first (most direct), then tracking_id
    jsonl_path = find_jsonl(cli_uuid) if cli_uuid else None
    if not jsonl_path:
        jsonl_path = find_jsonl(tracking_id)
    if not jsonl_path:
        return ""

    messages = parse_session(jsonl_path)
    if not messages:
        return ""

    # Take last n_turns (user+assistant pairs count as turns)
    recent = messages[-n_turns * 2:] if len(messages) > n_turns * 2 else messages

    lines = []
    for msg in recent:
        content = msg.content[:2000] if msg.content else ""
        if content:
            lines.append(f"[{msg.role}] {content}")

    return "\n\n".join(lines)


def _gather_terminal(session_name: str, n_lines: int) -> str:
    """Grab the last n_lines from the session's terminal scrollback."""
    try:
        text = read_terminal(session_name)
    except Exception:
        return ""

    if not text:
        return ""

    lines = text.strip().splitlines()
    return "\n".join(lines[-n_lines:])


def summarize_session(
    tracking_id: str,
    session_info: dict,
    mode: str = "jsonl",
    count: int = 3,
) -> str | None:
    """Summarize a single session. Returns the summary text or None on failure.

    uai_toolkit: the model comes from the `session_summarize` feature's own entry in
    the LLM endpoint config (local LLLM, a hosted API, or nothing). Unconfigured is
    the normal default and returns None — the caller treats that as "no summary",
    exactly as it treats the model being down.

    The shared client is optional (install ``uai-toolkit[full]`` for httpx), but the
    call is in-process and has no interpreter/shebang mismatch.
    """
    from uai_toolkit.llm import complete, is_configured

    if not is_configured("session_summarize"):
        return None

    cli_uuid = session_info.get("cli_session_id", "")
    display_name = session_info.get("display_name") or session_info.get("name") or tracking_id
    session_dir = session_info.get("session_dir", "")

    # Gather context
    if mode == "terminal":
        context = _gather_terminal(tracking_id, count)
        source_desc = f"last {count} terminal lines"
    else:
        context = _gather_jsonl(tracking_id, cli_uuid, count)
        source_desc = f"last {count} JSONL turns"

    if not context:
        return None

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    prompt = SUMMARY_PROMPT.format(
        now=now,
        tracking_id=tracking_id,
        display_name=display_name,
    )

    input_text = f"Source: {source_desc}\n\n{context}"

    try:
        summary = complete("session_summarize", prompt, input_text, max_tokens=800)
    except Exception as e:
        return f"[ERROR summarizing {tracking_id}: {e}]"
    if not summary:
        return None            # endpoint chain returned nothing — same as model down

    # Append to log
    if session_dir:
        log_path = Path(session_dir) / f"{tracking_id}_lllmSummary.log"
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "a") as f:
            f.write(f"\n{'='*60}\n")
            f.write(f"{now} | {source_desc}\n")
            f.write(f"{'='*60}\n")
            f.write(summary.strip())
            f.write("\n")

    return summary


SUMMARIZE_EPILOG = """\
WHAT IT DOES
  Standalone per-session summarizer. For each selected session it reads recent
  activity and asks the model configured for ``session_summarize`` for a free-text,
  human-readable summary of what that session has
  been doing, then APPENDS it to:
    {session_dir}/{tracking_id}_lllmSummary.log
  (and prints it too, unless -q).

  This is NOT part of the work-landscape join. It emits a narrative, not a
  structured verdict, and nothing reads its output back. Reach for
  work_assess_sessions.py when you want the structured landscape signal
  (state / needs_pianoman); reach for THIS when you want a readable story of
  what a session has been up to.

INPUT MODE  (--jsonl and --terminal are mutually exclusive)
  --jsonl N     read the last N turns from the session's JSONL transcript
                (this is the default mode, N=3)
  --terminal N  read the last N lines of LIVE terminal scrollback
                (running sessions only)

SESSION SELECTION
  --sessions a,b,c   by tracking ID, CLI UUID, or terminal name
  (omitted)          all currently RUNNING sessions

EXAMPLES
  work_summarize_sessions.py                    # all running, last 3 JSONL turns each
  work_summarize_sessions.py -s Mullion,Anvil   # just these two sessions
  work_summarize_sessions.py --jsonl 8          # deeper context: 8 turns each
  work_summarize_sessions.py --terminal 200 -q  # from scrollback, log-only (no stdout)

SEE ALSO
  work_assess_sessions.py    structured landscape assessment (state / needs_pianoman)
  work_landscape.py          the cross-session structural table
  scripts/work/DESIGN.md     the full design & rationale
"""


def main():
    parser = argparse.ArgumentParser(
        description="Summarize a session's recent activity into a free-text narrative via the "
                    "configured session_summarize model, appended to {session_dir}/{id}_lllmSummary.log. Standalone -- "
                    "does NOT feed the work-landscape join.",
        epilog=SUMMARIZE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--sessions", "-s",
                        help="Comma-separated session IDs (tracking ID, CLI UUID, or terminal name). "
                             "Default: all running sessions.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--jsonl", "-j", type=int, default=None,
                       help="Read the last N turns from the JSONL transcript (default mode, N=3)")
    group.add_argument("--terminal", "-t", type=int, default=None,
                       help="Read the last N lines of live terminal scrollback (running sessions only)")
    parser.add_argument("--quiet", "-q", action="store_true",
                        help="Only append to the log file(s); don't print the summary to stdout")

    args = parser.parse_args()

    # Determine mode and count
    if args.terminal is not None:
        mode = "terminal"
        count = args.terminal
    else:
        mode = "jsonl"
        count = args.jsonl if args.jsonl is not None else 3

    store = SessionStore()

    # Resolve sessions
    if args.sessions:
        identifiers = [s.strip() for s in args.sessions.split(",")]
    else:
        # All running sessions
        running = list_sessions()
        identifiers = [s["name"] for s in running if s.get("running")]

    if not identifiers:
        print("No sessions found.")
        return

    for ident in identifiers:
        info = store.resolve(ident)
        if not info:
            # Fallback: use identifier as tracking_id with minimal info
            info = {"tracking_id": ident, "name": ident, "session_dir": ""}
            if not args.quiet:
                print(f"[WARN] Could not resolve session: {ident}")

        tracking_id = info.get("tracking_id", ident)
        if not args.quiet:
            display = info.get("display_name") or info.get("name") or tracking_id
            print(f"\n--- {display} ({tracking_id}) ---")

        summary = summarize_session(tracking_id, info, mode=mode, count=count)

        if summary:
            if not args.quiet:
                print(summary.strip())
            session_dir = info.get("session_dir", "")
            if session_dir:
                log_path = Path(session_dir) / f"{tracking_id}_lllmSummary.log"
                if not args.quiet:
                    print(f"  [logged to {log_path}]")
        else:
            if not args.quiet:
                print(f"  [no data available for {mode}]")


if __name__ == "__main__":
    main()
