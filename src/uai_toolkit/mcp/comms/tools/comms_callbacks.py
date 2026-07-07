"""
Comms callback tools — generate and execute callback endpoint URIs.

Tools:
    comms_make_endpoint    Generate a callback endpoint URI from parameters
    comms_deliver          Deliver a message to a callback endpoint URI
    comms_parse_endpoint   Parse a callback endpoint URI into its component fields
"""

import json
import sys
from pathlib import Path
from mcp.types import Tool, TextContent

# Import from extracted callback library
CALLBACK_LIB = Path.home() / "bin/ai/callbacks"
if str(CALLBACK_LIB) not in sys.path:
    sys.path.insert(0, str(CALLBACK_LIB))

from uai_toolkit.callbacks.callback_lib import make_endpoint_uri, execute_uri, parse_endpoint


def tools() -> list[Tool]:
    return [
        Tool(
            name="comms_make_endpoint",
            description=(
                "Generate a callback endpoint URI. Returns a single string that "
                "can be passed to any responder — the responder calls comms_deliver "
                "with the URI to send back a response. The responder never needs to "
                "know what kind of endpoint it is."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "scheme": {
                        "type": "string",
                        "enum": ["file", "fifo", "prompt", "none"],
                        "description": (
                            "Endpoint type. "
                            "file = write to a regular file. "
                            "fifo = write to a named pipe (caller must create it first). "
                            "prompt = send via send_prompt.py to an AI session. "
                            "none = no delivery."
                        ),
                    },
                    "path": {
                        "type": "string",
                        "description": (
                            "For file/fifo: absolute file path. "
                            "For prompt: the target platform (e.g. 'claude-cli')."
                        ),
                    },
                    "session": {
                        "type": "string",
                        "description": "For prompt://: target session identifier.",
                    },
                    "template": {
                        "type": "string",
                        "description": "Optional message template. Use {message} as placeholder for the delivered content.",
                    },
                    "submit": {
                        "type": "boolean",
                        "description": "For prompt://: press Enter after sending. Default true.",
                        "default": True,
                    },
                    "force": {
                        "type": "boolean",
                        "description": "For prompt://: send even if target is busy. Default false.",
                        "default": False,
                    },
                },
                "required": ["scheme"],
            },
        ),
        Tool(
            name="comms_deliver",
            description=(
                "Deliver a message to a callback endpoint URI. The URI was provided "
                "by the originator (via comms_make_endpoint or embedded in a message). "
                "You don't need to know what kind of endpoint it is — just pass the "
                "URI and the message."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "description": "Callback endpoint URI (e.g. file:///tmp/resp.txt, fifo:///tmp/pipe, prompt://claude-cli/session).",
                    },
                    "message": {
                        "type": "string",
                        "description": "The response message to deliver.",
                    },
                },
                "required": ["endpoint", "message"],
            },
        ),
        Tool(
            name="comms_parse_endpoint",
            description=(
                "Parse a callback endpoint URI into its component fields. "
                "Use this to inspect or decompose a URI you received."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "endpoint": {
                        "type": "string",
                        "description": "Callback endpoint URI (e.g. file:///tmp/resp.txt, prompt://claude-cli/abc123?submit=true).",
                    },
                },
                "required": ["endpoint"],
            },
        ),
    ]


async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    if name == "comms_make_endpoint":
        return _make_endpoint(arguments)
    if name == "comms_deliver":
        return _deliver(arguments)
    if name == "comms_parse_endpoint":
        return _parse_endpoint(arguments)
    return [TextContent(type="text", text=f"Unknown tool: {name}")]


def _make_endpoint(args: dict) -> list[TextContent]:
    try:
        uri = make_endpoint_uri(
            scheme=args["scheme"],
            path=args.get("path", ""),
            session=args.get("session", ""),
            template=args.get("template", ""),
            submit=args.get("submit", True),
            force=args.get("force", False),
        )
        return [TextContent(type="text", text=uri)]
    except ValueError as e:
        return [TextContent(type="text", text=f"Error: {e}")]


def _deliver(args: dict) -> list[TextContent]:
    endpoint = args.get("endpoint", "")
    message = args.get("message", "")
    if not endpoint:
        return [TextContent(type="text", text="Error: endpoint is required")]
    if not message:
        return [TextContent(type="text", text="Error: message is required")]

    try:
        result = execute_uri(endpoint, message)
        if result.success:
            return [TextContent(type="text", text=f"OK: {result.message}")]
        return [TextContent(type="text", text=f"FAIL: {result.message}")]
    except ValueError as e:
        return [TextContent(type="text", text=f"Error parsing endpoint: {e}")]


def _parse_endpoint(args: dict) -> list[TextContent]:
    endpoint = args.get("endpoint", "")
    if not endpoint:
        return [TextContent(type="text", text="Error: endpoint is required")]

    try:
        ep = parse_endpoint(endpoint)
        result = {
            "scheme": ep.scheme,
            "path": ep.path,
            "session": ep.session,
            "template": ep.template,
            "submit": ep.submit,
            "force": ep.force,
        }
        return [TextContent(type="text", text=json.dumps(result, indent=2))]
    except ValueError as e:
        return [TextContent(type="text", text=f"Error: {e}")]
