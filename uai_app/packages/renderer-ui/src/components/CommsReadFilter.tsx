/**
 * CommsReadFilter — two candidate pill designs for the Right-Panel Comms
 * Read/Unread filter, rendered side by side so PianoMan can try each and pick.
 *
 * Both drive the SAME value ('all' | 'read' | 'unread') and onChange, so clicking
 * either one updates the other's highlight — a live A/B of the two interactions.
 *
 * Variant 1 — CyclePill: one compact pill that steps All → Read → Unread → All.
 * Variant 2 — SplitPill: one pill, two halves (Read | Unread). Each half toggles
 *             independently; both-on and both-off both mean "show all" (PianoMan's
 *             stated rule).
 *
 * Once a winner is chosen, delete the loser.
 */

export type ReadFilter = 'all' | 'read' | 'unread';

interface Props {
  value: ReadFilter;
  onChange: (v: ReadFilter) => void;
}

// Read = settled/green, Unread = attention/blue (matches the unread dot).
const READ_C = 'var(--accent-green)';
const UNREAD_C = 'var(--accent-blue)';

// ── Variant 1: cycle-through pill ───────────────────────────────────────────
const CYCLE_NEXT: Record<ReadFilter, ReadFilter> = { all: 'read', read: 'unread', unread: 'all' };
const CYCLE_LABEL: Record<ReadFilter, string> = { all: 'All', read: 'Read', unread: 'Unread' };
const CYCLE_COLOR: Record<ReadFilter, string> = { all: 'var(--text-muted)', read: READ_C, unread: UNREAD_C };

export function ReadFilterCyclePill({ value, onChange }: Props): JSX.Element {
  const c = CYCLE_COLOR[value];
  const on = value !== 'all';
  return (
    <button
      type="button"
      title={`Filter: ${CYCLE_LABEL[value]} — click to cycle (All → Read → Unread)`}
      onClick={() => onChange(CYCLE_NEXT[value])}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        fontSize: 10,
        fontWeight: 600,
        lineHeight: 1,
        padding: '3px 8px',
        borderRadius: 10,
        cursor: 'pointer',
        color: on ? c : 'var(--text-muted)',
        border: `1px solid color-mix(in srgb, ${c} ${on ? '80%' : '40%'}, transparent)`,
        background: on ? `color-mix(in srgb, ${c} 16%, transparent)` : 'transparent',
      }}
    >
      <span style={{ opacity: 0.7, fontSize: 9 }}>{'↻'}</span>
      {CYCLE_LABEL[value]}
    </button>
  );
}

// ── Variant 2: split pill (two toggle halves) ───────────────────────────────
// Derive the two independent toggles from the single value, and fold them back.
function toToggles(v: ReadFilter): { read: boolean; unread: boolean } {
  if (v === 'read') return { read: true, unread: false };
  if (v === 'unread') return { read: false, unread: true };
  return { read: true, unread: true }; // 'all' shows both halves lit
}
function fromToggles(read: boolean, unread: boolean): ReadFilter {
  if (read === unread) return 'all'; // both-on or both-off ⇒ all
  return read ? 'read' : 'unread';
}

export function ReadFilterSplitPill({ value, onChange }: Props): JSX.Element {
  const t = toToggles(value);
  const half = (side: 'read' | 'unread'): React.CSSProperties => {
    const active = t[side];
    const c = side === 'read' ? READ_C : UNREAD_C;
    return {
      fontSize: 10,
      fontWeight: 600,
      lineHeight: 1,
      padding: '3px 8px',
      cursor: 'pointer',
      color: active ? c : 'var(--text-muted)',
      background: active ? `color-mix(in srgb, ${c} 18%, transparent)` : 'transparent',
      border: 'none',
    };
  };
  return (
    <span
      title="Read / Unread filter — toggle each side (both on = both off = all)"
      style={{
        display: 'inline-flex',
        alignItems: 'stretch',
        borderRadius: 10,
        overflow: 'hidden',
        border: '1px solid var(--border)',
      }}
    >
      <button
        type="button"
        style={{ ...half('read'), borderRight: '1px solid var(--border)' }}
        onClick={() => onChange(fromToggles(!t.read, t.unread))}
      >
        Read
      </button>
      <button
        type="button"
        style={half('unread')}
        onClick={() => onChange(fromToggles(t.read, !t.unread))}
      >
        Unread
      </button>
    </span>
  );
}
