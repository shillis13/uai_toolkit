/**
 * UAI App — Phase 1 Core UI
 *
 * Composes all architectural components:
 * - Navigator (left panel, tabbed session/brief lists)
 * - Workspace (center, tabbed terminal views + PromptBox)
 * - ContextPanel (right, collapsible session details)
 *
 * Wraps everything in ActionContextProvider for multi-select support.
 * Uses stores from 1A: SessionStore, AppStateStore, FolderStore.
 * All domain mutations route through the command bus.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { ErrorBoundary } from '@uai/renderer-ui';
import { useViewport } from '@uai/renderer-ui/viewport';
import { ActionContextProvider } from '@uai/renderer-ui/context';
import { ToastProvider } from '@uai/renderer-ui/components/Toast';
import { useAppStateStore, useSessionStore } from '@uai/renderer-ui/stores';
import { usePanelResize } from '@uai/renderer-ui/hooks/usePanelResize';
import Navigator from '@uai/renderer-ui/components/Navigator';
import Workspace from '@uai/renderer-ui/components/Workspace';
import BottomPanel from '@uai/renderer-ui/components/BottomPanel';
import SettingsPanel from '@uai/renderer-ui/components/SettingsPanel';
import { executeCommand } from '@uai/renderer-ui/utils/execute-command';
import { installCopyFlatten } from '@uai/renderer-ui/copyFlatten';
import type { AppearancePrefs, DeepLinkEvent } from '@uai/shared/types';

/** Apply appearance preferences to CSS custom properties on :root */
function applyAppearancePrefs(prefs: AppearancePrefs): void {
  const root = document.documentElement;
  if (prefs.fontUi) {
    root.style.setProperty('--font-ui', prefs.fontUi);
  } else {
    root.style.removeProperty('--font-ui');
  }
  if (prefs.fontMono) {
    root.style.setProperty('--font-mono', prefs.fontMono);
  } else {
    root.style.removeProperty('--font-mono');
  }
  if (prefs.fontSizeBase) {
    const base = prefs.fontSizeBase;
    root.style.setProperty('--size-xs', `${base - 2}px`);
    root.style.setProperty('--size-sm', `${base - 1}px`);
    root.style.setProperty('--size-base', `${base}px`);
    root.style.setProperty('--size-md', `${base + 1}px`);
    root.style.setProperty('--size-lg', `${base + 2}px`);
  }
}

