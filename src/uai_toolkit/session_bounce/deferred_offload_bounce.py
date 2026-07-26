#!/usr/bin/env python3
"""deferred_offload_bounce.py <tid> --session-dir DIR

Idle-gated one-shot that REALIZES an accumulated offload by self-bouncing, but
only when a resume is worth it on CAPACITY grounds (fixed-rate plan: no dollars).
The lossless sibling of deferred_self_compact: offload (Stop/99) pre-stages a
leaner transcript; this cashes it in with a stop+resume when the capacity
recommendation (metrics.resume.recommend, from uai_toolkit.hooks.common.lib_offload_metrics) says so.

Armed by Stop/10_auto_bounce for a session that opted in (`bounce.auto`). On each
fire it decides ONE of:
  STOP       — opted out / bounce already scheduled / recommend fell back to hold.
  RESCHEDULE — session still active (< IDLE_MIN_S idle): arm another one-shot.
  TRIGGER    — idle >= IDLE_MIN_S AND recommend still says bounce: schedule the
               launchd `--resume` and send the session `/exit` (the self-bounce).

Self-directed: fires only for a session that opted in, so the `/exit` is that
session's OWN configured behavior — not an external actor. Lossless: the offload
already ran; the resume just reads the leaner transcript.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI" / "ai_root"))
GEN = AI_ROOT / "ai_general"
MGR = GEN / "scripts" / "scheduling" / "scheduled_task_mgr.py"
SEND_SLASH = GEN / "scripts" / "session_mgmt" / "send_slash_command.py"
SELF = GEN / "scripts" / "session_bounce" / "deferred_offload_bounce.py"
CLAUDECLI = Path.home() / "myenv" / "bin" / "claudeCli"
PY = sys.executable

IDLE_MIN_S = 300               # idle >= 5 min before bouncing (mirror self-compact)
RESCHEDULE_IN = "5m"
RESUME_IN_MIN = 2              # launchd --resume delay
# Bounce on a positive CAPACITY recommendation only — see lib_offload_metrics.estimate.
# NO cost/color tiers; this is context pressure x sheddable magnitude, not dollars.
RECOMMEND_BOUNCE = ("worth_it", "urgent")


def _log(m):
    print(f"[deferred_offload_bounce] {m}", file=sys.stderr)


def _job_id(tid):
    return f"auto_bounce_{tid}"


def _state_path(session_dir, tid):
    return Path(session_dir) / f"{tid}_state.json"


def _read_state(session_dir, tid):
    try:
        return json.loads(_state_path(session_dir, tid).read_text())
    except Exception:
        return {}


_HOOK_COMMON = GEN / "data" / "hooks" / "common"


def _read_union_state(session_dir, tid):
    """UNION read (canonical accessor file OVER the legacy hooks' file; todo_0495).
    Both config (bounce.auto / bounce.auto_recommend, may be MCP-set) and the
    runtime flags (bounce.armed / bounce.scheduled) are read through this union and
    written through `_set` (the shared bridge → locked canonical accessor for
    enrolled/flipped sessions, legacy otherwise), so reads and writes stay on the
    same store in every phase. Falls back to the legacy-only read if the shared
    helper can't be imported (launchd env) — never fails."""
    try:
        if str(_HOOK_COMMON) not in sys.path:
            sys.path.insert(0, str(_HOOK_COMMON))
        from uai_toolkit.hooks.common.lib_session_state_union import read_union
        return read_union(session_dir, tid)
    except Exception:
        return _read_state(session_dir, tid)


def _write_state(session_dir, tid, state):
    p = _state_path(session_dir, tid)
    try:
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(p)
    except OSError as e:
        _log(f"state write failed: {e}")


def _set(session_dir, tid, **kw):
    """Persist runtime flags through the shared bridge (enrolled → locked canonical
    accessor, else legacy; todo_0495). Legacy RMW fallback if the bridge can't be
    imported (launchd env) — never fails."""
    try:
        if str(_HOOK_COMMON) not in sys.path:
            sys.path.insert(0, str(_HOOK_COMMON))
        from uai_toolkit.hooks.common.lib_session_state_union import write_session_state
        write_session_state(session_dir, tid, kw)
    except Exception:
        st = _read_state(session_dir, tid)
        st.update(kw)
        _write_state(session_dir, tid, st)


def _activity_idle_secs(session_dir):
    """Seconds since the session went idle per activity_state.json, or None if it
    is not cleanly idle (busy / missing / unparseable) — 'not safely idle'."""
    try:
        d = json.loads((Path(session_dir) / "activity_state.json").read_text())
    except Exception:
        return None
    if d.get("state") != "idle":
        return None
    at = d.get("at")
    if not at:
        return None
    try:
        t = _dt.datetime.fromisoformat(at)
        now = _dt.datetime.now(t.tzinfo) if t.tzinfo else _dt.datetime.now()
        return max(0, int((now - t).total_seconds()))
    except Exception:
        return None


def _recommend(session_dir, tid):
    # metrics.resume is written by Stop/04 through the bridge → canonical for
    # enrolled sessions, so read via the union (todo_0495).
    m = _read_union_state(session_dir, tid).get("metrics.resume") or {}
    return m.get("recommend"), int(m.get("sheddable_tokens") or 0), m.get("used_pct")


def _bounce_tiers(session_dir, tid):
    # config (may be MCP-set → canonical); union read
    return set(_read_union_state(session_dir, tid).get("bounce.auto_recommend") or RECOMMEND_BOUNCE)


def _arm(tid, session_dir, in_=RESCHEDULE_IN):
    """(Re)arm a self-destructing one-shot that fires THIS script again."""
    cmd = f"AI_ROOT={AI_ROOT} {PY} {SELF} {tid} --session-dir {session_dir}"
    log = GEN / "logs" / "auto_bounce" / f"{_job_id(tid)}.log"
    subprocess.run([PY, str(MGR), "once", "--in", in_, "--id", _job_id(tid),
                    "--command", cmd, "--remove", "--log", str(log)], check=False)


def cancel(tid):
    subprocess.run([PY, str(MGR), "once", "--cancel", _job_id(tid)], check=False)


def reconcile_from_stop(session_dir, tid, recommend) -> str:
    """Called by Stop/10_auto_bounce. Arm on transition INTO a bounce recommendation,
    cancel on transition OUT — touching launchd only on transitions (no churn).
    Returns a short status string for the hook log."""
    st = _read_union_state(session_dir, tid)   # config (bounce.auto/*) may be MCP-set → canonical
    if not st.get("bounce.auto"):
        if st.get("bounce.armed"):
            cancel(tid)
            _set(session_dir, tid, **{"bounce.armed": False})
        return "auto_bounce: disabled"
    if st.get("bounce.scheduled"):
        return "auto_bounce: bounce already scheduled"
    tiers = set(st.get("bounce.auto_recommend") or RECOMMEND_BOUNCE)
    bounce = recommend in tiers
    armed = bool(st.get("bounce.armed"))
    if bounce and not armed:
        _arm(tid, session_dir)
        _set(session_dir, tid, **{"bounce.armed": True})
        return f"auto_bounce: ARMED (recommend={recommend})"
    if not bounce and armed:
        cancel(tid)
        _set(session_dir, tid, **{"bounce.armed": False})
        return f"auto_bounce: cancelled (recommend={recommend})"
    return f"auto_bounce: steady (recommend={recommend}, armed={armed})"


def _do_bounce(tid):
    """Schedule the launchd --resume, then send the session /exit (the self-bounce)."""
    job = f"self_restart_{tid}"
    resume_cmd = f"AI_ROOT={AI_ROOT} {CLAUDECLI} --resume {tid}"
    log = GEN / "logs" / "self_restart" / f"{job}.log"
    subprocess.run([PY, str(MGR), "once", "--in", f"{RESUME_IN_MIN}m", "--id", job,
                    "--command", resume_cmd, "--remove", "--log", str(log)], check=False)
    subprocess.run([PY, str(SEND_SLASH), tid, "/exit"], check=False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("tid")
    ap.add_argument("--session-dir", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    tid, session_dir = a.tid, a.session_dir
    st = _read_union_state(session_dir, tid)   # config (bounce.auto/*) may be MCP-set → canonical

    if not st.get("bounce.auto"):
        _set(session_dir, tid, **{"bounce.armed": False})
        _log("STOP: bounce.auto disabled")
        return 0
    if st.get("bounce.scheduled"):
        _log("STOP: a bounce is already scheduled this cycle")
        return 0

    recommend, shed, used_pct = _recommend(session_dir, tid)
    if recommend not in _bounce_tiers(session_dir, tid):
        _set(session_dir, tid, **{"bounce.armed": False})
        _log(f"STOP: recommend={recommend} (used_pct={used_pct}, shed≈{shed}) no longer says bounce")
        return 0

    idle = _activity_idle_secs(session_dir)
    if idle is None or idle < IDLE_MIN_S:
        _log(f"RESCHEDULE: not safely idle (idle={idle}s < {IDLE_MIN_S}s)")
        if not a.dry_run:
            _arm(tid, session_dir)
        return 0

    _log(f"TRIGGER: idle {idle}s, recommend={recommend}, used_pct={used_pct}, sheddable≈{shed} — bouncing")
    if a.dry_run:
        _log("DRY-RUN: would schedule --resume + send /exit; nothing done")
        return 0
    _set(session_dir, tid, **{"bounce.scheduled": True, "bounce.armed": False})
    _do_bounce(tid)
    return 0


if __name__ == "__main__":
    sys.exit(main())
