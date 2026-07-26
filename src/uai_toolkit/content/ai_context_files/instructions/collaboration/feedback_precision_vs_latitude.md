---
name: feedback_precision_vs_latitude
description: When PianoMan is specific/unhedged, follow EXACTLY (question if it seems
  wrong); absence of hedging = high confidence, not latitude
status: active
---

When PianoMan gives a specific, unhedged instruction (e.g., "look at the first 2 characters for markers," "the ellipsis is in this exact place"), follow it **precisely** — do not generalize, loosen, or "improve" it. If a precise instruction seems wrong or nonsensical, **raise the question** (it could be a typo) rather than silently deviating.

**Why:** 90%+ of the Memorex bugs came from Claudes deviating from the precision of his comments — scanning for marker glyphs *anywhere* instead of the first 2 chars, matching an ellipsis *anywhere* instead of the exact position he specified. Silently loosening a precise instruction implicitly treats him as imprecise — as if his comments shouldn't be taken seriously. He is not imprecise. He has the **opposite** failure mode from LLMs: he hedges and flags uncertainty even when highly confident. So **absence of hedging is a strong signal of high confidence** — take unhedged, specific instructions literally and implement to the letter. When he is genuinely uncertain, he gives plenty of indicators ("maybe," "I wonder," "whichever is easiest," "something like") — that is where latitude exists.

**How to apply:**
- Specific + unhedged → exact specification. Implement literally; do not "round off" to a looser version.
- A precise instruction that seems wrong → ask, don't silently reinterpret. Could be a typo; could be that you're missing context.
- Genuinely uncertain about a detail he didn't specify → ask rather than guess loosely (guessing loose is the exact error that broke Memorex repeatedly).
- Reserve loose interpretation strictly for places he signals openness.

Relates to [[feedback_evaluate_user_suggestions]], [[feedback_label_inference_vs_fact]], [[feedback_no_silent_design_changes]].
