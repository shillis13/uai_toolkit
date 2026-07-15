/**
 * Git File View — scope command channel.
 *
 * The Git File View is embeddable in many places (Session→Work→Files, dashboards,
 * etc.). Wherever it's dropped in, the host may want to DRIVE its scope (which
 * repo/dir + date range it shows) programmatically instead of making the user
 * edit the toolbar — and in fixed embeds the scope bar is hidden entirely.
 *
 * This is the advertised command for that: call `setGitFileViewScope(detail)` and
 * every mounted GitFileViewPane picks it up and reloads. Target one instance with
 * `tabId`, or omit it to broadcast to all mounted views.
 *
 * It's a plain window CustomEvent (no main-process round-trip) because setting the
 * scope of an already-mounted renderer component is a pure UI action.
 */

export const GFV_SET_SCOPE_EVENT = 'uai:gitFileView:setScope';

/**
 * The delta filter — restrict the change set to one contributor / AI session /
 * todo, or (for a worker-scoped view) the UNION of a set of todos. Single-value
 * kinds use `value`; the `todos` kind uses `values` (a worker's todo ids).
 */
export interface GitFileViewFilter {
  kind: 'author' | 'ai' | 'todo' | 'todos';
  value?: string;
  values?: string[];
}

export interface GitFileViewScope {
  /** Target a specific pane instance by its tabId; omit to broadcast to all. */
  tabId?: string;
  /** Repo root or any dir under it (recursively scoped). */
  dir?: string;
  /** ISO date (YYYY-MM-DD) lower bound. */
  since?: string;
  /** ISO date (YYYY-MM-DD) upper bound; '' / undefined = latest. */
  until?: string;
  /**
   * Delta filter. Pass an object to filter by contributor / AI session / todo,
   * or `null` to clear it. Omit the key entirely to leave the filter unchanged.
   */
  filter?: GitFileViewFilter | null;
}

/**
 * The advertised command to set a mounted Git File View's Repo / Dir / Date Range
 * AND its AI-session / todo filter. Dispatches to every mounted view; each applies
 * the fields that are present and reloads. Present-but-null `filter` clears it;
 * an omitted `filter` key leaves it as-is.
 */
export function setGitFileViewScope(detail: GitFileViewScope): void {
  window.dispatchEvent(new CustomEvent<GitFileViewScope>(GFV_SET_SCOPE_EVENT, { detail }));
}
