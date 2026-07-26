#!/usr/bin/env python3
"""declare_stop — a session declares WHY it is ending its turn (todo_0520).

Instead of the Stop hook *guessing* at turn-quality from output text (the
heuristic checkers 02/03/05/06), the session makes a positive declaration: it
selects one or more reasons from a config-driven taxonomy
(Stop/declare_stop.config.yml), plus per-reason params and an optional free-text
note. This script records that declaration into the canonical per-session hook
state file so the Stop handler (require_stop_declaration) can validate it, and so
the Live Board and downstream effects have a single structured source.

This script is the LOGIC; the declare_stop MCP tool is a thin wrapper over it
(reference: MCP-thin-wrapper principle). It is also runnable directly for tests.

Scope note: this writes the per-session HOOK STATE file
({session_dir}/{tracking_id}_state.json — the same file register_self_brief.py
and the hooks read/write). It does NOT touch the session_store registry (SQLite);
per session_mgmt/DESIGN.md, identity/roles/status live there. `stop.board_status`
below is a namespaced derived HINT for the Live Board, not the canonical session
status — how the board consumes it is wired in P2.

Keys written:
  - stop.declared_at   : ISO timestamp of this declaration
  - stop.checklist     : checklist JSON when the preferred checklist path is used
  - stop.payload       : {reasons:[...], params:{...}, note:"..."}
  - stop.block_streak  : reset to 0 (a valid declaration clears the anti-deadlock
                         counter the Stop handler increments on undeclared turns)
  - stop.board_status  : derived Live-Board status hint (highest-priority reason)
  - stop.pending_effects : downstream effects to fire (schedule_wake/flag_human/
                         check_assigned_todos/verify_todo) — RECORDED here, ACTED
                         on by P2. P1 records intent only; it triggers nothing.
  - updated_at

Env: AI_SESSION_DIR + AI_TRACKING_ID identify the state file (same as the hooks).
Exit 0 on success (prints JSON result); non-zero with a clear message otherwise —
errors are surfaced, never silently swallowed (workspace rule).
"""

import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

# The reason taxonomy lives with the tool (this directory), not in the hook dir.
CONFIG_PATH = Path(__file__).resolve().parent / "declare_stop.config.yml"

# Live-Board status priority — when several reasons carry a board_status, the
# most operationally salient wins. Higher index = higher priority.
_BOARD_PRIORITY = [
    "idle", "active", "paused", "parked", "managing_context",
    "waiting", "blocked", "wants_discussion", "needs_decision",
]

# Downstream effect names the config may attach to a reason (P2 acts on these).
_KNOWN_EFFECTS = {
    "schedule_wake", "flag_human", "check_assigned_todos", "verify_todo",
}


def _load_config():
    """Load the taxonomy. Lazy yaml import so a missing dep is a clear error."""
    try:
        import yaml  # noqa: PLC0415 — lazy on purpose
    except ImportError:
        raise RuntimeError(
            "declare_stop: PyYAML is required to read the taxonomy config."
        )
    if not CONFIG_PATH.exists():
        raise RuntimeError(f"declare_stop: taxonomy config not found: {CONFIG_PATH}")
    with CONFIG_PATH.open() as f:
        cfg = yaml.safe_load(f) or {}
    reasons = {r["id"]: r for r in cfg.get("reasons", []) if isinstance(r, dict) and r.get("id")}
    return cfg, reasons


def _board_status(selected, reasons_by_id):
    """Highest-priority board_status among the selected reasons (else 'idle')."""
    statuses = []
    for rid in selected:
        for entry in reasons_by_id.get(rid, {}).get("downstream", []) or []:
            if isinstance(entry, str) and entry.startswith("board_status:"):
                statuses.append(entry.split(":", 1)[1].strip())
    if not statuses:
        return "idle"
    return max(statuses, key=lambda s: _BOARD_PRIORITY.index(s) if s in _BOARD_PRIORITY else -1)


def _pending_effects(selected, reasons_by_id):
    """Collect the non-board downstream effects to fire (P2 consumes these)."""
    effects = []
    for rid in selected:
        for entry in reasons_by_id.get(rid, {}).get("downstream", []) or []:
            name = entry.split(":", 1)[0].strip() if isinstance(entry, str) else str(entry)
            if name in _KNOWN_EFFECTS:
                effects.append({"effect": name, "reason": rid})
    return effects


# ── Checklist (todo_0520) — the yes/no turn-review a session hands in at stop.
# Phased in ALONGSIDE the legacy reason list; both paths write the same stop.* state.
CHECKLIST_KEYS = [
    "addressed_prompt", "logical", "claims_verified", "did_what_i_said",
    "work_finished", "errors_handled",              # quality (yes = healthy)
    "asking_needless_question", "want_to_revisit",   # reflection
    "more_work_now", "waiting_on", "told_to_stop",   # end / continue
    "want_break", "want_switch",                     # preference
    "start_next_now", "schedule_next_min",           # what's next
    "note_to_user", "note_to_hamilton",              # notify
]
_CHECKLIST_BOOL_KEYS = {
    "addressed_prompt", "logical", "claims_verified", "did_what_i_said",
    "work_finished", "errors_handled", "asking_needless_question",
    "want_to_revisit", "more_work_now", "told_to_stop",
    "want_break", "want_switch", "start_next_now",
}
_CHECKLIST_TEXT_KEYS = {"waiting_on", "note_to_user", "note_to_hamilton"}


