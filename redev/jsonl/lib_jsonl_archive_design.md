# lib_jsonl_archive.py — redevelopment design

**File:** `src/uai_toolkit/jsonl/lib_jsonl_archive.py` (1,248 lines, no CLI — library only)
**Read at:** 2026-08-01. The packaged copy is byte-identical to the live source
(`ai_root/ai_general/scripts/jsonl/lib_jsonl_archive.py`) apart from two import rewrites
(`:356`, `:1152`). Of the five files in this scope, this is the only one **not** diverged.

## Terms used here

- **Archive** — a sidecar directory next to a transcript holding extracted content.
- **Stub** — the short placeholder text left in the transcript where content was removed.
- **Manifest** — `offload_manifest.jsonl` inside an archive: one record per extraction,
  the ledger that makes the extraction reversible.
- **CAS** — compare-and-swap: fingerprint before read, re-check before write, refuse on
  change.
- **Interval** — the span of a transcript between two `/compact` events.
- **Branch** — within one interval, a `parentUuid` path; `br0` is the live one.

## 1. What it is for

This is the **durable-storage engine** under the whole reclaim ladder, plus — through
accretion — the package's **single source of truth for three unrelated shared vocabularies**.
Four distinct jobs live in one file:

1. **Archive-and-stub storage**: a portable, fork-safe per-session archive; body writes
   with content hashes; a locked, atomically-rewritable manifest; integrity-checked reads;
   a CAS-guarded transcript commit that leaves untouched lines byte-identical; and a
   kind-aware `rehydrate` that restores any stubbed block.
2. **Canonical record classification**: what kind of thing a JSONL record is
   (`is_turn_start`, `classify_record` and friends), so every tool agrees.
3. **Canonical compaction-interval and branch model**: how a transcript is partitioned by
   `/compact` events and how a `--interval` / `--branch` spec is parsed.
4. **A read-only token-mass map** (`analyze`) by region.

Jobs 2–4 have no dependency on job 1. See the recommendations file.

## 2. Where this sits on the reclaim ladder

The ladder (offload < bounce < summarize < self-compact < compact) is described in full in
`lib_engram_design.md` §2. This file is the **substrate for the two reversible rungs**:

- **Offload** (lossless): `Archive` + `commit` + `rehydrate` are the mechanism.
  `STUB_PREFIXES` (`:37-41`) enumerates every stub form the offload family writes.
- **Summarize** (lossy, reversible): `lib_engram` builds on the same `Archive`, `commit`
  and integrity primitives but keeps its own namespace, its own manifest kind, and its own
  rehydrate.

Two invariants this file enforces on behalf of the whole ladder:

- **Reclaim is inert until `--resume`.** Nothing here changes a running session.
- **Reversibility is sacred.** The phrase is the code's own (`:170`, `:1230`). Every read
  path re-hashes what it reads and refuses to hand back content that does not match.

## 3. Interface

No CLI. Library only. The public surface, grouped by job:

**Storage / safety**
- `class Archive(jsonl_path, dry_run=False, archive_dir=None, namespace=None)` (`:476`)
  — `.ensure()`, `.ref(slug)`, `.write_body(slug, value, meta)`, `.fsync_dir()`,
  `.manifest_lock(timeout=10, poll=0.05, stale_after=120)`, `.append_manifest(recs)`,
  `.rewrite_manifest(recs)` (caller must hold the lock), `.load_manifest()`,
  `.read_exact(rec, verify=True)`.
- `class BodyIntegrityError(slug, expected, got, value)` (`:171`) — carries the decoded
  but unverified value so a deliberate salvage path can use it.
- `commit(jsonl_path, raw_lines, records, dirty, sig0, sig1, backup=True) -> "nochange" |
  "raced" | "error" | "ok"` (`:696`).
- `rehydrate(jsonl_path, dry_run=False, archive_dir=None, namespace="offload")` (`:726`).
- `ensure_backup` (`:99`), `atomic_write` (`:112`), `_stat_sig` (`:84`),
  `resolve_archive_dir` (`:423`).

