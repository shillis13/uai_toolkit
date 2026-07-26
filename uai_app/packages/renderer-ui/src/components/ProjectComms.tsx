/**
 * ProjectComms — the Comms aspect, on the real Conversation model.
 *
 * Conversations come from the SQLite-backed read CLI via
 * window.uai.comms.conversations / .conversation (see CONVERSATIONS_MESSAGING_DESIGN.md).
 * The shell Navigator lists conversations (filtered to the project/team's members);
 * selecting one renders its message thread (author-colored, sub-threaded by
 * effective_subject, read-state from deliveries) + an inject box.
 *
 * Note: posting (the inject box) routes through the send-path that ThroughLine is
 * updating (reply_to → conversation). Until that lands, the box is present but
 * disabled with a note — read side is live now.
 */

import { useEffect, useRef, useState } from 'react';
import type { SessionCard } from '@uai/shared/cards';
import { trackingIdFrom } from './SessionLink';
import { executeCommand } from '../utils/execute-command';

// Open a session in a workspace tab if the endpoint resolves to one (todo_0406).
function openSessionIf(ep: string) { const tid = trackingIdFrom(ep); if (tid) executeCommand('workspace.tabs.open', { type: 'session', targetId: tid }); }

// ── shared helpers (kept — imported by ProjectTeam / ProjectOverview) ────────
const PALETTE = ['var(--accent-cyan,#56c7d6)', 'var(--accent-green,#5cd693)', 'var(--accent-yellow,#e0af68)',
  'var(--accent-purple,#bb9af7)', 'var(--accent-blue,#7aa2f7)', 'var(--accent-orange,#e8915c)', 'var(--accent-red,#f7768e)'];
