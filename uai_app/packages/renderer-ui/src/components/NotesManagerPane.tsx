/**
 * NotesManagerPane — the Notes Mgr tab (an `app`-type tab, targetId 'notes-manager').
 *
 * Management surface for the filesystem notes backend (scripts/notes/notes_mgr.py
 * via the note.* commands). Two-pane split, modeled on LiveBoardPane:
 *   left  = note list (id, status badge, recipients, summary, msg count) — note.list
 *   right = selected note's thread (content.md + messages) — note.read
 *
 * A status control (open/resolved/archived) calls note.setStatus; a "＋ New Note"
 * button opens NoteDialog mode='note'. Read-only reflection of external ground
 * truth otherwise.
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { executeCommand } from '../utils/execute-command';
import { TabNavArrows } from './TabNavArrows';
import NoteDialog from './NoteDialog';
import { consumePendingNoteFocus, TodoLink, ensureRefIndexLoaded } from './RefLink';
import { sessionColor } from '../utils/session-color';
import { useMention, MentionPopover, makeRecipientSource } from './mention';
import { useSessionStore } from '../stores/session-store';
import { useViewport } from '../viewport';
import { showContextMenu, type ContextMenuItem } from '../utils/context-menu';

// @-token for a session name (quote if it contains whitespace) — matches PromptBox.
function mentionToken(name: string): string {
  return /\s/.test(name) ? `"${name}"` : name;
}

// In the UAI the human operating the app is PianoMan; comments authored here are
// his, and @mentions are sent FROM his user URI (piano_man = PRIMARY_USER_ID).
const NOTE_AUTHOR = 'PianoMan';
const USER_SENDER = 'piano_man';

// Per-author color, same scheme as MessagesTab: one gold for the user, a stable
// hash color per session — so a note's thread reads clearly by who said what.
const USER_COLOR = '#e8c07a';
const USER_AUTHORS = new Set(['pm', 'PM', 'PianoMan', 'piano_man', 'user', 'User']);
function senderColor(author: string): string {
  return USER_AUTHORS.has(author) ? USER_COLOR : sessionColor(author || '?');
}
// Low-alpha tint of a hex color for message backgrounds (bold-but-readable).
function tint(hex: string, alpha = '1f'): string {
  return /^#[0-9a-fA-F]{6}$/.test(hex) ? hex + alpha : 'transparent';
}

// ── Backend shapes (notes_mgr --json) ──────────────────────────────────────

interface NoteListItem {
  id: string;
  status: string;
  recipients: string[];
  created_by?: string;
  created_at?: string;
  messages: number;
  resulted_in?: string[];
  summary?: string;
  title?: string;
  updated_at?: string;
}

// reply_to is null, or a {type,id,...} object. For turns the backend may carry
// session/transcript/turn alongside (or fold them into) id — render loosely.
interface NoteReplyTo {
  type?: string;
  id?: string | number;
  session?: string;
  transcript?: string;
  turn?: string | number;
}

interface NoteMessage {
  id: string;
  author: string;
  timestamp?: string;
  reply_to?: NoteReplyTo | null;
  body: string;
}

interface NoteCapture {
  file?: string;
  captured_at?: string;
  source_tab?: string;
  component_path?: string;
  data?: unknown;
}

interface NoteDetail {
  id: string;
  meta?: Record<string, unknown>;
  content?: string;
  messages?: NoteMessage[];
  captures?: NoteCapture[];
}

// Recursively render captured context data (arbitrary object/array/scalar tree).
function CaptureValue({ value, depth = 0 }: { value: unknown; depth?: number }): JSX.Element {
  if (value === null || value === undefined || value === '') {
    return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  }
  if (Array.isArray(value)) {
    return (
      <div>
        {value.map((v, i) => (
          <div key={i} style={{ marginLeft: 10 }}>
            <span style={{ color: 'var(--text-muted)' }}>{'• '}</span><CaptureValue value={v} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }
  if (typeof value === 'object') {
    return (
      <div>
        {Object.entries(value as Record<string, unknown>).map(([k, v]) => (
          <div key={k} style={{ marginLeft: depth ? 10 : 0 }}>
            <span style={{ color: 'var(--text-sec)' }}>{k}:</span>{' '}<CaptureValue value={v} depth={depth + 1} />
          </div>
        ))}
      </div>
    );
  }
  return <span style={{ color: 'var(--text)' }}>{String(value)}</span>;
}

// ── Shared inline styles for the action toolbar + inline forms ─────────────
const ACT_BTN: React.CSSProperties = {
  background: 'var(--bg-hover)', border: '1px solid var(--border-strong)', color: 'var(--text)',
  borderRadius: 6, padding: '4px 10px', fontSize: 12, cursor: 'pointer', fontWeight: 600,
};
const GHOST_BTN: React.CSSProperties = {
  background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)',
  borderRadius: 6, padding: '5px 12px', fontSize: 12, cursor: 'pointer',
};
const PRIMARY_BTN = (enabled: boolean): React.CSSProperties => ({
  background: enabled ? 'var(--accent-blue-bg)' : 'var(--bg-hover)',
  border: `1px solid ${enabled ? 'var(--accent-blue)' : 'var(--border)'}`,
  color: enabled ? 'var(--text)' : 'var(--text-muted)',
  borderRadius: 6, padding: '5px 13px', fontSize: 12,
  cursor: enabled ? 'pointer' : 'default', fontWeight: 600,
});
const PANEL: React.CSSProperties = {
  background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 8,
  padding: '11px 12px', marginBottom: 14, display: 'flex', flexDirection: 'column', gap: 8,
};
const PANEL_TITLE: React.CSSProperties = {
  color: 'var(--text-sec)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.05em', fontWeight: 700,
};
const FIELD: React.CSSProperties = {
  width: '100%', boxSizing: 'border-box', background: 'var(--bg-deep)', color: 'var(--text)',
  border: '1px solid var(--border)', borderRadius: 6, padding: '7px 10px', fontSize: 12.5,
};

const STATUSES = ['open', 'resolved', 'archived'] as const;

const STATUS_COLOR: Record<string, string> = {
  open: 'var(--accent-green)',
  resolved: 'var(--accent-blue)',
  archived: 'var(--text-muted)',
  draft: 'var(--accent-yellow)',
};

function fmtTime(ts?: string): string {
  if (!ts) return '';
  const d = new Date(ts);
  if (Number.isNaN(d.getTime())) return ts;
  return d.toLocaleString();
}

// Involved parties in a note (note_0039): every session that commented in the
// thread PLUS every @-mentioned name in the body or any comment. De-duped, order
// = comment authors first, then mention-only names.
function involvedSessions(detail: NoteDetail): string[] {
  const set = new Set<string>();
  for (const m of detail.messages || []) if (m.author) set.add(m.author);
  const scan = (t?: string) => {
    if (!t) return;
    for (const mm of t.matchAll(/@("[^"]+"|[A-Za-z0-9_.\-]+)/g)) set.add(mm[1].replace(/^"|"$/g, ''));
  };
  scan(detail.content);
  for (const m of detail.messages || []) scan(m.body);
  return [...set];
}

function replyToText(rt?: NoteReplyTo | null): string | null {
  if (!rt) return null;
  if (rt.type === 'turn') {
    const session = rt.session || (typeof rt.id === 'string' ? rt.id : '');
    const turn = rt.turn ?? rt.id ?? '';
    return `↳ turn ${session ? `${session}#` : '#'}${turn}`;
  }
  if (rt.type) return `↳ ${rt.type} ${rt.id ?? ''}`.trim();
  return null;
}

// ── UI-state persistence ───────────────────────────────────────────────────
// The Notes Mgr is an `app`-type tab; switching away UNMOUNTS it, so plain
// useState would drop the selected note, open dialogs, and any draft text. We
// write-through to localStorage: pane-level state (selected note, status filter)
// under one key, and per-note action drafts (reply/edit/convert/@session — text
// AND which form is open) under a per-note key, so returning restores exactly
// where you were.
const PANE_KEY = 'uai:notesMgr:pane';
const draftKey = (noteId: string) => `uai:notesMgr:draft:${noteId}`;

interface NoteActionDraft {
  reply: string;
  editing: boolean;
  editText: string;
  convertOpen: boolean;
  convertTitle: string;
  convertAssignee: string;
  mentionOpen: boolean;
  mentionTarget: string;
  mentionMsg: string;
}
const EMPTY_DRAFT: NoteActionDraft = {
  reply: '', editing: false, editText: '', convertOpen: false, convertTitle: '',
  convertAssignee: '', mentionOpen: false, mentionTarget: '', mentionMsg: '',
};

type NoteListView = 'expanded' | 'compact';
function loadPane(): { selectedId: string | null; statusFilter: string; listView: NoteListView } {
  // Default to showing only Open notes (persisted choice wins once set).
  try {
    const raw = localStorage.getItem(PANE_KEY);
    if (raw) return { selectedId: null, statusFilter: 'open', listView: 'expanded', ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return { selectedId: null, statusFilter: 'open', listView: 'expanded' };
}
function savePane(p: { selectedId: string | null; statusFilter: string; listView: NoteListView }): void {
  try { localStorage.setItem(PANE_KEY, JSON.stringify(p)); } catch { /* ignore */ }
}

