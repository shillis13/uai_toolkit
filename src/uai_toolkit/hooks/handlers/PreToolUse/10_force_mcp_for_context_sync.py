#!/usr/bin/env python3
"""PreToolUse hook — block direct Read of context files; force MCP access.

Certain directories contain structured context that should be loaded via
the knowledge/guidance MCP tools (knowledge_get_context, knowledge_memory_read,
etc.) rather than raw file reads. This ensures consistent load-tracking,
session-state recording, and format normalization.

Blocked paths (relative to AI_ROOT):
  - ai_general/data/session_briefs/
  - ai_general/ai_traits/
  - ai_general/ai_context_files/
  - ai_general/ai_profiles/
  - ai_memories/80_working_memory/

Exceptions (never blocked):
  - DESIGN.md / README.md files (governed-doc reads must always work)
  - manifest.yml in working memory (bootstrap needs it)
  - Files outside AI_ROOT
  - Non-Read tool calls
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))

# Paths relative to AI_ROOT that require MCP access instead of direct Read
GUARDED_PREFIXES = [
    "ai_general/data/session_briefs",
    "ai_general/ai_traits",
    "ai_general/ai_context_files",
    "ai_general/ai_profiles",
    "ai_memories/80_working_memory",
]

# Filenames that are always allowed (even inside guarded dirs)
ALLOWED_FILENAMES = {
    "DESIGN.md",
    "README.md",
    "manifest.yml",
}

# MCP tool suggestions per guarded prefix
MCP_SUGGESTIONS = {
    "ai_general/data/session_briefs": "knowledge_get_context with the session brief name",
    "ai_general/ai_traits": "knowledge_get_context, knowledge_how_to, or knowledge_guidance_search",
    "ai_general/ai_context_files": "knowledge_get_context with the context file name",
    "ai_general/ai_profiles": "knowledge_get_context with the profile/role name",
    "ai_memories/80_working_memory": "knowledge_memory_read with the slot number",
}


def _resolve_relative(file_path):
    """Resolve a file path relative to AI_ROOT, following symlinks."""
    try:
        resolved = Path(file_path).resolve()
        ai_root_resolved = AI_ROOT.resolve()
        return str(resolved.relative_to(ai_root_resolved))
    except (ValueError, OSError):
        return None


def handler(hook_input, context):
    tool_name = hook_input.get("tool_name", "")
    if tool_name != "Read":
        return HookResult.skip("not a Read")

    file_path = hook_input.get("tool_input", {}).get("file_path", "")
    if not file_path:
        return HookResult.skip("no file_path")

    # Check if filename is in the always-allowed set
    filename = Path(file_path).name
    if filename in ALLOWED_FILENAMES:
        return HookResult.allow(f"allowed filename: {filename}")

    # Resolve to relative path within AI_ROOT
    rel_path = _resolve_relative(file_path)
    if rel_path is None:
        return HookResult.allow("outside AI_ROOT")

    # Check against each guarded prefix
    for prefix in GUARDED_PREFIXES:
        if rel_path.startswith(prefix):
            suggestion = MCP_SUGGESTIONS.get(prefix, "the appropriate knowledge MCP tool")
            return HookResult.block(
                f"BLOCKED: Direct Read of context files is not allowed.\n\n"
                f"  Path: {rel_path}\n"
                f"  Guarded directory: {prefix}/\n\n"
                f"Use {suggestion} instead of reading this file directly.\n"
                f"This ensures load-tracking and consistent context delivery.",
                f"guarded_context_read: {rel_path}"
            )

    return HookResult.allow()


if __name__ == "__main__":
    sys.exit(run_hook("force_mcp_for_context", "PreToolUse", handler))
