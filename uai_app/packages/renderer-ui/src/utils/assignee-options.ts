/**
 * assignee-options — reusable builder for the grouped "assign a todo to a worker"
 * option list (Projects · Teams · Active sessions · Stopped sessions). The
 * Add-Note "create todo" dialog is its first consumer (todo_0525).
 *
 * Extracted from the WorkMgrPane/WorkSurface implementation so new consumers
 * use the same ordering/labelling. Those existing inline copies can migrate here
 * after their concurrent edits settle. Sessions are ordered
 * running-before-stopped, and within each, open-tab sessions first (then by name
 * / most-recent activity). Any source may be omitted; that group is simply absent.
 */

export const ASSIGNEE_GROUPS = ['Projects', 'Teams', 'Active sessions', 'Stopped sessions'] as const;
export type AssigneeGroup = (typeof ASSIGNEE_GROUPS)[number];
export interface AssigneeOption { uri: string; label: string; grp: AssigneeGroup }

interface BuildOpts {
  projects?: any[];
  teams?: any[];
  sessions?: any[];
  /** tracking_ids of sessions with an open tab — sorted to the front of each group. */
  openTabIds?: Set<string>;
}

export function buildAssigneeOptions({ projects = [], teams = [], sessions = [], openTabIds }: BuildOpts): AssigneeOption[] {
  const out: AssigneeOption[] = [];
  const byName = (a: any, b: any) => (a.display_name || '').localeCompare(b.display_name || '');
  [...projects].sort(byName).forEach((p: any) =>
    out.push({ uri: `uai://project/${String(p.entity_id).replace(/^project:/, '')}`, label: p.display_name, grp: 'Projects' }));
  [...teams].sort(byName).forEach((t: any) =>
    out.push({ uri: `uai://team/${String(t.entity_id).replace(/^team:/, '')}`, label: t.display_name, grp: 'Teams' }));
  const sess = (sessions || []).filter((s: any) => !s.archived);
  const sLabel = (s: any) => s.display_name || String(s.tracking_id).slice(0, 12);
  const sUri = (s: any) => `uai://session/${s.tracking_id}`;
  const hasTab = (s: any) => !!openTabIds && openTabIds.has(s.tracking_id);
  const running = sess.filter((s: any) => s.process_status === 'running');
  const stopped = sess.filter((s: any) => s.process_status !== 'running');
  [...running.filter(hasTab).sort(byName), ...running.filter((s: any) => !hasTab(s)).sort(byName)]
    .forEach((s: any) => out.push({ uri: sUri(s), label: sLabel(s), grp: 'Active sessions' }));
  [...stopped.filter(hasTab).sort(byName), ...stopped.filter((s: any) => !hasTab(s)).sort((a: any, b: any) => (b.last_activity || '').localeCompare(a.last_activity || ''))]
    .forEach((s: any) => out.push({ uri: sUri(s), label: sLabel(s), grp: 'Stopped sessions' }));
  return out;
}
