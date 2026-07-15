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
- Source transcript: the active session's conversation JSONL (or a path supplied by the user)

### Capabilities
- Bash filesystem access (Claude Code / Codex CLI)
- `chat` MCP (locate/read source conversations) - optional

---

## Workflow Steps

### Step 1: Identify Source Chat

If current session: use the active session's transcript path (the CLI records the
conversation JSONL under the session data directory).

If a different chat: the user provides the path/ID, or use the `chat` MCP to
locate it.

### Step 2: Export Chat History

```bash
EXPORT_FILE="$HOME/AI/ai_root/ai_claude/work/chat_exports/$(date +%Y%m%d_%H%M%S)_export.json"
cp "$SOURCE_TRANSCRIPT" "$EXPORT_FILE"
```

Output: JSON/JSONL file copied into the working directory for processing.

### Step 3: Condense the Export

**Option A: Self-condense (same Claude instance)**
Load the export and apply the condensation prompt directly.

**Option B: Delegate to CLI worker**
```bash
~/AI/ai_root/ai_general/scripts/cli/claudeCli --display-name condense_$(date +%H%M%S) \
  "Condense the chat export at $EXPORT_FILE following the guidelines in ~/AI/ai_root/ai_general/ai_context_files/methods/_archive_condensation/prompt_condense_chat_history.md. Save result to ~/AI/ai_root/ai_claude/work/chat_exports/condensed_$(date +%Y%m%d_%H%M%S).md"
```

### Step 4: Create Continuation Seed

Populate the continuation template:
```bash
CONDENSED_FILE="[path to condensed output]"
SEED_FILE="$HOME/AI/ai_root/ai_claude/work/chat_exports/continuation_seed_$(date +%Y%m%d_%H%M%S).md"
FEEDBACK_FILE="$HOME/AI/ai_root/ai_comms/announcements/feedback_req_$(date +%Y%m%d_%H%M%S).md"

# Read template, substitute placeholders, write seed
```

### Step 5: Create New Session

Launch a fresh CLI session for the continuation (e.g. via the `sessions` MCP or
your launcher). The new session starts empty and will be seeded with the
condensed history in the next step.

### Step 6: Attach Condensed History

Pass the condensed file and continuation seed to the new session directly on
disk — the CLI has full filesystem access, so the seed prompt can reference the
condensed file by absolute path, or its contents can be inlined into the initial
prompt.

### Step 7: Submit Continuation Prompt

Deliver the continuation seed template with placeholders filled:
- `{{CONDENSED_HISTORY}}` → content of condensed file
- `{{CONTEXT_DIGEST}}` → optional additional context
- `{{FEEDBACK_FILE_PATH}}` → path to feedback request file

### Step 8: Verify and Monitor

- Confirm new chat acknowledges the context
- After ~5 exchanges, remind about feedback checkpoint
- Collect feedback in the announcement file

---

## Quick Command

When asked to continue a chat, run this sequence:
1. `chat` MCP to find the conversation (if not current)
2. Copy the transcript to the working directory
3. Condense (delegate to a CLI worker or self-process)
4. Launch a new session with seed attached
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

**Export fails**: Confirm the source transcript path exists and is readable
**Condensation too large**: Increase compression, focus on outcomes not process
**New session doesn't pick up context**: Verify seed template is properly formatted
