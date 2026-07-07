/**
 * SessionLink — renders a session reference (tracking id or uai://session/<id>) as a
 * clickable link that opens the session in a workspace tab. Reusable anywhere a session
 * is referenced (todo provenance/history/assignee, comms, rosters, …).
 */

import { useSessionStore } from '../stores';
import { executeCommand } from '../utils/execute-command';

const TRACKING_RE = /^\d{8}_\d{6}_[0-9a-f]{8}_[a-z]{2,4}$/;

/** True if the string is a bare session tracking id. */
export function isTrackingId(s: string): boolean {
  return TRACKING_RE.test((s || '').trim());
}

/** Pull a tracking id out of a raw value or a uai://session/<id> URI, else null. */
export function trackingIdFrom(value: string): string | null {
  const v = (value || '').trim();
  if (isTrackingId(v)) return v;
  const m = v.match(/uai:\/\/session\/([^/\s]+)/i);
  if (m && isTrackingId(m[1])) return m[1];
  return null;
}

export default function SessionLink({ id, label }: { id: string; label?: string }): JSX.Element {
  const { getSession } = useSessionStore();
  const session = getSession(id);
  const text = label || session?.display_name || id;
  const open = (e: React.MouseEvent) => {
    e.stopPropagation();
    executeCommand('workspace.tabs.open', { type: 'session', targetId: id });
  };
  return (
    <a className="session-link" onClick={open} title={`Open session ${session?.display_name ? session.display_name + ' · ' : ''}${id}`}>
      {text}
    </a>
  );
}

/** Render arbitrary text, turning any embedded session tracking id into a SessionLink. */
export function LinkifySessions({ text }: { text: string }): JSX.Element {
  const parts = (text || '').split(/(\d{8}_\d{6}_[0-9a-f]{8}_[a-z]{2,4})/g);
  return <>{parts.map((p, i) => isTrackingId(p) ? <SessionLink key={i} id={p} /> : <span key={i}>{p}</span>)}</>;
}
