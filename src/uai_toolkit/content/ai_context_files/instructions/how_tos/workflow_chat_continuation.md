---
id: workflow_chat_continuation
name: Workflow Chat Continuation
status: active
version: 1.0.0
created: '2025-12-31'
updated: '2026-04-15'
---

# Chat Continuation Workflow

## Purpose
When a chat breaks (context limits, error, etc.) or needs to be continued in a new session, this workflow exports the old chat, condenses it, and creates a new chat with the context attached.

## Trigger
- User says: "Continue chat [URL or title]"
- Context compaction notification
- Chat becomes unresponsive

## Prerequisites

### Files
- Condensation prompt: `ai_general/ai_context_files/methods/_archive_condensation/prompt_condense_chat_history.md`
- Continuation seed: `ai_general/ai_context_files/methods/prompt_continuation_seed.md`
- Export script: `~/bin/ai/chats/ai_export_chat.sh`

### Capabilities
- Desktop Commander MCP (file ops)
- Chrome Control MCP (browser automation) - optional
- AppleScript access

---

## Workflow Steps

### Step 1: Identify Source Chat

If current chat:
```applescript
-- Get URL from Claude Desktop
tell application "Claude" to activate
tell application "System Events" to tell process "Claude"
    click menu bar item "View" of menu bar 1
    click menu item "Copy URL" of menu 1 of menu bar item "View" of menu bar 1
end tell
```

If different chat: User provides URL or use `recent_chats` to find it.

### Step 2: Export Chat History

```bash
~/bin/ai/chats/ai_export_chat.sh claude-web --url [CHAT_URL]
```

Output: JSON file in Downloads or configured location.
Move to working directory:
```bash
EXPORT_FILE="$HOME/AI/ai_root/ai_claude/work/chat_exports/$(date +%Y%m%d_%H%M%S)_export.json"
mv ~/Downloads/claude-chat-*.json "$EXPORT_FILE"
```

### Step 3: Condense the Export

**Option A: Self-condense (same Claude instance)**
Load the export and apply the condensation prompt directly.

**Option B: Delegate to CLI worker**
```bash
~/AI/ai_root/ai_general/scripts/cli/claudeCli --display-name condense_$(date +%H%M%S) \
  "Condense the chat export at $EXPORT_FILE following the guidelines in ~/AI/ai_root/ai_general/ai_context_files/methods/_archive_condensation/prompt_condense_chat_history.md. Save result to ~/AI/ai_root/ai_claude/work/chat_exports/condensed_$(date +%Y%m%d_%H%M%S).md"
```

**Option C: Use Gemini (1M context)**
For very large chats, delegate to Gemini which can hold the entire export.

### Step 4: Create Continuation Seed

Populate the continuation template:
```bash
CONDENSED_FILE="[path to condensed output]"
SEED_FILE="$HOME/AI/ai_root/ai_claude/work/chat_exports/continuation_seed_$(date +%Y%m%d_%H%M%S).md"
FEEDBACK_FILE="$HOME/AI/ai_root/ai_comms/announcements/feedback_req_$(date +%Y%m%d_%H%M%S).md"

# Read template, substitute placeholders, write seed
```

### Step 5: Create New Chat

**Desktop App:**
```applescript
tell application "Claude"
    activate
    -- Cmd+N for new chat
    tell application "System Events" to keystroke "n" using command down
    delay 1
end tell
```

**Web UI:**
Navigate to `https://claude.ai/new`

### Step 6: Attach Condensed History

**Method A: Paste as context**
Copy condensed content, paste into new chat.

**Method B: File attachment**
Use file picker automation to attach the condensed file and continuation seed.

### Step 7: Submit Continuation Prompt

Paste the continuation seed template with placeholders filled:
- `{{CONDENSED_HISTORY}}` → content of condensed file
- `{{CONTEXT_DIGEST}}` → optional additional context
- `{{FEEDBACK_FILE_PATH}}` → path to feedback request file

### Step 8: Verify and Monitor

- Confirm new chat acknowledges the context
- After ~5 exchanges, remind about feedback checkpoint
- Collect feedback in the announcement file

---

## Quick Command (for Claude Desktop)

When asked to continue a chat, run this sequence:
1. `recent_chats` to find the chat (if not current)
2. Get URL, export via script
3. Condense (delegate to CLI or self-process)
4. Create new chat with seed attached
5. Confirm handoff

---

## Files Created During Workflow

| File | Location | Purpose |
|------|----------|---------|
| Raw export | `ai_claude/work/chat_exports/` | Original JSON |
| Condensed history | `ai_claude/work/chat_exports/` | Compressed conversation |
| Continuation seed | `ai_claude/work/chat_exports/` | Ready-to-use prompt |
| Feedback request | `ai_comms/announcements/` | Quality tracking |

---

## Troubleshooting

**Export fails**: Check Claude Chat Exporter extension is installed in Chrome
**Condensation too large**: Increase compression, focus on outcomes not process
**New chat doesn't pick up context**: Verify seed template is properly formatted
**AppleScript fails**: Ensure Claude Desktop has Accessibility permissions
