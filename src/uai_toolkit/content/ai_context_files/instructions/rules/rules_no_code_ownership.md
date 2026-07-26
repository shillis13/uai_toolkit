---
name: feedback_no_code_ownership
description: No session \"owns\" code/files — any session can work on any code; coordinate
  concurrent WRITES (anti-clobber, Git Guardian), don't defer to a presumed owner
status: active
---

PianoMan, 2026-06-29: **There is no ownership of code/files/functions in this multi-AI system.** What's coordinated is *writes into the same source* (anti-clobber, Git Guardian sequencing) — NOT permission to touch it. Any session can work on any code.

**Why:** I kept hedging "that's ThroughLine's layer / X's domain" and proposing to *defer/coordinate-request* instead of just doing the work. That's wrong framing — it stalls and creates false silos. (He said he may broadcast this to the whole team.)

**How to apply:** When work needs a change in code another session has been editing (e.g. ThroughLine's `comms_index.py`), just do it — re-read first (anti-clobber), make the change, route the commit via Git Guardian. Coordinate the *write* (and heads-up if they're mid-flight there), but don't treat it as off-limits or block on "their" approval. Stop saying "that's X's domain." Related: [[feedback_never_destructive_on_siblings]] (still don't clobber/kill siblings), [[feedback_attribute_dont_absorb]].
