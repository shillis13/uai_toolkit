/**
 * Search State Store — keeps a per-tab snapshot of the Search tab's state so it
 * survives the component unmounting on tab switches (Workspace mounts only the
 * active tab). SearchContent hydrates from the snapshot on mount and writes it
 * back on change, so switching away and back restores query, results, filters,
 * sort, and view exactly as they were ("sticky until cleared").
 *
 * Purely ephemeral module-level cache — not persisted to disk.
 */

export interface SearchSnapshot {
  query: string;
  scope: 'sessions' | 'transcripts';
  results: unknown[];
  sessionResults: unknown[];
  totalMatches: number;
  sessionsSearched: number;
  searchTimeMs: number;
  viewMode: 'grouped' | 'flat';
  sortMode: 'hits' | 'time';
  hasSearched: boolean;
  regexMode: boolean;
  caseSensitive: boolean;
  deduplicateEnabled: boolean;
  includeSubagents: boolean;
  filtersOpen: boolean;
  filterPlatforms: string[];
  /** Selected session statuses (multi-select). Both selected = no status filter. */
  filterStatuses: string[];
  filterMsgTypes: string[];
  invertResults: boolean;
  /** Date range (ISO strings) — '' means open-ended. Applies to both scopes. */
  dateFrom: string;
  dateTo: string;
}

const cache = new Map<string, SearchSnapshot>();

export function getSearchSnapshot(tabId: string): SearchSnapshot | undefined {
  return cache.get(tabId);
}

export function setSearchSnapshot(tabId: string, snap: SearchSnapshot): void {
  cache.set(tabId, snap);
}

export function clearSearchSnapshot(tabId: string): void {
  cache.delete(tabId);
}
