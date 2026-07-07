/**
 * SessionStartsValue — renders a session's start history: the most recent start,
 * with a toggle to reveal all prior starts in descending (newest-first) order.
 *
 * `starts` is the Session.start_history array (local-time ISO strings, appended
 * most-recent-LAST by the SessionStart hook). Shared by the Session Details panel
 * (ContextPanel) and the Session Store's Store Fields tab so both render identically.
 */
import { useState } from 'react';

function fmt(iso: string): string {
  const d = new Date(iso);
  return isNaN(d.getTime()) ? iso : d.toLocaleString();
}

export function SessionStartsValue({ starts }: { starts?: string[] | null }): JSX.Element {
  const [expanded, setExpanded] = useState(false);
  const list = Array.isArray(starts) ? starts : [];

  if (list.length === 0) {
    return <span className="ctx-detail-value">{'—'}</span>;
  }

  // Most recent is the last element; show it, then all newest-first on expand.
  const mostRecent = list[list.length - 1];
  const descending = [...list].reverse();
  const hasMore = list.length > 1;

  return (
    <span className="ctx-detail-value session-starts-value">
      <span
        className={hasMore ? 'session-starts-toggle' : undefined}
        onClick={hasMore ? () => setExpanded(v => !v) : undefined}
        title={hasMore ? (expanded ? 'Hide earlier starts' : 'Show all starts') : undefined}
        style={hasMore ? { cursor: 'pointer' } : undefined}
      >
        {fmt(mostRecent)}
        {hasMore && (
          <span className="session-starts-count">
            {' '}{expanded ? '▾' : '▸'} {list.length} starts
          </span>
        )}
      </span>
      {expanded && hasMore && (
        <ol className="session-starts-list">
          {descending.map((ts, i) => (
            <li key={`${ts}-${i}`} className="session-starts-item">
              {fmt(ts)}
            </li>
          ))}
        </ol>
      )}
    </span>
  );
}