def _validate_checklist(cl):
    """Validate the complete checklist contract and return a shallow copy."""
    if not isinstance(cl, dict):
        raise ValueError("declare_stop: checklist must be an object")
    missing = [key for key in CHECKLIST_KEYS if key not in cl]
    if missing:
        raise ValueError(
            "declare_stop: checklist is missing required field(s): %s"
            % ", ".join(missing)
        )
    extra = sorted(set(cl) - set(CHECKLIST_KEYS))
    if extra:
        raise ValueError(
            "declare_stop: checklist has unknown field(s): %s" % ", ".join(extra)
        )
    wrong_bools = sorted(
        key for key in _CHECKLIST_BOOL_KEYS if type(cl[key]) is not bool
    )
    if wrong_bools:
        raise ValueError(
            "declare_stop: checklist field(s) must be boolean: %s"
            % ", ".join(wrong_bools)
        )
    wrong_text = sorted(
        key for key in _CHECKLIST_TEXT_KEYS if not isinstance(cl[key], str)
    )
    if wrong_text:
        raise ValueError(
            "declare_stop: checklist field(s) must be strings: %s"
            % ", ".join(wrong_text)
        )
    sched = cl["schedule_next_min"]
    if type(sched) is not int or sched < 0:
        raise ValueError(
            "declare_stop: checklist schedule_next_min must be an integer >= 0"
        )
    return dict(cl)


def _checklist_decide(cl):
    """Derive (decision, next, board_status, effects) from the checklist answers."""
    waiting = bool(cl["waiting_on"].strip())
    # want_to_revisit → continue, so the session can re-think/revise instead of ending.
    cont = ((cl["more_work_now"] or cl["want_to_revisit"]) and not cl["told_to_stop"]
            and not cl["want_break"] and not waiting)
    sched = cl["schedule_next_min"]
    decision = "continue" if cont else "end"
    if cont or cl["start_next_now"]:
        nxt = "now"
    elif sched > 0:
        nxt = "in %dm" % sched
    else:
        nxt = "await_user"
    if waiting:
        board = "waiting"
    elif cl["want_break"]:
        board = "paused"
    elif cl["told_to_stop"]:
        board = "parked"
    elif cl["note_to_user"].strip():
        board = "wants_discussion"
    elif cont or cl["want_switch"]:
        board = "active"
    else:
        board = "idle"
    effects = []
    if sched > 0:
        effects.append({"effect": "schedule_wake", "after_min": sched})
    if cl["note_to_user"].strip():
        effects.append({"effect": "note_user"})
    if cl["note_to_hamilton"].strip():
        effects.append({"effect": "note_hamilton"})
    if cl["want_switch"]:
        effects.append({"effect": "flag_human", "reason": "want_switch"})
    if cl["asking_needless_question"]:
        effects.append({"effect": "flag_human", "reason": "asking_needless_question"})
    return decision, nxt, board, effects


def _declare_via_checklist(cl, note, session_dir, tracking_id):
    """Record a checklist declaration + return a terse result. Shares the write
    bridge with the legacy path; increments the same stop.declare_count so the
    Stop gate sees it as a declaration."""
    now = datetime.now().isoformat()
    decision, nxt, board, effects = _checklist_decide(cl)
    payload = {"checklist": cl, "note": (note or "").strip()}
    _hook_common = Path(__file__).resolve().parents[2] / "data" / "hooks" / "common"
    if str(_hook_common) not in sys.path:
        sys.path.insert(0, str(_hook_common))
    from uai_toolkit.hooks.common.lib_session_state_union import read_union, write_session_state
    state = read_union(session_dir, tracking_id)
    updates = {
        "stop.declared_at": now,
        "stop.checklist": json.dumps(cl),
        "stop.payload": json.dumps(payload),
        "stop.block_streak": 0,
        "stop.board_status": board,
        "stop.pending_effects": json.dumps(effects),
        "stop.declare_count": int(state.get("stop.declare_count") or 0) + 1,
        "updated_at": now,
    }
    if not write_session_state(session_dir, tracking_id, updates):
        raise RuntimeError("declare_stop: could not write session state for %s" % tracking_id)
    return {"ok": True, "decision": decision, "next": nxt, "board_status": board}


