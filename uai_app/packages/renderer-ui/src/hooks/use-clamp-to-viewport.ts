import { useLayoutEffect, useEffect, type RefObject } from 'react';

/**
 * useClampToViewport — the shared "stay on screen" behavior for any floating UI
 * element (dropdown, context menu, recipient picker, popover). PianoMan asked
 * every menu/dropdown to inherit this instead of each re-implementing (or
 * forgetting) edge handling.
 *
 * After the browser lays the element out at its intended anchored position, this
 * measures it and, if any edge is clipped by the window, nudges it back on-screen
 * with a CSS `transform` translate. Using `transform` (not left/top) makes it
 * anchor-agnostic: it works whether the element is positioned by left/top OR
 * right/bottom, and it never fights the anchoring math. Idempotent — the
 * transform is reset before every measure, so an element already fully visible is
 * left untouched, and re-running never drifts.
 *
 * Usage: give the floating element a ref and call this with (ref, isOpen). Pass
 * any position inputs (anchor x/y, style) in `deps` so it re-clamps when the
 * anchor moves. Runs in useLayoutEffect, so the shift lands before paint (no
 * visible jump).
 */
export function useClampToViewport(
  ref: RefObject<HTMLElement | null>,
  active: boolean,
  deps: unknown[] = [],
  opts: { margin?: number } = {},
): void {
  const margin = opts.margin ?? 6;
  useLayoutEffect(() => {
    if (!active) return;
    const el = ref.current;
    if (!el) return;
    // Reset any prior clamp so we measure the natural (anchored) position — keeps
    // this idempotent across re-runs and anchor changes.
    el.style.transform = '';
    const rect = el.getBoundingClientRect();
    if (rect.width === 0 && rect.height === 0) return;   // not laid out yet
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    let dx = 0;
    let dy = 0;
    // Horizontal: pull in from the right edge first, then guard the left.
    if (rect.right > vw - margin) dx = (vw - margin) - rect.right;
    if (rect.left + dx < margin) dx = margin - rect.left;
    // Vertical: pull in from the bottom edge first, then guard the top.
    if (rect.bottom > vh - margin) dy = (vh - margin) - rect.bottom;
    if (rect.top + dy < margin) dy = margin - rect.top;
    if (dx !== 0 || dy !== 0) {
      el.style.transform = `translate(${Math.round(dx)}px, ${Math.round(dy)}px)`;
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, active, margin, ...deps]);
}

/**
 * useSubmenuAutoFlip — the cascading-submenu companion to useClampToViewport
 * (todo_0547). Top-level menus clamp themselves via a transform, but their
 * CASCADING submenus (`.context-submenu`, opened at CSS `left:100%`) still fall
 * off the right/bottom edge when the parent menu sits near a screen edge — e.g.
 * right-clicking a session tab at the right edge of the Tab bar.
 *
 * This attaches ONE delegated `mouseover` listener to the menu root and, for any
 * `.submenu-trigger` the pointer enters, measures that trigger's direct
 * `.context-submenu` child and toggles `flip-left` / `flip-up` so the submenu
 * opens toward the available space instead of off-screen. DOM-based (not React
 * state), so it works for BOTH stateful submenus (SessionContextMenu's SubMenu)
 * and pure-CSS `:hover` cascades (Navigator [+ New], Workspace) with one call.
 *
 * Idempotent: flip classes are cleared before each measure, so the natural
 * position is measured every time and an already-fitting submenu is left alone.
 *
 * Usage: pass the menu container ref and whether it is open. Re-binds when
 * `active`/`deps` change.
 */
export function useSubmenuAutoFlip(
  ref: RefObject<HTMLElement | null>,
  active: boolean,
  deps: unknown[] = [],
  opts: { margin?: number } = {},
): void {
  const margin = opts.margin ?? 6;
  useEffect(() => {
    if (!active) return;
    const root = ref.current;
    if (!root) return;
    const onOver = (e: Event) => {
      const target = e.target as HTMLElement | null;
      const trigger = target?.closest?.('.submenu-trigger');
      if (!trigger || !root.contains(trigger)) return;
      const sub = trigger.querySelector(':scope > .context-submenu') as HTMLElement | null;
      if (!sub) return;
      // Clear prior flip so we measure the natural (left:100%, top:0) position.
      sub.classList.remove('flip-left', 'flip-up');
      const rect = sub.getBoundingClientRect();
      if (rect.width === 0 && rect.height === 0) return;   // not visible yet
      if (rect.right > window.innerWidth - margin) sub.classList.add('flip-left');
      if (rect.bottom > window.innerHeight - margin) sub.classList.add('flip-up');
    };
    root.addEventListener('mouseover', onOver);
    return () => root.removeEventListener('mouseover', onOver);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ref, active, margin, ...deps]);
}
