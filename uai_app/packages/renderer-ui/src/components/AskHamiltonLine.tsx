/**
 * AskHamiltonLine — the always-on bottom-right capture cluster (todo_0340).
 *
 * NOTE ON NAMING: this file still hosts the "Ask Hamilton" pill, but now also
 * hosts the ubiquitous "Add Note" pill beside it — the two are one primitive
 * (a Note; recipient differs). Kept the filename to avoid churning App.tsx
 * (which mounts it) while another session actively edits that file; a rename to
 * something like QuickCaptureBar is a trivial future cleanup.
 *
 * Two always-present affordances, bottom-right, on every view:
 *   ＋ Add Note  → NoteDialog mode='note'         (recipient defaults to PM)
 *   ⚚ Ask Hamilton → NoteDialog mode='ask-hamilton' (recipient defaults Hamilton),
 *                    with an `N ⚑` counter of items needing PianoMan.
 *
 * Three tiers were specced for Ask Hamilton; only Tier 1 (this pill + capture)
 * is built. Tier 2 (floating chat to comms endpoint 'hamilton', where a snapshot
 * attaches) and Tier 3 (navigate to Hamilton's session page) remain TODO stubs.
 *
 * The counter N reuses the work.landscape model (same source the Live Board
 * "Needs PianoMan" list uses) and counts rows flagged needs_pianoman.
 *
 * Mounted once, globally, from App.tsx. Dark theme, inline styles (matching
 * LiveBoardPane): Add Note is cool/neutral, Ask Hamilton warm/orange.
 */

import { useState, useEffect, useCallback } from 'react';
import { executeCommand } from '../utils/execute-command';
import NoteDialog from './NoteDialog';

// Minimal shape of the work.landscape model — only what the counter needs.
interface LandAssessment {
  needs_pianoman?: boolean;
}
interface LandRow {
  activity_state?: string;
  assessment?: LandAssessment | null;
}
interface LandscapeModel {
  rows?: LandRow[];
}

type CaptureMode = 'note' | 'ask-hamilton';

const NEEDS_STATES = new Set(['blocked', 'permission_prompt']);

function rowNeedsPianoman(r: LandRow): boolean {
  if (r.assessment?.needs_pianoman) return true;
  return NEEDS_STATES.has(r.activity_state || '');
}

export default function AskHamiltonLine({ inline = false }: { inline?: boolean } = {}): JSX.Element {
  // `inline` = embedded in the footer bar (compact, no fixed positioning);
  // default = the floating bottom-right cluster.
  const pad = inline ? '2px 9px' : '7px 13px';
  const fs = inline ? 11.5 : 12.5;
  const bw = inline ? 1 : 2;
  // null = closed; otherwise the mode the dialog was opened in.
  const [openMode, setOpenMode] = useState<CaptureMode | null>(null);
  const [needsCount, setNeedsCount] = useState(0);

  const refreshCount = useCallback(async () => {
    const res = await executeCommand<{ model: LandscapeModel }>('work.landscape', {}, { onFailure: 'silent' });
    if (res.ok && res.data?.model?.rows) {
      setNeedsCount(res.data.model.rows.filter(rowNeedsPianoman).length);
    }
  }, []);

  useEffect(() => {
    refreshCount();
    // Light periodic refresh so the counter stays roughly live. work.landscape
    // is read-only; a 60s cadence keeps it cheap.
    const t = setInterval(refreshCount, 60000);
    return () => clearInterval(t);
  }, [refreshCount]);

  // Global shortcuts to OPEN the capture dialogs from anywhere:
  //   ⌘/Ctrl+Shift+N → Add Note   ·   ⌘/Ctrl+Shift+H → Ask Hamilton
  // (This component is always mounted in the footer, so the listener is global.)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || !e.shiftKey) return;
      const k = e.key.toLowerCase();
      if (k === 'n') { e.preventDefault(); setOpenMode('note'); }
      else if (k === 'h') { e.preventDefault(); setOpenMode('ask-hamilton'); }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, []);

  // TODO (Tier 2): a floating chat panel to comms endpoint 'hamilton' with a
  // snapshot attach. Stubbed for now — only Tier 1 capture is wired.
  // TODO (Tier 3): navigate to Hamilton's session page.

  return (
    <>
      <div
        style={inline
          ? { display: 'inline-flex', alignItems: 'center', gap: 6 }
          : { position: 'fixed', right: 110, bottom: 18, zIndex: 10500, display: 'flex', alignItems: 'center', gap: 8 }}
      >
        {/* ── Add Note (ubiquitous, cool/neutral) ── */}
        <button
          onClick={() => setOpenMode('note')}
          title="Add Note (⌘⇧N)"
          style={{
            display: 'flex', alignItems: 'center', gap: 6,
            background: 'var(--bg-panel)',
            border: `${bw}px solid var(--accent-blue)`,
            color: 'var(--text)',
            borderRadius: 999,
            padding: pad,
            fontSize: fs, fontWeight: 600,
            cursor: 'pointer',
            boxShadow: inline ? 'none' : '0 6px 18px rgba(0,0,0,0.4)',
          }}
        >
          <span style={{ color: 'var(--accent-blue)', fontWeight: 700 }}>{'＋'}</span>
          <span>Add Note</span>
        </button>

        {/* ── Ask Hamilton (warm/orange, with needs-you counter) ── */}
        <button
          onClick={() => setOpenMode('ask-hamilton')}
          title="Ask Hamilton (⌘⇧H)"
          style={{
            display: 'flex', alignItems: 'center', gap: 7,
            background: 'var(--attention-bg)',
            border: `${bw}px solid var(--accent-orange)`,
            color: 'var(--accent-orange)',
            borderRadius: 999,
            padding: pad,
            fontSize: fs, fontWeight: 600,
            cursor: 'pointer',
            boxShadow: inline ? 'none' : '0 6px 18px rgba(0,0,0,0.4)',
          }}
        >
          <span style={{ color: 'var(--accent-orange)' }}>{'⚚'}</span>
          <span>Ask Hamilton{'…'}</span>
          {needsCount > 0 && (
            <span
              style={{
                marginLeft: 2,
                background: 'var(--attention-badge-bg)',
                border: '1px solid var(--attention-badge-border)',
                color: 'var(--accent-orange)',
                borderRadius: 999,
                padding: '1px 8px',
                fontSize: 11, fontWeight: 700,
              }}
              title={`${needsCount} item(s) need PianoMan`}
            >
              {needsCount} {'⚑'}
            </span>
          )}
        </button>
      </div>

      <NoteDialog
        isOpen={openMode !== null}
        onClose={() => setOpenMode(null)}
        mode={openMode ?? 'note'}
        sourceTab={openMode ?? 'note'}
        onCreated={() => {
          // A fresh ask/note may shift the needs count; refresh.
          refreshCount();
        }}
      />
    </>
  );
}
