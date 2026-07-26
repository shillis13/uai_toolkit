/**
 * Briefs dialogs — the [+ New] › Briefs submenu (todo_0600 section 2). THREE separate,
 * single-purpose dialogs (PianoMan: they are not three views of one thing, so no
 * merged mode-tabs):
 *   section 2.1 CreateBriefFromSessionDialog — pick a source session, name it → brief.create
 *   section 2.2 LaunchFromBriefsDialog        — platform + brief(s) → session.create
 *   section 2.3 LoadBriefsIntoSessionDialog   — pick a running session + brief(s) → traits.load
 *
 * Brief selection uses the sortable <BriefListPicker> (list + child-folder sections),
 * not a search box. Session selection reuses <SessionPicker>.
 */

import { useState, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { useSessionStore } from '../stores/session-store';
import { executeCommand } from '../utils/execute-command';
import SessionPicker from './SessionPicker';
import BriefListPicker from './BriefListPicker';
import type { ContextSelection } from './AddContextPicker';

export type BriefsMode = 'create' | 'launch' | 'load';
type ToastFn = (msg: string, type?: 'error' | 'info' | 'warning') => void;

const PLATFORMS: { value: string; label: string }[] = [
  { value: 'claude_cli', label: 'Claude' }, { value: 'codex_cli', label: 'Codex' },
  { value: 'grok_cli', label: 'Grok' }, { value: 'antigravity_cli', label: 'Antigravity' },
];

const fieldStyle: React.CSSProperties = {
  background: 'var(--bg-deep)', border: '1px solid var(--border)', borderRadius: 5,
  color: 'var(--text)', fontSize: 12, padding: '5px 8px', outline: 'none', width: '100%',
};
const labelStyle: React.CSSProperties = { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3, display: 'block' };

// Shared modal shell: backdrop + panel + header + footer (Cancel / primary).
function Shell({ title, onClose, canSubmit, busy, submitLabel, onSubmit, children }: {
  title: string; onClose: () => void; canSubmit: boolean; busy: boolean; submitLabel: string;
  onSubmit: () => void; children: React.ReactNode;
}): JSX.Element {
  return createPortal(
    <div onClick={onClose}
      style={{ position: 'fixed', inset: 0, background: 'color-mix(in srgb, var(--bg-deep) 70%, transparent)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div onClick={(e) => e.stopPropagation()}
        style={{ background: 'var(--bg-panel, var(--bg-card))', border: '1px solid var(--border-bright, var(--border))', borderRadius: 10, padding: 16, width: 540, maxWidth: '92vw', maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 12px 40px rgba(0,0,0,0.4)' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)' }}>{title}</div>
          <button onClick={onClose} style={{ marginLeft: 'auto', background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: 18, cursor: 'pointer', lineHeight: 1 }}>✕</button>
        </div>
        {children}
        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <button onClick={onClose} style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)', borderRadius: 6, padding: '6px 14px', fontSize: 13, cursor: 'pointer' }}>Cancel</button>
          <button onClick={onSubmit} disabled={!canSubmit || busy}
            style={{ background: 'var(--accent-blue-bg)', border: '1px solid var(--accent-blue)', color: 'var(--text)', borderRadius: 6, padding: '6px 16px', fontSize: 13, fontWeight: 600, cursor: canSubmit && !busy ? 'pointer' : 'not-allowed', opacity: canSubmit && !busy ? 1 : 0.5 }}>
            {busy ? 'Working…' : submitLabel}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}

// ── section 2.1 Create brief from session ──────────────────────────────────────────
function CreateBriefFromSessionDialog({ onClose, toastFn }: { onClose: () => void; toastFn?: ToastFn }): JSX.Element {
  const { getSession } = useSessionStore();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [name, setName] = useState('');
  const [desc, setDesc] = useState('');
  const [folder, setFolder] = useState('');
  const [busy, setBusy] = useState(false);
  const s = sessionId ? getSession(sessionId) : undefined;

  const submit = useCallback(async () => {
    if (!s || !name.trim()) return;
    setBusy(true);
    try {
      const res = await executeCommand('brief.create', {
        sessionIds: [s.tracking_id],
        opts: { name: name.trim(), description: desc.trim() || undefined, folder: folder.trim(), targetName: s.display_name || s.tracking_id },
      }, { onFailure: 'toast', toastFn });
      if (res?.ok) {
        toastFn?.(`Brief "${name.trim()}" requested`, 'info');
        onClose();
      }
    } finally {
      setBusy(false);
    }
  }, [s, name, desc, folder, toastFn, onClose]);

  return (
    <Shell title="Create brief from session" onClose={onClose} canSubmit={!!s && !!name.trim()} busy={busy} submitLabel="Create brief" onSubmit={submit}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div><label style={labelStyle}>Source session (the brief is condensed from this session)</label>
          <SessionPicker selectedId={sessionId} onSelect={setSessionId} height={210} /></div>
        <div><label style={labelStyle}>Brief name</label>
          <input style={fieldStyle} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. AuthRefactor-Handoff" /></div>
        <div><label style={labelStyle}>Description (optional)</label>
          <input style={fieldStyle} value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="What this brief captures" /></div>
        <div><label style={labelStyle}>Folder (optional)</label>
          <input style={fieldStyle} value={folder} onChange={(e) => setFolder(e.target.value)} placeholder="(default briefs folder)" /></div>
      </div>
    </Shell>
  );
}

// ── section 2.2 Launch new session from brief(s) ───────────────────────────────────
function LaunchFromBriefsDialog({ onClose, toastFn }: { onClose: () => void; toastFn?: ToastFn }): JSX.Element {
  const [platform, setPlatform] = useState('claude_cli');
  const [name, setName] = useState('');
  const [briefs, setBriefs] = useState<ContextSelection[]>([]);
  const [busy, setBusy] = useState(false);

  const submit = useCallback(async () => {
    if (!briefs.length) return;
    setBusy(true);
    try {
      const label = name.trim() || `From ${briefs.length} brief${briefs.length === 1 ? '' : 's'}`;
      const res = await executeCommand('session.create', {
        platform, displayName: label, roles: ['assistant'], contextItems: briefs,
      }, { onFailure: 'toast', toastFn });
      const data = res?.data as { trackingId?: string } | undefined;
      if (res?.ok && data?.trackingId) {
        await executeCommand('workspace.tabs.open', { type: 'session', targetId: data.trackingId, label });
        onClose();
      }
    } finally {
      setBusy(false);
    }
  }, [platform, name, briefs, toastFn, onClose]);

  return (
    <Shell title="Launch new session from brief(s)" onClose={onClose} canSubmit={briefs.length > 0} busy={busy} submitLabel="Launch →" onSubmit={submit}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div style={{ display: 'flex', gap: 8 }}>
          <div style={{ flex: 1 }}><label style={labelStyle}>Platform</label>
            <select style={fieldStyle} value={platform} onChange={(e) => setPlatform(e.target.value)}>
              {PLATFORMS.map((p) => <option key={p.value} value={p.value}>{p.label}</option>)}
            </select></div>
          <div style={{ flex: 2 }}><label style={labelStyle}>Session name (optional)</label>
            <input style={fieldStyle} value={name} onChange={(e) => setName(e.target.value)} placeholder="New session name" /></div>
        </div>
        <div><label style={labelStyle}>Brief(s) to seed the new session with</label>
          <BriefListPicker selected={briefs} onChange={setBriefs} height={240} /></div>
      </div>
    </Shell>
  );
}

// ── section 2.3 Load brief(s) into a session ───────────────────────────────────────
function LoadBriefsIntoSessionDialog({ onClose, toastFn }: { onClose: () => void; toastFn?: ToastFn }): JSX.Element {
  const { getSession } = useSessionStore();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [briefs, setBriefs] = useState<ContextSelection[]>([]);
  const [busy, setBusy] = useState(false);
  const s = sessionId ? getSession(sessionId) : undefined;

  const submit = useCallback(async () => {
    if (!s || !briefs.length) return;
    setBusy(true);
    try {
      const res = await executeCommand<{ results: Array<{ type: string; name: string; success: boolean; error?: string }> }>('traits.load', {
        sessionId: s.tracking_id, items: briefs.map((b) => ({ type: b.type, name: b.name })),
      }, { onFailure: 'toast', toastFn });
      const results = res?.data?.results ?? [];
      const failures = results.filter((r) => !r.success);
      if (res?.ok && results.length === briefs.length && failures.length === 0) {
        toastFn?.(`Loaded ${briefs.length} brief${briefs.length === 1 ? '' : 's'} into ${s.display_name || s.tracking_id}`, 'info');
        onClose();
      } else if (res?.ok) {
        toastFn?.(`Failed to load ${failures.length || briefs.length} brief${(failures.length || briefs.length) === 1 ? '' : 's'}.`, 'error');
      }
    } finally {
      setBusy(false);
    }
  }, [s, briefs, toastFn, onClose]);

  return (
    <Shell title="Load brief(s) into session" onClose={onClose} canSubmit={!!s && briefs.length > 0} busy={busy} submitLabel="Load →" onSubmit={submit}>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        <div><label style={labelStyle}>Target session (the brief is loaded into this session)</label>
          <SessionPicker selectedId={sessionId} onSelect={setSessionId} initialFilter={{ state: 'running' }} height={180} /></div>
        <div><label style={labelStyle}>Brief(s) to load</label>
          <BriefListPicker selected={briefs} onChange={setBriefs} height={180} /></div>
      </div>
    </Shell>
  );
}

/** Router: Navigator opens one of the three dialogs by mode. */
export default function BriefsDialog({ mode, onClose, toastFn }: { mode: BriefsMode; onClose: () => void; toastFn?: ToastFn }): JSX.Element {
  if (mode === 'create') return <CreateBriefFromSessionDialog onClose={onClose} toastFn={toastFn} />;
  if (mode === 'launch') return <LaunchFromBriefsDialog onClose={onClose} toastFn={toastFn} />;
  return <LoadBriefsIntoSessionDialog onClose={onClose} toastFn={toastFn} />;
}
