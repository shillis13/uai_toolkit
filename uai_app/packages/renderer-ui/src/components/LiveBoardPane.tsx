/**
 * LiveBoardPane — the cross-session work landscape, in-app (the "Live Board" tab).
 *
 * The app surface for scripts/work/work_landscape.py: every session × its
 * reconciled activity_state × the todo it owns, plus the curated NEEDS PIANOMAN
 * list and the ownership gaps. This is Hamilton's board, finally with a view
 * instead of CLI-only.
 *
 * Opened as an `app`-type workspace tab (targetId: 'live-board') from
 * Navigator › Tools › Work, routed through TabContentPane's app switch.
 *
 * Data source: the `work.landscape` command (main process runs the script
 * --enrich --json and returns the model). Read-only — External Ground Truth.
 */

import { useState, useEffect, useCallback } from 'react';
import { executeCommand } from '../utils/execute-command';
import { TabNavArrows } from './TabNavArrows';
import { useViewport } from '../viewport';
import { useSessionStore } from '../stores/session-store';
import { getSessionStateVisual } from '../stores/session-state';
import { onActivityChange } from '../stores/session-activity';
import { TodoLink } from './RefLink';
import SessionLink, { isTrackingId } from './SessionLink';

interface LandTodo {
  id?: string;
  status?: string;
  title?: string;
  updated?: string;
  created?: string;
}

interface LandAssessment {
  state?: string;
  needs_pianoman?: boolean;
  open_question?: string | null;
  project_guess?: string | null;
}

interface LandRow {
  kind: 'session' | 'team' | 'project' | 'unassigned';
  name: string;
  tracking_id?: string;
  platform: string;
  status: string;
  activity_state: string;
  state_display: string;
  ago: string;
  last_activity?: string | null;   // raw ISO — default sort key
  roles: string[];
  todos: LandTodo[];
  assessment?: LandAssessment | null;
}

interface LandTotals {
  todos: number;
  todos_no_assignee: number;
  active_sessions: number;
  active_no_todo: number;
  needs_pm?: number;
}

// An escalated decision that genuinely needs PianoMan (todo_0578), filed by
// Hamilton via escalations_mgr; rendered in the "Needs You" panel.
interface PmDecision {
  id: string;
  decision: string;
  options?: string;
  recommendation?: string;
  source_todo?: string;
  source_session?: string;
  note?: string;
  created_at?: string;
}

interface LandscapeModel {
  rows: LandRow[];
  needs_pm?: PmDecision[];
  totals: LandTotals;
}

// The State column now derives from the SAME source of truth as Recent Sessions:
// the live session store × the canonical getSessionStateVisual() encoding. This
// kills the stale "Responding" (a session whose process has stopped reads
// Stopped, exactly as it does in Recent Sessions) and tracks state live via the
// session-store subscription instead of the periodic landscape snapshot.
//
// backendProcess maps the landscape row's registry `status` vocabulary
// ("active"/"stopped"/"exited") onto the store's process_status vocabulary
// ("running"/"stopped"/"exited") so the fallback path (no live session in the
// store) still runs through the canonical encoder.
function backendProcess(status: string | undefined): string {
  if (status === 'active') return 'running';
  if (status === 'exited') return 'exited';
  return 'stopped';
}

// Worker-kind badge — sessions are the default (no badge); teams/projects/the
// unassigned bucket get a small colored tag so the unified list reads clearly.
const KIND_BADGE: Record<string, { label: string; color: string } | null> = {
  session: null,
  team: { label: 'TEAM', color: 'var(--accent-purple)' },
  project: { label: 'PROJECT', color: 'var(--accent-cyan)' },
  unassigned: { label: 'BACKLOG', color: 'var(--text-muted)' },
};

const STATUS_CODE: Record<string, string> = {
  Triaging: 'TR', Needs_Research: 'NR', Needs_Derivation: 'ND', Ready: 'RD',
  In_Progress: 'IP', Reviewing: 'RV', Accepting: 'AC', Blocked: 'BL',
  Done: 'DN', Cancelled: 'CN',
};

// Human-readable work descriptor from a todo: the clean title (id prefix
// stripped), NOT the raw todo id. Fast path until sessions/Hamilton author a
// curated focus phrase (todo_0395).
function landTitle(t: LandTodo): string {
  const raw = (t.title && t.title.trim()) ? t.title : (t.id || '');
  const clean = raw.replace(/^(?:todo|task)_\d+_?/, '').replace(/_/g, ' ').trim();
  return clean || (t.id || '(untitled)');
}

