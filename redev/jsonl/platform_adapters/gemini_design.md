# platform_adapters/gemini.py — redevelopment design

Scope: `src/uai_toolkit/jsonl/platform_adapters/gemini.py` (416 lines). Adapter for Gemini CLI
sessions. The largest adapter, because Gemini has **three** distinct on-disk shapes.

## 1. What it is for

Translate a Gemini CLI session into the shared `StandardizedSession` model, and back. Unlike the
other four adapters, this one is not a single format reader: it dispatches on file suffix and
then on the shape of the top-level JSON.

## 2. Interface — and the family contract it implements

```python
PLATFORM = "gemini"                                          # gemini.py:15
sniff(path: Path, first_obj: Any | None = None) -> bool      # gemini.py:18
from_file(path: str | Path) -> StandardizedSession           # gemini.py:322
to_platform_text(session: StandardizedSession) -> str        # gemini.py:335
```

All four contract members present. Private helpers: `_extract_text_from_content` (32),
`_message_record_from_gemini_message` (47), `_from_snapshot_json` (172),
`_load_jsonl_conversation` (230), `_from_jsonl` (274).

**What `sniff` must guarantee** (family rules in `__init___design.md`): cheap, no re-read, never
raises, tolerates `first_obj is None`. Gemini's:

```python
# gemini.py:19-27
"/.gemini/" in str(path.resolve())                    # path signal
isinstance(first_obj, list)                           # ← claims ANY top-level JSON array
{"sessionId", "projectHash"} <= set(first_obj.keys()) # snapshot header
first_obj.get("$set")                                 # event-log marker
```

**Detection order matters, and this sniff is the reason it matters most.** Gemini is tried
fourth, after `agy`, `grok`, and `codex` (`platform_adapters/__init__.py:41-47`). The bare
`isinstance(first_obj, list)` test would otherwise claim any JSON-array file in existence. Its
position behind three narrower adapters is the only thing containing it — and it does not contain
it enough. See §8.

## 3. Integration

- **Called by**: `platform_adapters/__init__.detect_platform` and `read_jsonl.parse_session`.
- **`to_platform_text`**: no production caller; exercised by
  `~/bin/ai/jsonl/tests/test_standardized_adapters.py` against two fixtures —
  `gemini_legacy_snapshot.json` and `gemini_event_log.jsonl` — asserting byte-exact round-trip.
  Gemini is the only adapter with two fixtures, because it has two file shapes.
- **Depends on**: `standardized_session`, `platform_adapters.common`.
- **Discovery**: `read_jsonl` looks for Gemini sessions at
  `~/.gemini/tmp/**/session-*.json` (read_jsonl.py:102-103, 636-638) — note the glob expects the
  `session-` prefix and a `.json` suffix, so `.jsonl` event logs found by that path are *not*
  discovered by `find_jsonl`, only by direct path.

## 4. Data & config

Reads the transcript. `_from_snapshot_json` and `_from_jsonl` both use `path.read_text()`, i.e.
**the whole file into memory at once** (gemini.py:173, 275, 328) — unlike Claude/Codex/Grok/AGY,
which stream line by line. Writes nothing. No environment variables.

## 5. How it works

### 5.1 Format dispatch — `from_file` (322-331)

```
suffix == ".jsonl"  → _from_jsonl(path)                     # event-log form
otherwise           → json.loads(read_text()) → _from_snapshot_json(path, data)
                      on JSONDecodeError    → _from_snapshot_json(path, [])   ← silently empty
```

### 5.2 Snapshot form — `_from_snapshot_json` (172-226)

Two sub-shapes, distinguished at runtime:

- **dict** (182-188) → `platform_variant = "gemini_json_snapshot"`. Header fields come from
  `sessionId`, `projectHash`, `startTime`, `lastUpdated`, `kind`; messages from `data["messages"]`.
- **list** (189-195) → `platform_variant = "gemini_json_legacy_list"`. The bare array *is* the
  message list; `session_id` comes from the first message's `sessionId`, `start_time` from the
  first message's timestamp and `last_updated` from the last.

Both produce **exactly one source record** holding the entire file text (197-204), which is what
makes the round-trip exact for this form: `to_platform_text` re-emits `source_records[0].raw_text`
(337-338). The header records `roundtrip={"strategy": "emit_source_text", "json_style": "pretty-2"}`
(224) — a note that the reconstruction path, if used, must indent by 2 to match.

### 5.3 Event-log form — `_from_jsonl` (274-318) and `_load_jsonl_conversation` (230-270)

This is Gemini's mutable-log format: lines are *operations*, not messages. `_load_jsonl_conversation`
replays them:

- **`$rewindTo`** (240-253) — truncate the conversation back to the named message id, dropping it
  and everything after. **If the id is not found, the entire conversation is cleared** (249-252).
- **`$set`** (254-256) — merge into session metadata.
- A record with `sessionId` and `projectHash` but no `id` (257-259) — session header, merged into
  metadata.
- Anything with a string `id` (260-267) — a message. **Re-appearance of an id updates the existing
  message in place** and appends another source id, rather than adding a second message. So Gemini
  messages are *edited*, and the adapter honors that.

The result is an ordered list of `(id, message, source_ids)` reflecting the log's final state.
Every raw line still becomes a source record (284-294), tagged with `platform_subtype` of `$set`
or `$rewindTo` where applicable — so round-trip re-emits the full operation log including the
operations that were replayed away.

### 5.4 Message conversion — `_message_record_from_gemini_message` (47-168)

Per Gemini message `type`:

