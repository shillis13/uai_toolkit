/**
 * SessionStore — renderer-side shared store.
 *
 * Holds a snapshot of sessions from the main process.
 * Updates via two paths:
 *   Path 1: Command result snapshots apply immediately
 *   Path 2: StoreChanged events trigger refresh from main
 *
 * All components read from this store. No component fetches sessions independently.
 */

import { useState, useEffect, useCallback } from 'react';
import type { Session, StoreChangedEvent } from '../../shared/types';

// ─── Singleton state (shared across all useSessionStore consumers) ──────────

let sessions: Session[] = [];
let aiRoot: string = '';
let initialized = false;
const listeners = new Set<() => void>();

function notify(): void {
  for (const listener of listeners) {
    listener();
  }
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

// ─── Bootstrap and refresh ─────────────────────────────────────────────────

async function bootstrap(): Promise<void> {
  const snapshot = await window.uai.bootstrap();
  sessions = snapshot.sessions;
  aiRoot = snapshot.aiRoot || '';
  initialized = true;
  notify();
}

async function refresh(): Promise<void> {
  const list = await window.uai.sessions.list();
  sessions = list;
  notify();
}

// ─── Path 2: Subscribe to store change events from main ────────────────────

let unsubStoreChanged: (() => void) | null = null;

function startListening(): void {
  if (unsubStoreChanged) return;
  unsubStoreChanged = window.uai.onStoreChanged((event: StoreChangedEvent) => {
    if (event.changed.includes('sessions')) {
      refresh();
    }
  });
}

// ─── React Hook ────────────────────────────────────────────────────────────

export function useSessionStore(): {
  sessions: Session[];
  initialized: boolean;
  aiRoot: string;
  refresh: () => Promise<void>;
  getSession: (trackingId: string) => Session | undefined;
} {
  const [, forceUpdate] = useState(0);

  useEffect(() => {
    // Bootstrap on first mount
    if (!initialized) {
      bootstrap();
      startListening();
    }
    // Subscribe to store changes for re-render
    const unsub = subscribe(() => forceUpdate(n => n + 1));
    return unsub;
  }, []);

  const getSession = useCallback((trackingId: string): Session | undefined => {
    return sessions.find(s => s.tracking_id === trackingId);
  }, []);

  return {
    sessions,
    initialized,
    aiRoot,
    refresh,
    getSession,
  };
}
