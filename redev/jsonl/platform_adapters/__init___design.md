# platform_adapters/__init__.py — redevelopment design

Scope: `src/uai_toolkit/jsonl/platform_adapters/__init__.py` (58 lines). This is the family's
registry and detector; the shared contract every sibling implements is defined here.

## Terms

- **Adapter** — one module per AI command-line tool, translating that tool's transcript format
  into the shared `StandardizedSession` data model.
- **Sniff** — a cheap test answering "did this platform write this file?".
- **Standardized session** — the platform-neutral data model in
  `src/uai_toolkit/jsonl/standardized_session.py`: a header, a list of *source records* (one per
  raw line, kept verbatim), and a list of *message records* (the semantic stream).

## 1. What it is for

Given a transcript path, decide which platform produced it and hand back the module that can
parse it. Two functions, `detect_platform` and `adapter_for_platform`, plus the `ADAPTERS`
registry. Everything platform-specific lives in the sibling modules; nothing outside this package
is allowed to read a platform-specific field.

## 2. Interface

```python
ADAPTERS: dict[str, module]                      # __init__.py:10  keys: claude codex gemini agy grok
detect_platform(path: str | Path) -> str         # __init__.py:34
adapter_for_platform(platform: str) -> module    # __init__.py:54  raises ValueError on unknown
_first_json_object(path) -> Any | None           # __init__.py:19  private helper
```

`detect_platform` returns one of `standardized`, `agy`, `grok`, `codex`, `gemini`, `claude` —
note `"standardized"` is **not** a key in `ADAPTERS`, so `adapter_for_platform("standardized")`
raises. Callers must special-case it, and `read_jsonl.parse_session` does
(src/uai_toolkit/jsonl/read_jsonl.py:1027-1028).

### The shared contract every adapter must satisfy

Implemented today, and relied on by `read_jsonl`:

| symbol | signature | required? |
|---|---|---|
| `PLATFORM` | `str` module constant | yes — all five define it |
| `sniff` | `(path: Path, first_obj: Any \| None = None) -> bool` | yes — `detect_platform` calls it on every adapter |
| `from_file` | `(path: str \| Path) -> StandardizedSession` | yes — the only entry point `read_jsonl` uses |
| `to_platform_text` | `(session: StandardizedSession) -> str` | **not uniformly implemented** — `agy.py` has none |

`to_platform_text` re-emits the platform's own format from a standardized session. Its only
caller anywhere is the round-trip test `~/bin/ai/jsonl/tests/test_standardized_adapters.py:36`;
there is no production caller in either tree. Every implementation short-circuits: if
`source_records` are present it re-emits their `raw_text` verbatim, which is what makes the
round-trip byte-exact. The hand-built reconstruction below that short-circuit is therefore
almost never exercised.

### What `sniff` must guarantee

Read the code, not the intent — these are the actual properties:

1. **Side-effect free and cheap.** It gets the path plus the *already-parsed first JSON object*
   of the file, so it must not re-read the file. All five obey this; four of them call
   `path.resolve()`, which does touch the filesystem.
2. **Never raises.** `detect_platform` has no exception handling around the loop
   (__init__.py:48). An adapter that throws takes down detection for every file.
3. **May be wrong, and the cost is asymmetric.** A false positive steals a file from a later
   adapter; a false negative just falls through. Order therefore substitutes for precision.
4. **`first_obj` may be `None`** (unreadable file, empty file, malformed first line) — every
   `sniff` must handle that. All five do, via `isinstance` guards.

`detect_platform`'s two-stage structure matters: `is_standardized_session_file` is checked
*first* and separately (__init__.py:36), because a standardized file is a re-encoding of some
other platform's session and would otherwise be mis-sniffed.

### Why the order is what it is

```python
# __init__.py:41-47
for name, adapter in (("agy", agy), ("grok", grok), ("codex", codex),
                      ("gemini", gemini), ("claude", claude)):
```

