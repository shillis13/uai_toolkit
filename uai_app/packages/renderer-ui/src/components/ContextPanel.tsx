/**
 * ContextPanel — Right collapsible panel showing session details.
 *
 * Shows: tracking ID, CLI UUID, platform, status, roles, tags, notes.
 * Click-to-copy on identity fields. Notes section editable.
 * Resizable width. State persisted in AppStateStore.
 *
 * Registered as 'context_panel' in ComponentRegistry.
 */

import { useState, useRef, useCallback, useEffect } from 'react';
import { useViewport } from '../viewport';
import { useAppStateStore, useSessionStore } from '../stores';
import { useToast } from './Toast';
import { useCommandErrorHandler } from '../hooks/useCommandErrorHandler';
import { executeCommand } from '../utils/execute-command';
import { TagList } from './tags/TagBadge';
import { TagPicker } from './tags/TagPicker';
import { TagManager } from './TagManager';
import PromptsTab from './PromptsTab';
import MessagesTab from './MessagesTab';
import ContextTab from './ContextTab';
import { SessionStartsValue } from './SessionStarts';
import type { Session } from '@uai/shared/types';

type RightPanelTab = 'details' | 'context' | 'prompts' | 'messages';

// ─── Color maps ────────────────────────────────────────────────────────

const PROCESS_STATUS_COLORS: Record<string, string> = {
  running: 'var(--accent-green)',
  stopped: 'var(--text-muted)',
  exited: 'var(--text-muted)',
};

const IDENTITY_STATUS_COLORS: Record<string, string> = {
  draft: 'var(--text-muted)',
  pending: 'var(--accent-yellow)',
  confirmed: 'var(--accent-green)',
  failed: 'var(--accent-red)',
  orphaned: 'var(--accent-orange)',
};

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-cyan)',
};

// ─── Detail Row with copy ────────────────────────────────────────────────

function DetailRow({
  label,
  value,
  copyable,
  mono,
  isPath,
  customContent,
}: {
  label: string;
  value?: string | null;
  copyable?: boolean;
  mono?: boolean;
  isPath?: boolean;
  customContent?: React.ReactNode;
}): JSX.Element {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    if (!value) return;
    window.uai.clipboard.write(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [value]);

  const displayValue = isPath && value ? value.split('/').pop() || value : (value || '\u2014');

  return (
    <div className="ctx-detail-row">
      <span className="ctx-detail-label">{label}</span>
      {customContent || (
        <span
          className={`ctx-detail-value${copyable && value ? ' copyable' : ''}${mono ? ' mono' : ''}`}
          onClick={copyable && value ? handleCopy : undefined}
          title={copyable && value ? (isPath ? value : 'Click to copy') : undefined}
        >
          {copied ? '\u2713 Copied' : displayValue}
        </span>
      )}
    </div>
  );
}

// ─── Collapsible Section ──────────────────────────────────────────────────

function DetailSection({
  title,
  defaultOpen = true,
  children,
}: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}): JSX.Element {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="ctx-detail-section">
      <div className="ctx-detail-section-header" onClick={() => setOpen(v => !v)}>
        <span className="ctx-detail-section-arrow">{open ? '\u25BE' : '\u25B8'}</span>
        <span className="ctx-detail-section-title">{title}</span>
      </div>
      {open && <div className="ctx-detail-section-body">{children}</div>}
    </div>
  );
}

// ─── Notes Editor ────────────────────────────────────────────────────────

function NotesEditor({ sessionId, initialNotes }: { sessionId: string; initialNotes: string | null }): JSX.Element {
  const [editing, setEditing] = useState(false);
  const [notes, setNotes] = useState(initialNotes || '');
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const { showToast } = useToast();
  const errorHandler = useCommandErrorHandler({
    fields: { notes: textareaRef },
  });

  useEffect(() => {
    setNotes(initialNotes || '');
    setEditing(false);
  }, [sessionId, initialNotes]);

  const save = useCallback(async () => {
    // Notes live in the session store `notes` field — the single source of
    // truth, set at launch via the launcher's --notes param and edited here.
    // (Previously this wrote to app_state.json sessionPrefs while the display
    // read session.notes, so edits silently vanished on refresh.)
    const result = await executeCommand('session.update', {
      trackingId: sessionId,
      patch: { notes },
    }, {
      onFailure: 'inline', errorHandler, field: 'notes', toastFn: showToast,
    });
    if (result.ok) {
      setEditing(false);
    }
  }, [sessionId, notes, errorHandler, showToast]);

  if (!editing) {
    return (
      <div className="ctx-notes-section">
        <div className="ctx-section-header" onClick={() => setEditing(true)}>
          <span>Notes</span>
          <span className="ctx-edit-btn">Edit</span>
        </div>
        {notes ? (
          <div className="ctx-notes-text">{notes}</div>
        ) : (
          <div className="ctx-notes-empty">No notes. Click Edit to add.</div>
        )}
      </div>
    );
  }

  return (
    <div className="ctx-notes-section">
      <div className="ctx-section-header">
        <span>Notes</span>
        <span className="ctx-save-btn" onClick={save}>Save</span>
        <span className="ctx-cancel-btn" onClick={() => { setNotes(initialNotes || ''); setEditing(false); }}>Cancel</span>
      </div>
      <textarea
        ref={textareaRef}
        className="ctx-notes-textarea"
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        autoFocus
        rows={4}
      />
    </div>
  );
}

