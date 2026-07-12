# Hook Framework

Central hook handler directory. One dispatcher (`dispatch.py`) routes all three AI CLI platforms to the same handlers.

## Architecture

```
~/.claude/settings.json  ─┐
~/.codex/hooks.json       ─┼─→  dispatch.py <EventName>  ─→  {Type}/*_sync*  (sequential)
~/.gemini/settings.json  ─┘                               ─→  {Type}/*_async* (parallel)
```

Each platform config has one entry per event type pointing at `dispatch.py`. The dispatcher scans the appropriate directory, runs `_sync` handlers in numeric order (stops on exit 2 = block), and fires `_async` handlers concurrently.

## Platform Event Name Mapping

Gemini uses different event names. The dispatcher maps them to our canonical directory names.

┌───────────────────────────┬──────────────────┬──────────────────┬──────────────┐
│ **Canonical (directory)** │ **Claude Code**  │ **Codex**        │ **Gemini**   │
├───────────────────────────┼──────────────────┼──────────────────┼──────────────┤
│ `SessionStart`            │ SessionStart     │ SessionStart     │ SessionStart │
├───────────────────────────┼──────────────────┼──────────────────┼──────────────┤
│ `UserPromptSubmit`        │ UserPromptSubmit │ UserPromptSubmit │ BeforeAgent  │
├───────────────────────────┼──────────────────┼──────────────────┼──────────────┤
│ `PreToolUse`              │ PreToolUse       │ PreToolUse       │ BeforeTool   │
├───────────────────────────┼──────────────────┼──────────────────┼──────────────┤
│ `PostToolUse`             │ PostToolUse      │ PostToolUse      │ AfterTool    │
├───────────────────────────┼──────────────────┼──────────────────┼──────────────┤
│ `PreCompact`              │ PreCompact       │ —                │ PreCompress  │
├───────────────────────────┼──────────────────┼──────────────────┼──────────────┤
│ `PostCompact`             │ PostCompact      │ —                │ —            │
├───────────────────────────┼──────────────────┼──────────────────┼──────────────┤
│ `Stop`                    │ Stop             │ Stop             │ AfterAgent   │
├───────────────────────────┼──────────────────┼──────────────────┼──────────────┤
│ `Notification`            │ —                │ —                │ Notification │
└───────────────────────────┴──────────────────┴──────────────────┴──────────────┘

"—" means the platform doesn't support that event.

> **Scope note:** the table above lists only the events we currently *route* through the
> dispatcher — not the full set each platform supports. Two cells are also out of date vs.
> platform capability: **Claude Code *does* fire `Notification`** (we just have no handler),
> and **Codex *does* support `PreCompact`/`PostCompact`/`PermissionRequest`/`SubagentStart`/
> `SubagentStop`** (the "—" reflects what we wire, not capability). For the complete,
> source-verified lists — including events we don't yet handle — see the reference below.

## Complete Hook Event Reference

Source-verified against the official docs (fetched 2026-06-20):
- **Claude Code** — https://code.claude.com/docs/en/hooks.md
- **Codex** — https://developers.openai.com/codex/hooks

### Claude Code — 30 events

| Event | Fires when | Matchers | We handle? |
|---|---|---|---|
| `SessionStart` | a session begins or resumes | `startup`, `resume`, `clear`, `compact` | ✅ |
| `Setup` | `--init-only`, or `--init`/`--maintenance` in `-p` mode | `init`, `maintenance` | — |
| `UserPromptSubmit` | a prompt is submitted, before Claude processes it | (none) | ✅ |
| `UserPromptExpansion` | a typed command expands into a prompt | command names | — |
| `PreToolUse` | before a tool call executes (can block) | tool names | ✅ |
| `PermissionRequest` | a permission dialog appears | tool names | — |
| `PermissionDenied` | a tool call is denied by the auto-mode classifier | tool names | — |
| `PostToolUse` | after a tool call succeeds | tool names | ✅ |
| `PostToolUseFailure` | after a tool call fails | tool names | — |
| `PostToolBatch` | after a parallel tool batch resolves | (none) | — |
| `Notification` | Claude Code sends a notification | `permission_prompt`, `idle_prompt`, `auth_success`, `elicitation_*` | — (dir exists, empty) |
| `MessageDisplay` | while assistant message text is displayed | (none) | — |
| `SubagentStart` | a subagent is spawned | agent types | — |
| `SubagentStop` | a subagent finishes | agent types | — |
| `TaskCreated` | a task is created via `TaskCreate` | (none) | — |
| `TaskCompleted` | a task is marked completed | (none) | — |
| `Stop` | Claude finishes responding | (none) | ✅ |
| `StopFailure` | the turn ends due to an API error | `rate_limit`, `overloaded`, `authentication_failed`, … | — |
| `TeammateIdle` | an agent-team teammate is about to go idle | (none) | — |
| `InstructionsLoaded` | a CLAUDE.md / `rules/*.md` is loaded into context | `session_start`, `nested_traversal`, `path_glob_match`, `include`, `compact` | — |
| `ConfigChange` | a config file changes mid-session | `user_settings`, `project_settings`, `local_settings`, `policy_settings`, `skills` | — |
| `CwdChanged` | the working directory changes | (none) | — |
| `FileChanged` | a watched file changes on disk | literal filenames | — |
| `WorktreeCreate` | a worktree is created | (none) | — |
| `WorktreeRemove` | a worktree is removed | (none) | — |
| `PreCompact` | before context compaction | `manual`, `auto` | ✅ |
| `PostCompact` | after context compaction completes | `manual`, `auto` | ✅ (handler symlinked to PreCompact) |
| `Elicitation` | an MCP server requests user input during a tool call | MCP server names | — |
| `ElicitationResult` | a user responds to an MCP elicitation | MCP server names | — |
| `SessionEnd` | a session terminates | `clear`, `resume`, `logout`, `prompt_input_exit`, `bypass_permissions_disabled`, `other` | — (planned: tag hygiene) |

