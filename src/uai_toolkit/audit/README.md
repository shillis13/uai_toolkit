# Audit System — CLI Reference

## Overview

The audit system captures AI communications and tool calls, then provides forensics tools for investigating what happened, when, and by whom.

**Three layers:**
1. **Capture** — hooks and instrumentation that emit events in real-time
2. **Storage** — daily JSONL files (source of truth) + SQLite indexes (queryable)
3. **Forensics** — CLI commands that aggregate evidence into timelines and graphs

## Quick Start

```bash
# What happened to this file?
python3 ~/bin/ai/audit/audit.py files investigate /path/to/file.py

# Where did this file go? (moved/renamed/deleted)
python3 ~/bin/ai/audit/audit.py files trace /path/to/missing_file.py

# What did this session do?
python3 ~/bin/ai/audit/audit.py session 20260412_030506_f3c818cf_cla

# Who talked to this session?
python3 ~/bin/ai/audit/audit.py comms timeline 20260412_030506_f3c818cf_cla

# Follow the conversation thread
python3 ~/bin/ai/audit/audit.py comms chain 20260412_030506_f3c818cf_cla

# Find ghost messages (unattributed writes)
python3 ~/bin/ai/audit/audit.py query comms --unmatched-writes --since 2026-04-12

# Rebuild search index from JSONL
python3 ~/bin/ai/audit/audit.py rebuild comms
python3 ~/bin/ai/audit/audit.py rebuild tools
```

## Commands

### `files investigate <path>` — What changed?

Shows the modification history of a file: who read it, who wrote it, when it was committed, current metadata.

```bash
audit.py files investigate /path/to/file.py [--since DATE] [--until DATE] \
    [--no-timemachine] [--delta from-first|from-prev] [--format text|json|raw]
```

**Data sources:** filesystem stat, git log, tool-call audit, anti-clobbering access log, Time Machine snapshots.

If the file doesn't exist, shows a suggestion to use `files trace` instead.

### `files trace <path>` — Where did it go?

Tracks moves, renames, and deletions. Uses git `--follow` with rename detection, scans Bash tool events for `mv`/`rm`/`cp` commands, checks Time Machine for deletion windows.

```bash
audit.py files trace /path/to/old_file.py [--since DATE] [--until DATE] \
    [--no-timemachine] [--delta from-first|from-prev] [--format text|json|raw]
```

**Status values:** EXISTS, MISSING, MISSING — renamed to X, MISSING — deleted in commit Y.

### `session <identifier>` — What did this session do?

Unified activity timeline interleaving tool calls and communications. Shows summary counts (tool calls by status, messages sent/received, files touched).

```bash
audit.py session <tracking_id|uuid|display_name> [--since DATE] [--until DATE] \
    [--delta from-first|from-prev] [--format text|json|raw]
```

**Accepts any identifier:** tracking ID, CLI UUID, UUID prefix, terminal session name, display name.

### `comms timeline <identifier>` — Who talked to this session?

Comms-only view showing TRANS (transmitted) and RECV (received) messages with peer identification. De-duplicates prompt_dispatch + session_write pairs into logical transmissions.

```bash
audit.py comms timeline <identifier> [--since DATE] [--until DATE] \
    [--delta from-first|from-prev] [--format text|json|raw]
```

### `comms chain <identifier>` — Follow the thread

Transitive communication graph: who talked to whom, and who those sessions talked to. Dual output: tree table (overview) + flow tree (directional detail).

```bash
audit.py comms chain <identifier> [--since DATE] [--until DATE] \
    [--depth N] [--direction out|in|both] [--format text|json|raw]
```

### `query <category> [filters]` — Raw event queries

Direct queries against the audit index. Category is `comms` or `tools`.

```bash
audit.py query comms --target-session <tracking_id>
audit.py query comms --actor-tracking-id <tracking_id>
audit.py query comms --unmatched-writes --since 2026-04-12
audit.py query tools --target-file /path/to/file.py
audit.py query tools --action Edit --since 2026-04-16
```

