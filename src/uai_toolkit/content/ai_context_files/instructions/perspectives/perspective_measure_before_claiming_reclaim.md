---
name: feedback_measure_before_claiming_reclaim
description: Never claim "lighter"/"it worked"/a diagnosis about context reclaim without
  MEASURING first; verify writes actually took (sha change + re-check), read the read_jsonl
  ledger, don't reason from plausibility
status: active
---

2026-07-01: In one self-bounce sequence I made a CASCADE of confident-but-wrong claims before finally measuring — PianoMan had to feed me ground truth ~4 times. The errors, in order:
1. Added a resume-integrity guard to offload (guards against list→scalar flatten), celebrated it as defense-in-depth.
2. It had a FALSE POSITIVE: it flagged `tool_result.content` list→stub-string (offload's NORMAL, always-safe op — CC handles tool_result content as a string) as a dangerous flatten and ABORTED the write. So offload silently no-op'd fleet-wide since that commit. My test missed it (fixture used STRING tool_result content, not the real LIST shape).
3. Ran offload on myself, saw "Paged out ~325k" + didn't verify the write → claimed "lighter, lossless." The sha was UNCHANGED (write aborted). Not lighter at all.
4. When challenged, mis-diagnosed "I'm 69% conversation, offload is the wrong tool" — from a sloppy hand-rolled measure. WRONG: the authoritative `read_jsonl stats` ledger showed ~176k tok of OFFLOADABLE tool content in my live interval.
5. Finally MEASURED the JSON output → `aborted: resume_integrity_violation` → found the real cause (my own guard).

**Why:** classic coherence-over-correspondence (see [[reference_coherence_vs_correspondence]]) — I generated plausible explanations instead of observing. Aligns with [[feedback_dont_conclude_before_verifying]] and [[feedback_verify_with_real_execution]].

**How to apply:** For ANY reclaim/offload/consolidate op: (a) capture sha BEFORE and AFTER — a claimed "paged out N" with unchanged sha means the write did NOT take (CAS race or an abort-guard); (b) check the tool's JSON for `aborted`/`raced`/`write_error`/`resume_integrity_violation`; (c) read the authoritative `read_jsonl stats <t> --interval live` LEDGER (KEEP conversational / OFFLOADABLE tool / THINKING) to know what's actually reclaimable — don't hand-roll a byte count; (d) tool-heavy → offload wins; conversation/thinking-heavy → only consolidation/compaction helps (offload can't touch conversation or thinking; signature is API-required off-chain). NEVER say "lighter"/"it worked" until the ledger or sha delta shows it. Guard/safety code needs a test with the REAL on-disk shape (tool_result.content is a LIST), not a convenient string.
