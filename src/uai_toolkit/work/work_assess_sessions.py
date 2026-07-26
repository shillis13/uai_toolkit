#!/usr/bin/env python3
"""work_assess_sessions.py — LLLM interpretive layer for the work landscape.

The landscape query (work_landscape.py) gives the structural skeleton: which
session owns which todo, status, freshness. It cannot tell that a session is
*stuck*, or ended its last turn with an open question to PianoMan. This script
adds that soft layer: it tails each active session's transcript and asks the
local LLM (no tools, text-in / structured-out) for a per-session assessment,
written to data/work/assessments.json for work_landscape.py to consume.

Designed to run headless on a schedule (sched-task-mgr / cron) so the coordinator
never burns its own context reading everyone's logs.

Targets Python 3.9.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime

_ENV_ROOT = os.environ.get("AI_ROOT")
AI_ROOT = _ENV_ROOT if (_ENV_ROOT and os.path.isdir(_ENV_ROOT)) else "$AI_ROOT"
MGR_DIR = AI_ROOT + "/ai_general/scripts/mgrs"
LLLM_PROMPT = AI_ROOT + "/ai_general/scripts/lllm/lllm_prompt.py"
OUT_DIR = AI_ROOT + "/ai_general/data/work"
OUT_FILE = OUT_DIR + "/assessments.json"

# Only assess sessions whose last activity is within this many hours (skip stale).
FRESH_HOURS = 12
# How much of the transcript tail to feed the model.
TAIL_CHARS = 6000

ASSESS_PROMPT = (
    "You are a session-state assessor for a multi-agent AI workspace. Read the "
    "session transcript excerpt and output ONLY a single JSON object, no prose, "
    "with exactly these keys: "
    '{"state": one of "productive"|"blocked"|"waiting_on_user"|"idle", '
    '"project_guess": short scope string or null, '
    '"open_question": the unresolved question the session is waiting on, or null, '
    '"needs_pianoman": true or false, '
    '"recent_directives": array (0-3) of short strings — each a concrete task '
    "PianoMan (the human operator) told THIS session to do, most recent first}. "
    "For recent_directives: PianoMan is the human user. Include ONLY direct work "
    "instructions from the human — NOT messages relayed from other named agents "
    "(e.g. 'Queued Message from <Agent>', 'You have unread mail', another session "
    "speaking), NOT system reminders/notifications/tool output. Each entry is a "
    "terse imperative (e.g. 'Fix the Work Mgr sort order'). Empty array if the "
    "excerpt shows no human directive. "
    "Base it only on the excerpt."
)


def _run_json(mgr, args):
    out = []
    try:
        proc = subprocess.run([mgr] + args + ["--json"], cwd=MGR_DIR,
                              capture_output=True, text=True, timeout=30)
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            if isinstance(data, list):
                out = data
            elif isinstance(data, dict):
                for key in ("sessions", "todos", "items"):
                    if isinstance(data.get(key), list):
                        out = data[key]
                        break
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        out = []
    return out


def _fresh(iso_ts, hours):
    """True if iso_ts is within `hours` of now."""
    ok = False
    if iso_ts:
        try:
            then = datetime.fromisoformat(iso_ts)
            now = datetime.now(then.tzinfo)
            ok = (now - then).total_seconds() <= hours * 3600
        except (ValueError, TypeError):
            ok = False
    return ok


def _transcript_tail(path, limit):
    """Extract the last `limit` chars of human-readable text from a jsonl transcript.

    `path` may be a string or a list of paths (a session accrues one per resume);
    in the list case the most recent (last) entry is used.
    """
    text = ""
    if isinstance(path, list):
        path = path[-1] if path else ""
    if path and os.path.isfile(path):
        chunks = []
        try:
            with open(path, "r", errors="replace") as fh:
                lines = fh.readlines()[-60:]
            for line in lines:
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                role = obj.get("type") or (obj.get("message") or {}).get("role")
                content = (obj.get("message") or {}).get("content")
                piece = ""
                if isinstance(content, str):
                    piece = content
                elif isinstance(content, list):
                    piece = " ".join(
                        p.get("text", "") for p in content
                        if isinstance(p, dict) and p.get("type") == "text"
                    )
                if piece.strip():
                    chunks.append("%s: %s" % (role or "?", piece.strip()))
        except OSError:
            chunks = []
        text = "\n".join(chunks)[-limit:]
    return text


def _parse_assessment(raw):
    """Pull the first JSON object out of the model's reply. None on failure."""
    parsed = None
    if raw:
        match = re.search(r"\{.*\}", raw, re.DOTALL)
        if match:
            try:
                parsed = json.loads(match.group(0))
            except json.JSONDecodeError:
                parsed = None
    return parsed


def _normalize_recent_directives(value):
    """Return at most three non-empty, single-line directive strings.

    Local models can omit the new key or return the wrong JSON type despite the
    requested schema. Keep that malformed output from leaking into the cache/UI.
    """
    if not isinstance(value, list):
        return []
    clean = []
    for item in value:
        if not isinstance(item, str):
            continue
        item = " ".join(item.split())
        if item and item not in clean:
            clean.append(item)
        if len(clean) == 3:
            break
    return clean


def assess_one(name, excerpt):
    """Run the LLLM assessment for one session's excerpt. None on failure."""
    result = None
    try:
        # Invoke lllm_prompt.py via its own shebang (the MCP venv python, which has
        # httpx) — NOT the caller's interpreter. /usr/bin/python3 lacks httpx, so
        # using sys.executable here made every call fail under the scheduler.
        proc = subprocess.run(
            [LLLM_PROMPT, ASSESS_PROMPT, "--text", excerpt],
            capture_output=True, text=True, timeout=120,
        )
        if proc.returncode == 0:
            result = _parse_assessment(proc.stdout)
            if isinstance(result, dict):
                result["recent_directives"] = _normalize_recent_directives(
                    result.get("recent_directives")
                )
            else:
                result = None
    except (subprocess.SubprocessError, OSError):
        result = None
    return result


