/**
 * NewsTab — Navigator tab showing news articles and research reports.
 *
 * News: generated daily/weekly from docs/news/ (flat list).
 * Reports: research_and_reports/ rendered as a collapsible folder hierarchy.
 *
 * Read state is persisted to an external store (news_read_state.json). Unread
 * items are brighter + flagged with a dot; read items are dimmer. Opening an
 * item marks it read. Right-click → Mark as Read / Mark as Unread.
 */

import { useState, useEffect, useMemo, useCallback, useRef } from 'react';
import { showContextMenu, type ContextMenuItem } from '../utils/context-menu';

interface NewsItem {
  type: 'news' | 'report';
  name: string;
  path: string;
  size: number;
  modified: string;
  kind?: string;
  relPath?: string;
  isDir?: boolean;
}

function formatDate(iso: string): string {
  try {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
  } catch { return iso.slice(0, 10); }
}

interface TreeNode {
  name: string;
  path: string;
  isDir: boolean;
  item?: NewsItem;
  children: Map<string, TreeNode>;
}

function buildTree(reports: NewsItem[]): TreeNode {
  const root: TreeNode = { name: '', path: '', isDir: true, children: new Map() };
  for (const it of reports) {
    const segs = (it.relPath || it.name).split('/').filter(Boolean);
    let node = root;
    segs.forEach((seg, i) => {
      if (!node.children.has(seg)) {
        node.children.set(seg, { name: seg, path: '', isDir: true, children: new Map() });
      }
      node = node.children.get(seg)!;
      if (i === segs.length - 1) { node.item = it; node.isDir = !!it.isDir; node.path = it.path; }
    });
  }
  return root;
}

/** Newest `modified` timestamp (epoch ms) at/under a node. Files use their own
 *  mtime; folders inherit their freshest descendant so recency bubbles up — the
 *  key for descending-chronological ordering across the whole tree. */
function nodeMTime(node: TreeNode): number {
  let max = node.item ? (Date.parse(node.item.modified) || 0) : 0;
  for (const c of node.children.values()) max = Math.max(max, nodeMTime(c));
  return max;
}

/** Every folder key under a node, keyed exactly as renderNode does
 *  (`child.item?.path || `${node.path}/${child.name}``) — used to seed the
 *  default-collapsed set so only the first level under each section is expanded. */
function collectDirKeys(node: TreeNode, out: Set<string>): void {
  for (const child of node.children.values()) {
    if (child.isDir) {
      out.add(child.item?.path || `${node.path}/${child.name}`);
      collectDirKeys(child, out);
    }
  }
}

/** All file (non-dir) paths at/under a node — for dir-level read state + bulk mark. */
function descendantFilePaths(node: TreeNode): string[] {
  const out: string[] = [];
  const walk = (n: TreeNode) => {
    if (n.item && !n.isDir) out.push(n.item.path);
    for (const c of n.children.values()) walk(c);
  };
  walk(node);
  return out;
}

