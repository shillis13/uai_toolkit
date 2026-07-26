#!/usr/bin/env python3
"""needs_user_mgr.py — the "Needs Me / Needs User" decision queue (todo_0578/0579).

WHAT THIS IS
    A small, durable store of decisions that only the human user (PianoMan) can
    make. When a coordinator (Hamilton) or a session hits a fork in the road that
    it should not decide on its own — a go/no-go, a "which of these two designs",
    a policy call — it FILES the decision here with enough context that the user
    can answer without going and digging. The user answers; the answer routes back
    to whoever filed it; the record is marked answered and drops off the open list.

WHERE IT SHOWS UP
    The UAI Live Board's "Needs Me" tab renders the open decisions (via
    work_landscape.py, which reads this same store). The user answers in place on
    the board, or over MCP (workflow_needs_user_* tools), or from this CLI.

HOW IT RELATES TO OTHER SIGNALS
    This does NOT replace the existing escalation signals — a session's
    declare_stop(reason=need_decision) and a "needs PianoMan" todo flag are still
    the triggers that say "someone needs the user." This store is the
    context-carrying SURFACE those signals lacked: the actual question, the
    options, the filer's recommendation, and where it came from, all in one place.

THE STORE
    File: data/work/pm_decisions.json  ->  {"decisions": [ <record>, ... ]}
    (The filename is historical — kept so the decisions already filed there are
    not disturbed. The concept is "needs user", not "PM" specifically.)

    Record fields:
      id              short unique id (assigned on --add)
      decision        one-line question the user must answer
      options         the choices, e.g. "build now | defer" (free text, optional)
      recommendation  the filer's lean, so the user can just say "yes" (optional)
      source_todo     originating todo id, e.g. todo_0411 (optional; links on board)
      source_session  originating session name or id (optional; links on board)
      note            extra background — the LONGER the better; the board shows
                      this in an expandable "Details" section (optional)
      status          "open", "answered", or "addressed"
      created_at      when filed (local time)
      answered_at     when the user answered (local time; null until then)
      answer          the user's answer (null until then)

    Forward-compatible by design: the record is a plain dict, so adding fields
    later — e.g. a `comments` thread or a richer `state` beyond open/answered
    (todo_0579 item 5, "wait and see") — is additive and won't break older records
    or readers, which ignore unknown keys.

USING IT (flag-based CLI — exactly one of --add / --answer / --list per call)
    File a decision the user needs to make:
      needs_user_mgr.py --add --decision "go/no-go on the drag-drop feature" \
          --options "build now | defer" --recommendation "go" \
          --source-todo todo_0411 --source-session Hardy \
          --note "PM created 0411 himself and asked for a go/no-go first."

    Record the user's answer (routes back to the filer, clears from open list):
      needs_user_mgr.py --answer <id> --text "go — ship it"

    See what's waiting:
      needs_user_mgr.py --list --open        # only unanswered
      needs_user_mgr.py --list --json        # machine-readable
"""

import argparse
import json
import os
import sys
import uuid
from datetime import datetime
from pathlib import Path

_AI_ROOT = Path(os.environ.get("AI_ROOT", str(Path.home() / "AI" / "ai_root")))
STORE = _AI_ROOT / "ai_general" / "data" / "work" / "pm_decisions.json"
_RESOLVED = {"answered", "addressed"}


