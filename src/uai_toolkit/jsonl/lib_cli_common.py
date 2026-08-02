#!/usr/bin/env python3
"""lib_cli_common — the ONE definition of the jsonl tools' COMMON CLI parameters.

Same "single source of truth" idea as lib_jsonl_archive.is_turn_start (turn
counting) and classify_record (record kind), applied to the CLI surface: the
interval/branch-aware tools — context_stats, read_jsonl, and the future
turn_digest — must expose the SAME flag names with the SAME semantics and the SAME
SPEC grammars. This module owns those flags and the grammar so they can never
drift per-tool.

COMMON FLAG SET (identical names + semantics across tools):
  --session <id|self|path>   which transcript. A tracking-id / display-name, an
                             explicit .jsonl path, or the literal 'self' (current
                             CLI session via $AI_CLI_SESSION_ID / $AI_TRACKING_ID).
  --interval SPEC            compaction interval(s). Default = current/live (the
                             LAST interval). Grammar (lib_jsonl_archive.select_intervals):
                             N | last|live | -1 | "1,3" | "2-4"  (0=prologue, 1..N).
  --branch SPEC             branch WITHIN the interval. Default = live (br0).
                             Grammar (lib_jsonl_archive.select_branches):
                             brN | live | -1 | "0,1" | "0-2".  v1 enumerates only br0.
  --turns SPEC              absolute turn-number range (the Tn shown in output).
                             Grammar: N | N-M | N- | -N | "1,3" | last|live.
  --units {tokens,bytes}    which figure fills size columns (tokens = bytes/4
                             estimate; bytes = exact wire bytes).

argparse-based tools (context_stats, turn_digest) call add_common_args(parser).
read_jsonl uses a hand-rolled dispatcher, so it consumes the SPEC grammars
directly (select_intervals / select_branches / select_turn_numbers) and the
resolve_session() resolver — same functions, same grammar, no argparse.
"""
from __future__ import annotations

import datetime as _dt
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

# Re-export the canonical interval + branch model so a tool imports ONE place.
from uai_toolkit.jsonl.lib_jsonl_archive import (  # noqa: E402,F401
    BRANCH_LIVE,
    compaction_intervals,
    find_compactions,
    interval_branches,
    interval_line_ranges,
    interval_live_chain,
    line_in_intervals,
    records_with_lines,
    select_branches,
    select_intervals,
)

# ── flag registry (canonical names / defaults / help) ─────────────────────
DEFAULT_INTERVAL = None      # None => current/live (the LAST interval)
DEFAULT_BRANCH = "live"      # br0
DEFAULT_UNITS = "tokens"

_HELP = {
    "session": (
        "which transcript: a tracking-id, a display name (e.g. 'Anvil'), an explicit "
        "path to a .jsonl, or the literal 'self' for the current CLI session "
        "(resolved via $AI_CLI_SESSION_ID / $AI_TRACKING_ID). (default: self)"
    ),
    "interval": (
        "compaction interval(s) to scope to. SPEC: N | last | live | -1 | '1,3' | '2-4' "
        "(0=prologue, 1..N, last/live=current; NEGATIVE = offset FROM live: -1=one before live, "
        "-2=two before). (default: current/live interval)"
    ),
    "branch": (
        "branch WITHIN the selected interval. SPEC: brN | live | -1 | '0,1' | '0-2' "
        "(br0 = the live tip->root chain a --resume reloads; br1+ = rewind/dead-retry "
        "forks). v1 enumerates only br0. (default: live / br0)"
    ),
    "turns": (
        "absolute turn-number range (the Tn shown in output). SPEC: N | N-M | N- | -N | "
        "'1,3' | last | live | all. (default: all turns in scope)"
    ),
    "units": (
        "which figure fills size columns. 'tokens' (default) shows the bytes/4 ESTIMATE; "
        "'bytes' shows EXACT wire byte counts. (default: tokens)"
    ),
}


def add_common_args(parser, *, session=True, interval=True, branch=True,
                    turns=True, units=True, session_positional=False, turns_help=None):
    """Register the common flags on an argparse parser (argparse-based tools).

    session_positional=True ALSO accepts the transcript as a bare positional
    (back-compat with context_stats' existing `TRANSCRIPT` arg); --session is the
    canonical name and wins if both are given.

    turns_help overrides the shared --turns help text for a tool whose DEFAULT differs
    from the common "all turns in scope" (e.g. turn_digest defaults to the last turn) —
    keeps the flag's grammar shared while letting the help stay truthful (Codex F4).
    """
    if session:
        if session_positional:
            parser.add_argument("transcript", nargs="?", metavar="TRANSCRIPT",
                                help=_HELP["session"])
        parser.add_argument("--session", metavar="ID|self|PATH", default=None,
                            help=_HELP["session"])
    if interval:
        parser.add_argument("--interval", metavar="SPEC", default=DEFAULT_INTERVAL,
                            help=_HELP["interval"])
    if branch:
        parser.add_argument("--branch", metavar="SPEC", default=DEFAULT_BRANCH,
                            help=_HELP["branch"])
    if turns:
        parser.add_argument("--turns", metavar="SPEC", default=None,
                            help=turns_help or _HELP["turns"])
    if units:
        parser.add_argument("--units", choices=("tokens", "bytes"), default=DEFAULT_UNITS,
                            metavar="{tokens,bytes}", help=_HELP["units"])
    return parser


