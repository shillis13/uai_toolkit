/**
 * CaptureComponentPicker — a pull-out drawer for the Add Note dialog that lets
 * you drill down the LIVE component tree and multi-select exactly the UI pieces
 * you want to capture, instead of grabbing the whole app and ✕-ing the rest.
 *
 * Docks to the right edge of the dialog. On open it snapshots the live viewport
 * tree (via the getTree prop). Each node has a checkbox + an expand/collapse
 * chevron. "Add selected" hands back the checked subtrees, which the dialog
 * appends to its capture list (same trim UI as a full capture). Checking a node
 * captures that node AND its subtree; if both an ancestor and a descendant are
 * checked, only the ancestor's subtree is added (the descendant is already in it).
 */

import { useState, useEffect, useRef } from 'react';
import type { ViewportNode } from '@contracts/viewport';

export interface PickerTheme {
  panel: string;
  border: string;
  text: string;
  textDim: string;
  accentText: string;
}

interface Props {
  open: boolean;
  theme: PickerTheme;
  /** Snapshot the current live tree (already visibility-pruned). Called on open. */
  getTree: () => ViewportNode;
  onAdd: (nodes: ViewportNode[]) => void;
  onClose: () => void;
}

const pathKey = (p: number[]) => p.join('.');

// Each nesting LAYER gets its own accent so the tree reads as colored strata —
// matches the capture outline in NoteDialog.
const LAYER_COLORS = [
  'var(--accent-blue)', 'var(--accent-green)', 'var(--accent-yellow)',
  'var(--accent-purple)', 'var(--accent-cyan)', 'var(--accent-orange)',
];

/** Resolve the subtree at a path (array of child indices). */
function nodeAt(root: ViewportNode, path: number[]): ViewportNode | null {
  let n: ViewportNode = root;
  for (const i of path) {
    if (!n.children[i]) return null;
    n = n.children[i];
  }
  return n;
}

