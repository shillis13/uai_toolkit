# Standardized CLI Session JSONL Schema v1.0

## Purpose

Canonical interchange format for CLI chat/session history used by `ai_general/scripts/jsonl/read_jsonl.py` and its platform adapters.

Goals:
- normalize Claude Code, Codex, and Gemini session files into one parse target
- preserve enough source detail for best-effort or exact same-platform round-trips
- keep derived display/grouping concerns out of the persisted schema
- remain extensible across future platform and schema revisions

## Design Principles

1. **Semantic + source preservation**
   - Semantic records power downstream parsing and display.
   - Optional source-preservation records keep original platform records/text for lossless same-platform round-trips.

2. **Extensible envelope**
   - Every line has `schema`, `version`, and `record_kind`.
   - New record kinds and new payload fields may be added without breaking older readers that ignore unknown fields.

3. **Derived views stay derived**
   - Turn/day/section envelopes are **not** persisted in the standardized JSONL.
   - Day-grouping, turn-grouping, and similar presentation-only structures remain output of `read_jsonl.py`.

4. **Platform-specific data is allowed**
   - Platform-specific fields belong in `platform_metadata`, `platform_extras`, or `extensions`.
   - Not every field must be printable across all platforms.

## File Structure

A standardized file is newline-delimited JSON. Each line is an envelope:

```json
{
  "schema": "ai_root.standardized_cli_session_jsonl",
  "version": "1.0",
  "record_kind": "session|source_record|message|event",
  "payload": { ... }
}
```

Recommended ordering:
1. one `session` record
2. zero or more `source_record` records
3. zero or more `event` records
4. zero or more `message` records

## Record Kinds

### 1. `session`

Session-level metadata.

```json
{
  "schema": "ai_root.standardized_cli_session_jsonl",
  "version": "1.0",
  "record_kind": "session",
  "payload": {
    "session_id": "...",
    "platform": "claude|codex|gemini",
    "source_format": "json|jsonl",
    "platform_variant": "optional variant label",
    "source_path": "/absolute/original/path",
    "start_time": "ISO-8601 or platform-native string",
    "last_updated": "ISO-8601 or platform-native string",
    "kind": "main|subagent|...",
    "metadata": {},
    "platform_metadata": {},
    "roundtrip": {},
    "extensions": {}
  }
}
```

#### Notes
- `metadata` is platform-agnostic miscellaneous session data.
- `platform_metadata` is original session/header metadata that may only make sense on the source platform.
- `roundtrip` documents how same-platform export should be attempted, e.g. `emit_source_records`, `emit_source_text`, or semantic reconstruction.

### 2. `source_record`

Optional source-preservation line used for lossless or near-lossless same-platform round-trip.

```json
{
  "schema": "ai_root.standardized_cli_session_jsonl",
  "version": "1.0",
  "record_kind": "source_record",
  "payload": {
    "source_id": "src-000001",
    "sequence": 1,
    "raw_text": "exact original line or source blob",
    "raw_obj": {},
    "timestamp": "optional normalized timestamp",
    "platform_type": "platform top-level type",
    "platform_subtype": "optional subtype",
    "extensions": {}
  }
}
```

#### Notes
- For line-oriented formats, `raw_text` is normally the original line without trailing newline.
- For Gemini legacy `.json` snapshots, a `source_record` may hold the **entire original file text** in one record.
- Consumers that only need normalized messages may ignore `source_record` lines entirely.

### 3. `message`

Normalized semantic message record. This is the primary thing `read_jsonl.py` parses downstream.

```json
{
  "schema": "ai_root.standardized_cli_session_jsonl",
  "version": "1.0",
  "record_kind": "message",
  "payload": {
    "record_id": "msg-000001",
    "sequence": 1,
    "timestamp": "ISO-8601 or platform-native string",
    "role": "user|assistant|system",
    "message_type": "user|response|thinking|tool_use|tool_result|system|meta|skill|agent_result|injected",
    "content_text": "plain text view",
    "content_blocks": [],
    "tool": {
      "name": "optional tool name",
      "input": {},
      "call_id": "optional call id"
    },
    "visible": true,
    "source_ids": ["src-000004"],
    "platform_extras": {},
    "extensions": {}
  }
}
```

#### Notes
- `content_text` is the normalized printable text view.
- `content_blocks` allows future richer normalized content without breaking `content_text` consumers.
- `source_ids` links semantic records back to original platform records.
- `platform_extras` stores platform-specific semantic details that are not promoted to common fields.

### 4. `event`

Reserved for future non-message semantic records that should remain normalized but are not directly printable as transcript messages.

```json
{
  "schema": "ai_root.standardized_cli_session_jsonl",
  "version": "1.0",
  "record_kind": "event",
  "payload": {
    "record_id": "evt-000001",
    "sequence": 1,
    "timestamp": "...",
    "event_type": "...",
    "content_text": "optional human summary",
    "source_ids": [],
    "platform_extras": {},
    "extensions": {}
  }
}
```

## Round-Trip Guidance

### Same-platform round-trip priority

Preferred order:
1. emit preserved `source_record.raw_text` / snapshot text when available
2. otherwise reconstruct from normalized `message` records plus session/platform metadata

This means:
- `platformA.original -> standardized -> platformA.new` should strive to be exact when source-preservation records are present.
- cross-platform round-trip is **not** assumed to be lossless.

## Envelopes That Remain Output-Only

The following are intentionally **not** persisted as standardized records in v1.0:
- per-day transcript sections
- per-turn group wrappers
- presentation labels like “Today — Sunday”
- rendered transcript-only summaries

These are derived views produced by `read_jsonl.py` after parsing normalized `message` records.

## Compatibility Expectations

Readers should:
- require `schema` and `record_kind`
- ignore unknown keys
- preserve unknown `extensions` content when rewriting if possible

Writers should:
- keep `record_kind` stable
- add new optional fields rather than redefining old ones
- use new `version` only for incompatible changes

## Platform Mapping Summary

- **Claude Code**
  - Source format: JSONL
  - Typical round-trip strategy: emit preserved source lines

- **Codex**
  - Source format: JSONL
  - Typical round-trip strategy: emit preserved source lines

- **Gemini**
  - Source format: either legacy pretty-printed `.json` snapshot or newer `.jsonl` event log
  - Typical round-trip strategy:
    - snapshot: emit preserved full source text when available
    - event log: emit preserved source lines
