/**
 * MultiSelectMenu — a compact dropdown-checklist multi-select. The sanctioned
 * control for a LARGE or DYNAMIC choice set (tags, folders, models, …) where a
 * row of pills would be noise (see components/DESIGN.md Pills section). A single button
 * shows the label + selected count and opens a checklist popover; dismissed on
 * outside click. Mirrors StatusFilterMenu's shape, generalized.
 */

import { useState, useRef, useEffect } from 'react';

interface Props {
  label: string;
  options: string[];
  selected: string[];
  onChange: (next: string[]) => void;
  /** Optional label formatter for an option (default: the option itself). */
  render?: (opt: string) => string;
  maxHeight?: number;
}

export default function MultiSelectMenu({
  label, options, selected, onChange, render, maxHeight = 240,
}: Props): JSX.Element {
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

  const sel = new Set(selected);
  const toggle = (o: string) =>
    onChange(sel.has(o) ? selected.filter((x) => x !== o) : [...selected, o]);

  return (
    <div ref={ref} style={{ position: 'relative', display: 'inline-block' }}>
      <button
        onClick={() => setOpen((v) => !v)}
        title={selected.length ? `${label}: ${selected.join(', ')}` : label}
        style={{
          background: 'var(--bg-deep)', border: '1px solid var(--border)', borderRadius: 5,
          color: selected.length ? 'var(--text)' : 'var(--text-muted)', fontSize: 12,
          padding: '3px 8px', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 5,
        }}
      >
        {label}{selected.length ? ` (${selected.length})` : ''}
        <span style={{ fontSize: 9, color: 'var(--text-muted)' }}>{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <div style={{
          position: 'absolute', top: '100%', left: 0, marginTop: 3, zIndex: 10001,
          minWidth: 170, maxHeight, overflowY: 'auto',
          background: 'var(--bg-panel, var(--bg-card))', border: '1px solid var(--border-bright, var(--border))',
          borderRadius: 6, boxShadow: '0 8px 24px rgba(0,0,0,0.35)', padding: 4,
        }}>
          {options.length === 0 ? (
            <div style={{ padding: '6px 8px', color: 'var(--text-muted)', fontSize: 12 }}>None</div>
          ) : (
            <>
              {selected.length > 0 && (
                <button onClick={() => onChange([])}
                  style={{ width: '100%', textAlign: 'left', background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: 11, padding: '3px 8px', cursor: 'pointer' }}>
                  Clear ({selected.length})
                </button>
              )}
              {options.map((o) => (
                <label key={o} title={o}
                  style={{ display: 'flex', alignItems: 'center', gap: 7, padding: '3px 8px', cursor: 'pointer', fontSize: 12,
                    color: sel.has(o) ? 'var(--text)' : 'var(--text-sec)' }}>
                  <input type="checkbox" checked={sel.has(o)} onChange={() => toggle(o)} />
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{render ? render(o) : o}</span>
                </label>
              ))}
            </>
          )}
        </div>
      )}
    </div>
  );
}
