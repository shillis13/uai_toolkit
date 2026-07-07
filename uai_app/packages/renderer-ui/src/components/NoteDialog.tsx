/**
 * NoteDialog — the ubiquitous note-capture dialog.
 *
 * Add Note and Ask Hamilton are ONE primitive over the same notes backend
 * (scripts/notes/notes_mgr.py via the note.* commands). This single dialog
 * backs both:
 *   - mode='note'         → capture, recipient defaults to PM (self/PianoMan).
 *   - mode='ask-hamilton' → same capture, recipient preset to Hamilton, titled
 *                           "Ask Hamilton". Surfaced from the Tier-1 pill.
 *
 * Rendered as a floating portal overlay (mirrors BriefDialog's createPortal
 * pattern) with inline styles matching the dark theme used by LiveBoardPane.
 *
 * On submit it calls note.create. If a `subjectSession` (a specific session's
 * turn) was supplied, it follows with note.addMessage binding the body to that
 * turn via reply-to `turn:<trackingId>:<transcript>:<turn>`.
 */

import { useState, useEffect, useRef, useMemo, useCallback } from 'react';
import { createPortal } from 'react-dom';
import { executeCommand } from '../utils/execute-command';
import { ViewportRegistry } from '../viewport';
import type { ViewportNode } from '@contracts/viewport';
import { useSessionStore } from '../stores/session-store';
import { useMention, MentionPopover, makeRecipientSource } from './mention';
import CaptureComponentPicker from './CaptureComponentPicker';

// @-token for a session name (quote if it contains whitespace) — matches PromptBox.
function mentionToken(name: string): string {
  return /\s/.test(name) ? `"${name}"` : name;
}

export type NoteDialogMode = 'note' | 'ask-hamilton';

// ── Viewport capture helpers (Component 6: [Capture Content]) ──────────────
// A capture is a (possibly trimmed) ViewportNode subtree grabbed on demand from
// the live component tree. The tree IS the selection tree — the user captures
// the current view, then sheds subtrees they don't want ("trim").

function countNodes(n: ViewportNode): number {
  return 1 + n.children.reduce((s, c) => s + countNodes(c), 0);
}

/** Drop children that aren't actually visible (closed menus, hidden panes).
 * The spec captures "what's ACTUALLY visible" — invisible reporters are noise. */
function pruneInvisible(node: ViewportNode): ViewportNode {
  return {
    ...node,
    children: node.children.filter((c) => c.visible).map(pruneInvisible),
  };
}

/** Immutably remove the node at `path` (array of child indices) from `root`. */
function pruneAt(root: ViewportNode, path: number[]): ViewportNode {
  if (path.length === 0) return root; // root is removed by dropping the whole capture
  const [i, ...rest] = path;
  const children = root.children.slice();
  if (rest.length === 0) {
    children.splice(i, 1);
  } else if (children[i]) {
    children[i] = pruneAt(children[i], rest);
  }
  return { ...root, children };
}

export interface NoteSubjectSession {
  trackingId: string;
  transcript: string;
  turn: number | string;
}

interface NoteDialogProps {
  isOpen: boolean;
  onClose: () => void;
  mode?: NoteDialogMode;
  /** UAI tab that was active when capture began — stored on the note meta. */
  sourceTab?: string;
  /** Optional binding to a specific session turn (Ask-Hamilton-from-a-turn). */
  subjectSession?: NoteSubjectSession;
  /** Fired after a successful create with the new note id. */
  onCreated?: (noteId: string) => void;
  /** When set, the dialog EDITS this existing (draft) note instead of creating a
   *  new one — prefills the title/body; on save it updates the note and finalizes
   *  it (draft → open), or re-saves it as a draft. */
  editNote?: { id: string; title: string; text: string } | null;
}

// note.create returns the raw notes_mgr `create` payload: { success, id, ... }.
interface NoteCreateResult {
  success?: boolean;
  id?: string;
}

