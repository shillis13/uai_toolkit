---
name: reference_messaging_backtick_shell_eval
description: Sending comms messages with code/backticks via messaging.py in Bash —
  backticks (and $) get shell-evaluated even inside double quotes; use the Python
  send path or a file
status: active
---

When sending a comms message whose body contains **backticks**, `$`, or other shell-active characters via `messaging.py send --content "…"` in a **Bash** tool call, the shell command-substitutes the backticks (and expands `$`) **even inside double quotes** — silently dropping/mangling that portion of the message (you'll see a stray `X: command not found` warning, but the send still "succeeds" with corrupted content).

Hit 2026-07-01 sending ThroughLine a technical note that contained `` `.state != "persistent"` `` — the backtick span was executed and dropped; the key sentence never arrived.

**How to send code/technical content safely:**
- Write the body to a file (Write tool → no shell), then send via a small Python call that imports `messaging_mgr` and calls `send_message(to=…, content=open(path).read(), reply_to="none", subject=…, urgency="async")`. This bypasses shell interpolation entirely.
- Or avoid backticks/`$` in the prose (spell out "state != persistent" instead of code-fencing it).

This is the same class as `[[reference_git_guardian]]`-style operational gotchas — the send *reports success* while the content is wrong, so verify the sent body when it contained shell-active chars. Related: MCP comms tools (`comms_send_prompt`) don't have this problem (no shell layer), but they *poke* the recipient — see the active-vs-pull distinction in [[project_self_bounce_proven]]'s comms notes.
