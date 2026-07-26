/**
 * ProjectOverview — the Overview aspect, composed as a DASHBOARD that fills the pane
 * (todo_0623 redesign). A card grid — Identity · Work · Team · Recent activity · Notes
 * · Docs — replacing the old metadata column that floated in an empty canvas.
 *
 * Design: docs/designs/2026-06-21-project-editor-design.md §2.1
 */

import { useState, useEffect } from 'react';
import type { ProjectCard, SessionCard } from '@uai/shared/cards';
import { type FsEntry, fmtSize } from './ProjectFolderTree';
import { useProjectConversations, nameColor, formatTime, type Conversation } from './ProjectComms';
import { trackingIdFrom } from './SessionLink';

const LIFECYCLE_COLORS: Record<string, string> = {
  active: 'var(--accent-green)', paused: 'var(--accent-yellow)',
  complete: 'var(--accent-blue)', archived: 'var(--text-muted)',
};
const NOTE_COLORS: Record<string, string> = {
  open: 'var(--accent-yellow)', done: 'var(--accent-green)', reviewing: 'var(--accent-purple)', blocked: 'var(--accent-red)',
};

const prettyRole = (r: string): string => r.replace(/[_-]+/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase());
function initials(name: string): string {
  const p = (name || '').replace(/[_-]/g, ' ').trim().split(/\s+/);
  return (((p[0]?.[0] || '') + (p[1]?.[0] || p[0]?.[1] || '')).toUpperCase()) || '?';
}
function Avatar({ name }: { name: string }): JSX.Element {
  return <span className="pe-avatar" style={{ background: nameColor(name) }}>{initials(name)}</span>;
}
// A conversation's representative "who" — the first non-PianoMan participant, resolved
// to a live session name when it's a session endpoint.
function convWho(c: Conversation, roster: SessionCard[]): string {
  const p = (c.participants || []).find(x => x !== 'piano_man') || (c.participants || [])[0] || '?';
  const tid = trackingIdFrom(p);
  if (tid) return roster.find(s => s.tracking_id === tid)?.display_name || tid.slice(0, 10);
  const m = String(p).match(/^([^(]+)\s*\(/);
  return m ? m[1].trim() : String(p).split('_')[0] || '?';
}

interface ProjectOverviewProps {
  project: ProjectCard;
  sessions: SessionCard[];                       // roster
  roleAssignments?: Record<string, string[]>;
  workSummary?: React.ReactNode;                 // the vital-signs bar
  onGotoTeam: () => void;
  onGotoComms?: () => void;
  onGotoWork?: () => void;
  onOpenSession?: (trackingId: string) => void;
  // Retained for prop compatibility (Docs file selection is not used by the dashboard).
  selectedFilePath?: string;
  onSelectFile?: (entry: FsEntry) => void;
  showDocs?: boolean;
}

function useWorkerNotes(names: string[]): Array<{ id: string; title: string; status: string }> | null {
  const [notes, setNotes] = useState<Array<{ id: string; title: string; status: string }> | null>(null);
  const key = names.filter(Boolean).join('|');
  useEffect(() => {
    let alive = true;
    (window.uai as any).notes?.forWorker(names.filter(Boolean))
      .then((n: Array<{ id: string; title: string; status: string }>) => { if (alive) setNotes(n); })
      .catch(() => { if (alive) setNotes([]); });
    return () => { alive = false; };
  }, [key]);   // eslint-disable-line react-hooks/exhaustive-deps
  return notes;
}

// Notes this worker is tagged on (todo_0419). Kept exported for other consumers.
export function WorkerNotes({ names }: { names: string[] }): JSX.Element | null {
  const notes = useWorkerNotes(names);
  if (!notes || notes.length === 0) return null;
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

function useDocs(dir: string): FsEntry[] {
  const [files, setFiles] = useState<FsEntry[]>([]);
  useEffect(() => {
    let alive = true;
    if (!dir) { setFiles([]); return; }
    window.uai.fs.listDir(`${dir}/docs`)
      .then(es => { if (alive) setFiles((es as FsEntry[]).filter(e => e.type === 'file').slice(0, 6)); })
      .catch(() => { if (alive) setFiles([]); });
    return () => { alive = false; };
  }, [dir]);
  return files;
}

export default function ProjectOverview({
  project, sessions, roleAssignments, workSummary, onGotoTeam, onGotoComms, onGotoWork, onOpenSession,
}: ProjectOverviewProps): JSX.Element {
  const roster = sessions;
  const roleEntries = Object.entries(roleAssignments || {});
  const memberRoles: Record<string, string[]> = {};
  roleEntries.forEach(([role, ms]) => ms.forEach(m => (memberRoles[m] ||= []).push(role)));
  const reviewer = roleEntries.find(([k]) => /reviewer/i.test(k));
  const lead = roleEntries.find(([k]) => /lead/i.test(k));
  const others = roleEntries.filter(([k]) => !/reviewer|lead/i.test(k));
  const seats = [
    { label: 'Reviewer', holder: reviewer?.[1]?.[0] || null },
    { label: 'Lead', holder: lead?.[1]?.[0] || null },
    ...others.map(([k, ms]) => ({ label: prettyRole(k), holder: ms[0] || null })),
  ];
  const seatless = roster.filter(s => !(memberRoles[s.display_name || s.tracking_id] || memberRoles[s.tracking_id]));
  const findTid = (name: string): string => roster.find(s => (s.display_name || s.tracking_id) === name)?.tracking_id || name;

  const { conversations } = useProjectConversations(roster.map(s => s.tracking_id).filter(Boolean), true);
  const docs = useDocs(project.working_dir || '');
  const notes = useWorkerNotes([project.display_name, (project as any).project_id, project.entity_id].filter(Boolean) as string[]);

  return (
    <div className="pe-detail-body pe-dash">
      {/* IDENTITY */}
      <section className="pe-dcard pe-d-identity">
        <div className="pe-id-top">
          <div className="pe-id-ic" aria-hidden="true">📁</div>
          <div className="pe-id-txt">
            <div className="pe-id-name">{project.display_name}</div>
            {project.goal && <div className="pe-id-goal">{project.goal}</div>}
          </div>
        </div>
        <div className="pe-chips">
          {project.lifecycle_status && <span className="pe-chip"><span className="pe-chip-d" style={{ background: LIFECYCLE_COLORS[project.lifecycle_status] || 'var(--text-muted)' }} />{project.lifecycle_status}</span>}
          <span className="pe-chip">⑂ {project.branch || 'main'}</span>
          <span className="pe-chip">git: {project.git_status}</span>
          {project.availability && <span className="pe-chip">{project.availability}</span>}
        </div>
        <div className="pe-metarow">
          <span className="k">Working dir</span>
          {project.working_dir
            ? <span className="v link" title="Open in OS" onClick={() => window.uai.openPath(project.working_dir)}>{project.working_dir} ⧉</span>
            : <span className="v">—</span>}
          {project.project_id && <><span className="k">Project ID</span><span className="v mono">{project.project_id}</span></>}
          {project.source_path && <><span className="k">Registry</span><span className="v mono">{project.source_path}</span></>}
        </div>
        {project.tags.length > 0 && (
          <div className="pe-tags">{project.tags.map(t => <span key={t} className="pe-tag">{t}</span>)}</div>
        )}
      </section>

      {/* WORK */}
      <section className="pe-dcard pe-d-work">
        <div className="pe-dcard-h"><span className="lbl">Work</span>{onGotoWork && <span className="link" onClick={onGotoWork}>open Work List →</span>}</div>
        {workSummary}
      </section>

      {/* TEAM */}
      <section className="pe-dcard pe-d-team">
        <div className="pe-dcard-h"><span className="lbl">Team</span><span className="link" onClick={onGotoTeam}>open Team →</span></div>
        <div className="pe-seats">
          {seats.map(s => (
            <div
              key={s.label}
              className={`pe-seat${s.holder ? '' : ' empty'}`}
              onClick={() => { if (s.holder) onOpenSession?.(findTid(s.holder)); }}
              title={s.holder ? `${s.label}: ${s.holder}` : `${s.label}: unfilled`}
            >
              {s.holder ? <Avatar name={s.holder} /> : <span className="pe-avatar pe-avatar-empty">+</span>}
              <div><div className="pe-seat-role">{s.label}</div><div className="pe-seat-who">{s.holder || 'unfilled'}</div></div>
            </div>
          ))}
        </div>
        {seatless.length > 0 && (
          <div className="pe-dmembers">
            {seatless.map(s => (
              <span key={s.entity_id} className="pe-dmchip" onClick={() => onOpenSession?.(s.tracking_id)}>
                <span className="pe-dmdot" style={{ background: s.process_status === 'running' ? 'var(--accent-green)' : 'var(--text-muted)' }} />
                {s.display_name || s.tracking_id.slice(0, 12)}
              </span>
            ))}
          </div>
        )}
      </section>

      {/* ACTIVITY */}
      <section className="pe-dcard pe-d-activity">
        <div className="pe-dcard-h"><span className="lbl">Recent activity</span>{onGotoComms && <span className="link" onClick={onGotoComms}>open Comms →</span>}</div>
        {conversations.length === 0
          ? <div className="pe-note">No conversations among the team yet.</div>
          : <div className="pe-convlist">
              {conversations.slice(0, 7).map(c => {
                const who = convWho(c, roster);
                return (
                  <div key={c.id} className="pe-convrow">
                    <Avatar name={who} />
                    <div className="pe-convmain">
                      <div className="pe-convtop">
                        <span className="pe-convwho">{who}</span>
                        {c.needs_input && <span className="pe-needs">needs input</span>}
                        <span className="pe-convt">{formatTime(c.last_activity)}</span>
                      </div>
                      <div className="pe-convsub">{c.topic || c.last_message_preview || '(untitled)'}</div>
                    </div>
                  </div>
                );
              })}
            </div>}
      </section>

      {/* NOTES */}
      <section className="pe-dcard pe-d-notes">
        <div className="pe-dcard-h"><span className="lbl">Notes</span></div>
        {!notes ? <div className="pe-note">…</div>
          : notes.length === 0 ? <div className="pe-note">No notes tagged on this project.</div>
          : <div className="pe-dnotes">
              {notes.slice(0, 6).map(n => (
                <div key={n.id} className="pe-dnote" title={n.id}>
                  <span className="st" style={{ background: NOTE_COLORS[n.status] || 'var(--text-muted)' }} />
                  <span className="ttl">{n.title}</span>
                  <span className="stt">{n.status}</span>
                </div>
              ))}
            </div>}
      </section>

      {/* DOCS */}
      <section className="pe-dcard pe-d-docs">
        <div className="pe-dcard-h"><span className="lbl">Docs</span></div>
        {docs.map(f => (
          <div key={f.path} className="pe-doclink" onClick={() => window.uai.openPath(f.path)}><span className="ic">📄</span>{f.name}</div>
        ))}
        {project.working_dir && (
          <div className="pe-doclink" onClick={() => window.uai.openPath(project.working_dir)}><span className="ic">📁</span>Open working dir ⧉</div>
        )}
        {docs.length === 0 && !project.working_dir && <div className="pe-note">No working directory.</div>}
      </section>
    </div>
  );
}

// ── Right Panel content for a selected file (retained; used by file aspects) ─────
export function FileMetaPanel({ entry }: { entry: FsEntry }): JSX.Element {
  return (
    <>
      <div className="pe-right-label">File</div>
      <div className="pe-right-name">{entry.name}</div>
      <div className="pe-right-label">Path</div>
      <div className="pe-right-val mono">{entry.path}</div>
      <div className="pe-right-label">Size · modified</div>
      <div className="pe-right-val">{fmtSize(entry.size) || '—'}{entry.modified ? ` · ${new Date(entry.modified).toLocaleString()}` : ''}</div>
      <button className="pe-open-btn" onClick={() => window.uai.openPath(entry.path)}>⧉ Open in OS</button>
    </>
  );
}
