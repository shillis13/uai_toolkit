# platform_adapters/claude.py — recommendations for the re-design

Claude is the reference adapter and the one that works. These are narrow.

## 1. Emit messages in block order, not "tool_use first, text last"

`from_file` accumulates `text` blocks into `text_parts` during the block loop and emits them as a
single message **after** the loop (claude.py:196-215), while `thinking`, `tool_use`, and
`tool_result` are emitted inline (135-194). So a line containing `[text, tool_use]` produces the
tool_use message *before* the text message, and `msg_seq` — which becomes
`Message.line_number` and `StandardizedMessageRecord.sequence` — records the inverted order.

Whether any consumer depends on within-line ordering is unknown, but the record claims to be a
sequence and is not one. Emit in block order; if the "join adjacent text blocks into one message"
behavior is wanted (and it probably is — Claude splits prose across blocks arbitrarily), coalesce
*runs* of adjacent text blocks in place rather than hoisting all of them to the end.

## 2. Do not silently drop `image` and other unrecognized blocks

The block dispatch (claude.py:130-194) is an `if/elif` chain with no `else`. Any block type that
is not `text`, `thinking`, `tool_use`, or `tool_result` produces nothing. `image` blocks are the
concrete case: they exist in real transcripts, `scrub_files.py` has a whole embed-offload feature
built around them, and this adapter makes them invisible to every consumer of the message stream.

Emit a record — even a placeholder carrying the block type and its serialized size — so that
"what the model saw" accounting is not silently short. At minimum, count the unrecognized types
and put the tally in `header.metadata` so the gap is visible.

## 3. Hoist `classify_user_type` out of the per-line loop

It is defined inside the `for line in handle` loop (claude.py:82) and therefore rebuilt for every
line of a transcript that may run to tens of thousands. Move it to module scope. This is
mechanical and safe.

## 4. Make the classification fallback loud, or delete it

```python
# claude.py:88-99
try:
    from uai_toolkit.jsonl.lib_jsonl_archive import classify_user_record
    return classify_user_record(raw_entry)
except Exception:
    ...inline copy of the rules...
```

The docstring's whole point is that there must be exactly one classifier so `read_jsonl`,
`lib_context_analysis`, and `chain_skip` make byte-for-byte the same decision. The fallback
defeats that: if `lib_jsonl_archive` changes its rules and this copy is not updated, sessions
classify differently depending on whether an import happened to succeed — and nothing reports
which path ran.

Also note the `except Exception` catches a genuine bug inside `classify_user_record` just as
readily as an ImportError, substituting the stale copy without a word.

In a proper package the import cannot fail, so: delete the fallback. If it must stay for a
standalone-copy scenario, catch `ImportError` only, and record which path was taken in
`header.metadata`.

## 5. Do not lose malformed lines

A `json.JSONDecodeError` skips the line entirely (claude.py:49-50) — no source record. Since
`to_platform_text` re-emits source records, a round-trip of a file with one bad line silently
produces a *different file*, and the round-trip test would fail as an opaque diff rather than a
stated cause. Emit a source record with `raw_text` preserved and `raw_obj = None`, and count the
failures in `header.metadata`. (The same fix applies to all five adapters.)

## 6. Tier-A portability, inline

- `"/.claude/" in str(path.resolve())` (claude.py:19) — POSIX separator, never matches on native
  Windows. See the family recommendations for the shared fix.
- `path.open()` (claude.py:42) — add `encoding="utf-8"`. On Windows the platform default is the
  ANSI code page and a non-ASCII transcript raises out of `from_file`, uncaught.
- `line.rstrip("\n")` (44) — leaves `\r` on CRLF input, inside `raw_text` and therefore inside
  round-trip output. Gemini's `_from_jsonl` already uses `splitlines()` (gemini.py:275), which
  handles this correctly; copy that.

## 7. Explain or drop the `promptId` fallback

`session_id = session_id or str(entry.get("sessionId") or entry.get("promptId") or "")`
(claude.py:64). Why a prompt id would stand in for a session id is not determinable from the code
— rationale unknown, needs an owner's answer. If it is vestigial, dropping it removes a way for a
session to acquire a wrong identity from its first record.
