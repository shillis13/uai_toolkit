---
name: reference_mcp_schema_validation
description: Anthropic API server-side draft-2020-12 schema enforcement (rolled out
  ~2026-06-11) 400s on invalid MCP tool schemas — all client versions; stale client
  tool-caches keep the error alive after the fix
status: active
---

The Anthropic **API server-side** validates every tool `input_schema` against JSON Schema draft 2020-12. Strict enforcement rolled out ~**2026-06-11** and hit **all Claude Code versions simultaneously** (2.1.86 and 2.1.173 alike) — the client version is irrelevant. Error: `400 invalid_request_error: tools.N.custom.input_schema: JSON schema is invalid`. The index `N` shifts per session's tool layout, so one bad tool looks like multiple bugs. Sessions with deferred MCP tools are immune until they load the bad tool.

First case: comms `comms_send_slash_command` had `required: [identifier, identifier, command]` (duplicate violates `uniqueItems`). It entered tools.yml **2026-05-30** and worked for ~12 days before the API started rejecting it — proof the change was server-side. (Earlier version of this memory blamed CC 2.1.173 "forwarding schemas verbatim" — **falsified** and corrected.)

**Why a tools.yml fix doesn't reach running sessions:** Claude Code caches each MCP server's tool list at connect time and refetches only on `notifications/tools/list_changed` or reconnect. The shared ToolRegistry used to emit list_changed only when tool *names* changed, so a schema-only fix never propagated — running sessions kept 400ing on the stale cached schema. **Unblock a live session: `/mcp` → reconnect the server** (or restart the session). Also: long-running MCP server *processes* run pre-fix code; only data (tools.yml) hot-reloads, not Python.

**Forensic detail (2026-06-12, session 343a052b):** Enforcement flipped at ~2026-06-12T01:20Z (21:20 EDT Jun 11) — first 400 in transcripts. On 2.1.173 with deferred tools, a session is poisoned only if it ToolSearch-loaded the bad tool (recorded as `tool_reference` entries in tool_results — grep the JSONL for the tool name); the schema itself isn't in the transcript, it comes from the client's connect-time cache. So: error index `tools.N` lands in the native+loaded-refs zone and varies per session; two same-version sessions differ because one loaded/held the bad tool and the other didn't. Rule: any CC process that (re)started or reconnected comms AFTER the fix (~2026-06-12T02:00Z) is clean; older unreconnected processes still 400.

**Remedy (VERIFIED 2026-06-12 on session 343a052b):** `/mcp` → select the *specific poisoned server* (comms) → reconnect → fixed immediately, including ToolSearch-loaded reference schemas. CRITICAL: a bare `/mcp` may reconnect a different server (it showed "Reconnected to chat") and fix nothing — the reconnect must target the server whose schema is bad. Works on 2.1.173 (deferred) and expected on 2.1.86 (full tool list).

**Diagnose:** `$HOME/myenv/bin/python ai_general/scripts/setup/validate_mcp_schemas.py [server...]` — runs `Draft202012Validator.check_schema` (same check as the API) against every server in `~/.claude/mcp_cli_config.json`.

**Prevention (in `ai_general/apps/mcps/shared/tool_registry.py`):** (1) auto-dedupes `required` arrays recursively + warns on any remaining draft-2020-12 violation at load; (2) `list_changed` now fires on a sha256 digest of full tool definitions (names + descriptions + schemas), not just names. Covers comms/knowledge/sessions/workflow. Hooks never define API tools — hook edits can't cause this error. Related: [[feedback_enforce_dont_instruct]], [[feedback_explain_root_cause]].
