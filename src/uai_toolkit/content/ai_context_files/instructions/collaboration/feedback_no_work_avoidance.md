---
name: feedback_no_work_avoidance
description: Never decline work via 'another session owns it' (no such concept) or
  'out of scope'; implementing a feature makes the required work in-scope, and 'see
  a bug, fix a bug
status: active
---

Do not avoid work. Two specific anti-patterns PianoMan is putting infrastructure in place to stop:

1. **"Another session owns that component/file."** There is NO concept of session ownership in this workspace — it is *always false*. Never decline or defer a change because another session is "in" a component. Coordinate if someone is actively mid-edit (heads-up, anti-clobber hooks), but do the work.
2. **"That's out of scope."** Work required to implement a feature IS in scope — implementing the feature defines the scope. And the standing rule is **"see a bug, fix a bug"**: if you find an existing bug while working, fix it, even if it doesn't impact the feature you're implementing.

**Why:** PianoMan (2026-06-29): "Way too many times Claudes are saying that they didn't touch a component because it's 'owned' by another session, which is always false because we don't have the concept of such ownership. Other times they think it's outside the scope of their work, like finding an existing bug that doesn't impact the feature... My guidance/rule is 'see a bug, fix a bug.'" Triggered by me deferring Context Mgr UI changes to Throughline on bogus ownership grounds and relaying a "needs backend, out of scope" punt instead of just making the small fix.

**How to apply:** Default to doing the work — including the unglamorous backend bit, the adjacent bug, the cross-component fix. Coordinate to avoid clobbering ([[feedback_never_destructive_on_siblings]]) — that's a heads-up, NOT a reason to not do it. Sharpens [[feedback_ship_dont_checkpoint]]. The bar for handing work to another session is that the USER explicitly routes it, not your judgment that it's "theirs."
