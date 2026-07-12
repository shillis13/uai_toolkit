# PostToolUse Handlers

Fired after a tool call completes. All handlers here are async (fire-and-forget).

| Handler | Type | Purpose |
|---|---|---|
| `00_dump_stdin_async.py` | async | **Temporary debug** — dumps raw hook stdin JSON for platform inspection. Remove after use. |
| `01_audit_tools_async.py` | async | Audits every tool call to JSONL. Cross-platform — handles Claude Code, Codex (via AUDIT_PLATFORM env), and Gemini. Records tool name, input preview, result preview, and success/failure detection. |
| `02_record_knowledge_loads_async.py` | async | Tracks knowledge/guidance loads to session state. When `knowledge_get_role`, `get_trait`, `get_skill`, `get_profile`, or `get_knowledge` is called, records it in `loaded.manifest` and the type-specific `loaded.*` keys. Deduplicates. |
| `03_track_file_read_async.py` | async | Records file reads to the file access tracker. Part of the anti-clobbering system — provides the "last read" timestamps that `04_check_file_conflict_sync.py` (PreToolUse) checks against. |
| `04_track_file_write_async.py` | async | Records file writes to the file access tracker. Part of the anti-clobbering system — provides the "last modified by session X" data for conflict detection. |
