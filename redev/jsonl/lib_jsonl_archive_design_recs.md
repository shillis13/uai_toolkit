# lib_jsonl_archive.py — recommendations

Companion to `lib_jsonl_archive_design.md`.

## 1. Split it. It is four modules wearing one name.

**Problem.** The file is named for archiving, but only about a third of it archives.
Three independent vocabularies accreted into it because it was the convenient shared
place:

| Concern | Lines | Depends on the archive? |
|---|---|---|
| File safety + archive store + manifest + commit + rehydrate | `:44-131`, `:383-803` | — |
| Canonical record classification and turn boundaries | `:196-380` | **no** |
| Compaction-interval and branch model | `:806-1109` | **no** |
| Region/token-mass analysis | `:1112-1248` | reads stub prefixes only |

The cost is concrete. `chain_skip.py` — the *replacement* reclaim mechanism, which
archives nothing — imports `is_turn_start`, `classify_record`, `compaction_intervals`,
`select_intervals`, `_stat_sig`, `atomic_write` and `ensure_backup` from a module whose
entire reason for existing it does not use. `read_jsonl.py` imports it at module scope
(`:70`) and then re-exports the interval model (`read_jsonl.py:1885-1899`). Nine modules in
the live source tree import from it.

**Recommendation.** In the re-design, split into roughly:
- `jsonl/records.py` — `is_turn_start`, `classify_record` and the predicates,
  `human_turn_indices`, `protect_from_index`, `wire_size`, `sha8`, `render_readable`.
  No dependencies. This is the true shared vocabulary.
- `jsonl/intervals.py` — the compaction-interval and branch model, plus the `--interval` /
  `--branch` spec parsers.
- `jsonl/transcript_io.py` — `_stat_sig`, `ensure_backup`, `atomic_write`, `commit`, and
  the per-transcript lock recommended below. Every mutator needs exactly this and nothing
  else.
- `jsonl/archive.py` — `Archive`, `write_body`/`read_exact`, manifest + lock,
  `resolve_archive_dir`, `rehydrate`, `BodyIntegrityError`. Only the modules that actually
  archive depend on this.

**Constraint:** the single-source property is the *point*. Splitting must not create two
turn-start predicates. Everything in `records.py` and `intervals.py` should have exactly
one definition and no re-implementations anywhere.

## 2. `tokens()` — leave it, fence it, name it

**Problem.** `tokens(nbytes) = max(1, round(nbytes/4))` (`:192`) is the token estimate for
the entire ladder. `FINDING_bytes_per_token.md` measured, against `message.usage` ground
truth, ~2.74 characters/token for message content and ~5.37 characters/token for whole wire
records — so `/4` understates content cost and overstates wire cost. It is also fed
**characters** (`wire_size` uses `len` / `len(json.dumps(...))`) while its parameter is
named `nbytes`.

**Recommendation** — this matches the standing ruling
(`DESIGN_RULING_TOKEN_ESTIMATOR_CONSUMERS.md`, 2026-07-31), do not exceed it:
- Keep the function and its signature. It is a compatibility fallback.
- Rename the parameter to `nchars` and say in the docstring that it is a **degraded
  heuristic with no decision authority**.
- Any calibrated estimator arrives as a **separate, structured API** (upstream is building
  `lib_token_estimate.py`), exposed alongside the legacy number in read-only/shadow output,
  never substituted underneath existing callers.
- Nothing that selects what to page out may consume a point estimate as authorization.

## 3. Replace the size-only CAS with a real lock

**Problem.** `_stat_sig` (`:84`) is size-only, on the stated grounds that a live
transcript is append-only. That holds for Claude Code and **not** for these tools, which
rewrite in place. `commit` (`:705-715`) then does a fingerprint check followed by a
separate `os.replace` — `TODO_0708_RESTORE_CAS_CODE_REVIEW.md` objects to exactly this
being called compare-and-swap.

