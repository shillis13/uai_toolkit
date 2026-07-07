/**
 * TabManagerPane — an app-tab for managing the main workspace tabs in bulk.
 *
 * Selection model (matches file managers / PianoMan's spec):
 *   - click            → select only this (clears prior); sets the anchor.
 *   - cmd/ctrl+click    → toggle this in/out of the selection; sets the anchor.
 *   - shift+click       → select the inclusive range from the anchor to here.
 *
 * Actions: close selected (and close-others), reorder by drag-and-drop of the
 * selection, activate/jump (double-click), and — for session tabs — stop/resume.
 * "Group selected" is present but DISABLED (deferred).
 *
 * Reads the live tab list from the app-state store; reorder persists via
 * updateAppState({ tabs }) (same path as the tab-bar drag handler); close/
 * activate go through the command bus (workspace.tabs.*).
 */

import { useState, useCallback, useMemo, useRef } from 'react';
import { useAppStateStore, useSessionStore } from '../stores';
import { executeCommand } from '../utils/execute-command';
import { useToast } from './Toast';
import { TabNavArrows } from './TabNavArrows';
import type { Tab, TabType } from '@uai/shared/types';

// Distinct icon + color per kind. Terminal (green), Folder (yellow), Project
// (cyan/📦), and Team (blue/👥) are deliberately all different from each other —
// folder's 📂 and green are NOT reused by project.
const TAB_TYPE_META: Record<string, { icon: string; color: string; label: string }> = {
  session: { icon: '✱', color: 'var(--accent-orange)', label: 'Session' },
  folder: { icon: '📂', color: 'var(--accent-yellow)', label: 'Folder' },
  terminal: { icon: '>_', color: 'var(--accent-green)', label: 'Terminal' },
  brief: { icon: '📖', color: 'var(--accent-cyan)', label: 'Brief' },
  project: { icon: '📦', color: 'var(--accent-cyan)', label: 'Project' },
  team: { icon: '👥', color: 'var(--accent-blue)', label: 'Team' },
  webai: { icon: '🌐', color: 'var(--accent-purple)', label: 'Web AI' },
  app: { icon: '🛠', color: 'var(--accent-orange)', label: 'App' },
  transcript: { icon: '✱', color: 'var(--accent-orange)', label: 'Transcript' },
  search: { icon: '🔍', color: 'var(--text-sec)', label: 'Search' },
};
const metaOf = (t: string) => TAB_TYPE_META[t] || { icon: '●', color: 'var(--text-muted)', label: t };

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-cyan)',
};

