#!/usr/bin/env python3
"""SessionStart hook (async) — reap orphaned deferred self-compact timers.

A deferred self-compact one-shot (com.shawnhillis.oneshot.compact_deferred.<tid>)
can outlive its session if the session died while a timer was armed. On any
session start, opportunistically cancel deferred one-shots whose session is
gone/inactive. Bounded (only compact_deferred.* one-shots) and fire-and-forget.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult


def handler(hook_input, context):
    try:
        _jsonl = str(Path(__file__).resolve().parents[3] / "scripts" / "jsonl")
        if _jsonl not in sys.path:
            sys.path.insert(0, _jsonl)
        from uai_toolkit.jsonl.deferred_self_compact import sweep_orphans
        status = sweep_orphans()
    except Exception as e:
        return HookResult.allow(f"deferred-compact sweep skipped: {e}")
    return HookResult.allow(status)


if __name__ == "__main__":
    sys.exit(run_hook("sweep_deferred_compact", "SessionStart", handler))
