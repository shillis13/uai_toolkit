/**
 * PromptLogTab — Bottom panel tab for viewing user_prompts.jsonl.
 *
 * Auto-updates via logTail file watcher. Provides filtering by:
 * - Date range (defaults to last 2 days)
 * - Session name (multi-select combo dropdown)
 * - Platform / AI type (multi-select)
 *
 * Platform indicated by colored left border (no label column).
 * Session names get stable distinct colors via hash.
 * Single-line entries with tooltip preview and click-to-expand.
 * 30-minute gaps get a visual separator.
 * Session name is clickable to open the session tab.
 */

import { useState, useEffect, useCallback, useRef, useMemo } from 'react';
import { executeCommand } from '../utils/execute-command';
import { sessionColor } from '../utils/session-color';

// ─── Types ──────────────────────────────────────────────────────────────

interface PromptEntry {
  ts: string;
  tracking_id: string;
  session_name: string;
  platform: string;
  prompt_preview: string;
  prompt_length: number;
  cwd?: string;
}

// ─── Constants ──────────────────────────────────────────────────────────

const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-blue)',
};

const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude',
  codex_cli: 'Codex',
  gemini_cli: 'Gemini',
};

function daysAgo(n: number): string {
  const d = new Date();
  d.setDate(d.getDate() - n);
  return d.toISOString().slice(0, 10);
}

function formatTime(ts: string): string {
  try {
    const d = new Date(ts);
    return d.toLocaleString(undefined, {
      month: 'short', day: 'numeric',
      hour: '2-digit', minute: '2-digit', second: '2-digit',
    });
  } catch {
    return ts.slice(0, 19);
  }
}

const GAP_THRESHOLD_MS = 30 * 60 * 1000; // 30 minutes

// ─── Multi-Select Dropdown ──────────────────────────────────────────────

function MultiSelectDropdown({ label, options, selected, onToggle, colorFn }: {
  label: string;
  options: string[];
  selected: Set<string>;
  onToggle: (value: string) => void;
  colorFn?: (value: string) => string;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const btnRef = useRef<HTMLButtonElement>(null);
  const menuRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const dismiss = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node) &&
          btnRef.current && !btnRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    };
    setTimeout(() => document.addEventListener('mousedown', dismiss), 0);
    return () => document.removeEventListener('mousedown', dismiss);
  }, [open]);

  const activeCount = selected.size;

  // Compute fixed position from button rect
  const menuStyle = useMemo((): React.CSSProperties => {
    if (!open || !btnRef.current) return {};
    const rect = btnRef.current.getBoundingClientRect();
    return {
      position: 'fixed',
      left: rect.left,
      bottom: window.innerHeight - rect.top + 4,
      zIndex: 9999,
    };
  }, [open]);

  return (
    <div className="prompt-log-dropdown">
      <button
        ref={btnRef}
        className={`prompt-log-dropdown-btn${activeCount > 0 ? ' active' : ''}`}
        onClick={() => setOpen(v => !v)}
      >
        {label}{activeCount > 0 ? ` (${activeCount})` : ''} {open ? '\u25B4' : '\u25BE'}
      </button>
      {open && (
        <div ref={menuRef} className="prompt-log-dropdown-menu" style={menuStyle}>
          {options.length === 0 && (
            <div className="prompt-log-dropdown-empty">No options</div>
          )}
          {options.map(opt => (
            <label key={opt} className="prompt-log-dropdown-option">
              <input
                type="checkbox"
                checked={selected.has(opt)}
                onChange={() => onToggle(opt)}
              />
              <span style={{ color: colorFn ? colorFn(opt) : 'var(--text)' }}>
                {opt}
              </span>
            </label>
          ))}
          {activeCount > 0 && (
            <button
              className="prompt-log-dropdown-clear"
              onClick={() => { for (const v of selected) onToggle(v); }}
            >
              Clear all
            </button>
          )}
        </div>
      )}
    </div>
  );
}

