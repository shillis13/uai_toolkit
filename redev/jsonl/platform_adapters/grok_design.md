# platform_adapters/grok.py — redevelopment design

Scope: `src/uai_toolkit/jsonl/platform_adapters/grok.py` (519 lines). Adapter for Grok CLI
transcripts. The largest and most recently added adapter.

## 1. What it is for

Translate a Grok CLI chat history
(`~/.grok/sessions/<url-encoded-cwd>/<session-uuid>/chat_history.jsonl`) into the shared
`StandardizedSession` model, and back.

## 2. Interface — and the family contract it implements

```python
PLATFORM = "grok"                                            # grok.py:15
sniff(path: Path, first_obj: Any | None = None) -> bool      # grok.py:46
from_file(path: str | Path) -> StandardizedSession           # grok.py:166
to_platform_text(session: StandardizedSession) -> str        # grok.py:429
```

All four contract members present. Module constants encoding format knowledge:
`_GROK_TYPES` (18-25) — the six top-level record types; `_GROK_KEYS` (28-43) — every key observed
on a chat-history line, used as a whitelist for the content sniff.
Private helpers: `_content_to_text` (85), `_summary_to_text` (113), `_parse_tool_arguments` (132),
`_classify_user` (148).

**What `sniff` must guarantee** (family rules in `__init___design.md`): cheap, no re-read of the
file, never raises, tolerant of `first_obj is None`. Grok's is the most elaborate of the five and
the only one that reasons explicitly about its neighbours:

```python
# grok.py:59-82
"/.grok/sessions/" in resolved or path.name == "chat_history.jsonl"   # path signals → True
if "step_index" in first_obj or "uuid" in first_obj or "parentUuid" in first_obj: return False
if first_obj["type"] in {session_meta, response_item, event_msg, turn_context}:   return False
keys == {"type","content"} and type in _GROK_TYPES                    → True
type in _GROK_TYPES and keys <= _GROK_KEYS and (content present or type in {reasoning, backend_tool_call})
                                                                       → True
```

**Detection order matters, and Grok's negative checks are why it can sit second.** Grok runs after
`agy` but *before* `codex`, `gemini`, and `claude` (`platform_adapters/__init__.py:41-47`). Its
`type` values — `system`, `user`, `assistant` — overlap Claude's directly, so without the explicit
rejections at grok.py:66-69 it would claim Claude and Codex transcripts. The in-code comment at
`__init__.py:39-40` records the placement decision; the rejections are the mechanism that makes it
safe. **Any re-implementation that reorders the family must re-derive these rejections**, because
they are order-specific: Grok rejects `uuid`/`parentUuid` (Claude) and the four Codex types, but
does *not* reject Gemini's markers, because Gemini runs after it anyway.

## 3. Integration

- **Called by**: `platform_adapters/__init__.detect_platform` and `read_jsonl.parse_session`.
- **`to_platform_text`**: no production caller, and **no test either** — the round-trip suite's
  fixture table (`~/bin/ai/jsonl/tests/test_standardized_adapters.py:19-24`) covers claude, codex,
  and two gemini shapes. There is no `test_grok_adapter.py` in `~/bin/ai/jsonl/tests/`. **Grok is
  the only adapter with no test at all.**
- **Depends on**: `standardized_session`, `platform_adapters.common` (`compact_json`,
  `join_text_parts`, `normalize_timestamp` — the only adapter that uses `join_text_parts`).
- **Discovery**: `read_jsonl` searches `~/.grok/sessions/**/chat_history.jsonl` and treats the
  **parent directory name as the session UUID** (read_jsonl.py:104-105, 670-675, 2380-2384).

## 4. Data & config

Reads the transcript one line at a time (grok.py:176). Writes nothing. No environment variables.

## 5. How it works

### 5.1 `from_file` (166-426)

Single pass. Every parseable dict line becomes a `StandardizedSourceRecord` with verbatim
`raw_text` and a computed `platform_subtype` (197-206): `synthetic_reason` for synthetic user
lines, `kind.tool_type` for backend tool calls, `model_id` for assistant lines. Malformed lines
and non-dict lines are skipped silently (183-186).

