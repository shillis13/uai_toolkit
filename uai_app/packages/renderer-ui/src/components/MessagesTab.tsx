/**
 * MessagesTab — displays inbox/sent/archive messages for the active session.
 *
 * Features: hover tooltip, click-to-expand with a full detail layout (incl. a
 * link to offloaded message bodies), a [Select] mode with per-row checkboxes +
 * select-all, and a right-click context menu (Archive / Mark Unread / Reply /
 * Delete) that applies to all selected messages — mirroring TranscriptViewer.
 * Part of the right panel (ContextPanel) tab system.
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import type { InboxMessage, Session } from '@uai/shared/types';
import { scanSessionCommsCount } from '../stores/comms-count-state';
import { ReadFilterSplitPill, type ReadFilter } from './CommsReadFilter';
import { showContextMenu, type ContextMenuItem } from '../utils/context-menu';
import { sessionColor } from '../utils/session-color';
import { useSessionStore } from '../stores/session-store';
import { LinkifyRefs } from './RefLink';

type MsgFolder = 'inbox' | 'sent' | 'archive';

// The user is a first-class comms recipient (uai://user/<id>). Messages sent BY
// the user all share one fixed color; every session gets its own hash color.
const PRIMARY_USER_ID = 'piano_man';
const USER_COLOR = '#e8c07a'; // warm gold — distinct from the session palette
const USER_DISPLAY_NAMES: Record<string, string> = { piano_man: 'PianoMan' };

function isUser(from: string): boolean {
  return from === PRIMARY_USER_ID || from in USER_DISPLAY_NAMES;
}

/** Color for a given sender: one fixed color for the user, hash color per session. */
function senderColor(from: string): string {
  return isUser(from) ? USER_COLOR : sessionColor(from);
}

/**
 * Resolve a sender's display name: prefer a matching session's display_name,
 * then a known-user friendly name, else the extracted short name.
 */
function resolveDisplayName(from: string, sessions: readonly Session[]): string {
  const sess = sessions.find(s => s.tracking_id === from);
  if (sess && sess.display_name) return sess.display_name;
  if (from in USER_DISPLAY_NAMES) return USER_DISPLAY_NAMES[from];
  return extractSenderName(from);
}

// ── Draft persistence (per message id, across navigation / reopen) ──────────
const DRAFT_PREFIX = 'uai:msgDraft:';
function getDraft(msgId: string): string {
  try { return localStorage.getItem(DRAFT_PREFIX + msgId) || ''; } catch { return ''; }
}
function setDraft(msgId: string, text: string): void {
  try {
    if (text) localStorage.setItem(DRAFT_PREFIX + msgId, text);
    else localStorage.removeItem(DRAFT_PREFIX + msgId);
  } catch { /* storage unavailable — drafts simply won't persist */ }
}
function clearDraft(msgId: string): void {
  try { localStorage.removeItem(DRAFT_PREFIX + msgId); } catch { /* ignore */ }
}

// ── Selected subtab persistence (note_0024) ─────────────────────────────────
// The Comms folder (Inbox/Sent/Archive) and read filter are local state, so
// they reset to Inbox every time the right panel remounts on a tab change. The
// user wants the last-selected subtab to still be active on return, so we stash
// the choice in localStorage (a single global preference — the subtab you like,
// regardless of which session tab is active).
const FOLDER_KEY = 'uai:commsFolder';
const READFILTER_KEY = 'uai:commsReadFilter';
function loadFolder(): MsgFolder {
  try {
    const v = localStorage.getItem(FOLDER_KEY);
    if (v === 'inbox' || v === 'sent' || v === 'archive') return v;
  } catch { /* ignore */ }
  return 'inbox';
}
function saveFolder(f: MsgFolder): void {
  try { localStorage.setItem(FOLDER_KEY, f); } catch { /* ignore */ }
}
function loadReadFilter(): ReadFilter {
  try {
    const v = localStorage.getItem(READFILTER_KEY);
    if (v === 'all' || v === 'read' || v === 'unread') return v;
  } catch { /* ignore */ }
  return 'all';
}
function saveReadFilter(r: ReadFilter): void {
  try { localStorage.setItem(READFILTER_KEY, r); } catch { /* ignore */ }
}

