/**
 * StatusFilterMenu — a compact, narrow multi-select for statuses. Replaces a
 * wide row of status pills with a single button that opens a checklist popover,
 * so it fits inline on a control bar. Reusable: pass the status set + the active
 * Set + toggle/all/none handlers and colour/label resolvers.
 */

import { useState, useRef, useEffect } from 'react';

interface Props {
  statuses: string[];
  active: Set<string>;
  onToggle: (status: string) => void;
  onAll: () => void;
  onNone: () => void;
  statusColor: (status: string) => string;
  statusLabel: (status: string) => string;
}

export default function StatusFilterMenu({
  statuses, active, onToggle, onAll, onNone, statusColor, statusLabel,
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

  const activeCount = statuses.filter((s) => active.has(s)).length;
  const allOn = activeCount === statuses.length && statuses.length > 0;
  // Summary: "All" when everything's on, else the active count. Plus a strip of
  // little colour dots for the active statuses so it reads at a glance.
  const summary = allOn ? 'All' : activeCount === 0 ? 'None' : String(activeCount);

  return (
    <div className="wm-statusmenu" ref={ref} style={{ position: 'relative' }}>
      <button
        className="wm-statusmenu-btn"
        onClick={() => setOpen((v) => !v)}
        title="Filter by status"
      >
        <span className="wm-statusmenu-label">Status</span>
        <span className="wm-statusmenu-dots">
          {statuses.filter((s) => active.has(s)).slice(0, 6).map((s) => (
            <span key={s} className="wm-statusmenu-dot" style={{ background: statusColor(s) }} />
          ))}
        </span>
        <span className="wm-statusmenu-count">{summary}</span>
        <span className="wm-statusmenu-caret">{open ? '▴' : '▾'}</span>
      </button>
      {open && (
        <div className="wm-statusmenu-pop">
          <div className="wm-statusmenu-actions">
            <button onClick={onAll}>All</button>
            <button onClick={onNone}>None</button>
          </div>
          {statuses.map((s) => {
            const on = active.has(s);
            return (
              <label key={s} className="wm-statusmenu-row">
                <input type="checkbox" checked={on} onChange={() => onToggle(s)} />
                <span className="wm-statusmenu-dot" style={{ background: statusColor(s) }} />
                <span style={{ color: on ? statusColor(s) : 'var(--text-sec)' }}>{statusLabel(s)}</span>
              </label>
            );
          })}
        </div>
      )}
    </div>
  );
}
