/**
 * Git Viewer State Store — per-tab snapshots so the Git Viewer's UI selections
 * survive the component unmounting on tab switches (Workspace mounts only the
 * ACTIVE tab, so switching away and back would otherwise reset everything).
 *
 * Each pane hydrates from its snapshot on mount and writes it back on change, so
 * returning to the tab restores the selected file, filter, scope, timeline
 * handles, zoom, and which sub-tab (File / Commit View) was showing — "sticky
 * until the tab is closed". Purely an ephemeral module-level cache; not persisted
 * to disk. Mirrors stores/search-state-store.ts.
 */

import type { GitFileViewFilter } from '../components/git-file-view-scope';

/** File-View slice — the rich state of one GitFileViewPane instance. */
export interface GfvSnapshot {
  dir: string;
  since: string;
  until: string;
  /** The loaded changelog, so returning to the tab is instant (no reload flash). */
  data: unknown | null;
  fromIdx: number;
  toIdx: number;
  lockSide: 'left' | 'right' | null;
  zoom: { lo: number; hi: number } | null;
  selPath: string | null;
  diffView: 'diff' | 'before' | 'after';
  filter: GitFileViewFilter | null;
  barOpen: boolean;
  collapsed: string[];
  expandedCommits: string[];
  /** File-view (diff) panel height in px (null = default), and maximized flag. */
  diffHeight?: number | null;
  diffMax?: boolean;
}

/** Viewer-wrapper slice — which sub-tab is active + the Commit View's target. */
export interface GitViewerSnapshot {
  activeTab: 'file' | 'commit';
  commitHash: string | null;
  commitDir: string;
  /** Commit View: last-selected file within the commit. */
  commitSelFile: string | null;
}

const gfvCache = new Map<string, GfvSnapshot>();
const viewerCache = new Map<string, GitViewerSnapshot>();

export function getGfvSnapshot(tabId: string | undefined): GfvSnapshot | undefined {
  return tabId ? gfvCache.get(tabId) : undefined;
}
export function setGfvSnapshot(tabId: string | undefined, snap: GfvSnapshot): void {
  if (tabId) gfvCache.set(tabId, snap);
}

export function getGitViewerSnapshot(tabId: string | undefined): GitViewerSnapshot | undefined {
  return tabId ? viewerCache.get(tabId) : undefined;
}
export function setGitViewerSnapshot(tabId: string | undefined, snap: GitViewerSnapshot): void {
  if (tabId) viewerCache.set(tabId, snap);
}

export function clearGitViewerState(tabId: string): void {
  gfvCache.delete(tabId);
  viewerCache.delete(tabId);
}
