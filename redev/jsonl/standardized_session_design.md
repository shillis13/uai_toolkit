# standardized_session.py — redevelopment design

Source of record:
`/Users/shawnhillis/AI/uai_toolkit/src/uai_toolkit/jsonl/standardized_session.py`
(306 lines). All line citations are against that file unless another path is given.

## Terms

- **Standardized session** — this project's vendor-neutral representation of a
  recorded AI CLI conversation, independent of whether it came from Claude, Codex,
  Gemini, Anti-Gravity (`agy`), or Grok.
- **Envelope** — the outer wrapper written around each record: `{schema, version,
  record_kind, payload}`. Lines 33-52 show the shape.
- **Record kind** — which of the four record types an envelope carries: `session`
  (the header), `source_record`, `message`, or `event` (11).
- **Platform adapter** — a per-vendor module under
  `src/uai_toolkit/jsonl/platform_adapters/` that converts one vendor's native file
  into a `StandardizedSession`.
- **Dataclass** — a Python class whose fields are declared as annotations; the
  standard library generates the constructor.
- **JSONL** — JSON Lines: one complete JSON value per line.
- **Round-trip** — write a structure out and read it back with nothing lost.

---

## 1. What it is for

`standardized_session.py` defines the vendor-neutral shape that every session
transcript is converted into before anything else in the package looks at it. It is a
**schema module**: five dataclasses, their JSON envelope encoders and decoders, and
three file-level helpers. It contains no parsing logic, no vendor knowledge, no
input/output beyond `read_text`/`write_text`, and no dependencies outside the standard
library.

Its practical role is as the seam between the five platform adapters (which produce it)
and `read_jsonl.parse_session` (which consumes it and flattens it into the `Message`
model everything else uses).

---

## 2. Interface

### 2.1 Constants

```python
STANDARDIZED_SCHEMA_NAME    = "ai_root.standardized_cli_session_jsonl"   # 8
STANDARDIZED_SCHEMA_VERSION = "1.0"                                     # 9
RecordKind = Literal["session", "source_record", "message", "event"]    # 11
```

`STANDARDIZED_SCHEMA_NAME` is the on-disk magic string. Changing it invalidates every
previously written file and every detection call.

### 2.2 The five dataclasses

Every one follows the same pattern: a `to_envelope()` instance method and a
`from_envelope()` class method, so the class is its own codec.

**`StandardizedSessionHeader`** (18-70) — one per file. Required: `session_id`,
`platform`, `source_format`. Optional: `platform_variant`, `source_path`, `start_time`,
`last_updated`, `kind`, and four free-form dictionaries — `metadata`,
`platform_metadata`, `roundtrip`, `extensions`.

**`StandardizedSourceRecord`** (73-113) — the raw original line, preserved. Carries
`source_id`, `sequence`, `raw_text` (the original line verbatim), `raw_obj` (its parsed
form), `timestamp`, `platform_type`, `platform_subtype`, `extensions`. This is the
lossless-fidelity half of the schema: one source record per input line, so the original
bytes survive conversion.

**`StandardizedMessageRecord`** (116-177) — a normalized message. `record_id`,
`sequence`, `timestamp`, `role`, `message_type`, `content_text`, `content_blocks`,
`tool_name` / `tool_input` / `tool_call_id`, `visible`, `source_ids` (which source
records this message was derived from), `platform_extras`, `extensions`.

Note the envelope **nests the three tool fields under a `tool` key** (146-150) and
`from_envelope` un-nests them (161, 170-172). The in-memory field names and the on-disk
key names deliberately differ here.

**`StandardizedEventRecord`** (180-220) — a non-message occurrence: `record_id`,
`sequence`, `timestamp`, `event_type`, `content_text`, `source_ids`, `platform_extras`,
`extensions`. **No adapter in the package constructs one** — see §3.

**`StandardizedSession`** (223-242) — the container: a header plus three lists.
`all_envelopes()` (230-235) emits header, then source records, then **event records,
then message records** — note events precede messages in the output order.
`to_jsonl_text()` (237-239) joins compact JSON lines with a trailing newline.
`source_record_map()` (241-242) indexes source records by `source_id`.

### 2.3 The three file-level functions

- `write_standardized_session(session, path) -> Path` (246-249) —
  `path.write_text(session.to_jsonl_text())`. **No `encoding=`.**