// Order a session's todos so the CURRENT work surfaces first: In_Progress, then
// Reviewing/Blocked, then everything else; within a tier, most-recently-updated.
const _tier = (s?: string): number =>
  s === 'In_Progress' ? 0 : (s === 'Reviewing' || s === 'Blocked' || s === 'Accepting') ? 1 : 2;
function currentTodos(todos: LandTodo[]): LandTodo[] {
  return [...(todos || [])].sort((a, b) => {
    const p = _tier(a.status) - _tier(b.status);
    if (p) return p;
    return (b.updated || b.created || '').localeCompare(a.updated || a.created || '');
  });
}

const NEEDS_STATES = new Set(['blocked', 'permission_prompt']);

function needsPianoman(r: LandRow): boolean {
  if (r.assessment?.needs_pianoman) {
    return true;
  }
  return NEEDS_STATES.has(r.activity_state);
}

function needsReason(r: LandRow): string {
  const q = (r.assessment?.open_question || '').trim();
  if (q) {
    return q;
  }
  if (r.activity_state === 'permission_prompt') {
    return 'permission prompt — needs user';
  }
  if (r.activity_state === 'blocked') {
    return 'blocked — needs user';
  }
  return '(see session)';
}

// Live Board subviews (todo_0579). Tab-like, expandable — add a row here to add a
// tab. `board` = the cross-session table; `needs_me` = the PianoMan decisions.
type BoardTab = 'board' | 'needs_me';
const BOARD_TABS: { id: BoardTab; label: string }[] = [
  { id: 'board', label: 'Session Board' },
  { id: 'needs_me', label: 'Needs Me' },
];

// The "Needs Me" badge tracks which decisions PianoMan has already seen so it can
// show a new/updated count alongside the still-open count. The seen set persists
// across reloads so "new since I last looked" survives a refresh.
const SEEN_KEY = 'liveBoard.needsMe.seenIds';
function loadSeen(): Set<string> {
  try {
    return new Set(JSON.parse(localStorage.getItem(SEEN_KEY) || '[]'));
  } catch {
    return new Set();
  }
}
function saveSeen(ids: Set<string>): void {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify([...ids]));
  } catch {
    /* localStorage unavailable — badge just won't persist across reloads */
  }
}

// A decision's filed-at timestamp, formatted in local time (workspace convention:
// display local, never UTC), e.g. "Jul 18, 8:52 PM".
function formatWhen(iso?: string): string {
  if (!iso) return '';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });
}

