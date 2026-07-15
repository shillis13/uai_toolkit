/**
 * BottomPanel — collapsible bottom drawer with configurable tabs.
 *
 * Supports two tab types:
 * - LogFileTab: live file tail viewer bound to any file on disk
 * - SpecialTab: built-in tabs (Related Entities, System Monitor)
 *
 * Log tabs are runtime-configurable: add, remove, reorder, filter.
 * Uses LogFileViewer for file tailing with schema-driven formatting.
 */

import { useState, useEffect, useCallback, useRef, useMemo, type ReactNode } from 'react';
import { useViewport } from '../viewport';
import { useSessionStore, useAppStateStore } from '../stores';
import { useRelationships, inverseLabel } from '../stores/relationship-store';
import AskHamiltonLine from './AskHamiltonLine';
import LogFileViewer from './LogFileViewer';
import type { LogFileSchema } from './LogFileViewer';
import PromptLogTab from './PromptLogTab';
import type { Session } from '@uai/shared/types';

// ─── Tab Types ──────────────────────────────────────────────────────────

interface LogFileTabDef {
  kind: 'log';
  id: string;
  label: string;
  filePath: string;
  schema?: LogFileSchema;
  sessionScoped?: boolean;  // filter by active session
  pinned?: boolean;
}

interface SpecialTabDef {
  kind: 'special';
  id: string;
  label: string;
  component: 'related' | 'monitor' | 'prompts' | 'session_log' | 'hooks_log';
  pinned?: boolean;
}

interface SetupTabDef {
  kind: 'setup';
  id: string;
  label: string;
  pinned?: boolean;
}

type BottomPanelTabDef = LogFileTabDef | SpecialTabDef | SetupTabDef;

// ─── Known Log Presets ──────────────────────────────────────────────────

const AI_ROOT = typeof process !== 'undefined' ? (process.env?.AI_ROOT || '') : '';

function getDefaultTabs(aiRoot: string): BottomPanelTabDef[] {
  return [
    { kind: 'special', id: 'related', label: 'Related', component: 'related', pinned: true },
    // Both logs are per-session with a dynamically-computed path off the ACTIVE
    // session's dir. Session Log = the CLI's own logs/session.log; Hooks Log = the
    // per-session hook_events.jsonl.
    { kind: 'special', id: 'session_log', label: 'Session Log', component: 'session_log', pinned: true },
    { kind: 'special', id: 'hooks_log', label: 'Hooks Log', component: 'hooks_log', pinned: true },
    {
      kind: 'log', id: 'app_log', label: 'App Log',
      filePath: `${aiRoot}/ai_general/data/activity_log.jsonl`,
      schema: { format: 'jsonl', timestampField: 'ts', levelField: 'event', displayFields: ['session', 'event', 'payload'] },
      pinned: true,
    },
    {
      kind: 'log', id: 'error_log', label: 'Errors',
      filePath: `${aiRoot}/ai_general/data/uai_errors.jsonl`,
      schema: { format: 'jsonl', timestampField: 'ts', levelField: 'level', displayFields: ['source', 'session', 'message'] },
      pinned: true,
    },
    {
      kind: 'special', id: 'prompts', label: 'Prompts', component: 'prompts', pinned: true,
    },
    { kind: 'special', id: 'monitor', label: 'Monitor', component: 'monitor', pinned: true },
  ];
}

// ─── BottomPanel ────────────────────────────────────────────────────────

interface BottomPanelProps {
  activeSessionId: string | null;
}