// Each mode gets a SATURATED, distinct identity so the floating dialog reads as
// its own colored card over the app — not a tint on the same near-black. Add
// Note = blue; Ask Hamilton = violet. `bg` (the card body) and `headerBg` (a
// solid color band) are deliberately far from the app's neutral #0c0e14.
const NOTE_THEME = {
  headerBg: 'var(--accent-blue-solid)', headerText: '#ffffff', headerSub: 'rgba(255,255,255,0.88)',
  bg: 'var(--overlay-note-bg)', panel: 'var(--bg-deep)', border: 'var(--border)', borderStrong: 'var(--overlay-note-border)',
  text: 'var(--text)', textDim: 'var(--text-sec)', accent: 'var(--accent-blue)', accentBg: 'var(--accent-blue-bg)', accentText: 'var(--text)',
};
const HAMILTON_THEME = {
  headerBg: 'var(--accent-purple-solid)', headerText: '#ffffff', headerSub: 'rgba(255,255,255,0.88)',
  bg: 'var(--overlay-hamilton-bg)', panel: 'var(--bg-deep)', border: 'var(--border)', borderStrong: 'var(--overlay-hamilton-border)',
  text: 'var(--text)', textDim: 'var(--text-sec)', accent: 'var(--accent-purple)', accentBg: 'var(--bg-hover)', accentText: 'var(--text)',
};

// Draft persistence for the note body, per mode (note | ask-hamilton). The draft
// survives ANY close (ESC, ✕, click-away, app nav) EXCEPT an explicit Save
// (successful create) or Cancel — those two clear it.
const NOTE_DRAFT_PREFIX = 'uai:noteDraft:';
function getNoteDraft(mode: NoteDialogMode): string {
  try { return localStorage.getItem(NOTE_DRAFT_PREFIX + mode) || ''; } catch { return ''; }
}
function saveNoteDraft(mode: NoteDialogMode, text: string): void {
  try {
    if (text) localStorage.setItem(NOTE_DRAFT_PREFIX + mode, text);
    else localStorage.removeItem(NOTE_DRAFT_PREFIX + mode);
  } catch { /* storage unavailable — draft simply won't persist */ }
}
function clearNoteDraft(mode: NoteDialogMode): void {
  try { localStorage.removeItem(NOTE_DRAFT_PREFIX + mode); } catch { /* ignore */ }
}

