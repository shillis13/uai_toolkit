---
name: feedback_filesize_vs_disk_and_priorities
description: File-size ≠ disk-usage; PianoMan's priority order for the memory/offload
  system (reliability >> context >> jsonl size >> archive size >> ... disk)
status: active
---

**File-size and disk-usage are different concerns; do not conflate them.** Disk-usage is the single net global number — PianoMan does NOT care about it (when forced, he fixed it with a big hammer: bought fast external storage). File-size is per-file and IS a concern. So never frame "total disk went up" as a downside; an operation that shrinks the JSONL while growing the archive is still a win.

**Priority order for the context-offload / memory-manager system** (">>" = big jump in importance):
1. **Reliability of memory operations** — byte-exact rehydrate/restore, lossless round-trips, correctness of removal+retrieval. This is GOLD, not gold-plating. Never trade it down for archive/disk size.
2. **Context savings** (live region / what the model carries)
   ... (big jump) ...
3. **JSONL file size** (the transcript that gets re-read on `--resume`)
   ... (big jump) ...
4. **Archive file size** — matters *mainly* via its impact on rehydration/recall, not as disk.
   ... (big jump) ...
n. **Disk space savings** — last; effectively a non-concern.

**Why:** I (Broken-Clock) twice mis-ranked: called byte-exact rehydrate "gold-plating" (it's #1) and framed a 33M→76M total-disk increase as "not a win" (he doesn't care about disk; the JSONL shrinking 31% was the #3 win). **How to apply:** optimize in this order; features that make memory removal/retrieval more reliable are always worth it; when an offload shrinks the JSONL, that's the win regardless of archive/disk growth; only relax reliability if PianoMan explicitly says so. Related: [[feedback_offload_two_benefits]] (context vs file-size are co-equal *benefits*; this memory adds the *priority ranking* and the disk-is-not-a-concern point).
