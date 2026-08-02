# resume_note.py — recommendations

Companion to `resume_note_design.md`.

## 1. Rename `bounced`, and never report a realization that did not happen

**The defect, measured.** `FINDING_never_bounced.md` (T2 run): a session performed eight
correct Summarize acts reporting 365,525 tokens reclaimed. Every `enact` returned
`bounced: true`. **The session never restarted** — one `SessionStart` in the entire run.
All of it moved off-chain in the file while live context retained every token.

Root cause is a name: `reclaim_and_stage.py:234` returns
`{"bounced": bool(rec["consolidated"]), …}`. The module's own comments (`:172-179`) make
the intent clear — the field means *"you should now bounce"*, an instruction to the caller
— but it is past tense, and it is returned to a **model**, which reasonably reads it as
"this is done". The MCP path never performs step 4.

**Fix.** This is a contract problem in `resume_note`'s family even though the field lives
in the caller:
- Rename to something imperative and unambiguous: `bounce_required: true` /
  `bounce_performed: false`.
- Report **both** — what was written to disk, and whether it has been realized. They are
  different facts and today only one is reported.
- The only thing entitled to set a "reclaim realized" flag is something that observed the
  resume. `verify_on_wake` is that thing; nothing else should imply it.
- Any result surfaced to a model must state plainly that the reclaim is **inert until
  resume**. That sentence exists in several docstrings and in none of the return values.

## 2. Reconcile the notice threshold with the gate threshold

