---
name: feedback_every_declarative_needs_evidence
description: Every declarative statement out of the terminal needs evidence/proof;
  don't assert unverified
status: active
---

PianoMan (2026-07-12) moved to require that **every declarative statement** I emit carry evidence or proof, after I made multiple confident-but-wrong claims in one session:
- "a fork is cheaper than a fresh subagent" — he's on a flat subscription; no per-token cost delta at all.
- "the MCP server is one shared process, not per-session" — it's 30 per-session stdio children (proven by ps).
- "PID 307 has no AI_TRACKING_ID (identity-less edge case)" — it's Git-Guardian's Codex sessions-MCP child (proven by parent chain `codex resume <uuid>`); the grep miss was a ps-eww env limitation, not absence.
- "claude_cli_8866 is a placeholder" — it's Relay's real active tracking_id in an older format (proven by session_store).

**Why:** confident unverified assertions repeatedly failed his scrutiny. Coherence-led guessing is not correspondence. A command/grep returning nothing is *filter-suspect*, not proof of absence. An unfamiliar-looking string may be a real (legacy) value. Restating a thing at higher confidence than the evidence supports is the defect.

**How to apply:** state a factual/technical claim only with the evidence that backs it (command output, file contents, a cited source) — run the check rather than reason about it. Explicitly label anything inferred or unverified AS such, and give its confidence (e.g. "n=1, not generalized"). Treat negatives/absences as "verify the filter/tool" before concluding. Never inflate an observation into a conclusion. Related: [[feedback_label_inference_vs_fact]] [[feedback_verify_with_real_execution]] [[feedback_definitive_negatives_need_sourcing]] [[feedback_dont_conclude_before_verifying]] [[feedback_iterate_filters_not_search_space]] [[feedback_no_fabricated_premises]]
