/**
 * SessionStoreStateVars — Namespace-grouped KV list from per-session state JSON.
 *
 * Groups keys by namespace prefix (env.*, context.*, transcript.*, etc.).
 * Supports inline edit and delete. env.* keys are read-only.
 */

import { useState, useEffect, useCallback, useMemo, forwardRef, useImperativeHandle } from 'react';
import { useToast } from './Toast';

interface SessionStoreStateVarsProps {
  trackingId: string;
}

export interface StateVarsHandle {
  addNew: () => void;
  refresh: () => void;
}

interface StateEntry {
  key: string;
  value: unknown;
  namespace: string;
  type: string;
}

const NAMESPACE_ORDER = ['env', 'context', 'transcript', 'session', 'compact', 'loaded', 'usage', '_other'];

function detectType(value: unknown): string {
  if (typeof value === 'boolean') return 'bool';
  if (typeof value === 'number') return Number.isInteger(value) ? 'int' : 'float';
  if (Array.isArray(value)) return 'list';
  if (typeof value === 'object' && value !== null) return 'obj';
  return 'str';
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'boolean') return value ? 'true' : 'false';
  if (typeof value === 'number') return String(value);
  if (Array.isArray(value)) return value.join(', ');
  return JSON.stringify(value);
}

function parseEntries(state: Record<string, unknown>): StateEntry[] {
  const entries: StateEntry[] = [];
  for (const [key, value] of Object.entries(state)) {
    const dotIdx = key.indexOf('.');
    const namespace = dotIdx > 0 ? key.slice(0, dotIdx) : '_other';
    entries.push({ key, value, namespace, type: detectType(value) });
  }
  return entries;
}

function groupByNamespace(entries: StateEntry[]): Map<string, StateEntry[]> {
  const groups = new Map<string, StateEntry[]>();
  for (const entry of entries) {
    const ns = entry.namespace;
    if (!groups.has(ns)) groups.set(ns, []);
    groups.get(ns)!.push(entry);
  }
  // Sort groups by defined order
  const ordered = new Map<string, StateEntry[]>();
  for (const ns of NAMESPACE_ORDER) {
    if (groups.has(ns)) {
      ordered.set(ns, groups.get(ns)!);
      groups.delete(ns);
    }
  }
  // Append remaining namespaces alphabetically
  for (const [ns, entries] of [...groups.entries()].sort((a, b) => a[0].localeCompare(b[0]))) {
    ordered.set(ns, entries);
  }
  return ordered;
}

const TYPE_BADGE_COLORS: Record<string, string> = {
  str: 'var(--accent-blue)',
  int: 'var(--accent-green)',
  float: 'var(--accent-yellow)',
  bool: 'var(--accent-purple)',
  list: 'var(--accent-cyan)',
  obj: 'var(--accent-orange)',
};

