/**
 * SessionStoreMgrPane — Main pane for the Session Store Manager.
 *
 * Split layout: left list (sessions grouped by status), right detail panel.
 * Top-level tabs: Sessions | Validate.
 * Integrates with session_store.py and session_mgr.py via IPC.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import type { SessionStoreRecord } from './session-store-types';
import SessionStoreDetail from './SessionStoreDetail';
import SessionStoreValidate from './SessionStoreValidate';
import { useToast } from './Toast';
import { TabNavArrows } from './TabNavArrows';
import { usePanelResize } from '../hooks/usePanelResize';
import { useViewport } from '../viewport';

type TopView = 'sessions' | 'validate';
type StatusFilter = 'all' | 'running' | 'stopped' | 'exited';
type PlatformFilter = 'all' | 'claude_cli' | 'codex_cli' | 'gemini_cli';

interface SessionStoreMgrPaneProps {
  tabId?: string;
  initialSession?: string;
  initialSubTab?: string;
}

const PLATFORM_DOTS: Record<string, string> = {
  claude_cli: 'sess-store-dot-claude',
  codex_cli: 'sess-store-dot-codex',
  gemini_cli: 'sess-store-dot-gemini',
};

function formatAge(isoDate: string | null | undefined): string {
  if (!isoDate) return '';
  try {
    const diff = Date.now() - new Date(isoDate).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins}m`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h`;
    const days = Math.floor(hours / 24);
    return `${days}d`;
  } catch {
    return '';
  }
}

function truncateId(tid: string): string {
  if (tid.length <= 24) return tid;
  return tid.slice(0, 22) + '...';
}

const PANE_KEY = 'uai:sessStorePane';
function loadPaneState(): { topView: TopView; statusFilter: StatusFilter; platformFilter: PlatformFilter; selectedId: string | null } {
  try { const raw = localStorage.getItem(PANE_KEY); if (raw) return { topView: 'sessions', statusFilter: 'all', platformFilter: 'all', selectedId: null, ...JSON.parse(raw) }; } catch { /* ignore */ }
  return { topView: 'sessions', statusFilter: 'all', platformFilter: 'all', selectedId: null };
}

