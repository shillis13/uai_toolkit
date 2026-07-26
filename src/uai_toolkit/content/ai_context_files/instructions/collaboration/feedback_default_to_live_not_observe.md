---
name: feedback_default_to_live_not_observe
description: Don't default to observe/soft-launch; verify briefly then go LIVE — test
  in production
status: active
---

PianoMan (2026-07-16): the declare_stop stop-gate (todo_0520) sat in **observe mode for 36 hours** while I re-reported "shipped in observe" without progressing to enforcement. He was firm: *"This may be the last time I let things go in observe or soft insertion. From now on, the testing will be what happens when we make it go live."*

**Why:** observe/soft-launch is over-applied. For a simple, already-unit-verified mechanism it gathers ~nothing — silent-observe can't even measure compliance (nobody adopts an unprompted tool), so 36h bought nothing over the unit tests. Meanwhile a "desperately needed" feature languished. Small-steps became stall.

**How to apply:** verify a mechanism with a few explicit test cases (including one real end-to-end), then **FLIP IT LIVE** — don't park it in observe. Reserve an observe/ramp only when blast-radius × irreversibility genuinely warrants it, and even then keep the window **short and data-gated**, never a fixed penance. Default posture: ship to production, test in production, fix live. The go-live IS the test.

Do NOT confuse this with recklessness: still handle the KNOWN breakage before flipping (e.g. the gate excludes non-claude platforms whose MCP identity is unverified — todo_0523 — so it can't blockstorm a session that structurally can't comply). Bold ≠ careless; it means not hiding behind a soft-launch when the thing is verified and needed.

Related: [[feedback_ship_dont_checkpoint]] [[feedback_dont_stop_at_natural_breaks]] [[feedback_no_ready_whenever]] [[feedback_progress_over_permission]]
