# Card/Container Base Abstraction Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor folder-specific and card-specific code into generic Card/Container base abstractions so every future entity type (Groups, Teams, Projects) reuses the same container/card logic without duplication.

**Architecture:** Bottom-up: contracts first, then shared types, then main-process container manager, then command handlers, then renderer store, then card rendering components, then Navigator integration. Each layer builds on the one below. Existing folder functionality is preserved via thin wrappers that delegate to the new generic operations.

**Tech Stack:** TypeScript, React, Electron IPC, Vitest, node:fs (JSON persistence)

---

## File Map

### New files
| File | Responsibility |
|------|---------------|
| `architecture/contracts/cards.ts` | BaseCard, ContainerCapability, AnyCard contract types |
| `src/shared/cards.ts` | Runtime card/container types (re-exports + helpers) |
| `src/main/container-manager.ts` | Generic container CRUD — placement rules, tree validation |
| `src/renderer/stores/card-store.ts` | Unified card store with type-filtered accessors |
| `src/renderer/components/cards/BaseCardView.tsx` | Renders any card: platform bar, name, status dot, meta |
| `src/renderer/components/cards/CardRenderer.tsx` | Discriminated union dispatch to type-specific visuals |
| `src/renderer/components/cards/CardListView.tsx` | Generic sortable, filterable, multi-selectable card list |
| `src/renderer/components/cards/ContainerTreeView.tsx` | Generic collapsible tree with folder/container navigation |
| `src/renderer/components/cards/SessionCardVisual.tsx` | Session-specific rendering (status, ctx%, roles) |
| `src/renderer/components/cards/BriefCardVisual.tsx` | Brief-specific rendering (description, size) |
| `src/renderer/components/cards/FolderCardVisual.tsx` | Folder-specific rendering (item count, subfolder count) |
| `src/renderer/components/cards/index.ts` | Barrel export |
| `src/tests/contract-container-manager.test.ts` | Container manager tests (both placement rules) |
| `src/tests/contract-cards.test.ts` | Card type system tests |

### Modified files
| File | Changes |
|------|---------|
| `architecture/contracts/entities.ts` | Add `'group'` to EntityType, update CardId union |
| `architecture/contracts/index.ts` | Re-export `./cards` |
| `src/shared/types.ts` | Re-export card types from contracts |
| `src/shared/index.ts` | Re-export from `./cards` |
| `src/main/folder-manager.ts` | Thin wrapper delegating to container-manager |
| `src/main/command-handlers.ts` | Add `container.*` commands, alias `folder.*` to them |
| `src/renderer/stores/index.ts` | Export `useCardStore` |
| `src/renderer/components/Navigator.tsx` | Use CardListView + ContainerTreeView |
| `src/renderer/components/index.ts` | Re-export card components |
| `src/shared/component-descriptions.ts` | Add card_list, container_tree descriptions |

---

## Task 1: Update Entity Contracts

**Files:**
- Modify: `architecture/contracts/entities.ts`
- Create: `architecture/contracts/cards.ts`
- Modify: `architecture/contracts/index.ts`
- Test: `src/tests/contract-cards.test.ts`

- [ ] **Step 1: Write contract card type tests**

Create `src/tests/contract-cards.test.ts`:

```typescript
import { describe, it, expect } from 'vitest';
import type {
  BaseCard, ContainerCapability, SessionCard, BriefCard,
  FolderCard, GroupCard, AnyCard, PlacementRule, ContainerType,
} from '../../architecture/contracts';
import { makeEntityId, parseEntityId } from '../../architecture/contracts';

describe('Card type system contracts', () => {
  it('BaseCard has required fields', () => {
    const card: BaseCard = {
      entity_id: 'session:test_123',
      entity_type: 'session',
      display_name: 'Test Session',
      created_at: '2026-04-24T00:00:00Z',
      last_activity: '2026-04-24T01:00:00Z',
      tags: ['dev'],
    };
    expect(card.entity_id).toBe('session:test_123');
    expect(card.entity_type).toBe('session');
    expect(card.container).toBeUndefined();
  });

  it('ContainerCapability defines children and placement rule', () => {
    const cap: ContainerCapability = {
      children: ['session:a', 'session:b'],
      sub_containers: ['folder:child1'],
      placement_rule: 'exclusive',
    };
    expect(cap.placement_rule).toBe('exclusive');
    expect(cap.children).toHaveLength(2);
  });

  it('FolderCard has container capability with exclusive placement', () => {
    const folder: FolderCard = {
      entity_id: 'folder:test_folder',
      entity_type: 'folder',
      display_name: 'My Folder',
      created_at: '2026-04-24T00:00:00Z',
      last_activity: '2026-04-24T00:00:00Z',
      tags: [],
      builtin: false,
      container: {
        children: [],
        sub_containers: [],
        placement_rule: 'exclusive',
      },
    };
    expect(folder.container.placement_rule).toBe('exclusive');
  });

  it('GroupCard has container capability with non-exclusive placement', () => {
    const group: GroupCard = {
      entity_id: 'group:my_group',
      entity_type: 'group',
      display_name: 'My Group',
      created_at: '2026-04-24T00:00:00Z',
      last_activity: '2026-04-24T00:00:00Z',
      tags: [],
      container: {
        children: [],
        sub_containers: [],
        placement_rule: 'non-exclusive',
      },
    };
    expect(group.container.placement_rule).toBe('non-exclusive');
  });

  it('SessionCard is a leaf card (no container)', () => {
    const session: SessionCard = {
      entity_id: 'session:20260424_000000_abcdef01_cla',
      entity_type: 'session',
      display_name: 'Test',
      created_at: '2026-04-24T00:00:00Z',
      last_activity: '2026-04-24T00:00:00Z',
      tags: [],
      tracking_id: '20260424_000000_abcdef01_cla',
      platform: 'claude_cli',
      process_status: 'running',
    };
    expect(session.container).toBeUndefined();
    expect(session.tracking_id).toBeTruthy();
  });

  it('AnyCard union accepts all card types', () => {
    const cards: AnyCard[] = [
      {
        entity_id: 'session:test', entity_type: 'session', display_name: 'S',
        created_at: '', last_activity: '', tags: [],
        tracking_id: 'test', platform: 'claude_cli', process_status: 'running',
      },
      {
        entity_id: 'folder:test', entity_type: 'folder', display_name: 'F',
        created_at: '', last_activity: '', tags: [], builtin: false,
        container: { children: [], sub_containers: [], placement_rule: 'exclusive' },
      },
    ];
    expect(cards).toHaveLength(2);
  });

  it('EntityType includes group', () => {
    const ref = makeEntityId('group', 'my_group');
    const parsed = parseEntityId(ref);
    expect(parsed.type).toBe('group');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src && npx vitest run tests/contract-cards.test.ts`
Expected: FAIL — types don't exist yet

- [ ] **Step 3: Add 'group' to EntityType and CardId in entities.ts**

In `architecture/contracts/entities.ts`, update:

```typescript
export type EntityType = 'session' | 'brief' | 'project' | 'team' | 'tag' | 'folder' | 'group';

export type CardId = `session:${string}` | `brief:${string}` | `project:${string}` | `team:${string}` | `folder:${string}` | `group:${string}`;
```

- [ ] **Step 4: Create architecture/contracts/cards.ts**

```typescript
/**
 * Card & Container Contracts — Phase 2A
 *
 * Base card abstraction and container capability.
 * Every entity in the system is a Card. Some cards are also Containers.
 */

import type { EntityId, EntityType, CardId } from './entities';
import type { Platform, SessionProcessStatus } from './identity';

// ─── Placement Rules ──────────────────────────────────────────────────────

export type PlacementRule = 'exclusive' | 'non-exclusive';

export type ContainerType = 'folder' | 'group';
// Future: 'team' | 'project'

// ─── Base Card ────────────────────────────────────────────────────────────

export interface BaseCard {
  entity_id: EntityId;
  entity_type: EntityType;
  display_name: string;
  created_at: string;
  last_activity: string;
  tags: string[];
  icon?: string;
  color?: string;

  /** Container capability — undefined for leaf cards */
  container?: ContainerCapability;
}

export interface ContainerCapability {
  children: EntityId[];
  sub_containers: string[];
  placement_rule: PlacementRule;
}

// ─── Type-Specific Card Extensions ────────────────────────────────────────

export interface SessionCard extends BaseCard {
  entity_type: 'session';
  container?: undefined;  // leaf card — explicit for discriminated union narrowing
  tracking_id: string;
  platform: Platform;
  process_status: SessionProcessStatus;
  cli_session_id?: string | null;
  terminal_session?: string | null;
  session_dir?: string | null;
  project_dir?: string | null;
  parent_tracking_id?: string | null;
  roles?: string[];
  model?: string | null;
  identity_status?: string;
  archived?: boolean;
  activity_state?: string;
  context_percent?: number | null;
  exchange_count?: number;
  pinned?: boolean;
  notes?: string | null;
}

export interface BriefCard extends BaseCard {
  entity_type: 'brief';
  container?: undefined;  // leaf card — explicit for discriminated union narrowing
  name: string;
  description: string | null;
  status: 'active' | 'superseded' | 'archived';
  brief_path: string;
  file_size: number | null;
  condenser_session?: string | null;
  content_hash?: string | null;
}

export interface FolderCard extends BaseCard {
  entity_type: 'folder';
  builtin: boolean;
  container: ContainerCapability;  // always present for folders
}

export interface GroupCard extends BaseCard {
  entity_type: 'group';
  container: ContainerCapability;  // always present for groups
}

// ─── Discriminated Union ──────────────────────────────────────────────────

export type AnyCard = SessionCard | BriefCard | FolderCard | GroupCard;

// ─── Type Guards ──────────────────────────────────────────────────────────

export function isContainerCard(card: BaseCard): card is FolderCard | GroupCard {
  return card.container !== undefined;
}

export function isSessionCard(card: BaseCard): card is SessionCard {
  return card.entity_type === 'session';
}

export function isBriefCard(card: BaseCard): card is BriefCard {
  return card.entity_type === 'brief';
}

export function isFolderCard(card: BaseCard): card is FolderCard {
  return card.entity_type === 'folder';
}

export function isGroupCard(card: BaseCard): card is GroupCard {
  return card.entity_type === 'group';
}
```

