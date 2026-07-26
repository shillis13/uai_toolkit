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

import { useState, useRef, useEffect } from 'react';
import type { ReactNode } from 'react';
import { useViewport } from '../viewport';
import type { TodoListModel } from './useTodoListModel';
import {
  StatusCode, TodoId, PriorityChip, effectivePriority, statusColor, statusLabel, assigneeLabel, formatTitle, todoNum,
  highlight, itemDate, fmtDate, fmtTs, NO_ASSIGNEE, TREE_GROUP_COLORS,
} from './WorkMgrPane';
import type { WorkItem, ViewMode } from './WorkMgrPane';

interface TodoListViewProps {
  model: TodoListModel;
  viewMode: ViewMode;
  selectedId: string | null;
  onSelect: (id: string) => void;
  // Multi-select is host-owned (todo_0558) so the detail pane can show bulk actions.
  selIds: Set<string>;
  onSelIdsChange: (s: Set<string>) => void;
  // Bulk drag-drop targets (todo_0411). ids = the dragged selection (1+).
  onReparent: (ids: string[], targetId: string) => void;   // drop onto a todo → make children
  onSetStatus: (ids: string[], status: string) => void;    // drop onto a kanban status section
  onReassign: (ids: string[], uri: string) => void;        // drop onto an assignee section
  matches: (t: WorkItem) => boolean;
  isFiltering: boolean;
  search: string;
  kanbanNest: boolean;
  busy?: string | null;
  loading?: boolean;
  error?: string | null;
  collapsedGroups: Set<string>;
  toggleGroup: (k: string) => void;
  collapsedNodes: Set<string>;
  toggleNode: (k: string) => void;
  density?: 'compact' | 'expanded';   // list row density (todo_0556)
  viewportId?: string;
  listWidthPx?: number;
}

