/**
 * SessionStoreHistory — Change log timeline for a session.
 *
 * Shows who changed what, when, with old and new values.
 * Supports pagination via "Load More".
 */

import { useState, useEffect, useCallback } from 'react';
import type { ChangeLogEntry } from './session-store-types';

interface SessionStoreHistoryProps {
  trackingId: string;
}

const PAGE_SIZE = 50;

function formatTimestamp(ts: string): string {
  if (!ts) return '--';
  try {
    return new Date(ts).toLocaleString();
  } catch {
    return ts;
  }
}

function truncateValue(val: string | null | undefined, maxLen = 60): string {
  if (!val) return '--';
  return val.length > maxLen ? val.slice(0, maxLen) + '...' : val;
}

export default function SessionStoreHistory({ trackingId }: SessionStoreHistoryProps): JSX.Element {
  const [entries, setEntries] = useState<ChangeLogEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState(PAGE_SIZE);
  const [hasMore, setHasMore] = useState(false);

  const loadHistory = useCallback(async (requestLimit: number) => {
    setLoading(true);
    setError(null);
    try {
      // Request one extra to detect if more exist
      const rows = await window.uai.sessionStore.history(trackingId, { limit: requestLimit + 1 });
      if (rows.length > requestLimit) {
        setEntries(rows.slice(0, requestLimit));
        setHasMore(true);
      } else {
        setEntries(rows);
        setHasMore(false);
      }
    } catch (err: any) {
      setError(err.message || 'Failed to load history');
    } finally {
      setLoading(false);
    }
  }, [trackingId]);

  useEffect(() => {
    loadHistory(limit);
  }, [loadHistory, limit]);

  const handleLoadMore = useCallback(() => {
    setLimit(prev => prev + PAGE_SIZE);
  }, []);

  if (loading && entries.length === 0) {
    return <div className="traits-mgr-loading">Loading change history...</div>;
  }

  if (error) {
    return <div className="traits-mgr-error">{error}</div>;
  }

  if (entries.length === 0) {
    return <div className="traits-mgr-empty">No change history found</div>;
  }

  return (
    <div className="sess-store-history-content">
      <div className="sess-store-history-list">
        {entries.map((entry, idx) => (
          <div key={entry.id || idx} className="sess-store-history-row">
            <div className="sess-store-history-header">
              <span className="sess-store-history-ts">{formatTimestamp(entry.changed_at)}</span>
              <span className="sess-store-history-field">{entry.field}</span>
              {entry.pid != null && (
                <span className="sess-store-history-pid">PID {entry.pid}</span>
              )}
            </div>
            <div className="sess-store-history-values">
              <span className="sess-store-history-old" title={entry.old_value || ''}>
                {truncateValue(entry.old_value)}
              </span>
              <span className="sess-store-history-arrow">{'\u2192'}</span>
              <span className="sess-store-history-new" title={entry.new_value || ''}>
                {truncateValue(entry.new_value)}
              </span>
            </div>
          </div>
        ))}
      </div>

      {hasMore && (
        <button className="sess-store-load-more" onClick={handleLoadMore} disabled={loading}>
          {loading ? 'Loading...' : 'Load More'}
        </button>
      )}
    </div>
  );
}
