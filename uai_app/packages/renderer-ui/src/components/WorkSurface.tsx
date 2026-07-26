/**
 * WorkSurface — the reusable Work rendering (List / Tree / Kanban / By-Assigned)
 * over a GIVEN todo set (todo_0544 A2).
 *
 * This is the state-glue the global Work Mgr (WorkMgrPane) keeps inline, lifted
 * into a standalone component so the worker Tab's Work aspect can reuse the EXACT
 * same rendering — the same `useTodoListModel` + `TodoListView` + `TodoItemView`
 * trio — scoped to one worker. It takes the (already-scoped) `todos` as a prop
 * instead of loading the global set itself.
 *
 * HARD CONSTRAINT (todo_0544): WorkMgrPane is NOT modified — it keeps its own
 * inline glue. WorkSurface is a parallel host of the same shared components; the
 * two can be DRY'd later with PianoMan's ok. Behavior/markup mirror WorkMgrPane's
 * body so the worker Tab looks/works identically at narrower scope.
 *
 * Mutations route through the same Command Bus verbs WorkMgrPane uses
 * (todo.setStatus / todo.assign / todo.unassign / todo.move) and then call
 * `onReload` so the host refetches and feeds a fresh `todos` prop.
 */

import { useCallback, useMemo, useState } from 'react';
import { useViewport } from '../viewport';
import StatusFilterMenu from './StatusFilterMenu';
import SortMenu from './SortMenu';
import { executeCommand } from '../utils/execute-command';
import ParentPicker from './ParentPicker';
import TodoItemView from './TodoItemView';
import TodoBulkPanel from './TodoBulkPanel';
import TodoListView from './TodoListView';
import { useTodoListModel } from './useTodoListModel';
import { useCardStore, useAppStateStore } from '../stores';
import {
  STATUS_ORDER, NO_ASSIGNEE, statusColor, statusLabel, assigneeLabel,
  formatTitle, todoNum,
} from './WorkMgrPane';
import type { WorkItem, ViewMode } from './WorkMgrPane';

type SortMode = 'updated' | 'number' | 'status' | 'title' | 'assignee';

const ALL_STATUSES = Object.keys(STATUS_ORDER).sort((a, b) => STATUS_ORDER[a] - STATUS_ORDER[b]);
const FINALIZED = new Set(['Done', 'Cancelled']);

// Inline status changer for the detail header (mirrors WorkMgrPane's StatusSelect).
function StatusSelect({ status, onChange }: { status: string; onChange: (s: string) => void }): JSX.Element {
  return (
    <select className="wm-status-select" value={status} onChange={e => onChange(e.target.value)}
      style={{ color: statusColor(status), borderColor: statusColor(status) }} title="Change status">
      {ALL_STATUSES.map(s => <option key={s} value={s}>{statusLabel(s)}</option>)}
    </select>
  );
}

export interface WorkSurfaceProps {
  /** Already-scoped todo set (via work-scope.ts) — the worker's work items. */
  todos: WorkItem[];
  loading?: boolean;
  /** Called after a mutation so the host refetches and passes a fresh `todos`. */
  onReload?: () => void;
  /** The host toggles whether finalized (Done/Cancelled) todos are fetched. */
  onWantFinalized?: (want: boolean) => void;
  /** Per-instance viewport id so multiple WorkSurfaces register distinctly. */
  viewportId?: string;
  /** Empty-state text when the scoped set is empty. */
  emptyLabel?: string;
  /** Stack the detail editor BELOW the list instead of beside it (worker-Tab
   *  Work aspect — PianoMan 2026-07-21). Default false keeps the Work Mgr split. */
  stacked?: boolean;
}

