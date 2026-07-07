/**
 * TabContentPane — dispatches to type-specific content based on tab.type.
 *
 * This is the workspace content router. Each tab type gets its own
 * content component. Session tabs get terminal + Memorex + PromptBox.
 * Folder tabs get a file-explorer-style browser. Group tabs get a
 * management view. Terminal tabs get raw shells. Brief tabs get docs.
 */

import { useState, useEffect, useCallback, useRef, useMemo, type MouseEvent as ReactMouseEvent } from 'react';
import { createPortal } from 'react-dom';
import { useViewport } from '../viewport';
import type { Tab } from '@uai/shared/types';
import type { Session } from '@uai/shared/types';
import { useSessionStore, useCardStore, useAppStateStore } from '../stores';
import { getSearchSnapshot, setSearchSnapshot } from '../stores/search-state-store';
import { useFeature } from '../stores/features';
import { executeCommand } from '../utils/execute-command';
import { useToast } from './Toast';
import SessionContextMenu from './SessionContextMenu';
import SessionPane from './SessionPane';
import PromptBox from './PromptBox';
import ContextPanel from './ContextPanel';
import TranscriptViewer from './TranscriptViewer';
import { CardListView } from './cards';
import ProjectDetailView from './ProjectDetailView';
import ProjectEditor from './ProjectEditor';
import SessionWorkView from './SessionWorkView';
import TeamDetailView from './TeamDetailView';
import WebAIPane from './WebAIPane';
import ContextMgrPane from './ContextMgrPane';
import TodoManagerPane from './TodoManagerPane';
import TaskManagerPane from './TaskManagerPane';
import type { AnyCard } from '@uai/shared/cards';
import { isSessionCard, isProjectCard, isTeamCard } from '@uai/shared/cards';
import StandaloneTerminal from './StandaloneTerminal';
import SessionStoreMgrPane from './SessionStoreMgrPane';
import ScheduledTasksPane from './ScheduledTasksPane';
import AssignedTasksMgr from './AssignedTasksMgr';
import McpManagerPane from './McpManagerPane';
import WorkMgrPane from './WorkMgrPane';
import LiveBoardPane from './LiveBoardPane';
import NotesManagerPane from './NotesManagerPane';
import TabManagerPane from './TabManagerPane';
import GitViewerPane from './GitViewerPane';
import UserMessagesPane from './UserMessagesPane';

// ─── Shared types for folder/group content views ──────────────────────────

type FolderViewMode = 'list' | 'grid';
type FolderSortField = 'activity' | 'name' | 'created';

/** Sort cards by the selected field */
function sortCards(cards: AnyCard[], field: FolderSortField): AnyCard[] {
  const sorted = [...cards];
  switch (field) {
    case 'activity':
      sorted.sort((a, b) => (b.last_activity || '').localeCompare(a.last_activity || ''));
      break;
    case 'name':
      sorted.sort((a, b) => a.display_name.localeCompare(b.display_name));
      break;
    case 'created':
      sorted.sort((a, b) => (b.created_at || '').localeCompare(a.created_at || ''));
      break;
  }
  // Pinned items sort to top regardless
  sorted.sort((a, b) => {
    const ap = isSessionCard(a) && a.pinned ? 1 : 0;
    const bp = isSessionCard(b) && b.pinned ? 1 : 0;
    return bp - ap;
  });
  return sorted;
}

/** Filter cards by a text query against display_name and tags */
function filterCards(cards: AnyCard[], query: string): AnyCard[] {
  if (!query.trim()) return cards;
  const q = query.toLowerCase();
  return cards.filter(c => {
    if (c.display_name.toLowerCase().includes(q)) return true;
    if (c.tags?.some(t => t.toLowerCase().includes(q))) return true;
    if (isSessionCard(c) && c.platform?.toLowerCase().includes(q)) return true;
    if (isSessionCard(c) && c.tracking_id.toLowerCase().includes(q)) return true;
    return false;
  });
}

// ─── Folder Content Toolbar ───────────────────────────────────────────────

function FolderToolbar({ viewMode, onViewModeChange, sortField, onSortChange, resultCount, totalCount, filterDrawerOpen, onToggleFilterDrawer, activeSessionFilterCount }: {
  viewMode: FolderViewMode;
  onViewModeChange: (mode: FolderViewMode) => void;
  sortField: FolderSortField;
  onSortChange: (field: FolderSortField) => void;
  filterText: string;
  onFilterChange: (text: string) => void;
  resultCount: number;
  totalCount: number;
  filterDrawerOpen?: boolean;
  onToggleFilterDrawer?: () => void;
  activeSessionFilterCount?: number;
}): JSX.Element {
  return (
    <div className="folder-toolbar">
      <div className="folder-toolbar-left">
        <div className="folder-toolbar-view-toggle">
          <button
            className={`folder-toolbar-btn${viewMode === 'list' ? ' active' : ''}`}
            onClick={() => onViewModeChange('list')}
            title="List view"
          >{'\u2630'}</button>
          <button
            className={`folder-toolbar-btn${viewMode === 'grid' ? ' active' : ''}`}
            onClick={() => onViewModeChange('grid')}
            title="Grid view"
          >{'\u2637'}</button>
        </div>
        <select
          className="folder-toolbar-sort"
          value={sortField}
          onChange={(e) => onSortChange(e.target.value as FolderSortField)}
        >
          <option value="activity">By Activity</option>
          <option value="name">By Name</option>
          <option value="created">By Created</option>
        </select>
        {resultCount !== totalCount && (
          <span className="folder-toolbar-count">{resultCount}/{totalCount}</span>
        )}
      </div>
      <div className="folder-toolbar-right">
        {onToggleFilterDrawer && (
          <button
            className={`folder-filter-toggle${(activeSessionFilterCount || 0) > 0 ? ' active' : ''}`}
            onClick={onToggleFilterDrawer}
            title={filterDrawerOpen ? 'Hide filters' : 'Show filters'}
          >
            Filters{(activeSessionFilterCount || 0) > 0 ? ` (${activeSessionFilterCount})` : ''} {filterDrawerOpen ? '\u25B2' : '\u25BC'}
          </button>
        )}
      </div>
    </div>
  );
}

// ─── Folder Filter (moved from Navigator) ──────────────────────────────

interface DateRange { from: string; to: string; }
type DateField = 'created_at' | 'last_activity';

