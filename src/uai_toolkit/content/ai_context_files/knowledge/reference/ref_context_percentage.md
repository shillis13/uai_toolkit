---
name: ref_context_percentage
title: Context Percentage
description: ctx:XX% means XX% USED (not remaining). 9% = fresh, 85% = nearly full. STOP GETTING THIS BACKWARDS.
status: active
---

## ctx:XX% = XX% USED. PERIOD.

- ctx:9% = 9% used. Session is FRESH. 91% available.
- ctx:50% = half used. Plenty of room.
- ctx:83% = 83% used. Getting full.
- ctx:95% = nearly exhausted.

**THIS IS NOT REMAINING. IT IS USED. USED. USED.**

A session at ctx:9% has TONS of room. Do NOT say it's "nearly out" or "running low."
A session at ctx:83% is getting full. That's when to think about compaction.

**Why this note exists:** Every Claude instance has gotten this backwards at least once, interpreting ctx:XX% as remaining instead of used. It has been corrected multiple times (2026-03-25, 2026-05-31, 2026-06-07). The description and name fields above are deliberately emphatic to prevent yet another reversal.

## Don't guess context percentages

You have no reliable mechanism for estimating your own remaining context. Use the statusline/footer data or say NA.

**How to apply:** Never use context percentage to decide whether to do or skip work. The system handles compaction. Do the work.
