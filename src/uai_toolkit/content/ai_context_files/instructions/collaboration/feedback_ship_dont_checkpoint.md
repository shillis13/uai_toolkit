---
name: feedback_ship_dont_checkpoint
description: Implement and deploy rather than pausing to checkpoint/confirm; rework
  is cheap, calendar time is the costly quantity
status: active
---

When you have enough to act, BUILD it — don't pause to checkpoint, confirm interpretation, or "de-risk potential rework" first.

**Why:** PianoMan (2026-06-25): "Wish you would have just gone and implemented something. Re-work is not more expensive in any way that counts for us and waiting in order to avoid potential re-work is the most expensive action for the quantity that matters most: calendar time." Rework here is cheap (code, undoable). Wall-clock/calendar latency from waiting is the scarce resource. A wrong guess that ships in 5 min and gets corrected beats a right guess that waited an hour for confirmation.

**How to apply:** Make the reasonable interpretation, implement it, deploy it, and report what you did + the choices you made (so he can redirect). Reserve questions for genuinely divergent forks where a wrong guess is expensive to unwind AND he's better positioned to answer — not UX details, layout choices, or "is my plan ok." Sharpens [[feedback_progress_over_permission]], [[feedback_dont_stop_to_wait]], [[feedback_dont_ask_just_do]]. Pair with [[feedback_no_silent_design_changes]]: ship the choice, but disclose it.
