---
name: feedback_match_communication_register
description: For UX/feature/visual requests, talk about user-facing behavior — never
  dump low-level implementation details (hex, ANSI codes, internal symbols, coined
  jargon) the user shouldn't need
status: active
---

Match the communication register to the conversation. For **visual / UX / feature** requests, describe the **user-facing observation and the user-facing change** — not the mechanism. Do NOT surface low-level implementation details the user neither asked for nor needs: hex color values, ANSI code numbers, internal function/file/variable names, or invented jargon. They add cognitive load, obscure the actual point, and signal I'm thinking about my code instead of the user's experience.

**Why:** PianoMan reacted strongly ("Whaaa? Why are these details here?") when, in a UX discussion, I wrote "ANSI magenta (35/95) → #bb9af7, same as Thinking… remap so 'code purple' ≠ 'thinking purple'." The real point was trivially simple — *"some text shows up in the same purple as Thinking blocks; want them different?"* The jargon ("code purple", code numbers) made a one-sentence idea unintelligible.

**How to apply:**
- Lead with what the user sees and what will change for them. Keep hex/codes/symbols out of UX/feature replies.
- A fix proposal = "here's the visible problem, here's the visible result," not the wiring.
- **Nuance (context-dependent):** this is about register, not a blanket ban. When PianoMan is actively debugging, doing architecture, or has explicitly engaged on the technical mechanism (e.g., the Memorex verb-line/marker work), deep detail is wanted and correct. The rule is: don't drag implementation internals into a conversation that's operating at the experience level.

Relates to [[feedback_stop_at_technical_answer]], [[feedback_define_terms_before_use]].
