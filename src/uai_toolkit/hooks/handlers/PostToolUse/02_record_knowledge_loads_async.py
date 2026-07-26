#!/usr/bin/env python3
"""PostToolUse handler — record knowledge/guidance loads to session state.

Records what a session pulled into context to the loaded.manifest key, from
either source:
  - any knowledge_get_* MCP call (by reference name/topic), or
  - a direct Read of a guarded context dir (by AI_ROOT-relative path).

The latter replaces the retired force-MCP PreToolUse block: raw Reads of
session_briefs / ai_traits / ai_context_files / ai_profiles / working_memory
are now allowed, and tracked here instead of forbidden.

Async handler — fire-and-forget, never blocks.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult
from uai_toolkit.hooks.common.lib_session_state_union import read_union, write_session_state  # session-state bridge (todo_0495)

TRACKED_TOOLS = {
    "knowledge_get_context": "context",
    # Legacy tool names still tracked
    "knowledge_get_role": "role",
    "knowledge_get_trait": "trait",
    "knowledge_get_skill": "skill",
    "knowledge_get_profile": "profile",
    "knowledge_get_knowledge": "knowledge",
}

# Direct Reads of these dirs (relative to AI_ROOT) are ALLOWED — the old
# PreToolUse force-MCP block that forbade them is gone. Tracking moved here so a
# raw Read of a context file still lands in loaded.manifest (keyed by
# AI_ROOT-relative path), instead of only knowledge_get_context calls showing up.
AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
GUARDED_READ_TYPES = {
    "ai_general/data/session_briefs": "brief",
    "ai_general/ai_traits": "trait",
    "ai_general/ai_context_files": "context",
    "ai_general/ai_profiles": "profile",
    "ai_memories/80_working_memory": "memory",
}
# Filenames that carry no context-load meaning even inside guarded dirs.
UNTRACKED_READ_FILENAMES = {"DESIGN.md", "README.md", "manifest.yml"}


def _match_tool(tool_name):
    """Match tool_name against TRACKED_TOOLS, handling MCP prefix.

    Claude Code sends 'mcp__knowledge__knowledge_get_role' but we
    track 'knowledge_get_role'.
    """
    if tool_name in TRACKED_TOOLS:
        return tool_name
    # Strip MCP prefix: mcp__<server>__<tool> → <tool>
    if tool_name.startswith("mcp__"):
        bare = tool_name.split("__", 2)[-1]
        if bare in TRACKED_TOOLS:
            return bare
    return None


def _guarded_read_load(hook_input, raw_tool_name):
    """If this is a direct Read of a guarded context file, return
    (load_type, AI_ROOT-relative-path); else (None, None). Covers exactly the
    dirs the retired force-MCP PreToolUse block used to guard."""
    if raw_tool_name != "Read" and not raw_tool_name.endswith("__Read"):
        return None, None
    file_path = hook_input.get("tool_input", {}).get("file_path", "")
    if not file_path or Path(file_path).name in UNTRACKED_READ_FILENAMES:
        return None, None
    try:
        rel = str(Path(file_path).resolve().relative_to(AI_ROOT.resolve()))
    except (ValueError, OSError):
        return None, None
    for prefix, load_type in GUARDED_READ_TYPES.items():
        if rel.startswith(prefix):
            return load_type, rel
    return None, None


def handler(hook_input, context):
    raw_tool_name = hook_input.get("tool_name", "")

    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")

    now = datetime.now().isoformat()

    # Two sources feed loaded.manifest:
    #   (1) knowledge_get_* MCP calls — recorded by reference name/topic.
    #   (2) direct Read of a guarded context dir — recorded by AI_ROOT-relative
    #       path (the force-MCP block that used to forbid these reads is gone).
    tool_name = _match_tool(raw_tool_name)
    read_type, read_relpath = _guarded_read_load(hook_input, raw_tool_name)

    if tool_name:
        # Different tools use different param names:
        #   get_context: "references" (array)
        #   role/skill/profile: "name"; trait: "identifier"; knowledge: "topics"
        tool_input = hook_input.get("tool_input", {})
        loaded_name = tool_input.get("name") or tool_input.get("identifier") or tool_input.get("topic") or tool_input.get("query") or ""
        topics = tool_input.get("references") or tool_input.get("topics") or []
        if not loaded_name and not topics:
            return HookResult.skip("no name/topic in tool input")

        # Don't record a failed load.
        tool_result = hook_input.get("tool_result", "")
        if isinstance(tool_result, str) and (tool_result.startswith("[Role not found")
                or tool_result.startswith("[Trait not found") or tool_result.startswith("Error")):
            return HookResult.skip(f"tool returned error for {loaded_name}")

        load_type = TRACKED_TOOLS[tool_name]
        src = tool_name
        update_lists = True  # role/trait comma-lists take clean identifiers
        # references[] (knowledge_get_context) and topics[] (knowledge_get_knowledge)
        # both arrive in `topics`; record whenever present, regardless of load_type.
        # (Previously gated on load_type=="knowledge", which silently dropped every
        # knowledge_get_context load — the primary tool.)
        if topics:
            names_to_record = [t for t in topics if isinstance(t, str) and t.strip()]
        elif loaded_name:
            names_to_record = [loaded_name]
        else:
            names_to_record = []
    elif read_type:
        load_type = read_type
        src = "Read"
        update_lists = False  # a path is not a clean identifier — manifest only
        names_to_record = [read_relpath]
    else:
        return HookResult.skip("not a tracked load")

    if not names_to_record:
        return HookResult.skip("nothing to record")

    # Read current state (union) and update loaded.manifest + the flat lists.
    state = read_union(context.session_dir, context.tracking_id)

    manifest_raw = state.get("loaded.manifest", "[]")
    try:
        manifest = json.loads(manifest_raw) if isinstance(manifest_raw, str) else manifest_raw
    except (json.JSONDecodeError, TypeError):
        manifest = []

    if not isinstance(manifest, list):
        manifest = []

    # Track the flat comma-lists locally so the write below is TARGETED (never a
    # whole-state writeback, which would copy canonical keys into legacy — todo_0495).
    roles = [r.strip() for r in state.get("loaded.roles", "").split(",") if r.strip()]
    traits = [t.strip() for t in state.get("loaded.traits", "").split(",") if t.strip()]
    roles_changed = traits_changed = False

    recorded = []
    for name in names_to_record:
        # Check for duplicates — don't record the same load twice
        if any(e.get("type") == load_type and e.get("name") == name for e in manifest):
            continue

        manifest.append({
            "type": load_type,
            "name": name,
            "src": src,
            "at": now,
        })

        # Maintain the flat comma-lists only for clean identifier loads (knowledge
        # tools) — a guarded Read records a path, which doesn't belong in these.
        if update_lists and load_type == "role":
            if name not in roles:
                roles.append(name)
                roles_changed = True
        elif update_lists and load_type == "trait":
            if name not in traits:
                traits.append(name)
                traits_changed = True

        recorded.append(name)

    if not recorded:
        return HookResult.allow(f"already recorded: {load_type}/{','.join(names_to_record)}")

    updates = {"loaded.manifest": json.dumps(manifest), "updated_at": now}
    if roles_changed:
        updates["loaded.roles"] = ",".join(roles)
    if traits_changed:
        updates["loaded.traits"] = ",".join(traits)
    write_session_state(context.session_dir, context.tracking_id, updates)
    return HookResult.allow(f"recorded {load_type}: {','.join(recorded)}")


if __name__ == "__main__":
    sys.exit(run_hook("record_knowledge_loads", "PostToolUse", handler))
