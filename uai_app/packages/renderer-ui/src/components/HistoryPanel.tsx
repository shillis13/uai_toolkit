/**
 * HistoryPanel — Prompt history viewer with rewind, copy, resend, edit actions.
 *
 * Ported from UCI HistoryPanel.tsx. Adapted for UAI's transcript IPC.
 * Shows user prompts only, filters out system-injected messages.
 * Keyboard-navigable: Arrow keys, Space to expand, Enter for action menu, Esc to dismiss.
 */

import { useState, useEffect, useRef, useCallback } from 'react';

export interface HistoryEntry {
  role: 'user' | 'assistant';
  content: string;
  timestamp: string;
  index: number;
}

type HistoryAction = 'rewind' | 'copy' | 'resend' | 'edit';

interface HistoryPanelProps {
  cliSessionId: string;
  onDismiss: () => void;
  onAction?: (action: HistoryAction, entry: HistoryEntry) => void;
}

const ACTION_ITEMS: Array<{ id: HistoryAction; label: string; hint: string }> = [
  { id: 'edit', label: 'Edit & send', hint: 'Put in prompt box for editing' },
  { id: 'resend', label: 'Re-send', hint: 'Send this prompt again as-is' },
  { id: 'copy', label: 'Copy to clipboard', hint: 'Copy the full prompt text' },
  { id: 'rewind', label: 'Rewind to here', hint: 'Truncate conversation at this point' },
];

const formatTime = (ts: string): string => {
  try {
    return new Date(ts).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  } catch { return ''; }
};

const formatDateKey = (ts: string): string => {
  try {
    const d = new Date(ts);
    return d.toISOString().slice(0, 10); // YYYY-MM-DD
  } catch { return 'unknown'; }
};

const formatDateLabel = (dateKey: string): string => {
  try {
    const d = new Date(dateKey + 'T12:00:00');
    const today = new Date();
    const yesterday = new Date(today);
    yesterday.setDate(yesterday.getDate() - 1);

    if (d.toDateString() === today.toDateString()) return 'Today';
    if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
    return d.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' });
  } catch { return dateKey; }
};

const truncate = (text: string): string => text.replace(/\n/g, ' ').trim();

const isRealUserPrompt = (content: string): boolean => {
  const trimmed = content.trim();
  if (!trimmed) return false;
  if (trimmed.startsWith('Base directory for this skill:')) return false;
  if (trimmed.startsWith('AI_ROOT:')) return false;
  if (trimmed.startsWith('<system-reminder>')) return false;
  if (trimmed.startsWith('<task-notification>')) return false;
  if (trimmed.startsWith('<command-name>')) return false;
  if (trimmed.startsWith('<command-message>')) return false;
  if (trimmed.startsWith('<local-command-stdout>')) return false;
  if (trimmed.startsWith('# ') && trimmed.length > 1000) return false;
  if (/^[!/]/.test(trimmed) && trimmed.length < 50) return false;
  return true;
};

