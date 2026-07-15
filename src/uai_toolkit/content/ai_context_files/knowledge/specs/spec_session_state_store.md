# Session State Store Specification

**Version:** 1.0.0
**Created:** 2026-04-30
**Status:** active
**Maintainer:** PianoMan
**Design Source:** todo_0282 design doc rev 5

## Summary

Per-session mutable key-value store for AI CLI sessions. Disk-backed with file locking. Provides a single source of truth for runtime session data — roles, features, environment, context usage, loaded documents, conversation metadata — accessible from MCP tools, CLI scripts, and Python imports.

## Terminology

| Term | Meaning | NOT to be confused with |
|---|---|---|
| **session data dir** | Per-session directory for runtime artifacts. Path: `ai_general/data/sessions/{platform}/{YYYY}/{MM}/{tracking_id}/` | `project_dir`, `working_dir` |
| **tracking_id** | Primary session identifier. Format: `{YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}` | `cli_session_id`, `terminal_session` |
| **session state** | The key-value store managed by `SessionStore` | Session registry (SQLite `session_store.py`) |

## Design Philosophy

- **Disk is truth.** Every operation reads from and writes to a JSON file. No in-memory cache is trusted across calls.
- **File locking for concurrency.** Shared locks on reads (multiple concurrent readers OK). Exclusive locks on mutations (prevents lost updates between MCP server and hook processes).
- **Atomic write for crash safety.** tmp file + rename guards against mid-write process death. Secondary to locking.
- **Auto-persist.** All mutating operations write to disk immediately. No separate `persist()` call needed for normal use.

## Storage

**File:** `{session_data_dir}/state.{uuid8}.json` (discriminated filename via `lib_session.instance_filename()`)

```json
{
  "tracking_id": "20260425_005120_e0954f5d_cla",
  "persisted_at": "2026-04-26T01:30:00-04:00",
  "state": {
    "role": ["chat", "assistant", "architect"],
    "features": [],
    "ai_root": "$AI_ROOT",
    "ai_root_main": "$AI_ROOT",
    "env.AI_TRACKING_ID": "20260425_005120_e0954f5d_cla",
    "env.AI_CLI_SESSION_ID": "e0954f5d-fae8-49ff-8e91-c77db0d73227",
    "env.AI_SESSION_DIR": "...",
    "env.AI_SESSION_PLATFORM": "claude_cli",
    "env.AI_PROJECT_DIR": "$AI_ROOT",
    "session.display_name": "Nightwatch",
    "loaded.docs": "20:5,40:2",
    "loaded.mslots": "3-6",
    "conversation.artifacts": 0,
    "context.used_pct": 18,
    "context.tokens": 180432,
    "context.cost_usd": 22.90,
    "context.updated_at": "2026-04-26T01:30:00-04:00"
  }
}
```

## Key Namespace Conventions

Keys are flat strings. Namespaces are dot-delimited by convention (not enforced). The namespace is part of the key string — no separate namespace parameter.

| Prefix | Purpose | Examples |
|---|---|---|
| `env.*` | Seeded from OS environment at launch | `env.AI_TRACKING_ID`, `env.AI_SESSION_PLATFORM` |
| `context.*` | Context window usage, cached by hook | `context.used_pct`, `context.tokens`, `context.cost_usd` |
| `session.*` | Identity and behavioral metadata | `session.display_name` |
| `loaded.*` | Documents, memory slots, data the session has read | `loaded.docs`, `loaded.mslots` |
| `conversation.*` | Properties of the chat itself | `conversation.artifacts` |
| (none) | Free-form; includes legacy keys | `role`, `features`, `ai_root`, `ai_root_main` |

**Reserved list-typed keys:** `role`, `features` — these support merge and remove semantics. `set` on a list key merges values; `remove` subtracts values.

## Reserved Key Registry

Well-known keys are defined in `schema_session_state_keys.latest.yml` (in `ai_traits/knowledge/50_schemas/`). This is the canonical source of truth for key names, types, writers, and descriptions.

**Validation behavior:** When `sessions_state_set` is called with a namespaced key (contains a dot):
- Exact match in registry → allowed
- Not in registry but namespace prefix matches a reserved namespace (`env.*`, `context.*`, `session.*`, `loaded.*`, `conversation.*`, `footer.*`) → rejected with error listing valid keys in that namespace
- No namespace prefix and not reserved → allowed as free-form key

This prevents LLM inconsistency (e.g., writing `context.usage_pct` instead of `context.used_pct`) while leaving free-form keys unrestricted.

**Adding reserved keys:** Requires editing the schema file — a deliberate design decision involving human review, not an ad-hoc AI action. See `schema_session_state_keys` change management section.

**Discovering reserved keys:** AI sessions call `sessions_state_keys` MCP tool to retrieve the list, filtered by namespace.

