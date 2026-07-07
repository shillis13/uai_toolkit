# Session Identity Specification v5.4

**Status:** Draft — supersedes v5.3
**Created:** 2026-04-22
**Author:** Continuity (Claude CLI, Architect) with PianoMan
**Scope:** CLI session identity for Claude CLI, Codex CLI, Gemini CLI, terminal substrates, statusline writers, session registry consumers, UCI, and UAI.
**Changes from v5.3:** Draft session lifecycle, expanded registry contract, instance-scoped sessionInfo filenames, UAI app as registry writer, launch request schema.

---

## 1. Purpose

Provide one stable identity model for AI CLI sessions that supports:

- deterministic launch-time identity before platform bootstraps finish
- exact lookup by tracking ID, CLI UUID, or terminal session name
- lightweight registry lookup for UI/client consumers
- richer per-session filesystem state without bloating the identity core
- statusline/event writes from inside the running CLI process
- **draft sessions created by the app before launch** (new in v5.4)
- **app-written metadata fields alongside wrapper-written identity** (new in v5.4)
- legacy v5.1/v5.2/v5.3 session compatibility without renaming old IDs

---

## 2. Identity Model

Three identity classes:

| Identity | Meaning | Stability | Source |
|---|---|---|---|
| `tracking_id` | system-owned stable handle for this launch/session record | immutable | launcher/wrapper, or app (draft) |
| `cli_session_id` | platform-native conversation/session UUID | mutable until known, then stable | platform or wrapper |
| `terminal_session` | tmux/zellij/session substrate name | normally stable, substrate-owned | launcher/substrate |

Rules:

1. `tracking_id` is the primary key and never changes after creation.
2. `cli_session_id` is authoritative for platform-native resume/history correlation.
3. `terminal_session` stays the terminal substrate name; do not rename this field.
4. Lookups use exact matching only. No fuzzy identity resolution.
5. Existing legacy tracking IDs remain valid and are not renamed.
6. **The app may create draft tracking IDs before a launcher runs.** (New in v5.4.)

---

## 3. Tracking ID Format

### 3.1 New Format

```text
{YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}
```

Example:

```text
20260411_012005_fcf141f7_cla
```

Regex:

```regex
^(?<date>\d{8})_(?<time>\d{6})_(?<uuid8>[0-9a-f]{8})_(?<platform3>cla|cod|gem)$
```

Platform codes:

| platform | code |
|---|---|
| `claude_cli` | `cla` |
| `codex_cli` | `cod` |
| `gemini_cli` | `gem` |

### 3.2 Semantics

- **Timestamp is local launch time.** The `{YYYYMMDD}_{HHMMSS}` embedded in the tracking ID is the launcher's local time (`datetime.now()`), matching the workspace convention that timestamps are local. (The separate `created_at` DB column remains ISO-8601 UTC for storage; see §5.) Display layers show local time directly. Identity creation is centralized in the launcher precisely so this is consistent — the app no longer mints IDs in TypeScript (it formerly did so in UTC, causing drift).
- `uuid8` is a correlation convenience and collision reducer. It is **not** authoritative identity — nothing parses it back out to recover a UUID or platform (tracking IDs are opaque; see session_mgmt/DESIGN.md). `cli_session_id` is authoritative.
- **Claude:** `uuid8 == cli_session_id[:8]` holds *by construction* for sessions created through the reserve→launch path. At reserve the launcher mints one UUID, derives `uuid8` from it, and stores it as the draft's `cli_session_id`; at launch that UUID is passed as `claude --session-id`, so Claude adopts it. The correspondence is a guarantee at creation, never a contract consumers may rely on by parsing.
- **Codex / Gemini:** the platform-native UUID is discovered only *after* launch, so `cli_session_id` is null at reserve and `uuid8` is a pure launch-time label. `uuid8 != cli_session_id[:8]` is normal and expected here — do not treat divergence as an error.
- `cli_session_id` in the registry/sessionInfo is the authoritative platform UUID.
- If a platform later reveals a different actual CLI UUID than the UUID used to form `tracking_id`, update `cli_session_id` only. Do not rename the tracking ID or session directory.
- IDs are immutable. Resolver code must support both new and legacy IDs.

