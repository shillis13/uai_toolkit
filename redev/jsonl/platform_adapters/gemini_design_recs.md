# platform_adapters/gemini.py — recommendations for the re-design

## 1. Replace the `isinstance(first_obj, list)` sniff — it is the family's worst detection rule

```python
# gemini.py:21-22
if isinstance(first_obj, list):
    return True
```

This claims **any** file whose top-level JSON value is an array. Reproduced against the packaged
code: `~/.gemini/tmp/**/vba_exports.json`, an unrelated data file, is detected as `gemini` and
parses into a session with zero messages and no error.

The rule exists to catch the legacy bare-array snapshot form (`gemini_json_legacy_list`,
gemini.py:189-195). Make it specific instead: require the array to be non-empty and its first
element to be a dict carrying a Gemini message shape — an `id` plus a `type` in
`{user, gemini, info, error, warning, meta}`. That still catches every real legacy snapshot and
stops claiming arbitrary JSON.

Also tighten the path signal: `"/.gemini/"` matches *any* file under the Gemini config directory,
not just transcripts. Require the `tmp/**/session-*` shape that `read_jsonl.find_jsonl` already
assumes (read_jsonl.py:636-638).

## 2. Do not turn a corrupt file into an empty session

```python
# gemini.py:327-330
try:
    data = json.loads(path.read_text())
except json.JSONDecodeError:
    return _from_snapshot_json(path, [])
```

A truncated or corrupt transcript reports "0 messages" identically to a genuinely empty one. Let
the exception propagate, or return a session whose header records the failure. Silently
succeeding on unparseable input is the behavior most likely to cause a wrong decision downstream
— for instance, an offload or archive tool concluding there is nothing to preserve.

## 3. Fix `$rewindTo` on a missing target

```python
# gemini.py:249-252
else:
    message_order = []
    message_map.clear()
    message_sources.clear()
```

If the rewind target id is not in the current conversation, the adapter discards **the entire
conversation**. On a file whose head was trimmed or rotated, the target is legitimately absent and
the whole session parses to nothing.

Rationale unknown — needs an owner's answer before changing the semantics. But the safe default
is the opposite: an unresolvable rewind should be *ignored* (leave the conversation as-is) and
recorded in the header metadata, not treated as "rewind to before the beginning".

## 4. Stream the file instead of `read_text()`

`_from_snapshot_json` (173), `_from_jsonl` (275), and `from_file` (328) each read the whole file
into memory, and `_from_snapshot_json` additionally stores the entire file text inside a single
source record (197-203). For the snapshot forms the whole-file source record is *deliberate* —
it is what makes round-trip exact — so keep it there. But `_from_jsonl` should stream like the
other four adapters do; it currently reads the file whole *and* builds per-line source records,
so a large event log is held twice over.

## 5. Pick one role for tool records, across the family

Gemini gives both `tool_use` and `tool_result` `role="assistant"` (120, 142). Claude uses `user`
for results, Codex `assistant`, Grok and AGY `tool`. Four adapters, three answers. Decide once —
`"tool"` is the only one that is true on every platform — and note that Claude's `"user"` is not
arbitrary: it mirrors the wire format and `read_jsonl`'s raw-line accounting splits user lines
into prompts vs tool_results on that basis (read_jsonl.py:1142-1147). So the change has a
downstream cost that must be paid deliberately, not incidentally.

## 6. Emit a `tool_result` even when `resultDisplay` is empty

`if result_display:` (131) skips the result record entirely for a tool that returned nothing or
an empty string, leaving an orphan `tool_use`. Consumers that pair calls with results by
`tool_call_id` see an unfinished call. Emit an empty-content result instead.

## 7. Unify the two `session_id` fallbacks

`path.stem` for snapshots (174) and `path.stem[-8:]` for event logs (298). One adapter, two
conventions, neither documented. Rationale unknown — the `[-8:]` presumably matches Gemini's
short-uuid filename convention, but it will silently truncate any other name.

## 8. Retire the parallel `msg_seq` accounting

`_message_record_from_gemini_message` increments a local `msg_seq` (89, 111, 130, 151) while its
two callers advance by `len(created)` (209-211, 313-316). They agree only because every increment
happens to correspond to exactly one appended record. Have the function return records without
sequence numbers and let a single caller number them — the invariant then cannot be violated.
