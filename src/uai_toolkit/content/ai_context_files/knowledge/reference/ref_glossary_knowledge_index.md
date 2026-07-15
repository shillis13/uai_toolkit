---
id: glossary_knowledge_index
name: Knowledge Glossary + Index
status: active
version: 2.0.0
updated: 2026-07-09
---

# Knowledge Glossary + Index

Fast term-recognition for workspace-specific concepts, so an AI knows what a term means
(and where to read more) without loading full documents.

> **v2.0 (2026-07-09):** slimmed to current terms only. For the **canonical vocabulary**
> (context file, context composition, the two-bucket ontology, roles/profiles/skills, the MCP
> set) see **`ref_ontology_glossary`**. For **live "which file explains X" lookup**, use
> `knowledge_search` / `context_mgr.py search` — a hand-maintained file index rots, so the old
> auto-generated index and its dead pointers were removed.

---

## Terms

**Scaffolding** (aliases: agent scaffolding, CLI scaffolding, agent infrastructure)
Everything built *around* CLI agents to extend them beyond a bare terminal: shared/expanded memory,
cross-agent comms, session identity & management, hooks, orchestration, launcher, and the UAI app.
The umbrella term for "the stuff we add around CLI agents."

**AI CLIs** (aliases: CLIs, CLI agents, terminal AIs)
Terminal-based command-line AI agents that do autonomous work — Claude Code, Codex CLI.
Launched via `ai_launch.py`; coordinate through the comms MCP (not file-based task dirs anymore).

**Claude Code** (aliases: Claude CLI, claude_cli)
Claude running in the terminal via the `claudeCli` launcher (`ai_launch.py`). Primary platform:
1M context, full bash, native tools, MCP servers, skills/plugins. Runs in a tmux session.

**UAI (Unified AI Interface)** (aliases: the app, unified_ai_ui)
The Electron app for managing AI sessions — tabs, prompt delivery (the **Prompt Box**), transcript
viewing, and monitoring. `ai_general/apps/unified_ai_ui/`.

**Git-Guardian** (aliases: GG)
The sole sanctioned git-write path — a dedicated session that all commits/pushes route through
(`scripts/git_guardian/git_guardian.py request`). Never `git commit`/`push` directly.

**Message Inserts** (aliases: INSERT blocks, structured inserts)
Structured comment blocks (`<<<INSERT type=X>>>…<<<END INSERT>>>`) for machine-readable markers
(MEMORY, DECISION, …) that can be emitted inline in a transcript and harvested later by the pipeline.
- Primary: `spec_message_insert` (knowledge/specs)

**Brief** (aliases: session brief, handoff)
A condensed session-handoff document (key decisions/context/state) so a successor can continue.
`data/session_briefs/`. Auto-generated on compaction.

**Working Memory** (aliases: memory slots, mslots)
Per-session slots under `ai_memories/80_working_memory/` (03=user model, 04=communication, 05=tools,
06=current context, 07=limitations, …). Read/written via the knowledge MCP memory tools.

**Claude Code Plugins** (aliases: plugins, /plugin)
Extension bundles for Claude Code (commands, agents, skills, MCP servers). Marketplaces are git repos
(`claude plugin marketplace add owner/repo`); e.g. **Superpowers** (obra/superpowers — TDD, debugging,
brainstorming, git-worktrees) and **Episodic Memory** (semantic search over past conversations).

**Skills** (aliases: SKILL.md, agent skills)
Model-invoked instruction packages (SKILL.md + optional scripts/references) loaded on demand.
In Claude Code they're invoked via the Skill tool; they complement plugins (which bundle
commands/agents/skills/MCP servers).

**Bootstrap Problem** (aliases: context bootstrap)
An AI needs to know what's *in* files to know *when* to load them. Solved by term-recognition
(this glossary + `ref_ontology_glossary`) plus on-demand delivery via the knowledge MCP
(`knowledge_get_context` / `knowledge_how_to`), which reads the `context.db` index.

---

## See Also

- **`ref_ontology_glossary`** — the canonical vocabulary and structural terms.
- **`knowledge_search` / `context_mgr.py search`** — live lookup of which file covers a topic.
- **`ref_directory_structure`** — where everything lives.
