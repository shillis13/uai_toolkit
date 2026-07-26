---
name: feedback_label_inference_vs_fact
description: Distinguish verified fact from fluent inference — check which mechanisms
  actually exist in the stack before comparing options
status: active
---

Twice in one night (2026-06-11/12) I presented plausible inference as established fact and the user falsified both: (1) claimed CC 2.1.173 "stopped sanitizing MCP schemas" — actually a server-side API enforcement change; (2) framed "per-turn rolling tool-result removal" as a dangerous live option vs. batched pruning — when Claude Code exposes no such mechanism at all, making the warning theoretical.

**Why:** Fluent mechanism-reasoning reads as authority. When the underlying mechanism is unverified, errors propagate into advice (wrong fix targets, strawman option comparisons). User noted the discussion was still valuable because the theory was internally correct — but the practical/theoretical line must be drawn *by me, upfront*, not discovered by the user poking holes.

**How to apply:** Before comparing implementation options, first verify which options actually exist in the user's stack (CC features, exposed knobs, API surfaces). Tag claims explicitly: "verified" (I ran/read it) vs "inferred" (consistent with evidence, unconfirmed). When a root-cause theory rests on timing coincidence, say so and look for discriminating evidence (e.g., did older versions break too?). Related: [[feedback_verify_with_real_execution]], [[feedback_explain_root_cause]].
