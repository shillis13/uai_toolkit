/**
 * TodoItemView — the ONE shared todo-item detail, used identically by:
 *   • Work Mgr                     (WorkMgrPane)
 *   • Session ▸ Work ▸ Work List   (ProjectEditor, session worker)
 *   • Project/Team ▸ Work List     (ProjectEditor, project/team worker)
 *
 * Subtabs (PianoMan's spec): Contents · Activities · Related · Files.
 *   Contents  — parent path · reformatted notes.md (no Created/Updated/Status) ·
 *               Provenance · Open Questions & Recommendations · Decisions & Pivots
 *   Activities — History · Comms / Chat comments · Reviews
 *   Related    — Children · Artifacts
 *   Files      — folder hierarchy + file preview (git view later; binary = no preview)
 *
 * Self-contained: fetches notes/provenance/files via window.uai.todos.*. The caller
 * supplies the (optional) Status + Assigned editors so each host keeps its own controls.
 */

import { useEffect, useMemo, useState } from 'react';
import type { ReactNode } from 'react';
import ProjectFolderTree, { type FsEntry } from './ProjectFolderTree';
import SessionLink, { LinkifySessions, trackingIdFrom } from './SessionLink';
import { executeCommand } from '../utils/execute-command';
import GitFileViewPane from './GitFileViewPane';
import type { GitFileViewFilter } from './git-file-view-scope';

export interface TodoLite {
  id: string; name?: string; title?: string; dirName?: string; status: string;
  tags?: string[]; flags?: string[]; assigned?: string[]; project?: string | null;
  parent?: string | null; children?: string[]; created?: string; updated?: string;
  path?: string; rel_path?: string;
}

const STATUS_COLORS: Record<string, string> = {
  In_Progress: 'var(--accent-blue)', Blocked: 'var(--accent-red)', Reviewing: 'var(--accent-purple)',
  Accepting: 'var(--accent-cyan)', Ready: 'var(--accent-green)', Needs_Derivation: 'var(--accent-yellow)',
  Needs_Research: 'var(--accent-orange)', Triaging: 'var(--text-sec, #b8c0cc)', Done: 'var(--pe-done, #55607a)',
  Cancelled: 'var(--text-muted)',
};
const statusColor = (s: string) => STATUS_COLORS[s] || 'var(--text-muted)';
const statusLabel = (s: string) => (s || '').replace(/_/g, ' ');
const todoNum = (id: string) => (id.match(/(\d+)/)?.[1] || id);
// leaf key from an id/dirName or `a/b/leaf` rel-path — the LAST todo_NNNN.
const tKey = (s?: string | null): string | null => { const ms = (s || '').match(/todo_\d+/g); return ms ? ms[ms.length - 1] : null; };
const titleOf = (t: TodoLite) => (t.title || t.name || t.dirName || t.id || '').replace(/^todo_\d+[_-]?/, '').replace(/_/g, ' ').trim() || t.id;
const fmtDate = (s?: string) => s ? new Date(s).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' }) : '';

