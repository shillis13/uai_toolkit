/**
 * AppStateStore — renderer-side shared app state store.
 *
 * Holds UI state that persists across app restarts: tabs, panel sizes,
 * pinned sessions, notes, lastViewedAt, card display preferences.
 *
 * Backed by app_state.json via main process IPC.
 * Same subscription model as SessionStore.
 */

import { useState, useEffect } from 'react';
import type { AppState, Tab, TabType } from '@uai/shared/types';
import type { StoreChangedEvent } from '@uai/shared/types';
import { markSessionViewed, setActiveSession } from './session-activity';
import { getSession } from './session-store';

// ─── Defaults ─────────────────────────────────────────────────────────────

const DEFAULT_APP_STATE: AppState = {
  tabs: [],
  activeTabId: null,
  panelSizes: {
    navigatorWidth: 280,
    contextPanelWidth: 300,
    bottomPanelHeight: 200,
    workMgrListWidth: 300,
    sessionStoreListWidth: 320,
    contextMgrCatalogWidth: 360,
    sessionWorkListWidth: 260,
  },
  navigatorTab: 'sessions',
  contextPanelOpen: false,
  bottomPanelOpen: false,
  sessionPrefs: {},
  promptBoxConfig: {
    autoSubmit: true,
    quickNudges: [
      { label: 'Proceed', text: 'proceed' },
      { label: 'Continue', text: 'continue' },
      { label: 'Yes', text: 'yes' },
      { label: 'Commit', text: 'commit and push' },
    ],
    quickNudgeColumns: 1,
    quickNudgesCollapsed: false,
  },
};

// ─── Singleton state ──────────────────────────────────────────────────────

let appState: AppState = { ...DEFAULT_APP_STATE };
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

export async function bootstrap(snapshot?: Partial<AppState>): Promise<void> {
  if (bootstrapping) return;
  bootstrapping = true;
  if (snapshot) {
    appState = { ...DEFAULT_APP_STATE, ...snapshot };
  } else {
    try {
      const loaded = await window.uai.appState.get();
      appState = { ...DEFAULT_APP_STATE, ...loaded };
    } catch {
      appState = { ...DEFAULT_APP_STATE };
    }
  }
  initialized = true;
  syncActiveSession();
  notify();
}

async function refresh(): Promise<void> {
  try {
    const loaded = await window.uai.appState.get();
    appState = { ...DEFAULT_APP_STATE, ...loaded };
    syncActiveSession();
    notify();
  } catch {
    // Keep current state on refresh failure
  }
}

// ─── Imperative API ───────────────────────────────────────────────────────

export function getAppState(): Readonly<AppState> {
  return appState;
}

export function isInitialized(): boolean {
  return initialized;
}

/**
 * Update app state locally and persist to main process.
 * Applies a partial update (shallow merge).
 */
export async function updateAppState(patch: Partial<AppState>): Promise<void> {
  appState = { ...appState, ...patch };
  notify();
  // Persist to main process
  try {
    await window.uai.appState.update(patch);
  } catch (err) {
    console.error('[AppStateStore] Failed to persist:', err);
  }
}

// ─── Tab Management Helpers ───────────────────────────────────────────────

/** Resolve the focused session from the active tab and update activity tracking.
 *  Keeps the focused session's unread-reply count clear while its tab is active. */
function syncActiveSession(): void {
  const tab = appState.tabs.find(t => t.id === appState.activeTabId);
  setActiveSession(tab && tab.type === 'session' ? tab.targetId : null);
}

export function openTab(targetId: string, label: string, type: TabType = 'session'): string {
  // Visiting a session marks it VIEWED (clears the unread indicator) but does NOT
  // count as activity — only typing/clicking in the workspace bumps "activity".
  if (type === 'session') {
    markSessionViewed(targetId, getSession(targetId)?.exchange_count);
  }
  const existing = appState.tabs.find(t => t.targetId === targetId && t.type === type);
  if (existing) {
    updateAppState({ activeTabId: existing.id });
    syncActiveSession();
    return existing.id;
  }

  const tab: Tab = {
    id: `tab_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
    type,
    label,
    targetId,
    openedAt: new Date().toISOString(),
  };

  updateAppState({
    tabs: [...appState.tabs, tab],
    activeTabId: tab.id,
  });
  syncActiveSession();

  return tab.id;
}

export function closeTab(tabId: string): void {
  const tabs = appState.tabs.filter(t => t.id !== tabId);
  const activeTabId = appState.activeTabId === tabId
    ? (tabs.length > 0 ? tabs[tabs.length - 1].id : null)
    : appState.activeTabId;

  updateAppState({ tabs, activeTabId });
  syncActiveSession();
}

export function activateTab(tabId: string): void {
  const tab = appState.tabs.find(t => t.id === tabId);
  // Switching to a session marks it VIEWED (clears unread) but is NOT activity.
  if (tab && tab.type === 'session') {
    markSessionViewed(tab.targetId, getSession(tab.targetId)?.exchange_count);
  }
  updateAppState({ activeTabId: tabId });
  syncActiveSession();
}

// ─── Path 2: Store change subscription ────────────────────────────────────

let unsubStoreChanged: (() => void) | null = null;

function startListening(): void {
  if (unsubStoreChanged) return;
  unsubStoreChanged = window.uai.onStoreChanged((event: StoreChangedEvent) => {
    if (event.changed.includes('appState')) {
      refresh();
    }
  });
}

// ─── React Hook ───────────────────────────────────────────────────────────

export function useAppStateStore(): {
  appState: AppState;
  initialized: boolean;
  updateAppState: (patch: Partial<AppState>) => Promise<void>;
  openTab: (targetId: string, label: string, type?: TabType) => string;
  closeTab: (tabId: string) => void;
  activateTab: (tabId: string) => void;
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

  return {
    appState,
    initialized,
    updateAppState,
    openTab,
    closeTab,
    activateTab,
  };
}