The in-code comment (39-40) gives the reason for two of the five: *"Priority: path/format-distinct
adapters first. Grok after agy (agy's `step_index` signature is unambiguous); before codex/claude
which are broader."* Reading the sniffs confirms the ordering is a strict precision ranking:

- `agy` (agy.py:67) — content only, requires `step_index` **and** `source ∈ {USER_EXPLICIT,
  SYSTEM, MODEL}`. Narrowest; nothing else looks like this.
- `grok` (grok.py:46) — path `/.grok/sessions/` **or** filename `chat_history.jsonl`, else a
  key-subset test. It explicitly rejects records carrying `step_index`, `uuid`, `parentUuid`, or
  a Codex type (grok.py:66-69), i.e. it hand-codes its own de-confliction with the adapters
  around it rather than relying on order alone.
- `codex` (codex.py:18) — path `/.codex/`, filename prefix `rollout-`, or a type in
  `{session_meta, response_item, event_msg, turn_context}`. Distinctive.
- `gemini` (gemini.py:18) — path `/.gemini/`, **or the first JSON value is a list**, or a
  `{sessionId, projectHash}` key pair, or a `$set` key. The list test is very broad (see below).
- `claude` (claude.py:18) — path `/.claude/`, or a type in a large set, or a nested
  `message.role ∈ {user, assistant}`. Broadest.

Then: **`return "claude"`** as the final fallback (__init__.py:50). Anything unrecognized is
claimed by Claude, and `claude.from_file` on a non-Claude file yields a session with zero message
records rather than an error.

Reordering this list changes which adapter claims ambiguous files. A re-design that replaces
ordering with something else (explicit confidence scores, or requiring sniffs to be mutually
exclusive) must keep the same net assignments for real transcripts.

## 3. Integration

- **Callers**: `read_jsonl.py:91` imports both functions (aliasing `detect_platform` and
  re-exporting it at read_jsonl.py:743); `lib_engram.py:77` imports `detect_platform` with a
  guarded fallback to `None` and an explicit note that detection *defaults to claude* when
  nothing matches (lib_engram.py:84-90).
- **Depends on**: `standardized_session.is_standardized_session_file`, and the five sibling
  adapter modules — all five are imported eagerly at module load (__init__.py:8).

## 4. Data & config

Reads the first line (or, for `.json`, the whole file) of the transcript being classified
(__init__.py:19-30). Writes nothing. No environment variables. No configuration — the adapter
list and the detection order are both hard-coded, so adding a platform means editing this file.

## 5. How it works

```
detect_platform(path):
    if is_standardized_session_file(path): return "standardized"
    first_obj = _first_json_object(path)          # None on any OSError/JSONDecodeError
    for name, adapter in FIXED_ORDER:
        if adapter.sniff(path, first_obj): return name
    return "claude"
```

`_first_json_object` (19) branches on suffix: `.json` files are parsed whole
(`json.loads(path.read_text())`); anything else is read line-by-line and the first non-blank line
is parsed. Failures return `None` rather than propagating.

## 6. Essential vs incidental

**Essential**

- The two-function surface (`detect_platform`, `adapter_for_platform`) and the fact that
  detection is *content-and-path* based, not extension based. Grok's `chat_history.jsonl` and
  Gemini's `.json` snapshots have no distinguishing extension.
- Standardized-file detection running *before* platform sniffing.
- The precision-ordered fallthrough, and the `claude` default. The default is load-bearing:
  `lib_engram` documents its behavior around it.
- `sniff` receiving a pre-parsed `first_obj` — otherwise detection re-reads the file five times.
- `adapter_for_platform` raising `ValueError` with the offending name (56-58) — this is how a
  bad `--platform` argument surfaces.

**Incidental**

- The exact tuple ordering as *literal source* — the ranking is essential, the hard-coded list
  is not. A registry with declared precision would be better.
- Eager import of all five adapters at package load.
- `"standardized"` being a return value of `detect_platform` but not a key of `ADAPTERS`. That
  asymmetry forces a special case in every caller and is worth removing.

## 7. Platform notes (Windows / WSL)

- **Tier A — path separator.** Every path-based sniff tests for a POSIX substring
  (`"/.claude/"`, `"/.codex/"`, `"/.gemini/"`, `"/.grok/sessions/"`). Under WSL these match.
  Under native Windows `str(path)` uses backslashes and **none of them ever match**, so
  classification silently degrades to the content tests, and anything the content tests miss
  becomes `claude`. Fix: compare `Path` parts, or normalize separators once, in one shared
  helper. `common.path_contains` (common.py:38) already exists for exactly this and is unused.
- **Tier A — no explicit encoding.** `_first_json_object` (__init__.py:22-23) uses
  `path.read_text()` and `path.open()` with no `encoding=`, so on Windows it uses the ANSI code
  page. A transcript with non-ASCII content raises `UnicodeDecodeError`, which *is* caught
  (28-29) and returns `None` — so detection silently falls back to `claude` instead of failing
  loudly. Add `encoding="utf-8"`.
- `path.resolve()` in four sniffs follows symlinks and hits the filesystem. Under WSL, a path
  under `/mnt/c/...` resolves fine; a Windows-side junction may not. Low risk, worth a note.

## 8. Risks & sharp edges

- **Gemini's sniff is dangerously broad.** `if isinstance(first_obj, list): return True`
  (gemini.py:21-22) claims *any* JSON file whose top level is an array. Verified on this machine:
  `~/.gemini/tmp/**/vba_exports.json` — an unrelated data file that merely happens to live under
  `~/.gemini` — is classified `gemini` and parsed into a session with **0 messages**, silently.
  Any `.json` array anywhere will do the same.
- **The final `return "claude"` hides detection failure.** There is no "unknown" outcome and no
  way for a caller to distinguish "this is Claude" from "nothing matched". `lib_engram` works
  around it by commenting on the behavior rather than detecting it.
- **A raising `sniff` breaks all detection** — no `try` around the loop (48).
- **`sniff` order is documented only in a comment.** The comment (39-40) explains agy and grok
  but says nothing about why gemini sits after codex, or why claude is last. Rationale for the
  gemini/claude relative order is unknown — needs an owner's answer.
- **The family contract is only half-built.** `~/bin/ai/jsonl/DESIGN_platform_adapter_contract.md`
  (status line: *"DRAFT for convergence"*) specifies four further per-adapter functions —
  `classify(rec)`, `is_turn_start(rec)`, `compaction_points(records)`, `structure(records)` —
  intended to move the Claude-specific turn/interval/branch predicates out of
  `lib_jsonl_archive` and `read_jsonl` and into the adapters. **None of the four exists in any
  adapter.** Until they do, `read_jsonl._chain_and_prompt_meta` (read_jsonl.py:839) reads
  `uuid`/`parentUuid`/`promptSource`/`logicalParentUuid` directly, so turn numbering, chain
  membership, and compaction intervals are Claude-only and every other platform silently uses a
  cruder fallback. **Treat that document as active work in flight, not settled design.**
