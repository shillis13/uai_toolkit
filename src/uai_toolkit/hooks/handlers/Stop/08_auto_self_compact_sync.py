#!/usr/bin/env python3
"""Stop hook — trigger self-compact when context usage exceeds threshold.

Reads compact.auto_self_pct from session state (default 85%). Two cooperating
delivery paths, both guarded by the compact.self_triggered cycle flag so a
handoff fires at most once per compaction cycle:

  1. Deferred idle-gated timer (deferred_self_compact.reconcile_from_stop, armed
     below): delivers the compact instruction during a lull — the graceful,
     never-mid-work path. But it ONLY fires when the session goes idle.
  2. Direct trigger (this hook, at/over threshold): a session that runs
     continuously past threshold never goes idle, so the deferred timer would
     never get its window and the session would never hand off. When ctx >=
     threshold we therefore trigger directly here — mint an auth token, inject
     the SAME instruction body the deferred path uses (subagent brief ->
     register -> comms /compact), and set compact.self_triggered.

Setting compact.self_triggered=true also stands the deferred one-shot down (it
STOPs when it sees that flag), so the two paths never double-fire. Below the
threshold, this hook only warns in the 80-85 band and keeps the deferred timer
reconciled.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

DEFAULT_THRESHOLD = 85
DEFAULT_WARNING_THRESHOLD = 80
# Minimum % of context still free for the session to write its OWN brief. At or
# above this, self-write (the session knows what mattered); below it, too tight —
# spawn a subagent that reads the transcript from disk (costs no live context).
# Override per session via state key compact.self_write_min_remaining.
DEFAULT_SELF_WRITE_MIN = 10
_AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI" / "ai_root"))


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")

    # Read session state
    state_path = Path(context.session_dir) / f"{context.tracking_id}_state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    # Check threshold (0 = disabled)
    threshold = state.get("compact.auto_self_pct", DEFAULT_THRESHOLD)
    try:
        threshold = int(threshold)
    except (ValueError, TypeError):
        threshold = DEFAULT_THRESHOLD

    if threshold <= 0:
        return HookResult.skip("auto-self-compact disabled (threshold=0)")

    # Already triggered this cycle?
    if state.get("compact.self_triggered"):
        return HookResult.skip("already triggered self-compact this cycle")

    # Already in a self-compact?
    if state.get("compact.self"):
        return HookResult.skip("self-compact already in progress")

    # Get current context %
    ctx_pct = state.get("context.used_pct")
    if ctx_pct is None:
        return HookResult.skip("no context.used_pct in state")

    try:
        ctx_pct = int(ctx_pct)
    except (ValueError, TypeError):
        return HookResult.skip("context.used_pct not numeric")

    # Arm/cancel/reconcile the deferred idle-gated compaction timer. THIS is what
    # eventually triggers /self-compact — during a lull, via a self-destructing
    # one-shot, never mid-work. This hook does not compact; it only warns (below)
    # and keeps the timer in sync (touches launchd only on transitions).
    defer_status = "deferred: (unavailable)"
    try:
        import sys as _sys
        _jsonl = str(Path(__file__).resolve().parents[3] / "scripts" / "jsonl")
        if _jsonl not in _sys.path:
            _sys.path.insert(0, _jsonl)
        from uai_toolkit.jsonl.deferred_self_compact import reconcile_from_stop
        defer_status = reconcile_from_stop(
            context.session_dir, context.tracking_id, ctx_pct, threshold)
    except Exception as e:
        defer_status = f"deferred reconcile error: {e}"

    if ctx_pct < threshold:
        # Check warning threshold
        warning_threshold = state.get("compact.warning_pct", DEFAULT_WARNING_THRESHOLD)
        try:
            warning_threshold = int(warning_threshold)
        except (ValueError, TypeError):
            warning_threshold = DEFAULT_WARNING_THRESHOLD

        if warning_threshold > 0 and ctx_pct >= warning_threshold:
            msg = f"Context at {ctx_pct}% — approaching self-compact threshold ({threshold}%). Consider wrapping up current work."
            output = json.dumps({"systemMessage": msg})
            return HookResult.output(output, f"ctx:{ctx_pct}% >= warning:{warning_threshold}% | {defer_status}")

        return HookResult.allow(f"ctx:{ctx_pct}% < threshold:{threshold}% | {defer_status}")

    # At/over threshold — tell the session to self-compact via the /self-compact
    # skill. The deferred idle-gated timer (armed above) only delivers during a
    # lull; a session running continuously past threshold never goes idle and
    # would otherwise never hand off. So we surface a one-line instruction to fire
    # /self-compact at itself, and set compact.self_triggered (which also stands
    # the deferred one-shot down, so the two paths never double-fire).
    #
    # The steps live in ONE place — the /self-compact skill (condenser subagent ->
    # register -> /compact). The skill is model-invocable and compaction is unguarded
    # (no token), so the session just runs /self-compact.
    try:
        from uai_toolkit.jsonl.deferred_self_compact import cancel as _cancel_deferred
    except Exception:
        _cancel_deferred = None

    msg = (f"Your context is at {ctx_pct}% — over the self-compact threshold "
           f"({threshold}%) and you're still working past it. Run /self-compact now: "
           f"it writes your handoff brief via a subagent, registers it, then compacts "
           f"— the brief auto-loads afterward.")

    # Guard once-per-cycle: persist BEFORE returning so a re-entrant Stop skips
    # (line ~54) and the deferred one-shot STOPs on its next fire.
    state["compact.self_triggered"] = True
    try:
        state_path.write_text(json.dumps(state, indent=2))
    except OSError as e:
        return HookResult.error(f"self-compact state write failed: {e} | {defer_status}")

    # Stand the deferred one-shot down so it doesn't fire later only to no-op.
    if _cancel_deferred:
        try:
            _cancel_deferred(context.tracking_id)
        except Exception:
            pass

    output = json.dumps({"systemMessage": msg})
    return HookResult.output(
        output, f"ctx:{ctx_pct}% >= threshold:{threshold}% -> /self-compact | {defer_status}")


if __name__ == "__main__":
    sys.exit(run_hook("auto_self_compact", "Stop", handler))
