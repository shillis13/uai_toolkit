# lib_engram.py — redevelopment design

**File:** `src/uai_toolkit/jsonl/lib_engram.py` (1,483 lines, no CLI — library only)
**Read at:** 2026-08-01, package copy. Compared against the live source
(`ai_root/ai_general/scripts/jsonl/lib_engram.py`, 1,560 lines) — **they have diverged
materially; see "Work in flight".**

## Terms used here

- **Transcript** — the Claude Code session file, one JSON object per line
  (`~/.claude/projects/<proj>/<sessionId>.jsonl`).
- **Active chain** — the records reachable from the conversational leaf by walking
  `parentUuid` upward. This, not file order, is what the model reloads on `--resume`.
  Records off the chain still sit in the file but are invisible to the model.
- **Turn** — one human prompt plus everything up to (not including) the next human prompt.
- **Engram** — the unit this file invents: the archived bytes of one consolidated
  turn-range plus the summary **stub** left in its place on the active chain.
- **Stub** — the replacement text written into the first record's `message.content`. It
  carries a header, a machine-readable `<<<ENGRAM_META …ENGRAM_META>>>` block, and the
  human-readable summary.
- **CAS** — compare-and-swap: fingerprint the file before reading, re-check before
  writing, refuse to write if it changed.
- **Reclaim ladder** — see the section of that name below.

---

## 1. What it is for

`lib_engram` is the **Summarize** rung of the context-reclaim ladder. It takes a
contiguous range of old turns on a session's active chain, archives every record in that
range byte-exactly into a sidecar directory, overwrites the range's first record with a
first-person summary stub, and re-points the next turn's `parentUuid` at that stub — so
the whole range falls off the active chain and stops being reloaded on `--resume`. It
also provides the inverse (`rehydrate_engram`, byte-exact restore), a read-only page-in
(`recall`), a read-only sizing primitive (`chain_size`), an advisory eviction planner
(`plan_eviction`), and three maintenance operations (`repair_manifest`,
`slim_engram_stubs`, `gc_archive`).

It is the **highest-stakes file in this package**: it performs a lossy-but-reversible
edit of the user's real conversation.

## 2. The reclaim ladder (the core design idea)

Per-file docs obscure this, so it is repeated in each of the five docs. The five scripts
are rungs of one ladder, ordered by how much is lost and how disruptive the recovery is:

| Rung | Mechanism | Loss | Reversal | Owner in this package |
|---|---|---|---|---|
| **Offload** | page bulky tool results / tool inputs off the chain | none (lossless) | rehydrate from archive | `lib_jsonl_archive.rehydrate` (+ `scrub_files` embeds); the tool-content offloader itself is **not shipped in this package** |
| **Bounce** | stop + resume the *same* session so a disk edit is actually realized | none | n/a (a bounce reclaims nothing by itself) | `resume_note.py`, `session_bounce/*` |
| **Summarize** | collapse a whole turn-range into a summary stub | lossy (turns → gist) but **reversible** | `rehydrate_engram` (disk undo) or `recall` (live page-in) | **`lib_engram.py`** + `summarizer.py` |
| **self-compact** | model-authored brief + `/compact` | lossy, **no bring-back** | none | `deferred_self_compact.py` |
| **compact** | the harness's own `/compact` | lossy, no bring-back | none | not ours |

Two properties bind the whole ladder and must survive any re-design:

1. **Every disk-side rung is inert until the next `--resume`.** A running process sends
   its in-memory message list, not the file. Editing the transcript reclaims nothing
   *now*. That is the entire reason the Bounce rung exists.
2. **Rungs are ordered by loss, and the cheap ones come first.** Offload is free reclaim
   and needs no judgment; Summarize costs a model-written summary and loses resolution;
   self-compact loses everything not in the brief. A replacement that lets a caller reach
   for Summarize before Offload has broken the design.

## 3. Interface

