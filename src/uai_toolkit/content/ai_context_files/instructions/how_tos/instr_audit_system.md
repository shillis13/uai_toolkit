---
id: instr_audit_system
name: Audit System
status: active
version: 1.0.0
created: '2026-04-16'
updated: '2026-04-16'
---

# Audit System — Usage Guide

## Overview

The audit system captures two categories of events and provides a forensics CLI for investigating file history.

**Comms audit** (`audit/comms/`) — every message sent between AI sessions, to Desktop Claude, or to web UI platforms. Captures who sent what, to whom, when, and via which delivery mechanism.

**Tools audit** (`audit/tools/`) — every tool call made by Claude Code, Codex CLI, or Gemini CLI. Captures which tool, what file was targeted, input/result previews, and success status.

**File forensics** (`audit files investigate`) — aggregates evidence from git, tool audit, access logs, filesystem metadata, and Time Machine into a chronological timeline for any file path.

## Architecture

```
~/bin/ai/audit/
├── __init__.py
├── lib_audit.py           # Public API: emit(), query(), rebuild_index()
├── lib_audit_store.py     # JSONL + SQLite storage engine
├── audit.py               # CLI entry point
├── hook_audit_tools.py    # PostToolUse/AfterTool hook (all 3 platforms)
└── providers/             # Forensics evidence providers
    ├── stat_provider.py
    ├── git_provider.py
    ├── tools_audit_provider.py
    ├── access_log_provider.py
    └── timemachine_provider.py
```

**Storage:**
```
ai_general/data/audit/
├── comms/
│   ├── events/audit_YYYY-MM-DD.jsonl   # Source of truth (append-only)
│   └── index.db                         # SQLite index (rebuildable)
├── tools/
│   ├── events/audit_YYYY-MM-DD.jsonl
│   └── index.db
└── config.yml
```

## Using the CLI

### Query comms events

```bash
# What was sent TO a specific session?
audit query comms --target-session 20260412_165233_ba0c7fad_cod

# What did a specific session SEND?
audit query comms --actor-tracking-id 20260412_030506_f3c818cf_cla

# Everything in a time window
audit query comms --since 2026-04-12T18:40:00Z --until 2026-04-12T18:45:00Z

# Ghost detection — find unmatched low-level writes (no high-level dispatch)
audit query comms --unmatched-writes --since 2026-04-12
```

### Query tool events

```bash
# What tool calls targeted a specific file?
audit query tools --target-file /path/to/file.py

# What did a specific session do?
audit query tools --actor-tracking-id 20260414_021257_bbddcf1e_cla

# All Edit operations today
audit query tools --action Edit --since 2026-04-16
```

### Investigate a file

```bash
# Full timeline — what happened to this file?
audit files investigate /path/to/file.py

# Restrict to recent history
audit files investigate /path/to/file.py --since 2026-04-12

# Skip Time Machine probing (faster)
audit files investigate /path/to/file.py --no-timemachine

# Investigate a deleted file
audit files investigate /path/to/deleted_file.md --since 2026-04-01
```

### Rebuild indexes

```bash
# Rebuild from JSONL (if index is corrupted or schema changed)
audit rebuild comms
audit rebuild tools
```

## Interpreting the Data

### Comms Events

**Two-tier model:** Every communication has up to two events:

1. **`prompt_dispatch`** (high-level) — emitted by the send_prompt dispatcher. Captures intent: who requested the send, the target, message preview. Has `actor.label` identifying the caller (e.g., `"prompting:send_prompt"`, `"prompting:send_to_session"`).

2. **`session_write`** (low-level) — emitted by `session_ops.write_to()`. Captures mechanics: delivery mode (paste/typed), substrate (tmux), success/failure.

**PID correlation:** Both events from the same send share the same `caller.pid` (or `caller.ppid` for subprocess paths). This links "why" to "what."

**Ghost detection:** A `session_write` with no matching `prompt_dispatch` from the same PID within 2 seconds = an unmatched write. This is either:
- A UCI PromptBox submission (goes through session_ops directly, bypasses MCP)
- An unknown/rogue caller (the ghost scenario)

