/**
 * Global "flatten structured rows on copy" handler.
 *
 * Problem: rows in the Bottom Panel log tabs, search results, etc. render each
 * field as its own element, so the browser's default copy drops a NEWLINE between
 * every field — one logical row becomes N lines (e.g. an error row copies as
 * time / level / source / session / message on five separate lines). Pasting that
 * into the Prompt Box (or anywhere) is a mess.
 *
 * Fix: ONE document-level copy handler (installed once) instead of a per-component
 * handler everywhere. A row opts in with `data-copyrow`. On copy, each selected
 * `[data-copyrow]` becomes a SINGLE line — its visible text with whitespace
 * collapsed to single spaces, i.e. "as it looks in the tab" — and rows are joined
 * by newlines. Selections that touch no `[data-copyrow]` are left to the browser's
 * default copy, so nothing else in the app is affected.
 */
export function installCopyFlatten(): () => void {
  const onCopy = (e: ClipboardEvent) => {
    const sel = window.getSelection();
    if (!sel || sel.rangeCount === 0 || sel.isCollapsed) return;

    // Rows (partially or fully) inside the selection.
    const rows = Array.from(document.querySelectorAll<HTMLElement>('[data-copyrow]'))
      .filter((r) => sel.containsNode(r, true));
    if (rows.length === 0) return; // not our structured content → default copy

    const text = rows
      .map((r) => (r.textContent || '').replace(/\s+/g, ' ').trim())
      .filter(Boolean)
      .join('\n');
    if (!text) return;

    e.clipboardData?.setData('text/plain', text);
    e.preventDefault();
  };

  document.addEventListener('copy', onCopy);
  return () => document.removeEventListener('copy', onCopy);
}
