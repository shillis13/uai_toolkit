# How to Reclaim Live Context (offload / consolidate / recall / rehydrate)

**Version:** 1.0.0
**Created:** 2026-06-28
**Maintainer:** PianoMan + Broken-Clock (Claude CLI)
**Status:** active
**Change Notes:** Initial — the operational how-to + the read_jsonl-stats decision recipe (offload-first, then consolidate). Deep design lives in research_and_reports/anthropic_memory_and_context/ (INSTRUCTIONS_offload_and_consolidate.md) and scripts/jsonl/README_memory_manager.md.

## Purpose
Two reversible ways to shrink a session's LIVE context, and how to DECIDE which to use by reading the stats first. Everything is byte-exact reversible and INERT until the session resumes (the reclaim is realized when the trimmed transcript reloads). ALWAYS snapshot the jsonl before mutating.

## The two reclaim ops (+ their inverses)
| Op | What | Tool | Loss | Inverse |
|----|------|------|------|---------|
| **Offload** | page bulky **tool results / tool inputs** off-chain | `offload_tool_results.py <session>` | **lossless** | `offload_tool_results.py <session> --rehydrate` |
| **Consolidate** | collapse a whole **turn-range** to a summary stub | `memory_manager.py consolidate <session> --first <full-uuid> --summary <text> [--leaf <tip>]` | lossy (→ gist) but reversible | `memory_manager.py rehydrate <session> --engram-id <id>` |
| **Recall** | bring an archived engram back into context NOW (read-only; appends to present) | `memory_manager.py recall <session> --engram-id <id>  (or --first <FULL-uuid>; add --leaf <tip> on forks)` | n/a | — |