- `load_standardized_session(path) -> StandardizedSession` (253-286) — reads every
  line, requires `schema == STANDARDIZED_SCHEMA_NAME` on each (264-265), dispatches on
  `record_kind`, raises `ValueError` on an unknown kind (275-276) or a missing header
  (278-279), and returns the three lists each sorted by `sequence` (281-286).
- `is_standardized_session_file(path) -> bool` (290-306) — opens the file, finds the
  first non-blank line, and returns whether it is a dict with the right `schema` and
  `record_kind == "session"`. Any `OSError` or `JSONDecodeError` returns `False`
  (304-305). Cheap enough to call as a detector.

### 2.4 Serialization details worth preserving

- `_compact_json` (14-15) uses `ensure_ascii=False` and `separators=(",", ":")` — no
  spaces, real Unicode characters rather than `\uNNNN` escapes.
- Every `from_envelope` uses `.get(key, default)` throughout and coerces containers with
  `dict(... or {})` / `list(... or [])` (66-69, 112, 169-176, 217-219). A missing or
  `null` field decodes to an empty container rather than failing. Decoding is
  deliberately permissive.
- Nothing validates types. A `sequence` that is a string decodes as a string and blows
  up later at the `sorted()` call (283-285).

---

## 3. Integration

### 3.1 Producers

Five platform adapters build `StandardizedSession` objects in memory:

| Adapter | File | Builds source records at |
|---|---|---|
| Claude | `platform_adapters/claude.py` | 54 |
| Codex | `platform_adapters/codex.py` | 52 |
| Gemini | `platform_adapters/gemini.py` | 197, 285 |
| Anti-Gravity (`agy`) | `platform_adapters/agy.py` | 120 |
| Grok | `platform_adapters/grok.py` | 209 |

Each exposes `sniff(path, first_obj)` and `from_file(path)`;
`platform_adapters/__init__.py:33-49` runs them in a fixed priority order — `agy`,
`grok`, `codex`, `gemini`, `claude` — with `claude` as the fallback, and checks
`is_standardized_session_file` first so a standardized file is recognized before any
vendor sniffing.

**No adapter constructs a `StandardizedEventRecord`.** The class is defined, encoded,
decoded, and stored, and nothing in the package produces one. It is designed-for, not
used.

### 3.2 Consumers

`read_jsonl.py` is the only consumer:

- imports `load_standardized_session` and `is_standardized_session_file` (92)
- `parse_session` (1011-1035) branches: a standardized file loads directly (1022-1023,
  1027-1028); otherwise the detected adapter's `from_file` produces an in-memory
  `StandardizedSession` (1030-1031). Either way the result goes to
  `_standardized_to_messages`.
- `_standardized_to_messages` (764-791) flattens `session.message_records` into
  `read_jsonl.Message` objects.

`catjsonl.py` and `scrub_files.py` do **not** import this module. Everything downstream
sees `Message`, never the standardized types.

### 3.3 What the flattening drops — this is the real integration contract

`_standardized_to_messages` (`read_jsonl.py:764-791`):

- **Skips every record with `visible == False`** (767-768).
- **Silently skips any record whose `message_type` is not a valid `MessageType`**
  (769-772) — a bare `except ValueError: continue` with no diagnostic. An adapter that
  emits an unrecognized type has those messages vanish without a word.
- **Drops all `event_records` entirely.** Nothing reads them.
- **Drops `content_blocks`, `platform_extras`, and `extensions`** as first-class data;
  they survive only inside `Message.raw`.
- Maps `record.sequence` → `Message.line_number` (783). This is why
  `Message.line_number` is documented (`read_jsonl.py:377`) as a *message ordinal* and
  not a file line, and why `catjsonl`'s `jgrep -n` output is not a navigable location
  (see `catjsonl_design.md` §8.3).
- Sets `Message.raw` to `{"standardized_record": record.to_envelope(),
  "session_header": session.header.to_envelope()}` (785-788) — **rebuilding the full
  header envelope once per message**. On a 20,000-message transcript that is 20,000
  copies of the same header dictionary.

### 3.4 The schema is not sufficient to describe a Claude session

`parse_session` does not rely on the standardized records alone. After flattening, it
calls `_chain_and_prompt_meta(jsonl_path)` (1033-1034), which **re-opens the raw file**
and walks Claude-native keys — `uuid`, `parentUuid`, `promptSource`, `isCompactSummary`
— to compute which records are on the active conversation chain, which start a turn,
and which are compaction continuations.