**Sizing / rendering**
- `wire_size(value)` (`:135`) — `len` for a string, else `len(json.dumps(...))`. A
  **character** count, not UTF-8 bytes. The in-flight calibration work is emphatic about
  this distinction.
- `tokens(nbytes) -> max(1, round(nbytes/4))` (`:192`).
- `render_readable(value)` (`:141`), `sha8(text)` (`:166`), `is_stub(value)` (`:162`).

**Classification (shared vocabulary)**
- `is_turn_start(rec)` (`:197`) and its alias `is_human_turn_start` (`:227`).
- `is_agent_result` (`:258`), `is_skill` (`:267`), `is_injected` (`:274`),
  `is_attachment` (`:282`), `is_tool` (`:286`), `classify_user_record` (`:299`),
  `classify_record` (`:313`).
- `human_turn_indices(jsonl_path, records)` (`:349`), `protect_from_index(...)` (`:373`).

**Interval / branch model (shared vocabulary)**
- `find_compactions` (`:834`), `compaction_intervals` (`:874`), `select_intervals` (`:908`),
  `interval_line_ranges` (`:970`), `line_in_intervals` (`:975`),
  `records_with_lines` (`:997`), `interval_live_chain` (`:1019`), `interval_branches`
  (`:1053`), `select_branches` (`:1065`), `compaction_boundaries` (`:1120`).

**Analysis**
- `analyze(jsonl_path, keep_last_turns=5, min_bytes=512)` (`:1162`).

**Constants callers depend on:** `KEEP_LAST_TURNS = 5` (`:33`), `MIN_BYTES = 512` (`:34`,
"~2x the ~265-char stub overhead, so offloading a block is net-positive"),
`MANIFEST_NAME` (`:36`), `STUB_PREFIXES` (`:37`), `KNOWN_NAMESPACES` (`:392`),
`LARGE_INPUT_KEYS` (`:1113`), `MIN_SUMMARY_CHARS = 2000` (`:1117`), `BRANCH_LIVE = 0`
(`:994`).

**Return conventions:** storage functions return booleans or status strings, never raise
for expected failures — except `read_exact` (raises `BodyIntegrityError`) and
`manifest_lock` (raises `TimeoutError`). The interval/branch selectors return
`(result, None)` or `(None, error_message)`.

## 4. Integration

**Importers in this package:** `jsonl/lib_engram.py:56`, `jsonl/read_jsonl.py:70` (module
alias `_lja`, plus lazy imports at `:1245`, `:1559`, and direct re-exports of the interval
model at `:1885-1899`), `jsonl/scrub_files.py:1205,1332`.

**Importers in the live source that are NOT in this package** (they show what the
vocabulary is really for): `chain_skip.py` (`is_turn_start`, `classify_record`,
`_stat_sig`, `atomic_write`, `ensure_backup`, `compaction_intervals`,
`select_intervals`), `lib_context_analysis.py`, `lib_cli_common.py`, `turn_digest.py`,
`lib_reclaim_history.py`, `lib_prompt_growth.py`, `memory_manager.py`,
`offload_tool_results.py`, `offload_session.py`.

**What it calls:** `read_jsonl.parse_session` — lazily, inside `human_turn_indices`
(`:356`) — and `scrub_files.get_image_dimensions_from_base64` — lazily, inside
`_image_vision_tokens` (`:1152`). Both are lazy specifically because those modules import
this one; both are wrapped so failure degrades rather than raises.

## 5. Data & config

No environment variables. No configuration.