// ── Unseen-update tracking (in-app only) ────────────────────────────────────
// A note is "unseen" if its message count grew since you last opened it.
// Opening a note (selecting it) marks it seen at its current message count.
const NOTE_SEEN_KEY = 'uai:notesSeen';
function loadSeen(): Record<string, number> {
  try { return JSON.parse(localStorage.getItem(NOTE_SEEN_KEY) || '{}') as Record<string, number>; }
  catch { return {}; }
}
function saveSeen(m: Record<string, number>): void {
  try { localStorage.setItem(NOTE_SEEN_KEY, JSON.stringify(m)); } catch { /* ignore */ }
}
function noteUnseen(n: { id: string; messages?: number }, seen: Record<string, number>): boolean {
  return (n.messages ?? 0) > (seen[n.id] ?? 0);
}

const STATUS_PILLS: { key: string; label: string }[] = [
  { key: '', label: 'All' },
  { key: 'draft', label: 'Draft' },
  { key: 'open', label: 'Open' },
  { key: 'resolved', label: 'Resolved' },
  { key: 'archived', label: 'Archived' },
];
function loadDraft(noteId: string): NoteActionDraft {
  try {
    const raw = localStorage.getItem(draftKey(noteId));
    if (raw) return { ...EMPTY_DRAFT, ...JSON.parse(raw) };
  } catch { /* ignore */ }
  return { ...EMPTY_DRAFT };
}
function saveDraft(noteId: string, d: NoteActionDraft): void {
  try {
    // Don't leave empty drafts lying around — clear the key when nothing's staged.
    const isEmpty = d.reply === '' && !d.editing && d.editText === '' && !d.convertOpen
      && d.convertTitle === '' && d.convertAssignee === '' && !d.mentionOpen
      && d.mentionTarget === '' && d.mentionMsg === '';
    if (isEmpty) localStorage.removeItem(draftKey(noteId));
    else localStorage.setItem(draftKey(noteId), JSON.stringify(d));
  } catch { /* ignore */ }
}

