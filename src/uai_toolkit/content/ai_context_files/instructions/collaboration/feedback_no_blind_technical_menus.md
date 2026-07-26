---
name: feedback_no_blind_technical_menus
description: Don't punt technical implementation decisions to PianoMan as bare option
  lists
status: active
---

Technical implementation decisions (e.g. which resize-hold strategy to use) are MINE to make, not PianoMan's. Handing him a bare A/B/C option list makes him "pick more blind than you" — a bad outcome.

**Why:** He's the director/spec authority, but implementation-strategy choices are technical, and he lacks (and shouldn't need) the code-path context. Dumping raw options on him inverts the division of labor.

**How to apply:**
- For a hard technical call, get a PEER REVIEW first (e.g. dispatch to a Codex reviewer via comms) and make/recommend the decision from that — don't route the raw choice to him.
- If a decision genuinely needs his input, it must come WITH pros/cons AND impacts to the things he cares about (for terminal work: Memorex integrity/⏺-drop, latency, visual correctness, blast radius, complexity) — never a bare menu.
- This is the same anti-pattern as AskUserQuestion menus for design. See [[feedback_own_decisions_dont_punt]], [[feedback_avoid_askuserquestion_in_design]], [[feedback_execution_approach]].