export default function BottomPanel({ activeSessionId }: BottomPanelProps): JSX.Element {
  const { appState, updateAppState } = useAppStateStore();
  const { getSession, aiRoot } = useSessionStore();
  const isOpen = appState.bottomPanelOpen ?? false;
  const panelHeight = appState.panelSizes?.bottomPanelHeight ?? 200;

  const [activeTab, setActiveTab] = useState('related');
  const [tabs, setTabs] = useState<BottomPanelTabDef[]>(() => getDefaultTabs(aiRoot || AI_ROOT));
  const [logFilter, setLogFilter] = useState('');
  const [addMenuOpen, setAddMenuOpen] = useState(false);
  const [editingTabId, setEditingTabId] = useState<string | null>(null);
  const tabNameInputRef = useRef<HTMLInputElement>(null);
  const [version, setVersion] = useState('?');

  // Dismiss add-menu on click-away
  useEffect(() => {
    if (!addMenuOpen) return;
    const dismiss = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (!target.closest('.bottom-panel-add-menu') && !target.closest('.bottom-panel-add-tab')) {
        setAddMenuOpen(false);
      }
    };
    setTimeout(() => window.addEventListener('mousedown', dismiss), 0);
    return () => window.removeEventListener('mousedown', dismiss);
  }, [addMenuOpen]);

  useViewport('bottom_panel', () => ({
    visible: true,
    state: { collapsed: !isOpen },
    actions: [
      {
        id: 'toggle',
        command: 'app.state.update',
        payload: { patch: { bottomPanelOpen: !isOpen } },
        label: isOpen ? 'Collapse panel' : 'Expand panel',
      },
    ],
    children: [],
  }));

  useEffect(() => {
    window.uai.getVersion?.().then(setVersion).catch(() => {});
  }, []);

  // Update tabs when aiRoot becomes available
  useEffect(() => {
    if (aiRoot) setTabs(getDefaultTabs(aiRoot));
  }, [aiRoot]);

  // Metrics for drawer bar
  const [metrics, setMetrics] = useState<{
    sessions: number; errors: number; cpu: number;
    sysStatus?: 'ok' | 'warn' | 'crit' | 'unknown'; pressure?: string;
    committedGb?: number; totalGb?: number; diskUsedPct?: number;
    claude7dPct?: number | null; claude7dReset?: string | number | null;
  }>({ sessions: 0, errors: 0, cpu: 0 });
  useEffect(() => {
    const interval = setInterval(async () => {
      try {
        const m = await window.uai.systemMetrics();
        setMetrics({
          sessions: m.active_sessions,
          errors: m.error_count,
          cpu: m.cpu_percent,
          sysStatus: m.sysmon_status,
          pressure: m.mem_pressure,
          committedGb: m.mem_committed_gb,
          totalGb: m.mem_total_gb,
          diskUsedPct: m.disk_used_pct,
          claude7dPct: m.claude_7d_pct,
          claude7dReset: m.claude_7d_reset,
        });
      } catch { /* ignore */ }
    }, isOpen && activeTab === 'monitor' ? 2000 : 5000);
    return () => clearInterval(interval);
  }, [isOpen, activeTab]);

  const toggleOpen = useCallback(() => {
    updateAppState({ bottomPanelOpen: !isOpen });
  }, [isOpen, updateAppState]);

  // Open the panel directly to a specific tab (used by tab bar when closed).
  const openToTab = useCallback((tabId: string) => {
    setActiveTab(tabId);
    if (!isOpen) updateAppState({ bottomPanelOpen: true });
  }, [isOpen, updateAppState]);

  // ── Per-session log base dir (dynamic). Session Log = logs/session.jsonl (the
  //    unified lib_logging per-session log, JSONL twin — filterable by level and
  //    component); Hooks Log = hook_events.jsonl (our hook pipeline). ──
  const activeSession = activeSessionId ? getSession(activeSessionId) : null;
  const sessionLogBase = useMemo(() => {
    if (!activeSession || !aiRoot) return null;
    const sd = activeSession.session_dir || '';
    const marker = '/ai_general/data/sessions/';
    if (sd.includes(marker)) {
      // Normalize to the current aiRoot (session_dir may use a stale base path).
      const tail = sd.split(marker)[1];
      return `${aiRoot}/ai_general/data/sessions/${tail}`;
    }
    return null;
  }, [activeSession, aiRoot]);
  const sessionLogPath = sessionLogBase ? `${sessionLogBase}/logs/session.jsonl` : null;
  const hooksLogPath = sessionLogBase ? `${sessionLogBase}/hook_events.jsonl` : null;

  const SESSION_LOG_SCHEMA: LogFileSchema = {
    format: 'jsonl', timestampField: 'ts', levelField: 'level',
    displayFields: ['logger', 'message'],
  };
  const HOOKS_LOG_SCHEMA: LogFileSchema = {
    format: 'jsonl', timestampField: 'ts', levelField: 'action',
    displayFields: ['hook_type', 'handler', 'reason'],
  };

  // ── Recent error bar — most recent error from main + renderer ──
  const [lastError, setLastError] = useState<{ ts: string; source: string; session: string; message: string } | null>(null);
  useEffect(() => {
    const poll = async () => {
      try { setLastError(await window.uai.getLastError?.() || null); } catch { /* ignore */ }
    };
    poll();
    const interval = setInterval(poll, 4000);
    return () => clearInterval(interval);
  }, []);

  // Add a new log tab
  const addLogTab = useCallback((label: string, filePath: string, schema?: LogFileSchema) => {
    const id = `log_${Date.now()}_${Math.random().toString(36).slice(2, 4)}`;
    const newTab: LogFileTabDef = { kind: 'log', id, label, filePath, schema };
    setTabs(prev => [...prev, newTab]);
    setActiveTab(id);
    setAddMenuOpen(false);
  }, []);

  // Create a new setup tab — user names it, then configures the log source
  const addSetupTab = useCallback(() => {
    const id = `setup_${Date.now()}_${Math.random().toString(36).slice(2, 4)}`;
    const newTab: SetupTabDef = { kind: 'setup', id, label: 'New Log' };
    setTabs(prev => [...prev, newTab]);
    setActiveTab(id);
    setEditingTabId(id);
    setAddMenuOpen(false);
    setTimeout(() => tabNameInputRef.current?.focus(), 100);
  }, []);

  // Convert a setup tab into a log tab once configured
  const configureSetupTab = useCallback((tabId: string, label: string, filePath: string, schema?: LogFileSchema) => {
    setTabs(prev => prev.map(t => t.id === tabId
      ? { kind: 'log' as const, id: tabId, label, filePath, schema }
      : t
    ));
    setEditingTabId(null);
  }, []);

  const removeTab = useCallback((tabId: string) => {
    setTabs(prev => prev.filter(t => t.id !== tabId || t.pinned));
    if (activeTab === tabId) setActiveTab(tabs[0]?.id || '');
  }, [activeTab, tabs]);

  // Resize
  const handleResizeMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startY = e.clientY;
    const startHeight = panelHeight;
    const onMouseMove = (ev: MouseEvent) => {
      const delta = startY - ev.clientY;
      updateAppState({ panelSizes: { ...appState.panelSizes, bottomPanelHeight: Math.max(100, Math.min(Math.max(600, Math.round(window.innerHeight * 0.85)), startHeight + delta)) } });
    };
    const onMouseUp = () => {
      document.removeEventListener('mousemove', onMouseMove);
      document.removeEventListener('mouseup', onMouseUp);
    };
    document.addEventListener('mousemove', onMouseMove);
    document.addEventListener('mouseup', onMouseUp);
  }, [panelHeight, appState.panelSizes, updateAppState]);

  // Status bar — always visible at bottom, same position open or closed
  const statusBar = (
    <div className="bottom-panel-drawer-bar" onClick={toggleOpen}>
      <span className="bottom-panel-drawer-summary">
        {metrics.sysStatus && (
          <>
            <span className={`bottom-panel-sys bottom-panel-sys-${metrics.sysStatus}`} title="System health (sysmon)">
              {'●'} {metrics.sysStatus.toUpperCase()}
            </span>
            &nbsp;|&nbsp;
          </>
        )}
        Sessions: {metrics.sessions} &nbsp;|&nbsp; Errors: {metrics.errors} &nbsp;|&nbsp; CPU: {metrics.cpu}%
        {metrics.committedGb != null && (
          <> &nbsp;|&nbsp; Mem: {metrics.committedGb.toFixed(1)}/{metrics.totalGb}GB{metrics.pressure ? ` (${metrics.pressure})` : ''}</>
        )}
        {metrics.diskUsedPct != null && (
          <> &nbsp;|&nbsp; Disk: {metrics.diskUsedPct}%</>
        )}
        {metrics.claude7dPct != null && (
          <span title="Claude Code 7-day usage (resets in …)">
            &nbsp;|&nbsp; 7d: <span className={`monitor-accent-${paceAccent(metrics.claude7dPct, metrics.claude7dReset, CLAUDE_7D_SECS)}`}>{Math.round(metrics.claude7dPct)}%</span> ({fmtCountdown(metrics.claude7dReset)})
          </span>
        )}
      </span>
      <span style={{ display: 'flex', alignItems: 'center', gap: 10, marginLeft: '12px' }}>
        {/* Add Note / Ask Hamilton — right-justified next to the version. stopPropagation
            so clicking a pill doesn't toggle the drawer open/closed. */}
        <span onClick={(e) => e.stopPropagation()}>
          <AskHamiltonLine inline />
        </span>
        <span className="bottom-panel-drawer-version" style={{ opacity: 0.4, fontSize: '10px' }}>
          UAI v{version}
        </span>
      </span>
    </div>
  );

  // Compact, always-visible tab strip — shows what's in the panel even when
  // closed, so users know there's content without opening it blindly.
  const tabStrip = (
    <div className="bottom-panel-tab-strip">
      <span
        className="bottom-panel-handle-chevron"
        onClick={(e) => { e.stopPropagation(); toggleOpen(); }}
        title={isOpen ? 'Collapse panel' : 'Expand panel'}
      >{isOpen ? '▼' : '▲'}</span>
      {tabs.map(tab => (
        <button
          key={tab.id}
          className={`bottom-panel-strip-tab${activeTab === tab.id && isOpen ? ' active' : ''}`}
          onClick={() => openToTab(tab.id)}
          title={tab.label}
        >
          {tab.label}
        </button>
      ))}
    </div>
  );

  // Recent-error bar — shows the most recent error/warn so problems are
  // visible without opening the panel. Click to jump to the Errors tab.
  const clearRecentError = useCallback((e: React.MouseEvent) => {
    e.stopPropagation();
    setLastError(null);
    window.uai.clearErrors?.().catch(() => { /* ignore */ });
  }, []);

  const recentErrorBar = lastError ? (
    <div
      className="bottom-panel-error-bar"
      onClick={() => openToTab('error_log')}
      title="Click to open the Errors log"
    >
      <span className="bottom-panel-error-icon">{'⚠'}</span>
      <span className="bottom-panel-error-source">{lastError.source}</span>
      <span className="bottom-panel-error-msg">{lastError.message}</span>
      <button
        className="bottom-panel-error-clear"
        onClick={clearRecentError}
        title="Clear this error line"
      >{'✕'}</button>
    </div>
  ) : null;

  if (!isOpen) {
    return (
      <div className="bottom-panel-collapsed">
        {tabStrip}
        {recentErrorBar}
        {statusBar}
      </div>
    );
  }

  const activeTabDef = tabs.find(t => t.id === activeTab);

  return (
    <div className="bottom-panel" style={{ height: panelHeight }}>
      <div className="bottom-panel-resize-handle" onMouseDown={handleResizeMouseDown} />
      <div className="bottom-panel-header">
        <div className="bottom-panel-tab-bar">
          <span className="bottom-panel-handle-chevron" onClick={toggleOpen} title="Collapse panel">{'\u25BC'}</span>
          {tabs.map(tab => (
            <div key={tab.id} className={`bottom-panel-tab-wrapper${activeTab === tab.id ? ' active' : ''}`}>
              {editingTabId === tab.id ? (
                <input
                  ref={tabNameInputRef}
                  className="bottom-panel-tab-name-input"
                  defaultValue={tab.label}
                  onBlur={(e) => {
                    const name = e.target.value.trim() || 'Log';
                    setTabs(prev => prev.map(t => t.id === tab.id ? { ...t, label: name } : t));
                    setEditingTabId(null);
                  }}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter') (e.target as HTMLInputElement).blur();
                    if (e.key === 'Escape') { setEditingTabId(null); }
                  }}
                  spellCheck={false}
                />
              ) : (
                <button
                  className={`bottom-panel-tab${activeTab === tab.id ? ' active' : ''}`}
                  onClick={() => setActiveTab(tab.id)}
                  onDoubleClick={() => !tab.pinned && setEditingTabId(tab.id)}
                  title={tab.pinned ? tab.label : 'Double-click to rename'}
                >
                  {tab.label}
                </button>
              )}
              {!tab.pinned && editingTabId !== tab.id && (
                <button className="bottom-panel-tab-close" onClick={() => removeTab(tab.id)} title="Remove tab">{'\u00d7'}</button>
              )}
            </div>
          ))}
          <div style={{ position: 'relative', display: 'inline-block' }}>
            <button className="bottom-panel-add-tab" onClick={() => setAddMenuOpen(v => !v)} title="Add log tab">+</button>
            {addMenuOpen && (
              <div className="bottom-panel-add-menu">
                <div className="context-menu-header" style={{ padding: '4px 10px', fontSize: '10px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Quick Add</div>
                <button className="bottom-panel-add-item" onClick={() => { addLogTab('Audit', `${aiRoot}/ai_general/data/audit/comms/events/${new Date().toISOString().slice(0, 10)}.jsonl`, { format: 'jsonl', timestampField: 'ts' }); setAddMenuOpen(false); }}>Audit Log (today)</button>
                <button className="bottom-panel-add-item" onClick={() => { addLogTab('Tool Events', `${aiRoot}/ai_general/data/audit/tools/events/${new Date().toISOString().slice(0, 10)}.jsonl`, { format: 'jsonl', timestampField: 'ts' }); setAddMenuOpen(false); }}>Tool Events (today)</button>
                <button className="bottom-panel-add-item" onClick={() => { addLogTab('Comms', `${aiRoot}/ai_general/data/audit/comms/events/${new Date().toISOString().slice(0, 10)}.jsonl`, { format: 'jsonl', timestampField: 'ts' }); setAddMenuOpen(false); }}>Comms Events (today)</button>
                <div className="context-menu-separator" />
                <button className="bottom-panel-add-item" onClick={() => { addSetupTab(); }}>New custom log...</button>
              </div>
            )}
          </div>
        </div>
        <div className="bottom-panel-toolbar">
          {(activeTabDef?.kind === 'log' || (activeTabDef?.kind === 'special' && activeTabDef.component === 'session_log')) && (
            <input
              className="bottom-panel-log-filter"
              type="text"
              placeholder="Filter..."
              value={logFilter}
              onChange={e => setLogFilter(e.target.value)}
            />
          )}
          {/* Collapse button removed — status bar at bottom handles toggle */}
        </div>
      </div>
      <div className="bottom-panel-body">
        {activeTabDef?.kind === 'log' && (
          <LogFileViewer
            key={activeTabDef.id}
            filePath={activeTabDef.filePath}
            schema={activeTabDef.schema}
            sessionFilter={activeTabDef.sessionScoped ? activeSessionId || undefined : undefined}
            searchFilter={logFilter || undefined}
          />
        )}
        {activeTabDef?.kind === 'special' && activeTabDef.component === 'session_log' && (
          activeSessionId && sessionLogPath ? (
            <LogFileViewer
              key={sessionLogPath}
              filePath={sessionLogPath}
              schema={SESSION_LOG_SCHEMA}
              searchFilter={logFilter || undefined}
            />
          ) : (
            <div className="bottom-panel-empty">
              {activeSessionId ? 'No session log available for this session yet.' : 'Select a session to view its log.'}
            </div>
          )
        )}
        {activeTabDef?.kind === 'special' && activeTabDef.component === 'hooks_log' && (
          activeSessionId && hooksLogPath ? (
            <LogFileViewer
              key={hooksLogPath}
              filePath={hooksLogPath}
              schema={HOOKS_LOG_SCHEMA}
              searchFilter={logFilter || undefined}
            />
          ) : (
            <div className="bottom-panel-empty">
              {activeSessionId ? 'No hooks log available for this session yet.' : 'Select a session to view its hooks log.'}
            </div>
          )
        )}
        {activeTabDef?.kind === 'special' && activeTabDef.component === 'related' && (
          <RelatedEntitiesTab activeSessionId={activeSessionId} />
        )}
        {activeTabDef?.kind === 'special' && activeTabDef.component === 'prompts' && (
          <PromptLogTab filePath={`${(aiRoot || '').replace(/\/AI\/.*$/, '')}/.claude/history.jsonl`} />
        )}
        {activeTabDef?.kind === 'special' && activeTabDef.component === 'monitor' && (
          <SystemMonitorTab onOpenTab={setActiveTab} />
        )}
        {activeTabDef?.kind === 'setup' && (
          <LogSetupForm
            tabId={activeTabDef.id}
            initialLabel={activeTabDef.label}
            aiRoot={aiRoot}
            onConfigure={configureSetupTab}
            onCancel={() => removeTab(activeTabDef.id)}
          />
        )}
      </div>
      {recentErrorBar}
      {statusBar}
    </div>
  );
}