To distinguish: check `caller.ppid`. If it's the UCI Electron app PID, it's a PromptBox submission. If unknown, investigate further.

### Tool Events

Each event has:
- `action` — tool name (Edit, Write, Read, Bash, Grep, etc.)
- `target.file` — file path for structured tools (Edit/Write/Read/Grep/Glob). Null for Bash and MCP tools.
- `target.session` — CLI session UUID
- `details.success` — tri-state: `true` (confirmed success), `false` (confirmed failure), `null` (unknown). Never guesses.
- `details.input_preview` / `details.result_preview` — first 512 chars of tool input and result

### Forensics Timeline

`audit files investigate` returns events from 5 sources, each with a `source` field:

| Source | What it tells you | Actor attribution |
|--------|------------------|-------------------|
| `stat` | Current file metadata (mtime, size, exists) | None |
| `git` | Commit history (hash, message, diff stats) | `co_author` from trailer |
| `tools_audit` | AI tool calls targeting this file | `tracking_id`, `platform` |
| `access_log` | Claude Code read/write ops (pre-audit history) | `session` UUID |
| `timemachine` | Snapshot presence/absence, deletion windows | None |

**Events are NOT deduplicated.** The same modification may appear from multiple sources — this is corroboration, not noise.

**`provider_error` events** indicate a source couldn't contribute (e.g., Time Machine unmounted, file not in a git repo). These are diagnostic — they tell you what evidence was unavailable.

**Deleted file investigation:** When a file is missing:
- `stat` returns nothing
- `git` uses `--all --follow` to search all branches
- `tools_audit` shows last known operations
- `timemachine` brackets the deletion window (last snapshot where present → first where missing)

## How It Works Under the Hood

### Comms Capture Flow

```
MCP send_prompt tool
  → _audit_prompt_dispatch()          # High-level: prompt_dispatch event
  → lib_send_prompt.send_cli()
    → session_ops.write_to()
      → _audit_emit_session_write()   # Low-level: session_write event
      → substrate.send_keys()         # Actual tmux/zellij delivery
```

The `_audit_emit` functions are wrapped in try/except pass — they never block or crash the delivery path.

### Tool Capture Flow

```
Claude/Codex/Gemini executes any tool
  → PostToolUse / AfterTool hook fires
  → hook_audit_tools.py reads stdin JSON
  → Normalizes platform differences
  → Extracts file path from tool_input
  → Detects success from tool_result
  → audit.emit(category="tools", ...)
  → Exits 0 (silent)
```

### Storage

- **JSONL** is the source of truth. Append-only, one event per line, `fcntl.flock` for cross-process safety.
- **SQLite** is a derived index. WAL mode for concurrent reads. Rebuildable from JSONL at any time via `audit rebuild`.
- Each event has a `v: 1` schema version for future migration.

### Platform Differences

| Platform | Hook event | Result field | Tool coverage | Config location |
|----------|-----------|-------------|---------------|-----------------|
| Claude Code | PostToolUse | tool_result | All tools | ~/.claude/settings.json |
| Codex CLI | PostToolUse | tool_response | Bash only | ~/.codex/hooks.json |
| Gemini CLI | AfterTool | tool_response | All tools | ~/.gemini/settings.json |

The hook script auto-detects the platform from `hook_event_name` and `AUDIT_PLATFORM` env var.

## Emitting Audit Events (For Developers)

To add audit instrumentation to new code:

```python
# At any chokepoint:
import sys
sys.path.insert(0, str(Path.home() / "bin" / "ai"))
from audit import lib_audit

lib_audit.emit(
    category="comms",           # or "tools"
    action="session_write",     # what happened
    target={                    # what was acted on
        "type": "cli_session",
        "session": "tracking_id_here",
    },
    details={                   # action-specific context
        "text_length": 100,
        "success": True,
    },
    label="my_tool:my_action",  # optional high-level caller identity
)
```

**Rules:**
- `emit()` never raises — wraps everything in try/except
- Actor (tracking_id, platform) and caller (pid, ppid, process) are auto-captured from env vars and os module
- Truncate any preview fields to 512 chars BEFORE calling emit
- `details.success` must be tri-state: `True`, `False`, or `None` (unknown) — never default to True
