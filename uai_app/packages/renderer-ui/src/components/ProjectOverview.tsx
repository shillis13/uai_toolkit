/**
 * ProjectOverview — the Overview aspect.
 *
 * Project metadata + collapsible Docs (a real file tree rooted at the project
 * working dir, via ProjectFolderTree / fs.listDir) + a Team summary that links to
 * the Team aspect. Selecting a file surfaces its metadata in the Right Panel
 * (FileMetaPanel) and double-click opens it in the OS.
 *
 * Design: docs/designs/2026-06-21-project-editor-design.md §2.1
 */

import { useState, useEffect } from 'react';
import type { ProjectCard, SessionCard } from '@uai/shared/cards';
import ProjectFolderTree, { type FsEntry, fmtSize } from './ProjectFolderTree';
import { nameColor } from './ProjectComms';

const LIFECYCLE_COLORS: Record<string, string> = {
  active: 'var(--accent-green)', paused: 'var(--accent-yellow)',
  complete: 'var(--accent-blue)', archived: 'var(--text-muted)',
};

interface ProjectOverviewProps {
  project: ProjectCard;
  sessions: SessionCard[];
  selectedFilePath?: string;
  onSelectFile: (entry: FsEntry) => void;
  onGotoTeam: () => void;
  workSummary?: React.ReactNode;   // Work vital-signs bar — rendered below Docs (todo_0416)
}

function Row({ k, v, color }: { k: string; v: string; color?: string }): JSX.Element {
  return (
    <div className="pe-meta-row">
      <span className="pe-meta-k">{k}</span>
      <span className="pe-meta-v" style={color ? { color } : undefined}>{v || '—'}</span>
    </div>
  );
}

