"""MCP tool: model-backed reasoning over a CONFIGURED endpoint.

Toolkit version of the upstream local-LLM tool. Upstream shells out to
scripts/lllm/{lllm_prompt,lllm_manager}.py, which drive a locally-run model
SERVER. This package ships no such server, so the reasoning calls are routed
through the shared per-feature client instead (uai_toolkit.llm, feature
``mcp_prompt``) and the server-lifecycle tools are not offered here.

WHAT THIS OFFERS
    sessions_reason_on_text   prompt + inline text  -> model answer
    sessions_reason_on_file   prompt + a file's text -> model answer
    sessions_list_models      report the endpoints configured for this feature

INTENTIONALLY NOT OFFERED (upstream-only)
    server_start / server_stop / server_status / switch_model
        These start, stop, and re-point a LOCAL model server process. A
        configured endpoint — which may be a hosted service — has no such
        process for us to manage, so exposing them here would be a lie.
    reason_on_text_async / reason_on_file_async / get_result
        The async variants hand work to the local request queue
        (scripts/lllm/request_queue.py), which is part of that same local server
        stack and is not vendored. Use the synchronous calls.

ENDPOINT / SECURITY
    The destination is whatever ``mcp_prompt`` names in the LLM endpoint config —
    an internally-hosted OpenAI-compatible model, a hosted API, or nothing.
    Nothing is configured by default: with no config these tools report that the
    feature is unconfigured and make no network connection.
    See src/uai_toolkit/llm/llm_endpoints.example.json.
"""

import asyncio
from pathlib import Path

from mcp.types import TextContent

from uai_toolkit.llm import complete, is_configured, load_endpoints

PREFIX = "sessions_"

# Reading a whole file into a prompt is unbounded by nature; cap it so a stray
# multi-megabyte path cannot be shipped to an endpoint by accident.
MAX_FILE_CHARS = 200_000

_UNCONFIGURED = (
    "The 'mcp_prompt' feature has no endpoint configured, so no model is "
    "available and no request was sent. Configure it in the LLM endpoint config "
    "($AI_ROOT/config/llm_endpoints.json, or $AI_LLM_ENDPOINTS) — see "
    "llm_endpoints.example.json for the shape."
)


def tools() -> list:
    """Tool definitions discovered by the sessions MCP server."""
    return [
        {
            "name": f"{PREFIX}reason_on_text",
            "description": (
                "Ask the configured reasoning model about inline text. Text in, "
                "text out — the model has no tools and cannot act. Returns a "
                "notice instead if no endpoint is configured."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string",
                               "description": "The instruction for the model."},
                    "input_text": {"type": "string",
                                   "description": "The text to reason over."},
                },
                "required": ["prompt", "input_text"],
            },
        },
        {
            "name": f"{PREFIX}reason_on_file",
            "description": (
                "Ask the configured reasoning model about a file's contents. The "
                "file is read locally and its text sent to the endpoint "
                f"(truncated at {MAX_FILE_CHARS} characters)."
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "prompt": {"type": "string",
                               "description": "The instruction for the model."},
                    "file_path": {"type": "string",
                                  "description": "Path to the file to reason over."},
                },
                "required": ["prompt", "file_path"],
            },
        },
        {
            "name": f"{PREFIX}list_models",
            "description": (
                "List the endpoints configured for the 'mcp_prompt' feature, in "
                "the order they would be tried. Reports configuration only — it "
                "contacts nothing."
            ),
            "inputSchema": {"type": "object", "properties": {}},
        },
    ]


def _text(msg: str) -> list:
    return [TextContent(type="text", text=msg)]


def _read_file_body(path: Path) -> str:
    """Read at most the amount that can be sent to an endpoint."""
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        body = handle.read(MAX_FILE_CHARS + 1)
    if len(body) > MAX_FILE_CHARS:
        return body[:MAX_FILE_CHARS] + "\n...[truncated]"
    return body


async def call_tool(name: str, arguments: dict) -> list | None:
    short = name.replace(PREFIX, "", 1)

    if short == "list_models":
        endpoints = load_endpoints("mcp_prompt")
        if not endpoints:
            return _text(_UNCONFIGURED)
        lines = ["Endpoints configured for 'mcp_prompt' (tried in order):"]
        for i, ep in enumerate(endpoints, 1):
            lines.append(
                f"  {i}. {ep.get('name', '?')}  kind={ep.get('kind', 'openai')}  "
                f"model={ep.get('model', '?')}  base_url={ep.get('base_url')}"
            )
        return _text("\n".join(lines))

    if short in ("reason_on_text", "reason_on_file"):
        if not is_configured("mcp_prompt"):
            return _text(_UNCONFIGURED)

        prompt = arguments["prompt"]
        if short == "reason_on_text":
            body = arguments["input_text"]
        else:
            path = Path(arguments["file_path"]).expanduser()
            try:
                body = await asyncio.to_thread(_read_file_body, path)
            except OSError as e:
                return _text(f"Error: could not read {path}: {e}")

        try:
            # The sessions MCP server is async; keep synchronous HTTP and file I/O
            # off its event loop so one slow endpoint does not stall every tool.
            out = await asyncio.to_thread(
                complete, "mcp_prompt", prompt, body, max_tokens=2000,
            )
        except Exception as e:                 # complete() shouldn't raise; be safe
            return _text(f"Error: {type(e).__name__}: {e}")
        if not out:
            return _text(
                "Error: no configured endpoint returned an answer (all endpoints "
                "in the chain failed, timed out, or lacked a credential)."
            )
        return _text(out)

    return None