// ─── Related Entities Tab ───────────────────────────────────────────────

const REL_PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-blue)',
};

const REL_PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude',
  codex_cli: 'Codex',
  gemini_cli: 'Gemini',
};

const REL_STATUS_COLORS: Record<string, string> = {
  running: 'var(--accent-green)',
  responding: 'var(--accent-green)',
  idle: 'var(--accent-cyan)',
  blocked: 'var(--accent-yellow)',
  error: 'var(--accent-red)',
  stopped: 'var(--text-muted)',
  exited: 'var(--text-muted)',
  unknown: 'var(--text-muted)',
};

interface RelatedGroup {
  label: string;
  items: RelatedItem[];
}

interface RelatedItem {
  id: string;
  entityType: string;
  relationLabel: string;
  displayName: string;
  platform?: string;
  processStatus?: string;
  activityState?: string;
  tabType: 'session' | 'brief';
}

/**
 * Categorize relationships into display groups:
 * Parent, Children, Linked Briefs, Team Members, Other.
 */
function categorizeRelationships(
  relationships: ReturnType<typeof useRelationships>['relationships'],
  activeSessionId: string,
  getSession: (id: string) => Session | undefined,
): RelatedGroup[] {
  const parent: RelatedItem[] = [];
  const children: RelatedItem[] = [];
  const briefs: RelatedItem[] = [];
  const team: RelatedItem[] = [];
  const other: RelatedItem[] = [];

  for (const rel of relationships) {
    const isSource = rel.source_id === activeSessionId;
    const targetId = isSource ? rel.target_id : rel.source_id;
    const targetType = isSource ? rel.target_type : rel.source_type;
    const forwardLabel = rel.relation_type;
    const effectiveLabel = isSource ? forwardLabel : inverseLabel(forwardLabel);
    const session = targetType === 'session' ? getSession(targetId) : undefined;

    const item: RelatedItem = {
      id: targetId,
      entityType: targetType,
      relationLabel: effectiveLabel.replace(/_/g, ' '),
      displayName: session?.display_name || targetId,
      platform: session?.platform,
      processStatus: session?.process_status,
      activityState: session?.activity_state,
      tabType: targetType === 'brief' ? 'brief' : 'session',
    };

    // Categorize by relationship semantics
    if (forwardLabel === 'forked_from' || forwardLabel === 'launched_from' || forwardLabel === 'continues') {
      if (isSource) {
        // This session was forked_from / launched_from / continues another -> that's the parent
        parent.push(item);
      } else {
        // Another session was forked_from / launched_from / continues this -> that's a child
        children.push(item);
      }
    } else if (forwardLabel === 'briefed_to') {
      // briefed_to: source session -> target brief
      briefs.push(item);
    } else if (forwardLabel === 'member_of') {
      // member_of: source is member, target is team/group
      team.push(item);
    } else if (forwardLabel === 'assigned_to') {
      team.push(item);
    } else {
      other.push(item);
    }
  }

  const groups: RelatedGroup[] = [];
  if (parent.length > 0) groups.push({ label: 'Parent', items: parent });
  if (children.length > 0) groups.push({ label: 'Children', items: children });
  if (briefs.length > 0) groups.push({ label: 'Linked Briefs', items: briefs });
  if (team.length > 0) groups.push({ label: 'Team Members', items: team });
  if (other.length > 0) groups.push({ label: 'Related', items: other });

  return groups;
}

