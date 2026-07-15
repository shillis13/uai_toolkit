/**
 * ScheduledTasksPane -- Scheduled tasks manager UI (launchd-backed).
 *
 * Two tabs: Groups, Status.
 * Groups tab: split panel (list/detail) with enable/disable toggle, filter pills,
 * job table with inline edit, add-job, run-now, and log viewer.
 * Status tab: live launchd sync state from `scheduled_task_mgr.py status --json` --
 * per-group job table with schedule, installed flag, last-run (exit + time),
 * next-fire, and state, colored by last exit code. Drift banner from sync.inSync.
 *
 * All data is sourced through the scheduled_task_mgr.py CLI (single source of truth)
 * via the window.uai.scheduledTasks IPC namespace.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useToast } from './Toast';
import { TabNavArrows } from './TabNavArrows';
import { useViewport } from '../viewport';

// ---- Types ----------------------------------------------------------------

interface ScheduledGroup {
  name: string;
  description?: string;
  enabled: boolean;
  jobCount: number;
}

interface ScheduledJob {
  id: string;
  description: string;
  schedule: string;
  command: string;
  log?: string;
  background?: boolean;
}

interface ScheduledGroupDetail {
  name: string;
  description?: string;
  enabled: boolean;
  env: Record<string, string>;
  jobs: ScheduledJob[];
}

interface ScheduledTaskRun {
  label?: string;
  exit: number;
  ts: string;
}

interface ScheduledStatusJob {
  id: string;
  schedule: string;
  label: string;
  installed: boolean;
  enabled: boolean;
  once?: boolean;
  lastRun: ScheduledTaskRun | null;
  nextFire: string | null;
  state: string;
  // Exposed by Noctis's sched_run wrapper via status_all() (todo_0458 #6):
  command?: string;    // the TARGET script/command, un-wrapped
  jobLog?: string;     // per-job timestamped log path
  groupLog?: string;   // per-group timestamped log path
}

/** Group-level health rollup (mirrors the SwiftBar group badge). Health counts
 *  only ACTIVE (enabled) jobs; disabled is its own bucket. */
interface HealthRollup {
  healthy: number;   // 🟢 active & (last run ok | persistent-running)
  failed: number;    // 🔴 active & last run exit != 0
  pending: number;   // 🟡 active & (never run | not installed yet)
  disabled: number;  // ⏸ enabled === false
}

interface ScheduledStatusGroup {
  name: string;
  jobs: ScheduledStatusJob[];
}

/** A launchd agent in our namespace with NO YAML task def (hand-installed /
 *  convention-named). Parity with SwiftBar's "Other LaunchD Agents" section. */
interface UnmanagedAgent {
  label: string;
  friendly: string;
  loaded: boolean;
  pid: string | null;
  exit: number | null;
}

interface ScheduledTasksStatus {
  groups: ScheduledStatusGroup[];
  sync: { inSync: boolean; missing: string[]; extra: string[] };
  errors: string[];
  unmanaged?: UnmanagedAgent[];
}

// ---- Helpers ---------------------------------------------------------------

