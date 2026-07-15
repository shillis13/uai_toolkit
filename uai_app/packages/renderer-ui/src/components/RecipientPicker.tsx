/**
 * RecipientPicker — multi-select picker of messageable targets for the Prompt Box.
 *
 * Lists every messageable entity: individual sessions AND groups (teams/projects,
 * which expand to their member sessions on select). Selection is stored as session
 * tracking_ids; a group is "selected" when all its members are. Empty selection =
 * send to the current tab (the caller supplies that default).
 *
 * Session names render in their platform color with the platform glyph beside them
 * (matching the Navigator). Quick filters narrow the (often long) session list:
 * Active-only (running, not archived) and Open-only (has a tab) default ON; an
 * optional platform filter narrows further. The current tab's session is always
 * shown, regardless of filters, so you can never lose your default recipient.
 *
 * Rendered as a fixed-position popover (anchorStyle) so it escapes the workspace's
 * overflow clip, mirroring the config/flyout popovers.
 */

import { useEffect, useRef, useState, type CSSProperties } from 'react';
import type { Session } from '@uai/shared/types';
import { useAppStateStore } from '../stores';
import type { MentionTarget } from './PromptBox';

interface RecipientPickerProps {
  targets: MentionTarget[];
  getSession: (id: string) => Session | undefined;
  /** Currently-selected recipient tracking_ids. */
  selected: string[];
  /** The current tab's session — pinned to the top + labeled, always shown. */
  currentSessionId: string;
  onChange: (next: string[]) => void;
  onClose: () => void;
  anchorStyle?: CSSProperties;
}

// Platform glyph + color, matching the Navigator's canonical session badges.
const PLATFORM_ICONS: Record<string, string> = {
  claude_cli: '●',   // ● filled circle
  codex_cli: '■',    // ■ filled square
  gemini_cli: '◆',   // ◆ filled diamond
};
const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-cyan)',
};
// Gemini omitted from the filter row by request (unused platform).
const PLATFORM_ORDER: Array<keyof typeof PLATFORM_ICONS> = ['claude_cli', 'codex_cli'];

/** A session is "active" when its process is running and it isn't archived. */
function isActive(s: Session | undefined): boolean {
  return !!s && s.process_status === 'running' && !s.archived;
}

/** Colored activity dot per session state so you don't fire at a busy/blocked one. */
function activityDot(s: Session | undefined): { color: string; title: string } {
  if (!s) return { color: 'var(--text-muted)', title: 'unknown' };
  if (s.prompt_block) return { color: 'var(--accent-red)', title: 'prompt-blocked' };
  switch (s.activity_state) {
    case 'responding': return { color: 'var(--accent-cyan)', title: 'responding' };
    case 'blocked': return { color: 'var(--accent-red)', title: 'blocked' };
    case 'permission_prompt': return { color: 'var(--accent-purple)', title: 'permission prompt' };
    case 'error': return { color: 'var(--accent-red)', title: 'error' };
    case 'stopped': return { color: 'var(--text-muted)', title: 'stopped' };
    case 'idle': return { color: 'var(--accent-green)', title: 'idle' };
    default: return { color: 'var(--text-muted)', title: s.activity_state || 'unknown' };
  }
}

