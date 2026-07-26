#!/usr/bin/env python3
"""work_landscape.py — Hamilton's data backbone.

Joins the three sources that already exist — sessions (session_store), todos
(todos-mgr), and activity (activity_log) — into one "who is doing what" view.

This is the deterministic skeleton the coordinator role's `landscape_awareness`
and `curate_for_pianoman` duties stand on. It reads only; it never mutates.

Assignment convention: a todo's assignees live in `assigned.yml` as
`uai://session/<tracking_id>` URIs, resolved here to the session display_name
(e.g. "Mullion"). project is a freeform scope string (e.g. "uai"). Both sparse —
the view surfaces that gap rather than hiding it.

Targets Python 3.9 (no 3.10+ syntax).
"""

import argparse
import glob
import json
import os
import subprocess
import sys
from datetime import datetime

MGR_DIR = "$AI_ROOT/ai_general/scripts/mgrs"
STATUS_CODE = {
    "Triaging": "TR", "Needs_Research": "NR", "Needs_Derivation": "ND",
    "Ready": "RD", "In_Progress": "IP", "Reviewing": "RV",
    "Accepting": "AC", "Blocked": "BL", "Done": "DN", "Cancelled": "CN",
}

# Relay's reconciled activity_state values that mean "needs the user right now"
# (real-time ground truth from hooks + terminal, not LLLM inference).
NEEDS_USER_STATES = {"blocked", "permission_prompt"}
# Compact display for the longer activity_state values.
STATE_SHORT = {"prompt_occupied": "drafting", "permission_prompt": "perm-req"}