- [ ] **Step 5: Update architecture/contracts/index.ts**

Add:
```typescript
export * from './cards';
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `cd src && npx vitest run tests/contract-cards.test.ts`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add architecture/contracts/cards.ts architecture/contracts/entities.ts architecture/contracts/index.ts src/tests/contract-cards.test.ts
git commit -m "feat(2A.1): add BaseCard, ContainerCapability, and AnyCard contract types"
```

---

## Task 2: Runtime Card Types in shared/

**Files:**
- Create: `src/shared/cards.ts`
- Modify: `src/shared/types.ts`
- Modify: `src/shared/index.ts`

- [ ] **Step 1: Create src/shared/cards.ts**

```typescript
/**
 * Card & Container runtime types — used by both main and renderer.
 *
 * Re-exports contract types and adds runtime helpers.
 */

// Re-export all card contract types
export type {
  BaseCard, ContainerCapability, SessionCard, BriefCard,
  FolderCard, GroupCard, AnyCard, PlacementRule, ContainerType,
} from '../../architecture/contracts';

export {
  isContainerCard, isSessionCard, isBriefCard, isFolderCard, isGroupCard,
} from '../../architecture/contracts';

// ─── Container Store Data ────────────────────────────────────────────────

/**
 * Extends FolderStoreData to support multiple container types.
 * Backward-compatible: folders.json still works as-is.
 */
export interface ContainerStoreData {
  schema_version: number;
  revision: number;
  roots: Record<string, string>;  // e.g. { sessions: 'all_sessions', briefs: 'all_briefs' }
  containers: Record<string, ContainerEntry>;
}

export interface ContainerEntry {
  id: string;
  name: string;
  container_type: 'folder' | 'group';
  icon: string | null;
  color: string | null;
  builtin: boolean;
  placement_rule: 'exclusive' | 'non-exclusive';
  sub_containers: string[];
  cards: string[];
}

// ─── CardFilter ──────────────────────────────────────────────────────────

export interface CardFilter {
  entity_types?: string[];
  tags?: string[];
  search?: string;
  containerId?: string;
  descendants?: boolean;
}
```

- [ ] **Step 2: Update src/shared/types.ts**

Add re-exports at the end of the existing re-export block:
```typescript
export type { BaseCard, ContainerCapability, SessionCard, BriefCard, FolderCard, GroupCard, AnyCard, PlacementRule, ContainerType } from '../../architecture/contracts';
export { isContainerCard, isSessionCard, isBriefCard, isFolderCard, isGroupCard } from '../../architecture/contracts';
```

- [ ] **Step 3: Update src/shared/index.ts**

Add:
```typescript
export * from './cards';
```

- [ ] **Step 4: Verify TypeScript compiles**

Run: `cd src && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 5: Commit**

```bash
git add src/shared/cards.ts src/shared/types.ts src/shared/index.ts
git commit -m "feat(2A.1): add runtime card/container types in shared/"
```

---

## Task 3: Generic Container Manager (main process)

**Files:**
- Create: `src/main/container-manager.ts`
- Test: `src/tests/contract-container-manager.test.ts`

- [ ] **Step 1: Write container manager tests**

Create `src/tests/contract-container-manager.test.ts`:

```typescript
/**
 * Contract Test: Container Manager
 *
 * Tests generic container operations with both exclusive and non-exclusive
 * placement rules. Validates that folder behavior is preserved and that
 * group-style containers work correctly.
 */

import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';

// Set AI_ROOT to a temp directory before importing
const tmpDir = fs.mkdtempSync(path.join(os.tmpdir(), 'uai-container-test-'));
process.env.AI_ROOT = tmpDir;

import {
  loadContainers, createContainer, addCardToContainer,
  removeCardFromContainer, moveCard, deleteContainer,
  renameContainer, listCards, validateContainerTree,
  getContainerSnapshot,
} from '../main/container-manager';

describe('ContainerManager — exclusive placement (folders)', () => {
  beforeEach(() => {
    // Reset store file
    const dataDir = path.join(tmpDir, 'ai_general', 'data');
    if (fs.existsSync(path.join(dataDir, 'containers.json'))) {
      fs.unlinkSync(path.join(dataDir, 'containers.json'));
    }
  });

  afterEach(() => {
    // Cleanup
  });

  it('creates a container under a root', () => {
    const { containerId } = createContainer('folder', 'My Folder', 'all_sessions');
    expect(containerId).toBeTruthy();

    const store = getContainerSnapshot();
    expect(store.containers[containerId]).toBeDefined();
    expect(store.containers[containerId].name).toBe('My Folder');
    expect(store.containers[containerId].placement_rule).toBe('exclusive');
  });

  it('adds a card to a container', () => {
    const { containerId } = createContainer('folder', 'Folder A', 'all_sessions');
    addCardToContainer(containerId, 'session:test_1');

    const store = getContainerSnapshot();
    expect(store.containers[containerId].cards).toContain('session:test_1');
  });

  it('moveCard with exclusive placement removes from old container', () => {
    const { containerId: folderA } = createContainer('folder', 'Folder A', 'all_sessions');
    const { containerId: folderB } = createContainer('folder', 'Folder B', 'all_sessions');

    addCardToContainer(folderA, 'session:test_1');
    moveCard('session:test_1', folderA, folderB);

    const store = getContainerSnapshot();
    expect(store.containers[folderA].cards).not.toContain('session:test_1');
    expect(store.containers[folderB].cards).toContain('session:test_1');
  });

  it('removeCardFromContainer moves card to root for exclusive placement', () => {
    const { containerId } = createContainer('folder', 'Folder A', 'all_sessions');
    addCardToContainer(containerId, 'session:test_1');
    removeCardFromContainer(containerId, 'session:test_1');

    const store = getContainerSnapshot();
    expect(store.containers[containerId].cards).not.toContain('session:test_1');
    // Card should be back at root
    expect(store.containers['all_sessions'].cards).toContain('session:test_1');
  });

  it('deleteContainer reparents children to parent', () => {
    const { containerId } = createContainer('folder', 'Doomed', 'all_sessions');
    addCardToContainer(containerId, 'session:orphan_1');
    deleteContainer(containerId);

    const store = getContainerSnapshot();
    expect(store.containers[containerId]).toBeUndefined();
    expect(store.containers['all_sessions'].cards).toContain('session:orphan_1');
  });

  it('renameContainer changes the name', () => {
    const { containerId } = createContainer('folder', 'Old Name', 'all_sessions');
    renameContainer(containerId, 'New Name');

    const store = getContainerSnapshot();
    expect(store.containers[containerId].name).toBe('New Name');
  });

  it('validates tree catches orphaned containers', () => {
    const store = getContainerSnapshot();
    // Manually create an orphan for test
    store.containers['orphan_test'] = {
      id: 'orphan_test', name: 'Orphan', container_type: 'folder',
      icon: null, color: null, builtin: false, placement_rule: 'exclusive',
      sub_containers: [], cards: [],
    };
    const errors = validateContainerTree(store);
    expect(errors.some(e => e.includes('orphan'))).toBe(true);
  });

  it('listCards returns cards in a container', () => {
    const { containerId } = createContainer('folder', 'List Test', 'all_sessions');
    addCardToContainer(containerId, 'session:list_1');
    addCardToContainer(containerId, 'session:list_2');

    const cards = listCards(containerId);
    expect(cards).toContain('session:list_1');
    expect(cards).toContain('session:list_2');
  });

  it('rejects session card placed under briefs root tree', () => {
    const { containerId } = createContainer('folder', 'Brief Folder', 'all_briefs');
    expect(() => addCardToContainer(containerId, 'session:wrong_root')).toThrow(
      /session cards can only be in the sessions container tree/i
    );
  });

  it('listCards with descendants includes nested containers', () => {
    const { containerId: parent } = createContainer('folder', 'Parent', 'all_sessions');
    const { containerId: child } = createContainer('folder', 'Child', parent);
    addCardToContainer(parent, 'session:p1');
    addCardToContainer(child, 'session:c1');

    const cards = listCards(parent, { descendants: true });
    expect(cards).toContain('session:p1');
    expect(cards).toContain('session:c1');
  });
});

