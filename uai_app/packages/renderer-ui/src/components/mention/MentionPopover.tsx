/**
 * MentionPopover — presentational dropdown for the reusable `@`-autocomplete.
 *
 * Position-fixed, anchored at the caret rect (sits just above the `@`). Scrolls when
 * there are many rows (no arbitrary result cap). Drive it with a UseMentionResult:
 *   <MentionPopover state={mention} />
 */

import { useEffect, useRef } from 'react';
import { createPortal } from 'react-dom';
import type { UseMentionResult } from './useMention';
import type { MentionKind } from './types';

const KIND_ICON: Record<string, string> = {
  session: '◉',
  team: '◈',
  project: '▣',
  directory: '📁',
  file: '📄',
};

function iconFor(kind: MentionKind): string {
  return KIND_ICON[kind] ?? '@';
}

const POPOVER_WIDTH = 320;

export interface MentionPopoverProps {
  state: UseMentionResult;
}

export function MentionPopover({ state }: MentionPopoverProps): JSX.Element | null {
  const { open, items, activeIndex, anchor, hint, apply, setActiveIndex } = state;
  const listRef = useRef<HTMLDivElement>(null);

  // Keep the active row scrolled into view during keyboard nav.
  useEffect(() => {
    const active = listRef.current?.querySelector('.mention-row.active');
    (active as HTMLElement | null)?.scrollIntoView({ block: 'nearest' });
  }, [activeIndex, items]);

  if (!open || !anchor || items.length === 0) return null;

  // Clamp horizontally to the viewport; open upward from the caret (prompt boxes live
  // at the bottom, and this reads naturally near the `@`).
  const left = Math.max(8, Math.min(anchor.left, window.innerWidth - POPOVER_WIDTH - 8));
  const style: React.CSSProperties = {
    position: 'fixed',
    left,
    width: POPOVER_WIDTH,
    bottom: window.innerHeight - anchor.top + 4,
    // Above the highest floating overlay (NoteDialog portals at 11000). The
    // popover must clear ANY dialog it's used inside, else it renders beneath —
    // which is exactly what happened in the Add Note dialog (note_0033 #5).
    zIndex: 12000,
  };

  // Portal to <body> so the position:fixed dropdown is anchored to the VIEWPORT,
  // never contained/clipped by an ancestor with a transform/filter/will-change
  // (e.g. an animated tab-content pane — which is why it failed inside Notes Mgr
  // but worked in the Prompt Box).
  return createPortal(
    <div className="mention-popover" style={style} ref={listRef} role="listbox" aria-label="Suggestions">
      {hint && <div className="mention-hint">{hint}</div>}
      {items.map((it, i) => (
        <div
          key={it.id}
          className={`mention-row${i === activeIndex ? ' active' : ''}`}
          onMouseDown={(e) => { e.preventDefault(); apply(it); }}
          onMouseEnter={() => setActiveIndex(i)}
          role="option"
          aria-selected={i === activeIndex}
          title={it.detail || it.label}
        >
          <span className={`mention-icon kind-${it.kind}`}>{iconFor(it.kind)}</span>
          <span className="mention-label">{it.label}</span>
          {it.detail && <span className="mention-detail">{it.detail}</span>}
          {it.badge && <span className="mention-badge">{it.badge}</span>}
        </div>
      ))}
    </div>,
    document.body,
  );
}
