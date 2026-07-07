/**
 * Workspace — Center panel with tabbed session views.
 *
 * Tab bar shows open sessions with platform color indicators.
 * Each tab renders a SessionPane (terminal + memorex).
 * When no tab is active, shows a browse placeholder.
 *
 * Tab state persisted in AppStateStore.
 * Keyboard shortcuts: Cmd+W close, Cmd+1-9 switch, Cmd+Shift+[/] prev/next.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useViewport } from '../viewport';
import { useAppStateStore, useSessionStore } from '../stores';
import { scanSessionPromptArea } from '../stores/prompt-area-state';
import { isSessionBreathing } from '../stores/session-state';
import { useFolderStore } from '../stores/folder-store';
import { useToast } from './Toast';
import { executeCommand } from '../utils/execute-command';
import TabContentPane from './TabContentPane';
import TabManagerMenu from './TabManagerMenu';
import SessionTitleBar from './SessionTitleBar';
import SessionContextMenu from './SessionContextMenu';
import { TabNavContext } from './TabNavArrows';
import type { Tab, GridLayout } from '@uai/shared/types';

// ─── Platform colors for tab indicators ─────────────────────────────────

const TAB_PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-blue)',
};

// Categorical palette that gives each tab group a distinct hue (cycled by index).
// Kept as hex literals — these are concatenated with alpha suffixes (`${color}0F`,
// `${color}33`) for translucent group backgrounds/borders, which only works on hex
// strings, not `var(--token)` references. Treated like the session-color identity
// palette: its own color space, intentionally not tokenized.
const GROUP_COLORS = [
  '#2ac3de', '#9ece6a', '#e0af68', '#f7768e',
  '#bb9af7', '#ff9e64', '#73daca', '#7aa2f7',
];

interface GroupTabState {
  visibleIds: string[];
  collapsed: boolean;
  layout: GridLayout;
}

// ─── Workspace ───────────────────────────────────────────────────────────

export default function Workspace(): JSX.Element {
  const { appState, updateAppState } = useAppStateStore();
  const { getSession } = useSessionStore();
  const folderStore = useFolderStore();
  const { showToast } = useToast();

  const { tabs, activeTabId } = appState;
  const activeTab = tabs.find(t => t.id === activeTabId);

  // Ref for the active tab element — used to scroll it into view
  const activeTabRef = useRef<HTMLDivElement>(null);
  // Ref for the tab-bar scroll container itself (the element that actually scrolls).
  // Needed because a grouped tab's parentElement is its group bracket, not the bar.
  const tabBarRef = useRef<HTMLDivElement>(null);

  // On tab switch, re-scan the prompt-area state of the session being left
  // (it may now hold staged text) and the session being entered.
  const prevSessionRef = useRef<string | null>(null);
  useEffect(() => {
    const current = activeTab && activeTab.type === 'session' ? activeTab.targetId : null;
    const prev = prevSessionRef.current;
    if (prev && prev !== current) scanSessionPromptArea(prev, 0);
    if (current) scanSessionPromptArea(current, 0);
    prevSessionRef.current = current;
  }, [activeTabId, activeTab]);

  // ─── Tab Navigation History ──────────────────────────────────────────
  // Tracks user-initiated tab activations as a linear history with an index pointer.
  // Back/forward arrows navigate this history without pushing new entries.
  // Combined into a single state to avoid cross-dependency between history and index.
  const [navHistory, setNavHistory] = useState<{ entries: string[]; index: number }>(
    () => ({ entries: activeTabId ? [activeTabId] : [], index: activeTabId ? 0 : -1 })
  );
  const isNavigatingRef = useRef(false);

  const canGoBack = navHistory.index > 0;
  const canGoForward = navHistory.index < navHistory.entries.length - 1;

  const navigateBack = useCallback(() => {
    if (!canGoBack) return;
    const newIndex = navHistory.index - 1;
    const tabId = navHistory.entries[newIndex];
    // Check the tab still exists
    if (!tabs.find(t => t.id === tabId)) return;
    isNavigatingRef.current = true;
    setNavHistory(prev => ({ ...prev, index: newIndex }));
    executeCommand('workspace.tabs.activate', { tabId }, {
      onFailure: 'toast', toastFn: showToast,
    });
  }, [canGoBack, navHistory, tabs, showToast]);

  const navigateForward = useCallback(() => {
    if (!canGoForward) return;
    const newIndex = navHistory.index + 1;
    const tabId = navHistory.entries[newIndex];
    if (!tabs.find(t => t.id === tabId)) return;
    isNavigatingRef.current = true;
    setNavHistory(prev => ({ ...prev, index: newIndex }));
    executeCommand('workspace.tabs.activate', { tabId }, {
      onFailure: 'toast', toastFn: showToast,
    });
  }, [canGoForward, navHistory, tabs, showToast]);

  // Track ALL activeTabId changes in navHistory — covers tab activations from
  // Navigator clicks, workspace.tabs.open commands, etc., not just executeActivateTab.
  useEffect(() => {
    if (!activeTabId) return;
    if (isNavigatingRef.current) {
      isNavigatingRef.current = false;
      return;
    }
    setNavHistory(prev => {
      const truncated = prev.entries.slice(0, prev.index + 1);
      if (truncated[truncated.length - 1] === activeTabId) return prev;
      const newEntries = [...truncated, activeTabId];
      return { entries: newEntries, index: newEntries.length - 1 };
    });
  }, [activeTabId]);

  // Center the active tab in the tab bar whenever it changes (open or activate),
  // clamped so we stop at the ends rather than over-scrolling. Positions are computed
  // via rects relative to the scroll container, so it's correct even when the tab is
  // nested inside a group bracket, and is scale-invariant to the hover-zoom transform
  // (an element's center x is unchanged by a bottom-center scale).
  useEffect(() => {
    if (!activeTabId) return;
    const raf = requestAnimationFrame(() => {
      const bar = tabBarRef.current;
      const el = activeTabRef.current;
      if (!bar || !el) return;
      const barRect = bar.getBoundingClientRect();
      const elRect = el.getBoundingClientRect();
      const elCenterInContent = (elRect.left - barRect.left) + bar.scrollLeft + elRect.width / 2;
      const target = elCenterInContent - bar.clientWidth / 2;
      const maxScroll = bar.scrollWidth - bar.clientWidth;
      bar.scrollTo({ left: Math.max(0, Math.min(target, maxScroll)), behavior: 'smooth' });
    });
    return () => cancelAnimationFrame(raf);
  }, [activeTabId, tabs.length]);

  // Group visibility/collapse state (per group container ID)
  const [groupStates, setGroupStates] = useState<Record<string, GroupTabState>>({});

  // Per-session Memorex state (lifted from TerminalPane for title bar access)
  const [memorexStates, setMemorexStates] = useState<Record<string, boolean>>({});
  const toggleMemorex = useCallback((sessionId: string) => {
    setMemorexStates(prev => ({ ...prev, [sessionId]: prev[sessionId] === false }));
  }, []);

  // Per-session transcript panel state
  const [transcriptStates, setTranscriptStates] = useState<Record<string, boolean>>({});
  const toggleTranscript = useCallback((sessionId: string) => {
    setTranscriptStates(prev => ({ ...prev, [sessionId]: !prev[sessionId] }));
  }, []);

  // Per-session Chat|Work subtab (lives in the title bar, not a separate row)
  const [subtabStates, setSubtabStates] = useState<Record<string, 'chat' | 'work'>>({});
  const setSubtab = useCallback((sessionId: string, v: 'chat' | 'work') => {
    setSubtabStates(prev => ({ ...prev, [sessionId]: v }));
  }, []);

  // Tab drag-and-drop reordering
  const [dragTabId, setDragTabId] = useState<string | null>(null);

  const handleTabDragStart = useCallback((e: React.DragEvent, tabId: string) => {
    setDragTabId(tabId);
    e.dataTransfer.effectAllowed = 'move';
    e.dataTransfer.setData('text/plain', tabId);
  }, []);

  const handleTabDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
  }, []);

  const handleTabDrop = useCallback((e: React.DragEvent, targetTabId: string) => {
    e.preventDefault();
    if (!dragTabId || dragTabId === targetTabId) { setDragTabId(null); return; }
    const newTabs = [...tabs];
    const dragIdx = newTabs.findIndex(t => t.id === dragTabId);
    const targetIdx = newTabs.findIndex(t => t.id === targetTabId);
    if (dragIdx === -1 || targetIdx === -1) { setDragTabId(null); return; }
    const [moved] = newTabs.splice(dragIdx, 1);
    newTabs.splice(targetIdx, 0, moved);
    updateAppState({ tabs: newTabs });
    setDragTabId(null);
  }, [dragTabId, tabs, updateAppState]);

  const executeCloseTab = useCallback((tabId: string) => {
    executeCommand('workspace.tabs.close', { tabId }, {
      onFailure: 'toast', toastFn: showToast,
    });
  }, [showToast]);

  const executeActivateTab = useCallback((tabId: string) => {
    executeCommand('workspace.tabs.activate', { tabId }, {
      onFailure: 'toast', toastFn: showToast,
    });
  }, [showToast]);

  // Tab context menu
  const [tabContextMenu, setTabContextMenu] = useState<{ x: number; y: number; tab: Tab } | null>(null);

  // Dismiss non-session tab context menu on outside click/right-click.
  // Session tabs use SessionContextMenu which handles its own dismiss.
  const tabMenuRef = useRef<HTMLDivElement>(null);
  const isNonSessionTab = tabContextMenu
    ? !getSession(tabContextMenu.tab.targetId)
    : false;
  useEffect(() => {
    // Only register dismiss handlers for non-session tab menus.
    // SessionContextMenu manages its own dismiss via useContextMenuDismiss.
    if (!tabContextMenu || !isNonSessionTab) return;
    const isInside = (e: Event) =>
      tabMenuRef.current != null && tabMenuRef.current.contains(e.target as Node);
    const dismiss = (e: MouseEvent) => {
      if (!isInside(e)) setTabContextMenu(null);
    };
    const dismissAndBlock = (e: MouseEvent) => {
      if (!isInside(e)) {
        e.preventDefault();
        e.stopPropagation();
        setTabContextMenu(null);
      }
    };
    const timer = setTimeout(() => {
      window.addEventListener('mousedown', dismiss);
      window.addEventListener('contextmenu', dismissAndBlock, true);
    }, 0);
    return () => {
      clearTimeout(timer);
      window.removeEventListener('mousedown', dismiss);
      window.removeEventListener('contextmenu', dismissAndBlock, true);
    };
  }, [tabContextMenu, isNonSessionTab]);

  const handleTabContextMenu = useCallback((e: React.MouseEvent, tab: Tab) => {
    e.preventDefault();
    // If menu is already open, dismiss it instead of reopening
    if (tabContextMenu) {
      setTabContextMenu(null);
      return;
    }
    // Clamp position to keep menu within viewport
    const menuWidth = 200;
    const menuHeight = 300;
    const x = Math.min(e.clientX, window.innerWidth - menuWidth);
    const y = Math.min(e.clientY, window.innerHeight - menuHeight);
    setTabContextMenu({ x, y, tab });
  }, []);

  const closeOtherTabs = useCallback((keepTabId: string) => {
    tabs.filter(t => t.id !== keepTabId).forEach(t => executeCloseTab(t.id));
    setTabContextMenu(null);
  }, [tabs, executeCloseTab]);

  // ─── Group Actions ────────────────────────────────────────────────

  const toggleGroupCollapse = useCallback((groupId: string) => {
    setGroupStates(prev => ({
      ...prev,
      [groupId]: {
        ...prev[groupId],
        collapsed: !prev[groupId]?.collapsed,
      },
    }));
  }, []);

  // Keyboard shortcuts
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!e.metaKey && !e.ctrlKey) return;

      // Cmd+W → close active tab
      if (e.key === 'w' && !e.shiftKey) {
        if (activeTabId) {
          e.preventDefault();
          executeCloseTab(activeTabId);
        }
        return;
      }

      // Cmd+1-9 → switch to tab by index
      const num = parseInt(e.key, 10);
      if (num >= 1 && num <= 9 && !e.shiftKey) {
        const idx = num - 1;
        if (idx < tabs.length) {
          e.preventDefault();
          executeActivateTab(tabs[idx].id);
        }
        return;
      }

      // Cmd+Shift+[ → previous tab
      if (e.shiftKey && e.key === '[') {
        e.preventDefault();
        const currentIdx = tabs.findIndex(t => t.id === activeTabId);
        if (currentIdx > 0) {
          executeActivateTab(tabs[currentIdx - 1].id);
        }
        return;
      }

      // Cmd+Shift+] → next tab
      if (e.shiftKey && e.key === ']') {
        e.preventDefault();
        const currentIdx = tabs.findIndex(t => t.id === activeTabId);
        if (currentIdx < tabs.length - 1) {
          executeActivateTab(tabs[currentIdx + 1].id);
        }
        return;
      }
    };

    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [tabs, activeTabId, executeCloseTab, executeActivateTab]);

  const handleCloseTab = useCallback((e: React.MouseEvent, tabId: string) => {
    e.stopPropagation();
    executeCloseTab(tabId);
  }, [executeCloseTab]);

  // ─── Tab Bar Rendering ──────────────────────────────────────────────

  const renderTab = (tab: Tab, closeHandler?: (e: React.MouseEvent) => void) => {
    const session = (tab.type === 'session' || tab.type === 'transcript') ? getSession(tab.targetId) : undefined;
    const platformColor = session ? (TAB_PLATFORM_COLORS[session.platform] || 'var(--text-muted)') : 'var(--text-muted)';
    const isActive = tab.id === activeTabId;
    const isStopped = session ? session.process_status !== 'running' : false;
    // Derive tab display label from live session display_name for session tabs
    const tabLabel = session?.display_name || tab.label;

    // Type-specific tab icon
    const TAB_TYPE_ICONS: Record<string, { icon: string; color: string; cls?: string }> = {
      session: { icon: session?.platform === 'codex_cli' ? '\u25CE' : session?.platform === 'gemini_cli' ? '\u2726' : '\u2731', color: platformColor, cls: 'tab-icon-ai' },
      folder: { icon: '\uD83D\uDCC2', color: 'var(--accent-yellow)' },
      terminal: { icon: '>_', color: 'var(--accent-green)' },
      brief: { icon: '\uD83D\uDCD6', color: 'var(--accent-cyan)' },
      project: { icon: '\uD83D\uDCCB', color: 'var(--accent-yellow)' },
      team: { icon: '\uD83D\uDC65', color: 'var(--accent-blue)' },
      webai: { icon: '\uD83C\uDF10', color: 'var(--accent-purple)' },
      app: { icon: '\uD83D\uDEE0', color: 'var(--accent-orange)' },
      transcript: { icon: '\u2731', color: platformColor, cls: 'tab-icon-ai' },
    };
    const typeIcon = TAB_TYPE_ICONS[tab.type] || { icon: '\u25CF', color: 'var(--text-muted)' };
    // Breathe the tab's AI icon while its session is non-idle (same source as the
    // Session Card dot + Recent icon \u2014 see stores/session-state.ts).
    const iconBreathing = session ? isSessionBreathing(session.activity_state, session.process_status) : false;

    return (
      <div
        key={tab.id}
        ref={isActive ? activeTabRef : undefined}
        className={`workspace-tab${isActive ? ' active' : ''}${dragTabId === tab.id ? ' dragging' : ''}${isStopped ? ' workspace-tab-stopped' : ''} workspace-tab-type-${tab.type}`}
        onClick={() => executeActivateTab(tab.id)}
        onContextMenu={(e) => handleTabContextMenu(e, tab)}
        draggable
        onDragStart={(e) => handleTabDragStart(e, tab.id)}
        onDragOver={handleTabDragOver}
        onDrop={(e) => handleTabDrop(e, tab.id)}
        onDragEnd={() => setDragTabId(null)}
        title={`${tab.type}: ${tab.targetId}`}
      >
        <span className={`workspace-tab-icon${typeIcon.cls ? ` ${typeIcon.cls}` : ''}${iconBreathing ? ' session-breathing' : ''}`} style={{ color: typeIcon.color }}>{typeIcon.icon}</span>
        <span className="workspace-tab-label">{tabLabel}</span>
        <button
          className="workspace-tab-close"
          onClick={closeHandler || ((e: React.MouseEvent) => handleCloseTab(e, tab.id))}
          title="Close tab"
        >{'\u00d7'}</button>
      </div>
    );
  };

  useViewport('workspace', () => ({
    visible: true,
    state: {
      activeTabId,
      tabCount: tabs.length,
      activeTabType: activeTab?.type,
      activeTabLabel: activeTab?.label,
      activeTabTargetId: activeTab?.targetId,
      tabTypes: tabs.map(t => ({ id: t.id, type: t.type, label: t.label })),
    },
    actions: [
      { id: 'close_active', command: 'workspace.tabs.close', label: 'Close active tab', payload: activeTabId ? { tabId: activeTabId } : {} },
    ],
    children: [
      ...(activeTab ? ['entity_view'] : []),
      'session_context_menu',
    ],
  }));

  const tabBarElements = useMemo(() => {
    const renderedTabIds = new Set<string>();
    const brackets: JSX.Element[] = [];

    // Collect tabs by groupId (Team or Project)
    const groupMap = new Map<string, typeof tabs>();
    for (const tab of tabs) {
      if (tab.groupId) {
        if (!groupMap.has(tab.groupId)) groupMap.set(tab.groupId, []);
        groupMap.get(tab.groupId)!.push(tab);
      }
    }

    // Render bracketed groups
    const colorIdx = { i: 0 };
    for (const [gid, memberTabs] of groupMap) {
      const state = groupStates[gid] || { visibleIds: memberTabs.map(t => t.targetId), collapsed: false, layout: 'single' as GridLayout };
      const color = GROUP_COLORS[colorIdx.i % GROUP_COLORS.length];
      colorIdx.i++;
      // Use first tab's label or groupId as bracket name
      const bracketLabel = gid.replace(/^(team|project):?/, '').replace(/_/g, ' ').slice(0, 20) || gid;
      const visibleTabs = state.collapsed ? [] : memberTabs;

      brackets.push(
        <div
          key={`bracket-${gid}`}
          className={`tab-group-bracket${state.collapsed ? ' collapsed' : ''}`}
          style={{ borderColor: color, background: `${color}0F` }}
        >
          <div
            className="tab-group-header"
            style={{ color, borderColor: `${color}33` }}
          >
            <span
              className="tab-group-collapse-btn"
              onClick={(e) => { e.stopPropagation(); toggleGroupCollapse(gid); }}
            >
              {state.collapsed ? '\u25B8' : '\u25BE'}
            </span>
            <span>{bracketLabel}</span>
            <span className="tab-group-badge" style={{ background: `${color}33`, color }}>{memberTabs.length}</span>
          </div>
          {visibleTabs.map(t => renderTab(t))}
          {state.collapsed && memberTabs.length > 0 && (
            <span
              className="tab-group-more"
              title={`${memberTabs.length} tab(s) — click to expand`}
              onClick={() => toggleGroupCollapse(gid)}
              style={{ cursor: 'pointer' }}
            >+{memberTabs.length}</span>
          )}
        </div>
      );

      memberTabs.forEach(t => renderedTabIds.add(t.id));
    }

    // Standalone tabs (no groupId)
    const standalone: JSX.Element[] = [];
    for (const tab of tabs) {
      if (renderedTabIds.has(tab.id)) continue;
      standalone.push(renderTab(tab));
    }

    return [...standalone, ...brackets];
  }, [tabs, groupStates, activeTabId]);

  // Expose Back/Forward to any pane (so manager panes render their own nav-arrows
  // instance inline in their own title bar). Memoized so consumers don't churn.
  const tabNavValue = useMemo(
    () => ({ canGoBack, canGoForward, navigateBack, navigateForward }),
    [canGoBack, canGoForward, navigateBack, navigateForward],
  );

  return (
    <TabNavContext.Provider value={tabNavValue}>
    <div className="workspace">
      {/* Tab bar — spans full width above content + context panel */}
      {tabs.length > 0 && (
        <div
          ref={tabBarRef}
          className="workspace-tab-bar"
          onMouseMove={(e) => {
            const bar = e.currentTarget;
            const tabEls = bar.querySelectorAll('.workspace-tab') as NodeListOf<HTMLElement>;
            const mouseX = e.clientX;
            const maxScale = 1.35;
            const radius = 120; // pixels of influence

            tabEls.forEach(tabEl => {
              const rect = tabEl.getBoundingClientRect();
              const tabCenter = rect.left + rect.width / 2;
              const dist = Math.abs(mouseX - tabCenter);
              const scale = dist < radius ? 1 + (maxScale - 1) * (1 - dist / radius) : 1;
              tabEl.style.transform = `scale(${scale})`;
              tabEl.style.transformOrigin = 'bottom center';
              tabEl.style.zIndex = scale > 1.01 ? '10' : '';
            });
          }}
          onMouseLeave={(e) => {
            const tabEls = e.currentTarget.querySelectorAll('.workspace-tab') as NodeListOf<HTMLElement>;
            tabEls.forEach(tabEl => {
              tabEl.style.transform = '';
              tabEl.style.zIndex = '';
            });
          }}
        >
          <TabManagerMenu />
          {tabBarElements}
        </div>
      )}

      {/* Session title bar — spans full width including over right panel area */}
      {activeTab && (activeTab.type === 'session' || activeTab.type === 'transcript') && (() => {
        const sessionCardId = `session:${activeTab.targetId}`;
        const parentFolderId = folderStore.cardLocation(sessionCardId) || 'all_sessions';
        const parentFolderObj = folderStore.getFolder(parentFolderId);
        return (
        <SessionTitleBar
          tab={activeTab}
          subtab={subtabStates[activeTab.targetId] || 'chat'}
          onSetSubtab={(v) => setSubtab(activeTab.targetId, v)}
          memorexEnabled={memorexStates[activeTab.targetId] !== false}
          onToggleMemorex={() => toggleMemorex(activeTab.targetId)}
          transcriptOpen={!!transcriptStates[activeTab.targetId]}
          onToggleTranscript={() => toggleTranscript(activeTab.targetId)}
          onToggleRightPanel={() => updateAppState({ contextPanelOpen: !appState.contextPanelOpen })}
          canGoBack={canGoBack}
          canGoForward={canGoForward}
          onNavigateBack={navigateBack}
          onNavigateForward={navigateForward}
          canGoUp={true}
          onNavigateUp={() => {
            if (parentFolderObj) {
              executeCommand('workspace.tabs.open', {
                type: 'folder',
                targetId: parentFolderId,
                label: parentFolderObj.name,
              });
            }
          }}
        />
        );
      })()}

      {/* Folder title bar — nav arrows + breadcrumb path (view/sort/filter controlled by FolderContent) */}
      {activeTab && activeTab.type === 'folder' && (() => {
        const folderId = activeTab.targetId;
        const parentId = folderStore.parentFolder(folderId) || (folderId !== 'all_sessions' ? 'all_sessions' : null);
        const parentObj = parentId ? folderStore.getFolder(parentId) : null;
        const breadcrumbs = folderStore.breadcrumbSegments(folderId);
        return (
          <div className="session-title-bar">
            <div className="stb-row">
              <div className="stb-left">
                <div className="stb-nav-arrows">
                  <button className="stb-nav-btn" title="Back" disabled={!canGoBack} onClick={navigateBack}>{'\u2190'}</button>
                  <button className="stb-nav-btn" title="Up to parent folder" disabled={!parentObj} onClick={() => {
                    if (parentId && parentObj) {
                      executeCommand('workspace.tabs.open', { type: 'folder', targetId: parentId, label: parentObj.name });
                    }
                  }}>{'\u2191'}</button>
                  <button className="stb-nav-btn" title="Forward" disabled={!canGoForward} onClick={navigateForward}>{'\u2192'}</button>
                </div>
                <span className="stb-name stb-breadcrumb">
                  {breadcrumbs.map((seg, i) => (
                    <span key={seg.id}>
                      {i > 0 && <span className="stb-breadcrumb-sep"> / </span>}
                      {i < breadcrumbs.length - 1 ? (
                        <span className="stb-breadcrumb-link" onClick={() => executeCommand('workspace.tabs.open', { type: 'folder', targetId: seg.id, label: seg.name })}>{seg.name}</span>
                      ) : (
                        <span className="stb-breadcrumb-current">{seg.name}</span>
                      )}
                    </span>
                  ))}
                </span>
                <div id="folder-toolbar-portal" />
              </div>
            </div>
          </div>
        );
      })()}

      {/* Generic title bar for simple non-session/folder tabs (terminal, brief,
          search, project, team, webai): nav arrows + title. NOT 'app' (manager)
          tabs \u2014 each Mgr pane renders its OWN title bar with its own <TabNavArrows/>
          instance inline (one bar, like Session tabs \u2014 no separate strip). */}
      {activeTab && activeTab.type !== 'session' && activeTab.type !== 'transcript' && activeTab.type !== 'folder' && activeTab.type !== 'app' && (
        <div className="session-title-bar">
          <div className="stb-row">
            <div className="stb-left">
              <div className="stb-nav-arrows">
                <button className="stb-nav-btn" title="Back" disabled={!canGoBack} onClick={navigateBack}>{'\u2190'}</button>
                <button className="stb-nav-btn" title="Forward" disabled={!canGoForward} onClick={navigateForward}>{'\u2192'}</button>
              </div>
              <span className="stb-name">{activeTab.label}</span>
            </div>
          </div>
        </div>
      )}

      {/* Content area — each entity view manages its own detail panel.
          NOTE: clicks do NOT count as session activity. Recent Sessions
          ordering is driven only by the user actually typing (terminal
          keystrokes + prompt submit), so navigating/clicking around — and
          especially switching tabs — never re-orders the list. */}
      <div className="workspace-content">
        {activeTab ? (
          <TabContentPane key={activeTab.id} tab={activeTab} memorexEnabled={activeTab.type === 'session' ? memorexStates[activeTab.targetId] !== false : undefined} transcriptOpen={activeTab.type === 'session' ? !!transcriptStates[activeTab.targetId] : undefined} onCloseTranscript={activeTab.type === 'session' ? () => toggleTranscript(activeTab.targetId) : undefined} subtab={activeTab.type === 'session' ? (subtabStates[activeTab.targetId] || 'chat') : undefined} />
        ) : (
          <div className="workspace-placeholder">
            <h2>UAI</h2>
            <p>Select a session to open it here.</p>
          </div>
        )}
        {/* Keep app/tool panes mounted when not active — prevents unmount/remount
            losing state (e.g. scan progress) on tab switch. Hidden via CSS. */}
        {tabs.filter(t => t.type === 'app' && t.id !== activeTabId).map(t => (
          <div key={t.id} style={{ display: 'none' }}>
            <TabContentPane tab={t} />
          </div>
        ))}
      </div>

      {/* Tab context menu */}
      {tabContextMenu && (() => {
        const ctxSession = getSession(tabContextMenu.tab.targetId) || undefined;
        const tabIdx = tabs.findIndex(t => t.id === tabContextMenu.tab.id);
        const closeLeftTabs = () => { tabs.slice(0, tabIdx).forEach(t => executeCloseTab(t.id)); setTabContextMenu(null); };
        const closeRightTabs = () => { tabs.slice(tabIdx + 1).forEach(t => executeCloseTab(t.id)); setTabContextMenu(null); };

        // Common menu items for ALL tab types
        const commonItems = (
          <>
            <div className="context-menu-separator" />
            <button className="context-menu-item" onClick={() => { executeCloseTab(tabContextMenu.tab.id); setTabContextMenu(null); }}>Close Tab</button>
            <div className="context-menu-item submenu-trigger">
              Tab {'\u25B6'}
              <div className="context-submenu">
                <button className="context-menu-item" onClick={closeLeftTabs}>Close All Left</button>
                <button className="context-menu-item" onClick={closeRightTabs}>Close All Right</button>
                <button className="context-menu-item" onClick={() => closeOtherTabs(tabContextMenu.tab.id)}>Close All Others</button>
              </div>
            </div>
          </>
        );

        if (!ctxSession) {
          // Non-session tab: basic menu + common items
          return (
            <div ref={tabMenuRef} className="context-menu" style={{ position: 'fixed', left: tabContextMenu.x, top: tabContextMenu.y, zIndex: 1000 }}>
              <button className="context-menu-item" onClick={() => {
                const name = prompt('Rename tab:', tabContextMenu.tab.label);
                if (name?.trim()) {
                  executeCommand('workspace.tabs.update', { tabId: tabContextMenu.tab.id, patch: { label: name.trim() } }, { onFailure: 'toast', toastFn: showToast });
                }
                setTabContextMenu(null);
              }}>Rename</button>
              {commonItems}
            </div>
          );
        }
        return (
          <SessionContextMenu
            x={tabContextMenu.x}
            y={tabContextMenu.y}
            session={ctxSession}
            onClose={() => setTabContextMenu(null)}
            tabId={tabContextMenu.tab.id}
            onCloseTab={executeCloseTab}
            onCloseOthers={closeOtherTabs}
          />
        );
      })()}
    </div>
    </TabNavContext.Provider>
  );
}
