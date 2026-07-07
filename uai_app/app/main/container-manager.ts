/**
 * ContainerManager — generic container persistence and CRUD.
 *
 * Workstream 2A: Card/Container Base Abstractions
 *
 * Generalizes folder-manager.ts to support any container type.
 * Two placement rules:
 *   - exclusive: a card can be in exactly one container (folders)
 *
 * Owns containers.json with atomic read-modify-write.
 * All mutations go through the command bus (see command-handlers.ts).
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import type { ContainerStoreData, ContainerEntry, PlacementRule } from '@uai/shared/cards';

// ─── Path ────────────────────────────────────────────────────────────────

function getAiRootMain(): string {
  return process.env.AI_ROOT_MAIN || path.join(os.homedir(), 'AI/ai_root');
}

function getContainersPath(): string {
  // UAI_CONTAINERS_PATH isolates folder writes (and the sibling containers.changed
  // signal, which derives from this path's dirname) for a test instance, so its
  // folder mutations never touch the user's shared containers.json. Seed it with a
  // copy of the real 4 KB containers.json if the test needs the existing folders.
  if (process.env.UAI_CONTAINERS_PATH) return process.env.UAI_CONTAINERS_PATH;
  return path.join(getAiRootMain(), 'ai_general', 'data', 'containers.json');
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

  // Try containers.json first
  try {
    const content = fs.readFileSync(containersPath, 'utf-8');
    const data = JSON.parse(content) as ContainerStoreData;
    dropGroupContainers(data);
    return data;
  } catch (err: unknown) {
    const isNotFound = (err as NodeJS.ErrnoException).code === 'ENOENT';
    if (!isNotFound) {
      // File exists but is corrupt — fail closed, do not overwrite
      throw new Error(`containers.json is corrupt and cannot be parsed. Manual repair needed: ${containersPath}`);
    }
  }

  // containers.json doesn't exist — try migrating from folders.json
  const foldersPath = containersPath.replace('containers.json', 'folders.json');
  try {
    const foldersContent = fs.readFileSync(foldersPath, 'utf-8');
    const foldersData = JSON.parse(foldersContent);
    const migrated = migrateFoldersToContainers(foldersData);
    dropGroupContainers(migrated);
    return migrated;
  } catch (err: unknown) {
    const isNotFound = (err as NodeJS.ErrnoException).code === 'ENOENT';
    if (!isNotFound) {
      throw new Error(`folders.json is corrupt and cannot be parsed. Manual repair needed: ${foldersPath}`);
    }
  }

  // Neither file exists — fresh install
  return structuredClone(DEFAULT_STORE);
}

function dropGroupContainers(data: ContainerStoreData): void {
  // Migration: drop group containers
  for (const [id, container] of Object.entries(data.containers || {})) {
    if ((container as any).type === 'group' || container.container_type === 'group') {
      console.warn(`[migration] Dropping group container "${container.name}" (${container.sub_containers.length} sub-containers, ${container.cards.length} members)`);
      delete data.containers[id];
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
    throw new Error(`Data directory does not exist: ${dir}. Create it before writing.`);
  }
  store.revision++;
  const tmpPath = `${filePath}.tmp.${process.pid}`;
  fs.writeFileSync(tmpPath, JSON.stringify(store, null, 2));
  fs.renameSync(tmpPath, filePath);

  // Touch signal file so watchers (including other UAI instances) detect the change
  const signalPath = path.join(dir, 'containers.changed');
  fs.writeFileSync(signalPath, String(Date.now()));
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
};

// ─── Helpers ─────────────────────────────────────────────────────────────

function cardRootType(cardId: string): string | null {
  if (cardId.startsWith('session:')) return 'sessions';
  if (cardId.startsWith('brief:')) return 'briefs';
  if (cardId.startsWith('project:')) return 'sessions';  // projects go in entities root
  return null;
}

function validateCardRootConstraint(cardId: string, containerId: string, store: ContainerStoreData): void {
  const rootType = cardRootType(cardId);
  if (!rootType) return;
  const rootId = store.roots[rootType];
  if (rootId && !isUnderRoot(containerId, rootId, store)) {
    throw new Error(`${rootType.slice(0, -1)} cards can only be in the ${rootType} container tree`);
  }
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
  type: 'folder',
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

    // Non-exclusive containers: just drop the container and its membership.
    // Cards stay wherever else they are — no reparenting needed.
    if (container.placement_rule === 'non-exclusive') {
      // Reparent sub-containers to parent
      for (const childId of container.sub_containers) {
        parent.sub_containers.push(childId);
      }
      // Cards are NOT moved — they remain in their other containers
      parent.sub_containers = parent.sub_containers.filter(id => id !== containerId);
      delete s.containers[containerId];
      return;
    }

    // Exclusive containers (folders): reparent or cascade
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
      validateCardRootConstraint(cardId, containerId, s);
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

    // Enforce root-tree constraint on target
    if (to.placement_rule === 'exclusive') {
      validateCardRootConstraint(cardId, toContainerId, s);
    }

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

    // Enforce root-tree constraint: all cards in the subtree must be compatible with the target root
    const allContainerIds = [containerId, ...descendants];
    for (const cid of allContainerIds) {
      const c = s.containers[cid];
      if (!c || c.placement_rule !== 'exclusive') continue;
      for (const cardId of c.cards) {
        validateCardRootConstraint(cardId, targetParentId, s);
      }
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
