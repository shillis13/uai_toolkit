"""
Workflow tool module — todo tools.

Thin subprocess wrapper around todo_mgr CLI (--json mode).
All business logic lives in todo_mgr.py; this module only builds
CLI arguments and forwards structured JSON results.
"""

import json
import os
import subprocess
import sys

from mcp.types import Tool, TextContent

# Locate todo_mgr entry point
TODO_MGR_MODULE = "uai_toolkit.todo.todo_mgr"

# Valid statuses for description text (loaded once at import)
VALID_STATUSES = [
    "Triaging", "Needs_Research", "Needs_Derivation", "Ready",
    "In_Progress", "Reviewing", "Accepting", "Blocked", "Done", "Cancelled",
]

ROOT_PROPERTY = {
    "root": {
        "type": "string",
        "description": "Alternate todo root directory. Omit to use the default (ai_general/work/todos/)."
    }
}


def _run_todo(command: str, args: list[str] | None = None, root: str | None = None, timeout: int = 30) -> dict | str:
    """Run todo_mgr --json [--root ROOT] <command> [args...] and return parsed JSON."""
    cmd = [sys.executable, "-m", TODO_MGR_MODULE, "--json", "--no-color"]
    if root:
        cmd += ["--root", root]
    cmd.append(command)
    if args:
        cmd += args
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    stdout = result.stdout.strip()
    if result.returncode != 0:
        stderr = result.stderr.strip()
        return {"error": stderr or stdout or f"Exit code {result.returncode}"}
    try:
        return json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return stdout


def tools() -> list[Tool]:
    return [
        Tool(
            name="workflow_todo_list",
            description="List todos with optional filtering by status, tag, or flag",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "status": {
                        "type": "string",
                        "description": "Filter by status (e.g., 'Ready', 'In_Progress', 'IP', 'TR')"
                    },
                    "tag": {
                        "type": "string",
                        "description": "Filter by tag (e.g., 'infrastructure', 'automation')"
                    },
                    "flag": {
                        "type": "string",
                        "description": "Filter by flag (e.g., 'high_priority', 'needs_testing')"
                    }
                }
            }
        ),
        Tool(
            name="workflow_todo_get",
            description="Get details of a specific todo by ID, number, or reference code (e.g., 'IP2', 'todo_0007_applescript')",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "identifier": {
                        "type": "string",
                        "description": "Todo identifier (ID or reference code)"
                    }
                },
                "required": ["identifier"]
            }
        ),
        Tool(
            name="workflow_todo_create",
            description="Create a new todo",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "name": {
                        "type": "string",
                        "description": "Todo name (will be slugified)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Initial description"
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Initial tags"
                    }
                },
                "required": ["name"]
            }
        ),
        Tool(
            name="workflow_todo_update",
            description="Update a section in a todo's notes.md. Sections: Description, Origin, What Success Looks Like, Approach (Optional), Why It Matters, Requirements, Dependencies, Notes. Creates section if it doesn't exist.",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "identifier": {
                        "type": "string",
                        "description": "Todo identifier (ID, number, or reference code)"
                    },
                    "section": {
                        "type": "string",
                        "description": "Section heading (without ##), e.g. 'Description', 'Notes', 'Requirements'"
                    },
                    "content": {
                        "type": "string",
                        "description": "New content for the section (replaces existing section content)"
                    }
                },
                "required": ["identifier", "section", "content"]
            }
        ),
        Tool(
            name="workflow_todo_set_status",
            description=f"Set todo status. Valid: {', '.join(VALID_STATUSES)}",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "identifier": {"type": "string", "description": "Todo identifier"},
                    "status": {"type": "string", "description": "New status (name or code)"}
                },
                "required": ["identifier", "status"]
            }
        ),
        Tool(
            name="workflow_todo_add_flag",
            description="Add a flag to a todo",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "identifier": {"type": "string", "description": "Todo identifier"},
                    "flag": {"type": "string", "description": "Flag name"}
                },
                "required": ["identifier", "flag"]
            }
        ),
        Tool(
            name="workflow_todo_remove_flag",
            description="Remove a flag from a todo",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "identifier": {"type": "string", "description": "Todo identifier"},
                    "flag": {"type": "string", "description": "Flag name"}
                },
                "required": ["identifier", "flag"]
            }
        ),
        Tool(
            name="workflow_todo_add_tag",
            description="Add a tag to a todo",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "identifier": {"type": "string", "description": "Todo identifier"},
                    "tag": {"type": "string", "description": "Tag name"}
                },
                "required": ["identifier", "tag"]
            }
        ),
        Tool(
            name="workflow_todo_remove_tag",
            description="Remove a tag from a todo",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "identifier": {"type": "string", "description": "Todo identifier"},
                    "tag": {"type": "string", "description": "Tag name"}
                },
                "required": ["identifier", "tag"]
            }
        ),
        Tool(
            name="workflow_todo_complete",
            description="Mark todo as Done and move to completed/",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "identifier": {"type": "string", "description": "Todo identifier"}
                },
                "required": ["identifier"]
            }
        ),
        Tool(
            name="workflow_todo_trash",
            description="Move todo to trash/ (soft delete)",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "identifier": {"type": "string", "description": "Todo identifier"}
                },
                "required": ["identifier"]
            }
        ),
        Tool(
            name="workflow_todo_move",
            description="Move a todo to a new parent (or 'root' to unparent). Usage: move <identifier> to <new_parent|root>",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "identifier": {
                        "type": "string",
                        "description": "Todo to move (ID, number, or reference code)"
                    },
                    "new_parent": {
                        "type": "string",
                        "description": "Target parent (todo identifier, or 'root'/'.'/'/' to unparent)"
                    }
                },
                "required": ["identifier", "new_parent"]
            }
        ),
        Tool(
            name="workflow_todo_kanban",
            description="Get kanban board view",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "format": {
                        "type": "string",
                        "enum": ["json", "text"],
                        "description": "Output format (default: json)",
                        "default": "json"
                    }
                }
            }
        ),
        Tool(
            name="workflow_todo_validate",
            description="Validate the todo tree. Checks for duplicate IDs, missing status files, multiple status files, and completed todos still in the active directory.",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                }
            }
        ),
        Tool(
            name="workflow_todo_find",
            description="Search todos by name pattern (glob). Returns matching todos from active, completed, and trash.",
            inputSchema={
                "type": "object",
                "properties": {
                    **ROOT_PROPERTY,
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match against todo names (e.g. '*memory*', 'todo_0233*')"
                    }
                },
                "required": ["pattern"]
            }
        ),
    ]


