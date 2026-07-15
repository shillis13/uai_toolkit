import { useState, useMemo, useRef, useEffect } from 'react';
import type { CSSProperties } from 'react';
import type { SavedPrompt } from '@uai/shared/types';

/**
 * PromptLibraryPopover — the saved-prompts repository, opened from the 🔖 Library
 * button in the Prompt Box control row. Search + insert/send + save-current +
 * inline edit/delete. Self-contained (the @-mention popover is coupled to its own
 * caret-driven state machine, so this is a small sibling rather than a reuse).
 *
 * Storage is the global AppState.savedPrompts array (shared across all prompt boxes);
 * the parent owns persistence via the command bus and passes the mutators in.
 */
export interface PromptLibraryPopoverProps {
  prompts: SavedPrompt[];
  /** Current textarea draft — enables "Save current draft" and is what gets stored. */
  draft?: string;
  /** Whether Send submits (true) or stages (false) — only affects the ▸ action's tooltip. */
  autoSubmit?: boolean;
  onInsert: (body: string) => void;          // drop at cursor for editing before send
  onSend?: (body: string) => void;           // fire as-is to the current target(s)
  onSave?: (title: string, tag: string | undefined) => void;
  onUpdate?: (id: string, patch: { title?: string; body?: string; tag?: string; clearTag?: boolean }) => void;
  onDelete?: (id: string) => void;
  /** Browse mode: pure search + peek + insert. Hides save/edit/delete/send — used as the
   *  "prompt explorer" inside the AI Re-Write dialog. */
  browseOnly?: boolean;
  /** Header label + insert-action verb (default "Prompt Library" / insert-at-cursor). */
  heading?: string;
  insertLabel?: string;
  anchorStyle?: CSSProperties;
  onClose: () => void;
}

