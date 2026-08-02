# platform_adapters/agy.py — redevelopment design

Scope: `src/uai_toolkit/jsonl/platform_adapters/agy.py` (277 lines). Adapter for Anti-Gravity
("AGY") transcripts. Anti-Gravity is an AI coding tool whose transcript is a flat list of
numbered *steps* rather than a message tree.

## 1. What it is for

Translate an Anti-Gravity JSONL transcript into the shared `StandardizedSession` model. It is the
only adapter in the family that does **not** implement the reverse direction.

## 2. Interface — and the family contract it implements

```python
PLATFORM = "agy"                                             # agy.py:15
sniff(path: Path, first_obj: Any | None = None) -> bool      # agy.py:67
from_file(path: str | Path) -> StandardizedSession           # agy.py:95
# to_platform_text  — ABSENT
```

**`to_platform_text` is missing.** The other four adapters define it; calling
`adapter_for_platform("agy").to_platform_text(session)` raises `AttributeError`. In practice
nothing calls it — its only caller anywhere is
`~/bin/ai/jsonl/tests/test_standardized_adapters.py:36`, and that test's `FIXTURES` dict
(test file lines 19-24) covers claude, codex, and two gemini shapes but **not** agy. AGY has a
separate test, `~/bin/ai/jsonl/tests/test_agy_adapter.py`, which necessarily cannot test
round-trip. So the family contract has four members but only four-fifths coverage, and the gap is
invisible until someone calls it.

Module-level constants that are part of the format knowledge:
`_TOOL_RESULT_TYPES` (agy.py:18-21) — the six step types that represent tool output;
`_KNOWN_SOURCES` (24) — `{USER_EXPLICIT, SYSTEM, MODEL}`.
Private helpers: `_classify_user_input` (27), `_extract_tool_name_from_type` (82).

**What `sniff` must guarantee** (family rules in `__init___design.md`): cheap, no re-read of the
file, never raises, tolerant of `first_obj is None`. AGY's is the narrowest of the five:

```python
# agy.py:73-79
isinstance(first_obj.get("step_index"), int) and first_obj.get("source") in _KNOWN_SOURCES
```

No path signal at all — Anti-Gravity's transcript location is not encoded here, and
`read_jsonl.find_jsonl` has **no AGY search path** (read_jsonl.py:635-675 covers Claude, Codex,
Gemini, Grok only). AGY files are therefore reachable only by explicit path, via `read-file`.

**Detection order matters, and AGY is deliberately first** (`platform_adapters/__init__.py:41-47`).
The in-code comment says AGY's `step_index` signature is unambiguous, which is why it can safely
lead. Grok reinforces this from the other side by explicitly refusing any record containing
`step_index` (grok.py:66-67) — the same de-confliction expressed twice.

## 3. Integration

- **Called by**: `platform_adapters/__init__.detect_platform` and `read_jsonl.parse_session`.
- **Depends on**: `standardized_session`, `platform_adapters.common` (`normalize_timestamp`; it
  also imports `compact_json` at agy.py:13 and never uses it — the residue of being copied from a
  sibling that has `to_platform_text`).
- **Test**: `~/bin/ai/jsonl/tests/test_agy_adapter.py`. Not materialized into the package.
- There is also `~/bin/ai/jsonl/agy_to_jsonl.py` in the source tree, not examined here — likely
  the converter that produces the files this adapter reads. Not materialized into the package.

## 4. Data & config

Reads the transcript one line at a time (agy.py:104). Writes nothing. No environment variables.
No configured location — see §2.

## 5. How it works

### 5.1 The AGY record shape

Each line is a step: `{step_index, type, source, content, status, created_at, tool_calls}`.
`source` says who produced it (`USER_EXPLICIT` / `SYSTEM` / `MODEL`) and `type` says what kind of
step it is. Timestamps come from `created_at` (agy.py:117), not `timestamp`.

### 5.2 `from_file` (95-277)

Single pass. Every parseable line becomes a `StandardizedSourceRecord` with verbatim `raw_text`,
`platform_type = type`, `platform_subtype = source` (119-129). Malformed lines are skipped
silently (110-111) — same defect as every other adapter, but here it has no round-trip
consequence because there is no round-trip.

Dispatch is on `type` first, then `source`:

- **`USER_INPUT`** (142-163) → one record, role `user`, `message_type` from
  `_classify_user_input`. Empty content produces nothing.
- **`source == "SYSTEM"`** (166-185) → only `SYSTEM_MESSAGE` with non-empty content becomes a
  `system` record. `CONVERSATION_HISTORY` and other system steps are explicitly treated as
  metadata-only (comment at 185) — source record, no message.
- **`source == "MODEL"`** (188-259):
  - `PLANNER_RESPONSE` → a `response` record if there is content (189-208), then one `tool_use`
    record per entry in `tool_calls` (210-234).
  - `type in _TOOL_RESULT_TYPES` → a `tool_result` record with role `"tool"` (236-259).

