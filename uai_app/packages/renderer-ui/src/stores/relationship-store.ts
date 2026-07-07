/**
 * RelationshipStore — renderer-side entity relationship store.
 *
 * Workstream 1C: Organization Entities
 *
 * Manages entity relationships (forked_from, briefed_to, etc.).
 * Relationships are stored in SQLite (entity_relationships table)
 * and queried on demand via main process IPC.
 *
 * Unlike SessionStore/FolderStore, this store loads relationships
 * lazily per entity rather than loading all at bootstrap.
 */

import { useState, useEffect, useCallback } from 'react';
import type { EntityRelationship, RelationType } from '@uai/shared/types';
import { INVERSE_RELATIONS } from '@uai/shared/types';

// ─── Singleton cache ──────────────────────────────────────────────────────

// Cache key: "entityType:entityId"
const cache = new Map<string, EntityRelationship[]>();
const listeners = new Set<() => void>();

function cacheKey(entityType: string, entityId: string): string {
  return `${entityType}:${entityId}`;
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

// ─── Query API ───────────────────────────────────────────────────────────

/**
 * Load relationships for an entity. Results are cached until invalidated.
 */
export async function loadRelationships(entityType: string, entityId: string): Promise<EntityRelationship[]> {
  const key = cacheKey(entityType, entityId);
  try {
    const rows = await window.uai.relationships.forEntity(entityType, entityId);
    const relationships = Array.isArray(rows) ? rows : [];
    cache.set(key, relationships);
    notify();
    return relationships;
  } catch {
    cache.set(key, []);
    notify();
    return [];
  }
}

/**
 * Get cached relationships for an entity (returns empty array if not loaded).
 */
export function getRelationships(entityType: string, entityId: string): ReadonlyArray<EntityRelationship> {
  return cache.get(cacheKey(entityType, entityId)) || [];
}

/**
 * Get relationships of a specific type for an entity.
 */
export function getRelationshipsByType(
  entityType: string,
  entityId: string,
  relationType: RelationType,
): EntityRelationship[] {
  const all = getRelationships(entityType, entityId);
  return all.filter(r => r.relation_type === relationType);
}

/**
 * Get the inverse label for a relationship type.
 */
export function inverseLabel(relationType: RelationType): string {
  return INVERSE_RELATIONS[relationType] || relationType;
}

/**
 * Invalidate cache for an entity (forces reload on next access).
 */
export function invalidate(entityType: string, entityId: string): void {
  cache.delete(cacheKey(entityType, entityId));
}

/**
 * Clear entire cache.
 */
export function clearCache(): void {
  cache.clear();
  notify();
}

// ─── Path 2: Store change subscription ────────────────────────────────────

let unsubStoreChanged: (() => void) | null = null;

function startListening(): void {
  if (unsubStoreChanged) return;
  unsubStoreChanged = window.uai.onStoreChanged((event) => {
    // Clear cache when relationships or sessions change
    if (event.changed.includes('relationships') || event.changed.includes('sessions')) {
      clearCache();
    }
  });
}

// ─── React Hook ───────────────────────────────────────────────────────────

/**
 * Hook to load and subscribe to relationships for a specific entity.
 * Triggers a load on mount and re-loads when the entity changes.
 */
export function useRelationships(entityType: string, entityId: string) {
  const [relationships, setRelationships] = useState<EntityRelationship[]>([]);
  const [loading, setLoading] = useState(true);

  const reload = useCallback(async () => {
    setLoading(true);
    const result = await loadRelationships(entityType, entityId);
    setRelationships(result);
    setLoading(false);
  }, [entityType, entityId]);

  useEffect(() => {
    startListening();
    reload();

    const unsub = subscribe(() => {
      const key = cacheKey(entityType, entityId);
      if (cache.has(key)) {
        // Cache populated — use it directly
        setRelationships([...cache.get(key)!]);
      } else if (entityId) {
        // Cache was cleared (e.g., by store change) — reload from main process
        reload();
      }
    });
    return unsub;
  }, [entityType, entityId, reload]);

  return {
    relationships,
    loading,
    reload,
    getByType: (type: RelationType) => relationships.filter(r => r.relation_type === type),
    inverseLabel,
  };
}
