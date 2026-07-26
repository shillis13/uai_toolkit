---
name: atrun needs Full Disk Access for at jobs to work
description: macOS at jobs fail with "Operation not permitted" unless /usr/libexec/atrun
  has Full Disk Access in System Settings
status: active
---

macOS `at` jobs (used by `schedule_future_prompt` / `schedule_prompt.py`) fail silently with "Operation not permitted" when trying to execute scripts.

**Fix:** Add `/usr/libexec/atrun` to System Settings → Privacy & Security → Full Disk Access. PianoMan also added it to Accessibility and Automation for good measure.

**Details:**
- Binary: `/usr/libexec/atrun`
- Managed by: `/System/Library/LaunchDaemons/com.apple.atrun.plist` (runs every 30 seconds)
- The at jobs queue and fire correctly — it's the script execution that fails
- Log evidence: `ai_general/logs/scheduled_prompts/{tag}.log` shows "Operation not permitted"
- Resolved: 2026-05-06, confirmed working with test job

**Symptoms:** scheduled prompts never arrive, at queue shows empty (jobs fired but failed), no error visible except in the log files.
