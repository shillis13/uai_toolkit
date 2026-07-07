# CLI Browser Automation: Instruction Levels Guide

**Created:** 2025-11-18  
**Topic:** How to instruct CLI instances for browser automation tasks  
**Context:** Now that Codex CLI and Claude CLI have BrowserMCP

---

## TL;DR

**They need explicit workflow instructions, but can handle execution autonomy.**

- ❌ Can't figure out: Your Chrome extensions, your workflows, your URLs
- ✅ Can figure out: How to navigate, click, retry, handle errors
- ✅ Can return: URLs, file paths, structured output via response files

---

## Instruction Spectrum

### Level 1: Too Vague ❌
```markdown
Download the chat history and create a new chat.
```

**Why it fails:**
- What extension?
- Which buttons?
- What chat?
- Which project?

### Level 2: Goal-Oriented (First Attempt) ⚠️
```markdown
Use the Claude Chat Exporter extension to export this chat as JSON and Markdown,
then create a new chat in the Development project. Return the new chat URL.

Chat URL: https://claude.ai/chat/abc123
```

**Why it might work:**
- Clear goal
- Specific URLs
- Named extension

**Why it might fail:**
- No selector hints
- No timing guidance
- Might miss extension location

### Level 3: Detailed Workflow (Recommended) ✅
```markdown
## Task: Export Chat and Create New Chat

**Extension:** "Claude Chat Exporter" (installed in Chrome)
**Current chat:** https://claude.ai/chat/abc123
**Target project:** Development (ID: xyz789)

### Steps:
1. Navigate to current chat URL
2. Click extension icon (top-right toolbar, Claude logo)
3. Click "Export JSON" button (first button in popup)
4. Wait 3 seconds
5. Click "Export Markdown" button (second button)
6. Wait 3 seconds
7. Navigate to https://claude.ai/project/xyz789
8. Click "New Chat" button
9. Return new chat URL

### Return Format:
```json
{
  "json_file": "$HOME/Downloads/filename.json",
  "md_file": "$HOME/Downloads/filename.md",
  "new_chat_url": "https://claude.ai/chat/new-id"
}
```
```

**Why it works:**
- Specific extension name
- Button descriptions
- Timing hints
- Clear output format
- URLs provided

---

## What They Can/Can't Do

### ✅ CLI Instances CAN:
- Navigate Chrome once given URLs
- Find elements based on descriptions
- Click buttons/links
- Handle basic errors and retry
- Wait for page loads
- Capture current URL
- Write structured output to response files

### ❌ CLI Instances CANNOT (without instruction):
- Know about your Chrome extensions
- Know your project structure
- Know your workflow patterns
- Access Desktop Claude's context/memory
- Make assumptions about UI element locations

---

## Output Capture Methods

### Method 1: Response File (Coordination Protocol)

**How it works:**
1. Desktop posts task to `tasks/incoming/`
2. CLI executes, writes to `tasks/responses/`
3. Desktop reads response file

**Example response:**
```markdown
# Response: Request #1050

**Status:** COMPLETED
**Completed:** 2025-11-18 17:45:00

## Results
Successfully exported chat and created new chat.

## Output Data
```json
{
  "exported_json": "$HOME/Downloads/chat_20251118_1745.json",
  "exported_markdown": "$HOME/Downloads/chat_20251118_1745.md",
  "new_chat_url": "https://claude.ai/chat/f7d9e8b3-a4c5-4d6e-8f9a-0b1c2d3e4f5g",
  "project_url": "https://claude.ai/project/xyz789"
}
```

## Execution Log
1. ✅ Navigated to chat abc123
2. ✅ Clicked extension icon
3. ✅ Exported JSON (downloaded to Downloads/)
4. ✅ Exported Markdown (downloaded to Downloads/)
5. ✅ Navigated to Development project
6. ✅ Created new chat
7. ✅ Captured new chat URL
```

### Method 2: CLI --print Mode

**Claude CLI:**
```bash
# Direct execution with output capture
claude --print "Export chat abc123 via extension, create new chat, return URL"

# Capture to variable
NEW_URL=$(claude --print "Export and create new chat. Print only URL.")

# With structured output
claude --print "Return JSON: {new_chat_url, json_file, md_file}" | jq .
```