// Notes this worker is tagged on (todo_0419). Shared shape used by projects/teams
// (and, later, the Session Work overview).
export function WorkerNotes({ names }: { names: string[] }): JSX.Element | null {
  const [notes, setNotes] = useState<Array<{ id: string; title: string; status: string }> | null>(null);
  const key = names.filter(Boolean).join('|');
  useEffect(() => {
    let alive = true;
    (window.uai as any).notes?.forWorker(names.filter(Boolean))
      .then((n: Array<{ id: string; title: string; status: string }>) => { if (alive) setNotes(n); })
      .catch(() => { if (alive) setNotes([]); });
    return () => { alive = false; };
  }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  if (!notes || notes.length === 0) return null;   // hide when none
  return (
    <div className="pe-collapse">
      <div className="pe-collapse-head"><span className="pe-collapse-chev">▾</span> Notes ({notes.length})</div>
      <div className="pe-notes-list">
        {notes.map(n => (
          <div key={n.id} className={`pe-note-row pe-note-${n.status}`} title={n.id}>
            <span className={`pe-note-dot pe-note-dot-${n.status}`} />
            <span className="pe-note-title">{n.title}</span>
            <span className="pe-note-status">{n.status}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

export default function ProjectOverview({ project, sessions, selectedFilePath, onSelectFile, onGotoTeam, workSummary }: ProjectOverviewProps): JSX.Element {
  const [docsOpen, setDocsOpen] = useState(true);
  const [filesOpen, setFilesOpen] = useState(false);
  const [teamOpen, setTeamOpen] = useState(true);

  return (
    <div className="pe-detail-body">
      <div className="pe-meta">
        {project.goal && <Row k="Goal" v={project.goal} />}
        <Row k="Lifecycle" v={project.lifecycle_status || '—'} color={LIFECYCLE_COLORS[project.lifecycle_status || ''] } />
        <Row k="Branch" v={`${project.branch || 'main'}  ·  ${project.git_status}`} />
        {/* clickable working dir → opens the folder in the OS (#5) */}
        <div className="pe-meta-row">
          <span className="pe-meta-k">Working dir</span>
          {project.working_dir
            ? <span className="pe-meta-v pe-link" title="Open folder in OS" onClick={() => window.uai.openPath(project.working_dir)}>{project.working_dir} ⧉</span>
            : <span className="pe-meta-v">—</span>}
        </div>
        {project.tags.length > 0 && <Row k="Tags" v={project.tags.map(t => `[${t}]`).join(' ')} />}
      </div>

      {/* Team above Docs & Files (#2) */}
      <div className="pe-collapse">
        <div className="pe-collapse-head" onClick={() => setTeamOpen(o => !o)}>
          <span className="pe-collapse-chev">{teamOpen ? '▾' : '▸'}</span> Team ({sessions.length})
          <span className="pe-collapse-hint" onClick={(e) => { e.stopPropagation(); onGotoTeam(); }}>open Team aspect →</span>
        </div>
        {teamOpen && (
          sessions.length === 0
            ? <div className="pe-note">No sessions associated with this project.</div>
            : <div className="pe-roster">
                {sessions.slice(0, 12).map(s => {
                  const c = nameColor(s.display_name || s.tracking_id);
                  return (
                    <div key={s.entity_id} className="pe-roster-chip" style={{ borderColor: c }} onClick={onGotoTeam}>
                      <span className="pe-item-dot" style={{ background: c }} />
                      <span style={{ color: c }}>{s.display_name || s.tracking_id.slice(0, 12)}</span>
                      {s.roles && s.roles.length > 0 && <span className="pe-roster-role">{s.roles.join(' · ')}</span>}
                    </div>
                  );
                })}
              </div>
        )}
      </div>

      {/* Notes this worker is tagged on (todo_0419) */}
      <WorkerNotes names={[project.display_name, (project as any).project_id, project.entity_id].filter(Boolean) as string[]} />

      {/* Docs (documentation) — conceptually separate from Files (#3) */}
      <div className="pe-collapse">
        <div className="pe-collapse-head" onClick={() => setDocsOpen(o => !o)}>
          <span className="pe-collapse-chev">{docsOpen ? '▾' : '▸'}</span> Docs
          <span className="pe-collapse-hint">documentation (docs/)</span>
        </div>
        {docsOpen && (
          project.working_dir
            ? <ProjectFolderTree rootPath={`${project.working_dir}/docs`} selectedPath={selectedFilePath} onSelectFile={onSelectFile} />
            : <div className="pe-note">No working directory on this project.</div>
        )}
      </div>

      {/* Work summary (vital-signs bar) — below Docs (todo_0416) */}
      {workSummary}

      {/* Files (the working dir) */}
      <div className="pe-collapse">
        <div className="pe-collapse-head" onClick={() => setFilesOpen(o => !o)}>
          <span className="pe-collapse-chev">{filesOpen ? '▾' : '▸'}</span> Files
          <span className="pe-collapse-hint">double-click a file → open in OS</span>
        </div>
        {filesOpen && (
          project.working_dir
            ? <ProjectFolderTree rootPath={project.working_dir} selectedPath={selectedFilePath} onSelectFile={onSelectFile} />
            : <div className="pe-note">No working directory on this project.</div>
        )}
      </div>
    </div>
  );
}

// ── Right Panel content for a selected file (decision 3) ────────────────────
export function FileMetaPanel({ entry }: { entry: FsEntry }): JSX.Element {
  return (
    <>
      <div className="pe-right-label">File</div>
      <div className="pe-right-name">{entry.name}</div>
      <div className="pe-right-label">Path</div>
      <div className="pe-right-val mono">{entry.path}</div>
      <div className="pe-right-label">Size · modified</div>
      <div className="pe-right-val">{fmtSize(entry.size) || '—'}{entry.modified ? ` · ${new Date(entry.modified).toLocaleString()}` : ''}</div>
      <div className="pe-right-label">Authored by</div>
      <div className="pe-right-val" style={{ color: 'var(--accent-yellow)' }}>blame-by-session pending (Component-7, other fork)</div>
      <button className="pe-open-btn" onClick={() => window.uai.openPath(entry.path)}>⧉ Open in OS</button>
    </>
  );
}
