/**
 * FolderStore — renderer-side shared folder store.
 *
 * Workstream 1C: Organization Entities
 *
 * Reads folders.json via main process IPC. Holds folder tree for navigator.
 * Same subscription model as SessionStore. Provides derived selectors for
 * folder path, breadcrumbs, card location, and descendant queries.
 */

import { useState, useEffect } from 'react';
import type { Folder, FolderStoreData } from '@uai/shared/types';
import type { StoreChangedEvent } from '@uai/shared/types';

// ─── Defaults ─────────────────────────────────────────────────────────────

const DEFAULT_STORE_DATA: FolderStoreData = {
  schema_version: 1,
  revision: 0,
  roots: {
    sessions: 'all_sessions',
    briefs: 'all_briefs',
  },
  folders: {
    all_sessions: {
      id: 'all_sessions',
      name: 'All Entities',
      icon: null,
      color: null,
      builtin: true,
      subfolders: [],
      cards: [],
    },
    all_briefs: {
      id: 'all_briefs',
      name: 'All Briefs',
      icon: null,
      color: null,
      builtin: true,
      subfolders: [],
      cards: [],
    },
  },
};

// ─── Singleton state ──────────────────────────────────────────────────────

let storeData: FolderStoreData = { ...DEFAULT_STORE_DATA };
let initialized = false;
let bootstrapping = false;
const listeners = new Set<() => void>();

// Reverse indexes (rebuilt on every store update)
let cardToFolder = new Map<string, string>();
let folderToParent = new Map<string, string>();

function rebuildIndexes(): void {
  cardToFolder = new Map();
  folderToParent = new Map();
  for (const folder of Object.values(storeData.folders)) {
    for (const cardId of folder.cards) {
      cardToFolder.set(cardId, folder.id);
    }
    for (const childId of folder.subfolders) {
      folderToParent.set(childId, folder.id);
    }
  }
}

function notify(): void {
  for (const listener of listeners) {
    listener();
  }
}

export function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// ─── Bootstrap and refresh ────────────────────────────────────────────────

export async function bootstrap(snapshot?: FolderStoreData): Promise<void> {
  if (bootstrapping && !snapshot) return;
  bootstrapping = true;
  if (snapshot) {
    storeData = snapshot;
  } else {
    try {
      const loaded = await window.uai.folders.list();
      storeData = loaded || DEFAULT_STORE_DATA;
    } catch {
      storeData = { ...DEFAULT_STORE_DATA };
    }
  }
  rebuildIndexes();
  initialized = true;
  notify();
}

async function refresh(): Promise<void> {
  try {
    const loaded = await window.uai.folders.list();
    storeData = loaded || DEFAULT_STORE_DATA;
    rebuildIndexes();
    notify();
  } catch {
    // Keep current state on refresh failure
  }
}

/**
 * Apply a snapshot directly (e.g. from command result) without round-trip.
 */
export function applySnapshot(snapshot: FolderStoreData): void {
  if (snapshot.revision <= storeData.revision) return; // stale
  storeData = snapshot;
  rebuildIndexes();
  notify();
}

// ─── Imperative API ───────────────────────────────────────────────────────

export function getFolderStore(): Readonly<FolderStoreData> {
  return storeData;
}

export function getFolder(id: string): Folder | undefined {
  return storeData.folders[id];
}

export function getRootId(tab: 'sessions' | 'briefs'): string {
  return storeData.roots[tab];
}

export function isInitialized(): boolean {
  return initialized;
}

// ─── Derived Selectors ───────────────────────────────────────────────────

/**
 * Which folder contains this card? Returns folder ID or null.
 */
export function cardLocation(cardId: string): string | null {
  return cardToFolder.get(cardId) || null;
}

/**
 * Parent folder of a folder. Returns folder ID or null (for roots).
 */
export function parentFolder(folderId: string): string | null {
  return folderToParent.get(folderId) || null;
}

/**
 * Path from root to folder as array of folder IDs.
 */
export function folderPath(folderId: string): string[] {
  const path: string[] = [];
  let current: string | null = folderId;
  const visited = new Set<string>();
  while (current && !visited.has(current)) {
    visited.add(current);
    path.unshift(current);
    current = folderToParent.get(current) || null;
  }
  return path;
}

/**
 * Breadcrumb segments for a folder: array of { id, name }.
 */
export function breadcrumbSegments(folderId: string): Array<{ id: string; name: string }> {
  const ids = folderPath(folderId);
  return ids.map(id => {
    const folder = storeData.folders[id];
    return { id, name: folder?.name || id };
  });
}

/**
 * All card IDs recursively under a folder (including subfolders).
 */
export function descendantCards(folderId: string): string[] {
  const result: string[] = [];
  const queue = [folderId];
  while (queue.length > 0) {
    const current = queue.shift()!;
    const folder = storeData.folders[current];
    if (!folder) continue;
    result.push(...folder.cards);
    queue.push(...folder.subfolders);
  }
  return result;
}

/**
 * Can navigate up from this folder? (false for roots)
 */
export function canGoUp(folderId: string): boolean {
  return folderId !== storeData.roots.sessions && folderId !== storeData.roots.briefs;
}

// ─── Path 2: Store change subscription ────────────────────────────────────

let unsubStoreChanged: (() => void) | null = null;

function startListening(): void {
  if (unsubStoreChanged) return;
  unsubStoreChanged = window.uai.onStoreChanged((event: StoreChangedEvent) => {
    if (event.changed.includes('folders')) {
      // If event includes a folder snapshot, apply directly
      if (event.snapshots?.folders) {
        applySnapshot(event.snapshots.folders as FolderStoreData);
      } else {
        refresh();
      }
    }
  });
}

// ─── React Hook ───────────────────────────────────────────────────────────

export function useFolderStore() {
  const [, forceUpdate] = useState(0);

  useEffect(() => {
    if (!initialized && !bootstrapping) {
      bootstrap();
      startListening();
    }
    const unsub = subscribe(() => forceUpdate(n => n + 1));
    return unsub;
  }, []);

  return {
    storeData,
    initialized,
    getFolder,
    getRootId,
    refresh,
    // Derived selectors
    cardLocation,
    parentFolder,
    folderPath,
    breadcrumbSegments,
    descendantCards,
    canGoUp,
    applySnapshot,
  };
}
