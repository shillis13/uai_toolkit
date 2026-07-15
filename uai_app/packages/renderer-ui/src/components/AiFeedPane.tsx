/**
 * AiFeedPane — the AI awareness feed (ai_comms/feed/activity.jsonl) as a singleton
 * app tab. Each entry is one session's ambient status post. Spruced up vs. the raw
 * terminal feed: sessions rendered in their platform color, a status dot, a rich
 * tooltip on the name, kind badges, text filtering, and clickable session names
 * that open that session's tab.
 */

import { useState, useEffect, useMemo, useCallback } from 'react';
import { useSessionStore } from '../stores';
import { executeCommand } from '../utils/execute-command';
import TabFrame from './TabFrame';
import { LinkifyRefs } from './RefLink';

// Platform → accent color (matches Recent Sessions / Tab Manager).
const PLATFORM_COLORS: Record<string, string> = {
  claude_cli: 'var(--accent-orange)',
  codex_cli: 'var(--accent-purple)',
  gemini_cli: 'var(--accent-cyan)',
};

// Derived from the bridge so we don't depend on the (non-ambient) global type.
type FeedEntry = Awaited<ReturnType<typeof window.uai.aiFeed.read>>[number];

function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (isNaN(d.getTime())) return iso;
  return d.toLocaleString(undefined, { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' });
}

// A first→last span for a collapsed group. Shares the date when both are the
// same day (e.g. "Jul 5, 04:39 PM–11:49 PM"); shows both dates otherwise.
function fmtSpan(first: string, last: string): string {
  if (first === last) return fmtTime(first);
  const a = new Date(first), b = new Date(last);
  if (isNaN(a.getTime()) || isNaN(b.getTime())) return `${fmtTime(first)}–${fmtTime(last)}`;
  const sameDay = a.toDateString() === b.toDateString();
  const hm = (d: Date) => d.toLocaleString(undefined, { hour: '2-digit', minute: '2-digit' });
  return sameDay ? `${fmtTime(first)}–${hm(b)}` : `${fmtTime(first)}–${fmtTime(last)}`;
}

export default function AiFeedPane(): JSX.Element {
  const { getSession } = useSessionStore();
  const [entries, setEntries] = useState<FeedEntry[] | null>(null);
  const [filter, setFilter] = useState('');
  const [kindFilter, setKindFilter] = useState<'all' | 'report' | 'event'>('all');

  const load = useCallback(async () => {
    try { setEntries(await window.uai.aiFeed.read(400)); } catch { setEntries([]); }
  }, []);
  useEffect(() => {
    load();
    const iv = setInterval(load, 5000);  // live-ish; feed is append-only
    return () => clearInterval(iv);
  }, [load]);

  const filtered = useMemo(() => {
    const q = filter.trim().toLowerCase();
    return (entries ?? []).filter(e => {
      if (kindFilter !== 'all' && e.kind !== kindFilter) return false;
      if (!q) return true;
      return (e.name?.toLowerCase().includes(q)) || (e.text?.toLowerCase().includes(q));
    });
  }, [entries, filter, kindFilter]);

  // Collapse repeated identical events (same session + kind + text) into one row
  // with a count and a first→last span — mirrors the injected-block renderer
  // (feed_lib.render_block). Unique-text reports never collapse; only the
  // repetitive auto-floor events (started/resumed/compacted) do. `filtered` is
  // newest-first; groups keep that order (by most-recent occurrence).
  const grouped = useMemo(() => {
    const map = new Map<string, { e: FeedEntry; count: number; first: string; last: string }>();
    const order: string[] = [];
    for (const e of filtered) {
      const key = `${e.session}\u0000${e.kind}\u0000${e.text}`;
      let g = map.get(key);
      if (!g) { g = { e, count: 0, first: e.ts, last: e.ts }; map.set(key, g); order.push(key); }
      g.count++;
      if (e.ts < g.first) g.first = e.ts;
      if (e.ts > g.last) g.last = e.ts;
    }
    return order
      .map(k => map.get(k)!)
      .sort((a, b) => (a.last < b.last ? 1 : a.last > b.last ? -1 : 0)); // newest-first
  }, [filtered]);

  const openSession = (trackingId: string, name: string) =>
    executeCommand('workspace.tabs.open', { type: 'session', targetId: trackingId, label: name });

  if (entries === null) return <div className="ai-feed-empty">Loading feed…</div>;

  return (
    <TabFrame
      title="AI Feed"
      headerExtra={<>
        <input
          className="ai-feed-filter"
          placeholder="Filter by session or text…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
        />
        <div className="ai-feed-kinds">
          {(['all', 'report', 'event'] as const).map(k => (
            <button key={k} className={`ai-feed-kind${kindFilter === k ? ' active' : ''}`} onClick={() => setKindFilter(k)}>{k}</button>
          ))}
        </div>
      </>}
      actions={<span className="ai-feed-count" title="Matching entries">{filtered.length}</span>}
    >
      <div className="ai-feed-list">
        {filtered.length === 0 && <div className="ai-feed-empty">No matching entries.</div>}
        {grouped.map((g, i) => {
          const e = g.e;
          const s = getSession(e.session);
          const color = (s?.platform && PLATFORM_COLORS[s.platform]) || 'var(--text-sec)';
          const running = s?.process_status === 'running';
          const when = g.count > 1 ? fmtSpan(g.first, g.last) : fmtTime(e.ts);
          const tip = [
            e.name,
            s?.platform ? `platform: ${s.platform}` : null,
            `id: ${e.session}`,
            s ? (running ? 'running' : 'stopped') : 'not in session store',
            g.count > 1 ? `${g.count}× between ${fmtTime(g.first)} and ${fmtTime(g.last)}` : fmtTime(e.ts),
          ].filter(Boolean).join('\n');
          return (
            <div key={i} className="ai-feed-row">
              <span className="ai-feed-time" title={when}>{when}</span>
              <button
                className="ai-feed-name"
                style={{ color }}
                title={tip}
                onClick={() => { if (s) openSession(e.session, e.name); }}
                disabled={!s}
              >
                {s && <span className={`ai-feed-dot ${running ? 'running' : 'stopped'}`} />}
                {e.name || 'unknown'}
              </button>
              {e.kind === 'event' && <span className="ai-feed-badge">event</span>}
              {g.count > 1 && <span className="ai-feed-badge" title="combined identical entries">×{g.count}</span>}
              <span className="ai-feed-text"><LinkifyRefs text={e.text} /></span>
            </div>
          );
        })}
      </div>
    </TabFrame>
  );
}