## Library Interface

**File:** `ai_general/scripts/session_mgmt/store.py`

```python
class SessionStore:
    def __init__(self, tracking_id=None, session_data_dir=None, session_id=None)
    # session_id is deprecated alias for tracking_id (compat with triggers.py)

    def get(self, key: str) -> Any                            # shared lock, read from disk
    def set(self, key: str, value: Any) -> dict               # exclusive lock; {key, value, changed}
    def delete(self, key: str) -> dict                        # exclusive lock; {key, deleted}
    def increment(self, key: str, amount: int|float = 1) -> dict  # exclusive lock; {key, value, changed}
    def decrement(self, key: str, amount: int|float = 1) -> dict  # alias for increment(key, -amount)
    def list_all(self, prefix: str = None) -> dict            # shared lock; filtered dict
    def remove(self, key: str, value: str) -> dict            # exclusive lock; list keys only
    def seed_from_env(self, var_names: list[str]) -> dict     # single exclusive lock; {seeded, missing}
    def persist(self) -> str                                  # initial file creation only
    def register_trigger(self, key: str, callback: Callable)  # fires on value change
```

**Increment/decrement:** Works on integers and floats. Key initialized to 0 if absent. ValueError if existing value is not numeric. `decrement()` exists for LLM clarity — calling `increment(key, -1)` is equivalent but less obvious.

## CLI Interface

**File:** `ai_general/scripts/session_mgmt/session_mgr.py`

```bash
session_mgr.py state_get <tracking_id> <key> [--data-dir /path]
session_mgr.py state_set <tracking_id> <key> <value> [--data-dir /path]
session_mgr.py state_delete <tracking_id> <key> [--data-dir /path]
session_mgr.py state_increment <tracking_id> <key> [--amount N] [--data-dir /path]
session_mgr.py state_decrement <tracking_id> <key> [--amount N] [--data-dir /path]
session_mgr.py state_list <tracking_id> [--prefix env.] [--data-dir /path]
session_mgr.py state_remove <tracking_id> <key> <values> [--data-dir /path]
session_mgr.py state_seed <tracking_id> --vars AI_TRACKING_ID,... [--data-dir /path]
```

**Resolution:** `--data-dir` bypasses SQLite lookup (for hooks/pre-registration contexts). Otherwise tracking_id is resolved via `session_store.py`.

**Output:** JSON to stdout. Errors to stderr with non-zero exit.

## MCP Tools

| Tool | Description | Returns |
|---|---|---|
| `sessions_state_get` | Get a session state value by key | The value, or None |
| `sessions_state_set` | Set a key-value pair (list keys merge) | `{key, value, changed}` |
| `sessions_state_delete` | Delete a key | `{key, deleted}` |
| `sessions_state_increment` | Add to a numeric key | `{key, value, changed}` |
| `sessions_state_decrement` | Subtract from a numeric key | `{key, value, changed}` |
| `sessions_state_list` | List all pairs (optional prefix filter) | `{key: value, ...}` |
| `sessions_state_remove` | Remove values from list keys | `{key, value}` |
| `sessions_state_keys` | List reserved key names (optional namespace filter) | `[{key, type, writer, description, dedicated_tool}]` |
| `sessions_get_ctx_used` | Current context usage | `{used_pct, tokens, cost_usd, updated_at}` |
| `sessions_get_ai_root` | Resolve AI_ROOT path | Path string |

**Transition:** Old names (`sessions_set`, `sessions_get`, etc.) kept as deprecated aliases with warning. Removed after one release cycle.

## Lifecycle

**Launch:** ai_launch.py creates `SessionStore`, calls `seed_from_env()`, sets display_name, calls `persist()` to create initial file.

**During session:** MCP tools and hooks read/write via `SessionStore`. Disk is truth. No stale in-memory state.

**Resume (attach):** MCP server already running, disk is truth, no action needed.

**Resume (relaunch):** New MCP server reads existing state file from disk. Immediate availability.

## Rebuildability

State file can be reconstructed from external sources:
- `env.*`: from OS environment (available at launch)
- `session.*`: from sessionInfo in same directory
- `role`, `features`: from session bootstrap
- `loaded.*`: AI re-sets on bootstrap
- `conversation.artifacts`: ephemeral, resets to 0 on rebuild
- `context.*`: re-populated on next hook fire

## Dependencies

- `session_store.py` (SQLite) — tracking_id -> session_data_dir resolution
- `lib_session.py` — `instance_filename()`, `find_instance_file()`
- `lib_paths.py` — AI_ROOT resolution

## Related

- `spec_session_identity` v5.3 — session identity model
- `protocol_response_footer` v2.0 — consumes session state for footer assembly
- `schema_hook_definition` — hooks that write to session state
- `schema_session_state_keys` — canonical registry of reserved key names
