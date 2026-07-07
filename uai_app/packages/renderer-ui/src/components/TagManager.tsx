/**
 * TagManager -- full-screen overlay for managing tags across all sessions.
 *
 * Features:
 *   - List all tags with session counts and colors
 *   - Expand a tag to see which sessions have it
 *   - Rename or delete tags (across all sessions)
 *   - Create new tags and assign them to sessions
 *   - Search/filter the tag list
 *   - Bulk add/remove tags from multiple sessions
 *
 * Ported from UCI TagManager, adapted to UAI's command bus pattern.
 * All mutations flow through executeCommand() -- no direct IPC calls.
 */

import { useState, useEffect, useCallback, useRef } from 'react';
import { useTagStore, useSessionStore } from '../stores';
import { executeCommand } from '../utils/execute-command';
import { useToast } from './Toast';
import type { Tag, Session } from '@uai/shared/types';

// ─── Types ──────────────────────────────────────────────────────────────

interface TagWithCount extends Tag {
  count: number;
  cardIds: string[];
}

interface TagManagerProps {
  isOpen: boolean;
  onClose: () => void;
}

// ─── Default Colors ─────────────────────────────────────────────────────

const TAG_COLORS = [
  '#ef4444', '#f97316', '#eab308', '#22c55e',
  '#06b6d4', '#3b82f6', '#8b5cf6', '#ec4899',
];

// ─── Component ──────────────────────────────────────────────────────────

