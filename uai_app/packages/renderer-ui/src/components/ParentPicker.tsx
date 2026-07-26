/**
 * ParentPicker — the ONE "choose / change a parent" dropdown (todo_0609).
 *
 * PM: "the two drop-downs are not the same and they should be." They diverged
 * because each site (WorkMgrPane editor re-parent, WorkSurface editor, TodoBulkPanel
 * Move-under-parent) hand-rolled its own <select> — different option lists (tree vs
 * flat), and WorkSurface was even missing "＋ New Parent". This is the single shared
 * control they ALL render, so they are identical by construction and can't drift
 * again. Options come from the shared buildParentOptions() (same hierarchy/format
 * everywhere).
 *
 * Structure (fixed): choose… / root (top level) / ＋ New Parent… / <hierarchy>.
 * Picking ＋ New Parent reveals an inline title input; Enter creates + re-parents.
 *
 * Callbacks:
 *   - onMove(parentId): parentId is 'root' (top level) or a todo id.
 *   - onCreateParent(name): create a new parent and move the target(s) under it.
 * The empty "choose…" option and the "＋ New Parent…" sentinel are handled here.
 */

import { useState, useCallback, useEffect } from 'react';
import type { WorkItem } from './WorkMgrPane';
import { buildParentOptions } from '../utils/parent-options';

interface ParentPickerProps {
  todos: WorkItem[];
  /** Ids that can't be a parent — the current todo / the whole selection. */
  excludeIds: Set<string>;
  onMove: (parentId: string) => void;
  onCreateParent: (name: string) => void;
  busy?: boolean;
  /** First (placeholder) option label — contextual (single vs bulk). */
  placeholder?: string;
  /** Select className — matches the host's other selects. */
  selectClassName?: string;
}

export default function ParentPicker({
  todos, excludeIds, onMove, onCreateParent, busy = false,
  placeholder = 'choose a parent…', selectClassName = 'wm-input wm-move-inline',
}: ParentPickerProps): JSX.Element {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const targetKey = [...excludeIds].sort().join('\u0000');

  // The same mounted picker can be reused as selection changes. Never carry a
  // half-entered parent name onto a different todo / bulk selection.
  useEffect(() => {
    setCreating(false);
    setName('');
  }, [targetKey]);

  const commitNew = useCallback(() => {
    const n = name.trim();
    if (!n) return;
    onCreateParent(n);
    setName('');
    setCreating(false);
  }, [name, onCreateParent]);

  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <select
        className={selectClassName}
        value=""
        disabled={busy}
        title="Re-parent this todo"
        onChange={(e) => {
          const v = e.target.value;
          if (!v) return;
          if (v === '__new_parent__') { setCreating(true); setName(''); }
          else onMove(v);
        }}
      >
        <option value="">{placeholder}</option>
        {/* root + New Parent at the TOP — most common targets (todo_0526/0609). */}
        <option value="root">root (top level)</option>
        <option value="__new_parent__">＋ New Parent…</option>
        {buildParentOptions(todos, excludeIds)}
      </select>
      {creating && (
        <input
          className="wm-input"
          autoFocus
          value={name}
          placeholder="New parent title…"
          disabled={busy}
          style={{ width: 160 }}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter') commitNew();
            else if (e.key === 'Escape') { setName(''); setCreating(false); }
          }}
          onBlur={() => { setName(''); setCreating(false); }}
        />
      )}
    </span>
  );
}
