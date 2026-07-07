/**
 * showContextMenu — shared right-click menu, matching the TranscriptViewer
 * pattern (same `.tv-context-menu` / `.tv-context-item` styling) so the Comms
 * and Prompts panels behave like the rest of the app. Builds a floating menu at
 * the cursor; dismisses on outside click / Escape / next right-click.
 */
export interface ContextMenuItem {
  label: string;
  action: () => void;
  danger?: boolean;
  disabled?: boolean;
}

export function showContextMenu(
  e: { clientX: number; clientY: number; preventDefault: () => void; stopPropagation: () => void },
  items: ContextMenuItem[],
): void {
  e.preventDefault();
  e.stopPropagation();

  const menu = document.createElement('div');
  menu.className = 'tv-context-menu';
  menu.style.left = `${e.clientX}px`;
  menu.style.top = `${e.clientY}px`;

  const cleanup = () => {
    menu.remove();
    document.removeEventListener('mousedown', onDown, true);
    document.removeEventListener('keydown', onKey, true);
    window.removeEventListener('contextmenu', onDown, true);
  };
  const onDown = (ev: Event) => {
    if (menu.contains(ev.target as Node)) return;
    ev.preventDefault();
    ev.stopPropagation();
    cleanup();
  };
  const onKey = (ev: KeyboardEvent) => { if (ev.key === 'Escape') cleanup(); };

  for (const item of items) {
    const el = document.createElement('div');
    el.className = `tv-context-item${item.danger ? ' tv-context-item-danger' : ''}${item.disabled ? ' tv-context-item-disabled' : ''}`;
    el.textContent = item.label;
    if (!item.disabled) {
      el.addEventListener('click', () => { cleanup(); item.action(); });
    }
    menu.appendChild(el);
  }

  document.body.appendChild(menu);
  // Keep the menu on-screen.
  const rect = menu.getBoundingClientRect();
  if (rect.right > window.innerWidth) menu.style.left = `${window.innerWidth - rect.width - 4}px`;
  if (rect.bottom > window.innerHeight) menu.style.top = `${window.innerHeight - rect.height - 4}px`;

  setTimeout(() => {
    document.addEventListener('mousedown', onDown, true);
    document.addEventListener('keydown', onKey, true);
    window.addEventListener('contextmenu', onDown, true);
  }, 0);
}
