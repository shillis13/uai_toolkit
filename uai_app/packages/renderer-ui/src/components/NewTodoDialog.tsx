/**
 * NewTodoDialog — the Work Mgr [+ New] dialog (todo_0557). Replaces the one-line
 * title field with an Add-Note-style modal that captures the common todo fields up
 * front: title, description, status, parent, tags, and named priority.
 *
 * Create routes through the same Command Bus verbs the rest of the Work Mgr uses:
 * todo.create carries the fields in one call, including --description. Its Command
 * Bus result includes todo_mgr's stdout, from which the new id is parsed and handed
 * back so the host can select it.
 */

import { useState, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { executeCommand } from '../utils/execute-command';
import { STATUS_ORDER, statusLabel, formatTitle, todoNum, PRIORITY_LEVELS, type WorkItem } from './WorkMgrPane';

// NB: WorkMgrPane's exported values must only be read at RENDER time, never at
// module top-level. WorkMgrPane imports this module and this module imports them
// back — a cycle. A top-level `Object.keys(STATUS_ORDER)` runs during module evaluation,
// before WorkMgrPane's STATUS_ORDER const is initialized, throwing a TDZ
// ReferenceError that kills the whole renderer bundle (black window). Computing it
// inside the component defers the access until after all modules have loaded.

interface NewTodoDialogProps {
  todos: WorkItem[];                 // candidate parents
  onClose: () => void;
  onCreated?: (id: string | null, status: string) => void;  // reload/select in the host
  toastFn?: (msg: string, type?: 'error' | 'info' | 'warning') => void;
}

const fieldStyle: React.CSSProperties = {
  background: 'var(--bg-deep)', border: '1px solid var(--border)', borderRadius: 5,
  color: 'var(--text)', fontSize: 12.5, padding: '6px 9px', outline: 'none', width: '100%',
};
const labelStyle: React.CSSProperties = { fontSize: 11, color: 'var(--text-muted)', marginBottom: 3, display: 'block' };

export default function NewTodoDialog({ todos, onClose, onCreated, toastFn }: NewTodoDialogProps): JSX.Element {
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [status, setStatus] = useState('Triaging');
  const [parent, setParent] = useState('');
  const [tags, setTags] = useState('');
  const [priority, setPriority] = useState('Normal');   // todo_0652
  const [busy, setBusy] = useState(false);

  // Computed at render (not module scope) to avoid the WorkMgrPane import cycle — see note above.
  const ALL_STATUSES = useMemo(
    () => Object.keys(STATUS_ORDER).sort((a, b) => STATUS_ORDER[a] - STATUS_ORDER[b]),
    [],
  );

  const parents = useMemo(
    () => [...todos].sort((a, b) => todoNum(a.id).localeCompare(todoNum(b.id), undefined, { numeric: true })),
    [todos],
  );

  const requestClose = useCallback(() => {
    if (!busy) onClose();
  }, [busy, onClose]);

  const submit = useCallback(async () => {
    if (!title.trim() || busy) return;
    setBusy(true);
    try {
      const extra: string[] = ['--status', status];
      if (parent) extra.push('--parent', parent);
      const tagList = tags.split(',').map(t => t.trim()).filter(Boolean);
      if (tagList.length) extra.push('--tags', tagList.join(','));
      if (description.trim()) extra.push('--description', description.trim());

      const res = await executeCommand<{ out: string }>('todo.create', { name: title.trim(), extra }, { onFailure: 'toast', toastFn });
      if (!res?.ok) { setBusy(false); return; }

      // todo.create returns todo_mgr stdout in data.out. Parse the authoritative id
      // instead of scanning by title (duplicate titles can exist).
      const todoId = (res.data?.out || '').match(/Created:\s*(todo_\d+(?:_[a-z0-9_]+)?)/i)?.[1] || null;
      // Priority is a separate marker, set after the todo exists (todo_0652).
      if (todoId && priority !== 'Normal') {
        await executeCommand('todo.priority', { id: todoId, level: priority }, { onFailure: 'toast', toastFn });
      }
      if (todoId) toastFn?.(`Created ${todoNum(todoId)} · ${title.trim()}`, 'info');
      else toastFn?.(`Created ${title.trim()}, but its id could not be determined.`, 'warning');
      setBusy(false);
      onCreated?.(todoId, status);
      onClose();
    } catch (err) {
      setBusy(false);
      toastFn?.(err instanceof Error ? err.message : String(err), 'error');
    }
  }, [title, description, status, parent, tags, priority, busy, toastFn, onCreated, onClose]);

  return createPortal(
    <div onClick={requestClose}
      onKeyDown={(e) => {
        if (e.key === 'Escape') { e.preventDefault(); requestClose(); }
        else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); void submit(); }
      }}
      style={{ position: 'fixed', inset: 0, background: 'color-mix(in srgb, var(--bg-deep) 70%, transparent)', zIndex: 10000, display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
      <div role="dialog" aria-modal="true" aria-labelledby="new-todo-dialog-title" onClick={(e) => e.stopPropagation()}
        style={{ background: 'var(--bg-panel, var(--bg-card))', border: '1px solid var(--border-bright, var(--border))', borderRadius: 10, padding: 16, width: 500, maxWidth: '92vw', maxHeight: '88vh', overflowY: 'auto', boxShadow: '0 12px 40px rgba(0,0,0,0.4)' }}>
        <div style={{ display: 'flex', alignItems: 'center', marginBottom: 12 }}>
          <div id="new-todo-dialog-title" style={{ fontWeight: 700, fontSize: 15, color: 'var(--text)' }}>New todo</div>
          <button onClick={requestClose} disabled={busy} style={{ marginLeft: 'auto', background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: 18, cursor: busy ? 'not-allowed' : 'pointer', lineHeight: 1 }}>✕</button>
        </div>

        <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
          <div>
            <label style={labelStyle}>Title</label>
            <input style={fieldStyle} autoFocus value={title} disabled={busy} onChange={(e) => setTitle(e.target.value)}
              placeholder="What needs doing?" />
          </div>
          <div>
            <label style={labelStyle}>Description (optional)</label>
            <textarea style={{ ...fieldStyle, minHeight: 64, resize: 'vertical' }} value={description} disabled={busy}
              onChange={(e) => setDescription(e.target.value)} placeholder="Context for future-you (goes into the todo's Description)." />
          </div>
          <div style={{ display: 'flex', gap: 8 }}>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Status</label>
              <select style={fieldStyle} value={status} disabled={busy} onChange={(e) => setStatus(e.target.value)}>
                {ALL_STATUSES.map(s => <option key={s} value={s}>{statusLabel(s)}</option>)}
              </select>
            </div>
            <div style={{ flex: 2 }}>
              <label style={labelStyle}>Parent (optional)</label>
              <select style={fieldStyle} value={parent} disabled={busy} onChange={(e) => setParent(e.target.value)}>
                <option value="">— none (top level) —</option>
                {parents.map(t => <option key={t.id} value={t.id}>{todoNum(t.id)} · {formatTitle(t).slice(0, 44)}</option>)}
              </select>
            </div>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'flex-end' }}>
            <div style={{ flex: 1 }}>
              <label style={labelStyle}>Tags (comma-separated, optional)</label>
              <input style={fieldStyle} value={tags} disabled={busy} onChange={(e) => setTags(e.target.value)} placeholder="e.g. uai, bug" />
            </div>
            <div>
              <label style={labelStyle}>Priority</label>
              <select style={fieldStyle} value={priority} disabled={busy} onChange={(e) => setPriority(e.target.value)}>
                {PRIORITY_LEVELS.map((p) => <option key={p} value={p}>{p}</option>)}
              </select>
            </div>
          </div>
        </div>

        <div style={{ display: 'flex', gap: 8, marginTop: 16, justifyContent: 'flex-end' }}>
          <button onClick={requestClose} disabled={busy} style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)', borderRadius: 6, padding: '6px 14px', fontSize: 13, cursor: busy ? 'not-allowed' : 'pointer' }}>Cancel</button>
          <button onClick={submit} disabled={!title.trim() || busy}
            style={{ background: 'var(--accent-blue-bg)', border: '1px solid var(--accent-blue)', color: 'var(--text)', borderRadius: 6, padding: '6px 16px', fontSize: 13, fontWeight: 600, cursor: title.trim() && !busy ? 'pointer' : 'not-allowed', opacity: title.trim() && !busy ? 1 : 0.5 }}>
            {busy ? 'Creating…' : 'Create todo'}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
