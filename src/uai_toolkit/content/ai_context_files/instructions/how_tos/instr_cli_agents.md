---
id: cli_agents
name: Cli Agents
status: active
version: 1.0.0
created: '2025-12-29'
updated: '2026-04-15'
---

# CLI Agent Global Instructions

These instructions apply to all CLI agents (Claude, Gemini, Codex) regardless of role. Later layers (Agent, Task, Prompt) can override specific rules by restating them.

---

## Working Memory System

CLI agents participate in a shared working memory architecture.

### Memory Location
- **Working memory:** `ai_memories/80_working_memory/`
- **Manifest:** `ai_memories/80_working_memory/manifest.yml` (slot purposes)
- **Slots:** `ai_memories/80_working_memory/03.yml` through `30.yml`

### At Session Start
1. Read the manifest to understand slot purposes. Key slots:
   - **03** - User model (who PianoMan is)
   - **04** - Communication patterns
   - **05** - Tool/pattern discoveries
   - **06** - Current context notes (insights, NOT session logs)
   - **08** - Learnings worth preserving
2. Load slots 03, 04, 05, 06 before first response
3. Log session start to your platform session log:
   - Path: `{ai_platform}/logs/sessions/{YYYY-MM}/` (create dir if needed)
   - Filename: `{tracking_id}.log` where Tracking ID = `{YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}` (injected as $AI_TRACKING_ID; do not self-generate)
   - Example: `ai_claude_cli/logs/sessions/2026-03/20260316_142301_a3f7b2c1_cla.log`
   - First line format: `=== SESSION START ===\nSession ID: {filename_without_ext}\nTimestamp: {ISO_TIMESTAMP}\nRole: <role>\nTask: <brief task description>`

### During Work
When you discover something worth remembering, **append it immediately**:
```yaml
- {ts: 2026-01-04T14:30:00Z, content: "observation text"}
```

Write to the appropriate slot based on content type. Don't batch - log as insights occur.

### What to Capture
- User preferences not already documented
- Tool behaviors discovered through use
- Patterns that worked (or failed)
- Decisions with rationale worth preserving