### Codex — 10 events

Configured in `~/.codex/hooks.json` or `[hooks]` in `config.toml` (same schema). Codex uses the **same canonical names** as Claude Code (no Gemini-style aliases).

| Event | Fires when | Matchers | Scope |
|---|---|---|---|
| `SessionStart` | session starts | `startup`, `resume`, `clear`, `compact` | session |
| `SubagentStart` | a subagent begins | agent types | subagent |
| `PreToolUse` | before Bash / `apply_patch` / MCP tool call | `Bash`, `apply_patch`, MCP names | turn |
| `PermissionRequest` | Codex requests approval (escalation / network) | tool names | turn |
| `PostToolUse` | after a tool produces output | tool names | turn |
| `PreCompact` | before conversation compaction | `manual`, `auto` | turn |
| `PostCompact` | after conversation compaction | `manual`, `auto` | turn |
| `UserPromptSubmit` | before prompt submission | (none) | turn |
| `SubagentStop` | a subagent completes | agent types | turn |
| `Stop` | turn processing stops | (none) | turn |

**Codex does NOT have:** `SessionEnd`, `Notification`, nor the `PostToolUseFailure`/`PostToolBatch`/`Task*`/`Worktree*`/`ConfigChange`/`CwdChanged`/`MessageDisplay`/`Elicitation*`/`StopFailure`/`TeammateIdle`/`Setup`/`UserPromptExpansion`/`InstructionsLoaded` events Claude Code adds.

### Gemini
Uses aliased names mapped by `dispatch.py` `EVENT_ALIASES`: `BeforeAgent`→`UserPromptSubmit`, `AfterAgent`→`Stop`, `BeforeTool`→`PreToolUse`, `AfterTool`→`PostToolUse`, `PreCompress`→`PreCompact`. Gemini-only events not currently used: `BeforeModel`, `AfterModel`, `BeforeToolSelection`, `SessionEnd`.

### Coverage gaps (no handler yet)
- **`SessionEnd`** (Claude only) — needed for tag hygiene (move `Tags`→`PriorTags` on end).
- **`SubagentStart` / `SubagentStop`** (Claude + Codex) — unhandled.
- **`Notification`** (Claude + Gemini) — directory exists but empty.
- **`StopFailure`** (Claude only) — distinct API-error turn end; candidate for retry/notify logic.

## Platform Peculiarities

### Claude Code
- **Config:** `~/.claude/settings.json` under `hooks` key
- **Matcher:** glob pattern (`*`, `Edit|Write`)
- **Timeout:** seconds
- **Stop hook stdin:** includes `last_assistant_message` and `stop_hook_active`
- **PreToolUse stdin:** `tool_name` is `Edit`, `Write`, `Bash`, `Read`, `Grep`, `Glob`, etc.
- **Exit 0 + JSON:** supports `decision`, `reason`, `systemMessage` for Stop hooks
- **Exit 2:** blocks, stderr shown to AI as continuation prompt

### Codex
- **Config:** `~/.codex/hooks.json` (or `[hooks]` in `config.toml`)
- **Matcher:** regex pattern (`.*`, `Bash`)
- **Timeout:** seconds
- **Stop hook stdin:** includes `last_assistant_message`, `stop_hook_active`, and `turn_id`
- **PreToolUse stdin:** `tool_name` is `Bash` or `apply_patch` (not `Edit`/`Write`)
- **`apply_patch`:** file edits use unified diff format in `tool_input.command`, not `tool_input.file_path`
- **Env vars:** `shell_environment_policy.include_only` in config.toml controls which env vars hooks see. Our AI vars (`AI_ROOT`, `AI_TRACKING_ID`, etc.) are added there.
- **Feature flag:** may need `[features] codex_hooks = true` — currently working without it

