# resume_note.py — redevelopment design

**File:** `src/uai_toolkit/jsonl/resume_note.py` (461 lines; library + a small CLI)
**Read at:** 2026-08-01. Packaged copy is identical to the live source apart from one
import rewrite (`:27`).

## Terms used here

- **Bounce** — a self-induced stop-and-resume of the *same* session on the *same*
  transcript. Invisible to the model: the thread continues.
- **Trim** — any disk-side reclaim (offload or summarize) applied to the transcript.
- **CAS** — compare-and-swap: fingerprint the file, re-check before acting, refuse on
  change.
- **Resume note** — a YAML file describing an armed bounce: identity, lifecycle,
  transcript fingerprints, expected outcome, and wake semantics.
- **Chain tokens** — `lib_engram.chain_size(...)["content_tokens_estimate"]`, the
  contract yardstick this whole file is denominated in.
- **KV re-prefill** — the cost of a resumed session re-reading its whole conversation.

## 1. What it is for

A trim is **inert until the session resumes** — a running process sends its in-memory
message list, not the file on disk. The Bounce exists solely to *realize* a trim. This
module owns everything around that bounce except the bounce itself: the resume-note file
format, the reclaim projection, the cost gate that decides whether a bounce is worth it,
the compare-and-swap validation performed before anything is killed or restored, and the
wake-time check that asks "did the reclaim actually take?".

It never trims and never bounces. It measures, decides, records, and verifies.

## 2. Where this sits on the reclaim ladder

Ladder: offload < **bounce** < summarize < self-compact < compact (full description in
`lib_engram_design.md` §2). The Bounce rung is odd and its oddness is the design:

- **A bounce reclaims nothing by itself.** It is the *realization* step for the rungs
  below and above it. Its own cost is the KV re-prefill of the whole conversation.
- Therefore it is **gated on the value of somebody else's reclaim** — hence
  `should_bounce`, which is a conjunction of "under pressure" and "the reclaim earns the
  re-prefill" (`:115-133`).
- It is **lossless**: nothing is dropped, nothing is summarized. That is why it sits below
  Summarize on the loss ordering even though it is more disruptive operationally.

## 3. Interface

```
resume_note.py <pre_trim.jsonl> <post_trim.jsonl>
resume_note.py -h | --help
```

Run directly, it is only the **reclaim projector** (`:453-461`): it prints
`project_reclaim()` as JSON — `{"before_tokens": …, "after_tokens": …, "reclaim_tokens":
…}` — reading both files read-only and writing nothing. Exit 0 for `--help`; otherwise it
propagates exceptions (a missing file raises).

Library API:

| Symbol | Signature | Notes |
|---|---|---|
| `capture_jsonl_state` (`:81`) | `(path, *, leaf_uuid=None, leaf_policy="conversational") -> {jsonl_path, sha256, size, mtime_ns, leaf_uuid, chain_tokens}` | The CAS fingerprint. Full sha256, not a size heuristic. |
| `project_reclaim` (`:107`) | `(pre_trim_path, post_trim_path) -> {before_tokens, after_tokens, reclaim_tokens}` | `reclaim_tokens` floors at 0. |
| `should_bounce` (`:115`) | `(used_pct, reclaim_tokens, before_tokens, *, min_used_pct=75.0, min_reclaim_tokens=40_000, min_reclaim_frac=0.15) -> {bounce, pressure, reclaim_ok, reclaim_floor, gate_policy_version, reason}` | The cost gate. |
| `write_resume_note` (`:164`) | 30+ keyword arguments → writes YAML, returns the note dict | Validates `reason` against `VALID_REASONS` and `model_fallback_policy` against `VALID_MODEL_FALLBACK`, raising `ValueError` (`:185-187`). |
| `is_expired` (`:321`) | `(note, now=None) -> bool` | Unparseable expiry ⇒ **True** (fail closed, `:328`). |
| `validate_pre_kill` (`:331`) | `(note, live_jsonl_path) -> {ok, checks, failed, inflight_blockers, live_state}` | Five checks; all must pass. |
| `matches_backup` (`:353`) | `(note) -> {ok, reason, actual, expected}` | Verifies the restore source before it is ever used. |
| `verify_on_wake` (`:365`) | `(note_path, jsonl_path, *, tolerance_frac=0.05, tolerance_floor=2000, resume_overhead_tokens=10_000) -> {took, expected_chain_tokens, actual_chain_tokens, delta, tolerance, allowance, rehydrate_handles, advice}` | Reads the note from disk. |
| `inflight_blocks_bounce` (`:156`) | `(note) -> [entries]` | Non-empty ⇒ the bounce must abort. |

