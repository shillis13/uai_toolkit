"""
Knowledge tool module -- memory tools.

Extracted from mcps/memory/server.py.
Slot-based memory operations for AI instances.

Delegates to memory_cli.py via subprocess (no direct memory_lib import).
"""

import json
import os
import subprocess
import sys
from pathlib import Path
from mcp.types import Tool, TextContent

MEMORY_MODULE = "ai_toolkit.memory.memory_cli"


def _run_cli(subcommand: str, args: list = None) -> str:
    """Run memory_cli.py and return stdout on success, or an error JSON string."""
    cmd = [sys.executable, "-m", MEMORY_MODULE, subcommand] + (args or [])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    if result.returncode != 0:
        # CLI writes JSON errors to stderr; fall back to generic message
        return result.stderr.strip() or json.dumps({"error": f"Exit code {result.returncode}"})
    return result.stdout.strip()


def tools() -> list[Tool]:
    return [
        Tool(
            name="knowledge_get_manifest",
            description="Get slot purposes and load behaviors. Call at bootstrap.",
            inputSchema={
                "type": "object",
                "properties": {
                    "ai": {"type": "string", "description": "AI instance. Default: claude_desktop"}
                }
            }
        ),
        Tool(
            name="knowledge_memory_read",
            description="Read slot contents with optional filters",
            inputSchema={
                "type": "object",
                "properties": {
                    "slot": {"type": "integer", "description": "Slot number"},
                    "limit": {"type": "integer", "description": "Max entries to return (default: all)"},
                    "since": {"type": "string", "description": "ISO timestamp - entries after this time"},
                    "oldest_first": {"type": "boolean", "description": "Chronological order (default: newest first)"},
                    "ai": {"type": "string", "description": "AI instance whose memory store to read (passed to memory_cli as --ai). Default: claude_desktop"}
                },
                "required": ["slot"]
            }
        ),
        Tool(
            name="knowledge_memory_append",
            description="Add timestamped observation to slot",
            inputSchema={
                "type": "object",
                "properties": {
                    "slot": {"type": "integer", "description": "Slot number"},
                    "content": {"type": "string", "description": "Observation to record"},
                    "ai": {"type": "string", "description": "AI instance whose memory store to append to (passed to memory_cli as --ai). Default: claude_desktop"}
                },
                "required": ["slot", "content"]
            }
        ),
        Tool(
            name="knowledge_memory_update",
            description="Modify entry at index (preserves timestamp)",
            inputSchema={
                "type": "object",
                "properties": {
                    "slot": {"type": "integer", "description": "Working memory slot number (03-30) containing the entry"},
                    "index": {"type": "integer", "description": "Entry index (0-based)"},
                    "content": {"type": "string", "description": "New content"},
                    "ai": {"type": "string", "description": "AI instance whose memory store to update (passed to memory_cli as --ai). Default: claude_desktop"}
                },
                "required": ["slot", "index", "content"]
            }
        ),
        Tool(
            name="knowledge_memory_delete",
            description="Remove entry by index OR delete entries before a date",
            inputSchema={
                "type": "object",
                "properties": {
                    "slot": {"type": "integer", "description": "Working memory slot number (03-30) to delete from"},
                    "index": {"type": "integer", "description": "Entry index to delete"},
                    "before": {"type": "string", "description": "ISO timestamp - delete entries before this"},
                    "ai": {"type": "string", "description": "AI instance whose memory store to delete from (passed to memory_cli as --ai). Default: claude_desktop"}
                },
                "required": ["slot"]
            }
        ),
        Tool(
            name="knowledge_memory_search",
            description="Search content across slots",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search term or regex pattern"},
                    "regex": {"type": "boolean", "description": "Treat query as regex (default: false)"},
                    "slots": {"type": "array", "items": {"type": "integer"}, "description": "Slots to search (default: all)"},
                    "since": {"type": "string", "description": "ISO timestamp filter"},
                    "content_only": {"type": "boolean", "description": "Match content field only (default: true)"},
                    "ai": {"type": "string", "description": "AI instance whose memory store to search (passed to memory_cli as --ai). Default: claude_desktop"}
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="knowledge_set_slot_config",
            description="Update or create slot definition in manifest",
            inputSchema={
                "type": "object",
                "properties": {
                    "slot": {"type": "integer", "description": "Working memory slot number (03-30) to define or update in the manifest"},
                    "name": {"type": "string", "description": "Short slot name/label shown in the manifest (e.g. 'user_model', 'communication')"},
                    "purpose": {"type": "string", "description": "Human-readable description of what the slot is for"},
                    "load": {"type": "string", "enum": ["AUTO", "TOPIC", "DEMAND"], "description": "When the slot loads into context: AUTO (always at bootstrap), TOPIC (only when topically relevant per its tags), or DEMAND (only when explicitly requested)"},
                    "tags": {"type": "array", "items": {"type": "string"}, "description": "Topic tags used to decide TOPIC-based loading and to categorize the slot"},
                    "ai": {"type": "string", "description": "AI instance whose manifest to update (passed to memory_cli as --ai). Default: claude_desktop"}
                },
                "required": ["slot"]
            }
        ),
        Tool(
            name="knowledge_memory_stats",
            description="Get entry counts and sizes for all slots",
            inputSchema={
                "type": "object",
                "properties": {
                    "ai": {"type": "string", "description": "AI instance whose memory stats to report (passed to memory_cli as --ai). Default: claude_desktop"}
                }
            }
        ),
    ]


