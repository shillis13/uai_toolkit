---
id: ai_architecture_overview
name: AI Architecture Overview
status: active
version: 1.0.0
created: 2026-05-05
updated: 2026-05-07
description: Canonical orientation map for the AI CLI ecosystem — launch, identity, coordination, memory, hooks, comms, traits, and UnifiedCLI.
supersedes:
  - ai_cli_scaffolding_overview_v1.1.md
  - architecture_augmentation_framework_v1.1.md
  - architecture_reference_combined_v1.1.md
last_reconciled_against:
  - ai_memories/80_working_memory/manifest.yml
  - ai_general/scripts/cli/ai_launch.py
  - ai_general/data/hooks/dispatch.py
  - ai_general/apps/mcps/comms/server.py
  - ai_general/scripts/session_mgmt/session_store.py
  - ai_general/scripts/messages/SCHEMA.md
  - ai_general/scripts/messages/messaging.py
  - ai_general/scripts/jsonl/condense.py
  - ai_general/data/scheduled_tasks/*.yml
  - ~/.claude/settings.json (hook configuration)
---

# AI Root Architecture Overview

**Version:** 1.0.0
**Status:** Active — canonical ecosystem orientation map
**Scope:** Launch, identity, session stores, TODOs/tasks, hooks, comms, memory, briefs, traits/profiles, local LLM, transcript tooling, UnifiedCLI.
**Companion docs (planned — todo_0288):**
- Doc 2: `arch_traits_profiles_registry.latest.md` — traits, profiles, registry architecture
- Doc 3: `arch_memory_context_library.latest.md` — memory, context, and library architecture

---

## 1. One-Screen Mental Model

The AI CLI stack turns terminal agents — Claude CLI and Codex CLI (and formerly Gemini CLI, retired 2026-07-12) — into a persistent, inspectable, orchestratable worker ecosystem. The core principle: **terminal CLIs stay real terminal sessions; everything around them becomes structured data and durable control surfaces.**

```
                                AI CLI ECOSYSTEM
┌─────────────────────────────────────────────────────────────────────────────────┐
│ User / Orchestrator / Another AI                                                │
│   │                                                                             │
│   ├─ launches/resumes ─▶ ai_launch.py ─▶ terminal substrate ─▶ live CLI       │
│   │                    [identity+bootstrap]  [tmux/zellij/PTY]  [Claude/etc.]   │
│   │                                                                             │
│   ├─ controls ────────▶ session_ops.py / send_prompt.py / hooks                 │
│   │                    [write/read/status] [prompt queues] [event handlers]     │
│   │                                                                             │
│   ├─ coordinates ─────▶ TODO tracker ─▶ Task-Coordination ─▶ callbacks/messages │
│   │                    [intent/backlog] [worker execution] [completion routing] │
│   │                                                                             │
│   ├─ remembers ───────▶ working memory + session state + session briefs         │
│   │                    [cross-platform] [per-session KV] [front-loaded context] │
│   │                                                                             │
│   └─ composes self ───▶ traits → roles → profiles → bootstrap prompts           │
│                        [source docs] [identity fragments] [session behavior]    │
└─────────────────────────────────────────────────────────────────────────────────┘
```

Useful shorthand: **terminal = actuator; SQLite/JSONL = index; `ai_comms/` = nervous system; traits/memory = durable cognition; hooks = reflex arc.**

### Conceptual Frame

The system extends the five canonical LLM agent components — Perception, Reasoning, Memory, Tools, Action — across multiple platforms with shared memory and coordinated execution. Each component has augmentations:

- **Perception** augmented by hooks (prepend context, inject standing messages, deliver queued prompts)
- **Reasoning** augmented by local LLM fallback, quality gates, intent-following observers
- **Memory** augmented by cross-platform working memory slots, session briefs, chat-history pipeline
- **Tools** augmented by MCP servers wrapping script contracts, devTrees for isolation
- **Action** augmented by prompt delivery, callbacks, task coordination, notification system

---

## 2. Launch, Identity, and Session Stores

`ai_launch.py` is the only supported entry point for launching AI CLI sessions. The symlinks `claudeCli` and `codexCli` point to it (a `geminiCli` symlink also existed, but Gemini CLI was retired 2026-07-12); `argv[0]` selects platform behavior.

```
User / UCI / MCP
   │
   ▼
┌────────────────────────────────────────────────────────────────────┐
│ ai_launch.py                                                     │
│  ├─ platform detection (argv[0] or --platform)                     │
│  ├─ bootstrap assembly: global → platform → roles/profile → task   │
│  ├─ tracking_id + optional platform UUID                           │
│  ├─ sessionInfo/state/env files                                    │
│  ├─ session_store.py registration                                  │
│  └─ prebuilt command handed to lib_session_substrate.py            │
└───────────────────────────┬────────────────────────────────────────┘
                            ▼
             tmux/zellij/node-pty session running Claude/Codex (Gemini retired 2026-07-12)
```

### Session Identity Layers

┌──────────────────────┬───────────────────────────────────────────────────────────────┬──────────────────────────┐
│ **Layer**            │ **Meaning**                                                   │ **Owner**                │
├──────────────────────┼───────────────────────────────────────────────────────────────┼──────────────────────────┤
│ `tracking_id`        │ Workspace primary key (`YYYYMMDD_HHMMSS_{uuid8}_{platform3}`) │ `ai_launch.py`         │
├──────────────────────┼───────────────────────────────────────────────────────────────┼──────────────────────────┤
│ Terminal session     │ Attachable tmux/zellij name (same as tracking_id)             │ Substrate                │
├──────────────────────┼───────────────────────────────────────────────────────────────┼──────────────────────────┤
│ `cli_session_id`     │ Platform-native conversation UUID                             │ Platform CLI + discovery │
├──────────────────────┼───────────────────────────────────────────────────────────────┼──────────────────────────┤
│ `parent_tracking_id` │ Lineage: worker/fork/handoff parent                           │ Launcher/session store   │
├──────────────────────┼───────────────────────────────────────────────────────────────┼──────────────────────────┤
│ `display_name`       │ Human-friendly name (chosen by agent or user)                 │ Session store            │
└──────────────────────┴───────────────────────────────────────────────────────────────┴──────────────────────────┘

### Two Stores

┌───────────────────────┬─────────────────┬────────────────────────────────────────────┬───────────────────────────────┐
│ **Store**             │ **Scope**       │ **Purpose**                                │ **Backing**                   │
├───────────────────────┼─────────────────┼────────────────────────────────────────────┼───────────────────────────────┤
│ `session_store.py`    │ Cross-session   │ Identity, lineage, lifecycle, tags,        │ SQLite:                       │
│                       │ registry        │ relationships, briefs                      │ `ai_general/data/sessions.db` │
├───────────────────────┼─────────────────┼────────────────────────────────────────────┼───────────────────────────────┤
│ `store.py` /`         │ One session     │ Mutable session-specific name/value state  │ `state.{uuid8}.json` in       │
│ ``session_mgr.py`     │                 │                                            │ session data dir              │
└───────────────────────┴─────────────────┴────────────────────────────────────────────┴───────────────────────────────┘

The per-session KV store supports reserved namespaces validated by `schema_session_state_keys.latest.yml`: `env.*`, `context.*`, `session.*`, `loaded.*`, `conversation.*`, `footer.*`.

---

## 3. TODO Tracker vs Task-Coordination

The system deliberately separates **intent/backlog** from **executable assignment**.

**TODO tracker** (`ai_general/work/todos/`, `todos-mgr`) is for backlog and project memory. TODOs are directory-shaped records with `notes.md`, status files, flags, tags, and optional children.

**Task-Coordination** (`task_coord_cli.py`, `task_coord_lib.py`, workflow MCP) is for worker execution. The v9.0 protocol uses zero-byte flag files for state transitions. Atomic directory moves prevent claim races. `.response.md` carries intermediate updates; `.completion.md` is the final deliverable.

Rule of thumb: **TODO = "this should exist"; Task = "this worker should do this now."**

---

## 4. Hooks Architecture

The hook framework intercepts CLI lifecycle events via a single dispatcher. Platform configuration points to `ai_general/data/hooks/dispatch.py`, and the dispatcher dynamically runs handlers in `ai_general/data/hooks/{HookType}/` by numeric filename order.

### Execution Model

- **`_sync` handlers:** Run sequentially, stdin piped, output aggregated. Exit code 2 = **block** (stops immediately, forwarding the blocking handler's output).
- **`_async` handlers:** Spawned in background, stdout/stderr suppressed. Fire-and-forget.
- Adding a new behavior = dropping in a handler file. No platform config changes needed.

### Hook Types and Current Handlers

┌────────────────────┬─────────────────────────────────────────────────────────────────────────────────────┬───────────────────────────────────────┐
│ **Event**          │ **Handlers**                                                                        │ **Purpose**                           │
├────────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┤
│ `SessionStart`     │ `01_inject_standing_messages_sync.py`                                               │ Front-load durable                    │
│                    │                                                                                     │ instructions/reminders from standing  │
│                    │                                                                                     │ message store                         │
├────────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┤
│ `UserPromptSubmit` │ `01_deliver_queued_prompts_sync.py` , `02_prepend_context_sync.py` ,                │ Inject queued prompts as              │
│                    │ `03_notify_unread_messages_sync.py`                                                 │ `additionalContext` , prepend         │
│                    │                                                                                     │ datetime/context usage, notify of     │
│                    │                                                                                     │ unread messages                       │
├────────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┤
│ `PreToolUse`       │ `01_devtree_boundary_check_sync.sh` , `02_devtree_bash_warning_sync.sh`             │ Prevent wrong-tree edits, warn on     │
│                    │                                                                                     │ high-risk bash in devTrees            │
├────────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┤
│ `PostToolUse`      │ `01_audit_tools_async.py`                                                           │ Durable tool usage audit trail        │
├────────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┤
│ `PreCompact` /     │ `01_compaction_sync.py`                                                             │ Compaction event logging, context     │
│ `PostCompact`      │                                                                                     │ transition evidence                   │
├────────────────────┼─────────────────────────────────────────────────────────────────────────────────────┼───────────────────────────────────────┤
│ `Stop`             │ `01_deliver_postresponse_sync.py` , `02_block_permission_seeking_sync.py` ,         │ Post-response prompt delivery,        │
│                    │ `03_quality_gate_sync.py` , `04_capture_context_sync.py` ,                          │ autonomy enforcement, quality         │
│                    │ `05_block_intent_without_action_sync.py` , `06_notify_unread_messages_sync.py` ,    │ observation, context capture, message │
│                    │ `07_remind_owed_replies_sync.py`                                                    │ reminders                             │
└────────────────────┴─────────────────────────────────────────────────────────────────────────────────────┴───────────────────────────────────────┘

### Hook-Driven Prompt Injection

The key integration between hooks and comms: **queued prompts are delivered automatically via hook handlers**, not pushed directly to the terminal.

1. A message/orchestrator queues a prompt: YAML entry in `ai_comms/prompts_inbox/{session}/`
2. On next user prompt (`UserPromptSubmit`), handler loads the queue, composes entries (urgency-sorted, max 10 entries / 8000 chars), and outputs them as `additionalContext`
3. Claude sees the queued content as part of the user's turn — no manual paste needed
4. Post-response prompts (`postResponse` delivery) are delivered by the `Stop` handler via `send_prompt.py --force`

### Hook Installation

**Current (as-built):** Claude Code hooks are configured directly in `~/.claude/settings.json`, each pointing to `dispatch.py` with the hook type as argument. Gemini CLI (retired 2026-07-12) had only an `AfterTool` audit hook (`hook_audit_tools.py`), never the full dispatcher architecture. Codex hooks are configured via `AGENTS.md` managed blocks.

**Planned:** A platform-agnostic YAML source (`hooks.yml`) and installer (`install_hooks.py`) are designed in `schema_hook_definition.latest.yml` but not yet implemented. When built, this would enable managing all platform hook configurations from one YAML file with sidecar manifests for idempotent updates.

---

## 5. Comms Architecture

The communications layer provides asynchronous messaging, prompt delivery, and callback routing across sessions.

### URI Namespaces

```
ai_comms/
├─ messages/                    File-based message store
│  ├─ inbox/{recipient}/        Direct messages (YAML)
│  ├─ archive/{recipient}/      Archived messages
│  └─ broadcasts/               Broadcast messages
├─ prompts_inbox/{session}/     Queued prompts for hook-driven injection
├─ notifications/user/          macOS notifications
└─ {platform_cli}/              Platform-specific areas
   ├─ instant_messaging/        Direct chats
   ├─ tasks/                    Dispatch task directories
   └─ to_execute/               Task queue
```

### Messages

Messages are YAML files in `ai_comms/messages/inbox/{recipient}/`:

- **ID format:** `msg_{YYYYMMDD_HHMMSS}_{random8}`
- **Types:** `direct` (one recipient), `broadcast` (all or group)
- **Urgency tiers:** `interrupt` > `prompt` > `async` > `passive`
- **Response types:** `reply`, `acknowledge`, `none`
- **Threading:** `replying_to` (immediate parent) + `conversation_id` (thread root)
- **Callbacks:** Optional endpoint URI for response routing

Messages wait in inboxes until read/acknowledged. Hook handlers (`03_notify_unread_messages_sync.py`) notify sessions of unread messages.

### Prompt Queue Entries

Prompt queue entries are YAML files in `ai_comms/prompts_inbox/{session}/` — distinct from messages:

- **ID format:** `queue_{YYYYMMDD_HHMMSS}_{random8}`
- **Delivery modes:** `pre-prompt` (injected on next user turn), `post-prompt` (same), `postResponse` (injected after AI responds via Stop hook)
- **Fields:** `to`, `content`, `urgency`, `delivery`, `ready_for_delivery`, `queued_at`, `source`, `callback_endpoint`

The `UserPromptSubmit` hook delivers `pre-prompt` and `post-prompt` entries as `additionalContext`. The `Stop` hook delivers `postResponse` entries via `send_prompt.py --force`.

### Callback Endpoints

The callback system decouples responders from response channels:

- **`prompt://target/session`** — Send via `send_prompt.py` (supports template, submit, force flags)
- **`file://path`** — Write to regular file
- **`fifo://path`** — Write to named FIFO
- **`none://`** — No-op (fire-and-forget)

Endpoints are constructed via `comms_make_endpoint` and delivered via `comms_deliver`. The responder doesn't need to know how to reach the requester — just calls `deliver(endpoint, message)`.

### Prompt Queuing

Any session/tool/script can queue a prompt for another session:

```
queue-prompt → YAML file → ai_comms/prompts_inbox/{session}/ → UserPromptSubmit hook → additionalContext
```

This is the primary mechanism for AI-to-AI communication when the target session is busy. The queued prompt waits until the target's next human prompt, then gets injected automatically.

### Standing Messages

Persistent messages that apply to scopes: `global`, `platform`, `team`, `project`. Injected by `SessionStart` hook for new sessions. Resumed sessions get only messages newer than their last activity.

### MCP Comms Server

The comms MCP server (`ai_general/apps/mcps/comms/`) aggregates three tool modules:
- **`comms_prompting`** — send_prompt, observe_session, wait_response, schedule, rename, condense, read_history (wraps `send_prompt.py`, `session_ops.py`, `condense.py`)
- **`comms_messages`** — send, broadcast, list, acknowledge, queue-prompt, standing messages, sweep (wraps `messaging.py`; underlying CLI supports more operations than MCP exposes)
- **`comms_callbacks`** — make_endpoint, deliver, parse_endpoint (wraps `callback_lib.py`)

---

## 6. Memory, Briefs, and Context Front-Loading

Five persistence layers form a continuum from hot to cold:

┌────────────────┬─────────────────┬────────────────────────────────────────┬─────────────────────────────────────────┐
│ **Layer**      │ **Temperature** │ **Backing**                            │ **Purpose**                             │
├────────────────┼─────────────────┼────────────────────────────────────────┼─────────────────────────────────────────┤
│ Context window │ Hot             │ In-memory (API)                        │ Current conversation                    │
├────────────────┼─────────────────┼────────────────────────────────────────┼─────────────────────────────────────────┤
│ Working memory │ Warm            │ `ai_memories/80_working_memory/*.yml`  │ Cross-session observations, user model, │
├────────────────┼─────────────────┼────────────────────────────────────────┼─────────────────────────────────────────┤
│ slots          │                 │                                        │ tools, context                          │
├────────────────┼─────────────────┼────────────────────────────────────────┼─────────────────────────────────────────┤
│ Session state  │ Warm            │ `state.{uuid8}.json`                   │ Per-session mutable data (context %,    │
│ KV             │                 │                                        │ loaded docs, footer)                    │
├────────────────┼─────────────────┼────────────────────────────────────────┼─────────────────────────────────────────┤
│ Session briefs │ Warm/Cool       │ `ai_general/data/session_briefs/*.yml` │ Successor-ready handoff dossiers        │
├────────────────┼─────────────────┼────────────────────────────────────────┼─────────────────────────────────────────┤
│ Chat history   │ Cold            │ `ai_memories/10_exported/` →           │ Archived conversations, searchable      │
├────────────────┼─────────────────┼────────────────────────────────────────┼─────────────────────────────────────────┤
│ pipeline       │                 │ `40_histories/` → `50_shards/`         │                                         │
└────────────────┴─────────────────┴────────────────────────────────────────┴─────────────────────────────────────────┘

### Working Memory

Shared slots under AI control (`ai_memories/80_working_memory/`), defined by `manifest.yml`:
- **AUTO-load:** 03=user model, 04=communication, 05=tools/patterns, 06=current context, 07=limitations, 12=reflection journal (Claude CLI only — `platform_scope: claude_cli`)
- **TOPIC-load:** 08=learnings, 09=cross-AI notes
- **DEMAND-load:** 10=project history, 11=novel phrasing

Agents read and write slots through the knowledge MCP memory tools (`knowledge_memory_append` / `_read` / `_search`), never by hand-editing the slot files.

### Session Briefs and Condensation

Briefs are NOT casual summaries — they are successor-ready dossiers built from JSONL transcripts via a condensation pipeline:

1. `compact_jsonl.py` — first-pass compaction (strip tool results, trim text)
2. `condense.py` — dispatch to a condenser session with `operational_handoff.md` prompt
3. Condenser AI writes YAML brief to `ai_general/data/session_briefs/`
4. `launch_from_brief.py` — new session receives brief at startup

Brief schema covers: source scope, summary, participants, current frontier, decisions, risks, traps, unresolved items, and next actions. Frontier-weighted: the last ~20% of the transcript disproportionately determines next actions.

Custom condensation: `condense.py` supports `--prompt` (custom condensation prompt), multiple `--src-uuid`/`--src-file` for multi-source merges, `--prepare-only` (output prepared input without dispatching), `--output`/`--name`/`--description` for metadata, and `--max-text` for size limits.

For details on the full memory stack and chat-history pipeline, see Doc 3.

---

## 7. Local LLM Integration

The local LLM layer provides private/offline reasoning and a fallback evaluator for hooks. MCP surface lives under the `sessions` server; business logic in `~/bin/ai/lllm/`.

Tools: `server_status`, `server_start`, `server_stop`, `list_models`, `switch_model`, `reason_on_text`, `reason_on_file`, async variants with `request_id` → `get_result`.

Default: OpenAI-compatible endpoint on `localhost:11881`. Used directly for private analysis, asynchronously with callbacks, or indirectly by the Stop quality gate.

---

## 8. Traits, Roles, Profiles, and Bootstrap Composition

The trait system is the source-of-truth content layer; profiles compose it into runnable identities.

```
ai_general/ai_context_files/           authored knowledge/instructions
  ├─ knowledge/10_architecture/        architecture maps (this doc)
  ├─ processes/30_protocols/           coordination protocols
  ├─ procedures/                       operational rules
  ├─ methods/                          problem-solving methods
  └─ templates/                        task/review/scaffold templates

ai_general/ai_profiles/               composition layer
  ├─ globals/                          universal bundles
  ├─ platforms/                        Claude/Codex platform traits (Gemini retired 2026-07-12)
  ├─ roles/                            assistant, worker, dev, reviewer, ...
  └─ profiles/                         composed identities

scan_traits_registry.py → traits_registry.db → guidance MCP / guidance_cli.py
```

Files are authored by humans/AIs; the SQLite traits registry is generated. Roles are atomic identity fragments. Profiles assemble global + platform + role traits for launch. The guidance MCP provides `get_role`, `get_skill`, `get_trait`, `how_to`, `search` for on-demand trait retrieval.

For details on the trait ontology, doc-type taxonomy, and registry architecture, see Doc 2.

---

## 9. Scheduled Tasks and Automation

Cron-based scheduled tasks managed by `scheduled_task_mgr.py` (REPL + CLI tool):

- YAML definitions in `ai_general/data/scheduled_tasks/*.yml`
- Auto-installs to crontab on every mutation
- Self-healing: `@reboot` bootstrap entry reinstalls after reboots

Current scheduled groups: bootstrap (@reboot self-healing), chat pipeline (4:00-5:00 AM), news scan (5:30 AM daily, 6:30 AM Sunday weekly), notification inbox sweep, reflection (daily), repo maintenance, system monitoring.

The news agent (Dispatch) runs as a persistent Claude Code session, forked from a seed conversation, with automatic session rotation after 30 runs.

---

## 10. UnifiedCLI and MCP Wrappers

### MCP Server Architecture

Local MCP servers are thin adapters over script contracts:

┌────────────────────┬─────────────────────────────────────────────────┐
│ **MCP namespace**  │ **Script layer exposed**                        │
├────────────────────┼─────────────────────────────────────────────────┤
│ `knowledge`        │ Guidance, search, memory, JSONL, chat pipeline  │
├────────────────────┼─────────────────────────────────────────────────┤
│ `sessions`         │ CLI-agent/session ops, session state, local LLM │
├────────────────────┼─────────────────────────────────────────────────┤
│ `workflow`         │ Task-Coordination, TODO manager, DevTrees       │
├────────────────────┼─────────────────────────────────────────────────┤
│ `comms`            │ Prompting, messages, callbacks                  │
├────────────────────┼─────────────────────────────────────────────────┤
│ Browser/chat tools │ Chat-playwright / Chrome CDP automation         │
└────────────────────┴─────────────────────────────────────────────────┘

### UnifiedCLI (UCI)

Electron-based graphical workspace. Calls `ai_launch.py` for create/resume/fork, `session_ops.py` for attach/read/write/status, `session_store.py` for identity/lifecycle, and `read_jsonl.py` for transcripts. The UI adds session cards, groups, tabs, PromptBox, `xterm.js`/`node-pty` terminal attach, transcript viewer, search, and compact-handoff workflows.

Design boundary: **UCI and MCPs call backend contracts; they do not construct platform CLI commands or raw tmux/zellij commands.**

### Unified AI Interface (UAI)

UAI is the planned successor to UCI — a full application rewrite with component API, command bus, external ground truth architecture, and multi-platform session management. Currently in architecture/design phase under `ai_general/projects/unified_ai_interface/`. See project docs there for details; UAI is not yet operational and is not part of the current ecosystem architecture.

---

## 11. Feature Inventory

┌────────────────────────────────┬────────────────────────────────────────────────────────────────────────┬
│ **Capability**                 │ **Primary files/tools**                                                │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Launch Claude/Codex            │ `ai_launch.py` , `claudeCli` , `codexCli` (`geminiCli` retired 2026-07-12) │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Terminal                       │ `session_ops.py` , `lib_session_substrate.py`                          │
│ attach/read/write/status       │                                                                        │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Cross-session registry         │ `session_store.py` , `ai_general/data/sessions.db`                     │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Per-session KV state           │ `store.py` , `session_mgr.py` , `schema_session_state_keys.latest.yml` │  
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ TODO backlog                   │ `ai_general/work/todos/` , `todos-mgr` , workflow todo MCP                   │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Executable Tasks               │ `task_coord_cli.py` , `task_coord_lib.py` ,                            │
│                                │ `ai_comms/{platform}/tasks/`                                           │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Messages / prompt queues       │ `messaging.py` , `send_prompt.py` , `ai_comms/messages/` ,             │
│                                │ `prompts_inbox/`                                                       │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Hooks / prompt augmentation    │ `dispatch.py` , `{HookType}/NN_handler_{sync\async}.py`                │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Scheduled tasks                │ `scheduled_task_mgr.py` , `ai_general/data/scheduled_tasks/*.yml`      │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ User notifications             │ `send_user_notification.py` , `inbox_manager.py`                       │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ JSONL transcript tooling       │ `read_jsonl.py` , `catjsonl.py` / `jgrep` , `compact_jsonl.py` ,       │
│                                │ `condense.py`                                                          │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Session Briefs / handoff       │ `operational_handoff.md` , `condense.py` , `launch_from_brief.py`      │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Local LLM                      │ `~/bin/ai/lllm/` , `sessions_local_llm.py` , port `11881`              │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Parallel orchestration         │ `dispatch_query.py` , wave/fork patterns, playbooks                    │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Isolated development           │ `~/bin/ai/devTrees/`                                                   │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ Traits/roles/profiles          │ `ai_general/ai_traits/` , `ai_general/ai_profiles/` ,                  │
│                                │ `guidance_cli.py`                                                      │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ GUI workspace                  │ UnifiedCLI Electron app, `xterm.js` , `node-pty` , React panels        │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ System monitoring              │ `sysmond` , SwiftBar plugin, scheduled collectors                      │
├────────────────────────────────┼────────────────────────────────────────────────────────────────────────┼
│ AI news aggregation            │ News agent (Dispatch), `news_launcher.sh` , daily/weekly reports       │
└────────────────────────────────┴────────────────────────────────────────────────────────────────────────┴

---

## 12. Known Drift

Older traits and docs may reference retired designs. The current as-built direction:

1. `ai_launch.py` owns launch and identity creation (not `claude_cli.py` wrappers).
2. `session_store.py` SQLite owns session registry, lifecycle, lineage, tags, relationships, briefs.
3. `store.py` / `session_mgr.py` owns per-session KV state with reserved namespaces.
4. `session_ops.py` owns live terminal interaction (not direct tmux/zellij commands).
5. `ai_comms/` is the durable coordination plane.
6. Hooks use a single dispatcher per event type with dynamic handlers underneath.
7. MCP servers wrap scripts rather than duplicate orchestration logic.
8. UnifiedCLI calls backend contracts, never platform CLIs directly.
9. Tracking IDs use `YYYYMMDD_HHMMSS_{uuid8}_{platform3}` format (not old `claude_cli_chat_*` naming).
10. Chat history pipeline directories are `10_exported/`, `20_preprocessed/`, `30_converted/`, `40_histories/` (not old `10_raw_exports/`, `20_normalized/`, `30_chunked/`).

**Actively reworking:** Chat history library and JSONL tooling are under revision. Shard/research system assumptions need revalidation against current model context limits. The quality gate Stop handler currently observes/logs rather than blocks.

**Not yet implemented:** UAI is in architecture/design phase. Hook-driven quality gates that block (vs observe) are designed but not deployed for blocking mode. Cross-platform memory federation (ai_ecosystem_manifest.yml) capability exists but is unused.