async def call_tool(name: str, arguments: dict) -> list[TextContent] | None:
    """Handle workflow todo tools via subprocess to todo_mgr --json."""
    root = arguments.get("root")

    try:
        if name == "workflow_todo_list":
            cli_args = []
            if arguments.get("status"):
                cli_args += ["--status", arguments["status"]]
            if arguments.get("tag"):
                cli_args += ["--tag", arguments["tag"]]
            if arguments.get("flag"):
                cli_args += ["--flag", arguments["flag"]]
            result = _run_todo("list", cli_args, root=root)

        elif name == "workflow_todo_get":
            result = _run_todo("get", [arguments["identifier"]], root=root)

        elif name == "workflow_todo_create":
            cli_args = ["--name", arguments["name"]]
            if arguments.get("description"):
                cli_args += ["--description", arguments["description"]]
            if arguments.get("tags"):
                cli_args += ["--tags", ",".join(arguments["tags"])]
            result = _run_todo("create", cli_args, root=root)

        elif name == "workflow_todo_update":
            cli_args = [
                "--id", arguments["identifier"],
                "--section", arguments["section"],
                "--content", arguments["content"],
            ]
            result = _run_todo("update", cli_args, root=root)

        elif name == "workflow_todo_set_status":
            cli_args = ["--id", arguments["identifier"], "--status", arguments["status"]]
            result = _run_todo("status", cli_args, root=root)

        elif name == "workflow_todo_add_flag":
            cli_args = ["--action", "add", "--id", arguments["identifier"], "--flag", arguments["flag"]]
            result = _run_todo("flag", cli_args, root=root)

        elif name == "workflow_todo_remove_flag":
            cli_args = ["--action", "remove", "--id", arguments["identifier"], "--flag", arguments["flag"]]
            result = _run_todo("flag", cli_args, root=root)

        elif name == "workflow_todo_add_tag":
            cli_args = ["--action", "add", "--id", arguments["identifier"], "--tag", arguments["tag"]]
            result = _run_todo("tag", cli_args, root=root)

        elif name == "workflow_todo_remove_tag":
            cli_args = ["--action", "remove", "--id", arguments["identifier"], "--tag", arguments["tag"]]
            result = _run_todo("tag", cli_args, root=root)

        elif name == "workflow_todo_complete":
            result = _run_todo("complete", [arguments["identifier"]], root=root)

        elif name == "workflow_todo_trash":
            result = _run_todo("trash", [arguments["identifier"]], root=root)

        elif name == "workflow_todo_move":
            cli_args = ["--id", arguments["identifier"], "--parent", arguments["new_parent"]]
            result = _run_todo("move", cli_args, root=root)

        elif name == "workflow_todo_kanban":
            fmt = arguments.get("format", "json")
            if fmt == "text":
                # Text kanban goes through normal CLI, not --json
                cmd = [sys.executable, "-m", TODO_MGR_MODULE, "--no-color"]
                if root:
                    cmd += ["--root", root]
                cmd.append("kanban")
                proc = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                result = proc.stdout.strip()
            else:
                result = _run_todo("kanban", root=root)

        elif name == "workflow_todo_validate":
            result = _run_todo("validate", root=root)

        elif name == "workflow_todo_find":
            cli_args = ["--pattern", arguments["pattern"]]
            result = _run_todo("find", cli_args, root=root)

        else:
            return None

        if isinstance(result, str):
            return [TextContent(type="text", text=result)]
        return [TextContent(type="text", text=json.dumps(result, indent=2, default=str))]

    except subprocess.TimeoutExpired:
        return [TextContent(type="text", text=json.dumps({"error": "Command timed out"}))]
    except Exception as e:
        return [TextContent(type="text", text=json.dumps({"error": str(e)}))]
