/**
 * GitCommitViewPane — the "Git Commit View" tab: full detail of ONE commit —
 * message + metadata (AI-session requesters, todos), the files it changed, and a
 * per-file unified diff. Fed a commit hash from the Git File View (or type one).
 */

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useViewport } from '../viewport';

type Status = 'A' | 'M' | 'D';
interface CommitFile { path: string; status: Status; }
interface CommitDetail {
  ok: boolean; error?: string;
  hash?: string; short?: string; ts?: string; unix?: number;
  author?: string; subject?: string; body?: string;
  requesters?: string[]; todos?: string[]; files?: CommitFile[]; repo_root?: string;
}

const STATUS_COLOR: Record<Status, string> = { A: 'var(--accent-green)', M: 'var(--accent-yellow)', D: 'var(--accent-red)' };
const STATUS_LABEL: Record<Status, string> = { A: 'added', M: 'modified', D: 'deleted' };

function fmtTs(unix?: number): string {
  if (!unix) return '';
  return new Date(unix * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', year: 'numeric', hour: '2-digit', minute: '2-digit' });
}
function fmtBytes(b: number | null | undefined): string {
  if (b == null) return '—';
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(2)} MB`;
}
function diffLineClass(ln: string): string {
  if (ln.startsWith('@@')) return 'gfv-dl-hunk';
  if (ln.startsWith('+++') || ln.startsWith('---') || ln.startsWith('diff ') || ln.startsWith('index ')) return 'gfv-dl-meta';
  if (ln.startsWith('+')) return 'gfv-dl-add';
  if (ln.startsWith('-')) return 'gfv-dl-del';
  return 'gfv-dl-ctx';
}

interface Props { commitHash: string | null; dir: string; tabId?: string; active?: boolean; }

export default function GitCommitViewPane({ commitHash, dir, active }: Props): JSX.Element {
  const [hashInput, setHashInput] = useState('');
  const [detail, setDetail] = useState<CommitDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [selFile, setSelFile] = useState<string | null>(null);
  const [diffRes, setDiffRes] = useState<{ diff: string; sizeAtTo: number | null } | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  const [sessNames, setSessNames] = useState<Record<string, string>>({});

  useEffect(() => {
    let c = false;
    window.uai.sessions.list().then((list) => {
      if (c) return;
      const m: Record<string, string> = {};
      for (const s of (list as any[]) ?? []) if (s?.tracking_id) m[s.tracking_id] = s.display_name || s.tracking_id;
      setSessNames(m);
    }).catch(() => {});
    return () => { c = true; };
  }, []);

  const loadCommit = useCallback((hash: string) => {
    if (!hash.trim()) return;
    setLoading(true); setError(null); setSelFile(null); setDiffRes(null);
    window.uai.gitFileView.commit(dir, hash.trim())
      .then((r: any) => { if (r?.ok) { setDetail(r); setHashInput(r.short || hash); } else { setError(r?.error || 'Failed to load commit'); setDetail(null); } })
      .catch((e: any) => { setError(e?.message || 'Failed'); setDetail(null); })
      .finally(() => setLoading(false));
  }, [dir]);

  // Load whenever the File View hands us a commit.
  useEffect(() => { if (commitHash) loadCommit(commitHash); /* eslint-disable-next-line */ }, [commitHash]);

  // Selected file → its diff within this commit (base = commit^).
  useEffect(() => {
    if (!selFile || !detail?.hash) { setDiffRes(null); return; }
    let cancelled = false;
    setDiffLoading(true);
    window.uai.gitFileView.diff(dir, selFile, detail.hash, detail.hash)
      .then((r: any) => { if (!cancelled) setDiffRes(r?.ok ? { diff: r.diff ?? '', sizeAtTo: r.size_at_to ?? null } : null); })
      .catch(() => { if (!cancelled) setDiffRes(null); })
      .finally(() => { if (!cancelled) setDiffLoading(false); });
    return () => { cancelled = true; };
  }, [selFile, detail, dir]);

  const files = detail?.files ?? [];
  const counts = useMemo(() => files.reduce((a, f) => { a[f.status]++; return a; }, { A: 0, M: 0, D: 0 } as Record<Status, number>), [files]);

  // Component-architecture (#7): report the Commit View's live state so the
  // viewport describe API can introspect the loaded commit + selected file.
  useViewport('git_commit_view', () => ({
    visible: !!active,
    label: 'Git Commit View',
    state: {
      commit: detail?.short ?? null, subject: detail?.subject ?? null,
      files: files.length, selectedFile: selFile, loading, error,
      aiSessions: detail?.requesters ?? [], todos: detail?.todos ?? [],
    },
    children: [],
  }));

  return (
    <div className="gcv-pane">
      <div className="gcv-toolbar">
        <input className="gfv-dir-input" value={hashInput} onChange={(e) => setHashInput(e.target.value)}
          placeholder="commit hash…" spellCheck={false} onKeyDown={(e) => { if (e.key === 'Enter') loadCommit(hashInput); }} />
        <button className="gfv-load" onClick={() => loadCommit(hashInput)} disabled={loading}>{loading ? 'Loading…' : 'Load commit'}</button>
      </div>

      {error && <div className="gfv-error">⚠ {error}</div>}
      {!detail && !loading && !error && (
        <div className="gfv-empty">Pick a commit in <strong>Git File View</strong> (click its hash), or type a commit hash above.</div>
      )}

      {detail?.ok && (
        <div className="gcv-body">
          <div className="gcv-left">
            <div className="gcv-head">
              <span className="gcv-hash">{detail.short}</span>
              <span className="gcv-date">{fmtTs(detail.unix)}</span>
              <span className="gcv-author">{detail.author}</span>
            </div>
            <div className="gcv-subject">{detail.subject}</div>
            {detail.body && detail.body.trim() !== detail.subject && (
              <pre className="gcv-message">{detail.body}</pre>
            )}
            <dl className="gfv-detail-list gcv-meta">
              <dt>AI sessions</dt>
              <dd>{(detail.requesters ?? []).length
                ? <span className="gfv-ai-sessions">{detail.requesters!.map((id) => <span key={id} className="gfv-ai-chip" title={id}>{sessNames[id] || id.slice(0, 15)}</span>)}</span>
                : <span style={{ color: 'var(--text-muted)' }}>none recorded</span>}</dd>
              <dt>Todos</dt>
              <dd>{(detail.todos ?? []).length
                ? <span className="gfv-todo-chips">{detail.todos!.map((t) => <span key={t} className="gfv-todo-chip">{t}</span>)}</span>
                : <span style={{ color: 'var(--text-muted)' }}>none</span>}</dd>
            </dl>
            <div className="gcv-files-head">
              Files ({files.length})
              <span className="gfv-counts">
                {counts.A > 0 && <span style={{ color: STATUS_COLOR.A }}>+{counts.A}</span>}
                {counts.M > 0 && <span style={{ color: STATUS_COLOR.M }}>~{counts.M}</span>}
                {counts.D > 0 && <span style={{ color: STATUS_COLOR.D }}>−{counts.D}</span>}
              </span>
            </div>
            <div className="gcv-files">
              {files.map((f) => (
                <div key={f.path} className={`gfv-row gfv-file${selFile === f.path ? ' gfv-file-sel' : ''}`}
                  title={`${STATUS_LABEL[f.status]} — click for diff`} onClick={() => setSelFile(f.path)}>
                  <span className="gfv-badge" style={{ color: STATUS_COLOR[f.status], borderColor: STATUS_COLOR[f.status] }}>{f.status}</span>
                  <span className="gfv-filename" style={{ color: STATUS_COLOR[f.status] }}>{f.path.split('/').pop()}</span>
                  <span className="gcv-file-dir">{f.path.split('/').slice(0, -1).join('/')}</span>
                </div>
              ))}
            </div>
          </div>

          <div className="gcv-right">
            {!selFile ? <div className="gfv-empty">Select a file to see its diff in this commit.</div> : (
              <>
                <div className="gfv-diff-head">
                  <span className="gfv-diff-file">{selFile.split('/').pop()}</span>
                  <span className="gfv-diff-span">size {fmtBytes(diffRes?.sizeAtTo)}</span>
                  {diffLoading && <span className="gfv-diff-loading">loading…</span>}
                </div>
                <div className="gfv-diff-body">
                  {diffLoading && !diffRes ? <div className="gfv-empty">Loading diff…</div>
                    : !diffRes || !diffRes.diff.trim() ? <div className="gfv-empty">No textual diff (binary or empty).</div>
                    : diffRes.diff.split('\n').map((ln, i) => <div key={i} className={`gfv-dl ${diffLineClass(ln)}`}>{ln || ' '}</div>)}
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