| Artifact | Path | R/W | Notes |
|---|---|---|---|
| Transcript | caller-supplied | read + rewrite in place | `commit` writes the whole file atomically but re-serializes only dirty lines |
| Backup | `<transcript>.jsonl.bak` | created once, never overwritten (`:99-109`) | shared across every mutator |
| Archive dir | `<stem>.<namespace>.<uuid8>.archive/` (legacy: `<stem>.<uuid8>.archive/`) | create/read | `resolve_archive_dir:423` |
| Body files | `<archive>/<slug>.txt` (always) + `<slug>.json` (when the value was not a plain string) | write/read | `write_body:494` |
| Manifest | `<archive>/offload_manifest.jsonl` | append + atomic rewrite | one JSON record per line |
| Lock | `<archive>/offload_manifest.jsonl.lock/` + `owner.json` inside it | mkdir/rmdir | `manifest_lock:558` |
| Temp files | `.jarch_tmp_*.jsonl` next to the transcript; `.manifest_tmp_*.jsonl` in the archive | create/replace | left behind if the process dies between `mkstemp` and `replace` |

**Durable formats a replacement inherits:**
- The **manifest record**. Kinds: `result`, `input.<key>`, `embed` (`:10-13`), plus
  `engram` (owned by `lib_engram`) and legacy kind-less offload records. Locators differ
  per kind: `tool_use_id` for tool content, `line` + `path` for embeds (`:786-797`).
- The **portable reference** `<archive_id>/<slug>.txt` (`:490-492`). Never an absolute
  path — so copying a transcript and its archive to a fork resolves against the fork's own
  copy. This is the single most load-bearing storage decision in the file.
- The **archive directory name**, because `read_jsonl --resolve` reconstructs the
  directory from `<stem>.<archive_id>.archive` using the *same rule* — which is exactly
  why the namespace was folded into `archive_id` as `"<ns>.<uuid8>"` rather than added as
  a separate path component (`:15-20`).

## 6. How it works

### 6.1 Archive resolution and namespaces (`:383-472`)