No CLI, no `__main__`. Pure library. In the live source tree a CLI wrapper
(`memory_manager.py`) exposes these as subcommands (`consolidate`, `rehydrate`, `recall`,
`map`, `chain-size`, `plan-eviction`, `slim`, `gc-archive`) — **that wrapper is not in
this package**, so today the only callers are Python importers.

Public functions (all take a transcript path first):

| Function | Kind | Returns |
|---|---|---|
| `consolidate(jsonl, first_uuid, summary_text, *, level, volatile, dry_run, leaf_uuid, leaf_policy, repair, through_uuid)` (`:481`) | **writes** | `{"ok":True,"engram":{…},"orphaned":n}` \| `{"error":…}` \| `{"raced":True}` |
| `summarize(...)` (`:700`) | alias | identical — thin passthrough to `consolidate` |
| `rehydrate_engram(jsonl, first_uuid=None, *, engram_id, dry_run, force, force_partial, allow_corrupt)` (`:713`) | **writes** | `{"ok":True,"restored":n[,"partial":True,"problems":[…]]}` \| `{"error":…}` \| `{"raced":True}` |
| `recall(jsonl, first_uuid=None, *, engram_id, max_bytes, allow_historical, allow_partial, allow_corrupt, leaf_uuid, leaf_policy)` (`:1148`) | read-only | `{"ok":True,"text":…,"turns":n,"tokens":n,…}` \| `{"error":…}` |
| `chain_size(jsonl, leaf_uuid=None, *, leaf_policy)` (`:857`) | read-only | byte/token breakdown + selected leaf |
| `plan_eviction(jsonl, *, need_tokens, keep_recent_turns=3, strategy="oldest"\|"largest", leaf_uuid, leaf_policy)` (`:912`) | read-only, **advisory** | `{"selected":[…],"total_freed_tokens":n,"feasible":bool,…}`; raises `ValueError` on a bad strategy (`:952`) or an unresolvable explicit leaf (`:961`) |
| `active_chain(jsonl, leaf_uuid=None, *, leaf_policy)` (`:312`) | read-only | list of records, root→leaf |
| `repair_manifest(jsonl, *, dry_run)` (`:1276`) | writes manifest | `{"repaired":[…],"count":n,"skipped":[…]}` |
| `slim_engram_stubs(jsonl, *, dry_run)` (`:1330`) | **writes transcript** | `{"ok":True,"slimmed":n,"total_saved":bytes,…}` |
| `gc_archive(jsonl, *, dry_run, grace_seconds=60)` (`:1408`) | deletes archive files | `{"removed":[…],"referenced":n,…}` |

Helpers other modules import: `is_engram_stub` (`:129`), `parse_stub_meta` (`:141`),
`select_active_leaf` (`:231`), `ENGRAM_STUB_PREFIX` (`:61`).

**Error convention:** these functions never raise for expected failures — they return an
`{"error": …}` dict. Two exceptions break the convention: `plan_eviction` raises
`ValueError` (`:953`, `:963`). A replacement should pick one convention; today a caller
must handle both.

**`{"raced": True}` is not an error and not a success.** It means the transcript changed
under the read, nothing was written, and the caller should retry later. Callers that only
check `res.get("ok")` silently treat a race as a failure (`reclaim_and_stage.py:108`
files it under `errors[]`, which is at least visible).

## 4. Integration

**Callers inside this package**
- `session_bounce/reclaim_and_stage.py:73,76,100,112,151,196` — `plan_eviction`,
  `chain_size`, `consolidate`. This is the primary consumer: plan → agent writes
  summaries → enact.
- `session_bounce/bounce_watch.py:70,105` — `chain_size` for the wake-verify yardstick.
- `jsonl/resume_note.py:76` — `chain_size` for every token number in the resume note.
- `jsonl/read_jsonl.py:1253` — imports `ENGRAM_STUB_PREFIX` only, lazily, to detect stubs
  when rendering (a deliberate lazy import to avoid a cycle, `read_jsonl.py:1237`).
