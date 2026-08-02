# standardized_session.py — recommendations for the re-design

Companion to `standardized_session_design.md`. Line citations are against
`src/uai_toolkit/jsonl/standardized_session.py` unless another path is given.

This module is the healthiest of the four in this review. The recommendations are
narrow, and one of them is a decision rather than a fix.

---

## Decide first

### 1. Keep the persistence half, or delete it — do not port it as-is

**The situation.** `write_standardized_session` (246-249), `to_jsonl_text` (237-239),
`all_envelopes` (230-235), and `source_record_map` (241-242) have **no callers anywhere
in the package**. Neither does `StandardizedEventRecord` (180-220). That is roughly 90
of 306 lines that are defined, coherent, and never exercised. Every Tier A portability
defect in the module lives in exactly that unexercised code.

**Why it is a decision and not a fix.** The in-memory half — the dataclasses as an
intermediate representation between adapters and `read_jsonl` — is genuinely
load-bearing and works. The on-disk half is a designed format with no producer, no
consumer, and no file. Porting it forward means carrying untested serialization code
into a new platform where its four encoding defects will finally bite.

**Recommendation.** Ask the owner what the writer was for. Then either:

- **Complete it** — fix items 3-6 below, add a round-trip test, and name the feature it
  serves; or
- **Delete it** — keep only the dataclasses, `load_standardized_session`, and
  `is_standardized_session_file`, which is all anything actually uses.

Deciding this first makes the rest of the list either necessary or moot.

**Before either path:** confirm no standardized file exists outside this repository —
written by the source tree's `lib_standardized_session.py`, by a companion tool, or by
hand. I searched this package only. If such files exist, the schema name (8) and the
format become a migration problem instead of a free change.

---

## Fix

### 2. Enforce the schema version, or stop writing it

`STANDARDIZED_SCHEMA_VERSION = "1.0"` (9) is emitted into every envelope (36, 87, 135,
194) and **never checked** — `load_standardized_session` validates the schema name
(264-265) and ignores the version entirely.

Combined with recommendation 7 below (unknown message types are silently dropped), a
future `2.0` file would load into `1.0` structures and quietly lose records. Two silent
failures compounding.

**Recommendation.** On load, compare the major version and refuse a file the code was
not written for, with a message naming both versions. A version field nobody checks is
worse than no version field, because it implies a safety that does not exist.

### 3. Set the encoding explicitly on every file operation

Three sites, all defaulting to the platform encoding:

| Line | Call | Failure on Windows |
|---|---|---|
| 248 | `path.write_text(...)` | `UnicodeEncodeError` — cp1252 cannot encode most non-ASCII, and `_compact_json` deliberately sets `ensure_ascii=False` (15) so real Unicode reaches the encoder |
| 260 | `path.read_text()` | fails or silently mis-decodes a UTF-8 file |
| 293 | `path.open()` | see recommendation 4 |

`encoding="utf-8"` on all three. This is the same defect class as `scrub_files.py:221`
and `scrub_files.py:665` — worth fixing package-wide in one pass rather than file by
file, since a mismatched read/write pair is a corruption path, not just a failure.

### 4. `is_standardized_session_file` must not raise

It catches `(OSError, json.JSONDecodeError)` (304). `UnicodeDecodeError` is a subclass
of `ValueError`, not of either, so it **propagates** out of a function whose entire
contract is to return a boolean. On Windows, a UTF-8 transcript with non-ASCII content
would crash the detector instead of returning `False` — and this function is called
early, from `platform_adapters/__init__.py:36`, before any other detection runs.

**Recommendation.** Fix the encoding (item 3), and also widen the catch to `ValueError`
so a decoder surprise can never turn a predicate into an exception.

### 5. Pin the line ending when writing

`write_text` (248) without `newline=""` lets Python translate `"\n"` to `"\r\n"` on
Windows, so the same session written on Windows and on WSL produces byte-different
files. `lib_jsonl_archive` depends on byte-identical untouched lines
(`lib_jsonl_archive.py:698`) and stubs carry content hashes, so this is not cosmetic.

**Recommendation.** `open(path, "w", encoding="utf-8", newline="")`, writing `"\n"`
explicitly.

