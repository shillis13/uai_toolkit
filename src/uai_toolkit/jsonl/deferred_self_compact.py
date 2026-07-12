#!/usr/bin/env python3
"""deferred_self_compact.py <tracking_id>

Fire body of the idle-gated self-compact one-shot timer. It is run by a
self-destructing launchd one-shot (scheduled_task_mgr.py once --remove), armed
when a session crosses its context threshold. On each fire it decides ONE of:

  STOP       — nothing to do: a compact/brief is already in flight this cycle,
               the session is now below threshold, or the session is gone.
  RESCHEDULE — the session is still active: arm another one-shot in 5 min.
  TRIGGER    — the session has been idle >= 5 min: deliver the compact instruction
               (self-write if there's room, else a subagent), then stop.

A hook/script cannot run an AI, so "trigger" DELIVERS A PROMPT the session acts on.
Delivery is refused unless the session is verifiably idle right before the send.
This script does not parse JSONL — condensation is delegated to condense.py.

Design: work/projects/briefing_redesign/deferred-self-compact-trigger.md
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

_AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI" / "ai_root"))
_GEN = _AI_ROOT / "ai_general"
_SESSION_MGMT = _GEN / "scripts" / "session_mgmt"
_PROMPTING = _GEN / "scripts" / "prompting"
_SCHED_MGR = _GEN / "scripts" / "scheduling" / "scheduled_task_mgr.py"
_SELF = _GEN / "scripts" / "jsonl" / "deferred_self_compact.py"
_SEND_PROMPT = _PROMPTING / "send_prompt.py"
_PROMPT_FILE = _GEN / "ai_context_files" / "instructions" / "how_tos" / "instr_operational_handoff.md"
for _d in (_SESSION_MGMT, _PROMPTING):
    if str(_d) not in sys.path:
        sys.path.insert(0, str(_d))

IDLE_MIN_S = 300              # idle >= 5 min before triggering
RESCHEDULE_IN = "5m"
DEFAULT_THRESHOLD = 85
SELF_WRITE_MIN_REMAINING = 10  # >= this % room -> self-write; else subagent
_PLATFORM_TARGET = {"claude_cli": "claude-cli", "codex_cli": "codex-cli", "gemini_cli": "gemini-cli"}


def _log(msg: str) -> None:
    print(f"[deferred_self_compact] {msg}", file=sys.stderr)


def _read_state(session_dir: str, tid: str) -> dict:
    p = Path(session_dir) / f"{tid}_state.json"
    try:
        return json.loads(p.read_text()) if p.exists() else {}
    except (OSError, ValueError):
        return {}


def _write_state(session_dir: str, tid: str, state: dict) -> None:
    p = Path(session_dir) / f"{tid}_state.json"
    try:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(p)
    except OSError:
        pass


def _set_deferred(session_dir: str, tid: str, **kw) -> None:
    """Merge fields into compact.deferred and persist."""
    state = _read_state(session_dir, tid)
    d = state.get("compact.deferred") or {}
    if not isinstance(d, dict):
        d = {}
    d.update(kw)
    state["compact.deferred"] = d
    state["updated_at"] = _dt.datetime.now().isoformat()
    _write_state(session_dir, tid, state)


def _activity_idle_secs(session_dir: str):
    """Seconds since the session went idle per activity_state.json, or None if it
    is not cleanly idle (busy / missing / unparseable) — 'not safely idle'."""
    p = Path(session_dir) / "activity_state.json"
    if not p.exists():
        return None
    try:
        d = json.loads(p.read_text())
    except (OSError, ValueError):
        return None
    if d.get("state") != "idle":
        return None
    at = d.get("at")
    if not at:
        return None
    try:
        t = _dt.datetime.fromisoformat(at)
        now = _dt.datetime.now(t.tzinfo) if t.tzinfo else _dt.datetime.now()
        return max(0.0, (now - t).total_seconds())
    except (ValueError, TypeError):
        return None


def _reschedule(tid: str) -> None:
    """Arm another one-shot in 5 min. Deterministic id -> replaces, never dups."""
    log = _GEN / "logs" / "oneshot" / f"compact_deferred_{tid}.log"
    try:
        subprocess.run(
            [sys.executable, str(_SCHED_MGR), "once", "--in", RESCHEDULE_IN,
             "--id", f"compact_deferred_{tid}",
             "--command", f'python3 "{_SELF}" {tid}',
             "--remove", "--log", str(log)],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as e:
        _log(f"reschedule failed: {e}")


def cancel(tid: str) -> None:
    """Cancel the deferred one-shot for this session (below-threshold / cleanup)."""
    try:
        subprocess.run(
            [sys.executable, str(_SCHED_MGR), "once", "--cancel", f"compact_deferred_{tid}"],
            capture_output=True, text=True, timeout=30,
        )
    except (subprocess.SubprocessError, OSError) as e:
        _log(f"cancel failed: {e}")


# Public alias — arming and rescheduling are the same op (deterministic id replaces).
arm = _reschedule


def sweep_orphans() -> str:
    """Cancel compact_deferred one-shots whose session is gone/inactive — a session
    can die while a timer is armed. Called opportunistically (e.g. from SessionStart).
    Bounded (only compact_deferred.* one-shots). Returns a summary string."""
    import re
    try:
        r = subprocess.run(
            [sys.executable, str(_SCHED_MGR), "once", "--list"],
            capture_output=True, text=True, timeout=30,
        )
        listing = r.stdout or ""
    except (subprocess.SubprocessError, OSError) as e:
        return f"sweep: list failed: {e}"
    tids = set(re.findall(r"compact_deferred_(\S+)", listing))
    if not tids:
        return "sweep: no deferred one-shots"
    try:
        from uai_toolkit.session_mgmt.session_store import SessionStore
        store = SessionStore()
    except Exception as e:
        return f"sweep: store unavailable: {e}"
    dead = 0
    for tid in tids:
        try:
            sess = store.resolve(tid)
        except Exception:
            sess = None
        status = str((sess or {}).get("status", "")).lower()
        if not sess or status in ("exited", "ended", "archived", "deleted"):
            cancel(tid)
            dead += 1
    return f"sweep: {dead}/{len(tids)} orphan one-shot(s) cancelled"


def reconcile_from_stop(session_dir: str, tid: str, ctx_pct, threshold: int) -> str:
    """Called by the Stop hook each response. Arms the one-shot when a session is
    at/over threshold (once — no launchd churn while armed), cancels it when it
    drops below, and re-arms a trigger that was delivered but clearly ignored.
    Touches launchd ONLY on transitions. Returns a short status string for the log."""
    state = _read_state(session_dir, tid)
    d = state.get("compact.deferred") or {}
    if not isinstance(d, dict):
        d = {}
    dstate = d.get("state", "none")

    if ctx_pct is not None and ctx_pct >= threshold:
        if dstate == "armed":
            return "deferred: already armed"
        if dstate == "triggered":
            # A compact instruction was delivered. Leave it, unless it clearly never
            # took: no compact in flight AND delivered > 10 min ago -> re-arm.
            if state.get("compact.self") or state.get("compact.self_triggered"):
                return "deferred: triggered, compact in flight"
            ta = d.get("triggered_at")
            recent = False
            if ta:
                try:
                    recent = (_dt.datetime.now() - _dt.datetime.fromisoformat(ta)).total_seconds() < 600
                except (ValueError, TypeError):
                    recent = False
            if recent:
                return "deferred: triggered, awaiting compact"
            arm(tid)
            _set_deferred(session_dir, tid, state="armed", armed_at=_dt.datetime.now().isoformat())
            return "deferred: re-armed (prior trigger ignored)"
        # none / unknown -> arm once
        arm(tid)
        _set_deferred(session_dir, tid, state="armed", armed_at=_dt.datetime.now().isoformat())
        return "deferred: armed"

    # below threshold
    if dstate == "armed":
        cancel(tid)
        _set_deferred(session_dir, tid, state="none")
        return "deferred: cancelled (below threshold)"
    return "deferred: idle"


def _live_idle(target: str, terminal: str) -> bool:
    """Double-checked live idle recheck right before delivery (Codex #2)."""
    if not target or not terminal:
        return False
    try:
        from uai_toolkit.prompting.lib_send_prompt import is_busy_cli
        return not is_busy_cli(target, terminal, double_check=True)
    except Exception as e:
        _log(f"live idle check failed -> treat as busy: {e}")
        return False


def _build_instruction(tid: str, ctx_pct, session_dir: str, token: str) -> str:
    """The compact instruction body — self-write if there's room, else subagent."""
    remaining = (100 - ctx_pct) if isinstance(ctx_pct, int) else 0
    brief_path = _GEN / "data" / "session_briefs" / "auto_briefs" / f"{tid}.yml"
    if remaining >= SELF_WRITE_MIN_REMAINING:
        return (
            f"You've been idle a while and your context is at {ctx_pct}% ({remaining}% room). "
            f"Write your handoff brief now, then compact — do these steps yourself (do NOT invoke "
            f"the /self-compact skill):\n"
            f"  1. Write your session brief from your current context (follow the operational_handoff "
            f"procedure) to {brief_path}.\n"
            f"  2. Register it: python3 {_GEN}/scripts/session_mgmt/register_self_brief.py {brief_path}\n"
            f"  3. Compact: comms_send_slash_command(identifier=\"self\", command=\"/compact\", "
            f"authorization_token=\"{token}\")"
        )
    return (
        f"You've been idle a while and your context is at {ctx_pct}% — only {remaining}% room, too tight "
        f"to write a brief yourself safely. Use a subagent (it reads the transcript from disk):\n"
        f"  1. Spawn a Task subagent to run: python3 {_GEN}/scripts/jsonl/condense.py --src-uuid "
        f"\"$AI_CLI_SESSION_ID\" --interval live --prepare-only --output /tmp/selfbrief_src.json\n"
        f"  2. Have it read /tmp/selfbrief_src.json + {_PROMPT_FILE}, then write a YAML brief to {brief_path} "
        f"(confirm it parses with yaml.safe_load).\n"
        f"  3. Register it: python3 {_GEN}/scripts/session_mgmt/register_self_brief.py {brief_path}\n"
        f"  4. Then compact: comms_send_slash_command(identifier=\"self\", command=\"/compact\", "
        f"authorization_token=\"{token}\")"
    )


def _deliver(target: str, terminal: str, message: str) -> bool:
    """Send the compact instruction; queue (don't interrupt) if busy at send time."""
    if not _SEND_PROMPT.exists():
        _log("send_prompt.py missing")
        return False
    endpoint = f"prompt://{target}/{terminal}?submit=true"
    try:
        r = subprocess.run(
            [sys.executable, str(_SEND_PROMPT), "--endpoint", endpoint, "--message", message, "--fb_queue"],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except (subprocess.SubprocessError, OSError) as e:
        _log(f"deliver failed: {e}")
        return False


_USAGE = """\
deferred_self_compact.py — fire body of the idle-gated self-compact one-shot

WHAT IT DOES
  The terminal, LOSSY rung of the context-reclaim ladder (Offload < Bounce < Summarize
  < self-compact < compact). This is the deferred one-shot that ARMS and FIRES a
  /self-compact directive for a session — the ONLY deliberate, model-facing prompt in
  the whole ladder (every other rung is silent disk surgery). It is run by a
  self-destructing launchd one-shot (scheduled_task_mgr.py `once --remove`), armed when
  a session crosses its context threshold, and re-armed on each Stop hook while still
  over threshold.

  On each fire it decides exactly ONE of:
    STOP        — nothing to do: a compact/brief is already in flight this cycle, the
                  session dropped below threshold, or the session is gone.
    RESCHEDULE  — the session is over threshold but not idle >= 5 min (or went busy on
                  the live recheck, or token mint failed): arm another one-shot in 5m.
    TRIGGER     — over threshold AND idle >= 5 min AND verifiably idle at send time:
                  DELIVER the compact instruction as a prompt the session acts on, then
                  stop. A hook/script can't run an AI, so it hands the model a prompt.

  Delivery self-writes the brief when there's >= 10% context room, else routes through
  a subagent that reads the transcript from disk. This script does NOT parse JSONL;
  condensation is delegated to condense.py.

USAGE
  deferred_self_compact.py <tracking_id>
  deferred_self_compact.py -h | --help

POSITIONAL ARGS
  <tracking_id>   the session to service, as a tracking id
                  (YYYYMMDD_HHMMSS_uuid8_plat3). Resolved via SessionStore to find the
                  session dir, platform, and terminal. If it doesn't resolve, the fire
                  is a no-op (STOP) — the launchd plist has already self-removed.

EXAMPLES
  # Show rich help:
  deferred_self_compact.py --help
  deferred_self_compact.py -h

  # Fire the deferred check for one session (normally invoked by the launchd one-shot):
  deferred_self_compact.py 20260705_120000_abcd1234_cla

CAVEATS
  * TERMINAL, LOSSY rung — a self-compact is a whole-context summary with NO bring-back.
    It is the last resort AFTER lossless/reversible rungs (offload, bounce, summarize)
    have been exhausted; it fires only under sustained context pressure + idleness.
  * Fail-CLOSED on idleness: it refuses to TRIGGER unless the session is cleanly idle
    per activity_state.json AND a live double-check right before the send agrees — a
    busy/missing/unparseable activity state reschedules rather than interrupts.
  * Exit codes: 0 for every normal outcome (STOP / RESCHEDULE / TRIGGER — the plist is
    one-shot). The only nonzero path is the original usage error; --help returns 0.
  * Diagnostics go to STDERR prefixed [deferred_self_compact]; delivery uses send_prompt
    with --fb_queue so it QUEUES rather than interrupting if the session is mid-turn.

"""

def main() -> int:
    if not sys.argv[1:] or sys.argv[1] in ("-h", "--help"):
        print(_USAGE)
        return 0
    if len(sys.argv) < 2:
        _log("usage: deferred_self_compact.py <tracking_id>")
        return 2
    tid = sys.argv[1].strip()

    try:
        from uai_toolkit.session_mgmt.session_store import SessionStore
        sess = SessionStore().resolve(tid)
    except Exception as e:
        _log(f"store resolve failed: {e}")
        return 0  # can't resolve -> nothing to do; plist already self-removed
    if not sess:
        _log(f"session not found: {tid} -> STOP")
        return 0

    session_dir = sess.get("session_dir")
    if not session_dir or not Path(session_dir).is_dir():
        _log("no session_dir -> STOP")
        return 0
    platform = sess.get("platform", "")
    target = _PLATFORM_TARGET.get(platform)
    terminal = sess.get("terminal_session") or tid
    state = _read_state(session_dir, tid)

    # --- STOP conditions -----------------------------------------------------
    # A compact/brief is already in flight THIS cycle (register_self_brief sets
    # compact.self; the auto path sets compact.self_triggered). Using the cycle
    # flags — NOT brief-file existence — avoids mistaking a stale prior brief as
    # fresh (Codex #5).
    if state.get("compact.self") or state.get("compact.self_triggered"):
        _log("compact already in flight this cycle -> STOP")
        _set_deferred(session_dir, tid, state="none")
        return 0

    threshold = state.get("compact.auto_self_pct", DEFAULT_THRESHOLD)
    try:
        threshold = int(threshold)
    except (ValueError, TypeError):
        threshold = DEFAULT_THRESHOLD
    ctx_pct = state.get("context.used_pct")
    try:
        ctx_pct = int(ctx_pct)
    except (ValueError, TypeError):
        ctx_pct = None
    if ctx_pct is None or ctx_pct < threshold:
        _log(f"ctx {ctx_pct} < threshold {threshold} (or unknown) -> STOP")
        _set_deferred(session_dir, tid, state="none")
        return 0

    if str(sess.get("status", "")).lower() in ("exited", "ended", "archived", "deleted"):
        _log(f"session status {sess.get('status')} -> STOP")
        _set_deferred(session_dir, tid, state="none")
        return 0

    # --- Idle gate -----------------------------------------------------------
    idle = _activity_idle_secs(session_dir)
    if idle is None or idle < IDLE_MIN_S:
        _log(f"idle={idle}s < {IDLE_MIN_S}s (or not cleanly idle) -> RESCHEDULE")
        _reschedule(tid)
        _set_deferred(session_dir, tid, state="armed")
        return 0

    # Live recheck immediately before delivery — refuse if it went active.
    if not _live_idle(target, terminal):
        _log("live recheck says busy -> RESCHEDULE")
        _reschedule(tid)
        _set_deferred(session_dir, tid, state="armed")
        return 0

    # --- TRIGGER -------------------------------------------------------------
    try:
        from uai_toolkit.session_mgmt import compact_auth
        token = compact_auth.mint(session_dir, "deferred_self_compact")
    except Exception as e:
        _log(f"token mint failed -> RESCHEDULE: {e}")
        _reschedule(tid)
        _set_deferred(session_dir, tid, state="armed")
        return 0
    if not token:
        _log("token mint returned None -> RESCHEDULE")
        _reschedule(tid)
        _set_deferred(session_dir, tid, state="armed")
        return 0

    msg = _build_instruction(tid, ctx_pct, session_dir, token)
    if _deliver(target, terminal, msg):
        _log(f"delivered compact instruction (ctx {ctx_pct}%) -> TRIGGERED")
        _set_deferred(session_dir, tid, state="triggered",
                      triggered_at=_dt.datetime.now().isoformat())
    else:
        _log("delivery failed -> RESCHEDULE")
        _reschedule(tid)
        _set_deferred(session_dir, tid, state="armed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
