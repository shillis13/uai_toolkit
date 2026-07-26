---
name: feedback_no_mass_fleet_actions_from_single_diagnosis
description: Don't extrapolate a single-session fix into a fleet-wide mass action;
  confirm scope + test on one first
status: active
---

A problem diagnosed on ONE session does not justify a fleet-wide sweep — even with the user's approval.

**Incident (2026-06-28):** diagnosed a stale comms MCP tool-cache on my *own* session, fixed it with `/mcp reconnect comms`, then mass-injected the same reconnect into 17 sessions via `comms_reconnect_mcp_servers`.

**Why it was wrong:** Most sessions may not have had the problem. The reconnect tool injects a *visible* `/mcp` slash-command into each terminal; on **Codex** sessions it's a no-op (`Usage: /mcp [verbose]`); and it left sessions **looking "stuck at /mcp"** in PianoMan's **iOS app Code feature** view (he had to manually stop the prior response + reprompt to clear each). The terminals were actually fine, but the appearance was alarming and the cleanup landed on him. Net: friction created, not removed.

**How to apply:** Scope fixes to the session(s) actually affected. Before any fleet/multi-session action — *even an approved one* — (1) confirm the problem's real scope (which sessions have it; do Codex/Gemini even apply?), and (2) **test on ONE session and verify the effect — including how it looks from the user's vantage** — before applying to the rest. "Approved" ≠ "do it to all at once, unverified." Mass injection of slash-commands/keystrokes is especially risky: it's visible, platform-specific, and can leave sessions needing manual recovery. Related: [[feedback_never_destructive_on_siblings]], [[feedback_communicate_during_critical_ops]].
