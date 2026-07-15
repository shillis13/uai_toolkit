/**
 * ContextMgrPane — Context Mgr tool (todo_0331 Phase 1, read-only).
 *
 * Replaces the weak ContextManagerPane (a file browser over trait_mgr) with a
 * real management surface backed by the context_mgr.py SQLite engine. Mirrors
 * ScheduledTasksPane structurally: header + sub-tab bar + master/detail, useState,
 * load-on-change, Toast, no polling.
 *
 * Three top tabs:
 *  - Library  — Catalog (search/filter/grouped list) + Focus (Content/Links/
 *               Loads/Info) + a collapsible bottom Peek drawer.
 *  - Link Matrix — stubbed placeholder (built by the next task).
 *  - Validate — dangling refs + orphans grouped by severity.
 *
 * Backend: window.uai.context.run(verb, args?) -> { ok, data?, error? }.
 * All verbs are read-only here; Phase-2 write actions (the `*` buttons) have
 * clear, intentionally-absent/disabled homes marked `Phase 2` below.
 */

import { useState, useEffect, useCallback, useRef, useMemo, useLayoutEffect, type ReactNode, type CSSProperties } from 'react';
import { marked } from 'marked';
import DOMPurify from 'dompurify';
import { useToast } from './Toast';
import { TabNavArrows } from './TabNavArrows';
import { usePanelResize } from '../hooks/usePanelResize';
import { getAiRoot } from '../stores/session-store';
import { useViewport } from '../viewport';

// Markdown rendering for the Content tab (.md context files). Mirrors
// TranscriptViewer's safe pipeline: marked → DOMPurify (no raw HTML injection).
marked.setOptions({ breaks: true, gfm: true });
function safeMarkdown(md: string): string {
  try {
    const r = marked.parse(md);
    return DOMPurify.sanitize(typeof r === 'string' ? r : String(r));
  } catch {
    return DOMPurify.sanitize(md);
  }
}

// ── Generic YAML formatter (note_0035) ──────────────────────────────────────
// A lightweight, dependency-free YAML colorizer for the Content tab (.yml/.yaml
// context files, which previously showed as flat gray text). Builds plain React
// elements (no raw HTML) — keys, values (type-classed), list dashes, doc
// separators, and #comments each get an accent.

/** Class for a scalar value by its apparent YAML type. */
function yamlValClass(v: string): string {
  const t = v.trim();
  if (!t) return 'yml-val';
  if (/^(true|false|yes|no|on|off|null|~)$/i.test(t)) return 'yml-bool';
  if (/^-?\d+(\.\d+)?$/.test(t)) return 'yml-num';
  if (/^["'].*["']$/.test(t)) return 'yml-str';
  if (/^(uai:\/\/|https?:\/\/|\/|~\/)/.test(t)) return 'yml-str';
  return 'yml-val';
}

/** Index of an inline ` #` comment not inside quotes, or -1. */
function yamlInlineCommentIdx(s: string): number {
  let q: string | null = null;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (q) { if (ch === q) q = null; continue; }
    if (ch === '"' || ch === "'") { q = ch; continue; }
    if (ch === '#' && i > 0 && /\s/.test(s[i - 1])) return i;
  }
  return -1;
}

function YamlLine({ line }: { line: string }): JSX.Element {
  const trimmed = line.trimStart();
  const indent = line.slice(0, line.length - trimmed.length);
  if (trimmed.startsWith('#')) return <div className="yml-line"><span className="yml-comment">{line}</span></div>;
  if (/^(---|\.\.\.)\s*$/.test(trimmed)) return <div className="yml-line">{indent}<span className="yml-sep">{trimmed}</span></div>;

  const ci = yamlInlineCommentIdx(line);
  const content = ci >= 0 ? line.slice(0, ci) : line;
  const comment = ci >= 0 ? line.slice(ci) : '';
  const commentSpan = comment ? <span className="yml-comment">{comment}</span> : null;

  const kv = content.match(/^(\s*)(- )?([^:]+?):(\s*)(.*)$/);
  if (kv) {
    const [, ind, dash, key, sp, val] = kv;
    return (
      <div className="yml-line">{ind}
        {dash ? <span className="yml-dash">{dash}</span> : null}
        <span className="yml-key">{key}</span><span className="yml-colon">:</span>{sp}
        {val ? <span className={yamlValClass(val)}>{val}</span> : null}{commentSpan}
      </div>
    );
  }
  const li = content.match(/^(\s*)(- )(.*)$/);
  if (li) {
    const [, ind, dash, val] = li;
    return <div className="yml-line">{ind}<span className="yml-dash">{dash}</span><span className={yamlValClass(val)}>{val}</span>{commentSpan}</div>;
  }
  return <div className="yml-line">{content}{commentSpan}</div>;
}

function YamlView({ text }: { text: string }): JSX.Element {
  const lines = (text ?? '').split('\n');
  return <pre className="context-mgr-yaml">{lines.map((line, i) => <YamlLine key={i} line={line} />)}</pre>;
}

/** Absolute on-disk path for an AI_ROOT-relative path (for open/copy). */
function absPathOf(relPath?: string | null): string | null {
  if (!relPath) return null;
  const root = getAiRoot();
  if (!root) return relPath;
  return relPath.startsWith('/') ? relPath : `${root.replace(/\/$/, '')}/${relPath}`;
}

// ---- Terms (see design doc 2026-06-25-context-mgr-tool-design.md) -----------
//  - Links: direct reference edges (one hop), both directions — the editable thing.
//  - Loads: transitive, flattened, de-duplicated, ordered leaf set a bundle includes.
//  - Peek:  a non-disruptive preview of any item without changing the main Focus.

// ---- Types -----------------------------------------------------------------

interface CtxItem {
  id: string;
  kind: string;
  name: string;
  title?: string | null;
  summary?: string | null;
  status?: string | null;
  scope?: string | null;
  loader?: string | null;
  path?: string | null;
  size_bytes?: number | null;
  updated_at?: string | null;
}

interface CtxMeta extends CtxItem {
  created_at?: string | null;
  content_hash?: string | null;
  // The engine returns provenance uniformly as a parsed object (or null) under
  // `provenance` — never a raw JSON string. InfoView pretty-prints it for display.
  provenance?: Record<string, unknown> | null;
  counts?: { outbound: number; inbound: number };
}

interface RefEdge {
  src_id: string;
  dst_id: string;
  edge_type: string;
  order_idx: number;
  resolved: boolean;
}

interface ResolveLeaf {
  id: string;
  kind: string;
  name: string;
  path?: string | null;
  via?: string[][];
  count?: number;
}

interface ResolveResult {
  id: string;
  resolved: ResolveLeaf[];
  unresolved: string[];
  total_size_bytes: number;
}

interface ValidateResult {
  dangling: Array<{ src_id: string; dst_id: string }>;
  orphans: Array<{ id: string; kind: string; severity: string }>;
}

interface ContentResult {
  id: string;
  kind: string;
  path: string;
  content: string;
}

/** Lightweight item row from the `graph` verb (Link Matrix tab). */
interface GraphItem {
  id: string;
  kind: string;
  name: string;
  title?: string | null;
  loader?: string | null;
  scope?: string | null;
  status?: string | null;
}

interface GraphEdge {
  src_id: string;
  dst_id: string;
  edge_type: string;
}

/** The whole reference graph, fetched once for client-side exploration. */
interface GraphResult {
  items: GraphItem[];
  edges: GraphEdge[];
}

type TopTab = 'library' | 'matrix' | 'validate';
// Two focus sub-tabs: Info (metadata + the file Content) and Links (direct
// links + the transitive Loads leaf set). 'content'/'loads' are legacy values
// still possibly in persisted state — normalizeFocusTab folds them in.
type FocusTab = 'info' | 'links';
function normalizeFocusTab(v: unknown): FocusTab {
  if (v === 'links' || v === 'loads') return 'links';
  return 'info'; // 'info' | 'content' | anything else → info
}
type StatusFilter = 'active' | 'all';
type LoaderFilter = 'mcp' | 'command' | null;

// ---- Constants -------------------------------------------------------------

/** The 8 kinds. */
const KINDS = ['knowledge', 'instruction', 'brief', 'memory', 'role', 'profile', 'skill', 'global'] as const;
// Canonical display order — SAME for the catalog list groups and the Kind
// dropdown (bundles first, then leaf context files). Change here to change both.
const KIND_DISPLAY_ORDER = ['global', 'profile', 'skill', 'role', 'knowledge', 'instruction', 'memory', 'brief'] as const;
const KIND_ORDER: Record<string, number> = KIND_DISPLAY_ORDER.reduce((acc, k, i) => { acc[k] = i; return acc; }, {} as Record<string, number>);
const BUNDLE_KINDS = new Set(['role', 'profile', 'skill', 'global']);

function isBundle(kind?: string | null): boolean {
  return !!kind && BUNDLE_KINDS.has(kind);
}

// ---- Link Matrix column taxonomy -------------------------------------------
//  Profiles col = profile + global; Roles/Sub-roles cols = role + skill bundles
//  (a bundle is "tier-1/Roles" when a profile|global references it, "tier-2/
//  Sub-roles" when another role|skill references it; it can be in both).
//  Context Files col = the four leaf kinds.
const PROFILE_KINDS = new Set(['profile', 'global']);
const ROLE_KINDS = new Set(['role', 'skill']);
const CONTEXT_FILE_KINDS = new Set(['knowledge', 'instruction', 'brief', 'memory']);

// Link Matrix arrow + boundary colors: outbound (what an item includes) vs
// inbound (what includes it). Direct-link selection model in LinkMatrixView.
const OUT_COLOR = 'var(--accent-cyan)';   // outbound — "includes →"
const IN_COLOR = 'var(--accent-orange)';  // inbound  — "included by"
const ORPHAN_COLOR = 'var(--accent-red)';     // no parent (no inbound)
const CHILDLESS_COLOR = 'var(--accent-yellow)'; // no children (no outbound)

// ── Kind / Sub-kind label colors ────────────────────────────────────────────
// Every kind gets a distinct, consistent base hue; sub-kinds (the first path
// segment under knowledge/ and instruction/ — e.g. reference, architecture,
// perspectives, rules, how_tos) get a deterministic same-family variation so
// they read as related-but-distinct. Used for label text in both the Library
// list and the Link Matrix (the only extra coloring the matrix needs).
const KIND_HUE: Record<string, number> = {
  global: 265, profile: 212, role: 190, skill: 158,
  knowledge: 45, instruction: 22, memory: 330, brief: 350,
};
function _strHash(s: string): number {
  let h = 0;
  for (let i = 0; i < s.length; i++) h = (Math.imul(h, 31) + s.charCodeAt(i)) >>> 0;
  return h;
}
/** HSL label color for a (kind, name). Sub-kind = first path segment of name
 *  for knowledge/instruction; shifts hue ±20° and nudges lightness within the
 *  kind's family so sibling categories stay distinguishable but coherent. */
function kindLabelColor(kind: string, name?: string | null): string {
  const base = KIND_HUE[kind] ?? (_strHash(kind) % 360);
  let hue = base;
  let light = 68;
  const sat = 72;
  if (name && name.includes('/') && (kind === 'knowledge' || kind === 'instruction')) {
    const sub = name.split('/')[0];
    const h = _strHash(sub);
    hue = (base + ((h % 41) - 20) + 360) % 360; // ±20°
    light = 60 + (h % 4) * 5;                   // 60–75%
  }
  return `hsl(${hue} ${sat}% ${light}%)`;
}
/** The sub-kind (category) of an item, or null — first path segment of its
 *  name for the two kinds that have categories. */
function subKindOf(kind: string, name?: string | null): string | null {
  if (name && name.includes('/') && (kind === 'knowledge' || kind === 'instruction')) {
    return name.split('/')[0];
  }
  return null;
}

/** Map a context item (kind, name) to the session_traits (type, name) pair used
 *  by `traits.load` / `traits.list`. The trait taxonomy differs from context
 *  kinds: knowledge + instruction leaves are both `traits` (their name already
 *  includes the category, e.g. `perspectives/x` / `reference/x` — matches the
 *  context item's name verbatim); bundles map to their own types. Returns null
 *  for kinds the traits system does not load individually. */
function kindToTrait(kind: string, name: string): { type: string; name: string } | null {
  switch (kind) {
    case 'knowledge':
    case 'instruction': return { type: 'traits', name };
    case 'role': return { type: 'roles', name };
    case 'skill': return { type: 'roles', name: `skill:${name}` };
    case 'profile': return { type: 'profiles', name };
    case 'global': return { type: 'globals', name };
    case 'brief': return { type: 'briefs', name };
    case 'memory': return { type: 'mslots', name };
    default: return null;
  }
}

// Kind filter as a compact dropdown (bundles first, then leaves) — a single
// control instead of a long pill row.
const KIND_MENU = KIND_DISPLAY_ORDER;
const KIND_LABEL: Record<string, string> = {
  global: 'Global', profile: 'Profiles', skill: 'Skills', role: 'Roles',
  knowledge: 'Knowledge', instruction: 'Instructions', memory: 'Memories', brief: 'Briefs',
};

/** Multi-select Kind filter with Excel-style "All" behavior:
 *  - check All → all checked; uncheck All → all unchecked
 *  - all individual checked → All checked; any unchecked → All unchecked
 *  - toggling one affects only that (the All state derives from the set).
 */
function KindMultiSelect({ selected, onChange }: { selected: Set<string>; onChange: (s: Set<string>) => void }): JSX.Element {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false); };
    document.addEventListener('mousedown', onDoc);
    return () => document.removeEventListener('mousedown', onDoc);
  }, [open]);
  const total = KIND_MENU.length;
  const allChecked = selected.size === total;
  const label = allChecked ? 'All kinds' : selected.size === 0 ? 'No kinds' : `${selected.size} kinds`;
  const toggleKind = (k: string) => {
    const next = new Set(selected);
    if (next.has(k)) next.delete(k); else next.add(k);
    onChange(next);
  };
  const rowStyle: CSSProperties = { display: 'flex', alignItems: 'center', gap: 7, padding: '4px 8px', fontSize: 12, cursor: 'pointer', color: 'var(--text)', borderRadius: 4 };
  return (
    <div ref={ref} style={{ position: 'relative' }}>
      <button
        className="context-mgr-kind-select"
        onClick={() => setOpen((v) => !v)}
        title="Filter by kind"
        style={{ background: 'var(--bg-panel)', color: 'var(--text)', border: '1px solid var(--border-bright)', borderRadius: 6, padding: '4px 10px', fontSize: 12, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6 }}
      >
        {label} <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{'▾'}</span>
      </button>
      {open && (
        <div style={{ position: 'absolute', top: 'calc(100% + 4px)', left: 0, zIndex: 50, background: 'var(--bg-card)', border: '1px solid var(--border-bright)', borderRadius: 6, padding: 4, minWidth: 170, boxShadow: '0 8px 24px rgba(0,0,0,0.5)' }}>
          <label style={{ ...rowStyle, fontWeight: 600 }}>
            <input
              type="checkbox"
              checked={allChecked}
              ref={(el) => { if (el) el.indeterminate = !allChecked && selected.size > 0; }}
              onChange={() => onChange(allChecked ? new Set() : new Set(KIND_MENU))}
            />
            <span>All kinds</span>
          </label>
          <div style={{ height: 1, background: 'var(--border)', margin: '3px 2px' }} />
          {KIND_MENU.map((k) => (
            <label key={k} style={rowStyle}>
              <input type="checkbox" checked={selected.has(k)} onChange={() => toggleKind(k)} />
              <span>{KIND_LABEL[k]}</span>
            </label>
          ))}
        </div>
      )}
    </div>
  );
}

