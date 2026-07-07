"""
Sessions tool module — cli-agent tools.

Extracted from mcps/cli-agent/server.py.
Provides agent launching, session management, and terminal reading.

All operations delegate to agent_ops_cli.py via subprocess.
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from mcp.types import Tool, TextContent


# --- Constants (kept in sync with lib_agent_ops.py / agent_ops_cli.py) ---
PLATFORM_NAMES = ["claude_cli", "codex_cli", "gemini_cli"]
ROLES = ["librarian", "dev_lead", "custodian", "peer_review", "tester", "researcher", "validator"]

# --- Subprocess plumbing ---
AI_ROOT = Path(os.environ.get("AI_ROOT", Path(__file__).resolve().parents[5]))
AGENT_OPS_CLI = AI_ROOT / "ai_general" / "scripts" / "cli" / "agent_ops_cli.py"

PREFIX = "sessions_"


def _run_cli(subcommand: str, args: list = None) -> dict:
    """Run agent_ops_cli.py and return parsed JSON (or error dict)."""
    cmd = [sys.executable, str(AGENT_OPS_CLI), subcommand] + (args or [])
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    except subprocess.TimeoutExpired:
        return {"success": False, "error": f"Timeout running: {subcommand}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

    output = result.stdout.strip()
    if result.returncode != 0:
        err = result.stderr.strip() or output or f"Error (exit {result.returncode})"
        # The CLI may emit JSON even on failure (e.g. {"success": false, ...})
        try:
            return json.loads(err)
        except (json.JSONDecodeError, ValueError):
            pass
        # Try stdout as well — some errors go there
        try:
            return json.loads(output)
        except (json.JSONDecodeError, ValueError):
            pass
        return {"success": False, "error": err}

    try:
        return json.loads(output)
    except (json.JSONDecodeError, ValueError):
        return {"success": False, "error": f"Invalid JSON from CLI: {output[:500]}"}


# === Tool definitions (unchanged) ===

def tools() -> list[Tool]:
    return [
        # Test/health check (combined test for all sessions sub-modules)
        Tool(
            name=f"{PREFIX}test",
            description="Test sessions server connectivity and configuration (cli-agent, session, local-llm)",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        # Generic launcher
        Tool(
            name=f"{PREFIX}launch_agent",
            description="Launch a CLI agent with specified role and platform",
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": {
                        "type": "string",
                        "enum": PLATFORM_NAMES,
                        "description": "Target platform: claude_cli, codex_cli, gemini_cli"
                    },
                    "role": {
                        "type": "string",
                        "enum": ROLES,
                        "description": "Agent role: librarian, dev_lead, custodian, peer_review, tester, researcher, validator"
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Task ID to execute (mutually exclusive with prompt)"
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Direct prompt for agent (mutually exclusive with task_id)"
                    },
                    "context_files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Additional files to load (supplements role defaults)"
                    },
                    "use_devtree": {
                        "type": "boolean",
                        "default": False,
                        "description": "Run in isolated devTree workspace (AI_ROOT_{uuid8}). Default: use main repo."
                    }
                },
                "required": ["platform", "role"]
            }
        ),
        # Management tools
        Tool(
            name=f"{PREFIX}kill",
            description="Terminate a running agent session",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Zellij session ID to kill"}
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name=f"{PREFIX}attach",
            description="Get command to attach to agent session (user must run manually)",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Zellij session ID"}
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name=f"{PREFIX}send_keys",
            description="Send keystrokes to agent session",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Zellij session ID"},
                    "keys": {"type": "string", "description": "Keys to send"},
                    "enter": {"type": "boolean", "default": True, "description": "Press Enter after keys"}
                },
                "required": ["session_id", "keys"]
            }
        ),
        Tool(
            name=f"{PREFIX}list_sessions",
            description="List all active CLI agent sessions",
            inputSchema={
                "type": "object",
                "properties": {
                    "platform": {"type": "string", "enum": PLATFORM_NAMES, "description": "Filter by platform"}
                }
            }
        ),
        Tool(
            name=f"{PREFIX}get_status",
            description="Get detailed status of an agent session including recent output",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Zellij session ID"},
                    "output_lines": {"type": "integer", "default": 30, "description": "Lines of recent output to include"}
                },
                "required": ["session_id"]
            }
        ),
        Tool(
            name=f"{PREFIX}read_session",
            description="Read and parse terminal content from a CLI session. Returns structured messages (JSON), cleaned text, or raw dump. Use status_only=true for fast polling (<100ms) to detect permission prompts and session state.",
            inputSchema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Zellij session name"},
                    "range": {"type": "string", "default": "all", "description": "Line range: 'all', 'start:N', 'M:N', 'N:end'"},
                    "format": {"type": "string", "enum": ["json", "text", "raw"], "default": "json", "description": "Output format"},
                    "page_size": {"type": "integer", "default": 500, "description": "Messages per page (0 = no pagination)"},
                    "page": {"type": "integer", "default": 1, "description": "Page number"},
                    "platform": {"type": "string", "enum": ["auto", "claude", "gemini", "codex"], "default": "auto", "description": "Platform override"},
                    "status_only": {"type": "boolean", "default": False, "description": "Return only session status, skip message parsing"}
                },
                "required": ["session_id"]
            }
        ),
    ]


# === CLI argument builders ===

def _launch_args(arguments: dict, include_platform: bool = True, default_platform: str = "claude_cli") -> list:
    """Build CLI flags for any launch subcommand from MCP tool arguments."""
    args = []
    if include_platform:
        platform = arguments.get("platform", default_platform)
        args.extend(["--platform", platform])
    if arguments.get("role"):
        args.extend(["--role", arguments["role"]])
    if arguments.get("task_id"):
        args.extend(["--task-id", arguments["task_id"]])
    if arguments.get("prompt"):
        args.extend(["--prompt", arguments["prompt"]])
    if arguments.get("context_files"):
        args.append("--context-files")
        args.extend(arguments["context_files"])
    if arguments.get("use_devtree"):
        args.append("--use-devtree")
    return args


# === Tool dispatch ===

async def call_tool(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls by dispatching to agent_ops_cli.py via subprocess."""

    # Strip prefix for internal dispatch
    short = name.replace(PREFIX, "", 1)

    if short == "test":
        result = _run_cli("test")

    # --- Launch tools ---
    elif short == "launch_agent":
        cli_args = _launch_args(arguments, include_platform=True)
        result = _run_cli("launch_agent", cli_args)

    # --- Management tools ---
    elif short == "kill":
        result = _run_cli("kill", ["--session-id", arguments["session_id"]])

    elif short == "attach":
        result = _run_cli("attach", ["--session-id", arguments["session_id"]])

    elif short == "send_keys":
        cli_args = ["--session-id", arguments["session_id"], "--keys", arguments["keys"]]
        if not arguments.get("enter", True):
            cli_args.append("--no-enter")
        result = _run_cli("send_keys", cli_args)

    elif short == "list_sessions":
        cli_args = []
        if arguments.get("platform"):
            cli_args.extend(["--platform", arguments["platform"]])
        result = _run_cli("list_sessions", cli_args)

    elif short == "get_status":
        cli_args = ["--session-id", arguments["session_id"]]
        output_lines = arguments.get("output_lines", 30)
        cli_args.extend(["--output-lines", str(output_lines)])
        result = _run_cli("get_status", cli_args)

    elif short == "read_session":
        cli_args = ["--session-id", arguments["session_id"]]
        if arguments.get("range") and arguments["range"] != "all":
            cli_args.extend(["--range", arguments["range"]])
        if arguments.get("format") and arguments["format"] != "json":
            cli_args.extend(["--format", arguments["format"]])
        if arguments.get("page_size") and arguments["page_size"] != 500:
            cli_args.extend(["--page-size", str(arguments["page_size"])])
        if arguments.get("page") and arguments["page"] != 1:
            cli_args.extend(["--page", str(arguments["page"])])
        if arguments.get("platform") and arguments["platform"] != "auto":
            cli_args.extend(["--platform-hint", arguments["platform"]])
        if arguments.get("status_only"):
            cli_args.append("--status-only")
        result = _run_cli("read_session", cli_args)

    else:
        return None  # Not handled by this module

    return [TextContent(type="text", text=json.dumps(result, indent=2))]
