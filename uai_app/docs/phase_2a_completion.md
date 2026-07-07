# Phase 2A Completion: Card/Container Base Abstraction Refactor

**Date:** 2026-04-25
**Executor:** Session `20260425_234902_acd5d3bd_cla` (Continuity IIb successor)
**Plan by:** Session `20260424_220902_67cd5cc7_cla` (2A worker)
**Status:** Complete — 50/50 tests pass, TypeScript clean

---

## What Changed

### New Abstractions

**BaseCard** — Every entity in the system is a Card. Universal fields: `entity_id`, `entity_type`, `display_name`, `created_at`, `last_activity`, `tags`, optional `container`.

**ContainerCapability** — Some cards hold other cards. Two placement rules:
- `exclusive` (folders): a card can be in exactly one container
- `non-exclusive` (groups): a card can be in many containers

**AnyCard** — Discriminated union: `SessionCard | BriefCard | FolderCard | GroupCard`. Discriminant is `entity_type`. Leaf cards have `container?: undefined` for narrowing.

### Files Created (14)

| File | Purpose |
|------|---------|
| `architecture/contracts/cards.ts` | BaseCard, ContainerCapability, AnyCard types, type guards |
| `src/shared/cards.ts` | Runtime re-exports + ContainerStoreData, ContainerEntry, CardFilter |
| `src/main/container-manager.ts` | Generic CRUD with placement rules, migration from folders.json |
| `src/renderer/stores/card-store.ts` | Unified card store with type-filtered accessors |
| `src/renderer/components/cards/BaseCardView.tsx` | Universal card chrome (platform bar, name, status dot) |
| `src/renderer/components/cards/CardRenderer.tsx` | Discriminated union dispatch to type-specific visuals |
| `src/renderer/components/cards/CardListView.tsx` | Generic sortable, filterable, multi-selectable list |
| `src/renderer/components/cards/ContainerTreeView.tsx` | Collapsible tree with container navigation |
| `src/renderer/components/cards/SessionCardVisual.tsx` | Session-specific rendering |
| `src/renderer/components/cards/BriefCardVisual.tsx` | Brief-specific rendering |
| `src/renderer/components/cards/FolderCardVisual.tsx` | Folder/group-specific rendering |
| `src/renderer/components/cards/index.ts` | Barrel export |
| `src/tests/contract-cards.test.ts` | 7 card type system tests |
| `src/tests/contract-container-manager.test.ts` | 13 container manager tests (both placement rules) |

### Files Modified (5)

| File | Change |
|------|--------|
| `architecture/contracts/entities.ts` | Added `'group'` to EntityType, `folder:` and `group:` to CardId |
| `architecture/contracts/index.ts` | Re-exports `./cards` |
| `src/shared/types.ts` | Re-exports card types and type guards from contracts |
| `src/shared/index.ts` | Re-exports `./cards` |
| `src/main/folder-manager.ts` | Refactored to thin wrapper delegating to container-manager |
| `src/main/command-handlers.ts` | Added 7 `container.*` command handlers |
| `src/shared/component-descriptions.ts` | Registered `card_list` and `container_tree` components |
| `src/renderer/stores/index.ts` | Exports `useCardStore` |
| `src/renderer/components/index.ts` | Re-exports `./cards` |

### Source File Count

48 (Phase 1) → 55 (Phase 2A) — net +7 production files, +2 test files

---

## Adding a New Entity Type — Complete Checklist

To add a new entity type (e.g., `GroupCard`, `TeamCard`), you need:

### 1. Type System
- [ ] Define the card interface extending `BaseCard` in `architecture/contracts/cards.ts`
- [ ] Add to `AnyCard` discriminated union
- [ ] Add type guard function (e.g., `isGroupCard`)
- [ ] Add entity type string to `EntityType` in `entities.ts`
- [ ] Add entity type to `CardId` union if it appears in card lists

### 2. Container Manager (if it's a container)
- [ ] Add container type to `TYPE_PLACEMENT` map in `container-manager.ts`
- [ ] `createContainer(type, ...)` already works — no code changes needed

### 3. Data Source
- [ ] Add adapter function in `card-store.ts` to convert raw data → card type
- [ ] Add IPC channel or store query to fetch the data
- [ ] Wire into `bootstrap()` and `refresh()` in card-store

### 4. Card Rendering (Navigator list item)
- [ ] Create `{Type}CardVisual.tsx` — what meta/badges appear on the card in lists
- [ ] Add type guard + visual dispatch line in `CardRenderer.tsx`

### 5. Detail View (center pane when selected)
- [ ] Create detail pane component or extend `SessionPane` pattern
- [ ] Wire into `Workspace.tsx` tab rendering for the entity type

### 6. Context Menu
- [ ] Define context menu actions for the card (right-click in Navigator)
- [ ] Define context menu actions for the tab (right-click on tab in Workspace)
- [ ] Register actions in Navigator's context menu handler

### 7. Commands
- [ ] Register any type-specific commands on the bus (or use generic `container.*`)
- [ ] Existing `container.create`, `container.addCard`, etc. work for any container type

### 8. Component Registry
- [ ] Add `ComponentDescription` for any new architectural components
- [ ] Register in `registerInitialComponents()`

### 9. Navigator Tab
- [ ] Add tab to Navigator tab bar
- [ ] Use `CardListView` + `ContainerTreeView` with type filter
- [ ] Add filter/sort controls appropriate to the entity type

### 10. Tests
- [ ] Add contract tests for new type constraints
- [ ] Add container tests if new placement rules are needed

---

## Migration

Container manager reads `containers.json` first. If not found, falls back to `folders.json` and migrates the data structure automatically. All folder operations continue to work through the thin wrapper — no breaking changes.

---

## What's NOT Done Yet

- Navigator does not yet use `CardListView` (still uses inline `SessionCard` component)
- Groups are defined in types but no UI or data source exists
- The 2A plan included a Navigator refactor (Task 8) which was deferred to avoid touching working UI before review