def gather(only_session):
    """Assess fresh active sessions; return {name: assessment}."""
    sessions = _run_json(MGR_DIR + "/sess-mgr", ["list"])
    stamp = datetime.now().isoformat(timespec="seconds")
    assessments = {}
    for sess in sessions:
        name = sess.get("display_name") or sess.get("tracking_id")
        if not name:
            continue
        if only_session and name != only_session:
            continue
        if not only_session:
            if sess.get("status") != "active" or not _fresh(sess.get("last_activity"), FRESH_HOURS):
                continue
        excerpt = _transcript_tail(sess.get("transcript_path"), TAIL_CHARS)
        if not excerpt:
            continue
        verdict = assess_one(name, excerpt)
        if verdict:
            verdict["assessed_at"] = stamp
            assessments[name] = verdict
    return assessments


ASSESS_EPILOG = """\
WHAT IT DOES
  The interpretive layer behind `work_landscape.py --enrich`. It reads each
  fresh session's recent transcript and asks the local LLM the questions that
  structure can't answer -- is it stuck? waiting on PianoMan? what's its open
  question? -- then caches a structured verdict per session. Built to run
  HEADLESS on a schedule.

  LLLM = local LLM: a tool-less llama-server model (text in, JSON out). It can
  only assess, never act. Reached via scripts/lllm/lllm_prompt.py.

PIPELINE  (per run)
  1. sess-mgr list --json, then a FRESHNESS GATE -- skip "active" ghosts idle
     more than 12h. (--session X assesses that one session on demand and
     bypasses the gate.)
  2. Read the tail of the session's newest transcript: ~the last 60 JSONL
     lines -> the last 6000 chars of human-readable user/assistant text.
  3. Run lllm_prompt.py with the assess prompt. The model must return ONE JSON
     object: {state, project_guess, open_question, needs_pianoman,
     recent_directives}. recent_directives (todo_0431) = 0-3 terse tasks
     PianoMan (the human) told this session to do, extracted from the excerpt
     while ignoring agent relays / system notifications -> the PM DIRECTIVES
     feed on the board.
     NB: lllm_prompt.py is invoked via its OWN shebang/venv (which has httpx) --
     using the caller's python silently zeroed every assessment under launchd.
  4. Defensively parse the first {...} block (local models wrap JSON in prose).
  5. Stamp each verdict with assessed_at.

OUTPUT -- data/work/assessments.json   (MERGE, never overwrite)
  Keyed by session display_name:
    { "Mullion": { "state": "productive|blocked|waiting_on_user|idle",
                   "project_guess": <str|null>, "open_question": <str|null>,
                   "needs_pianoman": true, "recent_directives": [<str>, ...],
                   "assessed_at": "2026-..." }, ... }
  New verdicts are merged OVER the existing file. A run that produces nothing
  (LLLM down/busy, or no fresh sessions) is a no-op -- it never clobbers
  last-good data; un-reassessed sessions keep their prior verdict (an older
  assessed_at is how you spot staleness). --stdout prints instead of writing.

SCHEDULING  (off by default)
  data/scheduled_tasks/work.yml defines an assess_sessions job (*/30 * * * *,
  enabled: false). Running the LLLM every 30 min keeps a model warm ~always --
  a GPU/RAM commitment, so it's PianoMan's call. To activate:
    sched-task-mgr enable work && sched-task-mgr install

EXAMPLES
  work_assess_sessions.py                    # assess all fresh sessions, merge to file
  work_assess_sessions.py --stdout           # dry run: print verdicts, write nothing
  work_assess_sessions.py --session Mullion  # assess one session, ignore freshness

SEE ALSO
  work_landscape.py --enrich   consumes this assessments file
  work_summarize_sessions.py   free-text (not structured) per-session summaries
  scripts/work/DESIGN.md        the full design & rationale
"""


def main():
    parser = argparse.ArgumentParser(
        description="LLLM per-session assessor: reads fresh sessions' transcripts and caches a "
                    "structured verdict (state / open_question / needs_pianoman / "
                    "recent_directives) that feeds `work_landscape.py --enrich`. "
                    "Read-only except for its own output file.",
        epilog=ASSESS_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--session",
                        help="assess ONLY this session (by display name); bypasses the 12h "
                             "freshness gate so you can force a re-assessment on demand")
    parser.add_argument("--stdout", action="store_true",
                        help="print the new verdicts as JSON and do NOT write/merge the file "
                             "(a safe dry run)")
    args = parser.parse_args()

    new = gather(args.session)

    if args.stdout:
        print(json.dumps(new, indent=2))
        return 0

    if not os.path.isdir(OUT_DIR):
        os.mkdir(OUT_DIR)

    # Merge over any existing assessments rather than overwrite. A run that
    # produces nothing (LLLM busy/down, no fresh sessions) must NOT clobber the
    # last-good data; sessions not re-assessed this run keep their prior verdict.
    merged = {}
    if os.path.isfile(OUT_FILE):
        try:
            with open(OUT_FILE) as fh:
                existing = json.load(fh)
            if isinstance(existing, dict):
                merged = existing
        except (OSError, json.JSONDecodeError):
            merged = {}
    merged.update(new)

    with open(OUT_FILE, "w") as fh:
        fh.write(json.dumps(merged, indent=2))
    print("wrote %d new assessment(s) (merged -> %d total) -> %s"
          % (len(new), len(merged), OUT_FILE))
    return 0


if __name__ == "__main__":
    sys.exit(main())
