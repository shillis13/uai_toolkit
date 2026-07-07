# Directory Structure Reference v3.0

**Architecture:** Multi-repo, AI-centric workspace with shared resources  
**Last Updated:** 2026-01-01  
**Status:** Active - Updated to reflect current pipeline structure

---

## External Resources

**Public Repository:** https://github.com/shillis13/ai_docs
- Mount: `ai_general/docs/` IS this submodule (not a copy)
- Access: `https://raw.githubusercontent.com/shillis13/ai_docs/main/<path>`
- Purpose: Cross-platform doc access for iOS, Web, other AI platforms
- Sync: Push from docs/ to update; submodule commit in ai_root tracks version

---

## Physical Layout

```
~/AI/ai_root/
├── ai_chat_artifacts/          # Mirrors 40_histories structure
├── ai_chatgpt/                 # ChatGPT-specific repo
├── ai_claude/                  # Claude-specific repo
├── ai_comms/                   # Communication and task coordination
├── ai_general/                 # Shared resources across AIs
└── ai_memories/                # Central memory processing pipeline
```

---

## Top-Level Directory Purposes

### ai_chat_artifacts/
**Purpose:** Storage for artifacts generated during chats (images, documents, data files)  
**Structure:** Mirrors `ai_memories/30_chat_histories/` for easy correlation  
**Example:**
```
ai_chat_artifacts/
├── claude/2025/10/30/
│   ├── diagram_architecture.png
│   └── analysis_data.csv
└── orchestrated/2025/10/29/
    └── collaboration_output.pdf
```

### ai_chatgpt/
**Purpose:** ChatGPT-specific configuration, instructions, and memories  
**Contains:**
```
ai_chatgpt/
├── ai_specific_memories/       # Chatty's self-knowledge
│   ├── capabilities.md         # What Chatty can/can't do
│   ├── work_log.md            # Projects worked on
│   ├── reflections.md         # Significant moments
│   ├── interactions.md        # Notable exchanges
│   └── ideas.md               # Future reference thoughts
│
├── ai_scripts/                # Ready-built scripts for Chatty
│   └── *.js
│
├── connectors/                # Custom connector configs
│
├── custom_gpts/               # Custom GPT configurations
│
├── instructions/              # Chatty-specific instructions
│   ├── to_ai_autogen/        # Auto-generated combined instructions
│   ├── instr_chatgpt_specific.md
│   ├── packager_config_instructions_v01.yml
│   └── [symlinks to ai_general/instructions/]
│
└── specs/                     # Chatty-specific specs
    ├── to_ai_autogen/
    ├── packager_config_specs_v01.yml
    └── [symlinks to ai_general/specs/]
```

### ai_claude/
**Purpose:** Claude-specific configuration, instructions, and memories  
**Contains:**
```
ai_claude/
├── ai_specific_memories/      # Claude's self-knowledge
│   ├── capabilities.md
│   ├── work_log.md
│   ├── reflections.md
│   ├── interactions.md
│   └── ideas.md
│
├── ai_scripts/               # Ready-built scripts for Claude
│   └── *.js
│
├── connectors/               # MCP connector configs
│
├── instructions/             # Claude-specific instructions
│   ├── to_ai_autogen/
│   ├── instr_claude_specific.md
│   ├── packager_config_instructions_v01.yml
│   └── [symlinks to ai_general/instructions/]
│
├── skills/                   # Claude Desktop skills
│
└── specs/                    # Claude-specific specs
    ├── to_ai_autogen/
    ├── packager_config_specs_v01.yml
    └── [symlinks to ai_general/specs/]
```

### ai_general/
**Purpose:** Shared resources, documentation, and tools used across all AIs  
**Contains:**
```
ai_general/
├── apps/                     # Shared apps and MCP servers
│   └── mcps/
│       └── cli-agent/        # CLI agent launcher MCP server
│
├── data/                     # Schemas and shared data structures
│   ├── schema_chat_history_v01.yaml
│   └── schema_chat_index_v01.yaml
│
├── docs/                     # Architecture and concept documentation
│   └── concept_*.md
│
├── instructions/             # Universal instructions (versioned)
│   ├── expectation_first_response_protocol_v1.0.md
│   ├── instr_bash_guide_v03.md
│   ├── instr_coding_guidelines_v01.md
│   ├── instr_development_guidelines_v04.md
│   ├── instr_footer_v03.md
│   ├── instr_general_guidelines_v03.md
│   ├── instr_python_guide_v05.md
│   ├── instr_vba_guide_v02.md
│   └── persistence_preferences.md
│
├── projects/                 # Project-specific documentation
│   ├── chat_history_processing/
│   ├── chat_orchestration/
│   ├── desktop_cli_workflow/
│   └── persona_modeling/
│
├── prompts/                  # Reusable prompt library
│   ├── roles/                # Role definitions for CLI agents
│   │   ├── manifest.yml      # Role registry
│   │   ├── custodian/
│   │   ├── dev_lead/
│   │   ├── librarian/
│   │   ├── ops/
│   │   ├── peer_review/
│   │   └── tester/
│   │       ├── role.yml      # Metadata, context_files, duties, ownership
│   │       └── prompt.md     # Role-specific bootstrap prompt
│   ├── platforms/            # Platform-specific prompts
│   │   ├── claude.md
│   │   ├── codex.md
│   │   └── gemini.md
│   ├── global.md             # Universal bootstrap instructions
│   ├── tasking.md            # Task execution protocol
│   └── archive/              # Deprecated prompts (legacy storage)
│       └── agent.{role}.md   # Old agent role prompts (deprecated, moved here)
│
├── research_and_reports/     # Research outputs
│   ├── ai_ethics/
│   ├── ai_platform_review_Oct2025/
│   ├── framework_to_compare_national_scale_economic_models/
│   └── system_design/
│
├── scripts/                  # Shared automation scripts
│   └── [symlinks to actual script locations]
│
└── specs/                    # Technical specifications (versioned)
    ├── spec_footer_v02.md
    └── spec_message_insert_v01.md
```

