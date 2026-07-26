/**
 * SortMenu — a compact sort-field dropdown for the Work Mgr list controls.
 *
 * The direction lives IN the field selection (no separate asc/desc button): the
 * trigger and the active row show a ▲/▼ chevron for the current direction, and
 * picking the field that's ALREADY active flips the direction. Picking a
 * different field switches to it (keeping the current direction). Mirrors the
 * StatusFilterMenu popover pattern (button + outside-click-dismissed list).
 */

import { useState, useRef, useEffect } from 'react';

interface SortField { value: string; label: string }

interface Props {
  fields: SortField[];
  value: string;         // current sort field
  ascending: boolean;    // ACTUAL direction — ▲ ascending / ▼ descending (todo_0607)
  onSelect: (value: string) => void;   // parent toggles-if-same, switches-if-different
}

export default function SortMenu({ fields, value, ascending, onSelect }: Props): JSX.Element {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('mousedown', onDown);
    return () => window.removeEventListener('mousedown', onDown);
  }, [open]);

  const current = fields.find(f => f.value === value);
  const dir = ascending ? '▲' : '▼';
  const dirTitle = ascending ? 'ascending — click the field again to flip' : 'descending — click the field again to flip';

  return (
    <div className="wm-statusmenu" ref={ref} style={{ position: 'relative' }}>
      <button className="wm-statusmenu-btn" onClick={() => setOpen(v => !v)} title={`Sort by ${current?.label ?? value} (${dirTitle})`}>
        <span className="wm-statusmenu-label">Sort: {current?.label ?? value}</span>
        <span className="wm-statusmenu-count" style={{ fontWeight: 700 }}>{dir}</span>
        <span className="wm-statusmenu-caret">{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <div className="wm-statusmenu-pop">
          {fields.map(f => {
            const active = f.value === value;
            // Same field → flip direction in place (keep menu open); different
            // field → switch and close.
            const pick = () => { onSelect(f.value); if (!active) setOpen(false); };
            return (
              <button
                key={f.value}
                className="wm-statusmenu-row"
                onClick={pick}
                style={{ display: 'flex', alignItems: 'center', gap: 8, width: '100%', background: 'transparent', border: 'none', cursor: 'pointer', textAlign: 'left', padding: '4px 8px', color: active ? 'var(--text)' : 'var(--text-sec)', fontWeight: active ? 700 : 400 }}
              >
                <span style={{ width: 12, color: 'var(--accent-blue)' }}>{active ? dir : ''}</span>
                <span>{f.label}</span>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
