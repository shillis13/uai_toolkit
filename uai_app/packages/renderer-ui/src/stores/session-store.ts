/**
 * SessionStore — renderer-side shared session store.
 *
 * Holds a snapshot of sessions from the main process.
 * Updates via two paths:
 *   Path 1: Command result snapshots apply immediately
 *   Path 2: StoreChanged events trigger refresh from main
 *
 * All components read from this store via useSessionStore().
 * No component fetches sessions independently.
 */

import { useState, useEffect, useCallback } from 'react';
import type { Session } from '@uai/shared/types';
import type { StoreChangedEvent } from '@uai/shared/types';

// ─── Singleton state ──────────────────────────────────────────────────────

let sessions: Session[] = [];
let aiRoot = '';
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

async function bootstrap(): Promise<void> {
  if (bootstrapping) return;
  bootstrapping = true;
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

// ─── Imperative API (for non-React consumers) ────────────────────────────

export function getSessions(): ReadonlyArray<Session> {
  return sessions;
}

export function getSession(trackingId: string): Session | undefined {
  return sessions.find(s => s.tracking_id === trackingId);
}

export function getAiRoot(): string {
  return aiRoot;
}

export function isInitialized(): boolean {
  return initialized;
}

// ─── Path 2: Store change subscription ────────────────────────────────────

let unsubStoreChanged: (() => void) | null = null;

function startListening(): void {
  if (unsubStoreChanged) return;
  unsubStoreChanged = window.uai.onStoreChanged((event: StoreChangedEvent) => {
    if (event.changed.includes('sessions') || event.changed.includes('appState')) {
      refresh();
    }
  });
}

// ─── React Hook ───────────────────────────────────────────────────────────

export function useSessionStore(): {
  sessions: Session[];
  initialized: boolean;
  aiRoot: string;
  refresh: () => Promise<void>;
  getSession: (trackingId: string) => Session | undefined;
} {
  const [, forceUpdate] = useState(0);

  useEffect(() => {
    if (!initialized && !bootstrapping) {
      bootstrap();
      startListening();
    }
    const unsub = subscribe(() => forceUpdate(n => n + 1));
    return unsub;
  }, []);

  const getSessionCb = useCallback((trackingId: string): Session | undefined => {
    return sessions.find(s => s.tracking_id === trackingId);
  }, []);

  return {
    sessions,
    initialized,
    aiRoot,
    refresh,
    getSession: getSessionCb,
  };
}
