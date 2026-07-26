---
name: feedback_build_after_every_change
description: UAI app must be built+deployed after completing each feature/fix/batch
  — not per-file, but per-completion
status: active
---

Every completed unit of UAI work (feature, fix, or batch of related changes) must be built and deployed before telling the user it's done. The granularity is per-completion, not per-file — implementing a fix that touches 5 files gets one build at the end, not five.

**Why:** The user runs the deployed app. Code changes that aren't built and deployed don't exist from their perspective. "I finished that" without a build is a lie.

**How to apply:** When you're about to tell the user work is complete:
1. TypeScript check
2. Version bump
3. Build (`electron-forge package`)
4. Deploy via `rsync -a --delete src.app/ dest.app/` to `ai_general/apps/unified_ai_ui/UnifiedAI.app/` — do NOT use `cp` (aliased to `cp -i`, hangs) and do NOT kill the running app
5. Report the version number and tell user to restart at their convenience

Do NOT end a response with "this will be in the next build" or defer the build indefinitely. Never kill the user's running app instance — just overwrite the install location and inform them.
