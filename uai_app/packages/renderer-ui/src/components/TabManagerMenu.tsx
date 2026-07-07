/**
 * TabManagerMenu — a "⋮" button in the tab bar that opens a dropdown for
 * bulk tab operations: multi-select tabs, then Close / Stop / Resume.
 *
 * Each row shows the tab's type icon, name, and type coloring.
 */

import { useState, useCallback, useRef, useEffect } from 'react';
import { useAppStateStore, useSessionStore } from '../stores';
import { executeCommand } from '../utils/execute-command';
import { useToast } from './Toast';
import type { Tab } from '@uai/shared/types';

const TAB_TYPE_META: Record<string, { icon: string; color: string }> = {
  session: { icon: '✱', color: 'var(--accent-orange)' },
  folder: { icon: '📂', color: 'var(--accent-yellow)' },
  terminal: { icon: '>_', color: 'var(--accent-green)' },
  brief: { icon: '📖', color: 'var(--accent-cyan)' },
  project: { icon: '📁', color: 'var(--accent-green)' },
  team: { icon: '👥', color: 'var(--accent-blue)' },
  webai: { icon: '🌐', color: 'var(--accent-purple)' },
  app: { icon: '🛠', color: 'var(--accent-orange)' },
  transcript: { icon: '✱', color: 'var(--accent-orange)' },
  search: { icon: '🔍', color: 'var(--text-sec)' },
};

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-cyan)',
};

export default function TabManagerMenu(): JSX.Element {
  const { appState } = useAppStateStore();
  const { getSession } = useSessionStore();
  const { showToast } = useToast();
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const ref = useRef<HTMLDivElement>(null);

  const tabs = appState.tabs;

  useEffect(() => {
    if (!open) return;
    const dismiss = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    setTimeout(() => document.addEventListener('mousedown', dismiss), 0);
    return () => document.removeEventListener('mousedown', dismiss);
  }, [open]);

  const toggle = useCallback((id: string) => {
    setSelected(prev => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  const selectedTabs = (): Tab[] => tabs.filter(t => selected.has(t.id));

  const doClose = useCallback(async () => {
    for (const t of selectedTabs()) {
      await executeCommand('workspace.tabs.close', { tabId: t.id }, { onFailure: 'toast', toastFn: showToast });
    }
    setSelected(new Set());
    setOpen(false);
  }, [tabs, selected, showToast]);

  const doStop = useCallback(async () => {
    const sessions = selectedTabs().filter(t => t.type === 'session');
    for (const t of sessions) {
      await executeCommand('session.stop', { trackingId: t.targetId }, { onFailure: 'toast', toastFn: showToast });
    }
    if (sessions.length === 0) showToast('No sessions selected', 'info');
    setSelected(new Set());
    setOpen(false);
  }, [tabs, selected, showToast]);

  const doResume = useCallback(async () => {
    const sessions = selectedTabs().filter(t => t.type === 'session');
    for (const t of sessions) {
      await executeCommand('session.resume', { trackingId: t.targetId }, { onFailure: 'toast', toastFn: showToast });
    }
    if (sessions.length === 0) showToast('No sessions selected', 'info');
    setSelected(new Set());
    setOpen(false);
  }, [tabs, selected, showToast]);

  const selCount = selected.size;

  return (
    <div className="tab-mgr" ref={ref}>
      <button
        className="tab-mgr-btn"
        title="Tab Manager"
        onClick={(e) => { e.stopPropagation(); setOpen(v => !v); }}
      >{'⋮'}</button>
      {open && (
        <div className="tab-mgr-menu">
          <div className="tab-mgr-header">Tab Manager</div>
          <div className="tab-mgr-actions">
            <button className="tab-mgr-action" disabled={selCount === 0} onClick={doClose}>Close Tabs</button>
            <button className="tab-mgr-action" disabled={selCount === 0} onClick={doStop}>Stop Sessions</button>
            <button className="tab-mgr-action" disabled={selCount === 0} onClick={doResume}>Resume Sessions</button>
          </div>
          <div className="tab-mgr-list">
            {tabs.length === 0 && <div className="tab-mgr-empty">No open tabs.</div>}
            {tabs.map(t => {
              const meta = TAB_TYPE_META[t.type] || { icon: '●', color: 'var(--text-muted)' };
              let color = meta.color;
              if (t.type === 'session') {
                const s = getSession(t.targetId);
                if (s?.platform) color = PLATFORM_COLORS[s.platform] || color;
              }
              const isSession = t.type === 'session';
              const s = isSession ? getSession(t.targetId) : undefined;
              const running = s?.process_status === 'running';
              return (
                <label key={t.id} className={`tab-mgr-row${selected.has(t.id) ? ' selected' : ''}`}>
                  <input type="checkbox" checked={selected.has(t.id)} onChange={() => toggle(t.id)} />
                  <span className="tab-mgr-row-icon" style={{ color }}>{meta.icon}</span>
                  <span className="tab-mgr-row-name" style={{ color }}>{t.label}</span>
                  {isSession && (
                    <span className={`tab-mgr-row-status ${running ? 'running' : 'stopped'}`}>{running ? '●' : '○'}</span>
                  )}
                </label>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}
