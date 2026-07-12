"""MCP tools wrapping the context-management scripts — the JSONL paging /
engram / self-bounce toolchain. Lets agents inspect and manage their own (or a
named session's) context window the sanctioned way instead of hand-rolling
transcript surgery.

Pattern: thin subprocess wrappers around the CLIs (the scripts are the single
source of truth — NO business logic lives here). Tool names use the `context_`
prefix. Mirrors tools/sched_tasks.py exactly.

Wrapped scripts:
  - ai_general/scripts/jsonl/read_jsonl.py            (stats)
  - ai_general/scripts/jsonl/offload_tool_results.py  (offload / rehydrate)
  - ai_general/scripts/jsonl/memory_manager.py        (recall / rehydrate / slim)
  - ai_general/scripts/session_bounce/reclaim_and_stage.py (consolidate plan/enact)
  - ai_general/scripts/session_bounce/self_restart.py (bounce / realize)

SESSION RESOLUTION: `_resolve_transcript()` reuses scrub_files.find_jsonl — the
SAME resolver offload_tool_results.py uses — which accepts a direct .jsonl path,
a tracking id, a uai:// URI, a display name, a CLI UUID (or prefix), or a
terminal session name, and returns the transcript path.

NOTE on "self": the MCP server's environment is the SERVER's, not the calling
agent's, so a bare "self"/$AI_TRACKING_ID would resolve to the wrong session.
Callers MUST pass an explicit session tracking_id — we do NOT silently default
to the server's own session.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI/ai_root"))
JSONL = AI_ROOT / "ai_general/scripts/jsonl"
BOUNCE = AI_ROOT / "ai_general/scripts/session_bounce"
SESSION_MGMT = AI_ROOT / "ai_general/scripts/session_mgmt"

READ_JSONL = JSONL / "read_jsonl.py"
OFFLOAD = JSONL / "offload_tool_results.py"          # legacy stub offloader (rehydrate path only)
CHAIN_SKIP = JSONL / "chain_skip.py"                  # NEW lossless offloader (parentUuid-skip)
CHECK_RESUME = JSONL / "check_resume_integrity.py"    # pre-bounce resume-integrity gate
MEMORY_MGR = JSONL / "memory_manager.py"
CHECK_RI = JSONL / "check_resume_integrity.py"
RECLAIM = BOUNCE / "reclaim_and_stage.py"
SELF_RESTART = BOUNCE / "self_restart.py"

PREFIX = "context_"


def _resolve_transcript(session):
    """Resolve a session identifier to its transcript .jsonl path.

    Reuses scrub_files.find_jsonl (the resolver offload_tool_results.py uses):
    accepts a direct path, tracking id, uai:// URI, display name, CLI UUID /
    prefix, or terminal session name. Returns a str path or None.
    """
    if not session:
        return None
    p = Path(session).expanduser()
    if p.exists() and p.is_file():
        return str(p)
    for d in (str(JSONL), str(SESSION_MGMT)):
        if d not in sys.path:
            sys.path.insert(0, d)
    try:
        from uai_toolkit.jsonl import scrub_files  # noqa: E402 — the offload script's own resolver
        found = scrub_files.find_jsonl(session)
        if found:
            return str(found)
    except Exception:
        pass
    return None


def _run(script, args=None, timeout=180, env=None):
    """Run `python3 <script> [args]` non-interactively. Returns a result dict.

    stdin is closed so the CLI never blocks on a prompt. Passing env overrides
    the child environment (used by context_bounce to inject AI_TRACKING_ID);
    env=None inherits the server's environment.
    """
    cmd = [sys.executable, str(script)] + (args or [])
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                           stdin=subprocess.DEVNULL, env=env)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"timeout running {Path(script).name}"}
    except Exception as e:
        return {"success": False, "error": str(e)}
    out = (p.stdout or "").strip()
    if p.returncode != 0:
        return {"success": False, "error": (p.stderr or out or
                f"exit {p.returncode}").strip()}
    try:
        return {"success": True, "data": json.loads(out)}
    except (json.JSONDecodeError, ValueError):
        return {"success": True, "output": out}


def _need_path(session):
    """Resolve session→path or return an error result dict (None on success)."""
    path = _resolve_transcript(session)
    if not path:
        return None, {"success": False,
                      "error": f"could not resolve session to a transcript: {session!r}. "
                               "Pass a .jsonl path, tracking id, uai:// URI, display name, "
                               "or CLI UUID."}
    return path, None


_SESSION = ("Session to act on. Accepts a direct .jsonl transcript path, a tracking id "
            "(YYYYMMDD_HHMMSS_uuid8_plat), a uai:// URI, a display name, or a CLI session "
            "UUID (prefix OK). REQUIRED — the server will NOT default to its own session "
            "(the MCP server env is not the calling agent's).")


def tools():
    return [
        Tool(name=f"{PREFIX}stats",
             description="Read-only context ledger for a session's transcript: message/turn "
                         "counts by type, tool usage, char/word/token totals, and the "
                         "full/stub (offloaded) split. Use this to see how big a context is and "
                         "where the weight lives before offloading or consolidating.",
             inputSchema={"type": "object", "properties": {
                 "session": {"type": "string", "description": _SESSION},
                 "interval": {"type": "string", "default": "live",
                              "description": "Compaction interval to scope stats to: 'live' (default, "
                                             "current live context since last compaction), 'last', a number "
                                             "(0=prologue, 1..N), or a range like '2-4'."}},
                 "required": ["session"]}),
        Tool(name=f"{PREFIX}offload",
             description="Lossless context reclaim by parentUuid-skip (chain_skip): drop ALL old "
                         "tool_use / tool_result / attachment records past the recency window off the "
                         "ACTIVE CHAIN by re-pointing parent pointers — no stubs, no archive, no size "
                         "threshold. Records stay in-file off-chain; realized on the next resume (set "
                         "bounce=true to offload + resume-integrity preflight + self_restart in ONE "
                         "action). Reversible (restore <T>.bak). SAFE DEFAULT: dry_run=true previews "
                         "the reclaim and mutates nothing.",
             inputSchema={"type": "object", "properties": {
                 "session": {"type": "string", "description": _SESSION},
                 "dry_run": {"type": "boolean", "default": True,
                             "description": "If true (DEFAULT), report what would be paged out without writing. "
                                            "Set false to actually offload."},
                 "keep_recent": {"type": "integer", "default": 3,
                                 "description": "Human turns at the tail protected from reclaim (never offloaded). "
                                                "Default 3. No size threshold — skip is free — so ALL old "
                                                "tool_use/tool_result/attachment records past this window are offloaded."},
                 "bounce": {"type": "boolean", "default": False,
                            "description": "If true, after a successful (non-dry-run) offload, immediately "
                                           "self-bounce the session to REALIZE the reduction (schedule a launchd "
                                           "--resume + /exit). One deliberate action = offload + realize, so the "
                                           "decision to offload doesn't need a separate context_bounce step. "
                                           "Requires session to be a tracking_id (like context_bounce). Ignored when dry_run."},
                 "bounce_in_min": {"type": "integer", "default": 2,
                                   "description": "Minutes until the scheduled self-resume when bounce=true (default 2)."}},
                 "required": ["session"]}),
        Tool(name=f"{PREFIX}recall",
             description="Recall (read-only): render the full original text of an archived engram "
                         "(a Summarized / paged-out turn-range) by its engram id, without "
                         "restoring it to the transcript. Use to 'remember' offloaded content "
                         "on demand.",
             inputSchema={"type": "object", "properties": {
                 "session": {"type": "string", "description": _SESSION},
                 "engram_id": {"type": "string",
                               "description": "Durable engram_id of the archived layer to render "
                                              "(from a stub's ENGRAM_META, or context_summarize_enact output)."},
                 "leaf": {"type": "string",
                          "description": "Optional active-chain leaf UUID to disambiguate forks. Omit unless "
                                         "the transcript has diverged branches."}},
                 "required": ["session", "engram_id"]}),
        Tool(name=f"{PREFIX}rehydrate",
             description="Restore (UNDO): restore previously offloaded/Summarized content back into "
                         "the live transcript on disk. If engram_id is given, undoes that one "
                         "Summarization (memory_manager restore); otherwise restores ALL "
                         "archived tool-result/attachment stubs (offload --rehydrate). Mutating.",
             inputSchema={"type": "object", "properties": {
                 "session": {"type": "string", "description": _SESSION},
                 "engram_id": {"type": "string",
                               "description": "Optional. If given, Restore just this Summarized engram. "
                                              "Omit to restore all offloaded tool-result/attachment stubs."}},
                 "required": ["session"]}),
        Tool(name=f"{PREFIX}slim",
             description="Shrink fat engram stubs: rewrite existing ENGRAM_META inline bodies[] "
                         "from fat to slim form (manifest untouched, recall stays byte-exact). "
                         "Reclaims live-context bytes held by verbose stubs. SAFE DEFAULT: "
                         "dry_run=true previews what would be slimmed.",
             inputSchema={"type": "object", "properties": {
                 "session": {"type": "string", "description": _SESSION},
                 "dry_run": {"type": "boolean", "default": True,
                             "description": "If true (DEFAULT), report what would be slimmed without writing. "
                                            "Set false to actually slim."}},
                 "required": ["session"]}),
        # ── Summarization plan/enact ──────────────────────────────────────
        # `context_summarize_*` are the canonical (primary) tool names. The old
        # `context_consolidate_*` names are retained below as deprecated aliases
        # routing to the SAME handler, so in-flight callers keep working.
        Tool(name=f"{PREFIX}summarize_plan",
             description="Summarization plan (read-only): recommend which turn-range(s) to Summarize "
                         "to free the requested token budget, given current usage. Returns the plan "
                         "(first_uuids to summarize) — no mutation. Feed the plan's ranges into "
                         "context_summarize_enact.",
             inputSchema={"type": "object", "properties": {
                 "session": {"type": "string", "description": _SESSION},
                 "used_pct": {"type": "number",
                              "description": "Current context usage as a percentage 0-100 (NOT 0-1)."},
                 "need_tokens": {"type": "integer",
                                 "description": "Target number of tokens to free by Summarizing."},
                 "leaf": {"type": "string",
                          "description": "Optional active-chain leaf UUID; REQUIRED on a forked transcript so "
                                         "Summarization follows the right branch."},
                 "keep_recent": {"type": "integer",
                                 "description": "Optional: number of recent turns to protect from Summarization."}},
                 "required": ["session", "used_pct", "need_tokens"]}),
        Tool(name=f"{PREFIX}summarize_enact",
             description="MUTATING: Summarize turn-range(s) into engram stubs using caller-supplied "
                         "summaries. summaries_file is a JSON file mapping {first_uuid: summary_text} "
                         "(produced from context_summarize_plan's ranges, one summary per range). "
                         "Reversible via context_rehydrate --engram-id (Restore). Skips the local-LLM shadow log.",
             inputSchema={"type": "object", "properties": {
                 "session": {"type": "string", "description": _SESSION},
                 "summaries_file": {"type": "string",
                                    "description": "Path to a JSON file {first_uuid: summary} — one summary per "
                                                   "range from context_summarize_plan (the Claude-quality path)."},
                 "leaf": {"type": "string",
                          "description": "Optional active-chain leaf UUID; REQUIRED on a forked transcript."},
                 "keep_recent": {"type": "integer",
                                 "description": "Optional: number of recent turns to protect from Summarization."}},
                 "required": ["session", "summaries_file"]}),
        # Deprecated aliases (kept working) — prefer context_summarize_plan/_enact.
        Tool(name=f"{PREFIX}consolidate_plan",
             description="DEPRECATED alias of context_summarize_plan (kept for back-compat). "
                         "Read-only: recommend which turn-range(s) to Summarize to free the requested "
                         "token budget. Prefer context_summarize_plan.",
             inputSchema={"type": "object", "properties": {
                 "session": {"type": "string", "description": _SESSION},
                 "used_pct": {"type": "number",
                              "description": "Current context usage as a percentage 0-100 (NOT 0-1)."},
                 "need_tokens": {"type": "integer",
                                 "description": "Target number of tokens to free by Summarizing."},
                 "leaf": {"type": "string",
                          "description": "Optional active-chain leaf UUID; REQUIRED on a forked transcript so "
                                         "Summarization follows the right branch."},
                 "keep_recent": {"type": "integer",
                                 "description": "Optional: number of recent turns to protect from Summarization."}},
                 "required": ["session", "used_pct", "need_tokens"]}),
        Tool(name=f"{PREFIX}consolidate_enact",
             description="DEPRECATED alias of context_summarize_enact (kept for back-compat). "
                         "MUTATING: Summarize turn-range(s) into engram stubs using caller-supplied "
                         "summaries. Prefer context_summarize_enact.",
             inputSchema={"type": "object", "properties": {
                 "session": {"type": "string", "description": _SESSION},
                 "summaries_file": {"type": "string",
                                    "description": "Path to a JSON file {first_uuid: summary} — one summary per "
                                                   "range from context_summarize_plan (the Claude-quality path)."},
                 "leaf": {"type": "string",
                          "description": "Optional active-chain leaf UUID; REQUIRED on a forked transcript."},
                 "keep_recent": {"type": "integer",
                                 "description": "Optional: number of recent turns to protect from Summarization."}},
                 "required": ["session", "summaries_file"]}),
        Tool(name=f"{PREFIX}check_resume",
             description="Read-only PREFLIGHT: would this transcript survive `claude --resume`? "
                         "Scans for the crash class where an offload stub flattened a list-typed "
                         "attachment field (deferred_tools_delta.addedNames, hook_additional_context."
                         "content, ...) into a bare string — CC runs .map()/.join() over those on "
                         "resume, so a flatten is fatal. Uses a verified field taxonomy PLUS "
                         "self-calibration (a field seen as a list elsewhere but a bare stub here is "
                         "a flatten), and — when a co-located <name>.jsonl.bak snapshot exists — the "
                         "exact offload pre-write guard diffed against it. Returns {ok, "
                         "standalone_violations, snapshot_diff}. Run before trusting a context_bounce.",
             inputSchema={"type": "object", "properties": {
                 "session": {"type": "string", "description": _SESSION}},
                 "required": ["session"]}),
        Tool(name=f"{PREFIX}bounce",
             description="Realize a lighter context: schedule a launchd self-resume in N minutes then "
                         "/exit, so the session restarts and reloads its (now offloaded/consolidated) "
                         "transcript fresh. This is the 'realize' step after offload/consolidate. "
                         "SAFE DEFAULT: dry_run=true prints the plan WITHOUT scheduling or exiting. "
                         "self_restart reads AI_TRACKING_ID from its environment; this tool injects the "
                         "session you pass as AI_TRACKING_ID for the child process.",
             inputSchema={"type": "object", "properties": {
                 "session": {"type": "string",
                             "description": "Tracking id of the session to bounce (injected as AI_TRACKING_ID for "
                                            "self_restart.py). REQUIRED — must be a tracking id "
                                            "(YYYYMMDD_HHMMSS_uuid8_plat), not a path."},
                 "in_min": {"type": "integer", "default": 2,
                            "description": "Minutes until the scheduled self-resume (default 2)."},
                 "dry_run": {"type": "boolean", "default": True,
                             "description": "If true (DEFAULT), print the plan and do NOT schedule or exit. "
                                            "Set false to actually schedule the bounce."}},
                 "required": ["session"]}),
    ]


async def call_tool(name, arguments):
    short = name[len(PREFIX):] if name.startswith(PREFIX) else name
    a = arguments or {}

    if short == "stats":
        path, err = _need_path(a.get("session"))
        if err:
            res = err
        else:
            res = _run(READ_JSONL, ["stats", path, "--interval", a.get("interval", "live")])

    elif short == "offload":
        path, err = _need_path(a.get("session"))
        if err:
            res = err
        else:
            # NEW lossless offloader: parentUuid-skip (chain_skip), not the old stub/archive path.
            # No size threshold; drops all old tool_use/tool_result/attachment records past the
            # recency window (keep_recent human turns), reversibly, and backs up to <T>.bak.
            keep = a.get("keep_recent", a.get("keep_last_turns", 3))
            args = ["offload", path, "--keep-recent", str(keep)]
            if a.get("dry_run", True):
                args.append("--dry-run")
            res = _run(CHAIN_SKIP, args)
            # One deliberate action = offload + realize. After a successful non-dry offload, run
            # the resume-integrity PREFLIGHT as a gate, then self-bounce (self_restart with the
            # caller's AI_TRACKING_ID injected — the server env is not the caller's).
            if a.get("bounce") and not a.get("dry_run", True) and res.get("success"):
                pre = _run(CHECK_RESUME, [path])
                pre_ok = pre.get("success") and "no resume-integrity violations" in (pre.get("output") or "").lower()
                if not pre_ok:
                    res = {"success": False,
                           "error": "resume-integrity preflight FAILED — did NOT bounce (offload written; restore <T>.bak if needed)",
                           "offloaded": res.get("output") or res.get("data"),
                           "preflight": pre.get("output") or pre}
                else:
                    session = a.get("session")
                    env = {**os.environ, "AI_TRACKING_ID": session}
                    bounce_res = _run(SELF_RESTART, ["--in-min", str(a.get("bounce_in_min", 2))], env=env)
                    res = {"success": True, "offloaded": res.get("output") or res.get("data"),
                           "preflight": "OK — safe to resume",
                           "bounce": bounce_res.get("data") or bounce_res.get("output") or bounce_res}

    elif short == "recall":
        path, err = _need_path(a.get("session"))
        if err:
            res = err
        else:
            args = ["recall", path, "--engram-id", a["engram_id"], "--json"]
            if a.get("leaf"):
                args += ["--leaf", a["leaf"]]
            res = _run(MEMORY_MGR, args)

    elif short == "rehydrate":
        path, err = _need_path(a.get("session"))
        if err:
            res = err
        elif a.get("engram_id"):
            res = _run(MEMORY_MGR, ["rehydrate", path, "--engram-id", a["engram_id"], "--json"])
        else:
            res = _run(OFFLOAD, [path, "--rehydrate", "--json"])

    elif short == "slim":
        path, err = _need_path(a.get("session"))
        if err:
            res = err
        else:
            args = ["slim-engrams", path, "--json"]
            if a.get("dry_run", True):
                args.append("--dry-run")
            res = _run(MEMORY_MGR, args)

    # `summarize_*` is canonical; `consolidate_*` is a deprecated alias routed to
    # the same logic (back-compat).
    elif short in ("summarize_plan", "consolidate_plan"):
        path, err = _need_path(a.get("session"))
        if err:
            res = err
        else:
            args = ["plan", path, "--used-pct", str(a["used_pct"]),
                    "--need-tokens", str(a["need_tokens"])]
            if a.get("leaf"):
                args += ["--leaf", a["leaf"]]
            if a.get("keep_recent") is not None:
                args += ["--keep-recent", str(a["keep_recent"])]
            res = _run(RECLAIM, args)

    elif short in ("summarize_enact", "consolidate_enact"):
        path, err = _need_path(a.get("session"))
        if err:
            res = err
        else:
            args = ["enact", path, "--summaries", a["summaries_file"], "--no-local-llm-shadow"]
            if a.get("leaf"):
                args += ["--leaf", a["leaf"]]
            if a.get("keep_recent") is not None:
                args += ["--keep-recent", str(a["keep_recent"])]
            res = _run(RECLAIM, args)

    elif short == "check_resume":
        path, err = _need_path(a.get("session"))
        if err:
            res = err
        else:
            res = _run(CHECK_RI, [path, "--json"])

    elif short == "bounce":
        session = a.get("session")
        if not session:
            res = {"success": False, "error": "session (tracking_id) is required"}
        else:
            args = ["--in-min", str(a.get("in_min", 2))]
            if a.get("dry_run", True):
                args.append("--dry-run")
            env = {**os.environ, "AI_TRACKING_ID": session}
            res = _run(SELF_RESTART, args, env=env)

    else:
        return None

    return [TextContent(type="text", text=json.dumps(res, indent=2))]
