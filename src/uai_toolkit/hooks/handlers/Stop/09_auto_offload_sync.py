#!/usr/bin/env python3
"""Stop hook — auto-offload ADVISORY layer (increment 1: warnings only).

Mirrors 08_auto_self_compact_sync.py, but for context_offload (LOSSLESS tool-
result paging) instead of /self-compact (LOSSY). This increment ONLY reads
state and injects graduated systemMessage warnings as the session fills up.
It NEVER mutates the transcript and NEVER fires an offload. Its only side
effect is caching the offloadable-token-count (otc) into session state so we
do not re-run the (relatively expensive) dry-run on every single Stop.

Key value = PROFILE ROUTING: high context% + HIGH otc  -> steer to context_offload
(offload will actually reclaim a lot, losslessly). high context% + LOW otc
-> steer to /self-compact or consolidation (the bulk is conversation/thinking,
which offload cannot touch, so offloading would barely help).

Terms:
  otc  = offloadable-token-count = tokens context_offload could reclaim losslessly
         right now (tool results / large inputs / attachments), from
         offload_tool_results.py --dry-run --json -> tokens_reclaimed.
  ctx% = context.used_pct, the live context-window fill percentage.

State keys (all in {tracking_id}_state.json; mirror compact.* naming):
  context.auto_offload_pct  -- (increment-2 firing toggle) auto-offload threshold
                               %; 0 or missing = DISABLED. Opt-in, default off.
                               In THIS increment it only decides whether the
                               "Auto-offload will fire at N%" suffix is shown.
  context.offload_warn_pct  -- first (gentle) warning % (default 60)
  context.offload_warn2_pct -- second (firmer) warning % (default 75)
  context.offload_otc_min   -- otc floor in TOKENS for "offload is worth it"
                               (default 200000)
  context.used_pct          -- current context fill % (read-only here)

Cache / spam-control keys this hook WRITES:
  context.otc_tokens        -- last computed otc
  context.otc_computed_at   -- epoch seconds of last otc compute
  context.otc_at_pct        -- ctx% at last otc compute
  context.offload_warned_level -- highest warn level already emitted (0/1/2);
                               reset to 0 when ctx drops back below warn_pct.

The advisory warnings themselves are ALWAYS active (that is the point of this
layer); they are governed by offload_warn_pct / offload_warn2_pct, NOT by the
auto_offload_pct firing toggle.

COORDINATION NOTE (increment 2 — NOT implemented here):
  Increment 2 will arm a deferred, idle-gated one-shot (clone
  ai_general/scripts/jsonl/deferred_self_compact.py -> deferred_auto_offload.py)
  that actually runs context_offload + bounce at context.auto_offload_pct during
  a lull. It must coordinate with 08_auto_self_compact_sync.py so that OFFLOAD
  (lossless) is the FIRST line of defense and /self-compact (lossy) is the
  fallback only when otc is low (conversation/thinking-heavy). i.e. at the
  firing point: if otc >= otc_min -> offload+bounce; else -> hand off to the
  self-compact path. This hook already computes the otc signal that routing
  decision will need.
"""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

DEFAULT_WARN_PCT = 60
DEFAULT_WARN2_PCT = 75
DEFAULT_OTC_MIN = 200000        # tokens
OTC_CACHE_TTL = 300             # seconds — reuse cached otc if computed within this
OTC_PCT_DELTA = 3               # recompute if ctx% moved >= this since last compute
OTC_TIMEOUT = 20               # seconds — hard cap on the dry-run subprocess

_JSONL_DIR = Path(__file__).resolve().parents[3] / "scripts" / "jsonl"
_OFFLOAD_SCRIPT = _JSONL_DIR / "offload_tool_results.py"


def _read_state(state_path):
    if state_path.exists():
        try:
            return json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def _persist(state_path, updates):
    """Read-modify-write the given keys into the state file (merge, don't clobber)."""
    state = _read_state(state_path)
    state.update(updates)
    try:
        state_path.write_text(json.dumps(state, indent=2))
    except OSError:
        pass


def _as_int(val, default=None):
    try:
        return int(val)
    except (ValueError, TypeError):
        return default


def _resolve_transcript(tracking_id):
    """Resolve tracking id -> transcript .jsonl path via scrub_files.find_jsonl
    (the same resolver offload_tool_results.py and tools/context_ops.py use)."""
    d = str(_JSONL_DIR)
    if d not in sys.path:
        sys.path.insert(0, d)
    try:
        import scrub_files  # noqa: E402
        found = scrub_files.find_jsonl(tracking_id)
        return str(found) if found else None
    except Exception:
        return None


def _compute_otc(context):
    """Run the offload dry-run and return tokens_reclaimed (int) or None on any failure."""
    transcript = _resolve_transcript(context.tracking_id)
    if not transcript:
        return None
    try:
        p = subprocess.run(
            [sys.executable, str(_OFFLOAD_SCRIPT), transcript, "--dry-run", "--json"],
            capture_output=True, text=True, timeout=OTC_TIMEOUT,
            stdin=subprocess.DEVNULL,
        )
        if p.returncode != 0:
            return None
        data = json.loads((p.stdout or "").strip())
        return _as_int(data.get("tokens_reclaimed"), None)
    except Exception:
        return None


