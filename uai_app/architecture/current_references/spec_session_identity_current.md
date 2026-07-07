# Session Identity Specification v5.3

**Status:** Draft / implementation target  
**Supersedes:** v5.2  
**Created:** 2026-04-11  
**Scope:** CLI session identity for Claude CLI, Codex CLI, Gemini CLI, terminal substrates, statusline writers, session registry consumers, and UCI.

---

## 1. Purpose

Provide one stable identity model for AI CLI sessions that supports:

- deterministic launch-time identity before platform bootstraps finish
- exact lookup by tracking ID, CLI UUID, or terminal session name
- lightweight registry lookup for UI/client consumers
- richer per-session filesystem state without bloating the registry
- statusline/event writes from inside the running CLI process
- legacy v5.1/v5.2 session compatibility without renaming old IDs

---

## 2. Identity Model

There are three identity classes:

| Identity | Meaning | Stability | Source |
|---|---|---:|---|
| `tracking_id` | system-owned stable handle for this launch/session record | immutable | launcher/wrapper |
| `cli_session_id` | platform-native conversation/session UUID | mutable until known, then stable | platform or wrapper |
| `terminal_session` | tmux/zellij/session substrate name | normally stable, substrate-owned | launcher/substrate |

Rules:

1. `tracking_id` is the primary key and never changes after creation.
2. `cli_session_id` is authoritative for platform-native resume/history correlation.
3. `terminal_session` stays the terminal substrate name; do not rename this field to `terminal_id`.
4. Lookups use exact matching only. No fuzzy identity resolution.
5. Existing legacy tracking IDs remain valid and are not renamed.

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

- Timestamp is UTC launch time.
- `uuid8` is a correlation convenience and collision reducer. It is not authoritative identity.
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
          sessionInfo.json
          statusline.jsonl
```

Example:

```text
ai_general/data/sessions/claude_cli/2026/04/20260411_012005_fcf141f7_cla/
```

Rationale:

- Date-first tracking IDs sort naturally.
- Month-level grouping prevents very large flat directories without making day-level lookup too fragmented.
- UUID-prefix sharding is no longer required because callers should normally know `tracking_id`; date grouping is enough for discovery and cleanup.

Legacy sessions without parseable new IDs may use:

```text
ai_general/data/sessions/{platform}/legacy/{tracking_id}/
```

---

## 5. Registry Schema

The registry is a slim identity/pointer index, not a mutable runtime state store.

Canonical schema:

```sql
CREATE TABLE sessions (
    tracking_id       TEXT PRIMARY KEY,
    cli_session_id    TEXT,
    platform          TEXT NOT NULL,
    terminal_session  TEXT,
    session_dir       TEXT NOT NULL,
    project_dir       TEXT NOT NULL,
    history_file      TEXT
);

CREATE INDEX idx_sessions_uuid
    ON sessions(cli_session_id)
    WHERE cli_session_id IS NOT NULL;

CREATE INDEX idx_sessions_terminal
    ON sessions(terminal_session);

CREATE INDEX idx_sessions_platform_project
    ON sessions(platform, project_dir);
