---
task_id: ws_2g
task_type: implementation
created: 2026-04-28T00:00:00Z
status: staged
depends_on: []
protocol: ai_general/ai_traits/processes/30_protocols/protocol_taskCoordination.latest.condensed.yml
---

# 2G: Projects Entity

**Project:** UAI (Unified AI Interface)
**DevTree:** AI_ROOT_uai-resurrection
**Project Dir:** ai_general/projects/unified_ai_interface
**Source Dir:** src/ (under project dir)

## Objective

Make devTrees/projects first-class entities in the app — browsable, associated with sessions, with detail views.

## What Already Exists

- `Project` interface in `architecture/contracts/entities.ts` — full type with id, name, goal, branch, working_dir, status, assigned_ais, tags, source_path, etc.
- `EntityType` includes `'project'` (would need to verify, may need adding)
- DevTrees live at `~/Documents/AI/devTrees/`
- Project metadata lives in `ai_general/projects/` directories
- Sessions have `project_dir` field linking them to a project

## What to Build

1. **ProjectCard type** — Extend BaseCard for projects (add to contracts/cards.ts and AnyCard union)
2. **ProjectCardVisual** — Type-specific rendering (working dir, branch, status badge, session count)
3. **DevTree indexer** — Main process module that scans devTrees directory and project metadata, returns ProjectCard[]
4. **Projects IPC** — `uai:projects:list` handler + preload API
5. **Projects tab in Navigator** — CardListView showing all projects
6. **Project detail** — When opened as a tab, show project info + associated sessions (filtered by project_dir match)
7. **Card store integration** — Add projects to useCardStore() bootstrap/refresh

## Validation

- `cd src && npx tsc --noEmit` — must pass
- `cd src && npx vitest run` — all tests must pass
- Projects tab shows discovered devTrees/projects
- Project cards show working dir, branch, status
- Associated sessions are discoverable from project detail

## Done When

User can see all projects in Navigator, view project details, see which sessions belong to which project.
