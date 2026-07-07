---
id: ontology_glossary
name: Ontology Glossary
status: active
version: 1.0.0
created: 2026-04-17
updated: 2026-04-17
---

# Ontology Glossary

The canonical reference for all terms, concepts, and structures in this AI workspace. Read this first — every other document assumes familiarity with these terms.

---

## Taxonomy Terms

- **Trait** — An atomic, reusable content element. The building block of the system. Lives in `ai_traits/`. A trait is a file containing knowledge, perspective, a process, a procedure, a method, a template, or a reminder. Traits are referenced by roles, skills, and profiles but never duplicated.

- **Role** — An atomic identity fragment. Carries its own description, duties, ownership scope, and references to specific traits. Examples: dev, tester, librarian, custodian. Roles are composed into profiles. Lives in `ai_profiles/roles/`.

- **Profile** — A pre-composed set of roles representing a full agent identity. Example: `developer_teammate` = [assistant, worker, dev, team_member]. Lives in `ai_profiles/`.

- **Skill** — An executable composition of traits with trigger conditions, decision trees, workflow patterns, and guidelines. Skills define *how to approach a class of problem* using available MCP tools. Lives in `ai_profiles/skills/`.

- **Composition** — The general act of assembling traits into something usable. Roles, profiles, skills, globals, and platform configs are all compositions.

- **Global** — A trait bundle included for every agent by launcher convention. Contains core perspective and procedures. Lives in `ai_profiles/globals/`.

- **Platform Config** — A trait bundle specific to a platform (Claude Code, Gemini, Codex). Included by the launcher based on target platform. Lives in `ai_profiles/platforms/`.

## Ontology Categories

The six categories that classify traits by their nature:

- **Perspective** — *How do you think?* Values, principles, identity, communication style. Shapes judgment, not specific actions. Example: `operating_principles`.

- **Knowledge** — *What is?* Facts, reference material, structural understanding, specifications, schemas. Subcategories: `10_architecture`, `20_registries`, `40_specs`, `50_schemas`.

- **Processes** — *What do you do and when?* Workflows, lifecycles, coordination sequences, cadences. Subcategories: `30_protocols`, `60_playbooks`, standalone.

- **Procedures** — *How do you do it?* Specific rules, conventions, standards, checklists. Example: `file_conventions`, `development_standards`.

- **Methods** — *How do you solve this class of problem?* Self-contained methodologies for specific problem types. Like procedures but larger, situationally entered. Example: `chat_condensation`, `search_agent`.

- **Templates** — *What's the structure for this work product?* Scaffolding that generates dynamic instances. Fixed structure, dynamic content. Example: `task_coordination_template`, `peer_review_template`.

- **Reminders** — Periodic content injected during conversations. Surfaces existing traits on a schedule. Example: "Don't forget to use your memory system."

## System Terms

- **Task** — A claimed unit of work in the task coordination lifecycle. Not a generic "thing to do." Has a specific lifecycle: staged → to_execute → in_progress → completed/error/cancelled. Managed via the workflow MCP server.

- **Todo** — A tracked work item in the todo system (`ai_general/work/todos/`). Higher-level than a Task. Todos get decomposed into Tasks when ready for execution. Managed via the workflow MCP server (`workflow_todo_*`).

- **Shard** — A Gemini CLI instance loaded with a portion of the conversation archive for parallel search. Multiple shards can search different time ranges or query angles simultaneously. Dispatched by the research-orchestration skill.

- **DevTree** — A sparse git worktree of `ai_general` providing filesystem isolation for parallel AI development. Only editable directories (scripts/, apps/, projects/, docs/) are checked out; shared directories are symlinked. Managed via the workflow MCP server (`workflow_devtree_*`).

- **Brief** — A condensed session handoff document. Contains the key decisions, context, and state from a session, formatted for a successor to pick up where the predecessor left off. Lives in `data/session_briefs/`.

