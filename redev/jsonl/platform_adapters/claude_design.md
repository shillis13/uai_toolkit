# platform_adapters/claude.py — redevelopment design

Scope: `src/uai_toolkit/jsonl/platform_adapters/claude.py` (276 lines). Adapter for Claude Code
CLI transcripts.

## 1. What it is for

Translate a Claude Code session transcript (`~/.claude/projects/<project>/<session-uuid>.jsonl`)
into the shared `StandardizedSession` model, and back. This is the reference adapter: it is the
only one whose platform is fully supported end-to-end by the rest of the toolkit (turn numbering,
chain walking, compaction intervals, offload) and the only one with a byte-exact round-trip test.

## 2. Interface — and the family contract it implements

Every adapter module must provide these; `claude.py` provides all four.

```python
PLATFORM = "claude"                                          # claude.py:15
sniff(path: Path, first_obj: Any | None = None) -> bool      # claude.py:18
from_file(path: str | Path) -> StandardizedSession           # claude.py:32
to_platform_text(session: StandardizedSession) -> str        # claude.py:233
```

**What `sniff` must guarantee** (see `__init___design.md` for the family rules): cheap, no
re-reading of the file, never raises, tolerant of `first_obj is None`. Claude's is the **last**
adapter tried (`platform_adapters/__init__.py:41-47`) and is also the **fallback return value**
when nothing matches (`__init__.py:50`), so its sniff can afford to be the broadest of the five —
and is:

```python
# claude.py:19-27
"/.claude/" in str(path.resolve())                     # path signal
first_obj["type"] in {user, assistant, system, custom-title, queue-operation,
                      file-history-snapshot, last-prompt, agent-name, agent-color}
first_obj["message"]["role"] in {user, assistant}      # nested signal
```

Being last is what makes this safe. If Claude were tried first, the nested `message.role` test
alone would claim Codex `response_item` records and any other tool that nests an OpenAI-style
message. **Detection order is not cosmetic here** — moving `claude` earlier silently steals files
from `codex` and `grok`.

`from_file` and `to_platform_text` are described in §5.

## 3. Integration

- **Called by**: `platform_adapters/__init__.detect_platform` (sniff) and
  `read_jsonl.parse_session` via `adapter_for_platform` (`read_jsonl.py:1030-1031`).
- **`to_platform_text` has no production caller** — its only use anywhere is the round-trip test
  `~/bin/ai/jsonl/tests/test_standardized_adapters.py:36`, which asserts
  `rebuilt_text == original_text` against the fixture
  `~/bin/ai/jsonl/test_files/claude_subagent_tool_use.jsonl`.
- **Depends on**: `standardized_session` (the four record dataclasses),
  `platform_adapters.common` (`compact_json`, `normalize_timestamp`), and — lazily, inside a
  nested function — `lib_jsonl_archive.classify_user_record` (claude.py:89).

## 4. Data & config

Reads the transcript file, one line at a time (claude.py:42). Writes nothing. No environment
variables. No configuration.

## 5. How it works

### 5.1 `from_file` (32-229)

One pass over the file. For **every** line, valid or not:

- Blank lines are skipped; a `json.JSONDecodeError` skips the line silently (49-50). A malformed
  line therefore **does not** produce a source record, which breaks the otherwise-exact
  correspondence between `source_id = f"src-{line_number:06d}"` (52) and the file's line numbers
  used elsewhere. `read_jsonl._src_line` (read_jsonl.py:752) parses that id back into a raw line
  number, so the numbering stays right; only the record is missing.
- A `StandardizedSourceRecord` is appended with the verbatim `raw_text`, the parsed `raw_obj`, the
  normalized timestamp, and `platform_type = entry["type"]` (53-62). **This is what makes
  round-trip byte-exact** — `to_platform_text` re-emits `raw_text`, not a reconstruction.

Then session-level facts are accumulated: `session_id` from the first `sessionId` or `promptId`
seen (64); `start_time` from the first non-empty timestamp and `last_updated` from the last
(65-69); and `kind = "subagent"` if any record has `isSidechain` (70-71).

Message extraction only considers lines with a dict `message` whose `role` is `user` or
`assistant` (73-78). Everything else — `system`, `file-history-snapshot`, `attachment`,
`custom-title`, and the rest — becomes a source record and **no message**. That is the split
`read_jsonl` calls "client-only" (read_jsonl.py:1915).

Content handling:

- **String content** (101-121) → one record. Type is `response` for assistant, or the result of
  `classify_user_type` for user.
- **List content** (123-194) → walked block by block:
  - `text` blocks are *accumulated* into `text_parts` and emitted as **one** message after the
    loop (196-215), so a line with two text blocks yields one message.
  - `thinking` → its own `thinking` record, role forced to `assistant` (135-151).
  - `tool_use` → `tool_use` record carrying `tool_name`, `tool_input`, `tool_call_id` (152-167).
  - `tool_result` → `tool_result` record with **role forced to `"user"`** (168-194), because in
    Claude's wire format tool results arrive on a user-role line. Content may be a string, a list
    of text sub-blocks (joined with newlines, 170-175), or something else (JSON-dumped, 179).
  - Any other block type — `image`, for instance — is **silently dropped** (127-129 guards
    non-dicts; the `if/elif` chain has no `else`).
- Ordering consequence: because text is emitted *after* the block loop, a line containing
  `[text, tool_use]` produces the tool_use message **before** the text message, inverting the
  order the model actually produced them. `msg_seq` reflects the emission order, not the block
  order.

### 5.2 User-message classification (82-99) — the important part

