/**
 * work-scope — scope the global todo set down to ONE worker (session / team /
 * project), for the worker Tab's Work aspect (todo_0544 A1).
 *
 * The worker Tab reuses the SAME rendering as the global Work Mgr (WorkSurface →
 * TodoListView), but fed a NARROWER todo set. This module owns that narrowing:
 * given a WorkScope descriptor and the full todo list, return the subset that
 * belongs to the worker.
 *
 * Assignee shapes (from assigned.yml, confirmed against real data):
 *   - session:  `uai://session/<tracking_id>`   (bare `<tracking_id>` tolerated)
 *   - team:     `uai://team/<id>`
 *   - project:  `uai://project/<id>`  (older todos also carry a `project` field)
 *
 * Scoping rules (per the ticket):
 *   - session  → todos assigned to this session.
 *   - team     → UNION: todos assigned to the team URI OR to any member session.
 *   - project  → todos assigned to the project URI (or `project` field) OR — like
 *                team — to any member session.
 */

import type { WorkItem } from './WorkMgrPane';

export type WorkScope =
  | { kind: 'session'; trackingId: string }
  | { kind: 'team'; id: string; memberTrackingIds?: string[] }
  | { kind: 'project'; id: string; memberTrackingIds?: string[] };

/** True when a todo is assigned to the given session (canonical URI or bare id). */
export function assignedToSession(t: WorkItem, trackingId: string): boolean {
  if (!trackingId) return false;
  const a = t.assigned || [];
  return a.includes(`uai://session/${trackingId}`) || a.includes(trackingId);
}

/** Narrow a full todo list to the ones belonging to `scope`. Pure — no I/O. */
export function scopeTodos(scope: WorkScope, todos: WorkItem[]): WorkItem[] {
  const list = todos || [];
  if (scope.kind === 'session') {
    return list.filter(t => assignedToSession(t, scope.trackingId));
  }
  if (scope.kind === 'team') {
    const teamUri = `uai://team/${scope.id}`;
    const members = scope.memberTrackingIds || [];
    return list.filter(t => {
      const a = t.assigned || [];
      if (a.includes(teamUri)) return true;
      return members.some(m => assignedToSession(t, m));
    });
  }
  // project — mirror the team union for its member sessions, plus the legacy
  // `project` field that pre-dates the assigned-URI scheme.
  const projUri = `uai://project/${scope.id}`;
  const members = scope.memberTrackingIds || [];
  return list.filter(t => {
    const a = t.assigned || [];
    if (a.includes(projUri)) return true;
    if ((t as { project?: string | null }).project === scope.id) return true;
    return members.some(m => assignedToSession(t, m));
  });
}

/**
 * Fetch the full todo set from `window.uai.todos.list(...)` and scope it. The
 * ticket's canonical entry point ("return its todo set from
 * window.uai.todos.list(false)"). `wantFinalized` surfaces Done/Cancelled todos
 * (the engine hides them by default) so a status filter can reveal them.
 */
export async function loadScopedTodos(scope: WorkScope, wantFinalized = false): Promise<WorkItem[]> {
  const rows = (await window.uai.todos.list(wantFinalized)) as WorkItem[];
  const norm = rows.map(t => ({ ...t, assigned: t.assigned || [], tags: t.tags || [], flags: t.flags || [] }));
  return scopeTodos(scope, norm);
}