describe('ContainerManager — non-exclusive placement (groups)', () => {
  beforeEach(() => {
    const dataDir = path.join(tmpDir, 'ai_general', 'data');
    if (fs.existsSync(path.join(dataDir, 'containers.json'))) {
      fs.unlinkSync(path.join(dataDir, 'containers.json'));
    }
  });

  it('creates a group container with non-exclusive placement', () => {
    const { containerId } = createContainer('group', 'My Group', 'all_sessions');

    const store = getContainerSnapshot();
    expect(store.containers[containerId].placement_rule).toBe('non-exclusive');
    expect(store.containers[containerId].container_type).toBe('group');
  });

  it('addCard to non-exclusive container does NOT remove from other containers', () => {
    const { containerId: folder } = createContainer('folder', 'Folder', 'all_sessions');
    const { containerId: group } = createContainer('group', 'Group', 'all_sessions');

    addCardToContainer(folder, 'session:shared_1');
    addCardToContainer(group, 'session:shared_1');

    const store = getContainerSnapshot();
    expect(store.containers[folder].cards).toContain('session:shared_1');
    expect(store.containers[group].cards).toContain('session:shared_1');
  });

  it('removeCardFromContainer on group does NOT move card to root', () => {
    const { containerId: folder } = createContainer('folder', 'Folder', 'all_sessions');
    const { containerId: group } = createContainer('group', 'Group', 'all_sessions');

    addCardToContainer(folder, 'session:shared_1');
    addCardToContainer(group, 'session:shared_1');
    removeCardFromContainer(group, 'session:shared_1');

    const store = getContainerSnapshot();
    expect(store.containers[group].cards).not.toContain('session:shared_1');
    // Still in folder
    expect(store.containers[folder].cards).toContain('session:shared_1');
  });
});
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd src && npx vitest run tests/contract-container-manager.test.ts`
Expected: FAIL — container-manager.ts doesn't exist

- [ ] **Step 3: Implement container-manager.ts**

Create `src/main/container-manager.ts`:

```typescript
/**
 * ContainerManager — generic container persistence and CRUD.
 *
 * Workstream 2A: Card/Container Base Abstractions
 *
 * Generalizes folder-manager.ts to support any container type.
 * Two placement rules:
 *   - exclusive: a card can be in exactly one container (folders)
 *   - non-exclusive: a card can be in many containers (groups)
 *
 * Owns containers.json with atomic read-modify-write.
 * All mutations go through the command bus (see command-handlers.ts).
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import type { ContainerStoreData, ContainerEntry, PlacementRule } from '../shared/cards';

// ─── Path ────────────────────────────────────────────────────────────────

function getContainersPath(): string {
  const aiRoot = process.env.AI_ROOT || path.join(os.homedir(), 'Documents/AI/ai_root');
  return path.join(aiRoot, 'ai_general', 'data', 'containers.json');
}

// ─── Default Store ───────────────────────────────────────────────────────

const DEFAULT_STORE: ContainerStoreData = {
  schema_version: 2,
  revision: 0,
  roots: { sessions: 'all_sessions', briefs: 'all_briefs' },
  containers: {
    all_sessions: {
      id: 'all_sessions',
      name: 'All Sessions',
      container_type: 'folder',
      icon: null,
      color: null,
      builtin: true,
      placement_rule: 'exclusive',
      sub_containers: [],
      cards: [],
    },
    all_briefs: {
      id: 'all_briefs',
      name: 'All Briefs',
      container_type: 'folder',
      icon: null,
      color: null,
      builtin: true,
      placement_rule: 'exclusive',
      sub_containers: [],
      cards: [],
    },
  },
};

// ─── Load / Save ─────────────────────────────────────────────────────────

export function loadContainers(): ContainerStoreData {
  const containersPath = getContainersPath();
  try {
    const content = fs.readFileSync(containersPath, 'utf-8');
    return JSON.parse(content) as ContainerStoreData;
  } catch {
    // Migration fallback: read folders.json and convert to container format
    const foldersPath = containersPath.replace('containers.json', 'folders.json');
    try {
      const foldersContent = fs.readFileSync(foldersPath, 'utf-8');
      const foldersData = JSON.parse(foldersContent);
      return migrateFoldersToContainers(foldersData);
    } catch {
      return structuredClone(DEFAULT_STORE);
    }
  }
}

/**
 * One-time migration: convert folders.json (FolderStoreData) to ContainerStoreData.
 */
function migrateFoldersToContainers(foldersData: any): ContainerStoreData {
  const containers: Record<string, ContainerEntry> = {};
  for (const [id, folder] of Object.entries(foldersData.folders || {})) {
    const f = folder as any;
    containers[id] = {
      id,
      name: f.name,
      container_type: 'folder',
      icon: f.icon || null,
      color: f.color || null,
      builtin: f.builtin || false,
      placement_rule: 'exclusive',
      sub_containers: f.subfolders || [],
      cards: f.cards || [],
    };
  }
  return {
    schema_version: 2,
    revision: foldersData.revision || 0,
    roots: foldersData.roots || { sessions: 'all_sessions', briefs: 'all_briefs' },
    containers,
  };
}

function saveContainers(store: ContainerStoreData): void {
  const filePath = getContainersPath();
  const dir = path.dirname(filePath);
  if (!fs.existsSync(dir)) {
    // Fail loudly if data dir doesn't exist — don't silently create hierarchy.
    // The data dir should have been created during app setup.
    throw new Error(`Data directory does not exist: ${dir}. Create it before writing.`);
  }
  store.revision++;
  const tmpPath = `${filePath}.tmp.${process.pid}`;
  fs.writeFileSync(tmpPath, JSON.stringify(store, null, 2));
  fs.renameSync(tmpPath, filePath);
}

function updateStore(mutator: (store: ContainerStoreData) => void): ContainerStoreData {
  const store = loadContainers();
  mutator(store);
  const errors = validateContainerTree(store);
  if (errors.length > 0) {
    throw new Error(`Container tree validation failed: ${errors.join('; ')}`);
  }
  saveContainers(store);
  return store;
}

// ─── ID Generation ───────────────────────────────────────────────────────

function generateContainerId(type: string): string {
  return `${type}_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 6)}`;
}

// ─── Placement Rule Map ──────────────────────────────────────────────────

const TYPE_PLACEMENT: Record<string, PlacementRule> = {
  folder: 'exclusive',
  group: 'non-exclusive',
};

// ─── Helpers ─────────────────────────────────────────────────────────────

function cardRootType(cardId: string): string | null {
  if (cardId.startsWith('session:')) return 'sessions';
  if (cardId.startsWith('brief:')) return 'briefs';
  return null;
}

function isUnderRoot(containerId: string, rootId: string, store: ContainerStoreData): boolean {
  let current = containerId;
  const visited = new Set<string>();
  while (current) {
    if (visited.has(current)) return false;
    visited.add(current);
    if (current === rootId) return true;
    const parent = Object.values(store.containers).find(c => c.sub_containers.includes(current));
    if (!parent) return false;
    current = parent.id;
  }
  return false;
}

function findParentContainer(containerId: string, store: ContainerStoreData): ContainerEntry | null {
  for (const container of Object.values(store.containers)) {
    if (container.sub_containers.includes(containerId)) return container;
  }
  return null;
}

function findCardContainer(cardId: string, store: ContainerStoreData, containerType?: string): ContainerEntry | null {
  for (const container of Object.values(store.containers)) {
    if (containerType && container.container_type !== containerType) continue;
    if (container.cards.includes(cardId)) return container;
  }
  return null;
}

function findAllCardContainers(cardId: string, store: ContainerStoreData): ContainerEntry[] {
  return Object.values(store.containers).filter(c => c.cards.includes(cardId));
}

function getAllDescendantIds(containerId: string, store: ContainerStoreData): string[] {
  const result: string[] = [];
  const queue = [containerId];
  while (queue.length > 0) {
    const current = queue.shift()!;
    const container = store.containers[current];
    if (!container) continue;
    for (const childId of container.sub_containers) {
      result.push(childId);
      queue.push(childId);
    }
  }
  return result;
}

// ─── Validation ──────────────────────────────────────────────────────────