### Gemini
- **Config:** `~/.gemini/settings.json` under `hooks` key
- **Matcher:** regex pattern (`.*`)
- **Timeout:** milliseconds (5000 = 5s, not 5)
- **Event names differ** — see mapping table above
- **Stop hook stdin:** field names may differ from Claude/Codex. Handlers use `transcript_path` JSONL fallback.
- **PreToolUse stdin:** tool names may differ from Claude/Codex
- **No PostCompact:** Gemini doesn't have a post-compression event
- **Extra events:** `BeforeModel`, `AfterModel`, `BeforeToolSelection`, `SessionEnd` — not currently used

## Handler Inventory

### SessionStart/
┌───────────────────────────────────────┬──────────┬───────────────────────────────────────────────────────────────────────────┐
│ **Handler**                           │ **Type** │ **Purpose**                                                               │
├───────────────────────────────────────┼──────────┼───────────────────────────────────────────────────────────────────────────┤
│ `01_inject_standing_messages_sync.py` │ sync     │ Inject applicable standing messages (global, platform, team, project) as  │
│                                       │          │ additionalContext                                                         │
└───────────────────────────────────────┴──────────┴───────────────────────────────────────────────────────────────────────────┘

### UserPromptSubmit/
┌─────────────────────────────────────┬──────────┬─────────────────────────────────────────────────────────┬
│ **Handler**                         │ **Type** │ **Purpose**                                             │
├─────────────────────────────────────┼──────────┼─────────────────────────────────────────────────────────┼
│ `01_deliver_queued_prompts_sync.py` │ sync     │ Deliver pre-prompt/post-prompt queue entries as         │
│                                     │          │ additionalContext                                       │
├─────────────────────────────────────┼──────────┼─────────────────────────────────────────────────────────┼
│ `02_prepend_context_sync.py`        │ sync     │ Prepend `[datetime]` to the prompt                      │
│                                     │          │                                                         │
├─────────────────────────────────────┼──────────┼─────────────────────────────────────────────────────────┼
│ `03_notify_unread_messages_sync.py` │ sync     │ Notify session of unread inbox/broadcast messages       │
└─────────────────────────────────────┴──────────┴─────────────────────────────────────────────────────────┴

### PreToolUse/
┌─────────────────────────────────────┬──────────┬─────────────────────────────────────────────────────────────────────────────────────┐
│ **Handler**                         │ **Type** │ **Purpose**                                                                         │
├─────────────────────────────────────┼──────────┼─────────────────────────────────────────────────────────────────────────────────────┤
│ `01_devtree_boundary_check_sync.sh` │ sync     │ Block edits outside devTree when `AI_PROJECT_DIR` contains `/devTrees/` . Handles   │
│                                     │          │ both `Edit` /`Write` (Claude) and `apply_patch` (Codex)                             │
├─────────────────────────────────────┼──────────┼─────────────────────────────────────────────────────────────────────────────────────┤
│ `02_devtree_bash_warning_sync.sh`   │ sync     │ Warn when bash commands reference main ai_root from a devTree session               │
├─────────────────────────────────────┼──────────┼─────────────────────────────────────────────────────────────────────────────────────┤
│ `03_block_lib_execution_sync.py`    │ sync     │ Block direct execution of `lib_*.py` files — use MCP or CLI wrappers instead        │
└─────────────────────────────────────┴──────────┴─────────────────────────────────────────────────────────────────────────────────────┘

### PostToolUse/
┌───────────────────────────┬──────────┬───────────────────────────────────────────────────────────────────────────────┐
│ **Handler**               │ **Type** │ **Purpose**                                                                   │
├───────────────────────────┼──────────┼───────────────────────────────────────────────────────────────────────────────┤
│ `01_audit_tools_async.py` │ async    │ Audit tool calls to JSONL. Supports all platforms via `AUDIT_PLATFORM` env    │
│                           │          │ var                                                                           │
└───────────────────────────┴──────────┴───────────────────────────────────────────────────────────────────────────────┘

### PreCompact/ and PostCompact/
┌─────────────────────────┬──────────┬────────────────────────────────────────────────────────────────────────────────────────┐
│ **Handler**             │ **Type** │ **Purpose**                                                                            │
├─────────────────────────┼──────────┼────────────────────────────────────────────────────────────────────────────────────────┤
│ `01_compaction_sync.py` │ sync     │ Log compaction events to session dir + central audit, send user notification.          │
│                         │          │ PostCompact is a symlink to PreCompact.                                                │
└─────────────────────────┴──────────┴────────────────────────────────────────────────────────────────────────────────────────┘

