---
name: ref_comms_architecture
title: Comms Architecture
description: AI-to-AI comms never materialized despite multiple designs — needs enforcement infrastructure (hooks) not just protocols
status: active
---

AI-to-AI communication patterns have been designed multiple times but never actually used in practice.
The protocols exist (messages MCP, direct/broadcast, reply-routing) but AIs don't check for messages
unless forced to. The missing piece is enforcement infrastructure — hooks that trigger AIs to look
at their message queues, not just protocols that assume they will.

**Why:** AIs are fire-and-forget. They don't maintain operational awareness. Every stall in the first
UAI attempt traced to an agent without a pulse loop or one that treated silence as "okay."

**How to apply:** Any comms design for UAI must include the trigger mechanism, not just the message
format. Hooks are the enforcement layer. Codex doesn't support hooks (as of 2026-04), so Codex
comms need a different trigger (periodic reminder in pre-prompt, or polling from the app side).

Related: UAI needs a unified notification system where one event (e.g., "session waiting for input")
can reach AI (via hook/reminder), app (via Tab indicator), and user (via macOS notification) through
a single emit — not three separate ad-hoc implementations.
