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


def declare_stop(reasons=None, params=None, note=None):
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

    state_path = Path(session_dir) / f"{tracking_id}_state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError) as e:
            raise RuntimeError(f"declare_stop: could not read state {state_path}: {e}")

    state["stop.declared_at"] = now
    state["stop.payload"] = json.dumps(payload)
    state["stop.block_streak"] = 0            # valid declaration clears the valve
    state["stop.board_status"] = board_status
    state["stop.pending_effects"] = json.dumps(pending)
    # Monotonic declaration counter (consume-on-stop, counter NOT a flag). The Stop
    # gate acks UP TO the count it observes; "declared this turn" == declare_count >
    # ack_count. A counter beats a boolean here because the gate's consume only acks
    # the count it saw — a declaration that races in during the consume stays
    # unacked (not lost), whereas a blind flag-clear would clobber it. No turn-start
    # stamp or clock comparison needed.
    state["stop.declare_count"] = int(state.get("stop.declare_count") or 0) + 1
    state["updated_at"] = now

    try:
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(state_path)
    except OSError as e:
        raise RuntimeError(f"declare_stop: could not write state {state_path}: {e}")

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
        else:
            reasons = [r.strip() for r in args.reasons.split(",") if r.strip()]
            params = _parse_params(args.param)
            note = args.note
        result = declare_stop(reasons=reasons, params=params, note=note)
    except (RuntimeError, ValueError, json.JSONDecodeError) as e:
        sys.stderr.write(str(e) + "\n")
        return 1
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