const SessionStoreStateVars = forwardRef<StateVarsHandle, SessionStoreStateVarsProps>(function SessionStoreStateVars({ trackingId }: SessionStoreStateVarsProps, ref): JSX.Element {
  const [state, setState] = useState<Record<string, unknown>>({});
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [editingKey, setEditingKey] = useState<string | null>(null);
  const [editDraft, setEditDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set());
  const [addingNew, setAddingNew] = useState(false);
  const [newKey, setNewKey] = useState('');
  const [newValue, setNewValue] = useState('');
  const { showToast } = useToast();

  const loadState = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await window.uai.sessionStore.stateList(trackingId);
      setState(data || {});
    } catch (err: any) {
      setError(err.message || 'Failed to load state');
    } finally {
      setLoading(false);
    }
  }, [trackingId]);

  useEffect(() => {
    loadState();
  }, [loadState]);

  useImperativeHandle(ref, () => ({ addNew: () => setAddingNew(true), refresh: loadState }), [loadState]);

  const entries = useMemo(() => parseEntries(state), [state]);
  const groups = useMemo(() => groupByNamespace(entries), [entries]);

  const toggleCollapse = useCallback((ns: string) => {
    setCollapsed(prev => {
      const next = new Set(prev);
      if (next.has(ns)) next.delete(ns); else next.add(ns);
      return next;
    });
  }, []);

  const startEdit = useCallback((key: string, currentValue: unknown) => {
    setEditingKey(key);
    setEditDraft(formatValue(currentValue));
  }, []);

  const handleSave = useCallback(async () => {
    if (!editingKey) return;
    setSaving(true);
    const result = await window.uai.sessionStore.stateSet(trackingId, editingKey, editDraft);
    if (result.ok) {
      showToast('Saved', 'info');
      setEditingKey(null);
      loadState();
    } else {
      showToast(result.error || 'Save failed', 'error');
    }
    setSaving(false);
  }, [trackingId, editingKey, editDraft, loadState, showToast]);

  const handleDelete = useCallback(async (key: string) => {
    const result = await window.uai.sessionStore.stateDelete(trackingId, key);
    if (result.ok) {
      showToast('Deleted', 'info');
      loadState();
    } else {
      showToast(result.error || 'Delete failed', 'error');
    }
  }, [trackingId, loadState, showToast]);

  const handleAddNew = useCallback(async () => {
    if (!newKey.trim()) return;
    setSaving(true);
    const result = await window.uai.sessionStore.stateSet(trackingId, newKey.trim(), newValue);
    if (result.ok) {
      showToast('Added', 'info');
      setAddingNew(false);
      setNewKey('');
      setNewValue('');
      loadState();
    } else {
      showToast(result.error || 'Add failed', 'error');
    }
    setSaving(false);
  }, [trackingId, newKey, newValue, loadState, showToast]);

  const handleEditKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleSave();
    if (e.key === 'Escape') setEditingKey(null);
  }, [handleSave]);

  const handleNewKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Enter') handleAddNew();
    if (e.key === 'Escape') { setAddingNew(false); setNewKey(''); setNewValue(''); }
  }, [handleAddNew]);

  if (loading) return <div className="traits-mgr-loading">Loading state variables...</div>;
  if (error) return <div className="traits-mgr-error">{error}</div>;

  return (
    <div className="sess-store-state-content">
      {/* New key form */}
      {addingNew && (
        <div className="sess-store-new-key-form">
          <input
            className="sess-store-field-input"
            type="text"
            placeholder="key.name"
            value={newKey}
            onChange={(e) => setNewKey(e.target.value)}
            onKeyDown={handleNewKeyDown}
            autoFocus
          />
          <input
            className="sess-store-field-input"
            type="text"
            placeholder="value"
            value={newValue}
            onChange={(e) => setNewValue(e.target.value)}
            onKeyDown={handleNewKeyDown}
          />
          <button className="traits-mgr-tab-btn active" onClick={handleAddNew} disabled={saving}>Add</button>
          <button className="traits-mgr-tab-btn" onClick={() => { setAddingNew(false); setNewKey(''); setNewValue(''); }}>Cancel</button>
        </div>
      )}

      {/* Namespace groups */}
      {entries.length === 0 && <div className="traits-mgr-empty">No state variables found</div>}
      {[...groups.entries()].map(([ns, nsEntries]) => {
        const isEnv = ns === 'env';
        const isCollapsed = collapsed.has(ns);
        return (
          <div key={ns} className="traits-mgr-category">
            <div className="traits-mgr-category-header" onClick={() => toggleCollapse(ns)}>
              <span className="traits-mgr-collapse-icon sess-store-ns-chevron">{isCollapsed ? '\u25B6' : '\u25BC'}</span>
              <span className="traits-mgr-category-name">{ns}</span>
              <span className="traits-mgr-category-count sess-store-ns-count">{nsEntries.length}</span>
              {isEnv && <span className="sess-store-readonly-note">read-only</span>}
            </div>
            {!isCollapsed && (
              <div className="traits-mgr-category-items">
                {isEnv && (
                  <div className="sess-store-env-note">
                    Environment variables are set by the launcher at session start and cannot be modified.
                  </div>
                )}
                {nsEntries.map(entry => (
                  <div key={entry.key} className="sess-store-state-row">
                    <span className="sess-store-state-key">{entry.key}</span>
                    <span className="sess-store-type-badge" style={{ color: TYPE_BADGE_COLORS[entry.type] || 'var(--text-muted)' }}>{entry.type}</span>
                    {editingKey === entry.key ? (
                      <div className="sess-store-field-edit sess-store-state-edit">
                        <input
                          className="sess-store-field-input"
                          type="text"
                          value={editDraft}
                          onChange={(e) => setEditDraft(e.target.value)}
                          onKeyDown={handleEditKeyDown}
                          disabled={saving}
                          autoFocus
                        />
                      </div>
                    ) : (
                      <span className="sess-store-state-value" title={formatValue(entry.value)}>
                        {formatValue(entry.value)}
                      </span>
                    )}
                    {!isEnv && editingKey !== entry.key && (
                      <div className="sess-store-state-btns">
                        <button className="sess-store-icon-btn" onClick={() => startEdit(entry.key, entry.value)} title="Edit">&#9998;</button>
                        <button className="sess-store-icon-btn sess-store-icon-delete" onClick={() => handleDelete(entry.key)} title="Delete">&times;</button>
                      </div>
                    )}
                  </div>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
});

export default SessionStoreStateVars;
