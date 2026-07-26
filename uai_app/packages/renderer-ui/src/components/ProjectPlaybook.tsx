/**
 * ProjectPlaybook — the Playbook and Workspace aspects of a Project (todo_0320,
 * UX redesign todo_0623 #3).
 *
 * PianoMan's definition (unchanged):
 *  - Playbook  = the top-level working_dir folders that define how the project
 *    operates. The rest of the working dir is the Workspace.
 *  - Workspace = the working_dir MINUS the Playbook folders, alongside the
 *    project's recent Git changes.
 *
 * Treatment (this file): Playbook reads as a curated "operating manual" — a shelf
 * of folder cards (name + item count) with the folder-picker tucked behind an
 * "Edit set" toggle and a real empty state. Workspace is a two-pane working
 * surface: the file tree beside the recent-changes (Git) view, so you see files
 * AND what changed together instead of flipping a toggle.
 *
 * The Playbook folder set lives in the project's registry `playbook:` list; the
 * checkbox editor writes it via project.setPlaybook.
 */

import { useState, useEffect } from 'react';
import ProjectFolderTree, { type FsEntry, fmtSize } from './ProjectFolderTree';
import GitFileViewPane from './GitFileViewPane';

// Top-level directory names under `dir` (files are ignored — Playbook is folders).
function useTopFolders(dir: string): string[] {
  const [folders, setFolders] = useState<string[]>([]);
  useEffect(() => {
    let alive = true;
    if (!dir) { setFolders([]); return; }
    window.uai.fs.listDir(dir)
      .then(entries => { if (alive) setFolders((entries as FsEntry[]).filter(e => e.type === 'directory').map(e => e.name)); })
      .catch(() => { if (alive) setFolders([]); });
    return () => { alive = false; };
  }, [dir]);
  return folders;
}

