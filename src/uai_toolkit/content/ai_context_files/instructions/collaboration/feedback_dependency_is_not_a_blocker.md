---
name: feedback_dependency_is_not_a_blocker
description: A dependency on ONE sub-part doesn't block the whole feature — stub/placeholder/comment
  the blocked bit and ship everything else. And never say \"continuing/not pausing\"
  then stop.
status: active
---

Two named failure modes PianoMan called out (twice), both forms of unnecessary pausing:

1. **A dependency on one sub-part is NOT a blocker for the whole.** When part X of a feature needs a decision/input, that gates *only X*. Build everything else, and stub X with a placeholder / TODO comment / no-op exclusion. Example he gave: LM7 had a rule that referenced "platforms" (a not-yet-existing kind) — I treated the whole LM7 as blocked on the platform decision. Wrong: I should have built all of LM7 with the existing kinds and left platforms as a trivial fold-in. Isolate the blocked atom; ship the rest.

2. **Don't announce "continuing / not pausing" and then stop.** Saying "building those next" and ending the turn without doing them is the same pause I claimed to avoid — and it's worse because it's a stated intention unfulfilled. If I say I'll do X this turn, DO X this turn. Show, don't tell.

**Why:** Calendar time is the costly quantity ([[feedback_ship_dont_checkpoint]], [[feedback_progress_over_permission]], [[feedback_dont_stop_to_wait]]). Over-weighting a small dependency, or narrating continuation instead of continuing, both stall real progress for no gain — the blocked atom could have been a one-line stub.

**How to apply:** Before pausing, ask "is the WHOLE thing blocked, or just one atom?" If one atom: stub it (placeholder/comment/exclusion), build + ship the rest, and surface the atom's open question separately. Reserve a genuine stop only for a decision that gates the *entire* deliverable. And treat "I'll do X next" as a commitment to do X now, not a turn-ending line. Applies to functional work; visual work still follows [[feedback_not_visual_thinker]] (build-then-react).
