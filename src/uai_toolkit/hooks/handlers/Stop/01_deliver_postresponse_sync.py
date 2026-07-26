#!/usr/bin/env python3
"""Stop hook — deliver postResponse queued prompts after AI finishes responding."""

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common.lib_hook_scripts import (
    get_tracking_id, get_queue_dir, load_queue_entries,
    filter_ready, compose_context, mark_all_delivered, SEND_PROMPT, is_locked,
    drop_blocked_sources,
)

# send_prompt.py's --target per platform. The target was hardcoded "claude-cli",
# so queued prompts to codex/gemini/… sessions were typed to the wrong CLI adapter
# (todo_0603). This hook fires for the CURRENT session, so its platform comes from
# the session's own env.
_PLATFORM_TARGET = {
    "claude_cli": "claude-cli", "codex_cli": "codex-cli", "gemini_cli": "gemini-cli",
    "grok_cli": "grok-cli", "antigravity_cli": "antigravity-cli",
}


def _target_for_platform():
    """The send_prompt target for THIS session's platform (default claude-cli)."""
    return _PLATFORM_TARGET.get(os.environ.get("AI_SESSION_PLATFORM") or "", "claude-cli")


def send_prompt_to_session(session, message, target):
    """Send (type + submit) a prompt to the session via send_prompt.py.

    Invoked through the Python interpreter so it does not depend on the script's
    executable bit or shebang. `target` is the platform-specific send_prompt adapter
    (claude-cli / codex-cli / …). Returns False on any failure (missing sender,
    non-zero exit, timeout) so the caller keeps the entries queued for retry.
    """
    if not SEND_PROMPT.exists():
        return False
    try:
        result = subprocess.run(
            [sys.executable, str(SEND_PROMPT), "--target", target,
             "--session", session, "--message", message,
             "--submit", "--force"],
            capture_output=True, text=True, timeout=90
        )
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return False


def handler(hook_input, context):
    tracking_id = get_tracking_id()
    if not tracking_id:
        return HookResult.skip("no tracking_id")

    if is_locked(tracking_id):
        return HookResult.skip("session is conversation-locked")

    entries = load_queue_entries(get_queue_dir(tracking_id))
    if not entries:
        return HookResult.skip("no queue entries")

    ready = filter_ready(entries)
    ready = drop_blocked_sources(tracking_id, ready)  # hold non-exempt while prompt-blocked
    if not ready:
        return HookResult.skip("no ready entries")

    prompt, included, overflow = compose_context(ready)
    if not included:
        return HookResult.skip("no entries composed")

    if send_prompt_to_session(tracking_id, prompt, _target_for_platform()):
        mark_all_delivered(included)
        return HookResult.allow(f"delivered {len(included)} entries, {len(overflow)} overflow")

    return HookResult.error("send_prompt failed")


if __name__ == "__main__":
    sys.exit(run_hook("deliver_postresponse", "Stop", handler))
