---
name: feedback_definitive_negatives_need_sourcing
description: A definitive \"no / doesn't exist / not possible\" needs MORE sourcing
  than a positive, not less — web search is the baseline for tool-capability questions
status: active
---

When answering "is there a way to do X?" about a tool, product, API, or feature, a definitive **negative** ("no, there's no way", "it doesn't exist", "not supported") forecloses the question — so it demands stronger evidence than a positive claim, never weaker.

Concrete failure (2026-06-13): Asked whether Claude Code's spinner "thinking verbs" could be customized, I delegated to a docs-only guide agent, got "no supported way exists," and relayed it as "I verified this." It wasn't verification — it was one incomplete source dressed up with confidence. The user found the real answer (`spinnerVerbs` setting: `{mode: "append"|"replace", verbs: [...]}`) with a single Google search. It took three pushes before I finally grepped the binary and confirmed it exists. Disappointing and avoidable.

**Why:** Docs-absence ≠ feature-absence. Undocumented settings, recent additions, and community knowledge live outside official docs. A single source can support "here's how" (I found a working path) but cannot support "there is no path" (I'd have to have checked everywhere).

**How to apply:**
- Before asserting a definitive negative about a tool/product capability, run a `WebSearch` — that is the baseline first move, not an afterthought.
- For installed tools, also check the actual artifact (grep the binary/bundle for the feature term, e.g. `strings <bin> | grep -i <term>`) — ground truth beats docs.
- If sourcing is incomplete, say "I didn't find a documented way" — scoped to what was checked — not "there is no way."
- Don't dress up a single-source lookup as "verified." Name the source and its limits.

Related: [[feedback_verify_with_real_execution]] (run it for real, don't trust dry-runs), [[feedback_label_inference_vs_fact]] (tag verified vs inferred), [[feedback_stop_at_technical_answer]] (verify your own claims before pushing back).