- `mcp/sessions/tools/context_ops.py` — exposes `context_summarize_plan/_enact`,
  `context_recall`, `context_rehydrate`, `context_consolidate_plan/_enact` (deprecated
  aliases). **It reaches these by subprocess into `$AI_ROOT/ai_general/scripts/…`, not
  into the installed package** (`context_ops.py:38-49`). On a machine that has only the
  package installed, those MCP tools cannot work. See §8.

**What it calls**
- `lib_jsonl_archive` (`:56`) for everything durable: `Archive`, `commit`, `_stat_sig`,
  `sha8`, `tokens`, `wire_size`, `render_readable`, `BodyIntegrityError`,
  `human_turn_indices`.
- `platform_adapters.detect_platform` (`:77`) for the Claude-only write guard.

## 5. Data & config

No environment variables. No configuration of any kind. Everything is derived from the
transcript path.

| Artifact | Path | R/W | Format | Who else touches it |
|---|---|---|---|---|
| Transcript | the path passed in | read + **rewrite in place** | JSONL, one record per line | Claude Code appends to it live; `chain_skip`/`scrub_files`/offloaders also rewrite it |
| Archive dir | `<transcript_dir>/<stem>.engram.<uuid8>.archive/` | create + write | directory | `lib_jsonl_archive.resolve_archive_dir` owns naming; `read_jsonl --resolve` reads it |
| Body files | `<archive>/engram.<engram_id>.<n>.txt` and `.json` | write, read, delete | text / JSON | `gc_archive` deletes unreferenced ones |
| Manifest | `<archive>/offload_manifest.jsonl` | append + atomic rewrite | JSONL, one record per engram, `kind:"engram"` | shared file format with the offload namespace, but a **separate directory** per namespace |
| Lock | `<archive>/offload_manifest.jsonl.lock/` (a directory) + `owner.json` | mkdir/rmdir | — | `lib_jsonl_archive.Archive.manifest_lock` |
| Backup | `<transcript>.jsonl.bak` | created once | JSONL | shared with every other mutator; **one backup per transcript, ever** (`lib_jsonl_archive.ensure_backup:99`) |

**State outlives code.** A replacement inherits transcripts that already contain engram
stubs and archives that already contain bodies. The two durable formats it must keep
reading are the stub text format (`:620-624`) and the manifest record (`:626-643`), both
versioned by `SCHEMA_VERSION = 1` (`:64`) — though see the note on slim bodies in §6,
where version is deliberately *not* the discriminator.

## 6. How it works

### 6.1 Leaf and chain selection (`:219-325`)

Everything is computed on the **active chain**, never on file order. `select_active_leaf`
(`:231`) picks the last non-`isSidechain` `user`/`assistant` record, because real
transcripts routinely end in `system` records (`stop_hook_summary`, `turn_duration`) or,
for subagents, sidechain tails — the naive "last record in the file" leaf walks the wrong
branch. `_chain_records` (`:260`) then walks `parentUuid` upward, guarding against cycles
and missing parents, and returns the chain root-first plus a `break_reason`.

An explicit `leaf_uuid` may be a **unique prefix** (`:274-280`). This exists because the
CLI and MCP surfaces display 8-character prefixes and invite "prefix OK"; exact-only
matching silently produced an empty chain and a zero-reclaim no-op exactly when a
pressured session reached for the lever (cited as todo_0632). An ambiguous prefix is an
explicit error, never a guess.

### 6.2 Turn boundaries — **a live inconsistency**

`_is_human_prompt` (`:219`) is a *structural heuristic*: a top-level, non-sidechain
`type=="user"` record whose content is not a `tool_result`.

`lib_jsonl_archive.is_turn_start` (`lib_jsonl_archive.py:197-227`) documents that this
heuristic was **replaced** by a non-heuristic signal (a non-null `promptSource` field),
because the heuristic over-counted: 16 "turns" against 12 real prompts on one measured
transcript, the four extras being a compaction summary and three continuation records.
That docstring asserts "every turn-numbering surface delegates HERE" and lists the
offload/summarize engine among them.

