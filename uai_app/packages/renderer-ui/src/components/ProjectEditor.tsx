/**
 * ProjectEditor — the Project tab's Center Pane.
 *
 * Splits the Center Pane into Navigator Panel · Detail Area · Right Panel,
 * parallel to how a Session tab splits into Title Bar / Terminal / Prompt / Right Panel.
 * Design: docs/designs/2026-06-21-project-editor-design.md  (todo_0320)
 *
 * Aspects (Navigator): Overview · Work List · Team · Comms.
 * Decisions (locked 2026-06-21): (1) nav expands uniformly into each aspect's items;
 * (2) Doc Folder == Work Folder == one generic tree; (3) Right Panel == reused ContextPanel.
 *
 * Build state: SHELL. Navigator + routing are live; Overview reuses ProjectDetailView;
 * Work/Team/Comms detail bodies are scaffolds wired to real nav data, filled per the
 * build sequence (Comms → Team → Work → Overview). See §6 of the design doc.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { ProjectCard, SessionCard } from '@uai/shared/cards';
import ProjectOverview, { FileMetaPanel } from './ProjectOverview';
import ProjectFolderTree, { type FsEntry } from './ProjectFolderTree';
import ProjectCommsDetail, { useProjectConversations, formatTime, type Conversation } from './ProjectComms';
import ProjectTeamDetail, { TeamMemberPanel } from './ProjectTeam';
import TodoItemView from './TodoItemView';
import { executeCommand } from '../utils/execute-command';

type AspectKey = 'overview' | 'work' | 'team' | 'comms' | 'files';
type WorkerKind = 'project' | 'team' | 'session';

interface AspectDef { key: AspectKey; label: string; icon: string; }
// Panel order (todo_0418): Overview · Team · Comms · Files · Work List.
// (Files aspect content is git-derived — todo_0417.)
const ASPECTS: AspectDef[] = [
  { key: 'overview', label: 'Overview', icon: '◉' },
  { key: 'team', label: 'Team', icon: '👥' },
  { key: 'comms', label: 'Comms', icon: '💬' },
  { key: 'files', label: 'Files', icon: '📁' },
  { key: 'work', label: 'Work List', icon: '☑' },
];

interface TodoItem { id?: string; name: string; dirName: string; path: string; status: string; tags: string[]; flags: string[]; assigned?: string[]; project?: string | null; }

// A selected Navigator item — the thing whose detail fills the center / overflow fills the right.
interface Selection { aspect: AspectKey; itemId: string | null; }

const STATUS_BADGE: Record<string, { label: string; color: string }> = {
  In_Progress: { label: 'IP', color: 'var(--accent-green)' },
  Blocked: { label: 'BL', color: 'var(--accent-orange)' },
  Reviewing: { label: 'RV', color: 'var(--accent-blue)' },
  Ready: { label: 'RD', color: 'var(--accent-blue)' },
  Triaging: { label: 'TR', color: 'var(--accent-purple)' },
  Done: { label: 'DN', color: 'var(--text-muted)' },
};

function badgeFor(status: string): { label: string; color: string } {
  return STATUS_BADGE[status] || { label: status.slice(0, 2).toUpperCase(), color: 'var(--text-muted)' };
}

// Full status palette for the vital-signs bar (mirrors Work Mgr's STATUS_COLORS,
// all via --accent-* vars so a recolor is one place). Ordered active→finalized.
const STATUS_FULL: Record<string, { abbr: string; color: string }> = {
  In_Progress: { abbr: 'IP', color: 'var(--accent-blue)' },
  Blocked: { abbr: 'BL', color: 'var(--accent-red)' },
  Reviewing: { abbr: 'RV', color: 'var(--accent-purple)' },
  Accepting: { abbr: 'AC', color: 'var(--accent-cyan)' },
  Ready: { abbr: 'RD', color: 'var(--accent-green)' },
  Needs_Derivation: { abbr: 'DV', color: 'var(--accent-yellow)' },
  Needs_Research: { abbr: 'RS', color: 'var(--accent-orange)' },
  Triaging: { abbr: 'TR', color: 'var(--text-sec, #b8c0cc)' },
  Done: { abbr: 'DN', color: 'var(--pe-done, #55607a)' },
  Cancelled: { abbr: 'CX', color: 'var(--text-muted)' },
};
const STATUS_SEQ = ['In_Progress', 'Blocked', 'Reviewing', 'Accepting', 'Ready', 'Needs_Derivation', 'Needs_Research', 'Triaging', 'Done', 'Cancelled'];
const OPEN_STATUS = (s: string) => s !== 'Done' && s !== 'Cancelled';
const statusLabelPE = (s: string) => (s || '').replace(/_/g, ' ');

// The densest single signal a worker has: a proportional, per-status colored
// block-bar of its todo set. Shared across session/project/team overviews.
// Files aspect (todo_0417): git-derived superset of files modified across this
// worker's (non-archived) todos, via the `Todo:` commit trailer. Leaf view — no
// sub-item list; click a file to open it. Git = ground-truth change history.
export function WorkerFilesView({ todoIds }: { todoIds: string[] }): JSX.Element {
  const [files, setFiles] = useState<string[] | null>(null);
  const key = todoIds.slice().sort().join(',');
  useEffect(() => {
    let alive = true;
    setFiles(null);
    if (!todoIds.length) { setFiles([]); return; }
    (window.uai as any).git.filesForTodos(todoIds)
      .then((f: string[]) => { if (alive) setFiles(f); })
      .catch(() => { if (alive) setFiles([]); });
    return () => { alive = false; };
  }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  return (
    <div className="pe-detail-body pe-files">
      <div className="pe-section-label">Files &nbsp;<span className="pe-files-sub">git-tracked changes across this worker's {todoIds.length} active todo{todoIds.length === 1 ? '' : 's'}</span></div>
      {files === null && <div className="pe-note">Reading git history…</div>}
      {files !== null && files.length === 0 && <div className="pe-note">No git-attributed file changes yet. (Files are attributed via the <code>Todo:</code> commit trailer — coverage grows as todo-tagged commits land.)</div>}
      {files && files.length > 0 && (
        <div className="pe-files-list">
          {files.map(f => (
            <div key={f} className="pe-file-row" onClick={() => window.uai.openPath?.(f)} title="Open">
              <span className="pe-file-ic">📄</span><span className="pe-file-path">{f}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function VitalSignsBar({ todos }: { todos: TodoItem[] }): JSX.Element {
  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    todos.forEach(t => { m[t.status] = (m[t.status] || 0) + 1; });
    return m;
  }, [todos]);
  const total = todos.length;
  const present = STATUS_SEQ.filter(s => counts[s]);
  const openCount = todos.filter(t => OPEN_STATUS(t.status)).length;
  const blocked = counts['Blocked'] || 0;

  if (total === 0) {
    return <div className="pe-vitals pe-vitals-empty">No work items assigned yet.</div>;
  }
  return (
    <div className="pe-vitals">
      <div className="pe-vitals-head">
        <span className="pe-vitals-title">Work</span>
        <span className="pe-vitals-stat">{openCount} open</span>
        {blocked > 0 && <span className="pe-vitals-stat pe-vitals-blocked">{blocked} blocked</span>}
        <span className="pe-vitals-stat pe-vitals-total">{total} total</span>
      </div>
      <div className="pe-vitals-bar">
        {present.map(s => {
          const c = counts[s]; const pct = (c / total) * 100;
          return (
            <div key={s} className="pe-vitals-seg" style={{ width: `${pct}%`, background: STATUS_FULL[s].color }}
              title={`${statusLabelPE(s)}: ${c}`}>
              <span className="pe-vitals-seg-lbl">{pct > 8 ? `${STATUS_FULL[s].abbr} ${c}` : c}</span>
            </div>
          );
        })}
      </div>
      <div className="pe-vitals-legend">
        {present.map(s => (
          <span key={s} className="pe-vitals-leg">
            <span className="pe-vitals-dot" style={{ background: STATUS_FULL[s].color }} />
            {statusLabelPE(s)} <b>{counts[s]}</b>
          </span>
        ))}
      </div>
    </div>
  );
}

// A single stat card for the Overview grid. `bar` (0–100) renders a heat-fill meter.
function StatCard({ label, value, accent, bar, onClick, title }: {
  label: string; value: ReactNode; accent?: string; bar?: number | null;
  onClick?: () => void; title?: string;
}): JSX.Element {
  const heat = (p: number) => p >= 85 ? 'var(--accent-red)' : p >= 60 ? 'var(--accent-orange)' : 'var(--accent-green)';
  return (
    <div className={`pe-statcard${onClick ? ' clickable' : ''}`} onClick={onClick} title={title}>
      <div className="pe-statcard-k">{label}</div>
      <div className="pe-statcard-v" style={accent ? { color: accent } : undefined}>{value}</div>
      {typeof bar === 'number' && (
        <div className="pe-statcard-meter"><div className="pe-statcard-fill" style={{ width: `${Math.max(0, Math.min(100, bar))}%`, background: heat(bar) }} /></div>
      )}
    </div>
  );
}

// The right panel's rich DEFAULT (nothing selected): a live worker digest so the
// third column earns its space instead of showing "Select an item…".
function WorkerDigest({ todos, conversations, roster, kind }: {
  todos: TodoItem[]; conversations: Conversation[]; roster: SessionCard[]; kind: WorkerKind;
}): JSX.Element {
  const open = todos.filter(t => OPEN_STATUS(t.status));
  const blocked = todos.filter(t => t.status === 'Blocked');
  const needsInput = conversations.filter(c => c.needs_input);
  const running = roster.filter(s => (s as any).process_status === 'running').length;
  const topOpen = open.slice(0, 4);
  const topConv = [...conversations].sort((a, b) => (b.needs_input ? 1 : 0) - (a.needs_input ? 1 : 0)).slice(0, 4);

  return (
    <div className="pe-digest">
      <div className="pe-digest-title">At a glance</div>

      {blocked.length > 0 && (
        <div className="pe-digest-alert">⚠ {blocked.length} blocked</div>
      )}

      <div className="pe-digest-sec">
        <div className="pe-digest-h">Open work <span className="pe-digest-n">{open.length}</span></div>
        {topOpen.length === 0
          ? <div className="pe-digest-empty">Nothing open.</div>
          : topOpen.map(t => {
              const b = badgeFor(t.status);
              return (
                <div key={t.dirName} className="pe-digest-row" title={t.name}>
                  <span className="pe-digest-dot" style={{ background: STATUS_FULL[t.status]?.color || 'var(--text-muted)' }} />
                  <span className="pe-digest-lbl">{t.name}</span>
                  <span className="pe-digest-badge" style={{ color: b.color }}>{b.label}</span>
                </div>
              );
            })}
        {open.length > topOpen.length && <div className="pe-digest-more">+{open.length - topOpen.length} more</div>}
      </div>

      <div className="pe-digest-sec">
        <div className="pe-digest-h">Conversations <span className="pe-digest-n">{conversations.length}</span>
          {needsInput.length > 0 && <span className="pe-digest-need">{needsInput.length} need input</span>}
        </div>
        {topConv.length === 0
          ? <div className="pe-digest-empty">No conversations.</div>
          : topConv.map(c => (
              <div key={c.id} className={`pe-digest-row${c.needs_input ? ' need' : ''}`} title={c.topic || ''}>
                {c.needs_input && <span className="pe-digest-dot" style={{ background: 'var(--accent-orange)' }} />}
                <span className="pe-digest-lbl">{c.topic || '(untitled)'}</span>
                <span className="pe-digest-badge">{c.message_count}</span>
              </div>
            ))}
      </div>

      {kind !== 'session' && (
        <div className="pe-digest-sec">
          <div className="pe-digest-h">Roster <span className="pe-digest-n">{roster.length}</span></div>
          <div className="pe-digest-roster">
            <span className="pe-digest-rstat"><span className="pe-digest-dot" style={{ background: 'var(--accent-green)' }} />{running} running</span>
            <span className="pe-digest-rstat"><span className="pe-digest-dot" style={{ background: 'var(--text-muted)' }} />{roster.length - running} idle</span>
          </div>
        </div>
      )}
    </div>
  );
}

// The right panel when a WORK item is selected — a typed inspector card.
function TodoInspector({ todo }: { todo: TodoItem }): JSX.Element {
  const b = badgeFor(todo.status);
  const assignees = (todo.assigned || []).map(a => a.split('/').pop() || a);
  return (
    <div className="pe-inspect">
      <div className="pe-inspect-head">
        <span className="pe-inspect-badge" style={{ background: STATUS_FULL[todo.status]?.color || 'var(--text-muted)' }}>{b.label}</span>
        <span className="pe-inspect-status">{statusLabelPE(todo.status)}</span>
      </div>
      <div className="pe-inspect-name">{todo.name}</div>
      <div className="pe-inspect-meta">
        {todo.id && <div className="pe-inspect-row"><span className="pe-inspect-k">ID</span><span className="pe-inspect-v">{todo.id}</span></div>}
        <div className="pe-inspect-row"><span className="pe-inspect-k">Assigned</span><span className="pe-inspect-v">{assignees.length ? assignees.join(' · ') : '—'}</span></div>
        {todo.project && <div className="pe-inspect-row"><span className="pe-inspect-k">Project</span><span className="pe-inspect-v">{todo.project}</span></div>}
        {todo.tags?.length > 0 && <div className="pe-inspect-row"><span className="pe-inspect-k">Tags</span><span className="pe-inspect-v">{todo.tags.join(' · ')}</span></div>}
        {todo.flags?.length > 0 && <div className="pe-inspect-row"><span className="pe-inspect-k">Flags</span><span className="pe-inspect-v">{todo.flags.join(' · ')}</span></div>}
      </div>
      <div className="pe-inspect-hint">Open the item in the Detail area for files &amp; contents; status/assignee actions land here next.</div>
    </div>
  );
}

interface ProjectEditorProps {
  /** Worker = project | team (a project with the 'team' tag). Omit when `session` is set. */
  project?: ProjectCard;
  /** Session-worker mode — renders the same aspect page scoped to one session (Chat|Work subtab). */
  session?: SessionCard;
  sessions?: SessionCard[];
}

