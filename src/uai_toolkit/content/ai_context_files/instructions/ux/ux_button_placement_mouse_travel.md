---
name: feedback_button_placement_mouse_travel
description: UI button placement — minimize mouse travel; \"next to X\" means X stays
  put, don't relocate the pair
status: active
---

PianoMan's button-placement rules (2026-07-18):

1. **Minimize the distance the mouse has to travel.** Don't shove action buttons to a far edge (e.g. `marginLeft:auto` right-align) when they can sit near what the user is already interacting with (e.g. inline right after the tab row).
2. **"Put button A next to button B" means B stays put — only A moves to it.** Do NOT relocate the pair. When he asked to place [＋New] next to [Reindex], I (via a subagent) moved BOTH into a new right-aligned group — a change he never requested. He caught it and asked why.

**Meta-lesson:** review a delegated subagent's ACTUAL diff before building/deploying — it can introduce unrequested changes (here, right-aligning the group). Don't ship what you didn't verify.

**How to apply:** place buttons to minimize travel; honor "next to" literally (anchor stays, mover moves); group pane-level actions logically and keep layouts stable. Ties to [[feedback_human_ui_polish]] (group logically, stable layouts) and [[feedback_no_silent_design_changes]].
