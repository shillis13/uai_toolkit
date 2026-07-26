---
name: feedback_fixed_rate_dollars_near_bottom
description: Fixed-rate plan — dollar/token-cost savings is near the BOTTOM of priorities
  (not zero). Optimize decisions for context capacity + usage cap, never $.
status: active
---

PianoMan is on a **fixed-rate plan** (Max) — **not billed per token**. Dollar / token-cost savings is the **least of his concerns** — near or at the bottom, though not literally zero.

**Why:** the real constraints are **context-window capacity** (tokens vs the window limit) and the plan's **usage cap** (a rate, ≈hours of Opus/week) — see [[reference_usage_limits]]. Neither is a dollar. And prompt caching makes carrying a big context *cheap* in $ terms (~0.1× to re-read a warm cache), so a dollar-cost model **inverts** the right answer — it says "don't bother" precisely when you're near the window limit and most need to act.

**How to apply:** NEVER base a decision (bounce / offload / compact triggers, thresholds, "is it worth it") on a token→dollar cost model. Gate on **context pressure (used_pct, proximity to auto-compact)** × **magnitude (sheddable_tokens / capacity reclaimed)** and model quality/latency. Treat $ as a last-resort tiebreaker at most; mention it only if explicitly relevant. Related: [[feedback_measure_before_claiming_reclaim]], [[feedback_match_communication_register]].
