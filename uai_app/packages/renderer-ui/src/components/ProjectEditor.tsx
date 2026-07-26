/**
 * ProjectEditor — the Project tab's Center Pane.
 *
 * Uses a title bar, horizontal aspect tabs, and one full-width aspect surface.
 * File/team selection details dock below that surface rather than in a permanent
 * right rail.
 * Design: docs/designs/2026-06-21-project-editor-design.md  (todo_0320)
 *
 * Aspects: Overview · Work List · Team · Comms plus project-only Playbook/Workspace.
 *
 * Build state: SHELL. Navigator + routing are live; Overview reuses ProjectDetailView;
 * Work/Team/Comms detail bodies are scaffolds wired to real nav data, filled per the
 * build sequence (Comms → Team → Work → Overview). See §6 of the design doc.
 */

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import type { ProjectCard, SessionCard } from '@uai/shared/cards';
import ProjectOverview from './ProjectOverview';
import ProjectFolderTree, { type FsEntry } from './ProjectFolderTree';
import { PlaybookView, WorkspaceView, FilePreviewPanel } from './ProjectPlaybook';
import ProjectCommsDetail, { useProjectConversations, formatTime, type Conversation } from './ProjectComms';
import ProjectTeamDetail, { TeamMemberPanel } from './ProjectTeam';
import WorkSurface from './WorkSurface';
import { scopeTodos } from './work-scope';
import { STATUS_ORDER, statusColor, itemDate } from './WorkMgrPane';
import type { WorkItem } from './WorkMgrPane';
import StatusFilterMenu from './StatusFilterMenu';
import GitFileViewPane from './GitFileViewPane';
import { executeCommand } from '../utils/execute-command';

type AspectKey = 'overview' | 'work' | 'team' | 'comms' | 'files' | 'playbook' | 'workspace';
type WorkerKind = 'project' | 'team' | 'session';

interface AspectDef { key: AspectKey; label: string; icon: string; }
// isProject inversion: a worker is a TEAM by default — the base aspects below are
// what any Team (and Project) has. Being a Project (isProject) UNLOCKS the extra
// PROJECT_ASPECTS. Panel order (todo_0623, PianoMan): Overview · Team · Comms ·
// Playbook · Work List · Workspace · Files — Playbook sits just before Work List,
// Workspace just after it, and Files is last.
const ASPECTS: AspectDef[] = [
  { key: 'overview', label: 'Overview', icon: '◉' },
  { key: 'team', label: 'Team', icon: '👥' },
  { key: 'comms', label: 'Comms', icon: '💬' },
  { key: 'work', label: 'Work List', icon: '☑' },
  { key: 'files', label: 'Files', icon: '📁' },
];
// Project-only aspects — only surfaced when isProject (a Team never has a working_dir,
// so Docs is meaningless for it). This is the "Project unlocks more than a Team".
const PROJECT_ASPECTS: AspectDef[] = [
  { key: 'playbook', label: 'Playbook', icon: '📓' },
  { key: 'workspace', label: 'Workspace', icon: '🗂' },
];

interface TodoItem { id?: string; name: string; dirName: string; path: string; status: string; tags: string[]; flags: string[]; assigned?: string[]; project?: string | null; updated?: string; created?: string; }


// The active aspect and its optional selected row.
interface Selection { aspect: AspectKey; itemId: string | null; }

// Per-worker UI persistence (todo_0623 #3): the focused aspect survives leaving and
// returning to a worker's tab, and app restarts. This is app-owned VIEW state (per the
// data-ownership rule) keyed by the worker's stable id — see the "UI state persistence"
// rule in this directory's DESIGN.md.
const PE_ASPECT_STORE = 'uai:pe:aspect';
function readAspectStore(): Record<string, AspectKey> {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(PE_ASPECT_STORE) || '{}');
    return parsed !== null && typeof parsed === 'object' && !Array.isArray(parsed)
      ? parsed as Record<string, AspectKey>
      : {};
  } catch { return {}; }
}
function loadAspect(key: string): AspectKey | null {
  return readAspectStore()[key] || null;
}
function saveAspect(key: string, aspect: AspectKey): void {
  try {
    localStorage.setItem(PE_ASPECT_STORE, JSON.stringify({ ...readAspectStore(), [key]: aspect }));
  } catch { /* ignore */ }
}