export default function LiveBoardPane() {
  const [model, setModel] = useState<LandscapeModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Live session store — the State column reads from here so it behaves exactly
  // like Recent Sessions. Subscribing re-renders the board on any store change,
  // and onActivityChange catches the ephemeral in-app activity signals too.
  const { getSession, sessions } = useSessionStore();
  const [, forceUpdate] = useState(0);
  useEffect(() => onActivityChange(() => forceUpdate((n) => n + 1)), []);

  // A decision's source_session may be a display name ("Hardy") or a tracking id.
  // Resolve a name to its tracking id (case-insensitive over display_name/name) so
  // it can render as a clickable SessionLink; return null if we can't place it.
  const resolveSessionId = useCallback((ref?: string): string | null => {
    const v = (ref || '').trim();
    if (!v) return null;
    if (isTrackingId(v)) return v;
    const lc = v.toLowerCase();
    const hit = sessions.find((s) => (s.display_name || '').toLowerCase() === lc);
    return hit?.tracking_id || null;
  }, [sessions]);

  // Resolve a row's visual state the Recent-Sessions way: prefer the live
  // session (activity_state × process_status); fall back to the landscape row.
  const resolveVisual = useCallback((r: LandRow) => {
    const live = r.tracking_id ? getSession(r.tracking_id) : undefined;
    return live
      ? getSessionStateVisual(live.activity_state, live.process_status)
      : getSessionStateVisual(r.activity_state, backendProcess(r.status));
  }, [getSession]);

  // Answer-in-place for the "Needs Me" decisions panel (todo_0578).
  const [answerFor, setAnswerFor] = useState<string | null>(null);
  const [answerText, setAnswerText] = useState('');
  // Which decision cards have their Details (note) section expanded (todo_0579).
  const [expandedNotes, setExpandedNotes] = useState<Set<string>>(new Set());
  const toggleNote = useCallback((id: string) => {
    setExpandedNotes((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);

  // Which subview is showing, and the seen-decisions set behind the Needs Me
  // badge (todo_0579).
  const [activeTab, setActiveTab] = useState<BoardTab>('board');
  const [seen, setSeen] = useState<Set<string>>(() => loadSeen());

  const load = useCallback(async () => {
    setLoading(true);
    const res = await executeCommand<{ model: LandscapeModel }>('work.landscape', {}, { onFailure: 'log' });
    if (res.ok && res.data) {
      setModel(res.data.model);
      setError(null);
    } else {
      setError(res.error?.message || 'Failed to load landscape');
    }
    setLoading(false);
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  // Answer an escalated decision: marks it answered + routes the answer to
  // Hamilton, then reloads so it clears from the board (todo_0578).
  const submitAnswer = useCallback(async (id: string) => {
    const text = answerText.trim();
    if (!text) return;
    await executeCommand('work.decision.answer', { id, answer: text }, { onFailure: 'log' });
    setAnswerFor(null);
    setAnswerText('');
    load();
  }, [answerText, load]);

  // Dismiss/archive a decision as already-addressed (no routed answer, just a
  // light heads-up to Hamilton); then reload so it clears from the board (todo_0579).
  const dismissDecision = useCallback(async (id: string) => {
    await executeCommand('work.decision.dismiss', { id }, { onFailure: 'log' });
    setAnswerFor((cur) => (cur === id ? null : cur));
    load();
  }, [load]);

  // Default sort: most-recent activity first (raw last_activity ISO desc; rows
  // without a timestamp sink to the bottom).
  const rows = [...(model?.rows || [])].sort(
    (a, b) => (b.last_activity || '').localeCompare(a.last_activity || ''),
  );
  const totals = model?.totals;
  const needs = rows.filter(needsPianoman);
  const decisions = model?.needs_pm ?? [];

  // Needs Me badge counts: every open decision counts toward `open`; those PM
  // hasn't seen since last viewing the tab count toward `newCount`.
  const openCount = decisions.length;
  const newCount = decisions.filter((d) => !seen.has(d.id)).length;
  const decisionIdsKey = decisions.map((d) => d.id).join(',');

  // Viewing the Needs Me tab marks the currently-open decisions as seen (and
  // prunes ones that have since been answered), which resets the new count.
  useEffect(() => {
    if (activeTab !== 'needs_me') return;
    const current = new Set(decisions.map((d) => d.id));
    setSeen((prev) => {
      if (prev.size === current.size && [...current].every((id) => prev.has(id))) {
        return prev;
      }
      saveSeen(current);
      return current;
    });
    // decisionIdsKey stands in for the decisions array identity.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, decisionIdsKey]);

  // Viewport reporter — exposes the live board's rows/totals so the "Capture
  // Content" feature (describeViewport) shows the real landscape instead of an
  // empty dead node. Top ~20 rows summarized as inline children (session name +
  // state + current-work title). Refresh maps to the same work.landscape command
  // the Refresh button fires.
  useViewport('live_board', () => ({
    visible: true,
    label: 'Work — Live Board',
    state: {
      activeTab,
      rows: rows.length,
      needsPianoman: needs.length,
      needsMeOpen: openCount,
      needsMeNew: newCount,
      loading,
      error,
      activeSessions: totals?.active_sessions ?? null,
      activeNoTodo: totals?.active_no_todo ?? null,
      todos: totals?.todos ?? null,
      todosNoAssignee: totals?.todos_no_assignee ?? null,
    },
    actions: [
      { id: 'refresh', command: 'work.landscape', payload: {}, label: 'Refresh landscape' },
    ],
    children: rows.slice(0, 20).map((r) => {
      const top = currentTodos(r.todos)[0];
      return {
        id: `live_board.row.${r.tracking_id || r.name}`,
        label: r.name,
        visible: true,
        state: {
          state: resolveVisual(r).label,
          activity: r.ago,
          needsPianoman: needsPianoman(r),
          work: top ? landTitle(top) : null,
          workStatus: top?.status ?? null,
          todoCount: r.todos.length,
        },
        children: [],
      };
    }),
  }));

  return (
    <div style={{ height: '100%', overflow: 'auto', background: 'var(--bg-deep)', color: 'var(--text)', fontSize: 13 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '12px 16px', borderBottom: '1px solid var(--border)' }}>
        <TabNavArrows />
        <div style={{ fontWeight: 700, color: '#fff', fontSize: 14 }}>Work — cross-session landscape</div>
        <button
          onClick={load}
          disabled={loading}
          style={{ background: 'var(--accent-blue-bg)', border: '1px solid var(--accent-blue)', color: 'var(--text)', borderRadius: 6, padding: '4px 11px', fontSize: 12, cursor: 'pointer' }}
        >
          {loading ? 'Refreshing…' : 'Refresh'}
        </button>
        {totals && (
          <span style={{ marginLeft: 'auto', display: 'flex', gap: 16, color: 'var(--text-muted)', fontSize: 12 }}>
            <span title="active sessions whose work isn't linked to a todo">
              <span style={{ color: 'var(--accent-orange)', fontWeight: 700 }}>{totals.active_no_todo}</span>/{totals.active_sessions} no todo
            </span>
            <span title="todos with no assignee">
              <span style={{ color: 'var(--accent-orange)', fontWeight: 700 }}>{totals.todos_no_assignee}</span>/{totals.todos} no assignee
            </span>
          </span>
        )}
      </div>

      <div style={{ display: 'flex', gap: 2, padding: '0 12px', borderBottom: '1px solid var(--border)', background: 'var(--bg-panel, var(--bg-deep))' }}>
        {BOARD_TABS.map((t) => {
          const active = t.id === activeTab;
          return (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              style={{
                background: 'transparent',
                border: 'none',
                borderBottom: active ? '2px solid var(--accent-blue)' : '2px solid transparent',
                color: active ? 'var(--text)' : 'var(--text-muted)',
                fontWeight: active ? 700 : 500,
                fontSize: 13,
                padding: '9px 12px',
                cursor: 'pointer',
                display: 'inline-flex',
                alignItems: 'center',
                gap: 6,
              }}
            >
              {t.label}
              {t.id === 'needs_me' && (newCount > 0 || openCount > 0) && (
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4 }}>
                  {newCount > 0 && (
                    <span
                      title={`${newCount} new since you last looked`}
                      style={{ fontSize: 10.5, fontWeight: 800, color: '#fff', background: 'var(--accent-purple)', borderRadius: 9, padding: '1px 6px', lineHeight: '15px' }}
                    >{newCount} new</span>
                  )}
                  {openCount > 0 && (
                    <span
                      title={`${openCount} open (unaddressed) decision${openCount === 1 ? '' : 's'}`}
                      style={{ fontSize: 10.5, fontWeight: 700, color: 'var(--text-sec)', background: 'var(--bg-hover)', border: '1px solid var(--border)', borderRadius: 9, padding: '1px 6px', lineHeight: '15px' }}
                    >{openCount} open</span>
                  )}
                </span>
              )}
            </button>
          );
        })}
      </div>

      {error && (
        <div style={{ padding: '10px 16px', color: 'var(--accent-orange)', fontSize: 12 }}>⚠ {error}</div>
      )}

      {activeTab === 'needs_me' && (
        decisions.length > 0 ? (
        <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border)', background: 'var(--attention-bg, #160f0c)' }}>
          <div style={{ fontSize: 11, letterSpacing: '.05em', textTransform: 'uppercase', color: 'var(--accent-purple)', fontWeight: 700, marginBottom: 8 }}>
            ✋ Needs Me — Decisions ({decisions.length})
          </div>
          {decisions.map((d) => {
            const srcId = resolveSessionId(d.source_session);
            const noteOpen = expandedNotes.has(d.id);
            return (
            <div key={d.id} style={{ marginBottom: 10, padding: '10px 12px', border: '1px solid var(--accent-purple)', borderRadius: 8, background: 'var(--bg-card)' }}>
              <div style={{ color: 'var(--text)', fontWeight: 700, fontSize: 13, marginBottom: 4 }}>{d.decision}</div>
              {d.options && <div style={{ fontSize: 12, marginBottom: 2 }}><span style={{ color: 'var(--text-muted)' }}>Options: </span><span style={{ color: 'var(--text)' }}>{d.options}</span></div>}
              {d.recommendation && <div style={{ fontSize: 12, marginBottom: 2 }}><span style={{ color: 'var(--text-muted)' }}>Hamilton's rec: </span><span style={{ color: 'var(--accent-green)', fontWeight: 600 }}>{d.recommendation}</span></div>}
              {/* Source references (clickable) + filed-at timestamp. */}
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, display: 'flex', flexWrap: 'wrap', alignItems: 'center', gap: 6 }}>
                {(d.source_todo || d.source_session) && (
                  <span>
                    source:{' '}
                    {d.source_todo && <TodoLink id={d.source_todo} />}
                    {d.source_todo && d.source_session && <span style={{ color: 'var(--text-muted)' }}> · </span>}
                    {d.source_session && (srcId
                      ? <SessionLink id={srcId} label={d.source_session} />
                      : <span style={{ color: 'var(--text-sec)' }}>{d.source_session}</span>)}
                  </span>
                )}
                {d.created_at && (
                  <span title={d.created_at} style={{ marginLeft: (d.source_todo || d.source_session) ? 'auto' : 0 }}>
                    filed {formatWhen(d.created_at)}
                  </span>
                )}
              </div>
              {/* Details (the note): richer background, collapsed by default (todo_0579). */}
              {d.note && (
                <div style={{ marginTop: 6 }}>
                  <button
                    onClick={() => toggleNote(d.id)}
                    style={{ background: 'transparent', border: 'none', color: 'var(--text-muted)', fontSize: 11.5, cursor: 'pointer', padding: 0, display: 'inline-flex', alignItems: 'center', gap: 4 }}
                  >
                    <span style={{ fontSize: 9 }}>{noteOpen ? '▼' : '▶'}</span> Details
                  </button>
                  {noteOpen && (
                    <div style={{ fontSize: 11.5, color: 'var(--text-sec)', marginTop: 4, whiteSpace: 'pre-wrap', lineHeight: 1.45 }}>{d.note}</div>
                  )}
                </div>
              )}
              {answerFor === d.id ? (
                <div style={{ display: 'flex', gap: 6, marginTop: 8 }}>
                  <input autoFocus value={answerText} onChange={(e) => setAnswerText(e.target.value)}
                    onKeyDown={(e) => { if (e.key === 'Enter') submitAnswer(d.id); if (e.key === 'Escape') { setAnswerFor(null); setAnswerText(''); } }}
                    placeholder="Your decision… (Enter to send to Hamilton)"
                    style={{ flex: 1, background: 'var(--bg-deep)', border: '1px solid var(--border)', borderRadius: 6, color: 'var(--text)', fontSize: 12, padding: '5px 9px', outline: 'none' }} />
                  <button onClick={() => submitAnswer(d.id)} disabled={!answerText.trim()} style={{ background: 'var(--accent-purple-bg, var(--bg-hover))', border: '1px solid var(--accent-purple)', color: 'var(--text)', borderRadius: 6, padding: '5px 12px', fontSize: 12, cursor: 'pointer', fontWeight: 600 }}>Send</button>
                  <button onClick={() => { setAnswerFor(null); setAnswerText(''); }} style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)', borderRadius: 6, padding: '5px 10px', fontSize: 12, cursor: 'pointer' }}>Cancel</button>
                </div>
              ) : (
                <div style={{ display: 'flex', gap: 8, marginTop: 8, alignItems: 'center' }}>
                  <button onClick={() => { setAnswerFor(d.id); setAnswerText(''); }} style={{ background: 'var(--accent-purple-bg, var(--bg-hover))', border: '1px solid var(--accent-purple)', color: 'var(--text)', borderRadius: 6, padding: '4px 12px', fontSize: 12, cursor: 'pointer', fontWeight: 600 }}>Answer →</button>
                  <button onClick={() => dismissDecision(d.id)} title="Already addressed — archive without answering" style={{ background: 'transparent', border: '1px solid var(--border)', color: 'var(--text-muted)', borderRadius: 6, padding: '4px 10px', fontSize: 12, cursor: 'pointer' }}>Already addressed</button>
                </div>
              )}
            </div>
            );
          })}
        </div>
        ) : (
          <div style={{ padding: '28px 16px', color: 'var(--text-muted)', fontSize: 13, textAlign: 'center' }}>
            Nothing needs you right now — no open decisions.
          </div>
        )
      )}

      {activeTab === 'board' && (
      <>
      {needs.length > 0 && (
        <div style={{ padding: '10px 16px', borderBottom: '1px solid var(--border)', background: 'var(--attention-bg, #160f0c)' }}>
          <div style={{ fontSize: 11, letterSpacing: '.05em', textTransform: 'uppercase', color: 'var(--accent-orange)', fontWeight: 700, marginBottom: 6 }}>
            Needs PianoMan ({needs.length})
          </div>
          {needs.map((r) => (
            <div key={r.name} style={{ display: 'flex', gap: 10, padding: '3px 0', fontSize: 12 }}>
              <span style={{ color: 'var(--accent-orange)', fontWeight: 600 }}>⚑</span>
              <span style={{ width: 150, color: 'var(--text)', fontWeight: 600 }}>{r.name}</span>
              <span style={{ color: 'var(--text-sec)' }}>{needsReason(r)}</span>
            </div>
          ))}
        </div>
      )}

      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 14 }}>
        <thead>
          <tr style={{ color: 'var(--text-muted)', textAlign: 'left' }}>
            <th style={{ padding: '7px 16px', fontWeight: 600 }}>Worker</th>
            <th style={{ padding: '7px 8px', fontWeight: 600 }}>State</th>
            <th style={{ padding: '7px 8px', fontWeight: 600 }}>Activity</th>
            <th style={{ padding: '7px 8px', fontWeight: 600 }}>Recent Work</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const isSession = r.kind === 'session';
            // Sessions: canonical live visual. Team/Project/Backlog: derived —
            // green when actively working (a todo In_Progress), muted otherwise.
            const visual = isSession
              ? resolveVisual(r)
              : { color: r.status === 'active' ? 'var(--accent-green)' : 'var(--text-muted)', label: r.state_display, breathing: false };
            const stateColor = visual.color;
            const stateLabel = visual.label;
            const assessState = r.assessment?.state;
            const badge = KIND_BADGE[r.kind];
            // Open the right tab per worker kind (unassigned/backlog isn't openable).
            const openTab = () => {
              if (isSession && r.tracking_id) executeCommand('workspace.tabs.open', { type: 'session', targetId: r.tracking_id, label: r.name }, { onFailure: 'log' });
              else if (r.kind === 'team' || r.kind === 'project') executeCommand('workspace.tabs.open', { type: r.kind, targetId: r.name, label: r.name }, { onFailure: 'log' });
            };
            const linkable = (isSession && r.tracking_id) || r.kind === 'team' || r.kind === 'project';
            return (
              <tr key={`${r.kind}:${r.name}`} style={{ borderTop: '1px solid var(--border)' }}>
                <td style={{ padding: '7px 16px', fontWeight: 600 }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 7 }}>
                    {badge && (
                      <span style={{
                        fontSize: 8.5, fontWeight: 800, letterSpacing: '.05em', color: badge.color,
                        border: `1px solid color-mix(in srgb, ${badge.color} 45%, transparent)`,
                        borderRadius: 3, padding: '0 4px', lineHeight: '13px',
                      }}>{badge.label}</span>
                    )}
                    {linkable ? (
                      <span
                        role="link"
                        title={`Open ${r.name}`}
                        onClick={openTab}
                        style={{ color: 'var(--accent-blue)', cursor: 'pointer', textDecoration: 'underline', textDecorationColor: 'color-mix(in srgb, var(--accent-blue) 45%, transparent)' }}
                      >{r.name}</span>
                    ) : (
                      <span style={{ color: 'var(--text)' }}>{r.name}</span>
                    )}
                  </span>
                </td>
                <td style={{ padding: '7px 8px' }}>
                  <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
                    <span
                      className={visual.breathing ? 'session-breathing' : undefined}
                      style={{ width: 8, height: 8, borderRadius: '50%', background: stateColor }}
                    />
                    <span style={{ color: 'var(--text-sec)' }}>{stateLabel}</span>
                  </span>
                </td>
                <td style={{ padding: '7px 8px', color: 'var(--text-muted)' }}>{r.ago}</td>
                <td style={{ padding: '7px 8px', color: 'var(--text-sec)' }}>
                  {r.todos.length > 0 ? (() => {
                    const ordered = currentTodos(r.todos);
                    const shown = ordered.slice(0, 3);   // current + previous two
                    const more = ordered.length - shown.length;
                    return (
                      <span>
                        {shown.map((t, i) => (
                          <span key={t.id || i} title={t.id}>
                            {i > 0 && <span style={{ color: 'var(--text-muted)' }}>{'  ·  '}</span>}
                            {landTitle(t)}{' '}
                            <span style={{ color: 'var(--accent-blue)' }}>[{STATUS_CODE[t.status || ''] || t.status}]</span>
                          </span>
                        ))}
                        {more > 0 && (
                          <span style={{ color: 'var(--text-muted)' }} title={ordered.slice(3).map((t) => `${t.id}: ${landTitle(t)}`).join('\n')}> +{more}</span>
                        )}
                      </span>
                    );
                  })() : (
                    <span style={{ color: 'var(--text-muted)' }}>(no assigned todo)</span>
                  )}
                  {assessState && assessState !== 'productive' && (
                    <span style={{ color: 'var(--accent-orange)', marginLeft: 6 }}>[{assessState}]</span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
      </>
      )}

    </div>
  );
}
