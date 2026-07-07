/**
 * useDraggable — reusable drag behavior for floating dialogs/popovers.
 *
 * Standing pattern for dialogs: give the dialog root `style={dragStyle}` (a transform
 * offset applied on top of its own positioning) and put `onMouseDown={onHandleMouseDown}`
 * on the drag handle (usually the header). Dragging never fights the dialog's anchor —
 * it just translates from wherever it's positioned.
 *
 * Drags that start on an interactive control (button/input/select/textarea/a) are
 * ignored, so header buttons (close, edit) still work.
 */

import { useCallback, useRef, useState, type CSSProperties } from 'react';

export interface DraggableApi {
  /** Current drag offset in px from the dialog's anchored position. */
  offset: { x: number; y: number };
  /** Apply to the dialog root's style (a translate transform). */
  dragStyle: CSSProperties;
  /** Put on the drag handle (e.g. the header) as onMouseDown. */
  onHandleMouseDown: (e: React.MouseEvent) => void;
  /** Reset back to the anchored position. */
  reset: () => void;
  /** True while a drag is in progress. */
  dragging: boolean;
}

export function useDraggable(): DraggableApi {
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [dragging, setDragging] = useState(false);
  const startRef = useRef<{ mx: number; my: number; ox: number; oy: number } | null>(null);

  const onHandleMouseDown = useCallback((e: React.MouseEvent) => {
    if (e.button !== 0) return;                        // left button only
    const target = e.target as HTMLElement;
    if (target.closest('button, input, select, textarea, a')) return;  // let controls work
    e.preventDefault();
    startRef.current = { mx: e.clientX, my: e.clientY, ox: offset.x, oy: offset.y };
    setDragging(true);
    document.body.style.userSelect = 'none';
    document.body.style.cursor = 'move';

    const onMove = (ev: MouseEvent) => {
      const s = startRef.current;
      if (!s) return;
      setOffset({ x: s.ox + (ev.clientX - s.mx), y: s.oy + (ev.clientY - s.my) });
    };
    const onUp = () => {
      setDragging(false);
      startRef.current = null;
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
      document.body.style.userSelect = '';
      document.body.style.cursor = '';
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [offset.x, offset.y]);

  const reset = useCallback(() => setOffset({ x: 0, y: 0 }), []);

  const dragStyle: CSSProperties = (offset.x || offset.y)
    ? { transform: `translate(${offset.x}px, ${offset.y}px)` }
    : {};

  return { offset, dragStyle, onHandleMouseDown, reset, dragging };
}
