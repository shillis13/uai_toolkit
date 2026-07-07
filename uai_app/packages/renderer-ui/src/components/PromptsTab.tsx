/**
 * PromptsTab — pending prompt-queue entries for the active session.
 *
 * Mirrors MessagesTab: hover tooltip, click-to-expand detail layout, [Select]
 * mode with per-row checkboxes + select-all, and a right-click context menu
 * (Hold / Release / Remove) that applies to all selected entries.
 * Part of the right panel (ContextPanel) tab system.
 */

import { useState, useEffect, useCallback } from 'react';
import type { QueueEntry } from '@uai/shared/types';
import { showContextMenu, type ContextMenuItem } from '../utils/context-menu';

const URGENCY_COLORS: Record<string, string> = {
  interrupt: 'var(--accent-red, #f7768e)',
  prompt: 'var(--accent-blue, #7aa2f7)',
  async: 'var(--text-muted, #565f89)',
  passive: 'var(--text-muted, #414868)',
};

const URGENCY_LABELS: Record<string, string> = {
  interrupt: 'INTERRUPT', prompt: 'PROMPT', async: 'ASYNC', passive: 'PASSIVE',
};

function formatTime(iso: string): string {
  if (!iso) return '';
  try {
    const d = new Date(iso);
    const diff = Date.now() - d.getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'just now';
    if (mins < 60) return `${mins}m ago`;
    const hours = Math.floor(mins / 60);
    if (hours < 24) return `${hours}h ago`;
    return `${Math.floor(hours / 24)}d ago`;
  } catch { return ''; }
}

function formatDateTime(iso: string): string {
  if (!iso) return '';
  try { return new Date(iso).toLocaleString(); } catch { return iso; }
}

