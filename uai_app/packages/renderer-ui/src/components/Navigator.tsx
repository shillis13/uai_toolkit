/**
 * Navigator — Left panel with tabbed session/brief lists.
 *
 * Tabs: Sessions | Briefs | Teams (placeholder) | Projects (placeholder)
 * Sessions tab: filter toolbar (status/platform pills, search), sort control,
 * collapsible Active/Stopped sections, session cards, context menu, multi-select.
 *
 * Reads from useSessionStore(). Dispatches commands via window.uai.execute().
 * Registers with ComponentRegistry.
 */

import { Fragment, useState, useRef, useEffect, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { useViewport } from '../viewport';
import { useSessionStore, useAppStateStore, useCardStore } from '../stores';
import { useFolderStore } from '../stores/folder-store';
import { useActionContext } from '../context';
import { useToast } from './Toast';
import { useContextMenuDismiss } from '../hooks/use-context-menu-dismiss';
import { executeCommand } from '../utils/execute-command';
import { promptBlockChip } from '../utils/prompt-block';
import { CardListView } from './cards';
import { FolderTree } from './folders/FolderTree';
import { Breadcrumbs } from './folders/Breadcrumbs';
import { FolderContextMenu } from './folders/FolderContextMenu';
import SessionContextMenu from './SessionContextMenu';
import ContextTab from './ContextTab';
import type { Session } from '@uai/shared/types';
import type { AnyCard, SessionCard } from '@uai/shared/cards';
import { isSessionCard } from '@uai/shared/cards';
import type { SortField, SortDirection, NavigatorTab } from '../../../../architecture/contracts';
import ProjectsTab from './ProjectsTab';
import { useFeature } from '../stores/features';
import NewsTab from './NewsTab';
import { SessionBadges, SESSION_BADGE_LEGEND } from './SessionBadges';
import { getSessionActivity, getUnreadReplyCount, onActivityChange } from '../stores/session-activity';
import { onPromptAreaChange, scanAllPromptAreas } from '../stores/prompt-area-state';
import { isSessionBreathing } from '../stores/session-state';
import { getCommsCount, scanCommsCounts, onCommsCountChange } from '../stores/comms-count-state';

// ─── Constants ───────────────────────────────────────────────────────────

const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude',
  codex_cli: 'Codex',
  gemini_cli: 'Gemini',
};

const TAB_LABELS: Record<string, string> = { sessions: 'Sessions', projects: 'Projects / Teams', webuis: 'Web UIs', terminals: 'Terminals', apps: 'Games', news: 'News & Reports' };

// ─── Helpers ─────────────────────────────────────────────────────────────

function getDisplayName(session: Session): string {
  if (session.display_name) {
    return session.display_name
      .replace(/^(claude|codex|gemini)_cli_/, '')
      .replace(/_\d{8}T\d{6}$/, '')
      .replace(/_/g, ' ');
  }
  return session.roles.length > 0 ? session.roles[0] : session.tracking_id;
}

// ─── Filter/Sort types ──────────────────────────────────────────────────

interface DateRange {
  from: string;  // ISO date string or ''
  to: string;    // ISO date string or ''
}

interface FilterState {
  status: Set<string>;      // 'running' | 'stopped' | 'archived'
  platform: Set<string>;    // 'claude_cli' | 'codex_cli' | 'gemini_cli'
  search: string;
  dateRange: DateRange | null;
  tags: Set<string>;
  unaffiliated: boolean;    // sessions not in any folder
}

const DEFAULT_FILTER: FilterState = {
  status: new Set(),
  platform: new Set(),
  search: '',
  dateRange: null,
  tags: new Set(),
  unaffiliated: false,
};

function filterSessions(sessions: Session[], filter: FilterState, folderCardIds?: Set<string>): Session[] {
  return sessions.filter(s => {
    // Status filter
    if (filter.status.size > 0) {
      const sessionStatus = s.archived ? 'archived' : s.process_status === 'running' ? 'running' : 'stopped';
      if (!filter.status.has(sessionStatus)) return false;
    } else {
      // Default: hide archived
      if (s.archived) return false;
    }

    // Platform filter
    if (filter.platform.size > 0 && !filter.platform.has(s.platform)) return false;

    // Date range filter
    if (filter.dateRange) {
      const activityDate = s.last_activity || s.created_at;
      if (filter.dateRange.from && activityDate < filter.dateRange.from) return false;
      if (filter.dateRange.to) {
        // Include the entire "to" day by comparing against the next day
        const toNext = filter.dateRange.to + 'T23:59:59.999Z';
        if (activityDate > toNext) return false;
      }
    }

    // Tag filter
    if (filter.tags.size > 0) {
      const sessionTags = new Set(s.tags);
      let hasMatch = false;
      for (const tag of filter.tags) {
        if (sessionTags.has(tag)) { hasMatch = true; break; }
      }
      if (!hasMatch) return false;
    }

    // Unaffiliated filter — sessions not in any folder
    if (filter.unaffiliated && folderCardIds) {
      const cardId = `session:${s.tracking_id}`;
      if (folderCardIds.has(cardId)) return false;
    }

    // Search (matches name, role, tracking ID, and tags)
    if (filter.search) {
      const q = filter.search.toLowerCase();
      const name = getDisplayName(s).toLowerCase();
      const role = s.roles.join(' ').toLowerCase();
      const tid = s.tracking_id.toLowerCase();
      const tags = s.tags.join(' ').toLowerCase();
      if (!name.includes(q) && !role.includes(q) && !tid.includes(q) && !tags.includes(q)) return false;
    }

    return true;
  });
}

/** Count of active (non-default) filters */
function countActiveFilters(filter: FilterState): number {
  let count = 0;
  if (filter.status.size > 0) count++;
  if (filter.platform.size > 0) count++;
  if (filter.dateRange) count++;
  if (filter.tags.size > 0) count++;
  if (filter.unaffiliated) count++;
  if (filter.search) count++;
  return count;
}

/** Parse a duration string like "7d", "24h", "1h" into an ISO date string */
function parseDuration(input: string): string | null {
  const s = input.trim().toLowerCase();
  const match = s.match(/^(\d+)\s*(d|day|days|h|hr|hrs|hour|hours|m|min|mins|minute|minutes|w|wk|wks|week|weeks)$/);
  if (!match) return null;
  const num = parseInt(match[1], 10);
  const unit = match[2][0]; // first char: d, h, m, w
  const now = new Date();
  if (unit === 'd') now.setDate(now.getDate() - num);
  else if (unit === 'h') now.setHours(now.getHours() - num);
  else if (unit === 'm') now.setMinutes(now.getMinutes() - num);
  else if (unit === 'w') now.setDate(now.getDate() - num * 7);
  else return null;
  return now.toISOString();
}

function sortSessions(sessions: Session[], field: SortField, direction: SortDirection): Session[] {
  const sorted = [...sessions];
  sorted.sort((a, b) => {
    let cmp = 0;
    switch (field) {
      case 'activity':
        cmp = (a.last_activity || a.created_at).localeCompare(b.last_activity || b.created_at);
        break;
      case 'created':
        cmp = a.created_at.localeCompare(b.created_at);
        break;
      case 'name':
        cmp = getDisplayName(a).localeCompare(getDisplayName(b));
        break;
    }
    return direction === 'desc' ? -cmp : cmp;
  });
  return sorted;
}

function getCardDisplayName(card: SessionCard): string {
  if (card.display_name) {
    return card.display_name
      .replace(/^(claude|codex|gemini)_cli_/, '')
      .replace(/_\d{8}T\d{6}$/, '')
      .replace(/_/g, ' ');
  }
  return card.roles && card.roles.length > 0 ? card.roles[0] : card.tracking_id;
}

function sortSessionCards(cards: SessionCard[], field: SortField, direction: SortDirection): SessionCard[] {
  const sorted = [...cards];
  sorted.sort((a, b) => {
    let cmp = 0;
    switch (field) {
      case 'activity':
        cmp = (a.last_activity || a.created_at).localeCompare(b.last_activity || b.created_at);
        break;
      case 'created':
        cmp = a.created_at.localeCompare(b.created_at);
        break;
      case 'name':
        cmp = getCardDisplayName(a).localeCompare(getCardDisplayName(b));
        break;
    }
    return direction === 'desc' ? -cmp : cmp;
  });
  return sorted;
}

