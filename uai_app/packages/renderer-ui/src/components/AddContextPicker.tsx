/**
 * AddContextPicker — the reusable "add context on launch" picker (todo_0600
 * section 1.3 + section 3.1). Shared by the Resume/Fork dialog and the Custom launcher.
 *
 * Lists everything a new/forked session can be seeded with — briefs, context
 * compositions (bundles/roles), and context files — from window.uai.traits.list
 * (discovery mode), grouped by kind with search + multi-select, and reports the
 * selection as the `contextItems` shape session.create consumes:
 *   { type, name, filePath? }[]
 *
 * Self-contained (no session needed); a controlled `selected` + onChange keeps
 * the parent dialog the single source of truth so it can submit the list.
 */

import { useEffect, useMemo, useState, useCallback } from 'react';

interface TraitItem { type: string; name: string; filePath?: string; mtime?: string }
export interface ContextSelection { type: string; name: string; filePath?: string }

interface AddContextPickerProps {
  selected: ContextSelection[];
  onChange: (items: ContextSelection[]) => void;
  height?: number | string;
  /** Restrict to these raw item types (e.g. ['briefs']) — used by the Briefs
   *  dialogs to reuse this as a brief-only multi-select. Omit for all types. */
  onlyTypes?: string[];
}

// Friendly group labels + display order (section 1.3 kinds first, then the rest).
const TYPE_LABEL: Record<string, string> = {
  briefs: 'Briefs',
  profiles: 'Bundles', bundles: 'Bundles',
  roles: 'Roles',
  traits: 'Context files', knowledge: 'Context files', instructions: 'Context files',
  skills: 'Skills', globals: 'Globals', mslots: 'Memory slots',
};
const TYPE_ORDER = ['Briefs', 'Bundles', 'Roles', 'Context files', 'Skills', 'Globals', 'Memory slots'];
const DEFAULT_OPEN = new Set(['Briefs', 'Bundles', 'Roles']);

const key = (t: string, n: string) => `${t}::${n}`;
const groupLabel = (type: string) => TYPE_LABEL[type] || (type.charAt(0).toUpperCase() + type.slice(1));

export default function AddContextPicker({ selected, onChange, height = 260, onlyTypes }: AddContextPickerProps): JSX.Element {
  const [items, setItems] = useState<TraitItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [openGroups, setOpenGroups] = useState<Set<string>>(new Set(DEFAULT_OPEN));
  const onlyTypesKey = JSON.stringify(onlyTypes ?? []);

  useEffect(() => {
    let live = true;
    (async () => {
      try {
        const res = await window.uai.traits.list('_discovery_');
        let list = Array.isArray(res) ? (res as TraitItem[]) : [];
        if (onlyTypes && onlyTypes.length) list = list.filter((it) => onlyTypes.includes(it.type));
        if (live) { setItems(list); setError(null); }
      } catch {
        if (live) setError('Failed to load context items.');
      } finally {
        if (live) setLoading(false);
      }
    })();
    return () => { live = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [onlyTypesKey]);

  const selectedKeys = useMemo(() => new Set(selected.map((s) => key(s.type, s.name))), [selected]);

  // Filter by search, then group by friendly label in the fixed display order.
  const groups = useMemo(() => {
    const q = search.trim().toLowerCase();
    const filtered = q
      ? items.filter((it) => it.name.toLowerCase().includes(q) || it.type.toLowerCase().includes(q))
      : items;
    const byLabel = new Map<string, TraitItem[]>();
    for (const it of filtered) {
      const lbl = groupLabel(it.type);
      (byLabel.get(lbl) || byLabel.set(lbl, []).get(lbl)!).push(it);
    }
    for (const list of byLabel.values()) list.sort((a, b) => a.name.localeCompare(b.name));
    const ordered = [...byLabel.keys()].sort((a, b) => {
      const ia = TYPE_ORDER.indexOf(a); const ib = TYPE_ORDER.indexOf(b);
      return (ia === -1 ? 99 : ia) - (ib === -1 ? 99 : ib) || a.localeCompare(b);
    });
    return ordered.map((lbl) => ({ label: lbl, items: byLabel.get(lbl)! }));
  }, [items, search]);

  const toggle = useCallback((it: TraitItem) => {
    const k = key(it.type, it.name);
    if (selectedKeys.has(k)) onChange(selected.filter((s) => key(s.type, s.name) !== k));
    else onChange([...selected, { type: it.type, name: it.name, filePath: it.filePath }]);
  }, [selected, selectedKeys, onChange]);

  const toggleGroup = (lbl: string) =>
    setOpenGroups((prev) => { const n = new Set(prev); n.has(lbl) ? n.delete(lbl) : n.add(lbl); return n; });

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <input value={search} onChange={(e) => setSearch(e.target.value)} placeholder="Search context…"
          style={{ flex: 1, background: 'var(--bg-deep)', border: '1px solid var(--border)', borderRadius: 5, color: 'var(--text)', fontSize: 12, padding: '5px 8px', outline: 'none' }} />
        {selected.length > 0 && (
          <button onClick={() => onChange([])} title="Clear selected context"
            style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)', borderRadius: 5, padding: '4px 8px', fontSize: 11, cursor: 'pointer' }}>
            Clear ({selected.length})
          </button>
        )}
      </div>

      <div style={{ height, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg-deep)' }}>
        {loading ? (
          <div style={{ padding: 16, color: 'var(--text-muted)', fontSize: 12 }}>Loading…</div>
        ) : error ? (
          <div style={{ padding: 16, color: 'var(--accent-orange)', fontSize: 12 }}>⚠ {error}</div>
        ) : groups.length === 0 ? (
          <div style={{ padding: 16, color: 'var(--text-muted)', fontSize: 12, textAlign: 'center' }}>No context items match.</div>
        ) : groups.map(({ label, items: gItems }) => {
          const open = openGroups.has(label) || !!search.trim();
          const selCount = gItems.filter((it) => selectedKeys.has(key(it.type, it.name))).length;
          return (
            <div key={label}>
              <button onClick={() => toggleGroup(label)}
                style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%', textAlign: 'left', background: 'var(--bg-panel, var(--bg-card))', border: 'none', borderBottom: '1px solid var(--border)', color: 'var(--text-sec)', fontSize: 11, fontWeight: 700, textTransform: 'uppercase', letterSpacing: '.04em', padding: '5px 10px', cursor: 'pointer' }}>
                <span style={{ fontSize: 9 }}>{open ? '▼' : '▶'}</span>
                {label} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({gItems.length}{selCount ? ` · ${selCount} selected` : ''})</span>
              </button>
              {open && gItems.map((it) => {
                const on = selectedKeys.has(key(it.type, it.name));
                return (
                  <label key={key(it.type, it.name)} title={it.filePath || it.name}
                    style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px 4px 20px', cursor: 'pointer', fontSize: 12,
                      background: on ? 'var(--accent-blue-bg, var(--bg-hover))' : 'transparent', color: on ? 'var(--text)' : 'var(--text-sec)' }}>
                    <input type="checkbox" checked={on} onChange={() => toggle(it)} />
                    <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{it.name}</span>
                  </label>
                );
              })}
            </div>
          );
        })}
      </div>
      {selected.length > 0 && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)' }}>{selected.length} context item{selected.length === 1 ? '' : 's'} will be added on launch.</div>
      )}
    </div>
  );
}