```python
def classify_user_type(raw_entry) -> str:      # defined INSIDE the per-line loop
    try:
        from uai_toolkit.jsonl.lib_jsonl_archive import classify_user_record
        return classify_user_record(raw_entry)
    except Exception:
        origin = raw_entry.get("origin")
        if isinstance(origin, dict) and origin.get("kind") == "task-notification":
            return "agent_result"
        if raw_entry.get("isMeta", False):
            if raw_entry.get("sourceToolUseID"):
                return "skill"
            return "injected"
        return "user"
```

The docstring states the intent explicitly: delegate to the **one** canonical record classifier so
that `read_jsonl`'s tagging is "byte-for-byte the same decision" that `lib_context_analysis` and
`chain_skip` make, with the inline copy preserving the original rules verbatim if the import
fails. This is the DESIGN.md invariant that user-role records are not all human input — skill
expansions, hook injections, and subagent notifications all arrive as user-role lines.

Two structural problems with the implementation, independent of the rules themselves:

- The function is **defined inside the per-line loop** (82), so it is rebuilt for every line of a
  transcript that may have tens of thousands.
- The `except Exception` fallback silently substitutes a *copy* of the rules. If
  `lib_jsonl_archive` changes its classification and this copy is not updated, sessions classify
  differently depending on whether an import happened to succeed — and nothing reports which path
  ran.

### 5.3 `to_platform_text` (233-276)

- **If `source_records` exist** (234-236): sort by sequence, join `raw_text` with newlines. Exact.
- **Otherwise** (238-276): reconstruct Claude-shaped lines from message records, threading
  `parentUuid` from the previous record's `entry_uuid` in `platform_extras` (274). This branch
  is never exercised by the test (the fixture always yields source records) and cannot be exact —
  it drops `usage`, `signature`, `requestId`, `cwd`, `gitBranch`, `isMeta`, `promptSource`, and
  everything else the wire format carries.

## 6. Essential vs incidental

**Essential**

- `sniff` staying *last* in the detection order, and remaining the fallback.
- Verbatim `raw_text` in every source record — this is the entire basis of lossless round-trip
  and of `read_jsonl`'s ability to re-read raw fields (`_chain_and_prompt_meta` re-reads the file
  rather than using these, but the property is relied on by `to_platform_text`).
- `source_id` encoding the 1-based file line number. `read_jsonl._src_line` decodes it, and
  `Message.source_line` is what every interval, chain, and turn filter keys on.
- The four-way user classification (`user` / `skill` / `agent_result` / `injected`) and its
  delegation to a single canonical classifier. Losing it means treating skill dumps and hook
  injections as human turns, which corrupts turn numbering and every consumer of it.
- Forcing `tool_result` records to role `user` — matches the wire format, and
  `read_jsonl`'s accounting splits raw user lines into prompts vs tool_results on this basis
  (read_jsonl.py:1142-1147).
- Emitting `thinking` as first-class records rather than folding them into responses. The
  `[/PRIVATE]` filter (read_jsonl.py:2668) operates on them.
- `kind = "subagent"` from `isSidechain`.

**Incidental**

- Defining `classify_user_type` inside the loop.
- The hand-reconstruction branch of `to_platform_text` — untested, lossy, unused.
- `session_id` falling back to `promptId` (claude.py:64) — rationale unknown; needs an owner's
  answer.
- The header's `metadata={"source_line_count": …}` and `roundtrip={"strategy": …}` fields — set
  but never read by anything in either tree.

## 7. Platform notes (Windows / WSL)

- **Tier A — `"/.claude/" in str(path.resolve())`** (claude.py:19). POSIX separator. Matches under
  WSL; never matches on native Windows, where the path renders as `C:\Users\…\.claude\projects\…`.
  Because Claude is also the fallback, the *practical* effect on Windows is small for Claude
  files — but it means the path signal is dead and only the content signals do any work, which in
  turn makes the ordering guarantee (§2) load-bearing rather than belt-and-braces.
- **Tier A — no explicit encoding.** `path.open()` (claude.py:42) uses the platform default. On
  Windows that is the ANSI code page; a transcript containing non-ASCII raises
  `UnicodeDecodeError` out of `from_file`, which — unlike in `sniff` — nothing catches. Add
  `encoding="utf-8"`.
- **Tier A — line endings.** `line.rstrip("\n")` (44) leaves a trailing `\r` on a CRLF file, which
  lands inside `raw_text` and therefore inside the round-trip output. `json.loads` tolerates it;
  byte-exactness does not.
- No process, signal, locking, or terminal concerns. Nothing Tier B or C.

## 8. Risks & sharp edges

- **Malformed lines vanish.** A `JSONDecodeError` skips the line without a source record and
  without a warning (49-50). `to_platform_text` then reproduces a file *missing that line*, and
  the round-trip assertion would fail — silently, as a diff, not as a stated cause.
- **Non-text, non-tool blocks are dropped without trace.** `image` blocks in particular: they
  exist in real transcripts, they are the subject of a whole offload tool
  (`scrub_files.py` embed offloading), and this adapter produces no message record for them. Any
  consumer counting "what the model saw" from message records undercounts.
- **Block emission order is not wire order** for lines mixing text with tool_use or thinking
  (§5.1). `msg_seq` is assigned in emission order, so `Message.line_number` and the `sequence`
  field encode the wrong order within such a line. Whether any consumer depends on within-line
  ordering is unknown.
- **The classification fallback is a silent divergence risk** (§5.2).
- **`sniff` is order-dependent for correctness, not just precision.** Its nested
  `message.role` test is broad enough to claim other platforms' records.
- **`session_id` is taken from the first record that has one** (64) and never re-checked. A
  transcript that was concatenated or rewritten with a different id would take the first.
