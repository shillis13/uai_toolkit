/**
 * TaskManagerPane — In-app task viewer.
 *
 * Shows tasks from the workflow task coordination system.
 * Backed by the uai:tasks:list IPC channel which calls
 * task_coord_cli.py list_tasks.
 *
 * Displays task list with status, platform, and description.
 * Simpler layout than TodoManagerPane — list view only.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import FilterPills from './FilterPills';
import { TabNavArrows } from './TabNavArrows';
import { useViewport } from '../viewport';

interface TaskItem {
  id: string;
  task_id?: string;  // legacy alias
  status: string;
  platform: string;
  file?: string;
  path?: string;
  template?: string;
  description?: string;
  created?: string;
}

interface TaskManagerPaneProps {
  tabId?: string;
  deepLinkId?: string;
}

const TASK_STATUS_COLORS: Record<string, string> = {
  staged: 'var(--accent-yellow)',
  running: 'var(--accent-blue)',
  complete: 'var(--accent-green)',
  failed: 'var(--accent-red)',
  cancelled: 'var(--text-muted)',
};

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-cyan)',
};

const TaskManagerPane = ({ tabId }: TaskManagerPaneProps): JSX.Element => {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [platformFilter, setPlatformFilter] = useState<string | null>(null);
  const [selectedTask, setSelectedTask] = useState<string | null>(null);

  // Load tasks on mount
  useEffect(() => {
    setLoading(true);
    setError(null);
    window.uai.tasks.list()
      .then((items) => {
        setTasks(items);
      })
      .catch((err) => {
        setError(err.message || 'Failed to load tasks');
        setTasks([]);
      })
      .finally(() => setLoading(false));
  }, []);

  // Refresh
  const handleRefresh = useCallback(() => {
    setLoading(true);
    setError(null);
    window.uai.tasks.list()
      .then((items) => {
        setTasks(items);
      })
      .catch((err) => {
        setError(err.message || 'Failed to load tasks');
        setTasks([]);
      })
      .finally(() => setLoading(false));
  }, []);

  // Filter tasks
  const filteredTasks = useMemo(() => {
    return tasks.filter(t => {
      if (statusFilter && t.status !== statusFilter) return false;
      if (platformFilter && t.platform !== platformFilter) return false;
      return true;
    });
  }, [tasks, statusFilter, platformFilter]);

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

  // Get canonical task ID (script returns 'id', legacy used 'task_id')
  const getTaskId = (task: TaskItem): string => task.id || task.task_id || '';

  // Format task ID for display
  const formatTaskId = (taskId: string): string => {
    if (!taskId) return '(unknown)';
    const parts = taskId.split('/');
    return parts[parts.length - 1] || taskId;
  };

  // Format platform label
  const formatPlatform = (platform: string): string => {
    return platform.replace('_cli', '').charAt(0).toUpperCase() + platform.replace('_cli', '').slice(1);
  };

  // Viewport reporter — exposes this Mgr's filters, selection, counts, and the
  // currently-visible tasks (top ~20) as inline children for describeViewport().
  useViewport('task_manager', () => ({
    visible: true,
    label: 'Task Manager',
    state: {
      statusFilter,
      platformFilter,
      total: tasks.length,
      visible: filteredTasks.length,
      selectedId: selectedTask,
    },
    children: filteredTasks.slice(0, 20).map(t => ({
      id: getTaskId(t),
      label: formatTaskId(getTaskId(t)),
      visible: true,
      state: { status: t.status, platform: t.platform, template: t.template, description: t.description },
      children: [],
    })),
  }));

  return (
    <div className="task-mgr" data-tab-id={tabId}>
      {/* Header */}
      <div className="task-mgr-header">
        <div className="mgr-title-group"><TabNavArrows /><div className="task-mgr-title">Task Manager</div></div>
        <div className="task-mgr-status-bar">
          <span>{tasks.length} tasks</span>
          <button className="todo-mgr-refresh-btn" onClick={handleRefresh} title="Refresh">
            Refresh
          </button>
        </div>
      </div>

      {/* Filter pills */}
      <FilterPills groups={[
        {
          groupKey: 'status',
          value: statusFilter,
          onChange: setStatusFilter,
          options: allStatuses,
          allLabel: 'All Status',
          colors: TASK_STATUS_COLORS,
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

      {/* Content */}
      <div className="task-mgr-content">
        {error && (
          <div className="traits-mgr-error">{error}</div>
        )}

        {loading && (
          <div className="traits-mgr-loading" style={{ padding: 16 }}>Loading tasks...</div>
        )}

        {!loading && filteredTasks.length === 0 && !error && (
          <div className="traits-mgr-empty">
            {tasks.length === 0
              ? 'No tasks found. Tasks will appear here when created via workflow tools.'
              : 'No tasks match the current filters.'}
          </div>
        )}

        <div className="task-mgr-list">
          {filteredTasks.map(task => (
            <div
              key={getTaskId(task)}
              className={`task-mgr-item ${selectedTask === getTaskId(task) ? 'selected' : ''}`}
              onClick={() => setSelectedTask(selectedTask === getTaskId(task) ? null : getTaskId(task))}
            >
              <div className="task-mgr-item-row">
                <span
                  className="task-mgr-status-badge"
                  style={{ background: TASK_STATUS_COLORS[task.status] || 'var(--text-muted)' }}
                >
                  {task.status}
                </span>
                {task.platform && (
                  <span
                    className="task-mgr-platform-badge"
                    style={{ color: PLATFORM_COLORS[task.platform] || 'var(--text-sec)' }}
                  >
                    {formatPlatform(task.platform)}
                  </span>
                )}
                <span className="task-mgr-item-id">{formatTaskId(getTaskId(task))}</span>
              </div>
              {task.template && (
                <div className="task-mgr-item-template">
                  Template: {task.template}
                </div>
              )}
              {task.description && (
                <div className="task-mgr-item-desc">{task.description}</div>
              )}
              {selectedTask === getTaskId(task) && task.created && (
                <div className="task-mgr-item-detail">
                  Created: {task.created}
                </div>
              )}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};

export default TaskManagerPane;