**Recommendation.** Add a per-transcript advisory lock in `platform_compat/locking`
(already planned in `DESIGN.md`: `fcntl` / `msvcrt`), held across the whole
read-modify-write by every mutator. Keep the size check as a cheap guard against the
external appender. Do not merely upgrade the fingerprint to a content hash — that narrows
the window without closing it, and costs a full file read.

## 4. Make durability honest instead of best-effort

**Problem.** `_fsync_path` (`:45`) and `_fsync_dir` (`:57`) swallow `OSError`. Directory
`fsync` is a POSIX idiom that fails on native Windows. So on Windows the whole two-phase
commit — "bodies durable → pointer durable → transcript" — silently degrades to
"whatever the OS felt like", with no signal, while the code continues to claim
crash-recoverability.

**Recommendation.** Move both into a `platform_compat/durability` adapter with an explicit
capability flag (`supports_directory_fsync`). Callers that depend on crash recovery should
be able to ask, and the docstrings that promise power-loss safety should say "on platforms
that support it". Keep the best-effort behaviour — just stop it being invisible.

## 5. Make `rehydrate` fail closed like its sibling

**Problem.** `lib_engram.rehydrate_engram` fails closed on any missing or corrupt body and
returns a problem list. `lib_jsonl_archive.rehydrate` (`:726`) does neither: a
`BodyIntegrityError` propagates as an exception mid-loop, and embed restore failures are
swallowed entirely (`:796`) and simply not counted in `restored`.

**Recommendation.** One rehydrate contract for both: pre-check every body, abort before
any write if anything is wrong, return `{"restored": n, "problems": [...]}`, and offer the
same `allow_partial` / `allow_corrupt` overrides. Reversibility is the package's headline
guarantee; the two implementations of it should not differ.

## 6. Guard `rewrite_manifest`

`rewrite_manifest` (`:625`) documents that the caller must hold `manifest_lock()` and does
not check. A caller that forgets loses records under concurrency, silently. Either take the
lock inside (and provide an explicit `_locked` variant for read-modify-write), or assert
that the lock directory exists and is owned by this pid.

## 7. Reconsider stale-lock stealing

`manifest_lock` steals a lock whose owner pid is dead **or** whose age exceeds 120 seconds
(`:534-549`). The pid rule is sound. The age rule steals from a live, slow holder — and
because `rewrite_manifest` replaces the whole file, the loser's records vanish entirely.

**Recommendation.** Steal only on a provably dead owner. If the owner cannot be verified
(missing or garbage `owner.json` — the back-compat case), keep an age rule but make it
generous, and log the steal loudly. Never steal from a pid that is alive.

## 8. Smaller items

- **Sweep temp files.** `.jarch_tmp_*` next to the transcript and `.manifest_tmp_*` in the
  archive are orphaned by any crash between `mkstemp` and `os.replace`. Nothing removes
  them. Add a sweep on `Archive.ensure()` for entries older than a few minutes.
- **Hash the exact value, not the rendering.** `write_body` records
  `sha8(render_readable(value))` and `read_exact` re-derives it the same way (`:506`,
  `:689`) — consistent, but it verifies the rendering, so two different JSON values that
  render identically both pass. For `exact_kind == "json"` bodies, hash the JSON text.
  *(Whether the current choice was deliberate is not determinable from the code —
  rationale unknown, needs an owner's answer.)*
- **Keep the negative-interval semantics and pin them with a test.** `-1` means "one
  interval before live", not Python's from-the-end indexing (`:934-937`). A future
  maintainer will "fix" this. A named test is the cheapest defence.
- **Document that `_stat_sig`, `_fsync_dir` etc. are public API in practice.** They are
  imported by name across modules; the leading underscore misleads.
- **Cache the file read.** `analyze` (`:1162`) reads the transcript, and
  `human_turn_indices` inside it calls `read_jsonl.parse_session`, which reads it again.
  `find_compactions` and `records_with_lines` each open it again. A shared parsed-record
  handle passed between these would remove several full passes on large files.
- **Retry `os.replace`.** On native Windows, replacing a file another process holds open
  raises a sharing violation. A short bounded retry with backoff in `atomic_write` (`:112`)
  costs little and prevents a class of spurious failures.
