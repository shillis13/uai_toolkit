/**
 * useSessionFilter — the ONE reusable session-filter/sort/search capability
 * (todo_0600 item 1.1.4–1.1.7). Given the session registry and a filter state,
 * returns the filtered + stably-sorted list. Meant to back every session lister
 * — the Resume/Fork picker, the Custom launcher, and session listers like a
 * Folder view — so the filtering logic lives in exactly one place.
 *
 * Pure/derivational: no data fetching, no side effects. Callers pass the sessions
 * (from the session store) + a SessionFilterState and render the result however
 * they like. The companion <SessionPicker> is the default UI over this hook.
 */

import { useMemo } from 'react';
import type { Session } from '@uai/shared/types';
import { cardLocation, useFolderStore } from '../stores/folder-store';

// Which identifier a lister shows for a session (1.1.2). All of them are always
// searchable and appear in the per-row tooltip (1.1.3) regardless of this choice.
export type SessionDisplayId = 'display_name' | 'tracking_id' | 'cli_session_id' | 'terminal_session';

export type SessionSortField = 'created' | 'last_activity' | 'name' | 'product';
export type SortDir = 'asc' | 'desc';

// Last-activity window presets (1.1.4 "last activity"). 'any' disables the filter.
export type ActivityWindow = 'any' | '1h' | '24h' | '7d' | '30d';
const WINDOW_MS: Record<Exclude<ActivityWindow, 'any'>, number> = {
  '1h': 3_600_000,
  '24h': 86_400_000,
  '7d': 604_800_000,
  '30d': 2_592_000_000,
};

export interface SessionFilterState {
  product: string | null;          // platform, e.g. 'claude_cli'; null = any
  state: 'all' | 'running' | 'stopped';
  folderId: string | null;         // folder id; null = any
  tags: string[];                  // session must carry ALL of these tags
  activityWithin: ActivityWindow;  // last-activity recency window
  search: string;                  // free-text over all metadata
  sortField: SessionSortField;
  sortDir: SortDir;
  includeArchived?: boolean;       // default false
}

export const DEFAULT_SESSION_FILTER: SessionFilterState = {
  product: null,
  state: 'all',
  folderId: null,
  tags: [],
  activityWithin: 'any',
  search: '',
  sortField: 'last_activity',
  sortDir: 'desc',
  includeArchived: false,
};

/** Resolve the label a lister should show for a session under the chosen id kind,
 *  falling back to the tracking id when the chosen field is empty. */
export function sessionLabel(s: Session, kind: SessionDisplayId): string {
  const v = (s as unknown as Record<string, unknown>)[kind];
  return (typeof v === 'string' && v.trim()) ? v : s.tracking_id;
}

/** Every identifier a session carries, for the per-row tooltip (1.1.3). */
export function sessionIdentifiers(s: Session): string {
  return [
    `Name: ${s.display_name || '—'}`,
    `Tracking: ${s.tracking_id}`,
    `CLI: ${s.cli_session_id || '—'}`,
    `Terminal: ${s.terminal_session || '—'}`,
    `Platform: ${s.platform}`,
  ].join('\n');
}

// Everything a search should match against — all identifiers + roles/tags/model.
function haystack(s: Session): string {
  return [
    s.display_name, s.tracking_id, s.cli_session_id, s.terminal_session,
    s.platform, s.model, (s.roles || []).join(' '), (s.tags || []).join(' '),
  ].filter(Boolean).join(' ').toLowerCase();
}

function isRunning(s: Session): boolean {
  return s.process_status === 'running';
}

function parseTime(v: string | null | undefined): number {
  if (!v) return 0;
  const t = Date.parse(v);
  return Number.isNaN(t) ? 0 : t;
}

/** Apply a SessionFilterState to a session list and return the filtered, stably
 *  sorted result. Stable: every comparator breaks ties on tracking_id so equal
 *  keys keep a deterministic order across renders (1.1.5). `now` is injected so
 *  the activity-window filter is testable/deterministic. */
export function filterSessions(sessions: Session[], f: SessionFilterState, now: number): Session[] {
  const searchTerms = f.search.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const cutoff = f.activityWithin === 'any' ? 0 : now - WINDOW_MS[f.activityWithin];

  const out = sessions.filter((s) => {
    if (!f.includeArchived && s.archived) return false;
    if (f.product && s.platform !== f.product) return false;
    if (f.state === 'running' && !isRunning(s)) return false;
    if (f.state === 'stopped' && isRunning(s)) return false;
    if (f.folderId && cardLocation(`session:${s.tracking_id}`) !== f.folderId) return false;
    if (f.tags.length && !f.tags.every((t) => (s.tags || []).includes(t))) return false;
    if (cutoff && parseTime(s.last_activity) < cutoff) return false;
    if (searchTerms.length) {
      const text = haystack(s);
      if (!searchTerms.every((term) => text.includes(term))) return false;
    }
    return true;
  });

  const dir = f.sortDir === 'asc' ? 1 : -1;
  const key = (s: Session): string | number => {
    switch (f.sortField) {
      case 'created': return parseTime(s.created_at);
      case 'last_activity': return parseTime(s.last_activity);
      case 'product': return s.platform || '';
      case 'name': return (sessionLabel(s, 'display_name') || '').toLowerCase();
      default: return 0;
    }
  };
  return out.sort((a, b) => {
    const ka = key(a); const kb = key(b);
    let cmp = 0;
    if (typeof ka === 'number' && typeof kb === 'number') cmp = ka - kb;
    else cmp = String(ka).localeCompare(String(kb));
    if (cmp !== 0) return cmp * dir;
    // Stable tie-break — deterministic regardless of input order or sort dir.
    return a.tracking_id.localeCompare(b.tracking_id);
  });
}

/** React hook wrapper: memoizes the filtered list. `now` defaults to render time
 *  when omitted; it is intentionally excluded from the memo deps so the list does
 *  not churn every render (it refreshes when sessions or any filter field change). */
export function useSessionFilter(sessions: Session[], f: SessionFilterState, now?: number): Session[] {
  // Folder membership lives outside the session records. Subscribe here so a
  // move between folders invalidates an active folder filter even when the
  // session array itself did not change.
  const { storeData } = useFolderStore();
  const nowStamp = now ?? Date.now();
  return useMemo(
    () => filterSessions(sessions, f, nowStamp),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [sessions, storeData.revision, f.product, f.state, f.folderId, JSON.stringify(f.tags), f.activityWithin, f.search, f.sortField, f.sortDir, f.includeArchived],
  );
}
