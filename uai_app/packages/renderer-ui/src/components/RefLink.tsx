/**
 * RefLink — renders `todo_####` / `note_####` references as clickable links with
 * a tooltip (complete name, status, assignee) that open the item in Work Mgr /
 * Notes Mgr. Mirrors SessionLink; reusable anywhere text may embed a ref.
 *
 * Data for the tooltip comes from module-level indexes lazily loaded from
 * window.uai.todos.list() and the note.list command, and refreshed on the
 * onStoreChanged('todos'|'notes') signal. The link action opens the relevant
 * manager tab and drives its selection via a focus event (+ a pending singleton
 * for the not-yet-mounted case) — NOT window.uai.todos.open (that reveals the
 * todo folder in Finder, which is a different affordance).
 */

import { useSyncExternalStore } from 'react';
import { getSession } from '../stores/session-store';
import { executeCommand } from '../utils/execute-command';

// ── Metadata indexes ────────────────────────────────────────────────────────

// Indexes are keyed by the SHORT ref (todo_####/note_####) that appears in text.
// The backend id can differ: note.list returns a full slug
// (note_0001_fix_dropdown…), so we extract the short ref for the key and keep the
// real `openId` for the open/focus action.
interface TodoMeta { openId: string; title: string; status: string; assigned: string[] }
interface NoteMeta { openId: string; title: string; status: string; recipients: string[] }

/** Extract the canonical short ref (todo_####/note_####) from a possibly-slugged id. */
function shortRef(id: string): string {
  const m = (id || '').match(/^(?:todo|note)_\d+/);
  return m ? m[0] : id;
}

let todoIndex = new Map<string, TodoMeta>();
let noteIndex = new Map<string, NoteMeta>();
let version = 0;
const listeners = new Set<() => void>();
let wired = false;
let todosRequested = false;
let notesRequested = false;

function emit(): void { version++; listeners.forEach(l => l()); }

async function loadTodos(): Promise<void> {
  try {
    const list = await window.uai.todos.list(true);
    const m = new Map<string, TodoMeta>();
    for (const t of list) {
      const key = shortRef(t.id);
      m.set(key, { openId: t.id, title: t.title || t.summary || key, status: t.status, assigned: t.assigned || [] });
    }
    todoIndex = m;
    emit();
  } catch { /* keep prior index */ }
}

async function loadNotes(): Promise<void> {
  try {
    const res = await executeCommand<{ notes: Array<{ id: string; title?: string; summary?: string; status: string; recipients?: string[] }> }>(
      'note.list', {}, { onFailure: 'log' },
    );
    const notes = (res?.ok && res.data?.notes) ? res.data.notes : [];
    const m = new Map<string, NoteMeta>();
    for (const n of notes) {
      const key = shortRef(n.id);
      m.set(key, { openId: n.id, title: n.title || n.summary || key, status: n.status, recipients: n.recipients || [] });
    }
    noteIndex = m;
    emit();
  } catch { /* keep prior index */ }
}

function ensureWired(): void {
  if (wired) return;
  wired = true;
  window.uai.onStoreChanged?.((e: { changed?: string[] }) => {
    if (e.changed?.includes('todos')) loadTodos();
    if (e.changed?.includes('notes')) loadNotes();
  });
}

function subscribe(cb: () => void): () => void {
  listeners.add(cb);
  ensureWired();
  if (!todosRequested) { todosRequested = true; loadTodos(); }
  if (!notesRequested) { notesRequested = true; loadNotes(); }
  return () => { listeners.delete(cb); };
}
function getVersion(): number { return version; }

// ── Focus plumbing (open manager + select the item) ─────────────────────────

let pendingTodoFocus: string | null = null;
let pendingNoteFocus: string | null = null;

export function focusTodoInWorkMgr(ref: string): void {
  const id = todoIndex.get(ref)?.openId ?? ref;
  pendingTodoFocus = id;
  executeCommand('workspace.tabs.open', { type: 'app', targetId: 'work-mgr', label: 'Work Mgr' });
  window.dispatchEvent(new CustomEvent('uai:workMgr:focusTodo', { detail: { id } }));
}
export function consumePendingTodoFocus(): string | null { const v = pendingTodoFocus; pendingTodoFocus = null; return v; }