export function nameColor(name: string): string {
  let h = 0;
  for (let i = 0; i < (name || '').length; i++) h = (h * 31 + name.charCodeAt(i)) >>> 0;
  return PALETTE[h % PALETTE.length];
}
export function formatTime(iso: string): string {
  if (!iso) return '';
  try {
    const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const h = Math.floor(mins / 60);
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch { return ''; }
}
function senderName(ep: string): string {
  if (!ep) return '?';
  const paren = ep.match(/^([^(]+)\s*\(/);
  if (paren) return paren[1].trim();
  if (ep.includes('_') && ep.split('_').length >= 4) return ep.split('_').slice(2, 4).join('_');
  return ep.slice(0, 20);
}

export interface Conversation {
  id: string; topic: string; status: string; needs_input: boolean;
  participants: string[]; last_activity: string; created_at: string;
  linked_work: unknown; message_count: number; last_message_preview: string;
}

const STATUS_COLOR: Record<string, string> = {
  needs_input: 'var(--accent-orange, #e8915c)', open: 'var(--accent-green, #5cd693)',
  blocked: 'var(--accent-red, #f7768e)', resolved: 'var(--text-muted, #7d8696)', archived: 'var(--text-muted, #7d8696)',
};

/** Conversations for the project/team's members (repeatable --participant OR). Gated to the Comms aspect. */
export function useProjectConversations(participantIds: string[], enabled: boolean): { conversations: Conversation[]; loading: boolean } {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(false);
  const key = participantIds.join(',');
  useEffect(() => {
    if (!enabled) return;
    let alive = true; setLoading(true);
    window.uai.comms.conversations({ participants: participantIds, order: 'last_activity', limit: 100 })
      .then(r => { if (alive) { setConversations((r || []) as Conversation[]); setLoading(false); } })
      .catch(() => { if (alive) { setConversations([]); setLoading(false); } });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, key]);
  return { conversations, loading };
}

interface ProjectCommsDetailProps {
  conversations: Conversation[];
  loading: boolean;
  selectedId: string | null;
  teamSize: number;
}

// PianoMan's comms identity — he's a participant in these conversations, so
// replies posted from the app go out under his name.
const PIANOMAN_SENDER = 'piano_man';

export default function ProjectCommsDetail({ conversations, loading, selectedId, teamSize }: ProjectCommsDetailProps): JSX.Element {
  const conv = conversations.find(c => c.id === selectedId) || null;
  const [detail, setDetail] = useState<{ messages?: Array<Record<string, any>>; deliveries?: Array<Record<string, any>> } | null>(null);
  const [draft, setDraft] = useState('');
  const [sending, setSending] = useState(false);
  const [sendErr, setSendErr] = useState<string | null>(null);
  const selectedIdRef = useRef(selectedId);
  selectedIdRef.current = selectedId;

  useEffect(() => {
    if (!selectedId) { setDetail(null); return; }
    let alive = true;
    window.uai.comms.conversation(selectedId)
      .then(d => { if (alive) setDetail(d as any); })
      .catch(() => { if (alive) setDetail(null); });
    setDraft(''); setSendErr(null);
    return () => { alive = false; };
  }, [selectedId]);

  // Reply into the conversation as PianoMan — threads onto the latest message so it
  // lands in this conversation. Reloads the thread on success.
  const send = async () => {
    const text = draft.trim();
    const msgs = detail?.messages || [];
    // Optimistic replies use local-only IDs until the read index catches up.
    // Never use one as the next reply anchor or a rapid second reply would target
    // a message ID the backend cannot resolve.
    const last = [...msgs].reverse().find(m => !m?._optimistic && m?.id);
    if (!text || !last?.id || sending) return;
    setSending(true); setSendErr(null);
    try {
      const res = await window.uai.comms.reply(String(last.id), PIANOMAN_SENDER, text);
      if (res?.ok) {
        setDraft('');
        // Show the reply instantly (optimistic stub), then reconcile against the
        // read index. messaging_mgr now writes the reply to comms_index before
        // returning (todo_0593), so a reload DOES reflect it — the reload replaces
        // the stub with the real message (real id, reply_to, read-state) and lets
        // a rapid follow-up reply anchor on it instead of skipping the stub.
        setDetail(d => ({
          ...(d || {}),
          messages: [...((d?.messages) || []), {
            id: `local_${String(last.id)}_${((d?.messages) || []).length}`,
            from: PIANOMAN_SENDER, body: text, created_at: new Date().toISOString(), delivery: 'message', _optimistic: true,
          }],
        }));
        if (selectedId) {
          try {
            // Keep `sending` true until the real indexed row is back. This closes
            // the small window where a rapid second submit could still anchor on
            // the previous real message while the optimistic stub was unresolved.
            const refreshed = await window.uai.comms.conversation(selectedId);
            if (selectedIdRef.current === selectedId) setDetail(refreshed as any);
          } catch {
            // Keep the optimistic stub if the reload fails. The next send skips
            // local-only IDs and therefore still targets a resolvable message.
          }
        }
      } else {
        setSendErr(res?.error || 'Send failed.');
      }
    } catch (e) {
      setSendErr(e instanceof Error ? e.message : String(e));
    } finally {
      setSending(false);
    }
  };

  if (loading) return <div className="pe-detail-body"><div className="pe-note">Loading conversations…</div></div>;

  // read-state per message id, from deliveries
  const readByMsg = new Map<string, boolean>();
  (detail?.deliveries || []).forEach(d => { if (d.read_at) readByMsg.set(d.message_id, true); });

  return (
    <div className="pe-detail-body pe-comms">
      {conversations.length === 0 && (
        <div className="pe-note">
          No conversations among this project's {teamSize} member{teamSize === 1 ? '' : 's'} yet.
          {' '}(Read index is live; populates once comms backfill runs.)
        </div>
      )}
      {conversations.length > 0 && !conv && (
        <div className="pe-note">Select a conversation from the Navigator. ({conversations.length})</div>
      )}
      {conv && (
        <>
          <div className="pe-section-label">
            {conv.topic || '(untitled)'}
            {conv.needs_input && <span className="pe-badge" style={{ color: 'var(--accent-orange)', marginLeft: 8 }}>needs input</span>}
            {/* lifecycle status only when it's something other than the default 'open' (#8.2) */}
            {conv.status && conv.status !== 'open' && !conv.needs_input && (
              <span className="pe-badge" style={{ color: STATUS_COLOR[conv.status] || 'var(--text-muted)', marginLeft: 8 }}>{conv.status}</span>
            )}
          </div>
          {/* participants — who's in this conversation (#8.1) */}
          <div className="pe-participants">
            {conv.participants.map(p => {
              const who = senderName(p);
              const isSession = !!trackingIdFrom(p);
              return <span key={p} className={`pe-pchip${isSession ? ' pe-pchip-link' : ''}`} style={{ borderColor: nameColor(who), color: nameColor(who) }} title={isSession ? `Open session ${p}` : p} onClick={isSession ? () => openSessionIf(p) : undefined}>{who}</span>;
            })}
          </div>
          <div className="pe-msg-thread">
            {(detail?.messages || []).map(m => {
              const who = senderName(m.from);
              // prompts and messages are already interwoven by created_at in the read;
              // distinguish prompts by their `delivery` field + a distinct color (#8.3).
              const isPrompt = m.delivery === 'prompt';
              return (
                <div key={m.id} className={`pe-msg${isPrompt ? ' pe-msg-prompt' : ''}`}>
                  <div className="pe-msg-head">
                    <span className={`pe-msg-who${trackingIdFrom(m.from) ? ' pe-pchip-link' : ''}`} style={{ color: nameColor(who) }} title={trackingIdFrom(m.from) ? `Open session ${m.from}` : undefined} onClick={trackingIdFrom(m.from) ? () => openSessionIf(m.from) : undefined}>{who}</span>
                    {isPrompt && <span className="pe-msg-kind">prompt</span>}
                    {/* per-message subject hidden for now — premature until derivation is solid (#8.5) */}
                    <span className="pe-msg-time">{formatTime(m.created_at)}</span>
                    {m.reply_to && <span className="pe-msg-reply" title={`reply to ${m.reply_to}`}>↩</span>}
                    {readByMsg.get(m.id) && <span className="pe-msg-read" title="read">✓</span>}
                  </div>
                  <div className="pe-msg-body">{m.body}</div>
                </div>
              );
            })}
            {detail && (detail.messages || []).length === 0 && <div className="pe-note">No messages.</div>}
          </div>
          <div className="pe-inject">
            <span className="pe-inject-to" title="Replies post as PianoMan">reply</span>
            <input
              className="pe-inject-field"
              placeholder={(detail?.messages || []).length === 0 ? 'No message to reply to yet' : 'Reply as PianoMan… (Enter to send)'}
              value={draft}
              disabled={sending || (detail?.messages || []).length === 0}
              onChange={e => setDraft(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); } }}
            />
            <button className="pe-inject-send" disabled={sending || !draft.trim() || (detail?.messages || []).length === 0} onClick={send}>
              {sending ? 'Sending…' : 'Send'}
            </button>
          </div>
          {sendErr && <div className="pe-note" style={{ color: 'var(--accent-orange)' }}>⚠ {sendErr}</div>}
        </>
      )}
    </div>
  );
}
