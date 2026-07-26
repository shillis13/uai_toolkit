---
name: Test after every change
description: Always verify the app renders and basic functionality works after code
  changes — don't just check compilation
status: active
---

After every code change to the board app, verify it actually works — not just that it compiles.

**Why:** User reported the board was broken (blank/black screen) across 4-5 messages. The root cause was a simple variable-used-before-declaration error that `tsc --noEmit` would have caught, but I only ran `vite build` (which is more lenient). Even after the user explicitly asked me to test, I initially only checked via Chrome Control instead of running `tsc --noEmit` first.

**How to apply:**
1. Run `npx tsc --noEmit` after every edit — grep output for changed filenames specifically
2. After fixing TS errors, reload the board tab and verify canvas renders (hasCanvas, canvasSize, rootChildren)
3. Never tell the user "ready to test" until both checks pass
4. If the user reports something is broken, check for compile/runtime errors FIRST before theorizing about race conditions or closure bugs
