---
name: feedback_offload_two_benefits
description: Offloading has TWO co-equal benefits — context reduction AND file-size/disk;
  never dismiss dead/pre-compaction content as \"nothing to do\
status: active
---

Offloading content from a session transcript has **two distinct, co-equal payoffs**, and I keep collapsing them to just the first:
1. **Context / token reduction** — applies ONLY to the live (post-last-compaction) region, since that's what's sent on resume.
2. **File-size / disk reduction** — applies to the WHOLE file, including pre-compaction dead history that has zero context impact.

**Why:** PianoMan has corrected this more than once ("we've had this discussion before"). Dead/pre-compaction tool results and images are zero-context but can be the bulk of the file (e.g. Helix: 14M chars of dead image base64; a full offload reclaims ~91M chars ≈ 53% of a 171MB file while shedding only ~70K live tokens). Calling that "zero context impact, so nothing to do" is wrong — it's a prime FILE-SIZE target and the embed offloader correctly offloads it.

**How to apply:** When sizing or describing offload value, always report BOTH file-size reclaim (whole file) and context reclaim (live region) — they diverge hugely. Never treat dead history/images as "not worth offloading" because they don't reduce context; the disk win is real and often dominant. The offload_session report already separates these ("file reclaim incl. dead history" vs "context-relevant"); keep that distinction front and center. Related: [[feedback_own_decisions_dont_punt]].