export default function HistoryPanel({ cliSessionId, onDismiss, onAction }: HistoryPanelProps): JSX.Element {
  const [entries, setEntries] = useState<HistoryEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedIdx, setSelectedIdx] = useState(-1);
  const [hoveredIdx, setHoveredIdx] = useState(-1);
  const [expandedIdx, setExpandedIdx] = useState(-1);
  const [actionMenuOpen, setActionMenuOpen] = useState(false);
  const [actionMenuIdx, setActionMenuIdx] = useState(0);
  const [collapsedDays, setCollapsedDays] = useState<Set<string>>(new Set());
  const [query, setQuery] = useState('');
  const listRef = useRef<HTMLDivElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);

    window.uai.transcript.history(cliSessionId)
      .then((result) => {
        if (cancelled) return;
        if (!result.ok) { setError(result.error || 'Failed to load history'); return; }
        const userMessages: HistoryEntry[] = result.messages
          .map((m, i) => ({ role: m.role as 'user' | 'assistant', content: m.content, timestamp: m.timestamp || '', index: i }))
          .filter(m => m.role === 'user' && isRealUserPrompt(m.content));
        setEntries(userMessages);
        if (userMessages.length > 0) {
          setSelectedIdx(userMessages.length - 1);
        }
      })
      .catch((err: unknown) => { if (!cancelled) setError(String(err)); })
      .finally(() => { if (!cancelled) setLoading(false); });

    return () => { cancelled = true; };
  }, [cliSessionId]);

  useEffect(() => {
    panelRef.current?.focus();
    if (listRef.current) listRef.current.scrollTop = listRef.current.scrollHeight;
  }, [loading]);

  // Scroll selected entry into view
  useEffect(() => {
    if (selectedIdx < 0 || !listRef.current) return;
    const el = listRef.current.querySelector(`[data-entry-idx="${selectedIdx}"]`) as HTMLElement | undefined;
    el?.scrollIntoView({ block: 'nearest' });
  }, [selectedIdx]);

  useEffect(() => {
    if (!actionMenuOpen) return;
    const handleClickOutside = (e: MouseEvent) => {
      const menu = document.querySelector('.tv-history-action-menu');
      if (menu && !menu.contains(e.target as Node)) setActionMenuOpen(false);
    };
    const timer = setTimeout(() => window.addEventListener('click', handleClickOutside), 0);
    return () => { clearTimeout(timer); window.removeEventListener('click', handleClickOutside); };
  }, [actionMenuOpen]);

  const executeAction = useCallback((action: HistoryAction) => {
    if (selectedIdx < 0 || selectedIdx >= entries.length) return;
    setActionMenuOpen(false);
    if (action === 'copy') {
      window.uai.clipboard.write(entries[selectedIdx].content);
      return;
    }
    if (onAction) onAction(action, entries[selectedIdx]);
  }, [selectedIdx, entries, onAction]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent) => {
    if (actionMenuOpen) {
      if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); setActionMenuOpen(false); return; }
      if (e.key === 'ArrowUp') { e.preventDefault(); setActionMenuIdx(prev => Math.max(0, prev - 1)); return; }
      if (e.key === 'ArrowDown') { e.preventDefault(); setActionMenuIdx(prev => Math.min(ACTION_ITEMS.length - 1, prev + 1)); return; }
      if (e.key === 'Enter') { e.preventDefault(); executeAction(ACTION_ITEMS[actionMenuIdx].id); return; }
      return;
    }
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); e.nativeEvent.stopImmediatePropagation(); onDismiss(); return; }
    if (e.key === 'ArrowUp') { e.preventDefault(); setSelectedIdx(prev => Math.max(0, prev - 1)); return; }
    if (e.key === 'ArrowDown') { e.preventDefault(); setSelectedIdx(prev => Math.min(entries.length - 1, prev + 1)); return; }
    if (e.key === 'PageUp') { e.preventDefault(); setSelectedIdx(prev => Math.max(0, prev - 20)); return; }
    if (e.key === 'PageDown') { e.preventDefault(); setSelectedIdx(prev => Math.min(entries.length - 1, prev + 20)); return; }
    const target = e.target as HTMLElement;
    if (target.tagName === 'BUTTON') return;
    if (e.key === ' ' && selectedIdx >= 0) { e.preventDefault(); setExpandedIdx(prev => prev === selectedIdx ? -1 : selectedIdx); return; }
    if (e.key === 'Enter' && selectedIdx >= 0) { e.preventDefault(); setActionMenuIdx(0); setActionMenuOpen(true); return; }
  }, [entries, selectedIdx, actionMenuOpen, actionMenuIdx, onDismiss, executeAction]);

  const handleEscOnly = useCallback((e: React.KeyboardEvent) => {
    if (e.key === 'Escape') { e.preventDefault(); e.stopPropagation(); e.nativeEvent.stopImmediatePropagation(); onDismiss(); }
  }, [onDismiss]);

  if (loading) return (
    <div className="tv-history-panel" ref={panelRef} tabIndex={0} onKeyDown={handleEscOnly}>
      <div className="tv-history-panel-header">
        <span className="tv-history-panel-title">Prompt History</span>
        <span className="tv-history-panel-status">Loading...</span>
        <button className="tv-history-panel-dismiss" onClick={onDismiss}>{'\u00d7'}</button>
      </div>
    </div>
  );

  if (error) return (
    <div className="tv-history-panel" ref={panelRef} tabIndex={0} onKeyDown={handleEscOnly}>
      <div className="tv-history-panel-header">
        <span className="tv-history-panel-title">Prompt History</span>
        <span className="tv-history-panel-status error">{error}</span>
        <button className="tv-history-panel-dismiss" onClick={onDismiss}>{'\u00d7'}</button>
      </div>
    </div>
  );

  if (entries.length === 0) return (
    <div className="tv-history-panel" ref={panelRef} tabIndex={0} onKeyDown={handleEscOnly}>
      <div className="tv-history-panel-header">
        <span className="tv-history-panel-title">Prompt History</span>
        <span className="tv-history-panel-status">No prompts in this session</span>
        <button className="tv-history-panel-dismiss" onClick={onDismiss}>{'\u00d7'}</button>
      </div>
    </div>
  );

  const q = query.trim().toLowerCase();
  const matchCount = q ? entries.filter((e) => e.content.toLowerCase().includes(q)).length : entries.length;
  return (
    <div className="tv-history-panel" ref={panelRef} tabIndex={0} onKeyDown={handleKeyDown}>
      <div className="tv-history-panel-header">
        <span className="tv-history-panel-title">Prompt History</span>
        <span className="tv-history-panel-status">
          {q ? `${matchCount} / ${entries.length}` : `${entries.length} prompts`}
        </span>
        <span className="tv-history-panel-hint">{'\u2191\u2193'} navigate {'\u00b7'} Space expand {'\u00b7'} Enter select {'\u00b7'} Esc dismiss</span>
        <button className="tv-history-panel-dismiss" onClick={onDismiss}>{'\u00d7'}</button>
      </div>
      <input
        className="tv-history-search"
        value={query}
        placeholder="Search prompts\u2026"
        onChange={(e) => { setQuery(e.target.value); setSelectedIdx(-1); }}
        onKeyDown={(e) => {
          // Keep typing (incl. arrows) in the field; Esc clears the query, then dismisses.
          e.stopPropagation();
          if (e.key === 'Escape') { e.preventDefault(); e.nativeEvent.stopImmediatePropagation(); if (query) setQuery(''); else onDismiss(); }
        }}
      />
      <div className="tv-history-panel-list" ref={listRef}>
        {(() => {
          const elements: JSX.Element[] = [];
          let lastDateKey = '';

          // Filter to entries matching the search; keep original indices for selection/actions.
          const visible: number[] = [];
          for (let i = 0; i < entries.length; i++) {
            if (q && !entries[i].content.toLowerCase().includes(q)) continue;
            visible.push(i);
          }
          if (q && visible.length === 0) {
            return [<div key="no-match" className="tv-history-empty">No prompts match &ldquo;{query}&rdquo;.</div>];
          }

          for (const i of visible) {
            const entry = entries[i];
            const dateKey = formatDateKey(entry.timestamp);
            const isDayCollapsed = collapsedDays.has(dateKey);

            // Day separator when date changes
            if (dateKey !== lastDateKey) {
              const dayEntryCount = visible.filter((vi) => formatDateKey(entries[vi].timestamp) === dateKey).length;
              elements.push(
                <div
                  key={`day-${dateKey}`}
                  className="tv-history-day-separator"
                  onClick={() => setCollapsedDays(prev => {
                    const next = new Set(prev);
                    if (next.has(dateKey)) next.delete(dateKey); else next.add(dateKey);
                    return next;
                  })}
                >
                  <span className="tv-history-day-toggle">{isDayCollapsed ? '\u25B6' : '\u25BC'}</span>
                  <span className="tv-history-day-label">{formatDateLabel(dateKey)}</span>
                  <span className="tv-history-day-count">{dayEntryCount}</span>
                  <span className="tv-history-day-line" />
                </div>
              );
              lastDateKey = dateKey;
            }

            if (isDayCollapsed) continue;

            const isSelected = i === selectedIdx;
            const isExpanded = i === expandedIdx;

            elements.push(
              <div
                key={entry.index}
                data-entry-idx={i}
                className={`tv-history-entry${isSelected ? ' selected' : ''}${isExpanded ? ' expanded' : ''}`}
                onMouseEnter={() => setHoveredIdx(i)}
                onMouseLeave={() => setHoveredIdx(-1)}
                onClick={() => setSelectedIdx(i)}
              >
                <span className="tv-history-entry-num">{i + 1}</span>
                <span className="tv-history-entry-time">{formatTime(entry.timestamp)}</span>
                {isExpanded ? (
                  <span className="tv-history-entry-expanded">{entry.content}</span>
                ) : (
                  <span className="tv-history-entry-text">{truncate(entry.content)}</span>
                )}
                {!isExpanded && !actionMenuOpen && i === hoveredIdx && entry.content.length > 80 && (
                  <div className="tv-history-tooltip">{entry.content}</div>
                )}
              </div>
            );
          }
          return elements;
        })()}
      </div>
      {actionMenuOpen && selectedIdx >= 0 && (() => {
        const entryEl = listRef.current?.querySelector(`[data-entry-idx="${selectedIdx}"]`) as HTMLElement | undefined;
        if (!entryEl) return null;
        const rect = entryEl.getBoundingClientRect();
        return (
          <div className="tv-history-action-menu" style={{ top: rect.bottom + 2, right: window.innerWidth - rect.right + 12 }}>
            {ACTION_ITEMS.map((item, ai) => (
              <div
                key={item.id}
                className={`tv-history-action-item ${item.id}${ai === actionMenuIdx ? ' selected' : ''}`}
                onClick={(e) => { e.stopPropagation(); executeAction(item.id); }}
                onMouseEnter={() => setActionMenuIdx(ai)}
              >
                <span className="tv-history-action-label">{item.label}</span>
                <span className="tv-history-action-hint">{item.hint}</span>
              </div>
            ))}
          </div>
        );
      })()}
    </div>
  );
}
