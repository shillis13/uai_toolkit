/**
 * ProjectTeam — the Team aspect of the Project Editor.
 *
 * Top: Roles & AIs assigned to the project, each in its own identity color.
 * Selecting an AI → its session metadata fills the Right Panel (TeamMemberPanel,
 * decision 3) and its work/files render in the lower detail. Double-click / Open
 * → opens that AI's Session tab.
 *
 * Real now: roster + per-AI session meta + open-session action (sessions are live).
 * Scaffolded: per-AI work (needs `owner` exposed on todos.list) and files (needs
 * the fs.listDir IPC, todo_0317).
 *
 * Design: docs/designs/2026-06-21-project-editor-design.md §2.3
 */

import type { SessionCard } from '@uai/shared/cards';
import { nameColor } from './ProjectComms';

const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude', codex_cli: 'Codex', gemini_cli: 'Gemini',
};

interface ProjectTeamDetailProps {
  sessions: SessionCard[];
  selectedId: string | null;
  onSelect: (trackingId: string) => void;
  onOpenSession: (trackingId: string) => void;
}

export default function ProjectTeamDetail({ sessions, selectedId, onSelect, onOpenSession }: ProjectTeamDetailProps): JSX.Element {
  const selected = sessions.find(s => s.tracking_id === selectedId) || null;

  return (
    <div className="pe-detail-body">
      <div className="pe-section-label">Roles &amp; AIs</div>
      {sessions.length === 0 && (
        <div className="pe-note">No sessions associated with this project yet (sessions whose working dir matches the project).</div>
      )}
      <div className="pe-roster">
        {sessions.map(s => {
          const c = nameColor(s.display_name || s.tracking_id);
          return (
            <div
              key={s.entity_id}
              className={`pe-roster-chip${selectedId === s.tracking_id ? ' on' : ''}`}
              style={{ borderColor: c }}
              onClick={() => onSelect(s.tracking_id)}
              onDoubleClick={() => onOpenSession(s.tracking_id)}
              title={`${s.display_name} — double-click to open Session tab`}
            >
              <span className="pe-item-dot" style={{ background: c }} />
              <span style={{ color: c }}>{s.display_name || s.tracking_id.slice(0, 12)}</span>
              {s.roles && s.roles.length > 0 && <span className="pe-roster-role">{s.roles.join(' · ')}</span>}
            </div>
          );
        })}
      </div>

      {selected && (
        <>
          <div className="pe-splitH" />
          <div className="pe-section-label">{selected.display_name} · work &amp; files</div>
          <div className="pe-scaffold-note">
            Per-AI work and files render here. Needs assignment (<code>assigned</code>) exposed on
            <code> todos.list</code> (to filter this AI's todos) and the <code>fs.listDir</code> IPC
            for files (todo_0317). Metadata + open are live now — see the Right Panel, or double-click to open the Session tab.
          </div>
        </>
      )}
    </div>
  );
}

// ── Right Panel content for a selected team member (decision 3) ──────────────
export function TeamMemberPanel({ session, onOpen }: { session: SessionCard; onOpen: (id: string) => void }): JSX.Element {
  const c = nameColor(session.display_name || session.tracking_id);
  return (
    <>
      <div className="pe-right-label">AI · session</div>
      <div className="pe-right-name" style={{ color: c }}>{session.display_name || session.tracking_id.slice(0, 14)}</div>
      <div className="pe-right-label">Platform</div>
      <div className="pe-right-val">{PLATFORM_LABELS[session.platform] || session.platform}</div>
      {session.process_status && (<><div className="pe-right-label">State</div><div className="pe-right-val">{session.process_status}</div></>)}
      {session.roles && session.roles.length > 0 && (<><div className="pe-right-label">Roles</div><div className="pe-right-val">{session.roles.join(' · ')}</div></>)}
      <div className="pe-right-label">Tracking ID</div>
      <div className="pe-right-val mono">{session.tracking_id}</div>
      <button className="pe-open-btn" onClick={() => onOpen(session.tracking_id)}>⧉ Open Session tab</button>
    </>
  );
}
