"""
Sessions tool module — local-llm tools.

Thin subprocess wrapper around ~/bin/ai/lllm/ scripts.
Prompt tools call lllm_prompt.py, server management calls lllm_manager.py.
No direct library imports.
"""

import json
import os
import subprocess
import sys
from pathlib import Path

from mcp.types import Tool, TextContent

# Callback schema for tool definitions (inlined)
CALLBACK_SCHEMA = {
    "type": "object",
    "description": "Optional callback for async result delivery.",
    "properties": {
        "type": {"type": "string", "enum": ["none", "file", "prompt"]},
        "output_path": {"type": "string"},
        "target": {"type": "string"},
        "session": {"type": "string"},
        "message_template": {"type": "string"},
        "submit": {"type": "boolean", "default": True},
        "force": {"type": "boolean", "default": False},
    },
    "required": ["type"],
}

PYTHON = "/opt/homebrew/bin/python3"
LLLM_DIR = Path(os.environ.get("AI_ROOT",
    Path(__file__).resolve().parents[5])) / "ai_general" / "scripts" / "lllm"
LLLM_PROMPT = str(LLLM_DIR / "lllm_prompt.py")
LLLM_MANAGER = str(LLLM_DIR / "lllm_manager.py")

PREFIX = "sessions_"


def _run(script, args, timeout=120):
    """Run a script and return (success, stdout, stderr)."""
    cmd = [PYTHON, script] + args
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return result.returncode == 0, result.stdout.strip(), result.stderr.strip()
    except subprocess.TimeoutExpired:
        return False, "", "Timeout after %ds" % timeout


def tools() -> list:
    return [
        Tool(
            name=f"{PREFIX}reason_on_text",
            description="Send prompt + text to the currently loaded local LLM, return response.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "System prompt / instruction"},
                    "input_text": {"type": "string", "description": "Text to reason about"},
                },
                "required": ["prompt", "input_text"],
            }
        ),
        Tool(
            name=f"{PREFIX}reason_on_text_async",
            description="Submit prompt + text and return immediately with a request_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "System prompt / instruction"},
                    "input_text": {"type": "string", "description": "Text to reason about"},
                    "callback_uri": {"type": "string", "description": "Callback endpoint URI"},
                    "callback": CALLBACK_SCHEMA,
                },
                "required": ["prompt", "input_text"],
            }
        ),
        Tool(
            name=f"{PREFIX}reason_on_file",
            description="Read a file and send its contents to the local LLM. Blocks until response.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "System prompt / instruction"},
                    "file_path": {"type": "string", "description": "Absolute path to file"},
                },
                "required": ["prompt", "file_path"],
            }
        ),
        Tool(
            name=f"{PREFIX}reason_on_file_async",
            description="Read a file and submit to the local LLM, returning immediately with a request_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "prompt": {"type": "string", "description": "System prompt / instruction"},
                    "file_path": {"type": "string", "description": "Absolute path to file"},
                    "callback_uri": {"type": "string", "description": "Callback endpoint URI"},
                    "callback": CALLBACK_SCHEMA,
                },
                "required": ["prompt", "file_path"],
            }
        ),
        Tool(
            name=f"{PREFIX}list_models",
            description="List all available models from the models registry.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name=f"{PREFIX}switch_model",
            description="Switch the LLM server to a different model.",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Model key from models.yml"},
                },
                "required": ["model"],
            }
        ),
        Tool(
            name=f"{PREFIX}server_start",
            description="Start the LLM server with a specific model.",
            inputSchema={
                "type": "object",
                "properties": {
                    "model": {"type": "string", "description": "Model key from models.yml"},
                },
                "required": ["model"],
            }
        ),
        Tool(
            name=f"{PREFIX}server_stop",
            description="Stop the running LLM server.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name=f"{PREFIX}server_status",
            description="Get the current status of the LLM server.",
            inputSchema={"type": "object", "properties": {}}
        ),
        Tool(
            name=f"{PREFIX}get_result",
            description="Retrieve the result of an async reasoning request by request_id.",
            inputSchema={
                "type": "object",
                "properties": {
                    "request_id": {"type": "string", "description": "Request ID from async calls"},
                },
                "required": ["request_id"],
            }
        ),
    ]


async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    short = name.replace(PREFIX, "", 1)

    if short == "reason_on_text":
        args = [arguments["prompt"], "--text", arguments["input_text"]]
        ok, out, err = _run(LLLM_PROMPT, args, timeout=300)
        return [TextContent(type="text", text=out if ok else f"Error: {err}")]

    elif short == "reason_on_text_async":
        args = [arguments["prompt"], "--text", arguments["input_text"], "--async"]
        if arguments.get("callback_uri"):
            args += ["--callback-uri", arguments["callback_uri"]]
        ok, out, err = _run(LLLM_PROMPT, args, timeout=30)
        return [TextContent(type="text", text=out if ok else f"Error: {err}")]

    elif short == "reason_on_file":
        args = [arguments["prompt"], "--file", arguments["file_path"]]
        ok, out, err = _run(LLLM_PROMPT, args, timeout=300)
        return [TextContent(type="text", text=out if ok else f"Error: {err}")]

    elif short == "reason_on_file_async":
        args = [arguments["prompt"], "--file", arguments["file_path"], "--async"]
        if arguments.get("callback_uri"):
            args += ["--callback-uri", arguments["callback_uri"]]
        ok, out, err = _run(LLLM_PROMPT, args, timeout=30)
        return [TextContent(type="text", text=out if ok else f"Error: {err}")]

    elif short == "list_models":
        ok, out, err = _run(LLLM_MANAGER, ["list-models"])
        return [TextContent(type="text", text=out if ok else f"Error: {err}")]

    elif short == "switch_model":
        ok, out, err = _run(LLLM_MANAGER, ["switch", "--model", arguments["model"]])
        return [TextContent(type="text", text=out if ok else f"Error: {err}")]

    elif short == "server_start":
        ok, out, err = _run(LLLM_MANAGER, ["start", "--model", arguments["model"]])
        return [TextContent(type="text", text=out if ok else f"Error: {err}")]

    elif short == "server_stop":
        ok, out, err = _run(LLLM_MANAGER, ["stop"])
        return [TextContent(type="text", text=out if ok else f"Error: {err}")]

    elif short == "server_status":
        ok, out, err = _run(LLLM_MANAGER, ["status"])
        return [TextContent(type="text", text=out if ok else f"Error: {err}")]

    elif short == "get_result":
        ok, out, err = _run(LLLM_PROMPT, ["--get-result", arguments["request_id"]])
        return [TextContent(type="text", text=out if ok else f"Error: {err}")]

    return None
