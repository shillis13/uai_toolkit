#!/usr/bin/env python3
"""PostCompact hook — record compact.end and stage brief for delivery.

Sets compact.end in session state. If compact.brief_file has a valid path,
stages it into context_to_load/ for delivery on next prompt.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

_AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI" / "ai_root"))


def read_state(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def write_state(path, state):
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(path)
    except OSError:
        pass


def handler(hook_input, context):
    tracking_id = context.tracking_id
    session_dir = context.session_dir

    if not tracking_id:
        return HookResult.skip("no tracking_id")
    if not session_dir or not Path(session_dir).is_dir():
        return HookResult.skip("no session_dir")

    state_path = Path(session_dir) / f"{tracking_id}_state.json"
    state = read_state(state_path)
    now = datetime.now().isoformat()

    # Record compact.end + reset the per-cycle compaction flags. These flags
    # (compact.self / compact.self_triggered) gate future compactions; if they
    # never clear, the auto-threshold path stops firing after the first cycle
    # and a stale compact.self could mislead the next run. Clear them now that
    # the cycle is ending — AFTER we read compact.brief_file below.
    brief_file = state.get("compact.brief_file", "")
    state["compact.end"] = now
    state["compact.self"] = False
    state["compact.self_triggered"] = False
    state["compact.brief_pending"] = False
    state["updated_at"] = now
    write_state(state_path, state)

    # No brief was written for the conversation that just compacted (e.g. a forced
    # auto-compaction left no turn to write one). The transcript is still on disk,
    # so stage a one-shot instruction telling the session to write the brief from
    # the just-compacted messages on its next turn. A hook can't run an AI itself;
    # the session spawns the subagent when it reads this note. interval -2 is the
    # interval just before the current (post-compaction) live one — valid as long
    # as the catch-up runs before any further compaction, which it does (the
    # session is near-empty right after compacting, and the note drains next turn).
    if not brief_file or not Path(brief_file).exists():
        try:
            inbox = Path(session_dir) / "context_to_load"
            inbox.mkdir(exist_ok=True)
            ref = {
                "type": "catchup_brief",
                "interval": "-2",
                "brief_path": str(_AI_ROOT / "ai_general" / "data" / "session_briefs"
                                  / "auto_briefs" / f"{tracking_id}.yml"),
                "prompt_path": str(_AI_ROOT / "ai_general" / "ai_context_files"
                                   / "instructions" / "how_tos" / "instr_operational_handoff.md"),
            }
            (inbox / "00_catchup_brief.ref").write_text(json.dumps(ref, indent=2))
            return HookResult.allow("compact.end set, no brief — staged catch-up instruction")
        except OSError as e:
            return HookResult.allow(f"compact.end set, no brief; catch-up staging failed: {e}")

    # A brief WAS registered pre-compaction. Its .ref is staged at registration
    # time by register_self_brief.py (the creator owns delivery staging), so there
    # is nothing to stage here — the .ref already survives the compaction and drains
    # on the next turn (UserPromptSubmit/06) or on resume (SessionStart/02).
    return HookResult.allow("compact.end set, brief registered (ref staged at registration)")


if __name__ == "__main__":
    sys.exit(run_hook("auto_brief_postcompact", "PostCompact", handler))
