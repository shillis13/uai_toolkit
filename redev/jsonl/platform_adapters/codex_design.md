# platform_adapters/codex.py — redevelopment design

Scope: `src/uai_toolkit/jsonl/platform_adapters/codex.py` (230 lines). Adapter for Codex CLI
"rollout" transcripts.

## 1. What it is for

Translate a Codex CLI session (`~/.codex/sessions/**/rollout-<date>-<uuid>.jsonl`, plus
`~/.codex/archived_sessions/`) into the shared `StandardizedSession` model, and back. Codex's
format is a flat event log of typed envelopes, structurally quite different from Claude's
message tree.

## 2. Interface — and the family contract it implements

```python
PLATFORM = "codex"                                           # codex.py:15
sniff(path: Path, first_obj: Any | None = None) -> bool      # codex.py:18
from_file(path: str | Path) -> StandardizedSession           # codex.py:29
to_platform_text(session: StandardizedSession) -> str        # codex.py:179
```

All four members of the family contract are present. **What `sniff` must guarantee** (family
rules in `__init___design.md`): cheap, no re-read of the file, never raises, tolerant of
`first_obj is None`.

```python
# codex.py:19-24
"/.codex/" in str(path.resolve()) or path.name.startswith("rollout-")   # path signals
first_obj["type"] in {session_meta, response_item, event_msg, turn_context}  # content signal
```

**Detection order matters.** Codex is tried third, after `agy` and `grok`
(`platform_adapters/__init__.py:41-47`). It must stay ahead of `claude`, because a Codex
`response_item` line nests a `payload` that Claude's sniff would not claim — but Codex records
under a `.codex` path are unambiguous, so the real ordering constraint is the other direction:
`grok` explicitly rejects Codex's four type names (grok.py:68-69) so that Grok, which runs
*before* Codex, cannot steal a Codex file. That negative check in Grok is what allows Codex to sit
third rather than second.

## 3. Integration

- **Called by**: `platform_adapters/__init__.detect_platform` and `read_jsonl.parse_session`.
- **`to_platform_text`**: no production caller; exercised only by
  `~/bin/ai/jsonl/tests/test_standardized_adapters.py` against the fixture
  `~/bin/ai/jsonl/test_files/codex_tool_call.jsonl`, which asserts byte-exact round-trip and the
  presence of a `tool_use` and a `meta` record.
- **Depends on**: `standardized_session`, `platform_adapters.common`
  (`compact_json`, `normalize_timestamp`).

Unlike `claude.py`, this adapter has **no dependency on `lib_jsonl_archive`** — there is no
classification delegation, because Codex has no `isMeta` / `sourceToolUseID` / `origin` analogue
(the contract document states this explicitly).

## 4. Data & config

Reads the transcript one line at a time (codex.py:38). Writes nothing. No environment variables.

## 5. How it works

### 5.1 `from_file` (29-175)

Single pass. Every parseable line gets a `StandardizedSourceRecord` carrying verbatim `raw_text`,
the parsed object, the timestamp, `platform_type = entry["type"]`, and — unique to this adapter —
`platform_subtype = payload["type"]` (codex.py:51-61). The two-level type is Codex's shape: an
outer envelope type and an inner payload type.

Malformed lines are skipped silently (45-46), same defect as Claude: no source record, so
round-trip would drop the line.

Message extraction handles exactly two envelope types:

- **`session_meta`** (69-85) → stores the whole payload as `session_payload` for the header, and
  emits **one synthetic `meta` message** whose text is
  `f"Session {payload['id']} ({payload.get('originator', 'codex')})"`. This is a *rendered
  string*, not source content — it exists so the session's identity is visible in a message
  stream. Note it consumes a `msg_seq`.
- **`response_item`** (87-160), branching on `payload["type"]`:
  - `message` (91-122) — role mapped: **`developer` → `system`** (93); anything not in
    `{user, assistant, system}` is skipped. Content may be a string, or a list of blocks whose
    `type` is in `{input_text, output_text, text}` joined with newlines (99-104). **Blocks of any
    other type are dropped**, including `input_image`, which the contract document names as
    Codex's attachment mechanism. Empty text skips the record entirely (107-108).
  - `function_call` (123-143) → `tool_use`. `arguments` is a JSON **string** that is parsed;
    on failure it becomes `{"raw": arguments}` (124-128) rather than being lost. `tool_call_id`
    comes from `call_id`.
  - `function_call_output` (144-160) → `tool_result`, `content_text` from `output`.
- **Every other envelope type — `event_msg`, `turn_context`, and anything new — produces a source
  record and no message** (87-88). The contract document says these should map to `meta` so their
  bytes are counted; today they simply are not.

