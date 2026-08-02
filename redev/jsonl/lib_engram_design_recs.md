# lib_engram.py — recommendations

Companion to `lib_engram_design.md`. Only real recommendations are listed.

## 1. Decide the mechanism question before porting anything

**Problem.** The packaged `lib_engram` implements a Summarize that **overwrites a
record's `message.content` with a stub**. Upstream retired that on 2026-07-27 (todo_0692):
`consolidate` now raises `NotImplementedError`
(`ai_general/scripts/jsonl/lib_engram.py:494`) and reclaim moved to `chain_skip.py` — pure
`parentUuid` re-pointing, no archive, no stub, restore is the reverse pointer write and is
byte-exact by construction because **nothing ever moves**.

**Recommendation.** Do not port the content-overwrite writer forward on autopilot. Read
`chain_skip.py` first and make an explicit decision. The re-pointing design eliminates
whole classes of risk this file spends 1,483 lines managing: no bodies to write, no
manifest to keep in sync, no two-phase commit, no garbage collection, no integrity hashes,
no fat-vs-slim stub migration.

**What is lost if you drop archive-and-stub entirely, and must be replaced:**
- **Recall** — paging an old range back into live context on demand. Re-pointing leaves
  the records in the file, so recall is still possible, but by a different route.
- **The stub as a self-describing recovery record.** The embedded `ENGRAM_META` lets a
  transcript recover with the manifest destroyed. Re-pointing needs an equivalent (upstream
  uses a `<transcript>.offload_tokens.jsonl` sidecar; `SKIP_EVENT_ATTRIBUTION_REVIEW.md`
  notes that sidecar is diagnostic, and the real safety net is `<transcript>.bak`).
- **The summary being visible on the chain at all.** Re-pointing splices a residue pair
  instead — with different token economics (see rec 5).

**What must survive either way** — carry these into the replacement regardless of
mechanism: chain-native selection; never summarize the live tail; `keep_recent_turns`;
fail-closed on ambiguity, corruption and non-Claude transcripts; byte-identical untouched
lines; and the balance invariant from `chain_skip.py:19-27` (a skip must remove a
`tool_use` and its `tool_result` together — not because the API rejects an orphan, but
because Claude Code's resume sanitizer silently *repairs* it by discarding the whole
assistant message, reasoning included).

## 2. Fix the turn-boundary divergence (defect, fix in the re-design)

**Problem.** `lib_engram._is_human_prompt` (`lib_engram.py:219`) uses a structural
heuristic. `lib_jsonl_archive.is_turn_start` (`lib_jsonl_archive.py:197-227`) documents
that this heuristic was replaced because it over-counts — 16 "turns" against 12 real
prompts on a measured transcript, the extras being an `isCompactSummary` record and three
continuation records — and asserts that every turn-numbering surface delegates to it.
The packaged `lib_engram` does not. Upstream already fixed it
(`ai_general/scripts/jsonl/lib_engram.py:211-213` now returns `is_turn_start(rec)`).

**Impact.** On any transcript with a compaction boundary or continuation record, the
packaged `lib_engram` disagrees with `read_jsonl`'s displayed turn numbers, and
`plan_eviction`'s `keep_recent_turns` window protects the wrong turns.

**Fix.** One line: delegate to `is_turn_start`. Then delete `_is_human_prompt` or keep it
as an alias. Add a test asserting the two agree on a transcript containing a compaction
summary and a continuation record.

## 3. Make `gc_archive` refuse to orphan a live stub

**Problem.** `gc_archive` (`:1408`) deletes body files whose slugs are not referenced by a
manifest record. The stub-embedded metadata exists precisely so the system survives
manifest loss — but gc reads only the manifest. A transcript with a live stub whose
manifest record was lost gets its bodies deleted, after which the stub is permanently
unrestorable. The 60-second `grace_seconds` window (`:1456`) protects only very recently
written bodies.

**Fix.** Before deleting, scan the transcript for live engram stubs and add every
`engram_id`'s derivable slugs (`engram.<id>.<n>`, reconstructable from `range_uuids`
length) to the referenced set. `repair_manifest` (`:1276`) already does this scan; reuse
it. Consider making gc refuse outright if it would delete bodies for an engram id that
appears in a live stub, rather than silently reconciling.

