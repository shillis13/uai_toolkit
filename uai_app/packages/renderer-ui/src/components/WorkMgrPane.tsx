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
const TREE_GROUP_COLORS = ['#2ac3de', '#9ece6a', '#e0af68', '#f7768e', '#bb9af7', '#ff9e64', '#73daca', '#7aa2f7'];

// Module-level view-state cache — persists the Work Mgr's selection + view across
// leaving and returning the tab (the pane unmounts on tab switch). Single instance
// since the Work Mgr is a singleton. (todo_0407)
const wmCache: {
  viewMode?: string; sortMode?: string; assignedFilter?: string; search?: string;
  activeStatuses?: string[]; collapsedGroups?: string[]; expandedNodes?: string[];
  selectedId?: string | null; detailTab?: string;
} = {};
import { useViewport } from '../viewport';
import { executeCommand } from '../utils/execute-command';
import { TabNavArrows } from './TabNavArrows';
import TodoItemView from './TodoItemView';
import { usePanelResize } from '../hooks/usePanelResize';
import { useCardStore, useAppStateStore } from '../stores';
import { useSessionStore } from '../stores/session-store';

interface WorkItem {
  id: string;
  rel_path?: string;
  status: string;
  tags: string[];
  flags: string[];
  assigned: string[];
  project?: string | null;
  parent?: string | null;
  children?: string[];
  title?: string;
  summary?: string;
  updated?: string;
  created?: string;
}

interface WorkMgrPaneProps { tabId?: string; }

type ViewMode = 'flat' | 'tree' | 'kanban' | 'assignee';
type GroupMode = 'none' | 'status' | 'project' | 'assigned';
type SortMode = 'updated' | 'number' | 'status' | 'title' | 'assignee';

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

