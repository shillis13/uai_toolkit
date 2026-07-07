#!/usr/bin/env python3
"""SessionStart hook — inject session context directly as additionalContext.

Reads and injects immediately (not deferred to first prompt):
  1. All files in ai_context_files/globals/ (global context for every session)
  2. All files in ai_context_files/platforms/<platform>/ (platform-specific)
  3. Roles defined in session store (resolved via guidance_cli)
  4. Anything pending in <session_dir>/context_to_load/ — drained by the same
     shared driver UserPromptSubmit uses (common/lib_context_load). Briefs are
     NOT re-loaded from state: if it's in the directory it loads, else it doesn't.

Files and symlinks in the context dirs are read in sorted order.
Content is injected directly into the session via additionalContext output,
making it available before the first user prompt.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common import lib_context_load

AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI" / "ai_root"))
AI_GENERAL = AI_ROOT / "ai_general"
CONTEXT_FILES_DIR = AI_GENERAL / "ai_context_files"

MAX_TOTAL_CHARS = 200_000

# Platform env var → platform dir name
PLATFORM_DIRS = {
    "claude_cli": "claude_code",
    "codex_cli": "codex",
    "gemini_cli": "gemini",
}


def _get_platform():
    platform = os.environ.get("AI_SESSION_PLATFORM", "")
    if platform:
        return platform
    tid = os.environ.get("AI_TRACKING_ID", "")
    if tid and "_" in tid:
        suffix = tid.rsplit("_", 1)[-1]
        return {"cla": "claude_cli", "cod": "codex_cli", "gem": "gemini_cli"}.get(suffix, "")
    return ""


def _read_dir_files(directory):
    """Read all text files/symlinks in a directory, sorted by name.

    Returns list of (filename, content) tuples.
    """
    results = []
    if not directory.is_dir():
        return results
    for entry in sorted(directory.iterdir()):
        if entry.name.startswith("."):
            continue
        if entry.is_file() or entry.is_symlink():
            try:
                resolved = entry.resolve()
                if resolved.exists():
                    content = resolved.read_text(encoding="utf-8", errors="replace")
                    results.append((entry.name, content))
            except (OSError, UnicodeDecodeError):
                pass
    return results


def handler(hook_input, context):
    source = hook_input.get("source", "")
    if source in ("clear", "compact"):
        return HookResult.skip("source is clear/compact")

    tracking_id = context.tracking_id
    session_dir = context.session_dir
    if not tracking_id:
        return HookResult.skip("no tracking_id")

    sections = []
    loaded_names = []
    total_chars = 0

    # 1. Global context files
    globals_dir = CONTEXT_FILES_DIR / "globals"
    for name, content in _read_dir_files(globals_dir):
        if total_chars + len(content) > MAX_TOTAL_CHARS:
            break
        sections.append(f"--- Global Context: {name} ---\n{content}\n--- End: {name} ---")
        total_chars += len(content)
        loaded_names.append(f"global/{name}")

    # 2. Platform-specific context files
    platform = _get_platform()
    if platform and platform in PLATFORM_DIRS:
        platform_dir = CONTEXT_FILES_DIR / "platforms" / PLATFORM_DIRS[platform]
        for name, content in _read_dir_files(platform_dir):
            if total_chars + len(content) > MAX_TOTAL_CHARS:
                break
            sections.append(f"--- Platform Context ({platform}): {name} ---\n{content}\n--- End: {name} ---")
            total_chars += len(content)
            loaded_names.append(f"platform/{name}")

    # 3. Roles from session store (skip 'assistant' — implicit base role)
    _sm = AI_GENERAL / "scripts" / "session_mgmt"
    if str(_sm) not in sys.path:
        sys.path.insert(0, str(_sm))
    try:
        from uai_toolkit.session_mgmt.session_store import SessionStore
        store = SessionStore()
        session = store.get(tracking_id)
        if session:
            roles = session.get("roles") or []
            for role in roles:
                if role and role != "assistant":
                    content = lib_context_load._resolve_via_guidance(role, tracking_id)
                    if content and total_chars + len(content) <= MAX_TOTAL_CHARS:
                        sections.append(f"--- Role: {role} ---\n{content}\n--- End Role: {role} ---")
                        total_chars += len(content)
                        loaded_names.append(f"role/{role}")
    except Exception:
        pass

    # 4. Pending context staged in context_to_load/ — drained by the SAME
    #    generic driver UserPromptSubmit uses (common/lib_context_load). No
    #    type-specific or re-load logic: if something is in the directory it
    #    loads (a self-compact brief .ref, a resume bundle, etc.); if not, it
    #    doesn't. Briefs are NOT re-loaded from session state.
    if session_dir:
        for stem, content, source in lib_context_load.drain(
            session_dir, tracking_id, max_chars=MAX_TOTAL_CHARS - total_chars
        ):
            sections.append(f"--- Context: {stem} (from {source}) ---\n{content}\n--- End: {stem} ---")
            total_chars += len(content)
            loaded_names.append(f"context/{stem}")

    if not sections:
        return HookResult.allow("no context to inject")

    combined = "\n\n".join(sections)
    output = json.dumps({"hookSpecificOutput": {"additionalContext": combined}})
    return HookResult.output(output, f"injected {len(sections)} context items: {', '.join(loaded_names)}")


if __name__ == "__main__":
    sys.exit(run_hook("stage_session_context", "SessionStart", handler))
