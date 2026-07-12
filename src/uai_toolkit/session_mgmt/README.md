# Session Management Scripts

Scripts for managing AI agent sessions — identity, state, discovery, and operations.

## Architecture

Three concerns, three stores:

| Concern | Script | Storage | Purpose |
|---------|--------|---------|---------|
| **Identity** | `session_store.py` | SQLite (`sessions.db`) | Session registration, metadata, resolve any identifier |
| **State** | `session_mgr.py` | JSON (`state.{uuid8}.json`) | Per-session mutable key-value state (context, env, roles) |
| **Discovery** | `session_registry.py` | Read-only (processes + JSONL) | Find what's running or historical across platforms |

- **session_store** = "who are you" — persistent identity, lifecycle, timestamps
- **session_mgr** = "what's your state" — mutable per-session variables, subprocess-friendly CLI
- **session_registry** = "what exists" — live discovery, does not write to any store

## Scripts with REPLs

| Script | Purpose | Symlink |
|--------|---------|---------|
| `session_store.py` | SQLite session store — registration, lookup, resolve, edit | `~/bin/ai/mgrs/sessions` |
| `session_traits.py` | Track loaded traits, roles, memory slots per session | `~/bin/ai/mgrs/traits` |
| `session_ops.py` | Session operations: read terminal, get status, write-to, attach | — |
| `todo_mgr.py`* | Todo CRUD, kanban, status workflow | `~/bin/ai/mgrs/todo` |

*todo_mgr lives in `~/bin/all_languages/python/src/todo_mgr/`, entry point at `~/bin/bin/todo_mgr`

## CLI-only Scripts (no REPL)

| Script | Purpose |
|--------|---------|
| `session_mgr.py` | Session state key-value store (state_get, state_set, state_list, etc.) |
| `session_registry.py` | Discover running and historical sessions across platforms |

## Libraries (imported, not run directly)

| File | Purpose |
|------|---------|
| `lib_session.py` | Session identity helpers (resolve identifiers, format tracking IDs) |
| `lib_session_identity.py` | Identity v5 — tracking ID generation, platform detection |
| `lib_session_substrate.py` | Terminal substrate abstraction (tmux/zellij send_keys, read_screen) |
| `store.py` | Legacy store module (pre-SQLite) |

## Utility Scripts

| Script | Purpose |
|--------|---------|
| `build_footer.py` | Assemble response footer for AI output |
| `rename_session.py` | Rename a session's display name |
| `hook_prompt_submit.py` | Claude Code hook: runs on each user prompt submit |
| `discover_sessions.py` | Batch session discovery and registration |
| `capture_session_uuid.sh` | Capture UUID from terminal screen |
| `ensure_session_watcher.sh` | Cron health check for fswatch-based UUID discovery |
| `fix_session_uuids.py` | Manual UUID verification via scrollback content matching |
| `handle_new_session_file.py` | fswatch handler for Codex/Gemini UUID discovery |
| `resolve_missing_uuids.py` | Stateless gap-filler for sessions missing UUIDs |
| `get_comms_id.py` | Get the comms identifier for the current session |
| `triggers.py` | Scheduled task trigger management |

## URI Mappings

`session_store.py` includes a `uri_mappings` table for resolving project/role URIs to session tracking IDs:

- `set_uri_mapping(uri, target_type, target_value, source_type, source_id)`
- `delete_uri_mappings(source_type, source_id)`
- `resolve_uri(uri)` → list of tracking IDs

Managed by:
- `../projects/projects_mgr.py` — syncs project and role URI mappings on role/session changes

## Overlap Clarification

**session_store.py vs session_registry.py:**
- `session_store.py` is the persistent SQLite store — create, update, resolve sessions by any identifier.
- `session_registry.py` is live discovery — scans processes and transcript files to find what's running now. Does not write to the store.

**session_mgr.py vs session_store.py:**
- `session_mgr.py` is the CLI interface for per-session key-value state (loaded docs, context usage, env vars). Subprocess-friendly.
- `session_store.py` is the session lifecycle store (identity, metadata, timestamps). Used as a library.

**session_ops.py vs session_registry.py:**
- `session_ops.py` acts on sessions (read their terminal, write to them, check status).
- `session_registry.py` finds sessions (what's running, what's historical).