### 3.3 Legacy Formats Accepted

Legacy IDs remain valid:

```text
{platform}_{YYYYMMDD}_{HHMMSS}
{platform}_{YYYYMMDD}_{HHMMSS}_{NN}
{uuid8}_{platform3}_{YYYYMMDD}_{HHMMSS}   # v5.2 draft only, if any exist
```

Legacy sessions are stored/read through compatibility paths. They are not retroactively renamed.

---

## 4. Session Directory Layout

New sessions use month-level grouping:

```text
ai_general/data/sessions/
  {platform}/
    {YYYY}/
      {MM}/
        {tracking_id}/
          sessionInfo.{uuid8}.json
          statusline.{uuid8}.jsonl
```

Example:

```text
ai_general/data/sessions/claude_cli/2026/04/20260411_012005_fcf141f7_cla/
  sessionInfo.fcf141f7.json
  statusline.fcf141f7.jsonl
```

### 4.1 Instance-Scoped Filenames (changed from v5.3)

Per-session files use discriminated names: `{base}.{uuid8}.{ext}` where `uuid8` is extracted from the tracking ID. This prevents filename collisions when session directories are listed, searched, or indexed by tools that scan across directories.

**Resolution order** (implemented by `find_instance_file()`):
1. Try discriminated name: `sessionInfo.{uuid8}.json`
2. Fall back to legacy name: `sessionInfo.json`

Writers MUST use the discriminated name for new sessions. Readers MUST try both for backward compatibility.

**Dual-file warning:** If both `sessionInfo.{uuid8}.json` and `sessionInfo.json` exist in the same directory, the discriminated name wins. A repair warning is logged. v5.3 writers are supported for legacy sessions only. For v5.4 session directories, writers must resolve via `find_instance_file()` and write the discovered canonical file.

### 4.2 Legacy Directory Layout

Legacy sessions without parseable new IDs use:

```text
ai_general/data/sessions/{platform}/legacy/{tracking_id}/
```

---

## 5. Registry Schema

### 5.1 Identity Core (v5.3 contract, preserved)

The registry's primary purpose is a slim identity/pointer index. These fields form the immutable identity core:

```sql
-- Identity core (v5.3 contract)
tracking_id       TEXT PRIMARY KEY,
cli_session_id    TEXT,
platform          TEXT NOT NULL,
terminal_session  TEXT,
session_dir       TEXT NOT NULL,
project_dir       TEXT NOT NULL,     -- immutable: launch-time project root
history_file      TEXT
```

These fields follow exactly the v5.3 contract. `project_dir` is immutable — it records where the session was launched. It does not change if the session's working context shifts.

### 5.2 Indexed Metadata (v5.4 extension)

UAI and UCI need queryable metadata beyond the identity core. These fields are **indexed into SQLite for query performance**. They are divided into two categories:

**SQLite-owned metadata** — SQLite is authoritative for these fields:

```sql
-- Lineage (immutable after creation)
parent_tracking_id  TEXT,

-- App-owned metadata
display_name        TEXT,
created_at          TEXT NOT NULL,       -- ISO 8601 UTC

-- Identity lifecycle (new in v5.4)
identity_status     TEXT DEFAULT 'confirmed',

-- App-managed flags
archived            BOOLEAN DEFAULT 0,

-- Schema
schema_version      INTEGER DEFAULT 2
```

**Denormalized runtime index** — sessionInfo is authoritative for these fields. SQLite copies are indexes for query performance, not sources of truth. Values may be repaired from sessionInfo during reconciliation:

```sql
-- Runtime metadata (sessionInfo-authoritative, mirrored here for queries)
working_dir         TEXT,
model               TEXT,
substrate           TEXT,
roles               TEXT DEFAULT '[]',  -- exception: app-owned, SQLite-authoritative (see Section 5.3)
transcript_path     TEXT,
cli_pid             INTEGER,
status              TEXT DEFAULT 'running',  -- wrapper-reported process lifecycle, NOT UAI RuntimeState
```

