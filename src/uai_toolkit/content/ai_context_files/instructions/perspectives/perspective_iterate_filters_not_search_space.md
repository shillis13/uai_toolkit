---
name: iterate_filters_not_search_space
description: When filtering narrows candidates to zero, fix the filter — don't abandon
  the candidate pool
status: active
---

When a broad search produces candidates but a narrowing filter yields zero results, iterate on the filter method against the same candidates — don't pivot to searching a different location.

**Why:** User asked to find a JSONL session file. Broad keyword grep found 64 candidates. Date-filtering by first-line timestamp silently dropped files whose first line lacked a timestamp (e.g. `file-history-snapshot` metadata). Result was zero matches, and instead of questioning the filter, I abandoned the 64-file pool and started searching unrelated directories. The answer was in the original pool all along.

**How to apply:**
- If a filter over known-good candidates returns nothing, the filter is suspect — try alternative methods (file mod time, deeper content grep, file size, different metadata fields)
- Silent drops are dangerous: when a pipeline step can't extract a value, surface it as "unknown" rather than discarding the entry
- 64 content-matched candidates → 0 after date filter = the date filter is broken, not the data