function daysAgoDate(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

interface FolderFilter {
  entityTypes: Set<string>;  // 'session' | 'project'
  status: Set<string>;
  platform: Set<string>;
  search: string;
  dateRange: DateRange | null;
  dateField: DateField;
  tags: Set<string>;
}

const DEFAULT_FOLDER_FILTER: FolderFilter = {
  entityTypes: new Set(),
  status: new Set(),
  platform: new Set(),
  search: '',
  // No default date filter. A hardcoded 10-day window here silently hid older
  // sessions in a folder's Tab view — so a folder the Navigator listed sessions for
  // showed none in its tab, and "Clear" (which resets to this default) didn't reveal
  // them. The folder tab now shows ALL members (matching the Navigator); the user can
  // opt into a date range via the filter UI.
  dateRange: null,
  dateField: 'last_activity',
  tags: new Set(),
};

function countActiveFolderFilters(f: FolderFilter): number {
  let n = 0;
  if (f.entityTypes.size > 0) n++;
  if (f.status.size > 0) n++;
  if (f.platform.size > 0) n++;
  if (f.dateRange) n++;
  if (f.tags.size > 0) n++;
  if (f.search) n++;
  return n;
}

function parseDuration(input: string): string | null {
  const s = input.trim().toLowerCase();
  const match = s.match(/^(\d+)\s*(d|h|m|w)/);
  if (!match) return null;
  const num = parseInt(match[1], 10);
  const unit = match[2];
  const now = new Date();
  if (unit === 'd') now.setDate(now.getDate() - num);
  else if (unit === 'h') now.setHours(now.getHours() - num);
  else if (unit === 'm') now.setMinutes(now.getMinutes() - num);
  else if (unit === 'w') now.setDate(now.getDate() - num * 7);
  else return null;
  return now.toISOString();
}

function applyFolderFilter(cards: AnyCard[], filter: FolderFilter): AnyCard[] {
  return cards.filter(c => {
    // Entity type filter applies to all card types
    if (filter.entityTypes.size > 0 && !filter.entityTypes.has(c.entity_type)) return false;
    if (!isSessionCard(c)) return true;
    // Status
    if (filter.status.size > 0) {
      const status = c.process_status === 'running' ? 'running' : 'stopped';
      if (!filter.status.has(status)) return false;
    }
    // Platform
    if (filter.platform.size > 0 && !filter.platform.has(c.platform)) return false;
    // Date range — uses selected date field (created_at or last_activity)
    if (filter.dateRange && (filter.dateRange.from || filter.dateRange.to)) {
      const d = filter.dateField === 'created_at'
        ? (c.created_at || '')
        : (c.last_activity || c.created_at || '');
      if (filter.dateRange.from && d.slice(0, 10) < filter.dateRange.from) return false;
      if (filter.dateRange.to && d.slice(0, 10) > filter.dateRange.to) return false;
    }
    // Tags
    if (filter.tags.size > 0) {
      const cardTags = new Set(c.tags || []);
      let hasMatch = false;
      for (const tag of filter.tags) { if (cardTags.has(tag)) { hasMatch = true; break; } }
      if (!hasMatch) return false;
    }
    // Search
    if (filter.search) {
      const q = filter.search.toLowerCase();
      const name = (c.display_name || '').toLowerCase();
      const tid = (c.tracking_id || '').toLowerCase();
      const tags = (c.tags || []).join(' ').toLowerCase();
      if (!name.includes(q) && !tid.includes(q) && !tags.includes(q)) return false;
    }
    return true;
  });
}

// ─── Inline Filter Pills (rendered in title bar) ────────────────────────

function InlineFilterPills({ filter, onFilterChange }: {
  filter: FolderFilter;
  onFilterChange: (f: FolderFilter) => void;
}): JSX.Element {
  const toggle = (key: 'entityTypes' | 'status' | 'platform', value: string) => {
    const next = new Set(filter[key]);
    if (next.has(value)) next.delete(value); else next.add(value);
    onFilterChange({ ...filter, [key]: next });
  };
  const activeCount = countActiveFolderFilters(filter);
  return (
    <>
      {activeCount > 0 && <button className="filter-pill filter-pill-clear" onClick={() => onFilterChange(DEFAULT_FOLDER_FILTER)}>{'\u2715'}</button>}
      <button className={`filter-pill${filter.entityTypes.has('session') ? ' active' : ''}`} onClick={() => toggle('entityTypes', 'session')}>Session</button>
      <button className={`filter-pill${filter.entityTypes.has('project') ? ' active' : ''}`} onClick={() => toggle('entityTypes', 'project')}>Project</button>
      <span className="filter-drawer-sep">|</span>
      <button className={`filter-pill${filter.status.has('running') ? ' active' : ''}`} onClick={() => toggle('status', 'running')}>Active</button>
      <button className={`filter-pill${filter.status.has('stopped') ? ' active' : ''}`} onClick={() => toggle('status', 'stopped')}>Stopped</button>
      <span className="filter-drawer-sep">|</span>
      <button className={`filter-pill platform-claude${filter.platform.has('claude_cli') ? ' active' : ''}`} onClick={() => toggle('platform', 'claude_cli')}>Claude</button>
      <button className={`filter-pill platform-codex${filter.platform.has('codex_cli') ? ' active' : ''}`} onClick={() => toggle('platform', 'codex_cli')}>Codex</button>
      <button className={`filter-pill platform-gemini${filter.platform.has('gemini_cli') ? ' active' : ''}`} onClick={() => toggle('platform', 'gemini_cli')}>Gemini</button>
      <span className="filter-drawer-sep">|</span>
      <select
        className="filter-drawer-date-field"
        value={filter.dateField}
        onChange={(e) => onFilterChange({ ...filter, dateField: e.target.value as DateField })}
        title="Date field to filter by"
      >
        <option value="last_activity">Activity</option>
        <option value="created_at">Created</option>
      </select>
      <input
        className="filter-drawer-date"
        type="date"
        value={filter.dateRange?.from || ''}
        onChange={(e) => onFilterChange({ ...filter, dateRange: { from: e.target.value, to: filter.dateRange?.to || '' } })}
        title="From date"
      />
      <span className="filter-drawer-sep">{'\u2013'}</span>
      <input
        className="filter-drawer-date"
        type="date"
        value={filter.dateRange?.to || ''}
        onChange={(e) => onFilterChange({ ...filter, dateRange: { from: filter.dateRange?.from || '', to: e.target.value } })}
        title="To date (empty = today)"
      />
      <span className="filter-drawer-sep">|</span>
      <input className="filter-drawer-search" type="text" placeholder="Search..." value={filter.search} onChange={(e) => onFilterChange({ ...filter, search: e.target.value })} />
    </>
  );
}

// ─── Filter Drawer for Folder View (legacy, kept for date picker) ───────

function FolderFilterDrawer({ filter, onFilterChange, availableTags }: {
  filter: FolderFilter;
  onFilterChange: (f: FolderFilter) => void;
  availableTags: string[];
}): JSX.Element {
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const datePickerRef = useRef<HTMLDivElement>(null);
  const dateBtnRef = useRef<HTMLButtonElement>(null);

  useEffect(() => {
    if (!showDatePicker) return;
    const handler = (e: MouseEvent) => {
      if (datePickerRef.current && !datePickerRef.current.contains(e.target as Node) &&
          dateBtnRef.current && !dateBtnRef.current.contains(e.target as Node)) {
        setShowDatePicker(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showDatePicker]);

  const toggleFilter = (key: 'entityTypes' | 'status' | 'platform', value: string) => {
    const next = new Set(filter[key]);
    if (next.has(value)) next.delete(value); else next.add(value);
    onFilterChange({ ...filter, [key]: next });
  };

  const toggleTag = (tag: string) => {
    const next = new Set(filter.tags);
    if (next.has(tag)) next.delete(tag); else next.add(tag);
    onFilterChange({ ...filter, tags: next });
  };

  const clearAllFilters = () => onFilterChange(DEFAULT_FOLDER_FILTER);

  const activeFilterCount = countActiveFolderFilters(filter);

  return (
    <div className="folder-filter-drawer">
      <div className="filter-drawer-pills">
        {activeFilterCount > 0 && (
          <button className="filter-pill filter-pill-clear" onClick={clearAllFilters}>Clear ({activeFilterCount})</button>
        )}
        <button className={`filter-pill${filter.entityTypes.has('session') ? ' active' : ''}`} onClick={() => toggleFilter('entityTypes', 'session')}>Session</button>
        <button className={`filter-pill${filter.entityTypes.has('project') ? ' active' : ''}`} onClick={() => toggleFilter('entityTypes', 'project')}>Project</button>
        <span className="filter-drawer-sep">|</span>
        <button className={`filter-pill${filter.status.has('running') ? ' active' : ''}`} onClick={() => toggleFilter('status', 'running')}>Active</button>
        <button className={`filter-pill${filter.status.has('stopped') ? ' active' : ''}`} onClick={() => toggleFilter('status', 'stopped')}>Stopped</button>
        <span className="filter-drawer-sep">|</span>
        <button className={`filter-pill platform-claude${filter.platform.has('claude_cli') ? ' active' : ''}`} onClick={() => toggleFilter('platform', 'claude_cli')}>Claude</button>
        <button className={`filter-pill platform-codex${filter.platform.has('codex_cli') ? ' active' : ''}`} onClick={() => toggleFilter('platform', 'codex_cli')}>Codex</button>
        <button className={`filter-pill platform-gemini${filter.platform.has('gemini_cli') ? ' active' : ''}`} onClick={() => toggleFilter('platform', 'gemini_cli')}>Gemini</button>
        <span className="filter-drawer-sep">|</span>
        <button
          ref={dateBtnRef}
          className={`filter-pill filter-pill-date${filter.dateRange ? ' active' : ''}`}
          onClick={() => { if (!showDatePicker) { setDateFrom(filter.dateRange?.from ?? ''); setDateTo(filter.dateRange?.to ?? ''); } setShowDatePicker(prev => !prev); }}
        >{filter.dateRange ? 'Date \u2713' : 'Date'}</button>

        {showDatePicker && createPortal(
          <div ref={datePickerRef} className="nav-date-popover" style={(() => {
            const rect = dateBtnRef.current?.getBoundingClientRect();
            if (!rect) return {};
            return { position: 'fixed' as const, top: rect.bottom + 4, left: rect.left, zIndex: 9999 };
          })()}>
            <div className="nav-date-section">
              <span className="nav-date-label">Quick</span>
              <div className="nav-date-quick-picks">
                {[{ label: '1h', val: '1h' }, { label: '6h', val: '6h' }, { label: '24h', val: '24h' }, { label: '7d', val: '7d' }, { label: '30d', val: '30d' }].map(p => (
                  <button key={p.val} className="nav-date-quick-btn" onClick={() => { const from = parseDuration(p.val); if (from) { onFilterChange({ ...filter, dateRange: { from, to: '' } }); setShowDatePicker(false); } }}>{p.label}</button>
                ))}
              </div>
            </div>
            <div className="nav-date-section">
              <span className="nav-date-label">Custom Range</span>
              <div className="nav-date-inputs">
                <label className="nav-date-input-label">From<input type="date" className="nav-date-input" value={dateFrom.slice(0, 10)} onChange={(e) => setDateFrom(e.target.value)} /></label>
                <label className="nav-date-input-label">To<input type="date" className="nav-date-input" value={dateTo.slice(0, 10)} onChange={(e) => setDateTo(e.target.value)} /></label>
              </div>
            </div>
            <div className="nav-date-actions">
              <button className="nav-date-apply-btn" onClick={() => { onFilterChange({ ...filter, dateRange: (dateFrom || dateTo) ? { from: dateFrom, to: dateTo } : null }); setShowDatePicker(false); }}>Apply</button>
              <button className="nav-date-clear-btn" onClick={() => { setDateFrom(''); setDateTo(''); onFilterChange({ ...filter, dateRange: null }); setShowDatePicker(false); }}>Clear</button>
            </div>
          </div>,
          document.body
        )}
        {availableTags.length > 0 && (
          <>
            <span className="filter-drawer-sep">|</span>
            <span className="filter-drawer-label">Tags</span>
            {availableTags.map(tag => (
              <button key={tag} className={`filter-pill filter-pill-tag${filter.tags.has(tag) ? ' active' : ''}`} onClick={() => toggleTag(tag)}>{tag}</button>
            ))}
          </>
        )}
        <span className="filter-drawer-sep">|</span>
        <input className="filter-drawer-search" type="text" placeholder="Search..." value={filter.search} onChange={(e) => onFilterChange({ ...filter, search: e.target.value })} />
      </div>
    </div>
  );
}

interface TabContentPaneProps {
  tab: Tab;
  memorexEnabled?: boolean;
  transcriptOpen?: boolean;
  onCloseTranscript?: () => void;
  /** Chat|Work view — lifted to Workspace so the toggle can live in the title bar. */
  subtab?: 'chat' | 'work';
}

function SessionContent({ tab, memorexEnabled, transcriptOpen, onCloseTranscript, subtab = 'chat' }: { tab: Tab; memorexEnabled?: boolean; transcriptOpen?: boolean; onCloseTranscript?: () => void; subtab?: 'chat' | 'work' }): JSX.Element {
  const { getSession } = useSessionStore();
  const { appState, updateAppState } = useAppStateStore();
  const session = getSession(tab.targetId);
  // Work subtab is feature-gated — if it's off (or gets turned off while active),
  // fall back to Chat so the body never renders blank.
  const workEnabled = useFeature('session.workSubtab');
  const effectiveSubtab: 'chat' | 'work' = subtab === 'work' && workEnabled ? 'work' : 'chat';

  // Transcript pin — when set, the transcript stays locked to that session across
  // session-tab switches (mirrors the right-panel pin) so two transcripts can be
  // compared / copied between. Pinning targets the active tab's session.
  const transcriptPinnedSession = appState.transcriptPinnedSession || null;
  const isTranscriptPinned = !!transcriptPinnedSession;
  const pinnedTranscriptSession = isTranscriptPinned ? getSession(transcriptPinnedSession) : undefined;
  const toggleTranscriptPin = useCallback(() => {
    updateAppState({ transcriptPinnedSession: isTranscriptPinned ? null : (tab.targetId || null) });
  }, [isTranscriptPinned, tab.targetId, updateAppState]);

  // Chat | Work — a session is a worker, so its Work view is the same aspect page
  // Projects/Teams use, scoped to this session (worker_pages design). The toggle
  // lives in the SessionTitleBar; `subtab` is passed down from Workspace.

  useViewport('entity_view', () => ({
    visible: true,
    label: `session: ${session?.display_name || tab.targetId}`,
    children: ['session_pane', 'context_panel'],
  }));

  if (!session) {
    return (
      <div className="workspace-placeholder">
        <h3>Session not found</h3>
        <p>{tab.targetId}</p>
      </div>
    );
  }

  const isActive = session.process_status === 'running';

  // The Chat content — one of: no-terminal placeholder / transcript / live terminal.
  // Rendered always (display-toggled) so switching to Work never detaches the terminal.
  const chatContent = !session.terminal_session ? (
    <div className="entity-view-row">
      <div className="entity-view-content">
        <div className="workspace-placeholder">
          <h2>{session.display_name || session.tracking_id}</h2>
          <p>No terminal session available.</p>
        </div>
      </div>
      <ContextPanel activeSessionId={session.tracking_id} />
    </div>
  ) : !isActive ? (
    <div className="entity-view-row">
      <div className="entity-view-content">
        <div className="transcript-content">
          <TranscriptViewer
            open={true}
            inline={true}
            zellijSession={session.terminal_session}
            cliSessionId={session.cli_session_id || undefined}
            sessionName={session.display_name || tab.label}
            platform={session.platform}
            onClose={() => { executeCommand('workspace.tabs.close', { tabId: tab.id }); }}
          />
        </div>
      </div>
      <ContextPanel activeSessionId={session.tracking_id} />
    </div>
  ) : (
    <div className="entity-view-row">
      <div className="entity-view-content">
        <SessionPane key={session.tracking_id} session={session} memorexEnabled={memorexEnabled} />
        <PromptBox
          sessionId={session.tracking_id}
          sessionName={session.display_name || session.tracking_id}
          cliSessionId={session.cli_session_id}
        />
      </div>
      {(() => {
        const tSession = pinnedTranscriptSession || session;
        const show = (transcriptOpen || isTranscriptPinned) && !!tSession?.terminal_session;
        if (!show) return null;
        return (
          <TranscriptViewer
            key={tSession.tracking_id}
            open={true}
            inline={false}
            zellijSession={tSession.terminal_session!}
            cliSessionId={tSession.cli_session_id || undefined}
            sessionName={tSession.display_name || tSession.tracking_id}
            platform={tSession.platform}
            pinned={isTranscriptPinned}
            onTogglePin={toggleTranscriptPin}
            onClose={() => {
              if (isTranscriptPinned) updateAppState({ transcriptPinnedSession: null });
              else onCloseTranscript?.();
            }}
          />
        );
      })()}
      <ContextPanel activeSessionId={session.tracking_id} />
    </div>
  );

  return (
    <div className="session-tab">
      <div className="session-subtab-body">
        <div className="session-subtab-chat" style={{ display: effectiveSubtab === 'chat' ? 'flex' : 'none' }}>{chatContent}</div>
        {effectiveSubtab === 'work' && <div className="session-subtab-work"><SessionWorkView session={session as any} /></div>}
      </div>
    </div>
  );
}

// ─── Platform labels (matches Navigator) ────────────────────────────────

const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude',
  codex_cli: 'Codex',
  gemini_cli: 'Gemini',
};

// ─── New Session Card ────────────────────────────────────────────────────

function NewSessionCard({ onCreateSession }: { onCreateSession: (platform: string) => void }): JSX.Element {
  const [showPicker, setShowPicker] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);

  // Close picker on outside click
  useEffect(() => {
    if (!showPicker) return;
    const handler = (e: MouseEvent) => {
      if (cardRef.current && !cardRef.current.contains(e.target as Node)) {
        setShowPicker(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showPicker]);

  return (
    <div
      ref={cardRef}
      className="session-card new-session-card"
      onClick={() => setShowPicker(!showPicker)}
    >
      <div className="new-session-plus">+</div>
      <div className="new-session-label">New Session</div>
      {showPicker && (
        <div className="new-session-picker">
          <button
            className="new-session-picker-btn claude"
            onClick={(e: ReactMouseEvent) => { e.stopPropagation(); setShowPicker(false); onCreateSession('claude_cli'); }}
          >Claude</button>
          <button
            className="new-session-picker-btn codex"
            onClick={(e: ReactMouseEvent) => { e.stopPropagation(); setShowPicker(false); onCreateSession('codex_cli'); }}
          >Codex</button>
          <button
            className="new-session-picker-btn gemini"
            onClick={(e: ReactMouseEvent) => { e.stopPropagation(); setShowPicker(false); onCreateSession('gemini_cli'); }}
          >Gemini</button>
        </div>
      )}
    </div>
  );
}

// ─── New Folder Card ──────────────────────────────────────────────────────

function NewFolderCard({ parentId }: { parentId: string }): JSX.Element {
  const { showToast } = useToast();

  const handleClick = useCallback(() => {
    const name = window.prompt('New folder name:');
    if (name && name.trim()) {
      executeCommand('folder.create', { parentId, name: name.trim() }, { onFailure: 'toast', toastFn: showToast });
    }
  }, [parentId, showToast]);

  return (
    <div className="session-card new-entity-card" onClick={handleClick}>
      <div className="new-session-plus">+</div>
      <div className="new-session-label">New Folder</div>
    </div>
  );
}

// ─── Collapsible Section ──────────────────────────────────────────────────

function FolderSection({ title, count, collapsed, onToggle, children }: {
  title: string;
  count: number;
  collapsed: boolean;
  onToggle: () => void;
  children: React.ReactNode;
}): JSX.Element {
  return (
    <div className="folder-section">
      <div className="folder-section-header" onClick={onToggle}>
        <span className="folder-section-chevron">{collapsed ? '\u25B6' : '\u25BC'}</span>
        <span className="folder-section-title">{title}</span>
        <span className="folder-section-count">({count})</span>
      </div>
      {!collapsed && <div className="folder-section-body">{children}</div>}
    </div>
  );
}

function FolderContent({ tab }: { tab: Tab }): JSX.Element {
  const { getCardsInContainer, getContainer, sessions: allSessionCards } = useCardStore();
  const { getSession, aiRoot } = useSessionStore();
  const { appState } = useAppStateStore();
  const { showToast } = useToast();
  const container = getContainer(tab.targetId);
  const directCards = getCardsInContainer(tab.targetId, { descendants: false });
  const allDescendantCards = getCardsInContainer(tab.targetId, { descendants: true });

  // Open tab target IDs for tab-open indicators
  const openTabTargetIds = useMemo(
    () => new Set(appState.tabs.map(t => t.targetId)),
    [appState.tabs]
  );

  // Create a new session (mirrors Navigator's createSession pattern)
  const createSession = useCallback(async (platform: string) => {
    const label = `New ${PLATFORM_LABELS[platform] || 'AI'} Session`;
    const result = await executeCommand('session.create', {
      platform,
      displayName: label,
      roles: ['assistant'],
      projectDir: aiRoot || undefined,
    }, { onFailure: 'toast', toastFn: showToast });
    const data = result?.data as { trackingId?: string } | undefined;
    if (result?.ok && data?.trackingId) {
      executeCommand('workspace.tabs.open', {
        type: 'session',
        targetId: data.trackingId,
        label,
      });
    }
  }, [aiRoot, showToast]);

  // For "all_sessions" root folder, show all session cards if container returns empty
  const isRoot = tab.targetId === 'all_sessions';
  const cards = isRoot && directCards.length === 0 ? allSessionCards : directCards;
  const descendantOnlyCards = useMemo(() => {
    const directIds = new Set(cards.map(c => c.entity_id));
    return allDescendantCards.filter(c => !directIds.has(c.entity_id));
  }, [cards, allDescendantCards]);

  const hasSubfolders = container && container.sub_containers && container.sub_containers.length > 0;

  const [viewMode, setViewMode] = useState<FolderViewMode>('grid');
  const [sortField, setSortField] = useState<FolderSortField>('activity');
  const [filterText, setFilterText] = useState('');
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; sessionId: string } | null>(null);
  const [sessionFilter, setSessionFilter] = useState<FolderFilter>(DEFAULT_FOLDER_FILTER);
  const [filterDrawerOpen, setFilterDrawerOpen] = useState(false);
  const filterBtnRef = useRef<HTMLButtonElement>(null);
  const filterPopoverRef = useRef<HTMLDivElement>(null);
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());

  // Close the filter dropdown on outside click / Escape.
  useEffect(() => {
    if (!filterDrawerOpen) return;
    const onDown = (e: MouseEvent) => {
      const t = e.target as Node;
      if (filterBtnRef.current?.contains(t) || filterPopoverRef.current?.contains(t)) return;
      setFilterDrawerOpen(false);
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setFilterDrawerOpen(false); };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('mousedown', onDown); document.removeEventListener('keydown', onKey); };
  }, [filterDrawerOpen]);

  const toggleSection = useCallback((section: string) => {
    setCollapsedSections(prev => {
      const next = new Set(prev);
      if (next.has(section)) next.delete(section); else next.add(section);
      return next;
    });
  }, []);

  // Collect available tags from all cards (direct + descendants)
  const availableTags = useMemo(() => {
    const tagSet = new Set<string>();
    for (const c of allDescendantCards) { if (isSessionCard(c)) { for (const t of c.tags || []) tagSet.add(t); } }
    for (const c of cards) { if (isSessionCard(c)) { for (const t of c.tags || []) tagSet.add(t); } }
    return Array.from(tagSet).sort();
  }, [cards, allDescendantCards]);

  // Apply filters to direct contents
  const sessionFiltered = useMemo(() => applyFolderFilter(cards, sessionFilter), [cards, sessionFilter]);
  const filtered = useMemo(() => filterCards(sessionFiltered, filterText), [sessionFiltered, filterText]);
  const sorted = useMemo(() => sortCards(filtered, sortField), [filtered, sortField]);

  // Apply filters to descendant-only contents
  const descFiltered = useMemo(() => applyFolderFilter(descendantOnlyCards, sessionFilter), [descendantOnlyCards, sessionFilter]);
  const descTextFiltered = useMemo(() => filterCards(descFiltered, filterText), [descFiltered, filterText]);
  const descSorted = useMemo(() => sortCards(descTextFiltered, sortField), [descTextFiltered, sortField]);

  const activeSessionFilterCount = countActiveFolderFilters(sessionFilter);

  const handleCardClick = useCallback((card: AnyCard) => {
    if (isSessionCard(card)) {
      const label = card.display_name || card.tracking_id;
      executeCommand('workspace.tabs.open', {
        type: 'session',
        targetId: card.tracking_id,
        label,
      });
    } else if (isProjectCard(card)) {
      executeCommand('workspace.tabs.open', {
        type: 'project',
        targetId: card.project_id || card.entity_id,
        label: card.display_name,
      });
    }
  }, []);

  const handleCardContextMenu = useCallback((card: AnyCard, e: React.MouseEvent) => {
    e.preventDefault();
    if (isSessionCard(card)) {
      const menuWidth = 200;
      const menuHeight = 300;
      const x = Math.min(e.clientX, window.innerWidth - menuWidth);
      const y = Math.min(e.clientY, window.innerHeight - menuHeight);
      setContextMenu({ x, y, sessionId: card.tracking_id });
    }
  }, []);

  const ctxSession = contextMenu ? getSession(contextMenu.sessionId) : null;

  if (!container && !isRoot) {
    return (
      <div className="workspace-placeholder">
        <h3>Folder not found</h3>
        <p>{tab.targetId}</p>
      </div>
    );
  }

  // Subfolder list
  const subfolders = container?.sub_containers || [];

  // Portal toolbar into Workspace folder title bar
  const portalTarget = document.getElementById('folder-toolbar-portal');

  return (
    <div className="folder-content">
      {/* Toolbar portaled into Workspace title bar */}
      {portalTarget && createPortal(
        <div className="stb-folder-controls">
          <div className="folder-toolbar-view-toggle">
            <button className={`folder-toolbar-btn${viewMode === 'list' ? ' active' : ''}`} onClick={() => setViewMode('list')} title="List view">{'\u2630'}</button>
            <button className={`folder-toolbar-btn${viewMode === 'grid' ? ' active' : ''}`} onClick={() => setViewMode('grid')} title="Grid view">{'\u2637'}</button>
          </div>
          <select className="folder-toolbar-sort" value={sortField} onChange={(e) => setSortField(e.target.value as FolderSortField)}>
            <option value="activity">Activity</option>
            <option value="name">Name</option>
            <option value="created">Created</option>
          </select>
          <div className="filter-drawer-anchor">
            <button
              ref={filterBtnRef}
              className={`folder-filter-toggle${activeSessionFilterCount > 0 ? ' active' : ''}`}
              onClick={() => setFilterDrawerOpen(v => !v)}
            >
              Filters{activeSessionFilterCount > 0 ? ` (${activeSessionFilterCount})` : ''} {filterDrawerOpen ? '\u25B2' : '\u25BC'}
            </button>
          </div>
        </div>,
        portalTarget
      )}
      {/* Filter dropdown — portaled to body so it isn't clipped by the title-bar
          row and can wrap to show all controls regardless of pane width. */}
      {filterDrawerOpen && (() => {
        const r = filterBtnRef.current?.getBoundingClientRect();
        const top = r ? r.bottom + 4 : 80;
        // Right-align to the button, but keep a margin from the window edge.
        const right = r ? Math.max(8, window.innerWidth - r.right) : 8;
        return createPortal(
          <div
            ref={filterPopoverRef}
            className="filter-drawer-popover"
            style={{ position: 'fixed', top, right, zIndex: 10000 }}
          >
            <InlineFilterPills filter={sessionFilter} onFilterChange={setSessionFilter} />
          </div>,
          document.body,
        );
      })()}
      <div className={viewMode === 'grid' ? 'folder-content-grid folder-content-sections' : 'folder-content-list folder-content-sections'}>
        {/* Subfolders section */}
        {subfolders.length > 0 && (
          <FolderSection
            title="Subfolders"
            count={subfolders.length}
            collapsed={collapsedSections.has('subfolders')}
            onToggle={() => toggleSection('subfolders')}
          >
            <div className={viewMode === 'grid' ? 'folder-section-grid' : 'folder-section-list'}>
              <NewFolderCard parentId={tab.targetId} />
              {subfolders.map(subId => {
                const sub = getContainer(subId);
                if (!sub) return null;
                const subCards = getCardsInContainer(subId);
                return (
                  <div
                    key={subId}
                    className="session-card subfolder-card"
                    onClick={() => executeCommand('workspace.tabs.open', { type: 'folder', targetId: subId, label: sub.name })}
                    title={`${sub.name} \u2014 ${subCards.length} items`}
                  >
                    <div className="card-content">
                      <div className="card-header">
                        <span className="subfolder-icon">{'\uD83D\uDCC1'}</span>
                        <span className="card-name">{sub.name}</span>
                        <span className="subfolder-count">{subCards.length}</span>
                      </div>
                    </div>
                  </div>
                );
              })}
            </div>
          </FolderSection>
        )}

        {/* Direct Contents section */}
        <FolderSection
          title="Direct Contents"
          count={sorted.length}
          collapsed={collapsedSections.has('direct')}
          onToggle={() => toggleSection('direct')}
        >
          <div className={viewMode === 'grid' ? 'folder-section-grid' : 'folder-section-list'}>
            {viewMode === 'grid' && !filterText && (
              <NewSessionCard onCreateSession={createSession} />
            )}
            <CardListView
              cards={sorted}
              viewMode={viewMode}
              openTabTargetIds={openTabTargetIds}
              onCardClick={handleCardClick}
              onCardContextMenu={handleCardContextMenu}
              emptyMessage={activeSessionFilterCount > 0 ? 'No items match the active filters.' : 'This folder is empty.'}
            />
          </div>
        </FolderSection>

        {/* Including Subfolders section — only when subfolders exist and there are descendant cards */}
        {hasSubfolders && descSorted.length > 0 && (
          <FolderSection
            title="Including Subfolders"
            count={descSorted.length}
            collapsed={collapsedSections.has('descendants')}
            onToggle={() => toggleSection('descendants')}
          >
            <CardListView
              cards={descSorted}
              viewMode={viewMode}
              openTabTargetIds={openTabTargetIds}
              onCardClick={handleCardClick}
              onCardContextMenu={handleCardContextMenu}
              emptyMessage="No items in subfolders."
            />
          </FolderSection>
        )}
      </div>
      {contextMenu && ctxSession && (
        <SessionContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          session={ctxSession}
          onClose={() => setContextMenu(null)}
        />
      )}
    </div>
  );
}

function TerminalContent({ tab }: { tab: Tab }): JSX.Element {
  return <StandaloneTerminal tabId={tab.id} />;
}

function BriefContent({ tab }: { tab: Tab }): JSX.Element {
  const cardStore = useCardStore();
  const brief = cardStore.briefs.find(b => b.name === tab.targetId || b.entity_id === `brief:${tab.targetId}`);

  if (!brief) {
    return (
      <div className="workspace-placeholder">
        <h3>Brief not found</h3>
        <p>{tab.targetId}</p>
      </div>
    );
  }

  return (
    <div className="brief-content" style={{ padding: 'var(--sp-md)', overflow: 'auto' }}>
      <div className="detail-view-header">
        <h3 className="detail-view-title">{brief.display_name}</h3>
        {brief.description && <p className="detail-view-subtitle">{brief.description}</p>}
      </div>
      <div className="detail-view-section">
        <div className="ctx-detail-row">
          <span className="ctx-detail-label">Status</span>
          <span className="ctx-detail-value" style={{ color: brief.status === 'active' ? 'var(--accent-green)' : 'var(--text-muted)' }}>
            {brief.status}
          </span>
        </div>
        {brief.condenser_session && (
          <div className="ctx-detail-row">
            <span className="ctx-detail-label">Condenser</span>
            <span className="ctx-detail-value copyable" onClick={() => window.uai.clipboard.write(brief.condenser_session!)}>
              {brief.condenser_session}
            </span>
          </div>
        )}
        <div className="ctx-detail-row">
          <span className="ctx-detail-label">Path</span>
          <span className="ctx-detail-value copyable" onClick={() => window.uai.clipboard.write(brief.brief_path)}>
            {brief.brief_path.split('/').slice(-2).join('/')}
          </span>
        </div>
        {brief.file_size != null && (
          <div className="ctx-detail-row">
            <span className="ctx-detail-label">Size</span>
            <span className="ctx-detail-value">{Math.round(brief.file_size / 1024)}KB</span>
          </div>
        )}
      </div>
    </div>
  );
}

function TranscriptContent({ tab }: { tab: Tab }): JSX.Element {
  const { getSession } = useSessionStore();
  const session = getSession(tab.targetId);

  useViewport('entity_view', () => ({
    visible: true,
    label: `transcript: ${session?.display_name || tab.targetId}`,
    children: ['session_pane', 'context_panel'],
  }));

  return (
    <div className="entity-view-row">
      <div className="entity-view-content">
        <div className="transcript-content">
          <TranscriptViewer
            open={true}
            inline={true}
            zellijSession={session?.terminal_session || tab.targetId}
            cliSessionId={session?.cli_session_id || undefined}
            sessionName={session?.display_name || tab.label}
            platform={session?.platform}
            onClose={() => {
              executeCommand('workspace.tabs.close', { tabId: tab.id });
            }}
          />
        </div>
      </div>
      <ContextPanel activeSessionId={tab.targetId} />
    </div>
  );
}

// --- Search Types ---

interface SearchMatchResult {
  lineNumber: number;
  messageType: string;
  content: string;
  matchText: string;
  matchStart?: number;
  matchEnd?: number;
  timestamp: string;
  sessionId?: string;
}

interface SessionGroupResult {
  sessionId: string;
  sessionName: string | null;
  filePath: string;
  projectSlug: string;
  matchCount: number;
  matches: SearchMatchResult[];
  expanded: boolean;
}

interface FlatMatch extends SearchMatchResult {
  sessionId: string;
  sessionName: string;
}

type SearchViewMode = 'grouped' | 'flat';
type SearchSortMode = 'hits' | 'time';

const MAX_VISIBLE_MATCHES = 3;

type SearchScope = 'sessions' | 'transcripts';

// ── Search filter option sets (data-driven so options are trivial to add/remove) ──
interface FilterOption { id: string; label: string }
// Platforms shown in the filter. Gemini intentionally omitted for now (a replacement
// is expected later); add/remove here — the dropdown rebuilds automatically.
const PLATFORM_OPTIONS: FilterOption[] = [
  { id: 'claude_cli', label: 'claude' },
  { id: 'codex_cli', label: 'codex' },
];
const STATUS_OPTIONS: FilterOption[] = [
  { id: 'active', label: 'active' },
  { id: 'stopped', label: 'stopped' },
];
const MSG_OPTIONS: FilterOption[] = [
  { id: 'user', label: 'user' },
  { id: 'assistant', label: 'assistant' },
  { id: 'tool', label: 'tool' },
];
// Relative-time quick picks for the date filter (label → milliseconds back from now).
const DATE_QUICK_PICKS: { label: string; ms: number }[] = [
  { label: '1h', ms: 3600e3 },
  { label: '6h', ms: 6 * 3600e3 },
  { label: '24h', ms: 24 * 3600e3 },
  { label: '7d', ms: 7 * 24 * 3600e3 },
  { label: '30d', ms: 30 * 24 * 3600e3 },
];

/** Parse a session's start time from its tracking_id (YYYYMMDD_HHMMSS_…) or a
 *  timestamp-ish field. Returns epoch ms, or null if unknown. */
function sessionStartMs(s: Session): number | null {
  const tid = (s as any).tracking_id as string | undefined;
  const m = tid && tid.match(/^(\d{4})(\d{2})(\d{2})_(\d{2})(\d{2})(\d{2})/);
  if (m) {
    const [, y, mo, d, h, mi, se] = m;
    const t = new Date(+y, +mo - 1, +d, +h, +mi, +se).getTime();
    if (!Number.isNaN(t)) return t;
  }
  const anyTs = (s as any).created || (s as any).started_at || (s as any).last_activity;
  if (anyTs) { const t = new Date(anyTs).getTime(); if (!Number.isNaN(t)) return t; }
  return null;
}

/** True if epoch-ms `t` falls within [fromIso, toIso] (either bound may be ''). */
function withinRange(t: number | null, fromIso: string, toIso: string): boolean {
  if (!fromIso && !toIso) return true;
  if (t == null) return false;        // a date filter is set but this item has no date
  if (fromIso) { const f = new Date(fromIso).getTime(); if (!Number.isNaN(f) && t < f) return false; }
  if (toIso) { const to = new Date(toIso).getTime(); if (!Number.isNaN(to) && t > to) return false; }
  return true;
}

/** Compact multi-select dropdown — replaces filter "pills". Shows "Label (n/total)"
 *  and a checkbox list in a popover; closes on outside click. */
function FilterMultiSelect({ label, options, selected, onToggle }: {
  label: string; options: FilterOption[]; selected: Set<string>; onToggle: (id: string) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);
  const allOn = selected.size >= options.length;
  const summary = allOn ? 'all' : options.filter(o => selected.has(o.id)).map(o => o.label).join(', ') || 'none';
  return (
    <div className="sp-dropdown" ref={ref}>
      <button className={`sp-dropdown-btn${allOn ? '' : ' sp-dropdown-active'}`} onClick={() => setOpen(v => !v)}>
        {label}: <span className="sp-dropdown-summary">{summary}</span> <span className="sp-dropdown-caret">{'▾'}</span>
      </button>
      {open && (
        <div className="sp-dropdown-menu">
          {options.map(o => (
            <label key={o.id} className="sp-dropdown-item">
              <input type="checkbox" checked={selected.has(o.id)} onChange={() => onToggle(o.id)} />
              {o.label}
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

/** Date-range filter: from/to datetime inputs + relative quick-picks. Bounds are ISO
 *  strings ('' = open). Used for both Sessions (by start time) and Transcripts (by
 *  message timestamp). */
function SearchDateFilter({ from, to, setFrom, setTo }: {
  from: string; to: string; setFrom: (v: string) => void; setTo: (v: string) => void;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);
  // datetime-local wants 'YYYY-MM-DDTHH:mm'; convert to/from ISO.
  const toLocalInput = (iso: string) => {
    if (!iso) return '';
    const d = new Date(iso); if (Number.isNaN(d.getTime())) return '';
    const pad = (n: number) => String(n).padStart(2, '0');
    return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
  };
  const fromLocal = (v: string) => v ? new Date(v).toISOString() : '';
  const active = !!(from || to);
  const summary = active
    ? `${from ? toLocalInput(from).slice(5, 16).replace('T', ' ') : '…'} – ${to ? toLocalInput(to).slice(5, 16).replace('T', ' ') : 'now'}`
    : 'any';
  return (
    <div className="sp-dropdown" ref={ref}>
      <button className={`sp-dropdown-btn${active ? ' sp-dropdown-active' : ''}`} onClick={() => setOpen(v => !v)}>
        Date: <span className="sp-dropdown-summary">{summary}</span> <span className="sp-dropdown-caret">{'▾'}</span>
      </button>
      {open && (
        <div className="sp-dropdown-menu sp-date-menu">
          <div className="sp-date-quick">
            {DATE_QUICK_PICKS.map(q => (
              <button key={q.label} className="sp-pill"
                onClick={() => { setFrom(new Date(Date.now() - q.ms).toISOString()); setTo(''); }}>
                {q.label}
              </button>
            ))}
          </div>
          <label className="sp-date-field">From
            <input type="datetime-local" value={toLocalInput(from)} onChange={(e) => setFrom(fromLocal(e.target.value))} />
          </label>
          <label className="sp-date-field">To
            <input type="datetime-local" value={toLocalInput(to)} onChange={(e) => setTo(fromLocal(e.target.value))} />
          </label>
          <button className="sp-pill" onClick={() => { setFrom(''); setTo(''); }}>Clear dates</button>
        </div>
      )}
    </div>
  );
}

function SearchContent({ tab }: { tab: Tab }): JSX.Element {
  // Restore prior search state for this tab so results/query/filters survive a
  // tab switch (the component unmounts when not active). See search-state-store.
  const restored = useRef(getSearchSnapshot(tab.id)).current;
  const firstRunRef = useRef(true);

  const [query, setQuery] = useState(restored?.query ?? (tab.targetId === '_global' ? '' : (tab.targetId || '')));
  const [scope, setScope] = useState<SearchScope>(restored?.scope ?? 'transcripts');
  const [results, setResults] = useState<SessionGroupResult[]>((restored?.results as SessionGroupResult[]) ?? []);
  const [sessionResults, setSessionResults] = useState<Session[]>((restored?.sessionResults as Session[]) ?? []);
  const [searching, setSearching] = useState(false);
  const [regexMode, setRegexMode] = useState(restored?.regexMode ?? false);
  const [caseSensitive, setCaseSensitive] = useState(restored?.caseSensitive ?? false);
  const [deduplicateEnabled, setDeduplicateEnabled] = useState(restored?.deduplicateEnabled ?? true);
  const [totalMatches, setTotalMatches] = useState(restored?.totalMatches ?? 0);
  const [sessionsSearched, setSessionsSearched] = useState(restored?.sessionsSearched ?? 0);
  const [searchTimeMs, setSearchTimeMs] = useState(restored?.searchTimeMs ?? 0);
  const [viewMode, setViewMode] = useState<SearchViewMode>(restored?.viewMode ?? 'grouped');
  const [sortMode, setSortMode] = useState<SearchSortMode>(restored?.sortMode ?? 'hits');
  const [hasSearched, setHasSearched] = useState(restored?.hasSearched ?? false);
  const [includeSubagents, setIncludeSubagents] = useState(restored?.includeSubagents ?? false);
  const inputRef = useRef<HTMLInputElement>(null);
  const { sessions } = useSessionStore();

  // Build a lookup map from cli_session_id to session data
  const sessionLookup = useMemo(() => {
    const map = new Map<string, Session>();
    for (const s of sessions) {
      if (s.cli_session_id) map.set(s.cli_session_id, s);
      map.set(s.tracking_id, s);
    }
    return map;
  }, [sessions]);

  // Focus input on mount
  useEffect(() => {
    setTimeout(() => inputRef.current?.focus(), 150);
  }, []);

  // NOTE: initial search (when a tab opens carrying a query) is handled by the
  // debounced effect below — query is seeded from tab.targetId. The '_global'
  // sentinel is treated as empty so opening global Search shows NO results.

  const doSearchImmediate = useCallback(async (searchQuery: string) => {
    if (!searchQuery.trim()) {
      setResults([]);
      setSessionResults([]);
      setTotalMatches(0);
      setHasSearched(false);
      return;
    }

    setSearching(true);
    setHasSearched(true);

    if (scope === 'sessions') {
      // Client-side session metadata search
      const start = Date.now();
      const q = caseSensitive ? searchQuery.trim() : searchQuery.trim().toLowerCase();
      const matched = sessions.filter(s => {
        const fields = [
          s.display_name || '',
          s.tracking_id || '',
          s.cli_session_id || '',
          s.platform || '',
          (s as any).role || '',
          (s as any).project_dir || '',
        ].join(' ');
        const haystack = caseSensitive ? fields : fields.toLowerCase();
        if (regexMode) {
          try { return new RegExp(q, caseSensitive ? '' : 'i').test(haystack); } catch { return false; }
        }
        return haystack.includes(q);
      });
      setSessionResults(matched);
      setResults([]);
      setTotalMatches(matched.length);
      setSessionsSearched(sessions.length);
      setSearchTimeMs(Date.now() - start);
      setSearching(false);
      return;
    }

    // Transcript search via backend
    try {
      const response = await window.uai.searchGrouped(searchQuery.trim(), {
        limit: 200,
        caseSensitive,
        regex: regexMode,
        deduplicate: deduplicateEnabled,
        includeSubagents,
      });

      const grouped: SessionGroupResult[] = response.results.map((r: any) => ({
        ...r,
        expanded: false,
      }));

      setResults(grouped);
      setSessionResults([]);
      setTotalMatches(response.totalMatches);
      setSessionsSearched(response.sessionsSearched);
      setSearchTimeMs(response.searchTimeMs);
    } catch (err) {
      console.error('[SearchContent] Search failed:', err);
      setResults([]);
      setTotalMatches(0);
    } finally {
      setSearching(false);
    }
  }, [caseSensitive, regexMode, deduplicateEnabled, includeSubagents, scope, sessions]);

  const doSearch = useCallback(() => {
    doSearchImmediate(query);
  }, [query, doSearchImmediate]);

  // Debounced auto-search on query/scope change.
  //  - On the very first mount, if we restored a prior snapshot, keep those
  //    results (don't re-search) so the tab is truly sticky.
  //  - When the query is empty/cleared, clear the results (no default results).
  useEffect(() => {
    if (firstRunRef.current) {
      firstRunRef.current = false;
      if (restored) return; // restored snapshot — leave results as-is
    }
    if (!query.trim()) {
      setResults([]);
      setSessionResults([]);
      setTotalMatches(0);
      setSessionsSearched(0);
      setHasSearched(false);
      return;
    }
    const timer = setTimeout(() => doSearchImmediate(query), scope === 'sessions' ? 150 : 400);
    return () => clearTimeout(timer);
  }, [query, scope, doSearchImmediate, restored]);

  const toggleExpanded = useCallback((sessionId: string) => {
    setResults(prev => prev.map(r =>
      r.sessionId === sessionId ? { ...r, expanded: !r.expanded } : r
    ));
  }, []);

  const handleMatchClick = useCallback((sessionId: string, _lineNumber: number) => {
    // Look up the session to get a display name
    const session = sessionLookup.get(sessionId);
    const label = session?.display_name || sessionId.slice(0, 12);

    executeCommand('workspace.tabs.open', {
      type: 'session',
      targetId: session?.tracking_id || sessionId,
      label: `Transcript — ${label}`,
    });
  }, [sessionLookup]);

  // Resolve session display name from lookup
  const getSessionDisplayName = useCallback((sessionId: string): string => {
    const session = sessionLookup.get(sessionId);
    return session?.display_name || sessionId.slice(0, 12);
  }, [sessionLookup]);

  const getSessionPlatform = useCallback((sessionId: string): string => {
    const session = sessionLookup.get(sessionId);
    return session?.platform || '';
  }, [sessionLookup]);

  // Sort results
  const sortedResults = useMemo(() => {
    const sorted = [...results];
    if (sortMode === 'hits') {
      sorted.sort((a, b) => b.matchCount - a.matchCount);
    } else if (sortMode === 'time') {
      sorted.sort((a, b) => {
        const aLatest = a.matches.reduce((max, m) => m.timestamp > max ? m.timestamp : max, '');
        const bLatest = b.matches.reduce((max, m) => m.timestamp > max ? m.timestamp : max, '');
        return bLatest.localeCompare(aLatest);
      });
    }
    return sorted;
  }, [results, sortMode]);

  // flatMatches is defined below (after filteredResults) so the flat view honors the
  // same platform/status/message/date filters as the grouped view.

  // Format timestamp for display
  const fmtTs = (ts: string): string => {
    if (!ts) return '';
    try {
      const d = new Date(ts);
      return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
    } catch { return ts.slice(0, 16); }
  };

  // Role badge helper
  const roleBadge = (role: string): string => {
    if (role === 'user') return 'U';
    if (role === 'assistant') return 'A';
    if (role === 'tool') return 'T';
    return '?';
  };

  // Render match content with highlighting
  const renderHighlighted = (text: string, match: SearchMatchResult): JSX.Element => {
    if (match.matchStart !== undefined && match.matchEnd !== undefined && match.matchStart < text.length) {
      const start = Math.min(match.matchStart, text.length);
      const end = Math.min(match.matchEnd, text.length);
      return (
        <>
          {text.slice(0, start)}
          <mark className="sp-match-highlight">{text.slice(start, end)}</mark>
          {text.slice(end)}
        </>
      );
    }
    return <>{text}</>;
  };

  // Render a match line — collapsed (one line, truncated) or expanded (full content)
  const renderMatchContent = (match: SearchMatchResult, matchKey: string): JSX.Element => {
    const text = match.content || '';
    const isExpanded = expandedMatches.has(matchKey);
    const isLong = text.length > 120;

    return (
      <span
        className={`sp-match-line-text${isExpanded ? ' sp-match-expanded' : ''}`}
        title={text.slice(0, 500)}
        onClick={(e) => { if (isLong) { e.stopPropagation(); toggleMatchExpand(matchKey); } }}
        style={isLong ? { cursor: 'pointer' } : undefined}
      >
        {isExpanded ? renderHighlighted(text, match) : renderHighlighted(isLong ? text.slice(0, 120) + '...' : text, match)}
      </span>
    );
  };

  // Filter state (hydrated from the per-tab snapshot for stickiness)
  const [filtersOpen, setFiltersOpen] = useState(restored?.filtersOpen ?? false);
  const [filterPlatforms, setFilterPlatforms] = useState<Set<string>>(new Set(restored?.filterPlatforms ?? PLATFORM_OPTIONS.map(o => o.id)));
  const [filterStatuses, setFilterStatuses] = useState<Set<string>>(new Set(restored?.filterStatuses ?? STATUS_OPTIONS.map(o => o.id)));
  const [filterMsgTypes, setFilterMsgTypes] = useState<Set<string>>(new Set(restored?.filterMsgTypes ?? MSG_OPTIONS.map(o => o.id)));
  const [dateFrom, setDateFrom] = useState<string>(restored?.dateFrom ?? '');
  const [dateTo, setDateTo] = useState<string>(restored?.dateTo ?? '');
  const [invertResults, setInvertResults] = useState(restored?.invertResults ?? false);
  const [expandedMatches, setExpandedMatches] = useState<Set<string>>(new Set());
  const toggleMatchExpand = (key: string) => setExpandedMatches(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });

  const togglePlatform = (p: string) => setFilterPlatforms(prev => { const n = new Set(prev); n.has(p) ? n.delete(p) : n.add(p); return n; });
  const toggleStatus = (s: string) => setFilterStatuses(prev => { const n = new Set(prev); n.has(s) ? n.delete(s) : n.add(s); return n; });
  const toggleMsgType = (t: string) => setFilterMsgTypes(prev => { const n = new Set(prev); n.has(t) ? n.delete(t) : n.add(t); return n; });

  // Apply client-side filters to results
  const filteredResults = useMemo(() => {
    const out = sortedResults.map(group => {
      const session = sessionLookup.get(group.sessionId);
      // Platform filter
      if (session && filterPlatforms.size < PLATFORM_OPTIONS.length && !filterPlatforms.has(session.platform)) return null;
      // Status filter (multi-select; both selected = no filter)
      if (session && filterStatuses.size < STATUS_OPTIONS.length) {
        const st = session.process_status === 'running' ? 'active' : 'stopped';
        if (!filterStatuses.has(st)) return null;
      }
      // Message type + date filter (transcripts filter by each match's timestamp)
      const filtered = group.matches.filter(m =>
        filterMsgTypes.has(m.messageType) &&
        withinRange(m.timestamp ? new Date(m.timestamp).getTime() : null, dateFrom, dateTo)
      );
      if (filtered.length === 0) return null;
      return { ...group, matches: filtered, matchCount: filtered.length };
    }).filter(Boolean) as SessionGroupResult[];

    // Re-sort AFTER filtering — filtering recomputes matchCount, so grouped
    // results must be re-ordered to actually obey the sort (item 8).
    if (sortMode === 'hits') {
      out.sort((a, b) => b.matchCount - a.matchCount);
    } else if (sortMode === 'time') {
      out.sort((a, b) => {
        const aLatest = a.matches.reduce((max, m) => m.timestamp > max ? m.timestamp : max, '');
        const bLatest = b.matches.reduce((max, m) => m.timestamp > max ? m.timestamp : max, '');
        return bLatest.localeCompare(aLatest);
      });
    }
    return out;
  }, [sortedResults, sessionLookup, filterPlatforms, filterStatuses, filterMsgTypes, dateFrom, dateTo, sortMode]);

  // Sessions scope: apply platform / status / date filters to the session-metadata
  // results (transcript groups use filteredResults above).
  const displaySessionResults = useMemo(() => {
    return sessionResults.filter(s => {
      if (filterPlatforms.size < PLATFORM_OPTIONS.length && !filterPlatforms.has(s.platform)) return false;
      if (filterStatuses.size < STATUS_OPTIONS.length) {
        const st = s.process_status === 'running' ? 'active' : 'stopped';
        if (!filterStatuses.has(st)) return false;
      }
      if (!withinRange(sessionStartMs(s), dateFrom, dateTo)) return false;
      return true;
    });
  }, [sessionResults, filterPlatforms, filterStatuses, dateFrom, dateTo]);

  const activeFilterCount = (filterPlatforms.size < PLATFORM_OPTIONS.length ? 1 : 0)
    + (filterStatuses.size < STATUS_OPTIONS.length ? 1 : 0)
    + (filterMsgTypes.size < MSG_OPTIONS.length ? 1 : 0)
    + (dateFrom || dateTo ? 1 : 0)
    + (invertResults ? 1 : 0);

  // Flat view: all matches across sessions in one list — sourced from filteredResults
  // so platform/status/message/date filters apply here exactly as in the grouped view.
  const flatMatches: FlatMatch[] = useMemo(() => {
    if (viewMode !== 'flat') return [];
    return filteredResults.flatMap(r =>
      r.matches.map(m => ({
        ...m,
        sessionId: r.sessionId,
        sessionName: getSessionDisplayName(r.sessionId),
      }))
    ).sort((a, b) => {
      if (sortMode === 'time') return (b.timestamp ?? '').localeCompare(a.timestamp ?? '');
      return 0;
    });
  }, [viewMode, filteredResults, sortMode, getSessionDisplayName]);

  // Persist search state for this tab so it survives unmount on tab switch (item 2).
  useEffect(() => {
    setSearchSnapshot(tab.id, {
      query, scope, results, sessionResults, totalMatches, sessionsSearched, searchTimeMs,
      viewMode, sortMode, hasSearched, regexMode, caseSensitive, deduplicateEnabled, includeSubagents,
      filtersOpen, filterPlatforms: [...filterPlatforms], filterStatuses: [...filterStatuses],
      filterMsgTypes: [...filterMsgTypes], invertResults, dateFrom, dateTo,
    });
  }, [tab.id, query, scope, results, sessionResults, totalMatches, sessionsSearched, searchTimeMs,
    viewMode, sortMode, hasSearched, regexMode, caseSensitive, deduplicateEnabled, includeSubagents,
    filtersOpen, filterPlatforms, filterStatuses, filterMsgTypes, invertResults, dateFrom, dateTo]);

  return (
    <div className="search-content">
      {/* Search header */}
      <div className="sp-header">
        {/* Scope toggle */}
        <div className="sp-scope-row">
          <button className={`sp-scope-btn${scope === 'sessions' ? ' active' : ''}`} onClick={() => setScope('sessions')}>Sessions</button>
          <button className={`sp-scope-btn${scope === 'transcripts' ? ' active' : ''}`} onClick={() => setScope('transcripts')}>Transcripts</button>
        </div>

        {/* Hints above search box */}
        {!hasSearched && !searching && (
          <div className="sp-hints-inline">
            {scope === 'transcripts' ? (
              // Mode-specific hint: describes ONLY the active mode and leads with the
              // same glyph as the mode-toggle button, so the two read together. The
              // whole hint swaps on toggle (no half-hidden leftovers). AND/OR/NOT
              // belongs to literal mode; regex expresses those itself.
              regexMode ? (
                <span className="sp-hint-inline"><span className="sp-hint-mode sp-hint-mode-regex">.*</span> regex pattern</span>
              ) : (<>
                <span className="sp-hint-inline"><span className="sp-hint-mode">Aa</span> literal text</span>
                <span className="sp-hint-sep">{'\u00b7'}</span>
                <span className="sp-hint-inline">combine with <strong>AND</strong> / <strong>OR</strong> / <strong>NOT</strong></span>
              </>)
            ) : (
              <span className="sp-hint-inline">Search by name, role, platform, project...</span>
            )}
          </div>
        )}

        {/* Input row */}
        <div className="sp-input-row">
          <button
            className={`sp-mode-btn ${regexMode ? 'sp-mode-regex' : ''}`}
            onClick={() => setRegexMode(prev => !prev)}
            title={regexMode ? 'Regex mode (click for literal)' : 'Literal mode (click for regex)'}
          >
            {regexMode ? '.*' : 'Aa'}
          </button>
          <div className="sp-input-wrapper">
            <input
              ref={inputRef}
              className="sp-input"
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') doSearch();
                if (e.key === 'Escape') setQuery('');
              }}
              placeholder={regexMode ? 'Regex pattern...' : 'Search transcripts...'}
              spellCheck={false}
            />
            {query && (
              <button className="sp-clear-btn" onClick={() => setQuery('')} title="Clear">{'\u2715'}</button>
            )}
            {searching && <span className="sp-spinner" />}
          </div>
        </div>

        {/* Filters toggle */}
        <div className="sp-filters-toggle" onClick={() => setFiltersOpen(v => !v)}>
          <span className="sp-filters-icon">{'\u2699'}</span>
          <span>Filters{activeFilterCount > 0 ? ` (${activeFilterCount})` : ''}</span>
          <span className="sp-filters-chevron">{filtersOpen ? '\u25B2' : '\u25BC'}</span>
        </div>

        {/* Filters panel */}
        {filtersOpen && (
          <div className="sp-filters">
            <div className="sp-filter-row">
              <FilterMultiSelect label="Platform" options={PLATFORM_OPTIONS} selected={filterPlatforms} onToggle={togglePlatform} />
              <FilterMultiSelect label="Status" options={STATUS_OPTIONS} selected={filterStatuses} onToggle={toggleStatus} />
              {scope === 'transcripts' && (
                <FilterMultiSelect label="Message" options={MSG_OPTIONS} selected={filterMsgTypes} onToggle={toggleMsgType} />
              )}
              <SearchDateFilter from={dateFrom} to={dateTo} setFrom={setDateFrom} setTo={setDateTo} />
            </div>
            <div className="sp-filter-row">
              <label className="sp-filter-check">
                <input type="checkbox" checked={caseSensitive} onChange={() => setCaseSensitive(v => !v)} />
                Case sensitive
              </label>
              <label className="sp-filter-check">
                <input type="checkbox" checked={deduplicateEnabled} onChange={() => setDeduplicateEnabled(v => !v)} />
                Deduplicate
              </label>
              <label className="sp-filter-check">
                <input type="checkbox" checked={invertResults} onChange={() => setInvertResults(v => !v)} />
                Invert results
              </label>
              <label className="sp-filter-check">
                <input type="checkbox" checked={includeSubagents} onChange={() => setIncludeSubagents(v => !v)} />
                Include subagents
              </label>
            </div>
          </div>
        )}

        {/* Stats row — Group/Flat + Sort on the LEFT, result count to their right (item 9) */}
        <div className="sp-stats-row">
          {/* View/sort controls (transcripts only, when there are results) */}
          {scope === 'transcripts' && results.length > 0 && (
            <div className="sp-view-controls">
              <button
                className={`sp-view-btn ${viewMode === 'grouped' ? 'active' : ''}`}
                onClick={() => setViewMode('grouped')}
                title="Group by session"
              >Grouped</button>
              <button
                className={`sp-view-btn ${viewMode === 'flat' ? 'active' : ''}`}
                onClick={() => setViewMode('flat')}
                title="Flat list"
              >Flat</button>
              <span className="sp-view-sep" />
              <select
                className="sp-sort-select"
                value={sortMode}
                onChange={(e) => setSortMode(e.target.value as SearchSortMode)}
              >
                <option value="hits">Most Hits</option>
                <option value="time">Most Recent</option>
              </select>
            </div>
          )}

          {searching && (
            <span className="sp-stats sp-searching">Searching...</span>
          )}
          {!searching && hasSearched && totalMatches > 0 && (
            <span className="sp-stats">
              {totalMatches} match{totalMatches !== 1 ? 'es' : ''} in {results.length} session{results.length !== 1 ? 's' : ''}
              {sessionsSearched > 0 && <span className="sp-stats-detail"> ({sessionsSearched} files searched)</span>}
              <span className="sp-stats-time">{searchTimeMs}ms</span>
            </span>
          )}
          {!searching && hasSearched && totalMatches === 0 && (
            <span className="sp-stats sp-no-results">No matches found</span>
          )}
        </div>
      </div>

      {/* Results */}
      <div className="sp-results">
        {/* Session results */}
        {scope === 'sessions' && displaySessionResults.map(s => {
          const platformCls = s.platform ? s.platform.replace('_cli', '') : '';
          return (
            <div
              key={s.tracking_id}
              className={`sp-session-card ${platformCls ? `sp-platform-${platformCls}` : ''}`}
              onClick={() => executeCommand('workspace.tabs.open', { type: 'session', targetId: s.tracking_id, label: s.display_name || s.tracking_id })}
            >
              {s.platform && <span className={`sp-platform-dot sp-dot-${platformCls}`} />}
              <span className="sp-session-name">{s.display_name || s.tracking_id}</span>
              <span className={`sp-session-status ${s.process_status === 'running' ? 'sp-status-running' : 'sp-status-stopped'}`}>
                {s.process_status === 'running' ? 'active' : 'stopped'}
              </span>
              {(s as any).role && <span className="sp-session-role">{(s as any).role}</span>}
              <span className="sp-session-id">{s.tracking_id.slice(0, 20)}</span>
            </div>
          );
        })}

        {/* Flat view */}
        {scope === 'transcripts' && viewMode === 'flat' && flatMatches.map((match, idx) => (
          <div
            key={`flat-${idx}`}
            className="sp-match-line sp-flat-match"
            onClick={() => handleMatchClick(match.sessionId, match.lineNumber)}
          >
            <span className="sp-flat-session" title={match.sessionName}>
              {match.sessionName.length > 20 ? match.sessionName.slice(0, 18) + '...' : match.sessionName}
            </span>
            <span className={`sp-role-badge sp-role-${match.messageType}`}>
              {roleBadge(match.messageType)}
            </span>
            <span className="sp-line-num">L{match.lineNumber}</span>
            {match.timestamp && <span className="sp-timestamp">{fmtTs(match.timestamp)}</span>}
            {renderMatchContent(match, `${match.sessionId || ''}-${match.lineNumber}`)}
          </div>
        ))}

        {/* Grouped view */}
        {scope === 'transcripts' && viewMode === 'grouped' && filteredResults.map((group) => {
          const displayName = getSessionDisplayName(group.sessionId);
          const platform = getSessionPlatform(group.sessionId);
          const visibleMatches = group.expanded
            ? group.matches
            : group.matches.slice(0, MAX_VISIBLE_MATCHES);
          const hiddenCount = group.matches.length - MAX_VISIBLE_MATCHES;

          return (
            <div
              key={group.sessionId}
              className={`sp-result-group ${platform ? `sp-platform-${platform.replace('_cli', '')}` : ''}`}
            >
              {/* Session header */}
              <div
                className="sp-group-header"
                onClick={() => handleMatchClick(group.sessionId, group.matches[0]?.lineNumber || 0)}
              >
                {platform && <span className={`sp-platform-dot sp-dot-${platform.replace('_cli', '')}`} />}
                <span className="sp-group-name">{displayName}</span>
                <span className="sp-group-slug" title={group.projectSlug}>{group.projectSlug}</span>
                <span className="sp-group-count">{group.matchCount}</span>
              </div>

              {/* Match lines */}
              <div className="sp-match-lines">
                {visibleMatches.map((match, idx) => (
                  <div
                    key={idx}
                    className="sp-match-line"
                    onClick={() => handleMatchClick(group.sessionId, match.lineNumber)}
                  >
                    <span className={`sp-role-badge sp-role-${match.messageType}`}>
                      {roleBadge(match.messageType)}
                    </span>
                    <span className="sp-line-num">L{match.lineNumber}</span>
                    {match.timestamp && <span className="sp-timestamp">{fmtTs(match.timestamp)}</span>}
                    {renderMatchContent(match, `${match.sessionId || ''}-${match.lineNumber}`)}
                  </div>
                ))}

                {!group.expanded && hiddenCount > 0 && (
                  <button
                    className="sp-show-more"
                    onClick={(e) => { e.stopPropagation(); toggleExpanded(group.sessionId); }}
                  >
                    +{hiddenCount} more
                  </button>
                )}

                {group.expanded && hiddenCount > 0 && (
                  <button
                    className="sp-show-more"
                    onClick={(e) => { e.stopPropagation(); toggleExpanded(group.sessionId); }}
                  >
                    Show less
                  </button>
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function ProjectContent({ tab }: { tab: Tab }): JSX.Element {
  const cardStore = useCardStore();
  const project = cardStore.projects.find(p =>
    p.project_id === tab.targetId ||
    p.entity_id === `project:${tab.targetId}` ||
    p.entity_id === tab.targetId ||
    p.display_name === tab.targetId
  );

  if (!project) {
    const isNew = tab.targetId.startsWith('new_project_');
    return (
      <div className="workspace-placeholder">
        <h3>{isNew ? 'New Project' : 'Project not found'}</h3>
        {isNew ? (
          <div style={{ maxWidth: '400px', textAlign: 'left' }}>
            <p style={{ color: 'var(--text-sec)', marginBottom: '16px' }}>
              Create a project by adding a <code>project.yml</code> file to a project directory, then re-index.
            </p>
            <p style={{ color: 'var(--text-muted)', fontSize: '12px' }}>
              Projects are discovered from <code>project.yml</code> files on disk.
              See the Projects tab in the Navigator for existing projects.
            </p>
          </div>
        ) : (
          <p>{tab.targetId}</p>
        )}
      </div>
    );
  }

  // Show sessions belonging to this project
  const projectSessions = cardStore.sessions.filter(s => s.project_dir === project.working_dir);

  // Pass ALL sessions — ProjectEditor filters project sessions by working_dir and,
  // for teams, resolves registry members (assigned_ais) against the full list.
  void projectSessions;
  return (
    <div className="project-content">
      <ProjectEditor project={project} sessions={cardStore.sessions} />
    </div>
  );
}

function TeamContent({ tab }: { tab: Tab }): JSX.Element {
  const cardStore = useCardStore();
  const team = cardStore.teams.find(t => t.entity_id === `team:${tab.targetId}` || t.entity_id === tab.targetId);

  if (!team) {
    return (
      <div className="workspace-placeholder">
        <h3>Team not found</h3>
        <p>{tab.targetId}</p>
      </div>
    );
  }

  return (
    <div className="team-content">
      <TeamDetailView team={team} />
    </div>
  );
}

// Conventional viewport ids for app-tab panes — so describeViewport() can reach
// each Mgr. A pane appears in the tree only once it registers a useViewport
// reporter under its id; until then the node resolves as not-visible. work_mgr
// is the first tool Mgr wired in.
const APP_VIEWPORT_IDS: Record<string, string> = {
  'work-mgr': 'work_mgr',
  'todo-manager': 'todo_manager',
  'task-manager': 'task_manager',
  'session-store-manager': 'session_store_mgr',
  'scheduled-tasks': 'scheduled_tasks',
  'assigned-tasks': 'assigned_tasks',
  'live-board': 'live_board',
  'notes-manager': 'notes_manager',
  'user-messages': 'user_messages',
  'mcp-manager': 'mcp_manager',
  'tab-manager': 'tab_manager',
  'git-file-view': 'git_file_view',
  'context-manager': 'context_manager',
};

// App-tab content wrapper — registers the center-pane `entity_view` node and
// points it at the active app pane's viewport id, so the Mgrs join the
// describeViewport() tree (mirrors SessionContent/TranscriptContent).
function AppContent({ tab }: { tab: Tab }): JSX.Element {
  const vpId = APP_VIEWPORT_IDS[tab.targetId || ''] || `app_${tab.targetId || 'unknown'}`;
  useViewport('entity_view', () => ({
    visible: true,
    label: `app: ${tab.label || tab.targetId}`,
    children: [vpId],
  }));
  switch (tab.targetId) {
    case 'todo-manager':
      return <TodoManagerPane tabId={tab.id} deepLinkId={tab.deepLinkId} />;
    case 'task-manager':
      return <TaskManagerPane tabId={tab.id} deepLinkId={tab.deepLinkId} />;
    case 'session-store-manager':
      return <SessionStoreMgrPane tabId={tab.id} initialSession={tab.deepLinkId} />;
    case 'scheduled-tasks':
      return <ScheduledTasksPane tabId={tab.id} />;
    case 'assigned-tasks':
      return <AssignedTasksMgr tabId={tab.id} />;
    case 'work-mgr':
      return <WorkMgrPane tabId={tab.id} />;
    case 'live-board':
      return <LiveBoardPane />;
    case 'notes-manager':
      return <NotesManagerPane />;
    case 'user-messages':
      return <UserMessagesPane />;
    case 'mcp-manager':
      return <McpManagerPane tabId={tab.id} />;
    case 'tab-manager':
      return <TabManagerPane tabId={tab.id} />;
    case 'git-file-view':
      return <GitViewerPane tabId={tab.id} />;
    case 'context-manager':
    default:
      return <ContextMgrPane tabId={tab.id} deepLinkId={tab.deepLinkId} />;
  }
}

export default function TabContentPane({ tab, memorexEnabled, transcriptOpen, onCloseTranscript, subtab }: TabContentPaneProps): JSX.Element {
  switch (tab.type) {
    case 'session':
      return <SessionContent tab={tab} memorexEnabled={memorexEnabled} transcriptOpen={transcriptOpen} onCloseTranscript={onCloseTranscript} subtab={subtab} />;
    case 'folder':
      return <FolderContent tab={tab} />;
    case 'terminal':
      return <TerminalContent tab={tab} />;
    case 'brief':
      return <BriefContent tab={tab} />;
    case 'transcript':
      // Legacy — transcript tabs are now just session tabs that show transcript for stopped sessions
      return <SessionContent tab={{ ...tab, type: 'session' }} memorexEnabled={memorexEnabled} />;
    case 'search':
      return <SearchContent tab={tab} />;
    case 'project':
      return <ProjectContent tab={tab} />;
    case 'team':
      // Teams are projects (registry .team.yml) — render the unified Project Editor
      // (team-flavored). Legacy TeamDetailView retired; one way to view a team.
      return <ProjectContent tab={{ ...tab, type: 'project' }} />;
    case 'webai':
      return <WebAIPane url={tab.targetId} />;
    case 'app':
      return <AppContent tab={tab} />;
    default:
      return (
        <div className="workspace-placeholder">
          <h3>Unknown tab type</h3>
          <p>{(tab as any).type}</p>
        </div>
      );
  }
}