### 6. Write atomically

`write_text` (248) truncates in place. A crash mid-write leaves a truncated session
file. Two atomic-write helpers already exist in the same package —
`scrub_files._atomic_write` (`scrub_files.py:613-636`) and
`lib_jsonl_archive.atomic_write` — and neither is used here. Moot while nothing calls
the writer; mandatory the moment something does.

### 7. Stop dropping unknown message types silently

Not in this file, but it is this schema's failure mode.
`read_jsonl._standardized_to_messages:769-772` does `MessageType(record.message_type)`
inside a bare `except ValueError: continue`. Any message whose type the `MessageType`
enum does not recognize — a new vendor block type, a typo, a value from a newer schema
version — vanishes with no warning, no counter, and no log line. Message counts shrink
and nothing says why.

**Recommendation.** Count the skipped records and report them on stderr, or map unknown
types to an explicit `unknown` `MessageType` member so they stay visible. Silence is the
wrong default for data loss.

### 8. Validate types, not just presence

Decoding is `.get()` with defaults throughout (66-69, 112, 169-176, 217-219). A
`sequence` arriving as a string decodes fine and then raises `TypeError` inside
`sorted()` (283-285), far from its cause.

Being permissive about **missing** fields is correct and should be kept (vendors add
fields without warning). Being permissive about **wrong types** just moves the failure
somewhere unhelpful. Coerce or reject the few fields that must be a specific type —
`sequence`, `timestamp`, `role`, `message_type` — at decode time.

### 9. Skip bad lines instead of failing the whole file

`load_standardized_session` raises on the first line with a mismatched `schema` (265) or
an unknown `record_kind` (276), so one corrupt line makes an entire session unloadable.
`is_standardized_session_file` inspects only the first line (293-303), so a file with a
good header and one bad record **passes detection and then fails to load** — the worst
combination.

Transcripts are appended to by live processes and are routinely truncated mid-line.
`scrub_files.scan_attachments` (`scrub_files.py:228-231`) and `lib_jsonl_archive` both
skip undecodable lines and continue; this module should match them, and report a count
of what it skipped.

---

## Tidy

### 10. Hoist the header envelope out of the message loop

`read_jsonl._standardized_to_messages:787` calls `session.header.to_envelope()` once per
message. On the 27,000-message transcript present in `~/.claude/projects` on this
machine, that builds and retains 27,000 identical 12-key dictionaries through
`Message.raw`. One line moved above the loop. A `read_jsonl` change, but a direct cost of
this schema's shape.

### 11. Stream the file instead of reading it whole

`load_standardized_session` does `read_text().splitlines()` (260). Transcripts reach
hundreds of megabytes; `~/.claude/projects` is 3.6 GB in total here. Iterating the file
handle is a one-line change and removes the ceiling.

### 12. Flatten the tool fields on the wire

The envelope nests `tool_name` / `tool_input` / `tool_call_id` under a `tool` key
(146-150) while they are flat in memory (126-128), so both codecs must remember the
asymmetry. **Rationale unknown — needs an owner's answer.** Unless there is one, flatten
it. Free to change while no file on disk uses the format (see recommendation 1).

### 13. Delete `RecordKind`

Line 11 declares a `Literal` type alias that is never used as an annotation anywhere in
the file. Either annotate `record_kind` with it or remove it.

---

## Add tests

For a module that is *entirely* encoders and decoders, one property test covers most of
it: **every dataclass round-trips through `to_envelope` → `from_envelope` unchanged**,
including empty containers, `None` values, and non-ASCII content. Then:

- `load_standardized_session(write_standardized_session(s))` reconstructs `s`
- a file with one corrupt line still loads the rest, and reports the skip
  (after recommendation 9)
- `is_standardized_session_file` returns `False` — never raises — for a binary file, an
  empty file, a directory, and a mis-encoded file (after recommendation 4)
- a `2.0` file is rejected with a clear message (after recommendation 2)
- a non-ASCII session round-trips byte-identically on both Windows and WSL
  (after recommendations 3 and 5)

`tests/smoke_test.py:49` currently imports `read_jsonl`, `catjsonl`, and `discovery`;
nothing asserts anything about this module.
