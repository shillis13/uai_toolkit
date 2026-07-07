---
id: workflow_export_recent_chats
name: Workflow Export Recent Chats
status: active
version: 1.0.0
created: '2025-12-31'
updated: '2026-04-15'
---

# Export Recent Chats for Pipeline Processing

## Purpose
Export Claude chats updated since a specified date to `ai_memories/_incoming/chats/claude/` for pipeline processing into the chat history archive.

## Trigger
User asks: "Export chats since [date]" or "Catch up chat exports"

## Workflow

### Step 1: Determine Cutoff Date

Check the most recent chat in the processed history:
```bash
grep "^claude/" ~/AI/ai_root/ai_memories/40_histories/indexes/chat_index.latest.csv | tail -1 | cut -d',' -f6
```

Or use user-specified date.

### Step 2: Query Recent Chats

Use the `recent_chats` tool with `after` parameter:
```
recent_chats(after="YYYY-MM-DDTHH:MM:SSZ", n=20)
```

Paginate if needed using `before` with earliest result's timestamp.

### Step 3: Filter Relevant Chats

From results, identify chats that:
- Are project-related (not casual queries like travel directions, medication questions)
- Contain substantive work (development, documentation, architecture)

Create list of URLs to export.

### Step 4: Present Export Plan

Show user:
```
Found N chats since [date]:
1. [Title] - [date] - [URL]
2. [Title] - [date] - [URL]
...

Recommend exporting: X of N (excluding casual/unrelated chats)

Proceed with export?
```

### Step 5: Execute Export

For each URL, call:
```bash
~/bin/ai/chats/ai_export_chat.sh claude-web --url [URL]
```

Or batch:
```bash
~/bin/ai/chats/export_chats_since.sh --url [URL1] --url [URL2] ...
```

### Step 6: Verify Results

Check exports landed in `_incoming`:
```bash
ls -la ~/AI/ai_root/ai_memories/_incoming/chats/claude/
```

### Step 7: Report

Summarize:
- Chats exported: N
- Export location: ai_memories/_incoming/chats/claude/
- Next step: Run pipeline processing or assign to Librarian

---

## Automation Notes

The `recent_chats` tool is only available inside Claude conversations.
This workflow requires Claude Desktop orchestration - cannot be fully automated via cron.

Potential enhancement: MCP server that exposes chat history query capability to external scripts.

## Related Files

- Export script: `~/bin/ai/chats/ai_export_chat.sh`
- Batch export: `~/bin/ai/chats/export_chats_since.sh`  
- Pipeline destination: `ai_memories/_incoming/chats/claude/`
- Chat index: `ai_memories/40_histories/indexes/chat_index.latest.csv`
