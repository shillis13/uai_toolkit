---
title: Claude Log Sources Mapping
version: 1.0
created: 2025-12-16
purpose: Identify what information is available from which log source
---

# Log Source Locations

## 1. Claude Desktop App Logs
**Location:** `~/Library/Logs/Claude/`

| File | Content | Useful For |
|------|---------|------------|
| `main.log` | App-level events: startup, shutdown, extension loading, update downloads, permission checks | App lifecycle, NOT chat switches |
| `mcp.log` | **GOLD** - Every MCP tool call with full JSON (tool name, arguments, results) | File reads, tool usage, timestamps |
| `mcp-server-{name}.log` | Per-server debug output | Debugging specific MCP servers |
| `claude.ai-web.log` | Web-related logs | Unknown |
| `unknown-window.log` | Unknown | Unknown |

### mcp.log Format
```
2025-12-16T16:06:55.750Z [info] [Desktop Commander] Message from client: {"method":"tools/call","params":{"name":"read_file","arguments":{"path":"/path/to/file"}},"jsonrpc":"2.0","id":13}
```
**Key signals:**
- `name":"read_file"` + `"path":"/..."` → File read event
- `name":"list_directory"` → Directory listing
- `name":"start_search"` → Search initiated
- Timestamps in ISO format

## 2. Claude CLI Logs  
**Location:** `~/.claude/`

| File/Dir | Content | Useful For |
|----------|---------|------------|
| `debug/{sessionId}.txt` | Full session transcripts - DEBUG output, tool calls, everything | CLI session history |
| `history.jsonl` | User prompts only (JSONL format) | What user asked |
| `daemon.log` | Pulse/orchestration system heartbeats | Daemon health |
| `logs/claude_*.log` | Command execution logs | CLI command output |
| `logs/orchestrator_pulse.log` | Orchestrator activity | Orchestration events |

### CLI debug file format
```
[DEBUG] Shell snapshot created successfully (7749 bytes)
[DEBUG] Loaded 0 unique skills...
```

## 3. App Data (NOT logs, but queryable)
**Location:** `~/Library/Application Support/Claude/`

| Path | Content | Useful For |
|------|---------|------------|
| `Local Storage/leveldb/` | Chat fragments, UI state, session markers | Active chat detection |
| `Session Storage/` | Session namespaces, chat UUIDs | Chat IDs |
| `config.json` | App config | - |
| `claude_desktop_config.json` | MCP server config | - |

### LevelDB data extraction
```bash
strings "Session Storage/000003.log" | grep -E '[0-9a-f]{8}-[0-9a-f]{4}'
```
Shows chat UUIDs.

---

# What We Can Detect From Each Source

| Signal | Source | Detection Method |
|--------|--------|------------------|
| File read (Desktop) | mcp.log | Parse JSON, look for `read_file` tool calls |
| Directory listing | mcp.log | Parse JSON, look for `list_directory` tool calls |
| Any tool call | mcp.log | Parse JSON, extract tool name + args |
| App start | main.log | Grep for startup patterns |
| MCP server connect | main.log | Grep for extension loading |
| CLI session start | ~/.claude/debug/ | New file created |
| CLI tool calls | ~/.claude/debug/*.txt | Parse DEBUG lines |
| Chat UUID | Session Storage | strings + grep |

---

# What We CANNOT Detect

| Signal | Why |
|--------|-----|
| Chat switch (URL change) | Not logged in main.log or mcp.log |
| My response content | Not in any log |
| Footer presence | Not in any log |
| Context compaction | Unknown if logged anywhere |
| Chat broken | No clear signal |

---

# Recommended Monitor Strategy

## Primary Source: mcp.log
- Every file I read goes here
- Every tool I call goes here
- Timestamps for sequencing
- JSON format = easy to parse

## Secondary Source: Session Storage (LevelDB)
- Chat UUIDs for tracking which chat
- Modification times on LDB files as activity indicator

## Tertiary: main.log
- App lifecycle only
- Not useful for per-chat monitoring

---

# Parser Design Implications

The parser should focus on **mcp.log** as primary input:

1. Tail mcp.log for new entries
2. Parse JSON from each line
3. Extract: timestamp, tool_name, arguments, result status
4. Emit structured events

For chat detection, we may need to:
- Watch Session Storage LDB files for modification
- Or accept that we can't reliably detect "new chat" and instead just watch for "system_status.yml read" as the positive signal