Two mechanisms page content out: **offload** (tool content and embedded images) and
**engram** (turn ranges). They originally shared one directory and one manifest. Layering
offload on an already-consolidated transcript then matched the engram directory by stem
glob and appended kind-less offload records into the engram manifest, **corrupting
rehydrate** (`:385-391`, cited as todo_0366). The fix namespaces the directory per
mechanism. Resolution order for a named namespace (`:460-472`): reuse this namespace's
directory → else adopt a legacy bare-id directory that provably belongs to this mechanism
(`_manifest_ownership:395` peeks at the manifest's record kinds) → else mint a fresh one.
`namespace=None` keeps the pre-namespacing behavior for legacy callers.

### 6.2 The write path

`write_body` (`:494`) stores two things: `<slug>.txt`, always, holding
`render_readable(value)` — a human/model-readable rendering that is the fault-in target —
and `<slug>.json`, only when the original value was not a plain string, holding the exact
JSON. `exact_kind` in the manifest records which one is authoritative for restore. The
recorded `sha8` is of the **readable** rendering, for both kinds (`:506`), and
`read_exact` re-derives it the same way (`:689`) — so the check is consistent, but it
verifies the *rendering*, not the JSON bytes. Two different JSON values that render
identically would pass. Rationale unknown — needs an owner's answer.

`commit` (`:696`) is the transcript writer:
- Empty dirty set ⇒ `"nochange"`.
- CAS: `sig0 != sig1` (the file changed *while we were reading it*) or the current size
  differs from `sig1` ⇒ `"raced"`, no write (`:705`).
- Optional one-time backup.
- Rebuild the file as: original raw line for every untouched index, freshly serialized
  JSON for every dirty index (`:713`). The separators are `(",", ":")` **deliberately**,
  matching Claude Code's own writer, so a record whose content is logically unchanged
  (e.g. a `parentUuid` restored on rehydrate) re-serializes byte-for-byte. Default
  `json.dumps` separators would inject whitespace and break the byte-exact guarantee.
- `atomic_write` (`:112`): `mkstemp` in the same directory → write → `fsync` the fd →
  `os.replace` → `fsync` the parent directory.

### 6.3 Locking and durability

`manifest_lock` (`:558`) is an atomic `mkdir` lock with an `owner.json` holding the pid
and start time. A held lock is stolen only if the owner pid is provably dead
(`_pid_alive:69`, a `signal 0` probe; permission errors count as alive) or the lock is
older than `stale_after` (120s default). It is **not reentrant** — the docstring says so
(`:565`) and `lib_engram.gc_archive:1473` correctly takes it once around a whole
scan-and-rewrite rather than nesting.

`fsync` appears at every durability boundary: body file (`:514`), archive directory
(`:521`), manifest append (`:619-620`), manifest rewrite (`:641`, `:645`), transcript temp
(`:119`) and its parent directory (`:123`). **Every one is best-effort**: `_fsync_path`
and `_fsync_dir` swallow `OSError` (`:53`, `:65`). On a platform where directory `fsync`
is not supported, durability silently degrades to whatever the OS offers, with no signal.

### 6.4 The CAS fingerprint is size-only (`:84-96`)

`_stat_sig` returns `(st_size,)`. mtime was **removed** on 2026-06-19 because it ticks
without a content change (flushes, touches, filesystem timestamp granularity) and produced
only false `"raced"` skips. The stated justification for size-only: *a live transcript is
append-only, so any change we must not clobber grows the file.*

That reasoning is correct for Claude Code. It is **not** correct for a second instance of
these tools, which rewrite in place and can produce a same-size result. There is no lock
on the transcript itself — only on the manifest. Two concurrent reclaim operations on one
transcript are guarded by nothing that can detect them.

### 6.5 `rehydrate` (`:726-803`)

Loads the manifest for the given namespace (default `"offload"`), **skips every
`kind:"engram"` record** (`:756` — those belong to `lib_engram`), splits the rest into
id-keyed tool-content restores and locator-keyed embed restores, then walks every record:
a stubbed `tool_result.content` or a stubbed `tool_use.input[key]` is replaced by
`read_exact` of its manifest record; embeds are restored by `(line, path)` navigation
(`_nav_set:719`).

Note the asymmetry with `lib_engram.rehydrate_engram`: this one does **not** fail closed.
`read_exact` can raise `BodyIntegrityError` mid-loop, aborting after some records have
been mutated in memory but before `commit` — so nothing is written and the transcript is
safe, but the caller gets an exception rather than a problem list. Embed failures are
swallowed entirely (`:796`) and simply not counted. A replacement should make the two
rehydrate paths behave alike.

### 6.6 Classification (`:196-380`)

`is_turn_start` (`:197`) is the canonical turn boundary: **a record with a non-null
`promptSource`**. The docstring records the measurement that motivated it — the old
structural heuristic reported 16 turns where `promptSource` reports 12, the four extras
being an `isCompactSummary` record and three "continued from a previous conversation"
continuation records. It asserts that every turn-numbering surface delegates here.

**That assertion is false for the packaged `lib_engram`**, which still uses its own
structural heuristic (`lib_engram.py:219`). See `lib_engram_design.md` §6.2. The
docstring is stale with respect to the file shipped next to it — a finding, not a nit.

`classify_record` (`:313`) returns one of
`attachment | system | skill | agent_result | injected | tool | user | assistant`. The
distinctions that matter: a client-injected `isMeta` user record carrying a
`sourceToolUseID` is a **skill expansion** (a 600 KB skill dump must not be bucketed as a
~2-token bookkeeping record — `:270`); an `origin.kind == "task-notification"` record is a
subagent result; any other `isMeta` user record is generic injected content. A record whose
content blocks are *purely* `tool_use`/`tool_result` is a `tool` record and is
offload-eligible; a record mixing text with a `tool_use` is not, because skipping it would
drop the text (`:288`).

`human_turn_indices` (`:349`) prefers `read_jsonl.parse_session` and maps
`m.source_line - 1` to raw record positions. The comment at `:358-360` records the bug
this fixed: `m.line_number` is the *message ordinal*, not the file line, and using it was
"the recency-window bug" — the protected window was computed against the wrong positions.
The fallback (parser unavailable) is `is_turn_start`.

`protect_from_index` (`:373`) turns a `keep_last_turns` count into "index at or after which
everything is protected verbatim."

### 6.7 Intervals and branches (`:806-1109`)

An interval is a **line range**. Interval 0 is the prologue (lines 1 .. first event − 1,
possibly empty); interval k spans event k's start line to event k+1's start line − 1; the
last interval is the live region. A compaction event's start line is the `isCompactSummary`
line, extended back one line if the immediately preceding record is a
`system`/`compact_boundary` (`:852-860`).

`select_intervals` (`:908`) parses the shared spec grammar: an integer, `last`/`live`,
`all`, comma lists, `lo-hi` ranges, and **negatives meaning offset from live** — `-1` is
one interval *before* live, not Python's from-the-end indexing (`:934-937`). That is an
unusual choice and it is documented in place; a replacement that "fixes" it to Python
semantics will silently change what every existing `--interval` invocation selects.

The **branch model** (`:980-1109`) narrows an interval to its live `parentUuid` chain,
`br0`. Fork enumeration is an explicit stub: `interval_branches` (`:1053`) returns only
`br0`, and `select_branches` errors clearly for anything else rather than silently
returning live (`:1104-1107`). The concept, the flag and the default exist now; `v1.1` is
marked TODO in the code.

### 6.8 `analyze` (`:1162-1248`)

A read-only region map: `pre_compaction` (before the last **substantive** compaction
summary — one rendering at least `MIN_SUMMARY_CHARS = 2000`, so a ~700-char continuation
marker does not count), `live_offloadable` (after that, outside the recency window — the
real lever), `live_protected` (the last N turns). Per region it counts lines, content
chars, offloadable results/inputs, already-stubbed blocks, and embedded images.

Image cost is tallied **separately** as vision tokens ≈ `w*h/750`, flat 1500 when
dimensions cannot be read (`_image_vision_tokens:1146`), explicitly so embeds are not
conflated with character-derived `off_tokens` (`:1226-1228`). That separation is a real
correctness property; the two constants are approximations of Anthropic's published
behavior and will drift.

## 7. Essential vs incidental

### Essential

- **Portable, path-free stub references** and the fork-safe archive naming. Absolute paths
  here would break every forked transcript.
- **Per-mechanism namespaces** with legacy-ownership fallback. The cross-contamination bug
  this fixed corrupted rehydrate.
- **Content hashing on write, verification on read, `BodyIntegrityError` on mismatch**,
  with the decoded value attached for a deliberate salvage path.
- **`commit`'s byte-identical untouched lines and compact separators.** Without these the
  byte-exact reversibility claim is false.
- **Write ordering:** body durable → manifest durable → transcript. And `os.replace` as
  the only way the transcript is ever swapped.
- **A one-time backup that is never overwritten** — provided callers understand it is one
  snapshot per transcript lifetime, not per operation.
- **The manifest lock's steal rule** (dead pid *or* stale), and its non-reentrancy being
  documented.
- **One canonical turn-start predicate, one canonical record classifier, one interval
  numbering, one branch model** — the value is that tools cannot disagree. If a
  replacement splits this file (recommended), these must stay single-sourced.
- **`is_tool`'s refusal to classify a mixed text+tool_use record as a tool record.**
- **Vision tokens counted separately from character-derived tokens.**
- **Lazy imports of `read_jsonl` and `scrub_files`** — they are cycle-breakers, not style.

### Incidental

- The file being **one module**. It is four modules (see the recommendations file).
- `MIN_BYTES = 512` and `KEEP_LAST_TURNS = 5` — tuned defaults, not contracts.
- `tokens() = bytes/4` — explicitly under review; see "Work in flight".
- The `"[…] stripped:"` entries in `STUB_PREFIXES` (`:38-40`), which correspond to the
  destructive `--mode strip` path. If strip is dropped, these stay only for reading old
  transcripts.
- `legacy` bare-id archive directories and the `namespace=None` resolution path — a
  migration affordance.
- `_manifest_ownership`'s heuristic (`:395`).
- `analyze`'s exact region names and output shape.
- The private-name imports other modules rely on (`_stat_sig` is imported by
  `lib_engram:56` and `chain_skip`): the underscore is meaningless here — these are public
  API in practice.

## 8. Platform notes (Tier A / B / C per `DESIGN.md`)

- **Tier B — `_fsync_dir` (`:57`).** `os.open(dir, O_RDONLY)` then `fsync` is a POSIX
  idiom. On native Windows this raises and is swallowed, so **rename durability silently
  disappears**. This is the file's clearest `platform_compat` candidate: a `durability`
  adapter with a POSIX branch and a Windows branch (`FlushFileBuffers` on the file handle;
  directory metadata durability has no direct equivalent), plus a capability flag so a
  caller can know it is degraded. WSL is fine.
- **Tier B — `_pid_alive` (`:69`).** `os.kill(pid, 0)` works on Windows Python for
  existence checks but the error taxonomy differs. Belongs in a `process` adapter (one
  already exists per `DESIGN.md`).
- **Tier B — `manifest_lock` (`:558`).** `os.mkdir` atomicity holds on NTFS, but
  `os.rmdir` on a directory another process has open fails on Windows, and a crashed
  holder's `owner.json` may be locked. The repo already plans a `platform_compat/locking`
  module (msvcrt vs fcntl); this lock should move behind it.
- **Tier A — `os.replace` over an open file.** On POSIX, replacing a file another process
  holds open is fine. On native Windows, `os.replace` fails with a sharing violation if
  the target is open without `FILE_SHARE_DELETE`. Claude Code's open-append-close-per-write
  pattern makes the window small but non-zero. Needs a retry-with-backoff wrapper at
  minimum; a real fix is platform-specific.
- **Tier A — temp file naming.** `.jarch_tmp_*` / `.manifest_tmp_*` land in the same
  directory as the target (required for atomic replace). Orphans accumulate after a crash
  and nothing sweeps them.
- **Tier A — line endings.** `commit` joins with `"\n"` and `atomic_write` writes bytes
  through `os.write` (`:118`), so there is no newline translation. **A replacement must
  not switch to text-mode writes**; on Windows that would rewrite every line ending and
  destroy the byte-identical guarantee.
- **Tier A — case sensitivity.** `resolve_archive_dir`'s glob (`:440`) and the
  `KNOWN_NAMESPACES` head match are case-sensitive; on a case-insensitive filesystem two
  archive directories differing only in case would collide. Not reachable today (all
  generated names are lowercase hex) but worth pinning.
- **Tier A — timestamps.** None generated here except lock `started_at` (epoch float,
  portable).
- **WSL specifically.** Everything above works on WSL. The one real WSL hazard is a
  transcript on a `/mnt/c` DrvFs path, where `fsync`, `os.replace` and `mkdir` locking are
  all weaker than on ext4. If Windows-hosted transcripts are in scope, that needs testing.

## 9. Risks & sharp edges

1. **Size-only CAS (§6.4).** The only guard against a concurrent writer, and blind to any
   same-size in-place rewrite.
2. **Best-effort `fsync` everywhere.** Every durability boundary can silently become a
   no-op. The two-phase commit's crash-recovery guarantees rest on these.
3. **Stale-lock stealing at 120s.** A legitimately slow holder (large manifest on a slow
   volume, a debugger) gets its lock stolen and two writers proceed. `rewrite_manifest` is
   atomic per call, so the result is last-write-wins on the whole manifest — one writer's
   records can vanish.
4. **`rewrite_manifest` requires the caller to hold the lock and does not check.** A
   caller that forgets loses records under concurrency, silently.
5. **`rehydrate` does not fail closed** and swallows embed failures (§6.5).
6. **Temp-file orphans** after a crash, never swept.
7. **The `analyze`/`human_turn_indices` pair calls `read_jsonl.parse_session`, which
   re-parses the whole file** — so `analyze` parses the transcript twice. Fine for
   interactive use, a real cost in a hook on a 100 MB transcript.
8. **`wire_size` counts characters, not bytes**, while the token divisor is described in
   bytes. On ASCII-heavy transcripts the difference is ~1%; the in-flight calibration
   measured 207,812 characters against 209,532 UTF-8 bytes over one sample.
9. **`find_compactions` and `records_with_lines` open and re-read the file** on every
   call, separately from every other reader. Several tools call several of these in
   sequence.
10. **`_manifest_ownership` mis-adopts a mixed legacy archive**: a directory containing
    both engram and offload records satisfies neither `belongs` test (`:465-466`), so a
    fresh directory is minted and the legacy content becomes invisible to the new
    namespace. Silent, and arguably correct, but surprising.

## 10. Work in flight — **do not read this file as settled design**

Active work lives in `ai_root/ai_general/work/experiments/t2_context_agency/`.

1. **`tokens(nbytes) = bytes/4` is measured wrong in both directions.**
   `FINDING_bytes_per_token.md` (2026-07-30) measures, against real `message.usage` ground
   truth, ~2.74 characters/token for message content and ~5.37 characters/token for whole
   wire records — so `/4` **understates** content cost and **overstates** wire cost.
   `TOKEN_ESTIMATOR_CALIBRATION.md` fits a calibrated estimator across 58,135 labeled
   pairs from 277 transcripts.
2. **But the ruling is: do not change it.** `DESIGN_RULING_TOKEN_ESTIMATOR_CONSUMERS.md`
   (2026-07-31, Codex): *"Do not replace or change the signature of
   `lib_jsonl_archive.tokens(nbytes)` and do not propagate the current calibrated point
   estimate into pageout selection."* The calibrated estimator may be exposed **beside**
   the legacy one in read-only/shadow output. A future record-aware estimator must be a
   **second, structured API**; this byte-count helper remains an explicitly degraded
   compatibility fallback. `ADVERSARIAL_REVIEW_TOKEN_CALIBRATION_RESIDUE_GATE.md`
   (2026-07-31) rejects the five calibration claims as worded.
3. **A record-aware estimator (`lib_token_estimate.py`) exists upstream** and is not in
   this package. A re-designer should expect `tokens()` to gain a sibling, not a
   replacement.
4. **The archive-and-stub mechanism itself is retired upstream** (todo_0692, cutover
   2026-07-27). `chain_skip.py` reclaims by pure `parentUuid` re-pointing with **no
   archive and no stub**. What survives from this file upstream is exactly the parts that
   are not about archiving: `is_turn_start`, `classify_record`, `_stat_sig`,
   `atomic_write`, `ensure_backup`, the interval model. That is strong independent evidence
   for the split recommended in the recs file.
5. **Classification is under audit.** `CLASSIFICATION_AUDIT_20260801.md` (Plumb, review
   pending) ran the classifier across 246 transcripts / 589,050 records and reports
   duplicate-uuid counts and active-chain counts. Note it evaluates **the last record for
   a duplicated uuid**, "matching the current production `by_uuid` behavior" — i.e.
   duplicate uuids are real and the last-write-wins choice is load-bearing.
6. **Branch enumeration `v1.1`** (fork enumeration beyond `br0`) is unbuilt and marked in
   code (`:1058`, `:1106`).
7. **todo_0707 (mutation-frame integrity)** and **todo_0708 (restore CAS)** are open at
   REQUEST_CHANGES. todo_0708's review specifically criticises "a fingerprint check
   followed by a replace, called compare-and-swap, when those are two separate
   operations" — which is exactly what `commit:705-715` does.
