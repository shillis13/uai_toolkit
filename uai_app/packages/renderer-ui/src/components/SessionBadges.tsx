/**
 * SessionBadges — the single, shared badge renderer for a session.
 *
 * Per design: badges are defined here and rendered on Session Cards first;
 * RecentSessions (and anywhere else) reuse this exact component so there is one
 * source of truth for what badges a session shows.
 *
 * Two groups:
 *   LEFT  (before the name) — state of the session's input surfaces. Rendered in
 *         FIXED, reserved slots so each badge always sits in the same column
 *         whether or not it's lit:
 *           ⊤  a workspace tab is open
 *           ✎  PromptBox has unsent draft text
 *           ▎  the CLI prompt area has unsent text
 *   RIGHT (after the name, right-justified) — unread counts. No reserved space;
 *         shown only when non-zero, always in this order:
 *           ↩N number of unread response messages (new CLI replies since viewed)
 *           ✉N number of unread communications (comms inbox)
 *
 * Reads live state from the activity / prompt-area / comms-count stores and
 * self-subscribes so it stays current wherever it's dropped.
 */

import { useEffect, useState } from 'react';
import { getUnreadReplyCount, onActivityChange } from '../stores/session-activity';
import { getPromptAreaState, onPromptAreaChange } from '../stores/prompt-area-state';
import { getCommsCount, onCommsCountChange } from '../stores/comms-count-state';
import { hasPromptBoxDraft } from './PromptBox';

/** Legend metadata — drives both the rendered badges and the legend row. */
export const SESSION_BADGE_LEGEND = [
  { key: 'tab',     glyph: '⊤', label: 'Tab',            cls: 'nav-badge-tab',             side: 'left',  title: 'A workspace tab is open for this session' },
  { key: 'draft',   glyph: '✎', label: 'Draft',          cls: 'nav-badge-draft',           side: 'left',  title: 'PromptBox has unsent draft text' },
  { key: 'prompt',  glyph: '▎', label: 'Prompt text',    cls: 'nav-badge-prompt',          side: 'left',  title: 'The CLI prompt area has unsent text' },
  { key: 'replies', glyph: '↩', label: 'Unread replies', cls: 'nav-badge-unread',          side: 'right', title: 'Number of unread response messages (new CLI replies since you last viewed)' },
  { key: 'comms',   glyph: '✉', label: 'Unread comms',   cls: 'nav-badge-comms has-unread', side: 'right', title: 'Number of unread communications in the comms inbox' },
] as const;

interface SessionBadgesProps {
  trackingId: string;
  /** Backend last_activity ISO — fallback signal for the unread heuristic. */
  lastActivity?: string;
  /** Current exchange count — used to compute the unread-reply count. */
  exchangeCount?: number;
  /** Whether a workspace tab is open for this session. */
  hasTab?: boolean;
  /** Which group to render. 'left'/'right' for the split RecentSessions layout;
   *  'all' (default) renders both inline for callers like cards. */
  group?: 'left' | 'right' | 'all';
}

export function SessionBadges({ trackingId, lastActivity, exchangeCount, hasTab, group = 'all' }: SessionBadgesProps): JSX.Element {
  // Self-subscribe so badges stay live wherever this component is dropped
  // (cards, RecentSessions, …) without the parent wiring its own listeners.
  const [, forceUpdate] = useState(0);
  useEffect(() => {
    const bump = () => forceUpdate(n => n + 1);
    const unsubs = [onActivityChange(bump), onPromptAreaChange(bump), onCommsCountChange(bump)];
    return () => { for (const u of unsubs) u(); };
  }, []);

  const unreadReplies = getUnreadReplyCount(trackingId, exchangeCount, lastActivity);
  const comms = getCommsCount(trackingId);
  const hasDraft = hasPromptBoxDraft(trackingId);
  const hasPromptText = getPromptAreaState(trackingId);

  // LEFT group. reserved=true → every slot always rendered (fixed columns);
  // reserved=false → only lit badges (inline, for cards).
  const renderLeft = (reserved: boolean): JSX.Element => {
    if (reserved) {
      return (
        <>
          <span className="nav-badge-slot nav-badge-tab" title="Tab open">{hasTab ? '⊤' : ''}</span>
          <span className="nav-badge-slot nav-badge-draft" title="PromptBox has unsent draft text">{hasDraft ? '✎' : ''}</span>
          <span className="nav-badge-slot nav-badge-prompt" title="CLI prompt area has unsent text">{hasPromptText ? '▎' : ''}</span>
        </>
      );
    }
    return (
      <>
        {hasTab && <span className="nav-badge nav-badge-tab" title="Tab open">{'⊤'}</span>}
        {hasDraft && <span className="nav-badge nav-badge-draft" title="PromptBox has unsent draft text">{'✎'}</span>}
        {hasPromptText && <span className="nav-badge nav-badge-prompt" title="CLI prompt area has unsent text">{'▎'}</span>}
      </>
    );
  };

  // RIGHT group — unread counts, fixed order, only when non-zero, no reservation.
  const renderRight = (): JSX.Element => (
    <>
      {unreadReplies > 0 && (
        <span
          className="nav-badge nav-badge-unread nav-badge-count"
          title={`${unreadReplies} unread response message${unreadReplies === 1 ? '' : 's'}`}
        >{'↩'}{unreadReplies}</span>
      )}
      {comms != null && comms.unread > 0 && (
        <span
          className="nav-badge nav-badge-comms nav-badge-count has-unread"
          title={`${comms.unread} unread communication${comms.unread === 1 ? '' : 's'}`}
        >{'✉'}{comms.unread}</span>
      )}
    </>
  );

  if (group === 'left') return renderLeft(true);
  if (group === 'right') return renderRight();
  return <>{renderLeft(false)}{renderRight()}</>;
}

export default SessionBadges;