export function validateContainerTree(store: ContainerStoreData): string[] {
  const errors: string[] = [];

  // Every container reachable from exactly one root
  const reachable = new Set<string>();
  for (const rootId of Object.values(store.roots)) {
    const queue = [rootId];
    while (queue.length > 0) {
      const id = queue.shift()!;
      if (reachable.has(id)) {
        errors.push(`Container ${id} reachable from multiple roots`);
        continue;
      }
      reachable.add(id);
      const container = store.containers[id];
      if (container) {
        queue.push(...container.sub_containers);
      }
    }
  }

  // Orphaned containers
  for (const id of Object.keys(store.containers)) {
    if (!reachable.has(id)) {
      errors.push(`Container ${id} is orphaned (not reachable from any root)`);
    }
  }

  // No container in two parents
  const parentCount = new Map<string, number>();
  for (const container of Object.values(store.containers)) {
    for (const childId of container.sub_containers) {
      parentCount.set(childId, (parentCount.get(childId) || 0) + 1);
    }
  }
  for (const [id, count] of parentCount) {
    if (count > 1) {
      errors.push(`Container ${id} appears in ${count} parents`);
    }
  }

  // Exclusive placement: no card in two exclusive containers
  const exclusiveCardContainer = new Map<string, string>();
  for (const container of Object.values(store.containers)) {
    if (container.placement_rule !== 'exclusive') continue;
    for (const cardId of container.cards) {
      if (exclusiveCardContainer.has(cardId)) {
        errors.push(`Card ${cardId} in exclusive containers ${exclusiveCardContainer.get(cardId)} and ${container.id}`);
      }
      exclusiveCardContainer.set(cardId, container.id);
    }
  }

  return errors;
}

// ─── CRUD Operations ─────────────────────────────────────────────────────

export function createContainer(
  type: 'folder' | 'group',
  name: string,
  parentId: string,
  opts?: { icon?: string; color?: string },
): { store: ContainerStoreData; containerId: string } {
  const containerId = generateContainerId(type);
  const store = updateStore((s) => {
    const parent = s.containers[parentId];
    if (!parent) throw new Error(`Parent container ${parentId} not found`);

    // Name unique within parent
    for (const sibId of parent.sub_containers) {
      const sib = s.containers[sibId];
      if (sib && sib.name === name) {
        throw new Error(`Container name "${name}" already exists in ${parentId}`);
      }
    }

    s.containers[containerId] = {
      id: containerId,
      name,
      container_type: type,
      icon: opts?.icon || null,
      color: opts?.color || null,
      builtin: false,
      placement_rule: TYPE_PLACEMENT[type] || 'exclusive',
      sub_containers: [],
      cards: [],
    };
    parent.sub_containers.push(containerId);
  });
  return { store, containerId };
}

export function renameContainer(containerId: string, name: string): ContainerStoreData {
  return updateStore((s) => {
    const container = s.containers[containerId];
    if (!container) throw new Error(`Container ${containerId} not found`);
    if (container.builtin) throw new Error(`Cannot rename builtin container`);

    const parent = findParentContainer(containerId, s);
    if (parent) {
      for (const sibId of parent.sub_containers) {
        if (sibId === containerId) continue;
        const sib = s.containers[sibId];
        if (sib && sib.name === name) {
          throw new Error(`Container name "${name}" already exists in parent`);
        }
      }
    }

    container.name = name;
  });
}

export function deleteContainer(
  containerId: string,
  policy: 'reparent' | 'cascade' = 'reparent',
): ContainerStoreData {
  return updateStore((s) => {
    const container = s.containers[containerId];
    if (!container) throw new Error(`Container ${containerId} not found`);
    if (container.builtin) throw new Error(`Cannot delete builtin container`);
    if (Object.values(s.roots).includes(containerId)) {
      throw new Error(`Cannot delete root container`);
    }

    const parent = findParentContainer(containerId, s);
    if (!parent) throw new Error(`Container ${containerId} has no parent`);

    if (policy === 'reparent') {
      for (const childId of container.sub_containers) {
        parent.sub_containers.push(childId);
      }
      for (const cardId of container.cards) {
        parent.cards.push(cardId);
      }
    } else {
      const descendants = getAllDescendantIds(containerId, s);
      for (const descId of descendants) {
        const desc = s.containers[descId];
        if (desc) {
          for (const cardId of desc.cards) {
            parent.cards.push(cardId);
          }
        }
        delete s.containers[descId];
      }
      for (const cardId of container.cards) {
        parent.cards.push(cardId);
      }
    }

    parent.sub_containers = parent.sub_containers.filter(id => id !== containerId);
    delete s.containers[containerId];
  });
}

export function addCardToContainer(containerId: string, cardId: string): ContainerStoreData {
  return updateStore((s) => {
    const container = s.containers[containerId];
    if (!container) throw new Error(`Container ${containerId} not found`);

    if (container.cards.includes(cardId)) return; // idempotent

    // Root-tree constraint: session cards must be under sessions root, brief cards under briefs root
    if (container.placement_rule === 'exclusive') {
      const rootType = cardRootType(cardId);
      if (rootType) {
        const rootId = s.roots[rootType];
        if (rootId && !isUnderRoot(containerId, rootId, s)) {
          throw new Error(`${rootType.slice(0, -1)} cards can only be in the ${rootType} container tree`);
        }
      }
    }

    // For exclusive placement, remove from other exclusive containers of same type
    if (container.placement_rule === 'exclusive') {
      for (const other of Object.values(s.containers)) {
        if (other.placement_rule === 'exclusive' && other.cards.includes(cardId)) {
          other.cards = other.cards.filter(id => id !== cardId);
        }
      }
    }

    container.cards.push(cardId);
  });
}

export function removeCardFromContainer(containerId: string, cardId: string): ContainerStoreData {
  return updateStore((s) => {
    const container = s.containers[containerId];
    if (!container) throw new Error(`Container ${containerId} not found`);

    container.cards = container.cards.filter(id => id !== cardId);

    // For exclusive placement, move card to root if not in any other exclusive container
    if (container.placement_rule === 'exclusive') {
      const rootType = cardRootType(cardId);
      if (rootType) {
        const rootId = s.roots[rootType];
        const root = s.containers[rootId];
        if (root && !root.cards.includes(cardId)) {
          // Check if card is in any other exclusive container
          const inOther = Object.values(s.containers).some(
            c => c.placement_rule === 'exclusive' && c.cards.includes(cardId)
          );
          if (!inOther) {
            root.cards.push(cardId);
          }
        }
      }
    }
  });
}

export function moveCard(
  cardId: string,
  fromContainerId: string,
  toContainerId: string,
  index?: number,
): ContainerStoreData {
  return updateStore((s) => {
    const from = s.containers[fromContainerId];
    const to = s.containers[toContainerId];
    if (!from) throw new Error(`Source container ${fromContainerId} not found`);
    if (!to) throw new Error(`Target container ${toContainerId} not found`);

    from.cards = from.cards.filter(id => id !== cardId);

    if (index !== undefined && index >= 0 && index <= to.cards.length) {
      to.cards.splice(index, 0, cardId);
    } else {
      to.cards.push(cardId);
    }
  });
}

export function listCards(
  containerId: string,
  opts?: { descendants?: boolean },
): string[] {
  const store = loadContainers();
  const container = store.containers[containerId];
  if (!container) return [];

  const result = [...container.cards];

  if (opts?.descendants) {
    const queue = [...container.sub_containers];
    while (queue.length > 0) {
      const childId = queue.shift()!;
      const child = store.containers[childId];
      if (!child) continue;
      result.push(...child.cards);
      queue.push(...child.sub_containers);
    }
  }

  return result;
}

export function getContainerSnapshot(): ContainerStoreData {
  return loadContainers();
}

export function reorderContainerChildren(containerId: string, orderedIds: string[]): ContainerStoreData {
  return updateStore((s) => {
    const container = s.containers[containerId];
    if (!container) throw new Error(`Container ${containerId} not found`);
    const current = new Set(container.sub_containers);
    const incoming = new Set(orderedIds);
    if (current.size !== incoming.size || ![...current].every(id => incoming.has(id))) {
      throw new Error(`Reorder must contain exactly the same child IDs`);
    }
    container.sub_containers = orderedIds;
  });
}

export function reorderContainerCards(containerId: string, orderedCardIds: string[]): ContainerStoreData {
  return updateStore((s) => {
    const container = s.containers[containerId];
    if (!container) throw new Error(`Container ${containerId} not found`);
    const current = new Set(container.cards);
    const incoming = new Set(orderedCardIds);
    if (current.size !== incoming.size || ![...current].every(id => incoming.has(id))) {
      throw new Error(`Reorder must contain exactly the same card IDs`);
    }
    container.cards = orderedCardIds;
  });
}

