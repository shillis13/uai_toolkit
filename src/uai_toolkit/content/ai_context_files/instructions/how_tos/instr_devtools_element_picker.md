---
name: Use DevTools element picker early for visual bugs
description: When a visual rendering issue occurs, use the browser/Electron DevTools
  element picker FIRST before analyzing data streams, escape sequences, or rendering
  pipelines.
status: active
---

When debugging visual rendering issues in Electron/web apps, use the DevTools element picker (Cmd+Option+I → click element picker → click on the problem) IMMEDIATELY. Don't spend time analyzing data streams, escape sequences, font rendering, or terminal protocols.

**Why:** A WWWWW rendering bug in xterm.js took hours of debugging PTY data, OSC 8 sequences, Unicode character widths, canvas addons, zellij configs, and multiple deploys. The element picker revealed in 10 seconds that it was `xterm-char-measure-element` — an internal measurement span that was visible due to a missing CSS rule.

**How to apply:** For ANY visual bug (wrong text, misaligned elements, phantom content, garbled rendering):
1. Open DevTools (Cmd+Option+I)
2. Use element picker to click on the problematic visual element
3. Read the element's tag, class, and computed styles
4. Fix from there — don't theorize about data pipelines first