### 5.3 Field Ownership Map

Every field has exactly one authoritative owner:

| Field | Owner | Mutable | Source of Truth | Notes |
|---|---|---|---|---|
| `tracking_id` | Wrapper or App (draft) | No | SQLite | Primary key |
| `cli_session_id` | Wrapper | Until known | SQLite | Platform UUID |
| `platform` | Wrapper or App (draft) | No | SQLite | |
| `terminal_session` | Wrapper/Substrate | Rare | SQLite | May change on resume |
| `session_dir` | Wrapper or App (draft) | No | SQLite | Absolute path |
| `project_dir` | Wrapper or App (draft) | No | SQLite | Immutable launch project root |
| `history_file` | Wrapper | Yes | SQLite | Updated when discovered |
| `parent_tracking_id` | Wrapper or App (draft) | No | SQLite | Set at creation |
| `display_name` | App / AI | Yes | SQLite | App-writable, user/AI editable |
| `working_dir` | Wrapper | Yes | sessionInfo | Mutable current working dir |
| `model` | Wrapper | No | sessionInfo | Set at launch |
| `substrate` | Wrapper | No | sessionInfo | tmux, zellij, none |
| `roles` | App / session_store | Yes | SQLite | JSON array. App-owned metadata — assigned at launch or updated by user/AI. Wrapper reads roles at launch from launch_context but does not own them. Mirrored to sessionInfo for child process convenience. |
| `cli_pid` | Wrapper | Yes | sessionInfo | Current process PID |
| `status` | Wrapper | Yes | sessionInfo | Wrapper-reported process/lifecycle status (running, stopped, exited). This is NOT the UAI renderer-derived RuntimeState (idle, responding, blocked, etc.). UAI derives richer runtime states from terminal parsing and does not write them back to this field. |
| `identity_status` | App / Wrapper | Yes | SQLite | draft, pending, confirmed, failed, orphaned |
| `archived` | App | Yes | SQLite | App-managed lifecycle flag |
| `created_at` | Wrapper or App (draft) | No | SQLite | ISO 8601 UTC |

**Key distinction:**
- **SQLite** holds identity pointers, lineage, app-owned metadata (`display_name`, `roles`, `identity_status`, `archived`), and denormalized runtime indexes
- **sessionInfo.{uuid8}.json** holds mutable runtime state that wrappers own (`working_dir`, `model`, `substrate`, `cli_pid`, `status`). For denormalized fields mirrored in SQLite, sessionInfo is authoritative — SQLite values may be repaired from sessionInfo during reconciliation.
- **app_state.json** holds pure UI state (pinned, lastViewedAt, notes, promptbox config, tab state)

`display_name` is SQLite-authoritative (app-owned). `roles` is SQLite-authoritative (app-owned; wrapper reads at launch from launch_context, mirrors to sessionInfo for child process convenience). Runtime fields like `working_dir`, `model`, `cli_pid`, `status` are sessionInfo-authoritative; SQLite copies are denormalized indexes updated by `session_store.py` synchronization.

### 5.4 Indexes

```sql
CREATE INDEX idx_sessions_uuid
    ON sessions(cli_session_id)
    WHERE cli_session_id IS NOT NULL;

CREATE INDEX idx_sessions_terminal
    ON sessions(terminal_session);

CREATE INDEX idx_sessions_platform_status
    ON sessions(platform, status);

CREATE INDEX idx_sessions_parent
    ON sessions(parent_tracking_id)
    WHERE parent_tracking_id IS NOT NULL;

CREATE INDEX idx_sessions_identity_status
    ON sessions(identity_status)
    WHERE identity_status != 'confirmed';
```

---

## 6. Per-Session State: `sessionInfo.{uuid8}.json`

Mutable runtime metadata lives in the session directory.

### 6.1 Path

```text
{session_dir}/sessionInfo.{uuid8}.json
```

Where `uuid8` is extracted from the tracking ID. Readers use `find_instance_file()` which tries the discriminated name first, then falls back to legacy `sessionInfo.json`.

