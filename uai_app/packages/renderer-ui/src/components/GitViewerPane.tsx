/**
 * GitViewerPane — the "Git Viewer" tool: a tabbed wrapper around
 *   • Git File View   (files A/M/D under a dir across a commit range)
 *   • Git Commit View (one commit's message + files + per-file diff)
 *
 * Clicking a commit in the File View navigates here to the Commit View with that
 * commit selected (cross-nav via onOpenCommit).
 */

import { useState, useCallback, useEffect, useRef } from 'react';
import { TabNavArrows } from './TabNavArrows';
import GitFileViewPane from './GitFileViewPane';
import GitCommitViewPane from './GitCommitViewPane';
import { useViewport } from '../viewport';
import { getGitViewerSnapshot, setGitViewerSnapshot } from '../stores/git-viewer-state-store';

type ViewTab = 'file' | 'commit';

export default function GitViewerPane({ tabId }: { tabId?: string }): JSX.Element {
  // Persistence (#6): restore which sub-tab was active and the Commit View's target.
  const restored = useRef(getGitViewerSnapshot(tabId)).current;
  const [tab, setTab] = useState<ViewTab>(restored?.activeTab ?? 'file');
  const [commitHash, setCommitHash] = useState<string | null>(restored?.commitHash ?? null);
  const [commitDir, setCommitDir] = useState<string>(restored?.commitDir ?? 'ai_general');

  useEffect(() => {
    if (!tabId) return;
    setGitViewerSnapshot(tabId, { activeTab: tab, commitHash, commitDir, commitSelFile: null });
  }, [tabId, tab, commitHash, commitDir]);

  // File View → open a commit in the Commit View.
  const openCommit = useCallback((hash: string, dir: string) => {
    setCommitHash(hash);
    setCommitDir(dir);
    setTab('commit');
  }, []);

  // Component-architecture (#7): report the Git Viewer's live tree — the active
  // sub-tab and both children — so the viewport describe API can introspect it and
  // recurse into git_file_view / git_commit_view.
  useViewport('git_viewer', () => ({
    visible: true,
    label: 'Git Viewer',
    state: { activeTab: tab, commitHash },
    children: ['git_file_view', 'git_commit_view'],
  }));

  return (
    <div className="gviewer-pane">
      <div className="gviewer-tabbar">
        <TabNavArrows />
        <span className="gviewer-title">Git Viewer</span>
        <div className="gviewer-tabs">
          <button className={`gviewer-tab${tab === 'file' ? ' active' : ''}`} onClick={() => setTab('file')}>Git File View</button>
          <button className={`gviewer-tab${tab === 'commit' ? ' active' : ''}`} onClick={() => setTab('commit')}>Git Commit View</button>
        </div>
      </div>
      <div className="gviewer-body">
        {/* Both stay mounted so each tab keeps its state when you switch. */}
        <div style={{ display: tab === 'file' ? 'flex' : 'none', flex: 1, minHeight: 0, minWidth: 0, overflow: 'hidden' }}>
          <GitFileViewPane tabId={tabId} onOpenCommit={openCommit} />
        </div>
        <div style={{ display: tab === 'commit' ? 'flex' : 'none', flex: 1, minHeight: 0, minWidth: 0, overflow: 'hidden' }}>
          <GitCommitViewPane tabId={tabId} commitHash={commitHash} dir={commitDir} active={tab === 'commit'} />
        </div>
      </div>
    </div>
  );
}