Constants that are policy, not implementation: `RESUME_NOTE_FIELDS` (`:30`, the emit
order), `VALID_REASONS = ("context-reclaim","timed","event","blocked")` (`:49`),
`VALID_MODEL_FALLBACK` (`:50`), `GATE_POLICY_VERSION = "1"` (`:51`),
`DEFAULT_TTL_SECONDS = 3600` (`:52`), `GATE_MIN_USED_PCT = 75.0` /
`GATE_MIN_RECLAIM_TOKENS = 40_000` / `GATE_MIN_RECLAIM_FRAC = 0.15` (`:55-57`),
`DEFAULT_RESUME_OVERHEAD_TOKENS = 10_000` (`:62`).

## 4. Integration

**Callers**
- `session_bounce/reclaim_and_stage.py:156, 201` — `should_bounce`, the gate on every
  plan and enact.
- `session_bounce/bounce_watch.py:46` — `capture_jsonl_state` for the watcher's pre-trim
  snapshot. `bounce_watch` re-implements the wake-verify arithmetic locally
  (`bounce_watch.py:53-56` defines its own `DEFAULT_RESUME_OVERHEAD_TOKENS = 10_000`)
  rather than calling `verify_on_wake` — because in the no-kill architecture there is no
  note to read (see §6.1). **Two copies of the same tolerance policy.**
- MCP: `context_bounce` / `context_check_resume` in
  `mcp/sessions/tools/context_ops.py`, indirectly and by subprocess into
  `$AI_ROOT/ai_general/scripts/…`.

**What it calls**: `lib_engram.chain_size` (`:76`) and nothing else beyond the standard
library. PyYAML is optional at both ends (`:247`, `:291`) with hand-rolled fallbacks.

**Who consumes the note it writes:** the design doc names an external bouncer
(`ai_general/research_and_reports/anthropic_memory_and_context/DESIGN_session_bounce_self_stop_resume.md`,
owned by another session). **In the architecture actually shipped here, nobody does** —
see §6.1.

## 5. Data & config

No environment variables. No configuration file.

| Artifact | Path | R/W | Format |
|---|---|---|---|
| Pre-trim transcript / backup | caller-supplied | **read only** | JSONL |
| Live (post-trim) transcript | caller-supplied | **read only** | JSONL |
| Resume note | caller-supplied `path` | write (`:239`), read (`:287`) | YAML, PyYAML if available else a hand-rolled flat emitter |

The note is the durable artifact. Its field list (`:30-48`) is the schema, in emit order:
identity/lifecycle (`bounce_id`, `session`, `tracking_id`, `cli_uuid`,
`terminal_session`, `session_dir`, `substrate`, `substrate_context`, `launcher_path`,
`reason`, `armed_at`, `stopped_at`, `expires_at`, `model`, `model_fallback_policy`,
`cwd`); CAS transcript state (`jsonl_path`, pre/post sha256+size+mtime_ns,
`expected_leaf_uuid`, `pre_bounce_backup` + its sha256, `trim_operation_id`); wake
semantics (`next_action`, `resume_prompt`, `context_before_tokens`,
`projected_reclaim_tokens`, `expected_chain_tokens`, `gate_policy_version`,
`rollback_policy`, `state_path`, `in_flight`, `rehydrate_handles`, `verify_on_wake`,
`wake_at`, `wake_on`).

## 6. How it works

### 6.1 Two architectures, one file

This module was written for a **kill-based bouncer**: an external process would validate
the note, kill the session, restore from backup on failure, and resume. That is where the
heavy CAS machinery comes from — the docstring records it as the Codex-review BLOCKER-1
fix (`:9-12`): the note carries hashes so the kill/rollback is compare-and-swap protected
and never a blind restore that could clobber records written after the snapshot.

On **2026-06-24 the architecture changed** (recorded in
`session_bounce/reclaim_and_stage.py:27-31`): *"there is NO kill and NO external bouncer
process — the session schedules its own launchd `--resume` then exits cleanly via `/exit`.
That dissolves the kill-race, so the heavy CAS machinery in `resume_note.py` relaxes to a
pre-bounce sanity gate (`should_bounce`) + a wake-verify."*

