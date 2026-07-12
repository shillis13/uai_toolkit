# PreToolUse Handlers

Fired before a tool call executes. Can **block** the tool call (exit 2) or allow it (exit 0).

| Handler | Type | Purpose |
|---|---|---|
| `00_dump_stdin_async.py` | async | **Temporary debug** — dumps raw hook stdin JSON for platform inspection. Remove after use. |
| `01_devtree_boundary_check_sync.sh` | sync | When `AI_PROJECT_DIR` is a devTree, **blocks** edits to files outside that devTree. Handles both Claude's Edit/Write (file_path) and Codex's apply_patch (unified diff). Allows: devTree files, ~/bin/, working memory, ~/.claude/, /tmp/. |
| `02_devtree_bash_warning_sync.sh` | sync | When in a devTree, **warns** (does not block) if a bash command references the main ai_root path directly. Suggests using $AI_ROOT instead. |
| `03_block_lib_execution_sync.py` | sync | **Blocks** direct execution of `lib_*.py` files via `python3 .../lib_something.py`. These are internal libraries — AI sessions should use MCP tools or CLI wrapper scripts instead. |
| `04_check_file_conflict_sync.py` | sync | **Anti-clobbering.** Checks if another session modified a file since this session last read it. If so, **blocks** the write and tells the AI to re-read first. Uses file_access_tracker.py for cross-session read/write tracking. |
| `05_require_design_md_read_sync.py` | sync | **Governed-doc enforcement.** If a DESIGN.md (or other governed doc) exists in the target file's directory or any parent up to AI_ROOT, **blocks** the edit unless the session has read it. Records reads in session state for the app's Right Panel → Context display. Extensible via `GOVERNED_DOCS` dict. |
| `06_check_image_size_sync.py` | sync | **Image size guard.** Blocks Read of images above a size threshold to prevent context blowout. |
| `07_block_direct_multiplexer_sync.py` | sync | **Multiplexer safety.** Blocks direct tmux/zellij commands that could affect other sessions. |
| `08_guard_git_commands_sync.py` | sync | **Git safety.** Blocks dangerous git operations (force push, reset --hard, etc.) unless explicitly authorized. |
| `09_guard_self_compact_sync.py` | sync | **Self-compact guard.** Prevents premature or unauthorized self-compaction. |

Direct Reads of context dirs (session_briefs, ai_traits, ai_context_files, ai_profiles, working_memory slots) are **allowed** — the load is tracked by `PostToolUse/02_record_knowledge_loads_async.py` (see its docstring), not blocked. `knowledge_get_context` remains the front door for *reference-based* loads (resolve-by-concept + format assembly).
