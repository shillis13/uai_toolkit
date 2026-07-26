import { describe, expect, it } from 'vitest';
import type { Session } from '../../packages/shared/src/types';
import {
  DEFAULT_SESSION_FILTER,
  filterSessions,
  type SessionFilterState,
} from '../../packages/renderer-ui/src/components/useSessionFilter';

const NOW = Date.parse('2026-07-23T12:00:00Z');

function makeSession(
  trackingId: string,
  overrides: Partial<Session> = {},
): Session {
  return {
    tracking_id: trackingId,
    cli_session_id: `${trackingId}-cli`,
    platform: 'claude_cli',
    terminal_session: trackingId,
    session_dir: `/tmp/${trackingId}`,
    project_dir: '/tmp',
    history_file: null,
    display_name: trackingId,
    roles: ['assistant'],
    model: null,
    parent_tracking_id: null,
    identity_status: 'confirmed',
    process_status: 'stopped',
    archived: false,
    created_at: '2026-07-20T12:00:00Z',
    runtime_state: 'stopped',
    activity_state: 'stopped',
    context_percent: null,
    exchange_count: 0,
    message_count: null,
    transcript_bytes: null,
    last_activity: '2026-07-23T11:00:00Z',
    start_history: [],
    pinned: false,
    lastViewedAt: null,
    notes: null,
    tags: [],
    loaded_briefs: [],
    ...overrides,
  };
}

function filter(overrides: Partial<SessionFilterState>): SessionFilterState {
  return { ...DEFAULT_SESSION_FILTER, ...overrides };
}

describe('filterSessions', () => {
  it('combines state, tag, recency, and free-text filters', () => {
    const sessions = [
      makeSession('wanted', {
        display_name: 'Build Agent',
        process_status: 'running',
        runtime_state: 'running',
        activity_state: 'idle',
        tags: ['release', 'nightly'],
        last_activity: '2026-07-23T11:30:00Z',
      }),
      makeSession('wrong-state', {
        display_name: 'Build Agent',
        tags: ['release', 'nightly'],
      }),
      makeSession('too-old', {
        display_name: 'Build Agent',
        process_status: 'running',
        tags: ['release', 'nightly'],
        last_activity: '2026-07-20T11:30:00Z',
      }),
    ];

    const result = filterSessions(sessions, filter({
      state: 'running',
      tags: ['release'],
      activityWithin: '24h',
      search: 'build nightly',
    }), NOW);

    expect(result.map((s) => s.tracking_id)).toEqual(['wanted']);
  });

  it('excludes archived sessions by default and includes them on request', () => {
    const archived = makeSession('archived', { archived: true });

    expect(filterSessions([archived], filter({}), NOW)).toEqual([]);
    expect(filterSessions([archived], filter({ includeArchived: true }), NOW)).toEqual([archived]);
  });

  it('sorts deterministically in either direction', () => {
    const sessions = [
      makeSession('session-b', { display_name: 'Same' }),
      makeSession('session-a', { display_name: 'Same' }),
      makeSession('session-c', { display_name: 'Zulu' }),
    ];

    expect(filterSessions(sessions, filter({ sortField: 'name', sortDir: 'asc' }), NOW)
      .map((s) => s.tracking_id)).toEqual(['session-a', 'session-b', 'session-c']);
    expect(filterSessions(sessions, filter({ sortField: 'name', sortDir: 'desc' }), NOW)
      .map((s) => s.tracking_id)).toEqual(['session-c', 'session-a', 'session-b']);
  });
});
