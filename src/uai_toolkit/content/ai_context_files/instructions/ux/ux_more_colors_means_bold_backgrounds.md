---
name: feedback_more_colors_means_bold_backgrounds
description: When PianoMan says \"more colors,\" he means saturated, visibly-different
  BACKGROUND colors per region (squint test = obviously different colored blocks)
  — NOT subtle tints/accents on a near-black field. He repeatedly rejects near-monochrome
  UIs; honor this aggressively.
status: active
---

PianoMan has asked for "more colors" many times and I keep failing him. The failure mode: I treat "more colors" as *accent colors on text/borders/badges over near-black backgrounds* (e.g. `rgba(hue, 0.05)` tints) — which keeps the large surfaces ~monochrome, exactly what he's reacting against. He's escalated to "I will soon start rejecting designs outright that use nearly mono-chromatic background coloring."

**Why:** A 5–8% color tint on `#0e0e12` is still black to the eye. The *field* — the big background areas — is what reads as monochrome. Coloring only text/borders doesn't change that.

**How to apply (the operational reframe that actually produces color):**
- **Color the large surfaces, not just the accents.** Each functional region gets a **distinct, saturated background hue** — real colors (e.g. an actual indigo `#1b2550`, green `#1c3a2a`, warm `#2d2016`), not near-black with a tint.
- **Squint test:** blur your eyes — you must see *obviously different colored blocks*, not one dark field. If it still looks monochrome squinted, it's wrong.
- **Overshoot** (see [[feedback_overshoot_visual_adjustments]]): start bolder/more saturated than feels comfortable, then dial back — never start subtle.
- Encode function/type/status/identity in **prominent** color all over (zone backgrounds, section headers, signature colors per aspect), not one accent hue.
- When unsure if it's "enough," it isn't — add more. He will tell me if it's too much; he has never said "too colorful."