### Stop/
┌──────────────────────────────────────────┬──────────┬──────────────────────────────────────────────────────────────────────┐
│ **Handler**                              │ **Type** │ **Purpose**                                                          │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────┤
│ `01_deliver_postresponse_sync.py`        │ sync     │ Deliver postResponse queued prompts via send_prompt                  │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────┤
│ `02_block_permission_seeking_sync.py`    │ sync     │ **Blocks** responses ending with "Want me to...", "Should I...",     │
│                                          │          │ etc.                                                                 │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────┤
│ `03_quality_gate_sync.py`                │ sync     │ Evaluate response against quality checklist (observe mode — logs,    │
│                                          │          │ doesn't block)                                                       │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────┤
│ `04_capture_context_sync.py`             │ sync     │ Write context% and token counts to session state file                │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────┤
│ `05_block_intent_without_action_sync.py` │ sync     │ **Blocks** responses that state intent ("I will...", "Let me...")    │
│                                          │          │ without acting                                                       │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────┤
│ `06_notify_unread_messages_sync.py`      │ sync     │ Notify session of unread messages via systemMessage                  │
├──────────────────────────────────────────┼──────────┼──────────────────────────────────────────────────────────────────────┤
│ `07_remind_owed_replies_sync.py`         │ sync     │ Remind session of pending reply obligations                          │
└──────────────────────────────────────────┴──────────┴──────────────────────────────────────────────────────────────────────┘

### Notification/
Empty — no handlers yet.

## Common Libraries

┌──────────────────────────────┬───────────────────────────────────────────────────────────────────────────────────┐
│ **File**                     │ **Purpose**                                                                       │
├──────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
│ `common/lib_hook_base.py`    │ `run_hook()` , `HookResult` , `HookContext` — standardized entry point with       │
│                              │ logging                                                                           │
├──────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
│ `common/lib_hook_scripts.py` │ Prompt queue utilities (load, filter, compose, deliver)                           │
├──────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
│ `common/lib_stop_hooks.py`   │ Stop hook helpers: `get_response_text()` , `should_evaluate()` , `is_retry()`     │
├──────────────────────────────┼───────────────────────────────────────────────────────────────────────────────────┤
│ `common/lib_hook_log.sh`     │ Bash logging equivalent for .sh handlers                                          │
└──────────────────────────────┴───────────────────────────────────────────────────────────────────────────────────┘

## Logging

Every handler logs to `{session_dir}/hook_events.jsonl`:

```json
{"ts":"2026-05-08T06:20:33","tracking_id":"...","hook_type":"Stop","handler":"block_permission_seeking","action":"block","reason":"permission-seeking phrase detected","exit_code":2,"duration_ms":1}
```

Fallback: `/tmp/hook_events_{tracking_id}.jsonl` if session_dir unavailable.

## Exit Codes

┌──────────┬─────────────┬─────────────────────────────────────────────────────────────────────────────────────┐
│ **Code** │ **Meaning** │ **Behavior**                                                                        │
├──────────┼─────────────┼─────────────────────────────────────────────────────────────────────────────────────┤
│ 0        │ Allow       │ Response/tool proceeds normally. Optional JSON on stdout for context injection.     │
├──────────┼─────────────┼─────────────────────────────────────────────────────────────────────────────────────┤
│ 1        │ Error       │ Non-blocking error. Logged, handler skipped, processing continues.                  │
├──────────┼─────────────┼─────────────────────────────────────────────────────────────────────────────────────┤
│ 2        │ Block       │ Blocks the action. Stderr message shown to AI. For Stop hooks, forces a retry turn. │
└──────────┴─────────────┴─────────────────────────────────────────────────────────────────────────────────────┘

## Adding a New Handler

1. Create script in the appropriate `{Type}/` directory
2. Name it `NN_descriptive_name_sync.py` or `NN_descriptive_name_async.sh`
3. Use `lib_hook_base.run_hook()` for Python handlers (gives you logging for free)
4. Source `common/lib_hook_log.sh` for bash handlers
5. Make it executable (`chmod +x`)
6. The dispatcher picks it up automatically — no config changes needed

## Config File Locations

┌──────────────┬───────────────────────────┬────────────────────────┐
│ **Platform** │ **Config file**           │ **Backup recommended** │
├──────────────┼───────────────────────────┼────────────────────────┤
│ Claude Code  │ `~/.claude/settings.json` │ Yes                    │
├──────────────┼───────────────────────────┼────────────────────────┤
│ Codex        │ `~/.codex/hooks.json`     │ Yes                    │
├──────────────┼───────────────────────────┼────────────────────────┤
│ Gemini       │ `~/.gemini/settings.json` │ Yes                    │
└──────────────┴───────────────────────────┴────────────────────────┘
