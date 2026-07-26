---
name: execution_approach_selection
description: When choosing between inline execution vs subagent dispatch, decide autonomously
  based on context usage, task needs, and review type
status: active
---

Don't ask "which approach?" — choose and state your choice with brief rationale.

**Why:** Asking the user to pick between execution approaches is a banal "go ahead" decision that wastes a turn. The user delegates authority; use it.

**How to apply:**

Factors for **inline execution** (same session):
- Low-to-moderate context usage — plenty of room to work
- Task needs deep awareness of what was just discussed or built
- Sequential tasks where each depends on the prior result
- Quick fixes, small features, iterations on recent work

Factors for **subagent dispatch** (fresh agent):
- High context usage (>60%) — subagents get a copy, expensive
- Task is independent and self-contained (has a plan doc, spec, clear inputs/outputs)
- Task benefits from a fresh perspective without accumulated assumptions
- Multiple independent tasks that can run in parallel

Factors for **different AI type** (Codex, Gemini via MCP):
- Code review — always prefer a different AI for reviews (fresh eyes, different biases)
- Peer review, architecture review, spec review — different perspective is the whole point
- When you've been going in circles on a problem — a second opinion breaks the loop

Context caching: subagents DO inherit your full context as a copy. At high context usage this is wasteful. Prefer inline when context is heavy unless the task genuinely needs isolation.