export default function WorkSurface({
  todos, loading = false, onReload, onWantFinalized,
  viewportId = 'work_surface', emptyLabel, stacked = false,
}: WorkSurfaceProps): JSX.Element {
  const cardStore = useCardStore();
  const { appState } = useAppStateStore();

  const [viewMode, setViewMode] = useState<ViewMode>('tree');
  const [sortMode, setSortMode] = useState<SortMode>('updated');
  const [sortReversed, setSortReversed] = useState(false);
  const [assignedFilter, setAssignedFilter] = useState('');
  const [search, setSearch] = useState('');
  const [activeStatuses, setActiveStatuses] = useState<Set<string>>(
    () => new Set(ALL_STATUSES.filter(s => !FINALIZED.has(s))),
  );
  const [kanbanNest, setKanbanNest] = useState(false);
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set());
  // Tree nodes are expanded by default; this holds the ones the user collapsed.
  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(new Set());
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selIds, setSelIds] = useState<Set<string>>(new Set());   // multi-select (todo_0558)
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const selected = useMemo(() => todos.find(t => t.id === selectedId) || null, [todos, selectedId]);
  const handleSelect = useCallback((id: string) => { setSelIds(new Set()); setSelectedId(id); }, []);

  // ── mutations via the Command Bus, then ask the host to refetch. ────────────
  const runCmd = useCallback(async (type: string, payload: Record<string, unknown>): Promise<boolean> => {
    const r = await executeCommand(type, payload);
    if (!r.ok) setError(r.error?.message || `${type} failed`);
    return r.ok;
  }, []);
  const setStatus = useCallback(async (id: string, status: string) => {
    setBusy(id); const ok = await runCmd('todo.setStatus', { id, status }); setBusy(null); if (ok) onReload?.();
  }, [runCmd, onReload]);
  const moveTo = useCallback(async (id: string, target: string) => {
    setBusy(id); const ok = await runCmd('todo.move', { id, target }); setBusy(null); if (ok) onReload?.();
  }, [runCmd, onReload]);
  // Single-value assignee semantics (like WorkMgrPane): clear all, then assign one.
  const setAssignee = useCallback(async (id: string, uri: string) => {
    setBusy(id);
    for (const a of (selected?.assigned || [])) await executeCommand('todo.unassign', { id, uri: a });
    if (uri) await executeCommand('todo.assign', { id, uri });
    setBusy(null); onReload?.();
  }, [selected, onReload]);

  // Bulk drag-drop ops (todo_0411) — apply to every dragged id, reload once.
  const bulkMove = useCallback(async (ids: string[], target: string) => {
    const list = ids.filter(id => id && id !== target); if (!list.length) return;
    setBusy('bulk'); let ok = false; for (const id of list) if (await runCmd('todo.move', { id, target })) ok = true;
    setBusy(null); if (ok) onReload?.();
  }, [runCmd, onReload]);
  const bulkStatus = useCallback(async (ids: string[], status: string) => {
    if (!ids.length) return;
    setBusy('bulk'); let ok = false; for (const id of ids) if (await runCmd('todo.setStatus', { id, status })) ok = true;
    setBusy(null); if (ok) onReload?.();
  }, [runCmd, onReload]);
  const bulkAssign = useCallback(async (ids: string[], uri: string) => {
    if (!ids.length) return;
    const nextUri = uri.trim();
    setBusy('bulk'); let ok = false;
    for (const id of ids) {
      const current = todos.find(t => t.id === id);
      for (const oldUri of (current?.assigned || [])) {
        if (await runCmd('todo.unassign', { id, uri: oldUri })) ok = true;
      }
      if (nextUri && await runCmd('todo.assign', { id, uri: nextUri })) ok = true;
    }
    setBusy(null); if (ok) onReload?.();
  }, [runCmd, onReload, todos]);
  const bulkComment = useCallback(async (ids: string[], text: string) => {
    if (!ids.length || !text.trim()) return;
    setBusy('bulk'); let ok = false; for (const id of ids) if (await runCmd('todo.comment', { id, text: text.trim() })) ok = true;
    setBusy(null); if (ok) onReload?.();
  }, [runCmd, onReload]);
  const bulkTrash = useCallback(async (ids: string[]) => {
    if (!ids.length) return;
    setBusy('bulk'); let ok = false; for (const id of ids) if (await runCmd('todo.trash', { id })) ok = true;
    setBusy(null); if (ok) { setSelIds(new Set()); setSelectedId(null); onReload?.(); }
  }, [runCmd, onReload]);
  const createParentAndMove = useCallback(async (name: string, ids: string[]) => {
    const nm = name.trim(); if (!nm || !ids.length) return;
    setBusy('bulk');
    const ok = await runCmd('todo.create', { name: nm });
    if (ok) {
      const norm = (s: string) => s.toLowerCase().replace(/[^a-z0-9]+/g, ' ').trim();
      const fresh = (await window.uai.todos.list(false)) as WorkItem[];
      const match = fresh.filter(t => norm(formatTitle(t)) === norm(nm))
        .sort((a, b) => todoNum(b.id).localeCompare(todoNum(a.id), undefined, { numeric: true }))[0];
      if (match) for (const id of ids) await runCmd('todo.move', { id, target: match.id });
    }
    setBusy(null); onReload?.();
  }, [runCmd, onReload]);
  const WS_ASSIGNEE_GROUPS = ['Projects', 'Teams', 'Active sessions', 'Stopped sessions'];

  // ── filter predicate + comparator (mirror WorkMgrPane). ─────────────────────
  const matches = useCallback((t: WorkItem): boolean => {
    if (!activeStatuses.has(t.status)) return false;
    if (assignedFilter) {
      if (assignedFilter === NO_ASSIGNEE) { if ((t.assigned || []).length) return false; }
      else if (!(t.assigned || []).includes(assignedFilter)) return false;
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      if (!(`${t.id} ${formatTitle(t)}`.toLowerCase().includes(q))) return false;
    }
    return true;
  }, [activeStatuses, assignedFilter, search]);

  const cmp = useCallback((a: WorkItem, b: WorkItem): number => {
    const base = (() => {
      switch (sortMode) {
        case 'number': return todoNum(a.id).localeCompare(todoNum(b.id), undefined, { numeric: true });
        case 'status': return (STATUS_ORDER[a.status] ?? 99) - (STATUS_ORDER[b.status] ?? 99);
        case 'title': return formatTitle(a).localeCompare(formatTitle(b));
        case 'assignee': return (assigneeLabel((a.assigned || [])[0] || '~') || '~').localeCompare(assigneeLabel((b.assigned || [])[0] || '~') || '~');
        case 'updated':
        default: return (b.updated || '').localeCompare(a.updated || '');
      }
    })();
    return sortReversed ? -base : base;
  }, [sortMode, sortReversed]);

  const model = useTodoListModel(todos, matches, cmp);
  const { filtered } = model;

  // Statuses present in the scoped data, plus Done/Cancelled always (toggle-on).
  const presentStatuses = useMemo(() => {
    const s = new Set<string>(['Done', 'Cancelled']); todos.forEach(t => s.add(t.status));
    return ALL_STATUSES.filter(x => s.has(x));
  }, [todos]);
  // Actively narrowing? The resting default hides only Done/Cancelled, which must
  // NOT count as filtering (else tree parents force-expand and can't collapse).
  const isFiltering = useMemo(
    () => !!search.trim() || !!assignedFilter
      || presentStatuses.some(s => !FINALIZED.has(s) && !activeStatuses.has(s)),
    [presentStatuses, activeStatuses, assignedFilter, search],
  );
  const toggleStatus = (s: string) => setActiveStatuses(prev => {
    const n = new Set(prev); n.has(s) ? n.delete(s) : n.add(s);
    // Fetching finalized todos is the host's job — ask it when a finalized pill flips.
    if (FINALIZED.has(s)) onWantFinalized?.(n.has('Done') || n.has('Cancelled'));
    return n;
  });
  const allAssignees = useMemo(() => {
    const s = new Set<string>(); todos.forEach(t => (t.assigned || []).forEach(a => s.add(a))); return Array.from(s).sort();
  }, [todos]);

  const toggleGroup = (k: string) => setCollapsedGroups(p => { const n = new Set(p); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const toggleNode = (k: string) => setCollapsedNodes(p => { const n = new Set(p); n.has(k) ? n.delete(k) : n.add(k); return n; });

  // Assignee dropdown options (Projects → Teams → sessions), mirroring WorkMgrPane.
  const openTabIds = useMemo(() => new Set((appState.tabs || []).map((t: any) => t.targetId)), [appState.tabs]);
  const assigneeOptions = useMemo(() => {
    const out: Array<{ uri: string; label: string; grp: string }> = [];
    const byName = (a: any, b: any) => (a.display_name || '').localeCompare(b.display_name || '');
    [...(cardStore.projects || [])].sort(byName).forEach((p: any) =>
      out.push({ uri: `uai://project/${String(p.entity_id).replace(/^project:/, '')}`, label: p.display_name, grp: 'Projects' }));
    [...(cardStore.teams || [])].sort(byName).forEach((t: any) =>
      out.push({ uri: `uai://team/${String(t.entity_id).replace(/^team:/, '')}`, label: t.display_name, grp: 'Teams' }));
    const sess = (cardStore.sessions || []).filter((s: any) => !s.archived);
    const sLabel = (s: any) => s.display_name || s.tracking_id.slice(0, 12);
    const sUri = (s: any) => `uai://session/${s.tracking_id}`;
    const hasTab = (s: any) => openTabIds.has(s.tracking_id);
    const running = sess.filter((s: any) => s.process_status === 'running');
    const stopped = sess.filter((s: any) => s.process_status !== 'running');
    [...running.filter(hasTab).sort(byName), ...running.filter((s: any) => !hasTab(s)).sort(byName)]
      .forEach((s: any) => out.push({ uri: sUri(s), label: sLabel(s), grp: 'Active sessions' }));
    [...stopped.filter(hasTab).sort(byName), ...stopped.filter((s: any) => !hasTab(s)).sort((a: any, b: any) => (b.last_activity || '').localeCompare(a.last_activity || ''))]
      .forEach((s: any) => out.push({ uri: sUri(s), label: sLabel(s), grp: 'Stopped sessions' }));
    return out;
  }, [cardStore.projects, cardStore.teams, cardStore.sessions, openTabIds]);
  const ASSIGNEE_GROUPS = ['Projects', 'Teams', 'Active sessions', 'Stopped sessions'];

  useViewport(viewportId, () => ({
    visible: true,
    label: 'Work Surface',
    state: { view: viewMode, sort: sortMode, total: todos.length, visible: filtered.length, selectedId },
    children: [],
  }));

  return (
    <div className={`work-mgr work-surface${stacked ? ' work-surface-stacked' : ''}`}>
      <div className="wm-body">
        {error && <div className="traits-mgr-error">{error}</div>}
        <div className="wm-split">
          <div className="wm-list-col">
            <div className="wm-controls">
              <div className="wm-seg">
                {(['flat', 'tree', 'kanban', 'assignee'] as ViewMode[]).map(m => (
                  <button key={m} className={`filter-pill ${viewMode === m ? 'active' : ''}`} onClick={() => setViewMode(m)}>
                    {m === 'flat' ? 'Flat' : m === 'tree' ? 'Tree' : m === 'kanban' ? 'Kanban' : 'By Assigned To'}
                  </button>
                ))}
              </div>
              <SortMenu
                fields={[
                  { value: 'updated', label: 'Updated' },
                  { value: 'number', label: 'Number' },
                  { value: 'status', label: 'Status' },
                  { value: 'title', label: 'Title' },
                  { value: 'assignee', label: 'Assigned to' },
                ]}
                value={sortMode}
                ascending={sortMode === 'updated' ? sortReversed : !sortReversed}
                onSelect={(v) => {
                  if (v === sortMode) setSortReversed(r => !r);
                  else setSortMode(v as SortMode);
                }}
              />
              <StatusFilterMenu
                statuses={presentStatuses}
                active={activeStatuses}
                onToggle={toggleStatus}
                onAll={() => setActiveStatuses(new Set(presentStatuses))}
                onNone={() => setActiveStatuses(new Set())}
                statusColor={statusColor}
                statusLabel={statusLabel}
              />
              <label className="wm-dd">Assigned to
                <select value={assignedFilter} onChange={e => setAssignedFilter(e.target.value)}>
                  <option value="">All</option>{allAssignees.map(a => <option key={a} value={a}>{assigneeLabel(a)}</option>)}<option value={NO_ASSIGNEE}>(unassigned)</option>
                </select>
              </label>
              {viewMode === 'kanban' && (
                <button className={`filter-pill ${kanbanNest ? 'active' : ''}`} onClick={() => setKanbanNest(v => !v)} title="Group items under their parent (dimmed context)">Nest</button>
              )}
              <span style={{ flex: 1 }} />
              <div className="wm-search">
                <span className="wm-search-ic">🔍</span>
                <input className="wm-search-input" type="text" value={search} placeholder="Search…"
                  onChange={e => setSearch(e.target.value)} />
                {search && <button className="wm-search-clear" onClick={() => setSearch('')} title="Clear search">✕</button>}
              </div>
            </div>
            <TodoListView
              model={model} viewMode={viewMode} selectedId={selectedId} onSelect={handleSelect}
              selIds={selIds} onSelIdsChange={setSelIds}
              onReparent={bulkMove} onSetStatus={bulkStatus} onReassign={bulkAssign}
              matches={matches} isFiltering={isFiltering} search={search}
              kanbanNest={kanbanNest} busy={busy} loading={loading} error={error}
              collapsedGroups={collapsedGroups} toggleGroup={toggleGroup}
              collapsedNodes={collapsedNodes} toggleNode={toggleNode}
              viewportId={`${viewportId}_list`}
            />
          </div>

          <div className="wm-detail">
            {selIds.size > 1 ? (
              <TodoBulkPanel
                ids={[...selIds]} todos={todos} statuses={ALL_STATUSES}
                assigneeOptions={assigneeOptions} assigneeGroups={WS_ASSIGNEE_GROUPS} busy={busy === 'bulk'}
                onStatus={s => bulkStatus([...selIds], s)}
                onAssign={u => bulkAssign([...selIds], u)}
                onComment={t => bulkComment([...selIds], t)}
                onMove={p => bulkMove([...selIds], p)}
                onCreateParent={n => createParentAndMove(n, [...selIds])}
                onDelete={() => bulkTrash([...selIds])}
                onClear={() => setSelIds(new Set())}
              />
            ) : !selected ? <div className="traits-mgr-empty">{emptyLabel || 'Select a work item'}</div> : (
              <TodoItemView
                viewportId={`${viewportId}_view`}
                todo={selected as any}
                allTodos={todos as any}
                search={search}
                onSelect={handleSelect}
                statusEditor={<StatusSelect status={selected.status} onChange={s => setStatus(selected.id, s)} />}
                assigneeEditor={
                  <select className="wm-status-select" value={(selected.assigned || [])[0] || ''} onChange={e => setAssignee(selected.id, e.target.value)} title="Assign to a project / team / session" disabled={busy === selected.id}>
                    <option value="">unassigned</option>
                    {ASSIGNEE_GROUPS.map(grp => {
                      const opts = assigneeOptions.filter(o => o.grp === grp);
                      return opts.length ? <optgroup key={grp} label={grp}>{opts.map(o => <option key={o.uri} value={o.uri}>{o.label}</option>)}</optgroup> : null;
                    })}
                    {(selected.assigned || [])[0] && !assigneeOptions.some(o => o.uri === (selected.assigned || [])[0]) && (
                      <option value={(selected.assigned || [])[0]}>{assigneeLabel((selected.assigned || [])[0])}</option>
                    )}
                  </select>
                }
                moveControl={
                  <ParentPicker
                    todos={todos}
                    excludeIds={new Set([selected.id])}
                    onMove={pid => moveTo(selected.id, pid)}
                    onCreateParent={n => createParentAndMove(n, [selected.id])}
                  />
                }
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
