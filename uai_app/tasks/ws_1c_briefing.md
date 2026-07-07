# Workstream 1C Briefing: Organization Entities

**Project:** UAI (Unified AI Interface) — architectural successor to UCI
**DevTree:** uai-resurrection
**AI_ROOT:** $HOME/Documents/AI/devTrees/AI_ROOT_uai-resurrection
**Project Dir:** ai_general/projects/unified_ai_interface

## Your Mission

Build the organizational layer: folders, tags, and entity relationships.
These features let users organize sessions and briefs into structures.
You build ON TOP of the 1A foundation (command bus, stores, component registry).

## Read Before Starting (in order)

1. **UCI data architecture:** `architecture/current_references/uci_data_architecture.md` — THE reference for folders, tags, relationships. Port this model.
2. **Architecture spec:** `architecture/uai_architecture_v1.1.md` — Sections 2 (Entity Model), 3 (Data Architecture)
3. **1A code:** `src/main/`, `src/renderer/stores/`, `src/shared/` — the foundation you build on
4. **Contracts:** `architecture/contracts/entities.ts` — EntityId, CardId, Folder, Tag, EntityRelationship types
5. **Delegation plan:** `tasks/phase_1_delegation.md` — Section "Workstream 1C" for scope and acceptance

## Key Rules

1. **All mutations through command bus** — register folder.*, tag.*, relationship.* commands
2. **FolderStore already stubbed in 1A** — flesh it out with full CRUD
3. **session_store.py is the SQLite API** — tags and relationships go through it, not raw SQL
4. **folders.json is app-only** — only the main process writes it, atomic read-modify-write
5. **Namespaced CardIds** — `session:<tracking_id>`, `brief:<name>`. Use EntityId from contracts.
6. **Views ≠ Folders** — platform/status/archive are computed filters, not stored folders

## What You're Building

### 1C.1 — Folder System
- Main process: folder CRUD command handlers (create, rename, delete, move card, reorder)
- folders.json read/write with atomic updates and revision tracking
- FolderStore in renderer (flesh out 1A stub)
- Folder tree rendering in navigator (1B will integrate your folder components)
- Breadcrumb navigation support
- Validation: no cycles, no orphans, cards in exactly one folder

### 1C.2 — Tag System
- Main process: tag command handlers (create, add, remove, list)
- SQLite card_tags table operations via session_store.py
- Tag management (create with name + color)
- Filter by tags support (expose to navigator)

### 1C.3 — Entity Relationships
- Main process: relationship command handlers (link, unlink, list)
- SQLite entity_relationships table via session_store.py
- Relationship display data for context panel
- Link types per contracts: forked_from, briefed_to, launched_from, loaded, member_of, continues, relates_to

## Important: Parallel Work

Workstream 1B (Core UI) is running in parallel. They own:
- Navigator component (they'll integrate your folder tree)
- Context panel (they'll display your relationships)
- App.tsx layout

You own:
- Command handlers for folder/tag/relationship commands
- Store implementations (FolderStore, tag/relationship query helpers)
- Folder tree sub-component that 1B can import
- Data validation logic

Coordinate via files: put your components in `src/renderer/components/folders/` and
`src/renderer/components/tags/` so they don't collide with 1B's component files.

## Output

Main process handlers in `src/main/command-handlers.ts` (ADD to existing, don't replace).
Store code in `src/renderer/stores/folder-store.ts` (flesh out the stub).
New files for tag store, relationship queries, folder tree component.

## Escalation

Architecture questions → prompt Continuity II at session 20260422_204104_640a7e0c_cla
Scope/UX questions → escalate to PianoMan

When done, send a prompt to Continuity II confirming completion.