**Grok transcripts generally carry no per-line timestamps** — the code says so at 190 and tries
`timestamp` then `created_at` (191). Confirmed on a real session on this machine: 70 messages
parsed, `start_time` and `last_updated` both empty. Consequences in §8.

Per record type:

- **`system`** (220-238) → `system` record. Empty text skips.
- **`user`** (240-264) → role and type from `_classify_user`, plus `synthetic_reason` and
  `prompt_index` copied into `platform_extras`.
- **`reasoning`** (266-289) → `thinking` record built from `summary`. **Emitted even when the
  text is empty** — the comment at 267-268 explains why: Grok reasoning is often encrypted
  (`encrypted_content`) with no readable body, and the record is kept so the turn structure stays
  visible. `platform_extras` records `has_encrypted_content`.
- **`assistant`** (291-341) → a `response` record if there is text, then one `tool_use` record per
  entry in `tool_calls` (315-340), each with `arguments` parsed by `_parse_tool_arguments`.
- **`tool_result`** (343-361) → `tool_result` record, role `"tool"`, id from `tool_call_id`.
- **`backend_tool_call`** (363-401) → a `tool_use` record for Grok's server-side tools (web
  search and similar). `tool_name` from `kind.tool_type`, input from `kind.action`, and a short
  human-readable `content_text` preferring `action.query` (376-380).
- Unknown types keep their source record only (403).

Header (405-421): `session_id` is **the parent directory name** when the file is named
`chat_history.jsonl`, else `path.stem` (407) — matching the `<session-uuid>/chat_history.jsonl`
layout. `model_id` is carried in `platform_metadata` if any assistant line supplied one.

### 5.2 `_classify_user` (148-163)

Grok has partial structural metadata, so this sits between Claude's fully-structural approach and
AGY's pure text matching:

1. `synthetic_reason` present → `injected`. (Grok's own field — values observed:
   `project_instructions`, `system_reminder`, per the docstring.)
2. `prompt_index` present, or the text contains `<user_query>` → `user`.
3. Text starts with `<system-reminder>`, `<user_info>`, or `<environment_` → `injected`.
4. Otherwise → `user`.

Only rule 3 is content matching, and it is a backstop. Note the return is a `(role, message_type)`
tuple where role is always `"user"` — the tuple shape is vestigial.

### 5.3 Content flattening — `_content_to_text` (85-110)

Handles `None`, `str`, `list` (via `join_text_parts`, then a fallback loop accepting plain
strings and `{text}` dicts), and `dict` (prefers `.text`, else `compact_json`). The fallback loop
at 96-104 is unreachable when `join_text_parts` returns anything non-empty — dead in the common
case, live only for lists of plain strings.

### 5.4 `to_platform_text` (429-519)

- If source records exist, re-emit `raw_text` in sequence order. Exact — and this is the only path
  the format ever takes in practice.
- Otherwise reconstruct per message type (438-518), including re-splitting `tool_use` back into
  either a `backend_tool_call` line or an `assistant` line with a `tool_calls` array, decided by
  `platform_extras["source_entry_type"]` (479). Untested.

## 6. Essential vs incidental

**Essential**

- The negative sniff checks (grok.py:66-69). They are what makes the detection order safe; without
  them Grok claims Claude and Codex files.
- Both path signals. `"/.grok/sessions/"` and the bare filename `chat_history.jsonl` — the second
  is what lets a copied-out transcript still be recognized.
- `session_id` from the **parent directory**, not the filename. Every Grok transcript is named
  `chat_history.jsonl`; the stem carries no identity. `read_jsonl.find_jsonl` and `list_sessions`
  both encode the same rule independently (read_jsonl.py:673, 2384).
- Emitting empty `thinking` records for encrypted reasoning. Dropping them would hide that the
  model reasoned at all, and the turn would look like it went straight from prompt to answer.