// Work-bar (vital-signs) filter — a view preference (status set + a "since" date),
// persisted globally (todo_0623 #1.3; DESIGN.md UI-state-persistence).
const PE_VITALS_STORE = 'uai:pe:vitalsFilter';
interface VitalsFilterState { schemaV: number; statuses: string[] | null; since: string }
function loadVitalsFilter(): VitalsFilterState {
  try {
    const v = JSON.parse(localStorage.getItem(PE_VITALS_STORE) || '{}');
    return {
      schemaV: v?.schemaV === 2 ? 2 : 1,
      statuses: Array.isArray(v?.statuses) ? v.statuses.filter((s: unknown): s is string => typeof s === 'string') : null,
      since: typeof v?.since === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v.since) ? v.since : '',
    };
  } catch { return { schemaV: 2, statuses: null, since: '' }; }
}
function saveVitalsFilter(statuses: string[], since: string): void {
  try { localStorage.setItem(PE_VITALS_STORE, JSON.stringify({ schemaV: 2, statuses, since })); } catch { /* ignore */ }
}

// The vital-signs bar reuses Work Mgr's canonical status ORDER + COLORS (todo_0623
// #1.1/#1.2) — one source of truth, so the bar always matches the Work Mgr status
// filter (ascending lifecycle left→right). Only the abbreviations are local.
const STATUS_ABBR: Record<string, string> = {
  In_Progress: 'IP', Blocked: 'BL', Reviewing: 'RV', Accepting: 'AC', Ready: 'RD',
  Needs_Derivation: 'DV', Needs_Research: 'RS', Triaging: 'TR', Done: 'DN', Cancelled: 'CX',
};
const abbrFor = (s: string): string => STATUS_ABBR[s] || (s || '?').slice(0, 2).toUpperCase();
const STATUS_SEQ = Object.keys(STATUS_ORDER).sort((a, b) => STATUS_ORDER[a] - STATUS_ORDER[b]);
const OPEN_STATUS = (s: string) => s !== 'Done' && s !== 'Cancelled';
const statusLabelPE = (s: string) => (s || '').replace(/_/g, ' ');

// The densest single signal a worker has: a proportional, per-status colored
// block-bar of its todo set. Shared across session/project/team overviews.
// Files aspect (todo_0417): git-derived superset of files modified across this
// worker's (non-archived) todos, via the `Todo:` commit trailer. Leaf view — no
// sub-item list; click a file to open it. Git = ground-truth change history.
export function WorkerFilesView({ todoIds }: { todoIds: string[] }): JSX.Element {
  // The worker-wide Files view = the full Git File View (timeline, diff, before/
  // after, per-file attribution) scoped to the UNION of this worker's todos, via
  // the `Todo:` commit trailer. Normalize to leaf ids (todo_NNNN) — the trailer
  // form the Git File View filters on. Empty (data sparsity) → a clear note; never
  // broaden the filter to fake-populate.
  const leafIds = useMemo(() => {
    const s = new Set<string>();
    for (const id of todoIds) { const m = (id || '').match(/todo_\d+/g); if (m) s.add(m[m.length - 1]); }
    return [...s];
  }, [todoIds]);
  // The `Todo:` trailer discipline is recent, so a ~180-day window captures a
  // worker's todo-attributed commits without loading the whole repo history.
  const since = useMemo(() => new Date(Date.now() - 180 * 86400000).toISOString().slice(0, 10), []);
  const gitFilter = useMemo(() => ({ kind: 'todos' as const, values: leafIds }), [leafIds]);
  if (leafIds.length === 0) {
    return (
      <div className="pe-detail-body pe-files">
        <div className="pe-note">No todos assigned to this worker yet — nothing to show. (Files are attributed via the <code>Todo:</code> commit trailer.)</div>
      </div>
    );
  }
  return (
    <div className="pe-files-git">
      <GitFileViewPane embedded showScopeBar={false} allowScopeChange={false}
        dir="ai_general" since={since} filter={gitFilter} />
    </div>
  );
}

