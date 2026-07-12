# UserPromptSubmit Handlers

Fired when the user submits a prompt, before the AI processes it.

| Handler | Type | Purpose |
|---|---|---|
| `00_dump_stdin_async.py` | async | **Temporary debug** — dumps raw hook stdin JSON to `data/hooks/data/stdin_dumps/` for inspecting platform differences. Remove after inspection. |
| `01_deliver_queued_prompts_sync.py` | sync | Delivers pre-prompt/post-prompt queue entries as additionalContext. Respects conversation locks. |
| `02_prepend_context_sync.py` | sync | Prepends `[datetime]` to the prompt as additionalContext. ctx% removed 2026-06-12 (context-anxiety mitigation, spec_response_footer v1.5); injects a no-number reassurance when ctx >= 85%. |
| `03_notify_unread_messages_sync.py` | sync | Checks for unread inbox/broadcast messages via messaging.py. If any, injects a notification as additionalContext. |
| `04_check_image_dimensions_sync.py` | sync | Parses image file paths from the prompt text. **Blocks** (exit 2) if any referenced image exceeds 2000px in either dimension. Provides resize instructions. |
| `05_log_user_prompts_async.py` | async | Logs every user prompt to `ai_general/data/audit/user_prompts.jsonl` with tracking_id, session name, platform, prompt preview, and timestamp. Looks up session display name from session_store if not in env. |
