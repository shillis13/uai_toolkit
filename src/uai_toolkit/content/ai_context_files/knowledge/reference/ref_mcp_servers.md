---
id: mcp_servers_reference_v1.0
name: Mcp Servers Reference V1.0
status: active
version: 1.0.0
created: '2026-03-21'
updated: '2026-06-21'
---

# MCP Servers & Tools Reference

**Version:** 1.0.0  
**Status:** Active  
**Location:** `ai_general/ai_context_files/knowledge/20_registries/`  
**Created:** 2026-02-04  

---

## Overview

MCP (Model Context Protocol) servers extend each CLI agent's capabilities by providing
structured tool access to inter-AI comms, the knowledge/memory store, session lifecycle,
task/workflow orchestration, and browser chat automation. Each server exposes a set of
tools callable directly from the agent's context. The workspace runs **5 live MCP servers** —
`comms`, `knowledge`, `sessions`, `workflow`, and `chat` — each sourced under
`ai_general/apps/mcps/<server>/`. (These consolidated the earlier ~13-server fleet:
guidance/knowledge-search/jsonl/memory folded into `knowledge`; cli-agent/session/local-llm
into `sessions`; todo/task-coord/devtree into `workflow`; messages/prompting into `comms`.)

## Server Inventory

### comms MCP

**Purpose:** Inter-AI messaging, prompt delivery, scheduling, session locks, and presence.  
**Source:** `ai_general/apps/mcps/comms/`  
**Tool prefix:** `comms_*`

┌────────────────┬─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ **Tool**       │ **Tools**                                                                                                               │
│ **Category**   │                                                                                                                         │
├────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Messaging      │ `comms_message` , `comms_reply` , `comms_reply_all` , `comms_message_ack` , `comms_read_message` , `comms_message_list` │
│                │ , `comms_message_responses` , `comms_search_messages` , `comms_read_history` , `comms_archive_message`                  │
├────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Broadcast      │ `comms_broadcast_message` , `comms_message_broadcast` , `comms_message_list_broadcasts` , `comms_broadcast_prompt`      │
├────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Prompt         │ `comms_send_prompt` , `comms_send_to_session` , `comms_send_slash_command` , `comms_deliver` , `comms_get_prompt_text`  │
│ delivery       │ , `comms_is_prompt_clear` , `comms_list_prompt_queue` , `comms_wait_response`                                           │
├────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Scheduling     │ `comms_schedule_future_prompt` , `comms_list_scheduled_prompts` , `comms_cancel_scheduled_prompt` ,                     │
│                │ `comms_sweep_expired`                                                                                                   │
├────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Sessions &     │ `comms_list_sessions` , `comms_is_busy` , `comms_observe_session` , `comms_lock_session` , `comms_unlock_session` ,     │
│ presence       │ `comms_list_locks` , `comms_rename_session` , `comms_check_messages` , `comms_check_owed` , `comms_list_pending`        │
├────────────────┼─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Standing       │ `comms_post_standing` , `comms_query_standing` , `comms_make_endpoint` , `comms_parse_endpoint` , `comms_load_context`  │
│ orders &       │ , `comms_condense_me`                                                                                                   │
│ endpoints      │                                                                                                                         │
└────────────────┴─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

---

### knowledge MCP

**Purpose:** Guidance delivery (traits/roles/skills/knowledge on demand), conversation-archive search, the chat-history pipeline, and the working-memory store.  
**Source:** `ai_general/apps/mcps/knowledge/`  
**Tool prefix:** `knowledge_*`

┌──────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ **Tool**     │ **Tools**                                                                                                                 │
│ **Category** │                                                                                                                           │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Guidance     │ `knowledge_guidance_search` , `knowledge_how_to` , `knowledge_get_context` , `knowledge_remind_me` ,                      │
│              │ `knowledge_get_references`                                                                                                │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Search       │ `knowledge_search` , `knowledge_grep_search` , `knowledge_stats`                                                          │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Memory store │ `knowledge_memory_read` , `knowledge_memory_append` , `knowledge_memory_update` , `knowledge_memory_delete` ,             │
│              │ `knowledge_memory_search` , `knowledge_memory_stats`                                                                      │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Chat         │ `knowledge_pipeline_status` , `knowledge_normalize` , `knowledge_chunk_file` , `knowledge_prepare_for_condensation` ,     │
│ pipeline     │ `knowledge_condense_history` , `knowledge_review_quarantine` , `knowledge_retry_quarantine` ,                             │
│              │ `knowledge_get_pipeline_config` , `knowledge_get_manifest` , `knowledge_set_slot_config`                                  │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Sessions &   │ `knowledge_list_sessions` , `knowledge_find_session` , `knowledge_read_session` , `knowledge_session_summary` ,           │
│ files        │ `knowledge_list_context` , `knowledge_read_file` , `knowledge_get_stale`                                                  │
└──────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

---

### sessions MCP

**Purpose:** CLI session lifecycle (launch/attach/kill), session state KV, the stateless reasoning service, and scheduled tasks.  
**Source:** `ai_general/apps/mcps/sessions/`  
**Tool prefix:** `sessions_*`, `sched_task_*`

