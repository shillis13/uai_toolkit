---
name: reference-claude-code-mechanics
description: How Claude Code (the product/harness) itself works — hook types and other
  platform mechanics, grown as learned
status: active
---

Durable facts about **Claude Code's own mechanics** (the product/harness), distinct from our workspace infrastructure. This is the "how Claude works" reference — grow it as we confirm things against the docs. Docs root: https://code.claude.com/docs/en/hooks-guide and /en/hooks.

## Hook types (the `type` field — NOT the event)
The command/prompt distinction is the per-hook `type`, not the lifecycle event (UserPromptSubmit, PreToolUse, …):
- **`command`** — runs a shell command; deterministic. **Every hook in our workspace is this type** (11 declarations). Each event registers exactly ONE command hook that shells to `ai_general/data/hooks/dispatch.py <Event>`, which fans out to the numbered handler scripts internally. So the "12 UserPromptSubmit scripts" are handlers beneath one command hook — not 12 hooks.
- **`prompt`** — no shell; Claude Code sends the `prompt` + hook input to a model (Haiku default; `model` field to override) for a single-turn yes/no verdict `{"ok": bool, "reason": ...}`. For judgment, not deterministic rules. On `UserPromptSubmit`, `ok:false` ends the turn with a warning line — it's a GATE, it cannot inject/modify context.
- **`agent`** — spawns a subagent that can read files/run tools before returning the same ok/reason verdict; experimental; 60s / up-to-50-turn defaults.
- **HTTP hooks** also exist.

**We use ZERO prompt or agent hooks — 100% command hooks.** (Confirmed 2026-07-12 against the docs.)

See also [[reference_environment_invariants]]. Candidate to promote into a fleet-shared `ai_context_files/knowledge/reference/` context file if the memory-system revisit decides these belong there.