// ---- Visual-state persistence ----------------------------------------------
// The Context Mgr is an `app`-type tab; switching away UNMOUNTS it, dropping all
// useState. Persist the visual state (active tab, filters, selection, focus tab,
// matrix selection) to localStorage so returning restores exactly where you were.
const CTXPANE_KEY = 'uai:ctxMgr:pane';
interface CtxPaneState {
  activeTab: TopTab; search: string; kinds: string[]; // selected kinds (multi); all = every kind
  loaderFilter: LoaderFilter;
  selectedId: string | null; focusTab: FocusTab; matrixSelected: string[];
  showOut: boolean; showIn: boolean; showOrphans: boolean; showChildless: boolean;
  schemaV?: number;  // migration marker (see loadCtxPane)
}
// Bump when a DEFAULT changes and existing persisted state should adopt it once.
const CTXPANE_SCHEMA_V = 2;
const CTXPANE_DEFAULT: CtxPaneState = {
  activeTab: 'library', search: '', kinds: [...KIND_DISPLAY_ORDER],
  loaderFilter: null, selectedId: null, focusTab: 'info', matrixSelected: [],
  showOut: true, showIn: false, showOrphans: false, showChildless: false,
  schemaV: CTXPANE_SCHEMA_V,
};
function loadCtxPane(): CtxPaneState {
  try {
    const raw = localStorage.getItem(CTXPANE_KEY);
    if (raw) {
      const merged: CtxPaneState = { ...CTXPANE_DEFAULT, ...JSON.parse(raw) };
      // One-time migration: Outbound links now default ON. Existing state from
      // before this schema adopts the new default ONCE; after that the user's
      // toggle persists normally (persistence persists, not persnickety).
      if ((merged.schemaV ?? 1) < CTXPANE_SCHEMA_V) {
        merged.showOut = true;
        merged.schemaV = CTXPANE_SCHEMA_V;
      }
      return merged;
    }
  } catch { /* ignore */ }
  return { ...CTXPANE_DEFAULT };
}
function saveCtxPane(patch: Partial<CtxPaneState>): void {
  try {
    saveCtxPane_cur = { ...saveCtxPane_cur, ...patch };
    localStorage.setItem(CTXPANE_KEY, JSON.stringify(saveCtxPane_cur));
  } catch { /* ignore */ }
}
let saveCtxPane_cur: CtxPaneState = loadCtxPane();

/** ⚙ mcp / ⌘ command loader badge glyph, or null for non-badged loaders. */
function loaderBadge(loader?: string | null): { glyph: string; label: string } | null {
  if (loader === 'mcp') return { glyph: '⚙', label: 'Loaded via MCP (knowledge_get_*)' };
  if (loader === 'command') return { glyph: '⌘', label: 'Loaded via /command' };
  return null;
}

