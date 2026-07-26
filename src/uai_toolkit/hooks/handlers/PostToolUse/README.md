# PostToolUse Handlers

Fired after a tool call completes. Most handlers here are async (fire-and-forget); the
exception is `05_guard_write_stub_sync.py`, which is **sync and can block (exit 2)**.

| Handler | Type | Purpose |
|---|---|---|
| `00_dump_stdin_async.py` | async | **Temporary debug** — dumps raw hook stdin JSON for platform inspection. Remove after use. |
| `01_audit_tools_async.py` | async | Audits every tool call to JSONL. Cross-platform — handles Claude Code, Codex (via AUDIT_PLATFORM env), and Gemini. Records tool name, input preview, result preview, and success/failure detection. |
| `02_record_knowledge_loads_async.py` | async | Tracks knowledge/guidance loads to session state. When `knowledge_get_role`, `get_trait`, `get_skill`, `get_profile`, or `get_knowledge` is called, records it in `loaded.manifest` and the type-specific `loaded.*` keys. Deduplicates. |
| `03_track_file_read_async.py` | async | Records file reads to the file access tracker. Part of the anti-clobbering system — provides the "last read" timestamps that `04_check_file_conflict_sync.py` (PreToolUse) checks against. |
| `04_track_file_write_async.py` | async | Records file writes to the file access tracker. Part of the anti-clobbering system — provides the "last modified by session X" data for conflict detection. |
| `05_guard_write_stub_sync.py` | **sync (blocks)** | Catches the offload-stub write bug: a large `content`/`new_string` that lands on disk as the archive placeholder instead of the real text (tool_result still says success; a Read returns the same stub — only raw bytes are ground truth). Reads the file back after Write/Edit/MultiEdit and, on a stub, exits 2 telling the agent to re-write via heredoc while the content is still in context. Two rules: line-1 stub (any file — whole-file Write loss) and full-shape stub anywhere in a **source** file (mid-file Edit loss). Tests: `tests/test_guard_write_stub_sync.py`. |
