/**
 * WorkMgrPane — Work-centric work tracker (Design Component 5a).
 *
 * Engine-backed (todo_mgr json + write verbs). See docs/designs/work_mgr.md and
 * docs/ux_standards.md. Key UX rules honored here:
 *   - Pills ONLY for stable-membership sets (status enum). Projects / assignees
 *     change regularly → dropdowns, never pills (ux_standards.md).
 *   - Tags are never pills and are not shown in the left list.
 *   - Relative indexes (TR/RD/IP refs) are REPL-only; never surfaced.
 *   - Finalized work (Done/Cancelled) hidden by default; explicit toggles. In
 *     tree view, hierarchy takes priority — a shown finalized node sits under its
 *     parent, not in a status bucket.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import type { ReactNode } from 'react';

// Distinct per-group hues for tree parent-child group outlines (cf. Kanban section colors).
export const TREE_GROUP_COLORS = ['#2ac3de', '#9ece6a', '#e0af68', '#f7768e', '#bb9af7', '#ff9e64', '#73daca', '#7aa2f7'];

// Module-level view-state cache — persists the Work Mgr's selection + view across
// leaving and returning the tab (the pane unmounts on tab switch). Single instance
// since the Work Mgr is a singleton. (todo_0407)
const wmCache: {
  viewMode?: string; sortMode?: string; sortReversed?: boolean; assignedFilter?: string; search?: string;
  activeStatuses?: string[]; collapsedGroups?: string[]; collapsedNodes?: string[];
  selectedId?: string | null; detailTab?: string; density?: string;
} = {};
import { useViewport } from '../viewport';
import StatusFilterMenu from './StatusFilterMenu';
import SortMenu from './SortMenu';
import { executeCommand } from '../utils/execute-command';
import ParentPicker from './ParentPicker';
import { TabNavArrows } from './TabNavArrows';
import TodoItemView from './TodoItemView';
import TodoListView from './TodoListView';
import TodoBulkPanel from './TodoBulkPanel';
import NewTodoDialog from './NewTodoDialog';
import { useToast } from './Toast';
import { useTodoListModel } from './useTodoListModel';
import { consumePendingTodoFocus } from './RefLink';
import { usePanelResize } from '../hooks/usePanelResize';
import { useCardStore, useAppStateStore } from '../stores';
import { useSessionStore } from '../stores/session-store';
import { assigneeLabel } from './assigneeLabel';
import { TODOS_CHANGED, notifyTodosChanged } from '../utils/todo-events';

export interface WorkItem {
  id: string;
  rel_path?: string;
  status: string;
  priority?: string;   // High | Normal | Low (todo_0652); default Normal
  tags: string[];
  flags: string[];
  assigned: string[];
  parent?: string | null;
  children?: string[];
  title?: string;
  summary?: string;
  updated?: string;
  created?: string;
}

interface WorkMgrPaneProps { tabId?: string; }

export type ViewMode = 'flat' | 'tree' | 'kanban' | 'assignee';
type GroupMode = 'none' | 'status' | 'project' | 'assigned';
type SortMode = 'updated' | 'number' | 'status' | 'priority' | 'title' | 'assignee';

// 2-3 letter status codes for the dense list rows (colored by status).
const STATUS_ABBR: Record<string, string> = {
  'In_Progress': 'IP', 'Blocked': 'BLK', 'Reviewing': 'REV', 'Accepting': 'ACC',
  'Ready': 'RDY', 'Needs_Derivation': 'DRV', 'Needs_Research': 'RSC',
  'Triaging': 'TRI', 'Done': 'DON', 'Cancelled': 'CXL',
};
const statusAbbr = (s: string): string => STATUS_ABBR[s] || (s || '?').slice(0, 3).toUpperCase();

// Spec-defined metadata files/dirs — these are NOT artifacts; hide from Files.
const SPEC_FILES = new Set(['notes.md', 'origin.yml', 'history.log', 'assigned.yml']);
function isSpecFile(rel: string): boolean {
  const base = rel.split('/').pop() || '';
  return SPEC_FILES.has(base) || base.endsWith('.status') || base.endsWith('.tag') || base.endsWith('.flag');
}

// PianoMan-specified lifecycle order (todo_0607): drives BOTH sort-by-status and the
// Status filter-dropdown order (ALL_STATUSES derives from this). Needs_Research wasn't
// in PM's list; placed before Needs_Derivation (research → derive → ready).
export const STATUS_ORDER: Record<string, number> = {
  'Blocked': 0, 'Triaging': 1, 'Needs_Research': 2, 'Needs_Derivation': 3, 'Ready': 4,
  'In_Progress': 5, 'Reviewing': 6, 'Accepting': 7, 'Done': 8, 'Cancelled': 9,
};
const STATUS_COLORS: Record<string, string> = {
  'In_Progress': 'var(--accent-blue)', 'Blocked': 'var(--accent-red)',
  'Reviewing': 'var(--accent-purple)', 'Accepting': 'var(--accent-cyan)',
  'Ready': 'var(--accent-green)', 'Needs_Derivation': 'var(--accent-yellow)',
  'Needs_Research': 'var(--accent-orange)', 'Triaging': 'var(--text-sec, #b8c0cc)',
  'Done': 'var(--accent-green)', 'Cancelled': 'var(--text-muted)',
};
const ALL_STATUSES = Object.keys(STATUS_ORDER).sort((a, b) => STATUS_ORDER[a] - STATUS_ORDER[b]);
const FINALIZED = new Set(['Done', 'Cancelled']);
export const NO_ASSIGNEE = '(unassigned)';

export const statusColor = (s: string): string => STATUS_COLORS[s] || 'var(--text-muted)';
export const statusLabel = (s: string): string => (s || '').replace(/_/g, ' ');

export function todoNum(id: string): string {
  const m = (id || '').match(/(?:todo|task)_(\d+)/);
  return m ? m[1] : id;
}
export function formatTitle(item: WorkItem): string {
  // Prefer an explicit title, else the id-derived slug. Either way STRIP a
  // leading todo_####_ / task_####_ prefix — the number is shown separately (as
  // the colored TodoId), so repeating it in the name is redundant. This also
  // normalizes the 2 todos whose title lacked the prefix into the same shape.
  const raw = (item.title && item.title.trim()) ? item.title : (item.id || '');
  return raw.replace(/^(?:todo|task)_\d+_?/, '').replace(/_/g, ' ').trim();
}
// Re-exported so existing importers (TodoListView) keep resolving from here.
export { assigneeLabel };
export function fmtDate(iso?: string): string {
  if (!iso) return '';
  try { return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); } catch { return ''; }
}
export function fmtTs(ts: string): string { try { return new Date(ts).toLocaleString(); } catch { return ts; } }
function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
// last-touched date, falling back to created when updated is absent (older todos).
export const itemDate = (t: { updated?: string; created?: string }): string | undefined => t.updated || t.created;

// Renders a todo id so it's clearly a todo_#### — dim "todo_" prefix, bright number.
export function TodoId({ id, big }: { id: string; big?: boolean }): JSX.Element {
  return (
    <span className={`wm-num${big ? ' wm-num-lg' : ''}`} title={id}>{todoNum(id)}</span>
  );
}
// 2-3 letter status code chip, colored by status.
export function StatusCode({ status }: { status: string }): JSX.Element {
  return <span className="wm-status-code" style={{ color: statusColor(status) }} title={statusLabel(status)}>{statusAbbr(status)}</span>;
}

// Priority (todo_0652). High/Normal/Low — Normal is the default and shows NO chip
// (no clutter, per PM). High = red, Low = blue.
export const PRIORITY_LEVELS = ['High', 'Normal', 'Low'];
export const PRIORITY_ORDER: Record<string, number> = { High: 0, Normal: 1, Low: 2 };
const PRIORITY_COLOR: Record<string, string> = { High: 'var(--accent-red)', Low: 'var(--accent-blue)' };
export function effectivePriority(item: Pick<WorkItem, 'priority' | 'flags'>): string {
  // Rolling-upgrade/read compatibility for todos created with the retired flag.
  return item.priority || (item.flags.includes('high_priority') ? 'High' : 'Normal');
}
export function PriorityChip({ priority }: { priority?: string }): JSX.Element | null {
  const p = priority || 'Normal';
  if (p === 'Normal') return null;
  return (
    <span className="wm-prio-chip" title={`Priority: ${p}`}
      style={{ color: PRIORITY_COLOR[p] || 'var(--text-muted)', borderColor: PRIORITY_COLOR[p] || 'var(--border)' }}>
      {p === 'High' ? '⬆ High' : '⬇ Low'}
    </span>
  );
}

// Wrap occurrences of `query` (case-insensitive) in <mark> for search highlighting.
export function highlight(text: string, query: string): ReactNode {
  const q = query.trim();
  if (!q) return text;
  const lower = text.toLowerCase(); const lq = q.toLowerCase();
  const out: ReactNode[] = []; let i = 0, n = 0;
  while (i < text.length) {
    const idx = lower.indexOf(lq, i);
    if (idx < 0) { out.push(text.slice(i)); break; }
    if (idx > i) out.push(text.slice(i, idx));
    out.push(<mark key={n++} className="wm-hl">{text.slice(idx, idx + q.length)}</mark>);
    i = idx + q.length;
  }
  return out;
}

function parseNotes(md: string): { preamble: string; sections: Array<{ heading: string; body: string }> } {
  if (!md) return { preamble: '', sections: [] };
  const lines = md.split('\n');
  const first = lines.findIndex(l => /^##\s+/.test(l));
  if (first === -1) return { preamble: md.trim(), sections: [] };
  const preamble = lines.slice(0, first).join('\n').trim();
  const sections: Array<{ heading: string; body: string }> = [];
  let cur: { heading: string; body: string[] } | null = null;
  for (const line of lines.slice(first)) {
    const h = line.match(/^##\s+(.*)$/);
    if (h) { if (cur) sections.push({ heading: cur.heading, body: cur.body.join('\n').trim() }); cur = { heading: h[1].trim(), body: [] }; }
    else if (cur) cur.body.push(line);
  }
  if (cur) sections.push({ heading: cur.heading, body: cur.body.join('\n').trim() });
  return { preamble, sections };
}
function serializeNotes(preamble: string, sections: Array<{ heading: string; body: string }>): string {
  const parts: string[] = [];
  if (preamble.trim()) parts.push(preamble.trim());
  for (const s of sections) parts.push(`## ${s.heading}\n\n${s.body}`.trimEnd());
  return parts.join('\n\n') + '\n';
}

// ── small UI atoms ──────────────────────────────────────────────────────────
// status changer — the easy way to set any state incl. finalize (#10)
function StatusSelect({ status, onChange }: { status: string; onChange: (s: string) => void }): JSX.Element {
  return (
    <select className="wm-status-select" value={status} onChange={e => onChange(e.target.value)}
      style={{ color: statusColor(status), borderColor: statusColor(status) }} title="Change status">
      {ALL_STATUSES.map(s => <option key={s} value={s}>{statusLabel(s)}</option>)}
    </select>
  );
}

// Priority editor (todo_0652) — small High/Normal/Low dropdown for the detail header.
function PrioritySelect({ priority, onChange }: { priority: string; onChange: (p: string) => void }): JSX.Element {
  return (
    <select className="wm-status-select" value={priority} onChange={e => onChange(e.target.value)} title="Change priority">
      {PRIORITY_LEVELS.map(p => <option key={p} value={p}>{p === 'Normal' ? 'Normal priority' : `${p} priority`}</option>)}
    </select>
  );
}

interface DetailState {
  raw: string;   // full notes.md — shown as ONE consolidated Notes field (#11)
  preamble: string;
  sections: Array<{ heading: string; body: string }>;
  provenance: { origin: Record<string, string>; history: Array<{ ts: string; status: string; session: string; note: string }> };
  files: Array<{ rel: string; size: number; isDir: boolean }>;
}
type DetailTab = 'contents' | 'details';

export default function WorkMgrPane({ tabId }: WorkMgrPaneProps): JSX.Element {
  const listResize = usePanelResize('workMgrListWidth', { def: 300, min: 200, max: () => Math.max(600, Math.round(window.innerWidth * 0.5)) });
  const { showToast } = useToast();
  const cardStore = useCardStore();
  const { appState } = useAppStateStore();
  const [todos, setTodos] = useState<WorkItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [viewMode, setViewMode] = useState<ViewMode>((wmCache.viewMode as ViewMode) ?? 'tree');
  const [density, setDensity] = useState<'compact' | 'expanded'>((wmCache.density as 'compact' | 'expanded') ?? 'compact');
  // groupMode fixed to status (Kanban groups by status); no group dropdown.
  const [groupMode] = useState<GroupMode>('status');
  const [sortMode, setSortMode] = useState<SortMode>((wmCache.sortMode as SortMode) ?? 'updated');
  const [sortReversed, setSortReversed] = useState<boolean>(wmCache.sortReversed ?? false);
  const [assignedFilter, setAssignedFilter] = useState<string>(wmCache.assignedFilter ?? '');
  const [search, setSearch] = useState<string>(wmCache.search ?? '');   // free-text search over id + title
  // Status filter is an independent multi-select pill set (#2). Done/Cancelled ARE
  // statuses (#5) — they're pills too, just deselected by default.
  const [activeStatuses, setActiveStatuses] = useState<Set<string>>(() => new Set(wmCache.activeStatuses ?? ALL_STATUSES.filter(s => !FINALIZED.has(s))));
  const [kanbanNest, setKanbanNest] = useState(false); // group kanban items under (dimmed) parent context

  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set(wmCache.collapsedGroups ?? []));
  // Tree nodes are EXPANDED by default; this holds the ones the user has collapsed
  // (persisted). Default-expanded keeps the tree visible, but every parent stays
  // collapsible — the old expanded-set default made parents un-collapsible.
  const [collapsedNodes, setCollapsedNodes] = useState<Set<string>>(() => new Set(wmCache.collapsedNodes ?? []));

  const [selectedId, setSelectedId] = useState<string | null>(wmCache.selectedId ?? null);
  // Multi-select set (todo_0558) — drives the bulk-actions detail pane. Lives here
  // (not in TodoListView) so the detail pane can react to it.
  const [selIds, setSelIds] = useState<Set<string>>(new Set());
  const [detail, setDetail] = useState<DetailState | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [newAssignee, setNewAssignee] = useState('');
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<{ content?: string; truncated?: boolean; error?: string } | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>((wmCache.detailTab as DetailTab) ?? 'contents');
  const [notesDraft, setNotesDraft] = useState<string | null>(null); // edit buffer for the one Notes field
  const [notesHeight, setNotesHeight] = useState(200); // adjustable Notes/Files boundary (#2)

  // Persist view state to the module cache so it survives leaving+returning the tab. (todo_0407)
  useEffect(() => {
    wmCache.viewMode = viewMode; wmCache.sortMode = sortMode; wmCache.sortReversed = sortReversed; wmCache.assignedFilter = assignedFilter;
    wmCache.search = search; wmCache.activeStatuses = [...activeStatuses]; wmCache.collapsedGroups = [...collapsedGroups];
    wmCache.collapsedNodes = [...collapsedNodes]; wmCache.selectedId = selectedId; wmCache.detailTab = detailTab; wmCache.density = density;
  }, [viewMode, sortMode, sortReversed, assignedFilter, search, activeStatuses, collapsedGroups, collapsedNodes, selectedId, detailTab, density]);

  // When a finalized status pill (Done/Cancelled) is active, fetch finalized todos too (todo_0404).
  // Also fetch them once a finalized todo is explicitly opened (e.g. a Done todo
  // from a link), so the requested item is actually present to show (todo_0608).
  const [forcedFinalized, setForcedFinalized] = useState(false);
  const wantFinalized = activeStatuses.has('Done') || activeStatuses.has('Cancelled') || forcedFinalized;
  // soft=true is a SOFT refresh (todo_0555): re-fetch and setTodos WITHOUT flipping
  // the loading flag (which blanks the list → scroll jump) and WITHOUT clearing on a
  // transient error. React then reconciles by key and only re-draws the rows that
  // actually changed, preserving scroll position.
  const load = useCallback((soft = false) => {
    if (!soft) setLoading(true);
    setError(null);
    window.uai.todos.list(wantFinalized)
      .then(items => setTodos((items as WorkItem[]).map(t => ({ ...t, assigned: t.assigned || [], tags: t.tags || [], flags: t.flags || [] }))))
      .catch(err => { setError(err?.message || 'load failed'); if (!soft) setTodos([]); })
      .finally(() => { if (!soft) setLoading(false); });
  }, [wantFinalized]);
  useEffect(() => { load(); }, [load]);
  // Reload when a todo changes anywhere — incl. edits inside the embedded detail
  // view (title/notes/status/assignment/move/create) — so the list one-liner stays
  // current. SOFT so it doesn't blank/scroll-jump the list (todo_0555).
  useEffect(() => {
    const onChanged = () => load(true);
    window.addEventListener(TODOS_CHANGED, onChanged);
    return () => window.removeEventListener(TODOS_CHANGED, onChanged);
  }, [load]);

  const selected = useMemo(() => todos.find(t => t.id === selectedId) || null, [todos, selectedId]);

  // Resolve an assignee URI to a human display name (session tracking_id →
  // display_name). Falls back to the last URI segment when unknown (e.g. a
  // transient/exited session — see note_0014 #5 re: storing the name).
  const { getSession } = useSessionStore();
  const assigneeName = useCallback((uri: string): string => {
    if (!uri) return '?';
    const last = uri.split('/').filter(Boolean).pop() || uri;
    if (uri.includes('session/')) { const s = getSession(last); if (s?.display_name) return s.display_name; }
    return last;
  }, [getSession]);

  const loadDetail = useCallback((id: string) => {
    setDetailLoading(true); setEdited({}); setSelectedFile(null); setFileContent(null); setNotesDraft(null);
    Promise.all([window.uai.todos.read(id), window.uai.todos.provenance(id), window.uai.todos.files(id)])
      .then(([notes, prov, files]) => {
        const { preamble, sections } = parseNotes(notes as string);
        setDetail({ raw: notes as string, preamble, sections, provenance: prov as any, files: files as any });
      }).catch(() => setDetail(null)).finally(() => setDetailLoading(false));
  }, []);
  const handleSelect = useCallback((id: string) => { setSelIds(new Set()); setSelectedId(id); loadDetail(id); }, [loadDetail]);

  // Focus a specific todo when a linkified todo_#### ref is clicked elsewhere
  // (RefLink.focusTodoInWorkMgr). Consume a pending focus on mount (the pane may
  // have just been opened by the click) and listen for live focus events. Clear
  // the text search so a filter can't hide the target from the list.
  const focusTodo = useCallback((id: string) => {
    setSearch('');
    // If the requested todo isn't in the loaded set, it's almost certainly a
    // finalized (Done/Cancelled) one the default filter didn't fetch — pull them
    // in so it can render (todo_0608).
    if (!todos.some(t => t.id === id)) setForcedFinalized(true);
    handleSelect(id);
  }, [handleSelect, todos]);
  useEffect(() => {
    const pending = consumePendingTodoFocus();
    if (pending) focusTodo(pending);
    const onFocus = (e: Event) => {
      const id = (e as CustomEvent<{ id: string }>).detail?.id;
      if (id) focusTodo(id);
    };
    window.addEventListener('uai:workMgr:focusTodo', onFocus);
    return () => window.removeEventListener('uai:workMgr:focusTodo', onFocus);
  }, [focusTodo]);

  // ── mutations — routed through the Command Bus (todo.* handlers) so they are
  //    logged, hookable, and identical to the viewport `actions` an agent fires.
  const runCmd = useCallback(async (type: string, payload: Record<string, unknown>): Promise<boolean> => {
    const r = await executeCommand(type, payload);
    if (!r.ok) setError(r.error?.message || `${type} failed`);
    return r.ok;
  }, []);
  const setPriority = useCallback(async (id: string, level: string) => {
    setBusy(id); const ok = await runCmd('todo.priority', { id, level }); setBusy(null); if (ok) load(true);   // todo_0652
  }, [runCmd, load]);
  const setStatus = useCallback(async (id: string, status: string) => {
    setBusy(id); const ok = await runCmd('todo.setStatus', { id, status }); setBusy(null); if (ok) load(true);   // soft refresh — no blank/scroll-jump (todo_0555)
  }, [runCmd, load]);
  const moveTo = useCallback(async (id: string, target: string) => {
    setBusy(id); const ok = await runCmd('todo.move', { id, target }); setBusy(null); if (ok) load(true);   // soft refresh — no blank/scroll-jump (todo_0555)
  }, [runCmd, load]);
  const doAssign = useCallback(async (id: string, uri: string) => {
    if (!uri.trim()) return;
    setBusy(id); const ok = await runCmd('todo.assign', { id, uri: uri.trim() }); setBusy(null); setNewAssignee(''); if (ok) load(true);   // soft refresh — no blank/scroll-jump (todo_0555)
  }, [runCmd, load]);
  const doUnassign = useCallback(async (id: string, uri: string) => {
    setBusy(id); const ok = await runCmd('todo.unassign', { id, uri }); setBusy(null); if (ok) load(true);   // soft refresh — no blank/scroll-jump (todo_0555)
  }, [runCmd, load]);

  // ── Bulk ops for multi-select drag-drop (todo_0411). Apply the same command to
  //    every dragged id, then reload + notify ONCE. Skip no-op targets (e.g. moving
  //    a todo onto itself). Returns nothing; errors surface via runCmd's setError.
  const bulkMove = useCallback(async (ids: string[], target: string) => {
    const list = ids.filter(id => id && id !== target);
    if (!list.length) return;
    setBusy('bulk'); let anyOk = false;
    for (const id of list) if (await runCmd('todo.move', { id, target })) anyOk = true;
    // The event listener above performs the one shared soft refresh; don't also
    // call load(true) here or every bulk mutation issues two list requests.
    setBusy(null); if (anyOk) notifyTodosChanged();
  }, [runCmd]);
  const bulkStatus = useCallback(async (ids: string[], status: string) => {
    if (!ids.length) return;
    setBusy('bulk'); let anyOk = false;
    for (const id of ids) if (await runCmd('todo.setStatus', { id, status })) anyOk = true;
    setBusy(null); if (anyOk) notifyTodosChanged();
  }, [runCmd]);
  const bulkAssign = useCallback(async (ids: string[], uri: string) => {
    if (!ids.length) return;
    const nextUri = uri.trim();
    setBusy('bulk'); let anyOk = false;
    for (const id of ids) {
      const current = todos.find(t => t.id === id);
      for (const oldUri of (current?.assigned || [])) {
        if (await runCmd('todo.unassign', { id, uri: oldUri })) anyOk = true;
      }
      if (nextUri && await runCmd('todo.assign', { id, uri: nextUri })) anyOk = true;
    }
    setBusy(null); if (anyOk) notifyTodosChanged();
  }, [runCmd, todos]);
  // Bulk actions for the multi-select detail panel (todo_0558).
  const bulkComment = useCallback(async (ids: string[], text: string) => {
    if (!ids.length || !text.trim()) return;
    setBusy('bulk'); let anyOk = false;
    for (const id of ids) if (await runCmd('todo.comment', { id, text: text.trim() })) anyOk = true;
    setBusy(null); if (anyOk) notifyTodosChanged();
  }, [runCmd]);
  const bulkTrash = useCallback(async (ids: string[]) => {
    if (!ids.length) return;
    setBusy('bulk'); let anyOk = false;
    for (const id of ids) if (await runCmd('todo.trash', { id })) anyOk = true;
    setBusy(null); if (anyOk) { setSelIds(new Set()); setSelectedId(null); notifyTodosChanged(); }
  }, [runCmd]);
  // Create a NEW parent todo, then move the whole group under it. Finds the created
  // todo by name in a fresh list (create doesn't return its id to the renderer).
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
    setBusy(null); if (ok) notifyTodosChanged();
  }, [runCmd]);
  // direct-edit notes: textarea saves on blur if changed (#7)
  const saveSection = useCallback(async (heading: string) => {
    if (!selected || !detail) return;
    const body = edited[heading];
    if (body === undefined) return;
    const orig = detail.sections.find(s => s.heading === heading)?.body ?? '';
    if (body === orig) return;
    const sections = detail.sections.map(s => s.heading === heading ? { ...s, body } : s);
    const md = serializeNotes(detail.preamble, sections);
    setBusy(selected.id); const ok = await runCmd('todo.writeNotes', { id: selected.id, content: md }); setBusy(null);
    if (ok) { setDetail({ ...detail, sections }); notifyTodosChanged(); }
  }, [selected, detail, edited, runCmd]);
  // Electron disables window.prompt(), so New opens a full dialog (todo_0557).
  const [showNewDialog, setShowNewDialog] = useState(false);

  const openFile = useCallback((id: string, rel: string) => {
    setSelectedFile(rel); setFileContent(null);
    window.uai.todos.readFile(id, rel).then(r => setFileContent(r as any));
  }, []);

  // ── filter predicate (independent multi-select status set) ──────────────────
  const matches = useCallback((t: WorkItem): boolean => {
    // The explicitly-opened todo always shows, even if the current filter would
    // hide it (e.g. opening a Done todo from a link, or returning to this tab with
    // it selected). The filter applies first; the specific request overrides it
    // (todo_0608).
    if (selectedId && t.id === selectedId) return true;
    if (!activeStatuses.has(t.status)) return false;
    if (assignedFilter) {
      if (assignedFilter === NO_ASSIGNEE) { if (t.assigned.length) return false; }
      else if (!t.assigned.includes(assignedFilter)) return false;
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      if (!(`${t.id} ${formatTitle(t)}`.toLowerCase().includes(q))) return false;
    }
    return true;
  }, [activeStatuses, assignedFilter, search, selectedId]);

  const cmp = useCallback((a: WorkItem, b: WorkItem): number => {
    const base = (() => {
      switch (sortMode) {
        case 'number': return todoNum(a.id).localeCompare(todoNum(b.id), undefined, { numeric: true });
        case 'status': return (STATUS_ORDER[a.status] ?? 99) - (STATUS_ORDER[b.status] ?? 99);
        case 'priority': return (PRIORITY_ORDER[effectivePriority(a)] ?? 1) - (PRIORITY_ORDER[effectivePriority(b)] ?? 1);
        case 'title': return formatTitle(a).localeCompare(formatTitle(b));
        case 'assignee': return (assigneeLabel(a.assigned[0] || '~') || '~').localeCompare(assigneeLabel(b.assigned[0] || '~') || '~');
        case 'updated':
        // Newest-touched first. `updated` is now populated from history.log's last
        // entry (todo_0607 backend fix); fall back to `created` so todos with no
        // history still sort by a real date instead of being a no-op.
        default: return (itemDate(b) || '').localeCompare(itemDate(a) || '');
      }
    })();
    return sortReversed ? -base : base;   // reverse-sort toggle (#1)
  }, [sortMode, sortReversed]);

  // Pill set = statuses present in the data, plus Done/Cancelled always (so the
  // finalized pills are always available to toggle on, #5), in canonical order.
  const presentStatuses = useMemo(() => {
    const s = new Set<string>(['Done', 'Cancelled']); todos.forEach(t => s.add(t.status));
    return ALL_STATUSES.filter(x => s.has(x));
  }, [todos]);
  // Are we ACTIVELY narrowing? (used to auto-expand + dim ancestors in Tree view.)
  // The resting default hides only the finalized statuses (Done/Cancelled), so that
  // alone must NOT count as filtering — otherwise every tree parent is force-expanded
  // and can never be collapsed. Real narrowing = a search, an assignee filter, or
  // hiding a NON-finalized status.
  const isFiltering = useMemo(
    () => !!search.trim() || !!assignedFilter
      || presentStatuses.some(s => !FINALIZED.has(s) && !activeStatuses.has(s)),
    [presentStatuses, activeStatuses, assignedFilter, search],
  );
  const toggleStatus = (s: string) => setActiveStatuses(prev => { const n = new Set(prev); n.has(s) ? n.delete(s) : n.add(s); return n; });
  const allAssignees = useMemo(() => { const s = new Set<string>(); todos.forEach(t => t.assigned.forEach(a => s.add(a))); return Array.from(s).sort(); }, [todos]);

  // Grouping / tree model for the todo list — computed by the extracted hook so
  // TodoListView (and any other host) can render the flat/tree/kanban/assignee
  // views. WorkMgrPane still owns matches/cmp (they depend on toolbar state) and
  // consumes model.* where it needs derived collections (viewport count, detail
  // pane parent/child lookups, the move picker).
  const model = useTodoListModel(todos, matches, cmp);
  const { byKey, childrenOf, filtered } = model;

  // Collapse/expand state stays here — it's persisted across tab switches in
  // wmCache — and is passed down to TodoListView.
  const toggleGroup = (k: string) => setCollapsedGroups(p => { const n = new Set(p); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const toggleNode = (k: string) => setCollapsedNodes(p => { const n = new Set(p); n.has(k) ? n.delete(k) : n.add(k); return n; });

  const parentItem = selected?.parent ? byKey.get(selected.parent) : null;
  const childItems = selected ? (childrenOf.get(selected.rel_path || selected.id) || []) : [];
  // breadcrumb: chain of ancestors root → … → current (#8)
  const ancestors = useMemo(() => {
    const chain: WorkItem[] = [];
    let cur: WorkItem | null | undefined = selected;
    const seen = new Set<string>();
    while (cur && cur.parent && !seen.has(cur.id)) {
      seen.add(cur.id);
      const p = byKey.get(cur.parent);
      if (!p) break;
      chain.unshift(p); cur = p;
    }
    return chain;
  }, [selected, byKey]);
  // status mix across direct children (#10) — [{status, count}] in canonical order
  const childMix = useMemo(() => {
    const m = new Map<string, number>();
    childItems.forEach(c => m.set(c.status, (m.get(c.status) || 0) + 1));
    return ALL_STATUSES.filter(s => m.has(s)).map(s => ({ status: s, count: m.get(s)! }));
  }, [childItems]);
  // save the one consolidated Notes field (#11)
  const saveNotes = async () => {
    if (!selected || notesDraft === null || !detail || notesDraft === detail.raw) return;
    const ok = await runCmd('todo.writeNotes', { id: selected.id, content: notesDraft });
    if (ok) { setDetail({ ...detail, raw: notesDraft }); notifyTodosChanged(); }
  };
  // vertical drag for the Notes/Files boundary in the Contents tab (#2)
  const onNotesResize = (e: React.MouseEvent) => {
    e.preventDefault();
    const startY = e.clientY; const start = notesHeight;
    document.body.style.cursor = 'row-resize'; document.body.style.userSelect = 'none';
    const onMove = (ev: MouseEvent) => setNotesHeight(Math.max(80, Math.min(start + (ev.clientY - startY), 640)));
    const onUp = () => {
      document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp);
      document.body.style.cursor = ''; document.body.style.userSelect = '';
    };
    document.addEventListener('mousemove', onMove); document.addEventListener('mouseup', onUp);
  };

  // Assignee dropdown options, ordered per spec #6.2: Projects → Teams → active
  // sessions (those with an open tab first) → stopped sessions (open-tab first,
  // then by last activity). Each maps to its uai:// URI.
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

  // Set assignee from the title-bar dropdown — single-value semantics (like Status):
  // clear existing assignees, then assign the chosen one ('' = unassigned).
  const setAssignee = async (id: string, uri: string) => {
    setBusy(id);
    for (const a of (selected?.assigned || [])) await executeCommand('todo.unassign', { id, uri: a });
    if (uri) await executeCommand('todo.assign', { id, uri });
    setBusy(null); load(true);   // soft refresh (todo_0555)
  };
  // Files → Artifacts: drop spec metadata (notes/origin/history/assigned/*.status/.tag) + dirs.
  const artifacts = (detail?.files || []).filter(f => !f.isDir && !isSpecFile(f.rel));

  // Viewport reporter — exposes this Mgr's data (state) and invocable actions
  // (each maps to a todo.* Command Bus command) to describeViewport() / agents /
  // the e2e harness. First tool Mgr to join the component-API surface.
  useViewport('work_mgr', () => ({
    visible: true,
    label: 'Work Mgr',
    state: {
      view: viewMode, group: groupMode, sort: sortMode,
      activeStatuses: Array.from(activeStatuses), assignedFilter,
      total: todos.length, visible: filtered.length, selectedId,
      // The SELECTED todo's actual state (note_0014 #3) with assignees resolved
      // to display names (note_0014 #4).
      selected: selected ? {
        id: selected.id,
        title: formatTitle(selected),
        status: selected.status,
        assigned: (selected.assigned || []).map(assigneeName),
        tags: selected.tags || [],
        flags: selected.flags || [],
      } : null,
    },
    actions: selected ? [
      { id: 'mark_done', command: 'todo.setStatus', payload: { id: selected.id, status: 'Done' }, label: 'Mark Done' },
      { id: 'mark_cancelled', command: 'todo.setStatus', payload: { id: selected.id, status: 'Cancelled' }, label: 'Cancel' },
      { id: 'mark_in_progress', command: 'todo.setStatus', payload: { id: selected.id, status: 'In_Progress' }, label: 'Start' },
    ] : [],
    children: [],
  }));

  return (
    <div className="work-mgr" data-tab-id={tabId}>
      {/* This pane owns its OWN title bar instance (no title bar is shared across
          peer panes; the generic Workspace bar no longer renders for managers). */}
      <div className="context-mgr-titlebar">
        <TabNavArrows />
        <span className="context-mgr-titlebar-title">Work Manager</span>
        <button className="wm-action-btn" onClick={() => setShowNewDialog(true)} title="Create a new todo">+ New</button>
        <button className="wm-action-btn" onClick={() => load()} title="Reload from disk">Refresh</button>
        <span style={{ flex: 1 }} />
        <div className="wm-search">
          <span className="wm-search-ic">🔍</span>
          <input className="wm-search-input" type="text" value={search} placeholder="Search todos…"
            onChange={e => setSearch(e.target.value)} />
          {search && <button className="wm-search-clear" onClick={() => setSearch('')} title="Clear search">✕</button>}
        </div>
      </div>
      <div className="wm-body">
        {error && <div className="traits-mgr-error">{error}</div>}
        <div className="wm-split">
          {/* Left COLUMN = filter bar + list, sized together (draggable). Filters
              live INSIDE the list column so they read as the list's controls, AND
              the detail/todo-viewer beside them spans the FULL height (no dead band
              above it — room to grow). */}
          <div className="wm-list-col" style={{ width: listResize.width }}>
            <div className="wm-controls">
              <div className="wm-seg">
                {(['flat', 'tree', 'kanban', 'assignee'] as ViewMode[]).map(m => (
                  <button key={m} className={`filter-pill ${viewMode === m ? 'active' : ''}`} onClick={() => setViewMode(m)}>
                    {m === 'flat' ? 'Flat' : m === 'tree' ? 'Tree' : m === 'kanban' ? 'Kanban' : 'By Assigned To'}
                  </button>
                ))}
              </div>
              {/* Row density: compact (1 line) vs expanded (+ summary/assignee/tags) — todo_0556 */}
              <button className="filter-pill" title="Toggle row density"
                onClick={() => setDensity(d => (d === 'compact' ? 'expanded' : 'compact'))}>
                {density === 'compact' ? '☰ Compact' : '≣ Expanded'}
              </button>
              <SortMenu
                fields={[
                  { value: 'updated', label: 'Updated' },
                  { value: 'number', label: 'Number' },
                  { value: 'status', label: 'Status' },
                  { value: 'priority', label: 'Priority' },
                  { value: 'title', label: 'Title' },
                  { value: 'assignee', label: 'Assigned to' },
                ]}
                value={sortMode}
                ascending={sortMode === 'updated' ? sortReversed : !sortReversed}
                onSelect={(v) => {
                  // Same field → flip direction; different field → switch to it.
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
            </div>
            <TodoListView
              model={model} viewMode={viewMode} selectedId={selectedId} onSelect={handleSelect}
              selIds={selIds} onSelIdsChange={setSelIds}
              onReparent={bulkMove} onSetStatus={bulkStatus} onReassign={bulkAssign}
              matches={matches} isFiltering={isFiltering} search={search}
              kanbanNest={kanbanNest} busy={busy} loading={loading} error={error}
              collapsedGroups={collapsedGroups} toggleGroup={toggleGroup}
              collapsedNodes={collapsedNodes} toggleNode={toggleNode}
              density={density}
              viewportId="work_mgr_todo_list"
            />
          </div>

          <div className="panel-resize-x" onMouseDown={listResize.onMouseDown} title="Drag to resize" />

          {/* Right detail — top: fields; bottom half: files (#13) */}
          <div className="wm-detail">
            {selIds.size > 1 ? (
              <TodoBulkPanel
                ids={[...selIds]} todos={todos} statuses={ALL_STATUSES}
                assigneeOptions={assigneeOptions} assigneeGroups={ASSIGNEE_GROUPS} busy={busy === 'bulk'}
                onStatus={s => bulkStatus([...selIds], s)}
                onAssign={u => bulkAssign([...selIds], u)}
                onComment={t => bulkComment([...selIds], t)}
                onMove={p => bulkMove([...selIds], p)}
                onCreateParent={n => createParentAndMove(n, [...selIds])}
                onDelete={() => bulkTrash([...selIds])}
                onClear={() => setSelIds(new Set())}
              />
            ) : !selected ? <div className="traits-mgr-empty">Select a work item</div> : (
              <TodoItemView
                viewportId="work_mgr_todo_view"
                todo={selected as any}
                allTodos={todos as any}
                search={search}
                onSelect={handleSelect}
                statusEditor={<StatusSelect status={selected.status} onChange={s => setStatus(selected.id, s)} />}
                priorityEditor={<PrioritySelect priority={effectivePriority(selected)} onChange={p => setPriority(selected.id, p)} />}
                assigneeEditor={
                  <select className="wm-status-select" value={selected.assigned[0] || ''} onChange={e => setAssignee(selected.id, e.target.value)} title="Assign to a project / team / session" disabled={busy === selected.id}>
                    <option value="">unassigned</option>
                    {ASSIGNEE_GROUPS.map(grp => {
                      const opts = assigneeOptions.filter(o => o.grp === grp);
                      return opts.length ? <optgroup key={grp} label={grp}>{opts.map(o => <option key={o.uri} value={o.uri}>{o.label}</option>)}</optgroup> : null;
                    })}
                    {selected.assigned[0] && !assigneeOptions.some(o => o.uri === selected.assigned[0]) && (
                      <option value={selected.assigned[0]}>{assigneeLabel(selected.assigned[0])}</option>
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
      {showNewDialog && (
        <NewTodoDialog
          todos={todos}
          onClose={() => setShowNewDialog(false)}
          toastFn={showToast}
          onCreated={(id, createdStatus) => {
            setSearch('');
            if (FINALIZED.has(createdStatus)) setForcedFinalized(true);
            if (id) handleSelect(id);
            load(true);   // soft refresh (todo_0555)
          }}
        />
      )}
    </div>
  );
}
