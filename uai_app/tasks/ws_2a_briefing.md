# Workstream 2A Briefing: Card/Container Base Abstraction Refactor

**Project:** UAI (Unified AI Interface)
**DevTree:** uai-resurrection
**AI_ROOT:** $HOME/Documents/AI/devTrees/AI_ROOT_uai-resurrection
**Project Dir:** ai_general/projects/unified_ai_interface

## Your Mission

Refactor the current folder-specific and card-specific code into generic base
abstractions. This is THE foundational refactor for Phase 2 — every future entity
type (Groups, Teams, Projects) must be able to reuse these abstractions without
duplicating container/card logic.

## The Problem We're Solving

In the predecessor app (UCI), each folder type and card type was a completely
separate implementation. Session cards, Brief cards, Session folders, Brief folders —
all different code doing the same things slightly differently. Adding Groups required
reimplementing the same operations a third time, and "simple stuff doesn't work
consistently" because bugs fixed in one type don't fix the same bug in others.

We must not repeat this mistake.

## The Core Insight: Everything is a Card

Every entity in the system is a Card. Some cards are also Containers (they hold
other cards). This is a capability, not a separate type hierarchy.

```
BaseCard (universal)
  ├── Can be tagged
  ├── Can have relationships
  ├── Can appear in lists
  ├── Can be multi-selected
  ├── Has context menu
  ├── Has display_name, icon, entity_id
  │
  ├── Leaf cards (not containers):
  │   ├── SessionCard — tracking_id, platform, terminal, status, etc.
  │   └── BriefCard — description, condenser_session, file_size, etc.
  │
  └── Container cards (hold other cards):
      ├── FolderCard — exclusive placement, tree structure
      ├── GroupCard — non-exclusive membership
      ├── TeamCard — profiles, comms_plan, role assignments
      └── ProjectCard — working_dir, branch, goal
```

A Folder is a Card that can contain other Cards (including other Folders).
A Group is a Card that can contain other Cards (non-exclusively).
A Team is a Card that can contain other Cards with comms and roles.

## Read Before Starting

1. **Current code:** `src/` — understand what exists from Phase 1 (1A-1D)
2. **Contracts:** `architecture/contracts/entities.ts` — current entity types
3. **UCI data architecture:** `architecture/current_references/uci_data_architecture.md` — folder model, card identity, conceptual model (Sections 2, 3, 4)
4. **Architecture spec:** `architecture/uai_architecture_v1.1.md` — Section 2 (Entity Model)

## What You're Building

### 2A.1 — Base Card Type System (`src/shared/cards.ts`)

Define the base card abstraction:

```typescript
interface BaseCard {
  entity_id: EntityId;           // "session:xxx", "brief:yyy", "folder:zzz"
  entity_type: EntityType;       // discriminant
  display_name: string;
  created_at: string;
  last_activity: string;
  tags: string[];
  icon?: string;
  color?: string;

  // Container capability (null for leaf cards)
  container?: ContainerCapability;
}

interface ContainerCapability {
  children: EntityId[];          // cards in this container
  sub_containers: string[];      // child container IDs (for tree structure)
  placement_rule: 'exclusive' | 'non-exclusive';
  // exclusive: card can be in exactly one container of this type
  // non-exclusive: card can be in many containers of this type
}

// Type-specific extensions
interface SessionCard extends BaseCard { entity_type: 'session'; ... }
interface BriefCard extends BaseCard { entity_type: 'brief'; ... }
interface FolderCard extends BaseCard { entity_type: 'folder'; container: ContainerCapability; ... }
interface GroupCard extends BaseCard { entity_type: 'group'; container: ContainerCapability; ... }
// Future: TeamCard, ProjectCard

type AnyCard = SessionCard | BriefCard | FolderCard | GroupCard;
```

### 2A.2 — Generic Container Operations (`src/main/container-manager.ts`)

Refactor `folder-manager.ts` into a generic container manager:

- `addCardToContainer(containerId, cardId)` — works for any container type
- `removeCardFromContainer(containerId, cardId)`
- `moveCard(cardId, fromContainerId, toContainerId)` — enforces placement rules
- `listCards(containerId, options?: { descendants?: boolean })`
- `createContainer(type, name, parentId?, opts?)` — creates folder, group, etc.
- `deleteContainer(containerId)` — with orphan handling
- `validateTree(rootId)` — tree integrity checks

Placement rule enforcement:
- `exclusive` containers: moveCard removes from old container automatically
- `non-exclusive` containers: addCard doesn't remove from other containers

Keep `folder-manager.ts` as a thin wrapper that calls container-manager with
`placement_rule: 'exclusive'` — don't break existing folder commands.

### 2A.3 — Generic Card Store (`src/renderer/stores/card-store.ts`)