def _now():
    # Local time (workspace convention: display local, no UTC).
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def _load():
    if not STORE.exists():
        return []
    try:
        data = json.loads(STORE.read_text())
    except FileNotFoundError:
        # The file can disappear between exists() and read_text().
        return []
    except json.JSONDecodeError as exc:
        # Never turn a corrupt durable store into an empty list that the next
        # write would silently overwrite.
        raise RuntimeError(f"decision store is not valid JSON: {STORE}: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("decisions", []), list):
        raise RuntimeError(f"decision store has an invalid shape: {STORE}")
    return data.get("decisions", [])


def _save(decisions):
    STORE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STORE.with_name(f".{STORE.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        tmp.write_text(json.dumps({"decisions": decisions}, indent=2, ensure_ascii=False))
        os.replace(tmp, STORE)
    finally:
        if tmp.exists():
            tmp.unlink()


def op_add(args):
    if not (args.decision or "").strip():
        return {"success": False, "error": "--decision is required"}
    rec = {
        "id": uuid.uuid4().hex[:8],
        "decision": args.decision.strip(),
        "options": (args.options or "").strip(),
        "recommendation": (args.recommendation or "").strip(),
        "source_todo": (args.source_todo or "").strip(),
        "source_session": (args.source_session or "").strip(),
        "note": (args.note or "").strip(),
        "status": "open",
        "created_at": _now(),
        "answered_at": None,
        "answer": None,
    }
    decisions = _load()
    decisions.append(rec)
    _save(decisions)
    return {"success": True, "id": rec["id"], "record": rec}


def op_answer(args):
    text = (args.text or "").strip()
    if not text:
        return {"success": False, "error": "--text (the answer) is required"}
    decisions = _load()
    for rec in decisions:
        if rec.get("id") == args.answer:
            if rec.get("status", "open") in _RESOLVED:
                return {"success": False, "error": f"{args.answer} already {rec.get('status')}"}
            rec["status"] = "answered"
            rec["answer"] = text
            rec["answered_at"] = _now()
            _save(decisions)
            # The record stays (marked answered) so the answer can be routed to
            # Hamilton before a caller prunes it; --list --open hides it.
            return {"success": True, "id": rec["id"], "record": rec}
    return {"success": False, "error": f"no open decision with id {args.answer!r}"}


def op_addressed(args):
    """Dismiss a decision as already-addressed/moot (archive it) without answering.

    Same effect as answering for the board (it drops off the open list) but marks
    a distinct status and does NOT carry a decision answer — the reason, if given,
    just records why it no longer needs the user.
    """
    decisions = _load()
    for rec in decisions:
        if rec.get("id") == args.addressed:
            if rec.get("status", "open") in _RESOLVED:
                return {"success": False, "error": f"{args.addressed} already {rec.get('status')}"}
            rec["status"] = "addressed"
            rec["answer"] = (args.text or "").strip() or "(marked already addressed)"
            rec["answered_at"] = _now()
            _save(decisions)
            return {"success": True, "id": rec["id"], "record": rec}
    return {"success": False, "error": f"no open decision with id {args.addressed!r}"}


def op_list(args):
    decisions = _load()
    if args.open:
        decisions = [d for d in decisions if d.get("status") not in _RESOLVED]
    # Oldest first — the board sorts by age so the longest-waiting call is on top.
    decisions = sorted(decisions, key=lambda d: d.get("created_at") or "")
    return {"success": True, "count": len(decisions), "decisions": decisions}


def main(argv=None):
    p = argparse.ArgumentParser(
        description="The 'Needs Me / Needs User' decision queue: file a decision only "
                    "the user can make, record the user's answer, or list what's waiting "
                    "(todo_0578/0579). The UAI Live Board's 'Needs Me' tab reads this "
                    "same store via work_landscape.py.",
        epilog="Examples:\n"
               "  needs_user_mgr.py --add --decision 'go/no-go on X' --options 'build now | defer' "
               "--recommendation 'go' --source-todo todo_0411 --source-session Hardy\n"
               "  needs_user_mgr.py --answer 1a2b3c4d --text 'go — ship it'\n"
               "  needs_user_mgr.py --list --open --json\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = p.add_mutually_exclusive_group(required=True)
    mode.add_argument("--add", action="store_true", help="File a new escalated decision")
    mode.add_argument("--answer", metavar="ID", help="Record the user's answer for decision ID")
    mode.add_argument("--addressed", metavar="ID",
                      help="Dismiss/archive decision ID as already-addressed or moot (no routed answer)")
    mode.add_argument("--list", action="store_true", help="List decisions")
    p.add_argument("--decision", help="[--add] one-line decision summary")
    p.add_argument("--options", help="[--add] the choices, e.g. 'build now | defer'")
    p.add_argument("--recommendation", help="[--add] Hamilton's lean")
    p.add_argument("--source-todo", help="[--add] originating todo id")
    p.add_argument("--source-session", help="[--add] originating session (name or id)")
    p.add_argument("--note", help="[--add] extra context from Hamilton")
    p.add_argument("--text", help="[--answer] the user's answer text / [--addressed] optional reason")
    p.add_argument("--open", action="store_true", help="[--list] only unresolved (open) decisions")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    args = p.parse_args(argv)

    if args.add:
        result = op_add(args)
    elif args.answer:
        result = op_answer(args)
    elif args.addressed:
        result = op_addressed(args)
    else:
        result = op_list(args)

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif not result.get("success"):
        print(f"Error: {result.get('error')}", file=sys.stderr)
        return 1
    elif args.list:
        ds = result["decisions"]
        if not ds:
            print("No decisions.")
        for d in ds:
            st = d.get("status", "open")
            mark = "[OPEN]" if st == "open" else f"[{st}]"
            print(f"  {d['id']}  {mark}  {d['decision']}")
            if d.get("options"):
                print(f"      options: {d['options']}")
            if d.get("recommendation"):
                print(f"      rec:     {d['recommendation']}")
            src = " / ".join(x for x in (d.get("source_todo"), d.get("source_session")) if x)
            if src:
                print(f"      source:  {src}")
    else:
        print(f"{result.get('id')}: {result['record']['status']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
