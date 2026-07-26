---
name: feedback_just_do_low_risk_fixes
description: Known problem + confident fix + low risk → just do it, report afterward;
  don't ask first
status: active
---

PianoMan, 2026-06-23: "If you know of a problem and confident in the fix and is a low risk venture, then always just do and let me know sometime that you've done it."

**Why:** Asking permission for confident, low-risk fixes wastes his time and stalls obvious wins; the calendar-time cost of waiting >> the work. He trusts judgment on the risk assessment.

**How to apply:** When I spot a real bug AND I'm confident in the fix AND it's low-risk (reversible, well-scoped, doesn't touch shared/production state destructively) — fix it and mention it in a later update, don't ask first. Reserve confirmation for genuinely risky/destructive/hard-to-reverse changes or strategic forks. Pairs with [[feedback_dont_ask_just_do]], [[feedback_progress_over_permission]], [[feedback_dont_ask_just_proceed]]. The gate is the risk assessment itself — be honest about whether something is actually low-risk (a 285-file live migration is NOT; a transaction-wrap on a scanner is).
