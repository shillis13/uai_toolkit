#!/usr/bin/env python3
"""PostToolUse handler — record knowledge/guidance loads to session state.

When any knowledge_get_* tool is called, records what was loaded to the
session state loaded.manifest key. This ensures all trait/role/skill/profile
loads are tracked regardless of which path the AI used.

Async handler — fire-and-forget, never blocks.
"""

import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "common"))
from uai_toolkit.hooks.common.lib_hook_base import run_hook, HookResult

TRACKED_TOOLS = {
    "knowledge_get_context": "context",
    # Legacy tool names still tracked
    "knowledge_get_role": "role",
    "knowledge_get_trait": "trait",
    "knowledge_get_skill": "skill",
    "knowledge_get_profile": "profile",
    "knowledge_get_knowledge": "knowledge",
}


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


def read_state(path):
    if path.exists():
        try:
            return json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            pass
    return {}


def write_state(path, state):
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2))
        tmp.rename(path)
    except OSError:
        pass


def handler(hook_input, context):
    raw_tool_name = hook_input.get("tool_name", "")
    tool_name = _match_tool(raw_tool_name)
    if not tool_name:
        return HookResult.skip("not a knowledge load tool")

    if not context.tracking_id or not context.session_dir:
        return HookResult.skip("no session identity")

    # Extract what was loaded from tool_input
    tool_input = hook_input.get("tool_input", {})

    # Different tools use different param names:
    #   get_context: "references" (array)
    #   role/skill/profile: "name"
    #   trait: "identifier"
    #   knowledge: "topics" (array)
    loaded_name = tool_input.get("name") or tool_input.get("identifier") or tool_input.get("topic") or tool_input.get("query") or ""
    topics = tool_input.get("references") or tool_input.get("topics") or []

    if not loaded_name and not topics:
        return HookResult.skip("no name/topic in tool input")

    load_type = TRACKED_TOOLS[tool_name]
    now = datetime.now().isoformat()

    # Check if the tool succeeded (tool_result should not contain error)
    tool_result = hook_input.get("tool_result", "")
    if isinstance(tool_result, str) and tool_result.startswith("[Role not found") or \
       isinstance(tool_result, str) and tool_result.startswith("[Trait not found") or \
       isinstance(tool_result, str) and tool_result.startswith("Error"):
        return HookResult.skip(f"tool returned error for {loaded_name}")

    # Read current state and update loaded.manifest
    state_path = Path(context.session_dir) / f"{context.tracking_id}_state.json"
    state = read_state(state_path)

    manifest_raw = state.get("loaded.manifest", "[]")
    try:
        manifest = json.loads(manifest_raw) if isinstance(manifest_raw, str) else manifest_raw
    except (json.JSONDecodeError, TypeError):
        manifest = []

    if not isinstance(manifest, list):
        manifest = []

    # Build list of names to record (knowledge_get_knowledge sends topics array)
    names_to_record = []
    if topics and load_type == "knowledge":
        names_to_record = [t for t in topics if isinstance(t, str) and t.strip()]
    elif loaded_name:
        names_to_record = [loaded_name]

    recorded = []
    for name in names_to_record:
        # Check for duplicates — don't record the same load twice
        already = False
        for entry in manifest:
            if entry.get("type") == load_type and entry.get("name") == name:
                already = True
                break
        if already:
            continue

        manifest.append({
            "type": load_type,
            "name": name,
            "src": tool_name,
            "at": now,
        })

        # Also update the type-specific loaded.* keys
        if load_type == "role":
            existing_roles = state.get("loaded.roles", "")
            roles = [r.strip() for r in existing_roles.split(",") if r.strip()] if existing_roles else []
            if name not in roles:
                roles.append(name)
                state["loaded.roles"] = ",".join(roles)
        elif load_type == "trait":
            existing = state.get("loaded.traits", "")
            traits = [t.strip() for t in existing.split(",") if t.strip()] if existing else []
            if name not in traits:
                traits.append(name)
                state["loaded.traits"] = ",".join(traits)

        recorded.append(name)

    if not recorded:
        return HookResult.allow(f"already recorded: {load_type}/{','.join(names_to_record)}")

    state["loaded.manifest"] = json.dumps(manifest)
    state["updated_at"] = now
    write_state(state_path, state)
    return HookResult.allow(f"recorded {load_type}: {','.join(recorded)}")


if __name__ == "__main__":
    sys.exit(run_hook("record_knowledge_loads", "PostToolUse", handler))
