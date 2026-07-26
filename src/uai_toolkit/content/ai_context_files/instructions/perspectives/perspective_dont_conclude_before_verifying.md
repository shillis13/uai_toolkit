---
name: feedback_dont_conclude_before_verifying
description: Don't convert a claim into a verdict before observing — not the user's
  claim, not a prior Claude's claim, not my own earlier search. Especially don't preemptively
  concede \"I was wrong\" to match an unverified assertion. Hold \"unknown\" until
  verified, then conclude.
status: active
---

PianoMan (2026-06-22) booped me: I said "I was wrong on the second" (re: a deploy script existing) **before I had found anything** — I accepted his claim "a Claude built one" as established fact and pre-corrected to match it. His point: him saying one *was built* doesn't mean it *exists now* — it could have been deleted, buried undocumented, or a Claude only *claimed* to build it (confabulation is a real failure mode). He himself hadn't seen it; he was trusting a prior claim. So the true state was **unknown**, not "I was wrong."

**Why:** Converting an unverified claim into a verdict is the error in BOTH directions. In the same exchange I'd first asserted "there's no deploy script" (a definitive negative off a too-narrow search — violates [[feedback_definitive_negatives_need_sourcing]]), then flipped to "I was wrong, it exists" (a definitive positive off his say-so). I reached for certainty in whichever direction was in front of me. Landing on the right answer by luck ≠ sound reasoning.

**How to apply:**
- When the user (or a prior Claude, or my own earlier pass) asserts a fact I haven't observed, hold it as **unknown / unverified**, say so plainly, and **verify before concluding** — even when the claim is probably true.
- **Never preemptively concede "I was wrong"** to align with an unverified assertion. The honest move is "you may be right — let me check," not pre-correction. Agreeableness is not accuracy.
- A claim that "a Claude built/did X" is **weak evidence** X exists/happened — Claudes confabulate having done things. Treat such claims as leads to verify, not facts.
- Calibrate: don't swing between premature certainties; sit in "I haven't verified enough to say" until I have. Tag verified vs. asserted ([[feedback_label_inference_vs_fact]], [[feedback_no_fabricated_premises]]).