export default function NewsTab(): JSX.Element {
  const [items, setItems] = useState<NewsItem[]>([]);
  const [readPaths, setReadPaths] = useState<Set<string>>(new Set());
  const [loading, setLoading] = useState(true);
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());
  const [collapsedDirs, setCollapsedDirs] = useState<Set<string>>(new Set());

  const reload = useCallback(async () => {
    try {
      const [list, read] = await Promise.all([window.uai.news.list(), window.uai.news.readState()]);
      setItems(list);
      setReadPaths(new Set(read));
    } catch { /* ignore */ }
    setLoading(false);
  }, []);

  useEffect(() => { reload(); }, [reload]);

  const { newsTree, reportTree } = useMemo(() => ({
    newsTree: buildTree(items.filter(i => i.type === 'news')),
    reportTree: buildTree(items.filter(i => i.type === 'report')),
  }), [items]);

  // Default view: sections expanded, but every nested folder collapsed — so only
  // the first level under News / Research & Reports shows. Seed once, after the
  // first real load; later reloads won't clobber the user's manual expansions.
  const seededCollapse = useRef(false);
  useEffect(() => {
    if (seededCollapse.current || items.length === 0) return;
    const keys = new Set<string>();
    collectDirKeys(newsTree, keys);
    collectDirKeys(reportTree, keys);
    setCollapsedDirs(keys);
    seededCollapse.current = true;
  }, [items, newsTree, reportTree]);

  const isRead = useCallback((p: string) => readPaths.has(p), [readPaths]);

  const mark = useCallback(async (paths: string[], read: boolean) => {
    if (paths.length === 0) return;
    setReadPaths(prev => {
      const n = new Set(prev);
      for (const p of paths) { if (read) n.add(p); else n.delete(p); }
      return n;
    });
    await window.uai.news.mark(paths, read);
  }, []);

  const toggleSection = (section: string) => {
    setCollapsedSections(prev => { const n = new Set(prev); n.has(section) ? n.delete(section) : n.add(section); return n; });
  };
  const toggleDir = (key: string) => {
    setCollapsedDirs(prev => { const n = new Set(prev); n.has(key) ? n.delete(key) : n.add(key); return n; });
  };

  const handleOpen = (item: NewsItem) => {
    window.uai.openPath(item.path);
    if (!item.isDir) mark([item.path], true);  // opening marks read
  };

  const itemMenu = useCallback((e: React.MouseEvent, paths: string[]) => {
    const anyUnread = paths.some(p => !readPaths.has(p));
    const items_: ContextMenuItem[] = [
      { label: paths.length > 1 ? `Mark ${paths.length} as Read` : 'Mark as Read', action: () => mark(paths, true), disabled: !anyUnread },
      { label: paths.length > 1 ? `Mark ${paths.length} as Unread` : 'Mark as Unread', action: () => mark(paths, false) },
    ];
    showContextMenu(e, items_);
  }, [readPaths, mark]);

  const newsFiles = descendantFilePaths(newsTree);
  const newsUnread = newsFiles.filter(p => !isRead(p)).length;
  const reportUnread = descendantFilePaths(reportTree).filter(p => !isRead(p)).length;

  if (loading) return <div className="session-list-empty">Loading...</div>;

  // `color` is applied to the whole row so chevron, icon, and name share one
  // color. Indent = 16 + depth*14 so top-level items sit clearly under the
  // section header.
  const renderNode = (node: TreeNode, depth: number, color: string): JSX.Element[] => {
    const rows: JSX.Element[] = [];
    // Folders get the full (brighter) section color; files a softer, less
    // saturated mix of it — so the two read as distinct.
    const folderColor = color;
    const fileColor = `color-mix(in srgb, ${color} 55%, var(--text-muted))`;
    // Descending chronological: newest first. Folders sort by their freshest
    // descendant (nodeMTime), so a folder with a recent report floats up. Ties
    // (same mtime, or none) fall back to name for a stable order.
    const kids = Array.from(node.children.values()).sort((a, b) => {
      const dt = nodeMTime(b) - nodeMTime(a);
      return dt !== 0 ? dt : a.name.localeCompare(b.name);
    });
    for (const child of kids) {
      const key = child.item?.path || `${node.path}/${child.name}`;
      if (child.isDir) {
        const files = descendantFilePaths(child);
        const dirUnread = files.filter(p => !isRead(p)).length;
        const collapsed = collapsedDirs.has(key);
        rows.push(
          <button
            key={key}
            className={`nav-apps-item nav-news-item${dirUnread > 0 ? ' nav-news-unread' : ' nav-news-read'}`}
            style={{ paddingLeft: `${16 + depth * 14}px`, color: folderColor }}
            onClick={() => toggleDir(key)}
            onContextMenu={(e) => itemMenu(e, files)}
            title={child.item?.path || child.name}
          >
            <span className="nav-apps-icon nav-news-chevron">{collapsed ? '▶' : '▼'}</span>
            <span className="nav-apps-icon">{'📁'}</span>
            <span className="nav-apps-label">{child.name}</span>
          </button>,
        );
        if (!collapsed) rows.push(...renderNode(child, depth + 1, color));
      } else {
        const it = child.item!;
        const read = isRead(it.path);
        const fileIcon = it.type === 'news' ? (it.kind === 'weekly' ? '📊' : '📰') : '📄';
        rows.push(
          <button
            key={key}
            className={`nav-apps-item nav-news-item${read ? ' nav-news-read' : ' nav-news-unread'}`}
            style={{ paddingLeft: `${16 + depth * 14}px`, color: fileColor }}
            onClick={() => handleOpen(it)}
            onContextMenu={(e) => itemMenu(e, [it.path])}
            title={`${it.path}\n${formatDate(it.modified)}`}
          >
            {/* empty chevron-width spacer so files align/indent under their
                parent folder (folders spend this column on a real chevron). */}
            <span className="nav-apps-icon nav-news-chevron" />
            <span className="nav-apps-icon">{fileIcon}</span>
            <span className="nav-apps-label">{child.name}</span>
          </button>,
        );
      }
    }
    return rows;
  };

  return (
    <div className="nav-apps-tab" style={{ padding: '0' }}>
      {/* News section */}
      <div className="session-section">
        <div className="session-section-header" onClick={() => toggleSection('news')}>
          <span className="session-section-arrow">{collapsedSections.has('news') ? '▶' : '▼'}</span>
          <span className="session-section-title" style={{ color: 'var(--accent-cyan)' }}>News</span>
          <span className="session-section-count" style={{ color: 'var(--accent-cyan)' }}>{newsFiles.length}</span>
          {newsUnread > 0 && <span className="nav-news-section-badge">{newsUnread}</span>}
        </div>
        {!collapsedSections.has('news') && (
          newsTree.children.size > 0 ? (
            <div className="nav-news-children">{renderNode(newsTree, 0, 'var(--accent-cyan)')}</div>
          ) : (
            <div className="session-list-empty" style={{ fontSize: '11px', padding: '8px 12px' }}>No news articles.</div>
          )
        )}
      </div>

      {/* Reports section — folder hierarchy */}
      <div className="session-section">
        <div className="session-section-header" onClick={() => toggleSection('reports')}>
          <span className="session-section-arrow">{collapsedSections.has('reports') ? '▶' : '▼'}</span>
          <span className="session-section-title" style={{ color: 'var(--accent-yellow)' }}>Research & Reports</span>
          <span className="session-section-count" style={{ color: 'var(--accent-yellow)' }}>{descendantFilePaths(reportTree).length}</span>
          {reportUnread > 0 && <span className="nav-news-section-badge">{reportUnread}</span>}
        </div>
        {!collapsedSections.has('reports') && (
          reportTree.children.size > 0 ? (
            <div className="nav-news-children">{renderNode(reportTree, 0, 'var(--accent-yellow)')}</div>
          ) : (
            <div className="session-list-empty" style={{ fontSize: '11px', padding: '8px 12px' }}>No reports.</div>
          )
        )}
      </div>
    </div>
  );
}
