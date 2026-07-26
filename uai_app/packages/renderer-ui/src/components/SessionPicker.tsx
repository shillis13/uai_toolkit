/**
 * SessionPicker — the reusable session lister/picker (todo_0600 section 1.1).
 *
 * Default UI over useSessionFilter: a sortable TABLE whose columns are the sort
 * fields (click a header to sort ▲▼), a Search box, and the filters (product /
 * state / last-activity / folder / tags) tucked behind a "Filters" toggle that
 * drops them into a row below — collapsed by default to keep the header calm.
 * Tags use a dropdown checklist, never pills (components/DESIGN.md Pills section).
 * Selection is controlled by the caller so it embeds in the Resume/Fork dialog,
 * the Custom launcher, and session listers like a Folder view.
 */

import { useMemo, useState } from 'react';
import { useSessionStore } from '../stores/session-store';
import { useFolderStore } from '../stores/folder-store';
import MultiSelectMenu from './MultiSelectMenu';
import {
  useSessionFilter, sessionLabel, sessionIdentifiers,
  DEFAULT_SESSION_FILTER,
  type SessionFilterState, type SessionDisplayId, type SessionSortField, type ActivityWindow,
} from './useSessionFilter';

const PLATFORM_LABEL: Record<string, string> = {
  claude_cli: 'Claude', codex_cli: 'Codex', gemini_cli: 'Gemini',
  grok_cli: 'Grok', antigravity_cli: 'Antigravity',
};
const DISPLAY_ID_LABEL: Record<SessionDisplayId, string> = {
  display_name: 'Name', tracking_id: 'Tracking id', cli_session_id: 'CLI id', terminal_session: 'Terminal',
};
const ACTIVITY_LABEL: Record<ActivityWindow, string> = {
  any: 'Any time', '1h': 'Past hour', '24h': 'Past day', '7d': 'Past week', '30d': 'Past month',
};

// Table columns; `sort` marks the ones that map to a sort field (clickable header).
const COLUMNS: { key: string; label: string; sort?: SessionSortField; width?: number }[] = [
  { key: 'name', label: 'Name', sort: 'name' },
  { key: 'product', label: 'Product', sort: 'product', width: 78 },
  { key: 'state', label: 'State', width: 74 },
  { key: 'last', label: 'Last active', sort: 'last_activity', width: 92 },
  { key: 'created', label: 'Created', sort: 'created', width: 70 },
];

const selectStyle: React.CSSProperties = {
  background: 'var(--bg-deep)', border: '1px solid var(--border)', borderRadius: 5,
  color: 'var(--text)', fontSize: 12, padding: '3px 6px', outline: 'none',
};