export default function SessionStoreMgrPane({ tabId, initialSession, initialSubTab }: SessionStoreMgrPaneProps): JSX.Element {
  const listResize = usePanelResize('sessionStoreListWidth', { def: 320, min: 240, max: () => Math.max(600, Math.round(window.innerWidth * 0.5)) });
  const [topView, setTopView] = useState<TopView>(loadPaneState().topView);
  const [sessions, setSessions] = useState<SessionStoreRecord[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(initialSession || loadPaneState().selectedId);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>(loadPaneState().statusFilter);
  const [platformFilter, setPlatformFilter] = useState<PlatformFilter>(loadPaneState().platformFilter);
  const [searchText, setSearchText] = useState('');
  const { showToast } = useToast();

  useEffect(() => {
    try { localStorage.setItem(PANE_KEY, JSON.stringify({ topView, statusFilter, platformFilter, selectedId })); } catch { /* ignore */ }
  }, [topView, statusFilter, platformFilter, selectedId]);
  const searchTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const listRef = useRef<HTMLDivElement>(null);

  // Load sessions
  const loadSessions = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const opts: Record<string, string> = {};
      if (statusFilter !== 'all') opts.status = statusFilter;
      if (platformFilter !== 'all') opts.platform = platformFilter;
      const rows = await window.uai.sessionStore.list(opts);
      setSessions(rows);
    } catch (err: any) {
      setError(err.message || 'Failed to load sessions');
    } finally {
      setLoading(false);
    }
  }, [statusFilter, platformFilter]);

  useEffect(() => {
    loadSessions();
  }, [loadSessions]);

  // Debounced search
  const filteredSessions = useMemo(() => {
    if (!searchText.trim()) return sessions;
    const q = searchText.toLowerCase();
    return sessions.filter(s => {
      const fields = [
        s.display_name || '',
        s.tracking_id,
        s.project_dir || '',
        s.notes || '',
        typeof s.roles === 'string' ? s.roles : Array.isArray(s.roles) ? s.roles.join(' ') : '',
      ].join(' ').toLowerCase();
      return fields.includes(q);
    });
  }, [sessions, searchText]);

  // Group by status
  const grouped = useMemo(() => {
    const groups: Record<string, SessionStoreRecord[]> = {
      running: [],
      stopped: [],
      exited: [],
      archived: [],
    };
    for (const s of filteredSessions) {
      if (s.archived === true || s.archived === 1) {
        groups.archived.push(s);
      } else {
        const status = s.status === 'running' || s.status === 'active' ? 'running' : s.status === 'exited' ? 'exited' : 'stopped';
        groups[status].push(s);
      }
    }
    // Sort each group by last_activity descending
    for (const key of Object.keys(groups)) {
      groups[key].sort((a, b) => (b.last_activity || b.created_at || '').localeCompare(a.last_activity || a.created_at || ''));
    }
    return groups;
  }, [filteredSessions]);

  const selectedSession = useMemo(
    () => sessions.find(s => s.tracking_id === selectedId) || null,
    [sessions, selectedId]
  );

  // Viewport reporter — exposes the Session Store Manager's live state (selection,
  // active view/filters, counts) plus the visible session rows (top 20, summarized
  // as id/name/status) as inline children, so describeViewport()/Capture Content
  // reflects what this pane actually shows.
  useViewport('session_store_mgr', () => ({
    visible: true,
    label: 'Session Store Manager',
    state: {
      view: topView,
      statusFilter, platformFilter,
      search: searchText || null,
      total: sessions.length,
      visible: filteredSessions.length,
      running: grouped.running.length,
      stopped: grouped.stopped.length,
      exited: grouped.exited.length,
      archived: grouped.archived.length,
      selectedId,
      selectedName: selectedSession?.display_name || null,
    },
    children: filteredSessions.slice(0, 20).map((s) => {
      const status = (s.archived === true || s.archived === 1)
        ? 'archived'
        : s.status === 'running' || s.status === 'active' ? 'running'
        : s.status === 'exited' ? 'exited' : 'stopped';
      return {
        id: s.tracking_id,
        label: s.display_name || s.tracking_id.slice(0, 20),
        visible: true,
        state: { name: s.display_name || null, status, platform: s.platform },
        children: [],
      };
    }),
  }));

  const handleSearchChange = useCallback((value: string) => {
    setSearchText(value);
  }, []);

  const handleRefresh = useCallback(() => {
    loadSessions();
  }, [loadSessions]);

  const handleSessionUpdated = useCallback(() => {
    loadSessions();
  }, [loadSessions]);

  const handleDelete = useCallback(async (trackingId: string) => {
    if (!window.confirm(`Delete session ${trackingId}? This cannot be undone.`)) return;
    const result = await window.uai.sessionStore.delete(trackingId);
    if (result.ok) {
      showToast('Session deleted', 'info');
      if (selectedId === trackingId) setSelectedId(null);
      loadSessions();
    } else {
      showToast(result.error || 'Delete failed', 'error');
    }
  }, [selectedId, loadSessions, showToast]);

  // Scroll to initial session on mount
  useEffect(() => {
    if (initialSession && listRef.current) {
      const el = listRef.current.querySelector(`[data-tid="${initialSession}"]`);
      if (el) el.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  }, [initialSession, sessions]);

  function renderGroupHeader(label: string, count: number): JSX.Element {
    return (
      <div className="traits-mgr-category-header sess-store-group-header">
        <span className="traits-mgr-category-name">{label}</span>
        <span className="traits-mgr-category-count">{count}</span>
      </div>
    );
  }

  function renderSessionRow(s: SessionStoreRecord): JSX.Element {
    const isSelected = s.tracking_id === selectedId;
    const dotClass = PLATFORM_DOTS[s.platform] || '';
    const tags = s.tags || [];
    return (
      <div
        key={s.tracking_id}
        data-tid={s.tracking_id}
        className={`traits-mgr-item sess-store-item${isSelected ? ' selected' : ''}`}
        onClick={() => setSelectedId(s.tracking_id)}
      >
        <div className="sess-store-item-left">
          <span className={`sess-store-platform-dot ${dotClass}`} />
          <span className="traits-mgr-item-name">{s.display_name || s.tracking_id.slice(0, 20)}</span>
        </div>
        <div className="sess-store-item-right">
          {tags.slice(0, 2).map((t: string) => (
            <span key={t} className="sess-store-tag-pill">{t}</span>
          ))}
          <span className="traits-mgr-item-sub">{formatAge(s.last_activity || s.created_at)}</span>
        </div>
      </div>
    );
  }

  return (
    <div className="traits-mgr-content">
      {/* Header */}
      <div className="traits-mgr-header">
        <div className="mgr-title-group"><TabNavArrows /><span className="traits-mgr-title">Session Store Manager</span></div>
      </div>

      {/* Top-level tabs (+ Refresh action, moved down from the title bar to sit by Validate) */}
      <div className="traits-mgr-tabs">
        <button className={`traits-mgr-tab-btn${topView === 'sessions' ? ' active' : ''}`} onClick={() => setTopView('sessions')}>Sessions</button>
        <button className={`traits-mgr-tab-btn${topView === 'validate' ? ' active' : ''}`} onClick={() => setTopView('validate')}>Validate</button>
        <button className="traits-mgr-tab-btn" onClick={handleRefresh} title="Refresh">Refresh</button>
      </div>

      {topView === 'validate' ? (
        <SessionStoreValidate />
      ) : (
        <div className="traits-mgr-split">
          {/* Left: session list — draggable width */}
          <div className="traits-mgr-list sess-store-list" ref={listRef} style={{ width: `${listResize.width}px` }}>
            {/* Filter bar */}
            <div className="sess-store-filter-bar">
              <div className="sess-store-status-filters">
                {(['all', 'running', 'stopped'] as StatusFilter[]).map(f => (
                  <button
                    key={f}
                    className={`traits-mgr-tab-btn${statusFilter === f ? ' active' : ''}`}
                    onClick={() => setStatusFilter(f)}
                  >
                    {f === 'all' ? 'All' : f === 'running' ? 'Active' : 'Stopped'}
                  </button>
                ))}
              </div>
              <div className="sess-store-platform-filters">
                {(['all', 'claude_cli', 'codex_cli'] as PlatformFilter[]).map(f => (
                  <button
                    key={f}
                    className={`traits-mgr-tab-btn sess-store-plat-btn${platformFilter === f ? ' active' : ''}`}
                    onClick={() => setPlatformFilter(f)}
                  >
                    {f === 'all' ? 'All' : f === 'claude_cli' ? 'Claude' : 'Codex'}
                  </button>
                ))}
              </div>
              <input
                className="sess-store-search-input"
                type="text"
                placeholder="Search..."
                value={searchText}
                onChange={(e) => handleSearchChange(e.target.value)}
              />
            </div>

            {/* Loading/error/empty states */}
            {loading && <div className="traits-mgr-loading">Loading sessions...</div>}
            {error && <div className="traits-mgr-error">{error}</div>}
            {!loading && !error && filteredSessions.length === 0 && (
              <div className="traits-mgr-empty">No sessions found</div>
            )}

            {/* Grouped session list */}
            {!loading && !error && (
              <>
                {grouped.running.length > 0 && (
                  <div className="traits-mgr-category">
                    {renderGroupHeader('Active', grouped.running.length)}
                    <div className="traits-mgr-category-items">
                      {grouped.running.map(s => renderSessionRow(s))}
                    </div>
                  </div>
                )}
                {grouped.stopped.length > 0 && (
                  <div className="traits-mgr-category">
                    {renderGroupHeader('Stopped', grouped.stopped.length)}
                    <div className="traits-mgr-category-items">
                      {grouped.stopped.map(s => renderSessionRow(s))}
                    </div>
                  </div>
                )}
                {grouped.exited.length > 0 && (
                  <div className="traits-mgr-category">
                    {renderGroupHeader('Exited', grouped.exited.length)}
                    <div className="traits-mgr-category-items">
                      {grouped.exited.map(s => renderSessionRow(s))}
                    </div>
                  </div>
                )}
                {grouped.archived.length > 0 && (
                  <div className="traits-mgr-category">
                    {renderGroupHeader('Archived', grouped.archived.length)}
                    <div className="traits-mgr-category-items">
                      {grouped.archived.map(s => renderSessionRow(s))}
                    </div>
                  </div>
                )}
              </>
            )}
          </div>

          <div className="panel-resize-x" onMouseDown={listResize.onMouseDown} title="Drag to resize" />

          {/* Right: detail panel */}
          <div className="traits-mgr-detail">
            {selectedSession ? (
              <SessionStoreDetail
                session={selectedSession}
                initialSubTab={initialSubTab}
                onUpdated={handleSessionUpdated}
                onDelete={handleDelete}
              />
            ) : (
              <div className="traits-mgr-empty">Select a session to inspect</div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