// Split notes.md into a preamble + ## sections.
function parseNotes(md: string): { preamble: string; sections: Array<{ heading: string; body: string }> } {
  if (!md) return { preamble: '', sections: [] };
  const lines = md.split('\n');
  const first = lines.findIndex(l => /^##\s+/.test(l));
  if (first === -1) return { preamble: md.trim(), sections: [] };
  const preamble = lines.slice(0, first).join('\n').trim();
  const sections: Array<{ heading: string; body: string }> = [];
  let cur: { heading: string; body: string[] } | null = null;
  for (const line of lines.slice(first)) {
    const h = line.match(/^##\s+(.*)$/);
    if (h) { if (cur) sections.push({ heading: cur.heading, body: cur.body.join('\n').trim() }); cur = { heading: h[1].trim(), body: [] }; }
    else if (cur) cur.body.push(line);
  }
  if (cur) sections.push({ heading: cur.heading, body: cur.body.join('\n').trim() });
  return { preamble, sections };
}
// Metadata already shown elsewhere (in the header) — never repeat in Contents.
const META_HEADING = /^(created|updated|status|owner|assigned|id|ref|tags?|flags?)\b/i;
// Strip lines that duplicate header metadata (title heading, **Created:**, etc.) from
// free text so the Summary/field bodies never repeat created/updated/status/owner.
const META_LINE = /^\s*(?:#{1,6}\s.*|[*_]{0,2}\s*(?:created|updated|last[ _]updated|status|owner|assigned|id|ref|priority)\s*[:*_].*)$/i;
function stripMetaLines(text: string): string {
  return text.split('\n').filter(l => !META_LINE.test(l)).join('\n').replace(/\n{3,}/g, '\n\n').trim();
}

interface Provenance { origin: Record<string, string>; history: Array<{ ts: string; status: string; session: string; note: string }> }

type Sub = 'contents' | 'activities' | 'related' | 'files';
interface Section { heading: string; body: string }

// notes.md convention (PianoMan): ## = a subtab, ### = a section within it. The
// canonical subtab names map ## headings to the UI tabs; anything unrecognized (or a
// legacy flat-## file) falls back to Contents so old notes still render.
const CANON_TAB: Record<string, Sub> = {
  contents: 'contents', content: 'contents',
  activities: 'activities', activity: 'activities',
  'links & artifacts': 'related', 'links and artifacts': 'related', links: 'related', artifacts: 'related', related: 'related',
  files: 'files',
};
const canonTab = (name: string): Sub | null => CANON_TAB[name.trim().toLowerCase()] ?? null;

// Parse notes.md into user-authored sections keyed by subtab. Structured mode when any
// ## matches a canonical subtab; else legacy (flat ## → Contents sections).
function parseStructured(md: string): { byTab: Record<Sub, Section[]>; structured: boolean } {
  const byTab: Record<Sub, Section[]> = { contents: [], activities: [], related: [], files: [] };
  if (!md.trim()) return { byTab, structured: false };
  const h2 = [...md.matchAll(/^##\s+(.+)$/gm)].map(m => m[1].trim());
  const structured = h2.some(canonTab);
  if (!structured) {
    const { preamble, sections } = parseNotes(md);
    const intro = stripMetaLines(preamble);
    if (intro) byTab.contents.push({ heading: '', body: intro });
    for (const s of sections) if (!META_HEADING.test(s.heading)) byTab.contents.push(s);
    return { byTab, structured: false };
  }
  let curTab: Sub | null = null, curSec: { heading: string; body: string[] } | null = null, intro: string[] = [];
  const flushSec = () => { if (curTab && curSec) byTab[curTab].push({ heading: curSec.heading, body: curSec.body.join('\n').trim() }); curSec = null; };
  const flushIntro = () => { if (curTab) { const t = stripMetaLines(intro.join('\n')); if (t) byTab[curTab].unshift({ heading: '', body: t }); } intro = []; };
  for (const line of md.split('\n')) {
    const m2 = line.match(/^##\s+(.+)$/), m3 = line.match(/^###\s+(.+)$/);
    if (m2) { flushSec(); flushIntro(); curTab = canonTab(m2[1]); intro = []; }
    else if (m3) { flushSec(); if (!curTab) curTab = 'contents'; curSec = { heading: m3[1].trim(), body: [] }; }
    else if (curSec) curSec.body.push(line);
    else if (curTab) intro.push(line);
  }
  flushSec(); flushIntro();
  return { byTab, structured: true };
}
const SUBTABS: Array<{ key: Sub; label: string }> = [
  { key: 'contents', label: 'Contents' },
  { key: 'activities', label: 'Activity & Links' },   // merged: Activities + Links & Artifacts (todo_0413)
  { key: 'files', label: 'Files' },
];

function Bullets({ items }: { items: string[] }): JSX.Element {
  return <ul className="tiv-list">{items.map((x, i) => <li key={i}>{x}</li>)}</ul>;
}
function Sample({ children }: { children: ReactNode }): JSX.Element {
  return <div className="tiv-sample"><span className="tiv-sample-tag">sample · capture not wired</span>{children}</div>;
}

export default function TodoItemView({ todo, allTodos = [], search = '', onSelect, statusEditor, assigneeEditor, moveControl }: {
  todo: TodoLite; allTodos?: TodoLite[]; search?: string;
  onSelect?: (id: string) => void; statusEditor?: ReactNode; assigneeEditor?: ReactNode; moveControl?: ReactNode;
}): JSX.Element {
  const [sub, setSub] = useState<Sub>('contents');
  const [notes, setNotes] = useState<string>('');
  const [prov, setProv] = useState<Provenance | null>(null);
  const [files, setFiles] = useState<Array<{ rel: string; size: number; isDir: boolean }>>([]);
  const [selFile, setSelFile] = useState<FsEntry | null>(null);
  const [loading, setLoading] = useState(true);
  const [reloadKey, setReloadKey] = useState(0);
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState('');
  const [saving, setSaving] = useState(false);
  const [peeking, setPeeking] = useState(false);   // [peek] → read-only raw notes.md in a bottom panel
  const [editSec, setEditSec] = useState<string | null>(null);   // heading of the ### section being edited in place (todo_0405)
  const [secDraft, setSecDraft] = useState('');
  const [secSaving, setSecSaving] = useState(false);

  useEffect(() => {
    let alive = true; setLoading(true); setSelFile(null);
    Promise.all([
      window.uai.todos.read(todo.id).catch(() => ''),
      (window.uai.todos as any).provenance?.(todo.id).catch(() => null) ?? Promise.resolve(null),
      window.uai.todos.files(todo.id).catch(() => []),
    ]).then(([n, p, f]: any[]) => {
      if (!alive) return;
      setNotes(n || ''); setProv(p || null); setFiles(Array.isArray(f) ? f : []); setLoading(false);
    });
    return () => { alive = false; };
  }, [todo.id, reloadKey]);

  // Editing exits when switching to another todo.
  useEffect(() => { setEditing(false); }, [todo.id]);

  const startEdit = () => { setDraft(notes); setEditing(true); };
  // Per-section edit (todo_0405): splice the new body into notes.md between `### <heading>`
  // and the next `##`/`###`, then save the whole file via todo_mgr.
  const startSecEdit = (heading: string, body: string) => { setEditSec(heading); setSecDraft(body); };
  const saveSecEdit = async () => {
    if (editSec == null) return;
    setSecSaving(true);
    try {
      const lines = notes.split('\n'); const out: string[] = []; let i = 0; let done = false;
      while (i < lines.length) {
        const m = lines[i].match(/^###\s+(.+)$/);
        if (!done && m && m[1].trim() === editSec) {
          out.push(lines[i]); i++;
          while (i < lines.length && !/^#{2,3}\s/.test(lines[i])) i++;
          out.push('', secDraft.trim(), ''); done = true; continue;
        }
        out.push(lines[i]); i++;
      }
      await executeCommand('todo.writeNotes', { id: todo.id, content: out.join('\n') });
    } finally { setSecSaving(false); setEditSec(null); setReloadKey(k => k + 1); }
  };
  const saveEdit = async () => {
    setSaving(true);
    try { await executeCommand('todo.writeNotes', { id: todo.id, content: draft }); }
    finally { setSaving(false); setEditing(false); setReloadKey(k => k + 1); }
  };

  const { byTab } = useMemo(() => parseStructured(notes), [notes]);
  const contentsSecs = byTab.contents.filter(s => !META_HEADING.test(s.heading));
  const sessionAssignee = trackingIdFrom((todo.assigned && todo.assigned[0]) || '');
  const hasOpenQ = contentsSecs.some(s => /question|recommendation/i.test(s.heading));
  const hasDecisions = contentsSecs.some(s => /decision|pivot/i.test(s.heading));

  // Parent path (ancestors) + children resolved from the full todo set. parent/children
  // are `a/b/leaf` rel-paths, so match by the LAST todo_NNNN (the leaf), not by t.id.
  const byKey = useMemo(() => { const m = new Map<string, TodoLite>(); allTodos.forEach(t => { const k = tKey(t.id || t.dirName); if (k) m.set(k, t); }); return m; }, [allTodos]);
  const ancestors = useMemo(() => {
    const out: TodoLite[] = []; let p = byKey.get(tKey(todo.parent) || ''); let guard = 0;
    while (p && guard++ < 12) { out.unshift(p); p = byKey.get(tKey(p.parent) || ''); }
    return out;
  }, [todo, byKey]);
  const children = useMemo(() => (todo.children || []).map(c => byKey.get(tKey(c) || '')).filter(Boolean) as TodoLite[], [todo, byKey]);
  // Artifacts = work products created while implementing the todo (live under data/).
  // NOT the todo's definition files (notes/origin/history/status/tag) which sit at the root.
  const artifacts = files.filter(f => !f.isDir && /^data\//.test(f.rel));
  // Git-backed Files view: pin the embedded Git File View's filter to THIS todo —
  // the files changed by commits carrying its `Todo:` trailer — scanning ai_general
  // from the todo's creation date. Memoized so the embed only reloads on re-select.
  const todoKey = tKey(todo.id || todo.dirName) || todo.id;
  const gitFilter = useMemo<GitFileViewFilter>(() => ({ kind: 'todo', value: todoKey }), [todoKey]);
  const gitSince = useMemo(() => (todo.created ? todo.created.slice(0, 10) : ''), [todo.created]);

  const nn = titleOf(todo);
  const nameSeed = todo.dirName || todo.id;
  const sampleDecisions = [`Chose the lighter-weight implementation for "${nn}" to avoid blocking on infra.`, `Deferred edge-case handling until the core flow is verified.`];
  const sampleQuestions = [`Open: is the scope of "${nn}" fully settled, or are there edge cases to confirm?`, `Recommendation: add a follow-up todo for test coverage once this lands.`];
  const base = Math.abs([...nameSeed].reduce((h, c) => ((h << 5) - h + c.charCodeAt(0)) | 0, 0)) % 40 + 8;
  const sampleComments = [{ turn: base, text: `Discussed scope of "${nn}" — agreed to keep the first pass minimal.` }, { turn: base + 7, text: `Pivot: original approach dropped in favor of a simpler path.` }];

  return (
    <div className="tiv">
      {/* Header — Open · id · title · dates | Status · Assigned. Clear rule below it. */}
      <div className="tiv-header">
        <div className="tiv-header-top">
          <button className="tiv-open" onClick={() => window.uai.todos.open(todo.id)} title="Reveal folder in Finder">Open</button>
          {!editing
            ? <>
                <button className="tiv-edit-btn" onClick={startEdit} title="Edit notes.md (## subtab / ### section)">✎ Edit</button>
                <button className={`tiv-edit-btn${peeking ? ' on' : ''}`} onClick={() => setPeeking(p => !p)} title="Peek the raw notes.md file (read-only)">👁 Peek</button>
              </>
            : <>
                <button className="tiv-edit-btn tiv-save" onClick={saveEdit} disabled={saving} title="Save via todo_mgr">{saving ? 'Saving…' : '✓ Save'}</button>
                <button className="tiv-edit-btn" onClick={() => setEditing(false)} disabled={saving} title="Discard changes">Cancel</button>
              </>}
          <span className="tiv-id"><span className="tiv-id-pre">todo_</span>{todoNum(todo.id)}</span>
          <span className="tiv-title">{titleOf(todo)}</span>
          <span className="tiv-spacer" />
          <span className="tiv-dates">
            {todo.created && <span title="created">created {fmtDate(todo.created)}</span>}
            {todo.updated && <span title="last updated">updated {fmtDate(todo.updated)}</span>}
          </span>
        </div>
        <div className="tiv-header-status">
          <span className="tiv-slabel">Status</span>
          {statusEditor ?? <span className="tiv-badge" style={{ background: statusColor(todo.status) }}>{statusLabel(todo.status)}</span>}
          <span className="tiv-slabel tiv-slabel-2">Assigned</span>
          {assigneeEditor ?? <span className="tiv-aval">{(todo.assigned && todo.assigned[0]) ? (todo.assigned[0].split('/').pop() || todo.assigned[0]) : '—'}</span>}
          {sessionAssignee && <SessionLink id={sessionAssignee} label="↗ open" />}
        </div>
      </div>

      {editing ? (
        <div className="tiv-editor">
          <div className="tiv-editor-hint">Editing <b>notes.md</b> — <code>## Subtab</code> (Contents / Activities / Links &amp; Artifacts) and <code>### Section</code>. Fields (created, status, …) are engine-owned; don't add them here. Saved via todo_mgr.</div>
          <textarea className="tiv-editor-area" value={draft} onChange={e => setDraft(e.target.value)} spellCheck={false} autoFocus
            onKeyDown={e => {
              if (e.key === 'Escape') { e.preventDefault(); setEditing(false); }        // Esc = Cancel
              else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) { e.preventDefault(); saveEdit(); }  // Cmd/Ctrl+Enter = Save
            }} />
        </div>
      ) : (<>
      {/* Subtabs — distinct band, clearly separated from the title/status above. */}
      <div className="tiv-subtabs">
        {SUBTABS.map(t => (
          <button key={t.key} className={`tiv-subtab ${sub === t.key ? 'on' : ''}`} onClick={() => setSub(t.key)}>{t.label}</button>
        ))}
      </div>

      <div className="tiv-body">
        {loading && <div className="tiv-muted">Loading…</div>}

        {!loading && sub === 'contents' && (
          <>
            <section className="tiv-sec">
              <div className="tiv-h">Parent path {moveControl && <span className="tiv-move">{moveControl}</span>}</div>
              {/* Ancestors only — an item is not a parent to itself; parentless → just "root". */}
              <div className="tiv-crumbs">
                <span className="tiv-crumb-root">root</span>
                {ancestors.map(a => { const aid = a.id || a.dirName || ''; return (
                  <span key={aid}><span className="tiv-crumb-sep">/</span>
                    <a className="tiv-link" onClick={() => onSelect?.(aid)}>todo_{todoNum(aid)} {titleOf(a).slice(0, 20)}</a></span>
                ); })}
              </div>
            </section>

            {/* User-authored fields — ## Contents / ### sections from notes.md, in order.
                Each has an inline ✎ to edit just that section (todo_0405). */}
            {contentsSecs.map((s, i) => {
              const body = stripMetaLines(s.body);
              if (!body && editSec !== s.heading) return null;
              const isEditing = editSec === s.heading;
              return (
                <section key={i} className="tiv-sec">
                  {s.heading && (
                    <div className="tiv-h">{s.heading}
                      {!editing && s.heading && !isEditing && <button className="tiv-sec-edit" title="Edit this section" onClick={() => startSecEdit(s.heading, body)}>✎</button>}
                    </div>
                  )}
                  {isEditing ? (
                    <div className="tiv-sec-editor">
                      <textarea className="tiv-sec-area" value={secDraft} autoFocus spellCheck={false}
                        onChange={e => setSecDraft(e.target.value)}
                        onKeyDown={e => { if (e.key === 'Escape') setEditSec(null); else if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) saveSecEdit(); }} />
                      <div className="tiv-sec-btns">
                        <button className="tiv-edit-btn tiv-save" onClick={saveSecEdit} disabled={secSaving}>{secSaving ? 'Saving…' : '✓ Save'}</button>
                        <button className="tiv-edit-btn" onClick={() => setEditSec(null)} disabled={secSaving}>Cancel</button>
                      </div>
                    </div>
                  ) : <p className="tiv-notes-body">{body}</p>}
                </section>
              );
            })}

            {/* System — provenance from origin.yml (not user-editable). */}
            <section className="tiv-sec">
              <div className="tiv-h">Provenance</div>
              {prov && Object.keys(prov.origin || {}).length ? (
                <div className="tiv-prov">{Object.entries(prov.origin).map(([k, v]) => {
                  const tid = trackingIdFrom(String(v));
                  return <span key={k} className="tiv-kv"><span className="tiv-k">{k}</span><span className="tiv-v">{tid ? <SessionLink id={tid} /> : String(v)}</span></span>;
                })}</div>
              ) : <div className="tiv-muted">No origin.yml.</div>}
            </section>

            {/* Placeholders only when the author hasn't written these sections yet. */}
            {!hasOpenQ && (
              <section className="tiv-sec"><div className="tiv-h">Open questions &amp; recommendations</div><Sample><Bullets items={sampleQuestions} /></Sample></section>
            )}
            {!hasDecisions && (
              <section className="tiv-sec"><div className="tiv-h">Decisions &amp; pivots</div><Sample><Bullets items={sampleDecisions} /></Sample></section>
            )}
          </>
        )}

        {!loading && sub === 'activities' && (
          <>
            <section className="tiv-sec">
              <div className="tiv-h">History</div>
              {prov && prov.history.length ? prov.history.map((h, i) => (
                <div key={i} className="tiv-histline">
                  <span className="tiv-hist-ts">{h.ts}</span>
                  <span style={{ color: statusColor(h.status) }}>{statusLabel(h.status)}</span>
                  {h.session && <SessionLink id={h.session} />}
                  <span className="tiv-hist-note"><LinkifySessions text={h.note} /></span>
                </div>
              )) : <div className="tiv-muted">No history.log entries.</div>}
            </section>
            <section className="tiv-sec">
              <div className="tiv-h">Comms · Chat comments</div>
              <Sample>{sampleComments.map((c, i) => (
                <div key={i} className="tiv-comment"><span className="tiv-turn">Turn {c.turn} ↗</span><span>{c.text}</span></div>
              ))}</Sample>
            </section>
            {/* User-authored Activities sections (## Activities / ### Reviews, …). */}
            {byTab.activities.filter(s => !META_HEADING.test(s.heading)).map((s, i) => {
              const body = stripMetaLines(s.body);
              if (!body) return null;
              return <section key={i} className="tiv-sec">{s.heading && <div className="tiv-h">{s.heading}</div>}<p className="tiv-notes-body">{body}</p></section>;
            })}
            {!byTab.activities.some(s => /review/i.test(s.heading)) && (
              <section className="tiv-sec"><div className="tiv-h">Reviews</div><div className="tiv-muted">No reviews recorded for this item yet.</div></section>
            )}
          </>
        )}

        {!loading && sub === 'activities' && (
          <>
            <section className="tiv-sec">
              <div className="tiv-h">Children ({children.length})</div>
              {children.length === 0 ? <div className="tiv-muted">No child items.</div> : (
                <div className="tiv-childlist">{children.map(c => (
                  <div key={c.id} className="tiv-childrow" onClick={() => onSelect?.(c.id)}>
                    <span className="tiv-cdot" style={{ background: statusColor(c.status) }} />
                    <span className="tiv-id-sm">todo_{todoNum(c.id)}</span>
                    <span className="tiv-title-sm">{titleOf(c)}</span>
                  </div>
                ))}</div>
              )}
            </section>
            <section className="tiv-sec">
              <div className="tiv-h">Artifacts ({artifacts.length})</div>
              {artifacts.length === 0 ? <div className="tiv-muted">No artifacts in this todo's folder.</div> : (
                <div className="tiv-artifacts">{artifacts.map(f => (
                  <div key={f.rel} className="tiv-artifact" onClick={() => (window.uai.todos as any).openData?.(todo.id, f.rel.replace(/^data\//, ''))} title="Open externally">
                    {f.rel} <span className="tiv-muted">{f.size} B</span>
                  </div>
                ))}</div>
              )}
            </section>
            {/* User-authored links (## Links & Artifacts / ### sections). */}
            {byTab.related.filter(s => !META_HEADING.test(s.heading)).map((s, i) => {
              const body = stripMetaLines(s.body);
              if (!body) return null;
              return <section key={i} className="tiv-sec">{s.heading && <div className="tiv-h">{s.heading}</div>}<p className="tiv-notes-body">{body}</p></section>;
            })}
          </>
        )}

        {!loading && sub === 'files' && (
          <section className="tiv-sec tiv-files-sec">
            <div className="tiv-files-hint">Files changed by commits for <b>{todoKey}</b> — a git-backed change view scoped to this todo (from its <code>Todo:</code> commit trailers). Scan starts at the todo's creation.</div>
            <div className="tiv-gitview">
              <GitFileViewPane
                tabId={`wm-files-${todoKey}`}
                embedded
                showScopeBar={false}
                allowScopeChange={false}
                dir="ai_general"
                since={gitSince}
                filter={gitFilter}
              />
            </div>
          </section>
        )}
      </div>
      </>)}
      {peeking && !editing && (
        <div className="tiv-peek">
          <div className="tiv-peek-bar">
            <span className="tiv-peek-title">👁 notes.md — read-only</span>
            <span className="tiv-spacer" />
            <button className="tiv-peek-close" onClick={() => setPeeking(false)} title="Close peek">✕</button>
          </div>
          <pre className="tiv-peek-body">{notes || '(empty notes.md)'}</pre>
        </div>
      )}
    </div>
  );
}
