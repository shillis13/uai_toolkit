/**
 * TodoManagerPane — In-app todo browser.
 *
 * Reads todo items from the filesystem-based todo system at
 * ai_general/todos/. Each todo is a directory with:
 *   - notes.md (content)
 *   - *.status (exactly one, e.g. In_Progress.status)
 *   - *.tag (zero or more, e.g. automation.tag)
 *   - *.flag (zero or more, e.g. high_priority.flag)
 *
 * Backed by the uai:todos:list and uai:todos:read IPC channels.
 * Split view: list on left, notes.md content viewer on right
 * (same pattern as ContextManagerPane).
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { TabNavArrows } from './TabNavArrows';
import { useViewport } from '../viewport';

interface TodoItem {
  name: string;
  dirName: string;
  status: string;
  tags: string[];
  flags: string[];
}

interface TodoManagerPaneProps {
  tabId?: string;
  deepLinkId?: string;
}

const STATUS_ORDER: Record<string, number> = {
  'In_Progress': 0,
  'Blocked': 1,
  'Reviewing': 2,
  'Accepting': 3,
  'Ready': 4,
  'Needs_Derivation': 5,
  'Needs_Research': 6,
  'Triaging': 7,
  'Done': 8,
  'Cancelled': 9,
};

const STATUS_COLORS: Record<string, string> = {
  'In_Progress': 'var(--accent-blue)',
  'Blocked': 'var(--accent-red)',
  'Reviewing': 'var(--accent-purple)',
  'Accepting': 'var(--accent-cyan)',
  'Ready': 'var(--accent-green)',
  'Needs_Derivation': 'var(--accent-yellow)',
  'Needs_Research': 'var(--accent-orange)',
  'Triaging': 'var(--text-muted)',
  'Done': 'var(--accent-green)',
  'Cancelled': 'var(--text-muted)',
};

const TodoManagerPane = ({ tabId }: TodoManagerPaneProps): JSX.Element => {
  const [todos, setTodos] = useState<TodoItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selectedTodo, setSelectedTodo] = useState<string | null>(null);
  const [viewerContent, setViewerContent] = useState<string | null>(null);
  const [viewerLoading, setViewerLoading] = useState(false);
  const [copyFeedback, setCopyFeedback] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string | null>(null);
  const [collapsedStatuses, setCollapsedStatuses] = useState<Set<string>>(new Set());

  // Load todos on mount
  useEffect(() => {
    setLoading(true);
    setError(null);
    window.uai.todos.list()
      .then((items) => {
        setTodos(items);
      })
      .catch((err) => {
        setError(err.message || 'Failed to load todos');
        setTodos([]);
      })
      .finally(() => setLoading(false));
  }, []);

  // Refresh
  const handleRefresh = useCallback(() => {
    setLoading(true);
    setError(null);
    window.uai.todos.list()
      .then((items) => {
        setTodos(items);
      })
      .catch((err) => {
        setError(err.message || 'Failed to load todos');
        setTodos([]);
      })
      .finally(() => setLoading(false));
  }, []);

  // Load notes.md content for selected todo
  const handleSelectTodo = useCallback((dirName: string) => {
    setSelectedTodo(dirName);
    setViewerContent(null);
    setViewerLoading(true);
    window.uai.todos.read(dirName)
      .then((content) => {
        setViewerContent(content);
      })
      .catch(() => {
        setViewerContent(null);
      })
      .finally(() => setViewerLoading(false));
  }, []);

  // Copy viewer content
  const handleCopyContent = useCallback(() => {
    if (!viewerContent) return;
    navigator.clipboard.writeText(viewerContent).then(() => {
      setCopyFeedback(true);
      setTimeout(() => setCopyFeedback(false), 1500);
    }).catch(() => {});
  }, [viewerContent]);

  // Toggle status collapse
  const toggleStatus = useCallback((status: string) => {
    setCollapsedStatuses(prev => {
      const next = new Set(prev);
      if (next.has(status)) next.delete(status);
      else next.add(status);
      return next;
    });
  }, []);

  // Filter todos
  const filteredTodos = useMemo(() => {
    if (!statusFilter) return todos;
    return todos.filter(t => t.status === statusFilter);
  }, [todos, statusFilter]);

  // Group by status
  const todosByStatus = useMemo(() => {
    const groups: Record<string, TodoItem[]> = {};
    for (const todo of filteredTodos) {
      if (!groups[todo.status]) groups[todo.status] = [];
      groups[todo.status].push(todo);
    }
    return groups;
  }, [filteredTodos]);

  // Sort statuses by priority order
  const sortedStatuses = useMemo(() => {
    return Object.keys(todosByStatus).sort((a, b) => {
      const orderA = STATUS_ORDER[a] ?? 99;
      const orderB = STATUS_ORDER[b] ?? 99;
      return orderA - orderB;
    });
  }, [todosByStatus]);

  // Unique statuses for filter pills
  const allStatuses = useMemo(() => {
    const statuses = new Set<string>();
    for (const todo of todos) statuses.add(todo.status);
    return Array.from(statuses).sort((a, b) => {
      const orderA = STATUS_ORDER[a] ?? 99;
      const orderB = STATUS_ORDER[b] ?? 99;
      return orderA - orderB;
    });
  }, [todos]);

  // Format the name nicely
  const formatName = (dirName: string): string => {
    return dirName
      .replace(/^todo_/, '')
      .replace(/^task_/, '')
      .replace(/^\d+_/, '')
      .replace(/_/g, ' ');
  };

  // Viewport reporter — exposes this Mgr's filters, selection, counts, and the
  // currently-visible todos (top ~20) as inline children for describeViewport().
  useViewport('todo_manager', () => ({
    visible: true,
    label: 'Todo Manager',
    state: {
      statusFilter,
      collapsed: Array.from(collapsedStatuses),
      total: todos.length,
      visible: filteredTodos.length,
      selectedId: selectedTodo,
    },
    children: filteredTodos.slice(0, 20).map(t => ({
      id: t.dirName,
      label: t.name || formatName(t.dirName),
      visible: true,
      state: { status: t.status, tags: t.tags, flags: t.flags },
      children: [],
    })),
  }));

  return (
    <div className="todo-mgr" data-tab-id={tabId}>
      {/* Header */}
      <div className="todo-mgr-header">
        <div className="mgr-title-group"><TabNavArrows /><div className="todo-mgr-title">Todo Manager</div></div>
        <div className="todo-mgr-status-bar">
          <span>{todos.length} todos</span>
          <button className="todo-mgr-refresh-btn" onClick={handleRefresh} title="Refresh">
            Refresh
          </button>
        </div>
      </div>

      {/* Status filter pills */}
      <div className="todo-mgr-filters">
        <button
          className={`todo-mgr-filter-pill ${statusFilter === null ? 'active' : ''}`}
          onClick={() => setStatusFilter(null)}
        >
          All
        </button>
        {allStatuses.map(status => (
          <button
            key={status}
            className={`todo-mgr-filter-pill ${statusFilter === status ? 'active' : ''}`}
            style={{ borderColor: STATUS_COLORS[status] || 'var(--border)' }}
            onClick={() => setStatusFilter(statusFilter === status ? null : status)}
          >
            {status.replace(/_/g, ' ')}
          </button>
        ))}
      </div>

      {/* Content area — split layout */}
      <div className="todo-mgr-content">
        {error && (
          <div className="traits-mgr-error">{error}</div>
        )}

        <div className="context-mgr-split">
          {/* Left: todo list grouped by status */}
          <div className="context-mgr-list">
            {loading && (
              <div className="traits-mgr-loading" style={{ padding: 16 }}>Loading...</div>
            )}

            {sortedStatuses.map(status => (
              <div key={status} className="todo-mgr-status-group">
                <div
                  className="todo-mgr-status-header"
                  onClick={() => toggleStatus(status)}
                >
                  <span className="traits-mgr-collapse-icon">
                    {collapsedStatuses.has(status) ? '\u25B6' : '\u25BC'}
                  </span>
                  <span
                    className="todo-mgr-status-dot"
                    style={{ background: STATUS_COLORS[status] || 'var(--text-muted)' }}
                  />
                  <span className="todo-mgr-status-name">{status.replace(/_/g, ' ')}</span>
                  <span className="traits-mgr-category-count">{todosByStatus[status].length}</span>
                </div>
                {!collapsedStatuses.has(status) && (
                  <div className="todo-mgr-status-items">
                    {todosByStatus[status].map(todo => (
                      <div
                        key={todo.dirName}
                        className={`traits-mgr-item ${selectedTodo === todo.dirName ? 'selected' : ''}`}
                        onClick={() => handleSelectTodo(todo.dirName)}
                      >
                        <span className="traits-mgr-item-name">{formatName(todo.dirName)}</span>
                        <span className="todo-mgr-item-meta">
                          {todo.flags.includes('high_priority') && (
                            <span className="todo-mgr-flag-badge" title="High Priority">!</span>
                          )}
                          {todo.tags.map(tag => (
                            <span key={tag} className="todo-mgr-tag-badge" title={tag}>
                              {tag}
                            </span>
                          ))}
                        </span>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            ))}

            {!loading && filteredTodos.length === 0 && !error && (
              <div className="traits-mgr-empty">No todos found.</div>
            )}
          </div>

          {/* Right: content viewer */}
          <div className="context-mgr-viewer">
            {selectedTodo ? (
              viewerLoading ? (
                <div className="traits-mgr-loading">Loading content...</div>
              ) : viewerContent !== null ? (
                <>
                  <div className="context-mgr-viewer-header">
                    <span className="context-mgr-viewer-path" title={selectedTodo}>
                      {selectedTodo}/notes.md
                    </span>
                    <button
                      className="context-mgr-viewer-copy"
                      onClick={handleCopyContent}
                    >
                      {copyFeedback ? 'Copied!' : 'Copy'}
                    </button>
                  </div>
                  <pre className="context-mgr-viewer-content">{viewerContent}</pre>
                </>
              ) : (
                <div className="traits-mgr-empty">No content available for this todo.</div>
              )
            ) : (
              <div className="traits-mgr-empty">Select a todo to view its notes</div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
};

export default TodoManagerPane;