Legacy `agent.{role}.md` prompt files are deprecated and relocated to `ai_general/prompts/archive/`.

### ai_memories/
**Purpose:** Central memory processing pipeline - converts chat exports to searchable, indexed memories  
**Contains:**
```
ai_memories/
├── 10_exported/              # Raw chat exports from AI platforms
│   ├── chatgpt/
│   ├── claude/
│   ├── claude_cli/
│   ├── codex_cli/
│   ├── gemini/
│   └── grok/
│
├── 20_preprocessed/          # Preprocessing stage
│   └── README.md
│
├── 30_converted/             # YAML conversion output
│   └── README.md
│
├── 40_histories/             # Chunked YAML archives (terminal storage)
│   ├── _chat_index.csv       # Master index of all chats
│   ├── _condensation_targets.txt
│   ├── _validation/
│   ├── chatgpt/YYYY/MM/      # ChatGPT histories by date
│   └── claude/YYYY/MM/       # Claude histories by date
│       └── claude.YYYYMMDD.{short_id}.{title_slug}/
│           ├── chunk_001.yml
│           └── chat.condensed.yml  # Created on-demand, not pre-stored
│
├── 50_threads/               # Thread-based organization (reserved)
│
├── 60_decisions/             # Architecture decisions (immutable)
│   ├── decision_log.yml
│   └── digests/
│
├── 60_knowledge/             # Reusable facts and information
│   ├── index_knowledge.yml
│   ├── about_user/
│   ├── coordination_system_v4_digest.md
│   └── know_*.md             # Knowledge articles
│
├── 70_milestones/            # Capability milestones
│   ├── capability_milestones.md
│   └── capability_milestones.yml
│
├── _incoming/                # Intake staging area
│   ├── chats/                # Raw exports awaiting processing
│   │   ├── chatgpt/
│   │   ├── claude/
│   │   ├── grok/
│   │   └── orchestrated_chat_tool_logs/
│   ├── digests/
│   └── pipeline_history_chats/
│
├── _templates/               # Template files
│   ├── decision_template.md
│   └── memory_digest_template.yml
│
├── mem0_extraction/          # Mem0 integration artifacts
│
├── quarantine/               # Files pending review/cleanup
│
└── reports/                  # Processing reports
    └── librarian_*.md
```

### ai_comms/
**Purpose:** AI-to-AI communication and task coordination system  
**Contains:**
```
ai_comms/
├── announcements/            # Broadcast messages to all AIs
│
├── chatgpt/                  # ChatGPT mailbox and tasks
│   ├── drafts/
│   ├── instant_messaging/
│   ├── note_passing/
│   ├── notifications/
│   ├── prompting/
│   ├── saved/
│   └── tasks/
│
├── claude/                   # Claude Desktop mailbox and tasks
│   ├── drafts/
│   ├── instant_messaging/
│   ├── note_passing/
│   ├── notifications/
│   ├── prompting/
│   ├── saved/
│   ├── tasks/
│   └── WAKE_UP_CHECKLIST.md
│
├── claude_cli/               # CLI coordination (symlinked from ~/.claude/coordination)
│   ├── broadcasts/
│   ├── init/                 # Initialization scripts
│   ├── instant_messaging/
│   ├── logs/
│   ├── note_passing/
│   ├── notifications/
│   ├── prompting/
│   ├── scheduling/
│   ├── synthesis/
│   └── tasks/
│
├── codex_cli/                # Codex CLI coordination
│   ├── cancelled/
│   ├── docs/
│   ├── instant_messaging/
│   ├── logs/
│   ├── note_passing/
│   ├── notifications/
│   ├── prompting/
│   └── tasks/
│
├── counters/                 # Atomic ID counters
│   └── *.NextId
│
├── desktop_claude/           # Desktop-specific prompts
│   └── prompts/
│
├── gemini/                   # Gemini mailbox and tasks
│   └── [same structure as chatgpt/]
│
├── gemini_cli/               # Gemini CLI coordination
│   ├── logs/
│   ├── tasks/
│   └── waves/
│
├── grok/                     # Grok mailbox and tasks
│   └── [same structure as chatgpt/]
│
├── orchestration/            # Wave orchestration
│   └── wave_{timestamp}/
│
├── staged/                   # Staged tasks awaiting assignment
│
└── _backlog/                 # Backlogged work items
```