// Per-folder item counts for the Playbook cards. Best-effort: -1 means the folder
// couldn't be read, null (absent) means still loading.
function useFolderItemCounts(dir: string, folders: string[]): Record<string, number> {
  const [counts, setCounts] = useState<Record<string, number>>({});
  // A serialized key avoids collisions between valid folder names containing
  // the delimiter (e.g. ["a|b", "c"] vs ["a", "b|c"]).
  const key = JSON.stringify(folders);
  useEffect(() => {
    let alive = true;
    if (!dir || folders.length === 0) { setCounts({}); return; }
    Promise.all(folders.map(f =>
      window.uai.fs.listDir(`${dir}/${f}`)
        .then(es => [f, (es as FsEntry[]).length] as const)
        .catch(() => [f, -1] as const),
    )).then(pairs => { if (alive) setCounts(Object.fromEntries(pairs)); });
    return () => { alive = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dir, key]);
  return counts;
}

// ── Playbook aspect ──────────────────────────────────────────────────────
export function PlaybookView({
  workingDir, playbook, onSetPlaybook, selectedPath, onSelectFile,
}: {
  workingDir: string;
  playbook: string[];
  onSetPlaybook: (folders: string[]) => void;
  selectedPath?: string;
  onSelectFile?: (entry: FsEntry) => void;
}): JSX.Element {
  const folders = useTopFolders(workingDir);
  const counts = useFolderItemCounts(workingDir, playbook);
  const [editing, setEditing] = useState(false);
  const [selFolder, setSelFolder] = useState<string | null>(null);
  const inPlaybook = new Set(playbook);
  if (!workingDir) return <div className="pe-note">No working directory on this project.</div>;
  const empty = playbook.length === 0;
  // If the selected shelf folder is removed while editing the set, fall back to
  // the full Playbook instead of continuing to browse a now-Workspace folder.
  const activeFolder = selFolder && inPlaybook.has(selFolder) ? selFolder : null;

  return (
    <div className="pe-detail-body pe-playbook">
      <div className="pe-pb-header">
        <div>
          <div className="pe-section-label">Playbook</div>
          <div className="pe-pb-sub">The folders that define how this project works — everything else lives in Workspace.</div>
        </div>
        <button className={`pe-pb-edit-btn${editing ? ' on' : ''}`} onClick={() => setEditing(e => !e)}>
          {editing ? 'Done' : '✎ Edit set'}
        </button>
      </div>

      {editing && (
        <div className="pe-pb-editset">
          <div className="pe-pb-editset-label">Check the top-level folders that make up the Playbook:</div>
          {folders.length === 0
            ? <span className="pe-note">No folders in the project directory yet.</span>
            : <div className="pe-pb-folders">
                {folders.map(f => (
                  <label key={f} className={`pe-pb-folder${inPlaybook.has(f) ? ' on' : ''}`}>
                    <input
                      type="checkbox"
                      checked={inPlaybook.has(f)}
                      onChange={e => onSetPlaybook(e.target.checked ? [...playbook, f] : playbook.filter(x => x !== f))}
                    />
                    <span>{f}</span>
                  </label>
                ))}
              </div>}
        </div>
      )}

      {empty && !editing && (
        <div className="pe-pb-empty">
          <div className="pe-pb-empty-ic" aria-hidden="true">📓</div>
          <div className="pe-pb-empty-text">No Playbook yet — choose the folders that define how this project operates.</div>
          <button className="pe-pb-edit-btn" onClick={() => setEditing(true)}>Choose folders</button>
        </div>
      )}

      {!empty && (
        <>
          <div className="pe-pb-shelf">
            {playbook.map(f => {
              const c = counts[f];
              return (
                <button
                  key={f}
                  className={`pe-pb-card${activeFolder === f ? ' on' : ''}`}
                  onClick={() => setSelFolder(activeFolder === f ? null : f)}
                  title={`Browse ${f}`}
                >
                  <span className="pe-pb-card-ic" aria-hidden="true">📓</span>
                  <span className="pe-pb-card-name">{f}</span>
                  <span className="pe-pb-card-meta">{c == null ? '…' : c < 0 ? '—' : `${c} item${c === 1 ? '' : 's'}`}</span>
                </button>
              );
            })}
          </div>
          <div className="pe-splitH" />
          <div className="pe-section-label">{activeFolder ? `Files · ${activeFolder}` : 'All Playbook files'}</div>
          <ProjectFolderTree
            rootPath={workingDir}
            includeNames={activeFolder ? [activeFolder] : playbook}
            selectedPath={selectedPath}
            onSelectFile={onSelectFile}
            emptyMessage="The Playbook folders were not found on disk."
          />
        </>
      )}
    </div>
  );
}

// ── Workspace aspect ─────────────────────────────────────────────────────
export function WorkspaceView({
  workingDir, playbook, selectedPath, onSelectFile,
}: {
  workingDir: string;
  playbook: string[];
  selectedPath?: string;
  onSelectFile?: (entry: FsEntry) => void;
}): JSX.Element {
  // Files and Changes are two SUB-ASPECTS, not both visible at once (todo_0623 #6.1).
  const [mode, setMode] = useState<'files' | 'changes'>('files');
  if (!workingDir) return <div className="pe-note">No working directory on this project.</div>;
  return (
    <div className="pe-detail-body pe-workspace">
      <div className="pe-ws-header">
        <div className="pe-section-label">Workspace</div>
        <div className="pe-pb-sub">Everything outside the Playbook — the live working area, or its recent changes.</div>
      </div>
      <div className="pe-ws-toolbar" role="tablist">
        <button role="tab" aria-selected={mode === 'files'} className={`pe-ws-toggle${mode === 'files' ? ' on' : ''}`} onClick={() => setMode('files')}>Files</button>
        <button role="tab" aria-selected={mode === 'changes'} className={`pe-ws-toggle${mode === 'changes' ? ' on' : ''}`} onClick={() => setMode('changes')}>Changes (Git)</button>
      </div>
      {mode === 'files'
        ? <ProjectFolderTree
            rootPath={workingDir}
            excludeNames={playbook}
            selectedPath={selectedPath}
            onSelectFile={onSelectFile}
            emptyMessage="Everything here is in the Playbook — nothing left for the Workspace."
          />
        : <div className="pe-ws-git"><GitFileViewPane dir={workingDir} embedded showScopeBar={false} allowScopeChange={false} /></div>}
    </div>
  );
}

// ── File preview panel (todo_0623 #5.1/#5.2/#5.3, #6.2) ───────────────────────
// The right-hand panel for a selected file in Playbook / Workspace: metadata at the
// top (indented) and the file's contents below. Read-only display via fs.readFile.
export function FilePreviewPanel({ entry }: { entry: FsEntry }): JSX.Element {
  const [state, setState] = useState<{ text?: string; truncated?: boolean; error?: string; loading: boolean }>({ loading: true });
  useEffect(() => {
    let alive = true;
    setState({ loading: true });
    if (entry.type !== 'file') { setState({ loading: false }); return; }
    window.uai.fs.readFile(entry.path)
      .then(r => { if (!alive) return; if (r.ok) setState({ text: r.content, truncated: r.truncated, loading: false }); else setState({ error: r.error || 'Could not read this file.', loading: false }); })
      .catch(() => { if (alive) setState({ error: 'Could not read this file.', loading: false }); });
    return () => { alive = false; };
  }, [entry.path, entry.type]);

  return (
    <div className="pe-filepreview">
      <div className="pe-filepreview-meta">
        <div className="pe-fp-label">File</div><div className="pe-fp-val">{entry.name}</div>
        <div className="pe-fp-label">Path</div><div className="pe-fp-val mono">{entry.path}</div>
        <div className="pe-fp-label">Size · modified</div>
        <div className="pe-fp-val">{fmtSize(entry.size) || '—'}{entry.modified ? ` · ${new Date(entry.modified).toLocaleString()}` : ''}</div>
      </div>
      <button className="pe-open-btn pe-filepreview-open" onClick={() => window.uai.openPath(entry.path)}>⧉ Open in OS</button>
      <div className="pe-filepreview-contents">
        <div className="pe-fp-label">Contents</div>
        {entry.type !== 'file'
          ? <div className="pe-note">Select a file to preview its contents.</div>
          : state.loading
            ? <div className="pe-note">Loading…</div>
            : state.error
              ? <div className="pe-note">{state.error}</div>
              : <pre className="pe-fp-pre">{state.text || '(empty file)'}{state.truncated ? '\n…(truncated)' : ''}</pre>}
      </div>
    </div>
  );
}