The function's own docstring says so plainly (`read_jsonl.py:841-842`): *"Structural
turn metadata from the ORIGINAL records (the standardized `Message.raw` drops
promptSource/isCompactSummary, like it drops the signature)"*, and at 851: *"Empty sets
⇒ caller falls back to the legacy USER-based numbering (non-Claude)."*

**Consequence:** a session written out with `write_standardized_session` and read back
would lose `on_chain`, `turn_number`, and `is_compaction`, because the second pass finds
none of the Claude-native keys it needs. The standardized format does not round-trip a
Claude session's structure. This is acknowledged in the code, not a hidden defect — but
a re-designer must not assume the schema is complete.

---

## 4. Data & config

- **Reads:** any file passed to `load_standardized_session` or
  `is_standardized_session_file`. In current use, that is only a file that
  `is_standardized_session_file` has already accepted.
- **Writes:** only through `write_standardized_session` (246-249) — **which has no
  caller anywhere in the package.**
- **Environment variables, configuration files, databases:** none.

`tools/manifest.py:226` maps this file from `ai:jsonl/lib_standardized_session.py` with
`kind: "clean"` — a mechanical copy with an import rewrite, invertible, no curation.
There is a matching import-rewrite rule at `tools/manifest.py:93`
(`from lib_standardized_session` → `from uai_toolkit.jsonl.standardized_session`). Of
the four modules in this review, this is the only one whose package and source copies
should be identical. No `.materialized` sidecar exists for it, which is consistent with
`kind: "clean"`.

### The most important data fact

**No file on disk is currently in this format.** Nothing in the package writes one.
`write_standardized_session`, `to_jsonl_text`, `all_envelopes`, and `source_record_map`
have **zero callers**. The schema exists as a real, working, in-memory intermediate
representation, and its persistence half is designed but unexercised.

That is good news for a re-design: **the on-disk format carries no legacy data burden.**
`DESIGN.md`'s note that "state outlives code and is usually the hardest thing to change"
does not bind here — as long as this is confirmed before anything is changed.

---

## 5. How it works

There is no algorithm. Each dataclass encodes itself to a dictionary and decodes itself
from one; `StandardizedSession` fans out to its records; the file helpers loop over
lines. The only behavior worth restating:

**Write:** `all_envelopes()` (230-235) produces header → source records → event records
→ message records; `_compact_json` renders each; joined with `"\n"` plus a trailing
newline (237-239).

**Read:** for each non-blank line — parse, reject if `schema` mismatches (264-265),
dispatch on `record_kind` (266-276), then sort each list by `sequence` (281-286). File
order therefore does not matter on read; `sequence` is authoritative.

**Detect:** read until the first non-blank line, check it is a dict whose `schema`
matches and whose `record_kind` is `"session"` (290-303). Note this reads the first
line only — a well-formed header followed by corrupt records still detects as
standardized, and the failure surfaces later in `load_standardized_session`.

---

## 6. Essential vs incidental

### Essential

1. **A vendor-neutral message representation, with the platform-specific parsing
   confined to adapters.** This is the architectural decision the whole `jsonl` package
   rests on, and `jsonl/README.md:150` records the corollary invariant that
   `read_jsonl` is the sole parser. Five vendors already plug in through it.
2. **Keeping the original bytes.** `StandardizedSourceRecord.raw_text` plus `raw_obj`
   (77-78) preserve each input line verbatim, and `StandardizedMessageRecord.source_ids`
   (129) links each normalized message back to the lines it came from. Any tool that
   rewrites a transcript in place — `scrub_files`, `lib_jsonl_archive` — depends on
   being able to get back to the original record. Drop this and in-place editing becomes
   unsound.
3. **Permissive decoding.** Every `from_envelope` defaults missing fields rather than
   raising (66-69, 112, 169-176, 217-219). Vendors add fields without warning; a schema
   that refuses to load an unfamiliar file is a schema that breaks on the next CLI
   update.
4. **The four free-form extension dictionaries** (`metadata`, `platform_metadata`,
   `roundtrip`, `extensions`, plus per-record `platform_extras`/`extensions`). They are
   the pressure valve that keeps vendor quirks out of the core schema.
5. **`is_standardized_session_file` as a cheap first-line detector**, called before any
   vendor sniffing (`platform_adapters/__init__.py:36`).
6. **`sequence` as the ordering key**, independent of file order (281-286).

### Incidental

1. **The entire persistence half.** `write_standardized_session`, `to_jsonl_text`,
   `all_envelopes`, `source_record_map` — no callers. Either wire them up with a stated
   purpose or delete them; do not port unexercised serialization code and inherit its
   bugs.
