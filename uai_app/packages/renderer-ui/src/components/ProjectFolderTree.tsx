/**
 * ProjectFolderTree — one generic, lazy, project-scoped file tree (decision 2).
 *
 * Reused for Docs (Overview, rooted at the project working dir) and work-files
 * (Work, rooted at a todo dir). Each directory loads its children on expand via
 * window.uai.fs.listDir (todo_0317). Click a file → onSelectFile (its meta fills
 * the Right Panel); double-click → open in the OS (window.uai.openPath).
 *
 * Design: docs/designs/2026-06-21-project-editor-design.md §2 + decision 2
 */

import { useEffect, useState } from 'react';

export interface FsEntry {
  name: string;
  path: string;
  type: 'file' | 'directory';
  size: number | null;
  modified: string | null;
}

export function fmtSize(n: number | null): string {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

interface NodeProps {
  entry: FsEntry;
  depth: number;
  selectedPath?: string;
  onSelectFile?: (entry: FsEntry) => void;
  onOpenFile?: (path: string) => void;
}

function DirNode({ entry, depth, selectedPath, onSelectFile, onOpenFile }: NodeProps): JSX.Element {
  const [open, setOpen] = useState(false);
  const [children, setChildren] = useState<FsEntry[] | null>(null);
  const [loading, setLoading] = useState(false);

  const toggle = async () => {
    const next = !open;
    setOpen(next);
    if (next && children === null) {
      setLoading(true);
      try { setChildren((await window.uai.fs.listDir(entry.path)) as FsEntry[]); }
      catch { setChildren([]); }
      finally { setLoading(false); }
    }
  };

  return (
    <>
      <div className="pe-tree-row" style={{ paddingLeft: 8 + depth * 14 }} onClick={toggle} title={entry.path}>
        <span className="pe-tree-caret">{open ? '▾' : '▸'}</span>
        <span className="pe-tree-icon">📁</span>{entry.name}
      </div>
      {open && (loading
        ? <div className="pe-tree-loading" style={{ paddingLeft: 8 + (depth + 1) * 14 }}>…</div>
        : (children || []).map(c => (
            <FsNode key={c.path} entry={c} depth={depth + 1} selectedPath={selectedPath} onSelectFile={onSelectFile} onOpenFile={onOpenFile} />
          )))}
    </>
  );
}

function FileNode({ entry, depth, selectedPath, onSelectFile, onOpenFile }: NodeProps): JSX.Element {
  return (
    <div
      className={`pe-tree-row pe-tree-file${selectedPath === entry.path ? ' sel' : ''}`}
      style={{ paddingLeft: 8 + depth * 14 }}
      onClick={() => onSelectFile?.(entry)}
      onDoubleClick={() => onOpenFile?.(entry.path)}
      title={`${entry.path} — double-click to open in OS`}
    >
      <span className="pe-tree-caret" />
      <span className="pe-tree-icon">📄</span>{entry.name}
      <span className="pe-tree-size">{fmtSize(entry.size)}</span>
    </div>
  );
}

function FsNode(props: NodeProps): JSX.Element {
  return props.entry.type === 'directory' ? <DirNode {...props} /> : <FileNode {...props} />;
}

interface ProjectFolderTreeProps {
  rootPath: string;
  selectedPath?: string;
  onSelectFile?: (entry: FsEntry) => void;
  onOpenFile?: (path: string) => void;
}

export default function ProjectFolderTree({ rootPath, selectedPath, onSelectFile, onOpenFile }: ProjectFolderTreeProps): JSX.Element {
  const [roots, setRoots] = useState<FsEntry[] | null>(null);

  useEffect(() => {
    let alive = true;
    if (!rootPath) { setRoots([]); return; }
    window.uai.fs.listDir(rootPath)
      .then(r => { if (alive) setRoots(r as FsEntry[]); })
      .catch(() => { if (alive) setRoots([]); });
    return () => { alive = false; };
  }, [rootPath]);

  const openInOs = (path: string) => { (onOpenFile ?? ((p: string) => window.uai.openPath(p)))(path); };

  if (roots === null) return <div className="pe-tree-loading">Loading…</div>;
  if (roots.length === 0) return <div className="pe-note">Empty or unreadable directory.</div>;
  return (
    <div className="pe-tree">
      {roots.map(e => (
        <FsNode key={e.path} entry={e} depth={0} selectedPath={selectedPath} onSelectFile={onSelectFile} onOpenFile={openInOs} />
      ))}
    </div>
  );
}