export function moveContainer(
  containerId: string,
  targetParentId: string,
  index?: number,
): ContainerStoreData {
  return updateStore((s) => {
    const container = s.containers[containerId];
    if (!container) throw new Error(`Container ${containerId} not found`);
    if (container.builtin) throw new Error(`Cannot move builtin container`);
    if (Object.values(s.roots).includes(containerId)) {
      throw new Error(`Cannot move root container`);
    }

    const target = s.containers[targetParentId];
    if (!target) throw new Error(`Target parent ${targetParentId} not found`);

    // Prevent cycles
    const descendants = getAllDescendantIds(containerId, s);
    if (descendants.includes(targetParentId) || targetParentId === containerId) {
      throw new Error(`Cannot move container into its own descendant`);
    }

    // Name unique in new parent
    for (const sibId of target.sub_containers) {
      if (sibId === containerId) continue;
      const sib = s.containers[sibId];
      if (sib && sib.name === container.name) {
        throw new Error(`Container name "${container.name}" already exists in target parent`);
      }
    }

    // Remove from old parent
    const oldParent = findParentContainer(containerId, s);
    if (oldParent) {
      oldParent.sub_containers = oldParent.sub_containers.filter(id => id !== containerId);
    }

    // Add to new parent
    if (index !== undefined && index >= 0 && index <= target.sub_containers.length) {
      target.sub_containers.splice(index, 0, containerId);
    } else {
      target.sub_containers.push(containerId);
    }
  });
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd src && npx vitest run tests/contract-container-manager.test.ts`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/main/container-manager.ts src/tests/contract-container-manager.test.ts
git commit -m "feat(2A.2): implement generic ContainerManager with placement rules"
```

---

## Task 4: Refactor FolderManager as Thin Wrapper

**Files:**
- Modify: `src/main/folder-manager.ts`

- [ ] **Step 1: Run existing folder tests to establish baseline**

Run: `cd src && npx vitest run`
Expected: All existing tests pass

- [ ] **Step 2: Refactor folder-manager.ts to delegate to container-manager**

Replace the entire `folder-manager.ts` with a thin wrapper that delegates every operation to `container-manager.ts`. All helper functions (`moveContainer`, `reorderContainerChildren`, `reorderContainerCards`) are already in container-manager from Task 3.

```typescript
/**
 * FolderManager — thin wrapper over ContainerManager.
 *
 * Preserves the existing folder API but delegates all logic to the
 * generic ContainerManager. Folders are containers with exclusive placement.
 *
 * Workstream 2A: Backward compatibility layer.
 */

import type { FolderStoreData, Folder } from '../shared/types';
import {
  loadContainers, createContainer as genericCreate,
  renameContainer, deleteContainer as genericDelete,
  addCardToContainer, removeCardFromContainer,
  moveCard as genericMoveCard, moveContainer,
  reorderContainerChildren, reorderContainerCards,
  validateContainerTree, getContainerSnapshot,
} from './container-manager';
import type { ContainerStoreData } from '../shared/cards';

// ─── Adapter: ContainerStoreData → FolderStoreData ───────────────────────

function toFolderStore(cs: ContainerStoreData): FolderStoreData {
  const folders: Record<string, Folder> = {};
  for (const [id, entry] of Object.entries(cs.containers)) {
    if (entry.container_type !== 'folder') continue;
    folders[id] = {
      id: entry.id,
      name: entry.name,
      icon: entry.icon,
      color: entry.color,
      builtin: entry.builtin,
      subfolders: entry.sub_containers.filter(
        sid => cs.containers[sid]?.container_type === 'folder'
      ),
      cards: entry.cards,
    };
  }
  return {
    schema_version: cs.schema_version,
    revision: cs.revision,
    roots: {
      sessions: cs.roots.sessions || 'all_sessions',
      briefs: cs.roots.briefs || 'all_briefs',
    },
    folders,
  };
}

// ─── Public API (unchanged signatures) ───────────────────────────────────

export function loadFolders(): FolderStoreData {
  return toFolderStore(loadContainers());
}

export function validateTree(store: FolderStoreData): string[] {
  return validateContainerTree(loadContainers());
}

export function createFolder(
  parentId: string, name: string, icon?: string,
): { store: FolderStoreData; folderId: string } {
  const { store, containerId } = genericCreate('folder', name, parentId, { icon });
  return { store: toFolderStore(store), folderId: containerId };
}

export function renameFolder(folderId: string, name: string): FolderStoreData {
  return toFolderStore(renameContainer(folderId, name));
}

export function deleteFolder(folderId: string, policy: 'reparent' | 'cascade' = 'reparent'): FolderStoreData {
  return toFolderStore(genericDelete(folderId, policy));
}

export function moveFolder(folderId: string, targetParentId: string, index?: number): FolderStoreData {
  return toFolderStore(moveContainer(folderId, targetParentId, index));
}

export function moveCard(cardId: string, targetFolderId: string, index?: number): FolderStoreData {
  const cs = loadContainers();
  let fromId: string | null = null;
  for (const [id, entry] of Object.entries(cs.containers)) {
    if (entry.cards.includes(cardId)) { fromId = id; break; }
  }
  if (fromId) {
    return toFolderStore(genericMoveCard(cardId, fromId, targetFolderId, index));
  }
  return toFolderStore(addCardToContainer(targetFolderId, cardId));
}

export function unfileCard(cardId: string): FolderStoreData {
  const cs = loadContainers();
  const rootType = cardId.startsWith('session:') ? 'sessions' : cardId.startsWith('brief:') ? 'briefs' : null;
  if (!rootType) throw new Error(`Invalid card ID: ${cardId}`);
  for (const [id, entry] of Object.entries(cs.containers)) {
    if (entry.placement_rule === 'exclusive' && entry.cards.includes(cardId)) {
      if (id === cs.roots[rootType]) return toFolderStore(cs);
      return toFolderStore(removeCardFromContainer(id, cardId));
    }
  }
  return toFolderStore(cs);
}

export function reorderSubfolders(parentId: string, orderedIds: string[]): FolderStoreData {
  return toFolderStore(reorderContainerChildren(parentId, orderedIds));
}

export function reorderCards(folderId: string, orderedCardIds: string[]): FolderStoreData {
  return toFolderStore(reorderContainerCards(folderId, orderedCardIds));
}

export function getSnapshot(): FolderStoreData {
  return toFolderStore(getContainerSnapshot());
}
```

- [ ] **Step 3: Run all existing tests**

Run: `cd src && npx vitest run`
Expected: All existing tests pass (folder commands still work via the wrapper)

- [ ] **Step 4: Commit**

```bash
git add src/main/folder-manager.ts src/main/container-manager.ts
git commit -m "refactor(2A.2): folder-manager now delegates to container-manager"
```

---

## Task 5: Add Container Commands to Command Handlers

**Files:**
- Modify: `src/main/command-handlers.ts`

- [ ] **Step 1: Add container.* command registrations**

In `command-handlers.ts`, after the existing `folder.*` registrations, add generic `container.*` commands:

```typescript
import {
  createContainer, renameContainer, deleteContainer,
  addCardToContainer, removeCardFromContainer,
  moveCard as containerMoveCard, moveContainer,
  reorderContainerChildren, reorderContainerCards,
  getContainerSnapshot, validateContainerTree, loadContainers,
  listCards as containerListCards,
} from './container-manager';
import type { ContainerStoreData } from '../shared/cards';

// ── container.create ──────────────────────────────────────────────────
bus.register('container.create', async (command: Command): Promise<CommandResult<{ containerId: string }>> => {
  const { type, name, parentId, icon, color } = command.payload as {
    type: 'folder' | 'group';
    name: string;
    parentId: string;
    icon?: string;
    color?: string;
  };
  try {
    const { store, containerId } = createContainer(type, name, parentId, { icon, color });
    emit('command', ['folders']);
    return {
      ok: true, command_id: command.id,
      data: { containerId },
      changed: { folders: true },
    };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, command_id: command.id, error: { code: 'CONTAINER_CREATE_FAILED', message } };
  }
});

// ── container.delete ──────────────────────────────────────────────────
bus.register('container.delete', async (command: Command): Promise<CommandResult> => {
  const { containerId, policy } = command.payload as {
    containerId: string;
    policy?: 'reparent' | 'cascade';
  };
  try {
    deleteContainer(containerId, policy);
    emit('command', ['folders']);
    return { ok: true, command_id: command.id, changed: { folders: true } };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, command_id: command.id, error: { code: 'CONTAINER_DELETE_FAILED', message } };
  }
});

// ── container.rename ──────────────────────────────────────────────────
bus.register('container.rename', async (command: Command): Promise<CommandResult> => {
  const { containerId, name } = command.payload as { containerId: string; name: string };
  try {
    renameContainer(containerId, name);
    emit('command', ['folders']);
    return { ok: true, command_id: command.id, changed: { folders: true } };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, command_id: command.id, error: { code: 'CONTAINER_RENAME_FAILED', message } };
  }
});

// ── container.addCard ─────────────────────────────────────────────────
bus.register('container.addCard', async (command: Command): Promise<CommandResult> => {
  const { containerId, cardId } = command.payload as { containerId: string; cardId: string };
  try {
    addCardToContainer(containerId, cardId);
    emit('command', ['folders']);
    return { ok: true, command_id: command.id, changed: { folders: true } };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, command_id: command.id, error: { code: 'CONTAINER_ADD_FAILED', message } };
  }
});

// ── container.removeCard ──────────────────────────────────────────────
bus.register('container.removeCard', async (command: Command): Promise<CommandResult> => {
  const { containerId, cardId } = command.payload as { containerId: string; cardId: string };
  try {
    removeCardFromContainer(containerId, cardId);
    emit('command', ['folders']);
    return { ok: true, command_id: command.id, changed: { folders: true } };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, command_id: command.id, error: { code: 'CONTAINER_REMOVE_FAILED', message } };
  }
});

// ── container.moveCard ────────────────────────────────────────────────
bus.register('container.moveCard', async (command: Command): Promise<CommandResult> => {
  const { cardId, fromContainerId, toContainerId, index } = command.payload as {
    cardId: string;
    fromContainerId: string;
    toContainerId: string;
    index?: number;
  };
  try {
    containerMoveCard(cardId, fromContainerId, toContainerId, index);
    emit('command', ['folders']);
    return { ok: true, command_id: command.id, changed: { folders: true } };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, command_id: command.id, error: { code: 'CONTAINER_MOVE_FAILED', message } };
  }
});

// ── container.reorder ─────────────────────────────────────────────────
bus.register('container.reorder', async (command: Command): Promise<CommandResult> => {
  const { containerId, orderedCardIds } = command.payload as {
    containerId: string;
    orderedCardIds: string[];
  };
  try {
    reorderContainerCards(containerId, orderedCardIds);
    emit('command', ['folders']);
    return { ok: true, command_id: command.id, changed: { folders: true } };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, command_id: command.id, error: { code: 'CONTAINER_REORDER_FAILED', message } };
  }
});
```

- [ ] **Step 2: Run all tests**

Run: `cd src && npx vitest run`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/main/command-handlers.ts
git commit -m "feat(2A.5): register container.* commands on command bus"
```

---

## Task 6: Card Store (renderer)

**Files:**
- Create: `src/renderer/stores/card-store.ts`
- Modify: `src/renderer/stores/index.ts`

- [ ] **Step 1: Create card-store.ts**

```typescript
/**
 * CardStore — unified renderer-side card store.
 *
 * Workstream 2A: Card/Container Base Abstractions
 *
 * Combines session and folder data into a single card-oriented store.
 * Provides type-filtered accessors and container-aware queries.
 * Existing useSessionStore() and useFolderStore() remain as thin wrappers.
 */

import { useState, useEffect, useCallback } from 'react';
import type { Session } from '../../shared/types';
import type { AnyCard, SessionCard, BriefCard, FolderCard, GroupCard, CardFilter } from '../../shared/cards';
import type { ContainerStoreData, ContainerEntry } from '../../shared/cards';
import type { EntityId } from '../../shared/types';
import { isSessionCard, isBriefCard, isFolderCard, isGroupCard } from '../../shared/cards';
import type { StoreChangedEvent } from '../../shared/types';

// ─── Singleton state ──────────────────────────────────────────────────────

let cards = new Map<string, AnyCard>();
let containerStore: ContainerStoreData | null = null;
let initialized = false;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) listener();
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// ─── Session → SessionCard adapter ───────────────────────────────────────

