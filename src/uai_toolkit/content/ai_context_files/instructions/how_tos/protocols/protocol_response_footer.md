# Response Footer Protocol

**Version:** 2.0.0
**Created:** 2026-04-30
**Status:** active
**Supersedes:** spec_response_footer v1.3 (v1.4)
**Maintainer:** PianoMan
**Design Source:** todo_0282 design doc rev 5

## Summary

Defines how AI sessions assemble and include response footers. The footer is built programmatically by `build_footer.py`, wrapped by the `sessions_get_footer` MCP tool. Data comes from session state, transcript stats, and statusline — gathered in two phases (pre-response hook + end-of-response assembly).

## Changes from v1.3/v1.4

- **Dropped:** Persona, Chat
- **Added:** Tracking_ID, CLI_UUID, Platform, Roles, Turn, Tokens
- **Renamed:** Usage -> Ctx Used, Msg -> Msgs
- **New:** Brief/full modes with auto cadence and dynamic format configuration
- **New:** Programmatic assembly replaces manual construction

## Protocol: When and How to Include Footers

1. AI sessions MUST call `sessions_get_footer` as the last action before finishing a response.
2. The returned string is included verbatim at the end of the response.
3. The AI provides `tags` (2-8 keywords) describing the response content.
4. The AI may override `mode` ("brief", "full") or omit for auto-cadence.

## Two-Phase Data Gathering

### Phase 1: UserPromptSubmit Hook (pre-response)

Fires when the user sends a message, before the AI responds.

**Script:** `ai_general/scripts/session_mgmt/hook_prompt_submit.py`

**Actions:**
1. Resolves session identity from `AI_TRACKING_ID` and `AI_SESSION_DIR` env vars
2. Locates statusline via `find_instance_file(session_data_dir, "statusline", "json")`
3. Reads the statusline file
4. Writes to session state under exclusive file lock:
   - `context.used_pct` — context window usage percentage
   - `context.tokens` — total token count
   - `context.cost_usd` — session cost
   - `context.updated_at` — timestamp of this cache

This makes context data available to the AI at any point during the turn via `sessions_state_get context.used_pct`, enabling context-aware behavior (e.g., deciding to compact).

**Platforms:** Claude Code and Gemini (native hooks). Codex: graceful degradation (context data may be absent).

### Phase 2: get_footer Call (end of response)

**Script:** `ai_general/scripts/session_mgmt/build_footer.py`
**MCP Tool:** `sessions_get_footer`

**Actions:**
1. Reads session state from disk (shared lock — gets hook-written context data)
2. Reads identity/config (display_name, IDs, roles, loaded docs, etc.)
3. Reads `context.used_pct` and `context.tokens` from store
4. Calls `read_jsonl.py summary <cli_uuid>` to derive Turn and Msgs counts
5. If store context data is missing (Codex, hook failure), falls back to direct statusline read
6. Computes timestamp (local time)
7. Resolves format template from store (or defaults)
8. Performs `{variable}` replacement
9. Returns formatted string

## Data Source Map

| Field | Variable | Source | Derivation |
|---|---|---|---|
| Timestamp | `{timestamp}` | System clock | `datetime.now()` local tz |
| AI_Name | `{display_name}` | Store: `session.display_name` | Fallback: platform name |
| Tracking_ID | `{tracking_id}` | Store: `env.AI_TRACKING_ID` | Fallback: `NA` |
| CLI_UUID | `{cli_uuid}` | Store: `env.AI_CLI_SESSION_ID` | Fallback: `NA` |
| Platform | `{platform}` | Store: `env.AI_SESSION_PLATFORM` | Fallback: `NA` |
| Proj | `{project}` | Store: `env.AI_PROJECT_DIR` | Last path component, CamelCase |
| Roles | `{roles}` | Store: `role` list | Comma-joined |
| Turn | `{turns}` | `read_jsonl.py summary` | `user_messages` (user exchange count) |
| Msgs | `{msgs}` | `read_jsonl.py summary` | `message_count` (total all types) |
| Ctx Used | `{ctx_used_pct}` | Store: `context.used_pct` | Fallback: statusline direct read |
| Tokens | `{tokens}` | Store: `context.tokens` | Fallback: statusline direct read |
| Docs | `{docs}` | Store: `loaded.docs` | Omitted if not set |
| MSlots | `{mslots}` | Store: `loaded.mslots` | Omitted if not set |
| Artifacts | `{artifacts}` | Store: `conversation.artifacts` | Omitted if not set |
| Tags | `{tags}` | Argument from caller | Required, no fallback |

