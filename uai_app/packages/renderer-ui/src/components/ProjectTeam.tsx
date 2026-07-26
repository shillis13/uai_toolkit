/**
 * ProjectTeam — the Team aspect of the Project Editor.
 *
 * Top: named seats and their assigned AIs; seatless members appear in the roster.
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

import { useState, useEffect } from 'react';
import type { SessionCard } from '@uai/shared/cards';
import { nameColor } from './ProjectComms';
import { buildAssigneeOptions } from '../utils/assignee-options';

const PLATFORM_LABELS: Record<string, string> = {
  claude_cli: 'Claude', codex_cli: 'Codex', gemini_cli: 'Gemini',
};

interface ProjectTeamDetailProps {
  sessions: SessionCard[];
  /** All sessions (teams only) — candidates for the add-member picker. */
  allSessions?: SessionCard[];
  /** Registry role_assignments for this worker: role name → member name(s). */
  roleAssignments?: Record<string, string[]>;
  /** Registry role_contexts: role name → context composition/file ref(s). */
  roleContexts?: Record<string, string[]>;
  selectedId: string | null;
  onSelect: (trackingId: string) => void;
  onOpenSession: (trackingId: string) => void;
  /** Assign (member=name) or unassign-keep-slot (member=null) a role's holder. */
  onSetRole?: (role: string, member: string | null) => void;
  onAddRole?: (role: string) => void;
  onRemoveRole?: (role: string) => void;
  /** Set (context=ref) or clear (context=null) a role's context reference. */
  onSetRoleContext?: (role: string, context: string | null) => void;
  onAddMember?: (name: string) => void;
  onRemoveMember?: (name: string) => void;
}

const prettyRole = (r: string): string => r.replace(/[_-]+/g, ' ').replace(/\b\w/g, ch => ch.toUpperCase());
// Core slots are always shown and never removable; every other role is user-managed.
const isCoreRole = (k: string): boolean => /reviewer|^lead$|lead/i.test(k);

// One shared session dropdown (todo_0623 #4.2) — grouped Active/Stopped exactly like
// the Todo-editor assignee picker, via the shared buildAssigneeOptions util. The option
// value is the member key (display_name || tracking_id) the team handlers use.
function SessionSelect({ sessions, value, firstOption, onPick, title, extraCurrent }: {
  sessions: SessionCard[]; value: string; firstOption: string;
  onPick: (memberKey: string | null) => void; title?: string; extraCurrent?: string;
}): JSX.Element {
  const opts = buildAssigneeOptions({ sessions });
  const keyFor = (uri: string): string => {
    const tid = uri.replace('uai://session/', '');
    return sessions.find(x => x.tracking_id === tid)?.display_name || tid;
  };
  const groups = (['Active sessions', 'Stopped sessions'] as const)
    .map(g => ({ g, items: opts.filter(o => o.grp === g) }))
    .filter(x => x.items.length > 0);
  const known = new Set<string>();
  groups.forEach(gr => gr.items.forEach(o => known.add(keyFor(o.uri))));
  return (
    <select className="pe-role-picker" value={value} title={title} onChange={e => onPick(e.target.value || null)}>
      <option value="">{firstOption}</option>
      {extraCurrent && !known.has(extraCurrent) && <option value={extraCurrent}>{extraCurrent}</option>}
      {groups.map(({ g, items }) => (
        <optgroup key={g} label={g}>
          {items.map(o => { const k = keyFor(o.uri); return <option key={o.uri} value={k}>{o.label}</option>; })}
        </optgroup>
      ))}
    </select>
  );
}