### 6.2 Schema

```json
{
  "schema_version": 4,
  "tracking_id": "20260411_012005_fcf141f7_cla",
  "cli_session_id": "fcf141f7-....",
  "platform": "claude_cli",
  "terminal_session": "20260411_012005_fcf141f7_cla",
  "session_dir": "/Users/.../ai_general/data/sessions/claude_cli/2026/04/20260411_012005_fcf141f7_cla",
  "project_dir": "$HOME/Documents/AI/ai_root",
  "working_dir": "$HOME/Documents/AI/ai_root",
  "history_file": "/Users/.../.claude/projects/.../uuid.jsonl",
  "display_name": "optional UI name",
  "parent_tracking_id": null,
  "model": "claude-opus-4-6",
  "roles": ["assistant"],
  "cli_pid": 12345,
  "substrate": "tmux",
  "status": "running",
  "created_at": "2026-04-11T01:20:05Z",
  "updated_at": "2026-04-11T01:20:05Z"
}
```

Schema version bumped from 3 to 4 for v5.4.

### 6.3 Rules

1. Write atomically: write `.tmp`, then rename.
2. `project_dir` is immutable after creation.
3. `working_dir` is mutable and belongs here, not in the registry identity core.
4. Runtime writers update `sessionInfo.{uuid8}.json` after registry mutations that affect mirrored fields.
5. Consumers needing live runtime state read this file after resolving `session_dir` from registry.

---

## 7. Draft Session Lifecycle (new in v5.4)

### 7.1 Identity Status

Sessions have an identity lifecycle tracked by `identity_status`:

```
draft → pending → confirmed
                → failed (launcher reported error)
draft → orphaned (no launcher claim before timeout)
pending → orphaned (no confirmation before timeout)
pending → failed (launcher reported error)
```

| Status | Meaning | Who Sets |
|---|---|---|
| `draft` | App or script created the ID. Identity/platform fields known, runtime fields null. Placeholder in UI. | App |
| `pending` | Launcher has been called with this ID. Awaiting identity completion. | App (when calling launcher) |
| `confirmed` | Wrapper finished. All identity fields populated. Fully operational. | Wrapper |
| `failed` | Launcher started and reported a failure, or wrote failure evidence to sessionInfo. Known failure. | Wrapper or App |
| `orphaned` | No launcher claim, heartbeat, terminal, or sessionInfo update before timeout. Abandoned/incomplete — cause unknown. | App (cleanup) |

### 7.2 Draft Creation

Any authorized writer can create a draft session. Canonical write order for crash recovery:

1. Writer generates tracking ID using the standard format (timestamp + uuid8 + platform).
2. Writer computes `session_dir`.
3. Writer creates `session_dir`.
4. Writer writes initial `sessionInfo.{uuid8}.json` with `identity_status: draft` and `launch_context`.
5. Writer inserts SQLite registry row with `identity_status = 'draft'` and pre-populated fields.
6. Writer emits SQLite change signal.
7. Session appears in app UI as a placeholder (draft indicator).

**Startup reconciliation:**
- sessionInfo exists but no SQLite row → create/repair SQLite row from sessionInfo, or mark as stray draft file.
- SQLite row exists but no sessionInfo → mark `identity_status = 'orphaned'` and notify.

### 7.3 Draft Pre-Population

When the app creates a draft for a session it's about to launch, it pre-populates all context-known fields:

| Field | How App Knows |
|---|---|
| `platform` | User selected in launch dialog |
| `project_dir` | Current project context or launch dialog |
| `display_name` | User entered or auto-generated |
| `roles` | Selected in launch dialog or inherited from template |
| `parent_tracking_id` | Current session if spawning |
| `tags` | Inherited from project/team/template |
| Relationships | member_of project, member_of team, forked_from, launched_from brief |

The launcher receives `--tracking-id` and reads pre-populated fields from the store instead of receiving them all as CLI arguments.

### 7.4 Launch Request Context