**Count definitions:**
- **Turn** = `user_messages` — number of user exchanges
- **Msgs** = `message_count` — total messages of all types (user, assistant, tool_use, tool_result, etc.)

**Why counts are derived, not accumulated:** Accumulated counters drift when hooks fail, files are lost, or sessions resume. Deriving from the transcript is always correct. Cost: ~1-2s per call for large transcripts.

**Why context data IS cached via hook:** Context data doesn't need to be exact-to-the-current-message. The start-of-turn value is close enough for the footer and useful throughout the turn for AI decision-making.

## Footer Formats

### Default Brief (every turn except every Nth)
```
{timestamp} | {display_name} | {tracking_id} | Ctx Used:{ctx_used_pct}% | Tokens:{tokens} | Turn:{turns}
Tags: {tags}
```

### Default Full (every Nth turn, default N=5)
```
{timestamp} | {display_name} | {tracking_id} | {cli_uuid}
{platform} | {project} | Roles:{roles} | Turn:{turns} | Msgs:{msgs} | Ctx Used:{ctx_used_pct}% | Tokens:{tokens}
Docs:{docs} | MSlots:{mslots} | Artifacts:{artifacts} | Tags: {tags}
```

### Dynamic Configuration

Format templates are stored in session state and configurable at runtime:

- `footer.format_brief` — format string for brief mode
- `footer.format_full` — format string for full mode
- `footer.full_every` — cadence for full footer (default: 5)

`build_footer.py` reads the format string, resolves `{variable}` references, and returns the assembled string. Variables resolving to None are handled gracefully.

Sessions can customize their footer: a worker session might use a minimal footer, an architect session includes more detail.

### Cadence

Full footer when `turn_count % footer.full_every == 0`. Turn count is derived from the transcript (not stored), so cadence is always accurate.

### Override

`mode` argument: `"brief"`, `"full"`, or omit for auto-cadence.

## Graceful Degradation

| Field | Fallback |
|---|---|
| AI_Name | Platform name (e.g., `claude_cli`) |
| Tracking_ID | `NA` |
| CLI_UUID | `NA` |
| Platform | `NA` |
| Proj | `NA` |
| Turn | `NA` (read_jsonl failed) |
| Msgs | Omitted on brief; `NA` on full |
| Ctx Used | Store -> statusline -> `NA` |
| Tokens | Store -> statusline -> `NA` |
| Docs, MSlots, Artifacts | Omitted if not set |
| Tags | Required — error if not provided |

## Interfaces

### CLI
```bash
build_footer.py <tracking_id> --tags "design,footer" [--mode brief|full] [--data-dir /path]
session_mgr.py get_footer <tracking_id> --tags "design,footer" [--mode brief|full] [--data-dir /path]
```

### MCP Tool
```
sessions_get_footer
  tags: string (required) — comma-separated keywords (2-8)
  mode: string (optional) — "brief", "full", or omit for auto
  Returns: formatted footer string
```

The MCP tool resolves tracking_id from the module-level SessionStore instance. The caller does not need to pass tracking_id.

## Dependencies

- `spec_session_state_store` v1.0 — session state reads
- `read_jsonl.py` — transcript summary. Syntax: `read_jsonl.py summary <uuid> [--platform claude|codex|gemini]`
- `lib_session.py` — `find_instance_file()` for discriminated filenames
- Statusline JSON — context/token data fallback
- `schema_hook_definition` — UserPromptSubmit hook definition

## Related

- `spec_session_state_store` v1.0 — data store consumed by this protocol
- `spec_session_identity` v5.3 — session identity model
- `schema_hook_definition` — hook that populates context data