def _get_otc(context, state, state_path, ctx_pct):
    """Return otc (int or None), using the cache when fresh; else recompute+persist.

    Reuse the cached value iff it was computed within OTC_CACHE_TTL seconds AND the
    ctx% has moved fewer than OTC_PCT_DELTA points since. Otherwise recompute.
    """
    now = time.time()
    cached = state.get("context.otc_tokens")
    computed_at = state.get("context.otc_computed_at")
    at_pct = state.get("context.otc_at_pct")
    if cached is not None and computed_at is not None and at_pct is not None:
        try:
            ca = float(computed_at)
        except (ValueError, TypeError):
            ca = None
        ap = _as_int(at_pct, None)
        cv = _as_int(cached, None)
        if ca is not None and ap is not None and cv is not None:
            if (now - ca) <= OTC_CACHE_TTL and abs(ctx_pct - ap) < OTC_PCT_DELTA:
                return cv  # fresh cache hit — do NOT recompute
    otc = _compute_otc(context)
    if otc is not None:
        _persist(state_path, {
            "context.otc_tokens": otc,
            "context.otc_computed_at": now,
            "context.otc_at_pct": ctx_pct,
        })
    return otc


def _fmt(otc):
    return f"~{otc:,} tok" if otc is not None else "an unknown amount"


def _build_message(level, ctx_pct, otc, otc_min, auto_pct):
    """Graduated + PROFILE-ROUTED warning. high otc -> steer to context_offload;
    low otc -> steer to /self-compact or consolidation."""
    auto_suffix = (f" Auto-offload will fire at {auto_pct}% when idle."
                   if auto_pct > 0 else "")
    high_otc = otc is not None and otc >= otc_min
    if level >= 2:
        head = f"Context at {ctx_pct}%."
        if high_otc:
            body = f" {_fmt(otc)} is losslessly offloadable — consider context_offload."
        elif otc is not None:
            body = (f" Only {_fmt(otc)} offloadable — you're conversation/thinking-heavy; "
                    "consider /self-compact or consolidation instead.")
        else:
            body = " Consider context_offload (lossless), or /self-compact if little is offloadable."
        return head + body + auto_suffix
    # level 1 — gentler
    head = f"Context at {ctx_pct}% and rising."
    if high_otc:
        body = f" {_fmt(otc)} is losslessly offloadable now — a context_offload would help."
    elif otc is not None:
        body = (f" Only {_fmt(otc)} is offloadable — mostly conversation/thinking; "
                "/self-compact or consolidation will help more than offload.")
    else:
        body = " Consider context_offload, or /self-compact if little is offloadable."
    return head + body + auto_suffix


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")

    state_path = Path(context.session_dir) / f"{context.tracking_id}_state.json"
    state = _read_state(state_path)

    warn_pct = _as_int(state.get("context.offload_warn_pct", DEFAULT_WARN_PCT), DEFAULT_WARN_PCT)
    warn2_pct = _as_int(state.get("context.offload_warn2_pct", DEFAULT_WARN2_PCT), DEFAULT_WARN2_PCT)
    otc_min = _as_int(state.get("context.offload_otc_min", DEFAULT_OTC_MIN), DEFAULT_OTC_MIN)
    auto_pct = _as_int(state.get("context.auto_offload_pct", 0), 0)

    ctx_pct = state.get("context.used_pct")
    if ctx_pct is None:
        return HookResult.skip("no context.used_pct in state")
    ctx_pct = _as_int(ctx_pct, None)
    if ctx_pct is None:
        return HookResult.skip("context.used_pct not numeric")

    prev_level = _as_int(state.get("context.offload_warned_level", 0), 0)

    # Below the first warning: cheap path — do NOT compute otc. Reset the warned
    # level so a later re-crossing re-emits.
    if ctx_pct < warn_pct:
        if prev_level != 0:
            _persist(state_path, {"context.offload_warned_level": 0})
        return HookResult.allow(f"ctx:{ctx_pct}% < warn:{warn_pct}%")

    # At/above warn: compute (or reuse cached) otc, decide the level.
    otc = _get_otc(context, state, state_path, ctx_pct)
    level = 2 if ctx_pct >= warn2_pct else 1

    # Spam control: only (re)emit when the level increases (mirror 08's
    # don't-warn-every-turn behavior).
    if level <= prev_level:
        return HookResult.allow(
            f"ctx:{ctx_pct}% level:{level} <= warned:{prev_level} (already warned) | otc:{otc}")

    msg = _build_message(level, ctx_pct, otc, otc_min, auto_pct)
    _persist(state_path, {"context.offload_warned_level": level})
    output = json.dumps({"systemMessage": msg})
    return HookResult.output(
        output, f"ctx:{ctx_pct}% level:{level} otc:{otc} otc_min:{otc_min}")


if __name__ == "__main__":
    sys.exit(run_hook("auto_offload_sync", "Stop", handler))
