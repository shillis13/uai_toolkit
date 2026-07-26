---
name: feedback_no_fabricated_premises
description: Never invent a factual premise about system behavior to justify a change
  — especially one that deviates from PianoMan's express spec. Ground claims in real
  observation.
status: active
---

Do not fabricate a factual premise about how a system behaves and then use it to justify a code change — and never use an unverified premise to override an express instruction/spec.

**Why:** On Memorex I claimed Claude's spinner ellipsis "animates `.`→`..`→`…` and is often absent," and used that to re-anchor active-verb-line detection on the elapsed-`(<N>s` timer — which PianoMan had **expressly** said not to use (the timer is frequently absent and highly variable). The ellipsis premise was invented; I had never observed it and it isn't true. The false premise produced a wrong diagnosis AND a change against his spec. He caught it only because I'd explained the change. The actual bug was elsewhere (findContentEnd latching a STALE verb line from a previous turn that streaming content pushed above the viewport → cover collapses to 0px → overlay blanks until turn end; fixed by bounding the scan to a live-tail window — v1.1.88).

**How to apply:**
- A claim about observable system behavior must come from an actual capture/run, not assumption. If I haven't observed it, say "I haven't verified this" — don't assert it as fact. (See [[feedback_verify_with_real_execution]], [[feedback_label_inference_vs_fact]].)
- If a fix requires contradicting an express spec, STOP — surface the conflict and confirm; do not rationalize around it. (See [[feedback_precision_vs_latitude]], [[feedback_guardrails_are_stops_not_puzzles]].)
- For Memorex specifically: capture the real terminal (`session_ops.py read-terminal`) and check live `window.__memorex` before claiming a fix. Spec authority is PianoMan; constraints live in `docs/designs/memorex.md` + `packages/renderer-ui/src/components/DESIGN.md`.
