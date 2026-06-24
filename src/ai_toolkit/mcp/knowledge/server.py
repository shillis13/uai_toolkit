"""knowledge MCP server (ai_toolkit) — guidance vertical slice.

Ported from ai_general/apps/mcps/knowledge. This first cut registers the
guidance sub-module; the search / memory / jsonl / chat_pipeline modules slot
in as their backing scripts get ported — add them to MODULES below.

Simplification vs. the original: direct module dispatch instead of the
tools.yml ToolRegistry (the dynamic tool-rename layer). The registry is ported
at ai_toolkit.mcp.shared.tool_registry and can be reintroduced when wanted.

Run: ai-mcp-knowledge  (stdio MCP server; needs ai_toolkit[mcp] + AI_ROOT content)
"""
from __future__ import annotations

import asyncio

from mcp.server import Server, NotificationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent

from ai_toolkit.mcp.knowledge.tools import (
    knowledge_guidance,
    knowledge_memory,
    knowledge_search,
    knowledge_jsonl,
)

# Sub-modules registered with this server. Each exposes tools() + call_tool().
# chat_pipeline is deferred (heavy: subprocesses the 7-stage pipeline + yaml).
MODULES = [knowledge_guidance, knowledge_memory, knowledge_search, knowledge_jsonl]

server = Server("knowledge")


def _build_dispatch() -> dict:
    dispatch: dict = {}
    for module in MODULES:
        for tool in module.tools():
            if tool.name in dispatch:
                raise RuntimeError(f"Duplicate handler: {tool.name}")
            dispatch[tool.name] = module.call_tool
    return dispatch


DISPATCH = _build_dispatch()


@server.list_tools()
async def list_tools():
    tools = []
    for module in MODULES:
        tools.extend(module.tools())
    return tools


@server.call_tool()
async def call_tool(name: str, arguments: dict):
    handler = DISPATCH.get(name)
    if handler is None:
        return [TextContent(type="text", text=f"Unknown tool: {name}")]
    result = await handler(name, arguments)
    if result is None:
        return [TextContent(type="text", text=f"No output for {name}")]
    return result


async def main():
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options(
                notification_options=NotificationOptions(tools_changed=True)
            ),
        )


def run():
    asyncio.run(main())


if __name__ == "__main__":
    run()
