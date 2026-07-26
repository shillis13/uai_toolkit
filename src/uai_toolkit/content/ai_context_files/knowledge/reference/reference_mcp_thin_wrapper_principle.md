---
name: reference_mcp_thin_wrapper_principle
description: MCP funcs are thin schema/param-assembly wrappers; business logic lives
  in scripts (single source of truth, live via subprocess). New param = script change
  + small MCP schema/passthrough edit + reconnect.
status: active
---

PianoMan, affirmed 2026-06-30: "As long as the business logic is in the scripts, some adjustments to MCP functions are expected to assemble and set parameters."

**Architecture convention for this workspace (`ai_general/`):**
- **Business logic lives in `scripts/`** (e.g. `scripts/context_files/guidance_lib.py` + `guidance_cli.py`). It is the single source of truth and is **live immediately**, because the MCP servers subprocess to the CLI per call (fresh code each time).
- **MCP functions (`apps/mcps/<server>/tools/*.py`) are a THIN layer**: declare the tool's inputSchema, assemble/validate parameters, and forward to the script. No business logic.
- Adding/changing a capability ⇒ change the script (engine) **and** make a small MCP-side edit (schema + `_build_cli_args`/passthrough). That MCP edit is **expected and normal**, not a smell.

**Reconnect caveat:** the MCP tool module runs **in-process** in the server, so a changed inputSchema or passthrough only takes effect after the running server reloads (`/mcp reconnect <server>` or the `comms_reconnect_mcp_servers` tool). The script-side logic needs no reconnect (subprocess reads current code). So an unreconnected session silently ignores a new param and uses defaults.

Pairs with [[reference_adding_mcp_tools]] (the 3-edit mechanics). This is the *why*: keep logic in scripts so it's reload-free and testable via CLI; the MCP is just the interface skin.