// Read state is singular per message: for a direct message it's whether the
// RECIPIENT session has read it (its tracking_id in read_by) — the same predicate
// messaging.py uses for unread reminders / get-unread. So the app credits the
// recipient session (not a separate 'user'), making Mark Read/Unread here drop
// the message from / return it to the session's unread state.

const TYPE_BADGES: Record<string, { label: string; color: string }> = {
  request: { label: 'REQ', color: 'var(--accent-red, #f7768e)' },
  'expiring-request': { label: 'EXP-REQ', color: 'var(--accent-yellow, #e0af68)' },
  advisory: { label: 'FYI', color: 'var(--accent-blue, #7aa2f7)' },
  delivery: { label: 'DELIVER', color: 'var(--accent-green, #9ece6a)' },
  question: { label: '?', color: 'var(--accent-purple, #bb9af7)' },
};

const URGENCY_DOTS: Record<string, string> = {
  interrupt: 'var(--accent-red, #f7768e)',
  prompt: 'var(--accent-blue, #7aa2f7)',
  async: 'var(--text-muted, #565f89)',
  passive: 'var(--text-muted, #414868)',
};

function formatTime(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  } catch { return ''; }
}

function formatDateTime(iso: string): string {
  if (!iso) return '';
  try {
    return new Date(iso).toLocaleString(undefined, {
      weekday: 'short', year: 'numeric', month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  } catch { return iso; }
}

/** The recipient's read timestamp for a message, or undefined if unread. The
 *  reader is the addressee (Sent folder) or this session (Inbox/Archive). */
function readAtFor(msg: InboxMessage, readerId: string | null): string | undefined {
  if (!readerId) return undefined;
  return (msg.read_by || []).find((r) => r.by === readerId)?.at;
}

/**
 * A formatted hover tooltip for a message's timestamps + parties: full local
 * date-times for Sent and Read. (There is no separate delivered/received
 * timestamp — delivery is synchronous, so received == sent; PianoMan opted to
 * surface Read time instead of the redundant Received.)
 */
function receiptTooltip(msg: InboxMessage, sessions: readonly Session[], readerId: string | null): string {
  const readAt = readAtFor(msg, readerId);
  const lines = [
    `From:     ${resolveDisplayName(msg.from, sessions)}`,
    `To:       ${resolveDisplayName(msg.to || '', sessions)}`,
    msg.subject ? `Subject:  ${msg.subject}` : '',
    '',
    `Sent:     ${formatDateTime(msg.created_at)}`,
    readAt ? `Read:     ${formatDateTime(readAt)}` : `Read:     (unread)`,
  ];
  return lines.join('\n');
}

function formatSize(text: string): string {
  const bytes = new Blob([text || '']).size;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '...';
}

function extractSenderName(from: string): string {
  const parenMatch = from.match(/^([^(]+)\s*\(/);
  if (parenMatch) return parenMatch[1].trim();
  if (from.includes('_') && from.split('_').length >= 4) {
    return from.split('_').slice(2, 4).join('_');
  }
  return from.slice(0, 20);
}

interface MessagesTabProps {
  sessionTrackingId: string | null;
}

export default function MessagesTab({ sessionTrackingId }: MessagesTabProps): JSX.Element {
  // Initialize from the persisted preference (note_0024) so the subtab the user
  // last had open is still active after a tab change.
  const [folder, setFolderState] = useState<MsgFolder>(loadFolder);
  const [readFilter, setReadFilterState] = useState<ReadFilter>(loadReadFilter);
  const setFolder = useCallback((f: MsgFolder) => { setFolderState(f); saveFolder(f); }, []);
  const setReadFilter = useCallback((r: ReadFilter) => { setReadFilterState(r); saveReadFilter(r); }, []);
  const [messages, setMessages] = useState<InboxMessage[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [replyingTo, setReplyingTo] = useState<string | null>(null);
  const [replyText, setReplyText] = useState('');
  // The expanded message's conversation thread (root + replies), chronological.
  const [thread, setThread] = useState<InboxMessage[]>([]);
  const { sessions } = useSessionStore();

  // Assemble a message's conversation thread from all folders (replies land in
  // Sent, the root in Inbox, etc.), deduped + sorted oldest→newest. This is the
  // folder-assembled path; the canonical index fix is todo_0373.
  const loadThread = useCallback(async (msg: InboxMessage) => {
    if (!sessionTrackingId || !msg.conversation_id) { setThread([]); return; }
    try {
      const [inb, snt, arc] = (await Promise.all([
        window.uai.comms.inboxList(sessionTrackingId),
        window.uai.comms.sentList(sessionTrackingId),
        window.uai.comms.archiveList(sessionTrackingId),
      ])) as InboxMessage[][];
      const seen = new Set<string>();
      const convo = [...(inb || []), ...(snt || []), ...(arc || [])]
        .filter(m => {
          if (m.conversation_id !== msg.conversation_id || seen.has(m.id)) return false;
          seen.add(m.id);
          return true;
        })
        .sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
      setThread(convo);
    } catch {
      setThread([]);
    }
  }, [sessionTrackingId]);

  // Open the reply composer for a message, seeding text from any saved draft.
  const openReply = useCallback((msgId: string) => {
    setExpandedId(msgId);
    setReplyingTo(msgId);
    setReplyText(getDraft(msgId));
  }, []);

  // Update the active reply text and persist it as a draft for this message.
  const onReplyTextChange = useCallback((msgId: string, text: string) => {
    setReplyText(text);
    setDraft(msgId, text);
  }, []);

  // Close the composer. `discard` also clears the persisted draft (Send/Cancel).
  const closeReply = useCallback((msgId: string, discard: boolean) => {
    if (discard) clearDraft(msgId);
    setReplyingTo(null);
    setReplyText('');
  }, []);

  const loadMessages = useCallback(async () => {
    if (!sessionTrackingId) { setMessages([]); return; }
    setLoading(true);
    try {
      let result: InboxMessage[];
      if (folder === 'archive') {
        result = (await window.uai.comms.archiveList(sessionTrackingId)) as InboxMessage[];
      } else if (folder === 'sent') {
        result = (await window.uai.comms.sentList(sessionTrackingId)) as InboxMessage[];
      } else {
        result = (await window.uai.comms.inboxList(sessionTrackingId)) as InboxMessage[];
      }
      setMessages(result || []);
    } catch {
      setMessages([]);
    } finally {
      setLoading(false);
    }
  }, [sessionTrackingId, folder]);

  useEffect(() => { loadMessages(); }, [loadMessages]);
  // Reset transient UI when the folder or session changes.
  useEffect(() => { setSelectMode(false); setSelected(new Set()); setReplyingTo(null); setThread([]); setExpandedId(null); }, [folder, sessionTrackingId]);

  // Open/close a message. Opening loads its thread + (if unread) marks it read.
  const openMessage = useCallback((msg: InboxMessage) => {
    const collapsing = expandedId === msg.id;
    setExpandedId(collapsing ? null : msg.id);
    if (collapsing) { setThread([]); return; }
    loadThread(msg);
    if (folder === 'sent' || !sessionTrackingId) return;

    const reader = sessionTrackingId;
    const alreadyRead = !!msg.read_by && msg.read_by.some(r => r.by === reader);
    if (alreadyRead) return;

    setMessages(prev => prev.map(m =>
      m.id === msg.id
        ? { ...m, read_by: [...(m.read_by || []), { by: reader, at: new Date().toISOString() }] }
        : m,
    ));
    const revert = () => setMessages(prev => prev.map(m =>
      m.id === msg.id ? { ...m, read_by: (m.read_by || []).filter(r => r.by !== reader) } : m,
    ));
    window.uai.comms.markRead(msg.id, reader)
      .then(res => { if (res.ok) scanSessionCommsCount(sessionTrackingId); else revert(); })
      .catch(revert);
  }, [expandedId, folder, sessionTrackingId, loadThread]);

  const toggleSelect = useCallback((id: string) => {
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }, []);

  // Unread reflects the RECIPIENT's read state: in Sent that's the addressee
  // (msg.to); elsewhere it's this session. Lifted so both the Read/Unread filter
  // and the per-row indicator share one definition.
  const isMsgUnread = useCallback((msg: InboxMessage): boolean => {
    const reader = folder === 'sent' ? msg.to : sessionTrackingId;
    return !(msg.read_by && msg.read_by.some(r => r.by === reader));
  }, [folder, sessionTrackingId]);

  // Apply the Read/Unread filter client-side. 'all' shows everything.
  const visibleMessages = useMemo(() => {
    if (readFilter === 'all') return messages;
    return messages.filter(m => (readFilter === 'unread' ? isMsgUnread(m) : !isMsgUnread(m)));
  }, [messages, readFilter, isMsgUnread]);

  // Group the list by conversation (item 4). A conversation with more than one
  // distinct recipient is a multi-recipient send — surfaced in its header (item 2).
  const conversationGroups = useMemo(() => {
    const byConvo = new Map<string, InboxMessage[]>();
    for (const m of visibleMessages) {
      const key = m.conversation_id || m.id;   // no conversation → its own singleton
      const arr = byConvo.get(key);
      if (arr) arr.push(m); else byConvo.set(key, [m]);
    }
    const groups = [...byConvo.entries()].map(([key, msgs]) => {
      const sorted = [...msgs].sort((a, b) => (a.created_at || '').localeCompare(b.created_at || ''));
      const recipients = [...new Set(msgs.map(m => m.to).filter(Boolean))];
      const subject = msgs.find(m => m.subject)?.subject || '';
      const latest = sorted[sorted.length - 1]?.created_at || '';
      return { key, subject, msgs: sorted, recipients, latest };
    });
    groups.sort((a, b) => (b.latest || '').localeCompare(a.latest || ''));
    return groups;
  }, [visibleMessages]);

  const allSelected = visibleMessages.length > 0 && selected.size === visibleMessages.length;
  const toggleSelectAll = useCallback(() => {
    setSelected(allSelected ? new Set() : new Set(visibleMessages.map(m => m.id)));
  }, [allSelected, visibleMessages]);

  // ── Bulk actions (apply to all selected, or to a single right-clicked msg) ──
  const refresh = useCallback(() => {
    loadMessages();
    if (sessionTrackingId) scanSessionCommsCount(sessionTrackingId);
  }, [loadMessages, sessionTrackingId]);

  const doArchive = useCallback(async (ids: string[]) => {
    await Promise.all(ids.map(id => window.uai.comms.archive(id)));
    setSelected(new Set()); refresh();
  }, [refresh]);

  const doMarkRead = useCallback(async (ids: string[]) => {
    if (!sessionTrackingId) return;
    await Promise.all(ids.map(id => window.uai.comms.markRead(id, sessionTrackingId)));
    setSelected(new Set()); refresh();
  }, [sessionTrackingId, refresh]);

  const doMarkUnread = useCallback(async (ids: string[]) => {
    if (!sessionTrackingId) return;
    await Promise.all(ids.map(id => window.uai.comms.markUnread(sessionTrackingId, id, sessionTrackingId)));
    setSelected(new Set()); refresh();
  }, [sessionTrackingId, refresh]);

  const doDelete = useCallback(async (ids: string[]) => {
    if (!sessionTrackingId) return;
    await Promise.all(ids.map(id => window.uai.comms.deleteMessage(sessionTrackingId, id)));
    setSelected(new Set()); refresh();
  }, [sessionTrackingId, refresh]);

  const sendReply = useCallback(async (msgId: string) => {
    if (!sessionTrackingId || !replyText.trim()) return;
    const res = await window.uai.comms.reply(msgId, sessionTrackingId, replyText.trim());
    if (res.ok) {
      closeReply(msgId, true);
      refresh();
      // Keep the thread visible: reload it so the just-sent reply appears nested.
      const parent = messages.find(m => m.id === msgId);
      if (parent) loadThread(parent);
    }
  }, [sessionTrackingId, replyText, refresh, closeReply, messages, loadThread]);

  const onRowContextMenu = useCallback((e: React.MouseEvent, msg: InboxMessage) => {
    // If the right-clicked row is part of an active selection, act on ALL
    // selected; otherwise act on just this row.
    const targets = (selectMode && selected.has(msg.id) && selected.size > 0)
      ? Array.from(selected)
      : [msg.id];
    const many = targets.length > 1;
    const copyTargets = () => {
      const byId = new Map(messages.map(m => [m.id, m]));
      const text = targets.map(id => byId.get(id)?.content || '').filter(Boolean).join('\n\n---\n\n');
      window.uai.clipboard.write(text);
    };
    const items: ContextMenuItem[] = [
      { label: many ? `Copy ${targets.length}` : 'Copy', action: copyTargets },
      { label: many ? `Archive ${targets.length}` : 'Archive', action: () => doArchive(targets) },
      { label: many ? `Mark ${targets.length} Read` : 'Mark as Read', action: () => doMarkRead(targets) },
      { label: many ? `Mark ${targets.length} Unread` : 'Mark as Unread', action: () => doMarkUnread(targets) },
      { label: 'Reply', action: () => openReply(msg.id), disabled: many || folder === 'sent' },
      { label: many ? `Delete ${targets.length}` : 'Delete', action: () => doDelete(targets), danger: true },
    ];
    showContextMenu(e, items);
  }, [selectMode, selected, folder, messages, doArchive, doMarkRead, doMarkUnread, doDelete, openReply]);

  if (!sessionTrackingId) {
    return <div className="comms-empty">Select a session to view its messages.</div>;
  }

  return (
    <div className="messages-tab">
      <div className="msg-folder-bar">
        {/* Read/Unread filter — split pill (PianoMan picked this for the 2-value
            case; the cycle pill in CommsReadFilter.tsx is kept for future 3-4
            value filters). Left-aligned at the head of the folder bar. */}
        <span style={{ display: 'inline-flex', alignItems: 'center', marginRight: 8 }}>
          <ReadFilterSplitPill value={readFilter} onChange={setReadFilter} />
        </span>
        {(['inbox', 'sent', 'archive'] as MsgFolder[]).map(f => (
          <button
            key={f}
            className={`msg-folder-btn${folder === f ? ' active' : ''}`}
            onClick={() => setFolder(f)}
            style={folder === f ? {
              background: 'rgba(122,162,247,0.20)',
              color: '#fff',
              fontWeight: 700,
              borderBottom: '2px solid var(--accent-blue, #7aa2f7)',
              borderRadius: '3px 3px 0 0',
            } : undefined}
          >
            {f.charAt(0).toUpperCase() + f.slice(1)}
          </button>
        ))}
        <button
          className={`msg-select-toggle${selectMode ? ' active' : ''}`}
          onClick={() => { setSelectMode(v => !v); setSelected(new Set()); }}
        >
          {selectMode ? 'Done' : 'Select'}
        </button>
      </div>

      {loading ? (
        <div className="comms-loading">Loading messages...</div>
      ) : visibleMessages.length === 0 ? (
        <div className="comms-empty">
          {messages.length === 0
            ? `No messages in ${folder}.`
            : `No ${readFilter} messages in ${folder}.`}
        </div>
      ) : (
        <div className="msg-list">
          {selectMode && (
            <label className="msg-select-all">
              <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} />
              <span>{selected.size > 0 ? `${selected.size} selected` : 'Select all'}</span>
            </label>
          )}
          {conversationGroups.map(group => {
            // Header only when it's actually a conversation (multiple messages) or a
            // multi-recipient send — a lone message needs no group chrome.
            const multi = group.msgs.length > 1 || group.recipients.length > 1;
            return (
              <div className="msg-convo" key={group.key}>
                {multi && (
                  <div className="msg-convo-header" title={group.recipients.join(', ')}>
                    <span className="msg-convo-subject">{group.subject || '(no subject)'}</span>
                    {folder === 'sent' && group.recipients.length > 1 && (
                      <span className="msg-convo-recips">{group.recipients.length} recipients</span>
                    )}
                    {group.msgs.length > 1 && <span className="msg-convo-count">{group.msgs.length} msgs</span>}
                    <span className="msg-convo-time">{formatTime(group.latest)}</span>
                  </div>
                )}
                {group.msgs.map(msg => {
            // Only recognized SEMANTIC types get a pill; 'direct'/'broadcast' get
            // none (a "direct" pill adds nothing when nearly everything is direct).
            const typeBadge = TYPE_BADGES[msg.type];
            const urgencyColor = URGENCY_DOTS[msg.urgency] || 'var(--text-muted)';
            // Unread reflects the RECIPIENT's read state (see isMsgUnread).
            const isUnread = isMsgUnread(msg);
            const expanded = expandedId === msg.id;
            const isSelected = selected.has(msg.id);
            // Color the row by author: one fixed color for the user, a stable
            // hash color per session — so sent replies read distinctly.
            const authorColor = senderColor(msg.from);
            // In the Sent folder the useful party is the RECIPIENT — show
            // "To: <recipient>" (colored by recipient); everywhere else the
            // sender, "From: <sender>". The content itself stays authorColor.
            const isSent = folder === 'sent';
            const headParty = isSent ? (msg.to || '') : msg.from;
            const headColor = isSent ? senderColor(msg.to || '') : authorColor;
            const headLabel = isSent ? 'To' : 'From';

            return (
              <div
                key={msg.id}
                className={`msg-entry${expanded ? ' expanded' : ''}${isUnread ? ' unread' : ''}${isSelected ? ' selected' : ''}`}
                onContextMenu={(e) => onRowContextMenu(e, msg)}
              >
                <div className="msg-entry-row">
                  {selectMode && (
                    <input
                      type="checkbox"
                      className="msg-select-checkbox"
                      checked={isSelected}
                      onClick={(e) => e.stopPropagation()}
                      onChange={() => toggleSelect(msg.id)}
                    />
                  )}
                  <div className="msg-entry-main" onClick={() => openMessage(msg)} title={truncate(msg.content, 400)}>
                    <div className="msg-entry-header">
                      {isUnread && <span className="msg-urgency-dot" style={{ backgroundColor: urgencyColor }} />}
                      {typeBadge && (
                        <span className="msg-type-badge" style={{ background: `${typeBadge.color}22`, color: typeBadge.color, borderColor: `${typeBadge.color}44` }}>
                          {typeBadge.label}
                        </span>
                      )}
                      <span className="msg-sender" style={{ color: headColor }} title={headParty}>{headLabel}: {resolveDisplayName(headParty, sessions)}</span>
                      {msg.subject && <span className="msg-subject">{msg.subject}</span>}
                      {/* Read-ago, right-justified (via .msg-time margin-left:auto);
                          falls back to received/sent-ago while still unread. Hover
                          for the full Sent + Read timestamps. */}
                      {(() => {
                        // Show the SENT time in the row without needing to open the
                        // message. Read time stays in the hover tooltip.
                        const readerId = folder === 'sent' ? (msg.to || null) : sessionTrackingId;
                        return (
                          <span className="msg-time" title={receiptTooltip(msg, sessions, readerId)}>
                            {formatTime(msg.created_at)}
                          </span>
                        );
                      })()}
                    </div>

                    {expanded ? (
                      <div className="msg-expanded">
                        <div className="msg-meta-row">
                          <span className="msg-meta-id" title={msg.from}>{msg.from}</span>
                          <span className="msg-meta-arrow">{'→'}</span>
                          <span className="msg-meta-id" title={msg.to}>{msg.to || '(unknown)'}</span>
                          <span className="msg-meta-spacer" />
                          <span className="msg-meta-dt">{formatDateTime(msg.created_at)}</span>
                          <span className="msg-meta-size">{formatSize(msg.content)}</span>
                        </div>
                        <div className="msg-content" style={{ color: authorColor }}><LinkifyRefs text={msg.content} /></div>
                        {/* Visible Reply affordance (right-click also has it, but a
                            button is discoverable). Disabled in the Sent folder. */}
                        {replyingTo !== msg.id && (
                          <div className="msg-expanded-actions">
                            <button
                              className="msg-reply-btn"
                              onClick={(e) => { e.stopPropagation(); openReply(msg.id); }}
                              disabled={folder === 'sent'}
                              title={folder === 'sent' ? "Can't reply from the Sent folder" : `Reply to ${resolveDisplayName(msg.from, sessions)}`}
                            >{'↩ Reply'}</button>
                          </div>
                        )}
                        {msg.body_file && (
                          <button
                            className="msg-offload-link"
                            onClick={(e) => { e.stopPropagation(); window.uai.openPath(msg.body_file as string); }}
                            title={msg.body_file}
                          >
                            {'📎'} Offloaded content — open {msg.body_file.split('/').pop()}
                          </button>
                        )}
                        {msg.reply_to && (
                          <span className="msg-reply-indicator">reply to {msg.reply_to.slice(0, 20)}</span>
                        )}
                        {thread.filter(t => t.id !== msg.id).length > 0 && (
                          <div style={{ marginTop: 8, borderTop: '1px solid var(--border)', paddingTop: 6, display: 'flex', flexDirection: 'column', gap: 7 }}>
                            <div style={{ fontSize: 10, textTransform: 'uppercase', letterSpacing: '.06em', color: 'var(--text-muted)', fontWeight: 700 }}>
                              Thread ({thread.length})
                            </div>
                            {thread.filter(t => t.id !== msg.id).map(t => (
                              <div key={t.id} style={{ borderLeft: `2px solid ${senderColor(t.from)}`, paddingLeft: 8 }}>
                                <div style={{ display: 'flex', gap: 8, alignItems: 'baseline' }}>
                                  <span style={{ color: senderColor(t.from), fontWeight: 600, fontSize: 12 }} title={t.from}>
                                    {resolveDisplayName(t.from, sessions)}
                                  </span>
                                  <span style={{ color: 'var(--text-muted)', fontSize: 10.5 }}>{formatTime(t.created_at)}</span>
                                </div>
                                <div style={{ color: senderColor(t.from), fontSize: 12, whiteSpace: 'pre-wrap', wordBreak: 'break-word', lineHeight: 1.45 }}>
                                  {t.content}
                                </div>
                              </div>
                            ))}
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="msg-entry-preview" style={{ color: authorColor }}>{truncate(msg.content, 120)}</div>
                    )}
                  </div>
                </div>

                {replyingTo === msg.id && (
                  <div className="msg-reply-box" onClick={(e) => e.stopPropagation()}>
                    <textarea
                      className="msg-reply-textarea"
                      value={replyText}
                      autoFocus
                      placeholder={`Reply to ${resolveDisplayName(msg.from, sessions)}...`}
                      onChange={(e) => onReplyTextChange(msg.id, e.target.value)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); sendReply(msg.id); }
                        if (e.key === 'Escape') closeReply(msg.id, false);
                      }}
                    />
                    <div className="msg-reply-actions">
                      <button className="msg-reply-send" disabled={!replyText.trim()} onClick={() => sendReply(msg.id)}>Send</button>
                      <button className="msg-reply-cancel" onClick={() => closeReply(msg.id, true)}>Cancel</button>
                    </div>
                  </div>
                )}
              </div>
            );
                })}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}
