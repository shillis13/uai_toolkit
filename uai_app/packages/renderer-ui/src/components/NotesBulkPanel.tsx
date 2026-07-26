/**
 * NotesBulkPanel — the Notes Mgr detail pane when MULTIPLE notes are selected
 * (todo_0559, the notes-list twin of the Work Mgr TodoBulkPanel). Replaces the
 * single-note thread view with the actions that apply to a group of notes:
 * change status, convert each to a todo, tag a session on each, add a comment to
 * each, and delete (soft-delete = archive; notes have no hard-delete verb).
 *
 * All actions operate on the passed `ids`; the host (NotesManagerPane) supplies
 * the handlers, which loop the underlying note.* commands and reload once.
 */
import { useState } from 'react';

interface SessionOption { value: string; label: string }

interface NotesBulkPanelProps {
  ids: string[];
  statuses: readonly string[];
  sessionOptions: SessionOption[];
  busy: boolean;
  onSetStatus: (status: string) => void;
  onConvert: () => void;
  onTag: (sessionId: string, sessionLabel: string) => void;
  onComment: (text: string) => void;
  onDelete: () => void;
  onClear: () => void;
}

const cap = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

export default function NotesBulkPanel({
  ids, statuses, sessionOptions, busy,
  onSetStatus, onConvert, onTag, onComment, onDelete, onClear,
}: NotesBulkPanelProps): JSX.Element {
  const [comment, setComment] = useState('');
  const [tagTarget, setTagTarget] = useState('');
  const [confirmDel, setConfirmDel] = useState(false);

  const rowStyle: React.CSSProperties = { display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' };
  const labelStyle: React.CSSProperties = { fontSize: 12, color: 'var(--text-sec)', minWidth: 120 };
  const selectStyle: React.CSSProperties = { fontSize: 12, padding: '3px 8px', background: 'var(--bg-deep)', color: 'var(--text)', border: '1px solid var(--border-strong)', borderRadius: 4, minWidth: 180 };
  const btnStyle: React.CSSProperties = { fontSize: 12, fontWeight: 700, padding: '4px 12px', borderRadius: 5, border: '1px solid var(--accent-blue)', background: 'transparent', color: 'var(--accent-blue)', cursor: 'pointer' };
  const dangerBtn: React.CSSProperties = { ...btnStyle, border: '1px solid var(--accent-red)', color: 'var(--accent-red)' };

  return (
    <div style={{ padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 14, overflowY: 'auto' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
        <span style={{ fontSize: 14, fontWeight: 700, color: 'var(--text)' }}>{ids.length} notes selected</span>
        <button style={{ ...btnStyle, borderColor: 'var(--border-strong)', color: 'var(--text-sec)' }} onClick={onClear}>Clear selection</button>
      </div>

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
        {ids.map((id) => (
          <span key={id} style={{ fontSize: 10.5, fontFamily: 'var(--font-mono)', color: 'var(--accent-cyan)', background: 'var(--bg-deep)', border: '1px solid var(--border)', borderRadius: 4, padding: '1px 6px' }}>
            {(id.match(/^(?:note)_\d+/) || [id])[0]}
          </span>
        ))}
      </div>

      <div style={rowStyle}>
        <label style={labelStyle}>Change status</label>
        <select style={selectStyle} value="" disabled={busy} onChange={(e) => { if (e.target.value) onSetStatus(e.target.value); }}>
          <option value="">— set all to —</option>
          {statuses.map((s) => <option key={s} value={s}>{cap(s)}</option>)}
        </select>
      </div>

      <div style={rowStyle}>
        <label style={labelStyle}>Tag session (on each)</label>
        <select style={selectStyle} value={tagTarget} disabled={busy} onChange={(e) => setTagTarget(e.target.value)}>
          <option value="">— pick a session —</option>
          {sessionOptions.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
        </select>
        <button
          style={btnStyle}
          disabled={busy || !tagTarget}
          onClick={() => {
            const label = sessionOptions.find((o) => o.value === tagTarget)?.label || tagTarget;
            onTag(tagTarget, label);
            setTagTarget('');
          }}
        >
          Tag all {ids.length}
        </button>
      </div>

      <div style={rowStyle}>
        <label style={labelStyle}>Convert to todos</label>
        <button style={btnStyle} disabled={busy} onClick={onConvert}>Create {ids.length} todos</button>
        <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>one todo per note, linked back</span>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        <label style={labelStyle}>Add comment (to each)</label>
        <textarea style={{ ...selectStyle, minWidth: 0, width: '100%', minHeight: 52, resize: 'vertical' }} value={comment} placeholder="Comment appended to every selected note…" disabled={busy}
          onChange={(e) => setComment(e.target.value)} />
        <div><button style={btnStyle} disabled={busy || !comment.trim()} onClick={() => { onComment(comment.trim()); setComment(''); }}>Add to all {ids.length}</button></div>
      </div>

      <div style={{ ...rowStyle, marginTop: 4, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
        {confirmDel ? (
          <>
            <span style={{ fontSize: 12, color: 'var(--text)' }}>Archive (soft-delete) {ids.length} notes?</span>
            <button style={dangerBtn} disabled={busy} onClick={() => { onDelete(); setConfirmDel(false); }}>Archive</button>
            <button style={{ ...btnStyle, borderColor: 'var(--border-strong)', color: 'var(--text-sec)' }} onClick={() => setConfirmDel(false)}>Cancel</button>
          </>
        ) : (
          <button style={dangerBtn} disabled={busy} onClick={() => setConfirmDel(true)}>Delete (archive) selected ({ids.length})</button>
        )}
      </div>
    </div>
  );
}
