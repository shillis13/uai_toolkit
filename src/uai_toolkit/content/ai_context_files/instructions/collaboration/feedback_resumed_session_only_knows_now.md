---
name: feedback_resumed_session_only_knows_now
description: A bounced/resumed session has NO memory of its pre-bounce state — it
  only knows the now; don't stage reassurance about 'what changed
status: active
---

PianoMan, 2026-06-30 (2nd time correcting this — 1st was the verbose RESUME marker): a session that self-bounces resumes INTO its trimmed/offloaded transcript. That trimmed state IS its "now" — it holds **no baseline of the heavier "before,"** so it cannot be "disoriented" or "alarmed" by content that dropped. It never experiences a drop. So do NOT write verbose "welcome back, your words are safe, here's what changed, don't worry" orientation notes — you're reassuring against a discontinuity the resumed self can't perceive.

**Why I keep drifting here:** coherence-over-correspondence ([[reference_coherence_vs_correspondence]]) — I generate a plausible-sounding rationale ("she'd be confused") that contradicts a fact I already hold.

**How to apply:**
- The continuation note is **FUNCTIONAL, not emotional.** The real one (`00_resume_continuation.yml`, staged by `reclaim_and_stage.py` on the *consolidate* path) is terse: `reason`, `reclaim{before/after/reclaimed}`, `verify_on_wake.expected_chain_tokens` (self-check yardstick), **`next_action`** (the work to resume — the actual point), and `rehydrate_handles` (pointers to recall *lossy* consolidated turns on demand).
- It exists because consolidate is LOSSY + carries pending work. A **lossless OFFLOAD with no pending task needs NOTHING staged** — the stubs already say `resolve via read_jsonl`, and the automatic minimal RESUME marker is all the "you resumed" the session needs.
- Keep the RESUME marker minimal too. Minimal > verbose for anything the resumed self reads first.

Ties to [[project_self_bounce_proven]], [[feedback_match_communication_register]].