async def call_tool(name: str, arguments: dict) -> list[TextContent] | None:
    try:
        ai = arguments.get("ai")

        if name == "knowledge_get_manifest":
            cli_args = []
            if ai:
                cli_args += ["--ai", ai]
            output = _run_cli("get_manifest", cli_args)

        elif name == "knowledge_memory_read":
            cli_args = [str(arguments["slot"])]
            if arguments.get("since"):
                cli_args += ["--since", arguments["since"]]
            if arguments.get("limit") is not None:
                cli_args += ["--limit", str(arguments["limit"])]
            if arguments.get("oldest_first"):
                cli_args.append("--oldest-first")
            if ai:
                cli_args += ["--ai", ai]
            output = _run_cli("read", cli_args)

        elif name == "knowledge_memory_append":
            cli_args = [str(arguments["slot"]), arguments["content"]]
            if ai:
                cli_args += ["--ai", ai]
            output = _run_cli("append", cli_args)

        elif name == "knowledge_memory_update":
            cli_args = [str(arguments["slot"]), str(arguments["index"]), arguments["content"]]
            if ai:
                cli_args += ["--ai", ai]
            output = _run_cli("update", cli_args)

        elif name == "knowledge_memory_delete":
            cli_args = [str(arguments["slot"])]
            if arguments.get("index") is not None:
                cli_args += ["--index", str(arguments["index"])]
            if arguments.get("before"):
                cli_args += ["--before", arguments["before"]]
            if ai:
                cli_args += ["--ai", ai]
            output = _run_cli("delete", cli_args)

        elif name == "knowledge_memory_search":
            cli_args = [arguments["query"]]
            slots = arguments.get("slots")
            if slots:
                for s in slots:
                    cli_args += ["--slot", str(s)]
            if arguments.get("regex"):
                cli_args.append("--regex")
            if arguments.get("since"):
                cli_args += ["--since", arguments["since"]]
            # CLI defaults content_only=True; pass --all-fields when caller wants False
            content_only = arguments.get("content_only", True)
            if not content_only:
                cli_args.append("--all-fields")
            if ai:
                cli_args += ["--ai", ai]
            output = _run_cli("search", cli_args)

        elif name == "knowledge_set_slot_config":
            cli_args = [str(arguments["slot"])]
            if arguments.get("name"):
                cli_args += ["--name", arguments["name"]]
            if arguments.get("purpose"):
                cli_args += ["--purpose", arguments["purpose"]]
            if arguments.get("load"):
                cli_args += ["--load", arguments["load"]]
            if arguments.get("tags"):
                cli_args += ["--tags"] + list(arguments["tags"])
            if ai:
                cli_args += ["--ai", ai]
            output = _run_cli("set_config", cli_args)

        elif name == "knowledge_memory_stats":
            cli_args = []
            if ai:
                cli_args += ["--ai", ai]
            output = _run_cli("stats", cli_args)

        else:
            return None

    except subprocess.TimeoutExpired:
        output = json.dumps({"error": "memory_cli.py timed out after 30s"})
    except Exception as e:
        output = json.dumps({"error": str(e)})

    return [TextContent(type="text", text=output)]