function sessionToCard(s: Session): SessionCard {
  return {
    entity_id: `session:${s.tracking_id}`,
    entity_type: 'session',
    display_name: s.display_name || s.tracking_id,
    created_at: s.created_at,
    last_activity: s.last_activity || s.created_at,
    tags: s.tags || [],
    tracking_id: s.tracking_id,
    platform: s.platform,
    process_status: s.process_status,
    cli_session_id: s.cli_session_id,
    terminal_session: s.terminal_session,
    session_dir: s.session_dir,
    project_dir: s.project_dir,
    parent_tracking_id: s.parent_tracking_id,
    roles: s.roles,
    model: s.model,
    identity_status: s.identity_status,
    archived: s.archived,
    activity_state: s.activity_state,
    context_percent: s.context_percent,
    exchange_count: s.exchange_count,
    pinned: s.pinned,
    notes: s.notes,
  };
}

// ─── ContainerEntry → FolderCard/GroupCard adapter ────────────────────────

function containerToCard(entry: ContainerEntry): FolderCard | GroupCard {
  const base = {
    entity_id: `${entry.container_type}:${entry.id}` as EntityId,
    entity_type: entry.container_type as 'folder' | 'group',
    display_name: entry.name,
    created_at: '',
    last_activity: '',
    tags: [],
    icon: entry.icon || undefined,
    color: entry.color || undefined,
    container: {
      children: entry.cards as any[],
      sub_containers: entry.sub_containers,
      placement_rule: entry.placement_rule,
    },
  };

  if (entry.container_type === 'group') {
    return { ...base, entity_type: 'group' } as GroupCard;
  }
  return { ...base, entity_type: 'folder', builtin: entry.builtin } as FolderCard;
}

// ─── Bootstrap and refresh ───────────────────────────────────────────────

export async function bootstrap(): Promise<void> {
  try {
    const [snapshot, folderData] = await Promise.all([
      window.uai.bootstrap(),
      window.uai.folders.list(),
    ]);

    cards = new Map();

    // Sessions → cards
    for (const session of snapshot.sessions) {
      const card = sessionToCard(session);
      cards.set(card.entity_id, card);
    }

    // Containers → cards
    if (folderData) {
      containerStore = {
        schema_version: folderData.schema_version,
        revision: folderData.revision,
        roots: folderData.roots,
        containers: {},
      };
      for (const [id, folder] of Object.entries(folderData.folders)) {
        const entry: ContainerEntry = {
          id, name: folder.name, container_type: 'folder',
          icon: folder.icon, color: folder.color, builtin: folder.builtin,
          placement_rule: 'exclusive',
          sub_containers: folder.subfolders, cards: folder.cards,
        };
        containerStore.containers[id] = entry;
        cards.set(`folder:${id}`, containerToCard(entry));
      }
    }

    initialized = true;
    notify();
  } catch {
    initialized = true;
    notify();
  }
}

async function refresh(): Promise<void> {
  try {
    const [sessions, folderData] = await Promise.all([
      window.uai.sessions.list(),
      window.uai.folders.list(),
    ]);

    const newCards = new Map<string, AnyCard>();

    for (const session of sessions) {
      const card = sessionToCard(session);
      newCards.set(card.entity_id, card);
    }

    if (folderData) {
      containerStore = {
        schema_version: folderData.schema_version,
        revision: folderData.revision,
        roots: folderData.roots,
        containers: {},
      };
      for (const [id, folder] of Object.entries(folderData.folders)) {
        const entry: ContainerEntry = {
          id, name: folder.name, container_type: 'folder',
          icon: folder.icon, color: folder.color, builtin: folder.builtin,
          placement_rule: 'exclusive',
          sub_containers: folder.subfolders, cards: folder.cards,
        };
        containerStore.containers[id] = entry;
        newCards.set(`folder:${id}`, containerToCard(entry));
      }
    }

    cards = newCards;
    notify();
  } catch {
    // Keep current state
  }
}

// ─── Imperative API ──────────────────────────────────────────────────────

export function getCard(entityId: string): AnyCard | undefined {
  return cards.get(entityId);
}

export function listAllCards(filter?: CardFilter): AnyCard[] {
  let result = Array.from(cards.values());

  if (filter?.entity_types) {
    result = result.filter(c => filter.entity_types!.includes(c.entity_type));
  }
  if (filter?.tags && filter.tags.length > 0) {
    result = result.filter(c => filter.tags!.some(t => c.tags.includes(t)));
  }
  if (filter?.search) {
    const q = filter.search.toLowerCase();
    result = result.filter(c => c.display_name.toLowerCase().includes(q));
  }

  return result;
}

export function getContainerForId(containerId: string): ContainerEntry | undefined {
  return containerStore?.containers[containerId];
}

export function getCardsInContainer(containerId: string, opts?: { descendants?: boolean }): AnyCard[] {
  const entry = containerStore?.containers[containerId];
  if (!entry) return [];

  const cardIds = [...entry.cards];

  if (opts?.descendants) {
    const queue = [...entry.sub_containers];
    while (queue.length > 0) {
      const childId = queue.shift()!;
      const child = containerStore?.containers[childId];
      if (!child) continue;
      cardIds.push(...child.cards);
      queue.push(...child.sub_containers);
    }
  }

  return cardIds.map(id => cards.get(id)).filter((c): c is AnyCard => c !== undefined);
}

export function getContainersForCard(cardId: string): string[] {
  if (!containerStore) return [];
  return Object.entries(containerStore.containers)
    .filter(([, entry]) => entry.cards.includes(cardId))
    .map(([id]) => id);
}

// ─── Type-specific convenience accessors ─────────────────────────────────

