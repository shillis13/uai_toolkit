# `sessions` — the session, terminal, and context server

*Explanation / front matter. For the full, exhaustive tool list, see the [tool reference appendix](../../../docs/user_guide/reference/scaffolding/mcp-tools/sessions.md).*

`sessions` is one of this workspace's local **Model Context Protocol (MCP)** servers. MCP is the open standard that lets an AI assistant call external tools; each server here bundles a related set of tools that any connected assistant can invoke.

`sessions` manages the running AI assistants themselves. A **session** here means one running command-line AI assistant — a single conversation with its own identity, terminal, and state. This server launches new sessions, sends keystrokes to a terminal, and reads a session's status and result. It keeps a small key-value store of state per session and manages that session's own context window (the text the model can currently see). It can also call out to a locally-hosted large language model for side reasoning and install scheduled background tasks.

## When you'd reach for it

Reach for `sessions` when you need to create, drive, or inspect a running AI assistant — or manage the resources one consumes. Launch a fresh command-line agent with a role (the job a session is launched to do) and a task; type into its terminal and read back what it produced; stash a counter or flag in its state store; page bulky material out of its context so it stays responsive and reload it later; ask a local model a question without spending the main model's turn; or register a recurring task that runs on a schedule.

## Main capability groups

- **Session lifecycle** — launch a new command-line agent, attach to or read a running session, list sessions, send keystrokes to its terminal, fetch its status or final result, switch its model, and kill or remove it.
- **Session state store** — get, set, list, load, persist, and remove per-session key-value state, including numeric increment and decrement.
- **Session server control** — start, stop, and check the status of the background service that tracks sessions.
- **Context operations** — measure a session's context usage and reshape it: offload (page bulky payloads out to a sidecar — a companion file — losslessly), rehydrate (reverse that), and slim, summarize, and consolidate (variations on trimming and merging what is in context), plus "bounce" (schedule a self-restart so the session reloads a lighter transcript). Most default to a safe dry-run that previews without changing anything.
- **Local large language model (LLM)** — send a prompt plus a file or text to a locally-hosted model and get a response, synchronously or in the background.
- **Scheduled tasks** — create, install, run, enable, disable, edit, and inspect background tasks that run on a schedule.

## Full tool reference

The complete list of every tool, its parameters, and its one-line purpose lives in the generated appendix:
**[`sessions` MCP tools](../../../docs/user_guide/reference/scaffolding/mcp-tools/sessions.md)** (59 tools).

<!--
## Sources verified against
- ai_general/apps/mcps/sessions/server.py — server name "sessions"; docstring "consolidates cli-agent, session, local-llm"; shells through agent_ops_cli.py
- ai_general/apps/mcps/sessions/tools.yml — 59 tool definitions (authoritative tool list)
- ai_general/apps/mcps/sessions/tools/ — modules: context_ops, sched_tasks, sessions_cli_agent, sessions_local_llm, sessions_session (capability groups derived from these + tool-name prefixes sched_task_*, sessions_state_*, sessions_server_*, context_*, sessions_reason_*)
- ai_general/data/MCP.json — servers.sessions (command_python)
- ai_general/docs/user_guide/reference/scaffolding/mcp-tools/sessions.md — appendix (purposes: context_offload = lossless paging w/ dry_run default; context_bounce = schedule self-resume then /exit; sessions_reason_on_text = prompt+text to loaded local LLM; sessions_launch_agent = launch CLI agent w/ role+platform)
Editorial: hand-written front matter. Audience = new outside human. Not git-committed.
-->
