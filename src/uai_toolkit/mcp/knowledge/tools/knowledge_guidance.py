"""
Knowledge tool module -- guidance tools.

Extracted from mcps/guidance/server.py.
Delivers traits, roles, skills, profiles, and knowledge on demand.

Calls guidance_cli.py via subprocess instead of importing guidance_lib directly.
"""

import os
import subprocess
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

AI_ROOT = Path(os.environ.get("AI_ROOT", Path(__file__).resolve().parents[5]))
GUIDANCE_CLI = AI_ROOT / "ai_general" / "scripts" / "context_files" / "guidance_cli.py"


def _run_cli(subcommand, args=None):
    """Run guidance_cli.py and return stdout."""
    from uai_toolkit.mcp.shared.subprocess_log import logged_run
    cmd = [sys.executable, str(GUIDANCE_CLI), subcommand] + (args or [])
    result = logged_run("knowledge", cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        return result.stderr.strip() or f"Error (exit {result.returncode})"
    return result.stdout.strip()


def tools() -> list:
    return [
        Tool(name="knowledge_get_context",
             description=(
                 "Load context by reference. Resolves any identifier: role name, skill name, "
                 "context-file id/name/alias, profile name, knowledge topic, or 'globals' (all global context files) "
                 "or 'globals/<name>' (specific global). "
                 "Resolution order: id -> alias -> name -> path -> FTS. "
                 "The 'load' parameter uniformly controls reference expansion for ANY item type: "
                 "'none' returns the item's own content only (role definition, profile's role list, or a "
                 "context file's text); 'direct' adds the items it directly references (one hop); "
                 "'recursive' (default) adds the full transitive closure, deduped — e.g. a profile expands "
                 "to its roles and all their context files. Pass one or more references to load."
             ),
             inputSchema={"type": "object", "properties": {
                 "references": {"type": "array", "items": {"type": "string"},
                                "description": "Context references to load (role names, skill names, context-file ids, profile names, knowledge topics)"},
                 "load": {"type": "string", "enum": ["none", "direct", "recursive"], "default": "recursive",
                          "description": "Reference-expansion depth: none (item only), direct (one hop), recursive (full closure, default)"},
             }, "required": ["references"]}),
        Tool(name="knowledge_list_context",
             description=(
                 "List available context items. Filter by type (roles, skills, traits, profiles, topics) "
                 "and/or category."
             ),
             inputSchema={"type": "object", "properties": {
                 "type": {"type": "string",
                          "description": "What to list: globals, roles, skills, traits, profiles, topics, or all (default: all)",
                          "enum": ["globals", "roles", "skills", "traits", "profiles", "topics", "all"]},
                 "category": {"type": "string",
                              "description": "Filter by category (e.g., 'knowledge', 'procedures', 'methods')"},
             }, "required": []}),
        Tool(name="knowledge_how_to",
             description="Natural language search across all traits, skills, and knowledge.",
             inputSchema={"type": "object", "properties": {
                 "query": {"type": "string", "description": "Natural language question"},
             }, "required": ["query"]}),
        Tool(name="knowledge_remind_me",
             description="Get configured reminders with dynamic variables resolved.",
             inputSchema={"type": "object", "properties": {}, "required": []}),
        Tool(name="knowledge_get_references",
             description="Show what an item references and what references it.",
             inputSchema={"type": "object", "properties": {
                 "id": {"type": "string", "description": "Item id"},
             }, "required": ["id"]}),
        Tool(name="knowledge_get_stale",
             description="Find items not updated in N days.",
             inputSchema={"type": "object", "properties": {
                 "days": {"type": "integer", "description": "Days since last update (default: 90)"},
                 "category": {"type": "string", "description": "Optional category filter"},
             }, "required": []}),
        Tool(name="knowledge_guidance_search",
             description="Rich filtered search across all items by category, status, text.",
             inputSchema={"type": "object", "properties": {
                 "query": {"type": "string", "description": "Search text"},
                 "category": {"type": "string", "description": "Filter by category"},
                 "status": {"type": "string", "description": "Filter by status"},
                 "item_type": {"type": "string", "description": "Filter by type (trait|role|skill|profile)"},
             }, "required": []}),
    ]


# Map from tool name back to CLI subcommand
_NAME_MAP = {
    "knowledge_get_context": "get_context",
    "knowledge_list_context": "list_context",
    "knowledge_how_to": "how_to",
    "knowledge_remind_me": "remind_me",
    "knowledge_get_references": "get_references",
    "knowledge_get_stale": "get_stale",
    "knowledge_guidance_search": "search",
    # Legacy names — still dispatched correctly
    "knowledge_get_role": "get_context",
    "knowledge_get_skill": "get_context",
    "knowledge_get_trait": "get_context",
    "knowledge_get_profile": "get_context",
    "knowledge_get_knowledge": "get_context",
    "knowledge_get_knowledge_topics": "list_context",
    "knowledge_list_roles": "list_context",
    "knowledge_list_skills": "list_context",
    "knowledge_list_profiles": "list_context",
    "knowledge_list_traits": "list_context",
}


def _build_cli_args(subcommand, arguments, original_name=""):
    """Build CLI argument list for a given subcommand and MCP arguments dict."""
    if subcommand == "get_context":
        # Unified get: extract references from various input shapes
        refs = arguments.get("references", [])
        if not refs:
            # Legacy compatibility: extract from old parameter names
            if arguments.get("name"):
                refs = [arguments["name"]]
            elif arguments.get("identifier"):
                refs = [arguments["identifier"]]
            elif arguments.get("topics"):
                refs = list(arguments["topics"])
        cli = list(refs)
        load = arguments.get("load")
        if load in ("none", "direct", "recursive"):
            cli += ["--load", load]
        return cli
    elif subcommand == "list_context":
        args = []
        # Determine type from arguments or legacy tool name
        list_type = arguments.get("type", "all")
        if list_type == "all" and original_name:
            # Infer from legacy tool name
            if "roles" in original_name:
                list_type = "roles"
            elif "skills" in original_name:
                list_type = "skills"
            elif "profiles" in original_name:
                list_type = "profiles"
            elif "traits" in original_name:
                list_type = "traits"
            elif "topics" in original_name or "knowledge_topics" in original_name:
                list_type = "topics"
        if list_type and list_type != "all":
            args += ["--type", list_type]
        if arguments.get("category"):
            args += ["--category", arguments["category"]]
        if arguments.get("status"):
            args += ["--status", arguments["status"]]
        return args
    elif subcommand == "how_to":
        return [arguments["query"]]
    elif subcommand == "remind_me":
        return []
    elif subcommand == "get_references":
        return [arguments["id"]]
    elif subcommand == "get_stale":
        args = []
        if arguments.get("days") is not None:
            args += ["--days", str(arguments["days"])]
        if arguments.get("category"):
            args += ["--category", arguments["category"]]
        return args
    elif subcommand == "search":
        args = []
        if arguments.get("query"):
            args.append(arguments["query"])
        if arguments.get("category"):
            args += ["--category", arguments["category"]]
        if arguments.get("status"):
            args += ["--status", arguments["status"]]
        if arguments.get("item_type"):
            args += ["--item-type", arguments["item_type"]]
        return args
    else:
        return []


async def call_tool(name: str, arguments: dict) -> list:
    if name not in _NAME_MAP:
        return None

    try:
        subcommand = _NAME_MAP[name]
        cli_args = _build_cli_args(subcommand, arguments, original_name=name)
        text = _run_cli(subcommand, cli_args)
        return [TextContent(type="text", text=text)]
    except subprocess.TimeoutExpired:
        return [TextContent(type="text", text="Error: guidance_cli.py timed out after 30s")]
    except Exception as e:
        return [TextContent(type="text", text=f"Error: {e}")]
