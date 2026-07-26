/**
 * parent-options.tsx — the SHARED "choose a parent" <option> list (todo_0609).
 *
 * PM: "the two drop-downs are not the same and they should be." The todo-editor's
 * re-parent dropdown built a hierarchical, indented tree while the bulk panel's
 * Move-under-parent built a flat list — so they looked different. This is the single
 * source both now render, guaranteeing identical options everywhere a parent is
 * picked (WorkMgrPane + WorkSurface editors, TodoBulkPanel).
 *
 * Mirrors utils/assignee-options.ts (Hardy's shared assignee-option builder).
 *
 * The tree is computed here from each todo's `parent` field so callers only pass the
 * flat todo list + the ids that can't be a parent (a todo can't parent itself, nor
 * the current selection — and never a descendant of an excluded node, which would make
 * a cycle, so an excluded node's whole subtree is omitted).
 */

import type { WorkItem } from '../components/WorkMgrPane';

// Do not import these runtime helpers from WorkMgrPane: WorkMgrPane renders
// ParentPicker, so doing so creates WorkMgrPane -> ParentPicker -> this module ->
// WorkMgrPane and can crash the renderer during module evaluation.
function todoNum(id: string): string {
  const match = (id || '').match(/(?:todo|task)_(\d+)/);
  return match ? match[1] : id;
}

function formatTitle(item: WorkItem): string {
  const raw = item.title?.trim() || item.id || '';
  return raw.replace(/^(?:todo|task)_\d+_?/, '').replace(/_/g, ' ').trim();
}

export function buildParentOptions(todos: WorkItem[], excludeIds: Set<string>): JSX.Element[] {
  // todo_mgr's `parent` points at the parent's RELATIVE PATH, not its short
  // `id` (e.g. parent="todo_0587_uai_app" while id="todo_0587"). Keying by
  // id flattens the entire real hierarchy because no parent reference matches.
  const keyOf = (todo: WorkItem): string => todo.rel_path || todo.id;
  const keys = new Set(todos.map(keyOf));
  const childrenOf = new Map<string, WorkItem[]>();
  for (const t of todos) {
    // A parent ref that isn't in the set is treated as a root (top-level) item.
    const key = t.parent && keys.has(t.parent) ? t.parent : '';
    const bucket = childrenOf.get(key);
    if (bucket) bucket.push(t);
    else childrenOf.set(key, [t]);
  }
  // Stable, numeric order within each level so the list is deterministic.
  for (const bucket of childrenOf.values()) {
    bucket.sort((a, b) => todoNum(a.id).localeCompare(todoNum(b.id), undefined, { numeric: true }));
  }

  const out: JSX.Element[] = [];
  const walk = (items: WorkItem[], depth: number): void => {
    for (const t of items) {
      // Excluded → skip it AND its subtree (can't re-parent under self/a descendant).
      if (excludeIds.has(t.id) || excludeIds.has(keyOf(t))) continue;
      out.push(
        // Indent each level relative to its immediate parent (todo_0648). Native
        // <option> COLLAPSES ordinary leading spaces, so use non-breaking spaces
        // ( ) — the standard way to make select-option indentation actually
        // render — two per depth level, plus a └ connector for child rows.
        <option key={t.id} value={t.id}>
          {'\u00A0\u00A0'.repeat(depth)}{depth > 0 ? '└ ' : ''}todo_{todoNum(t.id)} · {formatTitle(t).slice(0, 36)}
        </option>,
      );
      walk(childrenOf.get(keyOf(t)) || [], depth + 1);
    }
  };
  walk(childrenOf.get('') || [], 0);
  return out;
}
