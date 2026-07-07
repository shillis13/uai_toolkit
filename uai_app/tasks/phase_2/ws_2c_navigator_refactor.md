---
task_id: ws_2c
task_type: implementation
created: 2026-04-28T00:00:00Z
status: staged
depends_on: []
protocol: ai_general/ai_traits/processes/30_protocols/protocol_taskCoordination.latest.condensed.yml
---

# 2C: Navigator Refactor to Generic Card Components

**Project:** UAI (Unified AI Interface)
**DevTree:** AI_ROOT_uai-resurrection
**Project Dir:** ai_general/projects/unified_ai_interface
**Source Dir:** src/ (under project dir)

## Objective

Replace Navigator's inline SessionCard rendering with the generic card components built in Phase 2A. The Navigator should render all entity types through the unified card system instead of having type-specific inline components.

## What Already Exists

- Inline `SessionCard` function component in Navigator.tsx (~line 175) — to be replaced
- `CardListView` in `src/renderer/components/cards/CardListView.tsx` — generic list with multi-select
- `CardRenderer` in `src/renderer/components/cards/CardRenderer.tsx` — discriminated union dispatch
- `ContainerTreeView` in `src/renderer/components/cards/ContainerTreeView.tsx` — collapsible tree
- `Breadcrumbs` in `src/renderer/components/folders/Breadcrumbs.tsx` — exists but not wired
- `FolderTree` in `src/renderer/components/folders/FolderTree.tsx` — exists but not wired
- `useCardStore()` — unified store with type-filtered accessors
- `useFolderStore()` — folder-specific store (still works, delegates to container manager)

## What to Build

1. **Sessions tab** — Replace inline `SessionCard` and `renderCard` function with `CardListView` using `useCardStore().sessions`
   - Active/Stopped section grouping: two `CardListView` instances with filtered arrays
   - Keep existing filter toolbar (status, platform, search)
   - Keep existing sort controls
   - Multi-select via CardListView's cmd/ctrl+click (replaces inline selection handling)

2. **Folder tree navigation** — Wire `ContainerTreeView` or `FolderTree` into Sessions tab
   - Show folder hierarchy with expand/collapse
   - Breadcrumbs for current folder path
   - Click folder to filter sessions to that folder's contents
   - Click session card to open in workspace

3. **Briefs tab** — Replace placeholder text with real content
   - `CardListView` with `useCardStore().briefs` (may be empty if no brief data source yet)
   - BriefCard rendering via CardRenderer (BriefCardVisual already exists)
   - If no IPC exists to load briefs, create a placeholder that shows "No briefs loaded"

4. **Context menus** — Ensure context menus still work with the new card components
   - Right-click on session card: rename, archive, copy tracking ID, add to group
   - Right-click on folder in tree: rename, delete, create subfolder

## Key Files to Modify

- `src/renderer/components/Navigator.tsx` — major refactor
- Possibly `src/renderer/components/folders/Breadcrumbs.tsx` — wire into Navigator

## Key Files to Read First

- `src/renderer/components/Navigator.tsx` — understand what exists
- `src/renderer/components/cards/` — understand the generic card system
- `src/renderer/components/folders/` — understand folder components
- `src/renderer/stores/card-store.ts` — useCardStore API
- `docs/plans/phase_2_plan.md` — design context

## Validation

- `cd src && npx tsc --noEmit` — must pass
- `cd src && npx vitest run` — all tests must pass
- Sessions tab renders through CardListView, not inline components
- Filter and sort still work
- Multi-select still works (cmd/ctrl+click)
- Folder navigation shows tree with breadcrumbs
- Briefs tab shows content (or clean empty state)

## Done When

Navigator renders all entity types through the generic card system. Folder navigation works with breadcrumbs. Briefs tab shows real data or a clean empty state. No inline SessionCard component remains.