export function TagManager({ isOpen, onClose }: TagManagerProps): JSX.Element | null {
  const { tags, refresh: refreshTags } = useTagStore();
  const { sessions } = useSessionStore();
  const { showToast } = useToast();

  const [search, setSearch] = useState('');
  const [expandedTag, setExpandedTag] = useState<string | null>(null);
  const [renamingTag, setRenamingTag] = useState<string | null>(null);
  const [renameValue, setRenameValue] = useState('');
  const [confirmDelete, setConfirmDelete] = useState<string | null>(null);
  const [creatingTag, setCreatingTag] = useState(false);
  const [newTagName, setNewTagName] = useState('');
  const [newTagColor, setNewTagColor] = useState(TAG_COLORS[0]);
  const [assignSessionIds, setAssignSessionIds] = useState<Set<string>>(new Set());
  const [assignSearch, setAssignSearch] = useState('');
  const [loading, setLoading] = useState(false);

  const renameInputRef = useRef<HTMLInputElement>(null);
  const newTagInputRef = useRef<HTMLInputElement>(null);
  const searchInputRef = useRef<HTMLInputElement>(null);

  // ── Build tag list with session counts ──────────────────────────────

  const tagsWithCounts: TagWithCount[] = tags.map(tag => {
    const matchingSessions = sessions.filter(s => s.tags.includes(tag.name));
    return {
      ...tag,
      count: matchingSessions.length,
      cardIds: matchingSessions.map(s => `session:${s.tracking_id}`),
    };
  });

  // ── Reset state on open ────────────────────────────────────────────

  useEffect(() => {
    if (isOpen) {
      setExpandedTag(null);
      setSearch('');
      setRenamingTag(null);
      setConfirmDelete(null);
      setCreatingTag(false);
      setNewTagName('');
      setNewTagColor(TAG_COLORS[0]);
      setAssignSessionIds(new Set());
      setAssignSearch('');
      refreshTags();
      setTimeout(() => searchInputRef.current?.focus(), 100);
    }
  }, [isOpen, refreshTags]);

  // ── Keyboard shortcut: Escape to close ─────────────────────────────

  useEffect(() => {
    if (!isOpen) return;
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') {
        if (renamingTag) {
          setRenamingTag(null);
          return;
        }
        if (creatingTag) {
          setCreatingTag(false);
          return;
        }
        if (confirmDelete) {
          setConfirmDelete(null);
          return;
        }
        onClose();
      }
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, onClose, renamingTag, creatingTag, confirmDelete]);

  // ── Expand tag to show sessions ────────────────────────────────────

  const handleExpand = useCallback((tagName: string) => {
    setExpandedTag(prev => prev === tagName ? null : tagName);
  }, []);

  // ── Sessions for the expanded tag ──────────────────────────────────

  const expandedSessions: Session[] = expandedTag
    ? sessions.filter(s => s.tags.includes(expandedTag))
    : [];

  // ── Rename tag across all sessions ─────────────────────────────────

  const handleRename = useCallback(async (oldTag: string) => {
    const newTag = renameValue.trim();
    if (!newTag || newTag === oldTag) {
      setRenamingTag(null);
      return;
    }
    setLoading(true);
    try {
      const result = await executeCommand('tag.rename', {
        oldTag,
        newTag,
      }, { onFailure: 'toast', toastFn: showToast });

      if (result.ok) {
        setRenamingTag(null);
        setRenameValue('');
        if (expandedTag === oldTag) setExpandedTag(newTag);
        showToast(`Tag renamed: "${oldTag}" -> "${newTag}"`, 'info');
      }
    } finally {
      setLoading(false);
    }
  }, [renameValue, expandedTag, showToast]);

  // ── Delete tag from all sessions ───────────────────────────────────

  const handleDelete = useCallback(async (tagName: string) => {
    setLoading(true);
    try {
      const result = await executeCommand('tag.delete', {
        tag: tagName,
      }, { onFailure: 'toast', toastFn: showToast });

      if (result.ok) {
        setConfirmDelete(null);
        if (expandedTag === tagName) {
          setExpandedTag(null);
        }
        showToast(`Tag deleted: "${tagName}"`, 'info');
      }
    } finally {
      setLoading(false);
    }
  }, [expandedTag, showToast]);

  // ── Remove tag from a single session ───────────────────────────────

  const handleRemoveFromSession = useCallback(async (tagName: string, trackingId: string) => {
    await executeCommand('tag.remove', {
      cardId: `session:${trackingId}`,
      tag: tagName,
    }, { onFailure: 'toast', toastFn: showToast });
  }, [showToast]);

  // ── Start creating a new tag ───────────────────────────────────────

  const handleStartCreate = useCallback(() => {
    setCreatingTag(true);
    setNewTagName('');
    setNewTagColor(TAG_COLORS[0]);
    setAssignSessionIds(new Set());
    setAssignSearch('');
    setTimeout(() => newTagInputRef.current?.focus(), 50);
  }, []);

  // ── Create tag and optionally assign to sessions ───────────────────

  const handleCreateTag = useCallback(async () => {
    const tagName = newTagName.trim();
    if (!tagName) return;

    setLoading(true);
    try {
      const ids = Array.from(assignSessionIds);
      if (ids.length > 0) {
        // Add tag to each selected session
        const results = await Promise.all(
          ids.map(trackingId =>
            executeCommand('tag.add', {
              cardId: `session:${trackingId}`,
              tag: tagName,
            }, { onFailure: 'log' })
          )
        );
        const successes = results.filter(r => r.ok).length;
        showToast(`Tag "${tagName}" added to ${successes} session${successes !== 1 ? 's' : ''}`, 'info');
      } else {
        showToast(`Tag "${tagName}" created (assign it to sessions to persist)`, 'info');
      }

      setCreatingTag(false);
      setNewTagName('');
      setAssignSessionIds(new Set());
    } finally {
      setLoading(false);
    }
  }, [newTagName, assignSessionIds, showToast]);

  // ── Filter logic ───────────────────────────────────────────────────

  const filteredTags = search
    ? tagsWithCounts.filter(t => t.name.toLowerCase().includes(search.toLowerCase()))
    : tagsWithCounts;

  const filteredAssignSessions = assignSearch
    ? sessions.filter(s =>
        (s.display_name || '').toLowerCase().includes(assignSearch.toLowerCase()) ||
        s.tracking_id.toLowerCase().includes(assignSearch.toLowerCase())
      )
    : sessions;

  if (!isOpen) return null;

  return (
    <div className="tag-mgr-overlay" onClick={onClose}>
      <div className="tag-mgr-dialog" onClick={(e) => e.stopPropagation()}>

        {/* ── Header ──────────────────────────────────────────── */}
        <div className="tag-mgr-header">
          <h3 className="tag-mgr-title">Tag Manager</h3>
          <div className="tag-mgr-header-actions">
            <button
              className="tag-mgr-new-btn"
              onClick={handleStartCreate}
              title="Create a new tag"
              disabled={loading}
            >
              + New Tag
            </button>
            <input
              ref={searchInputRef}
              type="text"
              className="tag-mgr-search"
              placeholder="Search tags..."
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </div>
          <button className="tag-mgr-close" onClick={onClose} title="Close">&times;</button>
        </div>

        {/* ── Body ────────────────────────────────────────────── */}
        <div className="tag-mgr-body">

          {/* Create tag form */}
          {creatingTag && (
            <div className="tag-mgr-create-form">
              <div className="tag-mgr-create-header">
                <input
                  ref={newTagInputRef}
                  type="text"
                  className="tag-mgr-create-input"
                  placeholder="Tag name..."
                  value={newTagName}
                  onChange={(e) => setNewTagName(e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') handleCreateTag();
                    if (e.key === 'Escape') setCreatingTag(false);
                  }}
                />
                <div className="tag-mgr-color-row">
                  {TAG_COLORS.map((c) => (
                    <button
                      key={c}
                      className={`tag-mgr-color-swatch${c === newTagColor ? ' selected' : ''}`}
                      style={{ backgroundColor: c }}
                      onClick={() => setNewTagColor(c)}
                      title={c}
                    />
                  ))}
                </div>
                <div className="tag-mgr-create-actions">
                  <button
                    className="tag-mgr-btn tag-mgr-btn--primary"
                    onClick={handleCreateTag}
                    disabled={!newTagName.trim() || loading}
                  >
                    Create
                  </button>
                  <button
                    className="tag-mgr-btn"
                    onClick={() => setCreatingTag(false)}
                  >
                    Cancel
                  </button>
                </div>
              </div>

              {/* Session assignment section */}
              {newTagName.trim() && (
                <div className="tag-mgr-assign-section">
                  <div className="tag-mgr-assign-label">
                    Assign to sessions ({assignSessionIds.size} selected):
                  </div>
                  <input
                    type="text"
                    className="tag-mgr-assign-search"
                    placeholder="Filter sessions..."
                    value={assignSearch}
                    onChange={(e) => setAssignSearch(e.target.value)}
                  />
                  <div className="tag-mgr-assign-list">
                    {filteredAssignSessions.map(s => (
                      <label key={s.tracking_id} className="tag-mgr-assign-item">
                        <input
                          type="checkbox"
                          checked={assignSessionIds.has(s.tracking_id)}
                          onChange={(e) => {
                            setAssignSessionIds(prev => {
                              const next = new Set(prev);
                              if (e.target.checked) next.add(s.tracking_id);
                              else next.delete(s.tracking_id);
                              return next;
                            });
                          }}
                        />
                        <span className="tag-mgr-assign-name">
                          {s.display_name || s.tracking_id}
                        </span>
                        {s.display_name && (
                          <span className="tag-mgr-assign-id">{s.tracking_id}</span>
                        )}
                      </label>
                    ))}
                    {filteredAssignSessions.length === 0 && (
                      <div className="tag-mgr-empty">No sessions found</div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Tag list */}
          {loading && tagsWithCounts.length === 0 ? (
            <div className="tag-mgr-empty">Loading tags...</div>
          ) : filteredTags.length === 0 ? (
            <div className="tag-mgr-empty">
              {search ? 'No tags match your search' : 'No tags defined yet'}
            </div>
          ) : (
            <div className="tag-mgr-list">
              {filteredTags.map(({ name, color, count }) => (
                <div
                  key={name}
                  className={`tag-mgr-tag${expandedTag === name ? ' expanded' : ''}`}
                >
                  {/* Tag row */}
                  <div className="tag-mgr-tag-row" onClick={() => handleExpand(name)}>
                    <span className="tag-mgr-tag-expand">
                      {expandedTag === name ? '\u25BE' : '\u25B8'}
                    </span>
                    <span
                      className="tag-mgr-tag-color"
                      style={{ backgroundColor: color || '#666' }}
                    />
                    {renamingTag === name ? (
                      <input
                        ref={renameInputRef}
                        type="text"
                        className="tag-mgr-rename-input"
                        value={renameValue}
                        onChange={(e) => setRenameValue(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === 'Enter') handleRename(name);
                          if (e.key === 'Escape') setRenamingTag(null);
                        }}
                        onBlur={() => handleRename(name)}
                        onClick={(e) => e.stopPropagation()}
                        autoFocus
                      />
                    ) : (
                      <span className="tag-mgr-tag-name">{name}</span>
                    )}
                    <span className="tag-mgr-tag-count">
                      {count} {count === 1 ? 'session' : 'sessions'}
                    </span>
                    <div className="tag-mgr-tag-actions" onClick={(e) => e.stopPropagation()}>
                      <button
                        className="tag-mgr-action-btn"
                        title="Rename tag"
                        onClick={() => {
                          setRenamingTag(name);
                          setRenameValue(name);
                          setTimeout(() => renameInputRef.current?.focus(), 50);
                        }}
                        disabled={loading}
                      >
                        {'\u270E'}
                      </button>
                      {confirmDelete === name ? (
                        <span className="tag-mgr-confirm-delete">
                          <span className="tag-mgr-confirm-label">Delete?</span>
                          <button
                            className="tag-mgr-action-btn danger"
                            title="Confirm delete"
                            onClick={() => handleDelete(name)}
                            disabled={loading}
                          >
                            Yes
                          </button>
                          <button
                            className="tag-mgr-action-btn"
                            title="Cancel"
                            onClick={() => setConfirmDelete(null)}
                          >
                            No
                          </button>
                        </span>
                      ) : (
                        <button
                          className="tag-mgr-action-btn danger"
                          title="Delete tag from all sessions"
                          onClick={() => setConfirmDelete(name)}
                          disabled={loading}
                        >
                          {'\u2715'}
                        </button>
                      )}
                    </div>
                  </div>

                  {/* Expanded sessions list */}
                  {expandedTag === name && (
                    <div className="tag-mgr-sessions">
                      {expandedSessions.length === 0 ? (
                        <div className="tag-mgr-empty">No sessions with this tag</div>
                      ) : (
                        expandedSessions.map(s => (
                          <div key={s.tracking_id} className="tag-mgr-session-row">
                            <span
                              className="tag-mgr-session-status"
                              style={{
                                backgroundColor: s.process_status === 'running'
                                  ? 'var(--accent-green)'
                                  : 'var(--text-muted)',
                              }}
                            />
                            <span className="tag-mgr-session-name">
                              {s.display_name || s.tracking_id}
                            </span>
                            <span className="tag-mgr-session-id">{s.tracking_id}</span>
                            <button
                              className="tag-mgr-action-btn danger"
                              title={`Remove "${name}" from this session`}
                              onClick={() => handleRemoveFromSession(name, s.tracking_id)}
                              disabled={loading}
                            >
                              {'\u2715'}
                            </button>
                          </div>
                        ))
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

export default TagManager;