---

## Memory Processing Pipeline Flow

```
1. Export from AI platform
   ↓
   ai_memories/10_exported/{ai}/
   (or ai_memories/_incoming/chats/{ai}/)

2. Preprocess (normalize format)
   ↓
   ai_memories/20_preprocessed/

3. Convert to YAML format
   ↓
   ai_memories/30_converted/

4. Chunk by date/session/size
   ↓
   ai_memories/40_histories/{ai}/YYYY/MM/
   (terminal storage - never moves)

5. Create condensed summaries ON DEMAND
   ↓
   chat.condensed.yml alongside chunks
   (NOT pre-generated artifacts)

6. Extract knowledge/decisions
   ↓
   ai_memories/60_decisions/
   ai_memories/60_knowledge/
```

---

## Symlink Strategy

**AI-specific repos symlink to ai_general for shared resources:**

```bash
# Example: Claude's instructions use .latest symlinks
ai_claude/instructions/
├── instr_claude_specific.yml           # Claude-only
└── instr_operating_principles.latest.yml → ../../ai_general/docs/70_instructions/instr_operating_principles.latest.yml
```

**CLI coordination symlink:**
```bash
~/.claude/coordination → ~/AI/ai_root/ai_comms/claude_cli/
```

**Document versioning with .latest symlinks:**
```bash
ai_general/docs/70_instructions/
├── versions/
│   ├── instr_operating_principles_v1.0.yml
│   └── instr_operating_principles_v1.1.yml
└── instr_operating_principles.latest.yml → versions/instr_operating_principles_v1.1.yml
```

**Maintenance:**
- Canonical files in versions/ subdirectories
- .latest symlinks point to current version
- Breaking changes = new version file, update symlink

---

## File Naming Conventions

### Chat History Files
**Location:** `ai_memories/40_histories/{ai}/YYYY/MM/`  
**Directory Format:** `{ai}.{YYYYMMDD}.{short_id}.{title_slug}/`  
**Example:** `claude.20251230.abc123.bootstrap_testing/`
**Contents:**
- `chunk_001.yml`, `chunk_002.yml`, etc.
- `chat.condensed.yml` (created on-demand when needed)

### Knowledge Files
**Location:** `ai_memories/60_knowledge/`  
**Format:** `know_{topic}.md` or topic subdirectories  
**Examples:**
- `know_codex_mcp.md`
- `about_user/preferences.md`

### Decision Files
**Location:** `ai_memories/60_decisions/`  
**Format:** `decision_{date}_{topic}.md`  
**Example:** `decision_20251030_caching_strategy.md`

### Documentation Files
**Location:** `ai_general/docs/{tier}/`  
**Format:** `{name}.latest.{ext}` symlinked to `versions/{name}_v{X.Y}.{ext}`
**Condensed:** `{name}.latest.condensed.yml` for reduced token usage

---

## Key Principles

### Repo Isolation
Each AI repo is self-contained:
- Own instructions (with symlinks to general)
- Own specs (with symlinks to general)
- Own AI-specific memories
- Own scripts and connectors

### Shared Resources
Common resources live in `ai_general/`:
- Version-controlled instructions and specs
- Schemas and data structures
- Project documentation
- Prompt libraries
- Research outputs

### Central Memory Pipeline
`ai_memories/` processes conversations from ANY AI:
- Numbered pipeline stages (10→20→30→40)
- Condensed summaries created on-demand, not pre-stored
- Knowledge and decisions extracted to 60_ directories
- Cross-AI conversation support via orchestration

### Communication System
`ai_comms/` enables coordination:
- Per-AI mailboxes for async messages
- Task execution via tasks/ subdirectories
- CLI coordination with symlink integration
- Wave orchestration for parallel work
- Atomic counters for unique IDs

---

## Related Documentation

- **Architecture Overview:** `ai_general/docs/10_architecture/architecture_overview.latest.md`
- **Layer Model:** `ai_general/docs/10_architecture/architectural_layer_model.latest.md`
- **CLI Orchestration:** `ai_general/docs/10_architecture/cli_orchestration.latest.md`
- **Task Coordination:** `ai_general/docs/30_protocols/protocol_taskCoordination.latest.yml`
- **Knowledge Manifest:** `ai_general/docs/_knowledge_manifest.latest.yml`

---

**Document Version:** 3.0  
**Created:** 2025-10-30  
**Updated:** 2026-01-01  
**Architecture:** Multi-repo, AI-centric with shared resources  
**Status:** Active
