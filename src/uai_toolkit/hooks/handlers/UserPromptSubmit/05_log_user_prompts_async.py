#!/usr/bin/env python3
"""UserPromptSubmit handler — log all user prompts to a central JSONL file.

Captures every prompt submitted across all sessions into one searchable log.
Useful for tracking what was asked, when, and to which session.

Log: ai_general/data/audit/user_prompts.jsonl

Async — fire-and-forget, never blocks.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
LOG_FILE = AI_ROOT / "ai_general" / "data" / "audit" / "user_prompts.jsonl"


def handler(hook_input, context):
    prompt = hook_input.get("prompt", "")
    if not prompt:
        return HookResult.skip("no prompt")

    session_name = os.environ.get("AI_SESSION_DISPLAY_NAME", "")
    platform = os.environ.get("AI_SESSION_PLATFORM", "")

    # Look up display name from session store if not in env
    if not session_name and context.tracking_id:
        try:
            import subprocess
            store_script = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "session_store.py"
            if store_script.exists():
                result = subprocess.run(
                    [sys.executable, str(store_script), "get", context.tracking_id],
                    capture_output=True, text=True, timeout=5,
                )
                if result.returncode == 0 and result.stdout.strip():
                    session_data = json.loads(result.stdout)
                    session_name = session_data.get("display_name", "")
                    if not platform:
                        platform = session_data.get("platform", "")
        except (subprocess.TimeoutExpired, json.JSONDecodeError, OSError):
            pass

    entry = {
        "ts": datetime.now().isoformat(),
        "tracking_id": context.tracking_id or "",
        "session_name": session_name,
        "platform": platform,
        "prompt_preview": prompt[:500],
        "prompt_length": len(prompt),
        "cwd": hook_input.get("cwd", ""),
    }

    try:
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        return HookResult.skip("write failed")

    return HookResult.allow(f"logged {len(prompt)} chars")


if __name__ == "__main__":
    sys.exit(run_hook("log_user_prompts", "UserPromptSubmit", handler))