// ─── Context Menu ────────────────────────────────────────────────────────

function ContextMenu({ x, y, session, onClose, onRename, toastFn, folders }: {
  x: number;
  y: number;
  session: Session;
  onClose: () => void;
  onRename: () => void;
  toastFn: (message: string, type?: 'error' | 'info' | 'warning') => void;
  folders: Array<{ id: string; name: string }>;
}): JSX.Element {
  const menuRef = useRef<HTMLDivElement>(null);
  const [showFolderSubmenu, setShowFolderSubmenu] = useState(false);

  useEffect(() => {
    const handler = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) {
        onClose();
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [onClose]);

  return (
    <div ref={menuRef} className="context-menu" style={{ position: 'fixed', left: x, top: y, zIndex: 9999 }}>
      {/* ── Shared items (also in tab context menu) ── */}
      <button className="context-menu-item" onClick={() => {
        const displayName = session.display_name || session.tracking_id;
        window.uai.clipboard.write(displayName);
        toastFn('Copied name', 'info');
        onClose();
      }}>Copy Name</button>
      <button className="context-menu-item" onClick={() => {
        window.uai.clipboard.write(session.tracking_id);
        toastFn('Copied tracking ID', 'info');
        onClose();
      }}>Copy Tracking ID</button>
      <button className="context-menu-item" onClick={() => {
        window.uai.clipboard.write(`uai://session/${session.tracking_id}`);
        toastFn('Copied URI', 'info');
        onClose();
      }}>Copy URI</button>
      <div className="context-menu-separator" />
      <button className="context-menu-item" onClick={() => {
        executeCommand('workspace.tabs.open', {
          type: 'session',
          targetId: session.tracking_id,
          label: `Transcript — ${session.display_name || session.tracking_id}`,
        });
        onClose();
      }}>View Transcript</button>
      {session.process_status === 'running' && (
        <>
          <button className="context-menu-item" onClick={() => {
            executeCommand('session.stop', { trackingId: session.tracking_id }, {
              onFailure: 'toast', toastFn,
            });
            onClose();
          }}>Stop</button>
          <button className="context-menu-item danger" onClick={() => {
            executeCommand('session.stop', { trackingId: session.tracking_id, force: true }, {
              onFailure: 'toast', toastFn,
            });
            onClose();
          }}>Force Stop</button>
        </>
      )}
      {session.process_status !== 'running' && (
        <button className="context-menu-item" onClick={() => {
          executeCommand('session.resume', { trackingId: session.tracking_id }, {
            onFailure: 'toast', toastFn,
          });
          onClose();
        }}>Resume</button>
      )}

      {/* ── Navigator-specific entity management items ── */}
      <div className="context-menu-separator" />
      <button className="context-menu-item" onClick={() => {
        onRename();
        onClose();
      }}>Rename</button>
      {session.cli_session_id && (
        <button className="context-menu-item" onClick={() => {
          window.uai.clipboard.write(session.cli_session_id!);
          toastFn('Copied CLI UUID', 'info');
          onClose();
        }}>Copy CLI UUID</button>
      )}
      <button className="context-menu-item" onClick={() => {
        executeCommand('session.update', {
          trackingId: session.tracking_id,
          patch: { pinned: !session.pinned },
        }, { onFailure: 'toast', toastFn });
        onClose();
      }}>{session.pinned ? 'Unpin' : 'Pin'}</button>
      {folders.length > 0 && (
        <div
          className="context-menu-item submenu-trigger"
          onMouseEnter={() => setShowFolderSubmenu(true)}
          onMouseLeave={() => setShowFolderSubmenu(false)}
        >
          Move to Folder {'\u25B6'}
          {showFolderSubmenu && (
            <div className="context-submenu">
              {folders.map(f => (
                <button
                  key={f.id}
                  className="context-menu-item"
                  onClick={() => {
                    executeCommand('folder.moveCard', {
                      cardId: `session:${session.tracking_id}`,
                      targetFolderId: f.id,
                    }, { onFailure: 'toast', toastFn });
                    onClose();
                  }}
                >{f.name}</button>
              ))}
            </div>
          )}
        </div>
      )}
      {!session.archived && (
        <button className="context-menu-item danger" onClick={() => {
          executeCommand('session.archive', { trackingId: session.tracking_id }, {
            onFailure: 'toast', toastFn,
          });
          onClose();
        }}>Archive</button>
      )}
      {session.process_status !== 'running' && (
        <button className="context-menu-item danger" onClick={() => {
          if (!confirm(`Delete session "${session.display_name || session.tracking_id}"? This will archive and remove the session.`)) return;
          if (!session.archived) {
            executeCommand('session.archive', { trackingId: session.tracking_id }, {
              onFailure: 'toast', toastFn,
            });
          }
          toastFn('Session archived (full delete not yet implemented)', 'info');
          onClose();
        }}>Delete</button>
      )}
    </div>
  );
}

// ─── Session Card (removed — now rendered via CardListView + CardRenderer) ──

// ─── New Custom Session Dialog ──────────────────────────────────────────

const WEBAI_URLS: Record<string, string> = {
  webai_grok: 'https://grok.com',
  webai_perplexity: 'https://perplexity.ai',
};

const ALL_PLATFORM_LABELS: Record<string, string> = {
  ...PLATFORM_LABELS,
  webai_grok: 'Grok',
  webai_perplexity: 'Perplexity',
  local_llm: 'Local LLM',
};

function NewCustomSessionDialog({ x, y, onClose, toastFn, aiRoot }: {
  x: number;
  y: number;
  onClose: () => void;
  toastFn: (message: string, type?: 'error' | 'info' | 'warning') => void;
  aiRoot: string | null;
}): JSX.Element {
  const dialogRef = useRef<HTMLDivElement>(null);
  const [platform, setPlatform] = useState('claude_cli');
  const [displayName, setDisplayName] = useState('');
  const [projectDir, setProjectDir] = useState('');
  const [tags, setTags] = useState('');
  const [notes, setNotes] = useState('');
  const [contextExpanded, setContextExpanded] = useState(false);
  const [selectedContext, setSelectedContext] = useState<Array<{ type: string; name: string; filePath?: string }>>([]);

  // Draggable position
  const [pos, setPos] = useState({ x, y });
  const dragRef = useRef<{ startX: number; startY: number; origX: number; origY: number } | null>(null);

  const isWebAi = platform.startsWith('webai_');

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', handler);
    return () => document.removeEventListener('keydown', handler);
  }, [onClose]);

  // Drag handlers for moveable dialog
  const handleDragStart = useCallback((e: React.MouseEvent) => {
    if (!(e.target as HTMLElement).closest('.nav-custom-session-header')) return;
    dragRef.current = { startX: e.clientX, startY: e.clientY, origX: pos.x, origY: pos.y };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      setPos({
        x: dragRef.current.origX + (ev.clientX - dragRef.current.startX),
        y: dragRef.current.origY + (ev.clientY - dragRef.current.startY),
      });
    };
    const onUp = () => {
      dragRef.current = null;
      document.removeEventListener('mousemove', onMove);
      document.removeEventListener('mouseup', onUp);
    };
    document.addEventListener('mousemove', onMove);
    document.addEventListener('mouseup', onUp);
  }, [pos]);

  const handleSubmit = async () => {
    const label = displayName.trim() || `New ${ALL_PLATFORM_LABELS[platform] || 'AI'} Session`;

    // WebAI platforms open a webai tab instead of creating a session
    if (isWebAi) {
      const url = WEBAI_URLS[platform];
      if (url) {
        executeCommand('workspace.tabs.open', {
          type: 'webai',
          targetId: url,
          label,
        });
      }
      onClose();
      return;
    }

    // CLI / Local LLM session creation
    const result = await executeCommand('session.create', {
      platform,
      displayName: label,
      roles: ['assistant'],
      projectDir: projectDir.trim() || defaultDir,
      contextItems: selectedContext.length > 0 ? selectedContext : undefined,
      notes: notes.trim() || undefined,
    }, { onFailure: 'toast', toastFn });

    const data = result?.data as { trackingId?: string } | undefined;
    if (result?.ok && data?.trackingId) {
      const trackingId = data.trackingId;

      // Auto-open the new session tab
      executeCommand('workspace.tabs.open', {
        type: 'session',
        targetId: trackingId,
        label,
      });

      // Add tags
      const tagList = tags.trim()
        ? tags.split(',').map(t => t.trim()).filter(Boolean)
        : [];
      for (const tag of tagList) {
        executeCommand('tag.add', {
          cardId: `session:${trackingId}`,
          tag,
        }, { onFailure: 'toast', toastFn });
      }

      // Notes are now persisted to the session store via the launcher's
      // --notes param (passed through session.create above), so the session's
      // Notes state field is the single source of truth — no sessionPrefs copy.
    }

    onClose();
  };

  const defaultDir = '$AI_ROOT';

  return createPortal(
    <div
      ref={dialogRef}
      className="nav-custom-session-dialog"
      style={{ position: 'fixed', left: pos.x, top: pos.y, zIndex: 9999 }}
      onMouseDown={handleDragStart}
    >
      <div className="nav-custom-session-scrollable">
        <div className="nav-custom-session-header" style={{ cursor: 'grab' }}>New Custom Session</div>

        {/* Platform */}
        <div className="nav-custom-session-field">
          <label className="nav-custom-session-label">Platform</label>
          <select
            className="nav-custom-session-select"
            value={platform}
            onChange={(e) => setPlatform(e.target.value)}
          >
            <option value="claude_cli">Claude</option>
            <option value="codex_cli">Codex</option>
            <option value="gemini_cli">Gemini</option>
            <option disabled>{'\u2500\u2500 Web AI \u2500\u2500'}</option>
            <option value="webai_grok">Grok</option>
            <option value="webai_perplexity">Perplexity</option>
            <option disabled>{'\u2500\u2500 Local LLM \u2500\u2500'}</option>
            <option value="local_llm">Local LLM</option>
          </select>
        </div>

        {/* Display Name */}
        <div className="nav-custom-session-field">
          <label className="nav-custom-session-label">Display Name</label>
          <input
            className="nav-custom-session-input"
            type="text"
            value={displayName}
            onChange={(e) => setDisplayName(e.target.value)}
            placeholder="Optional"
            autoFocus
          />
        </div>

        {/* Project Directory — hide for webai */}
        {!isWebAi && (
          <div className="nav-custom-session-field">
            <label className="nav-custom-session-label">Project Directory</label>
            <div style={{ display: 'flex', gap: '4px' }}>
              <input
                className="nav-custom-session-input"
                type="text"
                value={projectDir}
                onChange={(e) => setProjectDir(e.target.value)}
                placeholder={defaultDir}
                style={{ flex: 1 }}
              />
              <button
                className="nav-custom-session-cancel"
                style={{ padding: '4px 8px', fontSize: '11px', whiteSpace: 'nowrap' }}
                onClick={async () => {
                  const dir = await (window.uai as any).dialog?.showOpenDirectory?.(defaultDir);
                  if (dir) setProjectDir(dir);
                }}
                title="Browse..."
              >{'\uD83D\uDCC2'}</button>
            </div>
          </div>
        )}

        {/* Tags */}
        {!isWebAi && (
          <div className="nav-custom-session-field">
            <label className="nav-custom-session-label">Tags</label>
            <input
              className="nav-custom-session-input"
              type="text"
              value={tags}
              onChange={(e) => setTags(e.target.value)}
              placeholder="dev, research, urgent, ..."
            />
          </div>
        )}

        {/* Notes */}
        {!isWebAi && (
          <div className="nav-custom-session-field">
            <label className="nav-custom-session-label">Notes</label>
            <textarea
              className="nav-custom-session-input nav-custom-session-textarea"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder="Initial notes for this session..."
              rows={2}
            />
          </div>
        )}

        {/* Add Context — reuses ContextTab pattern */}
        {!isWebAi && (
          <div className="nav-custom-session-context-section">
            <button
              className="nav-custom-session-context-toggle"
              onClick={() => setContextExpanded(v => !v)}
            >
              Add Context {contextExpanded ? '\u25BE' : '\u25B8'}
            </button>
            {contextExpanded && (
              <div className="nav-custom-session-context-body" style={{ maxHeight: '300px', overflowY: 'auto' }}>
                <ContextTab sessionTrackingId={null} discoveryMode={true} onSelectionChange={setSelectedContext} />
              </div>
            )}
          </div>
        )}

        <div className="nav-custom-session-actions">
          <button className="nav-custom-session-cancel" onClick={onClose}>Cancel</button>
          <button className="nav-custom-session-submit" onClick={handleSubmit}>
            {isWebAi ? 'Open' : 'Create'}
          </button>
        </div>
      </div>
    </div>,
    document.body
  );
}

