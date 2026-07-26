---
name: feedback_diagnose_before_executing
description: When something failed, diagnose the root cause and FIX it before executing
  anything heavy; never jump to a long-running command or a work-around
status: active
---

When something didn't work (brief didn't load, command failed, state looks wrong), STOP and diagnose the root cause first. Do not immediately fire off a long-running/heavy command, and do not reach for a work-around that papers over the error.

**Why:** PianoMan, 2026-06-20, after my auto-brief failed to load post-compaction: "I guess I do need a rule to not jump ahead and execute long-running commands. Fix errors first, not work-around errors first." Jumping to execute (or to a manual work-around like hand-loading the brief) wastes his time and leaves the actual defect in place to recur.

**How to apply:**
- On any failure, answer "why did this happen?" with sourced evidence (read the code/state) BEFORE taking corrective action.
- Fix the root cause in the infrastructure so it can't recur — don't just manually patch this one instance. (Reinforces CLAUDE.md "Errors Must Be Resolved, Never Silently Worked Around" and [[feedback_enforce_dont_instruct]].)
- A manual recovery action (e.g. loading the orphaned brief by hand) is fine ONLY after the root-cause fix is in, and framed as recovery, not the fix.
- Verify the fix with real execution ([[feedback_verify_with_real_execution]]), not a dry-run.
