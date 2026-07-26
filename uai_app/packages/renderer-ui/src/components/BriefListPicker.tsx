/**
 * BriefListPicker — a sortable list of the brief FILES with a collapsible section
 * per child folder (auto_briefs, …) (todo_0600 section 2, PianoMan's rework). NOT a
 * search box: briefs are few and we don't anticipate many, so a plain sortable
 * list reads better. Top-level briefs sit in the main list; each subfolder is an
 * expandable section below.
 *
 * Sourced from the brief index (window.uai.briefs.list via the card store), which
 * skips _archive and carries display_name / created_at / last_activity for sorting.
 * The selection is reported as the contextItems shape session.create / traits.load
 * consume: { type: 'briefs', name }, where `name` is the folder-qualified brief id.
 */

import { useMemo, useState } from 'react';
import { useCardStore } from '../stores';
import type { ContextSelection } from './AddContextPicker';

type SortKey = 'name' | 'recent' | 'created';

interface BriefRow { name: string; label: string; created: string; recent: string }

interface BriefListPickerProps {
  selected: ContextSelection[];
  onChange: (items: ContextSelection[]) => void;
  /** false = single-select (radio-like); default true (multi). */
  multi?: boolean;
  height?: number | string;
}

const rowSel = (s: ContextSelection[]) => new Set(s.filter((x) => x.type === 'briefs').map((x) => x.name));

function fmtDate(iso?: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? '' : d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

export default function BriefListPicker({ selected, onChange, multi = true, height = 240 }: BriefListPickerProps): JSX.Element {
  const { briefs } = useCardStore();
  const [sortKey, setSortKey] = useState<SortKey>('recent');
  const [asc, setAsc] = useState(false);
  const [openFolders, setOpenFolders] = useState<Set<string>>(new Set());

  // Split the flat brief index into top-level rows + a folder → rows map.
  const { top, folders } = useMemo(() => {
    const top: BriefRow[] = [];
    const folders = new Map<string, BriefRow[]>();
    for (const b of briefs) {
      const name = (b as { name?: string }).name || b.display_name;
      const row: BriefRow = {
        name,
        label: b.display_name || name.split('/').pop() || name,
        created: (b as { created_at?: string }).created_at || '',
        recent: (b as { last_activity?: string }).last_activity || '',
      };
      const slash = name.indexOf('/');
      if (slash === -1) top.push(row);
      else {
        const folder = name.slice(0, slash);
        (folders.get(folder) || folders.set(folder, []).get(folder)!).push(row);
      }
    }
    return { top, folders };
  }, [briefs]);

  const cmp = (a: BriefRow, b: BriefRow) => {
    let r = 0;
    if (sortKey === 'name') r = a.label.toLowerCase().localeCompare(b.label.toLowerCase());
    else if (sortKey === 'created') r = (a.created).localeCompare(b.created);
    else r = (a.recent).localeCompare(b.recent);
    if (r === 0) r = a.name.localeCompare(b.name);   // stable tie-break
    return asc ? r : -r;
  };

  const sel = rowSel(selected);
  const toggle = (name: string) => {
    if (sel.has(name)) onChange(selected.filter((x) => !(x.type === 'briefs' && x.name === name)));
    else if (multi) onChange([...selected, { type: 'briefs', name }]);
    else onChange([{ type: 'briefs', name }]);   // single-select replaces
  };
  const toggleFolder = (f: string) =>
    setOpenFolders((p) => { const n = new Set(p); n.has(f) ? n.delete(f) : n.add(f); return n; });

  const sortBtn = (k: SortKey, lbl: string) => (
    <button onClick={() => { if (sortKey === k) setAsc((v) => !v); else { setSortKey(k); setAsc(k === 'name'); } }}
      style={{ background: 'transparent', border: 'none', cursor: 'pointer', fontSize: 11, fontWeight: sortKey === k ? 700 : 500,
        color: sortKey === k ? 'var(--text)' : 'var(--text-muted)', padding: '2px 4px' }}>
      {lbl}{sortKey === k ? (asc ? ' ▲' : ' ▼') : ''}
    </button>
  );

  const briefRow = (r: BriefRow, indent = 0) => {
    const on = sel.has(r.name);
    return (
      <label key={r.name} title={r.name}
        style={{ display: 'flex', alignItems: 'center', gap: 8, padding: `4px 10px 4px ${10 + indent}px`, cursor: 'pointer', fontSize: 12.5,
          background: on ? 'var(--accent-blue-bg, var(--bg-hover))' : 'transparent', color: on ? 'var(--text)' : 'var(--text-sec)' }}>
        <input type={multi ? 'checkbox' : 'radio'} checked={on} onChange={() => toggle(r.name)} />
        <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{r.label}</span>
        <span style={{ flexShrink: 0, fontSize: 10.5, color: 'var(--text-muted)' }}>{fmtDate(r.recent)}</span>
      </label>
    );
  };

  const folderNames = [...folders.keys()].sort();

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 2, paddingLeft: 4 }}>
        <span style={{ fontSize: 10.5, color: 'var(--text-muted)', marginRight: 4 }}>Sort:</span>
        {sortBtn('recent', 'Recent')}{sortBtn('name', 'Name')}{sortBtn('created', 'Created')}
        {sel.size > 0 && (
          <button onClick={() => onChange(selected.filter((x) => x.type !== 'briefs'))}
            style={{ marginLeft: 'auto', background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)', borderRadius: 5, padding: '2px 7px', fontSize: 10.5, cursor: 'pointer' }}>
            Clear ({sel.size})
          </button>
        )}
      </div>
      <div style={{ height, overflowY: 'auto', border: '1px solid var(--border)', borderRadius: 6, background: 'var(--bg-deep)' }}>
        {briefs.length === 0 ? (
          <div style={{ padding: '24px 12px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 12 }}>No briefs.</div>
        ) : (
          <>
            {[...top].sort(cmp).map((r) => briefRow(r))}
            {folderNames.map((f) => {
              const open = openFolders.has(f);
              const rows = [...(folders.get(f) || [])].sort(cmp);
              const selCount = rows.filter((r) => sel.has(r.name)).length;
              return (
                <div key={f}>
                  <button onClick={() => toggleFolder(f)}
                    style={{ display: 'flex', alignItems: 'center', gap: 6, width: '100%', textAlign: 'left', background: 'var(--bg-panel, var(--bg-card))', border: 'none', borderTop: '1px solid var(--border)', color: 'var(--text-sec)', fontSize: 11, fontWeight: 700, padding: '5px 10px', cursor: 'pointer' }}>
                    <span style={{ fontSize: 9 }}>{open ? '▼' : '▶'}</span>
                    {f} <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>({rows.length}{selCount ? ` · ${selCount} selected` : ''})</span>
                  </button>
                  {open && rows.map((r) => briefRow(r, 14))}
                </div>
              );
            })}
          </>
        )}
      </div>
    </div>
  );
}
