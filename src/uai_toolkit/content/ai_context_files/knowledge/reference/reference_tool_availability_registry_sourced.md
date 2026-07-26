---
name: reference_tool_availability_registry_sourced
description: Claude Code deferred-tool availability on resume comes from the live
  ToolSearch registry, not cumulative on-chain deferred_tools_delta history — so offloading
  old tool-catalog attachments is safe for availability
status: active
---

Proven empirically on a live session (Tideline, 2026-07-01, golden-probe test with BC): **deferred-tool availability after a resume is sourced from the live ToolSearch registry, NOT from the cumulative sum of on-chain `deferred_tools_delta` attachments.**

Test: offload `--stub-attachments` stubbed the old deltas so `mcp__workflow__workflow_note_read`'s only on-chain declarations were archived-out. Post-bounce it still (a) got re-emitted in the fresh resume catalog from the registry and (b) ToolSearch-resolved + CALLED successfully returning real data. If availability were on-chain-cumulative, stubbing would have removed it and the harness couldn't re-add it.

Consequence: paging out old `deferred_tools_delta` catalog attachments (a large silent per-resume context cost — the ~240-tool catalog re-emits every resume, often bigger than the conversation) does not reduce tool availability. This cleared "gate 2" for making offload `--stub-attachments` default-on.

Caveat that matters: the *shape* of the stub does matter even when availability doesn't — flattening list-typed attachment fields (`addedNames` etc.) to bare strings breaks resume (`.map`/`.join` crash). See [[reference_resume_fails_content_map_join]]. Fix = shape-preserving stub + a pre-write resume-integrity guard that aborts the offload if any list field would flatten.