When a draft is created for launch, a `launch_context` object is written to sessionInfo alongside the identity fields:

```json
{
  "launch_context": {
    "requested_by": "app",
    "requested_at": "2026-04-22T14:30:00Z",
    "launch_params": {
      "platform": "claude_cli",
      "role": "architect",
      "project_dir": "/path/to/project",
      "model": "claude-opus-4-6",
      "prompt_file": "/path/to/initial_prompt.md",
      "system_prompt_additions": "/path/to/additions.md",
      "auto_approve": false,
      "brief_to_load": "pixel_iii"
    },
    "immutable_after": "pending"
  }
}
```

The launcher reads `launch_context.launch_params` to build native CLI arguments. After status transitions to `pending`, launch params are immutable — the launcher owns the session from that point.

### 7.5 Cleanup Rules

| Condition | Action |
|---|---|
| Draft older than 1 hour with no transition to pending | Mark `orphaned`, notify user |
| Pending older than 5 minutes with no confirmation and no launcher error | Mark `orphaned`, log warning, notify user |
| Pending with launcher-reported error | Mark `failed`, log error, notify user |
| Failed session | Visible in app with error indicator. User can retry or delete. |
| Orphaned session | Visible in app with warning. User can retry or delete. |

Cleanup runs on app startup and periodically (every 5 minutes).

---

## 8. Statusline Persistence

Statusline/event data is append-only JSONL:

```text
{session_dir}/statusline.{uuid8}.jsonl
```

Each line is one JSON object. Minimum useful fields:

```json
{"ts":"2026-04-11T01:20:10Z","cwd":"/path","model":"...","tokens":12345,"git_branch":"main"}
```

Rules:

- Statusline writers append one complete JSON object per line.
- Do not rewrite the full file for each status update.
- `sessionInfo.{uuid8}.json` can contain the latest known summary, but `statusline.{uuid8}.jsonl` is the durable event stream.
- Instance-scoped naming follows the same convention as sessionInfo.

---

## 9. Launcher Environment Contract

Wrappers must export these variables into the launched CLI process environment:

```bash
AI_TRACKING_ID=<tracking_id>
AI_CLI_SESSION_ID=<uuid-or-empty-if-pending>
AI_SESSION_DIR=<absolute session_dir>
AI_SESSION_PLATFORM=<platform>
AI_PROJECT_DIR=<immutable project_dir>
```

Purpose:

- lets statusline scripts find `statusline.{uuid8}.jsonl` without querying SQLite
- lets child tools locate `sessionInfo.{uuid8}.json`
- avoids bootstrap discovery gaps for processes that cannot read wrapper internals
- provides a stable integration point across Claude, Codex, Gemini, tmux, zellij, direct mode, UCI, and UAI

If `AI_CLI_SESSION_ID` is empty at launch and a UUID is discovered later, registry/sessionInfo are updated. Existing child process environment cannot be changed retroactively; statusline scripts should prefer sessionInfo for latest UUID if needed.

---

## 10. Creation Flow

### 10.1 Standard Flow (wrapper-initiated)

1. Wrapper computes or accepts `project_dir`.
2. Wrapper creates a UUID candidate when the platform does not provide one at launch.
3. Wrapper generates `tracking_id` using `{YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}`.
4. Wrapper computes `session_dir` under `{platform}/{YYYY}/{MM}/{tracking_id}`.
5. Wrapper creates `session_dir`.
6. Wrapper writes registry row with `identity_status = 'confirmed'`.
7. Wrapper writes `sessionInfo.{uuid8}.json`.
8. Wrapper exports `AI_*` variables into the launched CLI process.
9. Wrapper launches terminal substrate / CLI.
10. Wrapper updates `cli_pid`, `history_file`, or reconciled `cli_session_id` when discovered.

### 10.2 Draft Flow (app-initiated, new in v5.4)