**In this packaged copy, `lib_engram` does not delegate.** It uses its own heuristic at
`:538`, `:552`, `:556`, `:573`, `:970`, `:1118`. The upstream source has already fixed
this (`ai_general/scripts/jsonl/lib_engram.py:211-213` now returns `is_turn_start(rec)`).
So the packaged copy will disagree with `read_jsonl`'s displayed turn numbers on any
transcript containing a compaction boundary or a continuation record, and
`plan_eviction`'s `keep_recent_turns` window will protect the wrong turns. **This is a
real defect in the shipped file, not a documentation nit.**

### 6.3 `consolidate` — the page-out (`:481-697`)

1. **Refuse non-Claude transcripts** (`:510`). `_refuse_if_not_claude` (`:82`) fails
   *closed*: if `platform_adapters` cannot be imported at all, it refuses rather than
   risking a write to (e.g.) a Codex transcript with a different record shape. Read-only
   operations are deliberately exempt.
2. **Refuse an ambiguous fork** (`:524-528`) unless an explicit `leaf_uuid` is supplied.
   `_has_ambiguous_fork` (`:343`) only trips when two sibling subtrees *each* contain a
   human prompt — this deliberately ignores the off-chain body branch that `consolidate`
   itself creates, so re-consolidating an existing stub (an engram of engrams) is not
   mistaken for a fork.
3. **Select the range** on the chain: from `first_uuid` (which must be a human-turn start
   on the chain) through the record before the next human prompt. With `through_uuid`
   (`:546-553`) the span covers several whole turns collapsed into one engram.
4. **Refuse to summarize the present** (`:555-558`): if there is no following human turn,
   there is no successor pointer to re-route, so the live tail can never be consolidated.
5. **Verify the successor actually chains to the segment tail** (`:566-569`) unless
   `repair=True`.
6. **Mint an engram id** `<first_uuid8>.<random8>` (`:575`). Every body slug derives from
   it (`engram.<engram_id>.<n>`), so consolidating the same `first_uuid` twice can never
   overwrite the first engram's bodies. The docstring calls this "the recursion /
   source-immutability fix" (`:20`).
7. **Write bodies, then `fsync` the archive directory** (`:584-592`) so the bodies are
   durable *before* anything references them.
8. **Two-phase commit** — this is the crash-recovery design (`:502-504`):
   bodies → append manifest record with `state="prepared"` (`:654`) → rewrite the
   transcript (`:673`) → flip the manifest record to `"committed"` (`:679`).
   - Manifest append fails ⇒ delete bodies, transcript untouched (`:655`).
   - Transcript commit fails or races ⇒ flip to `"aborted"` and delete bodies (`:693`).
   - Transcript committed but the state flip fails ⇒ **do not claim committed**
     (`:683-691`): return `ok` with `manifest_state:"prepared"` and a warning. Recall and
     rehydrate by `first_uuid` still work off the live stub; `repair_manifest` finishes
     the flip later.
9. **The stub** (`:620-624`) is `header \n <<<ENGRAM_META {json} ENGRAM_META>>> \n summary`.
   The embedded metadata (`:602-619`) is the **transcript-only recovery path**: even with
   the manifest destroyed, the stub alone carries `engram_id`, `range_uuids`, `next_uuid`,
   `orig_parent_of_next`, per-body hashes, and the summary hash.
10. **Only two records are marked dirty** (`:672`): the stub-bearing record and the
    successor whose `parentUuid` moves. Every other line stays byte-identical
    (`lib_jsonl_archive.commit:713`).

**Slim bodies** (`:173-215`, cited as todo_0363): the inline metadata used to carry the
full per-body manifest records, ~86% of which was derivable. Now only `sha8` and
`exact_kind` are inline; `_hydrate_body` (`:193`) reconstructs `slug`, `body_uuid`, etc.
positionally at read time. **Detection is structural, not versioned** — a body lacking a
`"slug"` key is slim (`:180`, `:203`) — deliberately, so old "fat" stubs keep working.
The on-disk manifest stays full; only the in-context copy shrinks.

### 6.4 `rehydrate_engram` — the disk undo (`:713-853`)

