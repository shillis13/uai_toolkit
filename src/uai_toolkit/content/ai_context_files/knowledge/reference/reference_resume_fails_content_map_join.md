---
name: reference_resume_fails_content_map_join
description: 'Claude Code \"Failed to resume: _.content.map/K.join is not a function\"
  means a list-typed field in the transcript was flattened to a string — usually by
  the offload/reclaim tooling; how to diagnose and fix'
status: active
---

**Symptom:** `claude --resume <uuid>` dies immediately with `Failed to resume session: _.content.map is not a function` (or `K.join is not a function. (In 'K.join(\`\n\n\`)')`). The session is otherwise intact.

**Root cause:** somewhere in the JSONL a value that CC expects to be a **list** is a **string**. CC does `content.map(...)` / `parts.join('\n\n')` over it during reconstruction. The usual culprit is our own context-reclaim tooling (`ai_general/scripts/jsonl/offload_tool_results.py --stub-attachments`) replacing a list-typed `attachment.<key>` payload with a bare string stub. List-typed attachment fields that CC maps/joins on resume: `deferred_tools_delta.{addedNames,removedNames,readdedNames,addedLines}`, `mcp_instructions_delta.addedBlocks`, `agent_listing_delta.addedLines`, `hook_additional_context.content`. (String-typed and therefore safe to stub bare: `skill_listing.content` — 235 str / 0 list across the fleet, don't "fix" it.)

**Fixed 2026-07-01** in offload: stub is now shape-preserving (`att[key] = [stub] if isinstance(val, list) else stub`). Corrupted the Tideline session (`b71cdb5f`) during BC's dynamic-consolidation test; only that session was affected (`--stub-attachments` is opt-in, default off). See [[reference_messaging_backtick_shell_eval]] for the sibling "reclaim tooling silently corrupts" class.

**Diagnostic method that worked (and traps to avoid):**
- Reproduce headlessly: `claude --resume <uuid> -p "hi" < /dev/null` prints the exact error.
- **Don't trust head-N truncation bisect** for this — truncating changes which leaf CC picks as active, so the "first bad line" is a moving artifact, not the corrupt record.
- **Do** anomaly-detect instead: for each `(attachment.type, field)`, tally `type(value)` across the whole file; a field that is *mixed* str/list is the smoking gun (the str ones are offload stubs). Confirm the str values start with `[attachment archived:`.
- A field uniformly offloaded in one file won't show as "mixed" — cross-check its natural type against other transcripts in `~/.claude/projects/*/*.jsonl` before deciding it's corrupt.
- **Repair minimally & byte-faithfully:** wrap only the genuinely-list stubs `str -> [str]`, rewrite ONLY the changed lines (passthrough others verbatim), back up co-located as `<uuid>.CORRUPT_pre_repair_<date>.jsonl.bak` (`.jsonl.bak` so CC doesn't scan it as a phantom session). `--rehydrate` still restores the exact original from the archive body. Verify by resuming the real id, then strip the test-turn the verification appended.
- `--resume` **appends** to the transcript it opens and CC **scans every bare-`<uuid>.jsonl`** in the projects dir as a session — so use non-uuid temp names for scratch copies and clean them up.
