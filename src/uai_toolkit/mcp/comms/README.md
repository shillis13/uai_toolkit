# `comms` — the messaging and coordination server

*Explanation / front matter. For the full, exhaustive tool list, see the [tool reference appendix](../../../docs/user_guide/reference/scaffolding/mcp-tools/comms.md).*

`comms` is one of this workspace's local **Model Context Protocol (MCP)** servers. MCP is the open standard that lets an AI assistant call external tools; each server here bundles a related set of tools that any connected assistant (Claude, Codex, or Gemini running at the command line) can invoke.

`comms` is how running AI sessions talk to each other and how a person steers them. A **session** here means one running command-line AI assistant — a single conversation with its own identity and terminal. When several sessions are working in parallel, `comms` is the layer that carries a note from one to another, drops a fresh prompt into another session's input box, fans a single announcement out to a whole group, and coordinates who is allowed to interrupt whom.

## When you'd reach for it

Reach for `comms` when work spans more than one session and they need to exchange information without a human copy-pasting between terminals. Send a direct message and wait for the reply; broadcast one prompt to five sessions at once; schedule a prompt to arrive in ten minutes; lock a session so nothing interrupts it mid-task; or ask a session whether it is busy before you nudge it. It is the mailroom, the intercom, and the switchboard for the fleet of sessions.

## Main capability groups

- **Direct messages** — send a message to one session, read your inbox, reply, reply-all, acknowledge, archive, and search past messages.
- **Prompts** — write text directly into another session's prompt input area, read what is currently typed there, check whether it is clear to write to, and queue prompts for delivery.
- **Broadcasts** — send the same message, prompt, slash command (a `/`-prefixed instruction typed into a session), or context file to a group of sessions in one call.
- **Scheduled prompts** — schedule a prompt to fire at a future time, then list or cancel what is pending.
- **Session coordination** — lock and unlock a session, block or unblock it from receiving prompts, check if it is busy, and observe its current terminal state.
- **Callbacks and endpoints** — build and parse callback URIs and endpoints (the address a result is delivered back to) and deliver a result back to a waiting caller.
- **Recipient sets** — register a named group of sessions so you can address them all by one name later.
- **Standing messages** — post a persistent announcement (scoped to everyone, a team, a platform — which vendor tool: Claude/Codex/Gemini — or a project) that sessions read on demand rather than being pushed.
- **Context staging** — stage reference files or notes into a session's context so they load on its next turn, and request condensation of a session's own history into a handoff file.

## Full tool reference

The complete list of every tool, its parameters, and its one-line purpose lives in the generated appendix:
**[`comms` MCP tools](../../../docs/user_guide/reference/scaffolding/mcp-tools/comms.md)** (51 tools).

<!--
## Sources verified against
- ai_general/apps/mcps/comms/server.py — server name "comms", dynamic tool discovery from tools/*.py
- ai_general/apps/mcps/comms/tools.yml — 51 tool definitions (authoritative tool list)
- ai_general/apps/mcps/comms/tools/ — module split: comms_broadcast, comms_callbacks, comms_messages, comms_prompting, comms_recipients (capability groups derived from these + tool names)
- ai_general/data/MCP.json — servers.comms (command_python, deployed to claude_cli, claude_desktop, gemini, uci, codex)
- ai_general/docs/user_guide/reference/scaffolding/mcp-tools/comms.md — appendix (tool count 51, purposes)
Editorial: hand-written front matter; audience = new outside human per style_spec.md. Not git-committed.
-->
