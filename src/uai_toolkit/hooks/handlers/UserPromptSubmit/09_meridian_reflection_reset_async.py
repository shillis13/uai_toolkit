#!/usr/bin/env python3
"""UserPromptSubmit hook — re-arm Meridian's reflection schedule.

Acts ONLY for Meridian's session (tracking_id 20260423_045650_app3020c_cla); on
every other session's prompt it's a cheap no-op. When Meridian receives a prompt,
it runs the reset script, which ensures the `meridian_reflection` task group
exists and, if either of its two run-once jobs has already fired (disabled) — or
the group doesn't exist yet — reschedules reflect_1 to the next 8:53am and
reflect_2 to 8:53am two days later and enables both. If both are still pending it
does nothing, so frequent prompts don't perpetually defer the schedule.

Why UserPromptSubmit rather than Stop: Meridian is wildcard-excluded ("*") from
every Stop handler (a deliberate "do not interrupt" protection), which would make
a Stop handler inert for it. Meridian has no UserPromptSubmit exclusion, so this
fires normally here. It injects nothing and returns allow — it never alters or
blocks the prompt.

Does NOT re-arm on the reflection prompt itself. The reflection job sends the
reflection text to Meridian, which would fire this very hook — and since the job
has just self-disabled, that would re-arm immediately (not wanted). We detect it:
if the incoming prompt contains the reflection's own opening line (read live from
meridian_reflection.md, so it stays correct if the file is edited), we skip.
Genuine prompts still re-arm.

Detached / fire-and-forget: the reset runs in its own session (start_new_session)
so it never delays Meridian's prompt. The real logic lives in
scripts/scheduling/meridian_reflection/reset_schedule.py.
"""

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

MERIDIAN_TRACKING_ID = "20260423_045650_app3020c_cla"
BASE = Path.home() / "AI/ai_root/ai_general/scripts/scheduling/meridian_reflection"
RESET = BASE / "reset_schedule.py"
REFLECTION_PROMPT = Path.home() / "AI/ai_root/ai_general/prompts/reflections/meridian_reflection.md"
VENV_PY = Path.home() / "myenv/ai_venv/bin/python3"


def _is_reflection_prompt(prompt):
    """True if `prompt` is the auto-sent reflection (so we must NOT re-arm on it).

    Signature = the first non-empty line of the live reflection file. Both the
    sender and this check read the same file, so edits can't desync them. A
    send_prompt 'From:' prefix or trailing whitespace doesn't matter — we look
    for the signature as a substring."""
    if not prompt:
        return False
    try:
        for line in REFLECTION_PROMPT.read_text().splitlines():
            sig = line.strip()
            if sig:
                return sig in prompt
    except OSError:
        pass
    return False


def handler(hook_input, context):
    if context.tracking_id != MERIDIAN_TRACKING_ID:
        return HookResult.skip("not meridian")
    if _is_reflection_prompt(hook_input.get("prompt", "")):
        return HookResult.skip("reflection prompt — not a re-arm trigger")
    if not RESET.exists():
        return HookResult.error("reset script missing: {}".format(RESET))
    py = str(VENV_PY) if VENV_PY.exists() else sys.executable
    try:
        subprocess.Popen([py, str(RESET)],
                         stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         start_new_session=True)
    except Exception as e:
        return HookResult.error("reset failed: {}".format(e))
    return HookResult.allow("meridian reflection schedule checked/re-armed")


if __name__ == "__main__":
    sys.exit(run_hook("meridian_reflection_reset", "UserPromptSubmit", handler))