Resolution order for the target engram: explicit `engram_id` → the live stub's embedded
`engram_id` → most recent committed record for `first_uuid` (`:746-754`). If the manifest
is gone entirely, the parsed stub metadata *is* the engram record (`:751`).

Three guards, each with its own override:
- **Handle validation** (`:760-774`, unless `force`): the live `first_uuid` record must
  still be an engram stub, its `engram_id` must match, and the **summary hash must
  match** — an edited stub summary must not silently rehydrate.
- **Fail-closed pre-checks** (`:780-813`, unless `force_partial`/`allow_corrupt`): every
  range record present, body count equal to range length, successor present, every body
  readable. Any problem aborts **before a single byte is written**.
- **Integrity** (`:798-806`): `Archive.read_exact` re-hashes each body and raises
  `BodyIntegrityError` on mismatch. Default = abort. `force_partial` = skip that body
  (its stub stays, result marked `partial`). `allow_corrupt` = write the corrupt body
  anyway and flag it loudly.

On full success the manifest record is **removed** (`:847`); on partial it is kept and
marked `"partial"` (`:851`).

### 6.5 Reversibility — the exact contract

This is the most important paragraph in this document.

**What round-trips byte-exactly:** the *records* in the archived range. Each is written
whole to the archive (`consolidate:584-591`), and restored by wholesale replacement
(`:817-825`). Untouched lines in the transcript are never re-serialized
(`lib_jsonl_archive.commit:713`), and touched lines are re-serialized with Claude Code's
own compact separators, so a record whose content is logically unchanged comes back
byte-for-byte.

**Where it is lossy:** the *summary* replaces the original first record's content in the
model's view. Until you rehydrate, the model sees a gist. That is the intended trade.

**Where loss becomes permanent — enumerate these, a replacement must not add to the list:**

1. **`gc_archive` deletes bodies** (`:1408-1483`). It keeps bodies referenced by
   committed / partial / prepared records and deletes the rest. If a manifest record was
   lost or corrupted while its stub is still live, its bodies look unreferenced and are
   deleted — after which the stub is unrestorable. The 60-second `grace_seconds` window
   (`:1456-1459`) only protects bodies written in the last minute (the
   bodies-written-but-manifest-not-yet-appended window).
2. **`--mode strip` at the Offload rung** (a `lib_jsonl_archive` concept, `STUB_PREFIXES`
   includes `"[tool result stripped:"`, `:37-41`) discards instead of archiving. Not
   reachable through `lib_engram`, but it shares the transcript.
3. **The single `.jsonl.bak`** (`lib_jsonl_archive.ensure_backup:99`) is created **once,
   ever, per transcript** and never overwritten. After the first mutation of a session's
   life, the backup is a snapshot of that moment, not of the state before the *current*
   operation. It is not a rollback mechanism for operation N>1.
4. **`allow_corrupt=True`** deliberately writes a hash-mismatched body into the
   transcript (`:804`). That is a salvage path; it destroys the evidence that the body
   was wrong.
5. **An external process appending during the write.** The CAS guard
   (`lib_jsonl_archive.commit:705`) compares a **size-only** fingerprint taken twice
   around the read against the size at write time. A microsecond gap remains between the
   final `stat` and `os.replace`. A same-size change is undetectable by construction —
   the justification (`lib_jsonl_archive.py:84-96`) is that a live transcript is
   append-only so any change we must not clobber grows the file. That reasoning holds for
   Claude Code itself and **does not hold for another instance of these very tools**
   running concurrently, which rewrite in place at the same size. There is no
   cross-process lock on the transcript (only on the manifest).

**Not verified by me:** I did not run a round-trip test. The package ships no tests for
this file (`uai_toolkit/tests/` contains only `smoke_test`, `test_llm_endpoints`,
`test_tracker_concurrency`). The live source tree has an extensive suite
(`ai_general/scripts/jsonl/tests/`, ~450 tests per the in-flight review notes) that is
**not** materialized into the package.