export default function NotesManagerPane(): JSX.Element {
  const [notes, setNotes] = useState<NoteListItem[]>([]);
  const [selectedId, setSelectedId] = useState<string | null>(() => loadPane().selectedId);
  const [detail, setDetail] = useState<NoteDetail | null>(null);
  const [statusFilter, setStatusFilter] = useState<string>(() => loadPane().statusFilter);
  const [listView, setListView] = useState<NoteListView>(() => loadPane().listView);
  const [seen, setSeen] = useState<Record<string, number>>(() => loadSeen());
  const [loading, setLoading] = useState(false);
  const [detailLoading, setDetailLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  // Draft being edited in the floating Add Note dialog (null = creating fresh).
  const [editDraft, setEditDraft] = useState<{ id: string; title: string; text: string } | null>(null);

  // ── Per-note action state (reply / edit / convert-to-todo / @session) ──────
  const [reply, setReply] = useState('');
  const [busy, setBusy] = useState<string | null>(null); // which action is in flight
  const [flash, setFlash] = useState<string | null>(null); // transient success banner
  const [editing, setEditing] = useState(false);
  const [editText, setEditText] = useState('');
  const [convertOpen, setConvertOpen] = useState(false);
  const [convertTitle, setConvertTitle] = useState('');
  const [convertAssignee, setConvertAssignee] = useState('');
  const [mentionOpen, setMentionOpen] = useState(false);
  const [mentionTarget, setMentionTarget] = useState('');
  const [mentionMsg, setMentionMsg] = useState('');

  const flashMsg = useCallback((m: string) => {
    setFlash(m);
    setTimeout(() => setFlash((cur) => (cur === m ? null : cur)), 4000);
  }, []);

  // Persist pane-level state (selected note + status filter) on every change.
  useEffect(() => { savePane({ selectedId, statusFilter, listView }); }, [selectedId, statusFilter, listView]);
  // Load the todo/note ref index so linked-todo chips resolve their tooltips (note_0039).
  useEffect(() => { ensureRefIndexLoaded(); }, []);

  // Opening a note marks it seen at its current message count (so it drops out
  // of the unseen badges). Re-fires if its count grows while it stays selected.
  useEffect(() => {
    if (!selectedId) return;
    const n = notes.find((x) => x.id === selectedId);
    if (!n) return;
    const mc = n.messages ?? 0;
    setSeen((prev) => {
      if ((prev[selectedId] ?? -1) === mc) return prev;
      const next = { ...prev, [selectedId]: mc };
      saveSeen(next);
      return next;
    });
  }, [selectedId, notes]);

  // Write-through a partial update to the CURRENT note's action draft. Every
  // draft-field change goes through here so a tab switch (unmount) never loses it.
  const patchDraft = useCallback((partial: Partial<NoteActionDraft>) => {
    if (!selectedId) return;
    saveDraft(selectedId, { ...loadDraft(selectedId), ...partial });
  }, [selectedId]);

  // ── @-autocomplete for the comment composer (Relay's reusable ./mention) ────
  const { sessions } = useSessionStore();
  const replyRef = useRef<HTMLTextAreaElement>(null);
  const mentionTargets = useMemo(
    // Active (running) sessions only — no stale ghosts in the @ list (note_0035).
    () => sessions
      .filter((s) => !s.archived && s.display_name && s.process_status === 'running')
      .map((s) => {
        const name = s.display_name || s.tracking_id;
        return { token: mentionToken(name), label: name, kind: 'session' as const, count: 1, memberIds: [s.tracking_id] };
      }),
    [sessions],
  );
  const mentionTargetsRef = useRef(mentionTargets);
  mentionTargetsRef.current = mentionTargets;
  const mentionSources = useMemo(() => [makeRecipientSource(() => mentionTargetsRef.current)], []);
  const commitReplyMention = useCallback((next: string, caret: number) => {
    setReply(next);
    patchDraft({ reply: next });
    requestAnimationFrame(() => { const ta = replyRef.current; ta?.focus(); ta?.setSelectionRange(caret, caret); });
  }, [patchDraft]);
  const mention = useMention({ textareaRef: replyRef, sources: mentionSources, onApply: commitReplyMention });
  // Second @-autocomplete instance for the Edit-body textarea (its own ref/value).
  const editRef = useRef<HTMLTextAreaElement>(null);
  const commitEditMention = useCallback((next: string, caret: number) => {
    setEditText(next);
    patchDraft({ editText: next });
    requestAnimationFrame(() => { const ta = editRef.current; ta?.focus(); ta?.setSelectionRange(caret, caret); });
  }, [patchDraft]);
  const editMention = useMention({ textareaRef: editRef, sources: mentionSources, onApply: commitEditMention });

  // Viewport reporter — surfaces the Notes Mgr's list + selected note (with its
  // content/thread/captures counts) into "Capture Content" (describeViewport),
  // instead of an empty dead node. Top ~20 notes summarized as inline children.
  useViewport('notes_manager', () => ({
    visible: true,
    label: 'Notes Mgr',
    state: {
      statusFilter, total: notes.length, selectedId,
      selected: detail ? {
        id: detail.id,
        status: (detail.meta?.status as string) || null,
        recipients: (detail.meta?.recipients as string[]) || [],
        messages: detail.messages?.length ?? 0,
        captures: detail.captures?.length ?? 0,
        contentChars: detail.content?.length ?? 0,
      } : null,
    },
    children: notes.slice(0, 20).map((n) => ({
      id: `note.${n.id}`,
      label: n.summary || n.id,
      visible: true,
      state: { id: n.id, status: n.status, messages: n.messages, recipients: n.recipients || [] },
      children: [],
    })),
  }));

  const loadList = useCallback(async () => {
    setLoading(true);
    // Load ALL notes; status filtering (+ future sort/group) happens client-side
    // so per-status badge counts can see the whole set.
    const res = await executeCommand<{ notes: NoteListItem[] }>('note.list', {}, { onFailure: 'log' });
    if (res.ok && res.data) {
      setNotes(res.data.notes || []);
      setError(null);
    } else {
      setError(res.error?.message || 'Failed to load notes');
    }
    setLoading(false);
  }, []);

  const loadDetail = useCallback(async (id: string) => {
    setDetailLoading(true);
    const res = await executeCommand<{ note: NoteDetail }>('note.read', { id }, { onFailure: 'log' });
    if (res.ok && res.data) {
      setDetail(res.data.note);
    } else {
      setDetail(null);
    }
    setDetailLoading(false);
  }, []);

  // Focus a specific note when a linkified note_#### ref is clicked elsewhere
  // (RefLink.focusNoteInNotesMgr). Consume a pending focus on mount and listen
  // for live events. Clear the status filter so the target isn't hidden; the
  // [selectedId] effect loads its detail.
  const focusNote = useCallback((id: string) => { setStatusFilter(''); setSelectedId(id); }, []);
  useEffect(() => {
    const pending = consumePendingNoteFocus();
    if (pending) focusNote(pending);
    const onFocus = (e: Event) => {
      const id = (e as CustomEvent<{ id: string }>).detail?.id;
      if (id) focusNote(id);
    };
    window.addEventListener('uai:notesMgr:focusNote', onFocus);
    return () => window.removeEventListener('uai:notesMgr:focusNote', onFocus);
  }, [focusNote]);

  // Clicking a DRAFT reopens it in the floating Add Note dialog (rather than the
  // read/thread panel) so you can finish it. Reads its body/title first.
  const openDraft = useCallback(async (id: string) => {
    const res = await executeCommand<{ note: NoteDetail }>('note.read', { id }, { onFailure: 'log' });
    const note = res.ok ? res.data?.note : null;
    setEditDraft({
      id,
      title: (note?.meta?.title as string) || '',
      text: note?.content || '',
    });
    setDialogOpen(true);
  }, []);

  // Route a list-row click by status: drafts reopen in the dialog; the rest open
  // in the detail/thread panel.
  const handleRowClick = useCallback((n: { id: string; status?: string }) => {
    if ((n.status || '').toLowerCase() === 'draft') openDraft(n.id);
    else setSelectedId(n.id);
  }, [openDraft]);

  useEffect(() => {
    loadList();
  }, [loadList]);

  // Auto-refresh the list whenever ANY note changes — created via the global
  // Add Note pill, another session, or an MCP call — not just this pane's own
  // actions (note_0020: list wasn't updating without a manual reload).
  useEffect(() => {
    const unsub = window.uai.onStoreChanged?.((e: { changed?: string[] }) => {
      if (e.changed?.includes('notes')) loadList();
    });
    return () => { unsub?.(); };
  }, [loadList]);

  useEffect(() => {
    if (selectedId) loadDetail(selectedId);
    else setDetail(null);
    // Restore this note's persisted action draft (text + which form was open).
    const d = selectedId ? loadDraft(selectedId) : EMPTY_DRAFT;
    setReply(d.reply);
    setEditing(d.editing);
    setEditText(d.editText);
    setConvertOpen(d.convertOpen);
    setConvertTitle(d.convertTitle);
    setConvertAssignee(d.convertAssignee);
    setMentionOpen(d.mentionOpen);
    setMentionTarget(d.mentionTarget);
    setMentionMsg(d.mentionMsg);
  }, [selectedId, loadDetail]);

  const handleSetStatus = useCallback(async (id: string, status: string) => {
    const res = await executeCommand('note.setStatus', { id, status }, { onFailure: 'log' });
    if (res.ok) {
      await loadList();
      if (selectedId === id) await loadDetail(id);
    }
  }, [loadList, loadDetail, selectedId]);

  // Right-click a list row → change its status (note_0444). Set-status is the
  // only note-mutation command wired; 'archived' is the soft-delete.
  const handleRowContextMenu = useCallback((e: React.MouseEvent, n: { id: string; status?: string }) => {
    const cur = (n.status || '').toLowerCase();
    const items: ContextMenuItem[] = STATUSES.map((s) => ({
      label: cur === s ? `✓ ${s}` : `Mark ${s}`,
      action: () => handleSetStatus(n.id, s),
      disabled: cur === s,
    }));
    showContextMenu(e, items);
  }, [handleSetStatus]);

  // Keep the open note visible (note_0036): when a note is opened whose status
  // the active filter would hide, switch the filter to the pill matching it.
  // Fires once per newly-selected note so it never fights a manual filter change.
  const lastAutoFilterId = useRef<string | null>(null);
  useEffect(() => {
    if (!selectedId || !detail) return;
    if (lastAutoFilterId.current === selectedId) return;
    const st = ((detail.meta?.status as string) || '').toLowerCase();
    if (st && statusFilter && statusFilter !== st) setStatusFilter(st);
    lastAutoFilterId.current = selectedId;
  }, [selectedId, detail, statusFilter]);

  // ── Comment: append a message to the note's thread ─────────────────────────
  // Any @name tokens in the body are treated as mentions: after the comment is
  // posted, each named session is notified via comms (pointed at this note), so
  // "@Anvil" in a comment actually reaches Anvil rather than being inert text.
  const handleReply = useCallback(async () => {
    if (!detail || !reply.trim()) return;
    setBusy('reply');
    const body = reply.trim();
    const res = await executeCommand('note.addMessage',
      { id: detail.id, author: NOTE_AUTHOR, body }, { onFailure: 'log' });
    if (!res.ok) {
      setBusy(null);
      setError(res.error?.message || 'Failed to add comment');
      return;
    }
    // Notify any @mentioned sessions (dedup; ignore the author's own name).
    const mentions = [...new Set((body.match(/@([A-Za-z0-9_-]{2,})/g) || [])
      .map((s) => s.slice(1)))].filter((n) => n.toLowerCase() !== NOTE_AUTHOR.toLowerCase());
    const notified: string[] = [];
    const failed: string[] = [];
    for (const name of mentions) {
      const content =
        `${NOTE_AUTHOR} mentioned you in note ${detail.id}:\n\n${body}\n\n` +
        `Reply into its thread with ` +
        `workflow_note_add_message(identifier="${detail.id}", author="<you>", body="…").`;
      const sent = await executeCommand('comms.send',
        { from: USER_SENDER, to: name, content, urgency: 'prompt', subject: `Note ${detail.id}` },
        { onFailure: 'log' });
      (sent.ok ? notified : failed).push(name);
    }
    setBusy(null);
    setReply('');
    patchDraft({ reply: '' });
    await loadDetail(detail.id);
    await loadList();
    if (notified.length || failed.length) {
      const parts: string[] = [];
      if (notified.length) parts.push(`notified ${notified.map((n) => '@' + n).join(', ')}`);
      if (failed.length) parts.push(`couldn't resolve ${failed.map((n) => '@' + n).join(', ')}`);
      flashMsg(`Comment posted — ${parts.join('; ')}.`);
    }
  }, [detail, reply, loadDetail, loadList, patchDraft, flashMsg]);

  // ── Delete a captured-context item from the note ───────────────────────────
  const handleDeleteCapture = useCallback(async (file: string) => {
    if (!detail) return;
    const res = await executeCommand('note.deleteCapture', { id: detail.id, file }, { onFailure: 'log' });
    if (res.ok) { await loadDetail(detail.id); flashMsg('Capture removed.'); }
    else setError(res.error?.message || 'Failed to delete capture');
  }, [detail, loadDetail, flashMsg]);

  // ── Edit: rewrite the note body (content.md) ───────────────────────────────
  const startEdit = useCallback(() => {
    const body = detail?.content || '';
    setEditText(body);
    setEditing(true);
    patchDraft({ editing: true, editText: body });
  }, [detail, patchDraft]);

  const handleSaveEdit = useCallback(async () => {
    if (!detail || !editText.trim()) return;
    setBusy('edit');
    const res = await executeCommand('note.edit',
      { id: detail.id, text: editText.trim() }, { onFailure: 'log' });
    setBusy(null);
    if (res.ok) {
      setEditing(false);
      patchDraft({ editing: false, editText: '' });
      await loadDetail(detail.id);
      flashMsg('Note body updated.');
    } else {
      setError(res.error?.message || 'Failed to edit note');
    }
  }, [detail, editText, loadDetail, flashMsg, patchDraft]);

  // ── Convert to todo: create a todo from the note, link it, optional assign ──
  const handleConvert = useCallback(async () => {
    if (!detail || !convertTitle.trim()) return;
    setBusy('convert');
    const created = await executeCommand<{ out: string }>('todo.create',
      { name: convertTitle.trim() }, { onFailure: 'log' });
    if (!created.ok) {
      setBusy(null);
      setError(created.error?.message || 'Failed to create todo');
      return;
    }
    const m = (created.data?.out || '').match(/Created:\s*(todo_\d+\S*)/);
    const todoId = m?.[1];
    if (!todoId) {
      setBusy(null);
      setError('Todo created but its id could not be parsed.');
      return;
    }
    // Carry the note body into the todo's notes.md, with a back-reference.
    await executeCommand('todo.writeNotes',
      { id: todoId, content: `${detail.content || ''}\n\n— converted from ${detail.id}\n` },
      { onFailure: 'log' });
    // Record the linkage on the note (resulted_in[]).
    await executeCommand('note.linkTodo', { id: detail.id, todo: todoId }, { onFailure: 'log' });
    // Optional: assign the new todo to a session/project/team URI.
    let assignNote = '';
    if (convertAssignee.trim()) {
      const asg = await executeCommand('todo.assign',
        { id: todoId, uri: convertAssignee.trim() }, { onFailure: 'log' });
      assignNote = asg.ok ? ` → ${convertAssignee.trim()}` : ' (assign failed)';
    }
    setBusy(null);
    setConvertOpen(false);
    setConvertTitle('');
    setConvertAssignee('');
    patchDraft({ convertOpen: false, convertTitle: '', convertAssignee: '' });
    await loadDetail(detail.id);
    flashMsg(`Created ${todoId}${assignNote}.`);
  }, [detail, convertTitle, convertAssignee, loadDetail, flashMsg, patchDraft]);

  // ── @session: pull a session into the note by notifying it via comms ───────
  const handleMention = useCallback(async () => {
    if (!detail || !mentionTarget.trim()) return;
    // The mention field / autocomplete may include a leading "@" (e.g. "@Prism").
    // The comms recipient resolver matches on the bare name/id, so strip it —
    // sending "@Prism" fails with "no recipient matched '@Prism'".
    const target = mentionTarget.trim().replace(/^@+/, '');
    if (!target) return;
    setBusy('mention');
    const summary = (detail.content || '').trim().split('\n')[0].slice(0, 120);
    const extra = mentionMsg.trim() ? `\n\n${mentionMsg.trim()}` : '';
    const content =
      `You've been pulled into note ${detail.id}: "${summary}".${extra}\n\n` +
      `Reply into its thread with ` +
      `workflow_note_add_message(identifier="${detail.id}", author="<you>", body="…").`;
    const sent = await executeCommand('comms.send',
      { from: USER_SENDER, to: target, content, urgency: 'prompt', subject: `Note ${detail.id}` },
      { onFailure: 'log' });
    if (!sent.ok) {
      setBusy(null);
      setError(sent.error?.message || 'Failed to notify session');
      return;
    }
    // Record the @mention in the thread so the note itself shows who was pulled in.
    await executeCommand('note.addMessage',
      { id: detail.id, author: NOTE_AUTHOR, body: `@${target} pulled into this note.` },
      { onFailure: 'log' });
    setBusy(null);
    setMentionOpen(false);
    setMentionTarget('');
    setMentionMsg('');
    patchDraft({ mentionOpen: false, mentionTarget: '', mentionMsg: '' });
    await loadDetail(detail.id);
    flashMsg(`Notified ${target}.`);
  }, [detail, mentionTarget, mentionMsg, loadDetail, flashMsg, patchDraft]);

  const detailStatus = (detail?.meta?.status as string) || '';
  const selNote = notes.find((n) => n.id === selectedId);

  // Client-side status filter + per-status unseen-update counts (for pill badges).
  const filteredNotes = statusFilter
    ? notes.filter((n) => (n.status || '').toLowerCase() === statusFilter)
    : notes;
  const unseenByStatus = useMemo(() => {
    const m: Record<string, number> = { '': 0, open: 0, resolved: 0, archived: 0 };
    for (const n of notes) {
      if (!noteUnseen(n, seen)) continue;
      m[''] += 1;
      const s = (n.status || '').toLowerCase();
      if (s in m) m[s] += 1;
    }
    return m;
  }, [notes, seen]);

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', overflow: 'hidden', background: 'var(--bg-deep)', color: 'var(--text)', fontSize: 13 }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
        <TabNavArrows />
        <div style={{ fontWeight: 700, color: '#fff', fontSize: 14 }}>Notes Mgr</div>
        <button
          onClick={() => { setEditDraft(null); setDialogOpen(true); }}
          style={{ background: 'var(--accent-blue-bg)', border: '1px solid var(--accent-blue)', color: 'var(--text)', borderRadius: 6, padding: '4px 11px', fontSize: 12, cursor: 'pointer', fontWeight: 600 }}
        >
          {'＋'} New Note
        </button>
        <button
          onClick={loadList}
          disabled={loading}
          style={{ background: 'var(--accent-blue-bg)', border: '1px solid var(--accent-blue)', color: 'var(--text)', borderRadius: 6, padding: '4px 11px', fontSize: 12, cursor: 'pointer' }}
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>

      {/* Status filter pills — each shows a badge with the # of notes in that
          status that have unseen updates (hidden when 0). Right side: a segmented
          Expanded/Compact toggle for the list density. */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px', borderBottom: '1px solid var(--border)', flexWrap: 'wrap' }}>
        {STATUS_PILLS.map((p) => {
          const on = statusFilter === p.key;
          const badge = unseenByStatus[p.key] || 0;
          return (
            <button
              key={p.key || 'all'}
              onClick={() => setStatusFilter(p.key)}
              style={{
                display: 'flex', alignItems: 'center', gap: 6,
                background: on ? 'var(--accent-blue-bg)' : 'var(--bg-panel)',
                border: `1px solid ${on ? 'var(--accent-blue)' : 'var(--border)'}`,
                color: on ? 'var(--text)' : 'var(--text-sec)',
                borderRadius: 999, padding: '3px 12px', fontSize: 12,
                fontWeight: on ? 600 : 400, cursor: 'pointer', textTransform: 'capitalize',
              }}
            >
              {p.label}
              {badge > 0 && (
                <span style={{
                  background: 'var(--accent-orange)', color: 'var(--bg-deep)',
                  borderRadius: 999, minWidth: 16, height: 16, padding: '0 4px',
                  fontSize: 10.5, fontWeight: 700, display: 'inline-flex',
                  alignItems: 'center', justifyContent: 'center', lineHeight: 1,
                }}>{badge}</span>
              )}
            </button>
          );
        })}
        {/* List density toggle — Expanded (rich rows) vs Compact (2 lines). */}
        <div style={{ marginLeft: 'auto', display: 'inline-flex', borderRadius: 999, overflow: 'hidden', border: '1px solid var(--border)' }}>
          {(['expanded', 'compact'] as NoteListView[]).map((v) => {
            const on = listView === v;
            return (
              <button
                key={v}
                onClick={() => setListView(v)}
                title={v === 'expanded' ? 'Expanded rows' : 'Compact rows (2 lines)'}
                style={{
                  background: on ? 'var(--accent-blue-bg)' : 'transparent',
                  color: on ? 'var(--text)' : 'var(--text-muted)',
                  border: 'none', padding: '3px 11px', fontSize: 11.5,
                  fontWeight: on ? 600 : 400, cursor: 'pointer', textTransform: 'capitalize',
                }}
              >{v}</button>
            );
          })}
        </div>
      </div>

      {error && (
        <div style={{ padding: '10px 16px', color: 'var(--accent-orange)', fontSize: 12 }}>{'⚠'} {error}</div>
      )}

      {/* Split body */}
      <div style={{ flex: 1, display: 'flex', minHeight: 0 }}>
        {/* Left — list. overflowY:auto + the parent's minHeight:0 keep the list
            scrolling independently (note_0034 #0). */}
        <div style={{ width: 340, minWidth: 280, borderRight: '1px solid var(--border)', overflowY: 'auto', overflowX: 'hidden' }}>
          {filteredNotes.length === 0 && !loading && (
            <div style={{ padding: '14px 16px', color: 'var(--text-muted)', fontSize: 12 }}>No notes.</div>
          )}
          {filteredNotes.map((n) => {
            const active = n.id === selectedId;
            const unseen = noteUnseen(n, seen);
            const sc = STATUS_COLOR[n.status] || 'var(--text-muted)';
            const compact = listView === 'compact';
            const noteIdShort = (n.id.match(/^(?:note)_\d+/) || [n.id])[0];
            const recipients = n.recipients || [];
            return (
              <div
                key={n.id}
                onClick={() => handleRowClick(n)}
                onContextMenu={(e) => handleRowContextMenu(e, n)}
                style={{
                  padding: compact ? '6px 14px' : '10px 14px', cursor: 'pointer',
                  borderBottom: '1px solid var(--border)',
                  // Status-tinted: a colored left rail + a faint status wash so the
                  // list reads as colored blocks at a glance; brighter when active.
                  background: active
                    ? `color-mix(in srgb, ${sc} 20%, var(--bg-card))`
                    : `color-mix(in srgb, ${sc} 7%, transparent)`,
                  borderLeft: `3px solid ${sc}`,
                }}
              >
                {compact ? (
                  <>
                    {/* Line 1: id · status · tagged sessions · (unseen) · msgs */}
                    <div style={{ display: 'flex', alignItems: 'center', gap: 7, whiteSpace: 'nowrap', overflow: 'hidden' }}>
                      <span title={n.id} style={{ color: 'var(--accent-cyan)', fontSize: 10.5, fontFamily: 'var(--font-mono)', flexShrink: 0 }}>{noteIdShort}</span>
                      <span style={{
                        background: `color-mix(in srgb, ${sc} 22%, transparent)`, color: sc,
                        border: `1px solid color-mix(in srgb, ${sc} 55%, transparent)`,
                        borderRadius: 4, padding: '0 6px', fontSize: 10, fontWeight: 700,
                        textTransform: 'capitalize', flexShrink: 0,
                      }}>{n.status}</span>
                      <span style={{ display: 'inline-flex', gap: 5, overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0 }}>
                        {recipients.map((r) => (
                          <span key={r} style={{ color: senderColor(r), fontWeight: 600, fontSize: 10.5 }}>{r}</span>
                        ))}
                      </span>
                      {unseen && <span title="unseen updates" style={{ marginLeft: 'auto', width: 7, height: 7, borderRadius: 999, background: 'var(--accent-orange)', flexShrink: 0 }} />}
                      <span style={{ marginLeft: unseen ? 5 : 'auto', color: 'var(--text-muted)', fontSize: 10.5, flexShrink: 0 }}>{n.messages}m</span>
                    </div>
                    {/* Line 2: title only, truncated, never wrapped */}
                    <div title={n.title || n.summary || n.id} style={{
                      color: 'var(--text)', fontSize: 12, lineHeight: 1.3, marginTop: 2,
                      fontWeight: n.title ? 700 : 400, whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
                    }}>
                      {n.title || n.summary || n.id}
                    </div>
                  </>
                ) : (
                <>
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
                  <span title={n.id} style={{ color: 'var(--accent-cyan)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
                    {noteIdShort}
                  </span>
                  <span style={{
                    background: `color-mix(in srgb, ${sc} 22%, transparent)`, color: sc,
                    border: `1px solid color-mix(in srgb, ${sc} 55%, transparent)`,
                    borderRadius: 4, padding: '1px 7px', fontSize: 10.5, fontWeight: 700,
                    textTransform: 'capitalize', letterSpacing: '.02em',
                  }}>{n.status}</span>
                  {unseen && (
                    <span title="unseen updates" style={{ marginLeft: 'auto', width: 8, height: 8, borderRadius: 999, background: 'var(--accent-orange)', flexShrink: 0 }} />
                  )}
                  <span style={{ marginLeft: unseen ? 6 : 'auto', color: 'var(--text-muted)', fontSize: 11 }}>{n.messages} msg</span>
                </div>
                <div style={{ color: 'var(--text)', fontSize: 12.5, lineHeight: 1.35, marginBottom: 3, fontWeight: n.title ? 700 : 400 }}>
                  {n.title || n.summary || n.id}
                  {n.title && n.summary && (
                    <span style={{ display: 'block', color: 'var(--text-muted)', fontSize: 11, fontWeight: 400, marginTop: 1 }}>{n.summary}</span>
                  )}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 5, fontSize: 11 }}>
                  {(n.recipients || []).map((r) => (
                    <span key={r} style={{ color: senderColor(r), fontWeight: 600 }}>{r}</span>
                  ))}
                </div>
                </>
                )}
              </div>
            );
          })}
        </div>

        {/* Right — thread */}
        <div style={{ flex: 1, overflow: 'auto', minWidth: 0 }}>
          {!selectedId && (
            <div style={{ padding: '18px 18px', color: 'var(--text-muted)', fontSize: 12 }}>Select a note to view its thread.</div>
          )}
          {selectedId && detailLoading && (
            <div style={{ padding: '18px 18px', color: 'var(--text-muted)', fontSize: 12 }}>Loading…</div>
          )}
          {selectedId && !detailLoading && detail && (
            <div style={{ padding: '16px 18px' }}>
              {/* Note header — id · name · tagged sessions, ABOVE the status (note_0036). */}
              <div style={{ marginBottom: 12, paddingBottom: 10, borderBottom: '1px solid var(--border)' }}>
                <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
                  <span style={{ color: 'var(--accent-cyan)', fontFamily: 'var(--font-mono)', fontSize: 12 }}>{detail.id}</span>
                  <span style={{ color: 'var(--text)', fontWeight: 700, fontSize: 14 }}>
                    {selNote?.title || (detail.content || '').trim().split('\n')[0].slice(0, 90) || '(untitled)'}
                  </span>
                </div>
                {(selNote?.recipients || []).length > 0 && (
                  <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 5, flexWrap: 'wrap' }}>
                    <span style={{ color: 'var(--text-muted)', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.05em' }}>Tagged</span>
                    {(selNote?.recipients || []).map((r) => (
                      <span key={r} style={{ color: senderColor(r), fontWeight: 600, fontSize: 11.5 }}>{r}</span>
                    ))}
                  </div>
                )}
              </div>

              {/* Metadata (note_0039): created / updated, linked todos, involved sessions. */}
              {(() => {
                const created = (selNote?.created_at || detail.meta?.created_at) as string | undefined;
                const updated = (selNote?.updated_at || detail.meta?.updated_at) as string | undefined;
                const linked = Array.isArray(detail.meta?.resulted_in) ? (detail.meta!.resulted_in as string[]) : [];
                const involved = involvedSessions(detail);
                const LBL = { color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase' as const, letterSpacing: '.05em', fontWeight: 700, marginRight: 4 };
                const rows: JSX.Element[] = [];
                if (created) rows.push(<div key="c"><span style={LBL}>Created</span><span style={{ color: 'var(--text-sec)', fontSize: 11.5 }}>{fmtTime(created)}</span></div>);
                if (updated && updated !== created) rows.push(<div key="u"><span style={LBL}>Updated</span><span style={{ color: 'var(--text-sec)', fontSize: 11.5 }}>{fmtTime(updated)}</span></div>);
                if (linked.length) rows.push(
                  <div key="t"><span style={LBL}>Todos</span>
                    {linked.map((id) => <span key={id} style={{ marginRight: 8 }}><TodoLink id={id} /></span>)}
                  </div>
                );
                if (involved.length) rows.push(
                  <div key="i" style={{ display: 'flex', alignItems: 'baseline', gap: 6, flexWrap: 'wrap' }}>
                    <span style={LBL}>Involved</span>
                    {involved.map((s) => <span key={s} style={{ color: senderColor(s), fontWeight: 600, fontSize: 11.5 }}>{s}</span>)}
                  </div>
                );
                if (!rows.length) return null;
                return (
                  <div style={{ display: 'flex', flexDirection: 'column', gap: 4, marginBottom: 12, padding: '8px 11px', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 8 }}>
                    {rows}
                  </div>
                );
              })()}

              {/* Actions toolbar — status + Edit / Convert / @session */}
              <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
                <span style={{ color: 'var(--text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.05em', fontWeight: 700 }}>Status</span>
                <select
                  value={detailStatus}
                  onChange={(e) => handleSetStatus(detail.id, e.target.value)}
                  style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 6, padding: '3px 8px', fontSize: 12 }}
                >
                  {STATUSES.map((s) => <option key={s} value={s}>{s}</option>)}
                </select>
                <span style={{ width: 1, height: 18, background: 'var(--border)', margin: '0 2px' }} />
                <button
                  onClick={() => {
                    if (editing) { setEditing(false); patchDraft({ editing: false }); }
                    else startEdit();
                  }}
                  style={ACT_BTN}
                >{editing ? '✕ Cancel edit' : '✎ Edit'}</button>
                <button
                  onClick={() => {
                    const nv = !convertOpen;
                    const title = nv ? (detail.content || '').trim().split('\n')[0].slice(0, 80) : convertTitle;
                    setConvertOpen(nv); setMentionOpen(false); setConvertTitle(title);
                    patchDraft({ convertOpen: nv, mentionOpen: false, convertTitle: title });
                  }}
                  style={ACT_BTN}
                >{'→ Convert to Todo'}</button>
                <button
                  onClick={() => {
                    const nv = !mentionOpen;
                    setMentionOpen(nv); setConvertOpen(false);
                    patchDraft({ mentionOpen: nv, convertOpen: false });
                  }}
                  style={ACT_BTN}
                >{'@ Add session'}</button>
              </div>

              {flash && (
                <div style={{ background: 'rgba(92,214,147,0.12)', border: '1px solid var(--accent-green)', color: 'var(--accent-green)', borderRadius: 6, padding: '6px 10px', fontSize: 12, marginBottom: 12 }}>
                  {'✓'} {flash}
                </div>
              )}

              {/* Convert-to-todo inline form */}
              {convertOpen && (
                <div style={PANEL}>
                  <div style={PANEL_TITLE}>Convert to todo</div>
                  <input
                    value={convertTitle}
                    onChange={(e) => { setConvertTitle(e.target.value); patchDraft({ convertTitle: e.target.value }); }}
                    placeholder="Todo title"
                    style={FIELD}
                  />
                  <input
                    value={convertAssignee}
                    onChange={(e) => { setConvertAssignee(e.target.value); patchDraft({ convertAssignee: e.target.value }); }}
                    placeholder="Assign to (optional) — uai://session|project|team/<id>"
                    style={FIELD}
                  />
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                    <button onClick={() => { setConvertOpen(false); patchDraft({ convertOpen: false }); }} style={GHOST_BTN}>Cancel</button>
                    <button onClick={handleConvert} disabled={!convertTitle.trim() || busy === 'convert'} style={PRIMARY_BTN(!!convertTitle.trim() && busy !== 'convert')}>
                      {busy === 'convert' ? 'Creating…' : 'Create todo'}
                    </button>
                  </div>
                </div>
              )}

              {/* @session inline form */}
              {mentionOpen && (
                <div style={PANEL}>
                  <div style={PANEL_TITLE}>Pull a session into this note</div>
                  <input
                    value={mentionTarget}
                    onChange={(e) => { setMentionTarget(e.target.value); patchDraft({ mentionTarget: e.target.value }); }}
                    placeholder="Session (tracking id, name, or uai://session/<id>)"
                    style={FIELD}
                  />
                  <textarea
                    value={mentionMsg}
                    onChange={(e) => { setMentionMsg(e.target.value); patchDraft({ mentionMsg: e.target.value }); }}
                    placeholder="Optional message to include…"
                    rows={2}
                    style={{ ...FIELD, resize: 'vertical', fontFamily: 'inherit' }}
                  />
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8 }}>
                    <button onClick={() => { setMentionOpen(false); patchDraft({ mentionOpen: false }); }} style={GHOST_BTN}>Cancel</button>
                    <button onClick={handleMention} disabled={!mentionTarget.trim() || busy === 'mention'} style={PRIMARY_BTN(!!mentionTarget.trim() && busy !== 'mention')}>
                      {busy === 'mention' ? 'Notifying…' : 'Notify + add to thread'}
                    </button>
                  </div>
                </div>
              )}

              {/* content.md — read view or edit view */}
              {editing ? (
                <div style={{ marginBottom: 16 }}>
                  <textarea
                    autoFocus
                    ref={editRef}
                    value={editText}
                    onChange={(e) => { setEditText(e.target.value); patchDraft({ editText: e.target.value }); editMention.sync(e.target.value, e.target.selectionStart ?? e.target.value.length); }}
                    rows={6}
                    style={{
                      width: '100%', boxSizing: 'border-box', resize: 'vertical',
                      background: 'var(--bg-deep)', color: 'var(--text)', border: '1px solid var(--accent-blue)',
                      borderRadius: 8, padding: '10px 12px', fontSize: 13, fontFamily: 'inherit', lineHeight: 1.55,
                    }}
                    onKeyDown={(e) => {
                      if (editMention.handleKeyDown(e)) return;
                      if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); void handleSaveEdit(); }
                      else if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setEditing(false); patchDraft({ editing: false }); }
                    }}
                  />
                  <MentionPopover state={editMention} />
                  <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 8 }}>
                    <button onClick={() => { setEditing(false); patchDraft({ editing: false }); }} style={GHOST_BTN} title="Esc">Cancel</button>
                    <button onClick={handleSaveEdit} disabled={!editText.trim() || busy === 'edit'} style={PRIMARY_BTN(!!editText.trim() && busy !== 'edit')} title="⌘/Ctrl+Enter">
                      {busy === 'edit' ? 'Saving…' : 'Save body (⌘↵)'}
                    </button>
                  </div>
                </div>
              ) : detail.content ? (
                <div
                  style={{
                    background: 'var(--bg-panel)', border: '1px solid var(--border)',
                    borderLeft: `3px solid ${senderColor((detail.meta?.created_by as string) || '')}`,
                    borderRadius: 8,
                    padding: '11px 13px', color: 'var(--text)', fontSize: 13, lineHeight: 1.55,
                    whiteSpace: 'pre-wrap', marginBottom: 16,
                  }}
                >
                  {detail.content}
                </div>
              ) : null}

              {/* Captured context — the view state attached when the note was created */}
              {detail.captures && detail.captures.length > 0 && (
                <div style={{ marginBottom: 16 }}>
                  <div style={{ color: 'var(--text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.05em', fontWeight: 700, marginBottom: 8 }}>
                    Captured context ({detail.captures.length})
                  </div>
                  {detail.captures.map((cap, i) => (
                    <div key={cap.file || i} style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderLeft: '3px solid var(--accent-cyan)', borderRadius: 8, padding: '9px 12px', marginBottom: 8, fontSize: 12.5 }}>
                      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, marginBottom: 6 }}>
                        <span style={{ color: 'var(--accent-cyan)', fontWeight: 600 }}>{cap.component_path || cap.source_tab || 'capture'}</span>
                        {cap.source_tab && cap.component_path && <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>{cap.source_tab}</span>}
                        {cap.captured_at && <span style={{ color: 'var(--text-muted)', fontSize: 11, marginLeft: 'auto' }}>{fmtTime(cap.captured_at)}</span>}
                        {cap.file && (
                          <button
                            onClick={() => handleDeleteCapture(cap.file!)}
                            title="Delete this capture"
                            style={{ marginLeft: cap.captured_at ? 8 : 'auto', background: 'transparent', border: 'none', color: 'var(--accent-red)', cursor: 'pointer', fontSize: 13, fontWeight: 700, padding: '0 2px', lineHeight: 1 }}
                          >{'✕'}</button>
                        )}
                      </div>
                      <div style={{ color: 'var(--text)', lineHeight: 1.5 }}>
                        <CaptureValue value={cap.data} />
                      </div>
                    </div>
                  ))}
                </div>
              )}

              {/* Messages */}
              <div style={{ color: 'var(--text-muted)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '.05em', fontWeight: 700, marginBottom: 8 }}>
                Thread ({detail.messages?.length || 0})
              </div>
              {(detail.messages || []).map((m) => {
                const rt = replyToText(m.reply_to);
                const c = senderColor(m.author);
                return (
                  <div
                    key={m.id}
                    style={{
                      borderLeft: `3px solid ${c}`, background: tint(c),
                      borderRadius: '0 6px 6px 0', padding: '8px 11px', marginBottom: 7,
                    }}
                  >
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 3 }}>
                      <span style={{ color: c, fontWeight: 700, fontSize: 12.5 }}>{m.author}</span>
                      <span style={{ color: 'var(--text-sec)', fontSize: 11 }}>{fmtTime(m.timestamp)}</span>
                      {rt && <span style={{ color: 'var(--accent-blue)', fontSize: 11 }}>{rt}</span>}
                    </div>
                    <div style={{ color: c, fontSize: 12.5, lineHeight: 1.5, whiteSpace: 'pre-wrap' }}>
                      {m.body}
                    </div>
                  </div>
                );
              })}

              {/* Reply composer — comment into the thread */}
              <div style={{ marginTop: 12, borderTop: '1px solid var(--border)', paddingTop: 12 }}>
                <textarea
                  ref={replyRef}
                  value={reply}
                  onChange={(e) => { setReply(e.target.value); patchDraft({ reply: e.target.value }); mention.sync(e.target.value, e.target.selectionStart ?? e.target.value.length); }}
                  placeholder={`Comment as ${NOTE_AUTHOR}…  (@ to mention · ⌘/Ctrl+Enter to send)`}
                  rows={3}
                  style={{
                    width: '100%', boxSizing: 'border-box', resize: 'vertical',
                    background: 'var(--bg-deep)', color: 'var(--text)', border: '1px solid var(--border)',
                    borderRadius: 8, padding: '9px 11px', fontSize: 12.5, fontFamily: 'inherit', lineHeight: 1.5,
                  }}
                  onKeyDown={(e) => { if (mention.handleKeyDown(e)) return; if ((e.metaKey || e.ctrlKey) && e.key === 'Enter') { e.preventDefault(); void handleReply(); } }}
                />
                <MentionPopover state={mention} />
                <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 8 }}>
                  <button onClick={handleReply} disabled={!reply.trim() || busy === 'reply'} style={PRIMARY_BTN(!!reply.trim() && busy !== 'reply')}>
                    {busy === 'reply' ? 'Sending…' : 'Comment'}
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      <NoteDialog
        isOpen={dialogOpen}
        onClose={() => { setDialogOpen(false); setEditDraft(null); }}
        mode="note"
        sourceTab="notes-manager"
        editNote={editDraft}
        onCreated={(noteId) => {
          loadList();
          setEditDraft(null);
          setSelectedId(noteId);
        }}
      />
    </div>
  );
}