export default function CaptureComponentPicker({ open, theme, getTree, onAdd, onClose }: Props): JSX.Element | null {
  const [tree, setTree] = useState<ViewportNode | null>(null);
  const [checked, setChecked] = useState<Set<string>>(new Set());
  // Start with everything expanded a couple levels deep so the drill-down is
  // immediately visible; deeper levels collapse until opened.
  const [expanded, setExpanded] = useState<Set<string>>(new Set());

  // Snapshot the live tree ONCE, on the open→true edge only. getTree is read via a
  // ref so an unstable prop (NoteDialog recreates it each render) can't re-fire this
  // effect mid-session — re-snapshotting would reset the user's expand/check state
  // and re-collapse nested nodes, making components "disappear" off the list.
  const getTreeRef = useRef(getTree); getTreeRef.current = getTree;
  useEffect(() => {
    if (!open) return;
    let t: ViewportNode | null = null;
    try { t = getTreeRef.current(); } catch { t = null; }
    setTree(t);
    setChecked(new Set());
    // Auto-expand every node with children down a few levels so nested capturable
    // pieces (e.g. a tab's panes) are visible from the start, not buried.
    const exp = new Set<string>();
    const expandDeep = (node: ViewportNode, path: number[], depth: number) => {
      if (node.children.length === 0) return;
      exp.add(pathKey(path));
      if (depth <= 0) return;
      node.children.forEach((c, i) => expandDeep(c, [...path, i], depth - 1));
    };
    if (t) expandDeep(t, [], 3);
    setExpanded(exp);
  }, [open]);

  if (!open) return null;

  const toggleCheck = (key: string) => {
    setChecked((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };
  const toggleExpand = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  };

  // Deduped selection: drop any checked node that has a checked ANCESTOR (its
  // subtree already includes the descendant). Ancestor keys are dotted prefixes.
  const selectedKeys = Array.from(checked);
  const topLevelSelected = selectedKeys.filter((k) => {
    return !selectedKeys.some((other) => other !== k && (k === other || k.startsWith(other + '.')) && other.length < k.length);
  });

  const handleAdd = () => {
    if (!tree) return;
    const nodes: ViewportNode[] = [];
    for (const k of topLevelSelected) {
      const path = k === '' ? [] : k.split('.').map(Number);
      const node = nodeAt(tree, path);
      if (node) nodes.push(node);
    }
    if (nodes.length > 0) onAdd(nodes);
    onClose();
  };

  const renderRow = (node: ViewportNode, path: number[]): JSX.Element => {
    const key = pathKey(path);
    const isChecked = checked.has(key);
    const isExp = expanded.has(key);
    const hasKids = node.children.length > 0;
    const layer = LAYER_COLORS[path.length % LAYER_COLORS.length];
    const stateCount = node.state ? Object.keys(node.state).length : 0;
    const actionCount = node.actions?.length ?? 0;
    return (
      <div key={key || 'root'} style={{ marginLeft: path.length ? 10 : 0, borderLeft: path.length ? `2px solid ${layer}` : 'none', paddingLeft: path.length ? 6 : 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, padding: '2px 0' }}>
          {hasKids ? (
            <button
              onClick={() => toggleExpand(key)}
              title={isExp ? 'Collapse' : 'Expand'}
              style={{ background: 'transparent', border: 'none', color: theme.textDim, cursor: 'pointer', fontSize: 14, lineHeight: 1, padding: 0, width: 16, textAlign: 'center' }}
            >
              {isExp ? '▾' : '▸'}
            </button>
          ) : (
            <span style={{ width: 16, display: 'inline-block' }} />
          )}
          <label style={{ display: 'inline-flex', alignItems: 'center', gap: 6, cursor: 'pointer', flex: 1, minWidth: 0 }}>
            <input type="checkbox" checked={isChecked} onChange={() => toggleCheck(key)} style={{ cursor: 'pointer', accentColor: 'var(--accent-blue)' }} />
            <span style={{ color: layer, fontSize: 11.5, fontWeight: 600 }}>{node.id}</span>
            {node.label && node.label !== node.id && (
              <span style={{ color: theme.textDim, fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{'· '}{node.label}</span>
            )}
            {(stateCount > 0 || actionCount > 0) && (
              <span style={{ color: 'var(--text-muted)', fontSize: 10, flexShrink: 0 }}>
                {stateCount > 0 && `${stateCount}f`}{stateCount > 0 && actionCount > 0 && ' '}{actionCount > 0 && `${actionCount}a`}
              </span>
            )}
          </label>
        </div>
        {isExp && node.children.map((c, i) => renderRow(c, [...path, i]))}
      </div>
    );
  };

  return (
    <div
      style={{
        // Docks to the RIGHT edge INSIDE the dialog panel (the panel is
        // overflow:hidden, so an external left:100% drawer would be clipped).
        // Slides over the right ~340px of the body; the dialog's drag/resize
        // carries it for free since it's a child. Leaves the left of the body
        // peeking for context on wider dialogs.
        position: 'absolute', top: 0, right: 0, bottom: 0, width: 'min(340px, 100%)',
        background: theme.panel, borderLeft: `2px solid var(--accent-blue)`,
        boxShadow: '-8px 0 30px rgba(0,0,0,0.45)',
        display: 'flex', flexDirection: 'column', zIndex: 5,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', borderBottom: `1px solid ${theme.border}` }}>
        <span style={{ color: theme.text, fontWeight: 700, fontSize: 12.5 }}>Pick components</span>
        <span style={{ color: theme.textDim, fontSize: 10.5 }}>drill down · multi-select</span>
        <button
          onClick={onClose}
          title="Close"
          style={{ marginLeft: 'auto', background: 'transparent', border: 'none', color: theme.textDim, cursor: 'pointer', fontSize: 14, fontWeight: 700, lineHeight: 1 }}
        >
          {'✕'}
        </button>
      </div>

      <div style={{ flex: 1, overflow: 'auto', padding: '8px 10px', minHeight: 0 }}>
        {tree ? renderRow(tree, []) : (
          <div style={{ color: theme.textDim, fontSize: 11.5, padding: 8 }}>Nothing to capture from the current view.</div>
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '9px 12px', borderTop: `1px solid ${theme.border}` }}>
        <span style={{ color: theme.textDim, fontSize: 11 }}>
          {topLevelSelected.length > 0 ? `${topLevelSelected.length} selected` : 'none selected'}
        </span>
        <button
          onClick={() => setChecked(new Set())}
          disabled={checked.size === 0}
          style={{ marginLeft: 'auto', background: 'transparent', border: `1px solid ${theme.border}`, color: theme.textDim, borderRadius: 5, padding: '4px 10px', fontSize: 11, cursor: checked.size ? 'pointer' : 'default', opacity: checked.size ? 1 : 0.5 }}
        >
          Clear
        </button>
        <button
          onClick={handleAdd}
          disabled={topLevelSelected.length === 0}
          style={{
            background: topLevelSelected.length ? 'var(--accent-blue)' : theme.panel,
            border: `1px solid var(--accent-blue)`, color: topLevelSelected.length ? 'var(--bg-deep)' : theme.textDim,
            borderRadius: 5, padding: '4px 12px', fontSize: 11.5, fontWeight: 600,
            cursor: topLevelSelected.length ? 'pointer' : 'default', opacity: topLevelSelected.length ? 1 : 0.6,
          }}
        >
          Add selected
        </button>
      </div>
    </div>
  );
}
