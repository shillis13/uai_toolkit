# platform_adapters/common.py — recommendations for the re-design

Small file, but three of the four functions have something wrong with them.

## 1. Collapse the three duplicate timestamp normalizers into one

Three implementations of the same idea are live today:

- `common.normalize_timestamp` (common.py:14) — handles `None`, millisecond threshold
  `1_000_000_000_000`, returns `""` for unknown types.
- `read_jsonl._normalize_timestamp` (read_jsonl.py:713) — no `None` case, threshold written as
  `1e12`, otherwise identical.
- `standardized_session._compact_json` (standardized_session.py:14) is likewise a byte-identical
  duplicate of `common.compact_json`.

Pick one home. `common.py` is the natural one if the adapters are the only users; a shared
`text_utils`/`common_utils` module if `read_jsonl` also needs it. Duplicated numeric heuristics
diverge — these two already differ in whether `None` is handled.

## 2. Make "no timestamp" distinguishable from "bad timestamp"

`normalize_timestamp` returns `""` for `None`, for an unparseable type, and for a genuinely empty
string. Every adapter then uses truthiness as the "has a timestamp" test
(`if ts: ... start_time = ts`, e.g. claude.py:66-69, codex.py:64-67, agy.py:131-134,
grok.py:192-195). Result: a record with a malformed timestamp is silently treated as a record
with no timestamp, and it neither sets `start_time` nor advances `last_updated`.

Return `None` for absent and raise (or return a sentinel the caller must handle) for malformed.
The downstream cost of a wrong timestamp is real: `read_jsonl.group_by_day` buckets it under
`"Unknown"` and `_sort_messages_by_ts` sorts it as `datetime.min`, so a bad value quietly
reorders the transcript.

## 3. Do not emit naive local times

`datetime.fromtimestamp(value).isoformat()` (common.py:20) produces a timezone-*naive* local
string for epoch inputs, while string inputs pass through carrying their original `Z` or offset
(common.py:21-22). Both end up in the same `Message.timestamp` field, and
`read_jsonl._ts_to_local` (read_jsonl.py:722) then converts the tz-aware ones and leaves the naive
ones alone — so the two kinds are displayed consistently only because the naive ones were already
local. Any cross-platform comparison or sort mixing the two is wrong.

Emit timezone-aware ISO strings (`datetime.fromtimestamp(value, tz=timezone.utc).astimezone()`)
so every value in the field means the same thing. Display stays local per the project rule; the
stored value stops being ambiguous.

## 4. Delete `path_contains`, or make it the one path-matching primitive

`path_contains` (common.py:38) has no callers. Meanwhile all four path-based `sniff`
implementations inline exactly what it does — `needle in str(path.resolve())` — with POSIX-only
separators that never match on native Windows.

Best outcome: keep the function, teach it to normalize separators (compare `Path.parts`, or
`str(path).replace("\\", "/")`), and make every adapter call it. That fixes the family's
Windows detection defect in one place. Second best: delete it as dead code. Leaving an unused
correct-shaped helper next to five inlined broken copies is the current state and the worst one.

## 5. Reconsider `join_text_parts`

One caller (grok.py:94), which immediately re-implements a superset of its behavior when it
returns empty (grok.py:96-104). Either fold it into Grok, or widen it to be the family's single
"flatten a content field to text" helper — Claude (claude.py:170-179), Codex (codex.py:99-104),
and Gemini (gemini.py:32-43) each carry their own near-duplicate of that logic today. The second
option is the better one; those four near-duplicates differ in which block types they accept,
which is exactly where per-platform content silently goes missing.

## 6. Note for the re-designer: `agy.py` imports `compact_json` and never uses it

agy.py:13. Harmless, but it is the visible symptom of `agy` being the one adapter without
`to_platform_text` — the import was copied from a sibling. See the family recommendations.
