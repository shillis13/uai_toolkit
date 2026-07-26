/**
 * ResumeForkDialog — the [+ New] › "Resume / Fork ..." dialog (todo_0600 section 1).
 *
 * Composes the reusable <SessionPicker> (section 1.1) to pick a session, a Resume↔Fork
 * toggle (section 1.2), and — when Fork is chosen — expands to the custom-launcher fields
 * (section 1.3: name, working dir, description, roles; add-context is the shared picker,
 * stubbed disabled here until that component lands with the Custom work). A
 * grayed-out "Pre-processing actions" button stubs section 1.4.
 *
 * Resume → session.resume(trackingId). Fork → session.create(parentTrackingId=…)
 * then opens the new session's tab. Command payloads mirror SessionContextMenu.
 */

import { useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useSessionStore } from '../stores/session-store';
import { executeCommand } from '../utils/execute-command';
import SessionPicker from './SessionPicker';
import AddContextPicker, { type ContextSelection } from './AddContextPicker';

interface ResumeForkDialogProps {
  onClose: () => void;
  toastFn?: (msg: string) => void;
}

const fieldStyle: React.CSSProperties = {
  background: 'var(--bg-deep)', border: '1px solid var(--border)', borderRadius: 5,
  color: 'var(--text)', fontSize: 12, padding: '5px 8px', outline: 'none', width: '100%',
};
const labelStyle: React.CSSProperties = { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3, display: 'block' };

