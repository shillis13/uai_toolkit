"""
Knowledge tool module -- jsonl tools.

Extracted from mcps/jsonl/server.py.
Wraps read_jsonl.py for reading CLI session histories.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.types import Tool, TextContent


# === Configuration ===
AI_ROOT = Path(os.environ.get("AI_ROOT", os.path.expanduser("~/AI/ai_root")))
READ_JSONL_MODULE = "uai_toolkit.jsonl.read_jsonl"

# Formats whose stdout should be parsed as JSON before returning
JSON_FORMATS = {"json", "structured", "raw"}


def _run_read_jsonl(args: list[str], timeout: int = 30) -> tuple[int, str, str]:
    """Run read_jsonl.py with given args. Returns (returncode, stdout, stderr)."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", READ_JSONL_MODULE] + args,
            capture_output=True, text=True, timeout=timeout,
            cwd=str(AI_ROOT), env={**os.environ, "NO_COLOR": "1"},
        )
        return (result.returncode, result.stdout, result.stderr)
    except subprocess.TimeoutExpired:
        return (1, "", f"read_jsonl.py timed out after {timeout}s")
    except Exception as e:
        return (1, "", str(e))


def _build_result(returncode: int, stdout: str, stderr: str, fmt: str = "text") -> dict:
    """Build a result dict from subprocess output, parsing JSON when appropriate."""
    if returncode != 0:
        return {"error": stderr.strip() or stdout.strip() or "read_jsonl.py failed"}
    output = stdout.strip()
    if not output:
        return {"output": ""}
    if fmt in JSON_FORMATS:
        try:
            return json.loads(output)
        except json.JSONDecodeError:
            pass
    return {"output": output}


# === Tool Definitions ===

def tools() -> list[Tool]:
    return [
        Tool(
            name="knowledge_read_session",
            description="Read messages from a session by UUID. Returns parsed conversation history.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uuid": {
                        "type": "string",
                        "description": "Session UUID (full or prefix match)",
                    },
                    "platform": {
                        "type": "string",
                        "description": "Platform filter",
                        "enum": ["claude", "codex", "gemini"],
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format (default: json)",
                        "enum": ["text", "json", "structured", "raw"],
                        "default": "json",
                    },
                    "type_filter": {
                        "type": "string",
                        "description": "Comma-separated message types to include (e.g. 'user,response,thinking')",
                    },
                    "range": {
                        "type": "string",
                        "description": "Message range (e.g. '-10' for last 10, '1-5' for first five)",
                    },
                    "show_private": {
                        "type": "boolean",
                        "description": "Include private/thinking blocks (default: false)",
                        "default": False,
                    },
                },
                "required": ["uuid"],
            },
        ),
        Tool(
            name="knowledge_read_file",
            description="Read messages from one or more JSONL file paths.",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Primary JSONL file path",
                    },
                    "paths": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional JSONL file paths to read",
                    },
                    "platform": {
                        "type": "string",
                        "description": "Platform filter",
                        "enum": ["claude", "codex", "gemini"],
                    },
                    "format": {
                        "type": "string",
                        "description": "Output format (default: json)",
                        "enum": ["text", "json", "structured", "raw"],
                        "default": "json",
                    },
                    "type_filter": {
                        "type": "string",
                        "description": "Comma-separated message types to include",
                    },
                    "range": {
                        "type": "string",
                        "description": "Message range (e.g. '-10' for last 10)",
                    },
                    "show_private": {
                        "type": "boolean",
                        "description": "Include private/thinking blocks (default: false)",
                        "default": False,
                    },
                },
                "required": ["path"],
            },
        ),
        Tool(
            name="knowledge_find_session",
            description="Find the JSONL file path for a session UUID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "uuid": {
                        "type": "string",
                        "description": "Session UUID (full or prefix match)",
                    },
                },
                "required": ["uuid"],
            },
        ),
        Tool(
            name="knowledge_session_summary",
            description="Get summary statistics for a session (message counts, timestamps, etc.).",
            inputSchema={
                "type": "object",
                "properties": {
                    "uuid": {
                        "type": "string",
                        "description": "Session UUID",
                    },
                    "platform": {
                        "type": "string",
                        "description": "Platform filter",
                        "enum": ["claude", "codex", "gemini"],
                    },
                },
                "required": ["uuid"],
            },
        ),
        Tool(
            name="knowledge_list_sessions",
            description="List recent sessions across platforms.",
            inputSchema={
                "type": "object",
                "properties": {
                    "project_dir": {
                        "type": "string",
                        "description": "Project directory to filter by (optional)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of sessions to return (default: 20)",
                    },
                },
            },
        ),
    ]


# === Tool Dispatch ===

async def call_tool(name: str, arguments: dict) -> list[TextContent] | None:
    result: Any = {}

    if name == "knowledge_read_session":
        uuid = arguments["uuid"]
        fmt = arguments.get("format", "json")
        cmd_args = ["read", uuid, "--format", fmt]
        if arguments.get("platform"):
            cmd_args.extend(["--platform", arguments["platform"]])
        if arguments.get("type_filter"):
            for t in arguments["type_filter"].split(","):
                cmd_args.extend(["--type", t.strip()])
        if arguments.get("range"):
            cmd_args.extend(["--range", arguments["range"]])
        if arguments.get("show_private"):
            cmd_args.append("--show-private")
        rc, stdout, stderr = _run_read_jsonl(cmd_args, timeout=30)
        result = _build_result(rc, stdout, stderr, fmt)

    elif name == "knowledge_read_file":
        fmt = arguments.get("format", "json")
        all_paths = [arguments["path"]]
        if arguments.get("paths"):
            all_paths.extend(arguments["paths"])
        cmd_args = ["read-file"] + all_paths + ["--format", fmt]
        if arguments.get("platform"):
            cmd_args.extend(["--platform", arguments["platform"]])
        if arguments.get("type_filter"):
            for t in arguments["type_filter"].split(","):
                cmd_args.extend(["--type", t.strip()])
        if arguments.get("range"):
            cmd_args.extend(["--range", arguments["range"]])
        if arguments.get("show_private"):
            cmd_args.append("--show-private")
        rc, stdout, stderr = _run_read_jsonl(cmd_args, timeout=30)
        result = _build_result(rc, stdout, stderr, fmt)

    elif name == "knowledge_find_session":
        uuid = arguments["uuid"]
        rc, stdout, stderr = _run_read_jsonl(["find", uuid], timeout=10)
        if rc != 0:
            result = {"error": stderr.strip() or "Session not found"}
        else:
            result = {"path": stdout.strip()}

    elif name == "knowledge_session_summary":
        uuid = arguments["uuid"]
        cmd_args = ["summary", uuid]
        if arguments.get("platform"):
            cmd_args.extend(["--platform", arguments["platform"]])
        rc, stdout, stderr = _run_read_jsonl(cmd_args, timeout=10)
        result = _build_result(rc, stdout, stderr, "json")

    elif name == "knowledge_list_sessions":
        cmd_args = ["list"]
        if arguments.get("project_dir"):
            cmd_args.append(arguments["project_dir"])
        if arguments.get("limit") is not None:
            cmd_args.extend(["--limit", str(arguments["limit"])])
        rc, stdout, stderr = _run_read_jsonl(cmd_args, timeout=10)
        if rc != 0:
            result = {"error": stderr.strip() or "list failed"}
        else:
            result = {"output": stdout.strip()}

    else:
        return None

    text = json.dumps(result, indent=2, default=str) if isinstance(result, dict) else str(result)
    return [TextContent(type="text", text=text)]
