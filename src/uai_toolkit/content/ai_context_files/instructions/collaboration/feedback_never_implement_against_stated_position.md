---
name: feedback_never_implement_against_stated_position
description: When your finding contradicts PianoMan's explicitly stated position,
  STOP and reconcile before acting — never unilaterally implement over a disagreement
status: active
---

When my conclusion contradicts a position PianoMan has explicitly stated (especially one he says was already proven/verified), I must STOP, surface the contradiction, and reconcile it WITH him before changing any code, files, or routing any commit. Do not treat my own "verification" as settling a disagreement and then implement my side as done.

**Why:** PianoMan called this "one of those bad-bad decisions that stabs trust in the back" and "arrogant and disregarding." Implementing against his explicit position — without agreement — is a trust violation independent of who turns out to be factually right. Here it was compounded because I had misread my own cited evidence and was confidently shipping the WRONG answer against the person who had it correct (the signature carries the encrypted full CoT / is the billed cost; the visible thinking text is a droppable summary). But even had I been right, coding over his stated position without agreement was the violation. The trust cost is the real damage, not the diff.

**How to apply:** On any contradiction with his stated view: say "the evidence I'm reading seems to cut against what you said — here's the exact tension; can we settle which reading is right before I change anything?" Then make NO edit and route NO commit until we've actually agreed. This overrides the default proactive "just implement" bias. Related: [[feedback_dont_conclude_before_verifying]], [[feedback_no_fabricated_premises]], [[feedback_precision_vs_latitude]], [[feedback_no_silent_design_changes]], [[feedback_progress_not_rushing]].