export default function ResumeForkDialog({ onClose, toastFn }: ResumeForkDialogProps): JSX.Element {
  const { getSession } = useSessionStore();
  const [mode, setMode] = useState<'resume' | 'fork'>('resume');
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Fork-only fields (section 1.3).
  const [name, setName] = useState('');
  const [workdir, setWorkdir] = useState('');
  const [description, setDescription] = useState('');
  const [roles, setRoles] = useState('');
  const [context, setContext] = useState<ContextSelection[]>([]);
  const [contextOpen, setContextOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const selected = selectedId ? getSession(selectedId) : undefined;

  const submit = useCallback(async (trackingId?: string) => {
    const target = trackingId ? getSession(trackingId) : selected;
    if (!target || busy) return;
    setBusy(true);
    try {
      let succeeded = false;
      if (mode === 'resume') {
        const res = await executeCommand('session.resume', { trackingId: target.tracking_id }, { onFailure: 'toast', toastFn });
        succeeded = !!res?.ok;
      } else {
        const rolesArr = roles.split(',').map((r) => r.trim()).filter(Boolean);
        const res = await executeCommand('session.create', {
          parentTrackingId: target.tracking_id,
          platform: target.platform,
          displayName: name.trim() || undefined,
          projectDir: workdir.trim() || undefined,
          roles: rolesArr.length ? rolesArr : undefined,
          notes: description.trim() || undefined,
          contextItems: context.length ? context : undefined,
        }, { onFailure: 'toast', toastFn });
        const data = res?.data as { trackingId?: string } | undefined;
        if (res?.ok && data?.trackingId) {
          await executeCommand('workspace.tabs.open', { type: 'session', targetId: data.trackingId, label: `Fork of ${target.display_name || target.tracking_id}` });
          succeeded = true;
        }
      }
      if (succeeded) onClose();
    } finally {
      setBusy(false);
    }
  }, [getSession, selected, busy, mode, name, workdir, description, roles, context, toastFn, onClose]);

  const toggleBtn = (m: 'resume' | 'fork', label: string): JSX.Element => (
    <button onClick={() => setMode(m)}
      style={{ flex: 1, padding: '6px 0', fontSize: 13, cursor: 'pointer', fontWeight: mode === m ? 700 : 500,
        background: mode === m ? 'var(--accent-blue-bg, var(--bg-hover))' : 'transparent',
        border: `1px solid ${mode === m ? 'var(--accent-blue)' : 'var(--border)'}`,
        color: mode === m ? 'var(--text)' : 'var(--text-muted)',
        borderRadius: 6 }}>{label}</button>
  );

  return createPortal(
    <div onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'color-mix(in srgb, var(--bg-deep) 70%, transparent)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ background: 'var(--bg-panel, var(--bg-card))', border: '1px solid var(--border-bright, var(--border))', borderRadius: 10, padding: 16, width: 540, maxWidth: '92vw', maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 12px 40px rgba(0,0,0,0.4)' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)' }}>Resume / Fork Session</div>
          <button onClick={onClose} style={{ marginLeft: 'auto', background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: 18, cursor: 'pointer', lineHeight: 1 }}>✕</button>
        </div>

        <SessionPicker selectedId={selectedId} onSelect={setSelectedId}
          onConfirm={(trackingId) => {
            setSelectedId(trackingId);
            if (mode === 'resume') void submit(trackingId);
          }}
          height={260} />

        {/* Resume ↔ Fork toggle (section 1.2) */}
        <div style={{ display: 'flex', gap: 6, marginTop: 12 }}>
          {toggleBtn('resume', '↻ Resume')}
          {toggleBtn('fork', '⑂ Fork')}
        </div>

        {/* Fork-only expanded fields (section 1.3) */}
        {mode === 'fork' && (
          <div style={{ marginTop: 12, display: 'flex', flexDirection: 'column', gap: 8 }}>
            <div>
              <label style={labelStyle}>Name (optional)</label>
              <input style={fieldStyle} value={name} onChange={(e) => setName(e.target.value)} placeholder={selected ? `Fork of ${selected.display_name || selected.tracking_id}` : 'New session name'} />
            </div>
            <div>
              <label style={labelStyle}>Working directory (optional)</label>
              <input style={fieldStyle} value={workdir} onChange={(e) => setWorkdir(e.target.value)} placeholder={selected?.project_dir || '(inherit from parent)'} />
            </div>
            <div>
              <label style={labelStyle}>Roles (comma-separated, optional)</label>
              <input style={fieldStyle} value={roles} onChange={(e) => setRoles(e.target.value)} placeholder={(selected?.roles || []).join(', ') || 'e.g. assistant, dev'} />
            </div>
            <div>
              <label style={labelStyle}>Description (optional)</label>
              <textarea style={{ ...fieldStyle, minHeight: 44, resize: 'vertical' }} value={description} onChange={(e) => setDescription(e.target.value)} placeholder="What is this fork for?" />
            </div>
            {/* Add context (section 1.3) — the shared AddContextPicker. */}
            <div>
              <button onClick={() => setContextOpen((v) => !v)}
                style={{ background: 'transparent', border: 'none', color: 'var(--text-sec)', fontSize: 12, cursor: 'pointer', padding: 0, display: 'inline-flex', alignItems: 'center', gap: 5, fontWeight: 600 }}>
                <span style={{ fontSize: 9 }}>{contextOpen ? '▼' : '▶'}</span>
                Add context{context.length ? ` (${context.length})` : ''}
              </button>
              {contextOpen && (
                <div style={{ marginTop: 6 }}>
                  <AddContextPicker selected={context} onChange={setContext} height={200} />
                </div>
              )}
            </div>
            <button disabled title="Pre-processing actions (back up history, compact + brief, offload, …) — future feature"
              style={{ ...fieldStyle, width: 'auto', alignSelf: 'flex-start', cursor: 'not-allowed', opacity: 0.5, color: 'var(--text-muted)' }}>⚙ Pre-processing actions…</button>
          </div>
        )}

        {/* Footer */}
        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)', borderRadius: 6, padding: '6px 14px', fontSize: 13, cursor: 'pointer' }}>Cancel</button>
          <button onClick={() => void submit()} disabled={!selected || busy}
            style={{ background: 'var(--accent-blue-bg)', border: '1px solid var(--accent-blue)', color: 'var(--text)', borderRadius: 6, padding: '6px 16px', fontSize: 13, fontWeight: 600, cursor: selected && !busy ? 'pointer' : 'not-allowed', opacity: selected && !busy ? 1 : 0.5 }}>
            {busy ? 'Working…' : mode === 'resume' ? 'Resume →' : 'Fork →'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