Refactor the separate session-store, folder-store, tag-store into a unified card store:

```typescript
function useCardStore(): {
  // Universal card operations
  getCard(entityId: EntityId): AnyCard | undefined;
  listCards(filter?: CardFilter): AnyCard[];
  getContainer(containerId: string): ContainerCapability | undefined;
  getCardsInContainer(containerId: string, opts?: { descendants?: boolean }): AnyCard[];
  getContainersForCard(cardId: EntityId): string[];  // which containers hold this card

  // Type-specific accessors (convenience)
  sessions: SessionCard[];
  briefs: BriefCard[];
  folders: FolderCard[];
  groups: GroupCard[];

  // Existing store functionality preserved
  initialized: boolean;
  refresh: () => Promise<void>;
}
```

The existing `useSessionStore()`, `useFolderStore()` can become thin wrappers
around `useCardStore()` for backward compatibility during migration.

### 2A.4 — Generic Card Rendering (`src/renderer/components/cards/`)

Create a generic card rendering system:

```
src/renderer/components/cards/
  BaseCardView.tsx          — renders any card with platform bar, name, status dot, meta
  CardRenderer.tsx          — discriminates on entity_type, delegates to type-specific visual
  CardListView.tsx          — generic list with sort, filter, multi-select, context menu
  ContainerTreeView.tsx     — generic tree with collapse/expand, drag targets
  SessionCardVisual.tsx     — session-specific rendering (status, ctx%, roles)
  BriefCardVisual.tsx       — brief-specific rendering (description, size)
  FolderCardVisual.tsx      — folder-specific rendering (item count, subfolder count)
  index.ts                  — barrel export
```

Key principle: `CardListView` and `ContainerTreeView` work with `BaseCard`.
They don't know about sessions or briefs. Type-specific rendering happens in
the visual components, selected by `CardRenderer` based on `entity_type`.

### 2A.5 — Generic Container Commands

Register container commands that work for any container type:

```
container.create    — creates any container type (folder, group, team, project)
container.delete    — deletes any container
container.rename    — renames any container
container.addCard   — adds card to container (respects placement rules)
container.removeCard
container.moveCard  — moves card between containers
container.reorder   — reorders children

// Type-specific aliases for readability:
folder.create → container.create with type='folder', placement='exclusive'
group.create → container.create with type='group', placement='non-exclusive'
```

Existing folder.* commands in command-handlers.ts should be refactored to call
the generic container operations.

### 2A.6 — Update Navigator and Other Components

Update the Navigator component to use generic card/container rendering:

- Sessions tab: uses `CardListView<SessionCard>` + `ContainerTreeView` for folders
- Briefs tab: uses `CardListView<BriefCard>` + `ContainerTreeView` for folders
- Future Groups tab: uses `CardListView<AnyCard>` + `ContainerTreeView` for groups
- Future Teams tab: same pattern
- Future Projects tab: same pattern

Each navigator tab is just a `ContainerTreeView` with a type filter.

### 2A.7 — Update Contracts

Update `architecture/contracts/entities.ts`:
- Add `BaseCard`, `ContainerCapability`, `AnyCard` types
- Add `ContainerType`, placement rules
- Update `EntityType` to include 'folder' and 'group'
- Add generic container operation types

## Key Rules

1. **Don't break existing functionality** — folders must still work after refactor
2. **Existing commands remain valid** — folder.* commands become aliases for container.*
3. **All container types share the same operations** — add/remove/move/list/validate
4. **Placement rules are the ONLY difference** between folder types and group types
5. **Cards render through a discriminated union** — `CardRenderer` picks the visual by type
6. **Use the command bus** for all mutations
7. **Design tokens only** in CSS
8. **Register with ComponentRegistry** — update describe() for refactored components

## What NOT to Build

- Don't implement Groups, Teams, or Projects yet — just ensure the abstractions support them
- Don't build Group UI — just ensure `ContainerTreeView` would work with non-exclusive containers
- Don't touch the terminal, Memorex, or PromptBox — those aren't cards/containers

## Testing

- Existing contract tests must still pass
- Add tests: generic container operations (create, add, remove, move with both placement rules)
- Add tests: card store type filtering
- Folder functionality must work identically before and after refactor

## Output

Refactored code in `src/`. New files in `src/shared/cards.ts`,
`src/main/container-manager.ts`, `src/renderer/stores/card-store.ts`,
`src/renderer/components/cards/`. Updated existing files to use new abstractions.

## Escalation

Architecture questions → prompt Continuity II at session 20260422_204104_640a7e0c_cla
Scope/UX questions → escalate to PianoMan

When done, send a prompt to Continuity II confirming completion with a summary
of what was refactored and what new abstractions are available for Phase 2 consumers.