// ─── Tags Section ───────────────────────────────────────────────────────

function TagsSection({ session }: { session: Session }): JSX.Element {
  const [showPicker, setShowPicker] = useState(false);
  const [showTagManager, setShowTagManager] = useState(false);
  const { showToast } = useToast();

  const handleTagToggle = useCallback(async (cardId: string, tagName: string) => {
    const hasTag = session.tags.includes(tagName);
    const commandType = hasTag ? 'tag.remove' : 'tag.add';
    await executeCommand(commandType, { cardId, tag: tagName }, {
      onFailure: 'toast', toastFn: showToast,
    });
  }, [session.tags, showToast]);

  const handleTagCreate = useCallback(async (name: string, _color: string) => {
    // Create tag by adding it to the current session
    await executeCommand('tag.add', {
      cardId: `session:${session.tracking_id}`,
      tag: name,
    }, {
      onFailure: 'toast', toastFn: showToast,
    });
  }, [session.tracking_id, showToast]);

  const handleTagRemove = useCallback(async (tagName: string) => {
    await executeCommand('tag.remove', {
      cardId: `session:${session.tracking_id}`,
      tag: tagName,
    }, {
      onFailure: 'toast', toastFn: showToast,
    });
  }, [session.tracking_id, showToast]);

  return (
    <div className="ctx-tags-section">
      <div className="ctx-section-header">
        <span>Tags</span>
        <span
          className="ctx-edit-btn"
          onClick={() => setShowTagManager(true)}
        >
          Manage
        </span>
        <span
          className="ctx-edit-btn"
          onClick={() => setShowPicker(!showPicker)}
        >
          {showPicker ? 'Done' : 'Edit'}
        </span>
      </div>

      {session.tags.length > 0 && (
        <TagList
          tags={session.tags}
          onRemove={showPicker ? handleTagRemove : undefined}
        />
      )}

      {session.tags.length === 0 && !showPicker && (
        <div className="ctx-notes-empty">No tags. Click Edit to add.</div>
      )}

      {showPicker && (
        <TagPicker
          cardId={`session:${session.tracking_id}`}
          currentTags={session.tags}
          entityType="session"
          onTagToggle={handleTagToggle}
          onCreateTag={handleTagCreate}
        />
      )}

      <TagManager
        isOpen={showTagManager}
        onClose={() => setShowTagManager(false)}
      />
    </div>
  );
}

// ─── Platform label/color helpers ────────────────────────────────────────

const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude CLI',
  codex_cli: 'Codex CLI',
  gemini_cli: 'Gemini CLI',
};

const STATUS_LABELS: Record<string, string> = {
  running: 'Running',
  stopped: 'Stopped',
  exited: 'Exited',
};

// ─── ContextPanel ────────────────────────────────────────────────────────

interface ContextPanelProps {
  activeSessionId: string | null;
  active?: boolean;
}

