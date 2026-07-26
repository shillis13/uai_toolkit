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
import type { SessionCard } from '@uai/shared/cards';
import WorkSurface from './WorkSurface';
import { scopeTodos } from './work-scope';
import type { WorkItem } from './WorkMgrPane';
import { executeCommand } from '../utils/execute-command';
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
const sc = (s: string) => STATUS_COLORS[s] || 'var(--text-muted)';
const titleOf = (t: Todo) => (t.title || t.name || '').replace(/^todo_\d+[_-]?/, '').replace(/_/g, ' ').trim() || t.id || t.dirName;
const OPEN = (s: string) => s !== 'Done' && s !== 'Cancelled';

// Per-session view-state cache — persists the active aspect across tab leave/return.
const viewCache = new Map<string, { aspect?: string }>();

export default function SessionWorkView({ session }: { session: SessionCard }): JSX.Element {
  const tid = session.tracking_id;
  const cached = viewCache.get(tid);
  const [todos, setTodos] = useState<Todo[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [newName, setNewName] = useState<string | null>(null);  // non-null = the New-todo input is open
  const [aspect, setAspect] = useState<SessionAspect>((cached?.aspect as SessionAspect) ?? 'overview');
  // WorkSurface owns the status filter; it asks us to (re)load finalized todos when
  // a Done/Cancelled pill is toggled on (the engine hides them by default).
  const [wantFinalized, setWantFinalized] = useState(false);

  useEffect(() => { viewCache.set(tid, { aspect }); }, [tid, aspect]);

  const reload = useCallback(() => {
    window.uai.todos.list(wantFinalized).then(r => { setTodos(r as unknown as Todo[]); setLoaded(true); }).catch(() => setLoaded(true));
  }, [wantFinalized]);
  useEffect(() => { reload(); }, [reload]);

  const meUri = `uai://session/${tid}`;
  const isMine = useCallback((t?: Todo) => !!t && (t.assigned || []).includes(meUri), [meUri]);

  const openCount = todos.filter(t => isMine(t) && OPEN(t.status)).length;
  const totalMine = todos.filter(t => isMine(t)).length;

  // Session-scoped work set — the SAME shared scoping the Work Mgr reuse relies on
  // (A1). Rows carry both the WorkItem and Todo field sets (same engine payload).
  const scopedTodos = useMemo(
    () => scopeTodos({ kind: 'session', trackingId: tid }, todos as unknown as WorkItem[]),
    [todos, tid],
  );

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

  // Work List — the SHARED WorkSurface (the same list + detail the global Work Mgr
  // renders), scoped to this session (todo_0544). The session's New-todo affordance
  // stays above it (creates + assigns the todo to this session).
  const workListBody = (
    <div className="swv-worksurface" style={{ display: 'flex', flexDirection: 'column', flex: 1, minHeight: 0 }}>
      {newName !== null && (
        <div className="swv-newrow">
          <input className="swv-newinput" autoFocus value={newName} placeholder="New todo title…"
            onChange={e => setNewName(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') createTodo(); if (e.key === 'Escape') setNewName(null); }} />
          <button className="swv-pill on" onClick={createTodo}>Create</button>
          <button className="swv-pill" onClick={() => setNewName(null)}>Cancel</button>
        </div>
      )}
      <WorkSurface
        todos={scopedTodos}
        loading={!loaded}
        onReload={reload}
        onWantFinalized={setWantFinalized}
        viewportId="session_work_surface"
        emptyLabel="Select a work item from the list."
      />
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