function fmtBytes(n?: number | null): string {
  if (n == null) return '—';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${Math.round(n / 1024)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

function fmtTime(ts?: string | null): string {
  if (!ts) return '—';
  const d = new Date(ts);
  if (isNaN(d.getTime())) return ts;
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

/** A best-effort document version, if the item carries one (frontmatter/provenance). */
function itemVersion(meta?: CtxMeta | null): string | null {
  if (!meta) return null;
  const prov = meta.provenance as Record<string, unknown> | null | undefined;
  const v = (meta as any).version ?? prov?.version ?? prov?.['v'];
  if (v == null || v === '') return null;
  const s = String(v).trim();
  return s.startsWith('v') ? s : `v${s}`;
}

// ---- Catalog hierarchy (A) -------------------------------------------------
//  Each kind group's flat `kind:cat/sub/leaf` ids become a real folder tree so
//  the folder prefix is shown ONCE (as a collapsible dir) instead of repeated
//  in front of every leaf. Mirrors NewsTab's buildTree + renderNode pattern.

interface CtxTreeNode {
  seg: string;            // this node's path segment (display label)
  fullName: string;      // full name path within the kind (collapse key)
  isDir: boolean;
  item?: CtxItem;         // present on leaf nodes
  children: Map<string, CtxTreeNode>;
}

function buildCtxTree(list: CtxItem[]): CtxTreeNode {
  const root: CtxTreeNode = { seg: '', fullName: '', isDir: true, children: new Map() };
  for (const it of list) {
    const segs = (it.name || it.id).split('/').filter(Boolean);
    let node = root;
    segs.forEach((seg, i) => {
      let child = node.children.get(seg);
      if (!child) {
        child = { seg, fullName: segs.slice(0, i + 1).join('/'), isDir: true, children: new Map() };
        node.children.set(seg, child);
      }
      node = child;
      if (i === segs.length - 1) { node.item = it; node.isDir = false; }
    });
  }
  return root;
}

/** Sorted children: directories first, then alphabetical. */
function sortedChildren(node: CtxTreeNode): CtxTreeNode[] {
  return Array.from(node.children.values()).sort((a, b) => {
    if (a.isDir !== b.isDir) return a.isDir ? -1 : 1;
    return a.seg.localeCompare(b.seg);
  });
}

// ---- Component -------------------------------------------------------------

interface ContextMgrPaneProps {
  tabId: string;
  deepLinkId?: string;
}

export default function ContextMgrPane({ tabId, deepLinkId }: ContextMgrPaneProps): JSX.Element {
  const { showToast } = useToast();
  const catalogResize = usePanelResize('contextMgrCatalogWidth', { def: 360, min: 220, max: () => Math.max(700, Math.round(window.innerWidth * 0.5)) });

  // Generic engine call. Throws on !ok so callers can try/catch + toast.
  const run = useCallback(async (verb: string, args: string[] = []): Promise<any> => {
    const r = await window.uai.context.run(verb, args);
    if (!r.ok) throw new Error(r.error || `${verb} failed`);
    return r.data;
  }, []);

  // Top-level. Visual state lazy-inits from the persisted snapshot (see
  // CTXPANE_KEY) and is written back by the effect below, so switching tabs
  // away and back restores the tool exactly.
  const [activeTab, setActiveTab] = useState<TopTab>(() => saveCtxPane_cur.activeTab);

  // Header health
  const [totalItems, setTotalItems] = useState<number | null>(null);
  const [reindexing, setReindexing] = useState(false);

  // Library item actions: a "Load into…" session picker + an in-flight guard.
  const [loadPicker, setLoadPicker] = useState(false);
  const [sessions, setSessions] = useState<Array<{ id: string; name: string }>>([]);
  const [actionBusy, setActionBusy] = useState(false);

  // Links tab: "Is loaded by" scan — which sessions currently have THIS item in
  // context. Switchable to the inverse ("Is not loaded by"). Scanned on demand
  // (one traits.list per session), keyed by item id so we don't rescan on tab
  // flips. Match is by the traits (type, name) the item maps to.
  const [loadedScan, setLoadedScan] = useState<{
    itemId: string; loading: boolean;
    loaded: Array<{ id: string; name: string }>;
    notLoaded: Array<{ id: string; name: string }>;
  } | null>(null);
  const [loadedMode, setLoadedMode] = useState<'loaded' | 'not'>('loaded');

  // Catalog (left)
  const [items, setItems] = useState<CtxItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [search, setSearch] = useState(() => saveCtxPane_cur.search);
  const [searchActive, setSearchActive] = useState(() => !!saveCtxPane_cur.search);
  const [kindSel, setKindSel] = useState<Set<string>>(() => new Set(saveCtxPane_cur.kinds));
  const [loaderFilter, setLoaderFilter] = useState<LoaderFilter>(() => saveCtxPane_cur.loaderFilter);
  const [collapsedKinds, setCollapsedKinds] = useState<Set<string>>(new Set());
  // Collapsed folders inside the hierarchical catalog (key: `${kind}::${fullName}`).
  const [collapsedDirs, setCollapsedDirs] = useState<Set<string>>(new Set());

  // Validation (drives the Validate tab + the health line + per-row ⚠)
  const [validateResult, setValidateResult] = useState<ValidateResult | null>(null);
  const [validating, setValidating] = useState(false);

  // Focus (right). Tab order is Info · Content · Links (· Loads for bundles),
  // with Info the default (per todo_0338).
  const [selectedId, setSelectedId] = useState<string | null>(() => saveCtxPane_cur.selectedId);
  const [focusTab, setFocusTab] = useState<FocusTab>(() => normalizeFocusTab(saveCtxPane_cur.focusTab));
  const [meta, setMeta] = useState<CtxMeta | null>(null);
  const [content, setContent] = useState<ContentResult | null>(null);
  const [refs, setRefs] = useState<RefEdge[] | null>(null);
  const [loads, setLoads] = useState<ResolveResult | null>(null);
  const [focusLoading, setFocusLoading] = useState(false);
  const [copied, setCopied] = useState(false);
  const [pathCopied, setPathCopied] = useState(false);
  // Content view: render markdown (.md files) vs show raw source.
  const [contentRendered, setContentRendered] = useState(true);

  // Peek (bottom drawer) — preview without changing Focus.
  const [peek, setPeek] = useState<{ id: string; title: string; content: string } | null>(null);
  const [peekCollapsed, setPeekCollapsed] = useState(true);

  // Persist the visual state on any change (write-through to localStorage).
  useEffect(() => {
    saveCtxPane({ activeTab, search, kinds: Array.from(kindSel), loaderFilter, selectedId, focusTab });
  }, [activeTab, search, kindSel, loaderFilter, selectedId, focusTab]);

  // ---- Derived ------------------------------------------------------------

  /** Set of src ids that have at least one dangling outbound ref (for the ⚠ flag). */
  const danglingSrcSet = useMemo(() => {
    const s = new Set<string>();
    for (const d of validateResult?.dangling ?? []) s.add(d.src_id);
    return s;
  }, [validateResult]);

  const danglingCount = validateResult?.dangling.length ?? 0;

  const itemsByKind = useMemo(() => {
    const groups: Record<string, CtxItem[]> = {};
    for (const it of items) {
      if (!kindSel.has(it.kind)) continue; // multi-select kind filter (client-side)
      (groups[it.kind] ??= []).push(it);
    }
    return Object.entries(groups).sort(
      ([a], [b]) => (KIND_ORDER[a] ?? 99) - (KIND_ORDER[b] ?? 99) || a.localeCompare(b),
    );
  }, [items, kindSel]);

  // ---- Data loading -------------------------------------------------------

  const loadHealth = useCallback(async () => {
    setValidating(true);
    try {
      const [all, vr] = await Promise.all([
        run('list').catch(() => null),
        run('validate').catch(() => null),
      ]);
      if (Array.isArray(all)) setTotalItems(all.length);
      if (vr) setValidateResult(vr as ValidateResult);
    } finally {
      setValidating(false);
    }
  }, [run]);

  const loadCatalog = useCallback(async () => {
    setLoading(true);
    try {
      let data: any;
      if (searchActive && search.trim()) {
        data = await run('search', [search.trim()]);
      } else {
        const args: string[] = [];
        // Kind filter is applied client-side (multi-select); fetch all kinds.
        // Always active-only (archived hidden); no status filter surfaced.
        if (loaderFilter) args.push('--loader', loaderFilter);
        data = await run('list', args);
      }
      setItems(Array.isArray(data) ? data : []);
    } catch (err: any) {
      showToast(err.message || 'Failed to load catalog', 'error');
      setItems([]);
    } finally {
      setLoading(false);
    }
  }, [run, search, searchActive, loaderFilter, showToast]);

  // Mount: health + first catalog load.
  useEffect(() => { loadHealth(); }, [loadHealth]);
  useEffect(() => { loadCatalog(); }, [loadCatalog]);

  // Validate tab: refresh validation when opened.
  useEffect(() => {
    if (activeTab === 'validate') loadHealth();
  }, [activeTab, loadHealth]);

  // ---- Focus loading ------------------------------------------------------

  // On selection change: load metadata + clear caches. The focus sub-tab is
  // STICKY — it stays on whatever the user last chose (Info/Content/Links/Loads)
  // when moving between items, rather than snapping back to Info each time. The
  // (selectedId, focusTab) effect below reloads the active tab's data.
  useEffect(() => {
    if (!selectedId) { setMeta(null); setContent(null); setRefs(null); setLoads(null); return; }
    setContent(null);
    setRefs(null);
    setLoads(null);
    setContentRendered(true);
    let cancelled = false;
    run('get', [selectedId])
      .then((d) => { if (!cancelled) setMeta(d as CtxMeta); })
      .catch(() => { if (!cancelled) setMeta(null); });
    return () => { cancelled = true; };
  }, [selectedId, run]);

  // Load the active focus tab's data on (selection, focusTab) change.
  useEffect(() => {
    if (!selectedId) return;
    let cancelled = false;
    const load = async () => {
      try {
        // Info now also hosts the file Content (lazy). Links now also hosts the
        // transitive Loads leaf set (for bundles) — fetch both if missing.
        if (focusTab === 'info' && content === null) {
          const d = await run('content', [selectedId]);
          if (!cancelled) setContent(d as ContentResult);
        } else if (focusTab === 'links') {
          if (refs === null) {
            const d = await run('refs', [selectedId, '--both']);
            if (!cancelled) setRefs(Array.isArray(d) ? d : []);
          }
          if (isBundle(meta?.kind) && loads === null) {
            const d = await run('resolve', [selectedId]);
            if (!cancelled) setLoads(d as ResolveResult);
          }
        }
      } catch (err: any) {
        if (!cancelled) showToast(err.message || `Failed to load ${focusTab}`, 'error');
      }
    };
    setFocusLoading(true);
    load().finally(() => { if (!cancelled) setFocusLoading(false); });
    return () => { cancelled = true; };
  }, [selectedId, focusTab, content, refs, loads, meta, run, showToast]);

  // Deep link: auto-select once items load (id / name match).
  const deepLinkHandled = useRef(false);
  useEffect(() => {
    if (!deepLinkId || deepLinkHandled.current || items.length === 0) return;
    const match = items.find((it) => it.id === deepLinkId || it.name === deepLinkId);
    if (match) {
      deepLinkHandled.current = true;
      setSelectedId(match.id);
    }
  }, [deepLinkId, items]);

  // ---- Actions ------------------------------------------------------------

  const handleReindex = useCallback(async () => {
    setReindexing(true);
    try {
      await run('reindex');
      showToast('Reindexed context graph', 'info');
      await Promise.all([loadHealth(), loadCatalog()]);
    } catch (err: any) {
      showToast(err.message || 'Reindex failed', 'error');
    } finally {
      setReindexing(false);
    }
  }, [run, loadHealth, loadCatalog, showToast]);

  const handleSelect = useCallback((id: string) => {
    setSelectedId(id);
  }, []);

  const toggleKind = useCallback((kind: string) => {
    setCollapsedKinds((prev) => {
      const next = new Set(prev);
      if (next.has(kind)) next.delete(kind); else next.add(kind);
      return next;
    });
  }, []);

  const toggleDir = useCallback((key: string) => {
    setCollapsedDirs((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key); else next.add(key);
      return next;
    });
  }, []);

  /** cmd+click a path → open in OS; shift+click → copy the absolute path. */
  const handlePathClick = useCallback((e: React.MouseEvent, relPath?: string | null) => {
    const abs = absPathOf(relPath);
    if (!abs) return;
    if (e.shiftKey) {
      e.preventDefault();
      navigator.clipboard.writeText(abs).then(() => {
        setPathCopied(true);
        setTimeout(() => setPathCopied(false), 1500);
      }).catch(() => {});
    } else if (e.metaKey || e.ctrlKey) {
      e.preventDefault();
      window.uai.openPath(abs).then((r) => {
        if (!r?.ok) showToast(r?.error || 'Could not open file', 'error');
      }).catch((err: any) => showToast(err?.message || 'Could not open file', 'error'));
    }
  }, [showToast]);

  const handleSearchSubmit = useCallback(() => {
    setSearchActive(!!search.trim());
  }, [search]);

  const clearSearch = useCallback(() => {
    setSearch('');
    setSearchActive(false);
  }, []);

  const handleCopyContent = useCallback(() => {
    if (!content?.content) return;
    navigator.clipboard.writeText(content.content).then(() => {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    }).catch(() => {});
  }, [content]);

  /** Preview an item in the bottom Peek drawer WITHOUT changing Focus. */
  // Latest peek state, read inside the stable handlePeek without re-creating it.
  const peekStateRef = useRef<{ id: string | null; collapsed: boolean }>({ id: null, collapsed: true });
  useEffect(() => { peekStateRef.current = { id: peek?.id ?? null, collapsed: peekCollapsed }; }, [peek, peekCollapsed]);

  const closePeek = useCallback(() => { setPeek(null); setPeekCollapsed(true); }, []);

  const handlePeek = useCallback(async (id: string) => {
    // Toggle: clicking [peek] on the item already showing collapses the drawer.
    const cur = peekStateRef.current;
    if (cur.id === id && !cur.collapsed) { setPeekCollapsed(true); return; }
    setPeekCollapsed(false);
    const title = items.find((it) => it.id === id)?.title || id;
    setPeek({ id, title, content: 'Loading…' });
    try {
      const d = await run('content', [id]);
      setPeek({ id, title, content: (d as ContentResult)?.content ?? '(no content)' });
    } catch (err: any) {
      setPeek({ id, title, content: err.message || '(failed to load)' });
    }
  }, [items, run]);

  const promotePeekToFocus = useCallback(() => {
    if (peek) { setSelectedId(peek.id); setPeekCollapsed(true); }
  }, [peek]);

  // ---- Render -------------------------------------------------------------

  const selectedMetaKind = meta?.kind ?? items.find((it) => it.id === selectedId)?.kind;
  const focusIsBundle = isBundle(selectedMetaKind);
  const focusVersion = itemVersion(meta);
  const focusPath = meta?.path ?? content?.path ?? null;
  const contentIsMarkdown = (content?.path ?? '').toLowerCase().endsWith('.md');
  const contentIsYaml = /\.(ya?ml)$/i.test(content?.path ?? '');

  // ── Library item actions (Open / Open in Matrix / Load into… / Archive) ────
  const openSelectedFile = useCallback(async () => {
    const abs = absPathOf(focusPath);
    if (!abs) { showToast('No file path for this item', 'error'); return; }
    const r = await window.uai.openPath(abs);
    if (!r?.ok) showToast(r?.error || 'Could not open file', 'error');
  }, [focusPath, showToast]);

  // Jump to the Link Matrix with this item pre-selected. The matrix reads its
  // selection from the persisted pane snapshot on mount, so seed it then switch.
  const openInMatrix = useCallback(() => {
    if (!selectedId) return;
    saveCtxPane({ matrixSelected: [selectedId] });
    setActiveTab('matrix');
  }, [selectedId]);

  // Archive (soft-delete) the item after confirmation, then refresh the catalog.
  const archiveSelected = useCallback(async () => {
    if (!selectedId) return;
    if (!window.confirm(`Archive ${selectedId}?\n\nThis moves its file into the kind's _archive/ folder (reversible by moving it back) and drops it from the active index.`)) return;
    setActionBusy(true);
    try {
      const d = await run('archive', [selectedId]);
      if (d && d.ok === false) throw new Error(d.error || 'archive failed');
      if (d && d.error === 'referenced') {
        showToast(`Blocked: ${selectedId} is referenced by ${(d.referrers || []).join(', ')}. Unlink first.`, 'error');
        return;
      }
      showToast(`Archived ${selectedId}`, 'info');
      setSelectedId(null);
      await loadCatalog();
    } catch (e: any) {
      showToast(e?.message || 'Archive failed', 'error');
    } finally {
      setActionBusy(false);
    }
  }, [selectedId, run, showToast, loadCatalog]);

  // Load this item into a chosen session's context (traits.load).
  const openLoadPicker = useCallback(async () => {
    try {
      const list = await window.uai.sessions.list();
      const rows = (list || [])
        // Only ACTIVE (running) sessions — you can't load context into a stopped
        // one, and it keeps the list short (there can be 100+ total sessions).
        .filter((s) => s.process_status === 'running' && !s.archived)
        .map((s) => ({ id: s.tracking_id, name: s.display_name || s.tracking_id }))
        .filter((s) => s.id)
        .sort((a, b) => a.name.localeCompare(b.name));
      setSessions(rows);
    } catch { setSessions([]); }
    setLoadPicker(true);
  }, []);

  const loadIntoSession = useCallback(async (sessionId: string) => {
    if (!selectedId || !selectedMetaKind) return;
    const nm = meta?.name ?? selectedId.split(':').slice(1).join(':');
    const trait = kindToTrait(selectedMetaKind, nm);
    setLoadPicker(false);
    if (!trait) { showToast(`Kind "${selectedMetaKind}" can't be loaded as a trait`, 'error'); return; }
    setActionBusy(true);
    try {
      const res = await window.uai.traits.load(sessionId, [trait]);
      const r0 = res?.results?.[0];
      if (res?.success && (!r0 || r0.success)) showToast(`Loaded ${nm} into ${sessionId}`, 'info');
      else showToast(r0?.error || 'Load failed', 'error');
    } catch (e: any) {
      showToast(e?.message || 'Load failed', 'error');
    } finally {
      setActionBusy(false);
    }
  }, [selectedId, selectedMetaKind, meta, showToast]);

  // Scan every ACTIVE (running) session for whether it has THIS item loaded,
  // partitioning into loaded / not-loaded. One traits.list per session — so we
  // scan only RUNNING sessions (not all 100+), which is both correct (a stopped
  // session's loaded-state is stale) and the fix for the occasional lag this
  // caused when it fanned out across every session.
  const scanLoadedBy = useCallback(async () => {
    if (!selectedId || !selectedMetaKind) return;
    const nm = meta?.name ?? selectedId.split(':').slice(1).join(':');
    const trait = kindToTrait(selectedMetaKind, nm);
    if (!trait) { setLoadedScan({ itemId: selectedId, loading: false, loaded: [], notLoaded: [] }); return; }
    setLoadedScan({ itemId: selectedId, loading: true, loaded: [], notLoaded: [] });
    let list: any[] = [];
    try { list = await window.uai.sessions.list(); } catch { list = []; }
    const active = (list || [])
      .filter((s) => s.process_status === 'running' && !s.archived)
      .map((s) => ({ id: s.tracking_id, name: s.display_name || s.tracking_id }));
    const loaded: Array<{ id: string; name: string }> = [];
    const notLoaded: Array<{ id: string; name: string }> = [];
    await Promise.all(active.map(async (s) => {
      let has = false;
      try {
        const traits = await window.uai.traits.list(s.id);
        has = (traits || []).some((t: any) => t.loaded && t.type === trait.type && t.name === trait.name);
      } catch { /* treat as not-loaded */ }
      (has ? loaded : notLoaded).push(s);
    }));
    const byName = (a: { name: string }, b: { name: string }) => a.name.localeCompare(b.name);
    setLoadedScan({ itemId: selectedId, loading: false, loaded: loaded.sort(byName), notLoaded: notLoaded.sort(byName) });
  }, [selectedId, selectedMetaKind, meta]);

  // Auto-scan when the Links tab is open for an item we haven't scanned yet.
  useEffect(() => {
    if (focusTab !== 'links' || !selectedId) return;
    if (loadedScan?.itemId === selectedId) return;
    scanLoadedBy();
  }, [focusTab, selectedId, loadedScan, scanLoadedBy]);

  // Dismiss the "Load into…" session picker on outside-click / Esc.
  useEffect(() => {
    if (!loadPicker) return;
    const onDoc = () => setLoadPicker(false);
    const onKey = (e: KeyboardEvent) => { if (e.key === 'Escape') setLoadPicker(false); };
    document.addEventListener('click', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('click', onDoc); document.removeEventListener('keydown', onKey); };
  }, [loadPicker]);

  /** Recursively render a catalog tree: folders collapse/expand, leaves show
      ONLY their last segment (the folder prefix is shown once, on the dir). */
  const renderCatalogNode = (node: CtxTreeNode, kind: string, depth: number): JSX.Element[] => {
    const rows: JSX.Element[] = [];
    for (const child of sortedChildren(node)) {
      const indent = 16 + depth * 14;
      if (child.isDir) {
        const key = `${kind}::${child.fullName}`;
        const collapsed = collapsedDirs.has(key);
        rows.push(
          <div
            key={key}
            className="context-mgr-tree-dir"
            style={{ paddingLeft: `${indent}px` }}
            onClick={() => toggleDir(key)}
            title={child.fullName}
          >
            <span className="context-mgr-collapse">{collapsed ? '▶' : '▼'}</span>
            <span className="context-mgr-tree-folder" style={{ color: kindLabelColor(kind, `${child.fullName}/_`) }}>{child.seg}/</span>
          </div>,
        );
        if (!collapsed) rows.push(...renderCatalogNode(child, kind, depth + 1));
      } else {
        const it = child.item!;
        const badge = isBundle(it.kind) ? loaderBadge(it.loader) : null;
        const dangling = danglingSrcSet.has(it.id);
        rows.push(
          <div
            key={it.id}
            className={`context-mgr-item${selectedId === it.id ? ' selected' : ''}`}
            style={{ paddingLeft: `${indent}px` }}
            onClick={() => handleSelect(it.id)}
            title={it.title || it.id}
          >
            {/* chevron-width spacer so leaves align under their folder's name */}
            <span className="context-mgr-collapse context-mgr-tree-spacer" />
            <span className="context-mgr-item-id" style={{ color: kindLabelColor(it.kind, it.name) }}>{child.seg}</span>
            {badge && <span className="context-mgr-loader-badge" title={badge.label}>{badge.glyph}</span>}
            {dangling && <span className="context-mgr-warn" title="Has a dangling outbound reference">{'⚠'}</span>}
            {it.title && it.title !== it.name && <span className="context-mgr-item-title">{it.title}</span>}
          </div>,
        );
      }
    }
    return rows;
  };

  // Viewport reporter — surfaces the Context Mgr's live data to describeViewport()
  // so the "Capture Content" feature shows what the user is actually looking at
  // (active view, filters, counts, the selected item's detail, and the visible
  // catalog groups) rather than an empty dead node. Read-only: this tool drives
  // window.uai.context.run verbs, not Command Bus commands, so no actions.
  useViewport('context_manager', () => ({
    visible: true,
    label: 'Context Manager',
    state: {
      view: activeTab,
      totalItems,
      dangling: danglingCount,
      orphans: validateResult?.orphans.length ?? null,
      search: searchActive ? search : '',
      kinds: Array.from(kindSel),
      loaderFilter,
      visibleItems: itemsByKind.reduce((n, [, list]) => n + list.length, 0),
      selectedId,
      focusTab,
    },
    actions: [],
    children: [
      // The SELECTED item's detail — the focus of the Library master/detail.
      ...(selectedId ? [{
        id: 'context_manager.selection',
        label: meta?.name ?? selectedId,
        visible: true,
        state: {
          id: selectedId,
          kind: selectedMetaKind ?? null,
          title: meta?.title ?? null,
          path: focusPath,
          version: focusVersion,
          size: meta?.size_bytes ?? null,
          status: meta?.status ?? null,
          scope: meta?.scope ?? null,
          loader: meta?.loader ?? null,
          outbound: meta?.counts?.outbound ?? null,
          inbound: meta?.counts?.inbound ?? null,
          focusTab,
          contentChars: content?.content?.length ?? null,
          links: refs?.length ?? null,
          loads: loads?.resolved?.length ?? null,
        },
        children: [],
      }] : []),
      // Library catalog groups (kind → visible item names, top 20 each).
      ...(activeTab === 'library' ? itemsByKind.map(([kind, list]) => ({
        id: `context_manager.group.${kind}`,
        label: kind,
        visible: true,
        state: { count: list.length, items: list.slice(0, 20).map((it) => it.name) },
        children: [],
      })) : []),
      // Validate tab: dangling refs + orphans (top 20 samples).
      ...(activeTab === 'validate' && validateResult ? [{
        id: 'context_manager.validation',
        label: 'Validation',
        visible: true,
        state: {
          dangling: validateResult.dangling.length,
          orphans: validateResult.orphans.length,
          danglingSample: validateResult.dangling.slice(0, 20).map((d) => `${d.src_id} → ${d.dst_id}`),
          orphanSample: validateResult.orphans.slice(0, 20).map((o) => `${o.id} [${o.severity}]`),
        },
        children: [],
      }] : []),
    ],
  }));

  // The bottom Peek drawer — shared by the Library and Link Matrix tabs so a
  // [peek] from either surfaces the preview in the same place.
  const peekDrawer = (
    <div className={`context-mgr-peek${peekCollapsed ? ' collapsed' : ''}`}>
      <div className="context-mgr-peek-head" onClick={() => setPeekCollapsed((c) => !c)}>
        <span className="context-mgr-collapse">{peekCollapsed ? '▶' : '▼'}</span>
        <span className="context-mgr-peek-label">Peek{peek ? `: ${peek.id}` : ''}</span>
        {peek && !peekCollapsed && (
          <button
            className="sched-mgr-btn sched-mgr-btn-sm"
            onClick={(e) => { e.stopPropagation(); promotePeekToFocus(); }}
            title="Promote this peeked item to Focus"
          >{'⤢'} make Focus</button>
        )}
        {peek && (
          <button
            className="context-mgr-peek-close"
            onClick={(e) => { e.stopPropagation(); closePeek(); }}
            title="Close peek"
          >{'✕'}</button>
        )}
      </div>
      {!peekCollapsed && (
        <div className="context-mgr-peek-body">
          {peek ? <pre className="context-mgr-peek-pre">{peek.content}</pre>
            : <div className="context-mgr-empty">Use a [peek] affordance on a Links/Loads row, or the Link Matrix right-click menu, to preview it here.</div>}
        </div>
      )}
    </div>
  );

  return (
    <div className="context-mgr" data-tab-id={tabId}>
      {/* This pane owns its OWN title bar instance (UI Component Architecture:
          no title-bar element is shared across peer panes). Title + index
          health (count · dangling) sit inline here; Reindex lives next to
          Validate in the sub-tab bar below. */}
      <div className="context-mgr-titlebar">
        <TabNavArrows />
        <span className="context-mgr-titlebar-title">Context Manager</span>
        <span className="context-mgr-health" title="Indexed items · dangling references">
          {totalItems != null ? `${totalItems} items` : '…'}
          {' · '}
          <span className={danglingCount > 0 ? 'context-mgr-health-warn' : ''}>{danglingCount} dangling</span>
        </span>
      </div>
      <div className="sched-mgr-tabs context-mgr-tabbar">
        <button className={`sched-mgr-tab${activeTab === 'library' ? ' active' : ''}`} onClick={() => setActiveTab('library')}>Library</button>
        <button className={`sched-mgr-tab${activeTab === 'matrix' ? ' active' : ''}`} onClick={() => setActiveTab('matrix')}>Link Matrix</button>
        <button className={`sched-mgr-tab${activeTab === 'validate' ? ' active' : ''}`} onClick={() => setActiveTab('validate')}>Validate</button>
        <button
          className="sched-mgr-btn sched-mgr-btn-sm context-mgr-reindex-btn"
          onClick={handleReindex}
          disabled={reindexing}
          title="Rebuild the SQLite index (items + link edges) from the on-disk files"
        >{reindexing ? 'Reindexing…' : 'Reindex ⟳'}</button>
      </div>

      {/* LIBRARY */}
      {activeTab === 'library' && (
        <div className="context-mgr-library">
          <div className="context-mgr-split">
            {/* Catalog — draggable width */}
            <div className="context-mgr-catalog" style={{ width: `${catalogResize.width}px` }}>
              <div className="context-mgr-search-row">
                <input
                  className="clearable-input context-mgr-search"
                  type="text"
                  placeholder="Search context…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  onKeyDown={(e) => { if (e.key === 'Enter') handleSearchSubmit(); }}
                />
                {search && (
                  <button className="context-mgr-search-x" onClick={clearSearch} tabIndex={-1} title="Clear">{'×'}</button>
                )}
                <button className="sched-mgr-btn sched-mgr-btn-sm" onClick={handleSearchSubmit} title="Search">Go</button>
              </div>

              {/* Filter pills */}
              <div className="context-mgr-filters">
                <div className="context-mgr-pill-group">
                  <KindMultiSelect selected={kindSel} onChange={setKindSel} />
                </div>
                <div className="context-mgr-pill-group">
                  <button className={`sched-mgr-pill${loaderFilter === 'mcp' ? ' active' : ''}`} onClick={() => setLoaderFilter(loaderFilter === 'mcp' ? null : 'mcp')} title="Roles & profiles (loaded via MCP knowledge_get_*)">{'⚙'} mcp</button>
                  <button className={`sched-mgr-pill${loaderFilter === 'command' ? ' active' : ''}`} onClick={() => setLoaderFilter(loaderFilter === 'command' ? null : 'command')} title="Skills (invoked via a /command)">{'⌘'} command</button>
                </div>
              </div>

              {/* Item list grouped by kind */}
              <div className="context-mgr-catalog-list">
                {loading && <div className="context-mgr-loading">Loading…</div>}
                {!loading && items.length === 0 && <div className="context-mgr-empty">No items found.</div>}
                {!loading && itemsByKind.map(([kind, list]) => (
                  <div key={kind} className="context-mgr-group">
                    <div className="context-mgr-group-header" onClick={() => toggleKind(kind)}>
                      <span className="context-mgr-collapse">{collapsedKinds.has(kind) ? '▶' : '▼'}</span>
                      <span className="context-mgr-group-name" style={{ color: kindLabelColor(kind) }}>{kind}</span>
                      <span className="context-mgr-group-count">{list.length}</span>
                    </div>
                    {!collapsedKinds.has(kind) && (
                      <div className="context-mgr-group-items">
                        {renderCatalogNode(buildCtxTree(list), kind, 0)}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </div>

            <div className="panel-resize-x" onMouseDown={catalogResize.onMouseDown} title="Drag to resize" />

            {/* Focus */}
            <div className="context-mgr-focus">
              {!selectedId ? (
                <div className="context-mgr-empty context-mgr-focus-empty">Select an item to inspect it.</div>
              ) : (
                <>
                  <div className="context-mgr-focus-head">
                    <div className="context-mgr-focus-head-main">
                      <span className="context-mgr-focus-id" title={selectedId} style={selectedMetaKind ? { color: kindLabelColor(selectedMetaKind, meta?.name) } : undefined}>{meta?.name ?? selectedId}</span>
                      {focusVersion && <span className="context-mgr-version" title="Document version">{focusVersion}</span>}
                      {meta?.title && meta.title !== meta.name && <span className="context-mgr-focus-title">{meta.title}</span>}
                    </div>
                    {focusPath && (
                      <span
                        className="context-mgr-focus-path"
                        title={`${absPathOf(focusPath) ?? focusPath}\n⌘/Ctrl+click: open · Shift+click: copy`}
                        onClick={(e) => handlePathClick(e, focusPath)}
                      >{pathCopied ? 'Copied path ✓' : focusPath}</span>
                    )}
                  </div>
                  <div className="context-mgr-focus-actions">
                    <button className="context-mgr-action-btn" onClick={openSelectedFile} disabled={actionBusy} title="Open/edit the file in your OS editor">Open / edit</button>
                    <button className="context-mgr-action-btn" onClick={openInMatrix} disabled={actionBusy} title="Show this item in the Link Matrix">Link Matrix ↗</button>
                    <div className="context-mgr-action-loadwrap">
                      <button className="context-mgr-action-btn" onClick={(e) => { e.stopPropagation(); openLoadPicker(); }} disabled={actionBusy || !kindToTrait(selectedMetaKind ?? '', '')} title="Load this item into a session's context">Load into…</button>
                      {loadPicker && (
                        <div className="context-mgr-session-picker" onClick={(e) => e.stopPropagation()}>
                          <div className="context-mgr-session-picker-head">Load <strong>{meta?.name ?? selectedId}</strong> into:</div>
                          {sessions.length === 0 ? (
                            <div className="context-mgr-ctx-note">No active sessions found.</div>
                          ) : sessions.map((s) => (
                            <button key={s.id} className="context-mgr-ctx-item" onClick={() => loadIntoSession(s.id)} title={s.id}>{s.name}</button>
                          ))}
                          <button className="context-mgr-ctx-item context-mgr-session-cancel" onClick={() => setLoadPicker(false)}>Cancel</button>
                        </div>
                      )}
                    </div>
                    <button className="context-mgr-action-btn context-mgr-action-danger" onClick={archiveSelected} disabled={actionBusy} title="Archive (soft-delete) this item">Archive</button>
                  </div>
                  <div className="context-mgr-focus-tabs">
                    <button className={`context-mgr-focus-tab${focusTab === 'info' ? ' active' : ''}`} onClick={() => setFocusTab('info')}>Info</button>
                    <button className={`context-mgr-focus-tab${focusTab === 'links' ? ' active' : ''}`} onClick={() => setFocusTab('links')}>Links</button>
                  </div>

                  <div className="context-mgr-focus-body">
                    {/* Info = metadata (InfoView) then the file Content below, on
                        the same tab (#4). */}
                    {focusTab === 'info' && <InfoView meta={meta} />}
                    {/* Content — now hosted under the Info tab. */}
                    {focusTab === 'info' && (
                      focusLoading && content === null ? <div className="context-mgr-loading">Loading content…</div> : (
                        <>
                          <div className="context-mgr-content-head context-mgr-content-section">
                            <span
                              className="context-mgr-content-path"
                              title={`${absPathOf(content?.path) ?? content?.path ?? ''}\n⌘/Ctrl+click: open · Shift+click: copy`}
                              onClick={(e) => handlePathClick(e, content?.path)}
                            >{content?.path || selectedId}</span>
                            <div className="context-mgr-content-actions">
                              {contentIsMarkdown && (
                                <button
                                  className="context-mgr-viewer-copy"
                                  onClick={() => setContentRendered((r) => !r)}
                                  title="Toggle rendered markdown / raw source"
                                >{contentRendered ? 'Raw' : 'Rendered'}</button>
                              )}
                              <button className="context-mgr-viewer-copy" onClick={handleCopyContent} disabled={!content?.content}>{copied ? 'Copied!' : 'Copy'}</button>
                            </div>
                          </div>
                          {contentIsMarkdown && contentRendered ? (
                            // Sanitized via DOMPurify in safeMarkdown() (same pipeline as
                            // TranscriptViewer) — no untrusted HTML reaches the DOM.
                            <div
                              className="context-mgr-md"
                              dangerouslySetInnerHTML={{ __html: safeMarkdown(content?.content ?? '') }}
                            />
                          ) : contentIsYaml ? (
                            <YamlView text={content?.content ?? ''} />
                          ) : (
                            <pre className="context-mgr-content-pre">{content?.content ?? '(no content)'}</pre>
                          )}
                        </>
                      )
                    )}

                    {/* Links */}
                    {focusTab === 'links' && (
                      focusLoading && refs === null ? <div className="context-mgr-loading">Loading links…</div> : (
                        <>
                          <LinksView
                            selectedId={selectedId}
                            refs={refs ?? []}
                            onSelect={handleSelect}
                            onPeek={handlePeek}
                          />

                          {/* Loads — the transitive, flattened, de-duplicated leaf
                              set a bundle pulls in, each with its full path (#3,
                              merged from the old Loads tab). Bundles only. */}
                          {focusIsBundle && (
                            <div className="context-mgr-loads-merged">
                              {focusLoading && loads === null
                                ? <div className="context-mgr-loading">Resolving loads…</div>
                                : <LoadsView loads={loads} onSelect={handleSelect} onPeek={handlePeek} />}
                            </div>
                          )}

                          {/* Sessions that (do / do not) have this item loaded. */}
                          <div className="context-mgr-loadedby">
                            <div className="context-mgr-loadedby-head">
                              <div className="context-mgr-loadedby-toggle">
                                <button className={`context-mgr-seg${loadedMode === 'loaded' ? ' active' : ''}`} onClick={() => setLoadedMode('loaded')}>Is loaded by</button>
                                <button className={`context-mgr-seg${loadedMode === 'not' ? ' active' : ''}`} onClick={() => setLoadedMode('not')}>Is not loaded by</button>
                              </div>
                              <button className="context-mgr-loadedby-refresh" onClick={scanLoadedBy} disabled={loadedScan?.loading} title="Rescan sessions">↻</button>
                            </div>
                            {loadedScan?.loading ? (
                              <div className="context-mgr-loading">Scanning sessions…</div>
                            ) : (() => {
                              const rows = loadedMode === 'loaded' ? (loadedScan?.loaded ?? []) : (loadedScan?.notLoaded ?? []);
                              if (!rows.length) {
                                return <div className="context-mgr-ctx-note">{loadedMode === 'loaded' ? 'No active session has this loaded.' : 'Every active session has this loaded.'}</div>;
                              }
                              return (
                                <div className="context-mgr-loadedby-list">
                                  {rows.map((s) => (
                                    <div key={s.id} className="context-mgr-loadedby-item" title={s.id}>
                                      <span className={`context-mgr-loadedby-dot ${loadedMode === 'loaded' ? 'on' : 'off'}`} />
                                      {s.name}
                                    </div>
                                  ))}
                                </div>
                              );
                            })()}
                          </div>
                        </>
                      )
                    )}

                  </div>
                </>
              )}
            </div>
          </div>

          {/* Peek drawer (bottom) — shared with the matrix tab. */}
          {peekDrawer}
        </div>
      )}

      {/* LINK MATRIX (read/explore — Phase 1). Peek works here too (#4). */}
      {activeTab === 'matrix' && (
        <div className="context-mgr-matrix-wrap">
          <LinkMatrixView run={run} onPeek={handlePeek} />
          {peekDrawer}
        </div>
      )}

      {/* VALIDATE */}
      {activeTab === 'validate' && (
        <ValidateView
          result={validateResult}
          loading={validating}
          onSelect={(id) => { setActiveTab('library'); setSelectedId(id); }}
        />
      )}
    </div>
  );
}

// ---- Link Matrix tab -------------------------------------------------------

/**
 * LinkMatrixView — the read/explore link surface (todo_0331 Phase 1).
 *
 * Fetches the WHOLE reference graph once (`graph` verb) and renders four
 * columns left→right: Profiles (profile+global) · Roles (tier-1 bundles a
 * profile/global references) · Sub-roles (tier-2 bundles another role/skill
 * references) · Context Files (the four leaf kinds). A role/skill can appear
 * in both Roles and Sub-roles; one referenced only by another role/skill shows
 * only in Sub-roles; one nothing references shows in Roles (top-level).
 *
 * Interaction (read-only): click an item to SELECT it; its connected set — all
 * items transitively reachable treating edges as bidirectional (outbound = what
 * it pulls in, inbound = what pulls it in) — is highlighted across columns while
 * everything else dims. Click a selected item again to toggle it off.
 * Multi-select highlights the UNION of the selected items' connected sets. With
 * nothing selected, nothing dims. Connectivity is computed client-side via BFS
 * over an undirected adjacency map built once from the fetched edges.
 *
 * Phase 2 will add a "link mode" (create/delete edges); its affordance is
 * present here but inert.
 */
function LinkMatrixView({ run, onPeek }: {
  run: (verb: string, args?: string[]) => Promise<any>;
  onPeek: (id: string) => void;
}): JSX.Element {
  const { showToast } = useToast();
  const [graph, setGraph] = useState<GraphResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(() => new Set(saveCtxPane_cur.matrixSelected));
  // Direction toggles (each independent): show outbound arrows/borders, show
  // inbound. Outbound is the default. Persisted with the rest of the visual state.
  const [showOut, setShowOut] = useState(() => saveCtxPane_cur.showOut);
  const [showIn, setShowIn] = useState(() => saveCtxPane_cur.showIn);
  // Orphan/childless overlays (independent of selection): orphan = no parent (no
  // inbound), childless = no children (no outbound). Each is a highlight ring.
  const [showOrphans, setShowOrphans] = useState(() => saveCtxPane_cur.showOrphans);
  const [showChildless, setShowChildless] = useState(() => saveCtxPane_cur.showChildless);
  // Right-click context menu (open file / link ops) anchored at a client point.
  const [menu, setMenu] = useState<{ x: number; y: number; id: string } | null>(null);
  // Link-arm: the pending source of a new link. When set, the next item the user
  // picks becomes the target (src references dst). Only bundles can be a source.
  const [linkArm, setLinkArm] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  // Spotlight while hovering an "Unlink → X" row in the context menu: the edge
  // itself (drawn as a bright arrow) AND its far endpoint box. The link is the
  // point; the endpoint highlight is a bonus.
  const [menuHoverId, setMenuHoverId] = useState<string | null>(null);
  const [hoverEdge, setHoverEdge] = useState<{ src: string; dst: string; dir: 'out' | 'in' } | null>(null);

  // Persist the matrix selection + all matrix toggles across unmounts.
  useEffect(() => {
    saveCtxPane({ matrixSelected: Array.from(selectedIds), showOut, showIn, showOrphans, showChildless });
  }, [selectedIds, showOut, showIn, showOrphans, showChildless]);

  // Fetch the whole graph (initial mount + after a link/unlink write). Kept as a
  // callback so edge mutations can refresh the arrows/borders in place.
  const reloadGraph = useCallback(async () => {
    const d = await run('graph');
    setGraph(d as GraphResult);
    setError(null);
    return d as GraphResult;
  }, [run]);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    reloadGraph()
      .catch((e: any) => { if (!cancelled) setError(e?.message || 'Failed to load graph'); })
      .finally(() => { if (!cancelled) setLoading(false); });
    return () => { cancelled = true; };
  }, [reloadGraph]);

  // id -> item, for kind lookups while bucketing + rendering.
  const byId = useMemo(() => {
    const m = new Map<string, GraphItem>();
    for (const it of graph?.items ?? []) m.set(it.id, it);
    return m;
  }, [graph]);

  // Source items with ≥1 dangling outbound edge (target missing) → ⚠ badge.
  const danglingSrc = useMemo(() => {
    const s = new Set<string>();
    for (const e of graph?.edges ?? []) if (!byId.has(e.dst_id)) s.add(e.src_id);
    return s;
  }, [graph, byId]);

  // Bucket every item into its column(s).
  const columns = useMemo(() => {
    const profiles: GraphItem[] = [];
    const context: GraphItem[] = [];
    const roles: GraphItem[] = [];
    const subroles: GraphItem[] = [];

    // Which role/skill ids are pulled in by a profile/global vs by a role/skill.
    const hasProfileParent = new Set<string>();
    const hasRoleParent = new Set<string>();
    for (const e of graph?.edges ?? []) {
      const dst = byId.get(e.dst_id);
      if (!dst || !ROLE_KINDS.has(dst.kind)) continue;
      const src = byId.get(e.src_id);
      if (!src) continue;
      if (PROFILE_KINDS.has(src.kind)) hasProfileParent.add(dst.id);
      else if (ROLE_KINDS.has(src.kind)) hasRoleParent.add(dst.id);
    }

    for (const it of graph?.items ?? []) {
      if (PROFILE_KINDS.has(it.kind)) {
        profiles.push(it);
      } else if (CONTEXT_FILE_KINDS.has(it.kind)) {
        if (it.kind !== 'brief') context.push(it); // 3.5: briefs are excluded from the link matrix
      } else if (ROLE_KINDS.has(it.kind)) {
        // Top-level bundle (nothing references it) falls into Roles so it stays visible.
        const topLevel = !hasProfileParent.has(it.id) && !hasRoleParent.has(it.id);
        if (hasProfileParent.has(it.id) || topLevel) roles.push(it);
        if (hasRoleParent.has(it.id)) subroles.push(it);
      }
    }
    const sort = (a: GraphItem, b: GraphItem) => a.id.localeCompare(b.id);
    return {
      profiles: profiles.sort(sort),
      roles: roles.sort(sort),
      subroles: subroles.sort(sort),
      context: context.sort(sort),
    };
  }, [graph, byId]);

  // Transitive (recursive, multi-hop) links of the current selection.
  //   outLinks = every item reachable by following references FORWARD from the
  //     selection (things it includes, and everything those include, …) → cyan.
  //     e.g. select a Profile → its Roles AND those Roles' context files.
  //   inLinks  = every item that can reach the selection by following references
  //     forward (things that include it, transitively) → orange.
  //   outEdges/inEdges = the individual hops along those paths, so the arrow
  //     overlay draws the actual chain (Profile→Role, Role→file) rather than a
  //     single long-range line. An item can be in both sets; selected items in
  //     neither. Cycles are safe (visited-guard on traversal).
  const { outLinks, inLinks, outEdges, inEdges } = useMemo(() => {
    const out = new Set<string>();
    const inn = new Set<string>();
    const outE: Array<{ src: string; dst: string }> = [];
    const inE: Array<{ src: string; dst: string }> = [];
    if (selectedIds.size > 0) {
      // Adjacency restricted to items present in the matrix (byId).
      const fwd = new Map<string, string[]>();
      const bwd = new Map<string, string[]>();
      for (const e of graph?.edges ?? []) {
        if (!byId.has(e.src_id) || !byId.has(e.dst_id)) continue;
        (fwd.get(e.src_id) ?? fwd.set(e.src_id, []).get(e.src_id)!).push(e.dst_id);
        (bwd.get(e.dst_id) ?? bwd.set(e.dst_id, []).get(e.dst_id)!).push(e.src_id);
      }
      // BFS the transitive closure in one direction, recording hop edges.
      const walk = (
        adj: Map<string, string[]>,
        reach: Set<string>,
        edges: Array<{ src: string; dst: string }>,
        forward: boolean,
      ) => {
        const seen = new Set<string>(selectedIds);
        const seenEdge = new Set<string>();
        let frontier = Array.from(selectedIds);
        while (frontier.length) {
          const next: string[] = [];
          for (const node of frontier) {
            for (const nbr of adj.get(node) ?? []) {
              // Record the hop in true graph direction (src → dst).
              const src = forward ? node : nbr;
              const dst = forward ? nbr : node;
              const ek = `${src}\u0000${dst}`;
              if (!seenEdge.has(ek)) { seenEdge.add(ek); edges.push({ src, dst }); }
              if (!selectedIds.has(nbr)) reach.add(nbr);
              if (!seen.has(nbr)) { seen.add(nbr); next.push(nbr); }
            }
          }
          frontier = next;
        }
      };
      walk(fwd, out, outE, true);
      walk(bwd, inn, inE, false);
      for (const s of selectedIds) { out.delete(s); inn.delete(s); }
    }
    return { outLinks: out, inLinks: inn, outEdges: outE, inEdges: inE };
  }, [selectedIds, graph, byId]);

  // Orphan (no parent / no inbound) and childless (no children / no outbound)
  // sets, with the rule exclusions (7.1–7.3):
  //   orphan   — skip top-level compositions (global/profile = first column) + skills.
  //   childless — skip context files (= last column, never have children).
  const { orphanSet, childlessSet } = useMemo(() => {
    const hasIn = new Set<string>();
    const hasOut = new Set<string>();
    for (const e of graph?.edges ?? []) {
      if (byId.has(e.src_id)) hasOut.add(e.src_id);
      if (byId.has(e.dst_id)) hasIn.add(e.dst_id);
    }
    const orphans = new Set<string>();
    const childless = new Set<string>();
    for (const it of graph?.items ?? []) {
      if (it.kind === 'brief') continue; // not in the matrix at all
      if (!hasIn.has(it.id) && !PROFILE_KINDS.has(it.kind) && it.kind !== 'skill') orphans.add(it.id);
      if (!hasOut.has(it.id) && !CONTEXT_FILE_KINDS.has(it.kind)) childless.add(it.id);
    }
    return { orphanSet: orphans, childlessSet: childless };
  }, [graph, byId]);

  // Orphan/childless highlight rings (independent of selection; they stack over
  // the link border via box-shadow so both can show at once).
  const overlayStyle = (id: string): CSSProperties => {
    const orph = showOrphans && orphanSet.has(id);
    const chld = showChildless && childlessSet.has(id);
    if (orph && chld) return { boxShadow: `0 0 0 2px ${ORPHAN_COLOR}, 0 0 0 4px ${CHILDLESS_COLOR}` };
    if (orph) return { boxShadow: `0 0 0 2px ${ORPHAN_COLOR}` };
    if (chld) return { boxShadow: `0 0 0 2px ${CHILDLESS_COLOR}` };
    return {};
  };

  const toggle = useCallback((id: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id); else next.add(id);
      return next;
    });
  }, []);
  const clearSelection = useCallback(() => setSelectedIds(new Set()), []);
  const hasSelection = selectedIds.size > 0;

  // ── Open file + edit links (right-click actions) ──────────────────────────
  const nameOf = useCallback((id: string) => byId.get(id)?.name ?? id, [byId]);

  // Open an item's underlying file in the OS. `get` returns an AI_ROOT-relative
  // path; absPathOf resolves it for the shell.
  const openItem = useCallback(async (id: string) => {
    try {
      const meta = await run('get', [id]);
      const abs = absPathOf(meta?.path);
      if (!abs) { showToast('No file path for this item', 'error'); return; }
      const r = await window.uai.openPath(abs);
      if (!r?.ok) showToast(r?.error || 'Could not open file', 'error');
    } catch (e: any) {
      showToast(e?.message || 'Could not open file', 'error');
    }
  }, [run, showToast]);

  // Add / remove a reference edge (src bundle → dst). context_mgr writes the
  // YAML (self/cycle/missing guarded), then we reload the graph so arrows +
  // borders reflect the new edge immediately.
  const runEdgeOp = useCallback(async (verb: 'link' | 'unlink', src: string, dst: string) => {
    setBusy(true);
    try {
      const d = await run(verb, [src, dst, '--by', 'uai-context-mgr']);
      if (d && d.ok === false) throw new Error(d.error || `${verb} failed`);
      await reloadGraph();
      showToast(
        verb === 'link'
          ? `Linked ${nameOf(src)} → ${nameOf(dst)}`
          : `Unlinked ${nameOf(src)} → ${nameOf(dst)}`,
        'info',
      );
    } catch (e: any) {
      showToast(e?.message || `${verb} failed`, 'error');
    } finally {
      setBusy(false);
    }
  }, [run, reloadGraph, showToast, nameOf]);

  // Direct edges touching an item, for the "remove link" section of the menu.
  const edgesTouching = useCallback((id: string) => {
    const outs: string[] = []; const ins: string[] = [];
    for (const e of graph?.edges ?? []) {
      if (!byId.has(e.src_id) || !byId.has(e.dst_id)) continue;
      if (e.src_id === id) outs.push(e.dst_id);
      if (e.dst_id === id) ins.push(e.src_id);
    }
    return { outs, ins };
  }, [graph, byId]);

  // Clear the unlink-row spotlight whenever the menu goes away.
  useEffect(() => { if (!menu) { setMenuHoverId(null); setHoverEdge(null); } }, [menu]);
  // Global click / Esc dismiss the menu and cancel a pending link.
  useEffect(() => {
    if (!menu && !linkArm) return;
    const onDoc = () => setMenu(null);
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') { setMenu(null); setLinkArm(null); }
    };
    document.addEventListener('click', onDoc);
    document.addEventListener('keydown', onKey);
    return () => { document.removeEventListener('click', onDoc); document.removeEventListener('keydown', onKey); };
  }, [menu, linkArm]);

  type Dir = 'selected' | 'out' | 'in' | 'both' | 'dim' | null;
  const itemDir = (id: string): Dir => {
    if (!hasSelection) return null;
    if (selectedIds.has(id)) return 'selected';
    const o = showOut && outLinks.has(id);
    const i = showIn && inLinks.has(id);
    if (o && i) return 'both';
    if (o) return 'out';
    if (i) return 'in';
    return 'dim';
  };
  // Direction → boundary. out=cyan, in=orange, both=diagonally split (top-left
  // cyan / bottom-right orange). selected + dim are handled by CSS classes.
  const dirBorder = (dir: Dir): CSSProperties => {
    if (dir === 'out') return { border: `2px solid ${OUT_COLOR}` };
    if (dir === 'in') return { border: `2px solid ${IN_COLOR}` };
    if (dir === 'both') {
      return {
        borderWidth: 2, borderStyle: 'solid',
        borderTopColor: OUT_COLOR, borderLeftColor: OUT_COLOR,
        borderBottomColor: IN_COLOR, borderRightColor: IN_COLOR,
      };
    }
    return {};
  };
  const dirClass = (dir: Dir): string =>
    dir === 'selected' ? ' selected' : dir === 'dim' ? ' dimmed' : '';

  // ── Arrow overlay ─────────────────────────────────────────────────────────
  // An absolutely-positioned SVG over the columns; we draw one curved arrow per
  // HOP along the transitive chain (outEdges/inEdges), anchored on facing edges
  // so each line travels its inter-column gap. This makes a Profile→Role→file
  // selection render as two connected segments, not one long-range line.
  // Recomputed on selection/graph/scroll/resize.
  const colsRef = useRef<HTMLDivElement | null>(null);
  const itemEls = useRef<Map<string, HTMLElement>>(new Map());
  const [arrows, setArrows] = useState<Array<{ id: string; d: string; dir: 'out' | 'in'; hl?: boolean }>>([]);

  const recomputeArrows = useCallback(() => {
    const cont = colsRef.current;
    // Draw when there's a selection OR a hovered unlink edge to spotlight.
    if (!cont || (selectedIds.size === 0 && !hoverEdge)) { setArrows([]); return; }
    const cb = cont.getBoundingClientRect();
    const box = (el: HTMLElement) => {
      const r = el.getBoundingClientRect();
      return { cx: r.left - cb.left + r.width / 2, y: r.top - cb.top + r.height / 2, left: r.left - cb.left, right: r.right - cb.left };
    };
    const out: Array<{ id: string; d: string; dir: 'out' | 'in'; hl?: boolean }> = [];
    const arrow = (from: HTMLElement, to: HTMLElement, dir: 'out' | 'in', key: string, hl?: boolean) => {
      const a = box(from); const b = box(to);
      const x1 = a.cx <= b.cx ? a.right : a.left;
      const x2 = a.cx <= b.cx ? b.left : b.right;
      const dx = x2 - x1;
      out.push({ id: key, dir, hl, d: `M ${x1} ${a.y} C ${x1 + dx * 0.45} ${a.y} ${x2 - dx * 0.45} ${b.y} ${x2} ${b.y}` });
    };
    // Selection arrows: one per hop; edges are in true graph direction (src → dst).
    if (selectedIds.size > 0) {
      if (showOut) for (const e of outEdges) {
        const s = itemEls.current.get(e.src); const t = itemEls.current.get(e.dst);
        if (s && t) arrow(s, t, 'out', `o:${e.src}:${e.dst}`);
      }
      if (showIn) for (const e of inEdges) {
        const s = itemEls.current.get(e.src); const t = itemEls.current.get(e.dst);
        if (s && t) arrow(s, t, 'in', `i:${e.src}:${e.dst}`);
      }
    }
    // Hovered unlink edge — a bright, thick spotlight on the exact link that
    // clicking would remove (drawn last so it sits on top).
    if (hoverEdge) {
      const s = itemEls.current.get(hoverEdge.src); const t = itemEls.current.get(hoverEdge.dst);
      if (s && t) arrow(s, t, hoverEdge.dir, `hl:${hoverEdge.src}:${hoverEdge.dst}`, true);
    }
    setArrows(out);
  }, [selectedIds, outEdges, inEdges, showOut, showIn, hoverEdge]);

  useLayoutEffect(() => { recomputeArrows(); }, [recomputeArrows, graph]);
  useEffect(() => {
    const cont = colsRef.current;
    if (!cont) return;
    const on = () => recomputeArrows();
    cont.addEventListener('scroll', on, true); // capture: inner column scrolls too
    window.addEventListener('resize', on);
    const ro = new ResizeObserver(on);
    ro.observe(cont);
    return () => { cont.removeEventListener('scroll', on, true); window.removeEventListener('resize', on); ro.disconnect(); };
  }, [recomputeArrows]);

  const renderColumn = (label: string, list: GraphItem[]): JSX.Element => (
    <div className="context-mgr-matrix-col">
      <div className="context-mgr-matrix-col-head">
        <span className="context-mgr-matrix-col-name">{label}</span>
        <span className="context-mgr-group-count">{list.length}</span>
      </div>
      <div className="context-mgr-matrix-col-list">
        {list.length === 0 ? (
          <div className="context-mgr-empty">{'—'}</div>
        ) : list.map((it) => {
          const badge = isBundle(it.kind) ? loaderBadge(it.loader) : null;
          const dangling = danglingSrc.has(it.id);
          const dir = itemDir(it.id);
          const isArmSrc = linkArm === it.id;
          const isArmTarget = !!linkArm && linkArm !== it.id;
          const isHoverEdge = menuHoverId === it.id;
          return (
            <div
              key={it.id}
              ref={(el) => { if (el) itemEls.current.set(it.id, el); else itemEls.current.delete(it.id); }}
              className={`context-mgr-matrix-item${dirClass(dir)}${isArmSrc ? ' link-arm-src' : ''}${isArmTarget ? ' link-arm-target' : ''}${isHoverEdge ? ' link-edge-hover' : ''}`}
              style={{ ...dirBorder(dir), ...overlayStyle(it.id) }}
              onClick={(e) => {
                // While a link is armed, left-click completes it: armed src → this
                // item. Clicking the armed src itself cancels. Otherwise: select.
                if (linkArm) {
                  e.stopPropagation();
                  if (linkArm === it.id) { setLinkArm(null); return; }
                  const src = linkArm; setLinkArm(null);
                  runEdgeOp('link', src, it.id);
                  return;
                }
                toggle(it.id);
              }}
              onContextMenu={(e) => {
                e.preventDefault(); e.stopPropagation();
                setMenu({ x: e.clientX, y: e.clientY, id: it.id });
              }}
              title={it.title || it.name}
            >
              <span className="context-mgr-matrix-item-id" style={{ color: kindLabelColor(it.kind, it.name) }}>{it.kind}:{it.name}</span>
              {badge && <span className="context-mgr-loader-badge" title={badge.label}>{badge.glyph}</span>}
              {dangling && <span className="context-mgr-warn" title="Has a dangling outbound reference">{'⚠'}</span>}
            </div>
          );
        })}
      </div>
    </div>
  );

  if (loading && !graph) return <div className="context-mgr-loading">Loading graph…</div>;
  if (error) return <div className="context-mgr-empty">{error}</div>;

  const selectedLabels = Array.from(selectedIds).map((id) => byId.get(id)?.name ?? id);

  return (
    <div className="context-mgr-matrix">
      <div className="context-mgr-matrix-bar">
        {linkArm ? (
          <div className="context-mgr-linkarm" role="status">
            <span className="context-mgr-linkarm-dot" style={{ background: OUT_COLOR }} />
            <span>Linking from <strong>{nameOf(linkArm)}</strong> — click a target</span>
            <button
              className="sched-mgr-btn sched-mgr-btn-sm"
              onClick={(e) => { e.stopPropagation(); setLinkArm(null); }}
              title="Cancel linking (Esc)"
            >Cancel</button>
          </div>
        ) : (
          <span className="context-mgr-matrix-hint" title="Right-click any item to open its file or add/remove links">
            Right-click an item for actions ▾
          </span>
        )}
        <div className="context-mgr-pill-group">
          <button
            className={`sched-mgr-pill${showOut ? ' active' : ''}`}
            style={showOut ? { color: OUT_COLOR, borderColor: OUT_COLOR } : undefined}
            onClick={() => setShowOut((v) => !v)}
            title="Show outbound (includes) arrows"
          >{'→'} Outbound</button>
          <button
            className={`sched-mgr-pill${showIn ? ' active' : ''}`}
            style={showIn ? { color: IN_COLOR, borderColor: IN_COLOR } : undefined}
            onClick={() => setShowIn((v) => !v)}
            title="Show inbound (included-by) arrows"
          >{'←'} Inbound</button>
          <span className="context-mgr-pill-sep" />
          <button
            className={`sched-mgr-pill${showOrphans ? ' active' : ''}`}
            style={showOrphans ? { color: ORPHAN_COLOR, borderColor: ORPHAN_COLOR } : undefined}
            onClick={() => setShowOrphans((v) => !v)}
            title="Highlight items with no parent (nothing includes them). Excludes top-level global/profile and skills."
          >Orphans</button>
          <button
            className={`sched-mgr-pill${showChildless ? ' active' : ''}`}
            style={showChildless ? { color: CHILDLESS_COLOR, borderColor: CHILDLESS_COLOR } : undefined}
            onClick={() => setShowChildless((v) => !v)}
            title="Highlight items with no children (they include nothing). Excludes context files."
          >Childless</button>
        </div>
        <div className="context-mgr-matrix-summary">
          {hasSelection ? (
            <>
              <span>selected: <strong>{selectedLabels.join(', ')}</strong> — </span>
              <span style={{ color: OUT_COLOR, fontWeight: 600 }}>{'→'} includes</span>
              <span> · </span>
              <span style={{ color: IN_COLOR, fontWeight: 600 }}>included by</span>
              <span className="context-mgr-matrix-dim-note"> · unlinked dimmed</span>
              <button className="context-mgr-matrix-clear" onClick={clearSelection} title="Clear selection">clear</button>
            </>
          ) : (
            <span className="context-mgr-matrix-hint">
              Click an item to see its direct links — arrows to what it includes (cyan) and what
              includes it (orange). Click again to deselect; select several to combine.
            </span>
          )}
        </div>
      </div>
      <div className="context-mgr-matrix-cols" ref={colsRef} style={{ position: 'relative' }}>
        <svg
          className="context-mgr-matrix-arrows"
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', pointerEvents: 'none', overflow: 'hidden', zIndex: 4 }}
        >
          <defs>
            <marker id="ctxarrow-out" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto" markerUnits="userSpaceOnUse">
              <path d="M0,0 L7,3 L0,6 Z" fill={OUT_COLOR} />
            </marker>
            <marker id="ctxarrow-in" markerWidth="9" markerHeight="9" refX="7" refY="3" orient="auto" markerUnits="userSpaceOnUse">
              <path d="M0,0 L7,3 L0,6 Z" fill={IN_COLOR} />
            </marker>
            <marker id="ctxarrow-hl" markerWidth="12" markerHeight="12" refX="8" refY="4" orient="auto" markerUnits="userSpaceOnUse">
              <path d="M0,0 L9,4 L0,8 Z" fill={ORPHAN_COLOR} />
            </marker>
          </defs>
          {arrows.map((a) => (
            <path
              key={a.id}
              d={a.d}
              fill="none"
              stroke={a.hl ? ORPHAN_COLOR : (a.dir === 'out' ? OUT_COLOR : IN_COLOR)}
              strokeWidth={a.hl ? 3.5 : 1.5}
              opacity={a.hl ? 1 : (hoverEdge ? 0.25 : 0.8)}
              markerEnd={a.hl ? 'url(#ctxarrow-hl)' : `url(#ctxarrow-${a.dir})`}
            />
          ))}
        </svg>
        {renderColumn('Profiles', columns.profiles)}
        {renderColumn('Roles', columns.roles)}
        {renderColumn('Sub-roles', columns.subroles)}
        {renderColumn('Context Files', columns.context)}
      </div>
      {menu && (() => {
        const item = byId.get(menu.id);
        if (!item) return null;
        const canBeSrc = isBundle(item.kind);
        const touching = edgesTouching(menu.id);
        // Only offer to remove links that are CURRENTLY SHOWING — i.e. respect
        // the Outbound/Inbound direction toggles, so the menu matches the arrows.
        const outs = showOut ? touching.outs : [];
        const ins = showIn ? touching.ins : [];
        const armActive = !!linkArm && linkArm !== menu.id;
        // Keep the menu on-screen (simple right/bottom clamp).
        const style: CSSProperties = {
          position: 'fixed',
          left: Math.min(menu.x, window.innerWidth - 240),
          top: Math.min(menu.y, window.innerHeight - 320),
          zIndex: 50,
        };
        const act = (fn: () => void) => (e: React.MouseEvent) => { e.stopPropagation(); setMenu(null); fn(); };
        return (
          <div className="context-mgr-ctx-menu" style={style} onClick={(e) => e.stopPropagation()}>
            <div className="context-mgr-ctx-title" title={menu.id}>{item.kind}:{item.name}</div>
            <button className="context-mgr-ctx-item" onClick={act(() => onPeek(menu.id))}>Peek</button>
            <button className="context-mgr-ctx-item" onClick={act(() => openItem(menu.id))}>Open file</button>
            <button className="context-mgr-ctx-item" onClick={act(() => toggle(menu.id))}>
              {selectedIds.has(menu.id) ? 'Deselect' : 'Select'}
            </button>
            <div className="context-mgr-ctx-sep" />
            {armActive ? (
              <button className="context-mgr-ctx-item" disabled={busy}
                onClick={act(() => { const s = linkArm!; setLinkArm(null); runEdgeOp('link', s, menu.id); })}>
                Link <strong>{nameOf(linkArm!)}</strong> → here
              </button>
            ) : linkArm === menu.id ? (
              <button className="context-mgr-ctx-item" onClick={act(() => setLinkArm(null))}>Cancel linking</button>
            ) : canBeSrc ? (
              <button className="context-mgr-ctx-item" onClick={act(() => setLinkArm(menu.id))}>Link from here…</button>
            ) : (
              <div className="context-mgr-ctx-note">Only bundles (profile/role/skill/global) can start a link.</div>
            )}
            {(outs.length > 0 || ins.length > 0) && <div className="context-mgr-ctx-sep" />}
            {outs.map((dst) => (
              <button key={`o:${dst}`} className="context-mgr-ctx-item context-mgr-ctx-remove" disabled={busy}
                onClick={act(() => runEdgeOp('unlink', menu.id, dst))}
                onMouseEnter={() => { setMenuHoverId(dst); setHoverEdge({ src: menu.id, dst, dir: 'out' }); }}
                onMouseLeave={() => { setMenuHoverId(null); setHoverEdge(null); }}
                title={`Remove reference ${menu.id} → ${dst}`}>
                ✕ Unlink → {nameOf(dst)}
              </button>
            ))}
            {ins.map((src) => (
              <button key={`i:${src}`} className="context-mgr-ctx-item context-mgr-ctx-remove" disabled={busy}
                onClick={act(() => runEdgeOp('unlink', src, menu.id))}
                onMouseEnter={() => { setMenuHoverId(src); setHoverEdge({ src, dst: menu.id, dir: 'in' }); }}
                onMouseLeave={() => { setMenuHoverId(null); setHoverEdge(null); }}
                title={`Remove reference ${src} → ${menu.id}`}>
                ✕ Unlink {nameOf(src)} →
              </button>
            ))}
          </div>
        );
      })()}
    </div>
  );
}

// ---- Focus sub-views -------------------------------------------------------

function LinksView({ selectedId, refs, onSelect, onPeek }: {
  selectedId: string;
  refs: RefEdge[];
  onSelect: (id: string) => void;
  onPeek: (id: string) => void;
}): JSX.Element {
  const outbound = refs.filter((e) => e.src_id === selectedId).sort((a, b) => a.order_idx - b.order_idx);
  const inbound = refs.filter((e) => e.dst_id === selectedId).sort((a, b) => a.order_idx - b.order_idx);

  const row = (id: string, resolved: boolean) => (
    <div key={id} className="context-mgr-link-row">
      <button className="context-mgr-peek-btn" onClick={() => onPeek(id)} title="Preview in Peek drawer">[peek]</button>
      <span className="context-mgr-link-id" onClick={() => onSelect(id)} title="Open in Focus">{id}</span>
      {!resolved && <span className="context-mgr-warn" title="Dangling reference (target not found)">{'⚠'}</span>}
      {/* Phase 2: [− remove] / reorder controls render here. */}
    </div>
  );

  return (
    <div className="context-mgr-links">
      <div className="context-mgr-link-group">
        <div className="context-mgr-link-group-head">
          <span title="Files THIS one references — it pulls them in">{'→'} Includes <span style={{ color: 'var(--text-muted)' }}>(outbound)</span></span>
          <span className="context-mgr-group-count">{outbound.length}</span>
          {/* Phase 2: [+ Add reference] button home. */}
        </div>
        {outbound.length === 0 ? <div className="context-mgr-empty">Includes nothing.</div>
          : outbound.map((e) => row(e.dst_id, e.resolved))}
      </div>
      <div className="context-mgr-link-group">
        <div className="context-mgr-link-group-head">
          <span title="Files that reference THIS one — they pull it in">{'←'} Included by <span style={{ color: 'var(--text-muted)' }}>(inbound)</span></span>
          <span className="context-mgr-group-count">{inbound.length}</span>
        </div>
        {inbound.length === 0 ? <div className="context-mgr-empty">Included by nothing.</div>
          : inbound.map((e) => row(e.src_id, e.resolved))}
      </div>
    </div>
  );
}

function LoadsView({ loads, onSelect, onPeek }: {
  loads: ResolveResult | null;
  onSelect: (id: string) => void;
  onPeek: (id: string) => void;
}): JSX.Element {
  if (!loads) return <div className="context-mgr-empty">{'—'}</div>;
  const leaves = loads.resolved ?? [];
  const unresolved = loads.unresolved ?? [];
  return (
    <div className="context-mgr-loads">
      <div className="context-mgr-loads-summary">
        {leaves.length} leaf context file{leaves.length === 1 ? '' : 's'} · {fmtBytes(loads.total_size_bytes)}
        {unresolved.length > 0 && (
          <span className="context-mgr-health-warn"> · {unresolved.length} unresolved</span>
        )}
      </div>
      {leaves.map((leaf) => {
        const count = leaf.count ?? leaf.via?.length ?? 1;
        const tip = (leaf.via ?? []).map((chain) => chain.join(' → ')).join('  ·  ');
        const [lk, ...lrest] = leaf.id.split(':');
        return (
          <div key={leaf.id} className="context-mgr-load-row context-mgr-load-row-col">
            <div className="context-mgr-load-row-head">
              <button className="context-mgr-peek-btn" onClick={() => onPeek(leaf.id)} title="Preview in Peek drawer">[peek]</button>
              <span className="context-mgr-link-id" onClick={() => onSelect(leaf.id)} title="Open in Focus"
                style={{ color: kindLabelColor(lk, lrest.join(':')) }}>{leaf.id}</span>
              {count > 1 && <span className="context-mgr-dup-badge" title={tip}>{'×'}{count}</span>}
            </div>
            {leaf.path && (
              <span className="context-mgr-load-path" title={absPathOf(leaf.path) ?? leaf.path}>{leaf.path}</span>
            )}
          </div>
        );
      })}
      {unresolved.length > 0 && (
        <div className="context-mgr-load-unresolved">
          <div className="context-mgr-link-group-head"><span>Unresolved</span><span className="context-mgr-group-count">{unresolved.length}</span></div>
          {unresolved.map((id) => (
            <div key={id} className="context-mgr-load-row">
              <span className="context-mgr-link-id context-mgr-link-dangling">{id}</span>
              <span className="context-mgr-warn" title="Referenced but not found">{'⚠'}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function InfoView({ meta }: { meta: CtxMeta | null }): JSX.Element {
  if (!meta) return <div className="context-mgr-empty">No metadata.</div>;
  const badge = isBundle(meta.kind) ? loaderBadge(meta.loader) : null;
  const rows: Array<[string, ReactNode]> = [
    ['Kind', meta.kind],
    ['Loader', meta.loader ? <>{badge ? `${badge.glyph} ` : ''}{meta.loader}</> : '—'],
    ['Path', meta.path || '—'],
    ['Size', fmtBytes(meta.size_bytes)],
    ['Updated', fmtTime(meta.updated_at)],
    ['Created', fmtTime(meta.created_at)],
    ['Scope', meta.scope || '—'],
    ['Status', meta.status || '—'],
  ];
  if (meta.counts) rows.push(['Refs', `${meta.counts.outbound} includes · ${meta.counts.inbound} included-by`]);

  // The engine returns `provenance` as a parsed object (or null), never a raw
  // JSON string. Pretty-print the object for display; rendering a raw object as
  // a React child would crash the pane (React #31), so always stringify first.
  let provenance: string | null = null;
  const pj: unknown = meta.provenance;
  if (pj != null) {
    try { provenance = JSON.stringify(pj, null, 2); }
    catch { provenance = String(pj); }
  }

  return (
    <div className="context-mgr-info">
      {meta.summary && <p className="context-mgr-info-summary">{meta.summary}</p>}
      {rows.map(([label, val]) => (
        <div key={label} className="context-mgr-info-row">
          <span className="context-mgr-info-label">{label}</span>
          <span className="context-mgr-info-val">{val}</span>
        </div>
      ))}
      {provenance && (
        <div className="context-mgr-info-prov">
          <div className="context-mgr-info-label">Provenance</div>
          <pre className="context-mgr-info-prov-pre">{provenance}</pre>
        </div>
      )}
      {/* Phase 2: History (changelog) section renders here once writes land. */}
    </div>
  );
}

// ---- Validate tab ----------------------------------------------------------

/** Severity rank for sorting orphans: warn first, then low/expected. */
const SEVERITY_RANK: Record<string, number> = { warn: 0, high: 0, medium: 1, low: 2, info: 3 };

function ValidateView({ result, loading, onSelect }: {
  result: ValidateResult | null;
  loading: boolean;
  onSelect: (id: string) => void;
}): JSX.Element {
  const orphanGroups = useMemo(() => {
    const groups: Record<string, ValidateResult['orphans']> = {};
    for (const o of result?.orphans ?? []) (groups[o.severity] ??= []).push(o);
    return Object.entries(groups).sort(([a], [b]) => (SEVERITY_RANK[a] ?? 9) - (SEVERITY_RANK[b] ?? 9));
  }, [result]);

  const [collapsedSev, setCollapsedSev] = useState<Set<string>>(new Set(['low', 'info']));
  const toggleSev = (s: string) => setCollapsedSev((prev) => {
    const next = new Set(prev); if (next.has(s)) next.delete(s); else next.add(s); return next;
  });

  if (loading && !result) return <div className="context-mgr-loading">Validating…</div>;
  if (!result) return <div className="context-mgr-empty">No validation data.</div>;

  return (
    <div className="context-mgr-validate">
      <div className="context-mgr-validate-card">
        <h4 className="context-mgr-validate-h">Dangling references ({result.dangling.length})</h4>
        {result.dangling.length === 0 ? <div className="context-mgr-empty">None — all references resolve.</div> : (
          <div className="context-mgr-validate-list">
            {result.dangling.map((d, i) => (
              <div key={i} className="context-mgr-validate-row">
                <span className="context-mgr-link-id" onClick={() => onSelect(d.src_id)} title="Open the source in Library">{d.src_id}</span>
                <span className="context-mgr-arrow">{'→'}</span>
                <span className="context-mgr-link-dangling">{d.dst_id}</span>
                <span className="context-mgr-warn">{'⚠'}</span>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="context-mgr-validate-card">
        <h4 className="context-mgr-validate-h">Orphans ({result.orphans.length})</h4>
        <div className="context-mgr-validate-hint">Items with no inbound references. Briefs are expected orphans (low severity).</div>
        {orphanGroups.map(([sev, list]) => {
          const deemph = sev === 'low' || sev === 'info';
          const collapsed = collapsedSev.has(sev);
          return (
            <div key={sev} className={`context-mgr-orphan-group${deemph ? ' deemph' : ''}`}>
              <div className="context-mgr-group-header" onClick={() => toggleSev(sev)}>
                <span className="context-mgr-collapse">{collapsed ? '▶' : '▼'}</span>
                <span className={`context-mgr-sev context-mgr-sev-${sev}`}>{sev}</span>
                <span className="context-mgr-group-count">{list.length}</span>
              </div>
              {!collapsed && (
                <div className="context-mgr-group-items">
                  {list.map((o) => (
                    <div key={o.id} className="context-mgr-validate-row">
                      <span className="context-mgr-link-id" onClick={() => onSelect(o.id)} title="Open in Library">{o.id}</span>
                      <span className="context-mgr-orphan-kind">{o.kind}</span>
                    </div>
                  ))}
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