Header (162-174): `session_id` from `session_payload["id"]`, falling back to **the last 36
characters of the filename stem** (163) — the UUID tail of `rollout-<date>-<uuid>`. The whole
`session_meta` payload is preserved in `platform_metadata`.

### 5.2 `to_platform_text` (179-230)

- If source records exist, re-emit their `raw_text` in sequence order. Exact.
- Otherwise reconstruct: one synthetic `session_meta` line from the header (185-193), then one
  `response_item` per message. Roles are mapped back (`system` → `developer`, 200-201) and the
  content block type is chosen by role (`input_text` for user/developer, `output_text` for
  assistant, 206). `meta` records are skipped (196-197). Tool inputs are re-serialized to a JSON
  string via `compact_json` (214), matching Codex's string-typed `arguments`.

This branch cannot be exact — it drops `event_msg` and `turn_context` lines entirely (they were
never messages) and invents timestamps from the message records.

## 6. Essential vs incidental

**Essential**

- Recognizing the `rollout-` filename prefix. Codex archives can be moved out of `~/.codex`, and
  the prefix is then the only path signal.
- The two-level `platform_type` / `platform_subtype` on source records. Codex's semantics live in
  the payload type, not the envelope type.
- `developer` → `system` role mapping in both directions. The contract document fixes this:
  developer-role prompt injections are `system`, not `injected`.
- Parsing `function_call.arguments` from its JSON-string form, with the `{"raw": …}` fallback
  rather than dropping a call whose arguments will not parse.
- `session_id` falling back to the filename's UUID tail — a rollout file with no `session_meta`
  line (a truncated or in-progress session) still gets an identity.
- Preserving the full `session_meta` payload in `platform_metadata`; it carries `originator`,
  `thread_source`, `parent_thread_id`, which the contract document says are how Codex represents
  subagents.

**Incidental**

- The synthetic `meta` message built from an f-string (79-80). It is a display convenience that
  occupies a message slot and has no source text; `to_platform_text` has to special-case it back
  out (196-197).
- The hand-reconstruction branch of `to_platform_text` — untested, lossy.
- `metadata={"source_line_count": …}` and `roundtrip={"strategy": …}` — set, never read.

## 7. Platform notes (Windows / WSL)

- **Tier A — `"/.codex/" in str(path.resolve())`** (codex.py:19). POSIX separator; never matches
  on native Windows. The `rollout-` prefix test (same line) is separator-independent and does
  still work, so Codex detection degrades less badly than Gemini's or Grok's — but only for files
  that kept their original name.
- **Tier A — no explicit encoding** on `path.open()` (codex.py:38). Platform default; on Windows
  a non-ASCII transcript raises out of `from_file` uncaught.
- **Tier A — `line.rstrip("\n")`** (40) leaves `\r` on CRLF files, inside `raw_text`.
- Nothing Tier B or C.

## 8. Risks & sharp edges

- **Three envelope types are parsed into nothing.** `event_msg`, `turn_context`, and `compacted`
  (named in the contract document as Codex's compaction marker) produce source records but no
  messages. The direct consequence: `read_jsonl` has **no way to find compaction intervals in a
  Codex transcript**, so `--interval` and every interval-scoped number silently treat a Codex
  session as a single interval. Whether that is a deliberate deferral or an oversight is unknown —
  the contract document specifies the intended behavior but no code implements it.
- **`tool_result` records are given `role="assistant"`** (codex.py:152). This is inconsistent with
  the rest of the family: `claude.py:186` uses `"user"` (matching its wire format), while
  `grok.py:352` and `agy.py:246` use `"tool"`. Three different roles for the same concept across
  four adapters. Anything filtering by `role` rather than `message_type` gets platform-dependent
  results. Rationale unknown — needs an owner's answer.
- **Non-text content blocks are dropped**, including `input_image`. Codex carries attachments as
  inline content blocks (per the contract document's §2 response), so images in a Codex session
  are invisible to every consumer.
- **Turn numbering is wrong-shaped for Codex.** The contract document specifies that Codex turn
  numbers should come from the record's `turn_id` field, treated as first-class. No code reads
  `turn_id`. `read_jsonl._chain_and_prompt_meta` finds no `promptSource` and returns empty sets,
  so `_assign_turn_numbers` falls back to increment-on-user-message
  (read_jsonl.py:997-1008). The resulting `Tn` values *look* like Claude's and mean something
  different. **This is the single most misleading thing about the Codex path.**
- **Malformed lines vanish** (45-46), as in Claude.
- **`path.stem[-36:]`** (163) assumes a 36-character UUID tail. A renamed file shorter than that
  yields a truncated or nonsense id, with no check.
