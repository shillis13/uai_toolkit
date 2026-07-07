/**
 * AssignedTasksMgr — AI-powered work assignment viewer.
 *
 * Discovers tasks assigned to sessions by analyzing user_prompts.jsonl
 * via AI, then tracks their status. Data is persistent history, not cache.
 * Designed as a standalone Mgr for potential future merge with Task Manager.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import FilterPills from './FilterPills';
import { TabNavArrows } from './TabNavArrows';
import { useViewport } from '../viewport';

interface AssignedTask {
  id: string;
  summary: string;
  details: string;
  decisions: string[];
  sourcePrompts: Array<{ ts: string; preview: string; sessionName: string }>;
  status: string;
  statusSource: 'scan' | 'user';
  sessionId: string;
  sessionName: string;
  platform: string;
  assignedDate: string;
  confidence: number;
  dismissed: boolean;
  userNotes: string;
  scanMeta: { scannedAt: string; engine: string; daysBack: number };
}

interface ScanProgress {
  phase: 'discovery' | 'analysis';
  current: number;
  total: number;
  message: string;
}

interface AssignedTasksMgrProps {
  tabId?: string;
}

const STATUS_COLORS: Record<string, string> = {
  planned: 'var(--text-muted)',
  'in-progress': 'var(--accent-blue)',
  'needs-input': 'var(--accent-yellow)',
  completed: 'var(--accent-green)',
  cancelled: 'var(--text-muted)',
  deferred: 'var(--accent-purple)',
  unknown: 'var(--text-muted)',
};

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-cyan)',
};

const ENGINE_OPTIONS = [
  { value: 'lllm', label: 'LLLM' },
  { value: 'claude', label: 'Claude' },
];

const DAYS_OPTIONS = [1, 3, 5, 7, 14, 30];

const STATUS_VALUES = ['planned', 'in-progress', 'needs-input', 'completed', 'cancelled', 'deferred'];

const formatPlatform = (platform: string): string => {
  const base = platform.replace('_cli', '');
  return base.charAt(0).toUpperCase() + base.slice(1);
};

const formatTimeAgo = (isoStr: string): string => {
  const now = Date.now();
  const then = new Date(isoStr).getTime();
  const diffMs = now - then;
  if (diffMs < 0) return 'just now';
  const minutes = Math.floor(diffMs / 60000);
  if (minutes < 1) return 'just now';
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  return `${days}d ago`;
};

const formatDate = (isoStr: string): string => {
  try {
    const d = new Date(isoStr);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  } catch {
    return isoStr;
  }
};

const AssignedTasksMgr = ({ tabId }: AssignedTasksMgrProps): JSX.Element => {
  const [tasks, setTasks] = useState<AssignedTask[]>([]);
  const [loading, setLoading] = useState(true);
  const [scanning, setScanning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [progress, setProgress] = useState<ScanProgress | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [platformFilter, setPlatformFilter] = useState<string | null>(null);
  const [searchText, setSearchText] = useState('');
  const [engine, setEngine] = useState('lllm');
  const [daysBack, setDaysBack] = useState(5);
  const [expandedTaskId, setExpandedTaskId] = useState<string | null>(null);
  const [lastScanAt, setLastScanAt] = useState<string | null>(null);
  const [groupBySession, setGroupBySession] = useState(true);
  const [showDismissed, setShowDismissed] = useState(false);

  // Load stored data on mount. Checks if a scan is already running in the
  // backend (e.g. started before tab switch) and reflects that state.
  // Does NOT auto-scan on remount — only on very first open (no lastScanAt).
  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    Promise.all([
      window.uai.assignedTasks.load(),
      window.uai.assignedTasks.isScanning(),
    ])
      .then(([result, scanInProgress]: [{ tasks: AssignedTask[]; lastScanAt: string | null }, boolean]) => {
        if (cancelled) return;
        setTasks(result.tasks);
        setLastScanAt(result.lastScanAt);

        // If a scan is already running in the backend, reflect that in UI
        if (scanInProgress) {
          setScanning(true);
          return;
        }

        // Only auto-scan on very first open (never scanned before, no lastScanAt)
        if (result.tasks.length === 0 && !result.lastScanAt) {
          setScanning(true);
          setProgress(null);
          window.uai.assignedTasks.scan({ engine: 'lllm', daysBack: 5 })
            .then((scanResult: { tasks: AssignedTask[]; lastScanAt: string }) => {
              if (cancelled) return;
              setTasks(scanResult.tasks);
              setLastScanAt(scanResult.lastScanAt);
            })
            .catch((err: Error) => {
              if (cancelled) return;
              setError(err.message || 'Scan failed');
            })
            .finally(() => {
              if (!cancelled) setScanning(false);
            });
        }
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message || 'Failed to load assigned tasks');
        setTasks([]);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    // Subscribe to progress events — picks up events from scans started
    // before this mount (e.g. scan was running when user switched tabs)
    const cleanupProgress = window.uai.assignedTasks.onProgress((prog: ScanProgress) => {
      if (cancelled) return;
      setScanning(true);
      setProgress(prog);
    });

    // Subscribe to scan completion — picks up final result even if this
    // component was unmounted and remounted during the scan
    const cleanupComplete = window.uai.assignedTasks.onScanComplete?.((result: { tasks: AssignedTask[]; lastScanAt: string }) => {
      if (cancelled) return;
      setTasks(result.tasks);
      setLastScanAt(result.lastScanAt);
      setScanning(false);
      setProgress(null);
    });

    return () => {
      cancelled = true;
      if (typeof cleanupProgress === 'function') cleanupProgress();
      if (typeof cleanupComplete === 'function') cleanupComplete();
    };
  }, []);

  // Scan handler
  const handleScan = useCallback(() => {
    setScanning(true);
    setProgress(null);
    setError(null);
    window.uai.assignedTasks.scan({ engine, daysBack })
      .then((result: { tasks: AssignedTask[]; lastScanAt: string }) => {
        setTasks(result.tasks);
        setLastScanAt(result.lastScanAt);
      })
      .catch((err: Error) => {
        setError(err.message || 'Scan failed');
      })
      .finally(() => setScanning(false));
  }, [engine, daysBack]);

  // Cancel handler
  const handleCancel = useCallback(() => {
    window.uai.assignedTasks.cancelScan();
  }, []);

  // Update task handler
  const handleUpdateTask = useCallback((taskId: string, patch: Partial<AssignedTask>) => {
    window.uai.assignedTasks.updateTask(taskId, patch)
      .then((updatedTasks: AssignedTask[]) => {
        setTasks(updatedTasks);
      })
      .catch((err: Error) => {
        setError(err.message || 'Failed to update task');
      });
  }, []);

  // Filtering logic
  const filteredTasks = useMemo(() => {
    return tasks.filter(t => {
      if (statusFilter && t.status !== statusFilter) return false;
      if (platformFilter && t.platform !== platformFilter) return false;
      if (searchText && !t.summary.toLowerCase().includes(searchText.toLowerCase())) return false;
      if (!showDismissed && t.dismissed) return false;
      return true;
    });
  }, [tasks, statusFilter, platformFilter, searchText, showDismissed]);

  // Grouped view
  const grouped = useMemo(() => {
    if (!groupBySession) return null;
    const map = new Map<string, AssignedTask[]>();
    for (const t of filteredTasks) {
      const key = t.sessionId;
      if (!map.has(key)) map.set(key, []);
      map.get(key)!.push(t);
    }
    return map;
  }, [filteredTasks, groupBySession]);

  // Unique statuses and platforms for filter pills
  const allStatuses = useMemo(() => {
    const statuses = new Set<string>();
    for (const t of tasks) statuses.add(t.status);
    return Array.from(statuses).sort();
  }, [tasks]);

  const allPlatforms = useMemo(() => {
    const platforms = new Set<string>();
    for (const t of tasks) if (t.platform) platforms.add(t.platform);
    return Array.from(platforms).sort();
  }, [tasks]);

  // Viewport reporter — exposes this Mgr's filters, scan config, selection,
  // counts, and the currently-visible tasks (top ~20) as inline children.
  useViewport('assigned_tasks', () => ({
    visible: true,
    label: 'Assigned Tasks',
    state: {
      statusFilter,
      platformFilter,
      searchText,
      engine,
      daysBack,
      groupBySession,
      showDismissed,
      scanning,
      lastScanAt,
      total: tasks.length,
      visible: filteredTasks.length,
      selectedId: expandedTaskId,
    },
    children: filteredTasks.slice(0, 20).map(t => ({
      id: t.id,
      label: t.summary,
      visible: true,
      state: {
        status: t.status,
        platform: t.platform,
        session: t.sessionName || t.sessionId,
        confidence: t.confidence,
        dismissed: t.dismissed,
      },
      children: [],
    })),
  }));

  // Render a single task card
  const renderTaskCard = (task: AssignedTask) => (
    <div
      key={task.id}
      className={`at-mgr-task ${expandedTaskId === task.id ? 'expanded' : ''} ${task.dismissed ? 'dismissed' : ''}`}
      onClick={() => setExpandedTaskId(expandedTaskId === task.id ? null : task.id)}
    >
      <div className="at-mgr-task-row">
        <span
          className="at-mgr-status-badge"
          style={{ background: STATUS_COLORS[task.status] || 'var(--text-muted)' }}
        >
          {task.status}
        </span>
        {task.statusSource === 'user' && (
          <span className="at-mgr-user-override" title="Manually set">*</span>
        )}
        <span className="at-mgr-task-summary">{task.summary}</span>
        <span
          className="at-mgr-confidence"
          title={`Confidence: ${Math.round(task.confidence * 100)}%`}
          style={{ opacity: task.confidence }}
        >
          {'\u25CF'}
        </span>
        <span className="at-mgr-task-date">{formatDate(task.assignedDate)}</span>
      </div>

      {expandedTaskId === task.id && (
        <div className="at-mgr-task-detail">
          {task.details && (
            <div className="at-mgr-detail-section">
              <strong>Details:</strong> {task.details}
            </div>
          )}
          {task.decisions.length > 0 && (
            <div className="at-mgr-detail-section">
              <strong>Decisions:</strong>
              <ul>
                {task.decisions.map((d, i) => (
                  <li key={i}>{d}</li>
                ))}
              </ul>
            </div>
          )}
          {task.sourcePrompts.length > 0 && (
            <div className="at-mgr-detail-section">
              <strong>Source prompts:</strong>
              {task.sourcePrompts.map((p, i) => (
                <div key={i} className="at-mgr-source-prompt">
                  <span className="at-mgr-source-ts">{p.ts}</span>
                  <span className="at-mgr-source-text">{p.preview}</span>
                </div>
              ))}
            </div>
          )}

          {/* User actions */}
          <div className="at-mgr-task-actions">
            <select
              value={task.status}
              onChange={(e) => handleUpdateTask(task.id, { status: e.target.value })}
              onClick={(e) => e.stopPropagation()}
            >
              {STATUS_VALUES.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
            <button
              onClick={(e) => {
                e.stopPropagation();
                handleUpdateTask(task.id, { dismissed: !task.dismissed });
              }}
            >
              {task.dismissed ? 'Restore' : 'Dismiss'}
            </button>
          </div>
        </div>
      )}
    </div>
  );

  return (
    <div className="at-mgr" data-tab-id={tabId}>
      {/* Header */}
      <div className="at-mgr-header">
        <div className="mgr-title-group"><TabNavArrows /><div className="at-mgr-title">Assigned Tasks</div></div>
        <div className="at-mgr-controls">
          {/* Engine selector */}
          <select
            value={engine}
            onChange={(e) => setEngine(e.target.value)}
            className="at-mgr-select"
          >
            {ENGINE_OPTIONS.map(o => (
              <option key={o.value} value={o.value}>{o.label}</option>
            ))}
          </select>

          {/* Days back selector */}
          <select
            value={daysBack}
            onChange={(e) => setDaysBack(Number(e.target.value))}
            className="at-mgr-select"
          >
            {DAYS_OPTIONS.map(d => (
              <option key={d} value={d}>{d}d</option>
            ))}
          </select>

          {/* Scan / Cancel buttons */}
          {scanning ? (
            <button className="at-mgr-btn at-mgr-btn-cancel" onClick={handleCancel}>Cancel</button>
          ) : (
            <button className="at-mgr-btn at-mgr-btn-scan" onClick={handleScan}>Scan Now</button>
          )}

          {/* Last scan indicator */}
          {lastScanAt && (
            <span className="at-mgr-scan-age">Last scan: {formatTimeAgo(lastScanAt)}</span>
          )}
        </div>
      </div>

      {/* Progress bar (only during scan) */}
      {scanning && progress && (
        <div className="at-mgr-progress">
          <div
            className="at-mgr-progress-bar"
            style={{ width: `${(progress.current / Math.max(progress.total, 1)) * 100}%` }}
          />
          <span className="at-mgr-progress-label">
            {progress.phase === 'discovery' ? 'Scanning session' : 'Analyzing task'} {progress.current} of {progress.total}{progress.message ? ` — ${progress.message}` : ''}
          </span>
        </div>
      )}

      {/* Filter pills */}
      <FilterPills groups={[
        {
          groupKey: 'status',
          value: statusFilter,
          onChange: setStatusFilter,
          options: allStatuses,
          allLabel: 'All Status',
          colors: STATUS_COLORS,
        },
        ...(allPlatforms.length > 0 ? [{
          groupKey: 'platform',
          value: platformFilter,
          onChange: setPlatformFilter,
          options: allPlatforms,
          colors: PLATFORM_COLORS,
          formatLabel: formatPlatform,
        }] : []),
      ]} />

      {/* Search + view controls */}
      <div className="at-mgr-toolbar">
        <input
          type="text"
          placeholder="Search tasks..."
          value={searchText}
          onChange={(e) => setSearchText(e.target.value)}
          className="at-mgr-search"
        />
        <button
          className={`at-mgr-view-btn ${groupBySession ? 'active' : ''}`}
          onClick={() => setGroupBySession(v => !v)}
        >
          Group by Session
        </button>
        <label className="at-mgr-dismissed-toggle">
          <input
            type="checkbox"
            checked={showDismissed}
            onChange={(e) => setShowDismissed(e.target.checked)}
          />
          Show dismissed
        </label>
      </div>

      {/* Content */}
      <div className="at-mgr-content">
        {error && <div className="at-mgr-error">{error}</div>}
        {loading && <div className="at-mgr-loading">Loading...</div>}

        {!loading && filteredTasks.length === 0 && !error && (
          <div className="at-mgr-empty">
            {tasks.length === 0
              ? 'No assigned tasks found. Click "Scan Now" to discover tasks from session prompts.'
              : 'No tasks match the current filters.'}
          </div>
        )}

        {/* Grouped view */}
        {groupBySession && grouped ? (
          Array.from(grouped.entries()).map(([sessionId, sessionTasks]) => (
            <div key={sessionId} className="at-mgr-session-group">
              <div className="at-mgr-session-header">
                <span
                  className="at-mgr-session-name"
                  style={{ color: PLATFORM_COLORS[sessionTasks[0].platform] || 'var(--text-sec)' }}
                >
                  {sessionTasks[0].sessionName || sessionTasks[0].sessionId}
                </span>
                <span className="at-mgr-session-count">{sessionTasks.length} tasks</span>
              </div>
              {sessionTasks.map(task => renderTaskCard(task))}
            </div>
          ))
        ) : (
          filteredTasks.map(task => renderTaskCard(task))
        )}
      </div>
    </div>
  );
};

export default AssignedTasksMgr;