┌──────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ **Tool**     │ **Tools**                                                                                                                 │
│ **Category** │                                                                                                                           │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Lifecycle    │ `sessions_launch_agent` , `sessions_attach` , `sessions_kill` , `sessions_remove` , `sessions_send_keys` ,                │
│              │ `sessions_switch_model`                                                                                                   │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Info         │ `sessions_get` , `sessions_get_status` , `sessions_get_footer` , `sessions_get_ctx_used` , `sessions_get_result` ,        │
│              │ `sessions_get_ai_root` , `sessions_list` , `sessions_list_sessions` , `sessions_list_models` , `sessions_read_session` ,  │
│              │ `sessions_set`                                                                                                            │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Session      │ `sessions_state_get` , `sessions_state_set` , `sessions_state_delete` , `sessions_state_list` , `sessions_state_keys` ,   │
│ state        │ `sessions_state_load` , `sessions_state_persist` , `sessions_state_remove` , `sessions_state_increment` ,                 │
│              │ `sessions_state_decrement`                                                                                                │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Reasoning    │ `sessions_reason_on_text` , `sessions_reason_on_text_async` , `sessions_reason_on_file` , `sessions_reason_on_file_async` │
│ service      │ , `sessions_server_start` , `sessions_server_status` , `sessions_server_stop`                                             │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Scheduled    │ `sched_task_create` , `sched_task_add` , `sched_task_edit` , `sched_task_delete` , `sched_task_enable` ,                  │
│ tasks        │ `sched_task_disable` , `sched_task_install` , `sched_task_import` , `sched_task_run` , `sched_task_list` ,                │
│              │ `sched_task_view` , `sched_task_status` , `sched_task_logs`                                                               │
└──────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

---

### workflow MCP

**Purpose:** Todo tracking, task/playbook orchestration, directory watchers, and devTree isolation.  
**Source:** `ai_general/apps/mcps/workflow/`  
**Tool prefix:** `workflow_*`

┌──────────────┬───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┐
│ **Tool**     │ **Tools**                                                                                                                 │
│ **Category** │                                                                                                                           │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Todos        │ `workflow_todo_create` , `workflow_todo_get` , `workflow_todo_find` , `workflow_todo_list` , `workflow_todo_update` ,     │
│              │ `workflow_todo_set_status` , `workflow_todo_move` , `workflow_todo_complete` , `workflow_todo_trash` ,                    │
│              │ `workflow_todo_kanban` , `workflow_todo_add_flag` , `workflow_todo_remove_flag` , `workflow_todo_add_tag` ,               │
│              │ `workflow_todo_remove_tag` , `workflow_todo_validate`                                                                     │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Tasks &      │ `workflow_gen_task` , `workflow_get_task` , `workflow_list_tasks` , `workflow_move_task` , `workflow_list_templates` ,    │
│ playbooks    │ `workflow_list_playbooks` , `workflow_get_playbook` , `workflow_start_playbook` , `workflow_stop_playbook` ,              │
│              │ `workflow_list_platforms`                                                                                                 │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ Watchers     │ `workflow_start_watcher` , `workflow_stop_watcher` , `workflow_list_watchers` , `workflow_cleanup_watchers`               │
├──────────────┼───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┤
│ DevTrees     │ `workflow_devtree_create` , `workflow_devtree_destroy` , `workflow_devtree_list` , `workflow_devtree_status` ,            │
│              │ `workflow_devtree_refresh` , `workflow_devtree_commit` , `workflow_devtree_push` , `workflow_devtree_pr` ,                │
│              │ `workflow_devtree_merge`                                                                                                  │
└──────────────┴───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────┘

---

### chat MCP

**Purpose:** Browser-based chat automation — navigate, send, and read web AI chats (Claude.ai, ChatGPT, etc.).  
**Source:** `ai_general/apps/mcps/chat/`  
**Tool prefix:** `chat_*` (exposed as `mcp__chat__*`)

┌───────────────────┬───────────────────────────────────────────────┐
│ **Tool**          │ **Description**                               │
├───────────────────┼───────────────────────────────────────────────┤
│ `open_chat`       │ Navigate to a specific chat by URL or ID      │
├───────────────────┼───────────────────────────────────────────────┤
│ `new_chat`        │ Open a new chat                               │
├───────────────────┼───────────────────────────────────────────────┤
│ `get_messages`    │ Extract messages from the current chat        │
├───────────────────┼───────────────────────────────────────────────┤
│ `send_message`    │ Type and send a message                       │
├───────────────────┼───────────────────────────────────────────────┤
│ `wait_response`   │ Wait for the response to finish               │
├───────────────────┼───────────────────────────────────────────────┤
│ `get_current_url` │ Read the active chat URL                      │
├───────────────────┼───────────────────────────────────────────────┤
│ `detect_active`   │ Detect which AI chat is active in the browser │
├───────────────────┼───────────────────────────────────────────────┤
│ `test`            │ Health check                                  │
└───────────────────┴───────────────────────────────────────────────┘

---

## Tool Usage by Actor

┌────────────────┬────────────────┬───────────────────┬──────────────────────────────────────────┐
│ **MCP Server** │ **CLI Agents** │ **Orchestrators** │ **Notes**                                │
├────────────────┼────────────────┼───────────────────┼──────────────────────────────────────────┤
│ comms          │ ✓              │ ✓                 │ Messaging + prompt-delivery backbone     │
├────────────────┼────────────────┼───────────────────┼──────────────────────────────────────────┤
│ knowledge      │ ✓              │ ✓                 │ Guidance, search, memory, chat pipeline  │
├────────────────┼────────────────┼───────────────────┼──────────────────────────────────────────┤
│ sessions       │ ✓              │ ✓                 │ Launch/manage workers; reasoning service │
├────────────────┼────────────────┼───────────────────┼──────────────────────────────────────────┤
│ workflow       │ ✓              │ ✓                 │ Todos, tasks, playbooks, devTrees        │
├────────────────┼────────────────┼───────────────────┼──────────────────────────────────────────┤
│ chat           │ ✓              │ ✓                 │ Browser chat automation                  │
└────────────────┴────────────────┴───────────────────┴──────────────────────────────────────────┘