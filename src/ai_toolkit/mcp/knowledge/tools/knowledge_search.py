"""
Knowledge tool module -- knowledge-search tools.

Thin subprocess wrapper around search_cli.py.
No direct search_lib imports.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

SEARCH_MODULE = "ai_toolkit.scripts.histories.search_cli"


def _run_cli(subcommand, args=None, timeout=30):
    """Run search_cli.py and return stdout."""
    cmd = [sys.executable, "-m", SEARCH_MODULE, subcommand] + (args or [])
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if result.returncode != 0:
        return json.dumps({"error": result.stderr.strip() or "exit %d" % result.returncode})
    return result.stdout.strip()


def tools() -> list[Tool]:
    return [
        Tool(
            name="knowledge_search",
            description="""Search the AI conversation knowledge base.

Dual-mode search over 4+ year archive (500+ chats, 4700+ chunks).

Modes:
- SEARCH (default for "find X"): Curated result list with metadata
- ANSWER (default for "What is X?"): Editorial synthesis with citations

4-layer cascade finds results even when exact terms don't match.
""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search terms or question"
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["search", "answer", "auto"],
                        "default": "auto",
                        "description": "Response mode"
                    },
                    "use_synonyms": {
                        "type": "boolean",
                        "default": True,
                        "description": "Expand search with synonym table"
                    },
                    "max_results": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum results to return"
                    },
                    "max_tokens": {
                        "type": "integer",
                        "description": "Optional token budget constraint"
                    },
                    "output_file": {
                        "type": "boolean",
                        "default": False,
                        "description": "Write results to timestamped .md file"
                    },
                    "retrieve_artifacts": {
                        "type": "boolean",
                        "default": False,
                        "description": "Copy matching condensed files to retrieval directory"
                    }
                },
                "required": ["query"]
            }
        ),
        Tool(
            name="knowledge_stats",
            description="Get knowledge base index statistics",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name="knowledge_grep_search",
            description="""Grep search - regex over full chunk file contents.

Use when topic_search returns irrelevant results. Searches actual
conversation content for keyword matches.""",
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search terms"
                    },
                    "use_synonyms": {
                        "type": "boolean",
                        "default": True,
                        "description": "Expand with synonym table"
                    },
                    "max_results": {
                        "type": "integer",
                        "default": 10,
                        "description": "Maximum results"
                    },
                    "return_format": {
                        "type": "string",
                        "enum": ["condensed", "full"],
                        "default": "condensed",
                        "description": "Return condensed or full chunk content"
                    },
                    "output_file": {
                        "type": "boolean",
                        "default": False,
                        "description": "Write to .md file"
                    }
                },
                "required": ["query"]
            }
        ),
    ]


async def call_tool(name: str, arguments: dict) -> list[TextContent] | None:
    try:
        if name == "knowledge_search":
            args = [arguments["query"]]
            args += ["--max-results", str(arguments.get("max_results", 10))]
            mode = arguments.get("mode", "auto")
            if mode != "auto":
                args += ["--mode", mode]
            if not arguments.get("use_synonyms", True):
                args.append("--no-synonyms")
            if arguments.get("max_tokens"):
                args += ["--max-tokens", str(arguments["max_tokens"])]
            if arguments.get("output_file"):
                args.append("--output-file")
            if arguments.get("retrieve_artifacts"):
                args.append("--retrieve-artifacts")
            out = _run_cli("search", args)

        elif name == "knowledge_stats":
            out = _run_cli("stats")

        elif name == "knowledge_grep_search":
            args = [arguments["query"]]
            args += ["--max-results", str(arguments.get("max_results", 10))]
            if not arguments.get("use_synonyms", True):
                args.append("--no-synonyms")
            fmt = arguments.get("return_format", "condensed")
            if fmt != "condensed":
                args += ["--format", fmt]
            if arguments.get("output_file"):
                args.append("--output-file")
            out = _run_cli("grep", args)

        else:
            return None

        return [TextContent(type="text", text=out)]

    except Exception as e:
        return [TextContent(type="text", text=json.dumps({
            "error": str(e), "tool": name
        }, indent=2))]
