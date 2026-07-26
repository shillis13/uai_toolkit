#!/usr/bin/env python3
"""PreToolUse hook — guard MEMORY.md (the Claude auto-memory index).

MEMORY.md is NOT the memory store and must stay tiny + static. Memory belongs in
the scaffolding working-memory slots, written via the knowledge MCP tools
(``knowledge_memory_append`` / ``_read`` / ``_search``). This hook DENIES a
Write/Edit to any ``…/.claude/projects/*/memory/MEMORY.md`` and redirects the
session to the tools, staging the ``working_memory`` bundle (the memory how-to)
so it loads on the next turn.

Exception: a deliberate, sanctioned MEMORY.md edit is allowed when the session
sets ``AI_ALLOW_MEMORY_MD_EDIT=1`` (e.g. the migration/shrink work itself).

Scope note: this matches MEMORY.md only (the index that bloats), not the
individual memory files — those are separate content, left writable for now.
"""

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult  # noqa: E402

_WRITE_TOOLS = ("Edit", "Write", "MultiEdit", "apply_patch")


def _is_memory_md(path: str) -> bool:
    """True iff path is a Claude auto-memory index (…/.claude/projects/*/memory/MEMORY.md)."""
    p = (path or "").replace("\\", "/")
    return "/.claude/projects/" in p and p.endswith("/memory/MEMORY.md")


def handler(hook_input, context):
    tool_name = hook_input.get("tool_name", "")
    if tool_name not in _WRITE_TOOLS:
        return HookResult.skip(f"not a write tool ({tool_name})")

    file_path = hook_input.get("tool_input", {}).get("file_path", "")
    if not _is_memory_md(file_path):
        return HookResult.skip("not MEMORY.md")

    # Deliberate, sanctioned exception (migration/shrink or an intentional edit).
    if os.environ.get("AI_ALLOW_MEMORY_MD_EDIT", "").lower() in ("1", "true", "yes"):
        return HookResult.allow("AI_ALLOW_MEMORY_MD_EDIT set — sanctioned MEMORY.md edit")

    # Auto-load the memory guide (working_memory bundle) on the next turn.
    staged = "not staged"
    try:
        if context.session_dir:
            _cli = str(Path(__file__).resolve().parents[3] / "scripts" / "cli")
            if _cli not in sys.path:
                sys.path.insert(0, _cli)
            from uai_toolkit.cli.stage_context import stage_ref
            stage_ref(context.session_dir, "bundle", "working_memory")
            staged = "staged working_memory bundle"
    except Exception as e:  # best-effort; the deny reason still redirects
        staged = f"stage failed: {e}"

    reason = (
        "MEMORY.md is not the memory store — it stays tiny and static. Record memory "
        "in the scaffolding working-memory slots via the knowledge MCP tools: "
        "knowledge_memory_append(slot, content) to write, knowledge_memory_read / "
        "knowledge_memory_search to read. (The working_memory guide is being loaded "
        "for you.) If this is a genuinely sanctioned MEMORY.md change, set "
        "AI_ALLOW_MEMORY_MD_EDIT=1 and retry."
    )
    result = json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    })
    return HookResult.block(result, f"blocked MEMORY.md write | {staged}")


if __name__ == "__main__":
    sys.exit(run_hook("guard_memory_md", "PreToolUse", handler))
