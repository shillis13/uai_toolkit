#!/usr/bin/env python3
"""PreCompact hook — launch auto-brief creation for the compacting session.

Sets compact.start in session state, records pre-compaction snapshot,
clears compact.brief_file, and kicks off auto_brief.py in the background.

Async handler — launches the brief and returns immediately.
"""

import json
import os
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common.lib_session_state_union import read_union, write_session_state  # session-state bridge (todo_0495)

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
AUTO_BRIEF = Path.home() / "bin" / "ai" / "jsonl" / "auto_brief.py"
NOTIFY = Path.home() / "bin" / "ai" / "notifications" / "send_user_notification.py"

# Canonical "DisplayName (tracking_id)" for user-facing notices.
sys.path.insert(0, str(AI_ROOT / "ai_general" / "scripts" / "session_mgmt"))
try:
    from uai_toolkit.session_mgmt.lib_identity_display import format_identity
except Exception:  # pragma: no cover - degrade to raw id; a lookup must not break the hook
    def format_identity(identity, *, unknown="unknown"):
        return identity if identity else unknown


def handler(hook_input, context):
    tracking_id = context.tracking_id
    session_dir = context.session_dir

    if not tracking_id:
        return HookResult.skip("no tracking_id")
    if not session_dir or not Path(session_dir).is_dir():
        return HookResult.skip("no session_dir")

    state = read_union(session_dir, tracking_id)
    now = datetime.now().isoformat()

    # A self-compaction registers its brief BEFORE triggering /compact (via
    # register_self_brief.py, which sets compact.self + compact.brief_file). We
    # must PRESERVE that registration — clearing it here is what orphaned every
    # self-written brief. Only treat it as valid if the file actually exists.
    registered_brief = state.get("compact.brief_file", "")
    is_self = bool(state.get("compact.self")) and bool(registered_brief) and Path(registered_brief).exists()

    # Record pre-compaction snapshot — targeted write through the bridge (todo_0495).
    # pre_* values come from the union read above; the brief_file is preserved for a
    # self-compaction, else cleared.
    write_session_state(session_dir, tracking_id, {
        "compact.start": now,
        "compact.brief_file": registered_brief if is_self else "",
        "compact.end": "",  # clear previous end
        "compact.pre_ctx_pct": state.get("context.used_pct", ""),
        "compact.pre_tokens": state.get("context.tokens", ""),
        "compact.pre_turns": state.get("transcript.turns", ""),
        "compact.pre_msgs": state.get("transcript.messages", ""),
        "updated_at": now,
    })

    # Self-compaction: the AI already wrote + registered its own brief. Skip the
    # async condenser dispatch — PostCompact will stage the registered brief.
    if is_self:
        return HookResult.allow("compact.start set, self-compaction — brief already written by AI")

    # Check if auto-brief is enabled (default true)
    auto_brief_enabled = state.get("compact.auto_brief", True)
    if not auto_brief_enabled:
        return HookResult.allow("compact.start set, auto-brief disabled")

    # Launch auto_brief.py in background
    if not AUTO_BRIEF.exists():
        return HookResult.allow("compact.start set, auto_brief.py not found")

    try:
        proc = subprocess.Popen(
            [sys.executable, str(AUTO_BRIEF), tracking_id],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=os.environ,
        )
        # Don't wait — let it run async. But we need the result eventually.
        # Launch a wrapper that waits for auto_brief, writes the result, and
        # optionally injects the brief if compaction is already done.
        # For now, the brief path will be written by a completion watcher.
        #
        # Actually — auto_brief.py dispatches to a condenser session and returns
        # immediately (exit 0 = dispatched). The brief file appears later when
        # the condenser finishes. We need a separate mechanism to detect completion.
        # For now, set compact.brief_pending = true.
        proc.wait(timeout=30)  # auto_brief.py should return quickly (it dispatches)

        if proc.returncode == 0:
            write_session_state(session_dir, tracking_id, {
                "compact.brief_pending": True,
                "updated_at": datetime.now().isoformat(),
            })
            return HookResult.allow(f"compact.start set, auto-brief dispatched")
        elif proc.returncode == 1:
            # No idle condenser — notify user
            _notify_failure(tracking_id, "no idle condenser available")
            return HookResult.allow("compact.start set, no idle condenser for auto-brief")
        elif proc.returncode == 2:
            _notify_failure(tracking_id, "session not found or no history")
            return HookResult.allow("compact.start set, auto-brief: session/history not found")
        else:
            stderr = proc.stderr.read().decode() if proc.stderr else ""
            _notify_failure(tracking_id, f"auto_brief.py exit {proc.returncode}: {stderr[:200]}")
            return HookResult.allow(f"compact.start set, auto-brief failed (exit {proc.returncode})")

    except subprocess.TimeoutExpired:
        proc.kill()
        _notify_failure(tracking_id, "auto_brief.py timed out")
        return HookResult.allow("compact.start set, auto-brief timed out")
    except OSError as e:
        _notify_failure(tracking_id, str(e))
        return HookResult.allow(f"compact.start set, auto-brief launch failed: {e}")


def _notify_failure(tracking_id, reason):
    """Send user notification that auto-brief failed."""
    if not NOTIFY.exists():
        return
    msg = f"Auto-brief failed for session {format_identity(tracking_id)}: {reason}"
    try:
        subprocess.run(
            [sys.executable, str(NOTIFY), "error", msg],
            timeout=5, capture_output=True,
        )
    except (subprocess.TimeoutExpired, OSError):
        pass


if __name__ == "__main__":
    sys.exit(run_hook("auto_brief_precompact", "PreCompact", handler))