// ─── Filter Toolbar ──────────────────────────────────────────────────────

function FilterToolbar({ filter, onFilterChange, sortField, sortDirection, onSortChange, availableTags }: {
  filter: FilterState;
  onFilterChange: (f: FilterState) => void;
  sortField: SortField;
  sortDirection: SortDirection;
  onSortChange: (field: SortField, dir: SortDirection) => void;
  availableTags: string[];
}): JSX.Element {
  const [showDatePicker, setShowDatePicker] = useState(false);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');
  const datePickerRef = useRef<HTMLDivElement>(null);
  const dateBtnRef = useRef<HTMLButtonElement>(null);

  // Close date picker on outside click
  useEffect(() => {
    if (!showDatePicker) return;
    const handler = (e: MouseEvent) => {
      if (
        datePickerRef.current && !datePickerRef.current.contains(e.target as Node) &&
        dateBtnRef.current && !dateBtnRef.current.contains(e.target as Node)
      ) {
        setShowDatePicker(false);
      }
    };
    document.addEventListener('mousedown', handler);
    return () => document.removeEventListener('mousedown', handler);
  }, [showDatePicker]);

  const toggleFilter = (key: 'status' | 'platform', value: string) => {
    const next = new Set(filter[key]);
    if (next.has(value)) next.delete(value);
    else next.add(value);
    onFilterChange({ ...filter, [key]: next });
  };

  const toggleTag = (tag: string) => {
    const next = new Set(filter.tags);
    if (next.has(tag)) next.delete(tag);
    else next.add(tag);
    onFilterChange({ ...filter, tags: next });
  };

  const setDateRange = (from: string, to: string) => {
    if (!from && !to) {
      onFilterChange({ ...filter, dateRange: null });
    } else {
      onFilterChange({ ...filter, dateRange: { from, to } });
    }
  };

  const applyQuickDate = (duration: string) => {
    const from = parseDuration(duration);
    if (from) {
      setDateRange(from, '');
      setShowDatePicker(false);
    }
  };

  const clearAllFilters = () => {
    onFilterChange({
      status: new Set(),
      platform: new Set(),
      search: '',
      dateRange: null,
      tags: new Set(),
      unaffiliated: false,
    });
  };

  const cycleSortField = () => {
    const fields: SortField[] = ['activity', 'created', 'name'];
    const idx = fields.indexOf(sortField);
    onSortChange(fields[(idx + 1) % fields.length], sortDirection);
  };

  const toggleSortDir = () => {
    onSortChange(sortField, sortDirection === 'desc' ? 'asc' : 'desc');
  };

  const activeFilterCount = countActiveFilters(filter);

  return (
    <div className="nav-filter-toolbar">
      {/* Header with filter count and clear button */}
      {activeFilterCount > 0 && (
        <div className="nav-filter-header">
          <span className="nav-filter-badge">{activeFilterCount} filter{activeFilterCount !== 1 ? 's' : ''} active</span>
          <button className="nav-filter-clear-btn" onClick={clearAllFilters} title="Clear all filters">Clear all</button>
        </div>
      )}

      {/* Status pills */}
      <div className="nav-filter-row">
        <button
          className={`filter-pill${filter.status.has('running') ? ' active' : ''}`}
          onClick={() => toggleFilter('status', 'running')}
        >Active</button>
        <button
          className={`filter-pill${filter.status.has('stopped') ? ' active' : ''}`}
          onClick={() => toggleFilter('status', 'stopped')}
        >Stopped</button>
        <button
          className={`filter-pill${filter.status.has('archived') ? ' active' : ''}`}
          onClick={() => toggleFilter('status', 'archived')}
        >Archived</button>
      </div>

      {/* Platform pills */}
      <div className="nav-filter-row">
        <button
          className={`filter-pill platform-claude${filter.platform.has('claude_cli') ? ' active' : ''}`}
          onClick={() => toggleFilter('platform', 'claude_cli')}
        >Claude</button>
        <button
          className={`filter-pill platform-codex${filter.platform.has('codex_cli') ? ' active' : ''}`}
          onClick={() => toggleFilter('platform', 'codex_cli')}
        >Codex</button>
        <button
          className={`filter-pill platform-gemini${filter.platform.has('gemini_cli') ? ' active' : ''}`}
          onClick={() => toggleFilter('platform', 'gemini_cli')}
        >Gemini</button>
      </div>

      {/* Date range + Unaffiliated row */}
      <div className="nav-filter-row">
        <button
          ref={dateBtnRef}
          className={`filter-pill filter-pill-date${filter.dateRange ? ' active' : ''}`}
          onClick={() => {
            if (!showDatePicker) {
              setDateFrom(filter.dateRange?.from ?? '');
              setDateTo(filter.dateRange?.to ?? '');
            }
            setShowDatePicker(prev => !prev);
          }}
          title={filter.dateRange ? `Date: ${filter.dateRange.from || '...'} to ${filter.dateRange.to || 'now'}` : 'Filter by date range'}
        >{filter.dateRange ? 'Date \u2713' : 'Date'}</button>

        <button
          className={`filter-pill${filter.unaffiliated ? ' active' : ''}`}
          onClick={() => onFilterChange({ ...filter, unaffiliated: !filter.unaffiliated })}
          title="Show only sessions not in any folder"
        >Unaffiliated</button>

        {showDatePicker && createPortal(
          <div
            ref={datePickerRef}
            className="nav-date-popover"
            style={(() => {
              const rect = dateBtnRef.current?.getBoundingClientRect();
              if (!rect) return {};
              return { position: 'fixed' as const, top: rect.bottom + 4, left: rect.left, zIndex: 9999 };
            })()}
          >
            <div className="nav-date-section">
              <span className="nav-date-label">Quick</span>
              <div className="nav-date-quick-picks">
                {[
                  { label: '1h', val: '1h' },
                  { label: '6h', val: '6h' },
                  { label: '24h', val: '24h' },
                  { label: '7d', val: '7d' },
                  { label: '30d', val: '30d' },
                ].map(p => (
                  <button key={p.val} className="nav-date-quick-btn" onClick={() => applyQuickDate(p.val)}>{p.label}</button>
                ))}
              </div>
            </div>
            <div className="nav-date-section">
              <span className="nav-date-label">Custom Range</span>
              <div className="nav-date-inputs">
                <label className="nav-date-input-label">
                  From
                  <input type="date" className="nav-date-input" value={dateFrom.slice(0, 10)} onChange={(e) => setDateFrom(e.target.value)} />
                </label>
                <label className="nav-date-input-label">
                  To
                  <input type="date" className="nav-date-input" value={dateTo.slice(0, 10)} onChange={(e) => setDateTo(e.target.value)} />
                </label>
              </div>
            </div>
            <div className="nav-date-actions">
              <button className="nav-date-apply-btn" onClick={() => { setDateRange(dateFrom, dateTo); setShowDatePicker(false); }}>Apply</button>
              <button className="nav-date-clear-btn" onClick={() => { setDateFrom(''); setDateTo(''); setDateRange('', ''); setShowDatePicker(false); }}>Clear</button>
            </div>
          </div>,
          document.body
        )}
      </div>

      {/* Tag pills */}
      {availableTags.length > 0 && (
        <div className="nav-filter-row nav-filter-row-tags">
          <span className="nav-filter-row-label">Tags</span>
          {availableTags.map(tag => (
            <button
              key={tag}
              className={`filter-pill filter-pill-tag${filter.tags.has(tag) ? ' active' : ''}`}
              onClick={() => toggleTag(tag)}
              title={`Filter by tag: ${tag}`}
            >{tag}</button>
          ))}
        </div>
      )}

      {/* Search */}
      <div className="nav-filter-row">
        <input
          className="nav-search-input"
          type="text"
          placeholder="Search sessions..."
          value={filter.search}
          onChange={(e) => onFilterChange({ ...filter, search: e.target.value })}
        />
      </div>

      {/* Sort controls */}
      <div className="nav-sort-row">
        <button className="sort-btn" onClick={cycleSortField} title="Sort field">
          {sortField === 'activity' ? '\u23F1 Activity' : sortField === 'created' ? '\uD83D\uDCC5 Created' : '\uD83D\uDD24 Name'}
        </button>
        <button className="sort-btn" onClick={toggleSortDir} title="Sort direction">
          {sortDirection === 'desc' ? '\u2193' : '\u2191'}
        </button>
      </div>
    </div>
  );
}

