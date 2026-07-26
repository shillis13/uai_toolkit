---
name: reference_adding_mcp_tools
description: How to add a tool to a consolidated MCP server (comms/knowledge/sessions/workflow)
  — the 3 edit points and the reload-on-miss that makes it live without restart
status: active
---

The consolidated MCP servers live in `ai_general/apps/mcps/{comms,knowledge,sessions,workflow}/`. Adding a NEW tool requires **three** edits (a rename needs only `tools.yml`):

1. **`tools.yml`** — registry entry the client sees: `name`, `description`, `handler` (must equal the Tool name in step 2), `module`, `inputSchema`. File-watched → advertised live via `list_changed`.
2. **`tools/<module>.py` `tools()`** — append a `Tool(name=..., inputSchema=...)`. This is what `server.py build_dispatch()` scans to map `name -> module.call_tool`.
3. **`tools/<module>.py call_tool()`** — add an `elif name == "<tool>":` branch with the handler logic (the big if/elif on `name`).

**The gap that used to bite (fixed 2026-06-14):** `HANDLER_DISPATCH` was built once at import, so a brand-new tool was *advertised* (tools.yml hot-reloads) but *unhandled* → "Unknown tool: X". The servers were half-dynamic — names hot, handlers cold. Same bug hit `comms_send_slash_command` and `comms_load_context`.

**Fix:** all four `server.py` now have `build_dispatch(reload=True)` called as **reload-on-miss** in `call_tool`. So a new tool goes live on its first call — no restart. Caveat: editing `server.py` itself still needs one reconnect (a module can't reload itself); and the running server in *your* session is the pre-edit process until the next `/mcp` reconnect or new session.

**Second gap, closed 2026-07-01 (todo_0378):** the 2026-06-14 fix only covered a new tool in an *existing* module. A brand-new `tools/<x>.py` MODULE was still cold until restart, because `build_dispatch` iterated a hardcoded `modules = [...]` list bound at import. Now `build_dispatch` DISCOVERS modules by globbing `tools/*.py` (any module exposing `tools()` + `call_tool`) via the shared helper `apps/mcps/shared/handler_dispatch.py`, re-globbing on reload — so dropping a new module file auto-registers on the next dispatch-miss, zero restart. Verified live on the sessions server (56→57 handlers on a dropped-in module). All four servers use the shared helper; the hardcoded `modules` lists are gone. So **step-1's `module:` field in tools.yml + a new `tools/<x>.py` is all it takes** — no server.py edit to register a new module anymore.

See [[reference_mcp_schema_validation.md]] for the separate schema-cache reconnect issue. The shared discovery helper is the enforce-in-infra version of this whole note ([[feedback_enforce_dont_instruct]]).
