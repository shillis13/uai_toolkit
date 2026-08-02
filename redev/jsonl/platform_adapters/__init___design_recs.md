# platform_adapters/__init__.py — recommendations for the re-design

These are family-level recommendations; per-adapter items live in the sibling `_recs` files.

## 1. Finish or formally abandon the adapter contract

`~/bin/ai/jsonl/DESIGN_platform_adapter_contract.md` is marked *"DRAFT for convergence"* and
specifies six per-adapter functions. Two exist (`sniff`, `from_file`); four do not
(`classify`, `is_turn_start`, `compaction_points`, `structure`). The consequence, today, is that
`read_jsonl._chain_and_prompt_meta` (read_jsonl.py:839-968) reads Claude's `uuid`, `parentUuid`,
`promptSource`, `isCompactSummary`, and `logicalParentUuid` fields directly, and every non-Claude
platform falls back to increment-on-user-message turn numbering (read_jsonl.py:997-1008) with no
chain or interval concept at all.

The re-design is the moment to decide. Either:

- **Complete the contract** — move the Claude predicates into `claude.py`, implement the Codex
  half already specified in that document (turn starts from `turn_id`, intervals from `compacted`
  envelopes, always a single branch), and let the engine be platform-agnostic. This is the plan
  the document describes and it is coherent.
- **Or scope down honestly** — declare turn/chain/interval analysis Claude-only, and make the
  other adapters return sessions that carry no turn structure rather than a plausible-looking
  fallback. The current fallback produces turn numbers for Codex and Grok that *look* like
  Claude's but mean something different.

Do not ship the current half-state. The document itself flags the trap: Claude's reclaim/offload
semantics rest on the `parentUuid` tree, which Codex does not have, and rendering Claude-shaped
numbers for Codex "would look comparable while meaning something fundamentally different".

## 2. Make `sniff` order explicit rather than positional

Detection precision is encoded as tuple position (__init__.py:41-47), explained by a two-line
comment that covers two of the five adapters. Grok additionally hand-codes negative checks
against its neighbours (grok.py:66-69) — the same de-confliction expressed twice, in two
different mechanisms.

Recommendation: have each adapter declare its own precedence (a module constant, or a
`sniff` that returns a confidence rather than a bool) and sort in the registry. Then adding a
platform does not require reasoning about where in a literal tuple it belongs, and Grok's
negative checks can go away.

## 3. Add an explicit "unknown" outcome

`detect_platform` returns `"claude"` when nothing matched (__init__.py:50). Callers cannot tell a
real Claude transcript from an unrecognized file. `lib_engram` (lib_engram.py:84-90) documents
this rather than handling it.

Return `None` (or `"unknown"`) and let callers decide. `read_jsonl` can keep defaulting to Claude
for backward compatibility; `lib_engram` and anything doing destructive work should refuse.

## 4. Fix the two Tier-A portability defects here, once, for the whole family

- **Path separator.** All four path-based sniffs test POSIX substrings and match nothing on
  native Windows. `common.path_contains` (common.py:38) exists for this and is unused by every
  adapter. Either make the adapters use it and teach it to normalize separators, or delete it and
  put the normalization in a single shared `_path_marker(path, marker)` helper.
- **Encoding.** `_first_json_object` (__init__.py:22-23) reads with the platform default encoding
  and catches `UnicodeDecodeError` into a silent `None`, which then routes the file to the
  `claude` fallback. Add `encoding="utf-8"` — and consider *not* swallowing decode errors, since
  a transcript that will not decode is a real problem, not a detection hint.

## 5. Guard the sniff loop

`detect_platform` calls five third-party-ish functions with no `try` (__init__.py:48). One
adapter raising on a malformed record breaks detection for every file, including files it has no
claim on. Wrap each call and treat an exception as "no match" — but log it, because a raising
sniff is a bug.

## 6. Make `"standardized"` a real registry entry

`detect_platform` can return `"standardized"`, but `ADAPTERS` has no such key, so
`adapter_for_platform("standardized")` raises `ValueError` and every caller must special-case it
(read_jsonl.py:1022, 1027-1028 — twice in one function). Give the standardized format an adapter
module with the same `sniff`/`from_file` shape and the special case disappears.

## 7. Make `to_platform_text` a decided part of the contract, not an accident

Four adapters implement it; `agy.py` does not. Its only caller is a round-trip test, and every
implementation short-circuits to re-emitting the stored `raw_text` when source records are
present, so the hand-built reconstruction branches are effectively untested dead code.

Decide: either it is part of the contract (then `agy` must implement it, and the reconstruction
branches need tests that exercise them by dropping `source_records`), or it is not (then delete
all four and the test, and the standardized model stops pretending to be bidirectional).
Carrying an inconsistently-implemented, never-called, mostly-untested interface into a re-design
is the worst of the three options.