def declare_stop(reasons=None, params=None, note=None, checklist=None):
    """Record a stop declaration into session state. Returns a result dict.

    reasons: list of taxonomy reason IDs (may be empty for a note-only custom stop)
    params:  dict of per-reason parameters (passed through; not hard-validated in P1)
    note:    optional free-text (always allowed; required if `reasons` is empty)
    """
    if isinstance(reasons, str):        # tolerate a single reason passed bare
        reasons = [reasons]
    reasons = list(reasons or [])
    params = dict(params or {})
    note = (note or "").strip()

    session_dir = os.environ.get("AI_SESSION_DIR", "")
    tracking_id = os.environ.get("AI_TRACKING_ID", "")
    if not session_dir or not tracking_id:
        raise RuntimeError(
            "declare_stop: AI_SESSION_DIR and AI_TRACKING_ID must be set "
            "(they identify the session state file to update)."
        )

    # Checklist path (todo_0520, phased in): if the session handed in the yes/no
    # turn-review, record it and return a terse decision. Legacy reason path below.
    if checklist is not None:
        return _declare_via_checklist(
            _validate_checklist(checklist), note, session_dir, tracking_id
        )

    _cfg, reasons_by_id = _load_config()

    # Validate: known reason IDs only. A note-only declaration (no reasons) is a
    # valid custom stop. An unknown reason ID is a typo, not a custom reason —
    # surface it rather than silently record garbage.
    unknown = [r for r in reasons if r not in reasons_by_id]
    if unknown:
        raise ValueError(
            f"declare_stop: unknown reason id(s): {', '.join(unknown)}. "
            f"Known: {', '.join(sorted(reasons_by_id))}. "
            f"For a reason not in the taxonomy, pass no reasons and use `note`."
        )
    if not reasons and not note:
        raise ValueError(
            "declare_stop: provide at least one reason id, or a free-text note."
        )

    now = datetime.now().isoformat()
    payload = {"reasons": reasons, "params": params, "note": note}
    board_status = _board_status(reasons, reasons_by_id)
    pending = _pending_effects(reasons, reasons_by_id)

    # Read current state (for the declare_count increment) + write through the
    # shared bridge (todo_0495): enrolled sessions use the locked canonical
    # accessor, everyone else the legacy file. declare_stop is single-caller per
    # stop, so the read-then-write is not a concurrency concern.
    _hook_common = Path(__file__).resolve().parents[2] / "data" / "hooks" / "common"
    if str(_hook_common) not in sys.path:
        sys.path.insert(0, str(_hook_common))
    from uai_toolkit.hooks.common.lib_session_state_union import read_union, write_session_state

    state = read_union(session_dir, tracking_id)
    updates = {
        "stop.declared_at": now,
        "stop.payload": json.dumps(payload),
        "stop.block_streak": 0,            # valid declaration clears the valve
        "stop.board_status": board_status,
        "stop.pending_effects": json.dumps(pending),
        # Monotonic declaration counter (consume-on-stop, counter NOT a flag). The
        # Stop gate acks UP TO the count it observes; "declared this turn" ==
        # declare_count > ack_count. A counter beats a boolean because the gate's
        # consume only acks the count it saw — a declaration that races in during
        # the consume stays unacked (not lost), whereas a blind flag-clear would
        # clobber it. No turn-start stamp or clock comparison needed.
        "stop.declare_count": int(state.get("stop.declare_count") or 0) + 1,
        "updated_at": now,
    }
    if not write_session_state(session_dir, tracking_id, updates):
        raise RuntimeError(f"declare_stop: could not write session state for {tracking_id}")

    # Whether this declaration wants the turn to continue (self-continuation):
    # the Stop handler enforces it, but we surface it in the result for clarity.
    wants_continue = any(
        reasons_by_id.get(r, {}).get("control") == "block_continue" for r in reasons
    )
    return {
        "ok": True,
        "declared_at": now,
        "reasons": reasons,
        "board_status": board_status,
        "pending_effects": pending,
        "wants_continue": wants_continue,
        "note": note,
    }


def _parse_params(pairs):
    """Turn ['k=v', ...] into {k: v} for CLI testing."""
    out = {}
    for p in pairs or []:
        if "=" not in p:
            raise ValueError(f"declare_stop: --param must be key=value, got: {p}")
        k, v = p.split("=", 1)
        out[k.strip()] = v
    return out


def main():
    ap = argparse.ArgumentParser(description="Declare why this turn is ending.")
    ap.add_argument("--reasons", default="", help="comma-separated reason ids")
    ap.add_argument("--param", action="append", default=[], help="key=value (repeatable)")
    ap.add_argument("--note", default="", help="free-text note")
    ap.add_argument("--stdin", action="store_true",
                    help="read a JSON payload {reasons, params, note} from stdin "
                         "(how the declare_stop MCP tool passes structured args)")
    args = ap.parse_args()

    try:
        if args.stdin:
            payload = json.loads(sys.stdin.read() or "{}")
            reasons = payload.get("reasons") or []
            params = payload.get("params") or {}
            note = payload.get("note") or ""
            checklist = payload.get("checklist")   # None unless the caller sent one
        else:
            reasons = [r.strip() for r in args.reasons.split(",") if r.strip()]
            params = _parse_params(args.param)
            note = args.note
            checklist = None
        result = declare_stop(reasons=reasons, params=params, note=note, checklist=checklist)
    except (RuntimeError, ValueError, json.JSONDecodeError) as e:
        sys.stderr.write(str(e) + "\n")
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