export default function App(): JSX.Element {
  const { appState, updateAppState } = useAppStateStore();
  // Draggable width for the main left (Navigator) panel — drives the .app grid track.
  const navResize = usePanelResize('navigatorWidth', { def: 280, min: 200, max: () => Math.max(600, Math.round(window.innerWidth * 0.5)) });
  const { getSession } = useSessionStore();
  const [settingsVisible, setSettingsVisible] = useState(false);

  // Single-click: open/activate tab for session.
  // Double-click: also opens tab (same behavior — tabs.open deduplicates).
  // The single-click preview (workspace.tabs.update) caused terminal detach/reattach
  // issues and is disabled until terminal lifecycle is decoupled from tab content.
  const handleSelectSession = useCallback((trackingId: string, _opts?: { newTab?: boolean }) => {
    const session = getSession(trackingId);
    const label = session?.display_name || trackingId;
    executeCommand('workspace.tabs.open', {
      type: 'session',
      targetId: trackingId,
      label,
    });
  }, [getSession]);

  // Apply saved appearance preferences on mount
  useEffect(() => {
    if (appState.appearance) {
      applyAppearancePrefs(appState.appearance);
    }
  }, [appState.appearance]);

  // Flatten structured rows (log tabs, search results, …) to one line on copy, so a
  // copied error row doesn't paste as one-field-per-line. Opt-in via `data-copyrow`.
  useEffect(() => installCopyFlatten(), []);

  // Capture uncaught renderer errors → main process log (App Log + error log)
  useEffect(() => {
    const onError = (event: ErrorEvent) => {
      window.uai.logError?.({
        message: event.message || 'renderer error',
        stack: event.error?.stack,
        level: 'error',
      }).catch(() => { /* noop */ });
    };
    const onRejection = (event: PromiseRejectionEvent) => {
      const reason = event.reason;
      window.uai.logError?.({
        message: reason instanceof Error ? reason.message : String(reason),
        stack: reason instanceof Error ? reason.stack : undefined,
        level: 'error',
      }).catch(() => { /* noop */ });
    };
    window.addEventListener('error', onError);
    window.addEventListener('unhandledrejection', onRejection);
    return () => {
      window.removeEventListener('error', onError);
      window.removeEventListener('unhandledrejection', onRejection);
    };
  }, []);

  // Global keyboard shortcut: Cmd+, opens settings. Also listen for a
  // 'uai:open-settings' custom event so deep-tree buttons (e.g. the Navigator
  // header gear) can open Settings without prop-threading.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === ',') {
        e.preventDefault();
        setSettingsVisible((v) => !v);
      }
    };
    const openSettings = () => setSettingsVisible(true);
    window.addEventListener('keydown', handler);
    window.addEventListener('uai:open-settings', openSettings);
    return () => {
      window.removeEventListener('keydown', handler);
      window.removeEventListener('uai:open-settings', openSettings);
    };
  }, []);

  // ── Deep Link Navigation (uai:// protocol) ─────────────────────────
  useEffect(() => {
    const MANAGER_TO_TAB: Record<string, { type: string; targetId: string; label: string }> = {
      'context_mgr': { type: 'app', targetId: 'context-manager', label: 'Context Mgr' },
      'session_store': { type: 'app', targetId: 'session-store-manager', label: 'Session Store' },
      'todo_mgr': { type: 'app', targetId: 'todo-manager', label: 'Todos' },
      'task_mgr': { type: 'app', targetId: 'task-manager', label: 'Tasks' },
      'project_mgr': { type: 'app', targetId: 'context-manager', label: 'Context Mgr' },
    };

    const handleDeepLink = (event: DeepLinkEvent) => {
      const { manager, id } = event;

      if (manager === 'session') {
        const session = getSession(id);
        executeCommand('workspace.tabs.open', {
          type: 'session',
          targetId: id,
          label: session?.display_name || id,
        });
      } else if (manager === 'project') {
        // Find existing project tab by partial match (project_id may have prefix)
        const existingTab = appState.tabs.find(t =>
          t.type === 'project' && (
            t.targetId === id ||
            t.targetId.endsWith(`_${id}`) ||
            t.targetId.includes(id)
          )
        );
        if (existingTab) {
          executeCommand('workspace.tabs.activate', { tabId: existingTab.id });
        } else {
          executeCommand('workspace.tabs.open', {
            type: 'project',
            targetId: id,
            label: id,
          });
        }
      } else if (manager === 'game') {
        executeCommand('workspace.tabs.open', {
          type: 'app',
          targetId: `game:${id}`,
          label: `Game: ${id}`,
        });
      } else if (manager in MANAGER_TO_TAB) {
        const tabDef = MANAGER_TO_TAB[manager];
        executeCommand('workspace.tabs.open', {
          type: tabDef.type,
          targetId: tabDef.targetId,
          label: id ? `${tabDef.label}: ${id}` : tabDef.label,
          deepLinkId: id || undefined,
        });
      } else {
        // Unknown manager — try opening as a generic app tab
        executeCommand('workspace.tabs.open', {
          type: 'app',
          targetId: manager,
          label: id || manager,
        });
      }
    };

    return window.uai.onDeepLink(handleDeepLink);
  }, [getSession, appState.tabs]);

  // Global keyboard shortcut: Cmd+Shift+F opens search
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.shiftKey && e.key === 'f') {
        e.preventDefault();
        executeCommand('workspace.tabs.open', {
          type: 'search',
          targetId: '_global',
          label: 'Search',
        });
      }
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, []);

  // Save appearance preferences handler
  const handleSaveAppearance = useCallback((prefs: AppearancePrefs) => {
    applyAppearancePrefs(prefs);
    updateAppState({ appearance: prefs });
  }, [updateAppState]);

  // Determine active session/entity from active tab
  const activeTab = appState.tabs.find(t => t.id === appState.activeTabId);
  const activeSessionId = (activeTab?.type === 'session' ? activeTab.targetId : null) || null;

  useViewport('app', () => ({
    visible: true,
    children: ['session_navigator', 'workspace', 'bottom_panel'],
  }));

  return (
    <ToastProvider>
      <ErrorBoundary>
        <ActionContextProvider>
          <div className="app" style={{ gridTemplateColumns: `${navResize.width}px 1fr` }}>
            <div className="navigator-panel">
              <Navigator
                onSelectSession={handleSelectSession}
                activeSessionId={activeSessionId}
              />
              <div className="navigator-resize" onMouseDown={navResize.onMouseDown} title="Drag to resize" />
            </div>
            <div className="workspace-panel">
              <Workspace />
              <BottomPanel activeSessionId={activeSessionId} />
            </div>
          </div>
          <SettingsPanel
            visible={settingsVisible}
            onClose={() => setSettingsVisible(false)}
            initialPrefs={appState.appearance}
            onSave={handleSaveAppearance}
          />
          {/* Add Note / Ask Hamilton now live in the BottomPanel footer bar
              (right-justified next to the version), not floating. */}
        </ActionContextProvider>
      </ErrorBoundary>
    </ToastProvider>
  );
}