function formatSize(text: string): string {
  const bytes = new Blob([text || '']).size;
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

function truncate(text: string, maxLen: number): string {
  if (text.length <= maxLen) return text;
  return text.slice(0, maxLen) + '...';
}

interface PromptsTabProps {
  sessionTrackingId: string | null;
}

export default function PromptsTab({ sessionTrackingId }: PromptsTabProps): JSX.Element {
  const [entries, setEntries] = useState<QueueEntry[]>([]);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);
  const [selectMode, setSelectMode] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());

  const loadEntries = useCallback(async () => {
    if (!sessionTrackingId) { setEntries([]); return; }
    setLoading(true);
    try {
      const result = (await window.uai.comms.queueList(sessionTrackingId)) as QueueEntry[];
      setEntries(result || []);
    } catch {
      setEntries([]);
    } finally {
      setLoading(false);
    }
  }, [sessionTrackingId]);

  useEffect(() => { loadEntries(); }, [loadEntries]);
  useEffect(() => { setSelectMode(false); setSelected(new Set()); }, [sessionTrackingId]);

  const toggleSelect = useCallback((id: string) => {
    setSelected(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n; });
  }, []);
  const allSelected = entries.length > 0 && selected.size === entries.length;
  const toggleSelectAll = useCallback(() => {
    setSelected(allSelected ? new Set() : new Set(entries.map(e => e.id)));
  }, [allSelected, entries]);

  const doHold = useCallback(async (ids: string[]) => {
    if (!sessionTrackingId) return;
    await Promise.all(ids.map(id => window.uai.comms.queueHold(sessionTrackingId, id)));
    setSelected(new Set()); loadEntries();
  }, [sessionTrackingId, loadEntries]);
  const doRelease = useCallback(async (ids: string[]) => {
    if (!sessionTrackingId) return;
    await Promise.all(ids.map(id => window.uai.comms.queueRelease(sessionTrackingId, id)));
    setSelected(new Set()); loadEntries();
  }, [sessionTrackingId, loadEntries]);
  const doRemove = useCallback(async (ids: string[]) => {
    if (!sessionTrackingId) return;
    await Promise.all(ids.map(id => window.uai.comms.queueRemove(sessionTrackingId, id)));
    setSelected(new Set()); loadEntries();
  }, [sessionTrackingId, loadEntries]);

  const onRowContextMenu = useCallback((e: React.MouseEvent, entry: QueueEntry) => {
    const targets = (selectMode && selected.has(entry.id) && selected.size > 0)
      ? Array.from(selected)
      : [entry.id];
    const many = targets.length > 1;
    const items: ContextMenuItem[] = [
      { label: many ? `Hold ${targets.length}` : 'Hold', action: () => doHold(targets) },
      { label: many ? `Release ${targets.length}` : 'Release', action: () => doRelease(targets) },
      { label: many ? `Remove ${targets.length}` : 'Remove', action: () => doRemove(targets), danger: true },
    ];
    showContextMenu(e, items);
  }, [selectMode, selected, doHold, doRelease, doRemove]);

  if (!sessionTrackingId) {
    return <div className="comms-empty">Select a session to view its prompt queue.</div>;
  }
  if (loading) return <div className="comms-loading">Loading queue...</div>;
  if (entries.length === 0) return <div className="comms-empty">No pending prompts for this session.</div>;

  return (
    <div className="prompts-tab">
      <div className="msg-folder-bar">
        <span className="prompts-tab-title">Queue ({entries.length})</span>
        <button
          className={`msg-select-toggle${selectMode ? ' active' : ''}`}
          onClick={() => { setSelectMode(v => !v); setSelected(new Set()); }}
        >
          {selectMode ? 'Done' : 'Select'}
        </button>
      </div>

      {selectMode && (
        <label className="msg-select-all">
          <input type="checkbox" checked={allSelected} onChange={toggleSelectAll} />
          <span>{selected.size > 0 ? `${selected.size} selected` : 'Select all'}</span>
        </label>
      )}

      {entries.map(entry => {
        const color = URGENCY_COLORS[entry.urgency] || 'var(--text-muted)';
        const expanded = expandedId === entry.id;
        const isSelected = selected.has(entry.id);

        return (
          <div
            key={entry.id}
            className={`queue-entry${expanded ? ' expanded' : ''}${!entry.ready_for_delivery ? ' held' : ''}${isSelected ? ' selected' : ''}`}
            onContextMenu={(e) => onRowContextMenu(e, entry)}
          >
            <div className="msg-entry-row">
              {selectMode && (
                <input
                  type="checkbox"
                  className="msg-select-checkbox"
                  checked={isSelected}
                  onClick={(e) => e.stopPropagation()}
                  onChange={() => toggleSelect(entry.id)}
                />
              )}
              <div className="msg-entry-main" onClick={() => setExpandedId(expanded ? null : entry.id)} title={entry.content}>
                <div className="queue-entry-header">
                  <span className="queue-urgency-badge" style={{ background: `${color}22`, color, borderColor: `${color}44` }}>
                    {URGENCY_LABELS[entry.urgency] || entry.urgency}
                  </span>
                  <span className="queue-delivery-badge">{entry.delivery}</span>
                  <span className="queue-source">{entry.source}</span>
                  <span className="queue-time">{formatTime(entry.queued_at)}</span>
                  {!entry.ready_for_delivery && <span className="queue-held-badge">HELD</span>}
                </div>
                {expanded ? (
                  <div className="msg-expanded">
                    <div className="msg-meta-row">
                      <span className="msg-meta-id" title={entry.to}>{'→ ' + entry.to}</span>
                      <span className="msg-meta-spacer" />
                      <span className="msg-meta-dt">{formatDateTime(entry.queued_at)}</span>
                      <span className="msg-meta-size">{formatSize(entry.content)}</span>
                    </div>
                    <div className="msg-content">{entry.content}</div>
                  </div>
                ) : (
                  <div className="queue-entry-preview">{truncate(entry.content, 120)}</div>
                )}
              </div>
            </div>
          </div>
        );
      })}
    </div>
  );
}