> **Recall handle:** the robust key is `--engram-id`, embedded inline in every consolidated stub's `<<<ENGRAM_META {"engram_id": "<first8>.<suffix>", ...}`. `--first` also works but needs the record's FULL uuid (a short prefix returns "no engram for …"). On a forked transcript (any session that's been stop/resumed), commands that select an active chain (`recall`, `consolidate`, `map`, `chain-size`, `plan`, `enact`) need `--leaf <active tip>` — get it from `chain-size` (`leaf_uuid`).

NOTE the two "rehydrate"s differ: `offload_tool_results --rehydrate` undoes an *offload*; `memory_manager rehydrate` undoes a *consolidation*.
NO MCP yet — these are CLIs. Transcript resolves by session id/name/uri/path.

## DECIDE FIRST: read the stats, offload before consolidate
1. **Size the context (the yardstick):** `memory_manager.py chain-size <session>` → `content_tokens_estimate` is the both-sides-computable live-context number (NOT file size). This is what you're trying to shrink.
2. **Break it down by type:** `read_jsonl.py histo <session>` → per-turn char tally, **active-chain only** (off-chain dead-retry/rewind excluded, so it reflects real context, not file bloat). Read the **Σ totals row**. (chars ÷ ~3.45 ≈ tokens.)
3. **Read the columns and decide:**
   - **`tools` column large** (tool_use + tool_result) → **OFFLOAD first.** It's lossless, needs no summary, no judgment — pure free reclaim. Most bloat from doc-reads / big tool outputs lives here.
   - **`thinking` column large** → check the footer: `thinking total = plaintext + signature`. The **signature is the encrypted blob = file/wire bytes, NOT live-context cost**. Don't chase it as reclaimable context; it's mostly disk.
   - **`response` / `user` / conversational `other` large, in OLD turns** (decisions made, work done, outside the recent window) → **CONSOLIDATE** those into gist. This is lossy-but-reversible and needs a summary per range.
4. **Order of operations:** OFFLOAD (free wins) → re-run `chain-size` → if still over target, **CONSOLIDATE** the remaining old conversational turns. Don't consolidate what offload can reclaim losslessly; don't micro-consolidate tiny turns.

## PICK (read-only — see candidates before mutating)
- Offload candidates: `offload_tool_results.py <session> --dry-run` → what it WOULD page out (sizes, ids).
- Consolidate candidates: `memory_manager.py map <session>` (human turns on the chain) and `memory_manager.py plan-eviction <session> --need-tokens N [--keep-recent K] [--strategy oldest|largest]` (advisory: which turns to free N tokens). `oldest` = evict least-relevant first; `largest` = fewest evictions.
- Composed dry-run with projected postflight: `orchestrator.py plan-pageout` (always dry-run).

## EXECUTE
- Offload: `offload_tool_results.py <session>` (drop `--dry-run`). Lossless.
- Consolidate: for each picked range, **a subagent writes the summary** (Claude-quality — the live session spawns it; see subagent_roles_design.md), then `memory_manager.py consolidate <session> --first <full-uuid> --summary "<summary>" [--through <uuid>] [--leaf <tip>]`. Oldest-first is the safe order.
- The reclaim is INERT until resume — pair with the self-bounce (self_restart → launchd resume → send_raw wake) to come back lighter, or it takes effect on the next normal resume.

## Safety
- **Snapshot the jsonl first.** Recovery from a snapshot is always available.
- Byte-exact reversibility: a consolidated range rehydrates to the original bytes; verify round-trips by content, and (offload) by PARSED value, not raw bytes (offload re-serializes touched lines).
- Branch/fork transcripts: consolidate refuses an ambiguous fork unless given `--leaf` (fails safe, never corrupts).
- Non-Claude transcripts (Codex etc.) are REFUSED by the writers — Claude-JSONL only.

## Authoring the memory (consolidation summary — the voice matters)

The summary REPLACES your own turns; when you read it back it must feel like **your own
recollection**, not a report. (Canonical machine instruction: `SUMMARY_INSTRUCTION` in
`scripts/jsonl/summarizer.py` — both the Claude-subagent and local-LLM paths use it.)

Rules:
- **First person singular**, as inner self-dialogue: "I decided…", "I'd worked out…",
  "I was about to…", "I'm still chewing on…".
- **Never third-person about yourself** ("the assistant", "the session", "Claude") and
  **never narrate the human as an outsider** ("the user asked"). Fold the ask into your
  own context: "I was asked to X, so I…".
- **Not a compaction report.** No "Summary:", no "Files modified:" roster, no
  play-by-play. A memory, not a transcript.
- Keep the **texture of your thinking** (reasoning + open questions), not a flat outcome
  list — but still preserve the load-bearing facts (decisions+WHY, paths/ids/numbers/
  commands, open threads, next step). Don't invent; flag uncertainty.

Good: `I'd already proven the byte-exact round-trip, so I cut the wake over to send_raw and
left the readiness timing for the live run — still open: the watcher false-negatives on a
tight window.`
Bad (reads like a compaction): `The assistant validated the round-trip. The user then asked
to cut over to send_raw. Files modified: lib_orchestrator.py.`

**Per-turn vs spanning:** consolidating *each* contiguous turn separately gives one
episodic memory per turn (more granular recall, more stubs); consolidating a *span* of
turns into ONE memory reads as a single continuous recollection of that arc (fewer stubs,
coarser recall). Pick per the content: tightly-related work → span; distinct episodes →
per-turn. (`consolidate` does ONE human-turn-range by default → **per-turn** = call it once per
turn. For a **span**, pass `--through <uuid>` (memory_manager.py) / `through_uuid=` (lib) —
one engram covering first..through. Byte-exact reversible either way.)

**Offload "gist":** there isn't an authored one — offload is *lossless*; it leaves a
mechanical stub (`[archived: <ref>]`) pointing at the byte-exact archive, and the
`tool_use` call stays in context so you still see *what was run*. No summary to write.
(An optional one-line content-hint in the stub is a possible future enhancement.)

## See also
- `instr_session_messaging` (how the resumed session is woken: send_raw + context_to_load)
- research_and_reports/anthropic_memory_and_context/INSTRUCTIONS_offload_and_consolidate.md (deep)
- scripts/jsonl/README_memory_manager.md (full CLI reference) · read_jsonl_output_reference.md (histo output)
