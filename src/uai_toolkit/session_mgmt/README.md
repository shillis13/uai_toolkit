# Session Management Scripts

Scripts for managing AI agent sessions. The word "session" spans **three different
concerns** here — keep them straight and most of the confusion disappears:

| Concern | "What it answers" | Script | Backing store |
|---|---|---|---|
| **Identity / registry** | *Who are you?* — the durable record of every session | `session_store.py` | SQLite `../../data/sessions.db` |
| **Runtime state** | *What are your current variables?* — mutable per-session key/values | `store.py` (+ `session_mgr.py` CLI) | JSON `{session_dir}/state.{uuid8}.json` |
| **Live operations** | *Act on the running terminal* — read/write/status/kill | `session_ops.py` | live tmux/zellij (via `lib_session_substrate.py`) |

> ⚠️ **Naming hazard:** `session_store.py` and `store.py` **both define a class named
> `SessionStore`**, but they are unrelated — one is the SQLite identity DB, the other is
> the per-session key/value ("KV") state blob. This is the single most confusing thing in
> this directory. A rename is planned (see *Planned consolidation* below).

## Core scripts

| Script | What it is | Source of truth |
|---|---|---|
| `session_store.py` | **The authority.** SQLite registry of session identity/metadata (tracking_id, cli_uuid, platform, display_name, parent lineage, status, tags, URI mappings). Library `SessionStore` + full REPL/CLI. Per `DESIGN.md`, all session identity reads/writes go through here. | `data/sessions.db` |
| `store.py` | Per-session **runtime KV state** — a namespaced key/value bag (`role`, `features`, `context.*`, `env.*`, …) with file-locking + change triggers. Library only (no CLI). **Current, not legacy.** Class is also named `SessionStore` (see hazard above). | `state.{uuid8}.json` |
| `session_mgr.py` | Subprocess-friendly **CLI over `store.py`** — `state_get/set/list/increment/persist/load/…`, plus `get_footer` / `get_ctx_used` / `get_ai_root`. Resolves a tracking_id → session_dir via `session_store.py`, then reads/writes the JSON state file. | delegates |
| `session_ops.py` | **Live terminal operations** — `list-sessions` (live tmux), `read-terminal`, `get-status`, `write-to`, `kill`, `rename`, `attach`, `discover-uuid`. Reads the multiplexer for live state and `session_store.py` for metadata. The only sanctioned way to send text to / read / status a session. | live substrate + `sessions.db` |

## Other session_* scripts (commonly mistaken for the above)

| Script | What it **actually** does | Notes |
|---|---|---|
| `session_context_registry.py` | Tracks which **context items** (roles/skills/traits/briefs/mslots) a session has *loaded* — **not** a registry of sessions. Uses `data/context.db` for the item catalog + `session_store` for identity. | Formerly reachable as `session_traits.py`; that name is **obsolete** and the symlink is gone. Callers (e.g. `context_files/guidance_cli.py`) now invoke it by its real name. |
| `session_starts.py` | Derives a session's **start/resume/compact lifecycle timestamps** from transcript JSONL markers; writes `session.start_history` into the state file. | `derive <transcript>` / `backfill [--all]`. |
| `session_registry.py` | **Legacy** live discovery — scans `ps`/zellij + `~/.claude` & `~/.codex` transcripts and prints a list. Superseded by `session_store.py` for listing. | Kept only because `jsonl/memory_manager.py` imports its `find_jsonl_for_session` helper. Do not build new work on it. |

## Libraries (imported, not run directly)

| File | Purpose |
|---|---|
| `lib_session_substrate.py` | The tmux/zellij abstraction (`SessionSubstrate` ABC + `TmuxSubstrate`/`ZellijSubstrate`; `get_substrate()`, `build_tmux_command()`). The live-multiplexer layer everything terminal-related sits on. |
| `lib_session_activity.py` | Single change-guarded writer of `session.activity_state` into the state file (used by `session_ops` + hooks). |
| `lib_session.py` | **Legacy** flat-JSON registry helpers (`SessionInfo`, `resolve_identifier`, `instance_filename`). Predecessor to `session_store.py`, which now owns identity; `session_store` still borrows `instance_filename` from it. Being phased out. |
| `lib_identity_display.py` | Formats `"DisplayName (tracking_id)"` for notifications; delegates the name lookup to `session_store`. |
| `lib_uri.py` | `prompt://` / session-URI parsing helpers. |

## Utility scripts

| Script | Purpose |
|---|---|
| `build_footer.py` | Assemble the response footer for AI output. |
| `rename_session.py` | Rename a session's display name. |
| `register_self_brief.py` | Record a self-authored compaction brief in session state so PostCompact reloads it. |
| `hook_prompt_submit.py` | Claude Code hook: runs on each user prompt submit. |
| `handle_new_session_file.py` | fswatch handler for Codex/Gemini UUID discovery. |
| `resolve_missing_uuids.py` | Stateless gap-filler for sessions missing UUIDs. |
| `fix_session_uuids.py` | Manual UUID verification via scrollback content matching. |
| `get_comms_id.py` | Get the comms identifier for the current session. |
| `send_slash_command.py` | Send a slash command to a session's terminal through the live substrate. Slash commands are currently unguarded here; callers own policy. |
| `reconnect_mcp_servers.py` / `broadcast_mcp_reconnect.py` | Trigger MCP reconnects. |
| `declare_stop.py` | Mark a session idle/stopped. |
| `tag_mgr.py` | Session tag CRUD. |
| `triggers.py` | Scheduled-task trigger management. |

## DESIGN.md constraints (summary)

- `session_store.py` is the authoritative session-data store; all identity reads/writes go through it. Direct JSON-registry reads are legacy.
- `session_ops.py` is the **only** way to send text to sessions, read terminal content, or query status. No raw tmux/zellij outside `lib_session_substrate.py`.
- No time-based matching for identity; tracking IDs are opaque; `ai_launcher.py` creates identity, `session_store.py` persists it.

## Planned consolidation (not yet done)

The naming is being reworked so "session" stops meaning four different things:
- Rename `session_store.py` → **`session_registry.py`** (it is the identity *registry*). This frees the name currently held by the legacy discovery scanner, whose one live helper (`find_jsonl_for_session`) moves elsewhere first.
- Rename `store.py`'s class off the colliding `SessionStore` to a clear session-**state** name.
- Remove the remaining pre-SQLite artifacts once their last helper imports are relocated.

Until then, treat `session_store.py` as the registry and `store.py`/`session_mgr.py` as session-state.
