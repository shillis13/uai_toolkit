"""
Sessions tool module — session (per-CLI state) tools.

Thin subprocess wrapper around session_mgr.py.
Each tool call invokes session_mgr.py with the appropriate subcommand.
Session state persists to disk; no in-process state needed.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

AI_ROOT = Path(os.environ.get("AI_ROOT", Path(__file__).resolve().parents[5]))
SESSION_MGR = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "session_mgr.py"
TRACKING_ID = os.environ.get("AI_TRACKING_ID", "")
SESSION_DIR = os.environ.get("AI_SESSION_DIR", "")

# Path to reserved key registry
_REGISTRY_PATH = (
    Path.home() / "AI" / "ai_root"
    / "ai_general" / "ai_context_files" / "knowledge"
    / "schemas" / "schema_session_state_keys.yml"
)

STATE_PREFIX = "sessions_state_"
PREFIX = "sessions_"

# Deprecated alias mapping
_DEPRECATED_ALIASES = {
    "sessions_set": "sessions_state_set",
    "sessions_get": "sessions_state_get",
    "sessions_remove": "sessions_state_remove",
    "sessions_list": "sessions_state_list",
}


def _run_mgr(subcommand, extra_args=None, timeout=10):
    """Run session_mgr.py and return stdout."""
    from uai_toolkit.mcp.shared.subprocess_log import logged_run
    cmd = [sys.executable, str(SESSION_MGR), subcommand, TRACKING_ID]
    if SESSION_DIR:
        cmd += ["--data-dir", SESSION_DIR]
    if extra_args:
        cmd += extra_args
    result = logged_run("sessions", cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        return json.dumps({"error": result.stderr.strip() or "exit %d" % result.returncode})
    return result.stdout.strip()


def _load_registry_keys(namespace=None):
    """Load reserved key definitions from the YAML registry."""
    if not _REGISTRY_PATH.exists():
        return []
    try:
        import yaml
        with open(str(_REGISTRY_PATH)) as f:
            data = yaml.safe_load(f)
    except ImportError:
        return []
    except Exception:
        return []
    if not data:
        return []
    entries = data.get("reserved_keys", [])
    result = []
    for entry in entries:
        key = entry.get("key", "")
        if not key:
            continue
        if namespace:
            ns_prefix = namespace.rstrip(".") + "."
            if "." in key:
                if not key.startswith(ns_prefix):
                    continue
            else:
                continue
        result.append({
            "key": key,
            "type": entry.get("type", "str"),
            "writer": entry.get("writer", "unknown"),
            "description": entry.get("description", ""),
            "dedicated_tool": entry.get("dedicated_tool"),
        })
    return result


def tools():
    result = []

    result.append(Tool(
        name="{}get".format(STATE_PREFIX),
        description="Get a session state value by key.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "State key to retrieve"},
            },
            "required": ["key"],
        },
    ))
    result.append(Tool(
        name="{}set".format(STATE_PREFIX),
        description=(
            "Set a session state value. List keys (role, features) accept "
            "comma-separated values and merge with existing."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "State key"},
                "value": {"type": "string", "description": "Value to set"},
            },
            "required": ["key", "value"],
        },
    ))
    result.append(Tool(
        name="{}delete".format(STATE_PREFIX),
        description="Delete a key from session state.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "State key to delete"},
            },
            "required": ["key"],
        },
    ))
    result.append(Tool(
        name="{}increment".format(STATE_PREFIX),
        description="Add to a numeric session state key.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Numeric key to increment"},
                "amount": {"type": "number", "description": "Amount to add (default: 1)"},
            },
            "required": ["key"],
        },
    ))
    result.append(Tool(
        name="{}decrement".format(STATE_PREFIX),
        description="Subtract from a numeric session state key.",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "Numeric key to decrement"},
                "amount": {"type": "number", "description": "Amount to subtract (default: 1)"},
            },
            "required": ["key"],
        },
    ))
    result.append(Tool(
        name="{}list".format(STATE_PREFIX),
        description="List all session state key-value pairs. Optional prefix filter.",
        inputSchema={
            "type": "object",
            "properties": {
                "prefix": {"type": "string", "description": "Filter keys by prefix"},
            },
        },
    ))
    result.append(Tool(
        name="{}remove".format(STATE_PREFIX),
        description="Remove values from a list key (role, features).",
        inputSchema={
            "type": "object",
            "properties": {
                "key": {"type": "string", "description": "List key"},
                "value": {"type": "string", "description": "Comma-separated values to remove"},
            },
            "required": ["key", "value"],
        },
    ))
    result.append(Tool(
        name="{}keys".format(STATE_PREFIX),
        description="List reserved session state key names from the schema registry.",
        inputSchema={
            "type": "object",
            "properties": {
                "namespace": {"type": "string", "description": "Filter by namespace (e.g. 'context', 'env')"},
            },
        },
    ))
    result.append(Tool(
        name="{}persist".format(STATE_PREFIX),
        description="Save current session state to disk for later resume.",
        inputSchema={"type": "object", "properties": {}},
    ))
    result.append(Tool(
        name="{}load".format(STATE_PREFIX),
        description="Load previously persisted session state.",
        inputSchema={
            "type": "object",
            "properties": {
                "session_id": {"type": "string", "description": "Session ID to load (defaults to current)"},
            },
        },
    ))

    # Non-state tools
    result.append(Tool(
        name="{}get_ctx_used".format(PREFIX),
        description="Get context window usage from session state.",
        inputSchema={"type": "object", "properties": {}},
    ))
    result.append(Tool(
        name="{}get_footer".format(PREFIX),
        description="Get the formatted session response footer.",
        inputSchema={
            "type": "object",
            "properties": {
                "tags": {"type": "string", "description": "Comma-separated tags"},
                "mode": {"type": "string", "enum": ["brief", "full"], "description": "Footer verbosity: 'brief' for a compact one-line footer, 'full' for the expanded footer."},
            },
        },
    ))
    result.append(Tool(
        name="{}get_ai_root".format(PREFIX),
        description="Resolve the current AI_ROOT path.",
        inputSchema={"type": "object", "properties": {}},
    ))

    # Deprecated aliases
    for old_name, new_name in _DEPRECATED_ALIASES.items():
        result.append(Tool(
            name=old_name,
            description="[DEPRECATED: use {}] ".format(new_name),
            inputSchema={
                "type": "object",
                "properties": {
                    "key": {
                        "type": "string",
                        "description": (
                            "Session state key. DEPRECATED: this tool just forwards "
                            "to {0}; call {0} directly. (For the list variant the key "
                            "is ignored.)".format(new_name)
                        ),
                    },
                    "value": {
                        "type": "string",
                        "description": (
                            "Value for the state operation (used by the set/remove "
                            "variants; ignored by get/list). DEPRECATED: forwards to "
                            "{0}; call {0} directly.".format(new_name)
                        ),
                    },
                },
                "required": ["key"],
            },
        ))

    return result


async def call_tool(name, arguments):
    # Handle deprecated aliases
    if name in _DEPRECATED_ALIASES:
        new_name = _DEPRECATED_ALIASES[name]
        result = await _handle_tool(new_name, arguments)
        if result:
            result[0] = TextContent(
                type="text",
                text="[DEPRECATED] Use {} instead. ".format(new_name) + result[0].text,
            )
        return result
    return await _handle_tool(name, arguments)


async def _handle_tool(name, arguments):
    if name == "{}get".format(STATE_PREFIX):
        out = _run_mgr("state_get", [arguments["key"]])
        return [TextContent(type="text", text=out)]

    if name == "{}set".format(STATE_PREFIX):
        out = _run_mgr("state_set", [arguments["key"], arguments["value"]])
        return [TextContent(type="text", text=out)]

    if name == "{}delete".format(STATE_PREFIX):
        out = _run_mgr("state_delete", [arguments["key"]])
        return [TextContent(type="text", text=out)]

    if name == "{}increment".format(STATE_PREFIX):
        amount = str(arguments.get("amount", 1))
        out = _run_mgr("state_increment", [arguments["key"], amount])
        return [TextContent(type="text", text=out)]

    if name == "{}decrement".format(STATE_PREFIX):
        amount = str(arguments.get("amount", 1))
        out = _run_mgr("state_decrement", [arguments["key"], amount])
        return [TextContent(type="text", text=out)]

    if name == "{}list".format(STATE_PREFIX):
        args = []
        if arguments.get("prefix"):
            args += ["--prefix", arguments["prefix"]]
        out = _run_mgr("state_list", args)
        return [TextContent(type="text", text=out)]

    if name == "{}remove".format(STATE_PREFIX):
        out = _run_mgr("state_remove", [arguments["key"], arguments["value"]])
        return [TextContent(type="text", text=out)]

    if name == "{}keys".format(STATE_PREFIX):
        keys = _load_registry_keys(namespace=arguments.get("namespace"))
        return [TextContent(type="text", text=json.dumps(keys, indent=2))]

    if name == "{}persist".format(STATE_PREFIX):
        out = _run_mgr("state_persist")
        return [TextContent(type="text", text=out)]

    if name == "{}load".format(STATE_PREFIX):
        args = []
        if arguments.get("session_id"):
            args += ["--session-id", arguments["session_id"]]
        out = _run_mgr("state_load", args)
        return [TextContent(type="text", text=out)]

    if name == "{}get_ctx_used".format(PREFIX):
        out = _run_mgr("get_ctx_used")
        return [TextContent(type="text", text=out)]

    if name == "{}get_footer".format(PREFIX):
        args = []
        if arguments.get("tags"):
            args += ["--tags", arguments["tags"]]
        if arguments.get("mode"):
            args += ["--mode", arguments["mode"]]
        out = _run_mgr("get_footer", args)
        return [TextContent(type="text", text=out)]

    if name == "{}get_ai_root".format(PREFIX):
        out = _run_mgr("get_ai_root")
        return [TextContent(type="text", text=out)]

    return None
