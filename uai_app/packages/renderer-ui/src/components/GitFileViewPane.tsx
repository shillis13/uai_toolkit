/**
 * GitFileViewPane — "Git File View" app-tab.
 *
 * Shows the files Added / Modified / Deleted under a directory (recursively)
 * between two git commits, chosen with a time slider. The backend
 * (scripts/utils/git_file_view.py) is called ONCE for a dir + date range and
 * returns every commit that touches the dir with its per-file A/M/D. This pane
 * then computes the net delta between the two selected commits entirely
 * client-side, so dragging the slider handles updates the tree in real time.
 *
 * Slider: a time axis (oldest → newest commit) with a tick at every commit, and
 * two handles (From / To) that snap to commits. The delta = the net effect of
 * the commits in the [From..To] span (inclusive).
 */

import { useState, useCallback, useMemo, useRef, useEffect } from 'react';
import { useToast } from './Toast';
import { useViewport } from '../viewport';
import { GFV_SET_SCOPE_EVENT, type GitFileViewScope, type GitFileViewFilter } from './git-file-view-scope';
import { getGfvSnapshot, setGfvSnapshot } from '../stores/git-viewer-state-store';

type Status = 'A' | 'M' | 'D';
interface GfvFile { path: string; status: Status; }
interface GfvCommit {
  hash: string; short: string; ts: string; unix: number;
  author: string; subject: string; files: GfvFile[];
  requesters?: string[];   // AI session tracking-ids (Requester: trailer)
  todos?: string[];        // Todo: <id> trailers / inline todo_NNNN
  body?: string;           // full commit message (for expand/collapse)
}
interface GfvResult {
  ok: boolean; error?: string;
  repo_root?: string; dir?: string; dir_rel?: string;
  since?: string; until?: string; commit_count?: number;
  commits?: GfvCommit[];
}

const STATUS_COLOR: Record<Status, string> = {
  A: 'var(--accent-green)', M: 'var(--accent-yellow)', D: 'var(--accent-red)',
};
const STATUS_LABEL: Record<Status, string> = { A: 'added', M: 'modified', D: 'deleted' };

const daysAgoISO = (n: number) => new Date(Date.now() - n * 86400000).toISOString().slice(0, 10);

// ── Net delta between two commits (inclusive [from..to] span), reconstructed
// from the per-commit A/M/D changelog — equivalent to `git diff` of the span. ──
function computeNetDelta(commits: GfvCommit[], fromIdx: number, toIdx: number, match?: (c: GfvCommit) => boolean): Map<string, Status> {
  const first = new Map<string, Status>();
  const last = new Map<string, Status>();
  const lo = Math.max(0, Math.min(fromIdx, toIdx));
  const hi = Math.min(commits.length - 1, Math.max(fromIdx, toIdx));
  for (let i = lo; i <= hi; i++) {
    if (match && !match(commits[i])) continue;   // filter by contributor/AI/todo (#8)
    for (const f of commits[i].files) {
      if (!first.has(f.path)) first.set(f.path, f.status);
      last.set(f.path, f.status);
    }
  }
  const net = new Map<string, Status>();
  for (const [p, fst] of first) {
    const lst = last.get(p)!;
    if (fst === 'A') {
      if (lst !== 'D') net.set(p, 'A');          // added in span (still present)
    } else {
      net.set(p, lst === 'D' ? 'D' : 'M');       // existed before span
    }
  }
  return net;
}

// ── Build a nested tree from the net-delta paths (dir-relative). ──────────────
interface TreeNode {
  name: string; path: string; isDir: boolean;
  status?: Status; fullPath?: string; children: TreeNode[];
  counts: { A: number; M: number; D: number };
}
function buildTree(delta: Map<string, Status>, dirRel: string): TreeNode {
  const root: TreeNode = { name: dirRel ? dirRel.split('/').pop()! : '(repo root)', path: '', isDir: true, children: [], counts: { A: 0, M: 0, D: 0 } };
  const prefix = dirRel ? dirRel + '/' : '';
  for (const [full, status] of delta) {
    const rel = full.startsWith(prefix) ? full.slice(prefix.length) : full;
    const parts = rel.split('/');
    let node = root;
    node.counts[status]++;
    for (let i = 0; i < parts.length; i++) {
      const isLeaf = i === parts.length - 1;
      const seg = parts[i];
      const childPath = parts.slice(0, i + 1).join('/');
      let child = node.children.find((c) => c.name === seg && c.isDir === !isLeaf);
      if (!child) {
        child = { name: seg, path: childPath, isDir: !isLeaf, children: [], counts: { A: 0, M: 0, D: 0 }, ...(isLeaf ? { status, fullPath: full } : {}) };
        node.children.push(child);
      }
      if (!isLeaf) child.counts[status]++;
      node = child;
    }
  }
  const sortRec = (n: TreeNode) => {
    n.children.sort((a, b) => (Number(b.isDir) - Number(a.isDir)) || a.name.localeCompare(b.name));
    n.children.forEach(sortRec);
  };
  sortRec(root);
  return root;
}

// Axis tick label — granularity adapts to the visible span (hours → days → months).
function fmtAxis(unix: number, spanSec: number): string {
  const d = new Date(unix * 1000);
  if (spanSec <= 2 * 86400) return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
  if (spanSec <= 120 * 86400) return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
  return d.toLocaleDateString(undefined, { month: 'short', year: '2-digit' });
}