export default function NoteDialog({
  isOpen,
  onClose,
  mode = 'note',
  sourceTab,
  subjectSession,
  onCreated,
  editNote,
}: NoteDialogProps): JSX.Element | null {
  const askHamilton = mode === 'ask-hamilton';
  const T = askHamilton ? HAMILTON_THEME : NOTE_THEME;

  const [text, setText] = useState('');
  const [title, setTitle] = useState('');
  const [forPM, setForPM] = useState(!askHamilton);
  const [forHamilton, setForHamilton] = useState(askHamilton);
  // "Add Note or Todo": also spin a todo off this note (linked both ways).
  // What to create on submit — a note, a todo, or both. Create Note defaults on.
  const [createNote, setCreateNote] = useState(true);
  const [createTodo, setCreateTodo] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Captured view subtrees, each attached to the note on submit.
  const [captures, setCaptures] = useState<ViewportNode[]>([]);
  // Nodes whose state fields are expanded in the outline (key = captureIdx:path).
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  // Floating-window position (null → default top-center). Draggable by the header.
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);
  const dragRef = useRef<{ dx: number; dy: number } | null>(null);
  // Component-picker drawer (drill down + multi-select what to capture).
  const [pickerOpen, setPickerOpen] = useState(false);

  // ── @-autocomplete for the note body (same reusable ./mention as the thread) ──
  // Without this, typing "@Prism" in Add Note / Ask Hamilton was plain text with
  // no picker — the @notify on submit still fired, but the user had to spell the
  // name exactly. The popover resolves against live sessions.
  const { sessions } = useSessionStore();
  const bodyRef = useRef<HTMLTextAreaElement>(null);
  const mentionTargets = useMemo(
    () => sessions
      .filter((s) => !s.archived && s.display_name)
      .map((s) => {
        const name = s.display_name || s.tracking_id;
        return { token: mentionToken(name), label: name, kind: 'session' as const, count: 1, memberIds: [s.tracking_id] };
      }),
    [sessions],
  );
  const mentionTargetsRef = useRef(mentionTargets);
  mentionTargetsRef.current = mentionTargets;
  const mentionSources = useMemo(() => [makeRecipientSource(() => mentionTargetsRef.current)], []);
  const commitBodyMention = useCallback((next: string, caret: number) => {
    setText(next);
    saveNoteDraft(mode, next);
    requestAnimationFrame(() => { const ta = bodyRef.current; ta?.focus(); ta?.setSelectionRange(caret, caret); });
  }, [mode]);
  const mention = useMention({ textareaRef: bodyRef, sources: mentionSources, onApply: commitBodyMention });

  // Reset fields whenever the dialog (re)opens, applying the mode defaults.
  const [prevOpen, setPrevOpen] = useState(false);
  if (isOpen && !prevOpen) {
    setPrevOpen(true);
    // Editing an existing draft prefills its title/body; otherwise restore any
    // persisted per-mode draft text for a fresh note.
    setText(editNote ? editNote.text : getNoteDraft(mode));
    setTitle(editNote ? editNote.title : '');
    setForPM(!askHamilton);
    setForHamilton(askHamilton);
    setSubmitting(false);
    setError(null);
    setCaptures([]);
    setExpanded(new Set());
    setPos(null);
    setPickerOpen(false);
    // Editing an existing draft is always a note; a fresh open defaults to
    // Create Note on, Create todo off.
    setCreateNote(true);
    setCreateTodo(false);
  } else if (!isOpen && prevOpen) {
    setPrevOpen(false);
  }

  // [Capture Content]: snapshot the live view via the viewport registry. Grabs
  // the whole app tree; the user then trims subtrees they don't want.
  const handleCaptureView = () => {
    try {
      const tree = pruneInvisible(ViewportRegistry.describeViewport('app'));
      setCaptures((prev) => [...prev, tree]);
    } catch (e) {
      setError(`Capture failed: ${e instanceof Error ? e.message : String(e)}`);
    }
  };

  // Live, visibility-pruned tree for the picker drawer (snapshotted on open).
  const snapshotTree = () => pruneInvisible(ViewportRegistry.describeViewport('app'));
  // Picker "Add selected" → append each chosen subtree as its own capture, so
  // they flow through the same trim UI as a full capture.
  const addPickedCaptures = (nodes: ViewportNode[]) => {
    setCaptures((prev) => [...prev, ...nodes]);
  };

  // Which nodes have their state fields expanded (key = captureIdx:path).
  const toggleExpanded = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  const pruneCapture = (captureIdx: number, path: number[]) => {
    setCaptures((prev) =>
      prev.map((c, i) => (i === captureIdx ? pruneAt(c, path) : c)),
    );
  };

  const removeCapture = (captureIdx: number) => {
    setCaptures((prev) => prev.filter((_, i) => i !== captureIdx));
  };

  // ESC closes.
  useEffect(() => {
    if (!isOpen) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [isOpen, onClose]);

  if (!isOpen) return null;

  const recipients: string[] = [];
  if (forPM) recipients.push('PM');
  if (forHamilton) recipients.push('Hamilton');

  // A note needs a body + a recipient; a todo needs a body OR a title. Submit is
  // enabled when at least one of Create Note / Create todo is checked AND each
  // checked target is valid. A DRAFT save is note-only and lenient (title or body).
  const noteOk = text.trim().length > 0 && recipients.length > 0;
  const todoOk = text.trim().length > 0 || title.trim().length > 0;
  const canSubmit = !submitting
    && (createNote || createTodo)
    && (!createNote || noteOk)
    && (!createTodo || todoOk);
  const canDraft = createNote && (text.trim().length > 0 || title.trim().length > 0) && !submitting;

  const handleSubmit = () => finalize(false);

  // Save the note — as a finished note (asDraft=false) or a draft (asDraft=true).
  // Editing an existing draft UPDATES it (body/title/status); a fresh note is
  // created with the right status. Drafts skip the @notify + alsoTodo side effects
  // (those belong to a finished note), but keep their captures.
  const finalize = async (asDraft: boolean) => {
    if (asDraft ? !canDraft : !canSubmit) return;
    setSubmitting(true);
    setError(null);

    let noteId: string | null = null;

    // ── Note ── (when Create Note is checked)
    if (createNote) {
      if (editNote) {
        // Update the existing (draft) note in place, then set its status.
        await executeCommand('note.edit', { id: editNote.id, text: text.trim() }, { onFailure: 'log' });
        await executeCommand('note.setTitle', { id: editNote.id, title: title.trim() }, { onFailure: 'log' });
        await executeCommand('note.setStatus', { id: editNote.id, status: asDraft ? 'draft' : 'open' }, { onFailure: 'log' });
        noteId = editNote.id;
      } else {
        const res = await executeCommand<{ note: NoteCreateResult }>(
          'note.create',
          {
            text: text.trim(),
            recipients,
            status: asDraft ? 'draft' : 'open',
            ...(title.trim() ? { title: title.trim() } : {}),
            ...(sourceTab ? { sourceTab } : {}),
          },
          { onFailure: 'log' },
        );
        if (!res.ok || !res.data?.note?.id) {
          setError(res.error?.message || (asDraft ? 'Failed to save draft' : 'Failed to create note'));
          setSubmitting(false);
          return;
        }
        noteId = res.data.note.id;
      }

      // Bind the body to a specific session turn, if launched against one.
      if (!asDraft && !editNote && subjectSession) {
        const replyTo = `turn:${subjectSession.trackingId}:${subjectSession.transcript}:${subjectSession.turn}`;
        await executeCommand('note.addMessage',
          { id: noteId, author: 'PianoMan', body: text.trim(), replyTo }, { onFailure: 'log' });
      }

      // Attach any captured (trimmed) view subtrees.
      for (const cap of captures) {
        await executeCommand('note.addCapture',
          { id: noteId, componentPath: cap.label || cap.id, ...(sourceTab ? { sourceTab } : {}), data: JSON.stringify(cap) },
          { onFailure: 'log' });
      }

      // Notify @-mentioned sessions — a FINISHED note only (a draft shouldn't nudge).
      if (!asDraft) {
        const bare = (text.match(/@([A-Za-z0-9_-]{2,})/g) || []).map((s) => s.slice(1));
        const quoted = (text.match(/@"([^"]+)"/g) || []).map((s) => s.slice(2, -1));
        const targets = Array.from(new Set([
          ...bare, ...quoted, ...(forHamilton ? ['Hamilton'] : []),
        ].map((t) => t.trim()).filter(Boolean)));
        for (const name of targets) {
          const content =
            `You've been named in a new note ${noteId}` +
            (title.trim() ? ` — "${title.trim()}"` : '') + `:\n\n` +
            `${text.trim().slice(0, 500)}\n\n` +
            `Open it in the UAI Notes Mgr, or read via workflow_note_read(identifier="${noteId}").`;
          await executeCommand('comms.send',
            { from: 'piano_man', to: name, content, urgency: 'prompt', subject: `Note ${noteId}` }, { onFailure: 'log' });
        }
      }
    }

    // ── Todo ── (when Create todo is checked; not for a bare draft-save). Carries
    // the body into the todo's notes.md; links to the note when one was created.
    if (createTodo && !asDraft) {
      const todoName = (title.trim() || text.trim().split('\n')[0] || 'Untitled').slice(0, 80);
      const created = await executeCommand<{ out: string }>('todo.create', { name: todoName }, { onFailure: 'log' });
      const todoId = (created.data?.out || '').match(/Created:\s*(todo_\d+\S*)/)?.[1];
      if (todoId) {
        const backref = noteId ? `\n\n— converted from ${noteId}\n` : '\n';
        await executeCommand('todo.writeNotes',
          { id: todoId, content: `${text.trim()}${backref}` }, { onFailure: 'log' });
        if (noteId) await executeCommand('note.linkTodo', { id: noteId, todo: todoId }, { onFailure: 'log' });
      }
    }

    setSubmitting(false);
    clearNoteDraft(mode);  // successful Save clears the draft
    if (noteId) onCreated?.(noteId);
    onClose();
  };

  // Drag the floating panel by its header. Window-level listeners so the drag
  // continues even if the cursor outruns the panel.
  const onDragStart = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = (e.currentTarget.closest('[data-note-dialog]') as HTMLElement | null)?.getBoundingClientRect();
    const startX = rect ? rect.left : e.clientX;
    const startY = rect ? rect.top : e.clientY;
    dragRef.current = { dx: e.clientX - startX, dy: e.clientY - startY };
    const onMove = (ev: MouseEvent) => {
      if (!dragRef.current) return;
      setPos({ x: ev.clientX - dragRef.current.dx, y: ev.clientY - dragRef.current.dy });
    };
    const onUp = () => {
      dragRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  };

  const checkboxRow = (
    label: string,
    checked: boolean,
    onChange: (v: boolean) => void,
  ): JSX.Element => (
    <label
      style={{
        display: 'flex', alignItems: 'center', gap: 7, fontSize: 13,
        color: T.text, cursor: 'pointer', userSelect: 'none',
      }}
    >
      <input type="checkbox" checked={checked} onChange={(e) => onChange(e.target.checked)} style={{ margin: 0 }} />
      {label}
    </label>
  );

  // Recursive outline of a captured subtree. Shows the component id (primary)
  // plus its label (secondary), an expandable list of its state fields, and a
  // trim (✕) control on every non-root node.
  const renderNode = (node: ViewportNode, path: number[], captureIdx: number): JSX.Element => {
    const stateKeys = node.state ? Object.keys(node.state) : [];
    const actionCount = node.actions?.length ?? 0;
    const hasDetail = stateKeys.length > 0 || actionCount > 0;
    const rowKey = `${captureIdx}:${path.join('.')}`;
    const isExp = expanded.has(rowKey);
    const isRoot = path.length === 0;
    // Each component LAYER (nesting depth) gets its own accent, so the tree reads
    // as colored strata (app → workspace → pane → sub-component → …).
    const LAYER_COLORS = [
      'var(--accent-blue)', 'var(--accent-green)', 'var(--accent-yellow)',
      'var(--accent-purple)', 'var(--accent-cyan)', 'var(--accent-orange)',
    ];
    const layerColor = LAYER_COLORS[path.length % LAYER_COLORS.length];
    return (
      <div key={path.join('.') || 'root'} style={{ marginLeft: path.length ? 11 : 0, borderLeft: path.length ? `2px solid ${layerColor}` : 'none', paddingLeft: path.length ? 6 : 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 5, padding: '1px 0' }}>
          {/* Expand/collapse chevron on the LEFT — the natural disclosure target.
              Bigger (was 9px) so it's an easy, unambiguous click. `hasDetail`
              includes state OR actions, so nodes carrying actions are expandable. */}
          {hasDetail ? (
            <button
              onClick={() => toggleExpanded(rowKey)}
              title="Show captured fields"
              style={{
                background: 'transparent', border: 'none', color: 'var(--text-sec)',
                cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: 0, width: 16, textAlign: 'center',
              }}
            >
              {isExp ? '▾' : '▸'}
            </button>
          ) : (
            <span style={{ width: 16, display: 'inline-block' }} />
          )}
          <span style={{ color: layerColor, fontSize: 11.5, fontWeight: 600 }}>{node.id}</span>
          {node.label && node.label !== node.id && (
            <span style={{ color: T.textDim, fontSize: 11 }}>{'· '}{node.label}</span>
          )}
          {(stateKeys.length > 0 || actionCount > 0) && (
            <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>
              {stateKeys.length > 0 && `${stateKeys.length} field${stateKeys.length > 1 ? 's' : ''}`}
              {stateKeys.length > 0 && actionCount > 0 && ', '}
              {actionCount > 0 && `${actionCount} action${actionCount > 1 ? 's' : ''}`}
            </span>
          )}
          {/* Delete control pushed to the far RIGHT (marginLeft:auto) so it never
              sits under the chevron — indenting it there risked mis-clicking an ✕
              instead of expand/collapse. Gray (not alarming); every node has one. */}
          <button
            onClick={() => (isRoot ? removeCapture(captureIdx) : pruneCapture(captureIdx, path))}
            title={isRoot ? 'Remove this whole capture' : 'Remove this item from the capture'}
            style={{
              marginLeft: 'auto',
              background: 'transparent', border: 'none', color: 'var(--text-muted)',
              cursor: 'pointer', fontSize: 12, padding: '0 4px', fontWeight: 700, lineHeight: 1,
            }}
          >
            {'✕'}
          </button>
        </div>
        {isExp && (stateKeys.length > 0 || actionCount > 0) && (
          <div style={{ marginLeft: 24, marginBottom: 2 }}>
            {stateKeys.map((k) => (
              <div key={k} style={{ color: 'var(--text-sec)', fontSize: 10.5, lineHeight: 1.45 }}>
                <span style={{ color: 'var(--text-muted)' }}>{k}:</span>{' '}
                {JSON.stringify((node.state as Record<string, unknown>)[k]).slice(0, 90)}
              </div>
            ))}
            {/* Actions are captured too — surface them so nothing is silently
                hidden (note_0033 #4: "data included that doesn't show"). */}
            {(node.actions || []).map((a, ai) => (
              <div key={`act${ai}`} style={{ color: 'var(--text-sec)', fontSize: 10.5, lineHeight: 1.45 }}>
                <span style={{ color: 'var(--accent-orange)' }}>⚡ action:</span>{' '}
                {a.label || a.id}{a.command ? <span style={{ color: 'var(--text-muted)' }}>{` → ${a.command}`}</span> : null}
              </div>
            ))}
          </div>
        )}
        {node.children.map((c, i) => renderNode(c, [...path, i], captureIdx))}
      </div>
    );
  };

  // Non-blocking floating panel: NO full-screen backdrop (the app stays fully
  // interactive behind it), draggable by the header, always on top.
  return createPortal(
    <div
      data-note-dialog
      style={{
        position: 'fixed',
        left: pos ? pos.x : '50%',
        top: pos ? pos.y : '12vh',
        transform: pos ? 'none' : 'translateX(-50%)',
        // Resizable: drag the bottom-right corner to grow the whole dialog. Body
        // scrolls; header/footer stay put.
        width: 480, height: 600,
        minWidth: 380, minHeight: 340, maxWidth: '95vw', maxHeight: '92vh',
        resize: 'both', overflow: 'hidden',
        display: 'flex', flexDirection: 'column',
        background: T.bg, border: `2px solid ${T.borderStrong}`, borderRadius: 10,
        boxShadow: `0 18px 55px rgba(0,0,0,0.6), 0 0 0 1px ${T.borderStrong}, 0 6px 26px color-mix(in srgb, ${T.headerBg} 45%, transparent)`,
        color: T.text, fontSize: 13,
        zIndex: 11000,
      }}
    >
      {/* Header — a solid saturated color band (drag handle + close) */}
      <div
        onMouseDown={onDragStart}
        style={{
          padding: '13px 16px', background: T.headerBg,
          borderRadius: '8px 8px 0 0', flexShrink: 0,
          cursor: 'move', userSelect: 'none',
          display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 10,
        }}
      >
        <div>
          <div style={{ fontWeight: 800, color: T.headerText, fontSize: 15, letterSpacing: '.01em' }}>
            {askHamilton ? 'Ask Hamilton' : editNote ? 'Edit Draft' : 'Add Note'}
          </div>
          <div style={{ color: T.headerSub, fontSize: 11, marginTop: 2 }}>
            {askHamilton
              ? 'Capture a note routed to Hamilton.'
              : 'Capture a note. Defaults to you (PM).'}
            {subjectSession ? ` — re: ${subjectSession.trackingId} #${subjectSession.turn}` : ''}
          </div>
        </div>
        <button
          onClick={onClose}
          onMouseDown={(e) => e.stopPropagation()}
          title="Close"
          style={{
            background: 'rgba(255,255,255,0.18)', border: 'none', color: T.headerText,
            cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: '2px 7px', borderRadius: 5,
          }}
        >
          {'✕'}
        </button>
      </div>

        {/* Body — scrolls; the dialog grows via the resize handle. */}
        <div style={{ padding: '14px 16px', display: 'flex', flexDirection: 'column', gap: 12, flex: 1, overflowY: 'auto', minHeight: 0 }}>
          <input
            value={title}
            onChange={(e) => setTitle(e.target.value)}
            placeholder="Title / subject (optional)"
            style={{
              width: '100%', boxSizing: 'border-box',
              background: T.panel, color: T.text,
              border: `1px solid ${T.border}`, borderRadius: 6,
              padding: '8px 11px', fontSize: 13, fontFamily: 'inherit', fontWeight: 600,
            }}
          />
          <textarea
            autoFocus
            ref={bodyRef}
            value={text}
            onChange={(e) => { setText(e.target.value); saveNoteDraft(mode, e.target.value); mention.sync(e.target.value, e.target.selectionStart ?? e.target.value.length); }}
            placeholder={askHamilton ? 'What do you want to ask Hamilton?  (@ to mention)' : 'Note body…  (@ to mention)'}
            rows={6}
            style={{
              width: '100%', boxSizing: 'border-box', resize: 'vertical',
              background: T.panel, color: T.text,
              border: `1px solid ${T.border}`, borderRadius: 6,
              padding: '9px 11px', fontSize: 13, fontFamily: 'inherit', lineHeight: 1.5,
            }}
            onKeyDown={(e) => {
              if (mention.handleKeyDown(e)) return;
              if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') {
                e.preventDefault();
                void handleSubmit();
              }
            }}
          />
          <MentionPopover state={mention} />

          {/* [Capture Content] — snapshot the live view, then trim subtrees. */}
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <button
                onClick={handleCaptureView}
                title="Capture the current view's structured state (component tree)"
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  background: T.panel, border: `1px solid ${T.border}`, color: T.accentText,
                  borderRadius: 6, padding: '5px 11px', fontSize: 12, cursor: 'pointer', fontWeight: 600,
                }}
              >
                <span style={{ color: 'var(--accent-blue)' }}>{'📎'}</span> Capture view
              </button>
              <button
                onClick={() => setPickerOpen((v) => !v)}
                title="Drill down and multi-select just the components you want"
                style={{
                  display: 'inline-flex', alignItems: 'center', gap: 6,
                  background: pickerOpen ? 'var(--accent-blue)' : T.panel,
                  border: `1px solid var(--accent-blue)`, color: pickerOpen ? 'var(--bg-deep)' : T.accentText,
                  borderRadius: 6, padding: '5px 11px', fontSize: 12, cursor: 'pointer', fontWeight: 600,
                }}
              >
                <span style={{ color: pickerOpen ? 'var(--bg-deep)' : 'var(--accent-blue)' }}>{'⛃'}</span> Pick components{pickerOpen ? ' ▸' : '…'}
              </button>
              {captures.length > 0 && (
                <span style={{ color: T.textDim, fontSize: 11 }}>
                  {captures.length} capture{captures.length > 1 ? 's' : ''} — trim below
                </span>
              )}
            </div>

            {captures.length > 0 && (
              <div style={{ marginTop: 8, display: 'flex', flexDirection: 'column', gap: 8 }}>
                {captures.map((cap, ci) => (
                  <div key={ci} style={{ border: `1px solid ${T.border}`, borderRadius: 6, background: T.panel }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 9px', borderBottom: `1px solid ${T.border}` }}>
                      <span style={{ color: T.accentText, fontSize: 11.5, fontWeight: 600 }}>
                        {cap.label || cap.id}
                      </span>
                      <span style={{ color: T.textDim, fontSize: 10.5 }}>{countNodes(cap)} nodes</span>
                      <button
                        onClick={() => removeCapture(ci)}
                        style={{
                          marginLeft: 'auto', background: 'transparent', border: `1px solid ${T.border}`,
                          color: T.textDim, borderRadius: 5, padding: '2px 8px', fontSize: 10.5, cursor: 'pointer',
                        }}
                      >
                        Remove
                      </button>
                    </div>
                    <div style={{ maxHeight: 320, overflow: 'auto', padding: '6px 9px' }}>
                      {renderNode(cap, [], ci)}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>

          <div style={{ display: 'flex', gap: 18 }}>
            {checkboxRow('For PM', forPM, setForPM)}
            {checkboxRow('For Hamilton', forHamilton, setForHamilton)}
            {checkboxRow('Create Note', createNote, setCreateNote)}
            {checkboxRow('Create todo', createTodo, setCreateTodo)}
          </div>

          {recipients.length === 0 && (
            <div style={{ color: 'var(--accent-orange)', fontSize: 11 }}>Pick at least one recipient.</div>
          )}
          {error && (
            <div style={{ color: 'var(--accent-orange)', fontSize: 12 }}>{'⚠'} {error}</div>
          )}
        </div>

        {/* Footer */}
        <div
          style={{
            display: 'flex', justifyContent: 'flex-end', gap: 9, flexShrink: 0,
            padding: '12px 16px', borderTop: `1px solid ${T.border}`,
          }}
        >
          <button
            onClick={() => { clearNoteDraft(mode); onClose(); }}
            style={{
              background: 'transparent', border: `1px solid ${T.border}`, color: T.textDim,
              borderRadius: 6, padding: '6px 13px', fontSize: 12, cursor: 'pointer',
            }}
          >
            Cancel
          </button>
          {/* Save as Draft — parks the note (title/body) in the list marked
              "draft"; reopen it here later. Ask-Hamilton isn't drafted (it's a
              send action), so only offer this in note mode. */}
          {!askHamilton && createNote && (
            <button
              onClick={() => finalize(true)}
              disabled={!canDraft}
              title="Save as a draft — appears in the list marked 'draft'; reopens here to finish"
              style={{
                background: 'transparent', border: `1px solid ${canDraft ? T.accent : T.border}`,
                color: canDraft ? T.accentText : T.textDim,
                borderRadius: 6, padding: '6px 13px', fontSize: 12,
                cursor: canDraft ? 'pointer' : 'default', fontWeight: 600,
              }}
            >
              {submitting ? '…' : 'Save as Draft'}
            </button>
          )}
          <button
            onClick={handleSubmit}
            disabled={!canSubmit}
            style={{
              background: canSubmit ? T.accentBg : 'var(--bg-hover)',
              border: `1px solid ${canSubmit ? T.accent : T.border}`,
              color: canSubmit ? T.accentText : T.textDim,
              borderRadius: 6, padding: '6px 14px', fontSize: 12,
              cursor: canSubmit ? 'pointer' : 'default', fontWeight: 600,
            }}
          >
            {submitting ? 'Saving…'
              : askHamilton ? 'Send to Hamilton'
              : createNote && createTodo ? (editNote ? 'Finalize Note + Todo' : 'Save Note + Todo')
              : createNote ? (editNote ? 'Finalize Note' : 'Save Note')
              : createTodo ? 'Create Todo'
              : 'Save'}
          </button>
        </div>

        {/* Pull-out picker drawer — drill down + multi-select components to
            capture. Docks to the right edge inside the panel. */}
        <CaptureComponentPicker
          open={pickerOpen}
          theme={{ panel: T.panel, border: T.border, text: T.text, textDim: T.textDim, accentText: T.accentText }}
          getTree={snapshotTree}
          onAdd={addPickedCaptures}
          onClose={() => setPickerOpen(false)}
        />
      </div>,
    document.body,
  );
}