export default function PromptLibraryPopover({
  prompts, draft = '', autoSubmit = true, onInsert, onSend, onSave, onUpdate, onDelete,
  browseOnly = false, heading = '🔖 Prompt Library', insertLabel, anchorStyle, onClose,
}: PromptLibraryPopoverProps): JSX.Element {
  const allowSave = !browseOnly && !!onSave;
  const allowEdit = !browseOnly && !!onUpdate && !!onDelete;
  const allowSend = !browseOnly && !!onSend;
  const [query, setQuery] = useState('');
  const [peekId, setPeekId] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const [newTag, setNewTag] = useState('');
  const [editId, setEditId] = useState<string | null>(null);
  const [editTitle, setEditTitle] = useState('');
  const [editBody, setEditBody] = useState('');
  const [editTag, setEditTag] = useState('');
  const rootRef = useRef<HTMLDivElement>(null);
  const searchRef = useRef<HTMLInputElement>(null);

  useEffect(() => { searchRef.current?.focus(); }, []);

  // Dismiss on outside-click / Escape (Escape unwinds edit → save → close).
  useEffect(() => {
    const onDown = (e: MouseEvent) => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) onClose();
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      if (editId) setEditId(null);
      else if (saving) setSaving(false);
      else onClose();
    };
    document.addEventListener('mousedown', onDown);
    document.addEventListener('keydown', onKey);
    return () => {
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose, editId, saving]);

  const filtered = useMemo(() => {
    const list = [...prompts].sort((a, b) => (b.created || '').localeCompare(a.created || ''));
    const q = query.trim().toLowerCase();
    if (!q) return list;
    return list.filter((p) =>
      p.title.toLowerCase().includes(q) ||
      p.body.toLowerCase().includes(q) ||
      (p.tag || '').toLowerCase().includes(q));
  }, [prompts, query]);

  const hasDraft = draft.trim().length > 0;

  const commitSave = () => {
    const t = newTitle.trim();
    if (!t || !onSave) return;
    onSave(t, newTag.trim() || undefined);
    setSaving(false); setNewTitle(''); setNewTag('');
  };
  const beginEdit = (p: SavedPrompt) => {
    setEditId(p.id); setEditTitle(p.title); setEditBody(p.body); setEditTag(p.tag || '');
  };
  const commitEdit = () => {
    if (!editId || !editTitle.trim() || !onUpdate) return;
    const t = editTag.trim();
    onUpdate(editId, t
      ? { title: editTitle.trim(), body: editBody, tag: t }
      : { title: editTitle.trim(), body: editBody, clearTag: true });
    setEditId(null);
  };

  return (
    <div className="promptbox-lib-popover" ref={rootRef} role="dialog" aria-label={heading} style={anchorStyle}>
      <div className="promptbox-lib-head">
        <span className="promptbox-lib-title">{heading}</span>
        <button className="promptbox-lib-close" onClick={onClose} title="Close">{'✕'}</button>
      </div>

      <input
        ref={searchRef}
        className="promptbox-lib-search"
        placeholder="Search prompts…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />

      {allowSave && (saving ? (
        <div className="promptbox-lib-saverow">
          <input
            className="promptbox-lib-input" placeholder="Title…" value={newTitle} autoFocus
            onChange={(e) => setNewTitle(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') commitSave(); }}
          />
          <input
            className="promptbox-lib-input promptbox-lib-input-tag" placeholder="tag (optional)" value={newTag}
            onChange={(e) => setNewTag(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') commitSave(); }}
          />
          <button className="promptbox-lib-btn primary" onClick={commitSave} disabled={!newTitle.trim()}>Save</button>
          <button className="promptbox-lib-btn" onClick={() => setSaving(false)}>Cancel</button>
        </div>
      ) : (
        <button
          className="promptbox-lib-add"
          onClick={() => { setSaving(true); setNewTitle(''); setNewTag(''); }}
          disabled={!hasDraft}
          title={hasDraft ? 'Save the current draft as a reusable prompt' : 'Type something in the box first'}
        >
          {'＋'} Save current draft{'…'}
        </button>
      ))}

      <div className="promptbox-lib-list">
        {filtered.length === 0 && (
          <div className="promptbox-lib-empty">
            {prompts.length === 0
              ? (browseOnly ? 'The prompt library is empty.' : 'No saved prompts yet. Type a prompt, then “Save current draft”.')
              : 'No matches.'}
          </div>
        )}
        {filtered.map((p) => editId === p.id ? (
          <div className="promptbox-lib-editrow" key={p.id}>
            <input className="promptbox-lib-input" value={editTitle} placeholder="Title" onChange={(e) => setEditTitle(e.target.value)} />
            <textarea className="promptbox-lib-edittext" value={editBody} rows={3} onChange={(e) => setEditBody(e.target.value)} />
            <div className="promptbox-lib-editfoot">
              <input className="promptbox-lib-input promptbox-lib-input-tag" value={editTag} placeholder="tag" onChange={(e) => setEditTag(e.target.value)} />
              <button className="promptbox-lib-btn primary" onClick={commitEdit} disabled={!editTitle.trim()}>Save</button>
              <button className="promptbox-lib-btn" onClick={() => setEditId(null)}>Cancel</button>
            </div>
          </div>
        ) : (
          <div className="promptbox-lib-rowwrap" key={p.id}>
            <div className="promptbox-lib-row">
              <button
                className="promptbox-lib-rowmain"
                onClick={() => { onInsert(p.body); onClose(); }}
                title={insertLabel || 'Insert at cursor (edit before sending)'}
              >
                <span className="promptbox-lib-rowtitle">
                  {p.title}
                  {p.tag && <span className="promptbox-lib-tag">{p.tag}</span>}
                </span>
                <span className="promptbox-lib-rowpreview">{p.body.replace(/\s+/g, ' ').trim().slice(0, 90)}</span>
              </button>
              <div className="promptbox-lib-rowactions">
                <button
                  className={`promptbox-lib-act peek${peekId === p.id ? ' on' : ''}`}
                  onClick={() => setPeekId((cur) => (cur === p.id ? null : p.id))}
                  title={peekId === p.id ? 'Hide full text' : 'Peek — show the full prompt'}
                >{peekId === p.id ? '▲' : '👁'}</button>
                {allowSend && <button className="promptbox-lib-act send" onClick={() => { onSend?.(p.body); onClose(); }} title={autoSubmit ? 'Send as-is now' : 'Stage as-is now'}>{'▸'}</button>}
                {allowEdit && <button className="promptbox-lib-act edit" onClick={() => beginEdit(p)} title="Edit">{'✎'}</button>}
                {allowEdit && <button className="promptbox-lib-act danger" onClick={() => onDelete?.(p.id)} title="Delete">{'🗑'}</button>}
              </div>
            </div>
            {peekId === p.id && <pre className="promptbox-lib-peek">{p.body}</pre>}
          </div>
        ))}
      </div>
    </div>
  );
}