**Codex CLI:**
```bash
# Codex exec mode also captures stdout
codex exec "Navigate to chat, export via extension, create new chat, print URL"

# Or with explicit output
codex exec "$(cat task_instructions.md)" > output.txt
```

**Pros:**
- Direct command-line integration
- Captures stdout cleanly
- Scriptable and pipeable
- Great for automation

**Cons:**
- No built-in task tracking
- Need to parse stdout
- Less context than coordination protocol

### Method 3: Hybrid (Coordination + Codex Exec)

**Best of both:**
1. Desktop posts task to coordination
2. CLI uses Codex exec for browser work
3. CLI writes structured response
4. Desktop reads clean output

---

## Shell Script Automation with --print

### Example 1: Simple URL Capture

```bash
#!/bin/bash
# export_and_get_url.sh

CHAT_ID="$1"
PROJECT_ID="$2"

NEW_URL=$(claude --print "
Navigate to https://claude.ai/chat/${CHAT_ID}
Use Claude Chat Exporter extension to export JSON and Markdown
Create new chat in project ${PROJECT_ID}
Print only the new chat URL
")

echo "New chat: $NEW_URL"
```

**Usage:**
```bash
./export_and_get_url.sh abc123 xyz789
# Output: New chat: https://claude.ai/chat/new-id
```

### Example 2: Structured JSON Output

```bash
#!/bin/bash
# export_with_details.sh

RESULT=$(claude --print "
Export chat abc123 using Chrome extension
Create new chat in Development project
Return JSON with fields: new_chat_url, json_file, md_file
")

# Parse JSON
NEW_URL=$(echo "$RESULT" | jq -r .new_chat_url)
JSON_FILE=$(echo "$RESULT" | jq -r .json_file)
MD_FILE=$(echo "$RESULT" | jq -r .md_file)

# Use results
echo "Chat exported to: $JSON_FILE and $MD_FILE"
echo "New chat: $NEW_URL"

# Write for Desktop Claude
cat > ~/AI/ai_comms/claude_cli/tasks/responses/export_complete.json << EOF
{
  "status": "completed",
  "new_chat_url": "$NEW_URL",
  "exports": {
    "json": "$JSON_FILE",
    "markdown": "$MD_FILE"
  }
}
EOF
```

### Example 3: Coordination Integration

```bash
#!/bin/bash
# execute_browser_task.sh
# Wrapper that bridges coordination protocol and --print mode

TASK_FILE="$1"
RESPONSE_DIR="$2"

# Execute task using --print
RESULT=$(claude --print "$(cat $TASK_FILE)")

# Extract task ID from filename
TASK_ID=$(basename "$TASK_FILE" .md)

# Write structured response
cat > "$RESPONSE_DIR/${TASK_ID}_response.json" << EOF
{
  "task_id": "$TASK_ID",
  "timestamp": "$(date -Iseconds)",
  "result": $RESULT
}
EOF

echo "Task $TASK_ID completed. Response written to $RESPONSE_DIR"
```

**Desktop Claude workflow:**
1. Posts task: `tasks/incoming/req_1050.md`
2. Runs: `./execute_browser_task.sh tasks/incoming/req_1050.md tasks/responses/`
3. Reads: `tasks/responses/req_1050_response.json`

---

## Practical Examples

### Example 1: Simple Export

**Task file:** `req_1051_quick_export.md`
```markdown
# Request #1051: Quick Chat Export

Use Chrome extension "Claude Chat Exporter" to export current chat.

**Current chat:** https://claude.ai/chat/current-chat-id
**Extension location:** Chrome toolbar, top-right
**Buttons:** "Export JSON" (top), "Export Markdown" (bottom)

Click both buttons, wait 3 seconds between clicks.

Return file paths in response.
```

**Estimated autonomy:** 85% - CLI can execute with minimal decisions

### Example 2: Multi-Step Workflow

**Task file:** `req_1052_export_and_organize.md`
```markdown
# Request #1052: Export, Rename, and Organize

1. Export chat abc123 using extension (JSON + MD)
2. Rename files to: chat_project-name_YYYYMMDD.*
3. Move to: ~/AI/ai_memories/10_exported/claude/
4. Create new chat in Development project
5. Post message: "Continuing from [old chat link]"

**Extension:** Claude Chat Exporter
**Download location:** ~/Downloads/
**Date format:** 20251118
```

