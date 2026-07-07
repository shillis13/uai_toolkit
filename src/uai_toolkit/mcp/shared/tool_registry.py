"""
Dynamic tool registry — loads MCP tool definitions from YAML files.

Each MCP server has a tools.yml in its directory that defines tool names,
descriptions, and input schemas. The registry loads these at tools/list time
(not at import time), enabling live renames without server restarts.

When tools.yml changes, the server sends a list_changed notification so
the AI client refreshes its tool list.

Usage in a server:

    from uai_toolkit.mcp.shared.tool_registry import ToolRegistry

    registry = ToolRegistry(server_dir=Path(__file__).parent, server=mcp_server)

    @server.list_tools()
    async def list_tools():
        return registry.list_tools()

    @server.call_tool()
    async def call_tool(name, arguments):
        handler_key = registry.get_handler_key(name)
        # dispatch to the right module/function using handler_key
"""

import copy
import hashlib
import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

import yaml
from mcp.types import Tool


def _sanitize_schema(schema):
    """Repair lossless, API-fatal JSON-Schema mistakes in place.

    Currently dedupes `required` arrays (order-preserving). The Anthropic API
    validates tool input schemas against JSON Schema draft 2020-12, whose
    meta-schema requires `required` to have unique items — a duplicate entry
    causes a hard 400 that takes down every session loading the tool.

    Returns True if anything was changed. Recurses through all standard
    subschema locations.
    """
    if not isinstance(schema, dict):
        return False
    modified = False

    req = schema.get("required")
    if isinstance(req, list):
        seen = set()
        deduped = [x for x in req if not (x in seen or seen.add(x))]
        if len(deduped) != len(req):
            schema["required"] = deduped
            modified = True

    for key in ("properties", "$defs", "definitions", "patternProperties"):
        sub = schema.get(key)
        if isinstance(sub, dict):
            for v in sub.values():
                modified = _sanitize_schema(v) or modified
    for key in ("items", "additionalProperties", "not", "if", "then", "else", "contains"):
        if _sanitize_schema(schema.get(key)):
            modified = True
    for key in ("allOf", "anyOf", "oneOf", "prefixItems"):
        sub = schema.get(key)
        if isinstance(sub, list):
            for v in sub:
                modified = _sanitize_schema(v) or modified
    return modified


def _validate_schema(name, schema):
    """Warn loudly (to stderr) if a schema still violates draft 2020-12.

    Validation is best-effort: if jsonschema isn't installed we skip silently.
    We never raise — a bad schema should be visible and fixed, not crash the
    server, and the API itself is the final gate.
    """
    try:
        from jsonschema.validators import Draft202012Validator
    except ImportError:
        return
    try:
        Draft202012Validator.check_schema(schema)
    except Exception as e:
        print(
            f"[tool_registry] WARNING: tool '{name}' inputSchema is INVALID per "
            f"JSON Schema draft 2020-12 and WILL be rejected by the Anthropic API "
            f"(400). Fix its tools.yml entry. Detail: {e}",
            file=sys.stderr,
            flush=True,
        )


def _check_descriptions(name, description, schema):
    """Lint a tool's documentation completeness at load time (stderr, never stdout).

    The tool's description + per-property descriptions are the ENTIRE contract a
    calling model sees when it lists tools — an undocumented property means the
    model is guessing. This warns; it never raises (a thin doc shouldn't crash a
    server). Non-breaking SOP enforcement: makes gaps visible so they get fixed.
    """
    if not (description or "").strip():
        print(f"[tool_registry] DOC WARNING: tool '{name}' has no description.",
              file=sys.stderr, flush=True)
    props = (schema or {}).get("properties", {})
    undescribed = [p for p, d in props.items() if not (d or {}).get("description", "").strip()]
    if undescribed:
        print(f"[tool_registry] DOC WARNING: tool '{name}' has properties with no "
              f"description: {', '.join(undescribed)}. The description+inputSchema is "
              f"the only contract the calling model sees — document every property.",
              file=sys.stderr, flush=True)


