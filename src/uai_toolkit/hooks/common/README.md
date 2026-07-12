# Common Libraries

Shared code used by hook handlers across all event types.

| File | Purpose |
|---|---|
| `lib_hook_base.py` | **Base handler framework.** Provides `run_hook()` entry point, `HookResult` (allow/skip/block/error/output), `HookContext`, and standardized JSONL logging to `{session_dir}/hook_events.jsonl`. Every Python handler uses this. |
| `lib_hook_scripts.py` | **Prompt queue utilities.** Load, filter, compose, and deliver queued prompts. Provides `is_locked()` for conversation lock checking. Used by delivery handlers (01 in UserPromptSubmit and Stop). |
| `lib_stop_hooks.py` | **Stop hook helpers.** `get_response_text()` reads `last_assistant_message` from stdin (with JSONL transcript fallback), `get_last_user_message()` reads last user message from JSONL, `should_evaluate()` pre-filters short responses and retries, `is_retry()` checks `stop_hook_active`. |
| `lib_hook_log.sh` | **Bash logging.** Equivalent of lib_hook_base for .sh handlers. Source it at the top of a bash handler, then call `hook_log "action" "reason"` to write to hook_events.jsonl. |
| `dump_stdin.py` | **Temporary debug tool.** Writes raw hook stdin to `data/hooks/data/stdin_dumps/` for inspecting what each platform sends. Symlinked into handler directories as `00_dump_stdin_async.py` during inspection. Remove after use. |
