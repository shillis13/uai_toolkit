---
id: ontology_glossary
name: Ontology Glossary
status: active
version: 2.0.0
created: 2026-04-17
updated: 2026-07-09
---

# Ontology Glossary

The canonical reference for the terms, concepts, and structures in this AI workspace.
Read this first — other documents assume familiarity with these terms.

> **v2.0 (2026-07-09):** rewritten for the todo_0319 model — "trait" → **context file**,
> the two-bucket ontology, `context.db`, and the current MCP set. The former auto-generated
> "File Index" section was removed; use `context_mgr.py list` (or `ref_glossary_knowledge_index`)
> for the live file catalog.

---

## Core Vocabulary

- **Context file** — a single, atomic, reusable content element an AI draws on (the building
  block; replaces the old term *trait*). Lives under `ai_context_files/`. It is one of two
  kinds — **instruction** or **knowledge** — and is referenced by compositions, never duplicated.
  A context file's cross-links to other context files are **see-also only; never cascade-loaded.**

- **Context composition** — a bundle that *assembles* context files: a **role**, **skill**,
  **profile**, or **global**. Compositions **cascade** (a profile pulls in its roles, a role its
  context files + sub-roles/skills). Lives under `ai_profiles/`.

- **Instruction** — a context file that tells an AI *how to think, behave, or act* (directive).
  One of the two top-level kinds. Sub-kinds: perspectives, how_tos, rules, templates, reminders.

- **Knowledge** — a context file that tells an AI *what is* (facts, reference, structure —
  descriptive). The other top-level kind. Sub-kinds: architecture, specs, schemas, reference.

- **Role** — an identity fragment: description, duties, and references to context files (+ skills
  / sub-roles). Examples: dev, tester, librarian. Composed into profiles. `ai_profiles/roles/`.

- **Profile** — a pre-composed set of roles = a full agent identity. `ai_profiles/`.

- **Skill** — a composition that defines *how to approach a class of problem* using available
  tools (triggers, decision flow). `ai_profiles/skills/`.

- **Global** — a composition loaded for **every** session by launcher convention (core
  perspective + platform loads). `ai_profiles/globals/` (base + per-platform).

## The Two-Bucket Ontology

Context files are organized by kind, and the sub-directory sets the file's semantic prefix
(the first path segment of a context id **is** the category — see `ai_context_files/DESIGN.md`):

**instructions/** — *how to think/act*
- **perspectives/** (`perspective_`) — mindsets, principles, communication style; shapes judgment.
- **how_tos/** (`instr_`) — procedures + protocols (protocols nested).
- **rules/** (`rules_`) — normative constraints, conventions, standards.
- **templates/** — scaffolds that generate work-product instances.
- **reminders/** (`reminder_`) — short standing nudges surfaced on a schedule.

**knowledge/** — *what is*
- **architecture/** (`arch_`) — how the system is built.
- **specs/** (`spec_`) — specifications.
- **schemas/** (`schema_`) — data schemas.
- **reference/** (`ref_`) — registries, glossaries, manifests.

## System Terms

- **Todo** — a tracked work item (`ai_general/work/todos/`); backlog + project memory. Higher-level
  than a task. Managed via the workflow MCP (`workflow_todo_*`) / `todos-mgr`.
- **Task** — a scoped unit of work with an implementation plan (`work/tasks/`), assignable to
  sessions/projects. Managed via the workflow MCP.
- **Note** — a threaded discussion artifact (`work/notes/`); workflow MCP (`workflow_note_*`).
- **Brief** — a condensed session-handoff document (key decisions/context/state for a successor).
  `data/session_briefs/`.
- **DevTree** — a sparse git worktree of `ai_general` for isolated parallel development; workflow
  MCP (`workflow_devtree_*`).
- **Condensation** — semantic compression of chat history (70–90% token reduction, preserving
  decisions/artifacts). Knowledge MCP (`knowledge_condense_history`) + condensation-pipeline skill.
- **Bootstrap** — the context loaded before an AI's first response (globals → platform → role).
- **Offload / Bounce** — lossless context paging (archive large payloads to a sidecar) and a
  self-restart to realize the reduction; sessions MCP (`context_offload`, `context_bounce`).

## Infrastructure Terms

- **MCP server** — a tool provider using the Model Context Protocol. **Local custom servers**
  (code under `ai_general/apps/mcps/`): **comms** (messaging), **knowledge** (knowledge + guidance
  delivery + memory), **sessions** (session mgmt + context ops), **workflow** (todos/tasks/notes/
  playbooks) — each ships a `tools.yml` — plus **chat-playwright** (browser/web-chat automation,
  registered under the aliases `browser` and `chat`). Registered in `ai_general/data/MCP.json`.
  (`workstate` = third-party `mcp-tasks`, not one of ours.)
- **Knowledge MCP** — delivers context files, roles, and knowledge on demand (`knowledge_get_context`,
  `knowledge_how_to`, `knowledge_guidance_search`) plus archive search + the working-memory store.
  Reads the **`context.db`** index. Folds in the former guidance / knowledge-search / jsonl / memory
  servers.
- **context.db** — the authoritative, **rebuildable** index of the context-files corpus
  (`ai_general/data/context.db`), built by `context_mgr.py` from the on-disk sources (the source of
  truth). Reindexed by a post-commit hook when `ai_context_files/`/`ai_profiles/` change. It builds
  edges for compositions only, which is why file→file see-also links never cascade.
- **CLI session** — a running AI instance (Claude Code / Codex CLI), launched via
  `ai_launch.py`, running in a tmux session.
- **Session identity** — tracking id + CLI UUID. Tracking id: `{YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}`.
- **Git-Guardian** — the sole sanctioned git-write path; all commits/pushes route through it.
- **UAI (Unified AI Interface)** — the Electron app for managing AI sessions (tabs, prompt
  delivery, transcripts, monitoring). The **Prompt Box** is its prompt-input component.

## Architecture Terms

- **`ai_context_files/`** — the corpus: the source-of-truth context files (instructions + knowledge),
  indexed by `context.db`. (Replaces the former `ai_traits/`.)
- **`ai_profiles/`** — the composition layer: globals, platforms, roles, skills, and profiles that
  reference context files.
- **AI_ROOT** — env var pointing at the workspace root (`~/AI/ai_root`); scripts resolve paths
  relative to it. DevTrees set their own AI_ROOT.
- **Single canonical file** — each context file is one flat file; a semantic prefix encodes its kind
  and version lives in frontmatter. Retired items move to `_archive/`, parked ones to `.drafts/`
  (both `_`/`.`-prefixed, so `context_mgr` skips them).
- **Reference integrity** — context-file references are edited only via `context_mgr.py`
  `link`/`unlink`/`move` (which keep the index in sync and repoint inbound refs); never hand-edited.
- **Flat composability** — no inheritance: profiles list roles, roles list context files. Explicit
  and debuggable.

## Formalization Ladder

The progression from informal to formal: **Rule/Procedure** (prose) → **Script** (executable) →
**MCP tool** (atomic API) → **Skill** (a workflow using tools). Each level formalizes the previous.
