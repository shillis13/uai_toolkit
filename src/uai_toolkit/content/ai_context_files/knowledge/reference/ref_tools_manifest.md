---
id: tools_manifest
name: Tools Manifest
status: active
version: 2.0.0
updated: 2026-07-09
---

# Tools Manifest

The AI-accessible tools: MCP servers, the session launcher, the manager CLIs, and the
key operational scripts. Verify against the live tree — this is a snapshot.

> **v2.0 (2026-07-09):** rewritten for the current toolset (the v1.3.0 Feb doc listed archived
> launchers, wave/shard tooling, and `todo_mgr`). MCP servers/tools are catalogued in
> `ref_mcp_servers` and `ref_ontology_glossary` — not duplicated here.

---

## MCP servers

Local custom servers under `ai_general/apps/mcps/` (registered in `data/MCP.json`): **comms**,
**knowledge**, **sessions**, **workflow** (each with a `tools.yml`), plus **chat-playwright**
(browser/web-chat, aliased `browser`/`chat`). `workstate` = third-party `mcp-tasks`.
→ See **`ref_mcp_servers`** for the full server + tool catalog.

## Session launcher

**`ai_general/scripts/cli/ai_launch.py`** — launches CLI sessions (tmux), role bootstrapping,
resume, fork, session identity. Symlinked as `claudeCli` / `codexCli` / `geminiCli`.

## Manager CLIs

Thin CLI faces over the same logic the MCP servers use. Base: `~/bin/ai/mgrs/`.

| CLI | Purpose |
|---|---|
| `ctx-files-mgr` | Context-files index + delivery (`context_mgr.py`): list/get/search/reindex/validate, link/unlink/move, archive. |
| `todos-mgr` | Todos: create/list/assign/move/status (also workflow MCP `workflow_todo_*`). |
| `notes-mgr` | Notes: create/read/add-message/link-todo (also `workflow_note_*`). |
| `projects-mgr` | Project entities. |
| `msgs-mgr` | Inter-session messages (also comms MCP). |
| `sched-task-mgr` | Scheduled tasks / launchd jobs (also sessions MCP `sched_task_*`). |
| `gg` / `git_guardian` | Submit git-write requests to Git-Guardian (the only sanctioned git-write path). |

## Key operational scripts

Under `ai_general/scripts/` (many mirrored read-only at `~/bin/ai/`):

| Script | What it does |
|---|---|
| `context_files/context_mgr.py` | Builds/queries `context.db` (the context-files index). Owns reference edits. |
| `context_files/guidance_cli.py` | Delivery: `get_context` / `get_role` / `how_to` (backs the knowledge MCP). |
| `git_guardian/git_guardian.py` | `request` → routes commit/push work to Git-Guardian. |
| `messages/messaging_mgr.py` | Inter-session messaging engine (send/reply/broadcast, notify). |
| `prompting/send_prompt.py` | Injects a prompt into a target session (`prompt://` / `uai://` endpoints). |
| `session_mgmt/session_store.py` | Authoritative session registry (`sessions.db`). |
| `chat_pipeline/01_split … 07_append` | Chat-history ingestion pipeline (numbered stages). |
| `notifications/send_user_notification.py` | User-facing macOS notifications. |

## Conventions

- **Git writes** → Git-Guardian only (`gg` / `git_guardian.py request`).
- **Context-file reference edits** → `context_mgr.py link/unlink/move` (never hand-edit refs).
- Prefer the **MCP tool** or **mgr CLI** over calling a script directly when one exists — logic
  lives in the scripts; MCP faces and CLIs are thin wrappers.