class ToolRegistry:
    """Loads tool definitions from a YAML file and watches for changes."""

    def __init__(self, server_dir: Path, server=None, registry_file: str = "tools.yml"):
        self.server_dir = Path(server_dir)
        self.registry_path = self.server_dir / registry_file
        self.server = server  # MCP Server instance, for sending list_changed
        self._tools = []
        self._handler_map = {}  # tool_name -> handler_key
        self._digest = None  # sha256 of full tool definitions, for change detection
        self._last_mtime = 0
        self._lock = threading.Lock()
        self._load()

        # Start file watcher in background
        self._watch_thread = threading.Thread(target=self._watch, daemon=True)
        self._watch_thread.start()

    def _load(self):
        """Load or reload tool definitions from YAML."""
        if not self.registry_path.exists():
            return

        try:
            mtime = self.registry_path.stat().st_mtime
            if mtime == self._last_mtime:
                return  # No change

            with open(self.registry_path) as f:
                data = yaml.safe_load(f)

            if not data or "tools" not in data:
                return

            tools = []
            handler_map = {}

            for entry in data["tools"]:
                name = entry["name"]
                schema = copy.deepcopy(
                    entry.get("inputSchema", {"type": "object", "properties": {}, "required": []})
                )
                if _sanitize_schema(schema):
                    print(
                        f"[tool_registry] auto-sanitized inputSchema for tool '{name}' "
                        f"(deduped 'required'); fix its tools.yml entry to silence this.",
                        file=sys.stderr,
                        flush=True,
                    )
                _validate_schema(name, schema)
                _check_descriptions(name, entry.get("description", ""), schema)
                tool = Tool(
                    name=name,
                    description=entry.get("description", ""),
                    inputSchema=schema,
                )
                tools.append(tool)
                handler_map[name] = entry.get("handler", name)

            # Digest covers names, descriptions, AND schemas — a schema-only fix
            # (e.g. repairing an invalid inputSchema) must reach already-connected
            # clients, or they keep sending the stale cached schema to the API.
            new_digest = hashlib.sha256(
                json.dumps(
                    [[t.name, t.description, t.inputSchema] for t in tools],
                    sort_keys=True,
                ).encode()
            ).hexdigest()

            with self._lock:
                old_digest = self._digest
                self._tools = tools
                self._handler_map = handler_map
                self._last_mtime = mtime
                self._digest = new_digest

                # If any tool definition changed and we have a server, notify
                if old_digest and old_digest != new_digest and self.server:
                    self._notify_changed()

        except (yaml.YAMLError, KeyError, OSError) as e:
            print(f"[tool_registry] Failed to load {self.registry_path}: {e}", file=sys.stderr)

    def _notify_changed(self):
        """Send list_changed notification to the MCP client."""
        # Write raw JSON-RPC notification to stdout
        notification = json.dumps({"jsonrpc": "2.0", "method": "notifications/tools/list_changed"})
        try:
            sys.stdout.write(notification + "\n")
            sys.stdout.flush()
        except (OSError, BrokenPipeError):
            pass

    def _watch(self):
        """Watch the registry file for changes."""
        while True:
            time.sleep(2)
            try:
                if self.registry_path.exists():
                    mtime = self.registry_path.stat().st_mtime
                    if mtime != self._last_mtime:
                        self._load()
            except OSError:
                pass

    def list_tools(self):
        """Return current tool definitions. Called by server.list_tools()."""
        self._load()  # Check for changes on each call too
        with self._lock:
            return list(self._tools)

    def get_handler_key(self, tool_name):
        """Map a tool name to its handler key.

        The handler key is used by the server to dispatch to the right
        module/function. Defaults to the tool name itself if no explicit
        handler mapping exists.
        """
        with self._lock:
            return self._handler_map.get(tool_name, tool_name)

    def has_tool(self, tool_name):
        """Check if a tool exists in the registry."""
        with self._lock:
            return tool_name in self._handler_map


def generate_registry(server_dir, output_file="tools.yml"):
    """Generate a tools.yml from the current hardcoded tool definitions.

    Call this once per server to seed the registry file from the existing
    tools() functions. After that, the YAML file becomes the source of truth.

    Usage:
        python -c "from uai_toolkit.mcp.shared.tool_registry import generate_registry; generate_registry('/path/to/server')"
    """
    import importlib
    import pkgutil
    import sys

    server_dir = Path(server_dir)
    tools_dir = server_dir / "tools"
    sys.path.insert(0, str(server_dir))
    sys.path.insert(0, str(server_dir.parent))  # mcps/

    all_tools = []
    for importer, modname, ispkg in pkgutil.iter_modules([str(tools_dir)]):
        mod = importlib.import_module(f"tools.{modname}")
        if hasattr(mod, "tools"):
            for t in mod.tools():
                entry = {
                    "name": t.name,
                    "description": (t.description or "").strip(),
                    "handler": t.name,  # handler key = current name
                    "module": modname,
                }
                if t.inputSchema:
                    entry["inputSchema"] = t.inputSchema
                all_tools.append(entry)

    output = {
        "_meta": {
            "description": f"Tool definitions for {server_dir.name} MCP server",
            "generated_from": "existing tools() functions",
            "note": "Edit this file to rename tools. The server reloads dynamically.",
        },
        "tools": sorted(all_tools, key=lambda t: t["name"]),
    }

    out_path = server_dir / output_file
    with open(out_path, "w") as f:
        yaml.dump(output, f, default_flow_style=False, sort_keys=False, allow_unicode=True, width=120)

    print(f"Generated {out_path} with {len(all_tools)} tools")
    return out_path
