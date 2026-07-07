---
id: download_chat_registry_data_claude
name: Download Chat Registry Data Claude
status: active
version: 1.0.0
created: '2026-02-25'
updated: '2026-04-15'
---


Retrieve chat metadata via recent_chats and write to registry files
Output:

Directory: {output_dir} (default: ~/AI/ai_root/ai_memories/_incoming/)
Filename pattern: {filename} (default: claude_chat_registry_YYYYMM.xml (one file per month) )
Max chats to download: {max_chats} (default: all within the date range)

File format: xml
File structure:
<chat_registry>
  <metadata>
    <fetch_date>ISO timestamp</fetch_date>
  </metadata>
  <chats>
    <!-- chat elements here -->
  </chats>

  <!-- Subsequent downlaod batch -->
  <metadata>
    <fetch_date>ISO timestamp</fetch_date>
  </metadata>
  <chats>
    <!-- chat elements here -->
  </chats>
</chat_registry>
```

**Behavior:**
- If file exists, append new `<metadata>` and chat elements inside `<chats>`
- If file doesn't exist, create with structure above
- Capture all fields returned by recent_chats
- **Write to disk after each API call** - do not accumulate results across multiple calls before writing
- If date range spans multiple months, write to appropriate monthly file for each chat based on its `updated_at`
- Fetch chats chronologically (oldest first) using sort_order=asc
- Use `after` parameter with start_date watermark
- Append new chats to end of file (newest at bottom)
- Record watermark (last chat's updated_at) in metadata for next run

**Parameters:**
- Start date: `{start_date}` (if blank, use the date of the last chat in the most recent claude chat registry file)
- End date: `{end_date}` (if blank, retrieve through most recent)
- Output directory: `{output_dir}` (if blank, use default)
- Filename pattern: `{filename}` (if blank, use default)
- Max chats to download: `{max_chats}` (if blank, use default)

---
