---
name: feedback_prefer_subagent_execution
description: Always choose subagent-driven execution for implementation plans — don't
  ask
status: active
---

When executing implementation plans, always choose subagent-driven execution (one subagent per task, review between tasks). Don't ask the user to pick between inline and subagent — just proceed with subagents.

**Why:** The user prefers parallelism and delegation. Asking "which approach?" is unnecessary permission-seeking when the answer is always the same.

**How to apply:** After a plan is written and reviewed, immediately invoke superpowers:subagent-driven-development. Skip the "two options" prompt entirely.