function fmtBytes(b: number | null | undefined): string {
  if (b == null) return '—';
  if (b < 1024) return `${b} B`;
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`;
  return `${(b / 1024 / 1024).toFixed(2)} MB`;
}

function fmtTs(unix: number): string {
  if (!unix) return '';
  return new Date(unix * 1000).toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/**
 * Embeddable anywhere (#6). With no props it's the standalone Git File View mgr
 * (arbitrary repo/dir + range). Dropped into another view (Session→Work→Files,
 * dashboards, …), pass dir/since/until to preset the scope — those placements are
 * just specific settings of this one component.
 *
 * Scope-bar control (#5): `showScopeBar` sets whether the editable Repo/Dir/Date
 * bar starts open; `allowScopeChange` sets whether the user can change scope at
 * all (bar + the "⚙ Scope" chip). A fixed embed passes both false so the host's
 * values stand and the user can't touch them. Either way, a host can still drive
 * the scope programmatically with the advertised `setGitFileViewScope()` command
 * (#4) — target this instance by `tabId` or broadcast to all.
 */
interface GfvProps {
  tabId?: string;
  dir?: string;
  since?: string;
  until?: string;
  embedded?: boolean;
  showScopeBar?: boolean;      // start with the editable scope bar open (default !embedded)
  allowScopeChange?: boolean;  // let the user change scope via bar/chip (default !embedded)
  filter?: GitFileViewFilter | null;  // controlled delta filter (host-driven embeds); null clears
  onOpenCommit?: (hash: string, dir: string) => void;   // -> Git Commit View
}

export default function GitFileViewPane({ tabId, dir: dirProp, since: sinceProp, until: untilProp, embedded, showScopeBar, allowScopeChange, filter: filterProp, onOpenCommit }: GfvProps): JSX.Element {
  const { showToast } = useToast();
  // Persistence (#6): hydrate this tab's prior UI state so switching away and back
  // restores the selected file, filter, scope, handles, zoom, etc. Only for the
  // standalone tab — embedded instances are driven by props, not a saved snapshot.
  const restored = useRef(embedded ? undefined : getGfvSnapshot(tabId)).current;
  // Default to the ai_general repo ROOT so the standalone view is repo-wide — its
  // todo/AI/contributor filters then list everything in the repo (not just commits
  // under one subdir), matching what the embedded todo Files view shows.
  const [dir, setDir] = useState(dirProp ?? restored?.dir ?? 'ai_general');
  const [since, setSince] = useState(sinceProp ?? restored?.since ?? daysAgoISO(30));
  const [until, setUntil] = useState(untilProp ?? restored?.until ?? '');
  // Scope-bar visibility (#5): whether the user may change scope, and whether the
  // editable bar is currently open (vs the slim "⚙ Scope" chip).
  const canChange = allowScopeChange ?? !embedded;
  const [barOpen, setBarOpen] = useState(showScopeBar ?? restored?.barOpen ?? !embedded);
  const [data, setData] = useState<GfvResult | null>((restored?.data as GfvResult | null) ?? null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [fromIdx, setFromIdx] = useState(restored?.fromIdx ?? 0);
  const [toIdx, setToIdx] = useState(restored?.toIdx ?? 0);
  // #2 play-through: which extent is locked while stepping (null = shift the whole window).
  const [lockSide, setLockSide] = useState<'left' | 'right' | null>(restored?.lockSide ?? null);
  const [collapsed, setCollapsed] = useState<Set<string>>(new Set(restored?.collapsed ?? []));
  // Zoom: when set, the timeline axis rescales to [lo,hi] unix so densely-clustered
  // commits spread out. null = full range. (#7)
  const [zoom, setZoom] = useState<{ lo: number; hi: number } | null>(restored?.zoom ?? null);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const dragRef = useRef<null | 'from' | 'to'>(null);
  const paneRef = useRef<HTMLDivElement | null>(null);

  const commits = data?.ok ? (data.commits ?? []) : [];
  const n = commits.length;

  const load = useCallback(async (loadDir: string, loadSince: string, loadUntil: string) => {
    setLoading(true); setError(null);
    try {
      const res = (await window.uai.gitFileView.read(loadDir.trim(), loadSince || undefined, loadUntil || undefined)) as GfvResult;
      if (!res?.ok) { setError(res?.error || 'Failed to load'); setData(null); return; }
      setData(res);
      const c = res.commits ?? [];
      setFromIdx(0);
      setToIdx(Math.max(0, c.length - 1));
      setCollapsed(new Set());
      setZoom(null);
      setLockSide(null);
      if (c.length === 0) showToast('No commits touched this directory in the range', 'info');
    } catch (e: any) {
      setError(e?.message || 'Failed to load'); setData(null);
    } finally { setLoading(false); }
  }, [showToast]);
  const loadCurrent = useCallback(() => load(dir, since, until), [load, dir, since, until]);
  // #3 dir picker: native folder chooser → set dir + load (repo inferred from the dir's .git).
  const browse = useCallback(async () => {
    const picked = await window.uai.dialog?.showOpenDirectory?.(dir);
    if (picked) { setDir(picked); load(picked, since, until); }
  }, [dir, since, until, load]);
  // #4 repo selector: list the workspace's git repos (with host) once on mount.
  const [repos, setRepos] = useState<{ path: string; name: string; host: string }[]>([]);
  useEffect(() => {
    let cancelled = false;
    window.uai.gitFileView.repos('.').then((r: any) => {
      if (!cancelled && r?.ok) setRepos(r.repos ?? []);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);
  const pickRepo = useCallback((repoPath: string) => {
    if (repoPath) { setDir(repoPath); load(repoPath, since, until); }
  }, [since, until, load]);

  // Auto-load on mount, and reload when embedding props change the scope. On the
  // very first mount, if we restored a snapshot WITH loaded data (#6), keep it
  // instead of reloading — that's what makes returning to the tab instant.
  const didInitRef = useRef(false);
  useEffect(() => {
    if (dirProp) { setDir(dirProp); setSince(sinceProp ?? daysAgoISO(30)); setUntil(untilProp ?? ''); }
    if (!didInitRef.current) {
      didInitRef.current = true;
      if (!dirProp && restored?.data) return;   // restored — don't clobber
    }
    void load(dirProp ?? dir, sinceProp ?? since, untilProp ?? until);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dirProp, sinceProp, untilProp]);

  // #4 advertised scope command: any code can call setGitFileViewScope({tabId?,
  // dir?, since?, until?}) and this instance applies the given fields + reloads.
  // Omitting tabId broadcasts to every mounted view; matching tabId targets one.
  useEffect(() => {
    const onSetScope = (ev: Event) => {
      const d = (ev as CustomEvent<GitFileViewScope>).detail || {};
      if (d.tabId && d.tabId !== tabId) return;
      // Filter (#4): present-but-null clears it; omitted key leaves it unchanged.
      if ('filter' in d) setFilter(d.filter ?? null);
      const scopeChanged = d.dir !== undefined || d.since !== undefined || d.until !== undefined;
      const nextDir = d.dir ?? dir;
      const nextSince = d.since ?? since;
      const nextUntil = d.until ?? until;
      if (scopeChanged) {
        setDir(nextDir); setSince(nextSince); setUntil(nextUntil);
        void load(nextDir, nextSince, nextUntil);
      }
    };
    window.addEventListener(GFV_SET_SCOPE_EVENT, onSetScope as EventListener);
    return () => window.removeEventListener(GFV_SET_SCOPE_EVENT, onSetScope as EventListener);
  }, [tabId, dir, since, until, load]);

  // Time bounds of the slider — the ZOOM window when set, else first → last commit.
  const fullT0 = n > 0 ? commits[0].unix : 0;
  const fullT1 = n > 0 ? commits[n - 1].unix : 1;
  const t0 = zoom ? zoom.lo : fullT0;
  const t1 = zoom ? zoom.hi : fullT1;
  const span = Math.max(1, t1 - t0);
  const xOf = useCallback((unix: number) => ((unix - t0) / span) * 100, [t0, span]);
  const inView = useCallback((unix: number) => unix >= t0 - 1 && unix <= t1 + 1, [t0, t1]);

  // Filter the delta by contributor / AI session / todo (#8).
  const [filter, setFilter] = useState<GitFileViewFilter | null>(restored?.filter ?? null);
  const matchFilter = useCallback((c: GfvCommit): boolean => {
    if (!filter) return true;
    if (filter.kind === 'author') return c.author === filter.value;
    if (filter.kind === 'ai') return (c.requesters ?? []).includes(filter.value ?? '');
    if (filter.kind === 'todos') { const set = filter.values ?? []; return (c.todos ?? []).some((t) => set.includes(t)); }
    return (c.todos ?? []).includes(filter.value ?? '');
  }, [filter]);
  // Controlled filter: when a host passes a `filter` prop it drives the delta
  // filter (the Work Mgr Files tab pins it to the selected todo). Omitted = uncontrolled.
  useEffect(() => { if (filterProp !== undefined) setFilter(filterProp); }, [filterProp]);

  // Extents follow the filter: when a filter is active, snap the From/To handles to
  // the EARLIEST and LATEST matching commit so the timeline brackets exactly the
  // filtered work. Recomputes only when the matching set changes — dragging a handle
  // afterward is preserved (fromIdx/toIdx aren't deps here).
  const matchingIdxs = useMemo(() => {
    if (!filter || n === 0) return null;
    const out: number[] = [];
    for (let i = 0; i < n; i++) if (matchFilter(commits[i])) out.push(i);
    return out;
  }, [filter, n, commits, matchFilter]);
  const firstMatch = matchingIdxs && matchingIdxs.length ? matchingIdxs[0] : null;
  const lastMatch = matchingIdxs && matchingIdxs.length ? matchingIdxs[matchingIdxs.length - 1] : null;
  // Initial view follows the filter: when a filter is active, the From/To handles
  // snap to the earliest/latest matching commit AND the timeline starts ZOOMED to
  // that duration (the "initial zoom"); clearing the filter returns to the full
  // data range. Embedded views fit immediately; the standalone tab respects its
  // restored snapshot on first load, then fits whenever the filter changes.
  const fitInitRef = useRef(false);
  useEffect(() => {
    if (n === 0) return;
    const firstRun = !fitInitRef.current;
    fitInitRef.current = true;
    if (firstRun && !embedded) return;   // standalone first load → keep restored/loaded view
    if (filter && firstMatch !== null && lastMatch !== null) {
      setFromIdx(firstMatch); setToIdx(lastMatch);
      setZoom(firstMatch !== lastMatch ? { lo: commits[firstMatch].unix, hi: commits[lastMatch].unix } : null);
    } else if (!filter) {
      setZoom(null); setFromIdx(0); setToIdx(n - 1);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filter, firstMatch, lastMatch, n, embedded]);

  const delta = useMemo(() => (n > 0 ? computeNetDelta(commits, fromIdx, toIdx, matchFilter) : new Map<string, Status>()), [commits, fromIdx, toIdx, n, matchFilter]);

  // File-list search (filename / metadata / contents). Contents runs a backend
  // grep (debounced) against the file contents at the To commit.
  const [fileSearch, setFileSearch] = useState('');
  const [searchMode, setSearchMode] = useState<'name' | 'meta' | 'content'>('name');
  const [contentMatches, setContentMatches] = useState<Set<string> | null>(null);
  const [searchGrepping, setSearchGrepping] = useState(false);

  // Contents search (debounced): grep the changed files' content at the To commit.
  useEffect(() => {
    const q = fileSearch.trim();
    if (searchMode !== 'content' || !q || n === 0) { setContentMatches(null); setSearchGrepping(false); return; }
    let cancelled = false;
    setSearchGrepping(true);
    const timer = setTimeout(() => {
      window.uai.gitFileView.grep(dir, q, commits[toIdx].hash)
        .then((r: any) => { if (!cancelled) setContentMatches(new Set<string>(r?.ok ? (r.matches ?? []) : [])); })
        .catch(() => { if (!cancelled) setContentMatches(new Set<string>()); })
        .finally(() => { if (!cancelled) setSearchGrepping(false); });
    }, 300);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [searchMode, fileSearch, dir, commits, toIdx, n]);

  // tracking_id -> display name, so the AI-session contributors resolve to names
  // (also used by the metadata search below).
  const [sessNames, setSessNames] = useState<Record<string, string>>({});
  const [todoMap, setTodoMap] = useState<Record<string, { title: string; status: string }>>({});

  // Apply the file-list search to the delta (filename / metadata / contents).
  const searchedDelta = useMemo(() => {
    const q = fileSearch.trim().toLowerCase();
    if (!q) return delta;
    const out = new Map<string, Status>();
    if (searchMode === 'content') {
      if (!contentMatches) return delta;   // results pending → show all meanwhile
      for (const [p, s] of delta) if (contentMatches.has(p)) out.set(p, s);
      return out;
    }
    if (searchMode === 'name') {
      for (const [p, s] of delta) if (p.toLowerCase().includes(q)) out.set(p, s);
      return out;
    }
    // metadata: net status + the authors / AI-sessions / todos of the commits that touch each file
    const lo = Math.max(0, Math.min(fromIdx, toIdx)), hi = Math.min(n - 1, Math.max(fromIdx, toIdx));
    for (const [p, s] of delta) {
      const parts: string[] = [STATUS_LABEL[s]];
      for (let i = lo; i <= hi; i++) {
        if (!commits[i].files.some((f) => f.path === p)) continue;
        parts.push(commits[i].author);
        (commits[i].requesters ?? []).forEach((r) => parts.push(sessNames[r] || r));
        (commits[i].todos ?? []).forEach((t) => parts.push(t));
      }
      if (parts.join(' ').toLowerCase().includes(q)) out.set(p, s);
    }
    return out;
  }, [delta, fileSearch, searchMode, contentMatches, commits, fromIdx, toIdx, n, sessNames]);

  const tree = useMemo(() => buildTree(searchedDelta, data?.dir_rel ?? ''), [searchedDelta, data]);

  // Nearest commit index to a client X on the track.
  const idxFromClientX = useCallback((clientX: number): number => {
    const el = trackRef.current;
    if (!el || n === 0) return 0;
    const r = el.getBoundingClientRect();
    const frac = Math.max(0, Math.min(1, (clientX - r.left) / r.width));
    const target = t0 + frac * span;
    let best = 0, bestD = Infinity;
    for (let i = 0; i < n; i++) {
      const d = Math.abs(commits[i].unix - target);
      if (d < bestD) { bestD = d; best = i; }
    }
    return best;
  }, [commits, n, t0, span]);

  // Refs so the drag closure reads the latest from/to without re-binding.
  const fromIdxRef = useRef(fromIdx); fromIdxRef.current = fromIdx;
  const toIdxRef = useRef(toIdx); toIdxRef.current = toIdx;

  const onHandleDown = useCallback((which: 'from' | 'to') => (e: React.PointerEvent) => {
    e.preventDefault();
    dragRef.current = which;
    const move = (ev: PointerEvent) => {
      if (!dragRef.current) return;
      const idx = idxFromClientX(ev.clientX);
      if (dragRef.current === 'from') setFromIdx(Math.min(idx, toIdxRef.current));
      else setToIdx(Math.max(idx, fromIdxRef.current));
    };
    const up = () => { dragRef.current = null; window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); };
    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  }, [idxFromClientX]);

  // Click a commit tick → move the nearer handle to it.
  const onTrackClick = useCallback((e: React.MouseEvent) => {
    if (dragRef.current || n === 0) return;
    const idx = idxFromClientX(e.clientX);
    const dFrom = Math.abs(idx - fromIdx), dTo = Math.abs(idx - toIdx);
    if (dFrom <= dTo) setFromIdx(Math.min(idx, toIdx)); else setToIdx(Math.max(idx, fromIdx));
  }, [idxFromClientX, n, fromIdx, toIdx]);

  // Axis tick marks: ~6 evenly-time-spaced, labeled graduations across the span. (#2)
  const axisTicks = useMemo(() => {
    if (n === 0) return [] as { pct: number; label: string }[];
    const N = 6;
    return Array.from({ length: N + 1 }, (_, i) => ({ pct: (i / N) * 100, label: fmtAxis(t0 + (span * i) / N, span) }));
  }, [t0, span, n]);

  // Zoom into the selected [From..To] time window so clustered commits spread out. (#7)
  const zoomToSelection = useCallback(() => {
    if (fromIdx === toIdx) { showToast('Spread the handles apart first, then zoom', 'info'); return; }
    setZoom({ lo: commits[fromIdx].unix, hi: commits[toIdx].unix });
  }, [commits, fromIdx, toIdx, showToast]);
  const zoomOut = useCallback(() => setZoom(null), []);
  // Reset Zoom (#2): drop the zoom AND fling both handles to the full extent.

  // #2 play-through step: advance the selection by one commit. dir=+1 forward
  // (newer), -1 backward (older).
  //  • no lock  → shift the whole [from..to] window as a unit (same span).
  //  • locked   → move the OTHER extent; if it would cross the locked commit
  //    (span goes negative), flip the lock side so the locked commit stays put
  //    and the window reopens on the other side (passes cleanly through span-0).
  const step = useCallback((dir: 1 | -1) => {
    if (n === 0) return;
    const clamp = (x: number) => Math.max(0, Math.min(n - 1, x));
    if (lockSide === null) {
      const nf = fromIdx + dir, nt = toIdx + dir;
      if (nf >= 0 && nt <= n - 1) { setFromIdx(nf); setToIdx(nt); }
      return;
    }
    if (lockSide === 'left') {            // from locked, to moves
      const nt = clamp(toIdx + dir);
      if (nt >= fromIdx) { setToIdx(nt); }
      else { setLockSide('right'); setToIdx(fromIdx); setFromIdx(nt); }  // swap
    } else {                              // to locked, from moves
      const nf = clamp(fromIdx + dir);
      if (nf <= toIdx) { setFromIdx(nf); }
      else { setLockSide('left'); setFromIdx(toIdx); setToIdx(nf); }     // swap
    }
  }, [n, lockSide, fromIdx, toIdx]);
  const toggleLock = useCallback((side: 'left' | 'right') => {
    setLockSide((cur) => (cur === side ? null : side));
  }, []);

  const resetView = useCallback(() => { setZoom(null); setFromIdx(0); setToIdx(Math.max(0, n - 1)); }, [n]);
  // Fit to the filtered extent — the "initial zoom": handles at the earliest/latest
  // matching commit, axis zoomed to that duration. This is where a filtered view
  // opens and where "Reset zoom" returns to when a filter is active.
  const fitExtent = useCallback(() => {
    if (firstMatch === null || lastMatch === null) return;
    setFromIdx(firstMatch); setToIdx(lastMatch);
    setZoom(firstMatch !== lastMatch ? { lo: commits[firstMatch].unix, hi: commits[lastMatch].unix } : null);
  }, [firstMatch, lastMatch, commits]);
  // Full range — the higher level: widen the axis back out to the whole loaded data
  // range (dir + date range). Keeps the filtered selection; just un-zooms the axis.
  const fullRange = useCallback(() => { setZoom(null); }, []);

  // Expanded commit bodies (#4).
  const [expandedCommits, setExpandedCommits] = useState<Set<string>>(new Set(restored?.expandedCommits ?? []));
  const toggleCommit = useCallback((h: string) => {
    setExpandedCommits((prev) => { const s = new Set(prev); s.has(h) ? s.delete(h) : s.add(h); return s; });
  }, []);
  // Distinct filter values across the loaded range.
  const filterOpts = useMemo(() => {
    const authors = new Set<string>(), ais = new Set<string>(), todos = new Set<string>();
    for (const c of commits) {
      authors.add(c.author);
      (c.requesters ?? []).forEach((r) => ais.add(r));
      (c.todos ?? []).forEach((t) => todos.add(t));
    }
    return { authors: [...authors].sort(), ais: [...ais].sort(), todos: [...todos].sort() };
  }, [commits]);

  // ── Selected file → diff (#3) + details (#4) ────────────────────────────────
  const [selPath, setSelPath] = useState<string | null>(restored?.selPath ?? null);       // repo-relative
  const [diffRes, setDiffRes] = useState<{ diff: string; sizeAtTo: number | null } | null>(null);
  const [diffLoading, setDiffLoading] = useState(false);
  // View toggle (#1): the unified diff, or the whole file BEFORE / AFTER the span.
  const [diffView, setDiffView] = useState<'diff' | 'before' | 'after'>(restored?.diffView ?? 'diff');
  // File-view (diff) panel sizing: explicit px height (null = default 40%), a
  // maximized flag (fills the Git File View), and the last non-max height so
  // "restore previous" can return to it.
  const [diffH, setDiffH] = useState<number | null>(restored?.diffHeight ?? null);
  const [diffMax, setDiffMax] = useState<boolean>(restored?.diffMax ?? false);
  const diffPrevH = useRef<number | null>(restored?.diffHeight ?? null);
  const [contentRes, setContentRes] = useState<{ content: string; exists: boolean; view: 'before' | 'after' } | null>(null);
  const [contentLoading, setContentLoading] = useState(false);
  useEffect(() => {
    let cancelled = false;
    window.uai.sessions.list().then((list) => {
      if (cancelled) return;
      const m: Record<string, string> = {};
      for (const s of (list as any[]) ?? []) if (s?.tracking_id) m[s.tracking_id] = s.display_name || s.tracking_id;
      setSessNames(m);
    }).catch(() => {});
    window.uai.todos.list(true).then((list) => {
      if (cancelled) return;
      const m: Record<string, { title: string; status: string }> = {};
      for (const t of (list as any[]) ?? []) if (t?.id) m[t.id] = { title: t.title || t.summary || t.id, status: t.status || '' };
      setTodoMap(m);
    }).catch(() => {});
    return () => { cancelled = true; };
  }, []);
  const openTodo = useCallback((id: string) => { window.uai.todos.open(id).catch(() => {}); }, []);

  // Fetch the file's unified diff across the current [from..to] span. DEBOUNCED so
  // dragging the slider doesn't fire a fetch per tick (that was the jerk/flicker);
  // the prior diff stays on screen until the new one lands (no blanking).
  useEffect(() => {
    if (!selPath || n === 0) { setDiffRes(null); return; }
    let cancelled = false;
    setDiffLoading(true);
    const timer = setTimeout(() => {
      window.uai.gitFileView.diff(dir, selPath, commits[fromIdx].hash, commits[toIdx].hash)
        .then((r: any) => { if (!cancelled) setDiffRes(r?.ok ? { diff: r.diff ?? '', sizeAtTo: r.size_at_to ?? null } : { diff: '', sizeAtTo: null }); })
        .catch(() => { if (!cancelled) setDiffRes({ diff: '', sizeAtTo: null }); })
        .finally(() => { if (!cancelled) setDiffLoading(false); });
    }, 200);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [selPath, fromIdx, toIdx, dir, commits, n]);

  // Before/After views (#1): fetch the whole file content at from^ (before the
  // span) or to (after). Debounced, same as the diff. `diff` view uses diffRes.
  useEffect(() => {
    if (!selPath || n === 0 || diffView === 'diff') { setContentRes(null); return; }
    let cancelled = false;
    const ref = diffView === 'before' ? `${commits[fromIdx].hash}~1` : commits[toIdx].hash;
    setContentLoading(true);
    const timer = setTimeout(() => {
      window.uai.gitFileView.content(dir, selPath, ref)
        .then((r: any) => { if (!cancelled) setContentRes(r?.ok ? { content: r.content ?? '', exists: !!r.exists, view: diffView } : { content: '', exists: false, view: diffView }); })
        .catch(() => { if (!cancelled) setContentRes({ content: '', exists: false, view: diffView }); })
        .finally(() => { if (!cancelled) setContentLoading(false); });
    }, 200);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [selPath, diffView, fromIdx, toIdx, dir, commits, n]);

  // File details derived from the already-loaded changelog (no backend needed).
  const fileDetail = useMemo(() => {
    if (!selPath || n === 0) return null;
    const lo = Math.max(0, Math.min(fromIdx, toIdx));
    const hi = Math.min(n - 1, Math.max(fromIdx, toIdx));
    const touching: { commit: GfvCommit; status: Status }[] = [];
    for (let i = lo; i <= hi; i++) {
      const f = commits[i].files.find((x) => x.path === selPath);
      if (f) touching.push({ commit: commits[i], status: f.status });
    }
    const aiIds = new Set<string>();
    const todos = new Set<string>();
    for (const { commit } of touching) {
      (commit.requesters ?? []).forEach((r) => aiIds.add(r));
      (commit.todos ?? []).forEach((t) => todos.add(t));
    }
    return {
      touching,
      contributors: Array.from(new Set(touching.map((t) => t.commit.author))),
      aiSessions: Array.from(aiIds),
      todos: Array.from(todos).sort(),
      firstTs: touching[0]?.commit.unix ?? 0,
      lastTs: touching[touching.length - 1]?.commit.unix ?? 0,
      net: delta.get(selPath),
    };
  }, [selPath, commits, fromIdx, toIdx, delta, n]);

  const toggleDir = useCallback((path: string) => {
    setCollapsed((prev) => { const s = new Set(prev); if (s.has(path)) s.delete(path); else s.add(path); return s; });
  }, []);

  // ── File-view (diff) panel: manual vertical resize + maximize/restore/default ──
  // Drag the handle above the panel: its height = pane bottom → cursor. Clamped to
  // leave room for the controls + tree above.
  const startDiffResize = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const pane = paneRef.current; if (!pane) return;
    const rect = pane.getBoundingClientRect();
    document.body.style.cursor = 'row-resize'; document.body.style.userSelect = 'none';
    const onMove = (ev: MouseEvent) => {
      const h = Math.max(120, Math.min(rect.bottom - ev.clientY, rect.height - 160));
      setDiffMax(false); setDiffH(h); diffPrevH.current = h;
    };
    const onUp = () => {
      document.body.style.cursor = ''; document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove); window.addEventListener('mouseup', onUp);
  }, []);
  const maximizeDiff = useCallback(() => { if (diffH != null) diffPrevH.current = diffH; setDiffMax(true); }, [diffH]);
  const restorePrevDiff = useCallback(() => { setDiffMax(false); setDiffH(diffPrevH.current); }, []);
  const defaultDiff = useCallback(() => { setDiffMax(false); setDiffH(null); diffPrevH.current = null; }, []);

  // Persist this tab's UI state on every change so it survives unmount (#6).
  useEffect(() => {
    if (embedded || !tabId) return;
    setGfvSnapshot(tabId, {
      dir, since, until, data, fromIdx, toIdx, lockSide, zoom, selPath, diffView, filter, barOpen,
      collapsed: [...collapsed], expandedCommits: [...expandedCommits], diffHeight: diffH, diffMax,
    });
  }, [embedded, tabId, dir, since, until, data, fromIdx, toIdx, lockSide, zoom, selPath, diffView, filter, barOpen, collapsed, expandedCommits, diffH, diffMax]);

  // ── Render ─────────────────────────────────────────────────────────────────
  const totals = tree.counts;
  const fromC = commits[fromIdx];
  const toC = commits[toIdx];

  // Viewport reporter — expose the Git Viewer's real sub-components so the
  // [Capture Content] tree recurses PAST "app: Git Viewer" instead of stopping
  // dead there (note_0033 #3). Seven panes, each with its live state. Only the
  // app-tab instance registers (skip when embedded to avoid a duplicate id).
  // Commit count for the current span — the number of MATCHING commits when a
  // filter is active (so the summary reflects the filtered set, not the raw span),
  // else the plain span width.
  const spanLo = Math.min(fromIdx, toIdx), spanHi = Math.max(fromIdx, toIdx);
  const spanCommitCount = (() => {
    if (n === 0) return 0;
    if (!filter) return spanHi - spanLo + 1;
    let c = 0; for (let i = spanLo; i <= spanHi; i++) if (matchFilter(commits[i])) c++; return c;
  })();
  const spanLabel = n === 0 ? '(no commits)'
    : `${spanCommitCount} commit${spanCommitCount === 1 ? '' : 's'}${filter ? ' (filtered)' : ''}`;
  useViewport(embedded ? `git_file_view_embed_${tabId ?? 'x'}` : 'git_file_view', () => (embedded ? { visible: false, label: 'Git File View (embedded)', children: [] } : {
    visible: true,
    label: 'Git Viewer',
    state: { dir, since, until: until || '(latest)', commitCount: n, loading, error, span: spanLabel },
    children: [
      { id: 'gfv_topbar', label: 'Top bar — directory + date range', visible: true,
        state: { dir, since, until: until || '(latest)' }, children: [] },
      { id: 'gfv_zoombar', label: 'Zoom / timeline bar', visible: true,
        state: { zoomed: !!zoom, zoomLo: zoom?.lo ?? null, zoomHi: zoom?.hi ?? null, fromIdx, toIdx, fromCommit: fromC?.short ?? null, toCommit: toC?.short ?? null }, children: [] },
      { id: 'gfv_statsbar', label: 'Stats — commits / added / modified / deleted', visible: true,
        state: { commits: spanLabel, added: totals.A, modified: totals.M, deleted: totals.D }, children: [] },
      { id: 'gfv_filterbar', label: 'Filter bar', visible: true,
        state: { active: !!filter, kind: filter?.kind ?? null, value: filter?.value ?? null }, children: [] },
      { id: 'gfv_tree', label: 'Directory / file tree (center)', visible: true,
        state: { changedFiles: delta.size, added: totals.A, modified: totals.M, deleted: totals.D, collapsedDirs: collapsed.size }, children: [] },
      { id: 'gfv_metadata', label: 'File metadata (right panel)', visible: !!selPath,
        state: selPath ? { file: selPath, net: fileDetail?.net ?? null, contributors: fileDetail?.contributors ?? [] } : { file: null }, children: [] },
      { id: 'gfv_contents', label: 'File contents / diff (bottom panel)', visible: !!selPath,
        state: { file: selPath, diffLoaded: !!diffRes, diffLoading, sizeAtTo: diffRes?.sizeAtTo ?? null }, children: [] },
    ],
  }));

  const renderNode = (node: TreeNode, depth: number): JSX.Element[] => {
    const rows: JSX.Element[] = [];
    for (const child of node.children) {
      const pad = 10 + depth * 16;
      if (child.isDir) {
        const isCol = collapsed.has(child.path);
        rows.push(
          <div key={`d:${child.path}`} className="gfv-row gfv-dir" style={{ paddingLeft: pad }} onClick={() => toggleDir(child.path)}>
            <span className="gfv-caret">{isCol ? '▶' : '▼'}</span>
            <span className="gfv-dirname">{child.name}/</span>
            <span className="gfv-counts">
              {child.counts.A > 0 && <span style={{ color: STATUS_COLOR.A }}>+{child.counts.A}</span>}
              {child.counts.M > 0 && <span style={{ color: STATUS_COLOR.M }}>~{child.counts.M}</span>}
              {child.counts.D > 0 && <span style={{ color: STATUS_COLOR.D }}>−{child.counts.D}</span>}
            </span>
          </div>,
        );
        if (!isCol) rows.push(...renderNode(child, depth + 1));
      } else {
        const st = child.status!;
        const isSel = selPath === child.fullPath;
        rows.push(
          <div key={`f:${child.path}`} className={`gfv-row gfv-file${isSel ? ' gfv-file-sel' : ''}`} style={{ paddingLeft: pad + 16 }}
            title={`${STATUS_LABEL[st]} — click for diff & details`} onClick={() => setSelPath(child.fullPath ?? null)}>
            <span className="gfv-badge" style={{ color: STATUS_COLOR[st], borderColor: STATUS_COLOR[st] }}>{st}</span>
            <span className="gfv-filename" style={{ color: STATUS_COLOR[st] }}>{child.name}</span>
          </div>,
        );
      }
    }
    return rows;
  };

  const maximized = diffMax && !!selPath;
  return (
    <div className={`gfv-pane${maximized ? ' gfv-maximized' : ''}`} ref={paneRef}>
      {/* Scope bar (#5): the editable Repo / Dir / Date Range controls. Hideable —
          collapses to the slim "⚙ Scope" chip below. Suppressed entirely when the
          host locks scope (allowScopeChange=false). */}
      {canChange && barOpen && (
        <div className="gfv-toolbar">
          {repos.length > 0 && (
            <select className="gfv-repo-select" value="" onChange={(e) => pickRepo(e.target.value)} title="Jump to a workspace git repo">
              <option value="">Repo…</option>
              {repos.map((r) => <option key={r.path} value={r.path}>{r.name} · {r.host}</option>)}
            </select>
          )}
          <button className="gfv-browse" onClick={browse} title="Pick a directory (git repo inferred from it)">📁 Browse</button>
          <input className="gfv-dir-input" value={dir} onChange={(e) => setDir(e.target.value)}
            placeholder="directory (recursively)…" spellCheck={false}
            onKeyDown={(e) => { if (e.key === 'Enter') loadCurrent(); }} />
          <label className="gfv-datelbl">since <input type="date" className="gfv-date" value={since} onChange={(e) => setSince(e.target.value)} /></label>
          <label className="gfv-datelbl">until <input type="date" className="gfv-date" value={until} onChange={(e) => setUntil(e.target.value)} /></label>
          <button className="gfv-load" onClick={loadCurrent} disabled={loading}>{loading ? 'Loading…' : 'Load'}</button>
          <button className="gfv-scope-hide" onClick={() => setBarOpen(false)} title="Hide the scope bar">✕</button>
        </div>
      )}
      {/* Slim scope chip: current scope at a glance + the advertised "⚙ Scope"
          command entry (reopens the bar). Shown when scope is changeable but the
          bar is collapsed. */}
      {canChange && !barOpen && (
        <div className="gfv-scopechip">
          <span className="gfv-scopechip-info" title={`${dir}\n${since || 'earliest'} → ${until || 'latest'}`}>
            <span className="gfv-scopechip-repo">{((data?.repo_root || dir) || '').split('/').pop() || '(repo)'}</span>
            <span className="gfv-scopechip-dir">{data?.dir_rel || dir || '(root)'}</span>
            <span className="gfv-scopechip-range">{since || 'earliest'} → {until || 'latest'}</span>
            {filter && (
              <span className="gfv-scopechip-filter" title={`filtered by ${filter.kind}`}>
                ⧗ {filter.kind === 'todos'
                  ? `${filter.values?.length ?? 0} todos`
                  : `${filter.kind === 'ai' ? 'AI' : filter.kind}: ${filter.kind === 'ai' ? (sessNames[filter.value ?? ''] || (filter.value ?? '').slice(0, 12)) : (filter.value ?? '')}`}
              </span>
            )}
          </span>
          <button className="gfv-scope-set" onClick={() => setBarOpen(true)} title="Set Repo / Dir / Date Range + filter">⚙ Scope</button>
        </div>
      )}

      {error && <div className="gfv-error">⚠ {error}</div>}

      {data?.ok && n === 0 && !loading && (
        <div className="gfv-empty">No commits touched <code>{data.dir_rel || '(repo root)'}</code> in this range.</div>
      )}

      {n > 0 && (
        <>
          <div className="gfv-slider">
            <div className="gfv-slider-top">
              <button className="gfv-zoom-btn" onClick={zoomToSelection} disabled={fromIdx === toIdx} title="Zoom the timeline into the selected range">⤢ Zoom to selection</button>
              <button className="gfv-zoom-btn" onClick={filter ? fitExtent : resetView} title={filter ? 'Reset to the filtered extent (earliest→latest matching commit)' : 'Reset zoom + fling both handles to the full range'}>↺ Reset zoom</button>
              {filter && <button className="gfv-zoom-btn" onClick={fullRange} title="Zoom out to the full data range (dir + date range)">⊞ Full range</button>}
              <span className="gfv-play-sep" />
              <button className="gfv-step-btn" onClick={() => step(-1)} title="Step one commit backward (older)">◀ Prev</button>
              <button className="gfv-step-btn" onClick={() => step(1)} title="Step one commit forward (newer)">Next ▶</button>
              <button className={`gfv-lock-btn${lockSide === 'left' ? ' active' : ''}`} onClick={() => toggleLock('left')} title="Lock the From (left) extent while stepping">{lockSide === 'left' ? '🔒' : '🔓'} From</button>
              <button className={`gfv-lock-btn${lockSide === 'right' ? ' active' : ''}`} onClick={() => toggleLock('right')} title="Lock the To (right) extent while stepping">{lockSide === 'right' ? '🔒' : '🔓'} To</button>
              {zoom && (
                <span className="gfv-zoom-badge">
                  🔍 Zoomed: {fmtAxis(zoom.lo, span)} → {fmtAxis(zoom.hi, span)}
                  <button className="gfv-zoom-out" onClick={zoomOut} title="Zoom back out to the full range">✕ Zoom out</button>
                </span>
              )}
            </div>
            {/* axis tick-mark labels (#2) */}
            <div className="gfv-axis">
              {axisTicks.map((t, i) => (
                <span key={i} className="gfv-axis-tick" style={{ left: `${t.pct}%` }}>{t.label}</span>
              ))}
            </div>
            <div className="gfv-track" ref={trackRef} onClick={onTrackClick}>
              {/* axis gridlines */}
              {axisTicks.map((t, i) => (
                <span key={`g${i}`} className="gfv-gridline" style={{ left: `${t.pct}%` }} />
              ))}
              {/* commit ticks — only those in the zoomed view, and when a filter is
                  active ONLY the matching commits (the timeline shows just the todo's
                  commits, etc.). */}
              {commits.map((c, i) => ((inView(c.unix) && (!filter || matchFilter(c))) ? (
                <span key={c.hash} className="gfv-tick" style={{ left: `${xOf(c.unix)}%` }} title={`${c.short} ${fmtTs(c.unix)} — ${c.subject}`} data-i={i} />
              ) : null))}
              {/* selected band */}
              <span className="gfv-band" style={{ left: `${Math.max(0, Math.min(100, xOf(commits[fromIdx].unix)))}%`, width: `${Math.max(0, Math.min(100, xOf(commits[toIdx].unix)) - Math.max(0, Math.min(100, xOf(commits[fromIdx].unix))))}%` }} />
              {/* handles */}
              <span className="gfv-handle gfv-handle-from" style={{ left: `${Math.max(0, Math.min(100, xOf(commits[fromIdx].unix)))}%` }} onPointerDown={onHandleDown('from')} title="From (baseline)" />
              <span className="gfv-handle gfv-handle-to" style={{ left: `${Math.max(0, Math.min(100, xOf(commits[toIdx].unix)))}%` }} onPointerDown={onHandleDown('to')} title="To (target)" />
            </div>
            <div className="gfv-slider-labels">
              <span className="gfv-endpoint">
                <strong>From</strong> {fromC?.short} · {fmtTs(fromC?.unix ?? 0)}
                <span className="gfv-subj"> {fromC?.subject}</span>
              </span>
              <span className="gfv-endpoint gfv-endpoint-to">
                <strong>To</strong> {toC?.short} · {fmtTs(toC?.unix ?? 0)}
                <span className="gfv-subj"> {toC?.subject}</span>
              </span>
            </div>
          </div>

          <div className="gfv-summary">
            <span className="gfv-summary-repo">{(data?.repo_root || '').split('/').pop()} · {data?.dir_rel || '(root)'}</span>
            <span className="gfv-summary-span">{spanLabel}</span>
            <span style={{ color: STATUS_COLOR.A }}>+{totals.A} added</span>
            <span style={{ color: STATUS_COLOR.M }}>~{totals.M} modified</span>
            <span style={{ color: STATUS_COLOR.D }}>−{totals.D} deleted</span>
          </div>

          {/* filter bar (#8): restrict the delta to one contributor / AI session / todo.
              Hideable (#5): folds away with the scope bar into the ⚙ Scope chip, and is
              suppressed for fixed embeds (canChange=false). */}
          {canChange && barOpen && (
          <div className="gfv-filterbar">
            <span className="gfv-filter-lbl">Filter</span>
            <select className="gfv-filter-sel" value={filter?.kind === 'author' ? (filter.value ?? '') : ''}
              onChange={(e) => setFilter(e.target.value ? { kind: 'author', value: e.target.value } : null)}>
              <option value="">Contributor…</option>
              {filterOpts.authors.map((a) => <option key={a} value={a}>{a}</option>)}
            </select>
            <select className="gfv-filter-sel" value={filter?.kind === 'ai' ? (filter.value ?? '') : ''}
              onChange={(e) => setFilter(e.target.value ? { kind: 'ai', value: e.target.value } : null)}>
              <option value="">AI session…</option>
              {filterOpts.ais.map((a) => <option key={a} value={a}>{sessNames[a] || a.slice(0, 15)}</option>)}
            </select>
            <select className="gfv-filter-sel" value={filter?.kind === 'todo' ? (filter.value ?? '') : ''}
              onChange={(e) => setFilter(e.target.value ? { kind: 'todo', value: e.target.value } : null)}>
              <option value="">Todo…</option>
              {filterOpts.todos.map((t) => <option key={t} value={t}>{t}</option>)}
            </select>
            {filter && <button className="gfv-filter-clear" onClick={() => setFilter(null)}>✕ clear</button>}
          </div>
          )}

          {/* main row: delta tree (left) + selected-file details (right, #4) */}
          <div className="gfv-main" style={diffMax && selPath ? { display: 'none' } : undefined}>
            <div className="gfv-listcol">
              {/* file-list search: by filename / metadata / contents (contents greps
                  the file content at the To commit via the backend). */}
              <div className="gfv-filesearch">
                <span className="gfv-filesearch-ic">🔍</span>
                <input className="gfv-filesearch-input" value={fileSearch} onChange={(e) => setFileSearch(e.target.value)}
                  placeholder={searchMode === 'content' ? 'Search file contents…' : searchMode === 'meta' ? 'Search author / AI / todo / status…' : 'Search filenames…'}
                  spellCheck={false} />
                <select className="gfv-filesearch-mode" value={searchMode} onChange={(e) => setSearchMode(e.target.value as 'name' | 'meta' | 'content')} title="What to search">
                  <option value="name">Filename</option>
                  <option value="meta">Metadata</option>
                  <option value="content">Contents</option>
                </select>
                {searchMode === 'content' && searchGrepping && <span className="gfv-filesearch-busy">…</span>}
                {fileSearch && <button className="gfv-filesearch-clear" onClick={() => setFileSearch('')} title="Clear search">✕</button>}
              </div>
              <div className="gfv-tree">
                {totals.A + totals.M + totals.D === 0
                  ? <div className="gfv-empty">{fileSearch.trim() ? 'No files match this search.' : 'No net changes between these commits.'}</div>
                  : renderNode(tree, 0)}
              </div>
            </div>
            {selPath && fileDetail && (
              <div className="gfv-detail">
                <div className="gfv-detail-head">
                  <span className="gfv-detail-name">{selPath.split('/').pop()}</span>
                  <button className="gfv-detail-close" onClick={() => setSelPath(null)} title="Close details">✕</button>
                </div>
                <div className="gfv-detail-path" title={selPath}>{selPath}</div>
                <dl className="gfv-detail-list">
                  <dt>Net change</dt><dd>{fileDetail.net ? <span style={{ color: STATUS_COLOR[fileDetail.net] }}>{STATUS_LABEL[fileDetail.net]}</span> : '—'}</dd>
                  <dt>Size (at To)</dt><dd>{fmtBytes(diffRes?.sizeAtTo)}</dd>
                  <dt>Commits in range</dt><dd>{fileDetail.touching.length}</dd>
                  <dt>First change</dt><dd>{fileDetail.firstTs ? fmtTs(fileDetail.firstTs) : '—'}</dd>
                  <dt>Last change</dt><dd>{fileDetail.lastTs ? fmtTs(fileDetail.lastTs) : '—'}</dd>
                  <dt title="git author (all commits here are pushed by the human)">Git author</dt><dd>{fileDetail.contributors.join(', ') || '—'}</dd>
                  <dt title="AI sessions that requested the work (Requester: trailer)">AI sessions</dt>
                  <dd>{fileDetail.aiSessions.length
                    ? <span className="gfv-ai-sessions">{fileDetail.aiSessions.map((id) => (
                        <span key={id} className="gfv-ai-chip" title={id}>{sessNames[id] || id.slice(0, 15)}</span>
                      ))}</span>
                    : <span style={{ color: 'var(--text-muted)' }}>none recorded</span>}</dd>
                  <dt title="Todos referenced in the commit messages (Todo: trailer)">Todos</dt>
                  <dd>{fileDetail.todos.length
                    ? <span className="gfv-todo-chips">{fileDetail.todos.map((t) => (
                        <button key={t} className="gfv-todo-chip gfv-todo-chip-btn" onClick={() => openTodo(t)}
                          title={todoMap[t] ? `${t} — ${todoMap[t].title}${todoMap[t].status ? `  [${todoMap[t].status}]` : ''}\n(click to open)` : `${t} (click to open)`}>{t}</button>
                      ))}</span>
                    : <span style={{ color: 'var(--text-muted)' }}>none</span>}</dd>
                </dl>
                <div className="gfv-detail-commits-title">Changes in range</div>
                <div className="gfv-detail-commits">
                  {fileDetail.touching.slice().reverse().map(({ commit, status }) => {
                    const exp = expandedCommits.has(commit.hash);
                    return (
                      <div key={commit.hash} className="gfv-dc-wrap">
                        <div className="gfv-detail-commit" title="Click to expand the commit message" onClick={() => toggleCommit(commit.hash)}>
                          <span className="gfv-dc-caret">{exp ? '▼' : '▶'}</span>
                          <span className="gfv-badge" style={{ color: STATUS_COLOR[status], borderColor: STATUS_COLOR[status] }}>{status}</span>
                          <button className="gfv-dc-hash gfv-dc-hash-btn" title="Open in Git Commit View"
                            onClick={(e) => { e.stopPropagation(); onOpenCommit?.(commit.hash, dir); }}>{commit.short}</button>
                          <span className="gfv-dc-date">{fmtTs(commit.unix)}</span>
                          <span className="gfv-dc-subj">{commit.subject}</span>
                        </div>
                        {exp && <pre className="gfv-dc-body">{commit.body || commit.subject}</pre>}
                      </div>
                    );
                  })}
                </div>
              </div>
            )}
          </div>

          {/* drag handle to resize the file-view panel (hidden when maximized) */}
          {selPath && !diffMax && <div className="gfv-vresize" onMouseDown={startDiffResize} title="Drag to resize the file view" />}

          {/* bottom: unified diff of the selected file across [From..To] (#3) */}
          {selPath && (
            <div className="gfv-diff" style={diffMax ? { flex: '1 1 auto', height: 'auto' } : (diffH != null ? { flex: 'none', height: diffH } : undefined)}>
              <div className="gfv-diff-head">
                {/* #1: view toggle sits all the way left; filename follows. */}
                <div className="gfv-diff-views">
                  {(['diff', 'before', 'after'] as const).map((v) => (
                    <button key={v} className={`gfv-diff-viewbtn${diffView === v ? ' active' : ''}`} onClick={() => setDiffView(v)}>{v}</button>
                  ))}
                </div>
                <span className="gfv-diff-file">{selPath.split('/').pop()}</span>
                <span className="gfv-diff-span">{diffView === 'diff' ? `diff · ${fromC?.short} → ${toC?.short}` : diffView === 'before' ? `before · ${fromC?.short}^` : `after · ${toC?.short}`}</span>
                {(diffLoading || contentLoading) && <span className="gfv-diff-loading">loading…</span>}
                {/* file-view size controls: maximize within the pane / restore previous / default */}
                <div className="gfv-diff-size">
                  <button className={`gfv-diff-sizebtn${diffMax ? ' active' : ''}`} onClick={maximizeDiff} disabled={diffMax} title="Maximize the file view to fill the Git File View">⤢ Maximize</button>
                  <button className="gfv-diff-sizebtn" onClick={restorePrevDiff} title="Restore the previous size">⤡ Restore</button>
                  <button className="gfv-diff-sizebtn" onClick={defaultDiff} title="Reset to the default size">⭯ Default</button>
                </div>
              </div>
              <div className="gfv-diff-body">
                {diffView === 'diff' ? (
                  diffLoading && !diffRes ? <div className="gfv-empty">Loading diff…</div>
                    : !diffRes || !diffRes.diff.trim() ? (
                      <div className="gfv-empty">No net content change across this range.{(fileDetail?.touching.length ?? 0) > 1 && ' The file was touched by commits here but ends up identical (changed then reverted). Narrow the range to see an individual change.'}</div>
                    ) : diffRes.diff.split('\n').map((ln, i) => {
                      const cls = ln.startsWith('@@') ? 'gfv-dl-hunk'
                        : ln.startsWith('+++') || ln.startsWith('---') || ln.startsWith('diff ') || ln.startsWith('index ') ? 'gfv-dl-meta'
                        : ln.startsWith('+') ? 'gfv-dl-add'
                        : ln.startsWith('-') ? 'gfv-dl-del' : 'gfv-dl-ctx';
                      return <div key={i} className={`gfv-dl ${cls}`}>{ln || ' '}</div>;
                    })
                ) : (
                  contentLoading && !contentRes ? <div className="gfv-empty">Loading…</div>
                    : !contentRes || !contentRes.exists ? <div className="gfv-empty">File did not exist at this point ({diffView === 'before' ? 'before the range' : 'after the range'}).</div>
                    : contentRes.content.split('\n').map((ln, i) => (
                      <div key={i} className="gfv-cl"><span className="gfv-dl-num">{i + 1}</span><span className="gfv-cl-txt">{ln || ' '}</span></div>
                    ))
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
