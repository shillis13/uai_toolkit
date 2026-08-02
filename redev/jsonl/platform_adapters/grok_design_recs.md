# platform_adapters/grok.py — recommendations for the re-design

## 1. Grok has no tests — add them before porting, not after

Grok is the only adapter in the family with neither a round-trip fixture in
`~/bin/ai/jsonl/tests/test_standardized_adapters.py` (its `FIXTURES` table, lines 19-24, covers
claude, codex, and two gemini shapes) nor a dedicated test file. It is also the largest adapter
(519 lines) and the most recently added, i.e. the one with the least accumulated confidence.

Add a fixture and a round-trip assertion. Everything in the design doc for this adapter was
derived by reading the code plus one manual run against a real transcript — that is not a
substitute.

## 2. Decide what to do about the missing timestamps

Confirmed on a real session: Grok chat histories carry no per-line timestamps, so every
`Message.timestamp` is `""` and the header's `start_time` / `last_updated` are empty. The code
acknowledges this (grok.py:190) and tries `timestamp` then `created_at` (191), finding neither.

Downstream, silently:

- `read_jsonl.group_by_day` (read_jsonl.py:486-505) buckets the whole session under `"Unknown"` —
  a Grok session renders as one undated day.
- `_sort_messages_by_ts` (read_jsonl.py:2553) sorts every message as `datetime.min`, so `--sort`
  does nothing.
- The j-tools' `--since` / `--before` mtime-window filters have nothing to filter on.

Options, in preference order: (a) synthesize timestamps from the file's mtime plus record order,
marked as synthetic in `platform_extras`; (b) leave them empty but have the header declare
`has_timestamps: false` so renderers can say "undated" rather than "Unknown"; (c) do nothing and
document it. Doing nothing *without* documenting it is the current state and is the worst option.

## 3. Replace the key whitelist in `sniff` with a positive-signal test

```python
# grok.py:77
if record_type in _GROK_TYPES and keys <= _GROK_KEYS and (...)
```

`_GROK_KEYS` (grok.py:28-43) enumerates every key observed on a Grok line. The moment Grok CLI
adds a field, `keys <= _GROK_KEYS` fails and the content sniff stops matching. Detection then
rests entirely on the path signals — which usually still work, but a transcript copied out of
`~/.grok/sessions/` and renamed silently reclassifies as `claude` after a Grok version bump.

Invert it: require the *presence* of distinguishing keys rather than the absence of unknown ones.
Whitelists are the wrong shape for a format that will evolve.

## 4. Fold the neighbour rejections into the family's ordering mechanism

grok.py:66-69 hand-rejects `step_index` (AGY), `uuid` / `parentUuid` (Claude), and the four Codex
envelope types. This is de-confliction logic that duplicates what the detection order in
`platform_adapters/__init__.py:41-47` is already supposed to express — and it is *order-specific*:
Grok rejects the adapters that run near it but not Gemini, because Gemini runs after it anyway.

A re-implementation that changes the order must re-derive these by hand, which is exactly the kind
of hidden coupling a re-design should remove. See the family recommendations (`__init___design_recs.md`
item 2) — declared precedence, or confidence-returning sniffs, makes these rejections unnecessary.

## 5. Pick one role for tool records, across the family

`tool_result` uses `role="tool"` here (grok.py:352), which is the *correct* answer — but Claude
uses `"user"`, Codex and Gemini use `"assistant"`. See `codex_design_recs.md` item 3 for the
tradeoff; whichever way it goes, all four should agree.

## 6. Small cleanups

- `_classify_user` returns a `(role, message_type)` tuple where the role is always `"user"`
  (grok.py:148-163). Return just the type.
- The fallback loop in `_content_to_text` (96-104) is unreachable whenever `join_text_parts`
  returns anything, i.e. in the common case. Either widen `join_text_parts` to handle plain
  strings (it is a two-line change in `common.py` and Grok is its only caller) and delete the
  loop, or drop `join_text_parts` and keep the loop. Not both.
- Parenthesize `query or compact_json(kind) if kind else tool_name` (grok.py:380). The precedence
  is what was intended, but the expression is a re-implementation hazard.
- `path.name == "chat_history.jsonl"` (grok.py:59) claims that filename anywhere on the
  filesystem. Qualify it with a parent-directory check, or accept it and say so.