2. **`StandardizedEventRecord`** (180-220) — 41 lines defined, encoded, decoded,
   stored, sorted, and never produced by any adapter, nor read by
   `_standardized_to_messages`. Speculative.
3. **The nesting of tool fields under a `tool` key** on the wire (146-150) while they
   are flat in memory. A gratuitous asymmetry that every codec has to remember.
4. **`RecordKind`** (11) — a `Literal` alias that is declared and never used as an
   annotation anywhere in the file.
5. The exact string `"ai_root.standardized_cli_session_jsonl"` (8). Free to change while
   no file on disk uses it — but confirm that first (§4).
6. The header/source/event/message emission order in `all_envelopes` (232-234). Read
   sorts by `sequence` anyway, so the order is cosmetic.

---

## 7. Platform notes

Tiers per `DESIGN.md`: **A** = inline portability fix, **B** = genuinely OS-divergent,
**C** = platform-impossible.

| Concern | Where | Tier | Detail |
|---|---|---|---|
| **`write_text` with no `encoding=`** | 248 | **A** | Uses the platform default. On Windows that is typically cp1252, which cannot encode most non-ASCII text — and `_compact_json` deliberately sets `ensure_ascii=False` (15), so non-ASCII reaches the encoder as real characters. Writing a transcript containing an em dash or an emoji raises `UnicodeEncodeError` on Windows and succeeds on macOS and WSL. **Must be `encoding="utf-8"`.** |
| **`read_text` with no `encoding=`** | 260 | **A** | Same problem in reverse: a UTF-8 file written on Linux fails to decode, or silently mis-decodes, on Windows. |
| **`path.open()` with no `encoding=`** | 293 | **A** | `is_standardized_session_file` swallows the resulting `UnicodeDecodeError`? No — it catches only `OSError` and `json.JSONDecodeError` (304). A `UnicodeDecodeError` is a subclass of `ValueError`, not of either, so it **propagates** out of a function whose whole contract is to return a boolean. On Windows, a UTF-8 transcript with non-ASCII content would crash the detector rather than return `False`. Not reproduced (no Windows box available) but it follows from the code. |
| **`write_text` without `newline=""`** | 248 | **A** | Python text mode translates `"\n"` to `"\r\n"` on Windows. The same session written on Windows and on WSL produces byte-different files, breaking any content hash or byte-comparison check. `lib_jsonl_archive` relies on byte-identical untouched lines (`lib_jsonl_archive.py:698`), so this matters. |
| Path handling | 247, 254, 291 | **A — clean** | `pathlib` throughout, accepts `str | Path`. |
| No atomic write | 248 | **A** | `write_text` truncates in place. A crash mid-write leaves a truncated file. `scrub_files._atomic_write` (613-636) and `lib_jsonl_archive.atomic_write` both exist in the same package; neither is used here. Moot while nothing calls the writer, relevant the moment something does. |
| Whole file into memory | 260 | **A** | `read_text().splitlines()` materializes the file. Transcripts here reach hundreds of megabytes; `~/.claude/projects` is 3.6 GB in total on this machine. Streaming line-by-line is a one-line change. |
| Processes, signals, locking, terminals, case sensitivity | — | n/a | None of these apply — no subprocesses, no file handles held open, no filename matching. |

Nothing here belongs in `platform_compat/` and nothing is Tier C. All four real issues
are Tier A one-liners, and all four are in the **unused** persistence half of the module.

Related and adjacent, though not this module's code: `platform_adapters/claude.py:19`
sniffs with `"/.claude/" in str(path.resolve())` — a forward-slash string test that
fails on native Windows, where `resolve()` yields backslashes. Worth carrying into the
adapters' own design doc.

---

## 8. Risks & sharp edges

### 8.1 The schema version is written but never checked

`STANDARDIZED_SCHEMA_VERSION = "1.0"` (9) is emitted in every envelope (36, 87, 135,
194). `load_standardized_session` checks the schema **name** (264-265) and never looks
at `version`. `from_envelope` never looks at it either. So a future `2.0` file loads
silently into `1.0` structures, with fields interpreted under the wrong assumptions.
The version field is decoration until something enforces it.

### 8.2 Unknown message types disappear silently

Not in this file, but it is this schema's failure mode:
`read_jsonl._standardized_to_messages:769-772` does `MessageType(record.message_type)`
inside a bare `except ValueError: continue`. An adapter emitting a type the `MessageType`
enum does not know — a new vendor block type, a typo, a value from a newer schema
version — has those messages **dropped with no warning, no counter, and no log line**.
Message counts silently shrink. Given §8.1 leaves versions unenforced, these two
combine badly.