- **Worker** — A CLI session executing a claimed Task. Launched by an Orchestrator, reports results back. Can be Claude, Gemini, or Codex.

- **Orchestrator** — A session that launches and coordinates Workers. Decomposes work, dispatches, monitors progress, collects results. Uses the ai-comms skill.

- **Wave** — A batch of parallel Workers processing a set of tasks simultaneously. Used in batch condensation and parallel research.

- **Condensation** — Semantic compression of chat history. Target: 70-90% token reduction while preserving key decisions, artifacts, and context. Managed via the knowledge MCP server (`knowledge_condense_history`) and the condensation-pipeline skill.

- **Bootstrap** — The documents loaded before an AI's first response. Defines what the AI knows at startup. Configured via globals + platform + role traits.

- **Formalization Ladder** — The progression from informal to formal: Procedure (prose rule) → Script (executable) → MCP Tool (atomic API) → Skill (workflow using tools). Each level formalizes the previous.

## Infrastructure Terms

- **MCP Server** — A tool provider using the Model Context Protocol. Exposes atomic operations (search, create, read, etc.) that AI instances call. 5 live servers: comms, knowledge, sessions, workflow, chat.

- **Knowledge MCP** — The MCP server that delivers traits, roles, skills, and knowledge on demand (`guidance_search`, `how_to`, `get_context`), plus conversation-archive search and the working-memory store. Queries the traits registry SQLite database. Primary cross-platform delivery mechanism. (Folds in the former guidance/knowledge-search/jsonl/memory servers.)

- **CLI Session** — A running AI instance: Claude Code, Gemini CLI, or Codex CLI. Launched via `ai_launch.py` (symlinked as `claudeCli`, `codexCli`, `geminiCli`). Runs in a tmux session.

- **Session Identity** — A two-part identifier: tmux session name (tracking ID) + CLI UUID (platform conversation ID). The tracking ID format: `{YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}`.

- **UCI / UnifiedCLI** — The Electron app for managing AI sessions. Provides a visual interface for session tabs, prompt delivery, transcript viewing, and system monitoring.

- **PromptBox** — UCI's prompt input component. Supports pre-prompt and post-prompt injection, staging before send, and configuration via a drawer.

- **AI_ROOT** — Environment variable pointing to the workspace root (`~/AI/ai_root`). All scripts resolve paths relative to this. DevTrees set their own AI_ROOT.

- **Traits Registry** — SQLite database at `data/traits/traits_registry.db` indexing all traits and compositions. Built by `scripts/traits/scan_traits_registry.py`, queried by the guidance MCP server. Not tracked in git — generated artifact.

## Architecture Terms

