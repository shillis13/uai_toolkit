---
name: TO YOU markers — format and numbering
description: 'Use TO YOU section markers on every response; numbering resets to #1
  each user turn'
status: active
---

Always use `TO YOU: #N` section markers on user-facing output sections.

Numbering resets to #1 at the start of each new turn (user prompt). It is NOT cumulative across the conversation. The markers are per-turn output sections, not a running conversation counter.

**Why:** Claude passively ignored this rule for multiple messages — default training behavior (clean minimal output) silently overrode an explicit instruction. User correctly pointed out system prompt should carry more weight than defaults. Separately, Claude was incrementing the counter across turns instead of resetting per turn.

**How to apply:** Before finalizing any response, check: does this response have TO YOU markers? First TO YOU block in a new turn is always #1. Treat like the response footer — mandatory on every response.
