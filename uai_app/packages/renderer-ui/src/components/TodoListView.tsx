/**
 * TodoListView — the encapsulated Work Mgr todo LIST (flat / tree / kanban /
 * assignee views), extracted from WorkMgrPane so it can be dropped into other
 * hosts as an independent instance.
 *
 * The host computes the grouping/tree model via `useTodoListModel` and passes it
 * in, along with its filter predicate (`matches`), the derived `isFiltering`
 * flag, and the selection / drag / collapse callbacks. This component owns only
 * its OWN drag state (dragId/dragOverId); collapse/expand state is host-owned
 * (it's persisted across tab switches in WorkMgrPane's wmCache) and passed down.
 *
 * Behavior is preserved EXACTLY from the original inline list: same view modes,
 * drag-to-reparent, tree carets + auto-expand under filter, kanban nest, dimmed
 * ancestors, selection highlight, and empty state. Pure refactor — no style or
 * className changes.
 */

import { useState } from 'react';
import type { ReactNode } from 'react';
import { useViewport } from '../viewport';
import type { TodoListModel } from './useTodoListModel';
import {
  StatusCode, TodoId, statusColor, statusLabel, assigneeLabel, formatTitle, todoNum,
  highlight, itemDate, fmtDate, fmtTs, NO_ASSIGNEE, TREE_GROUP_COLORS,
} from './WorkMgrPane';
import type { WorkItem, ViewMode } from './WorkMgrPane';

interface TodoListViewProps {
  model: TodoListModel;
  viewMode: ViewMode;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onMove: (dragId: string, targetId: string) => void;   // targetId is another todo id
  matches: (t: WorkItem) => boolean;
  isFiltering: boolean;
  search: string;
  kanbanNest: boolean;
  busy?: string | null;
  loading?: boolean;
  error?: string | null;
  collapsedGroups: Set<string>;
  toggleGroup: (k: string) => void;
  expandedNodes: Set<string>;
  toggleNode: (k: string) => void;
  viewportId?: string;
  listWidthPx?: number;
}