### 8.3 No type validation anywhere

Decoding is entirely `.get()` with defaults (66-69, 112, 169-176, 217-219). A `sequence`
that arrives as a string decodes fine and then raises `TypeError` at the `sorted()` call
(283-285), far from the cause. A `content_text` that arrives as a list decodes fine and
fails somewhere downstream in formatting. The permissiveness is right (§6, essential
item 3), but it should be permissive about *missing* fields and strict about *wrong
types*, and today it is neither.

### 8.4 Errors are all-or-nothing

`load_standardized_session` raises `ValueError` on the first line whose `schema` does not
match (265) or whose `record_kind` is unknown (276). One corrupt line makes the entire
session unloadable. Meanwhile `is_standardized_session_file` inspects only the first line
(293-303), so a file with a good header and one bad record **passes detection and then
fails to load**. Compare `scrub_files.scan_attachments` (`scrub_files.py:228-231`) and
`lib_jsonl_archive`, which both skip undecodable lines and keep going. Transcripts are
appended to by live processes and are routinely truncated mid-line; strictness here is
the wrong default.

### 8.5 The header envelope is rebuilt once per message

`read_jsonl._standardized_to_messages:787` calls `session.header.to_envelope()` inside
the per-message loop, producing a fresh 12-key dictionary for every message. On a
27,000-message transcript — one exists in `~/.claude/projects` on this machine — that is
27,000 identical dictionaries retained in memory through `Message.raw`. Hoisting one call
out of the loop fixes it. This is a `read_jsonl` change, not a change here, but it is a
direct cost of this schema's shape.

### 8.6 Dead surface: about a third of the module

`write_standardized_session` (246-249), `to_jsonl_text` (237-239), `all_envelopes`
(230-235), `source_record_map` (241-242), the whole of `StandardizedEventRecord`
(180-220), and the `RecordKind` alias (11) have no callers in the package. Roughly 90 of
306 lines. It works and it is coherent — it has simply never been exercised, which means
every Tier A defect in §7 is also untested.

### 8.7 The schema cannot represent a session's structure

Detailed in §3.4. `on_chain`, `turn_number`, and `is_compaction` are computed by a
second raw-file pass (`read_jsonl._chain_and_prompt_meta`, 839-879) reading
Claude-native keys, because the standardized records do not carry them — stated in that
function's own docstring at 841-842. Anyone who writes a standardized file and reads it
back gets a session with no chain information. If the persistence half is ever to be
used for real, this gap has to close first.

### 8.8 Work in flight

`platform_adapters/` contains five adapters, one of which (`grok.py`) is not mentioned
anywhere in `DESIGN.md` or `jsonl/README.md`, and the priority comment at
`platform_adapters/__init__.py:40-42` reads as recently tuned (*"Grok after agy (agy's
step_index signature is unambiguous)"*). Vendor coverage is actively expanding, so the
schema should be treated as still moving, not settled.

### 8.9 No tests

`tests/smoke_test.py:49` imports `read_jsonl`, `catjsonl`, and `discovery`; it does not
import this module, though it loads it transitively. Nothing asserts that any dataclass
round-trips through `to_envelope`/`from_envelope`. For a module that is *entirely*
encoders and decoders, a round-trip property test is both the obvious test and the only
one really needed.

---

## 9. What I could not determine

- **Whether the persistence half was written for a planned feature or speculatively.**
  `write_standardized_session` has no caller and the format has no file on disk.
  Rationale unknown — needs an owner's answer. The answer decides whether §6's
  "incidental" items are deleted or completed.
- **What `StandardizedEventRecord` was meant to carry.** No adapter produces one and no
  consumer reads one. Rationale unknown — needs an owner's answer.
- **What the `roundtrip` dictionary on the header (30) is for.** The name suggests
  fidelity metadata for reconstructing the vendor's original file, but nothing sets it
  and nothing reads it. Rationale unknown — needs an owner's answer.
- **Why the tool fields are nested on the wire but flat in memory** (146-150 vs
  126-128). Rationale unknown — needs an owner's answer.
- **Whether any standardized file exists outside this repository** — written by the
  source tree's `lib_standardized_session.py`, by a companion tool, or by hand. I
  searched this package only. This must be checked before changing the format or the
  schema name, because it is the one thing that would turn a free change into a
  migration.