**The defect, measured.** `FINDING_gate_notice_mismatch.md`: the graduated awareness notice
fires at 60% ("you have crossed the point where reclaim is worth doing… summarize is your
lever"). The planner's gate is `GATE_MIN_USED_PCT = 75.0` (`:55`). A session read the
notice, called `context_summarize_plan`, and was refused —
`"defer: not under pressure (50% < 75%)"`, `ranges: []` — with 125,052 tokens reclaimable.
The finding's verdict: *"worse than not notifying at all: it trains a session that asking
does not work."*

**Fix.** Pick one number and derive both surfaces from it, or make the gate's refusal
actionable. Three options, in order of preference:
1. One source of truth for "reclaim is worth doing", consumed by both the notice and the
   gate.
2. Keep two thresholds but make the notice say what the gate will actually do at the
   current level.
3. Distinguish *pressure* (should we bounce now?) from *eligibility* (may we plan and
   enact a trim now?). A session below 75% should still be able to **stage** a trim; only
   the bounce needs the pressure test. That is arguably the correct model — the trim is
   cheap and inert, the bounce is expensive.

Whatever is chosen, the refusal must carry a reason the caller can act on. It already
carries a `reason` string (`:127-130`); the failure was that the two policies disagreed,
not that the string was missing.

## 3. Re-derive the resume-overhead band, or stop treating it as a constant

`DEFAULT_RESUME_OVERHEAD_TOKENS = 10_000` (`:62`) is documented as "measured ~7–9k in-situ
(2026-06-24)". `FINDING_overhead_floor.md` (2026-07-29) measured non-transcript overhead at
**~254,000 tokens**, having *tripled* across a bounce as the resumed session reloaded the
full deferred-tool and skill catalog — roughly 163k of system-message content. In that run,
288k of on-chain reclaim produced 101,098 tokens of live recovery.

The band is not a property of the bounce; it is a property of the session's tool/skill
configuration at resume time. Two fixes, both worth doing:

- **Measure it rather than assume it.** At wake, the overhead is derivable:
  `live_context − on_chain_content`. Compute it and report it, instead of allowing a fixed
  band. `verify_on_wake` already has both halves available in principle.
- **Report the overhead explicitly in the verify result.** A `took: true` today can mean
  "the reclaim landed" or "the reclaim vanished into a 163k catalog reload and we allowed
  it". Those must be distinguishable.

Related and worth stating in the same place: **every lever in this package reclaims
transcript only.** System prompt, MCP tool schemas, skill descriptions and injected
instructions are additive and untouchable. A session at 85% may have very little
reclaimable mass. Any threshold denominated in "percent of context used" is partly
measuring something no lever can move.

## 4. Fix `verify_on_wake`'s missing leaf

`capture_jsonl_state` was given an explicit `leaf_uuid` (`:87-92`, marked "HIGH 3") because
on a forked transcript the default conversational leaf may be a different branch than the
one that was trimmed. `verify_on_wake` was not: it calls `_chain_tokens(jsonl_path)` with
no leaf (`:381`), **even though the note it just read carries `expected_leaf_uuid`**
(`:219`). On a forked transcript it can verify against the wrong branch and report a
confident wrong answer. One-line fix; add a fork regression test.

## 5. De-duplicate the wake-verify policy

`resume_note.verify_on_wake` (`:365-396`) and `bounce_watch.verify`
(`bounce_watch.py:53-56` and following) each define
`DEFAULT_RESUME_OVERHEAD_TOKENS = 10_000` and the same
`expected + overhead + max(2000, 5%)` arithmetic. `bounce_watch` has its own copy because
in the no-kill architecture there is no note to read from. Extract the *policy* (the
allowance computation) into one function that takes the numbers directly; let both callers
supply them from wherever they have them.

## 6. Decide the note's fate — do not leave it half-alive

The 2026-06-24 architecture change (no kill, no external bouncer; the session schedules its
own resume and exits cleanly) left roughly 300 of this file's 461 lines with **no caller**:
`write_resume_note`, `validate_pre_kill`, `matches_backup`, `is_expired`,
`inflight_blocks_bounce`, `_load_note`, `verify_on_wake`, and the whole 40-field schema.
Unused code is untested code, and the fallback YAML parser proves it: `_flat_yaml`
(`:271-278`) emits `in_flight` as a nested list of dicts and `_load_note`'s fallback
(`:298-300`) cannot read it back — so without PyYAML, a **fail-closed safety field** round-trips
into garbage.

Three coherent choices:
1. **Delete the note machinery**, keep `should_bounce`, `capture_jsonl_state`,
   `project_reclaim` and the verify arithmetic. Smallest honest surface.
2. **Restore the note as the durable record of an armed bounce**, and wire it — the
   in-flight integrity work (todo_0707) is re-opening exactly the "what was actually
   applied" question the note was designed to answer.
3. **Keep it explicitly as a design artifact**, clearly marked unused, with the fallback
   parser removed and PyYAML made a hard requirement so it cannot silently corrupt.

What must not persist is the current state: a safety mechanism that looks live, is not
exercised, and has a latent data-loss bug in its fallback path.

## 7. Smaller items

- **Validate `used_pct` in `should_bounce`.** The units check ("percentage points, not a
  fraction") lives only in the CLI argument parser (`reclaim_and_stage.py:278-283`). A
  library caller passing `0.70` silently never bounces. Move the check into the function.
- **Name the unit in every token field.** The gate is fed wire-size/4 numbers
  (`plan_eviction`) while the note's `expected_chain_tokens` is content-size/4
  (`chain_size`). `CONTRACT_SEAM.md` confirms each contract is internally consistent, but
  the field names do not say which basis they use. Add a `basis` string, or suffix the
  names.
- **Avoid the double read.** `capture_jsonl_state` hashes the file and then parses it again
  via `chain_size`. One pass could produce both.
- **Use timezone-aware timestamps in the note.** `armed_at` / `expires_at` are naive local
  (`:191-193`). A note written on one machine and evaluated on another mis-evaluates
  expiry — and expiry is a fail-closed gate.
- **Do not promote `mtime_ns` to a CAS check** without a platform adapter: resolution is
  nanoseconds on ext4, 100ns ticks on NTFS, one second on FAT/exFAT. It is recorded but
  correctly not checked (`:340-346`) today.
