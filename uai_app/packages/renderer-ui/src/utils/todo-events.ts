/**
 * A tiny cross-component signal that a todo's list-facing content changed
 * (title/notes/status/assignment/move/create). The Work Mgr list listens and reloads so its rows —
 * including the one-line description — stay in sync with edits made anywhere,
 * including inside the embedded todo detail view (todo_0555).
 */
export const TODOS_CHANGED = 'uai:todos:changed';

export function notifyTodosChanged(): void {
  try { window.dispatchEvent(new CustomEvent(TODOS_CHANGED)); } catch { /* SSR/no-window */ }
}