- **`user`** (53-71) → one `user` record. Text from `content` (string or list-of-`{text}`), with a
  fallback to a top-level `message` string field (55-56).
- **`gemini`** (73-152) → potentially many records, in this order: the response text
  (74-89), then each entry of `thoughts` as a `thinking` record rendered as
  `f"{subject}: {description}"` (91-111), then for each `toolCalls` entry a `tool_use` record
  (113-130) immediately followed by a `tool_result` record built from `resultDisplay` if present
  (131-151). Both tool records get `role="assistant"`.
- **`info` / `error` / `warning` / `meta`** (154-167) → one record, role `system`, with
  `message_type = "system"` for `error` and `"meta"` for the other three.
- **Any other type** → nothing.

**Sequence-number bug**: the function takes `msg_seq` as a parameter and increments a *local* copy
as it emits (89, 111, 130, 151), while the caller advances by `len(created)`
(gemini.py:209-211, 313-316). Those agree only because every increment corresponds to exactly one
appended record — which holds today, but the two counters are maintained independently and
nothing enforces the invariant. Note also that the *first* record of each message reuses the
incoming `msg_seq` without incrementing first, so the local and caller counters are offset by one
in opposite directions; the net result happens to be correct.

### 5.5 `to_platform_text` (335-416)

Three branches: snapshot (re-emit stored text, or rebuild a pretty-printed dict, 336-373);
source-record re-emit for the event log (375-377); and a hand reconstruction that emits a header
line plus, for each message, its record **followed by a synthetic `{"$set": {"lastUpdated": …}}`
line** (388-415) — mimicking how the Gemini CLI writes.

## 6. Essential vs incidental

**Essential**

- Handling all three shapes. Real Gemini installations have snapshot `.json`, legacy bare-array
  `.json`, and event-log `.jsonl` files side by side.
- `$rewindTo` replay. Without it, a rewound Gemini session shows messages the user removed.
- Id-based message *update* semantics (260-267). Gemini rewrites messages in place; treating each
  line as a new message would duplicate them.
- One-source-record-holds-whole-file for the snapshot forms — the basis of exact round-trip there.
- Emitting `thoughts` as `thinking` records so the `[/PRIVATE]` filter and thinking accounting
  apply.
- The `platform_variant` distinction (`gemini_json_snapshot` / `gemini_json_legacy_list` /
  `gemini_jsonl_event_log`) — it is the only record of which shape was read.

**Incidental**

- The `f"{subject}: {description}".strip(": ")` thought rendering (96) — a display choice baked
  into stored content.
- The parallel `msg_seq` accounting (§5.4).
- The hand-reconstruction branches of `to_platform_text`.
- `metadata={"source_record_count": …}` — set, never read.

## 7. Platform notes (Windows / WSL)

- **Tier A — `"/.gemini/" in str(path.resolve())`** (gemini.py:19). POSIX separator; never matches
  on native Windows. Combined with §8's over-broad content test, Windows detection of Gemini files
  rests entirely on `isinstance(first_obj, list)` or the `{sessionId, projectHash}` pair.
- **Tier A — no explicit encoding** anywhere: `path.read_text()` at 173, 275, 328. Platform
  default. Uncaught `UnicodeDecodeError` on Windows for non-ASCII content — except at 327-330,
  where a `JSONDecodeError` (but not a decode error) is caught and turned into an empty session.
- **Tier A — whole-file reads.** `read_text()` on a large session is a memory spike the other
  adapters do not have.
- **Tier A — `splitlines()`** (275) handles CRLF correctly, unlike the other adapters'
  `rstrip("\n")`. Worth copying rather than fixing.
- Nothing Tier B or C.

## 8. Risks & sharp edges

- **The sniff claims any top-level JSON array.** `if isinstance(first_obj, list): return True`
  (gemini.py:21-22). Reproduced on this machine: `~/.gemini/tmp/**/vba_exports.json` — an
  unrelated data file — is classified `gemini` by `detect_platform` and parsed by `from_file`
  into a session with **zero message records**, with no error. Any JSON array file anywhere
  behaves the same. This is the family's most dangerous sniff.
- **A malformed `.json` file silently becomes an empty session.** `from_file` catches
  `JSONDecodeError` and calls `_from_snapshot_json(path, [])` (327-330). A truncated or corrupt
  transcript reports "0 messages" rather than an error, and the caller cannot distinguish that
  from an empty session.
- **An unresolvable `$rewindTo` erases the whole conversation.** `_load_jsonl_conversation`
  (249-252): if the target id is not in the current order, it clears `message_order`,
  `message_map`, and `message_sources` outright. On a file whose head was trimmed, the rewind
  target is legitimately absent and the entire session parses to nothing. Rationale unknown —
  needs an owner's answer; "clear everything" is a surprising choice for "I could not find the
  rewind point".
- **`tool_use` and `tool_result` both get `role="assistant"`** (gemini.py:120, 142). Fourth
  variation in the family: Claude uses `user` for results, Codex uses `assistant`, Grok and AGY
  use `tool`.
- **No `tool_result` when `resultDisplay` is absent or falsy** (131). A tool call that returned an
  empty string produces an orphan `tool_use` with no matching result.
- **`session_id` fallback is `path.stem[-8:]`** for the event-log form (298) and `path.stem` for
  snapshots (174) — two different conventions in one adapter.
- **No compaction, chain, or turn structure**, same as Codex: `read_jsonl` finds no `promptSource`
  and falls back to increment-on-user-message turn numbering.
- **Malformed lines in the event log are skipped silently** (280-282), so round-trip would drop
  them.