/** Convert a 5-field cron expression to human-readable English. */
function scheduleToEnglish(cron: string): string {
  if (!cron) return '';
  const trimmed = cron.trim();
  if (trimmed === '@reboot') return 'At system reboot';

  const parts = trimmed.split(/\s+/);
  if (parts.length < 5) return trimmed;
  const [min, hour, dom, mon, dow] = parts;

  // Common patterns
  if (min === '*' && hour === '*' && dom === '*' && mon === '*' && dow === '*')
    return 'Every minute';
  if (min.startsWith('*/')) {
    const n = min.slice(2);
    if (hour === '*' && dom === '*' && mon === '*' && dow === '*')
      return `Every ${n} minute${n === '1' ? '' : 's'}`;
  }
  if (hour.startsWith('*/')) {
    const n = hour.slice(2);
    if (min === '0' && dom === '*' && mon === '*' && dow === '*')
      return `Every ${n} hour${n === '1' ? '' : 's'}`;
  }
  if (dom === '*' && mon === '*' && dow === '*') {
    if (min !== '*' && hour !== '*')
      return `Daily at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
    if (min !== '*' && hour === '*')
      return `Hourly at :${min.padStart(2, '0')}`;
  }
  if (dom === '*' && mon === '*' && dow !== '*') {
    const dayNames: Record<string, string> = { '0': 'Sun', '1': 'Mon', '2': 'Tue', '3': 'Wed', '4': 'Thu', '5': 'Fri', '6': 'Sat', '7': 'Sun' };
    const days = dow.split(',').map(d => dayNames[d] || d).join(', ');
    if (min !== '*' && hour !== '*')
      return `${days} at ${hour.padStart(2, '0')}:${min.padStart(2, '0')}`;
  }

  return trimmed;
}

type SchedTab = 'groups' | 'status';
type GroupFilter = 'all' | 'enabled' | 'disabled';

// ---- Sub-views -------------------------------------------------------------

/** Format an ISO timestamp (UTC `...Z` or naive-local) to a short local string. */
function fmtTime(ts?: string | null): string {
  if (!ts) return '—';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// ── Log rendering: strip ANSI, colour by severity (todo_0440 #1/#2, todo_0458 #2) ──
// Raw logs arrive with terminal colour codes (e.g. \x1b[36m…\x1b[0m) and, for jobs
// installed through Noctis's sched_run wrapper, lines tagged `[ts] [OUT|ERR] …`.
// We strip the escape codes and colour each line by severity so a failure reads AS
// a failure instead of hiding in a wall of grey text.
const ANSI_RE = /\x1b\[[0-9;]*m/g;   // eslint-disable-line no-control-regex
function stripAnsi(s: string): string { return (s || '').replace(ANSI_RE, ''); }

type LogSeverity = 'err' | 'warn' | 'meta' | '';
function logLineSeverity(line: string): LogSeverity {
  const t = line.trim();
  if (!t) return '';
  // sched_run wrapper stream tag wins: `[2026-… ] [ERR] …` / `[OUT]`.
  const tag = /\]\s*\[(OUT|ERR)\]/.exec(line);
  if (tag) return tag[1] === 'ERR' ? 'err' : '';
  // Wrapper header/footer framing: `=== group/job START … ===`.
  if (/^===.*===$/.test(t)) return 'meta';
  if (/(^|\b)(error|traceback|exception|fatal|cannot|can['’]t open|no such file|permission denied|denied|unauthorized|forbidden|refused|failed|fail(ure)?)\b|\b(401|403|404|500|502|503)\b/i.test(t)) return 'err';
  if (/(^|\b)(warn(ing)?|deprecat|retry|skipp?ed)\b/i.test(t)) return 'warn';
  return '';
}

/** ANSI-stripped, severity-coloured log block. Replaces raw <pre> log dumps. */
function LogView({ text, className, empty }: { text?: string | null; className?: string; empty?: string }): JSX.Element {
  const clean = stripAnsi(text || '').replace(/\s+$/, '');
  if (!clean) return <pre className={`sched-mgr-log-content sched-log ${className || ''}`}>{empty || '(empty)'}</pre>;
  const lines = clean.split('\n');
  return (
    <pre className={`sched-mgr-log-content sched-log ${className || ''}`}>
      {lines.map((ln, i) => {
        const sev = logLineSeverity(ln);
        return (
          <span key={i} className={`sched-log-line${sev ? ' sev-' + sev : ''}`}>{ln || ' '}{'\n'}</span>
        );
      })}
    </pre>
  );
}

// ── Canonical job status — JOB_STATUS_MODEL.md (SwiftBar + UAI must match) ──
//  One classifier collapses STATE (lifecycle) + HEALTH (last run) into a single
//  canonical COLOUR + glyph + state chip + rollup bucket. Evaluation ORDER is
//  load-bearing: `.once` is checked BEFORE `.installed` so a self-retired once
//  job doesn't read "not-installed", and an ARMED (re-armed) once job ignores a
//  stale prior lastRun failure. Keep this in lockstep with the doc.
type JobColour = 'green' | 'red' | 'amber' | 'gray';
type RollupBucket = 'healthy' | 'failed' | 'pending' | 'paused';

interface JobStatus {
  colour: JobColour;
  stateLabel: string;   // lifecycle chip text
  healthLabel: string;  // health-dot tooltip
  bucket: RollupBucket;
}

function classifyJob(job: ScheduledStatusJob): JobStatus {
  const exit = job.lastRun ? job.lastRun.exit : null;
  // 1. once job — classified FIRST (before the installed check).
  if (job.once) {
    const armed = job.installed && job.enabled && job.state !== 'disabled';
    if (armed) {
      // Re-armed once job fires fresh — ignore any stale prior lastRun.
      return { colour: 'green', stateLabel: 'once · armed', healthLabel: 'Armed (once) — yet to run', bucket: 'healthy' };
    }
    if (exit != null && exit !== 0) {
      return { colour: 'red', stateLabel: 'once · failed', healthLabel: `Once job failed (exit ${exit})`, bucket: 'failed' };
    }
    return { colour: 'gray', stateLabel: 'once · done', healthLabel: 'Once job done', bucket: 'paused' };
  }
  // 2. not enabled / disabled
  if (!job.enabled || job.state === 'disabled') {
    return { colour: 'gray', stateLabel: 'disabled', healthLabel: 'Disabled', bucket: 'paused' };
  }
  // 3. not installed
  if (!job.installed) {
    return { colour: 'amber', stateLabel: 'not-installed', healthLabel: 'Defined but not installed', bucket: 'pending' };
  }
  // 4. persistent (KeepAlive — running, no discrete last run)
  if (job.state === 'persistent') {
    return { colour: 'green', stateLabel: 'persistent', healthLabel: 'Persistent (running)', bucket: 'healthy' };
  }
  // 5. recurring, last run failed
  if (exit != null && exit !== 0) {
    return { colour: 'red', stateLabel: 'enabled', healthLabel: `Last run failed (exit ${exit})`, bucket: 'failed' };
  }
  // 6. recurring, never run (pending — unproven until first run)
  if (job.lastRun == null) {
    return { colour: 'amber', stateLabel: 'enabled', healthLabel: 'Scheduled, no runs yet', bucket: 'pending' };
  }
  // 7. recurring, last run ok
  return { colour: 'green', stateLabel: 'enabled', healthLabel: 'Last run OK', bucket: 'healthy' };
}

/** Health-dot class from the canonical colour. */
function jobStatusClass(job: ScheduledStatusJob): string {
  return `sched-mgr-jobstat-${classifyJob(job).colour}`;
}

/** Health-dot tooltip. */
function jobStatusLabel(job: ScheduledStatusJob): string {
  return classifyJob(job).healthLabel;
}

/** LIFECYCLE STATE chip (label + colour class), tinted by the canonical colour. */
function jobStateChip(job: ScheduledStatusJob): { label: string; cls: string } {
  const s = classifyJob(job);
  return { label: s.stateLabel, cls: `sched-mgr-state-${s.colour}` };
}

/** Roll a group's jobs up into the four buckets via the canonical classifier. */
function rollupForJobs(jobs: ScheduledStatusJob[]): HealthRollup {
  const r: HealthRollup = { healthy: 0, failed: 0, pending: 0, disabled: 0 };
  for (const j of jobs) {
    const b = classifyJob(j).bucket;
    if (b === 'healthy') r.healthy++;
    else if (b === 'failed') r.failed++;
    else if (b === 'pending') r.pending++;
    else r.disabled++;   // 'paused' (disabled + once-done)
  }
  return r;
}

/** Compact group rollup badge: 🟢N 🔴M 🟡K ⏸D (non-zero buckets only). */
function GroupRollupBadge({ rollup }: { rollup: HealthRollup }): JSX.Element | null {
  const parts: Array<{ glyph: string; n: number; cls: string; title: string }> = [
    { glyph: '🟢', n: rollup.healthy, cls: 'ok', title: 'healthy (ok / running / once-armed)' },
    { glyph: '🔴', n: rollup.failed, cls: 'fail', title: 'failed last run' },
    { glyph: '🟡', n: rollup.pending, cls: 'pending', title: 'pending (never-run / not-installed)' },
    { glyph: '⏸', n: rollup.disabled, cls: 'disabled', title: 'paused / done (disabled / once-done)' },
  ].filter(p => p.n > 0);
  if (parts.length === 0) return null;
  return (
    <span className="sched-mgr-rollup">
      {parts.map(p => (
        <span key={p.cls} className={`sched-mgr-rollup-item sched-mgr-rollup-${p.cls}`} title={`${p.n} ${p.title}`}>
          {p.glyph}{p.n}
        </span>
      ))}
    </span>
  );
}

/** Health colour + state label for an UNMANAGED agent (mirrors SwiftBar):
 *  not-loaded → gray; loaded with a non-zero exit → red; else running/loaded → green. */
function unmanagedStatus(a: UnmanagedAgent): { colour: JobColour; label: string } {
  if (!a.loaded) return { colour: 'gray', label: 'not loaded' };
  if (a.exit != null && a.exit !== 0) return { colour: 'red', label: `loaded (exit ${a.exit})` };
  if (a.pid) return { colour: 'green', label: `running (pid ${a.pid})` };
  return { colour: 'green', label: a.exit != null ? `loaded (exit ${a.exit})` : 'loaded' };
}

// ---- Main Component --------------------------------------------------------

interface ScheduledTasksPaneProps {
  tabId?: string;
}

export default function ScheduledTasksPane({ tabId }: ScheduledTasksPaneProps): JSX.Element {
  const { showToast } = useToast();

  // State
  const [activeTab, setActiveTab] = useState<SchedTab>('groups');
  const [groups, setGroups] = useState<ScheduledGroup[]>([]);
  const [selectedGroup, setSelectedGroup] = useState<string | null>(null);
  const [groupDetail, setGroupDetail] = useState<ScheduledGroupDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState<GroupFilter>('all');
  const [mutating, setMutating] = useState(false);

  // Status tab
  const [status, setStatus] = useState<ScheduledTasksStatus | null>(null);
  const [statusLoading, setStatusLoading] = useState(false);
  // inSync starts as null (loading), becomes true/false after fetch
  const [inSync, setInSync] = useState<boolean | null>(null);
  const [dryRunPreview, setDryRunPreview] = useState<string | null>(null);

  // Run job state
  const [runningJobId, setRunningJobId] = useState<string | null>(null);
  const [runOutput, setRunOutput] = useState<{ stdout: string; stderr: string; exitCode: number } | null>(null);

  // Log viewer
  const [logViewJob, setLogViewJob] = useState<{ group: string; jobId: string } | null>(null);
  const [logContent, setLogContent] = useState<string>('');
  const [logLoading, setLogLoading] = useState(false);

  // Script peek (todo_0440 #3, todo_0458 #7) — Context-Mgr-style source peek.
  const [peekJob, setPeekJob] = useState<{ jobId: string; path: string; content: string; loading: boolean; error?: string } | null>(null);

  // Consolidated group logs (item 5): tail every job's log in the selected group.
  const [groupLogs, setGroupLogs] = useState<Array<{ jobId: string; content: string }> | null>(null);
  const [groupLogsLoading, setGroupLogsLoading] = useState(false);

  // Inline edit
  const [editingJob, setEditingJob] = useState<string | null>(null);
  const [editFields, setEditFields] = useState<Record<string, string>>({});

  // Add job form
  const [showAddJob, setShowAddJob] = useState(false);
  const [newJob, setNewJob] = useState({ id: '', schedule: '', command: '', description: '', log: '' });

  // Create group form
  const [showCreateGroup, setShowCreateGroup] = useState(false);
  const [newGroup, setNewGroup] = useState({ name: '', description: '', jobId: '', schedule: '', command: '', jobDescription: '', log: '' });

  // Delete confirmation
  const [confirmDelete, setConfirmDelete] = useState<{ type: 'group' | 'job'; group: string; jobId?: string } | null>(null);

  // ---- Data loading --------------------------------------------------------

  const loadGroups = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await window.uai.scheduledTasks.listGroups();
      setGroups(result);
    } catch (err: any) {
      setError(err.message || 'Failed to load groups');
    } finally {
      setLoading(false);
    }
  }, []);

  const loadGroupDetail = useCallback(async (name: string) => {
    setDetailLoading(true);
    try {
      const detail = await window.uai.scheduledTasks.viewGroup(name);
      setGroupDetail(detail);
    } catch {
      setGroupDetail(null);
    } finally {
      setDetailLoading(false);
    }
  }, []);

  const loadStatus = useCallback(async () => {
    setStatusLoading(true);
    try {
      const result = await window.uai.scheduledTasks.getStatus();
      setStatus(result);
      setInSync(result?.sync?.inSync ?? false);
    } catch {
      setStatus(null);
      setInSync(false);
    } finally {
      setStatusLoading(false);
    }
  }, []);

  // Load groups + status on mount. Status is needed on the GROUPS tab too, so the
  // per-group health rollup (failures) surfaces without switching to the Status tab.
  useEffect(() => { loadGroups(); loadStatus(); }, [loadGroups, loadStatus]);

  // Load detail when group selected
  useEffect(() => {
    if (selectedGroup) {
      loadGroupDetail(selectedGroup);
      setEditingJob(null);
      setShowAddJob(false);
      setLogViewJob(null);
      setRunOutput(null);
      setConfirmDelete(null);
    } else {
      setGroupDetail(null);
    }
  }, [selectedGroup, loadGroupDetail]);

  // Load tab-specific data on tab change
  useEffect(() => {
    if (activeTab === 'status') { loadStatus(); }
  }, [activeTab, loadStatus]);

  // ---- Mutations -----------------------------------------------------------

  const handleToggleGroup = useCallback(async (groupName: string, currentEnabled: boolean) => {
    setMutating(true);
    try {
      const result = currentEnabled
        ? await window.uai.scheduledTasks.disableGroup(groupName)
        : await window.uai.scheduledTasks.enableGroup(groupName);
      if (result.ok) {
        showToast(`Group '${groupName}' ${currentEnabled ? 'disabled' : 'enabled'}. Run Install to apply to launchd.`, 'info');
        await loadGroups();
        if (selectedGroup === groupName) await loadGroupDetail(groupName);
      } else {
        showToast(result.error || 'Failed to toggle group', 'error');
      }
    } catch (err: any) {
      showToast(err.message || 'Failed', 'error');
    } finally {
      setMutating(false);
    }
  }, [selectedGroup, loadGroups, loadGroupDetail, showToast]);

  const handleCreateGroup = useCallback(async () => {
    if (!newGroup.name || !newGroup.jobId || !newGroup.schedule || !newGroup.command) {
      showToast('Name, Job ID, Schedule, and Command are required', 'error');
      return;
    }
    setMutating(true);
    try {
      const result = await window.uai.scheduledTasks.createGroup({
        name: newGroup.name,
        description: newGroup.description || undefined,
        firstJob: {
          id: newGroup.jobId,
          schedule: newGroup.schedule,
          command: newGroup.command,
          description: newGroup.jobDescription || undefined,
          log: newGroup.log || undefined,
        },
      });
      if (result.ok) {
        showToast(`Group '${newGroup.name}' created`, 'info');
        setShowCreateGroup(false);
        setNewGroup({ name: '', description: '', jobId: '', schedule: '', command: '', jobDescription: '', log: '' });
        await loadGroups();
        setSelectedGroup(newGroup.name);
      } else {
        showToast(result.error || 'Failed to create group', 'error');
      }
    } catch (err: any) {
      showToast(err.message || 'Failed', 'error');
    } finally {
      setMutating(false);
    }
  }, [newGroup, loadGroups, showToast]);

  const handleAddJob = useCallback(async () => {
    if (!selectedGroup || !newJob.id || !newJob.schedule || !newJob.command) {
      showToast('Job ID, Schedule, and Command are required', 'error');
      return;
    }
    setMutating(true);
    try {
      const result = await window.uai.scheduledTasks.addJob(selectedGroup, {
        id: newJob.id,
        schedule: newJob.schedule,
        command: newJob.command,
        description: newJob.description || undefined,
        log: newJob.log || undefined,
      });
      if (result.ok) {
        showToast(`Job '${newJob.id}' added`, 'info');
        setShowAddJob(false);
        setNewJob({ id: '', schedule: '', command: '', description: '', log: '' });
        await loadGroupDetail(selectedGroup);
        await loadGroups();
      } else {
        showToast(result.error || 'Failed to add job', 'error');
      }
    } catch (err: any) {
      showToast(err.message || 'Failed', 'error');
    } finally {
      setMutating(false);
    }
  }, [selectedGroup, newJob, loadGroupDetail, loadGroups, showToast]);

  const handleSaveJobEdit = useCallback(async (jobId: string) => {
    if (!selectedGroup) return;
    setMutating(true);
    try {
      const patch: Record<string, string | undefined> = {};
      if (editFields.schedule !== undefined) patch.schedule = editFields.schedule;
      if (editFields.command !== undefined) patch.command = editFields.command;
      if (editFields.description !== undefined) patch.description = editFields.description;
      if (editFields.log !== undefined) patch.log = editFields.log;
      const result = await window.uai.scheduledTasks.editJob(selectedGroup, jobId, patch);
      if (result.ok) {
        showToast(`Job '${jobId}' updated`, 'info');
        setEditingJob(null);
        setEditFields({});
        await loadGroupDetail(selectedGroup);
      } else {
        showToast(result.error || 'Failed to edit job', 'error');
      }
    } catch (err: any) {
      showToast(err.message || 'Failed', 'error');
    } finally {
      setMutating(false);
    }
  }, [selectedGroup, editFields, loadGroupDetail, showToast]);

  const handleDeleteGroup = useCallback(async (groupName: string) => {
    setMutating(true);
    try {
      const result = await window.uai.scheduledTasks.deleteGroup(groupName);
      if (result.ok) {
        showToast(`Group '${groupName}' deleted`, 'info');
        setConfirmDelete(null);
        if (selectedGroup === groupName) { setSelectedGroup(null); setGroupDetail(null); }
        await loadGroups();
      } else {
        showToast(result.error || 'Failed to delete group', 'error');
      }
    } catch (err: any) {
      showToast(err.message || 'Failed', 'error');
    } finally {
      setMutating(false);
    }
  }, [selectedGroup, loadGroups, showToast]);

  const handleDeleteJob = useCallback(async (groupName: string, jobId: string) => {
    setMutating(true);
    try {
      const result = await window.uai.scheduledTasks.deleteJob(groupName, jobId);
      if (result.ok) {
        showToast(`Job '${jobId}' deleted`, 'info');
        setConfirmDelete(null);
        await loadGroupDetail(groupName);
        await loadGroups();
      } else {
        showToast(result.error || 'Failed to delete job', 'error');
      }
    } catch (err: any) {
      showToast(err.message || 'Failed', 'error');
    } finally {
      setMutating(false);
    }
  }, [loadGroupDetail, loadGroups, showToast]);

  const handleRunJob = useCallback(async (groupName: string, jobId: string) => {
    setRunningJobId(jobId);
    setRunOutput(null);
    try {
      const result = await window.uai.scheduledTasks.runJob(groupName, jobId);
      setRunOutput({ stdout: result.stdout, stderr: result.stderr, exitCode: result.exitCode });
    } catch (err: any) {
      setRunOutput({ stdout: '', stderr: err.message || 'Failed', exitCode: -1 });
    } finally {
      setRunningJobId(null);
    }
  }, []);

  const handleViewLog = useCallback(async (groupName: string, jobId: string) => {
    setLogViewJob({ group: groupName, jobId });
    setLogLoading(true);
    try {
      const content = await window.uai.scheduledTasks.getLogTail(groupName, jobId, 50);
      setLogContent(content);
    } catch {
      setLogContent('');
    } finally {
      setLogLoading(false);
    }
  }, []);

  // Peek the target SCRIPT source (todo_0440 #3 / todo_0458 #7). Pulls the first
  // script-looking token out of the job command and reads it (fs.readFile resolves
  // $AI_ROOT / relative paths); toggles closed if the same job is peeked again.
  const handlePeekJob = useCallback(async (jobId: string, command: string) => {
    if (peekJob && peekJob.jobId === jobId) { setPeekJob(null); return; }
    const m = /(\S+\.(?:py|sh|js|mjs|cjs|ts|rb|pl|zsh|bash))\b/.exec(command || '');
    if (!m) { setPeekJob({ jobId, path: '', content: '', loading: false, error: 'No script path found in this job command.' }); return; }
    const scriptPath = m[1].replace(/^["']|["']$/g, '');
    setPeekJob({ jobId, path: scriptPath, content: '', loading: true });
    try {
      const r = await window.uai.fs.readFile(scriptPath);
      if (r.ok) setPeekJob({ jobId, path: scriptPath, content: r.content || '', loading: false });
      else setPeekJob({ jobId, path: scriptPath, content: '', loading: false, error: r.error || 'read failed' });
    } catch (err: any) {
      setPeekJob({ jobId, path: scriptPath, content: '', loading: false, error: err?.message || 'read failed' });
    }
  }, [peekJob]);

  // Consolidated logs: tail every logged job in the group in parallel (item 5).
  const loadGroupLogs = useCallback(async (gname: string, jobs: ScheduledJob[]) => {
    const withLogs = jobs.filter(j => j.log);
    if (withLogs.length === 0) { setGroupLogs([]); return; }
    setGroupLogsLoading(true);
    try {
      const results = await Promise.all(withLogs.map(async j => {
        try {
          const c = await window.uai.scheduledTasks.getLogTail(gname, j.id, 30);
          return { jobId: j.id, content: c };
        } catch {
          return { jobId: j.id, content: '(failed to load log)' };
        }
      }));
      setGroupLogs(results);
    } finally {
      setGroupLogsLoading(false);
    }
  }, []);

  // Auto-load consolidated logs when a group's detail is shown.
  useEffect(() => {
    if (groupDetail) loadGroupLogs(groupDetail.name, groupDetail.jobs);
    else setGroupLogs(null);
  }, [groupDetail, loadGroupLogs]);

  const handleInstall = useCallback(async () => {
    setMutating(true);
    try {
      const result = await window.uai.scheduledTasks.install();
      if (result.ok) {
        showToast('launchd agents installed', 'info');
        await loadStatus();
      } else {
        showToast(result.error || 'Install failed', 'error');
      }
    } catch (err: any) {
      showToast(err.message || 'Install failed', 'error');
    } finally {
      setMutating(false);
    }
  }, [loadStatus, showToast]);

  const handleDryRun = useCallback(async () => {
    setMutating(true);
    try {
      const result = await window.uai.scheduledTasks.dryRun();
      if (result.ok) {
        setDryRunPreview(result.preview);
      } else {
        showToast(result.error || 'Dry run failed', 'error');
      }
    } catch (err: any) {
      showToast(err.message || 'Dry run failed', 'error');
    } finally {
      setMutating(false);
    }
  }, [showToast]);

  // ---- Filtered groups ------------------------------------------------------

  const filteredGroups = useMemo(() => {
    if (filter === 'all') return groups;
    return groups.filter(g => filter === 'enabled' ? g.enabled : !g.enabled);
  }, [groups, filter]);

  // Per-group health rollup, keyed by group name (from the status snapshot), so
  // the Groups tab + Status tab can both show 🟢N 🔴M 🟡K ⏸D and flag failures.
  const rollupByGroup = useMemo(() => {
    const m = new Map<string, HealthRollup>();
    for (const g of status?.groups ?? []) m.set(g.name, rollupForJobs(g.jobs));
    return m;
  }, [status]);

  // Status jobs for the SELECTED group, keyed by job id — powers the drill-down
  // health dot on the Groups-tab detail rows so a red group always shows WHICH
  // job is red inline (never a red rollup with no visible red job).
  const selectedGroupStatusJobs = useMemo(() => {
    const m = new Map<string, ScheduledStatusJob>();
    const sg = status?.groups.find(g => g.name === selectedGroup);
    for (const j of sg?.jobs ?? []) m.set(j.id, j);
    return m;
  }, [status, selectedGroup]);

  // Viewport reporter — exposes the Scheduled Tasks pane's live state (active tab,
  // selected group, enabled/disabled group counts) plus the scheduled jobs summarized
  // as inline children (top 20, name/schedule/enabled) so describeViewport()/Capture
  // Content reflects what this pane actually shows. Jobs are sourced from the launchd
  // status snapshot (loaded on mount) which carries schedule + enabled per job.
  const statusJobs = useMemo(
    () => (status?.groups ?? []).flatMap(g => g.jobs.map(j => ({ group: g.name, job: j }))),
    [status]
  );
  useViewport('scheduled_tasks', () => ({
    visible: true,
    label: 'Scheduled Tasks',
    state: {
      view: activeTab,
      filter,
      inSync,
      selectedGroup,
      groupsTotal: groups.length,
      groupsEnabled: groups.filter(g => g.enabled).length,
      groupsDisabled: groups.filter(g => !g.enabled).length,
      jobsTotal: statusJobs.length,
      jobsEnabled: statusJobs.filter(x => x.job.enabled).length,
      jobsDisabled: statusJobs.filter(x => !x.job.enabled).length,
    },
    children: statusJobs.slice(0, 20).map(({ group, job }) => ({
      id: `${group}/${job.id}`,
      label: job.id,
      visible: true,
      state: {
        group,
        schedule: job.schedule,
        scheduleHuman: scheduleToEnglish(job.schedule),
        enabled: job.enabled,
        installed: job.installed,
        state: job.state,
      },
      children: [],
    })),
  }));

  // ---- Render ---------------------------------------------------------------

  return (
    <div className="sched-mgr">
      {/* Header — Refresh sits LEFT (bright/primary) so it's easy to find. */}
      <div className="sched-mgr-header">
        <div className="mgr-title-group">
          <TabNavArrows />
          <span className="sched-mgr-title">Scheduled Tasks</span>
          <button
            className="sched-mgr-btn sched-mgr-btn-primary sched-mgr-refresh-btn"
            onClick={() => { loadGroups(); loadStatus(); }}
            disabled={loading}
            title="Reload groups + launchd status"
          >{'↻'} Refresh</button>
        </div>
      </div>

      {/* Tabs — the launchd sync badge sits next to Status (its home tab). */}
      <div className="sched-mgr-tabs">
        <button className={`sched-mgr-tab${activeTab === 'groups' ? ' active' : ''}`} onClick={() => setActiveTab('groups')}>Groups</button>
        <button className={`sched-mgr-tab${activeTab === 'status' ? ' active' : ''}`} onClick={() => setActiveTab('status')}>Status</button>
        {inSync === true && <span className="sched-mgr-sync-badge sched-mgr-sync-ok sched-mgr-sync-attab">In Sync</span>}
        {inSync === false && <span className="sched-mgr-sync-badge sched-mgr-sync-drift sched-mgr-sync-attab">Drift</span>}
        {inSync === null && <span className="sched-mgr-sync-badge sched-mgr-sync-loading sched-mgr-sync-attab">...</span>}
      </div>

      {/* Error banner */}
      {error && <div className="sched-mgr-error">{error}</div>}

      {/* Tab content */}
      {activeTab === 'groups' && (
        <div className="sched-mgr-split">
          {/* Left: Group list */}
          <div className="sched-mgr-list">
            <div className="sched-mgr-list-header">
              <span className="sched-mgr-list-label">Groups ({filteredGroups.length})</span>
              <button className="sched-mgr-btn sched-mgr-btn-sm" onClick={() => { setShowCreateGroup(true); setSelectedGroup(null); }} disabled={mutating}>+ New Group</button>
            </div>
            <div className="sched-mgr-filter-pills">
              <button className={`sched-mgr-pill${filter === 'all' ? ' active' : ''}`} onClick={() => setFilter('all')}>All</button>
              <button className={`sched-mgr-pill${filter === 'enabled' ? ' active' : ''}`} onClick={() => setFilter('enabled')}>Enabled</button>
              <button className={`sched-mgr-pill${filter === 'disabled' ? ' active' : ''}`} onClick={() => setFilter('disabled')}>Disabled</button>
            </div>
            {loading && <div className="sched-mgr-loading">Loading groups...</div>}
            {!loading && filteredGroups.length === 0 && (
              <div className="sched-mgr-empty">No task groups found.</div>
            )}
            <div className="sched-mgr-group-list">
              {filteredGroups.map(g => {
                const rollup = rollupByGroup.get(g.name);
                // Folder colour: RED if any failed, else AMBER if any pending, else default.
                const hasFailed = (rollup?.failed ?? 0) > 0;
                const hasPending = !hasFailed && (rollup?.pending ?? 0) > 0;
                return (
                <div
                  key={g.name}
                  className={`sched-mgr-group-row${selectedGroup === g.name ? ' selected' : ''}${hasFailed ? ' has-failure' : hasPending ? ' has-pending' : ''}`}
                  onClick={() => setSelectedGroup(g.name)}
                >
                  <span className={`sched-mgr-enabled-dot${g.enabled ? ' enabled' : ' disabled'}`} title={g.enabled ? 'Enabled' : 'Disabled'} />
                  <span className="sched-mgr-group-name">{g.name}</span>
                  <span className="sched-mgr-job-count" title={`${g.jobCount} job${g.jobCount !== 1 ? 's' : ''}`}>{g.jobCount}</span>
                  {rollup && <GroupRollupBadge rollup={rollup} />}
                  {g.description && <span className="sched-mgr-group-desc">{g.description}</span>}
                  <button
                    className={`sched-mgr-toggle-btn${g.enabled ? ' on' : ' off'}`}
                    onClick={(e) => { e.stopPropagation(); handleToggleGroup(g.name, g.enabled); }}
                    disabled={mutating}
                    title={g.enabled ? 'Disable' : 'Enable'}
                  >
                    {g.enabled ? 'ON' : 'OFF'}
                  </button>
                </div>
                );
              })}
            </div>
          </div>

          {/* Right: Detail / Create Group / Log Viewer */}
          <div className="sched-mgr-detail">
            {showCreateGroup && (
              <div className="sched-mgr-form">
                <h3 className="sched-mgr-form-title">New Group</h3>
                <div className="sched-mgr-form-row">
                  <label className="sched-mgr-form-label">Group Name</label>
                  <input className="sched-mgr-input" value={newGroup.name} onChange={e => setNewGroup({ ...newGroup, name: e.target.value })} placeholder="my_tasks" />
                </div>
                <div className="sched-mgr-form-row">
                  <label className="sched-mgr-form-label">Description</label>
                  <input className="sched-mgr-input" value={newGroup.description} onChange={e => setNewGroup({ ...newGroup, description: e.target.value })} placeholder="Optional" />
                </div>
                <h4 className="sched-mgr-form-subtitle">First Job</h4>
                <div className="sched-mgr-form-row">
                  <label className="sched-mgr-form-label">Job ID</label>
                  <input className="sched-mgr-input" value={newGroup.jobId} onChange={e => setNewGroup({ ...newGroup, jobId: e.target.value })} placeholder="main_job" />
                </div>
                <div className="sched-mgr-form-row">
                  <label className="sched-mgr-form-label">Schedule</label>
                  <input className="sched-mgr-input" value={newGroup.schedule} onChange={e => setNewGroup({ ...newGroup, schedule: e.target.value })} placeholder="*/5 * * * *" />
                  {newGroup.schedule && <span className="sched-mgr-cron-preview">{scheduleToEnglish(newGroup.schedule)}</span>}
                </div>
                <div className="sched-mgr-form-row">
                  <label className="sched-mgr-form-label">Command</label>
                  <input className="sched-mgr-input" value={newGroup.command} onChange={e => setNewGroup({ ...newGroup, command: e.target.value })} placeholder="/usr/bin/my-script.sh" />
                </div>
                <div className="sched-mgr-form-row">
                  <label className="sched-mgr-form-label">Description</label>
                  <input className="sched-mgr-input" value={newGroup.jobDescription} onChange={e => setNewGroup({ ...newGroup, jobDescription: e.target.value })} placeholder="Optional" />
                </div>
                <div className="sched-mgr-form-row">
                  <label className="sched-mgr-form-label">Log Path</label>
                  <input className="sched-mgr-input" value={newGroup.log} onChange={e => setNewGroup({ ...newGroup, log: e.target.value })} placeholder="Optional" />
                </div>
                <div className="sched-mgr-form-actions">
                  <button className="sched-mgr-btn" onClick={() => setShowCreateGroup(false)}>Cancel</button>
                  <button className="sched-mgr-btn sched-mgr-btn-primary" onClick={handleCreateGroup} disabled={mutating}>Create</button>
                </div>
              </div>
            )}

            {logViewJob && (
              <div className="sched-mgr-log-viewer">
                <div className="sched-mgr-log-header">
                  <span className="sched-mgr-log-title">Log: {logViewJob.group} / {logViewJob.jobId}</span>
                  <div>
                    <button className="sched-mgr-btn sched-mgr-btn-sm" onClick={() => handleViewLog(logViewJob.group, logViewJob.jobId)}>Refresh</button>
                    <button className="sched-mgr-btn sched-mgr-btn-sm" onClick={() => setLogViewJob(null)}>Back</button>
                  </div>
                </div>
                {logLoading && <div className="sched-mgr-loading">Loading log...</div>}
                {!logLoading && <LogView text={logContent} />}
              </div>
            )}

            {!showCreateGroup && !logViewJob && groupDetail && (
              <div className="sched-mgr-group-detail">
                {/* Group metadata */}
                <div className="sched-mgr-detail-meta">
                  <h3 className="sched-mgr-detail-name">{groupDetail.name}</h3>
                  {groupDetail.description && <p className="sched-mgr-detail-desc">{groupDetail.description}</p>}
                  <div className="sched-mgr-detail-row">
                    <span className="sched-mgr-detail-label">Enabled</span>
                    <button
                      className={`sched-mgr-toggle-btn${groupDetail.enabled ? ' on' : ' off'}`}
                      onClick={() => handleToggleGroup(groupDetail.name, groupDetail.enabled)}
                      disabled={mutating}
                    >
                      {groupDetail.enabled ? 'ON' : 'OFF'}
                    </button>
                  </div>
                  {Object.keys(groupDetail.env).length > 0 && (
                    <div className="sched-mgr-detail-env">
                      <span className="sched-mgr-detail-label">Env</span>
                      <div className="sched-mgr-env-pairs">
                        {Object.entries(groupDetail.env).map(([k, v]) => (
                          <span key={k} className="sched-mgr-env-pair"><span className="sched-mgr-env-key">{k}</span>=<span className="sched-mgr-env-val">{v}</span></span>
                        ))}
                      </div>
                    </div>
                  )}
                </div>

                {/* Job table */}
                <div className="sched-mgr-jobs-section">
                  <div className="sched-mgr-jobs-header">
                    <button className="sched-mgr-btn sched-mgr-btn-primary sched-mgr-addjob-btn" onClick={() => setShowAddJob(!showAddJob)} disabled={mutating}>
                      {showAddJob ? 'Cancel' : '+ Add Job'}
                    </button>
                    <span className="sched-mgr-jobs-label">Jobs ({groupDetail.jobs.length})</span>
                    {/* [Delete Group] relocated here — before the jobs, right-justified
                        (todo_0440 #7 / todo_0458 #4). Deliberate far-placement. */}
                    <div className="sched-mgr-jobs-header-right">
                      {confirmDelete && confirmDelete.type === 'group' && confirmDelete.group === groupDetail.name ? (
                        <span className="sched-mgr-confirm">
                          <span className="sched-mgr-confirm-q">Delete group '{groupDetail.name}' and all its jobs?</span>
                          <button className="sched-mgr-btn sched-mgr-btn-sm sched-mgr-btn-danger" onClick={() => handleDeleteGroup(groupDetail.name)} disabled={mutating}>Delete</button>
                          <button className="sched-mgr-btn sched-mgr-btn-sm" onClick={() => setConfirmDelete(null)}>Cancel</button>
                        </span>
                      ) : (
                        <button className="sched-mgr-btn sched-mgr-btn-sm sched-mgr-btn-danger" onClick={() => setConfirmDelete({ type: 'group', group: groupDetail.name })}>Delete Group</button>
                      )}
                    </div>
                  </div>

                  {/* Add job form */}
                  {showAddJob && (
                    <div className="sched-mgr-add-job-form">
                      <div className="sched-mgr-form-row-inline">
                        <input className="sched-mgr-input sched-mgr-input-sm" value={newJob.id} onChange={e => setNewJob({ ...newJob, id: e.target.value })} placeholder="Job ID" />
                        <input className="sched-mgr-input sched-mgr-input-sm" value={newJob.schedule} onChange={e => setNewJob({ ...newJob, schedule: e.target.value })} placeholder="Schedule" />
                        <input className="sched-mgr-input sched-mgr-input-sm sched-mgr-input-wide" value={newJob.command} onChange={e => setNewJob({ ...newJob, command: e.target.value })} placeholder="Command" />
                      </div>
                      <div className="sched-mgr-form-row-inline">
                        <input className="sched-mgr-input sched-mgr-input-sm" value={newJob.description} onChange={e => setNewJob({ ...newJob, description: e.target.value })} placeholder="Description" />
                        <input className="sched-mgr-input sched-mgr-input-sm" value={newJob.log} onChange={e => setNewJob({ ...newJob, log: e.target.value })} placeholder="Log path" />
                        <button className="sched-mgr-btn sched-mgr-btn-sm sched-mgr-btn-primary" onClick={handleAddJob} disabled={mutating}>Add</button>
                      </div>
                      {newJob.schedule && <span className="sched-mgr-cron-preview">{scheduleToEnglish(newJob.schedule)}</span>}
                    </div>
                  )}

                  {/* Job rows */}
                  {groupDetail.jobs.map(job => (
                    <div key={job.id} className="sched-mgr-job-row">
                      {editingJob === job.id ? (
                        /* Inline edit mode */
                        <div className="sched-mgr-job-edit">
                          <div className="sched-mgr-form-row-inline">
                            <span className="sched-mgr-job-id">{job.id}</span>
                            <input className="sched-mgr-input sched-mgr-input-sm" value={editFields.schedule ?? job.schedule} onChange={e => setEditFields({ ...editFields, schedule: e.target.value })} placeholder="Schedule" />
                            <input className="sched-mgr-input sched-mgr-input-sm sched-mgr-input-wide" value={editFields.command ?? job.command} onChange={e => setEditFields({ ...editFields, command: e.target.value })} placeholder="Command" />
                          </div>
                          <div className="sched-mgr-form-row-inline">
                            <input className="sched-mgr-input sched-mgr-input-sm" value={editFields.description ?? job.description} onChange={e => setEditFields({ ...editFields, description: e.target.value })} placeholder="Description" />
                            <input className="sched-mgr-input sched-mgr-input-sm" value={editFields.log ?? (job.log || '')} onChange={e => setEditFields({ ...editFields, log: e.target.value })} placeholder="Log path" />
                            <button className="sched-mgr-btn sched-mgr-btn-sm sched-mgr-btn-primary" onClick={() => handleSaveJobEdit(job.id)} disabled={mutating}>Save</button>
                            <button className="sched-mgr-btn sched-mgr-btn-sm" onClick={() => { setEditingJob(null); setEditFields({}); }}>Cancel</button>
                          </div>
                          {(editFields.schedule ?? job.schedule) && <span className="sched-mgr-cron-preview">{scheduleToEnglish(editFields.schedule ?? job.schedule)}</span>}
                        </div>
                      ) : (
                        /* Display mode */
                        <>
                          <div className="sched-mgr-job-summary">
                            {(() => {
                              // Drill-down: the launchd health dot + state chip for this
                              // job (from the status snapshot), so a red group visibly
                              // shows WHICH job is red right here in the detail.
                              const sj = selectedGroupStatusJobs.get(job.id);
                              if (!sj) return null;
                              const chip = jobStateChip(sj);
                              return (
                                <span className="sched-mgr-jobstat-cell">
                                  <span className={`sched-mgr-jobstat-dot ${jobStatusClass(sj)}`} title={jobStatusLabel(sj)} />
                                  <span className={`sched-mgr-state-chip ${chip.cls}`} title={`State: ${chip.label}`}>{chip.label}</span>
                                </span>
                              );
                            })()}
                            <span className="sched-mgr-job-id">{job.id}</span>
                            <span className="sched-mgr-job-schedule" title={job.schedule}>{scheduleToEnglish(job.schedule)}</span>
                            <span className="sched-mgr-job-desc">{job.description}</span>
                            {/* Discoverable reason for any non-green status — inline,
                                not just a hover tooltip (todo_0440 #4/#5). */}
                            {(() => {
                              const sj = selectedGroupStatusJobs.get(job.id);
                              if (!sj) return null;
                              const c = classifyJob(sj);
                              if (c.colour === 'green' || c.colour === 'gray') return null;
                              return <span className={`sched-mgr-job-reason sched-reason-${c.colour}`} title={c.healthLabel}>{c.healthLabel}</span>;
                            })()}
                          </div>
                          <div className="sched-mgr-job-detail">
                            <span className="sched-mgr-job-cmd" title={job.command}>{job.command}</span>
                            {job.log && <span className="sched-mgr-job-log" title={job.log}>{job.log.split('/').slice(-2).join('/')}</span>}
                            {job.background && <span className="sched-mgr-job-bg">bg</span>}
                          </div>
                          <div className="sched-mgr-job-actions">
                            <button className="sched-mgr-action-btn" onClick={() => handleRunJob(groupDetail.name, job.id)} disabled={runningJobId === job.id || mutating} title="Run Now">
                              {runningJobId === job.id ? 'Running...' : '\u25B6'}
                            </button>
                            <button className={`sched-mgr-action-btn${peekJob && peekJob.jobId === job.id ? ' active' : ''}`} onClick={() => handlePeekJob(job.id, job.command)} title="Peek script source">{'\u{1F441}'}</button>
                            {job.log && <button className="sched-mgr-action-btn" onClick={() => handleViewLog(groupDetail.name, job.id)} title="View Log">{'\u2261'}</button>}
                            <button className="sched-mgr-action-btn" onClick={() => { setEditingJob(job.id); setEditFields({}); }} title="Edit">{'\u270E'}</button>
                            <button className="sched-mgr-action-btn sched-mgr-action-danger" onClick={() => setConfirmDelete({ type: 'job', group: groupDetail.name, jobId: job.id })} title="Delete">{'\u2715'}</button>
                          </div>

                          {/* Script peek (Context-Mgr style) \u2014 todo_0440 #3 / todo_0458 #7 */}
                          {peekJob && peekJob.jobId === job.id && (
                            <div className="sched-mgr-peek">
                              <div className="sched-mgr-peek-header">
                                <span className="sched-mgr-peek-path" title={peekJob.path}>{peekJob.path || 'script'}</span>
                                <button className="sched-mgr-btn sched-mgr-btn-sm" onClick={() => setPeekJob(null)}>Close</button>
                              </div>
                              {peekJob.loading && <div className="sched-mgr-loading">Loading\u2026</div>}
                              {!peekJob.loading && peekJob.error && <div className="sched-mgr-peek-error">{peekJob.error}</div>}
                              {!peekJob.loading && !peekJob.error && <LogView text={peekJob.content} empty="(empty file)" />}
                            </div>
                          )}

                          {/* Delete confirmation */}
                          {confirmDelete && confirmDelete.type === 'job' && confirmDelete.jobId === job.id && (
                            <div className="sched-mgr-confirm">
                              <span>Delete job '{job.id}'?</span>
                              <button className="sched-mgr-btn sched-mgr-btn-sm sched-mgr-btn-danger" onClick={() => handleDeleteJob(confirmDelete.group, job.id)} disabled={mutating}>Delete</button>
                              <button className="sched-mgr-btn sched-mgr-btn-sm" onClick={() => setConfirmDelete(null)}>Cancel</button>
                            </div>
                          )}
                        </>
                      )}
                    </div>
                  ))}

                  {groupDetail.jobs.length === 0 && (
                    <div className="sched-mgr-empty">No jobs in this group.</div>
                  )}
                </div>

                {/* Consolidated logs — tail every logged job in the group, using
                    the available detail-view space (item 5). */}
                <div className="sched-mgr-group-logs">
                  <div className="sched-mgr-group-logs-header">
                    <span className="sched-mgr-jobs-label">Recent Logs</span>
                    <button
                      className="sched-mgr-btn sched-mgr-btn-sm"
                      onClick={() => loadGroupLogs(groupDetail.name, groupDetail.jobs)}
                      disabled={groupLogsLoading}
                    >{groupLogsLoading ? 'Loading…' : '↻ Refresh'}</button>
                  </div>
                  {groupLogsLoading && !groupLogs && <div className="sched-mgr-loading">Loading logs…</div>}
                  {groupLogs && groupLogs.length === 0 && (
                    <div className="sched-mgr-empty">No jobs in this group have a log path.</div>
                  )}
                  {groupLogs && groupLogs.map(gl => (
                    <div key={gl.jobId} className="sched-mgr-group-log-block">
                      <div className="sched-mgr-group-log-jobid">{gl.jobId}</div>
                      <LogView text={gl.content} className="sched-mgr-group-log-pre" />
                    </div>
                  ))}
                </div>

                {/* Run output */}
                {runOutput && (
                  <div className="sched-mgr-run-output">
                    <div className="sched-mgr-run-header">
                      <span className={`sched-mgr-exit-badge${runOutput.exitCode === 0 ? ' ok' : ' fail'}`}>Exit {runOutput.exitCode}</span>
                      <button className="sched-mgr-btn sched-mgr-btn-sm" onClick={() => setRunOutput(null)}>Close</button>
                    </div>
                    <LogView text={runOutput.stdout || runOutput.stderr} className="sched-mgr-run-content" empty="(no output)" />
                  </div>
                )}

              </div>
            )}

            {!showCreateGroup && !logViewJob && !groupDetail && !detailLoading && (
              <div className="sched-mgr-placeholder">Select a group to view details, or create a new one.</div>
            )}
            {detailLoading && <div className="sched-mgr-loading">Loading group details...</div>}
          </div>
        </div>
      )}

      {activeTab === 'status' && (
        <div className="sched-mgr-status-tab">
          {statusLoading && <div className="sched-mgr-loading">Checking launchd status...</div>}

          {!statusLoading && status && (
            <>
              {/* Sync / drift banner */}
              <div className={`sched-mgr-status-banner ${status.sync.inSync ? 'sched-mgr-status-ok' : 'sched-mgr-status-drift'}`}>
                {status.sync.inSync
                  ? 'In sync -- installed launchd agents match the task definitions.'
                  : `Drift detected -- ${status.sync.missing.length} missing, ${status.sync.extra.length} extra agent(s).`}
              </div>

              {/* Drift detail */}
              {!status.sync.inSync && (status.sync.missing.length > 0 || status.sync.extra.length > 0) && (
                <div className="sched-mgr-drift-section">
                  {status.sync.missing.length > 0 && (
                    <>
                      <h4>Missing agents ({status.sync.missing.length})</h4>
                      <pre className="sched-mgr-drift-lines">{status.sync.missing.join('\n')}</pre>
                    </>
                  )}
                  {status.sync.extra.length > 0 && (
                    <>
                      <h4>Extra agents ({status.sync.extra.length})</h4>
                      <pre className="sched-mgr-drift-lines">{status.sync.extra.join('\n')}</pre>
                    </>
                  )}
                </div>
              )}

              {status.errors && status.errors.length > 0 && (
                <div className="sched-mgr-error">{status.errors.join('\n')}</div>
              )}

              {/* Per-group job tables */}
              {status.groups.map(g => {
                const rollup = rollupForJobs(g.jobs);
                return (
                <div key={g.name} className={`sched-mgr-status-groups${rollup.failed > 0 ? ' has-failure' : rollup.pending > 0 ? ' has-pending' : ''}`}>
                  <h4>{g.name} ({g.jobs.length}) <GroupRollupBadge rollup={rollup} /></h4>
                  <table className="sched-mgr-status-table">
                    <thead>
                      <tr>
                        <th></th>
                        <th>Job</th>
                        <th>Schedule</th>
                        <th>Installed</th>
                        <th>Last Run</th>
                        <th>Next Fire</th>
                        <th>State</th>
                      </tr>
                    </thead>
                    <tbody>
                      {g.jobs.map(job => {
                        const stateChip = jobStateChip(job);
                        return (
                        <tr key={job.id}>
                          <td>
                            <div className="sched-mgr-jobstat-cell">
                              <span className={`sched-mgr-jobstat-dot ${jobStatusClass(job)}`} title={jobStatusLabel(job)} />
                              <span className={`sched-mgr-state-chip ${stateChip.cls}`} title={`State: ${stateChip.label}`}>{stateChip.label}</span>
                            </div>
                          </td>
                          <td>{job.id}</td>
                          <td title={job.schedule}>{scheduleToEnglish(job.schedule)}</td>
                          <td className={job.installed ? 'sched-mgr-val-on' : 'sched-mgr-val-off'}>{job.installed ? 'Yes' : 'No'}</td>
                          <td>
                            {job.lastRun ? (
                              <span className={job.lastRun.exit === 0 ? 'sched-mgr-val-on' : 'sched-mgr-val-fail'}>
                                exit {job.lastRun.exit} &middot; {fmtTime(job.lastRun.ts)}
                              </span>
                            ) : '—'}
                          </td>
                          <td>{job.state === 'persistent' ? 'running' : fmtTime(job.nextFire)}</td>
                          <td>{job.state}</td>
                        </tr>
                        );
                      })}
                    </tbody>
                  </table>
                </div>
                );
              })}

              {/* Unmanaged agents — launchd agents in our namespace with no YAML
                  task def (hand-installed / convention-named). Parity with the
                  SwiftBar "Other LaunchD Agents" section. */}
              {(status.unmanaged?.length ?? 0) > 0 && (
                <div className="sched-mgr-status-groups sched-mgr-unmanaged">
                  <h4>Other LaunchD Agents — unmanaged ({status.unmanaged!.length})</h4>
                  <div className="sched-mgr-unmanaged-hint">In our namespace (com.shawnhillis.* / com.pianoman.*) but not backed by a YAML task definition.</div>
                  {status.unmanaged!.map(a => {
                    const st = unmanagedStatus(a);
                    return (
                      <div key={a.label} className="sched-mgr-unmanaged-row">
                        <span className={`sched-mgr-jobstat-dot sched-mgr-jobstat-${st.colour}`} title={st.label} />
                        <span className="sched-mgr-unmanaged-name" title={a.label}>{a.friendly}</span>
                        <span className="sched-mgr-unmanaged-state">{st.label}</span>
                        {a.label.startsWith('com.shawnhillis.ai.') && (
                          <span className="sched-mgr-unmanaged-hint-inline" title="A convention-named AI agent with no YAML task — consider adding a task def to manage it">↳ add a YAML task to manage</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </>
          )}

          {!statusLoading && !status && (
            <div className="sched-mgr-empty">No status available.</div>
          )}

          {/* Dry run preview */}
          {dryRunPreview && (
            <div className="sched-mgr-dryrun">
              <div className="sched-mgr-dryrun-header">
                <h4>Dry Run Preview</h4>
                <button className="sched-mgr-btn sched-mgr-btn-sm" onClick={() => setDryRunPreview(null)}>Close</button>
              </div>
              <pre className="sched-mgr-dryrun-content">{dryRunPreview}</pre>
            </div>
          )}

          {/* Action buttons */}
          <div className="sched-mgr-status-actions">
            <button className="sched-mgr-btn sched-mgr-btn-primary" onClick={handleInstall} disabled={mutating}>Install</button>
            <button className="sched-mgr-btn" onClick={handleDryRun} disabled={mutating}>Dry Run</button>
            <button className="sched-mgr-btn" onClick={loadStatus} disabled={statusLoading}>Refresh</button>
          </div>
        </div>
      )}
    </div>
  );
}