### 6.6 `recall` — the live page-in (`:1148-1272`)

Read-only: it renders the archived bodies as text for the caller to surface as a tool
result. Nested stubs are expanded recursively to level 0 (`_render_bodies:1076`,
`max_depth=8`), with a `seen` set against cycles. It fails closed on any missing or
corrupt body unless `allow_partial`/`allow_corrupt`, and marks the header `INCOMPLETE`
when it proceeds anyway (`:1246-1250`).

One deliberate asymmetry: **thinking-block `signature` fields are dropped from the recall
rendering** (`:1063`) because an encrypted reasoning signature is inert outside a live
thinking block. The archive keeps them, so byte-exact Restore is unaffected — only the
model-facing render is lossy. A replacement must preserve exactly this split.

### 6.7 `chain_size` and `plan_eviction` — the numbers

`chain_size` (`:857`) reports `content_tokens_estimate` = `tokens(sum of message.content
wire sizes on the chain)`, plus separate `system_bytes`, `attachment_bytes`,
`envelope_bytes`. Its own docstring is careful (`:859-869`): these are **content-byte
heuristics, not what the model actually carries**. This number is nevertheless the
yardstick for the entire Bounce rung (`resume_note.py:74-78`, `bounce_watch.py:70`).

`plan_eviction` (`:912`) is **advisory and never writes**. Candidates are chain human
turns that are not already stubs, that have a successor, and that fall outside the last
`keep_recent_turns`. Each candidate's value is `tokens(sum(wire_size))` of its segment —
the same number `consolidate` records — so the plan and the act agree with each other
(they may still both be wrong; see "Work in flight"). Strategy `oldest` evicts
least-relevant first; `largest` reaches the target in fewest evictions at the cost of
dropping big recent context (`:934-944`).

Note the two functions use **different bases**: `chain_size` counts `message.content`
only, `plan_eviction` counts whole-record wire size including the JSON envelope. So
`chain_tokens_after_est` (`:1015`) subtracts a wire-size number from a content-size number.
Rationale unknown — needs an owner's answer. The in-flight `CONTRACT_SEAM.md` reviewed
this seam and concluded the *gate* is internally consistent (it uses wire/4 on both of its
inputs) while wake verification uses content/4 on both of its inputs — two consistent
contracts rather than one broken comparison — but `plan_eviction`'s own
`chain_tokens_after_est` field still mixes them.

## 7. Essential vs incidental

### Essential — a replacement must preserve these

- **Chain-native selection.** Ranges, candidates and sizes computed on the active chain,
  not file order. File-order logic silently includes dead forks.
- **Never consolidate the live tail.** The "no successor ⇒ refuse" rule (`:555-558`) is
  what makes the operation safe to run on a session that is still alive.
- **`keep_recent_turns` protection** of the freshest turns (`:979`).
- **Fail-closed everywhere.** Missing body, corrupt body, hash mismatch, non-Claude
  transcript, unavailable platform detection, ambiguous fork — all refuse rather than
  guess. The overrides (`force`, `force_partial`, `allow_corrupt`, `allow_historical`,
  `repair`) must stay opt-in and must stay *loud* in the result.
- **The two-phase commit and its failure ordering.** Bodies durable → pointer durable →
  transcript → state flip. Any reordering creates a window where a stub exists with no
  recoverable bodies.
- **Self-describing stubs.** The embedded metadata must remain sufficient to recall and
  rehydrate with the manifest destroyed. This is the single best property of the design.
- **Content hashing of bodies** and the summary hash on the stub.
- **Byte-identical untouched lines** and compact JSON separators on touched lines.
- **Unique engram ids so a re-consolidation cannot overwrite an earlier engram's bodies.**
- **The Claude-only write guard**, failing closed when detection is unavailable.
- **Signatures dropped from recall but kept in the archive.**
- **`plan_eviction` is advisory.** It must not acquire the power to enact.

### Incidental — free to change

- The name "engram" and the `consolidate`/`summarize` double naming (`:700-709`). One
  name.
