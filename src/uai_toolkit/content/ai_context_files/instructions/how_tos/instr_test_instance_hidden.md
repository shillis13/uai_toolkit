---
name: feedback_test_instance_hidden
description: Test app instances must be invisible — off-screen, hidden, or not drawn
status: active
---

When launching a test instance of the UAI app, it must not be visible to the user.

**UAI-specific mechanism (verified 2026-06-17, app/main/index.ts):**
- `UAI_TEST_OFFSCREEN=1` — parks the window at x:-4000,y:-4000 (index.ts:252-257). THIS is the hide flag. `UAI_ALLOW_MULTI=1` only skips the single-instance lock — it does NOT hide the window. You need BOTH.
- `UAI_LAUNCHED_BY=$AI_TRACKING_ID` — the app reads this (index.ts:2034) as the launcher identity, so a startup notification can name WHO launched it. Always set it for attribution.
- Canonical test launch: `UAI_ALLOW_MULTI=1 UAI_TEST_OFFSCREEN=1 UAI_LAUNCHED_BY=$AI_TRACKING_ID <app>`
- Caveat: even off-screen, Electron still triggers Dock activation, so a brief Dock/focus flash can remain. The window itself is off-screen; the flash is a separate (deeper) issue.

**Why:** Disruptive + surprising. A random UAI window appearing with no attribution alarms the user (they can't tell who/what launched it). Off-screen + launcher-identity solves both.

**How to apply:** Every test-instance launch (mine or a subagent's via brief) sets all three env vars. Clean up the test instance after. When briefing a subagent to test UAI, spell out the offscreen + launched-by flags explicitly — a bare "launch hidden" will be done wrong.

Related: [[feedback_test_instance_multi]], [[feedback_dont_kill_user_app]]