export default function TodoListView({
  model, viewMode, selectedId, onSelect, onMove, matches, isFiltering, search,
  kanbanNest, busy, loading, error, collapsedGroups, toggleGroup, expandedNodes, toggleNode,
  viewportId = 'todo_list_view', listWidthPx,
}: TodoListViewProps): JSX.Element {
  const { byKey, childrenOf, subtreeMatches, filtered, rootItems, groups, sortedGroupKeys, assigneeGroups, assigneeGroupKeys } = model;

  // drag-to-reparent: dragId = row being dragged; dragOverId = current drop target.
  const [dragId, setDragId] = useState<string | null>(null);
  const [dragOverId, setDragOverId] = useState<string | null>(null);

  const assigneeColor = (uri: string): string => {
    const pal = ['var(--accent-cyan)', 'var(--accent-green)', 'var(--accent-purple)', 'var(--accent-blue)', 'var(--accent-orange)', 'var(--accent-yellow)'];
    let h = 0; for (let i = 0; i < uri.length; i++) h = (h * 31 + uri.charCodeAt(i)) >>> 0;
    return pal[h % pal.length];
  };

  // tooltip = info ABOUT the todo (#7), not instructions
  const rowTip = (t: WorkItem): string => {
    const d = itemDate(t);
    return [
      t.id,
      `status: ${statusLabel(t.status)}`,
      t.assigned.length ? `assigned: ${t.assigned.map(assigneeLabel).join(', ')}` : 'unassigned',
      d ? `updated: ${fmtTs(d)}` : '',
      formatTitle(t),
    ].filter(Boolean).join('\n');
  };
  // ── row (shared) ────────────────────────────────────────────────────────────
  const renderRow = (t: WorkItem, depth: number, hasKids: boolean, expanded: boolean, dimmed = false): JSX.Element => {
    const key = t.rel_path || t.id;
    const d = itemDate(t);
    return (
      <div key={key}
        className={`wm-row ${selectedId === t.id ? 'selected' : ''} ${dragOverId === t.id && dragId !== t.id ? 'drop-target' : ''} ${dimmed ? 'wm-dimmed' : ''}`}
        draggable
        onClick={() => onSelect(t.id)}
        onDragStart={e => { e.stopPropagation(); setDragId(t.id); e.dataTransfer.effectAllowed = 'move'; }}
        onDragOver={e => { if (dragId && dragId !== t.id) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (dragOverId !== t.id) setDragOverId(t.id); } }}
        onDragLeave={() => { if (dragOverId === t.id) setDragOverId(null); }}
        onDrop={e => { e.preventDefault(); e.stopPropagation(); if (dragId && dragId !== t.id) onMove(dragId, t.id); setDragId(null); setDragOverId(null); }}
        onDragEnd={() => { setDragId(null); setDragOverId(null); }}
        title={rowTip(t)}
        style={{ paddingLeft: 4 + depth * 14, opacity: busy === t.id ? 0.5 : (dragId === t.id ? 0.4 : 1) }}>
        {viewMode === 'tree' && (
          <span className="wm-caret" onClick={e => { e.stopPropagation(); if (hasKids) toggleNode(key); }}
            style={{ cursor: hasKids ? 'pointer' : 'default' }}>{hasKids ? (expanded ? '▾' : '▸') : ''}</span>
        )}
        {/* status code redundant in Kanban (the section is the status) */}
        {viewMode !== 'kanban' && <StatusCode status={t.status} />}
        <TodoId id={t.id} />
        <span className="wm-title">{highlight(formatTitle(t), search)}</span>
        <span className="wm-row-meta">
          {t.flags.includes('high_priority') && <span className="todo-mgr-flag-badge" title="High Priority">!</span>}
          {d && <span className="wm-date" title={`updated ${fmtTs(d)}`}>{fmtDate(d)}</span>}
        </span>
      </div>
    );
  };
  const renderTreeNode = (t: WorkItem, depth: number): JSX.Element[] => {
    const key = t.rel_path || t.id;
    const kids = (childrenOf.get(key) || []).filter(subtreeMatches);
    const hasKids = kids.length > 0;
    // #3: under an active filter, auto-expand parents with matching children, and
    // dim a parent that's only shown to reveal a matching descendant.
    const expanded = expandedNodes.has(key) || (isFiltering && hasKids);
    const dimmed = isFiltering && !matches(t);
    const out = [renderRow(t, depth, hasKids, expanded, dimmed)];
    if (hasKids && expanded) for (const k of kids) out.push(...renderTreeNode(k, depth + 1));
    return out;
  };

  // Kanban "Nest": within a status section, group items under their parent. The
  // parent is shown DIMMED as context (it may live in a different status section);
  // roots render normally. (#kanban list-2.3)
  const renderKanbanNested = (items: WorkItem[]): JSX.Element => {
    const byParent = new Map<string, WorkItem[]>();
    for (const t of items) { const pk = t.parent || '__none__'; (byParent.get(pk) || byParent.set(pk, []).get(pk)!).push(t); }
    const blocks: JSX.Element[] = [];
    for (const [pk, kids] of byParent) {
      if (pk === '__none__') { for (const t of kids) blocks.push(renderRow(t, 0, false, false)); continue; }
      const parent = byKey.get(pk);
      blocks.push(
        <div key={`ctx-${pk}`} className="wm-kan-parentctx" onClick={() => parent && onSelect(parent.id)} title="parent (context — may be in another status)">
          ↳ {parent ? `todo_${todoNum(parent.id)} · ${formatTitle(parent).slice(0, 44)}` : pk}
        </div>
      );
      for (const t of kids) blocks.push(renderRow(t, 1, false, false));
    }
    return <div className="wm-kan-items">{blocks}</div>;
  };

  useViewport(viewportId, () => ({
    visible: true,
    label: 'Todo List',
    state: { viewMode, count: filtered.length, selectedId },
    children: [],
  }));

  return (
    <div className="wm-list" style={listWidthPx !== undefined ? { width: `${listWidthPx}px` } : undefined}>
      {loading && <div className="traits-mgr-loading" style={{ padding: 16 }}>Loading...</div>}
      {/* Flat — plain sorted list, no hierarchy */}
      {!loading && viewMode === 'flat' && filtered.map(t => renderRow(t, 0, false, false))}
      {/* Tree — real hierarchy. Parent-child clusters get an outlined/colored
          group box (like Kanban/Assigned sections); standalone roots render plain. */}
      {!loading && viewMode === 'tree' && (() => {
        const roots = rootItems.filter(subtreeMatches);
        const out: ReactNode[] = []; let gi = 0;
        for (const t of roots) {
          const key = t.rel_path || t.id;
          const kids = (childrenOf.get(key) || []).filter(subtreeMatches);
          const nodes = renderTreeNode(t, 0);
          if (kids.length === 0) { out.push(...nodes); }
          else {
            const col = TREE_GROUP_COLORS[gi++ % TREE_GROUP_COLORS.length];
            out.push(<div key={`grp-${key}`} className="wm-kan-section wm-tree-group" style={{ borderColor: col }}>{nodes}</div>);
          }
        }
        return out;
      })()}
      {/* Kanban — status sections (colored header, border, light bg) */}
      {!loading && viewMode === 'kanban' && sortedGroupKeys.map(key => {
        const items = groups[key];
        const collapsed = collapsedGroups.has(key);
        const col = statusColor(key);
        return (
          <div key={key} className="wm-kan-section" style={{ borderColor: col }}>
            <div className="wm-kan-header" onClick={() => toggleGroup(key)}
              style={{ background: `color-mix(in srgb, ${col} 14%, transparent)`, borderBottomColor: col }}>
              <span className="wm-kan-chev" style={{ color: col }}>{collapsed ? '▸' : '▾'}</span>
              <span className="wm-kan-title" style={{ color: col }}>{statusLabel(key)} <span className="wm-kan-count">({items.length})</span></span>
            </div>
            {!collapsed && (kanbanNest ? renderKanbanNested(items) : <div className="wm-kan-items">{items.map(t => renderRow(t, 0, false, false))}</div>)}
          </div>
        );
      })}
      {/* By Assigned To — Kanban-style, each section is a project/team/session (#3) */}
      {!loading && viewMode === 'assignee' && assigneeGroupKeys.map(key => {
        const items = assigneeGroups[key];
        const collapsed = collapsedGroups.has(key);
        const col = key === NO_ASSIGNEE ? 'var(--text-muted)' : assigneeColor(key);
        const label = key === NO_ASSIGNEE ? '(unassigned)' : assigneeLabel(key);
        return (
          <div key={key} className="wm-kan-section" style={{ borderColor: col }}>
            <div className="wm-kan-header" onClick={() => toggleGroup(key)}
              style={{ background: `color-mix(in srgb, ${col} 14%, transparent)`, borderBottomColor: col }}>
              <span className="wm-kan-chev" style={{ color: col }}>{collapsed ? '▸' : '▾'}</span>
              <span className="wm-kan-title" style={{ color: col }} title={key}>{label} <span className="wm-kan-count">({items.length})</span></span>
            </div>
            {!collapsed && <div className="wm-kan-items">{items.map(t => renderRow(t, 0, false, false))}</div>}
          </div>
        );
      })}
      {!loading && filtered.length === 0 && !error && <div className="traits-mgr-empty">No work items match.</div>}
    </div>
  );
}