export default function TabManagerPane(_props: { tabId?: string }): JSX.Element {
  const { appState, updateAppState } = useAppStateStore();
  const { getSession } = useSessionStore();
  const { showToast } = useToast();

  const tabs = appState.tabs;
  const activeTabId = appState.activeTabId;

  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [anchorId, setAnchorId] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [typeFilter, setTypeFilter] = useState<Set<TabType>>(new Set());
  const [dragId, setDragId] = useState<string | null>(null);
  const [dropIdx, setDropIdx] = useState<number | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  const [renameText, setRenameText] = useState('');
  const busyRef = useRef(false);

  // The "true" display name for a tab — a session's display_name (or tracking id)
  // for session tabs; the current label otherwise. Used by the rename quick-fill.
  const displayNameOf = useCallback((t: Tab): string => {
    if (t.type === 'session') {
      const s = getSession(t.targetId);
      return s?.display_name || s?.tracking_id || t.targetId;
    }
    return t.label;
  }, [getSession]);

  // Type chips present in the current tab set (in a stable display order).
  const presentTypes = useMemo(() => {
    const order: TabType[] = ['session', 'terminal', 'app', 'project', 'folder', 'brief', 'transcript', 'team', 'webai', 'search'];
    const have = new Set(tabs.map((t) => t.type));
    return order.filter((t) => have.has(t));
  }, [tabs]);

  // Displayed rows: full workspace order, then search + type filters applied.
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase();
    return tabs.filter((t) => {
      if (typeFilter.size > 0 && !typeFilter.has(t.type)) return false;
      if (q && !(`${t.label} ${t.type} ${t.targetId}`.toLowerCase().includes(q))) return false;
      return true;
    });
  }, [tabs, search, typeFilter]);
  const visibleIds = useMemo(() => visible.map((t) => t.id), [visible]);

  const filtering = search.trim().length > 0 || typeFilter.size > 0;

  // ── Selection (click / cmd+click / shift+click) ────────────────────────────
  const onRowClick = useCallback((e: React.MouseEvent, id: string) => {
    if (e.shiftKey && anchorId && visibleIds.includes(anchorId)) {
      const a = visibleIds.indexOf(anchorId);
      const b = visibleIds.indexOf(id);
      const [lo, hi] = a < b ? [a, b] : [b, a];
      setSelected(new Set(visibleIds.slice(lo, hi + 1)));
      // keep the anchor so successive shift-clicks re-range from the same point
    } else if (e.metaKey || e.ctrlKey) {
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(id)) next.delete(id); else next.add(id);
        return next;
      });
      setAnchorId(id);
    } else {
      setSelected(new Set([id]));
      setAnchorId(id);
    }
  }, [anchorId, visibleIds]);

  const selectAll = useCallback(() => setSelected(new Set(visibleIds)), [visibleIds]);
  const clearSel = useCallback(() => { setSelected(new Set()); setAnchorId(null); }, []);
  const toggleTypeFilter = useCallback((t: TabType) => {
    setTypeFilter((prev) => { const n = new Set(prev); if (n.has(t)) n.delete(t); else n.add(t); return n; });
  }, []);

  const selectedTabs = useCallback((): Tab[] => tabs.filter((t) => selected.has(t.id)), [tabs, selected]);
  const selCount = selected.size;

  // ── Close / activate / session actions ─────────────────────────────────────
  const activate = useCallback((id: string) => {
    executeCommand('workspace.tabs.activate', { tabId: id }, { onFailure: 'toast', toastFn: showToast });
  }, [showToast]);

  // ── Rename (with a "use Display Name" quick-fill) ──────────────────────────
  const startRename = useCallback((t: Tab) => { setRenaming(t.id); setRenameText(t.label); }, []);
  const cancelRename = useCallback(() => { setRenaming(null); setRenameText(''); }, []);
  const saveRename = useCallback((id: string, name: string) => {
    const label = name.trim();
    setRenaming(null); setRenameText('');
    if (!label) return;
    executeCommand('workspace.tabs.update', { tabId: id, patch: { label } }, { onFailure: 'toast', toastFn: showToast });
  }, [showToast]);

  const closeIds = useCallback(async (ids: string[]) => {
    if (busyRef.current || ids.length === 0) return;
    busyRef.current = true;
    try {
      for (const id of ids) {
        await executeCommand('workspace.tabs.close', { tabId: id }, { onFailure: 'toast', toastFn: showToast });
      }
      setSelected((prev) => { const n = new Set(prev); ids.forEach((i) => n.delete(i)); return n; });
    } finally { busyRef.current = false; }
  }, [showToast]);

  const closeSelected = useCallback(() => {
    const ids = selectedTabs().map((t) => t.id);
    if (ids.length > 3 && !window.confirm(`Close ${ids.length} tabs?`)) return;
    closeIds(ids);
  }, [selectedTabs, closeIds]);

  const closeOthers = useCallback(() => {
    const keep = selected;
    const ids = tabs.filter((t) => !keep.has(t.id)).map((t) => t.id);
    if (ids.length === 0) return;
    if (!window.confirm(`Close the other ${ids.length} tab(s), keeping ${keep.size} selected?`)) return;
    closeIds(ids);
  }, [tabs, selected, closeIds]);

  const sessionAction = useCallback(async (cmd: 'session.stop' | 'session.resume') => {
    const sessions = selectedTabs().filter((t) => t.type === 'session');
    if (sessions.length === 0) { showToast('No session tabs selected', 'info'); return; }
    for (const t of sessions) {
      await executeCommand(cmd, { trackingId: t.targetId }, { onFailure: 'toast', toastFn: showToast });
    }
  }, [selectedTabs, showToast]);

  // ── Reorder (drag & drop of the selection) ─────────────────────────────────
  const onDragStart = useCallback((e: React.DragEvent, id: string) => {
    // Dragging an unselected row selects only it; a selected row drags the whole set.
    if (!selected.has(id)) { setSelected(new Set([id])); setAnchorId(id); }
    setDragId(id);
    e.dataTransfer.effectAllowed = 'move';
    try { e.dataTransfer.setData('text/plain', id); } catch { /* ignore */ }
  }, [selected]);

  const onDragOverRow = useCallback((e: React.DragEvent, overId: string) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    setDropIdx(tabs.findIndex((t) => t.id === overId));
  }, [tabs]);

  const doDrop = useCallback((targetId: string | null) => {
    if (!dragId) return;
    // The moving set = the current selection (which includes dragId).
    const moving = tabs.filter((t) => selected.has(t.id) || t.id === dragId);
    const movingIds = new Set(moving.map((t) => t.id));
    const rest = tabs.filter((t) => !movingIds.has(t.id));
    // Insertion index in `rest`: before the target tab (or at end if dropped past it).
    let insertAt = rest.length;
    if (targetId && !movingIds.has(targetId)) {
      const ri = rest.findIndex((t) => t.id === targetId);
      if (ri >= 0) insertAt = ri;
    }
    const next = [...rest.slice(0, insertAt), ...moving, ...rest.slice(insertAt)];
    updateAppState({ tabs: next });
    setDragId(null);
    setDropIdx(null);
  }, [dragId, tabs, selected, updateAppState]);

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="tabmgr-pane">
      <div className="tabmgr-toolbar">
        <TabNavArrows />
        <div className="tabmgr-title">Tab Manager <span className="tabmgr-count">{tabs.length} tabs</span></div>
        <input
          className="tabmgr-search"
          placeholder="Filter by name / type…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>

      <div className="tabmgr-actionbar">
        <span className="tabmgr-selinfo">{selCount} selected</span>
        <button className="tabmgr-btn" onClick={selectAll} disabled={visible.length === 0}>Select all</button>
        <button className="tabmgr-btn" onClick={clearSel} disabled={selCount === 0}>Clear</button>
        <span className="tabmgr-sep" />
        <button className="tabmgr-btn tabmgr-btn-danger" onClick={closeSelected} disabled={selCount === 0}>Close ({selCount})</button>
        <button className="tabmgr-btn" onClick={closeOthers} disabled={selCount === 0}>Close others</button>
        <span className="tabmgr-sep" />
        <button className="tabmgr-btn" onClick={() => sessionAction('session.stop')} disabled={selCount === 0}>Stop</button>
        <button className="tabmgr-btn" onClick={() => sessionAction('session.resume')} disabled={selCount === 0}>Resume</button>
        <span className="tabmgr-sep" />
        <button className="tabmgr-btn" disabled title="Grouping is deferred for now">Group selected</button>
        {/* Type filter pills live next to Group selected (per PianoMan). */}
        <div className="tabmgr-typechips">
          {presentTypes.map((t) => {
            const m = metaOf(t);
            const on = typeFilter.has(t);
            const n = tabs.filter((x) => x.type === t).length;
            return (
              <button key={t} className={`tabmgr-chip${on ? ' active' : ''}`}
                style={on ? { color: m.color, borderColor: m.color } : undefined}
                onClick={() => toggleTypeFilter(t)} title={`${m.label} (${n})`}>
                <span style={{ color: m.color }}>{m.icon}</span> {n}
              </button>
            );
          })}
        </div>
      </div>

      {filtering && (
        <div className="tabmgr-hint">Showing {visible.length} of {tabs.length}. Drag-to-reorder still moves within the full tab order.</div>
      )}

      <div
        className="tabmgr-list"
        onDragOver={(e) => { e.preventDefault(); }}
        onDrop={() => doDrop(null)}
      >
        {visible.length === 0 && <div className="tabmgr-empty">{tabs.length === 0 ? 'No open tabs.' : 'No tabs match the filter.'}</div>}
        {visible.map((t) => {
          const m = metaOf(t.type);
          let color = m.color;
          const isSession = t.type === 'session';
          const s = isSession ? getSession(t.targetId) : undefined;
          if (isSession && s?.platform) color = PLATFORM_COLORS[s.platform] || color;
          const running = s?.process_status === 'running';
          const isSel = selected.has(t.id);
          const isActive = t.id === activeTabId;
          const realIdx = tabs.findIndex((x) => x.id === t.id);
          const isDropTarget = dropIdx === realIdx && dragId != null && !selected.has(t.id) && t.id !== dragId;
          const isRenaming = renaming === t.id;
          return (
            <div
              key={t.id}
              className={`tabmgr-row${isSel ? ' selected' : ''}${isActive ? ' active' : ''}${isDropTarget ? ' droptarget' : ''}${dragId === t.id ? ' dragging' : ''}`}
              draggable={!isRenaming}
              onClick={(e) => { if (!isRenaming) onRowClick(e, t.id); }}
              onDoubleClick={() => { if (!isRenaming) activate(t.id); }}
              onDragStart={(e) => onDragStart(e, t.id)}
              onDragOver={(e) => onDragOverRow(e, t.id)}
              onDrop={(e) => { e.stopPropagation(); doDrop(t.id); }}
              onDragEnd={() => { setDragId(null); setDropIdx(null); }}
              title={`${m.label} · ${t.targetId}\nClick to select · ⌘/Ctrl+click toggle · Shift+click range · double-click to open`}
            >
              <span className="tabmgr-grip" title="Drag to reorder">⋮⋮</span>
              <span className="tabmgr-row-icon" style={{ color }}>{m.icon}</span>
              {isRenaming ? (
                <span className="tabmgr-rename" onClick={(e) => e.stopPropagation()}>
                  <input
                    className="tabmgr-rename-input"
                    autoFocus
                    value={renameText}
                    onChange={(e) => setRenameText(e.target.value)}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter') saveRename(t.id, renameText);
                      else if (e.key === 'Escape') cancelRename();
                    }}
                  />
                  <button className="tabmgr-rename-dn" title="Set to the Display Name"
                    onClick={() => setRenameText(displayNameOf(t))}>→ Display Name</button>
                  <button className="tabmgr-rename-ok" title="Save" onClick={() => saveRename(t.id, renameText)}>✓</button>
                  <button className="tabmgr-rename-x" title="Cancel" onClick={cancelRename}>✕</button>
                </span>
              ) : (
                <span className="tabmgr-row-name" style={{ color }}>{t.label}</span>
              )}
              {isActive && !isRenaming && <span className="tabmgr-active-badge" title="Active tab">active</span>}
              {!isRenaming && (
                <div className="tabmgr-controls">
                  <button className="tabmgr-row-rename" onClick={(e) => { e.stopPropagation(); startRename(t); }} title="Rename tab">✎</button>
                  {isSession && <span className={`tabmgr-status ${running ? 'running' : 'stopped'}`} title={running ? 'running' : 'stopped'}>{running ? '●' : '○'}</span>}
                  <button className="tabmgr-row-go" onClick={(e) => { e.stopPropagation(); activate(t.id); }} title="Open this tab">{'↗'}</button>
                  <button className="tabmgr-row-close" onClick={(e) => { e.stopPropagation(); closeIds([t.id]); }} title="Close this tab">{'✕'}</button>
                </div>
              )}
              <span className="tabmgr-spacer" />
            </div>
          );
        })}
      </div>
    </div>
  );
}
