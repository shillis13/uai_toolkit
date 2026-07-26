/**
 * TodoBulkPanel — the Work Mgr detail pane when MULTIPLE todos are selected
 * (todo_0558). Replaces the single-todo editor with the actions that apply to a
 * group: change status, change assignee, add a comment (to each), move under an
 * existing parent, create a new parent for the group, and delete.
 *
 * All actions operate on the passed `ids`; the host supplies the handlers (which
 * loop the underlying todo_mgr commands and reload once) and the option lists.
 */
import { useState } from 'react';
import { formatTitle, todoNum, statusLabel, statusColor } from './WorkMgrPane';
import type { WorkItem } from './WorkMgrPane';
import ParentPicker from './ParentPicker';

interface AssigneeOption { uri: string; label: string; grp: string }

interface TodoBulkPanelProps {
  ids: string[];
  todos: WorkItem[];
  statuses: string[];
  assigneeOptions: AssigneeOption[];
  assigneeGroups: string[];
  busy: boolean;
  onStatus: (status: string) => void;
  onAssign: (uri: string) => void;
  onComment: (text: string) => void;
  onMove: (parentId: string) => void;
  onCreateParent: (name: string) => void;
  onDelete: () => void;
  onClear: () => void;
}

export default function TodoBulkPanel({
  ids, todos, statuses, assigneeOptions, assigneeGroups, busy,
  onStatus, onAssign, onComment, onMove, onCreateParent, onDelete, onClear,
}: TodoBulkPanelProps): JSX.Element {
  const [comment, setComment] = useState('');
  const [confirmDel, setConfirmDel] = useState(false);
  const byId = new Map(todos.map(t => [t.id, t]));
  const selSet = new Set(ids);

  return (
    <div className="wm-bulk">
      <div className="wm-bulk-head">
        <span className="wm-bulk-count">{ids.length} todos selected</span>
        <button className="wm-bulk-clear" onClick={onClear}>Clear selection</button>
      </div>

      <div className="wm-bulk-items">
        {ids.map(id => {
          const t = byId.get(id);
          return (
            <div key={id} className="wm-bulk-item">
              <span className="wm-num">{todoNum(id)}</span>
              {t && <span className="wm-status-code" style={{ color: statusColor(t.status) }}>{statusLabel(t.status)}</span>}
              <span className="wm-bulk-item-title">{t ? formatTitle(t) : id}</span>
            </div>
          );
        })}
      </div>

      <div className="wm-bulk-actions">
        <div className="wm-bulk-row">
          <label>Change status</label>
          <select className="wm-status-select" value="" disabled={busy} onChange={e => { if (e.target.value) onStatus(e.target.value); }}>
            <option value="">— set all to —</option>
            {statuses.map(s => <option key={s} value={s}>{statusLabel(s)}</option>)}
          </select>
        </div>

        <div className="wm-bulk-row">
          <label>Change assignee</label>
          <select className="wm-status-select" value="" disabled={busy} onChange={e => {
            if (e.target.value) onAssign(e.target.value === '__unassigned__' ? '' : e.target.value);
          }}>
            <option value="">— assign all to —</option>
            <option value="__unassigned__">Unassigned</option>
            {assigneeGroups.map(grp => {
              const opts = assigneeOptions.filter(o => o.grp === grp);
              return opts.length ? <optgroup key={grp} label={grp}>{opts.map(o => <option key={o.uri} value={o.uri}>{o.label}</option>)}</optgroup> : null;
            })}
          </select>
        </div>

        <div className="wm-bulk-row">
          <label>Move under parent</label>
          {/* Shared with the todo-editor re-parent dropdown so they're identical (todo_0609). */}
          <ParentPicker
            todos={todos}
            excludeIds={selSet}
            onMove={onMove}
            onCreateParent={onCreateParent}
            busy={busy}
            placeholder="— move all under —"
            selectClassName="wm-status-select"
          />
        </div>

        <div className="wm-bulk-row wm-bulk-comment">
          <label>Add comment (to each)</label>
          <textarea className="wm-input" rows={2} value={comment} placeholder="Comment appended to every selected todo…" disabled={busy}
            onChange={e => setComment(e.target.value)} />
          <button className="wm-btn" disabled={busy || !comment.trim()} onClick={() => { onComment(comment.trim()); setComment(''); }}>Add to all {ids.length}</button>
        </div>

        <div className="wm-bulk-row wm-bulk-danger">
          {confirmDel ? (
            <>
              <span>Delete {ids.length} todos (to trash)?</span>
              <button className="wm-btn wm-btn-danger" disabled={busy} onClick={() => { onDelete(); setConfirmDel(false); }}>Delete</button>
              <button className="wm-btn" onClick={() => setConfirmDel(false)}>Cancel</button>
            </>
          ) : (
            <button className="wm-btn wm-btn-danger" disabled={busy} onClick={() => setConfirmDel(true)}>Delete selected ({ids.length})</button>
          )}
        </div>
      </div>
    </div>
  );
}