export default function ProjectEditor({ project, session, sessions = [] }: ProjectEditorProps): JSX.Element {
  const kind: WorkerKind = session ? 'session' : (project?.tags.includes('team') ? 'team' : 'project');
  // a session worker has no Team aspect
  const aspects = useMemo(() => kind === 'session' ? ASPECTS.filter(a => a.key !== 'team') : ASPECTS, [kind]);
  const [sel, setSel] = useState<Selection>({ aspect: kind === 'team' ? 'team' : 'overview', itemId: null });
  const [navCollapsed, setNavCollapsed] = useState(false); // collapse the active aspect's nav items on re-click (#pt1)
  const [selectedFile, setSelectedFile] = useState<FsEntry | null>(null);
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [todosLoaded, setTodosLoaded] = useState(false);
  // Resizable panels (drag the dividers between Navigator · Detail · Right).
  const [navW, setNavW] = useState(196);
  const [rightW, setRightW] = useState(234);
  const startDrag = (which: 'nav' | 'right') => (e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX, startNav = navW, startRight = rightW;
    const onMove = (me: MouseEvent) => {
      const dx = me.clientX - startX;
      if (which === 'nav') setNavW(Math.max(150, Math.min(440, startNav + dx)));
      else setRightW(Math.max(160, Math.min(560, startRight - dx)));
    };
    const onUp = () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  // Work List todos (todos.list is wired/live; project scoping is Phase-0 pending, so show all for now).
  const reloadTodos = useCallback(() => {
    window.uai.todos.list()
      .then(rows => { setTodos(rows as TodoItem[]); setTodosLoaded(true); })
      .catch(() => setTodosLoaded(true));
  }, []);
  useEffect(() => { reloadTodos(); }, [reloadTodos]);

  const projectSessions = useMemo(
    () => project ? sessions.filter(s => !s.archived && s.project_dir === project.working_dir) : [],
    [sessions, project],
  );

  // Roster: project → sessions whose working dir matches; team → registry members
  // (assigned_ais), resolved to sessions or a name-only pseudo-card; session → itself.
  const roster = useMemo(() => {
    if (kind === 'session') return session ? [session] : [];
    if (kind === 'team') return (project!.assigned_ais || []).map(m =>
      sessions.find(s => s.display_name === m || s.tracking_id === m)
      ?? ({ entity_id: `member:${m}`, tracking_id: m, display_name: m, platform: '', roles: [], project_dir: '', archived: false } as unknown as SessionCard));
    return projectSessions;
  }, [kind, session, project, sessions, projectSessions]);

  // Work List filter — scope todos to THIS worker (#worker-pages).
  const projectId = project ? String(project.entity_id || '').replace(/^project:/, '') : '';
  const visibleTodos = useMemo(() => {
    if (kind === 'session') {
      const uri = session ? `uai://session/${session.tracking_id}` : '';
      return todos.filter(t => (t.assigned || []).includes(uri));
    }
    if (kind === 'project') {
      return todos.filter(t => t.project === projectId || (t.assigned || []).includes(`uai://project/${projectId}`));
    }
    // team: any todo assigned to a member session
    const memberUris = new Set(roster.map(s => `uai://session/${s.tracking_id}`));
    return todos.filter(t => (t.assigned || []).some(a => memberUris.has(a)));
  }, [kind, todos, session, projectId, roster]);

  // Conversations for this worker's participants (gated to the Comms aspect).
  const { conversations, loading: convLoading } = useProjectConversations(
    roster.map(s => s.tracking_id).filter(Boolean), sel.aspect === 'comms');

  // worker title-bar display
  const displayName = session ? (session.display_name || session.tracking_id.slice(0, 16)) : project!.display_name;
  const crumbIcon = kind === 'session' ? '🖥' : '📁';
  const navGrpLabel = kind === 'session' ? 'Session' : kind === 'team' ? 'Team' : 'Project';
  const statusLine = session
    ? `● ${session.process_status || 'session'}${session.platform ? ' · ' + session.platform : ''}`
    : `● ${project!.lifecycle_status || 'project'} · ${project!.branch || 'main'} · ${project!.git_status}`;

  const setAspect = (aspect: AspectKey) => { setSel({ aspect, itemId: null }); setSelectedFile(null); };
  const selectItem = (aspect: AspectKey, itemId: string) => setSel({ aspect, itemId });
  const openSession = (trackingId: string) =>
    executeCommand('workspace.tabs.open', { type: 'session', targetId: trackingId });

  const selectedSession = sel.aspect === 'team' && sel.itemId
    ? roster.find(s => s.tracking_id === sel.itemId) || null
    : null;

  const selectedTodo = sel.aspect === 'work' && sel.itemId
    ? visibleTodos.find(t => t.dirName === sel.itemId) || null
    : null;

  return (
    <div className="project-editor">
      <div className="pe-titlebar">
        <span className="pe-crumb-icon">{crumbIcon}</span>
        <span className="pe-crumb-project">{displayName}</span>
        <span className="pe-crumb-sep">›</span>
        <span className="pe-crumb-aspect">{aspects.find(a => a.key === sel.aspect)?.label}</span>
        <span className="pe-titlebar-spacer" />
        <span className="pe-titlebar-status">{statusLine}</span>
      </div>

      <div className="pe-grid" style={{ gridTemplateColumns: `${navW}px 6px 1fr 6px ${rightW}px` }}>
        {/* ── Navigator Panel ─────────────────────────────────── */}
        <nav className="pe-nav">
          <div className="pe-nav-grp">{navGrpLabel}</div>
          {aspects.map(a => (
            <div key={a.key}>
              <div
                className={`pe-aspect${sel.aspect === a.key ? ' on' : ''}`}
                onClick={() => { if (a.key === 'overview' || a.key === 'files') { setAspect(a.key); } else if (sel.aspect === a.key) setNavCollapsed(c => !c); else { setAspect(a.key); setNavCollapsed(false); } }}
              >
                <span className="pe-aspect-ic">{a.icon}</span>{a.label}
                {sel.aspect === a.key && a.key !== 'overview' && a.key !== 'files' && <span className="pe-aspect-chev">{navCollapsed ? '▸' : '▾'}</span>}
              </div>
              {sel.aspect === a.key && !navCollapsed && a.key !== 'overview' && a.key !== 'files' && (
                <NavItems
                  aspect={a.key}
                  todos={visibleTodos}
                  todosLoaded={todosLoaded}
                  sessions={roster}
                  conversations={conversations}
                  selectedItem={sel.itemId}
                  onSelect={(id) => selectItem(a.key, id)}
                />
              )}
            </div>
          ))}
        </nav>

        <div className="pe-resize" onMouseDown={startDrag('nav')} title="Drag to resize" />

        {/* ── Detail Area ─────────────────────────────────────── */}
        <section className="pe-detail">
          {sel.aspect === 'overview' && (
            <div className="pe-overview-wrap">
              {session
                ? <><VitalSignsBar todos={visibleTodos} /><SessionOverview session={session} convCount={conversations.length} /></>
                : <ProjectOverview
                    project={project!}
                    sessions={roster}
                    selectedFilePath={selectedFile?.path}
                    onSelectFile={setSelectedFile}
                    onGotoTeam={() => setAspect('team')}
                    workSummary={<VitalSignsBar todos={visibleTodos} />}
                  />}
            </div>
          )}
          {sel.aspect === 'work' && (
            <WorkDetail
              todos={visibleTodos}
              allTodos={todos}
              todosLoaded={todosLoaded}
              selectedDir={sel.itemId}
              onSelect={(dirName) => selectItem('work', dirName)}
              onReload={reloadTodos}
            />
          )}
          {sel.aspect === 'team' && (
            <ProjectTeamDetail
              sessions={roster}
              selectedId={sel.itemId}
              onSelect={(id) => selectItem('team', id)}
              onOpenSession={openSession}
            />
          )}
          {sel.aspect === 'comms' && (
            <ProjectCommsDetail
              conversations={conversations}
              loading={convLoading}
              selectedId={sel.itemId}
              teamSize={roster.length}
            />
          )}
          {sel.aspect === 'files' && (
            <WorkerFilesView todoIds={visibleTodos.map(t => (t.id || t.dirName)).filter(Boolean) as string[]} />
          )}
        </section>

        <div className="pe-resize" onMouseDown={startDrag('right')} title="Drag to resize" />

        {/* ── Right Panel — typed inspector on selection, live digest by default ── */}
        <aside className="pe-right">
          {selectedFile
            ? <FileMetaPanel entry={selectedFile} />
            : selectedSession
              ? <TeamMemberPanel session={selectedSession} onOpen={openSession} />
              : selectedTodo
                ? <TodoInspector todo={selectedTodo} />
                : <WorkerDigest todos={visibleTodos} conversations={conversations} roster={roster} kind={kind} />}
        </aside>
      </div>
    </div>
  );
}

// ── Session Overview body (the Overview aspect for a session worker) ────────
// A dense card grid of the session's vitals (was a flat key/value column).
function SessionOverview({ session, convCount }: { session: SessionCard; convCount: number }): JSX.Element {
  const ctx = typeof session.context_percent === 'number' ? session.context_percent : null;
  const status = session.process_status || '—';
  const running = status === 'running';
  const workDir = session.project_dir || '';
  const openDir = () => { if (workDir) (window as any).uai?.openPath?.(workDir); };
  return (
    <div className="pe-detail-body">
      <div className="pe-cardgrid">
        <StatCard label="Status" value={running ? '● running' : status}
          accent={running ? 'var(--accent-green)' : 'var(--text-muted)'} />
        <StatCard label="Platform" value={session.platform || '—'} />
        <StatCard label="Context used" value={ctx != null ? `${Math.round(ctx)}%` : '—'} bar={ctx} />
        <StatCard label="Exchanges" value={session.exchange_count ?? '—'} />
        <StatCard label="Conversations" value={convCount} />
        <StatCard label="Last active" value={session.last_activity ? formatTime(session.last_activity) : '—'} />
        <StatCard label="Model" value={session.model || '—'} />
        <StatCard label="Roles" value={(session.roles || []).join(' · ') || '—'} />
      </div>
      <div className="pe-idstrip">
        <div className="pe-idrow"><span className="pe-idk">Tracking ID</span><span className="pe-idv">{session.tracking_id}</span></div>
        {workDir && (
          <div className="pe-idrow"><span className="pe-idk">Working dir</span>
            <span className="pe-idv pe-idv-link" onClick={openDir} title="Open in Finder">{workDir}</span></div>
        )}
      </div>
    </div>
  );
}

// ── Navigator items (uniform expand — decision 1) ──────────────────────────
function NavItems({ aspect, todos, todosLoaded, sessions, conversations, selectedItem, onSelect }: {
  aspect: AspectKey; todos: TodoItem[]; todosLoaded: boolean; sessions: SessionCard[];
  conversations: Conversation[]; selectedItem: string | null; onSelect: (id: string) => void;
}): JSX.Element {
  if (aspect === 'work') {
    if (!todosLoaded) return <div className="pe-nav-note">Loading todos…</div>;
    if (todos.length === 0) return <div className="pe-nav-note">No todos.</div>;
    return (
      <>
        {todos.slice(0, 40).map(t => {
          const b = badgeFor(t.status);
          return (
            <div key={t.dirName}
              className={`pe-item${selectedItem === t.dirName ? ' on' : ''}`}
              onClick={() => onSelect(t.dirName)} title={t.name}>
              <span className="pe-item-label">{t.name}</span>
              <span className="pe-item-badge" style={{ color: b.color }}>{b.label}</span>
            </div>
          );
        })}
      </>
    );
  }
  if (aspect === 'team') {
    if (sessions.length === 0) return <div className="pe-nav-note">No sessions in this project.</div>;
    return (
      <>
        {sessions.map(s => (
          <div key={s.entity_id}
            className={`pe-item${selectedItem === s.tracking_id ? ' on' : ''}`}
            onClick={() => onSelect(s.tracking_id)} title={s.display_name}>
            <span className="pe-item-dot" />
            <span className="pe-item-label">{s.display_name}</span>
          </div>
        ))}
      </>
    );
  }
  if (aspect === 'comms') {
    if (conversations.length === 0) return <div className="pe-nav-note">No conversations yet.</div>;
    // needs-input first (actionable), otherwise keep the read's last-activity order.
    const ordered = [...conversations].sort((a, b) => (b.needs_input ? 1 : 0) - (a.needs_input ? 1 : 0));
    return (
      <>
        {ordered.map(c => (
          <div key={c.id}
            className={`pe-conv${selectedItem === c.id ? ' on' : ''}${c.needs_input ? ' needs' : ''}`}
            onClick={() => onSelect(c.id)} title={c.topic}>
            <div className="pe-conv-top">
              {c.needs_input && <span className="pe-item-dot" style={{ background: 'var(--accent-orange)' }} />}
              <span className="pe-conv-topic">{c.topic || '(untitled)'}</span>
              <span className="pe-conv-time">{formatTime(c.last_activity)}</span>
            </div>
            <div className="pe-conv-sub">
              <span className="pe-conv-count">{c.message_count} msg{c.message_count === 1 ? '' : 's'}</span>
              {c.last_message_preview && <span className="pe-conv-preview">· {c.last_message_preview}</span>}
            </div>
          </div>
        ))}
      </>
    );
  }
  // overview — sub-areas live inside the Overview detail (Docs / Team collapse)
  return <></>;
}

// ── Work detail (todos.read is live) ───────────────────────────────────────
function WorkDetail({ todos, allTodos, todosLoaded, selectedDir, onSelect, onReload }: {
  todos: TodoItem[]; allTodos?: TodoItem[]; todosLoaded: boolean; selectedDir: string | null;
  onSelect?: (dirName: string) => void; onReload?: () => void;
}): JSX.Element {
  const selected = todos.find(t => t.dirName === selectedDir) || null;
  if (!todosLoaded) return <div className="pe-detail-body"><div className="pe-note">Loading…</div></div>;
  if (!selected) return <div className="pe-detail-body"><div className="pe-note">Select a todo from the Navigator to see its detail. ({todos.length} todos)</div></div>;
  const selId = selected.id || selected.dirName;
  const parentOptions = (allTodos || todos).filter(t => (t.id || t.dirName) !== selId);
  // Re-parenting works in every pane (todo.move Command Bus verb), not just Work Mgr.
  const moveControl = (
    <select className="wm-input wm-move-inline" value="" title="Re-parent this todo"
      onChange={e => { const target = e.target.value; if (!target) return;
        executeCommand('todo.move', { id: selId, target }); setTimeout(() => onReload?.(), 300); }}>
      <option value="">choose a parent…</option>
      {parentOptions.map(t => <option key={t.dirName} value={t.id || t.dirName}>todo_{(t.id || '').match(/(\d+)/)?.[1] || t.dirName} · {t.name}</option>)}
      <option value="root">— move to root (top-level) —</option>
    </select>
  );
  // Shared todo-item view (identical across Work Mgr / Session Work / Project Work).
  return (
    <TodoItemView
      todo={{ ...(selected as any), id: selId }}
      allTodos={(allTodos || todos) as any}
      moveControl={moveControl}
      onSelect={onSelect ? (id) => { const t = (allTodos || todos).find(x => (x.id || x.dirName) === id); if (t) onSelect(t.dirName); } : undefined}
    />
  );
}
