#!/usr/bin/env python3
"""UserPromptSubmit hook — deliver pending context from the context_to_load/ inbox.

A thin driver: it hands the session's context_to_load/ inbox to the shared
loader (common/lib_context_load.drain) and injects whatever came back as
additionalContext. It has NO type-specific logic — whatever is in the directory
loads, whatever is not, does not. SessionStart uses the same loader.

Stage entries via:
  - stage_context.py / load_context.py (raw files or .ref pointers)
  - a .ref drop into <session_dir>/context_to_load/ (resolved via the knowledge
    loader — see lib_context_load)
  - a direct file/symlink drop
"""

import json
import sys
from pathlib import Path

_COMMON = Path(__file__).resolve().parent.parent / "common"
sys.path.insert(0, str(_COMMON))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common import lib_context_load


def _fmt_size(nbytes):
    """Human-readable byte size for the terminal marker."""
    if nbytes < 1024:
        return "{} B".format(nbytes)
    kb = nbytes / 1024.0
    if kb < 1024:
        return "{:.0f} KB".format(kb) if kb >= 10 else "{:.1f} KB".format(kb)
    return "{:.1f} MB".format(kb / 1024.0)


def _marker_line(stem, content, source):
    """One visible line per delivered item: what loaded and how big. Briefs
    (staged from session_briefs/) are labeled 'brief'; everything else 'context'."""
    src = (source or "").lower()
    name = str(stem or "")
    # Durable post-compaction reloads are queued as
    # 50_reload__<type>__<semantic-name>.ref. Show the semantic name/type rather
    # than leaking that internal priority prefix into the user's terminal.
    if name.startswith("50_reload__"):
        reload_type, sep, reload_name = name[len("50_reload__"):].partition("__")
        if sep:
            name = reload_name
            kind = "brief" if reload_type.rstrip("s") == "brief" else "context"
        else:
            kind = "context"
    else:
        kind = "brief" if (
            "session_briefs" in src
            or "auto_briefs" in src
            or src.startswith(("brief/", "briefs/"))
        ) else "context"
    name = " ".join(name.split()) or "(unnamed)"
    size = _fmt_size(len((content or "").encode("utf-8")))
    return "\U0001F4C4 {} loaded: {} ({})".format(kind, name, size)


def handler(hook_input, context):
    session_dir = context.session_dir
    tracking_id = context.tracking_id
    if not session_dir or not tracking_id:
        return HookResult.skip("no session identity")

    delivered = lib_context_load.drain(session_dir, tracking_id)
    if not delivered:
        return HookResult.skip("nothing pending in context_to_load")

    sections = [
        f"--- Context: {stem} (from {source}) ---\n{content}\n--- End: {stem} ---"
        for stem, content, source in delivered
    ]
    instruction = (
        f"The following {len(sections)} context file(s) were staged for loading "
        f"into this session. This is reference context — absorb it silently.\n\n"
        + "\n\n".join(sections)
    )
    # additionalContext feeds the brief into the model silently; systemMessage
    # prints a one-line-per-item marker to the USER's terminal so a brief reload
    # after a compaction is visible, not invisible (PianoMan, 2026-07-23).
    marker = "\n".join(_marker_line(stem, content, source)
                       for stem, content, source in delivered)
    output = json.dumps({
        "systemMessage": marker,
        "hookSpecificOutput": {
            "hookEventName": "UserPromptSubmit",
            "additionalContext": instruction,
        }
    })
    names = ", ".join(stem for stem, _, _ in delivered)
    return HookResult.output(output, f"delivered {len(delivered)} context items: {names}")


if __name__ == "__main__":
    sys.exit(run_hook("deliver_pending_context", "UserPromptSubmit", handler))