- `_parse_tool_arguments`' `{"raw": …}` fallback (132-145) — a tool call whose arguments will not
  parse is preserved rather than lost.
- Treating `backend_tool_call` as a `tool_use`. Grok's server-side tools are real tool usage and
  belong in tool accounting.
- Carrying `synthetic_reason` into `platform_extras` — it is the only structural evidence Grok
  gives about why a user-role line exists.

**Incidental**

- `_classify_user` returning a `(role, message_type)` tuple when role is always `"user"` (163).
- The unreachable fallback loop in `_content_to_text` (96-104).
- The `content_text` on `backend_tool_call` records (380) — a display convenience stored as
  content.
- `metadata={"source_line_count": …}` — set, never read.
- The hand-reconstruction branch of `to_platform_text`.

## 7. Platform notes (Windows / WSL)

- **Tier A — `"/.grok/sessions/" in str(path.resolve())`** (grok.py:59). POSIX separator; never
  matches on native Windows. Unlike the other adapters, Grok has a second path signal
  (`path.name == "chat_history.jsonl"`) that is separator-independent, so detection survives — but
  only because Grok's filename is a fixed constant.
- **Tier A — `path.name == "chat_history.jsonl"` returns `True` unconditionally**, for a file
  anywhere on the filesystem with that name. Narrow in practice, but it is a global claim on a
  fairly generic filename.
- **Tier A — no explicit encoding** on `path.open()` (grok.py:176). Platform default; uncaught
  `UnicodeDecodeError` on Windows for non-ASCII content.
- **Tier A — `line.rstrip("\n")`** (178) leaves `\r` on CRLF files inside `raw_text`.
- **Tier A — the URL-encoded working directory in the path.** Grok's layout is
  `~/.grok/sessions/<url-encoded-cwd>/<uuid>/chat_history.jsonl`. On Windows the encoded
  directory will contain an encoded drive letter and backslashes; nothing here decodes it, and
  nothing depends on decoding it, so this is a note rather than a defect.
- Nothing Tier B or C.

## 8. Risks & sharp edges

- **No tests.** Grok is the only adapter in the family with neither a round-trip fixture nor a
  dedicated test file. Every behavior above is asserted by reading the code and by one manual run
  against a real transcript (70 messages parsed cleanly).
- **No timestamps at all.** Confirmed on a real session: `start_time` and `last_updated` are both
  empty, and every `Message.timestamp` is `""`. Downstream, `read_jsonl.group_by_day`
  (read_jsonl.py:486-505) buckets every message under the label `"Unknown"`, so **a Grok session
  renders as a single undated day**; `_sort_messages_by_ts` (read_jsonl.py:2553) sorts them all as
  `datetime.min`, making `--sort` a no-op that silently reorders nothing; and `--since` / `--before`
  filtering in the j-tools cannot work. None of this is reported to the user.
- **`sniff`'s key-whitelist will reject new fields.** The second content rule requires
  `keys <= _GROK_KEYS` (77). When Grok CLI adds a field to its records, that rule stops matching
  and detection falls through to... the path signals, which usually still work. But for a
  transcript outside `~/.grok/sessions/` with a non-standard name, a Grok version bump silently
  reclassifies it as `claude`. A whitelist is the wrong shape for a format that will evolve.
- **`tool_result` uses `role="tool"`** (352) while Claude uses `"user"`, Codex `"assistant"`, and
  Gemini `"assistant"`. Four adapters, three answers for the same concept.
- **No chain, interval, or turn structure**, as with Codex, Gemini, and AGY:
  `read_jsonl._chain_and_prompt_meta` finds no `promptSource` and falls back to
  increment-on-user-message turn numbering (read_jsonl.py:997-1008).
- **`content_text` on `backend_tool_call`** is built as
  `query or compact_json(kind) if kind else tool_name` (380). Python's precedence parses this as
  `query or (compact_json(kind) if kind else tool_name)`, which is what was meant, but the
  expression is easy to misread and worth parenthesizing.
- **Malformed and non-dict lines vanish silently** (183-186), so round-trip would drop them.