```

Field rules:

| Field | Required | Mutable | Notes |
|---|---:|---:|---|
| `tracking_id` | yes | no | immutable primary key |
| `cli_session_id` | no initially | yes until known | set at launch when possible; reconcile later if needed |
| `platform` | yes | no | keep explicit; do not derive only from tracking ID |
| `terminal_session` | no | rare | substrate name; null only for direct/no-mux if none exists |
| `session_dir` | yes | no | absolute path to per-session directory |
| `project_dir` | yes | no | canonical project/root for this session |
| `history_file` | no | yes | platform transcript/history path when known |

Compatibility note: deployed implementations may temporarily retain old columns (`working_dir`, `display_name`, `status`, `model`, etc.) while callers migrate. Canonical consumers should treat registry identity/pointer fields above as the durable contract.

---

## 6. Per-Session State: `sessionInfo.json`

Mutable runtime metadata lives in the session directory.

Path:

```text
{session_dir}/sessionInfo.json
```

Required baseline shape:

```json
{
  "schema_version": 3,
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
  "model": "optional model name",
  "roles": [],
  "cli_pid": 12345,
  "substrate": "zellij",
  "status": "running",
  "created_at": "2026-04-11T01:20:05Z",
  "updated_at": "2026-04-11T01:20:05Z"
}
```

Rules:

1. Write atomically: write `.tmp`, then rename.
2. `project_dir` is immutable after creation.
3. `working_dir` is mutable and belongs here, not in the canonical registry.
4. Runtime writers should update `sessionInfo.json` after registry mutations that affect mirrored fields.
5. Consumers needing live state should read this file after resolving `session_dir` from registry.

---

## 7. Statusline Persistence

Statusline/event data is append-only JSONL:

```text
{session_dir}/statusline.jsonl
```

Each line is one JSON object. Minimum useful fields:

```json
{"ts":"2026-04-11T01:20:10Z","cwd":"/path","model":"...","tokens":12345,"git_branch":"main"}
```

Rules:

- Statusline writers append one complete JSON object per line.
- Do not rewrite the full file for each status update.
- `sessionInfo.json` can contain the latest known summary, but `statusline.jsonl` is the durable event stream.

---

## 8. Launcher Environment Contract

Wrappers must export these variables into the launched CLI process environment:

```bash
AI_TRACKING_ID=<tracking_id>
AI_CLI_SESSION_ID=<uuid-or-empty-if-pending>
AI_SESSION_DIR=<absolute session_dir>
AI_SESSION_PLATFORM=<platform>
AI_PROJECT_DIR=<immutable project_dir>
```

Purpose:

- lets statusline scripts find `statusline.jsonl` without querying SQLite
- lets child tools locate `sessionInfo.json`
- avoids bootstrap discovery gaps for processes that cannot read wrapper internals
- provides a stable integration point across Claude, Codex, Gemini, tmux, zellij, direct mode, and UCI

If `AI_CLI_SESSION_ID` is empty at launch and a UUID is discovered later, registry/sessionInfo are updated. Existing child process environment cannot be changed retroactively; statusline scripts should prefer `sessionInfo.json` for latest UUID if needed.

---

## 9. Creation Flow

1. Wrapper computes or accepts `project_dir`.
2. Wrapper creates a UUID candidate when the platform does not provide one at launch.
3. Wrapper generates `tracking_id` using `{YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}`.
4. Wrapper computes `session_dir` under `{platform}/{YYYY}/{MM}/{tracking_id}`.
5. Wrapper creates `session_dir`.
6. Wrapper writes registry row.
7. Wrapper writes `sessionInfo.json`.
8. Wrapper exports `AI_*` variables into the launched CLI process.
9. Wrapper launches terminal substrate / CLI.
10. Wrapper updates `cli_pid`, `history_file`, or reconciled `cli_session_id` when discovered.

Failure rule: if launch fails after registry creation, mark/update `sessionInfo.json` and registry compatibility fields as failed/stopped where supported; do not delete evidence silently.

---

## 10. Lookup and Resolution

Resolution order:

1. exact `tracking_id`
2. exact `terminal_session`
3. exact `cli_session_id`

After resolution, clients read `session_dir/sessionInfo.json` for runtime state. Registry rows should remain small enough that listing all sessions is cheap.

---

## 11. Migration Plan

1. Add `session_dir`, `project_dir`, `history_file` to current SQLite store.
2. Preserve existing rows and tracking IDs.
3. For legacy rows:
   - `project_dir = working_dir` when available.
   - fallback `project_dir = AI_ROOT` when missing, and preserve original uncertainty in `sessionInfo.json` if needed.
   - `history_file = transcript_path` when available.
   - `session_dir = ai_general/data/sessions/{platform}/legacy/{tracking_id}` when the new date-first format is not parseable.
4. Start generating new tracking IDs for new launches only.
5. Export `AI_*` environment variables from all launch paths.
6. Update statusline scripts to write to `$AI_SESSION_DIR/statusline.jsonl`.
7. After all consumers use canonical fields, optionally rebuild/slim the SQLite table to remove compatibility columns.

---

## 12. Open Items

- Decide whether `cli_session_id` can become `NOT NULL` after all platforms reliably receive a wrapper UUID at launch. Current spec keeps it nullable for bootstrap/reconciliation safety.
- Update any external UCI queries that still read `working_dir` from the registry to read `project_dir` from registry and `working_dir` from `sessionInfo.json`.
- Audit statusline scripts for `$AI_SESSION_DIR` support.
- Add a migration test containing at least one legacy v5.1 ID and one new v5.3 ID.
