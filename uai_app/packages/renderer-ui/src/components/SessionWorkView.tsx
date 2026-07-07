/**
 * SessionWorkView — a Session's own "Work" subtab (deliberately NOT the shared
 * ProjectEditor). A specialized, session-scoped cousin of the Work Mgr list.
 *
 * Tree view of the session's assigned work. "Show assigned-to-only" (default OFF):
 *   - also pull in the ANCESTORS of my items (dimmed + assignee, if not mine),
 *   - and ALL children of any parent I own (dimmed + assignee, if not mine).
 * Parent-child subtrees render as one colored/bounded group (multi-level = one group).
 *
 * View state (selection / filter / toggle) is persisted per-session so it survives
 * leaving and returning the tab.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { SessionCard } from '@uai/shared/cards';
import TodoItemView from './TodoItemView';
import SessionLink, { trackingIdFrom } from './SessionLink';
import { executeCommand } from '../utils/execute-command';
import { usePanelResize } from '../hooks/usePanelResize';
import { WorkerFilesView } from './ProjectEditor';
import { WorkerNotes } from './ProjectOverview';

type SessionAspect = 'overview' | 'work' | 'comms' | 'files';
const SESSION_ASPECTS: Array<{ key: SessionAspect; label: string; icon: string }> = [
  { key: 'overview', label: 'Overview', icon: '◉' },
  { key: 'work', label: 'Work List', icon: '☑' },
  { key: 'comms', label: 'Comms', icon: '💬' },
  { key: 'files', label: 'Files', icon: '📁' },
];

interface Todo {
  id?: string; name: string; dirName: string; path: string; status: string;
  tags: string[]; flags: string[]; assigned?: string[]; project?: string | null;
  title?: string; parent?: string | null; children?: string[];
}

const STATUS_COLORS: Record<string, string> = {
  In_Progress: 'var(--accent-blue)', Blocked: 'var(--accent-red)', Reviewing: 'var(--accent-purple)',
  Accepting: 'var(--accent-cyan)', Ready: 'var(--accent-green)', Needs_Derivation: 'var(--accent-yellow)',
  Needs_Research: 'var(--accent-orange)', Triaging: 'var(--text-sec, #b8c0cc)', Done: 'var(--pe-done, #55607a)',
  Cancelled: 'var(--text-muted)',
};
// Distinct per-group hues (mirrors the Work Mgr group palette).
const GROUP_COLORS = ['#2ac3de', '#9ece6a', '#e0af68', '#f7768e', '#bb9af7', '#ff9e64', '#73daca', '#7aa2f7'];
const ALL_STATUSES = ['In_Progress', 'Blocked', 'Reviewing', 'Accepting', 'Ready', 'Needs_Derivation', 'Needs_Research', 'Triaging', 'Done', 'Cancelled'];
const sc = (s: string) => STATUS_COLORS[s] || 'var(--text-muted)';
const num = (id: string) => id.match(/(\d+)/)?.[1] || id;
const titleOf = (t: Todo) => (t.title || t.name || '').replace(/^todo_\d+[_-]?/, '').replace(/_/g, ' ').trim() || t.id || t.dirName;
const OPEN = (s: string) => s !== 'Done' && s !== 'Cancelled';
// parent/children are `a/b/leaf` rel-paths — take the LAST todo_NNNN (the leaf), not the first.
const keyOf = (s?: string | null): string | null => { const ms = (s || '').match(/todo_\d+/g); return ms ? ms[ms.length - 1] : null; };

// Per-session view-state cache — persists across tab leave/return (within the app run).
const viewCache = new Map<string, { selDir: string | null; filter: string; assignedOnly: boolean; aspect?: string }>();

export default function SessionWorkView({ session }: { session: SessionCard }): JSX.Element {
  const tid = session.tracking_id;
  const cached = viewCache.get(tid);
  const [todos, setTodos] = useState<Todo[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [selDir, setSelDir] = useState<string | null>(cached?.selDir ?? null);
  const [filter, setFilter] = useState<'active' | 'done' | 'cancelled' | 'all'>((cached?.filter as any) ?? 'active');
  const [assignedOnly, setAssignedOnly] = useState<boolean>(cached?.assignedOnly ?? false);
  const [newName, setNewName] = useState<string | null>(null);  // non-null = the New-todo input is open
  const [cascade, setCascade] = useState<boolean>(false);       // cascade a parent's assignee to unassigned descendants
  const [aspect, setAspect] = useState<SessionAspect>((cached?.aspect as SessionAspect) ?? 'overview');
  const listResize = usePanelResize('sessionWorkListWidth', { def: 260, min: 180, max: () => Math.max(560, Math.round(window.innerWidth * 0.5)) });

  useEffect(() => { viewCache.set(tid, { selDir, filter, assignedOnly, aspect }); }, [tid, selDir, filter, assignedOnly, aspect]);

  const reload = useCallback(() => {
    // done/cancelled/all filters need finalized todos surfaced (todo_0404).
    window.uai.todos.list(filter !== 'active').then(r => { setTodos(r as unknown as Todo[]); setLoaded(true); }).catch(() => setLoaded(true));
  }, [filter]);
  useEffect(() => { reload(); }, [reload]);

  const meUri = `uai://session/${tid}`;
  const isMine = useCallback((t?: Todo) => !!t && (t.assigned || []).includes(meUri), [meUri]);

  const byKey = useMemo(() => {
    const m = new Map<string, Todo>();
    todos.forEach(t => { const k = keyOf(t.id || t.dirName); if (k) m.set(k, t); });
    return m;
  }, [todos]);

  const passFilter = useCallback((t: Todo) => filter === 'all' ? true : filter === 'done' ? t.status === 'Done' : filter === 'cancelled' ? t.status === 'Cancelled' : OPEN(t.status), [filter]);
  const myFiltered = useMemo(() => todos.filter(t => isMine(t) && passFilter(t)), [todos, isMine, passFilter]);
  const myKeys = useMemo(() => new Set(myFiltered.map(t => keyOf(t.id || t.dirName)).filter(Boolean) as string[]), [myFiltered]);

  // The set of tree nodes to show (mine + optionally ancestors + children of my parents).
  const nodeKeys = useMemo(() => {
    const nodes = new Set<string>(myKeys);
    if (!assignedOnly) {
      myKeys.forEach(k => {  // ancestors of each of my items
        let p = keyOf(byKey.get(k)?.parent); let g = 0;
        while (p && g++ < 16) { nodes.add(p); p = keyOf(byKey.get(p)?.parent); }
      });
      myKeys.forEach(k => {  // children of any parent I own
        const t = byKey.get(k);
        (t?.children || []).forEach(c => { const ck = keyOf(c); if (ck) nodes.add(ck); });
      });
    }
    // Only keep nodes we actually have data for (todos.list excludes Done/Cancelled),
    // so unloaded ancestors/children never render as empty group boxes.
    return new Set([...nodes].filter(k => byKey.has(k)));
  }, [myKeys, byKey, assignedOnly]);

  const childrenMap = useMemo(() => {
    const m = new Map<string, string[]>();
    nodeKeys.forEach(k => {
      const pk = keyOf(byKey.get(k)?.parent);
      if (pk && nodeKeys.has(pk)) { const arr = m.get(pk) || []; arr.push(k); m.set(pk, arr); }
    });
    return m;
  }, [nodeKeys, byKey]);
  const roots = useMemo(() => [...nodeKeys].filter(k => { const pk = keyOf(byKey.get(k)?.parent); return !pk || !nodeKeys.has(pk); }).sort(), [nodeKeys, byKey]);

  const selected = todos.find(t => t.dirName === selDir) || null;
  const openCount = todos.filter(t => isMine(t) && OPEN(t.status)).length;
  const totalMine = todos.filter(t => isMine(t)).length;

  const selId = selected ? (selected.id || selected.dirName) : '';
  const statusEditor = selected ? (
    <select className="wm-status-select" value={selected.status} title="Change status"
      onChange={e => { executeCommand('todo.setStatus', { id: selId, status: e.target.value }); setTimeout(reload, 300); }}>
      {ALL_STATUSES.map(s => <option key={s} value={s}>{s.replace(/_/g, ' ')}</option>)}
    </select>
  ) : undefined;
  // All loaded descendants of a todo (recurses to leaves via the children rel-paths).
  const descendantsOf = (startKey: string): Todo[] => {
    const out: Todo[] = []; const seen = new Set<string>(); const stack = [startKey];
    while (stack.length) {
      const k = stack.pop()!; if (seen.has(k)) continue; seen.add(k);
      const t = byKey.get(k); if (!t) continue;
      (t.children || []).forEach(c => { const ck = keyOf(c); if (ck && !seen.has(ck)) { const ct = byKey.get(ck); if (ct) { out.push(ct); stack.push(ck); } } });
    }
    return out;
  };
  const selKey = selected ? keyOf(selected.id || selected.dirName) : null;
  const selHasKids = !!selKey && (byKey.get(selKey)?.children || []).length > 0;
  const assigneeEditor = selected ? (
    <span className="swv-assign-wrap">
      <select className="wm-status-select" value={isMine(selected) ? meUri : ((selected.assigned || [])[0] || '')} title="Assign"
        onChange={e => {
          const v = e.target.value; const cur = (selected.assigned || [])[0];
          if (cur && cur !== v) executeCommand('todo.unassign', { id: selId, uri: cur });
          if (v) executeCommand('todo.assign', { id: selId, uri: v });
          // Cascade: assign the SAME uri to every unassigned descendant (skip ones that
          // already have a valid assignee — an explicit assignment is intentional).
          if (cascade && v && selKey) {
            descendantsOf(selKey).forEach(d => {
              if (!(d.assigned || []).length) executeCommand('todo.assign', { id: d.id || d.dirName, uri: v });
            });
          }
          setTimeout(reload, 350);
        }}>
        <option value="">unassigned</option>
        <option value={meUri}>this session ({session.display_name || tid})</option>
        {(selected.assigned || [])[0] && (selected.assigned || [])[0] !== meUri && <option value={(selected.assigned || [])[0]}>{(selected.assigned || [])[0]!.split('/').pop()}</option>}
      </select>
      {selHasKids && (
        <label className="swv-cascade" title="Also assign this to all descendant todos that are currently unassigned (recurses to leaves; won't override children that already have an assignee)">
          <input type="checkbox" checked={cascade} onChange={e => setCascade(e.target.checked)} /> cascade to children
        </label>
      )}
    </span>
  ) : undefined;

  const createTodo = () => {
    const name = (newName || '').trim();
    if (!name) { setNewName(null); return; }
    executeCommand('todo.create', { name }).then(() => {
      // assign the new todo to this session, then reload
      setTimeout(() => {
        window.uai.todos.list().then(r => {
          const arr = r as unknown as Todo[];
          const created = arr.find(t => titleOf(t).toLowerCase() === name.toLowerCase() || (t.name || '').includes(name.replace(/\s+/g, '_')));
          if (created) executeCommand('todo.assign', { id: created.id || created.dirName, uri: meUri });
          setNewName(null); setTimeout(reload, 250);
        });
      }, 250);
    });
  };

  const moveControl = selected ? (
    <select className="wm-input wm-move-inline" value="" title="Re-parent this todo"
      onChange={e => { const tgt = e.target.value; if (tgt) { executeCommand('todo.move', { id: selId, target: tgt }); setTimeout(reload, 300); } }}>
      <option value="">choose a parent…</option>
      {todos.filter(t => (t.id || t.dirName) !== selId).map(t => <option key={t.dirName} value={t.id || t.dirName}>todo_{num(t.id || '')} · {titleOf(t)}</option>)}
      <option value="root">— move to root (top-level) —</option>
    </select>
  ) : undefined;

  const renderAssignee = (t: Todo) => {
    const a = (t.assigned || [])[0];
    if (!a) return <span className="swv-unassigned">unassigned</span>;
    const stid = trackingIdFrom(a);
    if (stid) return <SessionLink id={stid} />;
    return <span className="swv-assignee-name">{a.split('/').pop()}</span>;
  };

  const renderNode = (k: string, depth: number): JSX.Element | null => {
    const t = byKey.get(k);
    if (!t) return null;
    const mine = isMine(t);
    const kids = childrenMap.get(k) || [];
    return (
      <div key={k}>
        <div className={`swv-item${selDir === t.dirName ? ' on' : ''}${mine ? '' : ' dim'}`}
          style={{ paddingLeft: 10 + depth * 15 }} onClick={() => setSelDir(t.dirName)} title={titleOf(t)}>
          <span className="swv-dot" style={{ background: sc(t.status) }} />
          <span className="swv-id">{k}</span>
          <span className="swv-name">{titleOf(t)}</span>
          {!mine && <span className="swv-assignee">{renderAssignee(t)}</span>}
        </div>
        {kids.map(ck => renderNode(ck, depth + 1))}
      </div>
    );
  };

  const s = session as any;
  const myTodoIds = todos.filter(t => isMine(t)).map(t => (t.id || t.dirName)).filter(Boolean) as string[];
  const statusCounts = useMemo(() => {
    const m: Record<string, number> = {};
    todos.filter(t => isMine(t)).forEach(t => { m[t.status] = (m[t.status] || 0) + 1; });
    return m;
  }, [todos, isMine]);
  const fmtDate = (v?: string) => v ? new Date(v).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }) : '—';
  const Card = ({ label, value, accent }: { label: string; value: React.ReactNode; accent?: string }) => (
    <div className="swv-card"><div className="swv-card-label">{label}</div><div className="swv-card-value" style={accent ? { color: accent } : undefined}>{value}</div></div>
  );

  const workListBody = (
    <div className="swv-body">
      {newName !== null && (
        <div className="swv-newrow" style={{ gridColumn: '1 / -1' }}>
          <input className="swv-newinput" autoFocus value={newName} placeholder="New todo title…"
            onChange={e => setNewName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') createTodo(); if (e.key === 'Escape') setNewName(null); }} />
          <button className="swv-pill on" onClick={createTodo}>Create</button>
          <button className="swv-pill" onClick={() => setNewName(null)}>Cancel</button>
        </div>
      )}
        <div className="swv-list" style={{ width: `${listResize.width}px` }}>
          <div className="swv-controls">
            <div className="swv-filter">
              {(['active', 'done', 'cancelled', 'all'] as const).map(f => (
                <button key={f} className={`swv-pill${filter === f ? ' on' : ''}`} onClick={() => setFilter(f)}>{f}</button>
              ))}
            </div>
            <label className="swv-toggle" title="Show only work assigned to this session (hide context parents/children)">
              <input type="checkbox" checked={assignedOnly} onChange={e => setAssignedOnly(e.target.checked)} />
              Assigned only
            </label>
          </div>
          <div className="swv-items">
            {!loaded && <div className="swv-note">Loading…</div>}
            {loaded && roots.length === 0 && <div className="swv-note">No {filter === 'active' ? 'open' : filter} work assigned to this session.</div>}
            {roots.map((r, i) => {
              const hasKids = (childrenMap.get(r) || []).length > 0;
              // Parent-child subtree = one colored/bounded group (like Work Mgr). A
              // standalone item (no children) gets no group box.
              return hasKids
                ? <div key={r} className="swv-group" style={{ borderColor: GROUP_COLORS[i % GROUP_COLORS.length] }}>{renderNode(r, 0)}</div>
                : <div key={r}>{renderNode(r, 0)}</div>;
            })}
          </div>
        </div>
        <div className="panel-resize-x" onMouseDown={listResize.onMouseDown} title="Drag to resize" />
        <div className="swv-detail">
          {selected
            ? <TodoItemView
                todo={{ ...(selected as unknown as Record<string, unknown>), id: selId } as any}
                allTodos={todos as any}
                statusEditor={statusEditor}
                assigneeEditor={assigneeEditor}
                moveControl={moveControl}
                onSelect={(id) => { const t = todos.find(x => (x.id || x.dirName) === id); if (t) setSelDir(t.dirName); }}
              />
            : <div className="swv-empty">Select a work item on the left to see and edit it.</div>}
        </div>
    </div>
  );

  // --- Overview aspect (0415/0420): work summary, description, notes, folder, timing ---
  const overviewBody = (
    <div className="pe-detail-body swv-overview">
      <section className="swv-ov-sec">
        <div className="pe-section-label">Work</div>
        <div className="swv-worksum">
          <span className="swv-ws-open">{openCount} open</span>
          <span className="swv-ws-total">· {totalMine} total</span>
          {Object.entries(statusCounts).sort().map(([st, c]) => (
            <span key={st} className="swv-ws-chip"><span className="swv-dot" style={{ background: sc(st) }} />{st.replace(/_/g, ' ')} {c}</span>
          ))}
        </div>
      </section>
      {s.notes && <section className="swv-ov-sec"><div className="pe-section-label">Description</div><p className="swv-ov-text">{s.notes}</p></section>}
      <WorkerNotes names={[session.display_name, tid].filter(Boolean) as string[]} />
      <section className="swv-ov-sec">
        <div className="pe-section-label">Working folder</div>
        {s.project_dir ? <a className="swv-link" onClick={() => window.uai.openPath?.(s.project_dir)}>{s.project_dir}</a> : <span className="pe-note">—</span>}
      </section>
      <section className="swv-ov-sec">
        <div className="pe-section-label">Identity &amp; timing</div>
        <div className="swv-kv"><span>Tracking ID</span><span className="swv-mono">{tid}</span></div>
        {s.roles && <div className="swv-kv"><span>Roles</span><span>{Array.isArray(s.roles) ? s.roles.join(', ') : s.roles}</span></div>}
        <div className="swv-kv"><span>Last activity</span><span>{fmtDate(s.last_activity)}</span></div>
      </section>
    </div>
  );

  return (
    <div className="swv">
      <div className="swv-header">
        <span className="swv-title">Session</span>
        <span className="swv-sub">{session.display_name || tid}</span>
        <button className="swv-new-btn" onClick={() => { setAspect('work'); setNewName(newName === null ? '' : null); }} title="New todo assigned to this session">+ New</button>
        <span className="swv-spacer" />
        <span className="swv-count">{openCount} open · {totalMine} total</span>
      </div>
      <div className="swv-page">
        <nav className="swv-nav">
          {SESSION_ASPECTS.map(a => (
            <button key={a.key} className={`swv-aspect${aspect === a.key ? ' on' : ''}`} onClick={() => setAspect(a.key)}>
              <span className="swv-aspect-ic">{a.icon}</span>{a.label}
            </button>
          ))}
        </nav>
        <div className="swv-content">
          {aspect === 'overview' && overviewBody}
          {aspect === 'work' && workListBody}
          {aspect === 'files' && <div className="pe-detail-body"><WorkerFilesView todoIds={myTodoIds} /></div>}
          {aspect === 'comms' && <div className="pe-detail-body"><div className="pe-note">Session conversations view is coming — for now use the Comms / Messages tools. This session: {s.exchange_count ?? 0} exchanges.</div></div>}
        </div>
        <aside className="swv-right">
          <div className="swv-right-title">At a Glance</div>
          <div className="swv-cards">
            <Card label="Status" value={s.process_status || '—'} accent={s.process_status === 'running' ? 'var(--accent-green)' : undefined} />
            <Card label="Platform" value={s.platform || '—'} />
            <Card label="Model" value={s.model || '—'} />
            <Card label="Context" value={s.context_percent != null ? `${s.context_percent}%` : '—'} />
            <Card label="Exchanges" value={s.exchange_count ?? '—'} />
            <Card label="Open work" value={openCount} />
          </div>
        </aside>
      </div>
    </div>
  );
}
