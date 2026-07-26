#!/usr/bin/env python3
"""Stop hook — require a declare_stop declaration this turn (declarative stop-gate).

todo_0520. The structured replacement for the heuristic stop-checkers
(02_block_permission_seeking / 03_quality_gate / 05_intent_without_action /
06_todo_audit enforcement): instead of guessing at turn quality from output text,
the session must positively DECLARE why it is stopping by calling the declare_stop
tool. That increments a monotonic counter (stop.declare_count); this handler acks
UP TO the count it observes (stop.ack_count) on the stop it authorizes, so
"declared this turn" == declare_count > ack_count (counter, not a flag — a
declaration that races in during the consume stays unacked, not lost).

Two orthogonal toggles (stop_gate.config.yml; per-session overrides
stop_gate.is_silent / stop_gate.observe_only in session state):
  is_silent    : true  = never write a nudge (pure log)
                 false = nudge the session on an undeclared stop
  observe_only : true  = never block (log/nudge + allow)
                 false = ENFORCE — block an undeclared stop (exit 2) until the
                         3-strike valve releases it

3-strike valve (enforcing only): after `max_consecutive_blocks` undeclared blocks,
escalate (feed + escalations log, recipients from `escalate_to`) and RELEASE the
stop — a session can never be trapped by the gate.

Per-session opt-out is dispatcher-level (Stop/exclusions.yml under
`require_stop_declaration`) — Codex sessions are excluded there until their MCP
servers carry session identity (todo_0523). Every turn is logged to
data/work/stop_gate.jsonl.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common.lib_session_state_union import read_union, write_session_state   # session-state bridge (todo_0495)

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
CONFIG_PATH = Path(__file__).resolve().parent / "stop_gate.config.yml"
LOG_PATH = AI_ROOT / "ai_general" / "data" / "work" / "stop_gate.jsonl"
ESCALATION_LOG = AI_ROOT / "ai_general" / "data" / "work" / "stop_gate_escalations.jsonl"

_NUDGE = (
    "Before ending your turn you must call the declare_stop tool "
    "(mcp__sessions__declare_stop) to record WHY you are stopping — one or more "
    "reason ids from the taxonomy (e.g. awaiting_user, finished_todo, more_work, "
    "blocked, waiting_on, need_decision, break, discuss_soonest) and/or a free-text "
    "note. Call it now, then end your turn again."
)


def _config():
    """(is_silent, observe_only, max_blocks, escalate_to) from config; safe defaults."""
    try:
        import yaml
    except ImportError:
        return True, True, 3, ["PianoMan", "Hamilton"]
    try:
        cfg = yaml.safe_load(CONFIG_PATH.read_text()) or {}
    except Exception:
        return True, True, 3, ["PianoMan", "Hamilton"]
    return (
        bool(cfg.get("is_silent", True)),
        bool(cfg.get("observe_only", True)),
        int(cfg.get("max_consecutive_blocks", 3)),
        cfg.get("escalate_to") or ["PianoMan", "Hamilton"],
    )


def _log(entry):
    try:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass


def _escalate(tracking_id, streak, recipients):
    """Valve tripped: record + announce that the gate released a stuck session.
    Best-effort and never raises — the release must happen regardless."""
    try:
        with open(ESCALATION_LOG, "a") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(),
                "tracking_id": tracking_id,
                "consecutive_undeclared": streak,
                "escalate_to": recipients,
            }) + "\n")
    except OSError:
        pass
    try:
        msg = (f"stop-gate: released {tracking_id} after {streak} consecutive "
               f"undeclared stops (attn {', '.join(recipients)}). It is not calling "
               f"declare_stop — please check in.")
        subprocess.run(["feed", "post", msg], timeout=10,
                       capture_output=True, cwd=str(AI_ROOT))
    except Exception:
        pass


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")

    # Enforce only where declare_stop PROVABLY works — the caller's MCP server must
    # carry session identity. Verified for Claude; Codex MCP servers get a stripped
    # env (todo_0523) so declare_stop fails, and other platforms are unverified.
    # So gate claude_cli ONLY and skip the rest — a session that structurally can't
    # declare must never be blockstormed. (Hooks carry AI_SESSION_PLATFORM even on
    # platforms whose MCP servers don't; skip is fail-safe if it's somehow unset.)
    if os.environ.get("AI_SESSION_PLATFORM") != "claude_cli":
        return HookResult.skip(
            f"gate is claude-only for now (platform={os.environ.get('AI_SESSION_PLATFORM') or '?'})")

    # Union read (sees state in the legacy file or, for enrolled sessions, the
    # canonical accessor); writes below are TARGETED via the bridge — never the
    # whole `state` dict, which would copy canonical keys into legacy (todo_0495).
    state = read_union(context.session_dir, context.tracking_id)

    is_silent, observe_only, max_blocks, escalate_to = _config()
    # per-session overrides
    if "stop_gate.is_silent" in state:
        is_silent = bool(state["stop_gate.is_silent"])
    if "stop_gate.observe_only" in state:
        observe_only = bool(state["stop_gate.observe_only"])

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
        "is_silent": is_silent,
        "observe_only": observe_only,
        "declared": declared,
        "reasons": reasons,
    })

    if declared:
        # Ack the observed count and clear the streak — this stop is authorized.
        write_session_state(context.session_dir, context.tracking_id, {
            "stop.ack_count": declare_count,
            "stop.block_streak": 0,
            "updated_at": datetime.now().isoformat(),
        })
        return HookResult.allow(f"declared: {','.join(reasons) or 'note-only'}")

    # ── Undeclared ────────────────────────────────────────────────────────────
    if observe_only:
        # Never block. Nudge unless silent.
        if is_silent:
            return HookResult.allow("observe_only+silent: undeclared")
        return HookResult.output(json.dumps({"systemMessage": _NUDGE}),
                                 "observe_only: undeclared nudge")

    # Enforcing: block until the 3-strike valve releases.
    streak = int(state.get("stop.block_streak") or 0) + 1
    write_session_state(context.session_dir, context.tracking_id, {
        "stop.block_streak": streak,
        "updated_at": datetime.now().isoformat(),
    })

    if streak > max_blocks:
        # Valve: escalate + RELEASE (reset streak, allow the stop through).
        _escalate(context.tracking_id, streak, escalate_to)
        write_session_state(context.session_dir, context.tracking_id,
                            {"stop.block_streak": 0})
        released = _NUDGE + (f" [Gate released after {streak} undeclared stops; "
                             f"{', '.join(escalate_to)} notified.]")
        return HookResult.output(json.dumps({"systemMessage": released}),
                                 f"valve released after {streak}")

    # Block this stop (exit 2 forces a retry turn with the nudge).
    return HookResult.block(_NUDGE, f"undeclared stop blocked (strike {streak}/{max_blocks})")


if __name__ == "__main__":
    sys.exit(run_hook("require_stop_declaration", "Stop", handler))
