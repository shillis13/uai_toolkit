---
title: Claude Log Sources Mapping
version: 1.0
created: 2025-12-16
purpose: Identify what information is available from which log source
---

# Log Source Locations

## 1. CLI Session Transcripts & Logs
**Location:** `~/.claude/`

| File/Dir | Content | Useful For |
|----------|---------|------------|
| `projects/<project>/<sessionId>.jsonl` | **GOLD** — full session transcript: every user prompt, assistant turn, and native/MCP tool call with arguments and results | Tool usage, file reads, timestamps, sequencing |
| `debug/{sessionId}.txt` | DEBUG output, tool calls, everything for a session | CLI session history |
| `history.jsonl` | User prompts only (JSONL format) | What the user asked |
| `daemon.log` | Pulse/orchestration heartbeats | Daemon health |
| `logs/claude_*.log` | Command execution logs | CLI command output |
| `logs/orchestrator_pulse.log` | Orchestrator activity | Orchestration events |
| `file-history/` | Native snapshots of files the CLI edited | Reconstructing file changes |

### JSONL transcript format
Each line is a JSON object. Tool calls appear as `tool_use` blocks and results as `tool_result` blocks:
```
{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"file_path":"/path/to/file"}}]}}
```
**Key signals:**
- `"name":"Read"` + `"file_path":"/..."` → file read event
- `"name":"Grep"` / `"name":"Glob"` → search initiated
- `mcp__<server>__<tool>` names → MCP tool calls (comms / knowledge / sessions / workflow / chat)
- Timestamps in ISO format on each entry

### CLI debug file format
```
[DEBUG] Shell snapshot created successfully (7749 bytes)
[DEBUG] Loaded 0 unique skills...
```

---

# What We Can Detect From Each Source

| Signal | Source | Detection Method |
|--------|--------|------------------|
| File read | `*.jsonl` transcript | Parse JSON, look for `Read` tool_use blocks |
| Search (Grep/Glob) | `*.jsonl` transcript | Parse JSON, look for `Grep`/`Glob` tool_use |
| MCP tool call | `*.jsonl` transcript | Parse JSON, extract `mcp__*` tool name + args |
| Any tool call | `*.jsonl` transcript | Parse JSON, extract tool name + args |
| User prompt | `history.jsonl` | One entry per prompt |
| CLI session start | `~/.claude/debug/` | New file created |
| File edit | `file-history/` | Snapshot written |

---

# What We CANNOT Detect

| Signal | Why |
|--------|-----|
| My response reasoning | Thinking blocks may be omitted from transcript |
| Footer presence | Not separately logged |
| Context compaction | Not clearly signaled in logs |
| Session broken/wedged | No clear signal |

---

# Recommended Monitor Strategy

## Primary Source: JSONL session transcript
- Every prompt, tool call, and result is recorded
- ISO timestamps for sequencing
- JSON format = easy to parse

## Secondary Source: `~/.claude/debug/*.txt`
- DEBUG-level detail and session lifecycle
- New file = new session started

## Tertiary: `logs/*.log`
- Command execution and orchestration activity

---

# Parser Design Implications

The parser should focus on the **JSONL session transcript** as primary input:

1. Tail the active `*.jsonl` for new lines
2. Parse JSON from each line
3. Extract: timestamp, tool_name, arguments, result status
4. Emit structured events

For session detection, watch `~/.claude/debug/` and `~/.claude/projects/` for new files.
