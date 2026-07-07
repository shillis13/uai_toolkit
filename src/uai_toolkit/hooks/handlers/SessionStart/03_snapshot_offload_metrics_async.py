#!/usr/bin/env python3
"""SessionStart hook — snapshot the offload-metrics baseline for this session.

Records the post-resume baseline that Stop/04 compares against to estimate how
many tokens a stop+resume would shed (see common/lib_offload_metrics.py).

Fires on every SessionStart source (startup/resume/clear/compact) — each begins a
new context baseline. File metrics (lean resumed jsonl size, cumulative archive)
are correct at this instant. The token/ctx baseline is NOT yet knowable (right
after a resume the state still holds the pre-resume token count), so it's marked
pending and the first Stop backfills it.

Async — fire-and-forget, never blocks.
"""

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common import lib_offload_metrics as lom


def handler(hook_input, context):
    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")

    transcript = hook_input.get("transcript_path") if isinstance(hook_input, dict) else None
    source = hook_input.get("source", "") if isinstance(hook_input, dict) else ""

    snap = {
        "ts": datetime.now().isoformat(),
        "source": source,
        "jsonl_bytes": 0,
        "jsonl_msgs": 0,
        "archive_bytes": 0,
        "archive_blocks": 0,
        "archive_orig_bytes": 0,
        "tokens": None,            # backfilled by first Stop (resumed count unknown here)
        "ctx_pct": None,
        "tokens_pending": True,
    }
    if transcript and Path(transcript).exists():
        try:
            snap["jsonl_bytes"] = Path(transcript).stat().st_size
        except OSError:
            pass
        snap["jsonl_msgs"] = lom.jsonl_line_count(transcript)
        a = lom.archive_stats(transcript)
        snap["archive_bytes"] = a["file_bytes"]
        snap["archive_blocks"] = a["blocks"]
        snap["archive_orig_bytes"] = a["orig_bytes"]

    state_path = Path(context.session_dir) / f"{context.tracking_id}_state.json"
    state = {}
    if state_path.exists():
        try:
            state = json.loads(state_path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    state["metrics.snapshot"] = snap
    state["updated_at"] = datetime.now().isoformat()
    try:
        tmp = state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(state_path)
    except OSError as e:
        return HookResult.skip(f"state write failed: {e}")

    return HookResult.allow(
        f"snapshot[{source or 'start'}] jsonl:{snap['jsonl_bytes']}B "
        f"archive:{snap['archive_orig_bytes']}B/{snap['archive_blocks']}blk (tokens pending)"
    )


if __name__ == "__main__":
    sys.exit(run_hook("snapshot_offload_metrics", "SessionStart", handler))