function agoLabel(iso?: string | null): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return '—';
  const s = Math.max(0, (Date.now() - t) / 1000);
  if (s < 60) return `${Math.floor(s)}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}
function dateLabel(iso?: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '—' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export interface SessionPickerProps {
  selectedId?: string | null;
  onSelect: (trackingId: string) => void;
  onConfirm?: (trackingId: string) => void;   // double-click
  initialFilter?: Partial<SessionFilterState>;
  height?: number | string;
}

export default function SessionPicker({
  selectedId, onSelect, onConfirm, initialFilter, height = 300,
}: SessionPickerProps): JSX.Element {
  const { sessions } = useSessionStore();
  const { storeData: folderStoreData } = useFolderStore();
  const [filter, setFilter] = useState<SessionFilterState>({ ...DEFAULT_SESSION_FILTER, ...initialFilter });
  const [displayId, setDisplayId] = useState<SessionDisplayId>('display_name');
  const [showFilters, setShowFilters] = useState(false);

  const set = <K extends keyof SessionFilterState>(k: K, v: SessionFilterState[K]) =>
    setFilter((f) => ({ ...f, [k]: v }));

  const products = useMemo(() => {
    const s = new Set<string>(); sessions.forEach((x) => s.add(x.platform)); return [...s].sort();
  }, [sessions]);
  const allTags = useMemo(() => {
    const s = new Set<string>(); sessions.forEach((x) => (x.tags || []).forEach((t: string) => s.add(t))); return [...s].sort();
  }, [sessions]);
  const folders = useMemo(() => {
    const all = folderStoreData.folders as Record<string, { id: string; name: string }>;
    return Object.values(all)
      .filter((fo) => fo.id !== 'all_briefs' && fo.id !== 'all_sessions')
      .map((fo) => ({ id: fo.id, name: fo.name }))
      .sort((a, b) => a.name.localeCompare(b.name));
  }, [folderStoreData]);

  const filtered = useSessionFilter(sessions, filter);
  const activeFilterCount =
    (filter.product ? 1 : 0) + (filter.state !== 'all' ? 1 : 0) +
    (filter.folderId ? 1 : 0) + (filter.tags.length ? 1 : 0) + (filter.activityWithin !== 'any' ? 1 : 0);

  // Click a sortable column header: same field → flip dir; else → switch to it.
  const clickSort = (f: SessionSortField) => setFilter((prev) => ({
    ...prev,
    sortField: f,
    sortDir: prev.sortField === f ? (prev.sortDir === 'asc' ? 'desc' : 'asc') : prev.sortDir,
  }));

  const cellStyle: React.CSSProperties = { padding: '4px 8px', fontSize: 11.5, whiteSpace: 'nowrap' };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6, minWidth: 480 }}>
      {/* Header: search + Filters toggle */}
      <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
        <input
          autoFocus
          value={filter.search}
          onChange={(e) => set('search', e.target.value)}
          placeholder="Search name, ids, platform, roles, tags…"
          style={{ ...selectStyle, flex: 1, padding: '5px 9px', fontSize: 12.5 }}
        />
        <button
          onClick={() => setShowFilters((v) => !v)}
          title="Show/hide filters"
          style={{ ...selectStyle, cursor: 'pointer', color: activeFilterCount ? 'var(--text)' : 'var(--text-muted)',
            borderColor: showFilters || activeFilterCount ? 'var(--accent-blue)' : 'var(--border)', display: 'inline-flex', alignItems: 'center', gap: 5 }}
        >
          Filters{activeFilterCount ? ` (${activeFilterCount})` : ''}
          <span style={{ fontSize: 9 }}>{showFilters ? '▴' : '▾'}</span>
        </button>
      </div>

      {/* Collapsible filter row */}
      {showFilters && (
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, alignItems: 'center', padding: '2px 0' }}>
          <select style={selectStyle} value={filter.product ?? ''} onChange={(e) => set('product', e.target.value || null)} title="AI product">
            <option value="">All products</option>
            {products.map((p) => <option key={p} value={p}>{PLATFORM_LABEL[p] || p}</option>)}
          </select>
          <select style={selectStyle} value={filter.state} onChange={(e) => set('state', e.target.value as SessionFilterState['state'])} title="Run state">
            <option value="all">Any state</option>
            <option value="running">Running</option>
            <option value="stopped">Stopped</option>
          </select>
          <select style={selectStyle} value={filter.activityWithin} onChange={(e) => set('activityWithin', e.target.value as ActivityWindow)} title="Last activity">
            {(Object.keys(ACTIVITY_LABEL) as ActivityWindow[]).map((w) => <option key={w} value={w}>{ACTIVITY_LABEL[w]}</option>)}
          </select>
          <select style={selectStyle} value={filter.folderId ?? ''} onChange={(e) => set('folderId', e.target.value || null)} title="Folder">
            <option value="">All folders</option>
            {folders.map((fo) => <option key={fo.id} value={fo.id}>{fo.name}</option>)}
          </select>
          <MultiSelectMenu label="Tags" options={allTags} selected={filter.tags} onChange={(t) => set('tags', t)} />
          <span style={{ marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 4, color: 'var(--text-muted)', fontSize: 11 }}>
            Show as
            <select style={selectStyle} value={displayId} onChange={(e) => setDisplayId(e.target.value as SessionDisplayId)} title="Which identifier to display">
              {(Object.keys(DISPLAY_ID_LABEL) as SessionDisplayId[]).map((k) => <option key={k} value={k}>{DISPLAY_ID_LABEL[k]}</option>)}
            </select>
          </span>
        </div>
      )}

      {/* Sortable table */}
      <div style={{ height, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg-deep)' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse' }}>
          <thead>
            <tr style={{ position: 'sticky', top: 0, background: 'var(--bg-panel, var(--bg-card))', zIndex: 1 }}>
              {COLUMNS.map((c) => {
                const active = c.sort && filter.sortField === c.sort;
                return (
                  <th key={c.key}
                    onClick={c.sort ? () => clickSort(c.sort!) : undefined}
                    style={{ textAlign: 'left', padding: '5px 8px', fontSize: 10.5, textTransform: 'uppercase', letterSpacing: '.04em',
                      color: active ? 'var(--text)' : 'var(--text-muted)', fontWeight: 700, borderBottom: '1px solid var(--border)',
                      cursor: c.sort ? 'pointer' : 'default', width: c.width, userSelect: 'none' }}>
                    {c.label}{active ? (filter.sortDir === 'asc' ? ' ▲' : ' ▼') : ''}
                  </th>
                );
              })}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr><td colSpan={COLUMNS.length} style={{ padding: '24px 12px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>No sessions match.</td></tr>
            ) : filtered.map((s) => {
              const sel = s.tracking_id === selectedId;
              const running = s.process_status === 'running';
              return (
                <tr key={s.tracking_id}
                  onClick={() => onSelect(s.tracking_id)}
                  onDoubleClick={() => onConfirm?.(s.tracking_id)}
                  title={sessionIdentifiers(s)}
                  style={{ cursor: 'pointer', background: sel ? 'var(--accent-blue-bg, var(--bg-hover))' : 'transparent', borderBottom: '1px solid var(--border)' }}>
                  <td style={{ ...cellStyle, overflow: 'hidden', textOverflow: 'ellipsis', maxWidth: 0 }}>
                    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                      <span title={running ? 'running' : 'stopped'} style={{ width: 6, height: 6, borderRadius: '50%', flexShrink: 0, background: running ? 'var(--accent-green)' : 'var(--text-muted)' }} />
                      <span style={{ color: 'var(--text)', fontWeight: sel ? 700 : 500 }}>{sessionLabel(s, displayId)}</span>
                    </span>
                  </td>
                  <td style={{ ...cellStyle, color: 'var(--text-sec)' }}>{PLATFORM_LABEL[s.platform] || s.platform}</td>
                  <td style={{ ...cellStyle, color: running ? 'var(--accent-green)' : 'var(--text-muted)' }}>{running ? 'running' : 'stopped'}</td>
                  <td style={{ ...cellStyle, color: 'var(--text-muted)' }}>{agoLabel(s.last_activity)}</td>
                  <td style={{ ...cellStyle, color: 'var(--text-muted)' }}>{dateLabel(s.created_at)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{filtered.length} of {sessions.length} sessions</div>
    </div>
  );
}
