/**
 * SessionStoreDetail — Right panel with Store Fields, State Vars, History sub-tabs.
 *
 * Store Fields: collapsible sections with inline editing for mutable fields.
 * State Vars: namespace-grouped KV list with inline edit.
 * History: change log timeline.
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import type { SessionStoreRecord } from './session-store-types';
import type { Session } from '@uai/shared/types';
import SessionStoreStateVars, { type StateVarsHandle } from './SessionStoreStateVars';
import SessionStoreHistory from './SessionStoreHistory';
import { SessionStartsValue } from './SessionStarts';
import { useToast } from './Toast';
import { executeCommand } from '../utils/execute-command';

type SubTab = 'fields' | 'state' | 'history';

interface SessionStoreDetailProps {
  session: SessionStoreRecord;
  initialSubTab?: string;
  onUpdated: () => void;
  onDelete: (trackingId: string) => void;
}

const IMMUTABLE_FIELDS = new Set(['tracking_id', 'platform', 'created_at', 'session_dir']);

const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude CLI',
  codex_cli: 'Codex CLI',
  gemini_cli: 'Gemini CLI',
};

function formatDate(value?: string | null): string {
  if (!value) return '--';
  try {
    return new Date(value).toLocaleString();
  } catch {
    return value;
  }
}

function CopyableField({ label, value }: { label: string; value: string | null | undefined }): JSX.Element {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(() => {
    if (!value) return;
    window.uai.clipboard.write(value);
    setCopied(true);
    setTimeout(() => setCopied(false), 1500);
  }, [value]);

  return (
    <div className="sess-store-field-row">
      <span className="sess-store-field-label">{label}</span>
      <span
        className="sess-store-field-value sess-store-copyable"
        onClick={handleCopy}
        title="Click to copy"
      >
        {copied ? 'Copied' : (value || '--')}
      </span>
    </div>
  );
}

function EditableField({ label, fieldKey, value, onSave }: {
  label: string;
  fieldKey: string;
  value: string | null | undefined;
  onSave: (key: string, val: string) => Promise<void>;
}): JSX.Element {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(value || '');
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);

  const startEdit = useCallback(() => {
    setDraft(value || '');
    setEditing(true);
    setSaveError(null);
  }, [value]);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setSaveError(null);
    try {
      await onSave(fieldKey, draft);
      setEditing(false);
    } catch (err: any) {
      setSaveError(err.message || 'Save failed');
    } finally {
      setSaving(false);
    }
  }, [fieldKey, draft, onSave]);

  const handleCancel = useCallback(() => {
    setEditing(false);
    setSaveError(null);
  }, []);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSave();
    if (e.key === 'Escape') handleCancel();
  }, [handleSave, handleCancel]);

  return (
    <div className="sess-store-field-row">
      <span className="sess-store-field-label">{label}</span>
      {editing ? (
        <div className="sess-store-field-edit">
          <input
            className={`sess-store-field-input${saveError ? ' sess-store-field-error' : ''}`}
            type="text"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={handleKeyDown}
            disabled={saving}
            autoFocus
          />
          {saveError && <span className="sess-store-field-error-msg">{saveError}</span>}
        </div>
      ) : (
        <span className="sess-store-field-value">
          {value || '--'}
          <button className="sess-store-edit-btn" onClick={startEdit} title="Edit">&#9998;</button>
        </span>
      )}
    </div>
  );
}

function DetailSection({ title, defaultOpen = true, children }: {
  title: string;
  defaultOpen?: boolean;
  children: React.ReactNode;
}): JSX.Element {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <div className="sess-store-section">
      <div className="sess-store-section-header" onClick={() => setOpen(v => !v)}>
        <span className="sess-store-section-arrow">{open ? '\u25BE' : '\u25B8'}</span>
        <span className="sess-store-section-title">{title}</span>
      </div>
      {open && <div className="sess-store-section-body">{children}</div>}
    </div>
  );
}

export default function SessionStoreDetail({ session, initialSubTab, onUpdated, onDelete }: SessionStoreDetailProps): JSX.Element {
  const [subTab, setSubTab] = useState<SubTab>(() => {
    const saved = localStorage.getItem('uai:sessStoreSubTab');
    if (saved === 'fields' || saved === 'state' || saved === 'history') return saved;
    return (initialSubTab === 'state' || initialSubTab === 'history') ? initialSubTab : 'fields';
  });
  const stateVarsRef = useRef<StateVarsHandle>(null);
  const { showToast } = useToast();

  useEffect(() => {
    try { localStorage.setItem('uai:sessStoreSubTab', subTab); } catch { /* ignore */ }
  }, [subTab]);
  const [tags, setTags] = useState<string[]>(session.tags || []);
  const [newTag, setNewTag] = useState('');
  const [addingTag, setAddingTag] = useState(false);

  // The Session Store shows a session's FULL state, not just the DB record. The
  // record from session_store.py omits the metrics/activity/briefs (and returns
  // tags unpopulated), so we pull the app's merged Session model — which unions
  // the DB record + the hook state file ({tid}_state.json) + the tag store — and
  // drive the read-only state display from it. (Data lives outside the app; we
  // only read it — Data Ownership Boundary, DESIGN.md #6.)
  const [full, setFull] = useState<Session | null>(null);
  const [queued, setQueued] = useState(0);
  const [inbox, setInbox] = useState<{ total: number; unread: number }>({ total: 0, unread: 0 });
  useEffect(() => {
    let alive = true;
    const tid = session.tracking_id;
    window.uai.sessions.get(tid).then(s => {
      if (!alive) return;
      setFull(s);
      if (s?.tags && !addingTag) setTags(s.tags);
    }).catch(() => {});
    window.uai.comms.queueCount(tid).then(n => { if (alive) setQueued(n); }).catch(() => {});
    window.uai.comms.inboxCount(tid).then(v => { if (alive) setInbox(v); }).catch(() => {});
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session.tracking_id]);

  // Update tags when the record OR the merged model changes.
  const srcTags = (full?.tags && full.tags.length) ? full.tags : session.tags;
  if (srcTags && JSON.stringify(srcTags) !== JSON.stringify(tags) && !addingTag) {
    setTags(srcTags);
  }

  const handleFieldSave = useCallback(async (key: string, value: string) => {
    const result = await executeCommand('session.update', {
      trackingId: session.tracking_id,
      patch: { [key]: value },
    });
    if (!result.ok) throw new Error(result.error?.message || 'Update failed');
    showToast('Saved', 'info');
    onUpdated();
  }, [session.tracking_id, onUpdated, showToast]);

  const handleAddTag = useCallback(async () => {
    const tag = newTag.trim();
    if (!tag) return;
    setAddingTag(true);
    const result = await executeCommand('tag.add', {
      cardId: `session:${session.tracking_id}`,
      tag,
    });
    if (result.ok) {
      setTags(prev => [...prev, tag]);
      setNewTag('');
      showToast('Tag added', 'info');
      onUpdated();
    } else {
      showToast(result.error?.message || 'Failed to add tag', 'error');
    }
    setAddingTag(false);
  }, [newTag, session.tracking_id, onUpdated, showToast]);

  const handleRemoveTag = useCallback(async (tag: string) => {
    const result = await executeCommand('tag.remove', {
      cardId: `session:${session.tracking_id}`,
      tag,
    });
    if (result.ok) {
      setTags(prev => prev.filter(t => t !== tag));
      showToast('Tag removed', 'info');
      onUpdated();
    } else {
      showToast(result.error?.message || 'Failed to remove tag', 'error');
    }
  }, [session.tracking_id, onUpdated, showToast]);

  const handleTagKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleAddTag();
    if (e.key === 'Escape') setNewTag('');
  }, [handleAddTag]);

  const rolesStr = typeof session.roles === 'string'
    ? session.roles
    : Array.isArray(session.roles)
      ? session.roles.join(', ')
      : '';

  return (
    <div className="sess-store-detail-content">
      {/* Sub-tab buttons */}
      <div className="traits-mgr-tabs sess-store-sub-tabs">
        <button className={`traits-mgr-tab-btn${subTab === 'fields' ? ' active' : ''}`} onClick={() => setSubTab('fields')}>Store Fields</button>
        <button className={`traits-mgr-tab-btn${subTab === 'state' ? ' active' : ''}`} onClick={() => setSubTab('state')}>State Vars</button>
        <button className={`traits-mgr-tab-btn${subTab === 'history' ? ' active' : ''}`} onClick={() => setSubTab('history')}>History</button>
        <div className="sess-store-subtab-actions">
          {subTab === 'fields' && (
            <>
              <button
                className="sess-store-bar-action-btn sess-store-archive-btn"
                onClick={() => { const archived = session.archived === true || session.archived === 1; handleFieldSave('archived', archived ? 'false' : 'true'); }}
              >{(session.archived === true || session.archived === 1) ? 'Unarchive' : 'Archive'}</button>
              <button className="sess-store-bar-action-btn sess-store-delete-btn" onClick={() => onDelete(session.tracking_id)}>Delete</button>
            </>
          )}
          {subTab === 'state' && (
            <>
              <button className="sess-store-bar-action-btn" onClick={() => stateVarsRef.current?.addNew()}>+ New Key</button>
              <button className="sess-store-bar-action-btn" onClick={() => stateVarsRef.current?.refresh()}>Refresh</button>
            </>
          )}
        </div>
      </div>

      {subTab === 'fields' && (
        <div className="sess-store-fields-content">
          <DetailSection title="Identity">
            <CopyableField label="Tracking ID" value={session.tracking_id} />
            <CopyableField label="CLI Session ID" value={session.cli_session_id} />
            <EditableField label="Display Name" fieldKey="display_name" value={session.display_name} onSave={handleFieldSave} />
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Identity Status</span>
              <span className={`sess-store-field-value sess-store-identity-${session.identity_status}`}>{session.identity_status}</span>
            </div>
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Status</span>
              <span className={`sess-store-field-value sess-store-status-${session.status}`}>{session.status}</span>
            </div>
          </DetailSection>

          <DetailSection title="Classification">
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Platform</span>
              <span className="sess-store-field-value">{PLATFORM_LABELS[session.platform] || session.platform}</span>
            </div>
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Substrate</span>
              <span className="sess-store-field-value">{session.substrate || '--'}</span>
            </div>
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Tmux Server</span>
              <span className="sess-store-field-value">{session.tmux_server || '--'}</span>
            </div>
            <EditableField label="Model" fieldKey="model" value={session.model} onSave={handleFieldSave} />
            <EditableField label="Roles" fieldKey="roles" value={rolesStr} onSave={handleFieldSave} />
            <CopyableField label="Parent" value={session.parent_tracking_id} />
          </DetailSection>

          <DetailSection title="Activity & Metrics">
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Activity State</span>
              <span className="sess-store-field-value">{full?.activity_state ?? '--'}</span>
            </div>
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Turns</span>
              <span className="sess-store-field-value">{full?.exchange_count != null ? String(full.exchange_count) : '--'}</span>
            </div>
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Messages</span>
              <span className="sess-store-field-value">{full?.message_count != null ? String(full.message_count) : '--'}</span>
            </div>
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Context Used</span>
              <span className="sess-store-field-value">{full?.context_percent != null ? `${full.context_percent}%` : '--'}</span>
            </div>
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Prompts (queued)</span>
              <span className="sess-store-field-value">{String(queued)}</span>
            </div>
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Comms</span>
              <span className="sess-store-field-value">{inbox.total > 0 ? `${inbox.total}${inbox.unread > 0 ? ` (${inbox.unread} unread)` : ''}` : '0'}</span>
            </div>
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Brief(s)</span>
              <span className="sess-store-field-value">{full?.loaded_briefs?.length ? full.loaded_briefs.join(', ') : '--'}</span>
            </div>
          </DetailSection>

          <DetailSection title="Paths">
            <CopyableField label="URI" value={`uai://session/${session.tracking_id}`} />
            <CopyableField label="Terminal" value={full?.terminal_session ?? session.terminal_session} />
            <CopyableField label="Project Dir" value={session.project_dir} />
            <CopyableField label="Working Dir" value={full?.project_dir ?? session.project_dir} />
            <CopyableField label="Session Dir" value={session.session_dir} />
            <CopyableField label="History File" value={session.history_file} />
          </DetailSection>

          <DetailSection title="Notes">
            <EditableField label="Notes" fieldKey="notes" value={session.notes} onSave={handleFieldSave} />
          </DetailSection>

          <DetailSection title="Tags">
            <div className="sess-store-tags-container">
              {tags.map(tag => (
                <span key={tag} className="sess-store-tag-pill sess-store-tag-removable">
                  {tag}
                  <button className="sess-store-tag-remove" onClick={() => handleRemoveTag(tag)} title="Remove tag">&times;</button>
                </span>
              ))}
              <div className="sess-store-tag-add">
                <input
                  className="sess-store-tag-input"
                  type="text"
                  placeholder="+ Add tag"
                  value={newTag}
                  onChange={(e) => setNewTag(e.target.value)}
                  onKeyDown={handleTagKeyDown}
                />
              </div>
            </div>
          </DetailSection>

          <DetailSection title="Timestamps">
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Created</span>
              <span className="sess-store-field-value">{formatDate(session.created_at)}</span>
            </div>
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Last Activity</span>
              <span className="sess-store-field-value">{formatDate(full?.last_activity ?? session.last_activity)}</span>
            </div>
            <div className="sess-store-field-row">
              <span className="sess-store-field-label">Session Starts</span>
              <SessionStartsValue starts={(full?.start_history ?? session.start_history)} />
            </div>
          </DetailSection>
        </div>
      )}

      {subTab === 'state' && (
        <SessionStoreStateVars ref={stateVarsRef} trackingId={session.tracking_id} />
      )}

      {subTab === 'history' && (
        <SessionStoreHistory trackingId={session.tracking_id} />
      )}
    </div>
  );
}
