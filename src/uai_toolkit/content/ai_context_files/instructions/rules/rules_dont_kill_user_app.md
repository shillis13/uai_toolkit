---
name: feedback_dont_kill_user_app
description: Never kill the user's running UAI app — start a separate instance for
  testing
status: active
---

Never `pkill` or kill the user's running UAI app instance. For testing, launch a separate copy (different port, different user-data-dir, or use the build output directly) instead of killing and relaunching the deployed app.

**Why:** The user is actively using the app. Killing it to test is disruptive.

**How to apply:** When building and testing:
1. Build with `electron-forge package` as usual
2. Deploy to the deploy dir as usual (user will restart when ready)
3. For automated tests, launch the built app from `app/out/` directly with a different CDP port, or run tests against the user's already-running instance without killing it
4. Never run `pkill -f "unified-ai-interface"` — that's the user's decision
