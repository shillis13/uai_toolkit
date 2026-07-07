import { useEffect, useRef, type RefObject } from 'react';

/**
 * Unified dismiss handler for all context menus.
 *
 * - Left-click outside → closes menu
 * - Right-click outside → closes menu AND blocks propagation so no new
 *   menu opens from the same event (capture-phase contextmenu listener)
 * - Escape → closes menu
 *
 * Listeners are deferred by one tick so the event that opened the menu
 * doesn't immediately self-dismiss.
 *
 * IMPORTANT: Only registers listeners when isOpen is true. When the menu
 * is not visible, no capture-phase listeners block contextmenu events.
 */
export function useContextMenuDismiss(
  menuRef: RefObject<HTMLElement | null>,
  onClose: () => void,
  isOpen?: boolean,
): void {
  const closeRef = useRef(onClose);
  closeRef.current = onClose;

  // If isOpen is not provided, infer from menuRef.current at call time.
  // Callers should pass isOpen explicitly for reliable behavior.
  const active = isOpen ?? (menuRef.current != null);

  useEffect(() => {
    if (!active) return;

    const isInside = (e: Event) =>
      menuRef.current != null && menuRef.current.contains(e.target as Node);

    const handleMouseDown = (e: MouseEvent) => {
      if (!isInside(e)) closeRef.current();
    };

    // Capture phase: fires before React synthetic onContextMenu handlers,
    // preventing a dismiss-right-click from reopening another menu.
    const handleContextMenu = (e: MouseEvent) => {
      if (!isInside(e)) {
        e.preventDefault();
        e.stopPropagation();
        closeRef.current();
      }
    };

    const handleEscape = (e: KeyboardEvent) => {
      if (e.key === 'Escape') closeRef.current();
    };

    const timer = setTimeout(() => {
      window.addEventListener('mousedown', handleMouseDown);
      window.addEventListener('contextmenu', handleContextMenu, true);
      window.addEventListener('keydown', handleEscape);
    }, 0);

    return () => {
      clearTimeout(timer);
      window.removeEventListener('mousedown', handleMouseDown);
      window.removeEventListener('contextmenu', handleContextMenu, true);
      window.removeEventListener('keydown', handleEscape);
    };
  }, [active]);
}
