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
import json
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


ASSESSMENTS_FILE = "$AI_ROOT/ai_general/data/work/assessments.json"


def _load_assessments():
    """Load the LLLM interpretive layer (work_assess_sessions.py output). Empty if absent."""
    data = {}
    try:
        with open(ASSESSMENTS_FILE, "r") as fh:
            loaded = json.load(fh)
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, json.JSONDecodeError):
        data = {}
    return data


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
        age = _age_secs(sess.get("last_activity"))
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
            "ago": _ago(sess.get("last_activity")),
            "last_activity": sess.get("last_activity"),   # raw ISO — for UI sort
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

    model = {
        "rows": rows,
        "totals": {
            "todos": len(todos),
            "todos_no_assignee": sum(1 for t in todos if not t.get("assigned")),
            "active_sessions": sum(1 for r in rows if r["kind"] == "session" and r["status"] == "active"),
            "active_no_todo": sum(1 for r in rows if r["kind"] == "session" and r["status"] == "active" and not r["todos"]),
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
  needs_pianoman with its open question. blocked / permission_prompt STATEs are
  folded in here too as real-time "needs the user" signals.

--json     Emit the raw joined model instead of the table -- the shape the UAI
           coordinator cockpit consumes.

EXAMPLES
  work_landscape.py                    # active sessions, structural table
  work_landscape.py --all              # include stopped sessions
  work_landscape.py --assignees-only   # only sessions that have a todo
  work_landscape.py --enrich           # + LLLM states + NEEDS PIANOMAN section
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
                        help="join in the LLLM assessment layer (states + NEEDS PIANOMAN) "
                             "from data/work/assessments.json, if present")
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
