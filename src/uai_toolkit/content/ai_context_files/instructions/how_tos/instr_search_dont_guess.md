---
name: Search for images and references instead of guessing
description: Always search the web for hardware/visual info instead of describing
  from memory — find the actual image, show it
status: active
---

When the user asks about physical hardware (button locations, port layouts, device appearance), SEARCH for the specific model's image or documentation instead of describing from memory.

**Why:** On 2026-05-25, PianoMan asked where the WPS button is on an ASUS RT-AX5400. Relay described it from memory (wrong location), then searched but found an image of a different model (RT-AX68U), then described that image as if it applied to the user's model. Three layers of wrong. Meanwhile Gemini found the correct info immediately.

**How to apply:**
1. Search for the EXACT model, not a similar one
2. Download and open the image (`open /tmp/file.png`) — Claude Code CLI can't render images inline
3. If you can't find the exact model, say so explicitly instead of substituting a different model's image
4. Never describe hardware from memory — always search first
