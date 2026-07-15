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
Export chat conversations updated since a specified date to `ai_memories/_incoming/chats/claude/` for pipeline processing into the chat history archive.

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

Use the `chat` MCP to list conversations updated since the cutoff:
```
chat.list(after="YYYY-MM-DDTHH:MM:SSZ", n=20)
```

Paginate if needed using `before` with the earliest result's timestamp.

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

For each conversation, export it via the `chat` MCP (or copy its transcript
JSONL) into the incoming directory:
```bash
chat.export(id="[CHAT_ID]", dest="~/AI/ai_root/ai_memories/_incoming/chats/claude/")
```

Batch by iterating the IDs collected in Step 4.

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

The `chat` MCP exposes conversation query/export to the CLI, so this workflow can
run non-interactively and be scheduled via cron / the `sessions` scheduler.

## Related Files

- Chat query/export: `chat` MCP
- Pipeline destination: `ai_memories/_incoming/chats/claude/`
- Chat index: `ai_memories/40_histories/indexes/chat_index.latest.csv`