- The stub's exact text format, the `<<<ENGRAM_META …>>>` delimiters, and the
  slim/fat body split — all internal, provided old stubs still parse.
- `SCHEMA_VERSION` (`:64`) — it is carried but never actually branched on; slim detection
  is structural (`:180`).
- The `sys.path` insertion at `:52-54`. Vestigial: every import in the file is already
  absolute (`uai_toolkit.jsonl.…`).
- The mixed error convention (dict vs `ValueError`).
- `slim_engram_stubs` (`:1330`) — a one-off migration of already-written stubs. If the
  replacement never writes fat stubs, this is dead on arrival except for legacy files.
- `level` and `volatile` parameters (`:482`): carried into the record and echoed by
  `recall` as a warning, but nothing in this package sets them. Their intended policy
  role is not determinable from the code — rationale unknown, needs an owner's answer.
- `gc_archive`'s 60-second grace window value.
- The `repair=True` escape hatch on `consolidate` (`:566`).

## 8. Platform notes (Tier A / B / C per `DESIGN.md`)

- **Tier A (fix inline).** All file I/O is `pathlib` + explicit `encoding="utf-8"`
  already. `commit` joins with `"\n"` and appends a trailing newline
  (`lib_jsonl_archive.py:715`) — text is written through `os.write` on bytes, so no
  newline translation. Good as-is; a replacement must not switch to text-mode writes on
  Windows or every line ending changes and no line stays byte-identical.
- **Tier A.** `datetime.now().isoformat()` (`:595`) is local time with no offset —
  matches the workspace convention, but it means manifest timestamps from two machines in
  different zones are not comparable.
- **Tier B (belongs in `platform_compat/`).** Everything durable this file relies on lives
  in `lib_jsonl_archive`: directory `fsync` (a no-op/error on Windows), the `mkdir`-based
  manifest lock, and the `os.kill(pid, 0)` liveness probe. See that file's doc.
- **Tier B.** Case sensitivity: archive dirs and body files are named from uuids
  (lowercase hex) so no collision risk, but `resolve_archive_dir`'s glob
  (`lib_jsonl_archive.py:440`) is case-sensitive on Linux and not on Windows — harmless
  today, a trap if slugs ever carry mixed case.
- **Tier C (degrade).** None in this file itself. But the **MCP integration is currently
  platform-and-layout-bound**: `mcp/sessions/tools/context_ops.py:38-49` shells out to
  `$AI_ROOT/ai_general/scripts/…`, a source-tree layout that a WSL install of the package
  will not have, and to scripts (`memory_manager.py`, `chain_skip.py`,
  `check_resume_integrity.py`) that are **not in the package at all**. A re-design must
  decide whether the MCP layer calls the library directly or whether those CLIs get
  materialized.
- **Concurrency.** The manifest lock is per-archive-directory and does not protect the
  transcript. Two tools mutating the same transcript at once are guarded only by the
  size-only CAS.

## 9. Risks & sharp edges

1. **Turn-boundary divergence (§6.2).** The shipped copy counts turns differently from
   `read_jsonl` and from upstream. Highest-priority correctness item.
2. **Size-only CAS.** An in-place rewrite by a sibling tool that preserves file size is
   invisible. Cross-tool safety rests on an assumption ("the transcript is append-only")
   that is false when two of these tools run concurrently.
3. **One backup, ever.** `.jsonl.bak` is not per-operation. Operators who believe "there
   is always a backup" are wrong from the second mutation onward.
4. **`gc_archive` is destructive and takes only a path.** A manifest that lost a record —
   the exact scenario the stub-embedded metadata exists to survive — becomes
   unrecoverable once gc runs.
5. **Partial commit states are user-visible.** `manifest_state:"prepared"` with
   `recovered_by_stub:True` (`:684-691`) means "the edit happened, the ledger is behind."
   `--engram-id` lookup does not work until `repair_manifest` runs. Any replacement needs
   an operator-facing way to notice this; nothing in the package surfaces it today.
