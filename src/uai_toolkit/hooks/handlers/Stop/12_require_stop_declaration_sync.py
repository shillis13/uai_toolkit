#!/usr/bin/env python3
"""Stop hook — require a declare_stop declaration this turn (declarative stop-gate).

todo_0520. The structured replacement for the heuristic stop-checkers
(02_block_permission_seeking / 03_quality_gate / 05_intent_without_action /
06_todo_audit enforcement): instead of guessing at turn quality from output text,
the session must positively DECLARE why it is stopping by calling the declare_stop
tool, which increments a monotonic counter (stop.declare_count). This handler acks
UP TO the count it observes (stop.ack_count) on the stop it authorizes, so
"declared this turn" == declare_count > ack_count. Counter not flag: acking only
the observed count means a declaration that races in during the consume stays
unacked (not lost), where a blind boolean-clear would clobber it. No turn-start
stamp or clock comparison needed. Acts by MODE:

  observe (default) : record only; never nudge or block   (SAFE — current phase)
  warn              : + a non-blocking systemMessage nudge when undeclared
  block             : NOT YET wired. P3 adds the 3-strike valve + PianoMan/Hamilton
                      escalation. Until then block FAILS SAFE — it logs + nudges
                      but never exits 2 — so a premature mode flip cannot deadlock
                      the fleet (a Stop gate that blocks with no valve would wedge
                      every turn). This is deliberate, not a stub oversight.

Mode source: Stop/declare_stop.config.yml `mode`, overridable per session via
state `stop_gate.mode`. Per-session opt-out is dispatcher-level (Stop/exclusions.yml
under `require_stop_declaration`). Every turn is logged to data/work/stop_gate.jsonl
for the observe/calibration pass (the base-rate data that gates any move to block).
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
CONFIG_PATH = Path(__file__).resolve().parent / "stop_gate.config.yml"
LOG_PATH = AI_ROOT / "ai_general" / "data" / "work" / "stop_gate.jsonl"


def _config_mode():
    """(mode, max_consecutive_blocks) from the taxonomy config; safe defaults."""
    try:
        import yaml
    except ImportError:
        return "observe", 3
    try:
        cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except (OSError, Exception):
        return "observe", 3
    return cfg.get("mode", "observe"), int(cfg.get("max_consecutive_blocks", 3))


def _log(entry):
    # Best-effort append. data/work/ already exists (todo_audit writes there); we do
    # NOT create it — a missing dir is a real signal, not something to paper over.
    try:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _write_state(state_path, state):
    try:
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(state_path)
    except OSError:
        pass


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")

    state_path = Path(context.session_dir) / f"{context.tracking_id}_state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            state = {}

    mode, _max_blocks = _config_mode()
    mode = state.get("stop_gate.mode", mode)          # per-session override

    # "Declared this turn" == there is an unacked declaration (counter, not flag).
    declare_count = int(state.get("stop.declare_count") or 0)
    acked = int(state.get("stop.ack_count") or 0)
    declared = declare_count > acked

    reasons = []
    if declared:
        try:
            payload = json.loads(state.get("stop.payload") or "{}")
            reasons = payload.get("reasons", []) if isinstance(payload, dict) else []
        except (json.JSONDecodeError, TypeError):
            reasons = []

    _log({
        "ts": datetime.now().isoformat(),
        "tracking_id": context.tracking_id,
        "mode": mode,
        "declared": declared,
        "reasons": reasons,
    })

    if declared:
        # Ack exactly the count we observed, authorizing this stop. A declaration
        # that arrives after this read keeps declare_count > ack_count, so it is
        # not lost — it counts for the next stop.
        state["stop.ack_count"] = declare_count
        state["updated_at"] = datetime.now().isoformat()
        _write_state(state_path, state)
        return HookResult.allow(f"declared: {','.join(reasons) or 'note-only'}")

    if mode == "observe":
        return HookResult.allow("observe: undeclared (not enforced)")

    # warn, or block-before-P3: non-blocking nudge only. NEVER exit 2 yet.
    nudge = (
        "Before ending your turn, call the declare_stop tool to record WHY you are "
        "stopping — one or more reason ids from the taxonomy (plus an optional note)."
    )
    if mode == "block":
        nudge += " [block mode is requested but enforcement is not yet wired (P3); not blocking.]"
    return HookResult.output(json.dumps({"systemMessage": nudge}), f"{mode}: undeclared nudge")


if __name__ == "__main__":
    sys.exit(run_hook("require_stop_declaration", "Stop", handler))
