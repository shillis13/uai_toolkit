---
name: feedback_self_context_management_autonomy
description: Standing grant — use context offload/consolidate/bounce tools on my own
  recognizance, no need to ask
status: active
---

PianoMan granted standing autonomy (2026-07-02): the context offloading and consolidation tools are **mine to use on my own recognizance** — self-manage my context when it helps, don't ask first. "Feel free to repeat when you think it will help."

**Why:** context reclaim is my concern to manage, like any other tool; asking each time is friction.

**How to apply:** when context is heavy, run the offload → preflight → bounce flow (or consolidate) without asking. Proven E2E on myself 2026-07-02: `offload_tool_results.py <tid>` (archive mode, reversible) → `check_resume_integrity.py <transcript-path>` (must say "Safe to resume") → `self_restart.py --in-min 2` (schedules launchd `--resume` + /exit). First self-bounce reclaimed ~403K live-context tokens losslessly. The MCP `context_*` tools may be stale in a running server — drive the scripts directly. Aligns with [[feedback_ship_dont_checkpoint]] and [[feedback_dont_ask_just_do]].
