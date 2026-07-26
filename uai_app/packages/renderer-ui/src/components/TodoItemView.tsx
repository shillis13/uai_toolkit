/**
 * TodoItemView — the ONE shared todo-item detail, used identically by:
 *   • Work Mgr                     (WorkMgrPane)
 *   • Session ▸ Work ▸ Work List   (ProjectEditor, session worker)
 *   • Project/Team ▸ Work List     (ProjectEditor, project/team worker)
 *
 * Subtabs (PianoMan's spec): Contents · Activities · Related · Files.
 *   Contents  — parent path · reformatted notes.md (no Created/Updated/Status) ·
 *               Provenance · Open Questions & Recommendations · Decisions & Pivots
 *   Activities — History · Comms / Chat comments · Reviews
 *   Related    — Children · Artifacts
 *   Files      — folder hierarchy + file preview (git view later; binary = no preview)
 *
 * Self-contained: fetches notes/provenance/files via window.uai.todos.*. The caller
 * supplies the (optional) Status + Assigned editors so each host keeps its own controls.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import type { ReactNode } from 'react';
import { useViewport } from '../viewport';
import ProjectFolderTree, { type FsEntry } from './ProjectFolderTree';
import SessionLink, { LinkifySessions, trackingIdFrom } from './SessionLink';
import { executeCommand } from '../utils/execute-command';
import { assigneeLabel } from './assigneeLabel';
import { notifyTodosChanged } from '../utils/todo-events';
import MarkdownBlock from './MarkdownBlock';
import GitFileViewPane from './GitFileViewPane';
import type { GitFileViewFilter } from './git-file-view-scope';

export interface TodoLite {
  id: string; name?: string; title?: string; dirName?: string; status: string;
  tags?: string[]; flags?: string[]; assigned?: string[]; project?: string | null;
  parent?: string | null; children?: string[]; created?: string; updated?: string;
  path?: string; rel_path?: string;
}

const STATUS_COLORS: Record<string, string> = {
  In_Progress: 'var(--accent-blue)', Blocked: 'var(--accent-red)', Reviewing: 'var(--accent-purple)',
  Accepting: 'var(--accent-cyan)', Ready: 'var(--accent-green)', Needs_Derivation: 'var(--accent-yellow)',
  Needs_Research: 'var(--accent-orange)', Triaging: 'var(--text-sec, #b8c0cc)', Done: 'var(--pe-done, #55607a)',
  Cancelled: 'var(--text-muted)',
};
const statusColor = (s: string) => STATUS_COLORS[s] || 'var(--text-muted)';
const statusLabel = (s: string) => (s || '').replace(/_/g, ' ');
const todoNum = (id: string) => (id.match(/(\d+)/)?.[1] || id);
// leaf key from an id/dirName or `a/b/leaf` rel-path — the LAST todo_NNNN.
const tKey = (s?: string | null): string | null => { const ms = (s || '').match(/todo_\d+/g); return ms ? ms[ms.length - 1] : null; };
const titleOf = (t: TodoLite) => (t.title || t.name || t.dirName || t.id || '').replace(/^todo_\d+[_-]?/, '').replace(/_/g, ' ').trim() || t.id;
const fmtDate = (s?: string) => s ? new Date(s).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '';

// Split notes.md into a preamble + ## sections.
function parseNotes(md: string): { preamble: string; sections: Array<{ heading: string; body: string }> } {
  if (!md) return { preamble: '', sections: [] };
  const lines = md.split('\n');
  const first = lines.findIndex(l => /^##\s+/.test(l));
  if (first === -1) return { preamble: md.trim(), sections: [] };
  const preamble = lines.slice(0, first).join('\n').trim();
  const sections: Array<{ heading: string; body: string }> = [];
  let cur: { heading: string; body: string[] } | null = null;
  for (const line of lines.slice(first)) {
    const h = line.match(/^##\s+(.*)$/);
    if (h) { if (cur) sections.push({ heading: cur.heading, body: cur.body.join('\n').trim() }); cur = { heading: h[1].trim(), body: [] }; }
    else if (cur) cur.body.push(line);
  }
  if (cur) sections.push({ heading: cur.heading, body: cur.body.join('\n').trim() });
  return { preamble, sections };
}
// Metadata already shown elsewhere (in the header) — never repeat in Contents.
const META_HEADING = /^(created|updated|status|owner|assigned|id|ref|tags?|flags?)\b/i;
// Strip lines that duplicate header metadata (title heading, **Created:**, etc.) from
// free text so the Summary/field bodies never repeat created/updated/status/owner.
const META_LINE = /^\s*(?:#{1,6}\s.*|[*_]{0,2}\s*(?:created|updated|last[ _]updated|status|owner|assigned|id|ref|priority)\s*[:*_].*)$/i;
function stripMetaLines(text: string): string {
  return text.split('\n').filter(l => !META_LINE.test(l)).join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

interface Provenance { origin: Record<string, string>; history: Array<{ ts: string; status: string; session: string; note: string }> }

type Sub = 'contents' | 'activities' | 'related' | 'files';
interface Section { heading: string; body: string }

// notes.md convention (PianoMan): ## = a subtab, ### = a section within it. The
// canonical subtab names map ## headings to the UI tabs; anything unrecognized (or a
// legacy flat-## file) falls back to Contents so old notes still render.
const CANON_TAB: Record<string, Sub> = {
  contents: 'contents', content: 'contents',
  activities: 'activities', activity: 'activities',
  'links & artifacts': 'related', 'links and artifacts': 'related', links: 'related', artifacts: 'related', related: 'related',
  files: 'files',
};
const canonTab = (name: string): Sub | null => CANON_TAB[name.trim().toLowerCase()] ?? null;

// Parse notes.md into user-authored sections keyed by subtab. Structured mode when any
// ## matches a canonical subtab; else legacy (flat ## → Contents sections).
function parseStructured(md: string): { byTab: Record<Sub, Section[]>; structured: boolean } {
  const byTab: Record<Sub, Section[]> = { contents: [], activities: [], related: [], files: [] };
  if (!md.trim()) return { byTab, structured: false };
  const h2 = [...md.matchAll(/^##\s+(.+)$/gm)].map(m => m[1].trim());
  const structured = h2.some(canonTab);
  if (!structured) {
    const { preamble, sections } = parseNotes(md);
    const intro = stripMetaLines(preamble);
    if (intro) byTab.contents.push({ heading: '', body: intro });
    for (const s of sections) if (!META_HEADING.test(s.heading)) byTab.contents.push(s);
    return { byTab, structured: false };
  }
  let curTab: Sub | null = null, curSec: { heading: string; body: string[] } | null = null, intro: string[] = [];
  const flushSec = () => { if (curTab && curSec) byTab[curTab].push({ heading: curSec.heading, body: curSec.body.join('\n').trim() }); curSec = null; };
  const flushIntro = () => { if (curTab) { const t = stripMetaLines(intro.join('\n')); if (t) byTab[curTab].unshift({ heading: '', body: t }); } intro = []; };
  for (const line of md.split('\n')) {
    const m2 = line.match(/^##\s+(.+)$/), m3 = line.match(/^###\s+(.+)$/);
    if (m2) { flushSec(); flushIntro(); curTab = canonTab(m2[1]); intro = []; }
    else if (m3) { flushSec(); if (!curTab) curTab = 'contents'; curSec = { heading: m3[1].trim(), body: [] }; }
    else if (curSec) curSec.body.push(line);
    else if (curTab) intro.push(line);
  }
  flushSec(); flushIntro();
  return { byTab, structured: true };
}
const SUBTABS: Array<{ key: Sub; label: string }> = [
  { key: 'contents', label: 'Contents' },
  { key: 'activities', label: 'Activity & Links' },   // merged: Activities + Links & Artifacts (todo_0413)
  { key: 'files', label: 'Files' },
];


// ── Threaded comments (note_0035) ───────────────────────────────────────────
// Comments are history.log entries (status 'comment') whose note is prefixed
// `[<id>|<parent>] text` by the engine. Parse them into a reply tree.
interface CommentNode { id: string; parent: string; text: string; ts: string; session: string; children: CommentNode[] }
function parseComments(history: Array<{ ts: string; status: string; session: string; note: string }>): CommentNode[] {
  const flat: CommentNode[] = [];
  let auto = 0;
  for (const h of history) {
    if (h.status !== 'comment') continue;
    const m = h.note.match(/^\[([^|\]]*)\|([^\]]*)\]\s?([\s\S]*)$/);
    const id = (m && m[1]) ? m[1] : `c${auto++}`;
    const parent = m ? m[2] : '';
    const text = m ? m[3] : h.note;
    flat.push({ id, parent, text, ts: h.ts, session: h.session, children: [] });
  }
  const byId = new Map(flat.map(n => [n.id, n]));
  const roots: CommentNode[] = [];
  for (const n of flat) {
    const p = n.parent && byId.get(n.parent);
    if (p) p.children.push(n); else roots.push(n);
  }
  return roots;
}

// A section whose body is ONLY HTML comments (+ whitespace) has no real content
// to show — hide it (note_0035). Strips <!-- … --> and checks what's left.
function isCommentOnly(text: string): boolean {
  return !text.replace(/<!--[\s\S]*?-->/g, '').trim();
}

// Render a notes body, turning HTML comments <!-- text --> into DIMMED inline
// text with the markers stripped (note_0035) — so authoring hints/placeholders
// read as muted asides rather than raw syntax. Non-comment text renders as-is.
// Render a notes section body as FORMATTED markdown — bold/italic, lists, code,
// links, sub-headings — instead of raw text (todo_0339). HTML comments <!-- x -->
// are kept but DIMMED (marked would otherwise drop them), preserving the
// comment-dimming from note_0035. Output is sanitized with DOMPurify.
// Thin wrapper over the shared MarkdownBlock (todo_0619): keeps the `tiv-notes-body`
// class the viewer's spacing depends on while all marked/DOMPurify/comment-dimming
// logic lives in one reusable place.
function NotesBody({ text }: { text: string }): JSX.Element {
  return <MarkdownBlock text={text} className="tiv-notes-body" />;
}

export default function TodoItemView({ todo, allTodos = [], search = '', onSelect, statusEditor, priorityEditor, assigneeEditor, moveControl, viewportId = 'todo_item_view' }: {
  todo: TodoLite; allTodos?: TodoLite[]; search?: string;
  onSelect?: (id: string) => void; statusEditor?: ReactNode; priorityEditor?: ReactNode; assigneeEditor?: ReactNode; moveControl?: ReactNode;
  /** Per-instance viewport id so multiple TodoItemViews register distinctly in
   *  describeViewport() (Prism's Git-Viewer pattern). Defaults for a lone host. */
  viewportId?: string;
}): JSX.Element {
  const [sub, setSub] = useState<Sub>('contents');
  const [notes, setNotes] = useState<string>('');
  const [prov, setProv] = useState<Provenance | null>(null);
  const [files, setFiles] = useState<Array<{ rel: string; size: number; isDir: boolean }>>([]);
  const [selFile, setSelFile] = useState<FsEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [editSec, setEditSec] = useState<string | null>(null);   // heading of the ### section being edited in place (todo_0405)
  const [secDraft, setSecDraft] = useState('');
  const [secSaving, setSecSaving] = useState(false);
  const [commentDraft, setCommentDraft] = useState('');
  const [commentSaving, setCommentSaving] = useState(false);
  // Editable title (note_0040) — the title is the first `# ` heading in notes.md,
  // so editing it is a notes.md write (no dir rename). titleOverride shows the new
  // value immediately until the parent list re-derives it from the engine.
  const [titleEditing, setTitleEditing] = useState(false);
  const [titleDraft, setTitleDraft] = useState('');
  const [titleSaving, setTitleSaving] = useState(false);
  const [titleOverride, setTitleOverride] = useState<string | null>(null);
  const [replyTarget, setReplyTarget] = useState<{ id: string; author: string } | null>(null);
  // Add Child (todo_0592) — inline title input in the header; creates a new todo
  // with THIS todo as its parent, then selects it.
  const [addingChild, setAddingChild] = useState(false);
  const [childTitle, setChildTitle] = useState('');
  const [childBusy, setChildBusy] = useState(false);
  const commentComposeRef = useRef<HTMLTextAreaElement>(null);
  const editorRef = useRef<HTMLDivElement>(null);
  const editorActionsRef = useRef<HTMLSpanElement>(null);
  // Click-away should COMMIT the edit, not discard it (todo_0651). Held in a ref,
  // reassigned every render, so the deferred mousedown listener always sees the
  // current draft without re-binding on each keystroke.
  const commitOrExitRef = useRef<() => void>(() => {});
  const focusComposer = () => { setSub('activities'); setTimeout(() => commentComposeRef.current?.focus(), 60); };

  // Viewport reporter — this todo-detail component surfaces its identity + active
  // subtab so describeViewport()/Capture Content sees it. Per-instance id lets
  // multiple TodoItemViews (Work Mgr, Session Work, Project) register distinctly.
  useViewport(viewportId, () => ({
    visible: true,
    label: `Todo — ${todo.title || todo.name || todo.id}`,
    state: { todoId: todo.id, status: todo.status, subtab: sub, editing, loading },
    children: [],
  }));

  useEffect(() => {
    let alive = true; setLoading(true); setSelFile(null);
    Promise.all([
      window.uai.todos.read(todo.id).catch(() => ''),
      (window.uai.todos as any).provenance?.(todo.id).catch(() => null) ?? Promise.resolve(null),
      window.uai.todos.files(todo.id).catch(() => []),
    ]).then(([n, p, f]: any[]) => {
      if (!alive) return;
      setNotes(n || ''); setProv(p || null); setFiles(Array.isArray(f) ? f : []); setLoading(false);
    });
    return () => { alive = false; };
  }, [todo.id, reloadKey]);

  // Editing exits when switching to another todo.
  useEffect(() => { setEditing(false); setTitleEditing(false); setTitleOverride(null); }, [todo.id]);
  // Click outside the open editor COMMITS the edit (todo_0651 — PM: edits should
  // save when you click away, not be silently discarded). Explicit discard is still
  // available via Esc / Cancel. Introduced as an exit affordance in todo_0554 so a
  // long edit isn't trapped by an off-screen Cancel button — now it saves.
  useEffect(() => {
    if (!editing) return;
    const onDown = (e: MouseEvent) => {
      const target = e.target as Node;
      const insideEditor = editorRef.current?.contains(target);
      const insideActions = editorActionsRef.current?.contains(target);
      if (!insideEditor && !insideActions) commitOrExitRef.current();
    };
    // defer binding so the click that opened the editor doesn't immediately close it
    const id = window.setTimeout(() => window.addEventListener('mousedown', onDown), 0);
    return () => { window.clearTimeout(id); window.removeEventListener('mousedown', onDown); };
  }, [editing]);

  const startEdit = () => { setDraft(notes); setEditing(true); };
  // Per-section edit (todo_0405): splice the new body into notes.md between `### <heading>`
  // and the next `##`/`###`, then save the whole file via todo_mgr.
  const startSecEdit = (heading: string, body: string) => { setEditSec(heading); setSecDraft(body); };
  const saveSecEdit = async () => {
    if (editSec == null) return;
    setSecSaving(true);
    try {
      const lines = notes.split('\n'); const out: string[] = []; let i = 0; let done = false;
      while (i < lines.length) {
        const m = lines[i].match(/^###\s+(.+)$/);
        if (!done && m && m[1].trim() === editSec) {
          out.push(lines[i]); i++;
          while (i < lines.length && !/^#{2,3}\s/.test(lines[i])) i++;
          out.push('', secDraft.trim(), ''); done = true; continue;
        }
        out.push(lines[i]); i++;
      }
      await executeCommand('todo.writeNotes', { id: todo.id, content: out.join('\n') });
      notifyTodosChanged();
    } finally { setSecSaving(false); setEditSec(null); setReloadKey(k => k + 1); }
  };
  const saveEdit = async () => {
    setSaving(true);
    try { await executeCommand('todo.writeNotes', { id: todo.id, content: draft }); notifyTodosChanged(); }
    finally { setSaving(false); setEditing(false); setReloadKey(k => k + 1); }
  };
  // Click-away behavior (todo_0651): save when the draft changed, else just exit.
  // Reassigned every render so it always closes over the current draft/notes.
  // Ignore further outside clicks while the first write is in flight; otherwise
  // the global listener could enqueue duplicate writes before editing closes.
  commitOrExitRef.current = () => {
    if (saving) return;
    if (draft !== notes) void saveEdit();
    else setEditing(false);
  };
  // Edit the title = set the first `# ` heading in notes.md (note_0040).
  const startTitleEdit = () => { setTitleDraft(titleOverride ?? titleOf(todo)); setTitleEditing(true); };
  const saveTitle = async () => {
    const t = titleDraft.trim();
    if (!t) { setTitleEditing(false); return; }
    setTitleSaving(true);
    try {
      const lines = notes.split('\n');
      const idx = lines.findIndex(l => /^#\s+/.test(l));
      if (idx >= 0) lines[idx] = `# ${t}`;
      else lines.unshift(`# ${t}`, '');
      await executeCommand('todo.writeNotes', { id: todo.id, content: lines.join('\n') });
      setTitleOverride(t);
      setTitleEditing(false);
      setReloadKey(k => k + 1);
      notifyTodosChanged();
    } finally { setTitleSaving(false); }
  };
  // Post a comment — appended to history.log (status 'comment') via the engine,
  // then reload provenance so it shows in the Comments list (note_0035).
  const postComment = async () => {
    const text = commentDraft.trim();
    if (!text) return;
    setCommentSaving(true);
    try {
      await executeCommand('todo.comment', { id: todo.id, text, ...(replyTarget ? { replyTo: replyTarget.id } : {}) });
      setCommentDraft(''); setReplyTarget(null);
    } finally { setCommentSaving(false); setReloadKey(k => k + 1); }
  };

  // Add Child (todo_0592): create a new todo, move it under THIS todo, select it.
  const createChild = async () => {
    const name = childTitle.trim();
    if (!name) return;
    setChildBusy(true);
    try {
      const created = await executeCommand<{ out: string }>('todo.create', { name }, { onFailure: 'log' });
      const newId = (created.data?.out || '').match(/Created:\s*(todo_\d+\S*)/)?.[1];
      if (!newId) return;
      await executeCommand('todo.move', { id: newId, target: todo.id }, { onFailure: 'log' });
      setChildTitle(''); setAddingChild(false);
      notifyTodosChanged();
      setReloadKey(k => k + 1);
      onSelect?.(newId);
    } finally { setChildBusy(false); }
  };

  const { byTab } = useMemo(() => parseStructured(notes), [notes]);
  const contentsSecs = byTab.contents.filter(s => !META_HEADING.test(s.heading));
  const sessionAssignee = trackingIdFrom((todo.assigned && todo.assigned[0]) || '');
  const hasOpenQ = contentsSecs.some(s => /question|recommendation/i.test(s.heading));
  const hasDecisions = contentsSecs.some(s => /decision|pivot/i.test(s.heading));

  // Lead gist (todo_0538): agent-created todos (workflow_todo_create --description)
  // Parent path (ancestors) + children resolved from the full todo set. parent/children
  // are `a/b/leaf` rel-paths, so match by the LAST todo_NNNN (the leaf), not by t.id.
  const byKey = useMemo(() => { const m = new Map<string, TodoLite>(); allTodos.forEach(t => { const k = tKey(t.id || t.dirName); if (k) m.set(k, t); }); return m; }, [allTodos]);
  const ancestors = useMemo(() => {
    const out: TodoLite[] = []; let p = byKey.get(tKey(todo.parent) || ''); let guard = 0;
    while (p && guard++ < 12) { out.unshift(p); p = byKey.get(tKey(p.parent) || ''); }
    return out;
  }, [todo, byKey]);
  const children = useMemo(() => (todo.children || []).map(c => byKey.get(tKey(c) || '')).filter(Boolean) as TodoLite[], [todo, byKey]);
  // Artifacts = work products created while implementing the todo (live under data/).
  // NOT the todo's definition files (notes/origin/history/status/tag) which sit at the root.
  const artifacts = files.filter(f => !f.isDir && /^data\//.test(f.rel));
  // Git-backed Files view: pin the embedded Git File View's filter to THIS todo —
  // the files changed by commits carrying its `Todo:` trailer — scanning ai_general
  // from the todo's creation date. Memoized so the embed only reloads on re-select.
  const todoKey = tKey(todo.id || todo.dirName) || todo.id;
  const gitFilter = useMemo<GitFileViewFilter>(() => ({ kind: 'todo', value: todoKey }), [todoKey]);
  const gitSince = useMemo(() => (todo.created ? todo.created.slice(0, 10) : ''), [todo.created]);


  return (
    <div className="tiv">
      {/* Header — Open · id · title · dates | Status · Assigned. Clear rule below it. */}
      <div className="tiv-header">
        <div className="tiv-header-top">
          <button className="tiv-open" onClick={() => window.uai.todos.open(todo.id)} title="Reveal folder in Finder">Open</button>
          {/* Comment from any subtab (note_0035) — jumps to Activities + focuses the composer. */}
          <button className="tiv-edit-btn" onClick={() => { setReplyTarget(null); focusComposer(); }} title="Add a comment">{'💬 Comment'}</button>
          {/* Add Child (todo_0592) — new todo parented to this one; inline title input. */}
          {addingChild ? (
            <span className="tiv-child-wrap">
              <input className="tiv-child-input" value={childTitle} autoFocus disabled={childBusy}
                placeholder="New child todo title…"
                onChange={e => setChildTitle(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); createChild(); } else if (e.key === 'Escape') { e.preventDefault(); setAddingChild(false); setChildTitle(''); } }} />
              <button className="tiv-child-save" title="Create child (Enter)" onClick={createChild} disabled={childBusy || !childTitle.trim()}>{childBusy ? '…' : '✓'}</button>
              <button className="tiv-child-cancel" title="Cancel (Esc)" onClick={() => { setAddingChild(false); setChildTitle(''); }} disabled={childBusy}>{'✕'}</button>
            </span>
          ) : (
            <button className="tiv-edit-btn" onClick={() => setAddingChild(true)} title="Create a new todo parented to this one">{'＋ Child'}</button>
          )}
          {/* Edit is now per-region (pencils on each boundary, note_0040). The global
              Save/Cancel show while the notes editor (opened from a region pencil) is active. */}
          {editing && (
            <span ref={editorActionsRef} className="tiv-edit-actions">
              <button className="tiv-edit-btn tiv-save" onClick={saveEdit} disabled={saving} title="Save via todo_mgr">{saving ? 'Saving…' : '✓ Save'}</button>
              <button className="tiv-edit-btn" onClick={() => setEditing(false)} disabled={saving} title="Discard changes">Cancel</button>
            </span>
          )}
          <span className="tiv-id"><span className="tiv-id-pre">todo_</span>{todoNum(todo.id)}</span>
          {titleEditing ? (
            <span className="tiv-title-edit-wrap">
              <input className="tiv-title-input" value={titleDraft} autoFocus disabled={titleSaving}
                onChange={e => setTitleDraft(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter') { e.preventDefault(); saveTitle(); } else if (e.key === 'Escape') { e.preventDefault(); setTitleEditing(false); } }} />
              <button className="tiv-title-save" title="Save title (Enter)" onClick={saveTitle} disabled={titleSaving}>{titleSaving ? '…' : '✓'}</button>
            </span>
          ) : (
            <span className="tiv-title">
              <button className="tiv-title-edit-btn" title="Edit title" onClick={startTitleEdit}>{'✎'}</button>
              {titleOverride ?? titleOf(todo)}
            </span>
          )}
          <span className="tiv-spacer" />
          <span className="tiv-dates">
            {todo.created && <span title="created">created {fmtDate(todo.created)}</span>}
            {todo.updated && <span title="last updated">updated {fmtDate(todo.updated)}</span>}
          </span>
        </div>
        <div className="tiv-header-status">
          <span className="tiv-slabel">Status</span>
          {statusEditor ?? <span className="tiv-badge" style={{ background: statusColor(todo.status) }}>{statusLabel(todo.status)}</span>}
          {priorityEditor && <><span className="tiv-slabel tiv-slabel-2">Priority</span>{priorityEditor}</>}
          <span className="tiv-slabel tiv-slabel-2">Assigned</span>
          {assigneeEditor ?? <span className="tiv-aval">{(todo.assigned && todo.assigned[0]) ? assigneeLabel(todo.assigned[0]) : '—'}</span>}
          {sessionAssignee && <SessionLink id={sessionAssignee} label="↗ open" />}
        </div>
      </div>

      {editing ? (
        <div className="tiv-editor" ref={editorRef}>
          <div className="tiv-editor-hint">Editing <b>notes.md</b> — <code>## Subtab</code> (Contents / Activities / Links &amp; Artifacts) and <code>### Section</code>. Fields (created, status, …) are engine-owned; don't add them here. Saved via todo_mgr.</div>
          <textarea className="tiv-editor-area" value={draft} onChange={e => setDraft(e.target.value)} spellCheck={false} autoFocus
            onKeyDown={e => {
              if (e.key === 'Escape') { e.preventDefault(); setEditing(false); }        // Esc = Cancel
              else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); saveEdit(); }  // Cmd/Ctrl+Enter = Save
            }} />
        </div>
      ) : (<>
      {/* Subtabs — distinct band, clearly separated from the title/status above. */}
      <div className="tiv-subtabs">
        {SUBTABS.map(t => (
          <button key={t.key} className={`tiv-subtab ${sub === t.key ? 'on' : ''}`} onClick={() => setSub(t.key)}>{t.label}</button>
        ))}
      </div>

      <div className="tiv-body">
        {loading && <div className="tiv-muted">Loading…</div>}

        {!loading && sub === 'contents' && (
          <>
            <section className="tiv-sec">
              <div className="tiv-h">Parent path {moveControl && <span className="tiv-move">{moveControl}</span>}</div>
              {/* Ancestors only — an item is not a parent to itself; parentless → just "root". */}
              <div className="tiv-crumbs">
                <span className="tiv-crumb-root">root</span>
                {ancestors.map(a => { const aid = a.id || a.dirName || ''; return (
                  <span key={aid}><span className="tiv-crumb-sep">/</span>
                    <a className="tiv-link" onClick={() => onSelect?.(aid)}>todo_{todoNum(aid)} {titleOf(a).slice(0, 20)}</a></span>
                ); })}
              </div>
            </section>

            {/* Contents region (note_0040): user-authored ## Contents / ### sections,
                boxed with a boundary + pencil (opens the notes editor). Each section
                also keeps its own inline ✎ for a quick, scoped edit (todo_0405). */}
            <div className="tiv-region">
              <div className="tiv-region-h">
                {!editing && <button className="tiv-region-edit" title="Edit contents" onClick={startEdit}>{'✎'}</button>}
                <span className="tiv-region-name">Contents</span>
              </div>
            {contentsSecs.map((s, i) => {
              const body = stripMetaLines(s.body);
              // Hide sections that are empty OR contain only <!-- comments -->
              // (unless it's the one being edited).
              if ((!body || isCommentOnly(body)) && editSec !== s.heading) return null;
              const isEditing = editSec === s.heading;
              return (
                <section key={i} className="tiv-sec">
                  {s.heading && (
                    <div className="tiv-h">
                      {!editing && s.heading && !isEditing && <button className="tiv-sec-edit" title="Edit this section" onClick={() => startSecEdit(s.heading, body)}>✎</button>}
                      {s.heading}
                    </div>
                  )}
                  {isEditing ? (
                    <div className="tiv-sec-editor">
                      <textarea className="tiv-sec-area" value={secDraft} autoFocus spellCheck={false}
                        onChange={e => setSecDraft(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Escape') setEditSec(null); else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) saveSecEdit(); }} />
                      <div className="tiv-sec-btns">
                        <button className="tiv-edit-btn tiv-save" onClick={saveSecEdit} disabled={secSaving}>{secSaving ? 'Saving…' : '✓ Save'}</button>
                        <button className="tiv-edit-btn" onClick={() => setEditSec(null)} disabled={secSaving}>Cancel</button>
                      </div>
                    </div>
                  ) : <NotesBody text={body} />}
                </section>
              );
            })}
            </div>

            {/* Provenance region — from origin.yml, system-owned, so it's boxed but
                has no pencil (note_0040: not free text). */}
            <section className="tiv-sec tiv-region">
              <div className="tiv-region-h"><span className="tiv-region-name">Provenance</span></div>
              {prov && Object.keys(prov.origin || {}).length ? (
                <div className="tiv-prov">{Object.entries(prov.origin).map(([k, v]) => {
                  const tid = trackingIdFrom(String(v));
                  return <span key={k} className="tiv-kv"><span className="tiv-k">{k}</span><span className="tiv-v">{tid ? <SessionLink id={tid} /> : String(v)}</span></span>;
                })}</div>
              ) : <div className="tiv-muted">No origin.yml.</div>}
            </section>

            {/* Open questions / Decisions regions — boxed with a pencil; when the
                author hasn't written them yet, the pencil opens the notes editor to
                add the section (note_0040). */}
            {!hasOpenQ && (
              <section className="tiv-sec tiv-region">
                <div className="tiv-region-h">
                  {!editing && <button className="tiv-region-edit" title="Add / edit this section" onClick={startEdit}>{'✎'}</button>}
                  <span className="tiv-region-name">Open questions &amp; recommendations</span>
                </div>
                <div className="tiv-muted">None yet — ✎ to add.</div>
              </section>
            )}
            {!hasDecisions && (
              <section className="tiv-sec tiv-region">
                <div className="tiv-region-h">
                  {!editing && <button className="tiv-region-edit" title="Add / edit this section" onClick={startEdit}>{'✎'}</button>}
                  <span className="tiv-region-name">Decisions &amp; pivots</span>
                </div>
                <div className="tiv-muted">None yet — ✎ to add.</div>
              </section>
            )}

            {/* Artifacts region — files inside the todo folder; boxed, no pencil
                (not free text, note_0040). */}
            <section className="tiv-sec tiv-region">
              <div className="tiv-region-h"><span className="tiv-region-name">Artifacts ({artifacts.length})</span></div>
              {artifacts.length === 0 ? <div className="tiv-muted">No artifacts in this todo's folder.</div> : (
                <div className="tiv-artifacts">{artifacts.map(f => (
                  <div key={f.rel} className="tiv-artifact" onClick={() => (window.uai.todos as any).openData?.(todo.id, f.rel.replace(/^data\//, ''))} title="Open externally">
                    {f.rel} <span className="tiv-muted">{f.size} B</span>
                  </div>
                ))}</div>
              )}
            </section>
          </>
        )}

        {!loading && sub === 'activities' && (
          <>
            <section className="tiv-sec">
              <div className="tiv-h">History</div>
              {(() => {
                // Comments live in the same log under status 'comment' — show them
                // in their own section below, not in the status trail.
                const hist = (prov?.history || []).filter(h => h.status !== 'comment');
                return hist.length ? hist.map((h, i) => (
                  <div key={i} className="tiv-histline">
                    <span className="tiv-hist-ts">{h.ts}</span>
                    <span style={{ color: statusColor(h.status) }}>{statusLabel(h.status)}</span>
                    {h.session && <SessionLink id={h.session} />}
                    <span className="tiv-hist-note"><LinkifySessions text={h.note} /></span>
                  </div>
                )) : <div className="tiv-muted">No history.log entries.</div>;
              })()}
            </section>
            <section className="tiv-sec">
              <div className="tiv-h">Comments</div>
              {(() => {
                const roots = parseComments(prov?.history || []);
                const render = (n: CommentNode, depth: number): ReactNode => (
                  <div key={n.id} className="tiv-comment-row" style={{ marginLeft: depth * 18 }}>
                    <div className="tiv-comment-meta">
                      <span className="tiv-comment-author">{n.session || 'unknown'}</span>
                      <span className="tiv-hist-ts">{n.ts}</span>
                      <button
                        className="tiv-comment-reply-btn"
                        onClick={() => { setReplyTarget({ id: n.id, author: n.session || 'comment' }); focusComposer(); }}
                        title="Reply to this comment"
                      >↩ Reply</button>
                    </div>
                    <div className="tiv-comment-text"><LinkifySessions text={n.text} /></div>
                    {n.children.map(c => render(c, depth + 1))}
                  </div>
                );
                return roots.length ? roots.map(n => render(n, 0)) : <div className="tiv-muted">No comments yet.</div>;
              })()}
              <div className="tiv-comment-compose">
                {replyTarget && (
                  <div className="tiv-comment-replying">
                    ↩ Replying to <b>{replyTarget.author}</b>
                    <button className="tiv-comment-replycancel" onClick={() => setReplyTarget(null)} title="Cancel reply">✕</button>
                  </div>
                )}
                <textarea
                  ref={commentComposeRef}
                  className="tiv-sec-area tiv-comment-area"
                  value={commentDraft}
                  placeholder={replyTarget ? 'Write a reply…  (⌘/Ctrl+Enter to post)' : 'Add a comment…  (⌘/Ctrl+Enter to post)'}
                  onChange={e => setCommentDraft(e.target.value)}
                  onKeyDown={e => { if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); void postComment(); } }}
                />
                <button className="tiv-edit-btn tiv-save" onClick={postComment} disabled={commentSaving || !commentDraft.trim()}>
                  {commentSaving ? 'Posting…' : (replyTarget ? 'Reply' : 'Comment')}
                </button>
              </div>
            </section>
            {/* User-authored Activities sections (## Activities / ### Reviews, …). */}
            {byTab.activities.filter(s => !META_HEADING.test(s.heading)).map((s, i) => {
              const body = stripMetaLines(s.body);
              if (!body || isCommentOnly(body)) return null;
              return <section key={i} className="tiv-sec">{s.heading && <div className="tiv-h">{s.heading}</div>}<NotesBody text={body} /></section>;
            })}
            {!byTab.activities.some(s => /review/i.test(s.heading)) && (
              <section className="tiv-sec"><div className="tiv-h">Reviews</div><div className="tiv-muted">No reviews recorded for this item yet.</div></section>
            )}
          </>
        )}

        {!loading && sub === 'activities' && (
          <>
            <section className="tiv-sec">
              <div className="tiv-h">Children ({children.length})</div>
              {children.length === 0 ? <div className="tiv-muted">No child items.</div> : (
                <div className="tiv-childlist">{children.map(c => (
                  <div key={c.id} className="tiv-childrow" onClick={() => onSelect?.(c.id)}>
                    <span className="tiv-cdot" style={{ background: statusColor(c.status) }} />
                    <span className="tiv-id-sm">todo_{todoNum(c.id)}</span>
                    <span className="tiv-title-sm">{titleOf(c)}</span>
                  </div>
                ))}</div>
              )}
            </section>
            {/* User-authored links (## Links & Artifacts / ### sections). */}
            {byTab.related.filter(s => !META_HEADING.test(s.heading)).map((s, i) => {
              const body = stripMetaLines(s.body);
              if (!body || isCommentOnly(body)) return null;
              return <section key={i} className="tiv-sec">{s.heading && <div className="tiv-h">{s.heading}</div>}<NotesBody text={body} /></section>;
            })}
          </>
        )}

        {!loading && sub === 'files' && (
          <section className="tiv-sec tiv-files-sec">
            <div className="tiv-files-hint">Files changed by commits for <b>{todoKey}</b> — a git-backed change view scoped to this todo (from its <code>Todo:</code> commit trailers). Scan starts at the todo's creation.</div>
            <div className="tiv-gitview">
              <GitFileViewPane
                tabId={`wm-files-${todoKey}`}
                embedded
                showScopeBar={false}
                allowScopeChange={false}
                dir="ai_general"
                since={gitSince}
                filter={gitFilter}
              />
            </div>
          </section>
        )}
      </div>
      </>)}
    </div>
  );
}
