# platform_adapters/agy.py — recommendations for the re-design

## 1. Fix the tool call / tool result pairing — it has never worked

```python
call_id = f"agy-step-{step_index}-{tool_name}"   # agy.py:216, on the tool_use side
call_id = f"agy-step-{step_index}-{tool_name}"   # agy.py:239, on the tool_result side
```

Identical construction, but `step_index` is the *call's* step on one side and the *result's* step
on the other, and those are always different steps. Every AGY `tool_use` and `tool_result`
therefore gets a unique id and nothing pairs. The code is visibly trying to correlate, so this
reads as a defect, not a decision.

Anti-Gravity gives no native call id, so pairing has to be positional: when a `PLANNER_RESPONSE`
emits N tool calls, the next N steps whose type is in `_TOOL_RESULT_TYPES` are their results, in
order. Mint the id once on the call side and hand it to the result side by keeping a small queue
across the line loop. If ordering turns out not to be guaranteed, say so and drop the ids
entirely rather than emitting ones that look meaningful and are not.

## 2. Decide whether `to_platform_text` is part of the contract

AGY is the only adapter without it. `adapter_for_platform("agy").to_platform_text(...)` raises
`AttributeError`. The round-trip test's fixture table
(`~/bin/ai/jsonl/tests/test_standardized_adapters.py:19-24`) simply omits agy, so the gap is
untested rather than tested-as-absent.

Two acceptable outcomes, one unacceptable one:

- Implement it (the `source_records` re-emit branch is four lines — see grok.py:429-436), and add
  agy to the round-trip fixture table.
- Or drop `to_platform_text` from the whole family (see the family recommendations — it has no
  production caller anywhere).
- **Not acceptable**: carrying a contract into the re-design that one of five implementers
  silently does not satisfy.

Also remove the now-honest-but-misleading `roundtrip={"strategy": "emit_source_records"}` header
(agy.py:271) if no re-emit exists, and the unused `compact_json` import (agy.py:13).

## 3. Move the injection markers out of the adapter

`_classify_user_input` (agy.py:27-64) recognizes `[Message] … sender= … priority=`,
`<ADDITIONAL_METADATA>`, `<USER_SETTINGS_CHANGE>`, `<system-reminder>`, `<command-name>`,
`<skill-`, `Launching skill:`, `<task-notification>`, `<agent-result>`. Most of those are strings
**this toolkit** injects, not Anti-Gravity's own vocabulary.

Consequence: when a hook's wrapper text changes, injected content silently reclassifies as `user`
and starts counting as a human turn — shifting turn numbers, `--turns` selections, and every
turn-scoped statistic, with no error anywhere.

Recommendation: define the markers once, next to the code that *emits* them, and have the adapter
import them. Then a change to an injection wrapper is a one-place change and a grep away from
being caught. Add a test that asserts the marker constants still match what the hooks and comms
layer actually write.

## 4. Give AGY a discovery path, or document that it has none

`read_jsonl.find_jsonl` (read_jsonl.py:635-675) searches Claude, Codex, Gemini, and Grok
locations. There is no AGY entry and no `AGY_*_DIR` constant in `read_jsonl` (95-105). AGY
sessions are reachable only by explicit path through `read-file`, yet `agy` is an accepted
`--platform` value and appears in every usage string (read_jsonl.py:19, 22, 31, 3047).

Either add the directory and the search, or remove `agy` from the identifier-resolution surface
so the CLI stops implying a lookup that cannot happen. Where Anti-Gravity writes its transcripts
is not determinable from this code — needs an owner's answer. (`~/bin/ai/jsonl/agy_to_jsonl.py`
in the source tree is the likely place that knowledge lives; it is not materialized into the
package.)

## 5. Document the classification rule ordering

Rule 1 (`source != "USER_EXPLICIT"` → `injected`, agy.py:38-40) short-circuits every content test
below it, so a `SYSTEM`-sourced skill expansion classifies as `injected` rather than `skill`.
That may well be right, but nothing says so, and the ordering is the kind of thing a
re-implementation reshuffles without noticing. Either state the intent in the code or restructure
so the order does not matter.

## 6. Carry `status` or drop it

`status` is read (agy.py:137) and stored in `platform_extras` for tool results only (256). Nothing
reads it. Either surface it (a failed tool result is worth distinguishing — Claude has
`is_error` for exactly this) or stop collecting it.
