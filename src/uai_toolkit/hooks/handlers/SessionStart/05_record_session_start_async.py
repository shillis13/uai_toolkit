#!/usr/bin/env python3
"""SessionStart hook — keep the session's start history complete and current.

On each genuine (re)start, rebuild `session.start_history` in the per-session state
file ({session_dir}/{tracking_id}_state.json) as the union of:

  - the history already recorded (prior plain --resume starts leave no transcript
    marker, so they must be preserved),
  - every lifecycle marker in the transcript (SESSION_IDENTITY / SESSION RESUMED /
    parentUuid==null chain anchors) — see session_starts.derive_starts, and
  - this start, right now.

So the field self-heals and BACKFILLS: a session that predates this hook still shows
its real history the first time it starts again. The UAI app surfaces the array in
the Session Details panel and the Session Store's Store Fields tab.

Async (fire-and-forget); fails open. Records startup + resume (genuine launches);
skips clear/compact (same process continuing) — those still appear via the
transcript's chain anchors, they just don't add a live 'now' entry.

Note on sources: Claude Code fires SessionStart with source in {startup, resume,
clear, compact}.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "scripts" / "session_mgmt"))

START_SOURCES = {"startup", "resume", "", None}


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no tracking_id / session_dir")

    source = (hook_input or {}).get("source")
    if source not in START_SOURCES:
        return HookResult.skip(f"source={source} is a continuation, not a start")

    try:
        import json
        import session_starts

        state_path = Path(context.session_dir) / f"{context.tracking_id}_state.json"
        existing = []
        if state_path.exists():
            try:
                _st = json.loads(state_path.read_text())
                _e = _st.get("session.start_history")
                if isinstance(_e, list):
                    existing = _e
            except (json.JSONDecodeError, OSError):
                existing = []

        # Transcript(s) for this session — the SessionStart payload carries the path.
        tpaths = []
        tp = (hook_input or {}).get("transcript_path")
        if tp:
            tpaths.append(tp)
        derived = session_starts.derive_starts(tpaths)

        merged = session_starts.merge_starts(existing, derived, [datetime.now().isoformat()])
        if not session_starts.write_start_history(context.session_dir, context.tracking_id, merged):
            return HookResult.error("could not write start_history")
        return HookResult.allow(f"start_history: {len(merged)} start(s) (source={source or 'startup'})")
    except Exception as e:  # noqa: BLE001 — async, fail open, but signal the error
        return HookResult.error(f"record_session_start failed: {e}")


if __name__ == "__main__":
    sys.exit(run_hook("record_session_start", "SessionStart", handler))