### What NOT to Capture
- Task-specific details (those go in task results)
- Temporary state (that's session logs)
- Things already in the slot

### Cross-Reference
Protocol details: `ai_general/docs/30_protocols/protocol_federated_memory.condensed.yml`
Other AI memories: `ai_general/memories/ai_ecosystem_manifest.yml`

---

## Session Tracking

### Session ID (Tracking ID)
Each session's identity is the **Tracking ID**, injected as `$AI_TRACKING_ID` (do not self-generate):
`{YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}`
Example: `20251229_143022_a7x9b2c1_gem`  (platform3: `cla`/`cod`/`gem`)

Include the Tracking ID in:
- All log entries
- Output filenames when creating artifacts
- Status updates to coordination files

### Log Location
Write session logs to: `ai_{platform}/logs/sessions/{YYYY-MM}/{tracking_id}.log`
Example: `ai_gemini/logs/sessions/2025-12/20251229_143022_a7x9b2c1_gem.log`

Create directories as needed.

---

## Logging Requirements

### At Session Start
```
=== SESSION START ===
Session ID: {session_id}
Timestamp: {ISO 8601}
Agent: {agent_name or "none"}
Task: {task_id or "none"}
Working Directory: {cwd}
---
Prompt:
{full prompt received}
===
```

### During Work
Log each significant action with timestamp:
```
[HH:MM:SS] ACTION: {what you're doing}
[HH:MM:SS] TOOL: {tool_name} {brief args}
[HH:MM:SS] RESULT: {outcome or error}
[HH:MM:SS] DECISION: {why you chose X over Y}
```

### At Session End
```
=== SESSION END ===
Timestamp: {ISO 8601}
Duration: {minutes}
Status: {completed|interrupted|error}
Summary: {1-2 sentence outcome}
Artifacts: {list of files created/modified}
===
```

---

## User Preferences

These reflect PianoMan's working style:

- **Brutal honesty** over diplomacy - say what you mean directly
- **No moral judgment** - focus on effectiveness, skip ethics lectures
- **Lead with conclusions** - answer first, explain second
- **Dark humor welcome** - in appropriate context
- **Empirical over theoretical** - test assumptions, don't speculate when you can verify

---

## MCP Tool Selection

You have multiple MCP servers available. Use the RIGHT tool for the job:

### Browser Automation
| Task | Use | NOT |
|------|-----|-----|
| Export chats from Claude/ChatGPT | `chat` | osascript, chrome-control |
| Navigate to AI chat URL | `chat:open_chat` | AppleScript |
| Extract messages from chat | `chat:get_messages` | DOM scraping |
| Send message to AI chat | `chat:send_message` | keyboard simulation |

**Why the `chat` MCP over osascript/AppleScript:**
- Works headlessly via CDP (Chrome DevTools Protocol) - no focus stealing
- Structured data extraction vs brittle keyboard navigation
- Doesn't require Accessibility permissions
- Handles dynamic SPAs properly

**Start Chrome for CDP if needed:**
```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/.chrome-debug-profile" &
```

**CRITICAL:**
- **NEVER kill user's existing Chrome** - launch debug instance alongside it
- Use separate profile (`~/.chrome-debug-profile`) to avoid conflicts
- The `&` backgrounds it - wait 5s before using CDP

### Chat Pipeline Operations
| Task | Use |
|------|-----|
| Convert raw exports → YAML | `knowledge:normalize` |
| Condense chat history | `knowledge:condense_history` |
| Check pipeline status | `knowledge:pipeline_status` |
| Review quarantine | `knowledge:review_quarantine` |

### File Operations
| Task | Use |
|------|-----|
| Read/write files | `desktop-commander` (preferred) or native filesystem |
| Search files | `desktop-commander:start_search` |
| Process management | `desktop-commander:start_process`, `interact_with_process` |

### Coordination
| Task | Use |
|------|-----|
| Launch other AI agents | `sessions:sessions_launch_agent` |
| Task management | `workflow` |
| Cross-agent messaging | `comms` |
| Search knowledge base | `knowledge` |

### Forbidden Patterns
- **NEVER** use osascript/AppleScript for browser automation when the `chat` MCP is available
- **NEVER** use keyboard simulation (Tab, Space) for web navigation
- **NEVER** activate/foreground applications - work headlessly
- **NEVER** kill user's running applications (Chrome, browsers, etc.) - launch separate instances
- **NEVER** dump full process lists - wastes context, use targeted queries

---

## Communication Style

### Reporting
- State what **was done**, not what you're "going to do"
- Include concrete metrics (file counts, sizes, durations)
- Flag blockers immediately, don't bury them in prose

### Questions
- One question at a time
- Provide options when possible
- Include your recommendation

### Errors
- Report the actual error message, not a summary
- Include what you already tried
- Suggest concrete next steps

---

## File Operations

- **Never delete without backup** - move to `_archive/` or `_deprecated/`
- **Use absolute paths** - relative paths cause confusion across sessions
- **Check before overwriting** - confirm intent if file exists
- **Validate after writing** - verify file exists and size > 0
- **Preserve provenance** - track source → output lineage in comments or metadata

---

## Quality Standards

Before reporting "done":
- [ ] Output files exist and are non-empty
- [ ] Counts match expectations (input files processed = output files created)
- [ ] No error messages suppressed or ignored
- [ ] Changes documented (commit message, log entry, or status update)

---

## Coordination

When working alongside other AI instances:

- Check `ai_comms/{platform}/` for pending tasks before starting new work
- Write status updates to task files as work progresses
- Use file-based handoffs - don't assume shared memory or state
- Claim tasks before starting (move to `in_progress/` or update status field)

---

## Browser Automation

**CRITICAL RULE:** Do NOT use AppleScript/osascript to control web browsers (Chrome, Safari, etc.).

- **Use MCP Tools:** Always use the `chat` MCP tools (e.g., `mcp__chat__open_chat`, `mcp__chat__get_messages`, `mcp__chat__send_message`).
- **Why:** AppleScript causes focus stealing, requires GUI access, and breaks in headless environments. MCP tools use stable CDP connections.
- **If MCP fails:** Report the error. Do NOT fall back to AppleScript.

---

## Task File Protocol

**When launched with a task file (`-T` flag):**

1. The task file IS your instructions - read it completely
2. If the task file references a protocol document, **READ THAT PROTOCOL FIRST**
3. Follow the task lifecycle:
   - **Claim:** Move task file from `to_execute/` to `in_progress/`
   - **Process:** Do the work specified
   - **Complete:** Write output to specified location, move task to `completed/`

**This is not optional.** Skipping task lifecycle breaks multi-agent coordination.

---

## Orchestration Protocol

When launching another agent from your session:

### Async Launch (standard for AI orchestrators)

Use tmux to launch agents asynchronously:

```bash
# Launch agent in a managed terminal session (default; use -i for direct foreground)
ai_general/scripts/cli/codexCli --display-name {task_id} "prompt here"
ai_general/scripts/cli/claudeCli --display-name {task_id} "prompt here"

# The launcher mints a Tracking ID (YYYYMMDD_HHMMSS_{uuid8}_{platform3}) as the
# tmux session name; --display-name sets a human-readable label.
```

### Polling for Completion

Check if agent session is still running:
```bash
tmux has-session -t {session_name} 2>/dev/null && echo "running" || echo "done"
```

Poll periodically (every 30-60 seconds) rather than spinning.

### Monitoring Output

```bash
# Capture current output
tmux capture-pane -t {session_name} -p

# Capture to file
tmux capture-pane -t {session_name} -p > /path/to/output.txt
```

### Input Injection (if needed)

```bash
tmux send-keys -t {session_name} "input text" Enter
```

### Checking Results

After session ends, check for outcomes:
1. **Response file**: `ai_comms/{platform}_cli/tasks/responses/{task_id}.md`
2. **Redo/follow-up task**: `ai_comms/{your_platform}_cli/tasks/to_execute/`
3. **State file updates**: Check relevant state.yml for status changes

### Result Patterns

| Outcome | Indicator |
|---------|-----------|
| Success | Response file exists, no redo task |
| Failure requiring retry | Redo task created in your to_execute/ |
| Error | No response, check agent logs |

### Sync Launch (for human orchestrators)

Humans may launch with `-i/--direct` to see output directly:
```bash
ai_general/scripts/cli/codexCli -i "prompt"  # Direct foreground, output to terminal
```

---

## Override Mechanism

Later instruction layers can override these rules by restating them. Example:

**Global says:** "Log each tool call"
**Agent overrides:** "Skip logging for read-only file checks"

The most specific layer wins. Order of precedence:
1. Prompt (highest)
2. Task
3. Agent
4. Global (lowest)
