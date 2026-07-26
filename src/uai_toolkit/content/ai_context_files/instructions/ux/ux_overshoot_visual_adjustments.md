---
name: feedback_overshoot_visual_adjustments
description: When adjusting visual attributes (size/color/brightness/position), make
  the FIRST adjustment deliberately too big, not too little
status: active
---

When adjusting any visual attribute (size, color, brightness, spacing, position/location), the first adjustment should deliberately **overshoot** — larger than the estimated "right" value — rather than undershoot.

**Why:** Claude knows visual attributes numerically but does not experience them; it maps quantities to generalized, theoretical human reactions learned from training (color theory, UX studies) and cannot account for the user's actual conditions (monitor brightness, room lighting, individual perception). Claude's adjustments skew too-small. An undershoot risks being imperceptible → the user concludes no change was made or the wrong thing was changed → a full round-trip is wasted and confidence drops. An overshoot is unmistakably visible → it confirms the correct attribute was changed, confirms direction, and gives a wide bracket to binary-search toward the Goldilocks value in fewer iterations. Undershoot is the expensive choice, not the safe one.

**How to apply:**
- First adjustment: push clearly past the estimate (roughly ~2x the change you think is right) — enough to be unmistakable.
- Always state the numeric before→after so the user can calibrate the next correction (this is a deliberate binary search; they need the bounds).
- Then converge: once the user can see it, correct back down toward the target.
- The user's eyes are ground truth; an overshoot is self-verifying through them. One visible-but-too-much probe beats a round-trip wasted on an invisible change.
- Bound by reversibility, not caution: visual tweaks are trivially undone, so overshoot freely. Only avoid overshooting changes that are genuinely hard to revert.

Relates to [[feedback_verify_with_real_execution]] — Claude can't self-verify visual output, so the user is the only ground truth.
