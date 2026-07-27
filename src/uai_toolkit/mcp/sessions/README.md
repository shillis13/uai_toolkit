# `sessions` — the session, terminal, and context server

*Explanation / front matter. For the full, exhaustive tool list, see the [tool reference appendix](../../../docs/user_guide/reference/scaffolding/mcp-tools/sessions.md).*

`sessions` is one of this workspace's local **Model Context Protocol (MCP)** servers. MCP is the open standard that lets an AI assistant call external tools; each server here bundles a related set of tools that any connected assistant can invoke.

`sessions` manages the running AI assistants themselves. A **session** here means one running command-line AI assistant — a single conversation with its own identity, terminal, and state. This server launches new sessions, sends keystrokes to a terminal, and reads a session's status and result. It keeps a small key-value store of state per session and manages that session's own context window (the text the model can currently see). It can also call a separately configured language-model endpoint for side reasoning and install scheduled background tasks.

## When you'd reach for it

Reach for `sessions` when you need to create, drive, or inspect a running AI assistant — or manage the resources one consumes. Launch a fresh command-line agent with a role (the job a session is launched to do) and a task; type into its terminal and read back what it produced; stash a counter or flag in its state store; page bulky material out of its context so it stays responsive and reload it later; ask a configured reasoning model a question without spending the main model's turn; or register a recurring task that runs on a schedule.

## Main capability groups

- **Session lifecycle** — launch a new command-line agent, attach to or read a running session, list sessions, send keystrokes to its terminal, fetch its status or final result, switch its model, and kill or remove it.
- **Session state store** — get, set, list, load, persist, and remove per-session key-value state, including numeric increment and decrement.
- **Session server control** — start, stop, and check the status of the background service that tracks sessions.
- **Context operations** — measure a session's context usage and reshape it: offload (page bulky payloads out to a sidecar — a companion file — losslessly), rehydrate (reverse that), and slim, summarize, and consolidate (variations on trimming and merging what is in context), plus "bounce" (schedule a self-restart so the session reloads a lighter transcript). Most default to a safe dry-run that previews without changing anything.
- **Configured reasoning model** — send a prompt plus bounded file text or inline text through the `mcp_prompt` endpoint chain. It may name a local or hosted service, is disabled by default, and offers synchronous calls only; the toolkit does not manage a model server or request queue.
- **Scheduled tasks** — create, install, run, enable, disable, edit, and inspect background tasks that run on a schedule.

## Full tool reference

The curated declaration set and every input schema live in [`tools.yml`](tools.yml).
The upstream workspace also generates a broader appendix, but it includes local-server and asynchronous-queue tools that this portable package deliberately omits.

<!--
## Sources verified against
- ai_general/apps/mcps/sessions/server.py — server name "sessions"; docstring "consolidates cli-agent, session, local-llm"; shells through agent_ops_cli.py
- ai_general/apps/mcps/sessions/tools.yml — upstream tool declarations; the toolkit trims seven local-server/async-queue declarations
- ai_general/apps/mcps/sessions/tools/ — modules: context_ops, sched_tasks, sessions_cli_agent, sessions_local_llm, sessions_session (capability groups derived from these + tool-name prefixes sched_task_*, sessions_state_*, sessions_server_*, context_*, sessions_reason_*)
- ai_general/data/MCP.json — servers.sessions (command_python)
- ai_general/docs/user_guide/reference/scaffolding/mcp-tools/sessions.md — upstream appendix (the toolkit reasoning calls instead use the config-only mcp_prompt endpoint chain)
Editorial: hand-written front matter. Audience = new outside human. Not git-committed.
-->