**Consequence: in the shipped system, `write_resume_note`, `validate_pre_kill`,
`matches_backup`, `is_expired`, `inflight_blocks_bounce`, `_load_note` and
`verify_on_wake` have no caller.** `reclaim_and_stage.py:15-25` says so explicitly ("NO
note is staged"; `staged` in every result is always `None`), and `bounce_watch.py:16-18`
says `verify --expected` is required precisely because "there is no note to read".

So roughly 300 of this file's 461 lines describe a mechanism that is currently unused. It
is not dead in the "delete it" sense — the in-flight work (§10) is re-opening exactly the
questions the note was designed to answer — but a re-designer must not assume it is
exercised or tested by anything in this package.

### 6.2 The gate (`:115-133`)

```
pressure      = used_pct >= 75.0
reclaim_floor = max(40_000, 0.15 * before_tokens)
reclaim_ok    = reclaim_tokens >= reclaim_floor
bounce        = pressure AND reclaim_ok
```

The **conjunction** is the design: a big reclaim at low pressure defers, because the
bounce costs a full KV re-prefill and there is no hurry. The `reason` string is written to
be shown to a model or a human (`:127-130`).

The absolute floor of 40,000 tokens has a second, documented job
(`reclaim_and_stage.py:181-187`): it guarantees the summaries written for a Summarize pass
are dwarfed by the reclaim, so the gate does not need a separate term for summarization
cost. The argument also notes that summaries are written in *subagent* contexts — usage
tokens, a different currency from the main-context tokens the reclaim saves.

### 6.3 The yardstick (`:74-78`, `:13-16`)

Every token number in this file is
`lib_engram.chain_size(...)["content_tokens_estimate"]` — the sum of `message.content`
wire sizes on the active chain, divided by 4. The docstring is honest about what it is
(`:13-16`): *a deterministic CONTRACT metric, computable identically before the bounce and
after the resume — NOT the true prefill/cache cost.* `cache_creation_input_tokens` is only
available on a relaunch and `/context` buckets differently.

That honesty is the design's strength and its weakness. Strength: before and after are
computed the same way, so the comparison is meaningful. Weakness: the same-formula
comparison is only valid if nothing *outside* the transcript changes across the bounce —
and the in-flight measurements show that assumption fails badly (§10.3).

### 6.4 The CAS fingerprint (`:81-103`)

`capture_jsonl_state` records a **full sha256** plus size, `mtime_ns`, the selected leaf
uuid and the chain tokens. This is much stronger than the size-only fingerprint used
inside `lib_jsonl_archive.commit` — appropriate, because here the file is read once and
acted on much later.

The `leaf_uuid` parameter (`:87-92`, marked "HIGH 3") exists because on a **forked
transcript** the default conversational leaf may be a different branch than the one a
fork-aware trim actually modified. Every fingerprint, snapshot and verification in this
family must be told which branch to measure or it silently measures the wrong one.

### 6.5 `validate_pre_kill` (`:331-350`)

Five checks, all must pass: live sha256 == `post_trim_sha256`; live size == `post_trim_size`;
live leaf == `expected_leaf_uuid`; note not expired; no unsafe in-flight entry. Any failure
⇒ do not kill, do not restore.

`matches_backup` (`:353`) is the companion: **verify the restore source's hash before
using it as a restore source.** That is the right instinct and should survive regardless of
architecture.

### 6.6 In-flight safety (`:137-160`)

`_normalize_inflight` coerces a bare string into a **fail-closed** entry:
`external_side_effect=True, persisted=False, safe_to_retry=False,
verification="unspecified (coerced from free text)"` (`:142-144`). A structured entry
keeps its own flags but every boolean defaults to `False`. `inflight_blocks_bounce`
returns entries with an external side effect not marked safe to retry; non-empty means
abort. So a caller that says nothing gets the safe answer, and a caller that says
something vague also gets the safe answer.

### 6.7 `verify_on_wake` (`:365-396`)

```
allowance = expected_chain_tokens + resume_overhead_tokens + max(2000, 5% * expected)
took      = actual <= allowance
```

The `resume_overhead_tokens` band exists because the *resumed* chain always carries more
than the trimmed base: the `<<<SESSION RESUMED>>>` marker, an injected continuation note,
the harness's deferred-tool and skill catalog, and the first turn's work. Measured in situ
2026-06-24 at ~7–9k, so the default band is 10,000 (`:59-62`). Setting it to 0 recovers a
strict pre-resume check. The docstring is explicit that **the unambiguous reclaim
yardstick is baseline→post-trim, not baseline→resumed** (`:377-378`).

When `took` is false the result carries the note's `rehydrate_handles` (`:393`) so a
caller can undo the trim — the recovery path if a reclaim did not land.

## 7. Essential vs incidental

### Essential

- **The conjunction gate.** Pressure AND value. Not either.
- **Fail-closed lifecycle.** Expired note ⇒ blocked; unparseable expiry ⇒ blocked;
  unspecified in-flight side effect ⇒ blocked.
- **Never restore from an unverified backup** (`matches_backup`).
- **The before/after metric must be computable identically on both sides**, whatever the
  formula is. This is the property that makes verification possible at all.
- **A tolerance band with a documented, measured basis** rather than an exact-match check.
  The specific number is incidental; having one and knowing where it came from is not.
- **Explicit `leaf_uuid` threading** for forked transcripts, in every measurement.
- **Reclaim floors at 0** (`:112`) — never report a negative reclaim.
- **`--used-pct` is percentage points, not a fraction.** `reclaim_and_stage.py:278-283`
  hard-errors on a value in `(0, 1]` because `0.70` meaning 70 would silently fail the
  gate (`0.70 < 75` ⇒ defer). A replacement must keep this units check somewhere.
- **A machine-readable reason string on every gate decision.** The T2 experiment's
  headline failure was a session being refused with no explanation it could act on.

### Incidental

- **The YAML note format and its 40-field schema.** Currently unwritten and unread by
  anything in this package.
- The hand-rolled YAML emitter (`:254-284`) and parser (`:294-317`) — a PyYAML-optional
  affordance. The parser is lossy (it cannot read the nested `in_flight` list of dicts it
  can emit) so a note round-trips only when PyYAML is present.
- `GATE_POLICY_VERSION`, `rollback_policy`, `state_path`, `trim_operation_id`,
  `substrate_context`, `launcher_path` — recorded, never read.
- The specific constants 75%, 40,000, 15%, 3600s, 10,000, 5%, 2,000.
- The demo CLI.
- `VALID_REASONS` / `VALID_MODEL_FALLBACK` enumerations.

## 8. Platform notes (Tier A / B / C per `DESIGN.md`)

- **Tier A.** `os.stat().st_mtime_ns` is available on all targets. Its **resolution
  differs**: nanoseconds on Linux/ext4, 100-nanosecond ticks on NTFS, and 1 second on
  FAT/exFAT. `mtime_ns` is recorded in the note but is **not** one of `validate_pre_kill`'s
  checks (`:340-346` checks hash, size, leaf, expiry, in-flight), so the divergence is
  currently harmless — do not promote it to a check without a platform adapter.
- **Tier A.** `_sha256_file` (`:66`) reads in 1 MiB chunks in binary mode. Portable.
- **Tier A.** `datetime.fromisoformat` on naive local timestamps (`:192`, `:326`). Emitted
  and parsed by the same machine in practice; a note written on one machine and read on
  another in a different zone would mis-evaluate expiry. Also: Python 3.10's
  `fromisoformat` does not accept all ISO-8601 spellings; `DESIGN.md` sets min Python 3.10.
- **Tier B.** Nothing here, but everything this file *serves* is Tier B/C: the bounce
  itself is `launchd` on macOS (`schtasks` on Windows, per `DESIGN.md`'s deferred
  `scheduling/` port), and the resume is a CLI relaunch.
- **Tier A.** File paths are strings in the note (`:212`, `:220`). A note written on WSL
  and read on native Windows would carry a POSIX path. If notes ever cross that boundary,
  the path fields need normalizing.
- **Portable and safe:** no locking, no signals, no process control, no terminal
  interaction in this file.

## 9. Risks & sharp edges

1. **Two copies of the wake-verify policy.** `resume_note.verify_on_wake` (`:365`) and
   `bounce_watch.verify` (`bounce_watch.py:53-56`) each define
   `DEFAULT_RESUME_OVERHEAD_TOKENS = 10_000` and the same tolerance arithmetic. They will
   drift.
2. **`verify_on_wake` cannot be told which leaf to measure.** It calls `_chain_tokens
   (jsonl_path)` with no `leaf_uuid` (`:381`) even though the note records
   `expected_leaf_uuid` — so on a forked transcript it can verify against the wrong
   branch. `capture_jsonl_state` was fixed for this ("HIGH 3", `:87`); `verify_on_wake`
   was not.
3. **The note is written but never read by anything shipped** (§6.1). Untested by use.
4. **`_load_note`'s fallback parser cannot read what `_flat_yaml` writes** for
   `in_flight` (a list of dicts): `_flat_yaml:271-278` emits `  - key: value` /
   `    key: value` blocks, and the fallback parser (`:298-300`) appends the raw line as a
   string. Without PyYAML, `in_flight` round-trips into garbage — and `in_flight` is a
   fail-closed safety field.
5. **`should_bounce` takes `used_pct` on trust.** Nothing in this file validates the range;
   the units check lives in the caller's argument parser (`reclaim_and_stage.py:281`), so a
   library caller can pass a fraction and silently never bounce.
6. **`capture_jsonl_state` parses the whole transcript** (via `chain_size`) in addition to
   hashing it. On a large transcript that is two full reads per snapshot.
7. **The projection and the verification use different bases.** `project_reclaim` and
   `verify_on_wake` both use `content_tokens_estimate` — consistent. But the *gate* is fed
   from `plan_eviction.total_freed_tokens`, which is **wire size / 4**
   (`reclaim_and_stage.py:154-156`), not content size / 4. So `should_bounce`'s
   `reclaim_tokens` and `before_tokens` are in one unit while the note's
   `expected_chain_tokens` is in another. The in-flight `CONTRACT_SEAM.md` reviewed this
   and concluded the gate is *internally* consistent (both its inputs are wire/4) — but a
   re-designer must not assume the numbers are interchangeable.

## 10. Work in flight — **do not read this file as settled design**

Active work lives in `ai_root/ai_general/work/experiments/t2_context_agency/`. This file's
constants and contracts are among the most actively disputed in the package.

1. **`FINDING_never_bounced.md` — the `bounced` field is a lie.** In the T2 run, eight
   correct summarize acts reclaimed a reported 365,525 tokens and every enact returned
   `bounced: true`. **The session never restarted** — one `SessionStart` in the whole run.
   Root cause: `reclaim_and_stage.py:234` returns
   `{"bounced": bool(rec["consolidated"]), …}`; the field means *"you should now bounce"*
   (an instruction to the caller) but reads as past tense to the model receiving it, and
   the MCP path never performs the bounce step. **All the reclaim moved off-chain in the
   file while the live context retained every token.** A replacement must name this field
   for what it is and must not report a realization that did not happen.
2. **`FINDING_gate_notice_mismatch.md` — the notice and the gate disagree by 15 points.**
   The graduated awareness notice fires at 60% ("summarize is your lever"); the planner's
   pressure gate is `GATE_MIN_USED_PCT = 75.0` (`:55`). A session read the notice, called
   `context_summarize_plan`, and was refused with `"defer: not under pressure (50% <
   75%)"` while 125,052 tokens were reclaimable. The finding's own verdict: *"This is
   worse than not notifying at all: it trains a session that asking does not work."* The
   two thresholds must be reconciled in the re-design.
3. **`FINDING_overhead_floor.md` — the 10,000-token resume-overhead band is far too
   small in the worst case.** Measured live: on-chain reclaim of 288k produced a live
   recovery of 101,098 tokens, because non-transcript overhead (system prompt, MCP tool
   schemas, skill descriptions, injected instructions) **tripled across the bounce** from
   ~90k to ~254k as the resumed session reloaded the full deferred-tool catalog — roughly
   163k of system-message content. Every lever a session has reclaims *transcript only*.
   The `DEFAULT_RESUME_OVERHEAD_TOKENS = 10_000` band was measured on a much lighter
   session and is not a general constant.
4. **`PLAN_EVICTION_RANGE_REVIEW.md` (2026-07-30) — the automatic gate must fail closed.**
   Ruling: projected reclaim cannot authorize an **automatic** bounce, because the only
   universally licensed lower bound on realized reclaim is zero. Automatic authorization
   was withdrawn in `2d5c904d`. Explicit operator-requested bounces and
   Summarize/Offload are unaffected. The review names `reclaim_and_stage.py`'s direct
   consumption of `total_freed_tokens` as the unsafe path.
5. **`FINDING_resume_recommend_estimator.md` (rev 3)** documents the withdrawal, and is
   itself a case study: rev 1 claimed a live over-authorization risk and was **retracted**
   (the mechanism belonged to the retired architecture), rev 2 overcorrected and was
   **also retracted**. Read it before drawing conclusions about the estimator path.
6. **`DESIGN_RULING_TOKEN_ESTIMATOR_CONSUMERS.md` (2026-07-31):** the underlying
   `tokens(nbytes)` helper keeps its signature and gains no decision authority; a
   record-aware estimator must be a second, structured API. Since every number in this
   file flows through that helper, its accuracy question is unresolved upstream of here.
7. **todo_0707 (mutation-frame integrity)** and **todo_0708 (restore CAS)** are open at
   REQUEST_CHANGES. todo_0708's review objects to "a fingerprint check followed by a
   replace, called compare-and-swap, when those are two separate operations" — the same
   critique applies to `validate_pre_kill` followed by an action.