1. App generates `tracking_id` using the standard format.
2. App computes `session_dir`.
3. App creates `session_dir`.
4. App writes initial `sessionInfo.{uuid8}.json` with `schema_version: 4`, `identity_status: draft`, and `launch_context`.
5. App inserts SQLite registry row with `identity_status = 'draft'` and pre-populated fields.
6. App emits SQLite change signal.
7. Session appears in UI as draft placeholder.
8. App calls launcher with `--tracking-id {tracking_id}`.
9. App updates `identity_status = 'pending'`.
10. Launcher reads `launch_context.launch_params` from sessionInfo (canonical source for launch params).
11. Launcher completes identity (cli_session_id, terminal_session, cli_pid).
12. Launcher updates registry and sessionInfo with `identity_status = 'confirmed'`.
13. App reflects confirmed state on next store change event.

**Retry semantics:** Retrying a `failed` or `orphaned` draft reuses the same tracking_id only if no `terminal_session` or `cli_session_id` was confirmed. Retry transitions `identity_status` back to `pending` and appends retry metadata to `launch_context`. If any CLI identity was already confirmed, create a new session instead.

Failure rule: if launch fails after registry creation, mark `identity_status = 'failed'` in both registry and sessionInfo. Do not delete evidence silently.

---

## 11. Lookup and Resolution

Resolution order:

1. exact `tracking_id`
2. exact `terminal_session`
3. exact `cli_session_id`

After resolution, clients read `sessionInfo.{uuid8}.json` (via `find_instance_file()`) for runtime state. Registry rows remain small enough that listing all sessions is cheap.

---

## 12. Signal Contract

### 12.1 SQLite Change Signal

All SQLite writers MUST use `session_store.py`. After every successful commit, `session_store.py` MUST write/touch the signal file:

```text
{data_dir}/sessions.changed
```

`{data_dir}` is the directory containing the session registry SQLite database, currently `ai_general/data/sessions/` or the configured session data root.

Signal file content:

```json
{
  "seq": 42,
  "changed": ["sessions"],
  "source": "session_store.py",
  "timestamp": "2026-04-22T14:30:00Z"
}
```

The app watches this signal file to detect external writes and refresh affected store slices.

### 12.2 sessionInfo Change Signal

Wrapper updates to sessionInfo are detected by the app via:
- Direct observation after app-initiated commands (app knows it triggered a launch)
- Periodic polling of `sessionInfo.{uuid8}.json` mtime for running sessions
- `identity_status` transitions in the registry (from draft → pending → confirmed)

**Denormalized index repair:** If sessionInfo mtime changes, the app reads it and updates denormalized SQLite metadata fields (whose source of truth is sessionInfo) via `session_store.py`, emitting `sessions.changed` if any indexed values changed. This prevents denormalized SQLite copies from going stale.

---

## 13. Migration from v5.3

1. **Registry schema:** Add `identity_status` column with default `'confirmed'`. Add `archived` column with default `0`. Existing sessions are confirmed and not archived.
2. **sessionInfo naming:** New sessions use `sessionInfo.{uuid8}.json`. `find_instance_file()` already handles both names. No migration needed for existing files.
3. **sessionInfo schema_version:** Bump to 4. Add `launch_context` field (null for existing sessions).
4. **Existing sessions:** All existing sessions get `identity_status = 'confirmed'`. No behavioral change.
5. **Draft capability:** New feature, no migration needed. Only new sessions created by the app use draft flow.
6. **Backward compatibility:** All v5.3 consumers continue to work. The identity core (Section 5.1) is unchanged. Extended metadata fields are additive.

---

## 14. Required Acceptance Criteria

Before v5.4 implementation is considered complete:

- A migration test must exist containing at least one v5.3 session, one v5.4 draft session, and one legacy v5.1 ID, verifying lookup, sessionInfo resolution, and identity lifecycle transitions.

## 15. Open Items

- Decide whether `cli_session_id` can become `NOT NULL` after all platforms reliably receive a wrapper UUID at launch.
- Validate that `--tracking-id` flag works for all three launcher paths (Claude, Codex, Gemini).
- Define how draft sessions interact with the session discovery pipeline (discover_sessions.py should recognize drafts without treating them as orphaned wrapperless sessions).
- Audit statusline scripts for instance-scoped filename support.