export default function RecipientPicker({
  targets, getSession, selected, currentSessionId, onChange, onClose, anchorStyle,
}: RecipientPickerProps): JSX.Element {
  const ref = useRef<HTMLDivElement>(null);
  const [filter, setFilter] = useState('');
  const [activeOnly, setActiveOnly] = useState(true);
  const [openOnly, setOpenOnly] = useState(true);
  // Empty set = all platforms. Otherwise, only the selected platforms show.
  const [platformSel, setPlatformSel] = useState<Set<string>>(new Set());
  const searchRef = useRef<HTMLInputElement>(null);

  const { appState } = useAppStateStore();
  // Sessions currently open in a tab.
  const openIds = new Set(
    (appState.tabs || []).filter((t) => t.type === 'session').map((t) => t.targetId),
  );

  useEffect(() => {
    const t = setTimeout(() => searchRef.current?.focus(), 0);
    const onDown = (e: MouseEvent) => {
      const el = e.target as HTMLElement;
      if (ref.current && !ref.current.contains(el) && !el.closest('.promptbox-recipients')) onClose();
    };
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose(); };
    const bind = setTimeout(() => {
      document.addEventListener('mousedown', onDown);
      document.addEventListener('keydown', onKey);
    }, 0);
    return () => {
      clearTimeout(t); clearTimeout(bind);
      document.removeEventListener('mousedown', onDown);
      document.removeEventListener('keydown', onKey);
    };
  }, [onClose]);

  const isSelected = (t: MentionTarget) =>
    t.memberIds.length > 0 && t.memberIds.every((id) => selected.includes(id));

  const toggle = (t: MentionTarget) => {
    if (isSelected(t)) onChange(selected.filter((id) => !t.memberIds.includes(id)));
    else onChange([...new Set([...selected, ...t.memberIds])]);
  };

  const togglePlatform = (p: string) => {
    setPlatformSel((prev) => {
      const next = new Set(prev);
      if (next.has(p)) next.delete(p); else next.add(p);
      return next;
    });
  };

  const q = filter.trim().toLowerCase();
  const match = (t: MentionTarget) => !q || t.label.toLowerCase().includes(q);
  const sessionIdOf = (t: MentionTarget) => t.memberIds[0];

  const groups = targets.filter((t) => t.kind !== 'session').filter(match)
    .sort((a, b) => a.label.localeCompare(b.label));

  const sessions = targets.filter((t) => t.kind === 'session').filter(match)
    .filter((t) => {
      const id = sessionIdOf(t);
      if (id === currentSessionId) return true;   // current tab is always available
      const s = getSession(id);
      if (activeOnly && !isActive(s)) return false;
      if (openOnly && !openIds.has(id)) return false;
      if (platformSel.size && !(s && platformSel.has(s.platform))) return false;
      return true;
    })
    .sort((a, b) => {
      if (sessionIdOf(a) === currentSessionId) return -1;
      if (sessionIdOf(b) === currentSessionId) return 1;
      return a.label.localeCompare(b.label);
    });

  // "Select all listed" acts on exactly the sessions currently visible (respects the
  // search box + Active/Open/platform filters), so you can narrow then bulk-select.
  const listedSessionIds = Array.from(new Set(sessions.flatMap((t) => t.memberIds)));
  const allListedSelected = listedSessionIds.length > 0 && listedSessionIds.every((id) => selected.includes(id));
  const someListedSelected = listedSessionIds.some((id) => selected.includes(id));
  const toggleAllListed = () => {
    if (allListedSelected) {
      const drop = new Set(listedSessionIds);
      onChange(selected.filter((id) => !drop.has(id)));
    } else {
      onChange([...new Set([...selected, ...listedSessionIds])]);
    }
  };

  return (
    <div className="promptbox-recipients-popover" ref={ref} role="dialog" aria-label="Choose recipients" style={anchorStyle}>
      <div className="promptbox-recipients-head">
        <span className="promptbox-recipients-title">{'→'} Recipients</span>
        <div className="promptbox-recipients-head-actions">
          {selected.length > 0 && (
            <button className="promptbox-recipients-clear" onClick={() => onChange([])} title="Clear — send to the current tab">
              Clear
            </button>
          )}
          <button className="promptbox-recipients-close" onClick={onClose} title="Close">{'×'}</button>
        </div>
      </div>
      <input
        ref={searchRef}
        className="promptbox-recipients-search"
        value={filter}
        placeholder="Filter sessions, teams, projects…"
        onChange={(e) => setFilter(e.target.value)}
      />
      <div className="promptbox-recipients-filters">
        <button
          className={`promptbox-recipients-fpill${activeOnly ? ' on' : ''}`}
          onClick={() => setActiveOnly((v) => !v)}
          title="Show only running, non-archived sessions"
        >Active</button>
        <button
          className={`promptbox-recipients-fpill${openOnly ? ' on' : ''}`}
          onClick={() => setOpenOnly((v) => !v)}
          title="Show only sessions open in a tab"
        >Open</button>
        <span className="promptbox-recipients-fsep" />
        {PLATFORM_ORDER.map((p) => (
          <button
            key={p}
            className={`promptbox-recipients-fplat${platformSel.has(p) ? ' on' : ''}`}
            onClick={() => togglePlatform(p)}
            title={p.replace('_cli', '')}
            style={{ color: PLATFORM_COLORS[p] }}
          >{PLATFORM_ICONS[p]}</button>
        ))}
      </div>
      {sessions.length > 1 && (
        <label className="promptbox-recipients-selectall" title="Select every session currently listed (respects the filters above)">
          <input
            type="checkbox"
            checked={allListedSelected}
            ref={(el) => { if (el) el.indeterminate = someListedSelected && !allListedSelected; }}
            onChange={toggleAllListed}
          />
          <span className="promptbox-recipients-name">Select all listed</span>
          <span className="promptbox-recipients-count">{listedSessionIds.length}</span>
        </label>
      )}
      <div className="promptbox-recipients-list">
        {groups.length === 0 && sessions.length === 0 && (
          <div className="promptbox-recipients-empty">No matching recipients.</div>
        )}
        {groups.length > 0 && <div className="promptbox-recipients-group-label">Teams &amp; Projects</div>}
        {groups.map((t) => (
          <label className="promptbox-recipients-row" key={`${t.kind}:${t.token}`}>
            <input type="checkbox" checked={isSelected(t)} onChange={() => toggle(t)} />
            <span className="promptbox-recipients-groupicon" title={t.kind}>{t.kind === 'team' ? '\u{1F465}' : '\u{1F4C1}'}</span>
            <span className="promptbox-recipients-name">{t.label}</span>
            <span className="promptbox-recipients-count">{t.count}</span>
          </label>
        ))}
        {sessions.length > 0 && groups.length > 0 && <div className="promptbox-recipients-group-label">Sessions</div>}
        {sessions.map((t) => {
          const s = getSession(sessionIdOf(t));
          const dot = activityDot(s);
          const isCurrent = sessionIdOf(t) === currentSessionId;
          const platform = s?.platform || '';
          const platColor = PLATFORM_COLORS[platform];
          return (
            <label className="promptbox-recipients-row" key={`session:${t.token}:${sessionIdOf(t)}`}>
              <input type="checkbox" checked={isSelected(t)} onChange={() => toggle(t)} />
              <span className="promptbox-recipients-dot" style={{ background: dot.color }} title={dot.title} />
              {platform && (
                <span className="promptbox-recipients-platicon" style={{ color: platColor }} title={platform.replace('_cli', '')}>
                  {PLATFORM_ICONS[platform] || '○'}
                </span>
              )}
              <span className="promptbox-recipients-name" style={platColor ? { color: platColor } : undefined}>{t.label}</span>
              {isCurrent && <span className="promptbox-recipients-current">current tab</span>}
            </label>
          );
        })}
      </div>
    </div>
  );
}
