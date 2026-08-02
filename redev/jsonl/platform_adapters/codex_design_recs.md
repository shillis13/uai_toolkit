# platform_adapters/codex.py — recommendations for the re-design

## 1. Implement the Codex half of the adapter contract, or stop pretending Codex has turns

`~/bin/ai/jsonl/DESIGN_platform_adapter_contract.md` specifies exactly what Codex needs and it is
already agreed between two authors: turn numbers from the record's `turn_id` field ("use `turn_id`
as FIRST-CLASS — the adapter sets `Message.turn_number` from `turn_id` directly; don't force
Claude-style heuristics"), compaction intervals from `compacted` envelopes, and always a single
branch because a Codex rollout is a linear event log.

None of it is implemented. `turn_id` is never read. The result is that
`read_jsonl._chain_and_prompt_meta` (read_jsonl.py:839) finds no `promptSource`, returns empty
sets, and `_assign_turn_numbers` falls back to increment-on-user-message numbering
(read_jsonl.py:997-1008). Codex sessions therefore display `Tn` values that look exactly like
Claude's and mean something different — and `--turns`, `--interval`, and every turn-scoped
statistic inherit the discrepancy silently.

Do one of:

- **Implement it.** Read `turn_id`, emit `compaction_points` from `compacted` envelopes, and
  declare a single branch. The contract document already specifies the mapping table.
- **Or make the absence explicit** — leave `turn_number` unset and have `read_jsonl` refuse
  turn-scoped operations on platforms that provide no turn structure, rather than silently
  substituting a different definition.

The contract document's own warning applies: rendering Claude-shaped numbers for Codex "would
look comparable while meaning something fundamentally different".

## 2. Stop dropping three envelope types on the floor

`event_msg`, `turn_context`, and `compacted` produce source records and no messages
(codex.py:87-88). The contract document says they should map to `MessageType.META` so their bytes
are counted but they are excluded from turn content — "Never drop local-only envelopes, and never
treat them as conversational text."

The immediate cost of dropping `compacted` is that **Codex compaction intervals are invisible**:
`read_jsonl`'s `--interval` and `compactions` command treat any Codex session as one interval.

## 3. Pick one role for tool records, across the family

`tool_result` gets `role="assistant"` here (codex.py:152). Claude uses `"user"`, Grok and AGY use
`"tool"`, Gemini uses `"assistant"`. Four adapters, three answers.

`"tool"` is the only one true on every platform. But note the change is not free: Claude's
`"user"` mirrors its wire format, and `read_jsonl`'s raw-line accounting splits user lines into
prompts vs tool_results on exactly that basis (read_jsonl.py:1142-1147). Change it deliberately
and check that accounting, or leave Claude alone and normalize only the other three — but write
down which was chosen.

## 4. Do not drop non-text content blocks

The content flattener accepts only `input_text`, `output_text`, and `text` (codex.py:103), so
`input_image` blocks — which the contract document names as Codex's attachment mechanism — produce
no record. Images in a Codex session are invisible to every consumer, including anything that
would offload or account for them. At minimum emit a placeholder record so the block's existence
and size are visible.

## 5. Replace the synthetic `session_meta` message with header metadata

`from_file` builds a `meta` message whose content is the f-string
`f"Session {payload['id']} ({payload.get('originator', 'codex')})"` (codex.py:79-80). It consumes
a message sequence number, has no corresponding source text, and `to_platform_text` has to
special-case it back out (196-197). The same information is already in
`header.platform_metadata` (172). Drop the synthetic message; let a renderer produce the line if
it wants one.

## 6. Guard `path.stem[-36:]`

The `session_id` fallback (codex.py:163) assumes a 36-character UUID tail. A renamed or shortened
file yields a truncated id with no check and no warning. Match the `rollout-<date>-<uuid>` shape
explicitly, and fall back to the whole stem if it does not match.