export function getSessions(): SessionCard[] {
  return listAllCards({ entity_types: ['session'] }) as SessionCard[];
}

export function getBriefs(): BriefCard[] {
  return listAllCards({ entity_types: ['brief'] }) as BriefCard[];
}

export function getFolders(): FolderCard[] {
  return listAllCards({ entity_types: ['folder'] }) as FolderCard[];
}

export function getGroups(): GroupCard[] {
  return listAllCards({ entity_types: ['group'] }) as GroupCard[];
}

// ─── Path 2: Store change subscription ───────────────────────────────────

let unsubStoreChanged: (() => void) | null = null;

function startListening(): void {
  if (unsubStoreChanged) return;
  unsubStoreChanged = window.uai.onStoreChanged((event: StoreChangedEvent) => {
    if (event.changed.includes('sessions') || event.changed.includes('folders')) {
      refresh();
    }
  });
}

// ─── React Hook ──────────────────────────────────────────────────────────

export function useCardStore() {
  const [, forceUpdate] = useState(0);

  useEffect(() => {
    if (!initialized) {
      bootstrap();
      startListening();
    }
    const unsub = subscribe(() => forceUpdate(n => n + 1));
    return unsub;
  }, []);

  return {
    initialized,
    getCard,
    listCards: listAllCards,
    getCardsInContainer,
    getContainersForCard,
    getContainer: getContainerForId,
    sessions: getSessions(),
    briefs: getBriefs(),
    folders: getFolders(),
    groups: getGroups(),
    refresh,
  };
}
```

- [ ] **Step 2: Update src/renderer/stores/index.ts**

Add:
```typescript
export { useCardStore } from './card-store';
```

- [ ] **Step 3: Verify TypeScript compiles**

Run: `cd src && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add src/renderer/stores/card-store.ts src/renderer/stores/index.ts
git commit -m "feat(2A.3): add unified CardStore with type-filtered accessors"
```

**Note:** The card store currently reads containers via `window.uai.folders.list()` which returns `FolderStoreData`. When groups are added, either update this IPC to return `ContainerStoreData` or add a `window.uai.containers.list()` channel. For now, the folder-only path is sufficient since groups are not yet implemented.

---

## Task 7: Generic Card Rendering Components

**Files:**
- Create: `src/renderer/components/cards/BaseCardView.tsx`
- Create: `src/renderer/components/cards/CardRenderer.tsx`
- Create: `src/renderer/components/cards/SessionCardVisual.tsx`
- Create: `src/renderer/components/cards/BriefCardVisual.tsx`
- Create: `src/renderer/components/cards/FolderCardVisual.tsx`
- Create: `src/renderer/components/cards/CardListView.tsx`
- Create: `src/renderer/components/cards/ContainerTreeView.tsx`
- Create: `src/renderer/components/cards/index.ts`

Due to the size of this task, it is split into sub-steps per file.

- [ ] **Step 1: Create BaseCardView.tsx**

```tsx
/**
 * BaseCardView — renders any card with platform bar, name, status dot, metadata.
 *
 * This is the universal card chrome. Type-specific content is passed as children.
 */

import type { BaseCard } from '../../../shared/cards';

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange, #ff9e64)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-blue)',
};

interface BaseCardViewProps {
  card: BaseCard;
  active?: boolean;
  selected?: boolean;
  onClick?: (e?: React.MouseEvent) => void;
  onContextMenu?: (e: React.MouseEvent) => void;
  platformColor?: string;
  statusColor?: string;
  children?: React.ReactNode;
}

export default function BaseCardView({
  card, active, selected, onClick, onContextMenu,
  platformColor, statusColor, children,
}: BaseCardViewProps): JSX.Element {
  return (
    <div
      className={`session-card${active ? ' active' : ''}${selected ? ' selected' : ''}`}
      onClick={(e) => onClick?.(e)}
      onContextMenu={onContextMenu}
    >
      {platformColor && <div className="card-platform-bar" style={{ backgroundColor: platformColor }} />}
      <div className="card-content">
        <div className="card-header">
          <span className="card-name">{card.display_name}</span>
          {statusColor && <span className="card-status-dot" style={{ backgroundColor: statusColor }} />}
        </div>
        {children}
      </div>
    </div>
  );
}
```

- [ ] **Step 2: Create SessionCardVisual.tsx**

```tsx
/**
 * SessionCardVisual — session-specific card rendering.
 *
 * Shows status, context %, roles, time, platform.
 */

import type { SessionCard } from '../../../shared/cards';

function formatTime(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  } catch { return ''; }
}

interface SessionCardVisualProps {
  card: SessionCard;
}

