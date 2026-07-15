/**
 * assigneeLabel — one source of truth for turning an assignee URI into the human
 * DISPLAY NAME shown in the UI.
 *
 * Identity is STORED as a stable id (a session tracking_id, or a project/team
 * id) inside `uai://<kind>/<id>` assignment URIs — but every surface (the Work
 * Mgr list's "Assigned To" grouping, the todo view, filters) should DISPLAY the
 * entity's display name. Display names carry identity continuity across
 * instances (PianoMan); the stored id stays stable underneath.
 *
 * Resolution is best-effort: if the entity isn't loaded/known (e.g. an exited
 * session no longer in the store), we fall back to the bare id rather than show
 * nothing. Reads the module-level store getters, so it works outside a hook —
 * callers just need to re-render when the session/card stores update (the Work
 * Mgr already subscribes to both), and the label re-resolves.
 *
 * Shared by WorkMgrPane (which also re-exports it), TodoListView, and
 * TodoItemView so all three stay in sync — and to avoid a WorkMgrPane <-> child
 * circular import.
 */

import { getSession, getSessions } from '../stores/session-store';
import { getCard } from '../stores/card-store';

/** The canonical, instance-independent form of a session name: strip a leading
 *  "Fork of " so a fork resolves to the identity it continues (todo_0441#5). */
function baseName(name: string): string {
  return name.replace(/^fork of\s+/i, '').trim();
}

/** Resolve a session tracking_id to its CANONICAL display name (todo_0441#5a):
 *  a raw tid pointing at a transient/forked/exited session should still read as
 *  the stable name. Prefer a LIVE session bearing the same base name (identity
 *  continuity across instances); else the tid's own last-known name; else the
 *  bare tid. */
function canonicalSessionName(tid: string): string {
  const own = getSession(tid)?.display_name;
  const base = own ? baseName(own) : '';
  if (base) {
    const live = getSessions().find(
      (s) => s.process_status === 'running' && s.display_name && baseName(s.display_name) === base,
    );
    return live?.display_name || own || tid;
  }
  return tid;
}

export function assigneeLabel(uri: string): string {
  if (!uri) return '?';
  const seg = uri.split('/').filter(Boolean);
  const last = seg[seg.length - 1] || uri;
  if (uri.includes('session/')) return canonicalSessionName(last);
  if (uri.includes('project/')) return getCard(`project:${last}`)?.display_name || last;
  if (uri.includes('team/')) return getCard(`team:${last}`)?.display_name || last;
  return last;
}