export default function ProjectTeamDetail({
  sessions, allSessions, roleAssignments, roleContexts, selectedId,
  onSelect, onOpenSession, onSetRole, onAddRole, onRemoveRole, onSetRoleContext, onAddMember, onRemoveMember,
}: ProjectTeamDetailProps): JSX.Element {
  const selected = sessions.find(s => s.tracking_id === selectedId) || null;
  const findSession = (name: string): SessionCard | null =>
    sessions.find(s => s.display_name === name || s.tracking_id === name) || null;
  const [newRole, setNewRole] = useState('');
  // Case-insensitive context lookup for a role key.
  const ctxFor = (key: string): string => {
    const ents = Object.entries(roleContexts || {});
    const hit = ents.find(([k]) => k.toLowerCase() === key.toLowerCase());
    return (hit?.[1] || [])[0] || '';
  };

  // Suggestions for the per-role CONTEXT field: real context items a role could
  // load (bundles = compositions, plus roles/skills/knowledge/instructions/globals).
  // The field stays free-text — this is a datalist of ids, not a hard constraint.
  const [ctxOptions, setCtxOptions] = useState<Array<{ id: string; label: string }>>([]);
  useEffect(() => {
    if (!onSetRoleContext) return;
    let alive = true;
    const KINDS = new Set(['bundle', 'global', 'instruction', 'knowledge', 'skill', 'role']);
    (window as { uai?: { context?: { run?: (v: string, a: string[]) => Promise<{ ok?: boolean; data?: unknown }> } } })
      .uai?.context?.run?.('list', [])
      .then(res => {
        if (!alive || !res?.ok || !Array.isArray(res.data)) return;
        const opts = (res.data as Array<{ id?: string; kind?: string; title?: string; name?: string }>)
          .filter(x => x.kind && KINDS.has(x.kind))
          .map(x => ({ id: String(x.id), label: String(x.title || x.name || x.id) }))
          .sort((a, b) => a.id.localeCompare(b.id));
        setCtxOptions(opts);
      })
      .catch(() => { /* suggestions are best-effort */ });
    return () => { alive = false; };
  }, [onSetRoleContext]);

  // Load-on-assume: stage a role's context into its assigned member's session.
  const [applyStatus, setApplyStatus] = useState<Record<string, string>>({});
  const [applying, setApplying] = useState<Record<string, boolean>>({});
  const applyContext = async (roleKey: string, member: string, context: string) => {
    setApplying(s => ({ ...s, [roleKey]: true }));
    setApplyStatus(s => ({ ...s, [roleKey]: '' }));
    try {
      const api = (window as { uai?: { roleContext?: { apply?: (m: string, c: string) => Promise<{ ok?: boolean; count?: number; error?: string }> } } }).uai;
      const res = await api?.roleContext?.apply?.(member, context);
      setApplyStatus(s => ({
        ...s,
        [roleKey]: res?.ok
          ? `✓ staged ${res.count} file(s) to ${member} — loads on their next turn`
          : `⚠ ${res?.error || 'failed'}`,
      }));
    } catch (e) {
      setApplyStatus(s => ({ ...s, [roleKey]: `⚠ ${e instanceof Error ? e.message : String(e)}` }));
    } finally {
      setApplying(s => ({ ...s, [roleKey]: false }));
    }
  };

  // Invert role_assignments → member name → team role labels (used to identify
  // which members already appear under a named seat).
  const roleEntries = Object.entries(roleAssignments || {});
  const memberRoles: Record<string, string[]> = {};
  for (const [role, members] of roleEntries) {
    for (const m of members) (memberRoles[m] ||= []).push(prettyRole(role));
  }

  // Reviewer + Lead are the two always-present, called-out slots; every other
  // key is a user-managed named role.
  const reviewerEntry = roleEntries.find(([k]) => /reviewer/i.test(k));
  const leadEntry = roleEntries.find(([k]) => /^lead$|lead/i.test(k));
  const reviewerMembers = reviewerEntry?.[1] ?? [];
  const leadMembers = leadEntry?.[1] ?? [];
  const otherEntries = roleEntries.filter(([k]) => !isCoreRole(k));

  // Reviewer is a SUGGESTION now, not required — only soft-warn when a KNOWN
  // non-Codex session holds it (a name-only member stays quiet).
  const reviewerNonCodex = reviewerMembers.filter(m => {
    const s = findSession(m);
    return s && s.platform && s.platform !== 'codex_cli';
  });
  const reviewerWarn = reviewerNonCodex.length
    ? `A Codex session is recommended as reviewer — ${reviewerNonCodex.join(', ')} isn't.`
    : null;

  const memberChip = (m: string) => {
    const c = nameColor(m);
    const s = findSession(m);
    const plat = s?.platform ? (PLATFORM_LABELS[s.platform] || s.platform) : '';
    return (
      <span
        key={m}
        className={`pe-roster-chip${selectedId && s?.tracking_id === selectedId ? ' on' : ''}`}
        style={{ borderColor: c }}
        onClick={() => onSelect(s?.tracking_id || m)}
        onDoubleClick={() => onOpenSession(s?.tracking_id || m)}
        title={`${m}${plat ? ` — ${plat}` : ''} — double-click to open Session tab`}
      >
        <span className="pe-item-dot" style={{ background: c }} />
        <span style={{ color: c }}>{m}</span>
      </span>
    );
  };

  // Picker for a role slot: choose a member or unassign (keeps the slot). Includes
  // the current holder as an option even if it's not in the roster.
  const rolePicker = (writeKey: string, members: string[]) => {
    if (!onSetRole) return null;
    const current = members[0] || '';
    return (
      <SessionSelect
        sessions={sessions}
        value={current}
        firstOption="— unassigned —"
        extraCurrent={current}
        onPick={v => onSetRole(writeKey, v)}
        title={`Who fills the "${writeKey}" seat`}
      />
    );
  };

  const roleRow = (
    label: string,
    members: string[],
    opts?: { tag?: string; warn?: string | null; hint?: string | null; writeKey?: string; removable?: boolean },
  ) => (
    <div className="pe-role-row" key={opts?.writeKey || label}>
      <div className="pe-role-head">
        <span className="pe-role-name">{label}</span>
        {opts?.tag && <span className="pe-role-tag" style={{ color: 'var(--text-muted)' }}>{opts.tag}</span>}
        {opts?.removable && onRemoveRole && opts.writeKey && (
          <button
            className="pe-role-del"
            title={`Remove the "${opts.writeKey}" seat`}
            onClick={() => onRemoveRole(opts.writeKey as string)}
          >×</button>
        )}
      </div>
      {/* Assignee + context on ONE horizontal line (todo_0623 Team #1). The assign
          dropdown IS the assignee display — no separate holder chip, so the assignee
          is never listed twice (#2). Context sits to the RIGHT of the dropdown. */}
      <div className="pe-role-assign">
        {opts?.writeKey && onSetRole
          ? rolePicker(opts.writeKey, members)
          : (members.length > 0
              ? members.map(memberChip)
              : <span className="pe-role-empty" style={{ color: 'var(--text-muted)' }}>unassigned</span>)}
        {opts?.writeKey && onSetRoleContext && (() => {
          const cur = ctxFor(opts.writeKey);
          return (
            <div className="pe-role-ctx">
              <span className="pe-role-ctx-label">context</span>
              <input
                key={`ctx-${opts.writeKey}-${cur}`}
                className="pe-role-ctx-input"
                list="pe-ctx-options"
                defaultValue={cur}
                placeholder="none — composition or file the seat loads"
                title="Context this seat loads when a session fills it (Enter to save)"
                onKeyDown={e => { if (e.key === 'Enter') { onSetRoleContext(opts.writeKey as string, (e.target as HTMLInputElement).value.trim() || null); (e.target as HTMLInputElement).blur(); } }}
                onBlur={e => { const v = e.target.value.trim(); if (v !== cur) onSetRoleContext(opts.writeKey as string, v || null); }}
              />
            </div>
          );
        })()}
      </div>
      {opts?.writeKey && onSetRoleContext && members.length > 0 && ctxFor(opts.writeKey) && (
        <div className="pe-role-apply-row">
          <button
            className="pe-role-apply"
            disabled={!!applying[opts.writeKey]}
            title={`Stage this seat's context into ${members[0]}'s session (loads on their next turn)`}
            onClick={() => applyContext(opts.writeKey as string, members[0], ctxFor(opts.writeKey as string))}
          >{applying[opts.writeKey] ? 'Loading…' : `Load context → ${members[0]}`}</button>
          {applyStatus[opts.writeKey] && (
            <span className="pe-role-apply-status" style={{ color: applyStatus[opts.writeKey].startsWith('✓') ? 'var(--accent-green)' : 'var(--accent-orange)' }}>
              {applyStatus[opts.writeKey]}
            </span>
          )}
        </div>
      )}
      {opts?.warn && <div className="pe-role-warn" style={{ color: 'var(--accent-orange)' }}>⚠ {opts.warn}</div>}
      {opts?.hint && <div className="pe-role-hint" style={{ color: 'var(--text-muted)' }}>{opts.hint}</div>}
    </div>
  );

  const submitNewRole = () => {
    const r = newRole.trim();
    if (!r || !onAddRole) return;
    if (roleEntries.some(([k]) => k.toLowerCase() === r.toLowerCase())) { setNewRole(''); return; }
    onAddRole(r);
    setNewRole('');
  };

  // Add-member picker candidates: sessions not already members.
  const memberNames = new Set(sessions.map(s => s.display_name || s.tracking_id));
  const addCandidates = (allSessions || []).filter(s => !s.archived && !memberNames.has(s.display_name || s.tracking_id));

  // Members shown below = on the team but holding NO named seat (todo_0623 #4.5).
  // Seat-holders appear under their seat above and are not repeated here.
  const seatless = sessions.filter(s =>
    (memberRoles[s.display_name || s.tracking_id] || memberRoles[s.tracking_id] || []).length === 0);

  return (
    <div className="pe-detail-body">
      {onSetRoleContext && (
        <datalist id="pe-ctx-options">
          {ctxOptions.map(o => <option key={o.id} value={o.id}>{o.label}</option>)}
        </datalist>
      )}
      {/* "Seats" (todo_0623 #4.3) — the team's role-slots, renamed to avoid colliding
          with a session's own adopted "roles" shown on the member chips below. */}
      <div className="pe-section-label">Seats <span className="pe-section-hint">— roles on this team a member fills</span></div>
      <div className="pe-roles">
        {roleRow('Reviewer', reviewerMembers, {
          tag: 'reviews the team’s work',
          warn: reviewerWarn,
          hint: reviewerMembers.length === 0 ? 'Optional. A Codex session is recommended.' : null,
          writeKey: reviewerEntry?.[0] || 'reviewer',
        })}
        {roleRow('Lead', leadMembers, {
          tag: 'optional',
          hint: leadMembers.length === 0 ? 'No lead — members self-select work from the pool.' : null,
          writeKey: leadEntry?.[0] || 'lead',
        })}
        {otherEntries.map(([role, members]) => roleRow(prettyRole(role), members, { writeKey: role, removable: true }))}
      </div>
      {onAddRole && (
        <div className="pe-role-add">
          {/* One affordance: type a name and press Enter (todo_0623 #4.1 — the separate
              +Add Role button was redundant with this input). */}
          <input
            className="pe-role-add-input"
            placeholder="New seat name… (Enter to add)"
            value={newRole}
            onChange={e => setNewRole(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter') submitNewRole(); }}
          />
        </div>
      )}

      <div className="pe-splitH" />
      <div className="pe-section-label">Members <span className="pe-section-hint">— on the team without a specific seat</span></div>
      {sessions.length === 0 && (
        <div className="pe-note">No members yet (a team's registry <code>members</code>, or sessions whose working dir matches the project).</div>
      )}
      {sessions.length > 0 && seatless.length === 0 && (
        <div className="pe-note">Every member holds a seat above.</div>
      )}
      {/* Quiet, neutral chips (todo_0623 #4.4) — a small status dot + plain name, matching
          how a session reads in the seat dropdown above, instead of loud per-name colors. */}
      <div className="pe-roster">
        {seatless.map(s => {
          const name = s.display_name || s.tracking_id;
          const running = s.process_status === 'running';
          return (
            <div
              key={s.entity_id}
              className={`pe-roster-chip pe-roster-chip-plain${selectedId === s.tracking_id ? ' on' : ''}`}
              onClick={() => onSelect(s.tracking_id)}
              onDoubleClick={() => onOpenSession(s.tracking_id)}
              title={`${name} — double-click to open Session tab`}
            >
              <span className="pe-item-dot" style={{ background: running ? 'var(--accent-green)' : 'var(--text-muted)' }} />
              <span>{s.display_name || s.tracking_id.slice(0, 12)}</span>
              {s.roles && s.roles.length > 0 && <span className="pe-roster-role pe-roster-selfrole">{s.roles.join(' · ')}</span>}
              {onRemoveMember && (
                <button
                  className="pe-roster-del"
                  title={`Remove ${name} from the team`}
                  onClick={e => { e.stopPropagation(); onRemoveMember(name); }}
                >×</button>
              )}
            </div>
          );
        })}
      </div>
      {onAddMember && (
        <div className="pe-member-add">
          <SessionSelect
            sessions={addCandidates}
            value=""
            firstOption="+ Add member…"
            onPick={v => { if (v) onAddMember(v); }}
            title="Add a session as a team member"
          />
        </div>
      )}

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