export default function SessionCardVisual({ card }: SessionCardVisualProps): JSX.Element {
  return (
    <div className="card-meta">
      <span className="card-time">{formatTime(card.last_activity)}</span>
      {card.roles && card.roles.length > 0 && <span className="card-role">{card.roles[0]}</span>}
      {card.context_percent != null && card.context_percent > 0 && (
        <span className="card-ctx">ctx:{card.context_percent}%</span>
      )}
      {card.identity_status && card.identity_status !== 'confirmed' && (
        <span className="card-badge draft">{card.identity_status}</span>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Create BriefCardVisual.tsx**

```tsx
/**
 * BriefCardVisual — brief-specific card rendering.
 */

import type { BriefCard } from '../../../shared/cards';

interface BriefCardVisualProps {
  card: BriefCard;
}

export default function BriefCardVisual({ card }: BriefCardVisualProps): JSX.Element {
  return (
    <div className="card-meta">
      {card.description && <span className="card-description">{card.description}</span>}
      {card.file_size != null && (
        <span className="card-size">{Math.round(card.file_size / 1024)}KB</span>
      )}
      <span className={`card-badge ${card.status}`}>{card.status}</span>
    </div>
  );
}
```

- [ ] **Step 4: Create FolderCardVisual.tsx**

```tsx
/**
 * FolderCardVisual — folder/group-specific card rendering.
 */

import type { FolderCard, GroupCard } from '../../../shared/cards';

interface FolderCardVisualProps {
  card: FolderCard | GroupCard;
}

export default function FolderCardVisual({ card }: FolderCardVisualProps): JSX.Element {
  const itemCount = card.container.children.length;
  const subCount = card.container.sub_containers.length;

  return (
    <div className="card-meta">
      <span className="card-count">{itemCount} items</span>
      {subCount > 0 && <span className="card-count">{subCount} sub</span>}
      {card.entity_type === 'group' && <span className="card-badge">group</span>}
    </div>
  );
}
```

- [ ] **Step 5: Create CardRenderer.tsx**

```tsx
/**
 * CardRenderer — discriminated union dispatch to type-specific visuals.
 *
 * Given any BaseCard, selects the right visual component based on entity_type.
 */

import type { AnyCard } from '../../../shared/cards';
import { isSessionCard, isBriefCard, isFolderCard, isGroupCard } from '../../../shared/cards';
import BaseCardView from './BaseCardView';
import SessionCardVisual from './SessionCardVisual';
import BriefCardVisual from './BriefCardVisual';
import FolderCardVisual from './FolderCardVisual';

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange, #ff9e64)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-blue)',
};

const STATUS_COLORS: Record<string, string> = {
  running: 'var(--accent-green)',
  stopped: 'var(--text-muted)',
  exited: 'var(--text-muted)',
};

interface CardRendererProps {
  card: AnyCard;
  active?: boolean;
  selected?: boolean;
  onClick?: (e?: React.MouseEvent) => void;
  onContextMenu?: (e: React.MouseEvent) => void;
}

export default function CardRenderer({
  card, active, selected, onClick, onContextMenu,
}: CardRendererProps): JSX.Element {
  let platformColor: string | undefined;
  let statusColor: string | undefined;

  if (isSessionCard(card)) {
    platformColor = PLATFORM_COLORS[card.platform];
    statusColor = STATUS_COLORS[card.process_status];
  }

  return (
    <BaseCardView
      card={card}
      active={active}
      selected={selected}
      onClick={onClick}
      onContextMenu={onContextMenu}
      platformColor={platformColor}
      statusColor={statusColor}
    >
      {isSessionCard(card) && <SessionCardVisual card={card} />}
      {isBriefCard(card) && <BriefCardVisual card={card} />}
      {(isFolderCard(card) || isGroupCard(card)) && <FolderCardVisual card={card} />}
    </BaseCardView>
  );
}
```

- [ ] **Step 6: Create CardListView.tsx**

```tsx
/**
 * CardListView — generic sortable, filterable, multi-selectable card list.
 *
 * Works with BaseCard. Does NOT know about sessions or briefs.
 * Type-specific rendering is handled by CardRenderer.
 */

import type { AnyCard } from '../../../shared/cards';
import CardRenderer from './CardRenderer';

interface CardListViewProps {
  cards: AnyCard[];
  activeCardId?: string;
  selectedIds?: Set<string>;
  onCardClick?: (card: AnyCard) => void;
  onCardSelect?: (card: AnyCard) => void;
  onCardContextMenu?: (card: AnyCard, e: React.MouseEvent) => void;
  emptyMessage?: string;
}

export default function CardListView({
  cards, activeCardId, selectedIds, onCardClick, onCardSelect,
  onCardContextMenu, emptyMessage = 'No items found.',
}: CardListViewProps): JSX.Element {
  if (cards.length === 0) {
    return <div className="session-list-empty">{emptyMessage}</div>;
  }

  return (
    <div className="card-list-view">
      {cards.map(card => (
        <CardRenderer
          key={card.entity_id}
          card={card}
          active={card.entity_id === activeCardId}
          selected={selectedIds?.has(card.entity_id)}
          onClick={(e?: React.MouseEvent) => {
            if (e && (e.metaKey || e.ctrlKey)) {
              onCardSelect?.(card);
            } else {
              onCardClick?.(card);
            }
          }}
          onContextMenu={(e) => onCardContextMenu?.(card, e)}
        />
      ))}
    </div>
  );
}
```

- [ ] **Step 7: Create ContainerTreeView.tsx**

```tsx
/**
 * ContainerTreeView — generic collapsible tree with container navigation.
 *
 * Shows sub-containers as collapsible nodes and cards as leaves.
 * Works with any container type (folders, groups).
 */

import { useState, useCallback } from 'react';
import type { AnyCard } from '../../../shared/cards';
import type { ContainerEntry } from '../../../shared/cards';
import CardListView from './CardListView';

interface ContainerTreeViewProps {
  container: ContainerEntry;
  allContainers: Record<string, ContainerEntry>;
  getCardsForIds: (cardIds: string[]) => AnyCard[];
  activeCardId?: string;
  selectedIds?: Set<string>;
  onCardClick?: (card: AnyCard) => void;
  onCardSelect?: (card: AnyCard) => void;
  onCardContextMenu?: (card: AnyCard, e: React.MouseEvent) => void;
  onContainerClick?: (containerId: string) => void;
  depth?: number;
}

export default function ContainerTreeView({
  container, allContainers, getCardsForIds,
  activeCardId, selectedIds,
  onCardClick, onCardSelect, onCardContextMenu,
  onContainerClick, depth = 0,
}: ContainerTreeViewProps): JSX.Element {
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());

  const toggleCollapse = useCallback((id: string) => {
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const cards = getCardsForIds(container.cards);

  return (
    <div className="container-tree-view" style={{ paddingLeft: depth > 0 ? 12 : 0 }}>
      {/* Sub-containers */}
      {container.sub_containers.map(childId => {
        const child = allContainers[childId];
        if (!child) return null;
        const isCollapsed = collapsed.has(childId);

        return (
          <div key={childId} className="tree-node">
            <div
              className="tree-node-label"
              onClick={() => {
                if (onContainerClick) {
                  onContainerClick(childId);
                } else {
                  toggleCollapse(childId);
                }
              }}
            >
              <span className="tree-toggle">{isCollapsed ? '▶' : '▼'}</span>
              <span className="tree-folder-icon">📁</span>
              <span className="tree-name">{child.name}</span>
              <span className="tree-count">({child.cards.length})</span>
            </div>
            {!isCollapsed && (
              <ContainerTreeView
                container={child}
                allContainers={allContainers}
                getCardsForIds={getCardsForIds}
                activeCardId={activeCardId}
                selectedIds={selectedIds}
                onCardClick={onCardClick}
                onCardSelect={onCardSelect}
                onCardContextMenu={onCardContextMenu}
                onContainerClick={onContainerClick}
                depth={depth + 1}
              />
            )}
          </div>
        );
      })}

      {/* Cards at this level */}
      <CardListView
        cards={cards}
        activeCardId={activeCardId}
        selectedIds={selectedIds}
        onCardClick={onCardClick}
        onCardSelect={onCardSelect}
        onCardContextMenu={onCardContextMenu}
      />
    </div>
  );
}
```

- [ ] **Step 8: Create index.ts barrel export**

```typescript
export { default as BaseCardView } from './BaseCardView';
export { default as CardRenderer } from './CardRenderer';
export { default as CardListView } from './CardListView';
export { default as ContainerTreeView } from './ContainerTreeView';
export { default as SessionCardVisual } from './SessionCardVisual';
export { default as BriefCardVisual } from './BriefCardVisual';
export { default as FolderCardVisual } from './FolderCardVisual';
```

- [ ] **Step 9: Update src/renderer/components/index.ts**

Add:
```typescript
export * from './cards';
```

- [ ] **Step 10: Verify TypeScript compiles**

Run: `cd src && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 11: Commit**

```bash
git add src/renderer/components/cards/
git commit -m "feat(2A.4): add generic card rendering components"
```

---

## Task 8: Update Navigator to Use Generic Components

**Files:**
- Modify: `src/renderer/components/Navigator.tsx`

- [ ] **Step 1: Refactor Navigator sessions tab to use CardListView**

Replace the inline `SessionCard` component and the `renderCard` function in Navigator.tsx with imports from the cards module. The `SessionCard` function component defined inline in Navigator.tsx should be removed. Instead, the sessions tab uses `CardListView` with the session cards from `useCardStore()`.

Key changes:
- Import `CardListView` from `./cards`
- Import `useCardStore` from `../stores`
- Replace the inline `SessionCard` component usage with `CardListView`
- Keep `FilterToolbar`, `ContextMenu`, rename inline, and create session functionality
- The Active/Stopped section grouping moves into the tab render using two `CardListView` instances

```tsx
// In the sessions tab section, replace:
// {active.map(renderCard)}
// with:
<CardListView
  cards={activeCards}
  activeCardId={activeSessionId ? `session:${activeSessionId}` : undefined}
  selectedIds={context.selection}
  onCardClick={(card) => { clearSelection(); onSelectSession(card.entity_id.split(':')[1]); }}
  onCardSelect={(card) => toggleSelect(card.entity_id)}
  onCardContextMenu={(card, e) => handleContextMenu(e, card.entity_id.split(':')[1])}
/>
```

Where `activeCards` and `stoppedCards` are derived from `useCardStore().sessions` with the same filter/sort logic.

- [ ] **Step 2: Verify the app still compiles**

Run: `cd src && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/renderer/components/Navigator.tsx
git commit -m "refactor(2A.6): Navigator sessions tab uses CardListView"
```

---

## Task 9: Update Component Descriptions

**Files:**
- Modify: `src/shared/component-descriptions.ts`

- [ ] **Step 1: Add card_list and container_tree component descriptions**

Add `CARD_LIST_VIEW` and `CONTAINER_TREE_VIEW` descriptions following the existing pattern, and register them in `registerInitialComponents()`.

- [ ] **Step 2: Verify compile**

Run: `cd src && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Commit**

```bash
git add src/shared/component-descriptions.ts
git commit -m "feat(2A.6): register CardListView and ContainerTreeView component descriptions"
```

---

## Task 10: Final Validation

- [ ] **Step 1: Run all tests**

Run: `cd src && npx vitest run`
Expected: All tests pass (existing + new contract tests)

- [ ] **Step 2: Verify TypeScript compiles**

Run: `cd src && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 3: Review file structure**

Verify these files exist:
```
architecture/contracts/cards.ts
src/shared/cards.ts
src/main/container-manager.ts
src/renderer/stores/card-store.ts
src/renderer/components/cards/BaseCardView.tsx
src/renderer/components/cards/CardRenderer.tsx
src/renderer/components/cards/CardListView.tsx
src/renderer/components/cards/ContainerTreeView.tsx
src/renderer/components/cards/SessionCardVisual.tsx
src/renderer/components/cards/BriefCardVisual.tsx
src/renderer/components/cards/FolderCardVisual.tsx
src/renderer/components/cards/index.ts
src/tests/contract-cards.test.ts
src/tests/contract-container-manager.test.ts
```

- [ ] **Step 4: Final commit if any stragglers**

```bash
git add -A
git status  # verify nothing unexpected
git commit -m "chore(2A): final cleanup for card/container abstraction refactor"
```

- [ ] **Step 5: Notify Continuity II**

Send a prompt to session `20260422_204104_640a7e0c_cla` confirming completion with a summary of what was refactored and what abstractions are now available.

---

## Summary of Abstractions for Phase 2 Consumers

After this refactor, adding a new entity type (e.g., `GroupCard`) requires:

1. **Define the card type** — extend `BaseCard` in `architecture/contracts/cards.ts`
2. **Add to AnyCard union** — discriminated by `entity_type`
3. **Add a visual component** — `GroupCardVisual.tsx` in `cards/`
4. **Register in CardRenderer** — one line type guard + visual
5. **Container operations** — `createContainer('group', ...)` just works
6. **Navigator tab** — `CardListView` + `ContainerTreeView` with type filter

No duplication of container logic, card rendering, or store management.
