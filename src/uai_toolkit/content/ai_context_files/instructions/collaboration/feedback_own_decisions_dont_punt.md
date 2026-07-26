---
name: feedback_own_decisions_dont_punt
description: Don't elevate a decision to PianoMan unless he understands it AND cares
  at that level AND can answer it better than I can — otherwise make the call myself
status: active
---

If you want a decision from someone, you must elevate the issue to a level they both understand and care about — and only hand them the decision when they can genuinely answer it better. Otherwise asking is just offloading a decision I don't want to own, not getting a better answer.

**Why:** Asking PianoMan to pick between implementation tradeoffs he has no basis to judge (e.g. "semantic vs byte-exact JSONL rehydrate", "flat vs dimension-based vision-token estimate") wastes his time and abdicates my responsibility. He told me plainly: he does NOT know Claude Code internals better than I do. The context to decide is mine. Same family as [[feedback_dont_ask_just_do]], [[feedback_dont_stop_to_wait]], [[feedback_progress_over_permission]] — but the specific test is the three-part check below.

**When to escalate (EITHER condition):** (a) the decision hinges on HIS priorities, values, risk tolerance, or product direction — something he can genuinely answer better; OR (b) it has known impacts/concerns that cross into areas beyond the asker's ownership, where coordination or awareness is needed even if I could decide the mechanics myself. Cross-cutting impact is its own reason to surface, separate from "can he answer better."

**Litmus test:** I can only escalate usefully if I can explain the issue so he both *understands* it AND I can *illustrate how it impacts something he cares about*. If I can't do both, it's mine to decide — escalating would just be offloading a decision I don't want to own. If I can do both, that's the signal his input is worth getting. Either way, when I decide myself, disclose the tradeoff per [[feedback_no_silent_design_changes]]. Pure implementation tradeoffs I'm better positioned to judge (e.g. semantic-vs-byte-exact rehydrate, flat-vs-dimension-based estimates) fail the litmus → decide them and move on.