function VitalSignsBar({ todos }: { todos: TodoItem[] }): JSX.Element {
  // Filter the bar by status and/or a "since" date (todo_0623 #1.3); persisted.
  const initialFilter = useMemo(() => loadVitalsFilter(), []);
  const [statusFilter, setStatusFilter] = useState<Set<string>>(() => {
    const known = (initialFilter.statuses || []).filter(s => STATUS_SEQ.includes(s));
    // v1 briefly used [] to mean "no restriction", while StatusFilterMenu defines
    // [] as None. Migrate that stored default to All; schema v2 can persist a real None.
    if (initialFilter.statuses === null
        || (initialFilter.schemaV < 2 && known.length === 0)
        || (initialFilter.statuses.length > 0 && known.length === 0)) {
      return new Set(STATUS_SEQ);
    }
    return new Set(known);
  });
  const [since, setSince] = useState<string>(() => initialFilter.since);
  useEffect(() => { saveVitalsFilter([...statusFilter], since); }, [statusFilter, since]);
  const filterActive = statusFilter.size !== STATUS_SEQ.length || !!since;
  const toggleStatus = (s: string) => setStatusFilter(prev => { const n = new Set(prev); if (n.has(s)) n.delete(s); else n.add(s); return n; });
  const clearFilter = () => { setStatusFilter(new Set(STATUS_SEQ)); setSince(''); };

  const filtered = useMemo(() => todos.filter(t => {
    if (!statusFilter.has(t.status)) return false;
    if (since) { const d = itemDate(t); if (!d || d.slice(0, 10) < since) return false; }
    return true;
  }), [todos, statusFilter, since]);

  const counts = useMemo(() => {
    const m: Record<string, number> = {};
    filtered.forEach(t => { m[t.status] = (m[t.status] || 0) + 1; });
    return m;
  }, [filtered]);
  // Group todos per status so a segment's tooltip can list the actual work items
  // (id + title), capped at 10 (todo_0623 #1.4).
  const byStatus = useMemo(() => {
    const m: Record<string, TodoItem[]> = {};
    filtered.forEach(t => { (m[t.status] ||= []).push(t); });
    return m;
  }, [filtered]);
  const segTitle = (s: string): string => {
    const list = byStatus[s] || [];
    const lines = list.slice(0, 10).map(t => {
      const num = (t.id || t.dirName || t.name || '').match(/todo_\d+/)?.[0];
      return `${num ? num + ' — ' : ''}${t.name}`.trim();
    });
    const more = list.length > 10 ? `\n…and ${list.length - 10} more` : '';
    return `${statusLabelPE(s)} · ${list.length}\n${lines.join('\n')}${more}`;
  };
  const total = filtered.length;
  const present = STATUS_SEQ.filter(s => counts[s]);
  const openCount = filtered.filter(t => OPEN_STATUS(t.status)).length;
  const blocked = counts['Blocked'] || 0;

  if (todos.length === 0) {
    return <div className="pe-vitals pe-vitals-empty">No work items assigned yet.</div>;
  }
  return (
    <div className="pe-vitals">
      <div className="pe-vitals-head">
        <span className="pe-vitals-title">Work</span>
        <span className="pe-vitals-stat">{openCount} open</span>
        {blocked > 0 && <span className="pe-vitals-stat pe-vitals-blocked">{blocked} blocked</span>}
        <span className="pe-vitals-stat pe-vitals-total">{filterActive ? `${total} of ${todos.length}` : `${total} total`}</span>
      </div>
      <div className="pe-vitals-filters">
        <StatusFilterMenu
          statuses={STATUS_SEQ} active={statusFilter} onToggle={toggleStatus}
          onAll={() => setStatusFilter(new Set(STATUS_SEQ))} onNone={() => setStatusFilter(new Set())}
          statusColor={statusColor} statusLabel={statusLabelPE}
        />
        <label className="pe-vitals-since">since <input type="date" value={since} onChange={e => setSince(e.target.value)} /></label>
        {filterActive && <button className="pe-vitals-clear" onClick={clearFilter} title="Clear the work filter">clear</button>}
      </div>
      {total === 0
        ? <div className="pe-note pe-vitals-nomatch">No work items match this filter.</div>
        : <>
      <div className="pe-vitals-bar">
        {present.map(s => {
          const c = counts[s]; const pct = (c / total) * 100;
          return (
            <div key={s} className="pe-vitals-seg" style={{ width: `${pct}%`, background: statusColor(s) }}
              title={segTitle(s)}>
              <span className="pe-vitals-seg-lbl">{pct > 8 ? `${abbrFor(s)} ${c}` : c}</span>
            </div>
          );
        })}
      </div>
      <div className="pe-vitals-legend">
        {present.map(s => (
          <span key={s} className="pe-vitals-leg">
            <span className="pe-vitals-dot" style={{ background: statusColor(s) }} />
            {statusLabelPE(s)} <b>{counts[s]}</b>
          </span>
        ))}
      </div>
      </>}
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


interface ProjectEditorProps {
  /** Worker = project | team (a project with the 'team' tag). Omit when `session` is set. */
  project?: ProjectCard;
  /** Session-worker mode — renders the same aspect page scoped to one session (Chat|Work subtab). */
  session?: SessionCard;
  sessions?: SessionCard[];
}

export default function ProjectEditor({ project, session, sessions = [] }: ProjectEditorProps): JSX.Element {
  const kind: WorkerKind = session ? 'session' : (project?.tags.includes('team') ? 'team' : 'project');
  // isProject inversion: Team is the base worker; only a genuine Project unlocks the
  // Project-only aspects (Docs, …). (Discriminant still reads the registry type via
  // the tag today; a future step can make isProject a first-class registry field.)
  const isProject = kind === 'project';
  const aspects = useMemo(() => {
    // Base = a Team's aspects; a session worker also drops the Team aspect.
    const base = kind === 'session' ? ASPECTS.filter(a => a.key !== 'team') : ASPECTS;
    if (!isProject) return base;
    // Project unlocks Playbook (before Work List) and Workspace (after Work List).
    const [playbook, workspace] = PROJECT_ASPECTS;
    const i = base.findIndex(a => a.key === 'work');
    if (i < 0) return [...base, ...PROJECT_ASPECTS];
    return [...base.slice(0, i), playbook, base[i], workspace, ...base.slice(i + 1)];
  }, [kind, isProject]);
  const persistKey = session ? `sess:${session.tracking_id}` : `proj:${String(project?.entity_id || project?.project_id || '')}`;
  const defaultAspect: AspectKey = kind === 'team' ? 'team' : 'overview';
  const [sel, setSel] = useState<Selection>(() => {
    const saved = loadAspect(persistKey);
    return {
      // Validate before the first paint, not only in the effect below, so an old
      // Project-only aspect cannot briefly render a blank Team surface.
      aspect: saved && aspects.some(a => a.key === saved) ? saved : defaultAspect,
      itemId: null,
    };
  });
  // Restore/persist the focused aspect (todo_0623 #3). If a restored aspect isn't valid
  // for this worker (e.g. a saved 'playbook' on a Team), fall back to the default.
  useEffect(() => {
    if (!aspects.some(a => a.key === sel.aspect)) {
      setSel(s => ({ ...s, aspect: defaultAspect }));
      return;
    }
    saveAspect(persistKey, sel.aspect);
  }, [persistKey, sel.aspect, aspects, defaultAspect]);
  const [selectedFile, setSelectedFile] = useState<FsEntry | null>(null);
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [todosLoaded, setTodosLoaded] = useState(false);
  // WorkSurface asks for finalized (Done/Cancelled) todos when those status pills
  // are toggled on; the engine hides them by default.
  const [wantFinalized, setWantFinalized] = useState(false);

  // Work List todos — the full set (scoped to this worker by `visibleTodos` below).
  const reloadTodos = useCallback(() => {
    window.uai.todos.list(wantFinalized)
      .then(rows => { setTodos(rows as TodoItem[]); setTodosLoaded(true); })
      .catch(() => setTodosLoaded(true));
  }, [wantFinalized]);
  useEffect(() => { reloadTodos(); }, [reloadTodos]);

  // Roster: a curated member list for BOTH teams AND projects (PianoMan, todo_0320:
  // "Project membership should work just like Teams" — NOT auto-derived from the
  // working dir). Registry `members:` (assigned_ais), resolved to live sessions or a
  // name-only pseudo-card; session worker → itself.
  const roster = useMemo(() => {
    if (kind === 'session') return session ? [session] : [];
    return (project?.assigned_ais || []).map(m =>
      sessions.find(s => s.display_name === m || s.tracking_id === m)
      ?? ({ entity_id: `member:${m}`, tracking_id: m, display_name: m, platform: '', roles: [], project_dir: '', archived: false } as unknown as SessionCard));
  }, [kind, session, project, sessions]);

  // Work List filter — scope todos to THIS worker via the shared work-scope helper
  // (A1), the SAME scoping the worker-Tab WorkSurface reuses. Rows carry both the
  // WorkItem and TodoItem field sets (same engine payload), so cast across.
  const workerId = project ? String(project.entity_id || '').replace(/^(project|team):/, '') : '';
  const visibleTodos = useMemo(() => {
    const all = todos as unknown as WorkItem[];
    const members = roster.map(s => s.tracking_id).filter(Boolean) as string[];
    const scoped = kind === 'session'
      ? scopeTodos({ kind: 'session', trackingId: session?.tracking_id || '' }, all)
      : kind === 'project'
        ? scopeTodos({ kind: 'project', id: workerId, memberTrackingIds: members }, all)
        : scopeTodos({ kind: 'team', id: workerId, memberTrackingIds: members }, all);
    return scoped as unknown as TodoItem[];
  }, [kind, todos, session, workerId, roster]);

  // Conversations for this worker's participants (gated to the Comms aspect).
  const { conversations, loading: convLoading } = useProjectConversations(
    roster.map(s => s.tracking_id).filter(Boolean), sel.aspect === 'comms');

  // worker title-bar display
  const displayName = session ? (session.display_name || session.tracking_id.slice(0, 16)) : project!.display_name;
  const crumbIcon = kind === 'session' ? '🖥' : '📁';
  // Clarified from the cryptic "active · main · unknown" (todo_0623 #3): the three
  // parts are the project lifecycle, the git branch, and the git working-tree status.
  const statusLine = session
    ? `● ${session.process_status || 'session'}${session.platform ? ' · ' + session.platform : ''}`
    : `● ${project!.lifecycle_status || 'project'} · ⑂ ${project!.branch || 'main'} · git: ${project!.git_status}`;
  const statusTitle = session
    ? 'Process status · platform'
    : 'Project lifecycle · git branch (⑂) · git working-tree status';

  const setAspect = (aspect: AspectKey) => { setSel({ aspect, itemId: null }); setSelectedFile(null); };
  const selectItem = (aspect: AspectKey, itemId: string) => setSel({ aspect, itemId });
  const openSession = (trackingId: string) =>
    executeCommand('workspace.tabs.open', { type: 'session', targetId: trackingId });

  // "Delete" == HIDE (todo_0532). Flips a visibility flag; NEVER deletes/moves any
  // files or directories. Reversible (restore via CLI: projects_mgr/teams_mgr
  // `update <id> --hidden false`). Confirm makes the non-destructive nature explicit.
  const [hiding, setHiding] = useState(false);
  const hideWorker = useCallback(() => {
    if (!project) return;
    const name = project.display_name;
    const ok = window.confirm(
      `Hide "${name}" from the workspace?\n\nThis does NOT delete any files or directories — it only hides ${kind === 'team' ? 'the team' : 'the project'} from the lists. You can restore it later.`,
    );
    if (!ok) return;
    setHiding(true);
    const id = String(project.entity_id || project.project_id || '').replace(/^(project|team):/, '');
    executeCommand(kind === 'team' ? 'team.setHidden' : 'project.setHidden', {
      id,
      hidden: true,
      sourcePath: project.source_path,
    }).finally(() => setHiding(false));
  }, [project, kind]);

  // Set/clear a team role from the Members & Roles view. Writes role_assignments
  // in the entity's registry yml via the command bus (member=null clears). The
  // card store refreshes on the resulting 'teams'/'projects' change event, so the
  // roles re-render without a manual reload.
  const roleCmd = useCallback((verb: 'setRoleAssignment' | 'addRole' | 'removeRole', payload: Record<string, unknown>) => {
    if (!project) return;
    const id = String(project.entity_id || project.project_id || '').replace(/^(project|team):/, '');
    executeCommand(`${kind === 'team' ? 'team' : 'project'}.${verb}`, { id, sourcePath: project.source_path, ...payload });
  }, [project, kind]);
  const setRole = useCallback((role: string, member: string | null) => roleCmd('setRoleAssignment', { role, member }), [roleCmd]);
  const addRole = useCallback((role: string) => roleCmd('addRole', { role }), [roleCmd]);
  const removeRole = useCallback((role: string) => roleCmd('removeRole', { role }), [roleCmd]);
  const setRoleContext = useCallback((role: string, context: string | null) => {
    if (!project) return;
    const id = String(project.entity_id || project.project_id || '').replace(/^(project|team):/, '');
    executeCommand(kind === 'team' ? 'team.setRoleContext' : 'project.setRoleContext', { id, role, context, sourcePath: project.source_path });
  }, [project, kind]);

  // Members: the registry `members:` list (names). add/remove recompute the whole
  // list and send it back through setMembers.
  const currentMembers = useMemo(() => (project?.assigned_ais || []).slice(), [project]);
  const setMembersCmd = useCallback((members: string[]) => {
    if (!project) return;
    const id = String(project.entity_id || project.project_id || '').replace(/^(project|team):/, '');
    executeCommand(kind === 'team' ? 'team.setMembers' : 'project.setMembers', { id, members, sourcePath: project.source_path });
  }, [project, kind]);
  const addMember = useCallback((name: string) => {
    if (!name || currentMembers.includes(name)) return;
    setMembersCmd([...currentMembers, name]);
  }, [currentMembers, setMembersCmd]);
  const removeMember = useCallback((name: string) => setMembersCmd(currentMembers.filter(m => m !== name)), [currentMembers, setMembersCmd]);

  // Promote a Team → Project (todo_0320): creates a home directory and converts the
  // registry file .team.yml → .proj.yml (members/roles carry over). PianoMan clicking
  // is the approval. window.prompt is disabled in Electron, so the folder name is
  // derived from the team name; confirm makes the registry rename explicit.
  const [promoting, setPromoting] = useState(false);
  const promoteWorker = useCallback(() => {
    if (!project) return;
    const ok = window.confirm(
      `Promote "${project.display_name}" to a Project?\n\nThis creates a home directory under ai_general/work/projects/ and renames the registry from .team.yml to .proj.yml. Members and roles carry over.`,
    );
    if (!ok) return;
    setPromoting(true);
    const id = String(project.entity_id || project.project_id || '').replace(/^(project|team):/, '');
    executeCommand('team.promoteToProject', { id, sourcePath: project.source_path }).finally(() => setPromoting(false));
  }, [project]);

  // Playbook folder set (todo_0320) — which top-level working_dir folders belong to
  // the Playbook; the rest fall to Workspace. Writes the project's registry list.
  const setPlaybookFolders = useCallback((folders: string[]) => {
    if (!project) return;
    const id = String(project.entity_id || project.project_id || '').replace(/^(project|team):/, '');
    executeCommand('project.setPlaybook', { id, folders, sourcePath: project.source_path });
  }, [project]);

  const selectedSession = sel.aspect === 'team' && sel.itemId
    ? roster.find(s => s.tracking_id === sel.itemId) || null
    : null;

  return (
    <div className="project-editor">
      <div className="pe-titlebar">
        <span className="pe-crumb-icon">{crumbIcon}</span>
        <span className="pe-crumb-project">{displayName}</span>
        <span className="pe-crumb-sep">›</span>
        <span className="pe-crumb-aspect">{aspects.find(a => a.key === sel.aspect)?.label}</span>
        <span className="pe-titlebar-spacer" />
        <span className="pe-titlebar-status" title={statusTitle}>{statusLine}</span>
        {project && kind === 'team' && (
          <button
            className="pe-titlebar-promote"
            title="Promote this team to a project — creates a home directory and unlocks project-only surfaces"
            disabled={promoting}
            onClick={promoteWorker}
          >
            {promoting ? 'Promoting…' : 'Promote to Project'}
          </button>
        )}
        {project && (
          <button
            className="pe-titlebar-delete"
            title={`Hide this ${kind === 'team' ? 'team' : 'project'} from the workspace (does not delete any files)`}
            disabled={hiding}
            onClick={hideWorker}
          >
            {hiding ? 'Hiding…' : 'Delete'}
          </button>
        )}
      </div>

      {/* ── Aspect tabs (was a left Navigator rail; PianoMan 2026-07-20 — aspects
             are tabs). Each aspect's own list + detail render full-width below. ── */}
      <div className="pe-subtabs" role="tablist">
        <div className="pe-subtabs-tabs">
          {aspects.map(a => (
            <button
              key={a.key}
              type="button"
              role="tab"
              aria-selected={sel.aspect === a.key}
              className={`pe-subtab${sel.aspect === a.key ? ' on' : ''}`}
              onClick={() => setAspect(a.key)}
              title={a.label}
            >
              <span className="pe-subtab-ic">{a.icon}</span>{a.label}
            </button>
          ))}
        </div>
      </div>

      <div className="pe-body">
        {/* ── Detail Area (full width) ─────────────────────────── */}
        <section className="pe-detail pe-detail-full">
          {sel.aspect === 'overview' && (
            <div className="pe-overview-wrap">
              {session
                ? <><VitalSignsBar todos={visibleTodos} /><SessionOverview session={session} convCount={conversations.length} /></>
                : <ProjectOverview
                    project={project!}
                    sessions={roster}
                    roleAssignments={project?.role_assignments || {}}
                    workSummary={<VitalSignsBar todos={visibleTodos} />}
                    onGotoTeam={() => setAspect('team')}
                    onGotoComms={() => setAspect('comms')}
                    onGotoWork={() => setAspect('work')}
                    onOpenSession={openSession}
                  />}
            </div>
          )}
          {sel.aspect === 'work' && (
            <WorkSurface
              todos={visibleTodos as unknown as WorkItem[]}
              loading={!todosLoaded}
              onReload={reloadTodos}
              onWantFinalized={setWantFinalized}
              viewportId="project_work_surface"
              emptyLabel="Select a work item from the list."
              stacked
            />
          )}
          {sel.aspect === 'team' && (
            <ProjectTeamDetail
              sessions={roster}
              allSessions={sessions}
              roleAssignments={project?.role_assignments || {}}
              roleContexts={project?.role_contexts || {}}
              selectedId={sel.itemId}
              onSelect={(id) => selectItem('team', id)}
              onOpenSession={openSession}
              onSetRole={setRole}
              onAddRole={addRole}
              onRemoveRole={removeRole}
              onSetRoleContext={setRoleContext}
              onAddMember={addMember}
              onRemoveMember={removeMember}
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
          {/* Playbook & Workspace — Project-only aspects (isProject unlock). Playbook =
              the working_dir folders defined as the Playbook; Workspace = the rest,
              with a Git File View toggle. */}
          {sel.aspect === 'playbook' && (
            <div className="pe-filebrowse">
              <div className="pe-filebrowse-main">
                <PlaybookView
                  workingDir={project?.working_dir || ''}
                  playbook={project?.playbook || []}
                  onSetPlaybook={setPlaybookFolders}
                  selectedPath={selectedFile?.path}
                  onSelectFile={setSelectedFile}
                />
              </div>
              {selectedFile && <aside className="pe-filebrowse-side"><FilePreviewPanel entry={selectedFile} /></aside>}
            </div>
          )}
          {sel.aspect === 'workspace' && (
            <div className="pe-filebrowse">
              <div className="pe-filebrowse-main">
                <WorkspaceView
                  workingDir={project?.working_dir || ''}
                  playbook={project?.playbook || []}
                  selectedPath={selectedFile?.path}
                  onSelectFile={setSelectedFile}
                />
              </div>
              {selectedFile && <aside className="pe-filebrowse-side"><FilePreviewPanel entry={selectedFile} /></aside>}
            </div>
          )}
        </section>

        {/* Detail-below strip: the selection inspector for aspects whose LIST lives
            in the main area (file tree, team roster). Replaces the removed right
            rail AND the "At a Glance" digest (PianoMan 2026-07-20 — the right panel
            broke the "shows what's selected" convention). Work items carry their
            own list+editor inside WorkSurface, so they need no inspector here. */}
        {/* Team-member inspector docks below (files now preview in the right panel of
            Playbook/Workspace — todo_0623 #5/#6.2). */}
        {selectedSession && (
          <aside className="pe-detail-below">
            <TeamMemberPanel session={selectedSession} onOpen={openSession} />
          </aside>
        )}
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


// WorkDetail (the bespoke work-aspect detail) was removed in todo_0544 — the Work
// aspect now mounts the shared <WorkSurface> (list + detail over the scoped set),
// the same rendering the global Work Mgr uses.
