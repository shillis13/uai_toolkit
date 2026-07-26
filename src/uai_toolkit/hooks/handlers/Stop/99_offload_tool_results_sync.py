#!/usr/bin/env python3
"""Stop hook — kick off resume-safe tool-content offloading (always last).

This is the FINAL sync Stop handler by convention (prefix 99). It carries no
knowledge of the other handlers: it just needs to (a) be reached at all — which,
for the last sync handler, means no earlier sync handler exited 2 / blocked the
Stop, so the turn genuinely ended and offloading can't collide with a continuing
turn — and (b) be the last thing to touch the transcript.

It runs offload_tool_results.py *synchronously* (blocking) — as a *_sync* handler,
the framework holds the turn open until we return, so CC hasn't begun the next turn's
writes: the transcript is quiescent for the offloader's whole read+write window, i.e.
no race by construction (the old detached launch raced concurrent appends 219x by
outliving the hook). The disk edit is inert on the running session (CC sends
in-memory, not the JSONL); the payoff is a lean next --resume. Verified safe: CC keeps
no persistent transcript handle, so the atomic os.replace can't orphan a later write;
the offloader's append-tolerant splice remains a backstop. Cost is a few seconds of
turn-end latency, only on a throttled (>= min_growth) run.

OPT-IN: only runs when session state `offload.on_stop` is truthy (dogfood gate).
THROTTLE: skips unless the transcript grew >= `offload.on_stop_min_growth` bytes
since the last launch, so it doesn't re-scan on every trivial turn.

Non-Claude platforms (Codex/Gemini AfterAgent) don't carry transcript_path in the
payload, so this skips gracefully there.

Tunable session-state keys (all optional):
  offload.on_stop             bool   master switch (default off)
  offload.on_stop_min_growth  int    bytes of growth to trigger (default 8192)
  offload.keep_last_turns     int    protected tail window (default 5)
  offload.min_bytes           int    per-block size floor (default 512)
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

DEFAULT_MIN_GROWTH = 8192
DEFAULT_KEEP_LAST_TURNS = 5
DEFAULT_MIN_BYTES = 512

# AI_ROOT-relative (devTree-safe): .../ai_general/data/hooks/Stop/this -> parents[3] = ai_general
OFFLOADER = Path(__file__).resolve().parents[3] / "scripts" / "jsonl" / "offload_tool_results.py"


def _int(state, key, default):
    try:
        return int(state.get(key, default))
    except (ValueError, TypeError):
        return default


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")

    # Union read; the single write below is TARGETED via the bridge (todo_0495).
    state = read_union(context.session_dir, context.tracking_id)

    # Opt-in gate (dogfood switch)
    if not state.get("offload.on_stop"):
        return HookResult.skip("offload.on_stop not enabled")

    # Resolve the transcript path (Claude Stop payload carries it)
    transcript = hook_input.get("transcript_path") if isinstance(hook_input, dict) else None
    if not transcript or not Path(transcript).exists():
        return HookResult.skip("no transcript_path in hook input")
    transcript = str(Path(transcript))

    if not OFFLOADER.exists():
        return HookResult.skip(f"offloader not found at {OFFLOADER}")

    # Throttle on growth since last launch
    try:
        cur_size = os.path.getsize(transcript)
    except OSError:
        return HookResult.skip("cannot stat transcript")
    last_size = _int(state, "offload.last_size", 0)
    min_growth = _int(state, "offload.on_stop_min_growth", DEFAULT_MIN_GROWTH)
    if cur_size - last_size < min_growth:
        return HookResult.skip(f"grew {cur_size - last_size}B < {min_growth}B since last offload")

    keep = _int(state, "offload.keep_last_turns", DEFAULT_KEEP_LAST_TURNS)
    min_bytes = _int(state, "offload.min_bytes", DEFAULT_MIN_BYTES)

    # Launch detached and return immediately (non-blocking). The offloader's
    # CAS guard handles any race with a new prompt; its idempotency handles
    # "nothing new to offload" cheaply.
    # Capture the detached offloader's own summary (Paged out / Reclaimed / raced /
    # error) to a per-session log instead of discarding it to /dev/null, so each run
    # is auditable. A timestamped header per launch keeps runs correlatable.
    log_path = Path(context.session_dir) / "offload.log"
    try:
        logf = open(log_path, "a", encoding="utf-8")
        logf.write(f"\n===== {datetime.now().isoformat(timespec='seconds')} "
                   f"SYNC run (size {cur_size:,}, +{cur_size - last_size:,}) =====\n")
        logf.flush()
    except OSError:
        logf = subprocess.DEVNULL  # fall back to discard rather than break offloading
    # SYNCHRONOUS (blocking) run — NOT detached. This handler is named *_sync* and the
    # framework runs sync handlers inline & blocking, so CC holds the turn open until we
    # return: the transcript is quiescent for our whole read+write window — no race by
    # construction. (The old detached Popen behaved async despite the _sync name and
    # raced concurrent appends 219x by outliving the hook.) Verified safe: CC keeps no
    # persistent transcript handle (lsof: open-append-close per record), so the
    # offloader's atomic os.replace can't orphan a later write. The append-tolerant
    # splice stays as a backstop. Cost: a few seconds of turn-end latency, but only on a
    # throttled (>= min_growth) run. timeout < the Stop-hook timeout so a pathological
    # offload never wedges turn-end; an atomic write means a killed offloader leaves the
    # transcript intact (retried next Stop).
    try:
        subprocess.run(
            ["python3", str(OFFLOADER), transcript,
             "--keep-last-turns", str(keep), "--min-bytes", str(min_bytes)],
            stdin=subprocess.DEVNULL, stdout=logf, stderr=subprocess.STDOUT,
            env=os.environ, timeout=20,
        )
    except subprocess.TimeoutExpired:
        # Fail gracefully well UNDER the 30s dispatcher budget (shared with handlers
        # 00..98) so CC never hard-kills the whole Stop chain. A real offload of a 40MB
        # transcript is ~2s; 20s covers pathological sizes with margin, and an atomic
        # write means a timed-out offloader leaves the transcript intact (retry next Stop).
        return HookResult.allow("offload timed out (>20s); atomic write left transcript intact, retry next Stop")
    except OSError as e:
        return HookResult.skip(f"run failed: {e}")
    finally:
        if logf is not subprocess.DEVNULL:
            try:
                logf.close()
            except OSError:
                pass

    # Record the size we launched against (best-effort, targeted write via bridge)
    write_session_state(context.session_dir, context.tracking_id,
                        {"offload.last_size": cur_size})

    return HookResult.allow(f"offload launched (size {cur_size}B, +{cur_size - last_size}B)")


if __name__ == "__main__":
    sys.exit(run_hook("offload_tool_results", "Stop", handler))
