/**
 * FolderManager — thin wrapper over ContainerManager.
 *
 * Preserves the existing folder API but delegates all logic to the
 * generic ContainerManager. Folders are containers with exclusive placement.
 *
 * Workstream 2A: Backward compatibility layer.
 */

import type { FolderStoreData, Folder } from '@uai/shared/types';
import {
  loadContainers, createContainer as genericCreate,
  renameContainer, deleteContainer as genericDelete,
  addCardToContainer, removeCardFromContainer,
  moveCard as genericMoveCard, moveContainer,
  reorderContainerChildren, reorderContainerCards,
  validateContainerTree, getContainerSnapshot,
} from './container-manager';
import type { ContainerStoreData } from '@uai/shared/cards';

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
      cards: entry.cards as any[],
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