const STATUS_ORDER: Record<string, number> = {
  'In_Progress': 0, 'Blocked': 1, 'Reviewing': 2, 'Accepting': 3, 'Ready': 4,
  'Needs_Derivation': 5, 'Needs_Research': 6, 'Triaging': 7, 'Done': 8, 'Cancelled': 9,
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
const NO_PROJECT = '(no project)';
const NO_ASSIGNEE = '(unassigned)';

const statusColor = (s: string): string => STATUS_COLORS[s] || 'var(--text-muted)';
const statusLabel = (s: string): string => (s || '').replace(/_/g, ' ');

function todoNum(id: string): string {
  const m = (id || '').match(/(?:todo|task)_(\d+)/);
  return m ? m[1] : id;
}
function formatTitle(item: WorkItem): string {
  // Prefer an explicit title, else the id-derived slug. Either way STRIP a
  // leading todo_####_ / task_####_ prefix — the number is shown separately (as
  // the colored TodoId), so repeating it in the name is redundant. This also
  // normalizes the 2 todos whose title lacked the prefix into the same shape.
  const raw = (item.title && item.title.trim()) ? item.title : (item.id || '');
  return raw.replace(/^(?:todo|task)_\d+_?/, '').replace(/_/g, ' ').trim();
}
function assigneeLabel(uri: string): string {
  if (!uri) return '?';
  const seg = uri.split('/').filter(Boolean);
  return seg[seg.length - 1] || uri;
}
function fmtDate(iso?: string): string {
  if (!iso) return '';
  try { return new Date(iso).toLocaleDateString(undefined, { month: 'short', day: 'numeric' }); } catch { return ''; }
}
function fmtTs(ts: string): string { try { return new Date(ts).toLocaleString(); } catch { return ts; } }
function fmtSize(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}
// last-touched date, falling back to created when updated is absent (older todos).
const itemDate = (t: { updated?: string; created?: string }): string | undefined => t.updated || t.created;

// Renders a todo id so it's clearly a todo_#### — dim "todo_" prefix, bright number.
function TodoId({ id, big }: { id: string; big?: boolean }): JSX.Element {
  return (
    <span className={`wm-num${big ? ' wm-num-lg' : ''}`} title={id}>{todoNum(id)}</span>
  );
}
// 2-3 letter status code chip, colored by status.
function StatusCode({ status }: { status: string }): JSX.Element {
  return <span className="wm-status-code" style={{ color: statusColor(status) }} title={statusLabel(status)}>{statusAbbr(status)}</span>;
}

// Wrap occurrences of `query` (case-insensitive) in <mark> for search highlighting.
function highlight(text: string, query: string): ReactNode {
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
  const cardStore = useCardStore();
  const { appState } = useAppStateStore();
  const [todos, setTodos] = useState<WorkItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  const [viewMode, setViewMode] = useState<ViewMode>((wmCache.viewMode as ViewMode) ?? 'tree');
  // groupMode fixed to status (Kanban groups by status); no group dropdown.
  const [groupMode] = useState<GroupMode>('status');
  const [sortMode, setSortMode] = useState<SortMode>((wmCache.sortMode as SortMode) ?? 'updated');
  // projectFilter retired from the bar (assignee subsumes it); kept inert for matches().
  const [projectFilter] = useState<string>('');
  const [assignedFilter, setAssignedFilter] = useState<string>(wmCache.assignedFilter ?? '');
  const [search, setSearch] = useState<string>(wmCache.search ?? '');   // free-text search over id + title
  // Status filter is an independent multi-select pill set (#2). Done/Cancelled ARE
  // statuses (#5) — they're pills too, just deselected by default.
  const [activeStatuses, setActiveStatuses] = useState<Set<string>>(() => new Set(wmCache.activeStatuses ?? ALL_STATUSES.filter(s => !FINALIZED.has(s))));
  const [kanbanNest, setKanbanNest] = useState(false); // group kanban items under (dimmed) parent context

  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(() => new Set(wmCache.collapsedGroups ?? []));
  const [expandedNodes, setExpandedNodes] = useState<Set<string>>(() => new Set(wmCache.expandedNodes ?? []));

  const [selectedId, setSelectedId] = useState<string | null>(wmCache.selectedId ?? null);
  const [detail, setDetail] = useState<DetailState | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [edited, setEdited] = useState<Record<string, string>>({});
  const [newAssignee, setNewAssignee] = useState('');
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileContent, setFileContent] = useState<{ content?: string; truncated?: boolean; error?: string } | null>(null);
  const [detailTab, setDetailTab] = useState<DetailTab>((wmCache.detailTab as DetailTab) ?? 'contents');
  const [notesDraft, setNotesDraft] = useState<string | null>(null); // edit buffer for the one Notes field
  const [notesHeight, setNotesHeight] = useState(200); // adjustable Notes/Files boundary (#2)
  // drag-to-reparent: dragId = row being dragged; dragOverId = current drop target.
  const [dragId, setDragId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  // Persist view state to the module cache so it survives leaving+returning the tab. (todo_0407)
  useEffect(() => {
    wmCache.viewMode = viewMode; wmCache.sortMode = sortMode; wmCache.assignedFilter = assignedFilter;
    wmCache.search = search; wmCache.activeStatuses = [...activeStatuses]; wmCache.collapsedGroups = [...collapsedGroups];
    wmCache.expandedNodes = [...expandedNodes]; wmCache.selectedId = selectedId; wmCache.detailTab = detailTab;
  }, [viewMode, sortMode, assignedFilter, search, activeStatuses, collapsedGroups, expandedNodes, selectedId, detailTab]);

  // When a finalized status pill (Done/Cancelled) is active, fetch finalized todos too (todo_0404).
  const wantFinalized = activeStatuses.has('Done') || activeStatuses.has('Cancelled');
  const load = useCallback(() => {
    setLoading(true); setError(null);
    window.uai.todos.list(wantFinalized)
      .then(items => setTodos((items as WorkItem[]).map(t => ({ ...t, assigned: t.assigned || [], tags: t.tags || [], flags: t.flags || [] }))))
      .catch(err => { setError(err?.message || 'load failed'); setTodos([]); })
      .finally(() => setLoading(false));
  }, [wantFinalized]);
  useEffect(() => { load(); }, [load]);

  const byKey = useMemo(() => { const m = new Map<string, WorkItem>(); for (const t of todos) m.set(t.rel_path || t.id, t); return m; }, [todos]);
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
  const handleSelect = useCallback((id: string) => { setSelectedId(id); loadDetail(id); }, [loadDetail]);

  // ── mutations — routed through the Command Bus (todo.* handlers) so they are
  //    logged, hookable, and identical to the viewport `actions` an agent fires.
  const runCmd = useCallback(async (type: string, payload: Record<string, unknown>): Promise<boolean> => {
    const r = await executeCommand(type, payload);
    if (!r.ok) setError(r.error?.message || `${type} failed`);
    return r.ok;
  }, []);
  const setStatus = useCallback(async (id: string, status: string) => {
    setBusy(id); const ok = await runCmd('todo.setStatus', { id, status }); setBusy(null); if (ok) load();
  }, [runCmd, load]);
  const moveTo = useCallback(async (id: string, target: string) => {
    setBusy(id); const ok = await runCmd('todo.move', { id, target }); setBusy(null); if (ok) load();
  }, [runCmd, load]);
  const doAssign = useCallback(async (id: string, uri: string) => {
    if (!uri.trim()) return;
    setBusy(id); const ok = await runCmd('todo.assign', { id, uri: uri.trim() }); setBusy(null); setNewAssignee(''); if (ok) load();
  }, [runCmd, load]);
  const doUnassign = useCallback(async (id: string, uri: string) => {
    setBusy(id); const ok = await runCmd('todo.unassign', { id, uri }); setBusy(null); if (ok) load();
  }, [runCmd, load]);
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
    if (ok) setDetail({ ...detail, sections });
  }, [selected, detail, edited, runCmd]);
  // Electron disables window.prompt(), so New opens an inline input instead.
  const [newTodoName, setNewTodoName] = useState<string | null>(null);
  const createTodo = useCallback(async () => {
    const name = (newTodoName || '').trim();
    if (!name) { setNewTodoName(null); return; }
    if (await runCmd('todo.create', { name })) load();
    setNewTodoName(null);
  }, [runCmd, load, newTodoName]);

  const openFile = useCallback((id: string, rel: string) => {
    setSelectedFile(rel); setFileContent(null);
    window.uai.todos.readFile(id, rel).then(r => setFileContent(r as any));
  }, []);

  // ── filter predicate (independent multi-select status set) ──────────────────
  const matches = useCallback((t: WorkItem): boolean => {
    if (!activeStatuses.has(t.status)) return false;
    if (projectFilter && (t.project || NO_PROJECT) !== projectFilter) return false;
    if (assignedFilter) {
      if (assignedFilter === NO_ASSIGNEE) { if (t.assigned.length) return false; }
      else if (!t.assigned.includes(assignedFilter)) return false;
    }
    if (search.trim()) {
      const q = search.trim().toLowerCase();
      if (!(`${t.id} ${formatTitle(t)}`.toLowerCase().includes(q))) return false;
    }
    return true;
  }, [activeStatuses, projectFilter, assignedFilter, search]);

  const cmp = useCallback((a: WorkItem, b: WorkItem): number => {
    switch (sortMode) {
      case 'number': return todoNum(a.id).localeCompare(todoNum(b.id), undefined, { numeric: true });
      case 'status': return (STATUS_ORDER[a.status] ?? 99) - (STATUS_ORDER[b.status] ?? 99);
      case 'title': return formatTitle(a).localeCompare(formatTitle(b));
      case 'assignee': return (assigneeLabel(a.assigned[0] || '~') || '~').localeCompare(assigneeLabel(b.assigned[0] || '~') || '~');
      case 'updated':
      default: return (b.updated || '').localeCompare(a.updated || '');
    }
  }, [sortMode]);

  // Pill set = statuses present in the data, plus Done/Cancelled always (so the
  // finalized pills are always available to toggle on, #5), in canonical order.
  const presentStatuses = useMemo(() => {
    const s = new Set<string>(['Done', 'Cancelled']); todos.forEach(t => s.add(t.status));
    return ALL_STATUSES.filter(x => s.has(x));
  }, [todos]);
  // are we narrowing? (used to auto-expand + dim ancestors in Tree view, #3)
  const isFiltering = useMemo(
    () => presentStatuses.some(s => !activeStatuses.has(s)) || !!projectFilter || !!assignedFilter,
    [presentStatuses, activeStatuses, projectFilter, assignedFilter],
  );
  const toggleStatus = (s: string) => setActiveStatuses(prev => { const n = new Set(prev); n.has(s) ? n.delete(s) : n.add(s); return n; });
  const allAssignees = useMemo(() => { const s = new Set<string>(); todos.forEach(t => t.assigned.forEach(a => s.add(a))); return Array.from(s).sort(); }, [todos]);

  const filtered = useMemo(() => todos.filter(matches).sort(cmp), [todos, matches, cmp]);

  // flat grouping
  const groups = useMemo(() => {
    if (groupMode === 'none') return { '': filtered };
    const map: Record<string, WorkItem[]> = {};
    for (const t of filtered) {
      const keys = groupMode === 'status' ? [t.status]
        : groupMode === 'project' ? [t.project || NO_PROJECT]
        : (t.assigned.length ? t.assigned : [NO_ASSIGNEE]);
      for (const k of keys) (map[k] ||= []).push(t);
    }
    return map;
  }, [filtered, groupMode]);
  const sortedGroupKeys = useMemo(() => {
    const keys = Object.keys(groups);
    if (groupMode === 'status') return keys.sort((a, b) => (STATUS_ORDER[a] ?? 99) - (STATUS_ORDER[b] ?? 99));
    return keys.sort((a, b) => a.localeCompare(b));
  }, [groups, groupMode]);

  // By-Assigned-To view (#3): Kanban-style, but each group is an assignee
  // (project / team / session) rather than a status.
  const assigneeGroups = useMemo(() => {
    const map: Record<string, WorkItem[]> = {};
    for (const t of filtered) {
      const keys = t.assigned.length ? t.assigned : [NO_ASSIGNEE];
      for (const k of keys) (map[k] ||= []).push(t);
    }
    return map;
  }, [filtered]);
  const assigneeGroupKeys = useMemo(() => Object.keys(assigneeGroups).sort((a, b) => {
    if (a === NO_ASSIGNEE) return 1; if (b === NO_ASSIGNEE) return -1;
    return assigneeLabel(a).localeCompare(assigneeLabel(b));
  }), [assigneeGroups]);
  const assigneeColor = (uri: string): string => {
    const pal = ['var(--accent-cyan)', 'var(--accent-green)', 'var(--accent-purple)', 'var(--accent-blue)', 'var(--accent-orange)', 'var(--accent-yellow)'];
    let h = 0; for (let i = 0; i < uri.length; i++) h = (h * 31 + uri.charCodeAt(i)) >>> 0;
    return pal[h % pal.length];
  };

  // tree (#9: hierarchy priority — finalized nodes sit under parent when shown)
  const childrenOf = useMemo(() => {
    const m = new Map<string, WorkItem[]>();
    for (const t of todos) { const pk = t.parent || '__root__'; (m.get(pk) || m.set(pk, []).get(pk)!).push(t); }
    for (const arr of m.values()) arr.sort(cmp);
    return m;
  }, [todos, cmp]);
  const rootItems = useMemo(() => todos.filter(t => !t.parent || !byKey.has(t.parent)).sort(cmp), [todos, byKey, cmp]);
  const subtreeMatches = useCallback((t: WorkItem): boolean => {
    if (matches(t)) return true;
    return (childrenOf.get(t.rel_path || t.id) || []).some(subtreeMatches);
  }, [matches, childrenOf]);

  const toggleGroup = (k: string) => setCollapsedGroups(p => { const n = new Set(p); n.has(k) ? n.delete(k) : n.add(k); return n; });
  const toggleNode = (k: string) => setExpandedNodes(p => { const n = new Set(p); n.has(k) ? n.delete(k) : n.add(k); return n; });

  // tooltip = info ABOUT the todo (#7), not instructions
  const rowTip = (t: WorkItem): string => {
    const d = itemDate(t);
    return [
      t.id,
      `status: ${statusLabel(t.status)}`,
      t.assigned.length ? `assigned: ${t.assigned.map(assigneeLabel).join(', ')}` : 'unassigned',
      t.project ? `project: ${t.project}` : '',
      d ? `updated: ${fmtTs(d)}` : '',
      formatTitle(t),
    ].filter(Boolean).join('\n');
  };
  // ── row (shared) ────────────────────────────────────────────────────────────
  const renderRow = (t: WorkItem, depth: number, hasKids: boolean, expanded: boolean, dimmed = false): JSX.Element => {
    const key = t.rel_path || t.id;
    const d = itemDate(t);
    return (
      <div key={key}
        className={`wm-row ${selectedId === t.id ? 'selected' : ''} ${dragOverId === t.id && dragId !== t.id ? 'drop-target' : ''} ${dimmed ? 'wm-dimmed' : ''}`}
        draggable
        onClick={() => handleSelect(t.id)}
        onDragStart={e => { e.stopPropagation(); setDragId(t.id); e.dataTransfer.effectAllowed = 'move'; }}
        onDragOver={e => { if (dragId && dragId !== t.id) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (dragOverId !== t.id) setDragOverId(t.id); } }}
        onDragLeave={() => { if (dragOverId === t.id) setDragOverId(null); }}
        onDrop={e => { e.preventDefault(); e.stopPropagation(); if (dragId && dragId !== t.id) moveTo(dragId, t.id); setDragId(null); setDragOverId(null); }}
        onDragEnd={() => { setDragId(null); setDragOverId(null); }}
        title={rowTip(t)}
        style={{ paddingLeft: 4 + depth * 14, opacity: busy === t.id ? 0.5 : (dragId === t.id ? 0.4 : 1) }}>
        {viewMode === 'tree' && (
          <span className="wm-caret" onClick={e => { e.stopPropagation(); if (hasKids) toggleNode(key); }}
            style={{ cursor: hasKids ? 'pointer' : 'default' }}>{hasKids ? (expanded ? '▾' : '▸') : ''}</span>
        )}
        {/* status code redundant in Kanban (the section is the status) */}
        {viewMode !== 'kanban' && <StatusCode status={t.status} />}
        <TodoId id={t.id} />
        <span className="wm-title">{highlight(formatTitle(t), search)}</span>
        <span className="wm-row-meta">
          {t.flags.includes('high_priority') && <span className="todo-mgr-flag-badge" title="High Priority">!</span>}
          {d && <span className="wm-date" title={`updated ${fmtTs(d)}`}>{fmtDate(d)}</span>}
        </span>
      </div>
    );
  };
  const renderTreeNode = (t: WorkItem, depth: number): JSX.Element[] => {
    const key = t.rel_path || t.id;
    const kids = (childrenOf.get(key) || []).filter(subtreeMatches);
    const hasKids = kids.length > 0;
    // #3: under an active filter, auto-expand parents with matching children, and
    // dim a parent that's only shown to reveal a matching descendant.
    const expanded = expandedNodes.has(key) || (isFiltering && hasKids);
    const dimmed = isFiltering && !matches(t);
    const out = [renderRow(t, depth, hasKids, expanded, dimmed)];
    if (hasKids && expanded) for (const k of kids) out.push(...renderTreeNode(k, depth + 1));
    return out;
  };

  // Kanban "Nest": within a status section, group items under their parent. The
  // parent is shown DIMMED as context (it may live in a different status section);
  // roots render normally. (#kanban list-2.3)
  const renderKanbanNested = (items: WorkItem[]): JSX.Element => {
    const byParent = new Map<string, WorkItem[]>();
    for (const t of items) { const pk = t.parent || '__none__'; (byParent.get(pk) || byParent.set(pk, []).get(pk)!).push(t); }
    const blocks: JSX.Element[] = [];
    for (const [pk, kids] of byParent) {
      if (pk === '__none__') { for (const t of kids) blocks.push(renderRow(t, 0, false, false)); continue; }
      const parent = byKey.get(pk);
      blocks.push(
        <div key={`ctx-${pk}`} className="wm-kan-parentctx" onClick={() => parent && handleSelect(parent.id)} title="parent (context — may be in another status)">
          ↳ {parent ? `todo_${todoNum(parent.id)} · ${formatTitle(parent).slice(0, 44)}` : pk}
        </div>
      );
      for (const t of kids) blocks.push(renderRow(t, 1, false, false));
    }
    return <div className="wm-kan-items">{blocks}</div>;
  };

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
    if (ok) setDetail({ ...detail, raw: notesDraft });
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
    setBusy(null); load();
  };
  // Files → Artifacts: drop spec metadata (notes/origin/history/assigned/*.status/.tag) + dirs.
  const artifacts = (detail?.files || []).filter(f => !f.isDir && !isSpecFile(f.rel));
  // Indented hierarchy options for the move picker (tree-ish; full tree picker is a follow-up).
  const moveOptions = (): JSX.Element[] => {
    const out: JSX.Element[] = [];
    const walk = (items: WorkItem[], depth: number) => {
      for (const t of items) {
        if (t.id === selected?.id) continue;
        out.push(<option key={t.id} value={t.id}>{' '.repeat(depth * 2)}{depth > 0 ? '└ ' : ''}todo_{todoNum(t.id)} · {formatTitle(t).slice(0, 36)}</option>);
        walk(childrenOf.get(t.rel_path || t.id) || [], depth + 1);
      }
    };
    walk(rootItems, 0);
    return out;
  };

  // Viewport reporter — exposes this Mgr's data (state) and invocable actions
  // (each maps to a todo.* Command Bus command) to describeViewport() / agents /
  // the e2e harness. First tool Mgr to join the component-API surface.
  useViewport('work_mgr', () => ({
    visible: true,
    label: 'Work Mgr',
    state: {
      view: viewMode, group: groupMode, sort: sortMode,
      activeStatuses: Array.from(activeStatuses), projectFilter, assignedFilter,
      total: todos.length, visible: filtered.length, selectedId,
      // The SELECTED todo's actual state (note_0014 #3) with assignees resolved
      // to display names (note_0014 #4).
      selected: selected ? {
        id: selected.id,
        title: formatTitle(selected),
        status: selected.status,
        project: selected.project || null,
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
        {newTodoName === null
          ? <button className="wm-action-btn" onClick={() => setNewTodoName('')} title="Create a new todo">+ New</button>
          : <span className="wm-new-inline">
              <input className="wm-search-input" autoFocus value={newTodoName} placeholder="New todo title…"
                onChange={e => setNewTodoName(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') createTodo(); if (e.key === 'Escape') setNewTodoName(null); }} />
              <button className="wm-action-btn" onClick={createTodo}>Create</button>
              <button className="wm-action-btn" onClick={() => setNewTodoName(null)}>✕</button>
            </span>}
        <button className="wm-action-btn" onClick={load} title="Reload from disk">Refresh</button>
        <span style={{ flex: 1 }} />
        <div className="wm-search">
          <span className="wm-search-ic">🔍</span>
          <input className="wm-search-input" type="text" value={search} placeholder="Search todos…"
            onChange={e => setSearch(e.target.value)} />
          {search && <button className="wm-search-clear" onClick={() => setSearch('')} title="Clear search">✕</button>}
        </div>
      </div>
      {/* Control bar. Pills only for the fixed status enum; project/assignee are
          dropdowns. */}
      <div className="wm-controls">
        <div className="wm-seg">
          {(['flat', 'tree', 'kanban', 'assignee'] as ViewMode[]).map(m => (
            <button key={m} className={`filter-pill ${viewMode === m ? 'active' : ''}`} onClick={() => setViewMode(m)}>
              {m === 'flat' ? 'Flat' : m === 'tree' ? 'Tree' : m === 'kanban' ? 'Kanban' : 'By Assigned To'}
            </button>
          ))}
        </div>
        <label className="wm-dd">Sort
          <select value={sortMode} onChange={e => setSortMode(e.target.value as SortMode)}>
            <option value="updated">Updated</option><option value="number">Number</option>
            <option value="status">Status</option><option value="title">Title</option>
            <option value="assignee">Assigned to</option>
          </select>
        </label>
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

      {/* Status filter — independent multi-select pills (#2); Done/Cancelled are
          statuses too (#5), just deselected by default. */}
      <div className="wm-statusbar">
        <button className={`filter-pill ${presentStatuses.every(s => activeStatuses.has(s)) ? 'active' : ''}`}
          onClick={() => setActiveStatuses(new Set(presentStatuses))} title="Select all statuses">All</button>
        {presentStatuses.map(s => {
          const on = activeStatuses.has(s);
          return (
            <button key={s} className={`filter-pill ${on ? 'active' : ''}`} onClick={() => toggleStatus(s)}
              style={{ color: on ? statusColor(s) : 'var(--text-muted)' }} title={`${statusLabel(s)} — click to toggle`}>
              {statusLabel(s)}
            </button>
          );
        })}
      </div>

      <div className="wm-body">
        {error && <div className="traits-mgr-error">{error}</div>}
        <div className="wm-split">
          {/* Left list (narrower, #12) — draggable width */}
          <div className="wm-list" style={{ width: `${listResize.width}px` }}>
            {loading && <div className="traits-mgr-loading" style={{ padding: 16 }}>Loading...</div>}
            {/* Flat — plain sorted list, no hierarchy */}
            {!loading && viewMode === 'flat' && filtered.map(t => renderRow(t, 0, false, false))}
            {/* Tree — real hierarchy. Parent-child clusters get an outlined/colored
                group box (like Kanban/Assigned sections); standalone roots render plain. */}
            {!loading && viewMode === 'tree' && (() => {
              const roots = rootItems.filter(subtreeMatches);
              const out: ReactNode[] = []; let gi = 0;
              for (const t of roots) {
                const key = t.rel_path || t.id;
                const kids = (childrenOf.get(key) || []).filter(subtreeMatches);
                const nodes = renderTreeNode(t, 0);
                if (kids.length === 0) { out.push(...nodes); }
                else {
                  const col = TREE_GROUP_COLORS[gi++ % TREE_GROUP_COLORS.length];
                  out.push(<div key={`grp-${key}`} className="wm-kan-section wm-tree-group" style={{ borderColor: col }}>{nodes}</div>);
                }
              }
              return out;
            })()}
            {/* Kanban — status sections (colored header, border, light bg) */}
            {!loading && viewMode === 'kanban' && sortedGroupKeys.map(key => {
              const items = groups[key];
              const collapsed = collapsedGroups.has(key);
              const col = statusColor(key);
              return (
                <div key={key} className="wm-kan-section" style={{ borderColor: col }}>
                  <div className="wm-kan-header" onClick={() => toggleGroup(key)}
                    style={{ background: `color-mix(in srgb, ${col} 14%, transparent)`, borderBottomColor: col }}>
                    <span className="wm-kan-chev" style={{ color: col }}>{collapsed ? '▸' : '▾'}</span>
                    <span className="wm-kan-title" style={{ color: col }}>{statusLabel(key)} <span className="wm-kan-count">({items.length})</span></span>
                  </div>
                  {!collapsed && (kanbanNest ? renderKanbanNested(items) : <div className="wm-kan-items">{items.map(t => renderRow(t, 0, false, false))}</div>)}
                </div>
              );
            })}
            {/* By Assigned To — Kanban-style, each section is a project/team/session (#3) */}
            {!loading && viewMode === 'assignee' && assigneeGroupKeys.map(key => {
              const items = assigneeGroups[key];
              const collapsed = collapsedGroups.has(key);
              const col = key === NO_ASSIGNEE ? 'var(--text-muted)' : assigneeColor(key);
              const label = key === NO_ASSIGNEE ? '(unassigned)' : assigneeLabel(key);
              return (
                <div key={key} className="wm-kan-section" style={{ borderColor: col }}>
                  <div className="wm-kan-header" onClick={() => toggleGroup(key)}
                    style={{ background: `color-mix(in srgb, ${col} 14%, transparent)`, borderBottomColor: col }}>
                    <span className="wm-kan-chev" style={{ color: col }}>{collapsed ? '▸' : '▾'}</span>
                    <span className="wm-kan-title" style={{ color: col }} title={key}>{label} <span className="wm-kan-count">({items.length})</span></span>
                  </div>
                  {!collapsed && <div className="wm-kan-items">{items.map(t => renderRow(t, 0, false, false))}</div>}
                </div>
              );
            })}
            {!loading && filtered.length === 0 && !error && <div className="traits-mgr-empty">No work items match.</div>}
          </div>

          <div className="panel-resize-x" onMouseDown={listResize.onMouseDown} title="Drag to resize" />

          {/* Right detail — top: fields; bottom half: files (#13) */}
          <div className="wm-detail">
            {!selected ? <div className="traits-mgr-empty">Select a work item</div> : (
              <TodoItemView
                todo={selected as any}
                allTodos={todos as any}
                search={search}
                onSelect={handleSelect}
                statusEditor={<StatusSelect status={selected.status} onChange={s => setStatus(selected.id, s)} />}
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
                  <select className="wm-input wm-move-inline" value="" onChange={e => { if (e.target.value) moveTo(selected.id, e.target.value); }} title="Re-parent this todo">
                    <option value="">choose a parent…</option>
                    {moveOptions()}
                    <option value="root">— move to root (top-level) —</option>
                  </select>
                }
              />
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