// ─── Messages nav badge ──────────────────────────────────────────────────

// The primary user's comms inbox id (matches UserMessagesPane.PRIMARY_USER_ID).
const USER_MESSAGES_ID = 'piano_man';

/** Unread-count badge for the Messages tool button (the user's comms inbox). */
function MessagesNavBadge(): JSX.Element | null {
  const [, forceUpdate] = useState(0);
  useEffect(() => onCommsCountChange(() => forceUpdate(n => n + 1)), []);
  useEffect(() => { scanCommsCounts([USER_MESSAGES_ID]); }, []);
  const unread = getCommsCount(USER_MESSAGES_ID)?.unread || 0;
  if (unread <= 0) return null;
  return <span className="nav-tool-badge">{unread > 99 ? '99+' : unread}</span>;
}

// ─── Navigator ───────────────────────────────────────────────────────────

interface NavigatorProps {
  onSelectSession: (trackingId: string, opts?: { newTab?: boolean }) => void;
  activeSessionId: string | null;
}

export default function Navigator({ onSelectSession, activeSessionId }: NavigatorProps): JSX.Element {
  const { sessions, initialized, refresh, aiRoot } = useSessionStore();
  const { appState, updateAppState } = useAppStateStore();
  const cardStore = useCardStore();
  const folderStore = useFolderStore();
  const { toggleSelect, context, clearSelection } = useActionContext();
  const { showToast } = useToast();

  const [activeTab, setActiveTab] = useState<NavigatorTab>('sessions');
  // Feature-gated Navigator tabs — hidden until the surface is ready. Filtered
  // out of the tab bar; if the active tab is one that's hidden, fall back to
  // Sessions so nothing strands on a now-invisible tab.
  const showProjectsTeams = useFeature('nav.projectsTeams');
  const showWebUis = useFeature('nav.webUis');
  const showGames = useFeature('nav.games');
  const tabEnabled = useCallback((tab: NavigatorTab): boolean => {
    if (tab === 'projects') return showProjectsTeams;
    if (tab === 'webuis') return showWebUis;
    if (tab === 'apps') return showGames;
    return true;
  }, [showProjectsTeams, showWebUis, showGames]);
  const [filter, setFilter] = useState<FilterState>(DEFAULT_FILTER);
  const [sortField, setSortField] = useState<SortField>('activity');
  const [sortDirection, setSortDirection] = useState<SortDirection>('desc');
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; sessionId: string } | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [activeSectionCollapsed, setActiveSectionCollapsed] = useState(false);
  const [stoppedSectionCollapsed, setStoppedSectionCollapsed] = useState(false);
  const [folderContextMenu, setFolderContextMenu] = useState<{ x: number; y: number; folderId: string } | null>(null);
  const [currentFolderId, setCurrentFolderId] = useState<string>('all_sessions');
  const [showNewMenu, setShowNewMenu] = useState(false);
  const newBtnRef = useRef<HTMLButtonElement>(null);
  const [customSessionDialog, setCustomSessionDialog] = useState<{ x: number; y: number } | null>(null);

  // Dismiss new session menu on click-away
  useEffect(() => {
    if (!showNewMenu) return;
    const dismiss = () => setShowNewMenu(false);
    window.addEventListener('click', dismiss);
    return () => window.removeEventListener('click', dismiss);
  }, [showNewMenu]);

  // Sync navigator tab from persisted app state after bootstrap
  useEffect(() => {
    if (appState.navigatorTab) {
      setActiveTab(appState.navigatorTab as NavigatorTab);
    }
  }, [appState.navigatorTab]);

  // If the active tab is (or becomes) feature-hidden, fall back to Sessions.
  useEffect(() => {
    if (!tabEnabled(activeTab)) setActiveTab('sessions');
  }, [activeTab, tabEnabled]);

  // Persist navigator tab
  const handleTabChange = useCallback((tab: NavigatorTab) => {
    setActiveTab(tab);
    updateAppState({ navigatorTab: tab });
  }, [updateAppState]);

  // Sort change
  const handleSortChange = useCallback((field: SortField, dir: SortDirection) => {
    setSortField(field);
    setSortDirection(dir);
  }, []);

  // Context menu
  const handleContextMenu = useCallback((e: React.MouseEvent, sessionId: string) => {
    e.preventDefault();
    if (contextMenu) { setContextMenu(null); return; }
    // Clamp position to keep menu within viewport
    const menuWidth = 200;
    const menuHeight = 300;
    const x = Math.min(e.clientX, window.innerWidth - menuWidth);
    const y = Math.min(e.clientY, window.innerHeight - menuHeight);
    setContextMenu({ x, y, sessionId });
  }, []);

  // Rename
  const startRename = useCallback((session: Session) => {
    setRenamingId(session.tracking_id);
    setRenameValue(session.display_name || '');
  }, []);

  const submitRename = useCallback(async () => {
    if (!renamingId || !renameValue.trim()) {
      setRenamingId(null);
      return;
    }
    await executeCommand('session.update', {
      trackingId: renamingId, patch: { display_name: renameValue.trim() },
    }, { onFailure: 'toast', toastFn: showToast });
    setRenamingId(null);
  }, [renamingId, renameValue, showToast]);

  const cancelRename = useCallback(() => {
    setRenamingId(null);
  }, []);

  // Create session
  const createSession = useCallback(async (platform: string) => {
    const label = `New ${PLATFORM_LABELS[platform] || 'AI'} Session`;
    const result = await executeCommand('session.create', {
      platform,
      displayName: label,
      roles: ['assistant'],
      projectDir: aiRoot || undefined,
    }, { onFailure: 'toast', toastFn: showToast });
    // Auto-open the new session in a tab
    const data = result?.data as { trackingId?: string } | undefined;
    if (result?.ok && data?.trackingId) {
      executeCommand('workspace.tabs.open', {
        type: 'session',
        targetId: data.trackingId,
        label,
      });
    }
  }, [aiRoot, showToast]);

  // Card-based handlers for CardListView
  // Single click = preview in current tab. Cmd+click = new tab.
  const handleCardClick = useCallback((card: AnyCard, e?: React.MouseEvent) => {
    clearSelection();
    if (isSessionCard(card)) {
      const newTab = e?.metaKey || e?.ctrlKey || false;
      onSelectSession(card.tracking_id, { newTab });
    }
  }, [clearSelection, onSelectSession]);

  // Double-click = always open in new tab
  const handleCardDoubleClick = useCallback((card: AnyCard) => {
    if (isSessionCard(card)) {
      onSelectSession(card.tracking_id, { newTab: true });
    }
  }, [onSelectSession]);

  const handleCardSelect = useCallback((card: AnyCard) => {
    toggleSelect(card.entity_id);
  }, [toggleSelect]);

  const handleCardContextMenu = useCallback((card: AnyCard, e: React.MouseEvent) => {
    e.preventDefault();
    if (isSessionCard(card)) {
      // Clamp position to keep menu within viewport
      const menuWidth = 200;
      const menuHeight = 300;
      const x = Math.min(e.clientX, window.innerWidth - menuWidth);
      const y = Math.min(e.clientY, window.innerHeight - menuHeight);
      setContextMenu({ x, y, sessionId: card.tracking_id });
    }
  }, []);

  // Folder navigation
  const handleFolderSelect = useCallback((folderId: string) => {
    setCurrentFolderId(folderId);
    // Open folder as a card grid in the center panel
    const container = cardStore.getContainer(folderId);
    const label = container?.name || folderId;
    executeCommand('workspace.tabs.open', {
      type: 'folder',
      targetId: folderId,
      label,
    });
  }, [cardStore]);

  // Folder context menu
  const handleFolderContextMenu = useCallback((folderId: string, event: React.MouseEvent) => {
    event.preventDefault();
    // Clamp position to keep menu within viewport
    const menuWidth = 200;
    const menuHeight = 250;
    const x = Math.min(event.clientX, window.innerWidth - menuWidth);
    const y = Math.min(event.clientY, window.innerHeight - menuHeight);
    setFolderContextMenu({ x, y, folderId });
  }, []);

  // Get session cards, optionally filtered by current folder
  const sessionCards = useMemo((): SessionCard[] => {
    let cards = cardStore.sessions;
    if (currentFolderId && currentFolderId !== 'all_sessions') {
      const folderCards = cardStore.getCardsInContainer(currentFolderId, { descendants: true });
      const folderCardIds = new Set(folderCards.map(c => c.entity_id));
      cards = cards.filter(c => folderCardIds.has(c.entity_id));
    }
    return cards;
  }, [cardStore, currentFolderId]);

  // Collect all unique tags across sessions for the tag filter pills
  const availableTags = useMemo(() => {
    const tagSet = new Set<string>();
    for (const s of sessions) {
      for (const t of s.tags) tagSet.add(t);
    }
    return Array.from(tagSet).sort();
  }, [sessions]);

  // Compute card IDs that are in any folder (for unaffiliated filter)
  const allFolderCardIds = useMemo((): Set<string> => {
    const ids = new Set<string>();
    const folders = folderStore.storeData.folders;
    for (const fId of Object.keys(folders)) {
      if (fId === 'all_sessions') continue; // root doesn't count
      const folder = folders[fId];
      if (folder?.cards) {
        for (const cardId of folder.cards) ids.add(cardId as string);
      }
    }
    return ids;
  }, [folderStore.storeData]);

  // Filter + sort using session cards from card store
  const filtered = useMemo(() => filterSessions(sessions, filter, allFolderCardIds), [sessions, filter, allFolderCardIds]);
  const sorted = useMemo(() => sortSessions(filtered, sortField, sortDirection), [filtered, sortField, sortDirection]);

  // Convert filtered Session[] to SessionCard[] for CardListView
  const filteredTrackingIds = useMemo(() => new Set(filtered.map(s => s.tracking_id)), [filtered]);
  const filteredSessionCards = useMemo(() =>
    sortSessionCards(sessionCards.filter(c => filteredTrackingIds.has(c.tracking_id)), sortField, sortDirection),
    [sessionCards, filteredTrackingIds, sortField, sortDirection]
  );
  const activeCards = useMemo(() => filteredSessionCards.filter(s => s.process_status === 'running'), [filteredSessionCards]);
  const stoppedCards = useMemo(() => filteredSessionCards.filter(s => s.process_status !== 'running'), [filteredSessionCards]);

  const ctxSession = contextMenu ? sessions.find(s => s.tracking_id === contextMenu.sessionId) : null;
  const activeCardId = activeSessionId ? `session:${activeSessionId}` : undefined;

  const openGlobalSearch = useCallback(() => {
    executeCommand('workspace.tabs.open', {
      type: 'search',
      targetId: '_global',
      label: 'Search',
    });
  }, []);

  useViewport('session_navigator', () => ({
    visible: true,
    label: `${activeTab} tab`,
    state: {
      activeTab,
      visibleCards: filteredSessionCards.length,
      filterActive: countActiveFilters(filter) > 0,
      filterPlatforms: Array.from(filter.platform),
      filterStatuses: Array.from(filter.status),
      filterSearch: filter.search,
      filterDateRange: filter.dateRange,
      filterTags: Array.from(filter.tags),
      filterUnaffiliated: filter.unaffiliated,
      toolsPanelOpen,
    },
    children: ['session_context_menu'],
  }));

  // session_context_menu viewport is registered by SessionContextMenu component itself

  const [toolsPanelOpen, setToolsPanelOpen] = useState(true);

  if (!initialized) {
    return <div className="navigator"><div className="session-list-loading">Loading sessions...</div></div>;
  }

  return (
    <div className="navigator">

      {/* ── 1. Tools (collapsible section) ───────────────────────────── */}
      <div className="nav-section">
        <div className="nav-section-header" onClick={() => setToolsPanelOpen(v => !v)}>
          <span className="nav-section-chevron">{toolsPanelOpen ? '\u25BC' : '\u25B6'}</span>
          <span className="nav-section-title">Tools</span>
        </div>
        {toolsPanelOpen && (
          <div className="nav-tools-groups">
            <div className="nav-tools-group nav-tools-group-work">
              <div className="nav-tools-group-label">Work</div>
              <div className="nav-tools-grid">
                <button className="nav-tool-btn" onClick={() => executeCommand('workspace.tabs.open', { type: 'app', targetId: 'live-board', label: 'Live Board' })}>Live Board</button>
                <button className="nav-tool-btn" onClick={() => executeCommand('workspace.tabs.open', { type: 'app', targetId: 'notes-manager', label: 'Notes Mgr' })}>Notes Mgr</button>
                <button className="nav-tool-btn" onClick={() => executeCommand('workspace.tabs.open', { type: 'app', targetId: 'work-mgr', label: 'Work Mgr' })}>Work Mgr</button>
                <button className="nav-tool-btn" onClick={() => executeCommand('workspace.tabs.open', { type: 'app', targetId: 'scheduled-tasks', label: 'Scheduled Tasks' })}>Sched Tasks</button>
                <button className="nav-tool-btn" onClick={() => executeCommand('workspace.tabs.open', { type: 'app', targetId: 'git-file-view', label: 'Git Viewer' })}>Git Viewer</button>
              </div>
            </div>
            <div className="nav-tools-group nav-tools-group-comms">
              <div className="nav-tools-group-label">Comms</div>
              <div className="nav-tools-grid">
                <button className="nav-tool-btn" onClick={() => executeCommand('workspace.tabs.open', { type: 'app', targetId: 'user-messages', label: 'Messages' })}>Messages<MessagesNavBadge /></button>
                <button className="nav-tool-btn" onClick={() => executeCommand('workspace.tabs.open', { type: 'app', targetId: 'tab-manager', label: 'Tab Manager' })}>Tab Mgr</button>
              </div>
            </div>
            <div className="nav-tools-group nav-tools-group-session">
              <div className="nav-tools-group-label">Session</div>
              <div className="nav-tools-grid">
                <button className="nav-tool-btn" onClick={() => executeCommand('workspace.tabs.open', { type: 'app', targetId: 'context-manager', label: 'Context Manager' })}>Context Mgr</button>
                <button className="nav-tool-btn" onClick={() => executeCommand('workspace.tabs.open', { type: 'app', targetId: 'session-store-manager', label: 'Session Store' })}>Session Store</button>
                <button className="nav-tool-btn" onClick={() => executeCommand('workspace.tabs.open', { type: 'app', targetId: 'mcp-manager', label: 'MCP Manager' })}>MCP Mgr</button>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* ── 2. Navigator header (Search + [+ New]) — order:-1 floats it to the
           very top of the left panel, above the Tools section. ──────────── */}
      <div className="nav-header-bar" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 8px', order: -1 }}>
        <button className="nav-search-btn" onClick={openGlobalSearch} style={{ display: 'flex', alignItems: 'center', gap: '5px', padding: '5px 12px', background: 'var(--bg-card)', border: '1.5px solid var(--border-bright)', borderRadius: '5px', color: 'var(--text-sec)', fontSize: '13px', cursor: 'pointer', fontWeight: 600 }}>
          <span style={{ fontSize: '16px', lineHeight: 1 }}>{'\uD83D\uDD0D'}</span>Search
        </button>
        <div style={{ position: 'relative' }}>
          <button ref={newBtnRef} className="nav-new-btn" onClick={(e) => { e.stopPropagation(); setShowNewMenu(v => !v); }} style={{ padding: '5px 12px', background: 'var(--bg-card)', border: '1.5px solid var(--border-bright)', borderRadius: '5px', color: 'var(--text-sec)', fontSize: '13px', fontWeight: 600, cursor: 'pointer' }}>
            + New
          </button>
          {showNewMenu && createPortal((
            <div className="context-menu" style={{ position: 'fixed', top: (newBtnRef.current?.getBoundingClientRect().bottom ?? 80) + 2, left: newBtnRef.current?.getBoundingClientRect().left ?? 8, zIndex: 10000, minWidth: '200px' }}>
              {/* Section 1: Sessions */}
              <div className="context-menu-header" style={{ padding: '4px 10px', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Sessions</div>
              <button className="context-menu-item" style={{ borderLeft: '3px solid var(--accent-orange)' }} onClick={() => { createSession('claude_cli'); setShowNewMenu(false); }}><span style={{ marginRight: '6px', color: 'var(--accent-orange)' }}>{'\u2731'}</span>Claude CLI</button>
              <button className="context-menu-item" style={{ borderLeft: '3px solid var(--accent-purple)' }} onClick={() => { createSession('codex_cli'); setShowNewMenu(false); }}><span style={{ marginRight: '6px', color: 'var(--accent-purple)' }}>{'\u25CE'}</span>Codex CLI</button>
              <button className="context-menu-item" style={{ borderLeft: '3px solid var(--accent-cyan)' }} onClick={() => { createSession('gemini_cli'); setShowNewMenu(false); }}><span style={{ marginRight: '6px', color: 'var(--accent-cyan)' }}>{'\u2726'}</span>Gemini CLI</button>
              <div className="context-menu-separator" />
              {/* Section 2: Resume / Fork, Briefs, Custom */}
              <div className="context-menu-item submenu-trigger">
                Resume / Fork {'\u25B6'}
                <div className="context-submenu">
                  {sessions.filter(s => s.process_status !== 'running').slice(0, 15).map(s => (
                    <button key={`resume-${s.tracking_id}`} className="context-menu-item" onClick={() => {
                      executeCommand('session.resume', { trackingId: s.tracking_id }, { onFailure: 'toast', toastFn: showToast });
                      setShowNewMenu(false);
                    }}>{s.display_name || s.tracking_id}</button>
                  ))}
                  {sessions.filter(s => s.process_status !== 'running').length === 0 && (
                    <div className="context-menu-item" style={{ color: 'var(--text-muted)', cursor: 'default' }}>No stopped sessions</div>
                  )}
                </div>
              </div>
              <div className="context-menu-item submenu-trigger">
                Briefs {'\u25B6'}
                <div className="context-submenu">
                  {cardStore.briefs.slice(0, 15).map(b => (
                    <button key={b.entity_id} className="context-menu-item" onClick={() => {
                      executeCommand('workspace.tabs.open', { type: 'brief', targetId: b.entity_id.split(':')[1], label: b.display_name });
                      setShowNewMenu(false);
                    }}>{b.display_name}</button>
                  ))}
                  {cardStore.briefs.length === 0 && (
                    <div className="context-menu-item" style={{ color: 'var(--text-muted)', cursor: 'default' }}>No briefs</div>
                  )}
                </div>
              </div>
              <button className="context-menu-item" onClick={(e) => {
                const rect = (e.target as HTMLElement).getBoundingClientRect();
                setCustomSessionDialog({ x: rect.left, y: rect.bottom + 4 });
                setShowNewMenu(false);
              }}>Custom...</button>
              <div className="context-menu-separator" />
              {/* Section 3: Terminal */}
              <button className="context-menu-item" onClick={() => {
                executeCommand('workspace.tabs.open', { type: 'terminal', targetId: `terminal_${Date.now()}`, label: 'Terminal' });
                setShowNewMenu(false);
              }}><span style={{ marginRight: '6px', fontFamily: 'monospace' }}>{'>_'}</span>Terminal</button>
              <div className="context-menu-separator" />
              {/* Section 4: Web AI */}
              <div className="context-menu-header" style={{ padding: '4px 10px', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Web AI</div>
              <button className="context-menu-item" onClick={() => { executeCommand('workspace.tabs.open', { type: 'webai', targetId: 'https://grok.com', label: 'Grok' }); setShowNewMenu(false); }}><span style={{ marginRight: '6px', color: '#fff', fontWeight: 700 }}>X</span>Grok</button>
              <button className="context-menu-item" onClick={() => { executeCommand('workspace.tabs.open', { type: 'webai', targetId: 'https://chatgpt.com', label: 'ChatGPT' }); setShowNewMenu(false); }}><span style={{ marginRight: '6px', color: '#74aa9c', fontWeight: 700 }}>G</span>ChatGPT</button>
              <button className="context-menu-item" onClick={() => { executeCommand('workspace.tabs.open', { type: 'webai', targetId: 'https://gemini.google.com', label: 'Gemini Web' }); setShowNewMenu(false); }}><span style={{ marginRight: '6px', color: '#4285f4', fontWeight: 700 }}>G</span>Gemini Web</button>
              <button className="context-menu-item" onClick={() => { executeCommand('workspace.tabs.open', { type: 'webai', targetId: 'https://claude.ai', label: 'Claude Web' }); setShowNewMenu(false); }}><span style={{ marginRight: '6px', color: '#e07a4a', fontWeight: 700 }}>C</span>Claude Web</button>
              <button className="context-menu-item" onClick={() => { executeCommand('workspace.tabs.open', { type: 'webai', targetId: 'https://perplexity.ai', label: 'Perplexity' }); setShowNewMenu(false); }}><span style={{ marginRight: '6px', color: '#bb9af7', fontWeight: 700 }}>P</span>Perplexity</button>
              <button className="context-menu-item" onClick={() => {
                const url = prompt('URL:');
                if (url?.trim()) { executeCommand('workspace.tabs.open', { type: 'webai', targetId: url.trim(), label: new URL(url.trim()).hostname }); }
                setShowNewMenu(false);
              }}>Custom URL...</button>
              <div className="context-menu-separator" />
              {/* Section 5: Organize */}
              <div className="context-menu-header" style={{ padding: '4px 10px', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Organize</div>
              <button className="context-menu-item" onClick={() => {
                const name = prompt('Folder name:');
                if (name?.trim()) {
                  executeCommand('folder.create', { parentId: 'all_sessions', name: name.trim() }, { onFailure: 'toast', toastFn: showToast });
                }
                setShowNewMenu(false);
              }}>New Folder</button>
              <button className="context-menu-item" onClick={() => {
                executeCommand('workspace.tabs.open', { type: 'project', targetId: `new_project_${Date.now()}`, label: 'New Project' });
                setShowNewMenu(false);
              }}>New Project</button>
            </div>
          ), document.body)}
        </div>
        <button
          className="nav-settings-btn"
          title="Settings (⌘,)"
          onClick={() => window.dispatchEvent(new CustomEvent('uai:open-settings'))}
          style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '5px 10px', background: 'var(--bg-card)', border: '1.5px solid var(--border-bright)', borderRadius: '5px', color: 'var(--text-sec)', fontSize: '16px', lineHeight: 1, cursor: 'pointer' }}
        >
          {'⚙'}
        </button>
      </div>
      <div className="nav-tab-bar">
        {(['sessions', 'projects', 'webuis', 'terminals', 'apps', 'news'] as NavigatorTab[]).filter(tabEnabled).map(tab => (
          <button
            key={tab}
            className={`nav-tab${activeTab === tab ? ' active' : ''}`}
            onClick={() => handleTabChange(tab)}
          >
            {TAB_LABELS[tab] || tab}
          </button>
        ))}
      </div>

      {/* ── 3. Tab Content (scrollable) ────────────────────────────── */}
      <div className="nav-tab-content">

      {/* Sessions tab — All Sessions folder tree.
          The FolderTree's own "All Sessions" root row provides the label,
          the expand/collapse chevron, and click-to-show-contents — so no
          separate section header is needed (it would be a duplicate). */}
      {activeTab === 'sessions' && (
        <div className="nav-section nav-section-body">
          <FolderTree
            rootId="all_sessions"
            selectedFolderId={currentFolderId}
            onSelectFolder={handleFolderSelect}
            onContextMenu={handleFolderContextMenu}
          />
        </div>
      )}

      {/* Projects tab */}
      {activeTab === 'projects' && (
        <ProjectsTab />
      )}

      {/* Web UIs tab */}
      {activeTab === 'webuis' && (
        <div className="nav-apps-tab">
          {appState.tabs.filter(t => t.type === 'webai').length === 0 ? (
            <div className="session-list-empty" style={{ fontSize: '12px', padding: '16px' }}>No web UIs open.</div>
          ) : appState.tabs.filter(t => t.type === 'webai').map(tab => (
            <button key={tab.id} className={`nav-apps-item${appState.activeTabId === tab.id ? ' active' : ''}`}
              onClick={() => executeCommand('workspace.tabs.activate', { tabId: tab.id })} title={tab.targetId}>
              <span className="nav-apps-icon" style={{ color: 'var(--accent-purple)' }}>{'\uD83C\uDF10'}</span>
              <span className="nav-apps-label">{tab.label}</span>
            </button>
          ))}
        </div>
      )}

      {/* Terminals tab */}
      {activeTab === 'terminals' && (
        <div className="nav-apps-tab">
          {appState.tabs.filter(t => t.type === 'terminal').length === 0 ? (
            <div className="session-list-empty" style={{ fontSize: '12px', padding: '16px' }}>No terminals open.</div>
          ) : appState.tabs.filter(t => t.type === 'terminal').map(tab => (
            <button key={tab.id} className={`nav-apps-item${appState.activeTabId === tab.id ? ' active' : ''}`}
              onClick={() => executeCommand('workspace.tabs.activate', { tabId: tab.id })} title={tab.targetId}>
              <span className="nav-apps-icon" style={{ color: 'var(--accent-green)' }}>{'>_'}</span>
              <span className="nav-apps-label">{tab.label}</span>
            </button>
          ))}
        </div>
      )}

      {/* Apps/Games tab — excludes manager tools (those are in Tools panel) */}
      {activeTab === 'apps' && (
        <div className="nav-apps-tab">
          <div className="session-list-empty" style={{ fontSize: '12px', padding: '16px' }}>
            No apps or games running.
          </div>
        </div>
      )}

      {/* News & Reports tab */}
      {activeTab === 'news' && (
        <NewsTab />
      )}

      {/* ── 4. Recent Sessions (collapsible section) ───────────────── */}
      <RecentSessions
        sessions={sorted}
        activeSessionId={activeSessionId}
        onSelect={onSelectSession}
        openTabTargetIds={new Set(appState.tabs.filter(t => t.type === 'session').map(t => t.targetId))}
      />

      {/* Session Context Menu — shared component */}
      {contextMenu && ctxSession && (
        <SessionContextMenu
          x={contextMenu.x}
          y={contextMenu.y}
          session={ctxSession}
          onClose={() => setContextMenu(null)}
        />
      )}

      {/* Folder Context Menu */}
      {folderContextMenu && (
        <FolderContextMenu
          x={folderContextMenu.x}
          y={folderContextMenu.y}
          folderId={folderContextMenu.folderId}
          onClose={() => setFolderContextMenu(null)}
          toastFn={showToast}
        />
      )}

      {/* New Custom Session Dialog */}
      {customSessionDialog && (
        <NewCustomSessionDialog
          x={customSessionDialog.x}
          y={customSessionDialog.y}
          onClose={() => setCustomSessionDialog(null)}
          toastFn={showToast}
          aiRoot={aiRoot}
        />
      )}

      </div>{/* end nav-tab-content */}
    </div>
  );
}

// ─── Recent Sessions (persistent bottom section) ─────────────────────────

const PLATFORM_ICONS: Record<string, string> = {
  claude_cli: '\u25CF',   // filled circle
  codex_cli: '\u25A0',   // filled square
  gemini_cli: '\u25C6',  // filled diamond
};

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-cyan)',
};

function formatTimeAgo(dateStr: string): string {
  if (!dateStr) return '';
  try {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'now';
    if (mins < 60) return `${mins}m`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h`;
    return `${Math.floor(hours / 24)}d`;
  } catch { return ''; }
}

function RecentSessions({ sessions, activeSessionId, onSelect, openTabTargetIds }: {
  sessions: Session[];
  activeSessionId: string | null;
  onSelect: (trackingId: string, opts?: { newTab?: boolean }) => void;
  openTabTargetIds?: Set<string>;
}): JSX.Element {
  const [expanded, setExpanded] = useState(true);
  // Re-render when session activity, prompt-area, OR comms-count state changes
  const [, forceUpdate] = useState(0);
  useEffect(() => onActivityChange(() => forceUpdate(n => n + 1)), []);
  useEffect(() => onPromptAreaChange(() => forceUpdate(n => n + 1)), []);
  useEffect(() => onCommsCountChange(() => forceUpdate(n => n + 1)), []);
  // One bulk prompt-area scan when the list first mounts. (A periodic poll was
  // tried and removed — prompt-area-occupied should ride the consolidated
  // runtime-state source alongside activity_state, not a UI poll.)
  useEffect(() => { scanAllPromptAreas(); }, []);
  // Scan comms inbox counts for the (bounded) visible session set
  useEffect(() => {
    const ids = sessions.filter(s => !s.archived).map(s => s.tracking_id).slice(0, 40);
    if (ids.length > 0) scanCommsCounts(ids);
  }, [sessions]);

  const recent = useMemo(() => {
    const timeOf = (s: Session) =>
      getSessionActivity(s.tracking_id) || new Date(s.last_activity || s.created_at).getTime();
    const live = [...sessions].filter(s => !s.archived);
    // Live sessions rank ABOVE inactive ones, then by recency. Without this,
    // a genuinely-running but idle session (e.g. Meridian: live tmux, but no
    // turn in weeks) gets pushed out of the window by recently-touched-but-
    // now-dead test/probe sessions that still carry a fresh last_activity.
    // Hamilton (the standing coordinator) is pinned to the very top, always.
    // Matched by display name so it survives relaunches / tracking-id changes.
    const isPinned = (s: Session) => s.display_name === 'Hamilton';
    // A "breathing" session is actively working (responding / needs-input / …).
    // Those cluster together just below the pin so the live ones are always in
    // view, regardless of how stale their last_activity happens to be.
    const isBreathing = (s: Session) => isSessionBreathing(s.activity_state, s.process_status);
    live.sort((a, b) => {
      const aPin = isPinned(a) ? 1 : 0;
      const bPin = isPinned(b) ? 1 : 0;
      if (aPin !== bPin) return bPin - aPin;
      const aBreath = isBreathing(a) ? 1 : 0;
      const bBreath = isBreathing(b) ? 1 : 0;
      if (aBreath !== bBreath) return bBreath - aBreath;
      // Within the breathing tier, order by a STABLE key (tracking_id, which
      // encodes birth time) instead of activity time — otherwise working
      // sessions constantly swap places as their timestamps tick each turn.
      if (aBreath && bBreath) {
        return a.tracking_id < b.tracking_id ? -1 : a.tracking_id > b.tracking_id ? 1 : 0;
      }
      const aRun = a.process_status === 'running' ? 1 : 0;
      const bRun = b.process_status === 'running' ? 1 : 0;
      if (aRun !== bRun) return bRun - aRun;
      return timeOf(b) - timeOf(a);
    });
    // Never hide a live session: widen the window to hold every running
    // session, then fill up to 25 with the most-recent remaining.
    const runningCount = live.filter(s => s.process_status === 'running').length;
    return live.slice(0, Math.max(25, runningCount));
  }, [sessions, forceUpdate]); // forceUpdate dep ensures re-sort on activity

  if (recent.length === 0) return <></>;

  return (
    <div className="nav-section nav-section-recent">
      <div className="nav-section-header" onClick={() => setExpanded(v => !v)}>
        <span className="nav-section-chevron">{expanded ? '\u25BC' : '\u25B6'}</span>
        <span className="nav-section-title">Recent Sessions</span>
        <span className="nav-section-count">{recent.length}</span>
      </div>
      {expanded && <div className="nav-section-body nav-recent-sessions">
      <div className="nav-recent-legend" title="Session indicators">
        {SESSION_BADGE_LEGEND.map((b, i) => (
          <Fragment key={b.key}>
            {i > 0 && SESSION_BADGE_LEGEND[i - 1].side !== b.side && (
              <span className="nav-recent-legend-sep">{'·'}</span>
            )}
            <span className="nav-recent-legend-item" title={b.title}>
              <span className={`nav-badge ${b.cls}`}>{b.glyph}</span>
              <span className="nav-recent-legend-label">{b.label}</span>
            </span>
          </Fragment>
        ))}
      </div>
      {recent.map(s => {
        const isRunning = s.process_status === 'running';
        const hasTab = openTabTargetIds?.has(s.tracking_id) ?? false;
        const unreadReplies = getUnreadReplyCount(s.tracking_id, s.exchange_count, s.last_activity);
        const comms = getCommsCount(s.tracking_id);
        const roles = s.roles?.length > 0 ? s.roles.join(', ') : '';
        const block = promptBlockChip(s.prompt_block);
        const tooltip = [
          s.display_name || s.tracking_id,
          `${PLATFORM_LABELS[s.platform] || s.platform} · ${s.process_status}`,
          block ? block.tooltip : '',
          roles ? `Roles: ${roles}` : '',
          s.context_percent != null ? `Context: ${s.context_percent}% used` : '',
          s.exchange_count != null ? `Turns: ${s.exchange_count}` : '',
          unreadReplies > 0 ? `Unread replies: ${unreadReplies}` : '',
          comms && comms.total > 0 ? `Comms inbox: ${comms.total}${comms.unread > 0 ? ` (${comms.unread} unread)` : ''}` : '',
          s.tags?.length > 0 ? `Tags: ${s.tags.join(', ')}` : '',
          s.project_dir ? `Project: ${s.project_dir.replace('$HOME', '~')}` : '',
          `URI: uai://session/${s.tracking_id}`,
        ].filter(Boolean).join('\n');
        return (
          <div
            key={s.tracking_id}
            className={`nav-recent-item${s.tracking_id === activeSessionId ? ' active' : ''}${isRunning ? ' running' : ' stopped'}${hasTab ? ' has-tab' : ''}`}
            onClick={() => onSelect(s.tracking_id)}
            onDoubleClick={() => onSelect(s.tracking_id, { newTab: true })}
            title={tooltip}
          >
            <span
              className={`nav-recent-icon${isSessionBreathing(s.activity_state, s.process_status) ? ' session-breathing' : ''}`}
              style={{ color: PLATFORM_COLORS[s.platform] || 'var(--text-muted)' }}
            >
              {PLATFORM_ICONS[s.platform] || '\u25CB'}
            </span>
            <span className="nav-recent-badges-left">
              <SessionBadges
                group="left"
                trackingId={s.tracking_id}
                lastActivity={s.last_activity}
                exchangeCount={s.exchange_count}
                hasTab={hasTab}
              />
            </span>
            <span
              className={`nav-recent-name${isSessionBreathing(s.activity_state, s.process_status) ? ' session-breathing' : ''}`}
              // Name takes the platform color (claude=orange, codex=purple,
              // gemini=cyan). Once a per-session color is stored it will override
              // this; until then the platform color is the "if not specified" case.
              style={{ color: PLATFORM_COLORS[s.platform] || undefined }}
            >
              {(s.display_name || s.tracking_id).slice(0, 24)}
            </span>
            {block && <span className="nav-recent-block" title={block.tooltip}>{block.short}</span>}
            <span className="nav-recent-badges-right">
              <SessionBadges
                group="right"
                trackingId={s.tracking_id}
                lastActivity={s.last_activity}
                exchangeCount={s.exchange_count}
                hasTab={hasTab}
              />
            </span>
            <span className="nav-recent-meta">
              {/* Fixed-width right-aligned columns so the ctx% and the age line
                  up vertically down the list regardless of digit count. The ctx
                  column is always rendered (empty when unknown) so the age column
                  never shifts. */}
              <span
                className="nav-recent-ctx"
                // Same percentage coloring as the session cards' context chip
                // (.card-ctx): <50 blue, >=50 yellow, >=80 red.
                style={
                  s.context_percent != null
                    ? {
                        color:
                          s.context_percent >= 80
                            ? 'var(--accent-red)'
                            : s.context_percent >= 50
                              ? 'var(--accent-yellow)'
                              : 'var(--accent-blue)',
                      }
                    : undefined
                }
              >
                {s.context_percent != null ? `${s.context_percent}%` : ''}
              </span>
              <span className="nav-recent-ago">
                {(() => {
                  const appActivity = getSessionActivity(s.tracking_id);
                  if (appActivity) return formatTimeAgo(new Date(appActivity).toISOString());
                  return formatTimeAgo(s.last_activity || s.created_at);
                })()}
              </span>
            </span>
          </div>
        );
      })}
      </div>}
    </div>
  );
}