export default function ContextPanel({ activeSessionId, active = true }: ContextPanelProps): JSX.Element {
  const { appState, updateAppState } = useAppStateStore();
  const { getSession } = useSessionStore();
  const draggingRef = useRef(false);
  const panelRef = useRef<HTMLDivElement>(null);
  const [queueCount, setQueueCount] = useState(0);
  const [inboxCount, setInboxCount] = useState({ total: 0, unread: 0 });

  const isOpen = appState.contextPanelOpen;
  const width = appState.panelSizes.contextPanelWidth;

  // Sub-tab is global app state so it persists across tab switches (the panel
  // is remounted per tab, so local state would reset to 'details' every time).
  const activeRightTab = (appState.contextPanelActiveTab as RightPanelTab) || 'details';
  const setActiveRightTab = useCallback(
    (tab: RightPanelTab) => updateAppState({ contextPanelActiveTab: tab }),
    [updateAppState],
  );

  // Pinned session: when set, the panel shows that session regardless of which
  // tab is active (compare/copy). Otherwise it follows the active tab.
  const pinnedSession = appState.contextPanelPinnedSession || null;
  const effectiveSessionId = pinnedSession || activeSessionId;
  const isPinned = !!pinnedSession;

  const session = effectiveSessionId ? getSession(effectiveSessionId) : undefined;

  useViewport('context_panel', () => ({
    visible: active && isOpen,
    state: { activeTab: activeRightTab, open: isOpen, width },
    actions: [
      {
        id: 'toggle',
        command: 'app.state.update',
        payload: { patch: { contextPanelOpen: !isOpen } },
        label: isOpen ? 'Close panel' : 'Open panel',
      },
    ],
    children: [],
  }), active);

  // Load badge counts when session changes, then poll so the Comms-unread and
  // Prompts-queued badges reflect data-store changes within a few seconds —
  // without needing a tab reload.
  useEffect(() => {
    if (!effectiveSessionId) {
      setQueueCount(0);
      setInboxCount({ total: 0, unread: 0 });
      return;
    }
    const poll = () => {
      window.uai.comms.queueCount(effectiveSessionId).then(setQueueCount).catch(() => setQueueCount(0));
      window.uai.comms.inboxCount(effectiveSessionId).then(setInboxCount).catch(() => setInboxCount({ total: 0, unread: 0 }));
    };
    poll();
    const t = setInterval(poll, 3000);
    return () => clearInterval(t);
  }, [effectiveSessionId]);

  const togglePanel = useCallback(() => {
    updateAppState({ contextPanelOpen: !isOpen });
  }, [isOpen, updateAppState]);

  // Resize handle
  const handleResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    draggingRef.current = true;
    const startX = e.clientX;
    const startWidth = width;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const onMouseMove = (ev: MouseEvent) => {
      if (!draggingRef.current) return;
      const delta = startX - ev.clientX;
      updateAppState({
        panelSizes: {
          ...appState.panelSizes,
          contextPanelWidth: Math.max(200, Math.min(startWidth + delta, Math.max(600, Math.round(window.innerWidth * 0.6)))),
        },
      });
    };

    const onMouseUp = () => {
      draggingRef.current = false;
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMouseMove);
      window.removeEventListener('mouseup', onMouseUp);
    };

    window.addEventListener('mousemove', onMouseMove);
    window.addEventListener('mouseup', onMouseUp);
  }, [width, appState.panelSizes, updateAppState]);

  if (!isOpen) {
    return <></>;
  }

  return (
    <div className="context-panel" ref={panelRef} style={{ width: `${width}px` }}>
      <div className="context-panel-resize" onMouseDown={handleResizeMouseDown} />
      <div className="context-panel-header">
        <div className="ctx-tab-bar">
          <button
            className={`ctx-tab-btn${activeRightTab === 'details' ? ' active' : ''}`}
            onClick={() => setActiveRightTab('details')}
          >Details</button>
          <button
            className={`ctx-tab-btn${activeRightTab === 'context' ? ' active' : ''}`}
            onClick={() => setActiveRightTab('context')}
          >Context</button>
          <button
            className={`ctx-tab-btn${activeRightTab === 'prompts' ? ' active' : ''}`}
            onClick={() => setActiveRightTab('prompts')}
          >
            Prompts{queueCount > 0 && <span className="ctx-tab-badge ctx-tab-badge-prompt">{queueCount}</span>}
          </button>
          <button
            className={`ctx-tab-btn${activeRightTab === 'messages' ? ' active' : ''}`}
            onClick={() => setActiveRightTab('messages')}
          >
            Comms{inboxCount.unread > 0 && <span className="ctx-tab-badge ctx-tab-badge-unread">{inboxCount.unread}</span>}
          </button>
          <button
            className={`ctx-tab-btn ctx-pin-btn${isPinned ? ' active' : ''}`}
            style={{ marginLeft: 'auto' }}
            title={isPinned
              ? `Pinned to ${getSession(pinnedSession || '')?.display_name || pinnedSession} — click to unpin (follow active tab)`
              : 'Pin this session — keep showing it when you switch to other tabs'}
            onClick={() => updateAppState({ contextPanelPinnedSession: isPinned ? null : (activeSessionId || null) })}
          >
            <svg className="ctx-pin-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M16 9V4l1 0c.55 0 1-.45 1-1s-.45-1-1-1H7c-.55 0-1 .45-1 1s.45 1 1 1l1 0v5c0 1.66-1.34 3-3 3v2h5.97v7l1 1 1-1v-7H19v-2c-1.66 0-3-1.34-3-3z"/>
            </svg>
          </button>
        </div>
      </div>
      {/* Toggle bar removed — use title bar button to close */}

      {activeRightTab === 'details' && (
        session ? (
          <div className="context-panel-body">

            {/* Status with action buttons */}
            <DetailRow label="Status" customContent={
              <span style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                {session.process_status === 'running' ? (
                  <button
                    className="ctx-action-btn ctx-action-danger"
                    onClick={() => executeCommand('session.stop', { trackingId: session.tracking_id })}
                  >Stop</button>
                ) : (
                  <button
                    className="ctx-action-btn ctx-action-primary"
                    onClick={() => executeCommand('session.resume', { trackingId: session.tracking_id })}
                  >Resume</button>
                )}
                <span
                  className="ctx-status-pill"
                  style={{ color: PROCESS_STATUS_COLORS[session.process_status] || 'var(--text-muted)' }}
                >
                  {STATUS_LABELS[session.process_status] || session.process_status}
                </span>
              </span>
            } />

            <div className="ctx-separator" />

            {/* Identity */}
            <DetailRow label="Display Name" value={session.display_name} />
            <DetailRow label="Tracking ID" value={session.tracking_id} copyable mono />
            <DetailRow label="URI" value={`uai://session/${session.tracking_id}`} copyable mono />
            <DetailRow label="CLI UUID" value={session.cli_session_id} copyable mono />
            <DetailRow label="Terminal" value={session.terminal_session} copyable mono />

            <div className="ctx-separator" />

            {/* Paths */}
            <DetailRow label="Project Dir" value={session.project_dir} isPath copyable mono />
            <DetailRow label="Working Dir" value={session.project_dir} isPath copyable mono />
            <DetailRow label="Session Dir" value={session.session_dir} isPath copyable mono />
            <DetailRow label="Transcript" value={session.history_file} isPath copyable mono />

            <div className="ctx-separator" />

            {/* Classification */}
            <DetailRow label="Platform" customContent={
              <span style={{ color: PLATFORM_COLORS[session.platform] || 'var(--text-secondary)' }}>
                {PLATFORM_LABELS[session.platform] || session.platform}
              </span>
            } />
            <DetailRow label="Brief(s)" value={session.loaded_briefs?.length ? session.loaded_briefs.join(', ') : null} />
            <DetailRow label="Profile(s)" value={null} />
            <DetailRow label="Role(s)" value={session.roles.join(', ') || null} />

            <div className="ctx-separator" />

            {/* Metrics */}
            <DetailRow label="Turns" value={session.exchange_count ? String(session.exchange_count) : null} />
            <DetailRow label="Messages" value={session.message_count != null ? String(session.message_count) : null} />
            <DetailRow label="Context Used" value={session.context_percent != null ? `${session.context_percent}%` : null} />
            <DetailRow label="Prompts (queued)" value={String(queueCount)} />
            <DetailRow label="Comms" value={inboxCount.total > 0 ? `${inboxCount.total}${inboxCount.unread > 0 ? ` (${inboxCount.unread} unread)` : ''}` : String(inboxCount.total)} />

            <div className="ctx-separator" />

            {/* Timestamps */}
            <DetailRow label="Created" value={session.created_at ? new Date(session.created_at).toLocaleString() : null} />
            <DetailRow label="Last Activity" value={session.last_activity ? new Date(session.last_activity).toLocaleString() : null} />
            <DetailRow label="Session Starts" customContent={<SessionStartsValue starts={session.start_history} />} />

            <div className="ctx-separator" />

            <TagsSection session={session} />

            <div className="ctx-separator" />

            <NotesEditor sessionId={session.tracking_id} initialNotes={session.notes} />
          </div>
        ) : (
          <div className="context-panel-empty">
            <p>Select a session to view details.</p>
          </div>
        )
      )}

      {activeRightTab === 'context' && (
        <div className="context-panel-body context-panel-body-context">
          <ContextTab sessionTrackingId={effectiveSessionId} />
        </div>
      )}

      {activeRightTab === 'prompts' && (
        <div className="context-panel-body">
          <PromptsTab sessionTrackingId={effectiveSessionId} />
        </div>
      )}

      {activeRightTab === 'messages' && (
        <div className="context-panel-body context-panel-body-messages">
          <MessagesTab sessionTrackingId={effectiveSessionId} />
        </div>
      )}

    </div>
  );
}
