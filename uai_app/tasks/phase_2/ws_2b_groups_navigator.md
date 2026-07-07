---
task_id: ws_2b
task_type: implementation
created: 2026-04-28T00:00:00Z
status: staged
depends_on: []
protocol: ai_general/ai_traits/processes/30_protocols/protocol_taskCoordination.latest.condensed.yml
---

# 2B: Groups in Navigator

**Project:** UAI (Unified AI Interface)
**DevTree:** AI_ROOT_uai-resurrection
**Project Dir:** ai_general/projects/unified_ai_interface
**Source Dir:** src/ (under project dir)

## Objective

Add a "Groups" tab to the Navigator panel. Groups are non-exclusive containers — a session can belong to multiple groups simultaneously, unlike folders where a session belongs to exactly one.

## What Already Exists

- `GroupCard` type defined in `architecture/contracts/cards.ts` with `container: ContainerCapability` (always present)
- `ContainerEntry` with `container_type: 'group'` and `placement_rule: 'non-exclusive'` in `src/shared/cards.ts`
- `container.create` with `type:'group'` already works in `src/main/command-handlers.ts`
- `container.addCard`, `container.removeCard`, `container.rename`, `container.delete` all work for groups
- `CardListView` and `ContainerTreeView` in `src/renderer/components/cards/` render any card type
- `GroupCard` type guard `isGroupCard()` exists
- `FolderCardVisual.tsx` already handles both folder and group cards (shows "group" badge)
- `useCardStore().groups` returns all group cards
- `containers.json` persists groups alongside folders via container manager

## What to Build

1. **Groups tab in Navigator** — Add "Groups" tab alongside Sessions/Briefs/Teams/Projects in the Navigator tab bar
2. **Group list rendering** — Use `CardListView` with `useCardStore().groups` filtered by entity_type
3. **Create Group UI** — "New Group" button or context menu action that dispatches `container.create` with `type:'group'`
4. **Group context menu** — Right-click on group card: Rename, Delete, Add Session(s), Open in Tab
5. **Add to Group flow** — Right-click session in Sessions tab: "Add to Group" submenu listing available groups, dispatches `container.addCard`
6. **Remove from Group** — In group detail or context menu, dispatch `container.removeCard`
7. **Group detail view** — When a group is selected, show its member sessions in a CardListView (or this can be deferred to 2D when the group opens as a tab)

## Key Files to Modify

- `src/renderer/components/Navigator.tsx` — add Groups tab, group-specific context menus
- `src/renderer/components/cards/FolderCardVisual.tsx` — may need group-specific adjustments

## Key Files to Read First

- `src/renderer/components/Navigator.tsx` — understand current tab structure
- `src/renderer/stores/card-store.ts` — understand `useCardStore()` API
- `src/renderer/components/cards/` — understand card rendering system
- `src/main/command-handlers.ts` — see existing `container.*` commands
- `docs/plans/phase_2_plan.md` — design decisions, especially "Folders vs Groups"

## Validation

- `cd src && npx tsc --noEmit` — must pass
- `cd src && npx vitest run` — all tests must pass
- Groups persist in `containers.json` across app restart
- Creating/renaming/deleting groups works through the command bus
- Adding/removing sessions to/from groups works
- A session can belong to multiple groups simultaneously

## Done When

User can create groups, add/remove sessions, see groups in Navigator with member counts, rename and delete groups. Groups persist across app restart.