function RelatedEntitiesTab({ activeSessionId }: { activeSessionId: string | null }): JSX.Element {
  const { relationships, loading } = useRelationships('session', activeSessionId || '');
  const { getSession } = useSessionStore();
  const { openTab } = useAppStateStore();

  if (!activeSessionId) return <div className="bottom-panel-empty">Select a session to view related entities</div>;
  if (loading) return <div className="bottom-panel-empty">Loading relationships...</div>;
  if (relationships.length === 0) return <div className="bottom-panel-empty">No related entities</div>;

  const groups = categorizeRelationships(relationships, activeSessionId, getSession);

  const handleClick = (item: RelatedItem) => {
    openTab(item.id, item.displayName, item.tabType);
  };

  return (
    <div className="related-entities">
      {groups.map(group => (
        <div key={group.label} className="related-group">
          <div className="related-group-header">{group.label}</div>
          <div className="related-group-items">
            {group.items.map(item => (
              <button
                key={item.id}
                className="related-card"
                onClick={() => handleClick(item)}
                title={`Open ${item.displayName}`}
              >
                {item.platform && (
                  <span
                    className="related-card-platform"
                    style={{ backgroundColor: REL_PLATFORM_COLORS[item.platform] || 'var(--text-muted)' }}
                  />
                )}
                <span
                  className="related-card-status"
                  style={{
                    backgroundColor: REL_STATUS_COLORS[item.activityState || item.processStatus || 'unknown'] || 'var(--text-muted)',
                  }}
                />
                <span className="related-card-name">{item.displayName}</span>
                {item.platform && (
                  <span className="related-card-badge" style={{ color: REL_PLATFORM_COLORS[item.platform] }}>
                    {REL_PLATFORM_LABELS[item.platform] || item.platform}
                  </span>
                )}
                {!item.platform && (
                  <span className="related-card-entity-type">{item.entityType}</span>
                )}
                <span className="related-card-relation">{item.relationLabel}</span>
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ─── System Monitor Tab ─────────────────────────────────────────────────

// ── Monitor helpers ───────────────────────────────────────────────────────
type MAccent = 'green' | 'yellow' | 'red' | 'blue' | 'cyan' | 'muted';

function pressureAccent(p?: string): MAccent {
  if (p === 'critical') return 'red';
  if (p === 'warn') return 'yellow';
  if (p === 'normal') return 'green';
  return 'muted';
}
function statusAccent(s?: string): MAccent {
  if (s === 'crit') return 'red';
  if (s === 'warn') return 'yellow';
  if (s === 'ok') return 'green';
  return 'muted';
}
function fmtUptime(sec?: number): string {
  if (!sec || sec <= 0) return '—';
  const d = Math.floor(sec / 86400), h = Math.floor((sec % 86400) / 3600), m = Math.floor((sec % 3600) / 60);
  if (d > 0) return `${d}d ${h}h`;
  if (h > 0) return `${h}h ${m}m`;
  return `${m}m`;
}
/** Normalize a reset timestamp to epoch-ms. The statusline bridge writes it as an
 *  epoch-SECONDS string (e.g. "1783058400"); older data may be ISO. Handles both. */
function resetMs(v?: string | number | null): number | null {
  if (v == null || v === '') return null;
  const s = String(v).trim();
  if (/^\d+$/.test(s)) { const n = Number(s); return n < 1e12 ? n * 1000 : n; } // sec vs ms
  const t = new Date(s).getTime();
  return isNaN(t) ? null : t;
}
function fmtReset(iso?: string | number | null): string {
  const t = resetMs(iso);
  if (t == null) return '—';
  return new Date(t).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function gb(n?: number | null): string { return n == null || isNaN(n) ? '—' : `${n.toFixed(1)} GB`; }
/** Compact token count: 1.2M / 45k / 900. */
function fmtTok(n?: number | null): string {
  if (n == null || isNaN(n)) return '—';
  if (n >= 1e6) return `${(n / 1e6).toFixed(1)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(0)}k`;
  return `${Math.round(n)}`;
}
/** Compact USD: $1.2k / $340 / $4.50 / <$0.01. */
function fmtUsd(n?: number | null): string {
  if (n == null || isNaN(n)) return '—';
  if (n >= 1000) return `$${(n / 1000).toFixed(1)}k`;
  if (n >= 100) return `$${n.toFixed(0)}`;
  if (n > 0 && n < 0.01) return '<$0.01';
  return `$${n.toFixed(2)}`;
}

/** Countdown to a reset time as days/hours/mins, matching the statusline format
 *  (2d5h12m / 5h12m / 12m). */
function fmtCountdown(iso?: string | number | null): string {
  const t = resetMs(iso);
  if (t == null) return '—';
  const diff = Math.floor((t - Date.now()) / 1000);
  if (diff <= 0) return 'now';
  const d = Math.floor(diff / 86400), h = Math.floor((diff % 86400) / 3600), m = Math.floor((diff % 3600) / 60);
  if (d > 0) return `${d}d${h}h${m}m`;
  if (h > 0) return `${h}h${m}m`;
  return `${m}m`;
}

/** Usage-pace accent (PianoMan's rule): a window grants `windowSecs` of runway;
 *  at `pct` used you have `(1−pct) × windowSecs` of budget-time left. If that
 *  exceeds the time until reset you're on pace (green); if it's behind, red. */
function paceAccent(pct?: number | null, iso?: string | number | null, windowSecs?: number): MAccent {
  if (pct == null || !windowSecs) return 'muted';
  const t = resetMs(iso);
  if (t == null) return 'muted';
  const timeUntilReset = (t - Date.now()) / 1000;
  if (timeUntilReset <= 0) return 'green';           // window is resetting
  const runway = windowSecs * (1 - Math.min(100, Math.max(0, pct)) / 100);
  const ratio = runway / timeUntilReset;
  if (ratio >= 1.15) return 'green';                 // comfortably on pace
  if (ratio >= 1.0) return 'yellow';                 // on pace but tight
  return 'red';                                      // burning too fast — will exhaust early
}
const CLAUDE_5H_SECS = 5 * 3600;
const CLAUDE_7D_SECS = 7 * 86400;

/** Projected exhaustion time (epoch ms) if the current burn rate would hit 100%
 *  BEFORE the window resets; null if you're on pace to make it. Rate is observed
 *  over the elapsed part of the window: rate = pct / elapsed, time-to-100 =
 *  (100−pct)/rate. */
function projectedRunout(pct?: number | null, iso?: string | number | null, windowSecs?: number): number | null {
  if (pct == null || !windowSecs || pct <= 0) return null;
  const reset = resetMs(iso);
  if (reset == null) return null;
  const now = Date.now();
  const timeUntilReset = (reset - now) / 1000;
  if (timeUntilReset <= 0) return null;
  const elapsed = windowSecs - timeUntilReset;
  if (elapsed <= 0) return null;
  const rate = pct / elapsed;                       // %/sec observed so far
  const runoutMs = now + ((100 - pct) / rate) * 1000;
  return runoutMs < reset ? runoutMs : null;        // only if it beats the reset
}
/** Full date-time for a projected run-out, e.g. "Jul 5, 3:40 PM". */
function fmtRunout(ms: number): string {
  return new Date(ms).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

/** Worst accent wins, for a card that folds two paces into one. */
function worstAccent(a: MAccent, b: MAccent): MAccent {
  const rank: Record<MAccent, number> = { red: 4, yellow: 3, green: 2, blue: 1, cyan: 1, muted: 0 };
  return rank[a] >= rank[b] ? a : b;
}
/** sysmon severity → accent for the active-events strip. */
/** Plain-language explanation of each sysmon event tier (1.1). Severity/precedence
 *  rises assessment → alert → episode; the higher tier supersedes lower tiers of
 *  the same kind. */
const KIND_EXPLAIN: Record<string, string> = {
  assessment: 'Assessment — an ongoing synthesized concern about a subsystem (e.g. memory), severity-voted from multiple signals. The mildest tier; clears when the signals stop.',
  alert: 'Alert — a specific rule that fired on a metric crossing a threshold or trend (e.g. swap_growth). More acute than an assessment.',
  episode: 'Episode — a sustained incident with a start (and eventual end) tracked over time. The highest tier; supersedes same-kind alerts and assessments.',
};
const EVENTS_LEGEND =
  'Active sysmon events, worst first. Tiers (low→high): Assessment (ongoing concern) → Alert (a fired rule) → Episode (a sustained incident). A higher tier supersedes lower tiers of the same kind, so you see one row per condition.';

function severityAccent(sev: number): MAccent {
  if (sev >= 4) return 'red';
  if (sev >= 2) return 'yellow';
  return 'blue';
}

interface MonitorCard {
  id: string;
  label: string;
  value: ReactNode;
  accent: MAccent;
  sub?: ReactNode;              // small line under the value
  details: ReactNode;          // shown when the card is expanded
}

type SysMetrics = Awaited<ReturnType<typeof window.uai.systemMetrics>>;
type SysVolume = Awaited<ReturnType<typeof window.uai.diskVolumes>>[number];

// Top resource users shown per CPU/Memory card (PianoMan: 3 ≤ N ≤ 7, default 3;
// configurable here for now — a single knob to lift into settings later).
const TOP_N = 3;

type TopProc = NonNullable<SysMetrics['top_cpu_processes']>[number];

/** Tiny inline time-series graph (last 1h) for a gauge's details. Normalizes the
 *  series to its own min/max and stretches to the panel width. Falls back to a
 *  "collecting" note until there are ≥2 samples. */
function Sparkline({ points, accent = 'blue', label }: { points?: number[]; accent?: MAccent; label?: string }): JSX.Element {
  const pts = (points ?? []).filter(n => typeof n === 'number' && isFinite(n));
  if (pts.length < 2) return <div className="monitor-spark-label">Collecting history…</div>;
  const W = 100, H = 30;
  const min = Math.min(...pts), max = Math.max(...pts), range = (max - min) || 1;
  const step = W / (pts.length - 1);
  const d = pts.map((v, i) => `${i === 0 ? 'M' : 'L'}${(i * step).toFixed(1)},${(H - ((v - min) / range) * H).toFixed(1)}`).join(' ');
  const stroke = `var(--accent-${accent === 'muted' ? 'blue' : accent})`;
  return (
    <div className="monitor-spark">
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" aria-hidden="true">
        <path d={d} fill="none" stroke={stroke} strokeWidth={1.5} vectorEffect="non-scaling-stroke" strokeLinejoin="round" />
      </svg>
      {label && <div className="monitor-spark-label">{label}</div>}
    </div>
  );
}
type TokBucket = NonNullable<NonNullable<SysMetrics['claude_tokens']>['dtd']>;

/** Detail rows for the top-N users of a resource (skips sysmon's "(other)"
 *  aggregate bucket — not an actual process you can act on). */
function topProcRows(list: TopProc[] | undefined, kind: 'cpu' | 'mem'): ReactNode {
  const rows = (list ?? []).filter(p => p.pid > 0 && p.name !== '(other)').slice(0, TOP_N);
  if (!rows.length) return <div className="monitor-detail-note">No process data yet.</div>;
  return <>
    <div className="monitor-detail-note">Top {rows.length} by {kind === 'cpu' ? 'CPU' : 'memory'}</div>
    {rows.map(p => (
      <div key={p.pid}>
        <span title={`pid ${p.pid}`}>{p.name}</span>
        <b>{kind === 'cpu' ? `${p.cpu_pct.toFixed(0)}%` : `${p.phys_gb.toFixed(1)} GB`}</b>
      </div>
    ))}
  </>;
}

function SystemMonitorTab({ onOpenTab }: { onOpenTab?: (tabId: string) => void }): JSX.Element {
  const [metrics, setMetrics] = useState<SysMetrics | null>(null);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [volumes, setVolumes] = useState<SysVolume[] | null>(null);
  const [boots, setBoots] = useState<Array<{ when: string }> | null>(null);
  const [recentErrors, setRecentErrors] = useState<Array<{ ts: string; source: string; session: string; message: string }> | null>(null);

  useEffect(() => {
    const load = async () => {
      try { setMetrics(await window.uai.systemMetrics()); } catch { /* ignore */ }
    };
    load();
    const interval = setInterval(load, 2000);
    return () => clearInterval(interval);
  }, []);

  // Fetch mounted volumes on demand when the Disk card's details open.
  useEffect(() => {
    if (expanded === 'disk' && volumes === null) {
      window.uai.diskVolumes().then(setVolumes).catch(() => setVolumes([]));
    }
  }, [expanded, volumes]);

  // Fetch boot history when the Uptime card's details open.
  useEffect(() => {
    if (expanded === 'uptime' && boots === null) {
      window.uai.bootHistory(8).then(setBoots).catch(() => setBoots([]));
    }
  }, [expanded, boots]);

  // Fetch recent errors when the Errors card's details open (refresh each open).
  useEffect(() => {
    if (expanded === 'errors') {
      window.uai.getRecentErrors(10).then(setRecentErrors).catch(() => setRecentErrors([]));
    }
  }, [expanded]);

  if (!metrics) return <div className="bottom-panel-empty">Loading metrics...</div>;

  const mem = metrics;
  const diskUsed = mem.disk_used_pct;
  const load = mem.load_avg;
  const pace5h = paceAccent(mem.claude_5h_pct, mem.claude_5h_reset, CLAUDE_5H_SECS);
  const pace7d = paceAccent(mem.claude_7d_pct, mem.claude_7d_reset, CLAUDE_7D_SECS);
  const events = mem.sysmon_events ?? [];

  const cards: MonitorCard[] = [
    {
      id: 'cpu', label: 'CPU',
      value: `${mem.cpu_percent}%`,
      accent: mem.cpu_percent > 80 ? 'red' : mem.cpu_percent > 50 ? 'yellow' : 'green',
      sub: mem.cpu_avg_1h != null ? <span className="monitor-sub">avg {Math.round(mem.cpu_avg_1h)}% (1h)</span> : undefined,
      details: (
        <div className="monitor-detail-rows">
          <div><span>Current</span><b>{mem.cpu_percent}%</b></div>
          <div><span>Average (15m / 1h / 6h)</span><b>{
            [mem.cpu_avg_15m, mem.cpu_avg_1h, mem.cpu_avg_6h].every(v => v == null)
              ? '—' : [mem.cpu_avg_15m, mem.cpu_avg_1h, mem.cpu_avg_6h].map(v => v == null ? '—' : `${Math.round(v)}%`).join(' / ')
          }</b></div>
          <div><span>Load avg (1m / 5m / 15m)</span><b>{load ? load.map(n => n.toFixed(2)).join('  ') : '—'}</b></div>
          {topProcRows(mem.top_cpu_processes, 'cpu')}
          <Sparkline points={mem.sparks?.cpu} accent="blue" label="CPU %, last 1h" />
        </div>
      ),
    },
    {
      id: 'memory', label: 'Memory',
      value: `${gb(mem.mem_committed_gb)} / ${mem.mem_total_gb ?? '—'} GB`,
      accent: pressureAccent(mem.mem_pressure),
      sub: <span className={`monitor-pressure monitor-accent-${pressureAccent(mem.mem_pressure)}`}>pressure {mem.mem_pressure ?? '—'}</span>,
      details: (
        <div className="monitor-detail-rows">
          <div><span>Committed</span><b>{gb(mem.mem_committed_gb)}</b></div>
          <div><span>Total (physical)</span><b>{mem.mem_total_gb ?? '—'} GB</b></div>
          <div><span>Pressure</span><b>{mem.mem_pressure ?? '—'}</b></div>
          <div><span>memorystatus level</span><b>{mem.mem_level ?? '—'}</b></div>
          <div><span>Swap</span><b>{gb(mem.swap_gb)}</b></div>
          {topProcRows(mem.top_mem_processes, 'mem')}
          <Sparkline points={mem.sparks?.mem} accent="blue" label="Committed GB, last 1h" />
        </div>
      ),
    },
    {
      id: 'swap', label: 'Swap',
      value: gb(mem.swap_gb),
      accent: (mem.swap_gb ?? 0) > 2 ? 'yellow' : 'green',
      sub: <span className={`monitor-pressure monitor-accent-${pressureAccent(mem.mem_pressure)}`}>pressure {mem.mem_pressure ?? '—'}</span>,
      details: (
        <div className="monitor-detail-rows">
          <div><span>Swap used</span><b>{gb(mem.swap_gb)}</b></div>
          <div><span>Memory pressure</span><b>{mem.mem_pressure ?? '—'}</b></div>
          <div className="monitor-detail-note">Swap &gt; 2 GB with rising memory is what tips sysmon to [WARN].</div>
          <Sparkline points={mem.sparks?.swap} accent="yellow" label="Swap GB, last 1h" />
        </div>
      ),
    },
    {
      id: 'disk', label: 'Disk',
      value: diskUsed != null ? `${diskUsed}% used` : '—',
      accent: diskUsed == null ? 'muted' : diskUsed >= 90 ? 'red' : diskUsed >= 75 ? 'yellow' : 'green',
      sub: <span className="monitor-sub">{gb(mem.disk_free_gb)} free / {mem.disk_total_gb ?? '—'} GB</span>,
      details: (
        <div className="monitor-detail-rows">
          {/* Built-in volume from the sysmon container figure (matches the card;
              df's '/' would misleadingly read the sealed system volume). */}
          <div>
            <span>Built-in (Macintosh HD)</span>
            <b className={`monitor-accent-${(diskUsed ?? 0) >= 90 ? 'red' : (diskUsed ?? 0) >= 75 ? 'yellow' : 'green'}`}>
              {diskUsed != null ? `${diskUsed}%` : '—'} · {gb(mem.disk_free_gb)} free / {mem.disk_total_gb ?? '—'} GB
            </b>
          </div>
          {volumes === null ? <div className="monitor-detail-note">Loading attached volumes…</div>
            : volumes.length === 0 ? <div className="monitor-detail-note">No attached volumes.</div>
            : volumes.map(v => (
              <div key={v.mount}>
                <span title={v.fs}>{v.mount.replace('/Volumes/', '')}</span>
                <b className={`monitor-accent-${v.used_pct >= 90 ? 'red' : v.used_pct >= 75 ? 'yellow' : 'green'}`}>
                  {v.used_pct}% · {v.free_gb.toFixed(0)} free / {v.total_gb.toFixed(0)} GB
                </b>
              </div>
            ))}
          <Sparkline points={mem.sparks?.disk} accent={diskUsed != null && diskUsed >= 90 ? 'red' : 'green'} label="Built-in used %, last 1h" />
        </div>
      ),
    },
    {
      id: 'claude', label: 'Claude Usage',
      // Both windows on one card; accent = worse of the two paces.
      value: (
        <span>
          <span className={`monitor-accent-${pace5h}`}>5h {mem.claude_5h_pct != null ? `${Math.round(mem.claude_5h_pct)}%` : '—'}</span>
          <span className="monitor-accent-muted"> · </span>
          <span className={`monitor-accent-${pace7d}`}>7d {mem.claude_7d_pct != null ? `${Math.round(mem.claude_7d_pct)}%` : '—'}</span>
        </span>
      ),
      accent: worstAccent(pace5h, pace7d),
      sub: <span className="monitor-sub">resets {fmtCountdown(mem.claude_5h_reset)} / {fmtCountdown(mem.claude_7d_reset)}</span>,
      details: (
        <div className="monitor-detail-rows">
          <div><span>5-hour window used</span><b className={`monitor-accent-${pace5h}`}>{mem.claude_5h_pct != null ? `${mem.claude_5h_pct}%` : '—'}</b></div>
          <div><span>5h resets in</span><b>{fmtCountdown(mem.claude_5h_reset)} <span className="monitor-accent-muted">({fmtReset(mem.claude_5h_reset)})</span></b></div>
          <div><span>7-day window used</span><b className={`monitor-accent-${pace7d}`}>{mem.claude_7d_pct != null ? `${mem.claude_7d_pct}%` : '—'}</b></div>
          <div><span>7d resets in</span><b>{fmtCountdown(mem.claude_7d_reset)} <span className="monitor-accent-muted">({fmtReset(mem.claude_7d_reset)})</span></b></div>
          {(() => {
            const r5 = projectedRunout(mem.claude_5h_pct, mem.claude_5h_reset, CLAUDE_5H_SECS);
            const r7 = projectedRunout(mem.claude_7d_pct, mem.claude_7d_reset, CLAUDE_7D_SECS);
            return <>
              {r5 != null && <div><span>5h projected to run out</span><b className="monitor-accent-red">{fmtRunout(r5)}</b></div>}
              {r7 != null && <div><span>7d projected to run out</span><b className="monitor-accent-red">{fmtRunout(r7)}</b></div>}
            </>;
          })()}
          <Sparkline points={mem.sparks?.claude_7d} accent={pace7d} label="7d usage %, last 1h" />
          <div className="monitor-detail-note">Color reflects pace: green if your remaining budget outlasts the window, red if you're on track to exhaust it early. A projected run-out shows only when the current burn rate would hit 100% before the reset.</div>
          {mem.claude_5h_pct == null && <div className="monitor-detail-note">No data yet — updates once a Claude session renders its statusline.</div>}
        </div>
      ),
    },
    {
      id: 'tokens', label: 'Tokens',
      // Headline = today's (dtd) total; details break out all four windows.
      value: fmtTok(mem.claude_tokens?.dtd?.total),
      accent: 'cyan',
      sub: <span className="monitor-sub">itd {fmtTok(mem.claude_tokens?.itd?.total)}{mem.claude_tokens?.itd?.cost != null ? ` · ${fmtUsd(mem.claude_tokens.itd.cost)}` : ''}</span>,
      details: (() => {
        const t = mem.claude_tokens;
        if (!t || (!t.dtd && !t.itd)) return <div className="monitor-detail-note">No token data yet — accumulates as sessions run.</div>;
        const row = (label: string, b?: TokBucket) => (
          <div>
            <span>{label}{b?.since ? <span className="monitor-accent-muted"> · since {fmtReset(b.since)}</span> : ''}</span>
            <b>{fmtTok(b?.total)} <span className="monitor-accent-muted">({fmtTok(b?.in)} in / {fmtTok(b?.out)} out)</span>{b?.cost != null ? <span className="monitor-accent-green"> · {fmtUsd(b.cost)}</span> : ''}</b>
          </div>
        );
        return (
          <div className="monitor-detail-rows">
            {row('Today (dtd)', t.dtd)}
            {row('Week (wtd)', t.wtd)}
            {row('Month (mtd)', t.mtd)}
            {row('Year (ytd)', t.ytd)}
            {row('Inception (itd)', t.itd)}
            <Sparkline points={mem.claude_tokens ? mem.sparks?.tokens : undefined} accent="cyan" label="Cumulative tokens, last 1h" />
            <div className="monitor-detail-note">Overall tokens across all Claude sessions, delta-accumulated. Each window shows what it's counted since it began (itd = ledger inception). Cost is the API-equivalent, cache-aware figure Claude Code reports (accurate even on a flat-rate plan) — not a token×price estimate.</div>
          </div>
        );
      })(),
    },
    {
      id: 'sessions', label: 'Sessions',
      value: `${mem.active_sessions}`, accent: 'cyan',
      details: <div className="monitor-detail-rows"><div><span>Active (running) sessions</span><b>{mem.active_sessions}</b></div></div>,
    },
    {
      id: 'errors', label: 'Errors',
      value: `${mem.error_count}`, accent: mem.error_count > 0 ? 'red' : 'green',
      details: (
        <div className="monitor-detail-rows">
          <div><span>Errors logged this app session</span><b>{mem.error_count}</b></div>
          {recentErrors === null ? <div className="monitor-detail-note">Loading recent errors…</div>
            : recentErrors.length === 0 ? <div className="monitor-detail-note">No errors recorded.</div>
            : <>
                <div className="monitor-detail-note">Recent errors — click to open the Errors log</div>
                {recentErrors.map((e, i) => (
                  <button
                    key={i}
                    className="monitor-error-row"
                    title={`${e.source} · ${e.session || 'unknown'}\n${e.message}\n\nClick to open the Errors log`}
                    onClick={() => onOpenTab?.('error_log')}
                  >
                    <span className="monitor-error-src">{e.source}</span>
                    <span className="monitor-error-msg">{e.message}</span>
                  </button>
                ))}
              </>}
        </div>
      ),
    },
    {
      id: 'uptime', label: 'Uptime',
      value: fmtUptime(mem.system_uptime_seconds), accent: 'blue',
      details: (
        <div className="monitor-detail-rows">
          <div><span>System uptime</span><b>{fmtUptime(mem.system_uptime_seconds)}</b></div>
          <div><span>App uptime</span><b>{fmtUptime(mem.uptime_seconds)}</b></div>
          <div className="monitor-detail-note">Recent bootups</div>
          {boots === null ? <div className="monitor-detail-note">Loading boot history…</div>
            : boots.length === 0 ? <div className="monitor-detail-note">No boot history.</div>
            : boots.map((b, i) => (
              <div key={i}><span>{i === 0 ? 'Current boot' : `Boot −${i}`}</span><b>{b.when}</b></div>
            ))}
        </div>
      ),
    },
  ];

  const expandedCard = cards.find(c => c.id === expanded);

  return (
    <div className="bottom-panel-monitor">
      {/* Overall sysmon status banner — matches the `sysmon status` header. */}
      <div className={`monitor-status-banner monitor-status-${statusAccent(mem.sysmon_status)}`}>
        <span className="monitor-status-dot" />
        <span className="monitor-status-label">
          {mem.sysmon_status ? mem.sysmon_status.toUpperCase() : 'system'}
        </span>
        {mem.sysmon_summary && <span className="monitor-status-summary">{mem.sysmon_summary}</span>}
        {mem.sysmon_stale && <span className="monitor-status-stale" title="sysmon summary is stale">⚠ stale</span>}
      </div>

      {/* Active sysmon events — episode/alert/assessment, worst first, with
          same-kind lower tiers suppressed (see readSysmonEvents). */}
      {events.length > 0 && (
        <div className="monitor-events">
          <div className="monitor-events-head">
            <span className="monitor-events-title">Active events</span>
            <span className="monitor-events-help" title={EVENTS_LEGEND}>ⓘ</span>
          </div>
          {events.map((e, i) => {
            // Chronic (updated ≠ since) reads "since X · updated Y"; fresh shows one time.
            const timeStr = e.updated && e.since && e.updated !== e.since
              ? `since ${e.since} · updated ${e.updated}`
              : (e.since || e.updated || '');
            return (
              <div
                key={i}
                className={`monitor-event monitor-event-${severityAccent(e.severity)}`}
                title={`${KIND_EXPLAIN[e.kind] || e.kind}${timeStr ? `\n\n${timeStr}` : ''}`}
              >
                <span className="monitor-event-dot" />
                <span className="monitor-event-kind">{e.kind}</span>
                <span className="monitor-event-msg">{e.message}</span>
                {timeStr && <span className="monitor-event-since">{timeStr}</span>}
              </div>
            );
          })}
        </div>
      )}

      <div className="monitor-grid">
        {cards.map(c => (
          <button
            key={c.id}
            className={`monitor-card monitor-card-clickable${expanded === c.id ? ' expanded' : ''}`}
            onClick={() => setExpanded(expanded === c.id ? null : c.id)}
            title="Click for details"
          >
            <div className="monitor-card-label">{c.label}</div>
            <div className={`monitor-card-value monitor-accent-${c.accent}`}>{c.value}</div>
            {c.sub && <div className="monitor-card-sub">{c.sub}</div>}
          </button>
        ))}
      </div>

      {expandedCard && (
        <div className="monitor-details">
          <div className="monitor-details-title">{expandedCard.label}</div>
          {expandedCard.details}
        </div>
      )}
    </div>
  );
}

// ─── Log Setup Form ────────────────────────────────────────────────────

const PRESET_SCHEMAS: { label: string; desc: string; getPath: (aiRoot: string) => string; schema: LogFileSchema }[] = [
  {
    label: 'Activity Log',
    desc: 'App-wide activity events',
    getPath: (r) => `${r}/ai_general/data/activity_log.jsonl`,
    schema: { format: 'jsonl', timestampField: 'ts', levelField: 'event', displayFields: ['session', 'event', 'payload'] },
  },
  {
    label: 'Audit Log (today)',
    desc: 'Comms audit events for today',
    getPath: (r) => `${r}/ai_general/data/audit/comms/events/${new Date().toISOString().slice(0, 10)}.jsonl`,
    schema: { format: 'jsonl', timestampField: 'ts' },
  },
  {
    label: 'Tool Events (today)',
    desc: 'Tool use audit events for today',
    getPath: (r) => `${r}/ai_general/data/audit/tools/events/${new Date().toISOString().slice(0, 10)}.jsonl`,
    schema: { format: 'jsonl', timestampField: 'ts' },
  },
  {
    label: 'User Prompts',
    desc: 'Cross-session user prompt log',
    getPath: (r) => `${r}/ai_general/data/audit/user_prompts.jsonl`,
    schema: { format: 'jsonl', timestampField: 'ts' },
  },
  {
    label: 'Hook Events',
    desc: 'Hook dispatch events for a session',
    getPath: () => '',
    schema: { format: 'jsonl', timestampField: 'ts' },
  },
];

function LogSetupForm({ tabId, initialLabel, aiRoot, onConfigure, onCancel }: {
  tabId: string;
  initialLabel: string;
  aiRoot: string;
  onConfigure: (tabId: string, label: string, filePath: string, schema?: LogFileSchema) => void;
  onCancel: () => void;
}): JSX.Element {
  const [filePath, setFilePath] = useState('');
  const [format, setFormat] = useState<'text' | 'jsonl'>('jsonl');
  const [tsField, setTsField] = useState('ts');
  const [levelField, setLevelField] = useState('');
  const [label, setLabel] = useState(initialLabel);
  const pathRef = useRef<HTMLInputElement>(null);

  useEffect(() => { setTimeout(() => pathRef.current?.focus(), 100); }, []);

  const handlePreset = (preset: typeof PRESET_SCHEMAS[0]) => {
    const path = preset.getPath(aiRoot);
    if (!path) {
      setFormat(preset.schema.format as 'text' | 'jsonl');
      setTsField(preset.schema.timestampField || 'ts');
      setLabel(preset.label);
      return;
    }
    onConfigure(tabId, preset.label, path, preset.schema);
  };

  const handleSubmit = () => {
    if (!filePath.trim()) return;
    const schema: LogFileSchema | undefined = format === 'jsonl'
      ? { format: 'jsonl', timestampField: tsField || undefined, levelField: levelField || undefined }
      : { format: 'text' };
    onConfigure(tabId, label || filePath.split('/').pop() || 'Log', filePath.trim(), schema);
  };

  return (
    <div className="log-setup-form">
      <div className="log-setup-section">
        <div className="log-setup-section-label">Presets</div>
        <div className="log-setup-presets">
          {PRESET_SCHEMAS.filter(p => p.getPath(aiRoot)).map(p => (
            <button key={p.label} className="log-setup-preset" onClick={() => handlePreset(p)} title={p.desc}>
              {p.label}
            </button>
          ))}
        </div>
      </div>
      <div className="log-setup-divider">or configure manually</div>
      <div className="log-setup-section">
        <div className="log-setup-row">
          <label className="log-setup-label">Tab name</label>
          <input className="log-setup-input" value={label} onChange={e => setLabel(e.target.value)} placeholder="My Log" />
        </div>
        <div className="log-setup-row">
          <label className="log-setup-label">File path</label>
          <input ref={pathRef} className="log-setup-input log-setup-input-path" value={filePath} onChange={e => setFilePath(e.target.value)} placeholder="/path/to/file.log or .jsonl" spellCheck={false} onKeyDown={e => { if (e.key === 'Enter') handleSubmit(); }} />
        </div>
        <div className="log-setup-row">
          <label className="log-setup-label">Format</label>
          <div className="log-setup-toggle-group">
            <button className={`log-setup-toggle${format === 'text' ? ' active' : ''}`} onClick={() => setFormat('text')}>Text</button>
            <button className={`log-setup-toggle${format === 'jsonl' ? ' active' : ''}`} onClick={() => setFormat('jsonl')}>JSONL</button>
          </div>
        </div>
        {format === 'jsonl' && (
          <>
            <div className="log-setup-row">
              <label className="log-setup-label">Timestamp field</label>
              <input className="log-setup-input log-setup-input-sm" value={tsField} onChange={e => setTsField(e.target.value)} placeholder="ts" />
            </div>
            <div className="log-setup-row">
              <label className="log-setup-label">Level field</label>
              <input className="log-setup-input log-setup-input-sm" value={levelField} onChange={e => setLevelField(e.target.value)} placeholder="level (optional)" />
            </div>
          </>
        )}
      </div>
      <div className="log-setup-actions">
        <button className="log-setup-btn log-setup-btn-primary" onClick={handleSubmit} disabled={!filePath.trim()}>Start Watching</button>
        <button className="log-setup-btn" onClick={onCancel}>Cancel</button>
      </div>
    </div>
  );
}