### `rebuild <category>` — Rebuild search index

Drops and recreates the SQLite index from JSONL files. Use after schema changes or if the index seems stale.

```bash
audit.py rebuild comms
audit.py rebuild tools
```

## Output Formats

All commands support `--format text|json|raw`:

| Format | Purpose | Contents |
|--------|---------|----------|
| `text` | Human investigation | Formatted timeline with colors, delta times, actor resolution |
| `json` | Programmatic / UCI app | Normalized model with summary, enriched events, de-duplicated comms |
| `raw` | Debugging | Raw provider events before normalization |

## Common Options

| Flag | Description |
|------|-------------|
| `--since YYYY-MM-DD` | Filter events after this date |
| `--until YYYY-MM-DD` | Filter events before this date |
| `--delta from-first` | Show elapsed time from first event |
| `--delta from-prev` | Show gap since previous event |
| `--no-timemachine` | Skip Time Machine probing (faster) |
| `--format text\|json\|raw` | Output format (default: text) |
| `--depth N` | Chain traversal depth (default: 2) |
| `--direction out\|in\|both` | Chain traversal direction (default: out) |

## Architecture

```
~/bin/ai/audit/
├── audit.py                     # CLI entry point (user-facing)
├── hook_audit_tools.py          # PostToolUse hook (auto-invoked by platforms)
├── lib_audit.py                 # Core: emit(), query(), rebuild_index()
├── lib_audit_store.py           # JSONL + SQLite storage engine
├── lib_session_resolver.py      # Session identity, alias sets, colors
├── lib_formatting.py            # Delta time, ANSI colors, TTY detection
├── lib_comms_normalizer.py      # De-duplicate prompt_dispatch + session_write
├── lib_bash_parser.py           # Extract file ops from Bash commands
├── lib_path_normalizer.py       # Cross-source path matching
├── lib_forensics_analyzer.py    # Investigate output formatter
├── lib_cmd_trace.py             # files trace implementation
├── lib_cmd_session.py           # session timeline implementation
├── lib_cmd_comms.py             # comms timeline + chain implementation
├── providers/                   # Evidence source adapters
│   ├── stat_provider.py         # Filesystem metadata
│   ├── git_provider.py          # Git log + rename/delete detection
│   ├── tools_audit_provider.py  # Tool-call audit index queries
│   ├── bash_trace_provider.py   # Bash command parsing for file ops
│   ├── access_log_provider.py   # Anti-clobbering hook log
│   └── timemachine_provider.py  # Time Machine snapshot probing
├── tests/                       # 86 tests
└── README.md                    # This file
```

**Data storage:**
```
ai_general/data/audit/
├── comms/events/audit_YYYY-MM-DD.jsonl    # Communications
├── comms/index.db                          # SQLite index (rebuildable)
├── tools/events/audit_YYYY-MM-DD.jsonl    # Tool calls
├── tools/index.db
└── config.yml                              # Retention, tiering config
```

## How Capture Works

**Communications:** `session_ops.write_to()` emits `session_write` events. MCP prompting tools emit `prompt_dispatch` events. PID correlation links the two tiers.

**Tool calls:** PostToolUse hooks fire on every tool completion in Claude Code, Codex CLI, and Gemini CLI. Each emits an event with tool name, file path, input/result preview, and success status.

**Hook registration:**
- Claude Code: `~/.claude/settings.json` (PostToolUse, all tools)
- Codex CLI: `~/.codex/hooks.json` (PostToolUse, Bash only)
- Gemini CLI: `~/.gemini/settings.json` (AfterTool, all tools)

## Session Identifiers

All session-based commands accept any identifier form:
- Tracking ID: `20260412_030506_f3c818cf_cla`
- CLI UUID: `f3c818cf-f6be-4088-a873-c53f066986ff`
- UUID prefix: `f3c818cf`
- Terminal session name: `20260412_030506_f3c818cf_cla`
- Display name: `CompactionII_20260412_165230_44dc7b51_cla`

Resolution via `session_store.resolve()` with prefix and display name matching.
