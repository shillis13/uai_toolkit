---
name: Claude usage limits — Max 20x plan
description: Measured usage limits for Max $200 plan — weekly cap, 5h windows, Opus
  vs Sonnet cost, rolling window mechanics
status: active
---

Max 20x ($200/mo) measured limits (as of May 2026, post-doubling):

- **5-hour window:** ~1,800 messages (post May 6 2026 doubling)
- **Weekly cap:** One full 5h fill = ~15% of weekly budget. Only ~6.6 full fills fit per week (~33 hours of maxed usage).
- **Opus vs Sonnet:** Opus consumes ~5x more allocation than Sonnet for equivalent work. Routing routine tasks through Sonnet yields up to 5x more work within same weekly cap.
- **Weekly reset:** Starts when you FIRST USE Claude after the previous period expires, not when the period ends. If period expires Wednesday but you don't use until Friday, new period runs Friday to Friday.
- **5h doubling:** May 6 2026 doubled the 5h window only. Weekly cap unchanged.

Mitigation: Sonnet for routine work (coordination, hooks, scripts, docs). Opus for complex reasoning (architecture, complex TypeScript, design). Codex/Gemini for reviews/research (different quota). LLLM for repetitive evaluations (zero Claude cost).

Sources: dev.to measured testing (alexdobrushskiy), Anthropic help center, HN discussions. Full research in Hamilton session context.
