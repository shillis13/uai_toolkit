/**
 * SessionStoreValidate — Validation view with Orphans and Stale Running cards.
 *
 * Each card has a Check button that runs the backend validation.
 * Results show individual sessions with Fix/Delete actions.
 */

import { useState, useCallback } from 'react';
import type { SessionStoreRecord, ValidationResult } from './session-store-types';
import { useToast } from './Toast';

export default function SessionStoreValidate(): JSX.Element {
  const [orphans, setOrphans] = useState<SessionStoreRecord[]>([]);
  const [orphansChecked, setOrphansChecked] = useState(false);
  const [orphansLoading, setOrphansLoading] = useState(false);

  const [staleResult, setStaleResult] = useState<ValidationResult | null>(null);
  const [staleChecked, setStaleChecked] = useState(false);
  const [staleLoading, setStaleLoading] = useState(false);

  const { showToast } = useToast();

  const checkOrphans = useCallback(async () => {
    setOrphansLoading(true);
    try {
      const result = await window.uai.sessionStore.findOrphans();
      setOrphans(Array.isArray(result) ? result : []);
      setOrphansChecked(true);
    } catch (err: any) {
      showToast(err.message || 'Orphan check failed', 'error');
    } finally {
      setOrphansLoading(false);
    }
  }, [showToast]);

  const checkStale = useCallback(async () => {
    setStaleLoading(true);
    try {
      const result = await window.uai.sessionStore.validateRunning();
      setStaleResult(result);
      setStaleChecked(true);
    } catch (err: any) {
      showToast(err.message || 'Validation failed', 'error');
    } finally {
      setStaleLoading(false);
    }
  }, [showToast]);

  const fixStale = useCallback(async () => {
    setStaleLoading(true);
    try {
      const result = await window.uai.sessionStore.validateRunning(true);
      setStaleResult(result);
      showToast('Stale sessions fixed', 'info');
    } catch (err: any) {
      showToast(err.message || 'Fix failed', 'error');
    } finally {
      setStaleLoading(false);
    }
  }, [showToast]);

  const deleteOrphan = useCallback(async (trackingId: string) => {
    if (!window.confirm(`Delete orphaned session ${trackingId}? This cannot be undone.`)) return;
    const result = await window.uai.sessionStore.delete(trackingId);
    if (result.ok) {
      setOrphans(prev => prev.filter(o => o.tracking_id !== trackingId));
      showToast('Orphan deleted', 'info');
    } else {
      showToast(result.error || 'Delete failed', 'error');
    }
  }, [showToast]);

  const staleList = staleResult?.stale || [];

  return (
    <div className="sess-store-validate-content">
      <div className="sess-store-validate-cards">
        {/* Orphaned Sessions */}
        <div className="sess-store-validate-card">
          <div className="sess-store-validate-card-header">
            <h3 className="sess-store-validate-card-title">Orphaned Sessions</h3>
            <button
              className="traits-mgr-tab-btn active"
              onClick={checkOrphans}
              disabled={orphansLoading}
            >
              {orphansLoading ? 'Checking...' : 'Check'}
            </button>
          </div>
          <p className="sess-store-validate-card-desc">
            Sessions in the store that have no corresponding process or terminal session.
          </p>
          {orphansChecked && (
            <div className="sess-store-validate-results">
              {orphans.length === 0 ? (
                <div className="sess-store-validate-ok">No orphaned sessions found.</div>
              ) : (
                <div className="sess-store-validate-list">
                  {orphans.map(o => (
                    <div key={o.tracking_id} className="sess-store-validate-result-row">
                      <div className="sess-store-validate-result-info">
                        <span className="sess-store-validate-result-name">{o.display_name || o.tracking_id.slice(0, 24)}</span>
                        <span className="sess-store-validate-result-id">{o.tracking_id.slice(0, 28)}</span>
                      </div>
                      <button
                        className="sess-store-action-btn sess-store-delete-btn"
                        onClick={() => deleteOrphan(o.tracking_id)}
                      >
                        Delete
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        {/* Stale Running Sessions */}
        <div className="sess-store-validate-card">
          <div className="sess-store-validate-card-header">
            <h3 className="sess-store-validate-card-title">Stale Running Sessions</h3>
            <div className="sess-store-validate-card-btns">
              <button
                className="traits-mgr-tab-btn active"
                onClick={checkStale}
                disabled={staleLoading}
              >
                {staleLoading ? 'Checking...' : 'Check'}
              </button>
              {staleChecked && staleList.length > 0 && (
                <button
                  className="traits-mgr-tab-btn"
                  onClick={fixStale}
                  disabled={staleLoading}
                >
                  Fix All
                </button>
              )}
            </div>
          </div>
          <p className="sess-store-validate-card-desc">
            Sessions marked as "running" in the store but whose process is no longer alive.
          </p>
          {staleChecked && (
            <div className="sess-store-validate-results">
              {staleList.length === 0 ? (
                <div className="sess-store-validate-ok">All running sessions are alive.</div>
              ) : (
                <div className="sess-store-validate-list">
                  {staleList.map(s => (
                    <div key={s.tracking_id} className="sess-store-validate-result-row">
                      <div className="sess-store-validate-result-info">
                        <span className="sess-store-validate-result-name">{s.display_name || s.tracking_id.slice(0, 24)}</span>
                        <span className="sess-store-validate-result-id">{s.tracking_id.slice(0, 28)}</span>
                        {s.last_activity && (
                          <span className="sess-store-validate-result-detail">Last active: {new Date(s.last_activity).toLocaleString()}</span>
                        )}
                      </div>
                    </div>
                  ))}
                </div>
              )}
              {staleResult?.fixed && staleResult.fixed.length > 0 && (
                <div className="sess-store-validate-fixed">
                  {staleResult.fixed.length} session(s) fixed.
                </div>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
