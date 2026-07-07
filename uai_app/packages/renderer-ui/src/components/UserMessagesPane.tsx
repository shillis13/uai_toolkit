/**
 * UserMessagesPane — PianoMan's Messages page (todo_0365).
 *
 * A direct session→user messaging channel, distinct from Notes (capture) and
 * from ephemeral notifications / in-session responses. It reuses the existing
 * inter-session MessagesTab wholesale by keying it to the USER's inbox: the user
 * is a first-class comms recipient (uai://user/<id> → inbox/<id>/), so
 * MessagesTab with sessionTrackingId=<user id> shows the user's inbox / sent /
 * archive with reply + archive, using the same comms plumbing sessions use.
 *
 * Opened as an `app`-type workspace tab (targetId: 'user-messages') from the
 * Navigator, routed through TabContentPane.
 */

import { useState, useEffect } from 'react';
import type { InboxMessage } from '@uai/shared/types';
import MessagesTab from './MessagesTab';
import { TabNavArrows } from './TabNavArrows';
import { useViewport } from '../viewport';

// The primary user's inbox id (see users_mgr / uai://user/<id>). Single-user for
// now; TODO: resolve the primary user dynamically (users_mgr) for multi-user.
const PRIMARY_USER_ID = 'piano_man';

export default function UserMessagesPane(): JSX.Element {
  // Snapshot of the user's inbox for the viewport reporter. The active folder
  // (inbox/sent/archive), selected/expanded row, and select-mode all live in
  // MessagesTab's local state and aren't reachable from this thin wrapper
  // without lifting them out (MessagesTab is shared by every session's tab, so
  // it can't carry the 'user_messages' id). The reporter therefore surfaces the
  // canonical inbox — the user's primary message channel — and its unread count.
  const [inbox, setInbox] = useState<InboxMessage[]>([]);
  const [unread, setUnread] = useState(0);

  useEffect(() => {
    let cancelled = false;
    const load = async (): Promise<void> => {
      try {
        const [msgs, count] = await Promise.all([
          window.uai.comms.inboxList(PRIMARY_USER_ID),
          window.uai.comms.inboxCount(PRIMARY_USER_ID),
        ]);
        if (cancelled) return;
        setInbox(msgs as InboxMessage[]);
        setUnread((count as { unread?: number }).unread ?? 0);
      } catch { /* comms unavailable — reporter stays empty */ }
    };
    void load();
    const timer = setInterval(() => void load(), 15000);
    return () => { cancelled = true; clearInterval(timer); };
  }, []);

  // Viewport reporter — exposes the user's inbox (state + summarized messages as
  // inline children) to describeViewport() / agents / the e2e harness so the
  // Messages pane shows content in "Capture Content" instead of an empty node.
  useViewport('user_messages', () => ({
    visible: true,
    label: 'Messages',
    state: {
      user: PRIMARY_USER_ID,
      folder: 'inbox',
      total: inbox.length,
      unread,
    },
    children: inbox.slice(0, 20).map((m) => ({
      id: `user_message:${m.id}`,
      label: `${m.from}${m.subject ? ` — ${m.subject}` : ''}`,
      visible: true,
      state: {
        from: m.from,
        subject: m.subject ?? null,
        unread: !(m.read_by && m.read_by.some((r) => r.by === PRIMARY_USER_ID)),
        created_at: m.created_at,
      },
      children: [],
    })),
  }));

  return (
    <div style={{ height: '100%', display: 'flex', flexDirection: 'column', background: 'var(--bg-deep)', color: 'var(--text)' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid var(--border)', flex: '0 0 auto' }}>
        <TabNavArrows />
        <div style={{ fontWeight: 700, color: '#fff', fontSize: 14 }}>Messages</div>
        <div style={{ color: 'var(--text-muted)', fontSize: 11 }}>
          direct messages from sessions to you — <span style={{ color: 'var(--text-muted)' }}>uai://user/{PRIMARY_USER_ID}</span>
        </div>
      </div>
      <div style={{ flex: '1 1 auto', minHeight: 0, overflow: 'auto' }}>
        <MessagesTab sessionTrackingId={PRIMARY_USER_ID} />
      </div>
    </div>
  );
}
