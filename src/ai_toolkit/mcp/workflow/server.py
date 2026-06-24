"""workflow MCP server (ai_toolkit) — todo path.

Ported from ai_general/apps/mcps/workflow. First cut registers the todo
sub-module (backed by the ported todo_mgr). task_coord slots in once callback_lib
is ported; devtree is deferred (git-worktree / dev-env management, Unix-coupled).

Direct module dispatch (same simplification as the knowledge server).

Run: ai-mcp-workflow  (stdio MCP server; needs ai_toolkit[mcp] + AI_ROOT)
"""
from __future__ import annotations

import asyncio

from mcp.server import Server, NotificationOptions
from mcp.server.stdio import stdio_server
from mcp.types import TextContent

from ai_toolkit.mcp.workflow.tools import workflow_todo

# task_coord (needs callback_lib) + devtree (git-worktree) added as ported.
MODULES = [workflow_todo]

server = Server("workflow")


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