- **ai_traits/** — Source of truth for all content elements, organized by ontology categories. The corpus.

- **ai_profiles/** — Composition layer. Contains globals, platforms, roles, skills, and pre-composed profiles that reference traits.

- **Backwards-compat symlinks** — `docs/10_architecture` → `ai_traits/knowledge/10_architecture`, etc. Old paths still resolve during transition.

- **`.latest.*` symlinks** — Versioning convention. `foo.latest.md` → `versions/foo_v2.1.md`. Consumers read `.latest`; version files hold the history.

- **Clean split** — Design principle: files own authored data (frontmatter), SQLite owns computed data (references, hashes, token estimates). No bidirectional sync.

- **Flat composability** — Design principle: no inheritance. Profiles explicitly list roles. Roles explicitly list traits. Transparent and debuggable.
## File Index (Generated from Registry)

_181 active items. Auto-generated — do not edit manually._


### Role
- **Assistant** — `ai_profiles/roles/assistant.yml`

### Global
- **Base** — `ai_profiles/globals/base.yml`

### Platform
- **Claude Code** — `ai_profiles/platforms/claude_code.yml`
- **Claude Desktop** — `ai_profiles/platforms/claude_desktop.yml`
- **Codex** — `ai_profiles/platforms/codex.yml`

### Role
- **Custodian** — `ai_profiles/roles/custodian.yml`
- **Dev** — `ai_profiles/roles/dev.yml`
- **Dev Lead** — `ai_profiles/roles/dev_lead.yml`

### Profile
- **Dev Lead Teammate** — `ai_profiles/dev_lead_teammate.yml`
- **Developer Teammate** — `ai_profiles/developer_teammate.yml`

### Platform
- **Gemini** — `ai_profiles/platforms/gemini.yml`

### Profile
- **Individual Developer** — `ai_profiles/individual_developer.yml`

### Role
- **Lead Cli** — `ai_profiles/roles/lead_cli.yml`
- **Librarian** — `ai_profiles/roles/librarian.yml`

### Profile
- **Librarian Profile** — `ai_profiles/librarian_profile.yml`

### Trait
- **Memory Pointer Protocol** — `ai_traits/_drafts/retired/instr_memory_slot_protocol_v1.0.yml`
- **Notification Pattern V1.1** — `ai_traits/_drafts/90_drafts/to_migrate_comms_docs/docs - old dir from claude_cli/NOTIFICATION_PATTERN_v1.1.md`

### Role
- **Peer Reviewer** — `ai_profiles/roles/peer_reviewer.yml`

### Trait
- **Productivity Infrastructure Todos** — `ai_traits/_drafts/90_drafts/_archive/productivity_infrastructure_todos.md`

### Role
- **Researcher** — `ai_profiles/roles/researcher.yml`
- **Team Member** — `ai_profiles/roles/team_member.yml`
- **Tester** — `ai_profiles/roles/tester.yml`

### Profile
- **Tester Profile** — `ai_profiles/tester_profile.yml`

### Role
- **Validator** — `ai_profiles/roles/validator.yml`
- **Worker** — `ai_profiles/roles/worker.yml`

### Skill
- **ai-comms** — `ai_profiles/skills/ai_comms.yml`
- **condensation-pipeline** — `ai_profiles/skills/condensation_pipeline.yml`
- **devtree-workflow** — `ai_profiles/skills/devtree_workflow.yml`
- **documentation-audit** — `ai_profiles/skills/documentation_audit.yml`
- **peer-review** — `ai_profiles/skills/peer_review.yml`
- **research-orchestration** — `ai_profiles/skills/research_orchestration.yml`
- **todo-triage** — `ai_profiles/skills/todo_triage.yml`

### Knowledge
- **Action Log Entry Schema** — `ai_traits/knowledge/50_schemas/schema_action_log.yml`
- **Ai Communication Architecture** — `ai_traits/knowledge/10_architecture/ai_communication_architecture.latest.condensed.yml`
- **Architectural Layer Model** — `ai_traits/knowledge/10_architecture/architectural_layer_model.latest.condensed.yml`
- **Artifact Extraction** — `ai_traits/knowledge/40_specs/spec_artifact_extraction.latest.md`
- **Ascii Diagrams Claude** — `ai_traits/knowledge/10_architecture/architecture_ascii_diagrams_claude.latest.md`
- **Augmentation Framework** — `ai_traits/knowledge/10_architecture/architecture_augmentation_framework.latest.condensed.yml`
- **Chat History Indexer** — `ai_traits/knowledge/40_specs/spec_chat_history_indexer.latest.md`
- **Claude Code Plugin System Reference** — `ai_traits/knowledge/20_registries/claude_code_plugins_reference.latest.yml`
- **Claude Context Quick Notes** — `ai_traits/knowledge/claude_context_quick_notes.latest.condensed.yml`
- **Claude Desktop Skills Reference** — `ai_traits/knowledge/20_registries/claude_desktop_skills_reference.latest.yml`
- **Cli Context And Tools** — `ai_traits/knowledge/instr_cli_context_and_tools.condensed.yml`
- **Cli Enhancement Ecosystem** — `ai_traits/knowledge/20_registries/cli_enhancement_ecosystem.latest.condensed.yml`
- **Cli Environment Overview** — `ai_traits/knowledge/instr_cli_environment_overview.condensed.yml`
- **Cli Orchestration** — `ai_traits/knowledge/10_architecture/cli_orchestration.latest.condensed.yml`
- **Cli Specialized Agent Roles** — `ai_traits/knowledge/40_specs/cli_specialized_agent_roles.latest.condensed.yml`
- **Condensation Flags** — `ai_traits/knowledge/50_schemas/schema_condensation_flags.latest.yml`
- **Condensation Flags.V1.0** — `ai_traits/knowledge/50_schemas/schema_condensation_flags.v1.0.yml`
- **Daemon Architecture** — `ai_traits/knowledge/10_architecture/daemon_architecture.latest.md`
- **Data Architecture Traits And Profiles** — `ai_traits/knowledge/10_architecture/arch_data_architecture_traits_and_profiles.md`
- **Directory Structure Reference** — `ai_traits/knowledge/20_registries/directory_structure_reference.latest.condensed.yml`
- **Document Registry** — `ai_traits/knowledge/20_registries/document_registry.latest.condensed.yml`
- **Environment Overview** — `ai_traits/knowledge/instr_environment_overview.latest.condensed.yml`
- **Federated Memory Architecture** — `ai_traits/knowledge/10_architecture/federated_memory_architecture.latest.condensed.yml`
- **Glossary Knowledge Index** — `ai_traits/knowledge/20_registries/glossary_knowledge_index.latest.condensed.yml`
- **Index Files** — `ai_traits/knowledge/50_schemas/schema_index_files.latest.condensed.yml`
- **Index Specs** — `ai_traits/knowledge/20_registries/index_specs.latest.condensed.yml`
- **Inventory** — `ai_traits/knowledge/20_registries/INVENTORY.latest.condensed.yml`
- **Know Codex Mcp** — `ai_traits/knowledge/know_codex_mcp.latest.condensed.yml`
- **Knowledge Glossary** — `ai_traits/knowledge/50_schemas/schema_knowledge_glossary.latest.yml`
- **Layered Context Hierarchy.Draft** — `ai_traits/knowledge/10_architecture/architecture_layered_context_hierarchy.draft.md`
- **Library System** — `ai_traits/knowledge/10_architecture/architecture_library_system.latest.condensed.yml`
- **Log Sources Mapping** — `ai_traits/knowledge/20_registries/log_sources_mapping.latest.condensed.yml`
- **Mcp Servers Reference V1.0** — `ai_traits/knowledge/20_registries/mcp_servers_reference_v1.0.md`
- **Memory Slot Schema** — `ai_traits/knowledge/50_schemas/schema_memory_slot.latest.yml`
- **Message Insert** — `ai_traits/knowledge/40_specs/spec_message_insert.latest.condensed.yml`
- **Overview** — `ai_traits/knowledge/10_architecture/architecture_overview.latest.condensed.yml`
- **Parallel Query Dispatcher** — `ai_traits/knowledge/40_specs/spec_parallel_query_dispatcher.yml`
- **Persona Engine Config Latest** — `ai_traits/knowledge/spec_persona_engine_config_latest.yml`
- **Playbook Schema Definition** — `ai_traits/knowledge/50_schemas/schema_playbook.yml`
- **Pointer Syntax** — `ai_traits/knowledge/50_schemas/schema_pointer_syntax.latest.condensed.yml`
- **Quality Gate Hierarchy** — `ai_traits/knowledge/40_specs/spec_quality_gate_hierarchy.md`
- **Reference Combined** — `ai_traits/knowledge/10_architecture/architecture_reference_combined.latest.md`
- **Response Footer** — `ai_traits/knowledge/40_specs/spec_response_footer.latest.condensed.yml`
- **Role Config** — `ai_traits/knowledge/50_schemas/schema_role_config.latest.yml`
- **Schema Evolution Guide** — `ai_traits/knowledge/50_schemas/SCHEMA_EVOLUTION_GUIDE.latest.condensed.yml`
- **Schema.Playbook** — `ai_traits/knowledge/50_schemas/schema.playbook.latest.condensed.yml`
- **Search Agent** — `ai_traits/knowledge/40_specs/spec_search_agent.latest.condensed.yml`
- **Session Identity** — `ai_traits/knowledge/40_specs/spec_session_identity.latest.condensed.yml`
- **Task Id Counter** — `ai_traits/knowledge/40_specs/spec_task_id_counter.latest.condensed.yml`
- **Task Orchestration Workflow Ascii** — `ai_traits/knowledge/40_specs/spec_task_orchestration_workflow_ascii.latest.md`
- **Taskfile** — `ai_traits/knowledge/50_schemas/schema_taskFile.latest.condensed.yml`
- **Taxonomy Document Types** — `ai_traits/knowledge/10_architecture/taxonomy_document_types.latest.md`
- **Tools Manifest** — `ai_traits/knowledge/20_registries/tools_manifest.latest.condensed.yml`
- **Vba Chain Analysis** — `ai_traits/knowledge/40_specs/spec_vba_chain_analysis.latest.md`
- **Vba Chain Breaking** — `ai_traits/knowledge/40_specs/spec_vba_chain_breaking.latest.md`
- **Vba Refactoring Plan** — `ai_traits/knowledge/40_specs/spec_vba_refactoring_plan.latest.md`
- **Wave Execution Model** — `ai_traits/knowledge/10_architecture/wave_execution_model.latest.md`
- **Wave Tree Execution** — `ai_traits/knowledge/40_specs/spec_wave_tree_execution.latest.md`

### Methods
- **Chat Condensation** — `ai_traits/methods/instr_chat_condensation.latest.condensed.yml`
- **Chat Condensation Prompt Template** — `ai_traits/methods/condensation_prompt_v1.yml`
- **Condensation Prompt V2** — `ai_traits/methods/condensation_prompt_v2.yml`
- **Prompt Condense Chat History** — `ai_traits/methods/prompt_condense_chat_history.md`
- **Prompt Continuation Seed** — `ai_traits/methods/prompt_continuation_seed.md`
- **Prompts For Response Analysis And Debug** — `ai_traits/methods/prompts_for_response_analysis_and_debug.md`
- **Search Agent Bootstrap** — `ai_traits/methods/search_agent_bootstrap.md`
- **Search Agent V2.5** — `ai_traits/methods/search_agent_v2.5.md`

### Perspective
- **Operating Principles** — `ai_traits/perspective/instr_operating_principles.latest.condensed.yml`
- **User Profile For Cli Agents** — `ai_traits/perspective/user_profile_for_cli_agents.latest.condensed.yml`
- **User Settings Personal Preferences Field** — `ai_traits/perspective/user_settings_personal_preferences_field.latest.md`

### Procedures
- **Action Logging** — `ai_traits/procedures/instr_action_logging.latest.condensed.yml`
- **Audit System** — `ai_traits/procedures/instr_audit_system.md`
- **ChatGPT Response Protocol** — `ai_traits/procedures/protocol_response_latest.yml`
- **Desktop Claude Context Preservation Rules** — `ai_traits/procedures/instr_claude_context_conservations.latest.condensed.yml`
- **Development** — `ai_traits/procedures/instr_development.latest.condensed.yml`
- **Download Chat Registry Data Claude** — `ai_traits/procedures/download_chat_registry_data_claude.md`
- **Feedback** — `ai_traits/procedures/instr_feedback.latest.condensed.yml`
- **File Conventions** — `ai_traits/procedures/instr_file_conventions.latest.condensed.yml`
- **Operational Handoff** — `ai_traits/procedures/operational_handoff.md`
- **Response Formatting** — `ai_traits/procedures/response_formatting.latest.md`
- **Todo** — `ai_traits/procedures/instr_todo.latest.condensed.yml`
- **Workstate Tracking** — `ai_traits/procedures/instr_workstate_tracking.latest.condensed.yml`
- **Writing** — `ai_traits/procedures/instr_writing.latest.condensed.yml`

### Processes
- **Agent Operations** — `ai_traits/processes/instr_agent_operations.latest.condensed.yml`
- **Ai Chat Orchestration** — `ai_traits/processes/30_protocols/protocol_ai_chat_orchestration.latest.condensed.yml`
- **Ai Orchestration** — `ai_traits/processes/60_playbooks/playbook.ai_orchestration.md`
- **At Self Wake** — `ai_traits/processes/30_protocols/protocol_at_self_wake.latest.condensed.yml`
- **Bulk Import 202512** — `ai_traits/processes/60_playbooks/chat_pipeline/BULK_IMPORT_202512.md`
- **Bulk Import 202512** — `ai_traits/knowledge/10_architecture/systems/chat_pipeline/BULK_IMPORT_202512.md`
- **Chat Pipeline** — `ai_traits/processes/30_protocols/chat_pipeline.latest.condensed.yml`
- **Chatgpt Browser Automation** — `ai_traits/processes/60_playbooks/playbook.chatgpt_browser_automation.latest.condensed.yml`
- **Claude Use Of Ai Agents** — `ai_traits/processes/instr_claude_use_of_ai_agents.latest.condensed.yml`
- **Cli Agents** — `ai_traits/processes/cli_agents.md`
- **Cli Browser Automation Guide** — `ai_traits/processes/60_playbooks/playbook.cli_browser_automation_guide.latest.md`
- **Cli Delegation** — `ai_traits/processes/instr_cli_delegation.condensed.yml`
- **Cli Launch Patterns** — `ai_traits/processes/60_playbooks/playbook.cli_launch_patterns.latest.md`
- **Cli Mcp Configuration** — `ai_traits/processes/60_playbooks/playbook.cli_mcp_configuration.latest.md`
- **Cli Session Persistence** — `ai_traits/processes/30_protocols/cli_session_persistence.latest.condensed.yml`
- **Codex Reminder All Ais** — `ai_traits/processes/CODEX_REMINDER_ALL_AIS.latest.md`
- **Condensed Resolution** — `ai_traits/processes/30_protocols/protocol_condensed_resolution.latest.md`
- **Directory Watcher Guide** — `ai_traits/processes/60_playbooks/playbook.directory_watcher_guide.latest.md`
- **Documentation Maintenance** — `ai_traits/processes/60_playbooks/playbook.documentation_maintenance.latest.condensed.yml`
- **Federated Memory** — `ai_traits/processes/instr_federated_memory.latest.condensed.yml`
- **Federated Memory** — `ai_traits/processes/30_protocols/protocol_federated_memory.latest.condensed.yml`
- **Gemini Canvas Automation** — `ai_traits/processes/60_playbooks/playbook.gemini_canvas_automation.latest.condensed.yml`
- **Gemini Librarian Operations** — `ai_traits/processes/60_playbooks/playbook.gemini_librarian_operations.latest.condensed.yml`
- **Gemini Vba Workflow** — `ai_traits/processes/60_playbooks/playbook.gemini_vba_workflow.latest.md`
- **Install Cli Codex Coordination** — `ai_traits/processes/60_playbooks/playbook.install_cli_codex_coordination.latest.md`
- **Librarian Task** — `ai_traits/processes/60_playbooks/chat_pipeline/LIBRARIAN_TASK.md`
- **Librarian Task** — `ai_traits/knowledge/10_architecture/systems/chat_pipeline/LIBRARIAN_TASK.md`
- **Maintenance Playbook** — `ai_traits/processes/60_playbooks/MAINTENANCE_PLAYBOOK.latest.md`
- **Multi Agent Recursive Tree Prompt Readme** — `ai_traits/processes/multi_agent_recursive_tree_prompt_readme.md`
- **Pipeline** — `ai_traits/processes/30_protocols/chat_pipeline/PIPELINE.md`
- **Pipeline** — `ai_traits/processes/60_playbooks/chat_pipeline/PIPELINE.md`
- **Pipeline** — `ai_traits/knowledge/10_architecture/systems/chat_pipeline/PIPELINE.md`
- **Reference Pointers** — `ai_traits/processes/30_protocols/protocol_reference_pointers.latest.condensed.yml`
- **Research Orchestration** — `ai_traits/processes/60_playbooks/playbook.research_orchestration.latest.condensed.yml`
- **Researcher Dispatch** — `ai_traits/processes/instr_researcher_dispatch.latest.condensed.yml`
- **Scripts** — `ai_traits/processes/60_playbooks/chat_pipeline/SCRIPTS.md`
- **Scripts** — `ai_traits/knowledge/10_architecture/systems/chat_pipeline/SCRIPTS.md`
- **Task Coordination Update Plan** — `ai_traits/processes/60_playbooks/task_coordination_update_plan.latest.md`
- **Task Template Condensation With Codex Review** — `ai_traits/processes/60_playbooks/task_template_condensation_with_codex_review.md`
- **Taskcoordination** — `ai_traits/processes/30_protocols/protocol_taskCoordination.latest.condensed.yml`
- **Tasking** — `ai_traits/processes/tasking.md`
- **Workflow Chat Continuation** — `ai_traits/processes/workflow_chat_continuation.md`
- **Workflow Export Recent Chats** — `ai_traits/processes/workflow_export_recent_chats.md`

### Reminders
- **Check for Learnings** — `ai_traits/reminders/reminder_check_for_learnings.md`
- **Current Date/Time** — `ai_traits/reminders/reminder_current_datetime.md`
- **Response Format** — `ai_traits/reminders/reminder_response_format.md`
- **Use Memory System** — `ai_traits/reminders/reminder_use_memory_system.md`

### Templates
- **Acceptance Template** — `ai_traits/templates/acceptance_template.latest.md`
- **Cli Task Session Aware** — `ai_traits/templates/cli_task_session_aware.latest.md`
- **Design Template** — `ai_traits/templates/design_template.latest.md`
- **Doc Audit Remediate Template** — `ai_traits/templates/doc_audit_remediate_template.latest.md`
- **Doc Audit Scan Template** — `ai_traits/templates/doc_audit_scan_template.latest.md`
- **Execution Log Template** — `ai_traits/templates/execution_log_template.latest.md`
- **Extraction Batch Template** — `ai_traits/templates/extraction_batch_template.latest.md`
- **Implementation Template** — `ai_traits/templates/implementation_template.latest.md`
- **Integration Template** — `ai_traits/templates/integration_template.latest.md`
- **Peer Review Template** — `ai_traits/templates/peer_review_template.latest.md`
- **Planning Mid Dev Template** — `ai_traits/templates/planning_mid_dev_template.latest.md`
- **Planning Template** — `ai_traits/templates/planning_template.latest.md`
- **Report Final Template** — `ai_traits/templates/report_final_template.latest.md`
- **Research Orchestrator Template** — `ai_traits/templates/research_orchestrator_template.latest.md`
- **Review Condensation Template** — `ai_traits/templates/review_condensation_template.latest.md`
- **Task Condense Batch Template** — `ai_traits/templates/task_condense_batch_template.latest.md`
- **Task Coordination Template** — `ai_traits/templates/task_coordination_template.latest.yml`
- **Task File Header Template** — `ai_traits/templates/task_file_header_template.latest.md`
- **Task Review Condensed Template** — `ai_traits/templates/task_review_condensed_template.latest.md`
- **Testing Template** — `ai_traits/templates/testing_template.latest.md`
