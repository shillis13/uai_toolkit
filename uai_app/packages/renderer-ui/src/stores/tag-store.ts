/**
 * TagStore — renderer-side shared tag store.
 *
 * Workstream 1C: Organization Entities
 *
 * Manages tag definitions and card-tag associations. Tags are stored
 * in SQLite (card_tags table) and queried via main process IPC.
 * Same subscription model as SessionStore and FolderStore.
 */

import { useState, useEffect } from 'react';
import type { Tag, EntityType } from '@uai/shared/types';
import type { StoreChangedEvent } from '@uai/shared/types';

// ─── Singleton state ──────────────────────────────────────────────────────

let allTags: Tag[] = [];
let initialized = false;
let bootstrapping = false;
const listeners = new Set<() => void>();

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

export async function bootstrap(): Promise<void> {
  if (bootstrapping) return;
  bootstrapping = true;
  try {
    const tags = await window.uai.tags.list();
    allTags = Array.isArray(tags) ? tags : [];
  } catch {
    allTags = [];
  }
  initialized = true;
  notify();
}

async function refresh(): Promise<void> {
  try {
    const tags = await window.uai.tags.list();
    allTags = Array.isArray(tags) ? tags : [];
    notify();
  } catch {
    // Keep current state on refresh failure
  }
}

// ─── Imperative API ───────────────────────────────────────────────────────

export function getAllTags(): ReadonlyArray<Tag> {
  return allTags;
}

export function getTag(name: string): Tag | undefined {
  return allTags.find(t => t.name === name);
}

export function isInitialized(): boolean {
  return initialized;
}

/**
 * Check if a card has a specific tag.
 * Uses session.tags from the SessionStore (tags are included in the Session object).
 * This helper is for convenience when you only have a tag name.
 */
export function hasTag(sessionTags: string[], tagName: string): boolean {
  return sessionTags.includes(tagName);
}

/**
 * Filter tags by entity type (e.g., only tags applicable to sessions).
 */
export function tagsForEntityType(entityType: EntityType): Tag[] {
  return allTags.filter(t => t.entity_types.includes(entityType));
}

// ─── Path 2: Store change subscription ────────────────────────────────────

let unsubStoreChanged: (() => void) | null = null;

function startListening(): void {
  if (unsubStoreChanged) return;
  unsubStoreChanged = window.uai.onStoreChanged((event: StoreChangedEvent) => {
    // Refresh on tag changes or session changes (session.tags field)
    if (event.changed.includes('tags') || event.changed.includes('sessions')) {
      refresh();
    }
  });
}

// ─── React Hook ───────────────────────────────────────────────────────────

export function useTagStore() {
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
    tags: allTags,
    initialized,
    getTag,
    getAllTags,
    hasTag,
    tagsForEntityType,
    refresh,
  };
}
