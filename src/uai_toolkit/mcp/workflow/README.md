# `workflow` — the tasks, todos, and dev-workflow server

*Explanation / front matter. For the full, exhaustive tool list, see the [tool reference appendix](../../../docs/user_guide/reference/scaffolding/mcp-tools/workflow.md).*

`workflow` is one of this workspace's local **Model Context Protocol (MCP)** servers. MCP is the open standard that lets an AI assistant call external tools; each server here bundles a related set of tools that any connected assistant can invoke.

`workflow` is how work gets tracked and structured. It holds the shared to-do list, generates and moves tasks through templated workflows, keeps free-form notes, runs repeatable multi-step procedures, and manages isolated development environments so parallel work does not collide. Where `comms` moves messages between sessions and `sessions` manages the assistants, `workflow` manages the *work itself* — what needs doing, what stage it is in, and where it is being done. A **session** here means one running command-line AI assistant — a single conversation with its own identity and terminal.

## When you'd reach for it

Reach for `workflow` when you need to record, assign, or advance a unit of work. Create a to-do and move it across a kanban board; generate a task from a template for a specific platform (which vendor tool: Claude/Codex/Gemini); keep a running note and link it to a to-do; kick off a **playbook** (a predefined multi-step procedure) or a **watcher** (a trigger that fires a command when a file changes); or spin up a **devtree** (an isolated git worktree — a self-contained checkout of the code — so one session can work without disturbing another's files).

## Main capability groups

- **Todos** — create, list, get, update, complete, move, and trash to-dos; set status; add or remove tags and flags; assign and unassign; view a kanban board; find and validate.
- **Tasks** — generate a task from a template, get and list tasks, move a task between stages, and list the available templates and platforms.
- **Notes** — create, list, read, and edit notes; append messages or captures; set status; and link a note to a to-do.
- **Playbooks and watchers** — start and stop playbooks (predefined multi-step procedures), and start, stop, and list file watchers (triggers that run a command when a matching file changes).
- **Devtrees** — create, refresh, commit, push, merge, open a pull request from, check the status of, list, and destroy isolated git-worktree development environments.
- **Prompt library** — save, get, list, update, and delete reusable prompt templates.

## Full tool reference

The complete list of every tool, its parameters, and its one-line purpose lives in the generated appendix:
**[`workflow` MCP tools](../../../docs/user_guide/reference/scaffolding/mcp-tools/workflow.md)** (55 tools).

<!--
## Sources verified against
- ai_general/apps/mcps/workflow/server.py — server name "workflow"; docstring "consolidates task-coord, todo, devtree"; libs task_coord_lib, todo_mgr
- ai_general/apps/mcps/workflow/tools.yml — 55 tool definitions (authoritative tool list)
- ai_general/apps/mcps/workflow/tools/ — modules: prompt_library, workflow_devtree, workflow_note, workflow_task_coord, workflow_todo (capability groups derived from these + tool-name prefixes)
- ai_general/data/MCP.json — servers.workflow (command_python)
- ai_general/docs/user_guide/reference/scaffolding/mcp-tools/workflow.md — appendix (purposes: workflow_devtree_create = "isolated dev environment (git sparse-checkout worktree)"; workflow_start_playbook = "creates initial task or runs start action"; workflow_start_watcher = "fswatch-based file watcher"; workflow_gen_task = "generate a task from template")
Editorial: hand-written front matter. Coined terms defined inline: playbook, watcher, devtree. Audience = new outside human. Not git-committed.
-->