export default function TodoListView({
  model, viewMode, selectedId, onSelect, selIds, onSelIdsChange, onReparent, onSetStatus, onReassign, matches, isFiltering, search,
  kanbanNest, busy, loading, error, collapsedGroups, toggleGroup, collapsedNodes, toggleNode,
  density = 'compact', viewportId = 'todo_list_view', listWidthPx,
}: TodoListViewProps): JSX.Element {
  const { byKey, childrenOf, subtreeMatches, filtered, rootItems, groups, sortedGroupKeys, assigneeGroups, assigneeGroupKeys } = model;

  // drag-to-reparent: dragOverId = row drop target being hovered.
  const [dragOverId, setDragOverId] = useState<string | null>(null);
  // dragIds = the drag payload (the selection if the dragged row is in it, else just
  // that row); dragOverSection = the status/assignee section hovered as a drop target.
  const [dragIds, setDragIds] = useState<string[]>([]);
  const [dragOverSection, setDragOverSection] = useState<string | null>(null);
  const lastClickRef = useRef<string | null>(null);
  // Reveal the opened todo: scroll the selected row to the middle of the list
  // when the selection changes (e.g. opening a todo from a link) (todo_0624).
  const selectedRowRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (selectedId && selectedRowRef.current) {
      selectedRowRef.current.scrollIntoView({ block: 'center', behavior: 'smooth' });
    }
  // `filtered` is also a dependency because a finalized todo opened from a link
  // can be selected before the follow-up fetch makes its row available.
  }, [selectedId, filtered]);
  // Actual on-screen row order, captured as rows render (todo_0589). Shift-click
  // ranges must follow VIEW order, not the flat `filtered` list — in tree/kanban
  // the rendered order differs, so a flat-order range selected wrong rows.
  const renderOrderRef = useRef<string[]>([]);
  renderOrderRef.current = [];
  const endDrag = () => { setDragOverId(null); setDragIds([]); setDragOverSection(null); };
  // A row reads as SELECTED (same look as single-select, like the Tab Mgr) when it's
  // the primary detail selection OR part of the multi-select set (todo_0558).
  const isSelected = (id: string) => selectedId === id || selIds.has(id);

  // Click selection: plain = single-select (opens detail, clears multi); Cmd/Ctrl =
  // toggle into the set (seeded with the open row); Shift = range in the sort order.
  const handleRowClick = (e: React.MouseEvent, id: string) => {
    if (e.metaKey || e.ctrlKey) {
      const n = new Set(selIds);
      if (n.size === 0 && selectedId && selectedId !== id) n.add(selectedId);
      if (n.has(id)) n.delete(id); else n.add(id);
      onSelIdsChange(n);
      lastClickRef.current = id;
    } else if (e.shiftKey && (lastClickRef.current || selectedId)) {
      const anchor = lastClickRef.current || selectedId!;
      // Range follows the actual on-screen order (dedup guards kanban's dimmed
      // context rows), not the flat sorted list (todo_0589).
      const order = [...new Set(renderOrderRef.current)];
      const a = order.indexOf(anchor), b = order.indexOf(id);
      if (a >= 0 && b >= 0) { const [lo, hi] = a < b ? [a, b] : [b, a]; onSelIdsChange(new Set(order.slice(lo, hi + 1))); }
    } else {
      onSelIdsChange(new Set()); lastClickRef.current = id; onSelect(id);
    }
  };
  // On drag start, the payload is the whole selection when the dragged row is part
  // of a multi-select; otherwise just that one row.
  const startRowDrag = (id: string) => {
    const ids = selIds.has(id) && selIds.size > 1 ? [...selIds] : [id];
    setDragIds(ids);
  };

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
    renderOrderRef.current.push(t.id);   // record on-screen order for shift-range (todo_0589)
    return (
      <div key={key}
        ref={t.id === selectedId ? selectedRowRef : undefined}
        className={`wm-row ${density === 'expanded' ? 'wm-row-exp' : ''} ${isSelected(t.id) ? 'selected' : ''} ${dragOverId === t.id && !dragIds.includes(t.id) ? 'drop-target' : ''} ${dimmed ? 'wm-dimmed' : ''}`}
        draggable
        onClick={e => handleRowClick(e, t.id)}
        onDragStart={e => { e.stopPropagation(); startRowDrag(t.id); e.dataTransfer.effectAllowed = 'move'; }}
        onDragOver={e => { if (dragIds.length && !dragIds.includes(t.id)) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (dragOverId !== t.id) setDragOverId(t.id); } }}
        onDragLeave={() => { if (dragOverId === t.id) setDragOverId(null); }}
        onDrop={e => { e.preventDefault(); e.stopPropagation(); if (dragIds.length && !dragIds.includes(t.id)) { onReparent(dragIds, t.id); onSelIdsChange(new Set()); } endDrag(); }}
        onDragEnd={endDrag}
        title={rowTip(t)}
        style={{ paddingLeft: 4 + depth * 14, opacity: busy === t.id ? 0.5 : (dragIds.includes(t.id) ? 0.4 : 1) }}>
        <div className="wm-row-line1">
          {viewMode === 'tree' && (
            <span className="wm-caret" onClick={e => { e.stopPropagation(); if (hasKids) toggleNode(key); }}
              style={{ cursor: hasKids ? 'pointer' : 'default' }}>{hasKids ? (expanded ? '▾' : '▸') : ''}</span>
          )}
          {/* status code redundant in Kanban (the section is the status) */}
          {viewMode !== 'kanban' && <StatusCode status={t.status} />}
          <TodoId id={t.id} />
          <PriorityChip priority={effectivePriority(t)} />
          <span className="wm-title">{highlight(formatTitle(t), search)}</span>
          <span className="wm-row-meta">
            {d && <span className="wm-date" title={`updated ${fmtTs(d)}`}>{fmtDate(d)}</span>}
          </span>
        </div>
        {/* Expanded: a second line with summary + assignee(s) + tags (todo_0556). */}
        {density === 'expanded' && (() => {
          const summ = (t.summary || '').replace(/<!--[\s\S]*?-->/g, '').trim();
          const asg = (t.assigned || []).map(assigneeLabel).filter(Boolean);
          if (!summ && !asg.length && !t.tags.length) return null;
          return (
            <div className="wm-row-line2">
              {summ && <span className="wm-row-summary">{summ}</span>}
              {asg.length > 0 && <span className="wm-row-asg">{asg.join(', ')}</span>}
              {t.tags.length > 0 && <span className="wm-row-tags">{t.tags.map(x => `#${x}`).join(' ')}</span>}
            </div>
          );
        })()}
      </div>
    );
  };
  const renderTreeNode = (t: WorkItem, depth: number): JSX.Element[] => {
    const key = t.rel_path || t.id;
    const kids = (childrenOf.get(key) || []).filter(subtreeMatches);
    const hasKids = kids.length > 0;
    // Parents are expanded by default; the user collapses them into collapsedNodes.
    // Under an active filter, force-expand parents with matching children so the
    // matches are revealed (and dim a parent shown only to reveal a descendant).
    const expanded = !collapsedNodes.has(key) || (isFiltering && hasKids);
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
        const over = dragOverSection === `status:${key}`;
        return (
          <div key={key} className={`wm-kan-section ${over ? 'wm-section-drop' : ''}`} style={{ borderColor: col }}
            onDragOver={e => { if (dragIds.length) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (!over) setDragOverSection(`status:${key}`); } }}
            onDragLeave={e => { if ((e.currentTarget as HTMLElement).contains(e.relatedTarget as Node | null)) return; if (over) setDragOverSection(null); }}
            onDrop={e => { e.preventDefault(); if (dragIds.length) { onSetStatus(dragIds, key); onSelIdsChange(new Set()); } endDrag(); }}>
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
        // (unassigned) isn't an assignable target — you can't "assign to nobody".
        const canDrop = key !== NO_ASSIGNEE;
        const over = dragOverSection === `assignee:${key}`;
        return (
          <div key={key} className={`wm-kan-section ${over ? 'wm-section-drop' : ''}`} style={{ borderColor: col }}
            onDragOver={canDrop ? (e => { if (dragIds.length) { e.preventDefault(); e.dataTransfer.dropEffect = 'move'; if (!over) setDragOverSection(`assignee:${key}`); } }) : undefined}
            onDragLeave={canDrop ? (e => { if ((e.currentTarget as HTMLElement).contains(e.relatedTarget as Node | null)) return; if (over) setDragOverSection(null); }) : undefined}
            onDrop={canDrop ? (e => { e.preventDefault(); if (dragIds.length) { onReassign(dragIds, key); onSelIdsChange(new Set()); } endDrag(); }) : undefined}>
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
