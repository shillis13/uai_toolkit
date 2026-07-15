/**
 * useTodoListModel — grouping / tree model for the Work Mgr todo list.
 *
 * Pure data hook: given the raw todos plus the host's filter predicate
 * (`matches`) and sort comparator (`cmp`), it computes every derived collection
 * the TodoListView needs to render the flat / tree / kanban / assignee views —
 * the by-key index, the filtered+sorted list, the flat status groups, the
 * assignee groups, and the parent/child tree relations.
 *
 * Extracted verbatim from WorkMgrPane so the list can live in its own
 * encapsulated component (and be dropped into other hosts). The host still owns
 * `matches`/`cmp` (they depend on its toolbar state) and passes them in.
 */

import { useMemo, useCallback } from 'react';
import type { WorkItem } from './WorkMgrPane';
import { NO_ASSIGNEE, STATUS_ORDER, assigneeLabel } from './WorkMgrPane';

export interface TodoListModel {
  filtered: WorkItem[];
  byKey: Map<string, WorkItem>;
  childrenOf: Map<string, WorkItem[]>;
  rootItems: WorkItem[];
  groups: Record<string, WorkItem[]>;
  sortedGroupKeys: string[];
  assigneeGroups: Record<string, WorkItem[]>;
  assigneeGroupKeys: string[];
  subtreeMatches: (t: WorkItem) => boolean;
}

export function useTodoListModel(
  todos: WorkItem[],
  matches: (t: WorkItem) => boolean,
  cmp: (a: WorkItem, b: WorkItem) => number,
): TodoListModel {
  const byKey = useMemo(() => { const m = new Map<string, WorkItem>(); for (const t of todos) m.set(t.rel_path || t.id, t); return m; }, [todos]);

  const filtered = useMemo(() => todos.filter(matches).sort(cmp), [todos, matches, cmp]);

  // flat grouping — groupMode is fixed to 'status' in the Work Mgr (Kanban groups by status).
  const groups = useMemo(() => {
    const map: Record<string, WorkItem[]> = {};
    for (const t of filtered) (map[t.status] ||= []).push(t);
    return map;
  }, [filtered]);
  const sortedGroupKeys = useMemo(
    () => Object.keys(groups).sort((a, b) => (STATUS_ORDER[a] ?? 99) - (STATUS_ORDER[b] ?? 99)),
    [groups],
  );

  // By-Assigned-To view (#3): Kanban-style, but each group is an assignee
  // (project / team / session) rather than a status.
  const assigneeGroups = useMemo(() => {
    const map: Record<string, WorkItem[]> = {};
    for (const t of filtered) {
      const keys = t.assigned.length ? t.assigned : [NO_ASSIGNEE];
      for (const k of keys) (map[k] ||= []).push(t);
    }
    return map;
  }, [filtered]);
  const assigneeGroupKeys = useMemo(() => Object.keys(assigneeGroups).sort((a, b) => {
    if (a === NO_ASSIGNEE) return 1; if (b === NO_ASSIGNEE) return -1;
    return assigneeLabel(a).localeCompare(assigneeLabel(b));
  }), [assigneeGroups]);

  // tree (#9: hierarchy priority — finalized nodes sit under parent when shown)
  const childrenOf = useMemo(() => {
    const m = new Map<string, WorkItem[]>();
    for (const t of todos) { const pk = t.parent || '__root__'; (m.get(pk) || m.set(pk, []).get(pk)!).push(t); }
    for (const arr of m.values()) arr.sort(cmp);
    return m;
  }, [todos, cmp]);
  const rootItems = useMemo(() => todos.filter(t => !t.parent || !byKey.has(t.parent)).sort(cmp), [todos, byKey, cmp]);
  const subtreeMatches = useCallback((t: WorkItem): boolean => {
    if (matches(t)) return true;
    return (childrenOf.get(t.rel_path || t.id) || []).some(subtreeMatches);
  }, [matches, childrenOf]);

  return { filtered, byKey, childrenOf, rootItems, groups, sortedGroupKeys, assigneeGroups, assigneeGroupKeys, subtreeMatches };
}