## 4. Make the transcript-mutation guard real

**Problem.** The compare-and-swap on the transcript is a **size-only** fingerprint
(`lib_jsonl_archive._stat_sig:84`), justified by "the transcript is append-only so any
change we must not clobber grows the file". That is true of Claude Code and **false of
these tools**, which rewrite in place at arbitrary sizes. Two reclaim operations on one
transcript are guarded by nothing. `TODO_0708_RESTORE_CAS_CODE_REVIEW.md` makes the same
objection at a different layer: *"calls a fingerprint check followed by a replace
'compare-and-swap', but those are two separate operations."*

**Fix.** A per-transcript advisory lock, in `platform_compat/locking` (the module already
exists in the plan), taken by every mutator for the whole read-modify-write. Keep the size
check as a cheap second line of defence against the external appender. Do not settle for
adding a content hash — it narrows the window, it does not close it.

## 5. Make the eviction plan report what it cannot know

**Problem.** `plan_eviction` returns `total_freed_tokens` as if it were a prediction of
realized reclaim. Three independent in-flight findings say it is not:
`FINDING_wholeturn_calibration.md` (net = removed − residue, and residue is not modelled),
`FINDING_offload_accounting.md` (split assistant-response shapes yield **zero** measured
reclaim), `FINDING_bytes_per_token.md` (the `/4` divisor is wrong in both directions).
`PLAN_EVICTION_RANGE_REVIEW.md` rules that the only licensed universal lower bound is
zero and that projected reclaim cannot authorize an automatic action.

**Fix.** Keep `plan_eviction` advisory and rename its output to say so — e.g.
`gross_removed_tokens_estimate` rather than `total_freed_tokens`, plus an explicit
`realized_reclaim_lower_bound: 0` and a `basis` string naming the divisor and the
selector. Do **not** wire a calibrated estimator into selection
(`DESIGN_RULING_TOKEN_ESTIMATOR_CONSUMERS.md` forbids it). The goal is that a caller
cannot accidentally treat the number as authorization.

## 6. Split the module along its two real seams

`lib_engram` currently mixes three things. In a re-design they should be separable:

- **Chain primitives** — `select_active_leaf`, `_chain_records`, `active_chain`,
  `has_branch_points`, `_has_ambiguous_fork`, `chain_size`. These are read-only, useful to
  every tool, and are the part upstream kept. They belong next to the other canonical
  vocabularies (see `lib_jsonl_archive_design_recs.md` rec 1), not inside a writer.
- **Planning** — `plan_eviction`. Read-only, advisory, and the one piece most likely to be
  redesigned independently.
- **The mutation engine** — `consolidate` / `rehydrate_engram` / `recall` /
  `repair_manifest` / `slim_engram_stubs` / `gc_archive`.

The seam is already visible in the platform guard: read-only operations are deliberately
exempt from the Claude-only refusal (`:71-73`).

## 7. Drop or fold

- **`summarize` as an alias of `consolidate`** (`:700-709`). Pick one name.
- **`slim_engram_stubs`** (`:1330`) — a one-time migration of already-written fat stubs. It
  is a maintenance script, not a library function; if the replacement never writes fat
  stubs it exists only for legacy files.
- **`SCHEMA_VERSION`** (`:64`) — carried, never branched on. Either use it or drop it;
  slim-body detection is deliberately structural (`:180`) and should stay that way.
- **The `sys.path` insertion** (`:52-54`) — vestigial; all imports are absolute.
- **`level` and `volatile`** (`:482`) — nothing in this package sets them. Either specify
  their policy role or drop them. *Rationale unknown — needs an owner's answer.*
- **The `repair=True` escape on the successor-chaining check** (`:566`) — an override for a
  condition that indicates the transcript is already inconsistent. Consider making it a
  separate, explicitly named repair operation rather than a flag on the normal path.

## 8. Unify the error convention

`consolidate`, `rehydrate_engram` and `recall` return `{"error": …}`; `plan_eviction`
raises `ValueError` (`:953`, `:963`). Callers must handle both. Pick one — dicts for
expected conditions is the better fit here, since `{"raced": True}` is neither success nor
error and does not map onto exceptions cleanly. Whichever is chosen, **`raced` must remain
distinguishable from `error`**: a race is a retry, an error is not.