# ── session resolution (--session <id|self|path>) ─────────────────────────
def execution_stamp() -> str:
    """Local-time 'generated at' stamp for tool output, so a pasted/saved snapshot is
    SELF-DATING (you can tell when it was produced). Local time per the workspace rule
    (timestamps are local, not UTC)."""
    now = _dt.datetime.now().astimezone()
    return f"generated {now.strftime('%Y-%m-%d %H:%M:%S %Z')}"


def resolve_session(value: str | None) -> Path | None:
    """Resolve a --session value (id | self | path) to a transcript Path.

    Order: explicit existing path; 'self'/None -> $AI_CLI_SESSION_ID then
    $AI_TRACKING_ID; else a (partial) id/name lookup via read_jsonl.find_jsonl."""
    finder = None
    try:
        from uai_toolkit.jsonl import read_jsonl
        finder = read_jsonl.find_jsonl
    except Exception:
        finder = None

    if value and value not in ("self",):
        p = Path(value).expanduser()
        if p.exists():
            return p
        return finder(value) if finder else None

    # 'self' or nothing: current session.
    sid = os.environ.get("AI_CLI_SESSION_ID", "")
    if sid and sid != "pending" and finder:
        got = finder(sid)
        if got:
            return got
    tid = os.environ.get("AI_TRACKING_ID", "")
    if tid and finder:
        return finder(tid)
    return None


# ── turns SPEC grammar (shared) ───────────────────────────────────────────
def select_turn_numbers(spec: str, turns_in_scope: list[int]):
    """Resolve a --turns SPEC against the turn numbers available in scope.

    turns_in_scope is the ordered, de-duplicated list of turn numbers visible in
    the current selection (>= 0). Grammar: N | N-M | N- | -N (last N) | comma
    lists | last|live | all | optional leading 't'. Returns (set_of_turns, None) or
    (None, error_message). This is the ONE turns grammar; read_jsonl's
    _select_turn_numbers delegates here so the Tn semantics match everywhere."""
    turns = list(turns_in_scope)
    if not turns:
        return set(), None
    max_turn = max(turns)
    available = set(turns)
    chosen: set[int] = set()
    for raw in str(spec).split(","):
        token = raw.strip().lower()
        if not token:
            continue
        if token.startswith("t"):
            token = token[1:]
        if token == "all":
            chosen.update(turns)          # every numbered turn in scope (backfill)
            continue
        if token in ("last", "live"):
            chosen.add(turns[-1])
            continue
        try:
            if token.startswith("-"):
                n = int(token[1:])
                if n < 0:
                    raise ValueError
                chosen.update(turns[-n:] if n else [])
            elif token.endswith("-"):
                start = int(token[:-1])
                chosen.update(t for t in turns if t >= start)
            elif "-" in token:
                lo_s, hi_s = token.split("-", 1)
                lo, hi = int(lo_s), int(hi_s)
                if hi < lo:
                    raise ValueError
                chosen.update(t for t in turns if lo <= t <= hi)
            else:
                chosen.add(int(token))
        except ValueError:
            return None, f"Invalid turn range token: {raw}"
    missing = sorted(t for t in chosen if t not in available)
    if missing:
        return None, (
            f"Requested turn(s) {missing} not available in the selected scope "
            f"(available T{turns[0]}..T{max_turn})."
        )
    return chosen, None


# ── one-call interval+branch resolution (argparse-based tools) ────────────
def selected_interval_indices(path, interval_spec):
    """The ``.index`` of every interval an ``interval_spec`` selects.

    None/''/'live'/'last' -> the live interval only. This lets CHAIN-SCOPED tools
    (context_stats, turn_digest) ITERATE one-interval-at-a-time instead of silently
    analyzing only the first of a multi-interval selection (Codex review, finding 2).
    Returns (indices, error)."""
    intervals = compaction_intervals(Path(path))
    if not intervals:
        return None, "No compaction intervals found in transcript."
    if interval_spec in (None, "", "live", "last"):
        return [intervals[-1]["index"]], None
    selected, err = select_intervals(interval_spec, intervals)
    if err:
        return None, err
    return [iv["index"] for iv in selected], None


def resolve_interval_branch(path, interval_spec, branch_spec):
    """Resolve (interval_spec, branch_spec) against a transcript.

    Returns (result, error). On success result is a dict:
      {"intervals": [selected interval dicts],
       "recs_lines": [(record, line), ...],
       "chain_uuids": [root..tip uuids of the selected interval's chosen branch],
       "line_ranges": [(lo, hi), ...]}
    interval_spec None/'' => the LAST interval (current/live). Multi-interval
    selections are allowed for line-range consumers (read_jsonl); the chain_uuids
    are computed for the FIRST selected interval's chosen branch (the reclaim tools
    scope to a single interval). branch_spec None/'' => live (br0)."""
    path = Path(path)
    intervals = compaction_intervals(path)
    if interval_spec in (None, "", "live", "last"):
        selected = [intervals[-1]]
    else:
        selected, err = select_intervals(interval_spec, intervals)
        if err:
            return None, err
    recs_lines = records_with_lines(path)
    primary = selected[0]
    branches = interval_branches(recs_lines, primary)
    chosen_branches, berr = select_branches(branch_spec, branches)
    if berr:
        return None, berr
    chain_uuids: list[str] = []
    for b in chosen_branches:
        chain_uuids.extend(b["uuids"])
    return {
        "intervals": selected,
        "recs_lines": recs_lines,
        "chain_uuids": chain_uuids,
        "line_ranges": interval_line_ranges(selected),
    }, None