def _run_json(mgr, args):
    """Run a manager with --json and return the parsed list. Empty list on failure."""
    result = []
    try:
        proc = subprocess.run(
            [mgr] + args + ["--json"],
            cwd=MGR_DIR, capture_output=True, text=True, timeout=30,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            if isinstance(data, list):
                result = data
            elif isinstance(data, dict):
                for key in ("sessions", "todos", "items"):
                    if isinstance(data.get(key), list):
                        result = data[key]
                        break
    except (subprocess.SubprocessError, json.JSONDecodeError, OSError):
        result = []
    return result


def _ago(iso_ts):
    """Human relative time from a local ISO timestamp. '?' if unparseable."""
    label = "?"
    if iso_ts:
        try:
            then = datetime.fromisoformat(iso_ts)
            now = datetime.now(then.tzinfo)
            secs = (now - then).total_seconds()
            if secs < 90:
                label = "now"
            elif secs < 3600:
                label = "%dm ago" % (secs // 60)
            elif secs < 86400:
                label = "%dh ago" % (secs // 3600)
            else:
                label = "%dd ago" % (secs // 86400)
        except (ValueError, TypeError):
            label = "?"
    return label


def _age_secs(iso_ts):
    """Age of a local ISO timestamp in seconds, or None if unparseable."""
    if not iso_ts:
        return None
    try:
        then = datetime.fromisoformat(iso_ts)
        now = datetime.now(then.tzinfo)
        return (now - then).total_seconds()
    except (ValueError, TypeError):
        return None


# A "responding"/"working" state that hasn't updated in this long lost its
# completion signal (the session bounced/compacted/exited mid-response, so the
# Stop→idle transition never fired). A real response updates activity within
# minutes — so treat a stale busy-state as idle for display. (Does NOT touch
# blocked/permission_prompt, which legitimately persist while waiting.)
STALE_IF_BUSY = frozenset({"responding", "working"})
STALE_BUSY_SECS = 600  # 10 minutes

# A transcript/activity source touched within this window means the session did
# REAL work just now — the truthful "is it alive" signal, independent of the
# Stop-hook last_activity column (stale for a resumed/mid-turn session). (todo_0575)
LIVE_ACTIVE_SECS = 180  # 3 minutes


def _resolve_transcript(sess):
    """Newest session transcript/activity-source path, or None (todo_0575).

    Considers every registry-stored path plus platform-specific fallbacks by
    cli_session_id, then chooses the newest existing candidate. This matters for
    resumed sessions whose registry can retain more than one transcript path."""
    candidates = []
    tp = sess.get("transcript_path")
    if isinstance(tp, list):
        candidates.extend(p for p in tp if p)
    elif tp:
        candidates.append(tp)
    hf = sess.get("history_file")
    if hf:
        candidates.append(hf)
    cli = sess.get("cli_session_id")
    plat = sess.get("platform") or ""
    pats = []
    unknown_plat = plat in ("", "?")
    if cli and (plat.startswith("claude") or unknown_plat):
        pats.append(os.path.expanduser("~/.claude/projects/*/%s.jsonl" % cli))
    if cli and (plat.startswith("codex") or unknown_plat):
        pats.append(os.path.expanduser("~/.codex/sessions/**/rollout-*%s.jsonl" % cli))
    if cli and (plat.startswith("gemini") or unknown_plat):
        # Gemini transcript filenames contain the first eight UUID characters,
        # not the full cli_session_id, and installations can use either suffix.
        uuid8 = cli[:8]
        pats.extend([
            os.path.expanduser("~/.gemini/**/*%s*.jsonl" % uuid8),
            os.path.expanduser("~/.gemini/**/*%s*.json" % uuid8),
        ])
    if cli and (plat.startswith("grok") or unknown_plat):
        pats.extend([
            os.path.expanduser("~/.grok/sessions/**/%s/chat_history.jsonl" % cli),
            os.path.expanduser("~/.grok/sessions/**/%s/events.jsonl" % cli),
        ])
    if cli and (plat.startswith("antigravity") or unknown_plat):
        # Antigravity's conversation DB is the authoritative per-turn activity
        # source; the JSONL cache may exist too.
        candidates.extend([
            os.path.expanduser(
                "~/.gemini/antigravity-cli/conversations/%s.db" % cli
            ),
            os.path.expanduser(
                "~/.gemini/antigravity-cli/cache/transcripts/%s.jsonl" % cli
            ),
        ])
    newest = None
    for pat in pats:
        candidates.extend(glob.glob(pat, recursive=True))
    for p in dict.fromkeys(candidates):
        try:
            m = os.stat(p).st_mtime
        except (OSError, TypeError):
            continue
        if newest is None or m > newest[0]:
            newest = (m, p)
    return newest[1] if newest else None


def _transcript_activity(sess):
    """(iso, age_secs) of the transcript/activity source mtime, or (None, None).

    The source is written on every turn, so its mtime is a truthful last-touch
    signal — unlike the last_activity column, which only the Stop hook writes and
    therefore reads stale for a resumed, still-responding session (todo_0575)."""
    path = _resolve_transcript(sess)
    if not path:
        return None, None
    try:
        m = os.stat(path).st_mtime
    except OSError:
        return None, None
    iso = datetime.fromtimestamp(m).astimezone().isoformat()
    return iso, _age_secs(iso)


def _derive_liveness(status, raw_state, age):
    """Coarse liveness axis, DISTINCT from the lifecycle `status` (todo_0575).

    The bug this fixes: `status == "active"` means only "the terminal process
    still exists", so sessions idle for days read "active". Liveness instead
    answers "did it do work recently?":
      - dead: terminal/process is gone (lifecycle status not active)
      - blocked / permission_prompt: really waiting on the user (surfaced as-is)
      - active: real activity within LIVE_ACTIVE_SECS
      - idle: alive but quiet
    (errored/rate-limited detection is a documented follow-up — see DESIGN.md.)"""
    if status != "active":
        return "dead"
    if raw_state in NEEDS_USER_STATES:
        return raw_state
    if age is not None and age <= LIVE_ACTIVE_SECS:
        return "active"
    return "idle"


ASSESSMENTS_FILE = "$AI_ROOT/ai_general/data/work/assessments.json"


def _normalize_directives(value):
    """Return the cached directive field in its public list-of-strings shape."""
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


def _load_assessments():
    """Load the LLLM interpretive layer (work_assess_sessions.py output). Empty if absent."""
    data = {}
    try:
        with open(ASSESSMENTS_FILE, "r") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            for name, assessment in loaded.items():
                if not isinstance(assessment, dict):
                    continue
                assessment = dict(assessment)
                assessment["recent_directives"] = _normalize_directives(
                    assessment.get("recent_directives")
                )
                data[name] = assessment
    except (OSError, json.JSONDecodeError):
        data = {}
    return data


PM_DECISIONS_FILE = "$AI_ROOT/ai_general/data/work/pm_decisions.json"


def _load_pm_decisions():
    """Open 'Needs Me' decisions (needs_user_mgr.py store), oldest first.

    The board's "Needs Me" tab renders these; longest-waiting on top (todo_0578/0579).
    A decision drops off once it's resolved — either answered or dismissed as
    already-addressed. Empty list if the store is absent — the rest of the
    landscape is unaffected.
    """
    try:
        with open(PM_DECISIONS_FILE, "r") as fh:
            loaded = json.load(fh)
        decisions = loaded.get("decisions", []) if isinstance(loaded, dict) else []
    except (OSError, json.JSONDecodeError):
        return []
    open_ = [d for d in decisions if d.get("status", "open") not in ("answered", "addressed")]
    return sorted(open_, key=lambda d: d.get("created_at") or "")


def load_landscape(include_stopped, enrich=False):
    """Build the joined model: each session with its assigned todos, plus gap tallies."""
    sessions = _run_json(MGR_DIR + "/sess-mgr", ["list"])
    todos = _run_json(MGR_DIR + "/todos-mgr", ["list"])
    assessments = _load_assessments() if enrich else {}

    # Assignment lives in assigned.yml as `uai://<kind>/<id>` URIs — the SINGLE
    # linkage. A todo is assigned to a WORKER (a session, team, or project — all
    # organized units that do work) or to nothing. Sessions resolve their
    # tracking-id to a display_name; team/project keep their id as the label.
    tid_to_name = {}
    for sess in sessions:
        tid = sess.get("tracking_id")
        if tid:
            tid_to_name[tid] = sess.get("display_name") or tid

    def _assignments(todo):
        """→ list of (kind, name) worker keys this todo is assigned to."""
        out = []
        for uri in (todo.get("assigned") or []):
            parts = (uri or "").split("/")
            if uri and uri.startswith("uai://") and len(parts) > 3:
                kind, ident = parts[2], parts[3]
                if kind in ("team", "project"):
                    out.append((kind, ident))
                else:  # session (or any other kind) → resolve to a session name
                    out.append(("session", tid_to_name.get(ident, ident)))
            else:  # legacy bare form → treat the last segment as a session
                ident = (uri or "").rstrip("/").split("/")[-1]
                if ident:
                    out.append(("session", tid_to_name.get(ident, ident)))
        return out

    assigned = {}      # (kind, name) -> [todos]
    unassigned = []    # todos with no worker
    for todo in todos:
        keys = _assignments(todo)
        if not keys:
            unassigned.append(todo)
        for key in keys:
            assigned.setdefault(key, []).append(todo)

    def _newest(ts_list):
        vals = [t.get("updated") or t.get("created") or "" for t in ts_list if (t.get("updated") or t.get("created"))]
        return max(vals) if vals else None

    rows = []
    # 1) Session workers — the live agents (real activity_state).
    for sess in sessions:
        status = sess.get("status") or "?"
        if status != "active" and not include_stopped:
            continue
        name = sess.get("display_name") or sess.get("tracking_id") or "?"
        raw_state = sess.get("activity_state") or "unknown"
        state_display = raw_state if raw_state != "unknown" else status
        # todo_0575: the last_activity COLUMN is Stop-hook-only, so a resumed/
        # mid-turn session reads stale. Fold in the transcript file mtime (touched
        # every turn) and take the MORE RECENT of the two as the true activity.
        # Only for ACTIVE sessions — a stopped one is `dead` liveness regardless, so
        # resolving its transcript would just be a wasted glob (matters under --all).
        col_iso = sess.get("last_activity")
        col_age = _age_secs(col_iso)
        tx_iso, tx_age = _transcript_activity(sess) if status == "active" else (None, None)
        cand = [(a, i) for a, i in ((col_age, col_iso), (tx_age, tx_iso)) if a is not None]
        if cand:
            age, eff_iso = min(cand, key=lambda x: x[0])   # smallest age = most recent
        else:
            age, eff_iso = None, col_iso
        if raw_state in STALE_IF_BUSY and age is not None and age > STALE_BUSY_SECS:
            state_display = "idle"
        rows.append({
            "kind": "session",
            "name": name,
            "tracking_id": sess.get("tracking_id"),
            "platform": (sess.get("platform") or "?").replace("_cli", ""),
            "status": status,
            "activity_state": raw_state,
            "state_display": state_display,
            "liveness": _derive_liveness(status, raw_state, age),   # todo_0575
            "activity_age_secs": age,                               # todo_0575 (for UI)
            "ago": _ago(eff_iso),
            "last_activity": eff_iso,   # truthful ISO (col vs transcript, newest) — for UI sort
            "roles": sess.get("roles") or [],
            "todos": assigned.get(("session", name), []),
            "assessment": assessments.get(name),
        })

    # 2) Team / Project workers — organized units that DO work. No live process,
    # so board state is DERIVED from their assigned todos: active if any is
    # In_Progress; last_activity = the newest assigned todo.
    for (kind, name), ts in sorted(assigned.items()):
        if kind == "session":
            continue
        newest = _newest(ts)
        active = any(t.get("status") == "In_Progress" for t in ts)
        rows.append({
            "kind": kind,
            "name": name,
            "tracking_id": None,
            "platform": kind,
            "status": "active" if active else "idle",
            "activity_state": "unknown",
            "state_display": "active" if active else "idle",
            "ago": _ago(newest),
            "last_activity": newest,
            "roles": [],
            "todos": ts,
            "assessment": None,
        })

    # 3) Unassigned bucket — todos with no worker, so nothing is invisible.
    if unassigned:
        newest = _newest(unassigned)
        rows.append({
            "kind": "unassigned",
            "name": "(unassigned)",
            "tracking_id": None,
            "platform": "",
            "status": "idle",
            "activity_state": "unknown",
            "state_display": "idle",
            "ago": _ago(newest),
            "last_activity": newest,
            "roles": [],
            "todos": unassigned,
            "assessment": None,
        })

    rows.sort(key=lambda r: (r["status"] != "active", r["name"].lower()))

    needs_pm = _load_pm_decisions()
    model = {
        "rows": rows,
        "needs_pm": needs_pm,   # open escalated decisions for the board's "Needs You" panel (todo_0578)
        "totals": {
            "todos": len(todos),
            "todos_no_assignee": sum(1 for t in todos if not t.get("assigned")),
            "active_sessions": sum(1 for r in rows if r["kind"] == "session" and r["status"] == "active"),
            "active_no_todo": sum(1 for r in rows if r["kind"] == "session" and r["status"] == "active" and not r["todos"]),
            "needs_pm": len(needs_pm),
        },
    }
    return model


def _fmt_todo(todo):
    code = STATUS_CODE.get(todo.get("status"), todo.get("status") or "?")
    return "%s [%s]" % (todo.get("id", "?"), code)


def _needs_pianoman(row):
    """Needs PianoMan if the LLLM assessor flagged it OR Relay's live activity_state
    says it's waiting on the user. Two complementary signals: interpretive + ground-truth."""
    flagged = bool((row.get("assessment") or {}).get("needs_pianoman"))
    if not flagged and row.get("activity_state") in NEEDS_USER_STATES:
        flagged = True
    return flagged


def _needs_reason(row):
    """The line to show under NEEDS PIANOMAN — the assessor's question, else the state."""
    reason = ((row.get("assessment") or {}).get("open_question") or "").strip()
    if not reason:
        state = row.get("activity_state")
        if state == "permission_prompt":
            reason = "permission prompt — needs user"
        elif state == "blocked":
            reason = "blocked — needs user"
        else:
            reason = "(see session)"
    return reason


def _recent_directives(row):
    """Defensively normalize one cached assessment's directive list."""
    raw = (row.get("assessment") or {}).get("recent_directives")
    return _normalize_directives(raw)


def render(model):
    """Render the landscape as a text table with a gaps footer. Single return."""
    lines = []
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines.append("LANDSCAPE — sessions x work   (%s)" % stamp)
    lines.append("")
    lines.append("%-14s %-5s %-10s %-9s %s" % ("SESSION", "PLAT", "STATE", "ACTIVITY", "CURRENT WORK"))
    lines.append("-" * 78)
    for row in model["rows"]:
        if row["todos"]:
            work = "; ".join(_fmt_todo(t) for t in row["todos"])
        else:
            work = "(no assigned todo)"
        assess = row.get("assessment")
        if assess and assess.get("state") and assess["state"] != "productive":
            flag = " ⚑" if assess.get("needs_pianoman") else ""
            work = "%s  [%s%s]" % (work, assess["state"], flag)
        state = STATE_SHORT.get(row["state_display"], row["state_display"])
        lines.append("%-14s %-5s %-10s %-9s %s" % (
            row["name"][:14], row["platform"][:5], state[:10], row["ago"][:9], work))

    needs = [r for r in model["rows"] if _needs_pianoman(r)]
    if needs:
        lines.append("")
        lines.append("NEEDS PIANOMAN (⚑)")
        for row in needs:
            lines.append("  %-14s %s" % (row["name"][:14], _needs_reason(row)))

    # What PianoMan told each session to do (todo_0431) — the assessor's
    # recent_directives, extracted from each transcript. Hamilton's core duty of
    # tracking directly-issued (non-todo) assignments. Only shows under --enrich.
    directives = [(r, _recent_directives(r)) for r in model["rows"]]
    directives = [(r, ds) for r, ds in directives if ds]
    if directives:
        lines.append("")
        lines.append("PM DIRECTIVES  (per session; age = assessment age)")
        for row, ds in directives:
            name = row["name"]
            assessed_at = (row.get("assessment") or {}).get("assessed_at")
            age = _ago(assessed_at)
            age_label = "[%s] " % age if age != "?" else ""
            for i, d in enumerate(ds[:3]):
                label = name[:14] if i == 0 else ""
                prefix = age_label if i == 0 else (" " * len(age_label))
                lines.append("  %-14s %s%s" % (label, prefix, ("• " + d)[:90]))

    t = model["totals"]
    lines.append("")
    lines.append("GAPS")
    lines.append("  active sessions with no assigned todo: %d / %d   <- work not linked to a todo"
                 % (t["active_no_todo"], t["active_sessions"]))
    lines.append("  todos with no assignee: %d / %d   <- assignment unpopulated (backfill / LLLM inference)"
                 % (t["todos_no_assignee"], t["todos"]))
    return "\n".join(lines)


LANDSCAPE_EPILOG = """\
WHAT IT DOES
  Read-only. Builds ONE cross-session "who is doing what" table by joining two
  live sources. It never touches their stores and never mutates anything:
    - sess-mgr  list --json  -> sessions (name, platform, status,
                                activity_state, last_activity, roles)
    - todos-mgr list --json  -> todos    (id, status, assigned URIs, flags)
  A todo is linked to a session through its assigned.yml URIs
  (uai://session/<tracking_id>), resolved here to the session's display name.
  If either manager is missing or errors, that half degrades to empty and the
  command still runs -- it never crashes on a bad/absent manager.

THE TABLE  (default output)
  One row per ACTIVE session (add --all for stopped ones too):
    NAME      session display name (e.g. "Mullion")
    PLATFORM  claude / codex / gemini
    STATE     Relay's reconciled activity_state -- responding / idle / blocked
              / permission_prompt / prompt_occupied / exited. Preferred over
              raw status (active/stopped), which LIES (a session reads "active"
              for days after going quiet). Falls back to status only when
              activity_state is "unknown".
    AGO       freshness -- time since last_activity (now / Nm / Nh / Nd)
    ROLES     the session's roles
    WORK      the todos assigned to that session
  Rows sort active-first, then by name. A totals line tallies the honest gaps:
  active sessions with NO assigned todo, and todos with NO assignee.

--enrich   (opt-in interpretive layer; off by default so the base view is
            instant and needs no local LLM running)
  Joins in data/work/assessments.json (written by work_assess_sessions.py) by
  session name, adding: (a) a non-productive state tag on the WORK cell, e.g.
  [waiting_on_user]; (b) a NEEDS PIANOMAN section listing each session flagged
  needs_pianoman with its open question; (c) a PM DIRECTIVES section of recent
  human-issued tasks, labeled with assessment age. blocked / permission_prompt
  STATEs are folded in here too as real-time "needs the user" signals.

--json     Emit the raw joined model instead of the table -- the shape the UAI
           coordinator cockpit consumes.

EXAMPLES
  work_landscape.py                    # active sessions, structural table
  work_landscape.py --all              # include stopped sessions
  work_landscape.py --assignees-only   # only sessions that have a todo
  work_landscape.py --enrich           # + LLLM states / needs / PM directives
  work_landscape.py --json --enrich    # full model as JSON (for tooling)

SEE ALSO
  scripts/work/DESIGN.md         the full design & rationale
  work_assess_sessions.py        writes the --enrich assessments file
  work_summarize_sessions.py     free-text per-session narrative summaries
"""


def main():
    parser = argparse.ArgumentParser(
        description="Cross-session work landscape: joins sess-mgr + todos-mgr into one "
                    "read-only 'who is doing what / what's stale / what needs me' table.",
        epilog=LANDSCAPE_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--all", action="store_true",
                        help="include stopped sessions (default: active only)")
    parser.add_argument("--json", action="store_true",
                        help="emit the raw joined model as JSON instead of the table")
    parser.add_argument("--assignees-only", "--owners-only", dest="assignees_only",
                        action="store_true",
                        help="show only sessions that have at least one assigned todo")
    parser.add_argument("--enrich", action="store_true",
                        help="join the LLLM assessment layer (states, NEEDS PIANOMAN, "
                             "PM DIRECTIVES) from data/work/assessments.json, if present")
    args = parser.parse_args()

    model = load_landscape(include_stopped=args.all, enrich=args.enrich)
    if args.assignees_only:
        model["rows"] = [r for r in model["rows"] if r["todos"]]

    if args.json:
        output = json.dumps(model, indent=2)
    else:
        output = render(model)
    print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