**Tool call correlation is synthetic.** AGY does not carry tool call ids, so the adapter
manufactures one: `f"agy-step-{step_index}-{tool_name}"` on the call side (216) and
`f"agy-step-{step_index}-{tool_name}"` on the result side (239), where the result's `tool_name`
comes from mapping the step type through `_extract_tool_name_from_type` (82-92). **These two
never match**: the call uses the `step_index` of the `PLANNER_RESPONSE` step, the result uses the
`step_index` of the result step, which is a different (later) step. So every AGY `tool_use` and
every AGY `tool_result` gets a unique id and nothing pairs. Whether pairing was intended is
unknown — the construction is clearly *trying* to pair, so this reads as a defect rather than a
decision.

Header (261-272): `session_id = path.stem`, `kind = "main"` always (AGY has no subagent concept
here), `platform_variant = "anti_gravity_jsonl"`.

### 5.3 `_classify_user_input` (27-64) — content-heuristic classification

This is the part with no equivalent elsewhere in the family. Its docstring states the reason
plainly: *"AGY doesn't have structural metadata like Claude's isMeta/sourceToolUseID/origin, so we
use content-based heuristics."* The rules, in order:

1. `source != "USER_EXPLICIT"` → `injected`.
2. Content contains `<command-name>`, `<skill-`, or `Launching skill:` → `skill`.
3. Content contains `<task-notification>` or `<agent-result>` → `agent_result`.
4. Content (left-stripped) starts with `<system-reminder>` → `injected`.
5. Content contains all of `[Message]`, `sender=`, `priority=` → `injected` (inter-agent
   messages from this toolkit's own comms layer).
6. Content contains `<ADDITIONAL_METADATA>` but not `<USER_REQUEST>` → `injected`.
7. Content contains `<USER_SETTINGS_CHANGE>` but not `<USER_REQUEST>` → `injected`.
8. Otherwise → `user`.

Rules 5, 6, and 7 encode knowledge of *this toolkit's* injection markers, not Anti-Gravity's — the
adapter is recognizing text that our own hooks and comms layer inserted.

## 6. Essential vs incidental

**Essential**

- The `step_index` + `source` sniff, and AGY's position **first** in the detection order.
- Timestamps from `created_at`, not `timestamp`.
- The four-way user classification producing the same vocabulary as Claude
  (`user` / `skill` / `agent_result` / `injected`). Whatever the mechanism, the *output* has to be
  the shared vocabulary or `read_jsonl`'s turn logic and filters see a different set of types per
  platform.
- Treating `CONVERSATION_HISTORY` and other SYSTEM steps as metadata-only. They are replayed
  context, not new content; counting them as messages would double-count the session.
- The `_TOOL_RESULT_TYPES` set and the step-type → tool-name mapping — this is format knowledge
  that exists nowhere else.

**Incidental**

- The specific marker strings in `_classify_user_input`. They are this toolkit's injection
  markers and will drift as the toolkit changes.
- The synthetic `agy-step-{n}-{name}` id format (§5.2) — it does not work and nothing depends on
  it.
- The unused `compact_json` import (13).
- `metadata={"source_line_count": …}` and `roundtrip={"strategy": "emit_source_records"}` (270-271)
  — the latter is actively misleading, since no `to_platform_text` exists to honor it.

## 7. Platform notes (Windows / WSL)

- **No path-based detection**, so AGY is the one adapter with no separator problem. It is also
  the one adapter that cannot be found by UUID, since `read_jsonl.find_jsonl` has no AGY search
  path.
- **Tier A — no explicit encoding** on `path.open()` (agy.py:104). Platform default; on Windows a
  non-ASCII transcript raises `UnicodeDecodeError` out of `from_file`, uncaught.
- **Tier A — `line.rstrip("\n")`** (107) leaves `\r` on CRLF files inside `raw_text`. Harmless
  here (no round-trip) but it also means `content` extracted from such a line carries stray
  carriage returns into display.
- Nothing Tier B or C.

## 8. Risks & sharp edges

- **No `to_platform_text`.** The family contract is not uniform, and the gap is a runtime
  `AttributeError` rather than anything a type checker or the test suite catches (§2).
- **Tool calls and tool results never pair** (§5.2). Any consumer matching `tool_call_id` — the
  `call_id → tool_name` lookup in `read_jsonl.session_stats` (read_jsonl.py:2083-2086), for
  example — finds nothing for AGY.
- **Classification is text-matching and will silently rot.** Every rule in `_classify_user_input`
  depends on a literal marker string. When a hook's wrapper text changes, injected content
  silently reclassifies as `user`, which means it starts *counting as a human turn*. Turn
  numbering, `--turns`, and every turn-scoped statistic shift under it, with no error. There is no
  test asserting the markers still match what the toolkit emits.
- **Rule ordering is load-bearing and undocumented.** Rule 1 (non-explicit source → `injected`)
  runs before every content test, so a `SYSTEM`-sourced skill expansion is `injected`, not
  `skill`. Whether that is intended is unknown.
- **No chain, interval, or turn structure.** As with Codex and Gemini,
  `read_jsonl._chain_and_prompt_meta` finds nothing and falls back to increment-on-user-message
  numbering (read_jsonl.py:997-1008).
- **`session_id = path.stem`** (263) with no validation — a renamed file changes the session id.
- **`status` is captured into `platform_extras` for tool results only** (256) and never used.
- **Malformed lines vanish silently** (110-111).