export function focusNoteInNotesMgr(ref: string): void {
  const id = noteIndex.get(ref)?.openId ?? ref;
  pendingNoteFocus = id;
  executeCommand('workspace.tabs.open', { type: 'app', targetId: 'notes-manager', label: 'Notes Mgr' });
  window.dispatchEvent(new CustomEvent('uai:notesMgr:focusNote', { detail: { id } }));
}
export function consumePendingNoteFocus(): string | null { const v = pendingNoteFocus; pendingNoteFocus = null; return v; }

// ── Tooltip helpers ─────────────────────────────────────────────────────────

/** Turn an assignee token (uai://session/<tid>, uai://project/<p>, or a bare id)
 *  into a friendly label, resolving session tracking ids to display names. */
function cleanAssignee(a: string): string {
  const sm = a.match(/uai:\/\/session\/([^/\s]+)/i);
  if (sm) { const s = getSession(sm[1]); return s?.display_name || sm[1]; }
  const pm = a.match(/uai:\/\/(project|team)\/([^/\s]+)/i);
  if (pm) return `${pm[1]}:${pm[2]}`;
  return a.replace(/^uai:\/\//, '');
}

/** Multi-line tooltip (name / status / assignee) for a todo id, from the index. */
export function todoTooltip(id: string): string {
  const m = todoIndex.get(id);
  if (!m) return `${id}  (loading…)`;
  return [m.title, `Status: ${m.status}`, `Assigned: ${m.assigned.length ? m.assigned.map(cleanAssignee).join(', ') : '—'}`].join('\n');
}
/** Multi-line tooltip (name / status / assignee) for a note id, from the index. */
export function noteTooltip(id: string): string {
  const m = noteIndex.get(id);
  if (!m) return `${id}  (loading…)`;
  return [m.title, `Status: ${m.status}`, `Assigned: ${m.recipients.length ? m.recipients.map(cleanAssignee).join(', ') : '—'}`].join('\n');
}

/** Kick off index loading + store-changed wiring from a non-React (imperative)
 *  caller (e.g. the Memorex terminal overlay). Safe to call repeatedly. */
export function ensureRefIndexLoaded(): void {
  ensureWired();
  if (!todosRequested) { todosRequested = true; loadTodos(); }
  if (!notesRequested) { notesRequested = true; loadNotes(); }
}

// ── Link components ─────────────────────────────────────────────────────────

export function TodoLink({ id, label }: { id: string; label?: string }): JSX.Element {
  useSyncExternalStore(subscribe, getVersion);
  return (
    <a
      className="ref-link ref-todo"
      title={todoTooltip(id)}
      onClick={(e) => { e.stopPropagation(); focusTodoInWorkMgr(id); }}
    >{label || id}</a>
  );
}

export function NoteLink({ id, label }: { id: string; label?: string }): JSX.Element {
  useSyncExternalStore(subscribe, getVersion);
  return (
    <a
      className="ref-link ref-note"
      title={noteTooltip(id)}
      onClick={(e) => { e.stopPropagation(); focusNoteInNotesMgr(id); }}
    >{label || id}</a>
  );
}

// ── Linkifier ───────────────────────────────────────────────────────────────

const REF_RE = /(todo_\d+|note_\d+)/g;

/** True if the text contains at least one todo_/note_ reference. */
export function hasRef(text: string): boolean {
  REF_RE.lastIndex = 0;
  return REF_RE.test(text || '');
}

/** Render text, turning any embedded todo_####/note_#### into a clickable link. */
export function LinkifyRefs({ text }: { text: string }): JSX.Element {
  const parts = (text || '').split(REF_RE);
  return (
    <>
      {parts.map((p, i) => {
        if (/^todo_\d+$/.test(p)) return <TodoLink key={i} id={p} />;
        if (/^note_\d+$/.test(p)) return <NoteLink key={i} id={p} />;
        return <span key={i}>{p}</span>;
      })}
    </>
  );
}