**Estimated autonomy:** 60% - Requires file operations + browser work

### Example 3: Conditional Workflow

**Task file:** `req_1053_smart_export.md`
```markdown
# Request #1053: Smart Export with Conditions

**Goal:** Export chat if it has >50 messages, create archive

**Logic:**
1. Navigate to chat
2. Count messages (look for message count in UI)
3. IF count > 50:
   - Export both formats
   - Create archive folder with date
   - Move exports
   - Create new chat with link
4. ELSE:
   - Skip export
   - Return count only

**Extension:** Claude Chat Exporter
```

**Estimated autonomy:** 40% - Requires logic and decisions

---

## Iteration and Refinement

### First Run: Expect Failures
- Element selectors might be wrong
- Timing might be off
- Extension behavior might differ


**What to do:**
1. Review CLI response/error log
2. Update selectors/timing in task
3. Post refined version as req_1051_v2
4. CLI retries with improvements

### Second Run: Refinements
- "Button not found" → Add fallback text
- "Click failed" → Add retry logic hint
- "Wrong element" → Add more specific selector

### Third Run: Template
Once working, save as reusable template:
```markdown
# Template: Export Chat via Extension

**Instructions:**
- Current chat URL: [FILL]
- Project for new chat: [FILL]

[PROVEN WORKFLOW STEPS]
```

---

## Best Practices

### DO:
✅ Provide specific URLs
✅ Name extensions and buttons
✅ Give timing hints (wait X seconds)
✅ Specify output format
✅ Include fallback options
✅ Allow for troubleshooting notes in response

### DON'T:
❌ Assume they know your extensions
❌ Use vague descriptions ("the button")
❌ Skip timing information
❌ Forget to specify return format
❌ Make them guess project IDs

---

## Decision Tree: How Much to Instruct

```
Is this a one-time task?
├─ YES → Detailed instructions
└─ NO → Will repeat?
    ├─ YES → Invest in template creation
    │         1. Detailed first run
    │         2. Refine based on errors
    │         3. Save as template
    └─ NO → Medium detail okay

Is the UI stable?
├─ YES → Can use specific selectors
└─ NO → Use descriptive language, allow flexibility

First time with this extension?
├─ YES → Very detailed instructions
└─ NO → Reference previous successful tasks

Does it require decisions?
├─ YES → Provide decision logic
└─ NO → Straightforward workflow okay
```

---

## Integration with Coordination Protocol

### Task Lifecycle

```
Desktop Claude                CLI Instance

1. Create task file     →     
   tasks/incoming/req_1050.md

2. Wait/continue work   ←     Claim task
                               Move to in_progress/

3. Continue other work  ←     Execute with BrowserMCP
                               - Navigate
                               - Click
                               - Capture output

4. Check responses      ←     Write response
                               Move to completed/

5. Read response file         
   Extract URLs/data
   Continue workflow
```

### Example Complete Flow

**Desktop → CLI:**
```markdown
# tasks/incoming/req_1050_export.md
[Detailed export instructions]
Return JSON with URLs.
```

**CLI → Desktop:**
```markdown
# tasks/responses/req_1050_response.md
{
  "new_chat": "https://claude.ai/chat/xyz",
  "exports": [...]
}
```

**Desktop uses result:**
```markdown
Navigate to new chat and continue work.
Link: [new_chat from response]
```

---

## Summary

**Instruction Level Required:** **Medium-High**

- Need specific extension names
- Need button descriptions  
- Need URLs and IDs
- Need timing hints

**Autonomy Level Available:** **Medium**

- Can navigate and click
- Can handle basic errors
- Can find elements from descriptions
- Can structure output

**Output Capture:** **✅ Works Well**

- Response files: Structured, tracked
- Codex exec: Direct stdout capture
- Both: Return URLs, file paths, structured data

**Recommendation:**

Start with **detailed instructions**, refine based on results, create **templates** for repeated tasks. Think of it like training a human intern: specific the first time, templates afterward.

---

**Related Documentation:**
- `cli_mcp_configuration.md` - MCP setup for CLI instances
- `coordination_system_v4_digest.md` - Task protocol details
- `req_1050_export_chat_example.md` - Example task file