// ─── PromptLogTab ───────────────────────────────────────────────────────

interface PromptLogTabProps {
  filePath: string;
}

// ─── Prompt Area / Draft Sections ──────────────────────────────────────

interface PromptAreaEntry {
  tracking_id: string;
  session_name: string;
  platform: string;
  prompt_text: string;
}

interface PromptDraftEntry {
  tracking_id: string;
  session_name: string;
  platform: string;
  draft: string;
}

function PromptAreaSection({ areas, onGoToSession }: { areas: PromptAreaEntry[]; onGoToSession: (trackingId: string, name: string) => void }): JSX.Element {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div className="prompt-section">
      <div className="prompt-section-header" onClick={() => setCollapsed(v => !v)}>
        <span className="prompt-section-chevron">{collapsed ? '\u25B6' : '\u25BC'}</span>
        <span className="prompt-section-title">Active Prompt Areas</span>
        <span className="prompt-section-count">{areas.length}</span>
      </div>
      {!collapsed && (
        <div className="prompt-section-body">
          {areas.length === 0 ? (
            <div className="prompt-section-empty">No active sessions have pending input</div>
          ) : areas.map(a => (
            <div key={a.tracking_id} className="prompt-section-row">
              <span className="prompt-section-dot" style={{ background: PLATFORM_COLORS[a.platform] || 'var(--text-muted)' }} />
              <span className="prompt-section-name" onClick={() => onGoToSession(a.tracking_id, a.session_name)} title={`Open ${a.session_name}`}>{a.session_name || a.tracking_id.slice(0, 16)}</span>
              <span className="prompt-section-text" title={a.prompt_text}>{a.prompt_text}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function PromptDraftSection({ drafts, onGoToSession }: { drafts: PromptDraftEntry[]; onGoToSession: (trackingId: string, name: string) => void }): JSX.Element {
  const [collapsed, setCollapsed] = useState(false);
  return (
    <div className="prompt-section">
      <div className="prompt-section-header" onClick={() => setCollapsed(v => !v)}>
        <span className="prompt-section-chevron">{collapsed ? '\u25B6' : '\u25BC'}</span>
        <span className="prompt-section-title">Prompt Box Drafts</span>
        <span className="prompt-section-count">{drafts.length}</span>
      </div>
      {!collapsed && (
        <div className="prompt-section-body">
          {drafts.length === 0 ? (
            <div className="prompt-section-empty">No prompt box drafts</div>
          ) : drafts.map(d => (
            <div key={d.tracking_id} className="prompt-section-row">
              <span className="prompt-section-dot" style={{ background: PLATFORM_COLORS[d.platform] || 'var(--text-muted)' }} />
              <span className="prompt-section-name" onClick={() => onGoToSession(d.tracking_id, d.session_name)} title={`Open ${d.session_name}`}>{d.session_name || d.tracking_id.slice(0, 16)}</span>
              <span className="prompt-section-text" title={d.draft}>{d.draft}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

// ─── PromptLogTab (main) ──────────────────────────────────────────────

export default function PromptLogTab({ filePath }: PromptLogTabProps): JSX.Element {
  const [entries, setEntries] = useState<PromptEntry[]>([]);
  const [dateFrom, setDateFrom] = useState(daysAgo(2));
  const [dateTo, setDateTo] = useState('');
  const [selectedSessions, setSelectedSessions] = useState<Set<string>>(new Set());
  const [selectedPlatforms, setSelectedPlatforms] = useState<Set<string>>(new Set());
  const [textSearch, setTextSearch] = useState('');
  const [autoScroll, setAutoScroll] = useState(true);
  const [expandedIdx, setExpandedIdx] = useState<number | null>(null);
  const [tooltipIdx, setTooltipIdx] = useState<number | null>(null);
  const [contextMenu, setContextMenu] = useState<{ x: number; y: number; entry: PromptEntry } | null>(null);
  const bodyRef = useRef<HTMLDivElement>(null);
  const tailIdRef = useRef(`prompts_${Date.now()}`);
  const tooltipTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  // ── Prompt areas + drafts state ──
  const [promptAreas, setPromptAreas] = useState<PromptAreaEntry[]>([]);
  const [promptDrafts, setPromptDrafts] = useState<PromptDraftEntry[]>([]);

  // Poll prompt areas every 5 seconds
  useEffect(() => {
    let cancelled = false;
    const fetchAreas = async () => {
      try {
        const areas = await window.uai.prompts.getPromptAreas();
        if (!cancelled) setPromptAreas(areas || []);
      } catch { /* ignore */ }
    };
    fetchAreas();
    const interval = setInterval(fetchAreas, 5000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  // Load prompt box drafts from sessionPrefs
  useEffect(() => {
    let cancelled = false;
    const fetchDrafts = async () => {
      try {
        const [appState, sessions] = await Promise.all([
          window.uai.appState.get(),
          window.uai.sessions.list(),
        ]);
        if (cancelled) return;
        const prefs = (appState.sessionPrefs || {}) as Record<string, { promptDraft?: string }>;
        const sessionMap = new Map<string, { display_name: string; platform: string }>();
        for (const s of sessions) {
          sessionMap.set(s.tracking_id, { display_name: s.display_name || s.tracking_id.slice(0, 16), platform: s.platform });
        }
        const drafts: PromptDraftEntry[] = [];
        for (const [tid, pref] of Object.entries(prefs)) {
          if (pref.promptDraft && pref.promptDraft.trim()) {
            const sess = sessionMap.get(tid);
            drafts.push({
              tracking_id: tid,
              session_name: sess?.display_name || tid.slice(0, 16),
              platform: sess?.platform || '',
              draft: pref.promptDraft.trim(),
            });
          }
        }
        setPromptDrafts(drafts);
      } catch { /* ignore */ }
    };
    fetchDrafts();
    const interval = setInterval(fetchDrafts, 10000);
    return () => { cancelled = true; clearInterval(interval); };
  }, []);

  const goToSessionById = useCallback((trackingId: string, label: string) => {
    executeCommand('workspace.tabs.open', { type: 'session', targetId: trackingId, label });
  }, []);

  // Build a lookup from CLI UUID → session info
  const sessionLookup = useMemo(() => {
    const map = new Map<string, { tracking_id: string; display_name: string; platform: string }>();
    try {
      // sessions may be available from window.uai — but we're not in a hook context.
      // We'll populate this lazily from parsed entries that resolve.
    } catch { /* ignore */ }
    return map;
  }, []);

  // Resolve session info from CLI UUID via the app's session list
  const resolveSession = useCallback(async (cliUuid: string): Promise<{ tracking_id: string; display_name: string; platform: string } | null> => {
    if (sessionLookup.has(cliUuid)) return sessionLookup.get(cliUuid)!;
    try {
      const sessions = await window.uai.sessions.list();
      for (const s of sessions) {
        if (s.cli_session_id) {
          sessionLookup.set(s.cli_session_id, {
            tracking_id: s.tracking_id,
            display_name: s.display_name || s.tracking_id.slice(0, 20),
            platform: s.platform,
          });
        }
      }
      return sessionLookup.get(cliUuid) || null;
    } catch { return null; }
  }, [sessionLookup]);

  // Parse JSONL lines — supports both history.jsonl (native) and user_prompts.jsonl (legacy)
  const parseLines = useCallback((lines: string[]): PromptEntry[] => {
    const parsed: PromptEntry[] = [];
    for (const line of lines) {
      if (!line.trim()) continue;
      try {
        const obj = JSON.parse(line);

        // Native Claude Code history.jsonl: {display, timestamp, sessionId, project}
        if (obj.display !== undefined && obj.timestamp !== undefined) {
          const text = obj.display || '';
          const ts = new Date(obj.timestamp).toISOString();
          const cliUuid = obj.sessionId || '';
          // Look up session info synchronously from cache
          const cached = sessionLookup.get(cliUuid);
          parsed.push({
            ts,
            tracking_id: cached?.tracking_id || cliUuid.slice(0, 20),
            session_name: cached?.display_name || '',
            platform: cached?.platform || 'claude_cli',
            prompt_preview: text,
            prompt_length: text.length,
            cwd: obj.project,
          });
          continue;
        }

        // Legacy user_prompts.jsonl: {ts, tracking_id, session_name, platform, ...}
        if (obj.ts && obj.tracking_id) {
          parsed.push({
            ts: obj.ts,
            tracking_id: obj.tracking_id,
            session_name: obj.session_name || '',
            platform: obj.platform || '',
            prompt_preview: obj.prompt_preview || '',
            prompt_length: obj.prompt_length || 0,
            cwd: obj.cwd,
          });
        }
      } catch { /* skip malformed */ }
    }
    return parsed;
  }, [sessionLookup]);

  // Start tailing — pre-populate session lookup, then parse
  useEffect(() => {
    const tailId = tailIdRef.current;
    let unsubscribe: (() => void) | null = null;

    (async () => {
      // Pre-populate session lookup from all known sessions
      try {
        const sessions = await window.uai.sessions.list();
        for (const s of sessions) {
          if (s.cli_session_id) {
            sessionLookup.set(s.cli_session_id, {
              tracking_id: s.tracking_id,
              display_name: s.display_name || s.tracking_id.slice(0, 20),
              platform: s.platform,
            });
          }
        }
      } catch { /* ignore */ }

      try {
        const result = await window.uai.logTail.start(tailId, filePath);
        if (result.ok && result.lines) {
          setEntries(parseLines(result.lines));
        }
      } catch { /* file may not exist yet */ }

      unsubscribe = window.uai.logTail.onData((id, lines) => {
        if (id !== tailId) return;
        const newEntries = parseLines(lines);
        if (newEntries.length > 0) {
          setEntries(prev => [...prev, ...newEntries]);
        }
      });
    })();

    return () => {
      window.uai.logTail.stop(tailId).catch(() => {});
      unsubscribe?.();
    };
  }, [filePath, parseLines, sessionLookup]);

  // Auto-scroll
  useEffect(() => {
    if (autoScroll && bodyRef.current) {
      bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
    }
  });

  const handleScroll = useCallback(() => {
    if (!bodyRef.current) return;
    const el = bodyRef.current;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    setAutoScroll(atBottom);
  }, []);

  // Dismiss context menu on outside click
  useEffect(() => {
    if (!contextMenu) return;
    const dismiss = () => setContextMenu(null);
    setTimeout(() => document.addEventListener('mousedown', dismiss), 0);
    return () => document.removeEventListener('mousedown', dismiss);
  }, [contextMenu]);

  // Base filter: date + text search (shared by all downstream filters)
  const baseFiltered = useMemo(() => {
    return entries.filter(e => {
      const dateStr = e.ts.slice(0, 10);
      if (dateFrom && dateStr < dateFrom) return false;
      if (dateTo && dateStr > dateTo) return false;
      if (textSearch) {
        const q = textSearch.toLowerCase();
        if (!e.prompt_preview.toLowerCase().includes(q) &&
            !e.session_name.toLowerCase().includes(q) &&
            !e.tracking_id.toLowerCase().includes(q)) return false;
      }
      return true;
    });
  }, [entries, dateFrom, dateTo, textSearch]);

  // Session dropdown options: base + platform filter, but NOT session filter
  const sessionNames = useMemo(() => {
    const names = new Set<string>();
    for (const e of baseFiltered) {
      if (selectedPlatforms.size > 0 && !selectedPlatforms.has(e.platform)) continue;
      names.add(e.session_name || e.tracking_id.slice(0, 20));
    }
    return Array.from(names).sort();
  }, [baseFiltered, selectedPlatforms]);

  // Platform dropdown options: base + session filter, but NOT platform filter
  const platforms = useMemo(() => {
    const plats = new Set<string>();
    for (const e of baseFiltered) {
      if (selectedSessions.size > 0) {
        const label = e.session_name || e.tracking_id.slice(0, 20);
        if (!selectedSessions.has(label)) continue;
      }
      if (e.platform) plats.add(e.platform);
    }
    return Array.from(plats).sort();
  }, [baseFiltered, selectedSessions]);

  // Final filtered: base + session + platform
  const filtered = useMemo(() => {
    return baseFiltered.filter(e => {
      if (selectedSessions.size > 0) {
        const label = e.session_name || e.tracking_id.slice(0, 20);
        if (!selectedSessions.has(label)) return false;
      }
      if (selectedPlatforms.size > 0 && !selectedPlatforms.has(e.platform)) return false;
      return true;
    });
  }, [baseFiltered, selectedSessions, selectedPlatforms]);

  const toggleSession = useCallback((name: string) => {
    setSelectedSessions(prev => {
      const next = new Set(prev);
      if (next.has(name)) next.delete(name); else next.add(name);
      return next;
    });
  }, []);

  const togglePlatform = useCallback((p: string) => {
    setSelectedPlatforms(prev => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p); else next.add(p);
      return next;
    });
  }, []);

  const goToSession = useCallback((entry: PromptEntry) => {
    const label = entry.session_name || entry.tracking_id.slice(0, 20);
    executeCommand('workspace.tabs.open', {
      type: 'session',
      targetId: entry.tracking_id,
      label,
    });
  }, []);

  const handleSessionClick = useCallback((e: React.MouseEvent, entry: PromptEntry) => {
    e.stopPropagation();
    goToSession(entry);
  }, [goToSession]);

  const handleContextMenu = useCallback((e: React.MouseEvent, entry: PromptEntry) => {
    e.preventDefault();
    e.stopPropagation();
    setContextMenu({ x: e.clientX, y: e.clientY, entry });
  }, []);

  const handleMouseEnterEntry = useCallback((idx: number) => {
    if (tooltipTimerRef.current) clearTimeout(tooltipTimerRef.current);
    tooltipTimerRef.current = setTimeout(() => setTooltipIdx(idx), 400);
  }, []);

  const handleMouseLeaveEntry = useCallback(() => {
    if (tooltipTimerRef.current) clearTimeout(tooltipTimerRef.current);
    tooltipTimerRef.current = null;
    setTooltipIdx(null);
  }, []);

  return (
    <div className="prompt-log-tab">
      {/* Active prompt areas + drafts */}
      <PromptAreaSection areas={promptAreas} onGoToSession={goToSessionById} />
      <PromptDraftSection drafts={promptDrafts} onGoToSession={goToSessionById} />

      {/* Filter bar */}
      <div className="prompt-log-filters">
        <label className="prompt-log-date-filter">
          <span className="prompt-log-filter-label">From</span>
          <input type="date" className="prompt-log-date-input" value={dateFrom} onChange={e => setDateFrom(e.target.value)} />
        </label>
        <label className="prompt-log-date-filter">
          <span className="prompt-log-filter-label">To</span>
          <input type="date" className="prompt-log-date-input" value={dateTo} onChange={e => setDateTo(e.target.value)} />
        </label>
        <MultiSelectDropdown
          label="Sessions"
          options={sessionNames}
          selected={selectedSessions}
          onToggle={toggleSession}
          colorFn={sessionColor}
        />
        <MultiSelectDropdown
          label="Platform"
          options={platforms}
          selected={selectedPlatforms}
          onToggle={togglePlatform}
          colorFn={(p) => PLATFORM_COLORS[p] || 'var(--text)'}
        />
        <input
          className="prompt-log-search"
          type="text"
          placeholder="Search prompts..."
          value={textSearch}
          onChange={e => setTextSearch(e.target.value)}
        />
        <span className="prompt-log-count">{filtered.length} / {entries.length}</span>
      </div>

      {/* Entries */}
      <div className="prompt-log-body" ref={bodyRef} onScroll={handleScroll}>
        {filtered.map((entry, idx) => {
          const platformColor = PLATFORM_COLORS[entry.platform] || 'var(--text-muted)';
          const sessionLabel = entry.session_name || entry.tracking_id.slice(0, 20);
          const sesColor = sessionColor(sessionLabel);
          const isExpanded = expandedIdx === idx;
          const showTooltip = tooltipIdx === idx && !isExpanded;

          // Gap detection
          let hasGap = false;
          if (idx > 0) {
            const prevTs = new Date(filtered[idx - 1].ts).getTime();
            const curTs = new Date(entry.ts).getTime();
            if (curTs - prevTs > GAP_THRESHOLD_MS) hasGap = true;
          }

          return (
            <div key={`${entry.ts}-${idx}`}>
              {hasGap && <div className="prompt-log-gap" />}
              <div
                className={`prompt-log-entry${isExpanded ? ' expanded' : ''}`}
                style={{ borderLeftColor: platformColor }}
                onClick={() => setExpandedIdx(isExpanded ? null : idx)}
                onContextMenu={(e) => handleContextMenu(e, entry)}
                onMouseEnter={() => handleMouseEnterEntry(idx)}
                onMouseLeave={handleMouseLeaveEntry}
              >
                <span className="prompt-log-time">{formatTime(entry.ts)}</span>
                <span
                  className="prompt-log-session"
                  style={{ color: sesColor }}
                  title={entry.tracking_id}
                  onClick={(e) => handleSessionClick(e, entry)}
                >
                  {sessionLabel}
                </span>
                {isExpanded ? (
                  <span className="prompt-log-expanded-text" onClick={(e) => e.stopPropagation()}>
                    <span className="prompt-log-collapse-chevron" onClick={() => setExpandedIdx(null)}>{'\u25B2'}</span>
                    <span className="prompt-log-selectable">{entry.prompt_preview}</span>
                    <span className="prompt-log-length" title="Prompt length">{entry.prompt_length} chars</span>
                  </span>
                ) : (
                  <span className="prompt-log-preview">{entry.prompt_preview}</span>
                )}
                {!isExpanded && (
                  <span className="prompt-log-length">{entry.prompt_length}</span>
                )}
                {/* Tooltip above the line */}
                {showTooltip && entry.prompt_preview.length > 80 && (
                  <div className="prompt-log-tooltip">{entry.prompt_preview}</div>
                )}
              </div>
            </div>
          );
        })}
        {filtered.length === 0 && entries.length > 0 && (
          <div className="prompt-log-empty">No prompts match current filters</div>
        )}
        {entries.length === 0 && (
          <div className="prompt-log-empty">No prompt data loaded</div>
        )}
      </div>

      {/* Context menu */}
      {contextMenu && (
        <div className="context-menu" style={{ position: 'fixed', left: contextMenu.x, top: contextMenu.y, zIndex: 1000 }}>
          <button className="context-menu-item" onClick={() => { goToSession(contextMenu.entry); setContextMenu(null); }}>
            Go to session
          </button>
          <button className="context-menu-item" onClick={() => { window.uai.clipboard.write(contextMenu.entry.prompt_preview); setContextMenu(null); }}>
            Copy prompt text
          </button>
          <button className="context-menu-item" onClick={() => { window.uai.clipboard.write(contextMenu.entry.tracking_id); setContextMenu(null); }}>
            Copy tracking ID
          </button>
        </div>
      )}

      {/* Live indicator */}
      {!autoScroll && (
        <button
          className="log-viewer-scroll-btn"
          onClick={() => {
            setAutoScroll(true);
            if (bodyRef.current) bodyRef.current.scrollTop = bodyRef.current.scrollHeight;
          }}
        >
          Live
        </button>
      )}
    </div>
  );
}