6. **Recursion depth.** `recall` expands nested engrams to depth 8 (`:1078`). At depth 8
   it silently stops expanding and renders the stub text instead — no problem is
   recorded. A deeply re-consolidated session degrades quietly.
7. **`consolidate` mutates the caller's parsed records in place** (`:663-669`) before the
   commit decision. Harmless today (they are re-read each call), but a caller that reuses
   the list would be surprised.
8. **`_uuid_index` (`:124`) is last-write-wins on duplicate uuids**, and `_chain_records`
   (`:266`) is explicitly last-write-wins too. Real transcripts do contain duplicate
   uuids (the in-flight classification audit measures duplicate counts across 246
   transcripts). Which duplicate you get determines which content is archived.

## 10. Work in flight — **do not read this file as settled design**

Active experimental work lives in
`ai_root/ai_general/work/experiments/t2_context_agency/`. The following bear directly on
this file:

1. **This mechanism has been retired upstream.** The live source
   (`ai_general/scripts/jsonl/lib_engram.py:1-7`) is now titled *"Compatibility readers
   for legacy archived Engram stubs"*: `consolidate()` and its `summarize` alias
   `raise NotImplementedError` (`:494`), cited as **todo_0692, cutover 2026-07-27**.
   New reclaim goes through **`chain_skip.py`** (2,146 lines, not in this package):
   *pure `parentUuid` re-pointing with no archive and no stub*, where Restore is the
   reverse pointer write and is byte-exact by construction because nothing ever moves.
   `offload_tool_results.py` was retired the same way. **A re-designer must not port the
   content-overwrite Summarize forward without first reading `chain_skip.py`.** What
   survives upstream from this file is `recall` + `rehydrate_engram` (to read/restore
   stubs already on disk), `chain_size`, `plan_eviction`, and `select_active_leaf`.
2. **The balance invariant (`chain_skip.py:19-27`).** A skip must remove a `tool_use` and
   its `tool_result` together. Not because the API rejects an orphan — Claude Code's
   resume sanitizer *silently repairs* the imbalance by dropping the whole assistant
   message carrying the orphaned `tool_use`, reasoning text included. Verified empirically
   2026-07-12 with headless `claude --resume`. This is a hard-won constraint that this
   package's copy does not encode anywhere.
3. **Token estimation is under active dispute.** `DESIGN_RULING_TOKEN_ESTIMATOR_CONSUMERS.md`
   (2026-07-31): do not change `tokens(nbytes)`'s signature, and **do not let the
   calibrated estimate drive page-out selection**. `PLAN_EVICTION_RANGE_REVIEW.md`
   (2026-07-30) rules that projected reclaim **cannot authorize an automatic bounce** —
   the only licensed universal lower bound on realized reclaim is zero — and names
   `reclaim_and_stage.py`'s consumption of `total_freed_tokens` as the unsafe path.
   Automatic authorization was withdrawn in commit `2d5c904d`.
4. **Net reclaim ≠ removed turn size.** `FINDING_wholeturn_calibration.md`: upstream
   `chain_skip.summarize_turn` splices a live user+assistant *residue pair* back onto the
   chain, so real reclaim is `removed − residue`. `plan_eviction` models only the first
   term. A "summarize-residue gate" is being designed; treat any residue-free projection
   as an overstatement.
5. **`FINDING_offload_accounting.md`:** for every tested *split* assistant-response shape
   (one API response stored as several JSONL records sharing a `message.id`), removing a
   `tool_use` yielded **zero** measured prompt reduction. Upstream now fails closed on
   split groups. Nothing in this package knows about response groups.
6. **`FINDING_overhead_floor.md`:** reclaim touches the transcript only. System prompt,
   MCP tool schemas, skill descriptions and injected instructions are additive and
   untouchable — measured at 253k tokens of non-transcript overhead in one live session,
   which tripled across a bounce as the tool catalog reloaded.
7. **todo_0707 (frame integrity) and todo_0708 (restore CAS)** are open design/review
   items on the mutation ledger and the restore path. Both are at REQUEST_CHANGES.
