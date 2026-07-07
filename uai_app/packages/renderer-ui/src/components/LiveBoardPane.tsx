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

interface LandTodo {
  id?: string;
  status?: string;
  project?: string | null;
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
  name: string;
  tracking_id?: string;
  platform: string;
  status: string;
  activity_state: string;
  state_display: string;
  ago: string;
  roles: string[];
  todos: LandTodo[];
  assessment?: LandAssessment | null;
}

interface LandTotals {
  todos: number;
  todos_no_assignee: number;
  todos_no_project: number;
  active_sessions: number;
  active_no_todo: number;
}

interface LandscapeModel {
  rows: LandRow[];
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

export default function LiveBoardPane() {
  const [model, setModel] = useState<LandscapeModel | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  // Live session store — the State column reads from here so it behaves exactly
  // like Recent Sessions. Subscribing re-renders the board on any store change,
  // and onActivityChange catches the ephemeral in-app activity signals too.
  const { getSession } = useSessionStore();
  const [, forceUpdate] = useState(0);
  useEffect(() => onActivityChange(() => forceUpdate((n) => n + 1)), []);

  // Resolve a row's visual state the Recent-Sessions way: prefer the live
  // session (activity_state × process_status); fall back to the landscape row.
  const resolveVisual = useCallback((r: LandRow) => {
    const live = r.tracking_id ? getSession(r.tracking_id) : undefined;
    return live
      ? getSessionStateVisual(live.activity_state, live.process_status)
      : getSessionStateVisual(r.activity_state, backendProcess(r.status));
  }, [getSession]);

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

  const rows = model?.rows || [];
  const totals = model?.totals;
  const needs = rows.filter(needsPianoman);

  // Viewport reporter — exposes the live board's rows/totals so the "Capture
  // Content" feature (describeViewport) shows the real landscape instead of an
  // empty dead node. Top ~20 rows summarized as inline children (session name +
  // state + current-work title). Refresh maps to the same work.landscape command
  // the Refresh button fires.
  useViewport('live_board', () => ({
    visible: true,
    label: 'Work — Live Board',
    state: {
      rows: rows.length,
      needsPianoman: needs.length,
      loading,
      error,
      activeSessions: totals?.active_sessions ?? null,
      activeNoTodo: totals?.active_no_todo ?? null,
      todos: totals?.todos ?? null,
      todosNoAssignee: totals?.todos_no_assignee ?? null,
      todosNoProject: totals?.todos_no_project ?? null,
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

      {error && (
        <div style={{ padding: '10px 16px', color: 'var(--accent-orange)', fontSize: 12 }}>⚠ {error}</div>
      )}

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
            <th style={{ padding: '7px 16px', fontWeight: 600 }}>Session</th>
            <th style={{ padding: '7px 8px', fontWeight: 600 }}>State</th>
            <th style={{ padding: '7px 8px', fontWeight: 600 }}>Activity</th>
            <th style={{ padding: '7px 8px', fontWeight: 600 }}>Recent Work</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const visual = resolveVisual(r);
            const stateColor = visual.color;
            const stateLabel = visual.label;
            const assessState = r.assessment?.state;
            return (
              <tr key={r.name} style={{ borderTop: '1px solid var(--border)' }}>
                <td style={{ padding: '7px 16px', fontWeight: 600 }}>
                  {r.tracking_id ? (
                    <span
                      role="link"
                      title={`Open ${r.name}'s session tab`}
                      onClick={() => executeCommand('workspace.tabs.open', { type: 'session', targetId: r.tracking_id, label: r.name }, { onFailure: 'log' })}
                      style={{ color: 'var(--accent-blue)', cursor: 'pointer', textDecoration: 'underline', textDecorationColor: 'color-mix(in srgb, var(--accent-blue) 45%, transparent)' }}
                    >{r.name}</span>
                  ) : (
                    <span style={{ color: 'var(--text)' }}>{r.name}</span>
                  )}
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

    </div>
  );
}
