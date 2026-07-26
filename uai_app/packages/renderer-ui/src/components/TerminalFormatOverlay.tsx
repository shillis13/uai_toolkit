/**
 * TerminalFormatOverlay — Formatted view of tmux scrollback.
 *
 * Opaque panel covers message content. It is full-height while idle and yields
 * the real terminal rows from an active verb downward. Transcript records own
 * settled cards; the terminal scrape supplies formatted provisional cards.
 *
 * Mouse: overlay captures all mouse events (scroll, selection).
 * Keyboard: all keys pass through to terminal except Cmd+C (copies from overlay).
 * Security: all text rendered via textContent.
 */

import { useEffect, useCallback, useRef, useState } from 'react';
import { useViewport } from '../viewport';
import type { Terminal } from 'xterm';
import { dedupConsecutiveBlocks } from './memorex-dedup';
import {
  appendUniqueProvisionalCards,
  applyTerminalToolViews,
  buildSettledTranscriptBlocks,
  calculateVirtualWindow,
  collectTerminalToolViews,
  flattenStructuredTranscript,
  settleProvisionalCards,
  terminalCardDelta,
  type SettledTranscriptBlock,
} from './memorex-transcript';
import { focusTodoInWorkMgr, focusNoteInNotesMgr, todoTooltip, noteTooltip, ensureRefIndexLoaded } from './RefLink';

// Claude CLI markers
const R = '\u23FA';  // ⏺ response/tool
const P = '\u276F';  // ❯ prompt
const T = '\u2234';  // ∴ thinking (THEREFORE symbol)
const COMPLETION = '\u273B';   // ✻ completion marker

// Codex CLI markers
const CODEX_TOOL = '\u2022';   // • tool call
const CODEX_PROMPT = '\u203A'; // › user prompt

// Gemini CLI markers
const GEMINI_RESPONSE = '\u2726';  // ✦ assistant response
const GEMINI_TOOL_TOP = '\u256D';  // ╭ tool box top border
const GEMINI_TOOL_BOT = '\u2570';  // ╰ tool box bottom border
const GEMINI_INFO = '\u2139';      // ℹ info/cancel status

// ANSI SGR parsing
const ANSI_RE = /\x1b\[([0-9;]*)m/g;

// Standard 16-color palette (matches Tokyo Night theme)
const FG16: Record<number, string> = {
  30: '#15161e', 31: '#f7768e', 32: '#9ece6a', 33: '#e0af68',
  34: '#7aa2f7', 35: '#bb9af7', 36: '#7dcfff', 37: '#a9b1d6',
  90: '#414868', 91: '#f7768e', 92: '#9ece6a', 93: '#e0af68',
  94: '#7aa2f7', 95: '#bb9af7', 96: '#7dcfff', 97: '#c0caf5',
};

const BG16: Record<number, string> = {
  40: '#15161e', 41: '#f7768e', 42: '#9ece6a', 43: '#e0af68',
  44: '#7aa2f7', 45: '#bb9af7', 46: '#7dcfff', 47: '#a9b1d6',
  100: '#414868', 101: '#f7768e', 102: '#9ece6a', 103: '#e0af68',
  104: '#7aa2f7', 105: '#bb9af7', 106: '#7dcfff', 107: '#c0caf5',
};

// 256-color palette: 0-7 standard, 8-15 bright, 16-231 color cube, 232-255 grayscale
function color256(n: number): string {
  if (n < 8) return Object.values(FG16)[n] || '#c0caf5';
  if (n < 16) return Object.values(FG16)[n - 8 + 8] || '#c0caf5';  // bright
  if (n < 232) {
    // 6x6x6 color cube
    const idx = n - 16;
    const r = Math.floor(idx / 36) * 51;
    const g = Math.floor((idx % 36) / 6) * 51;
    const b = (idx % 6) * 51;
    return `rgb(${r},${g},${b})`;
  }
  // Grayscale ramp
  const gray = (n - 232) * 10 + 8;
  return `rgb(${gray},${gray},${gray})`;
}

/** Remove ANSI *noise* that must never reach the renderer but carries no color
 *  information: OSC sequences (hyperlinks — the visible text is kept) and bare
 *  CSI-SGR codes whose ESC byte was dropped upstream. The latter leak into the
 *  overlay as literal "[38;5;116m" text (e.g. tmux session badges). ESC-prefixed
 *  SGR is deliberately preserved — renderAnsiLine needs it to colorize. */
function stripNoise(s: string): string {
  return s
    .replace(/\x1b\][0-9]*;[^\x07\x1b]*(?:\x07|\x1b\\)/g, '') // OSC (hyperlinks): keep visible text
    .replace(/\x1b[\]\\]/g, '')                              // stray OSC opener / ST remnants
    .replace(/(?<!\x1b)\[[0-9;]+m/g, '');                    // bare CSI-SGR (no ESC byte)
}

function stripAnsi(s: string): string {
  // Full plain-text clean: drop noise (OSC + bare CSI), then ESC-prefixed SGR.
  return stripNoise(s).replace(/\x1b\[[0-9;]*m/g, '');
}

/** Pattern for URLs and file paths that should become clickable links */
const LINK_RE = /(?:https?:\/\/[^\s<>'")\]]+)|(?:\/(?:Users|home|tmp|var|opt|etc|usr)[^\s<>'")\]]*)|(?:~\/[^\s<>'")\]]+)|(?:\.\/[^\s<>'")\]]+)/g;

/** Replace URL/path matches in a text node with clickable link spans */
function linkifyElement(parent: HTMLElement): void {
  // Collect all text nodes, including those inside ANSI-colored spans
  const textNodes: Text[] = [];
  const walk = (el: Node) => {
    for (const child of Array.from(el.childNodes)) {
      if (child.nodeType === Node.TEXT_NODE && child.textContent) {
        textNodes.push(child as Text);
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        walk(child);
      }
    }
  };
  walk(parent);

  for (const node of textNodes) {
    if (!node.textContent) continue;
    const text = node.textContent;
    LINK_RE.lastIndex = 0;
    let match: RegExpExecArray | null;
    const fragments: (string | { url: string })[] = [];
    let lastEnd = 0;

    while ((match = LINK_RE.exec(text)) !== null) {
      if (match.index > lastEnd) fragments.push(text.slice(lastEnd, match.index));
      fragments.push({ url: match[0] });
      lastEnd = match.index + match[0].length;
    }

    if (fragments.length === 0) continue;
    if (lastEnd < text.length) fragments.push(text.slice(lastEnd));

    const frag = document.createDocumentFragment();
    for (const f of fragments) {
      if (typeof f === 'string') {
        frag.appendChild(document.createTextNode(f));
      } else {
        const link = document.createElement('span');
        link.textContent = f.url;
        link.style.cssText = 'text-decoration:underline;text-decoration-style:dotted;cursor:pointer;';
        link.title = 'Cmd+click: open | Shift+click: copy';
        link.addEventListener('mousedown', (e) => {
          if (e.metaKey || e.shiftKey) {
            e.preventDefault();
            e.stopPropagation();
          }
        });
        link.addEventListener('click', (e) => {
          if (e.metaKey) {
            e.preventDefault();
            e.stopPropagation();
            if (f.url.startsWith('http')) {
              window.uai.openUrl(f.url);
            } else {
              window.uai.openPath(f.url);
            }
          } else if (e.shiftKey) {
            e.preventDefault();
            e.stopPropagation();
            navigator.clipboard.writeText(f.url);
          }
        });
        frag.appendChild(link);
      }
    }
    node.parentNode?.replaceChild(frag, node);
  }
}

// Matches todo_#### / note_#### references in terminal text.
const REF_RE = /todo_\d+|note_\d+/g;

/** Replace todo_/note_ references in a text node with clickable ref spans that
 *  open Work Mgr / Notes Mgr (RefLink), with a name/status/assignee tooltip.
 *  A separate pass from linkifyElement (URLs) — same text-node replacement shape,
 *  independent of the settled-region/cover detection so it can't cause blanking. */
function linkifyRefsInElement(parent: HTMLElement): void {
  ensureRefIndexLoaded();
  const textNodes: Text[] = [];
  const walk = (el: Node) => {
    for (const child of Array.from(el.childNodes)) {
      if (child.nodeType === Node.TEXT_NODE && child.textContent) {
        textNodes.push(child as Text);
      } else if (child.nodeType === Node.ELEMENT_NODE) {
        // Don't descend into already-linkified spans (URL or ref).
        const el2 = child as HTMLElement;
        if (!el2.dataset.reflink) walk(child);
      }
    }
  };
  walk(parent);

  for (const node of textNodes) {
    if (!node.textContent) continue;
    const text = node.textContent;
    const matches = [...text.matchAll(REF_RE)];
    if (matches.length === 0) continue;

    const frag = document.createDocumentFragment();
    let lastEnd = 0;
    for (const m of matches) {
      const start = m.index ?? 0;
      if (start > lastEnd) frag.appendChild(document.createTextNode(text.slice(lastEnd, start)));
      const ref = m[0];
      const isTodo = ref.startsWith('todo_');
      const span = document.createElement('span');
      span.textContent = ref;
      span.dataset.reflink = '1';
      span.style.cssText = `text-decoration:underline;text-decoration-style:dotted;cursor:pointer;color:var(${isTodo ? '--accent-blue' : '--accent-orange'});`;
      const setTitle = () => { span.title = isTodo ? todoTooltip(ref) : noteTooltip(ref); };
      setTitle();
      // The metadata index loads async; the imperative span never re-renders, so
      // refresh the tooltip on hover — by then the index is populated.
      span.addEventListener('mouseenter', setTitle);
      span.addEventListener('click', (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        if (isTodo) focusTodoInWorkMgr(ref); else focusNoteInNotesMgr(ref);
      });
      frag.appendChild(span);
      lastEnd = start + ref.length;
    }
    if (lastEnd < text.length) frag.appendChild(document.createTextNode(text.slice(lastEnd)));
    node.parentNode?.replaceChild(frag, node);
  }
}

/** Render a line with ANSI colors (fg, bg, bold, dim, italic, underline) */
function renderAnsiLine(raw: string, parent: HTMLDivElement, defaultColor: string): void {
  ANSI_RE.lastIndex = 0;
  let lastIdx = 0;
  let fg = defaultColor;
  let bg: string | undefined;
  let bold = false;
  let dim = false;
  let italic = false;
  let underline = false;
  let strikethrough = false;
  let hasEsc = false;
  let match: RegExpExecArray | null;

  const emitSpan = (text: string) => {
    if (!text) return;
    const span = document.createElement('span');
    // Trim trailing spaces from spans with background to prevent highlight stretching to edge
    span.textContent = bg ? text.trimEnd() : text;
    span.style.color = fg;
    if (bg) { span.style.backgroundColor = bg; span.style.borderRadius = '2px'; span.style.padding = '0 2px'; }
    if (bold) span.style.fontWeight = '600';
    if (dim) span.style.opacity = '0.6';
    if (italic) span.style.fontStyle = 'italic';
    if (underline) span.style.textDecoration = 'underline';
    if (strikethrough) span.style.textDecoration = (underline ? 'underline ' : '') + 'line-through';
    parent.appendChild(span);
  };

  while ((match = ANSI_RE.exec(raw)) !== null) {
    hasEsc = true;
    if (match.index > lastIdx) emitSpan(raw.slice(lastIdx, match.index));
    lastIdx = match.index + match[0].length;

    const codes = match[1].split(';').map(Number);
    let ci = 0;
    while (ci < codes.length) {
      const c = codes[ci];
      if (c === 0) { fg = defaultColor; bg = undefined; bold = false; dim = false; italic = false; underline = false; strikethrough = false; }
      else if (c === 1) bold = true;
      else if (c === 2) dim = true;
      else if (c === 3) italic = true;
      else if (c === 4) underline = true;
      else if (c === 9) strikethrough = true;
      else if (c === 22) { bold = false; dim = false; }
      else if (c === 23) italic = false;
      else if (c === 24) underline = false;
      else if (c === 29) strikethrough = false;
      else if (FG16[c]) fg = FG16[c];
      else if (BG16[c]) bg = BG16[c];
      else if (c === 39) fg = defaultColor;
      else if (c === 49) bg = undefined;
      // 256-color: 38;5;N (fg) or 48;5;N (bg)
      else if (c === 38 && codes[ci + 1] === 5 && ci + 2 < codes.length) {
        fg = color256(codes[ci + 2]); ci += 2;
      } else if (c === 48 && codes[ci + 1] === 5 && ci + 2 < codes.length) {
        bg = color256(codes[ci + 2]); ci += 2;
      }
      // RGB: 38;2;R;G;B (fg) or 48;2;R;G;B (bg)
      else if (c === 38 && codes[ci + 1] === 2 && ci + 4 < codes.length) {
        fg = `rgb(${codes[ci + 2]},${codes[ci + 3]},${codes[ci + 4]})`; ci += 4;
      } else if (c === 48 && codes[ci + 1] === 2 && ci + 4 < codes.length) {
        bg = `rgb(${codes[ci + 2]},${codes[ci + 3]},${codes[ci + 4]})`; ci += 4;
      }
      ci++;
    }
  }

  if (hasEsc && lastIdx < raw.length) emitSpan(raw.slice(lastIdx));
  else if (!hasEsc) {
    parent.style.color = defaultColor;
    parent.textContent = raw;
  }
}

interface Props {
  termRef: React.RefObject<Terminal | null>;
  containerRef: React.RefObject<HTMLDivElement | null>;
  sessionName: string;
  sessionId: string;
  enabled: boolean;
  active?: boolean;  // true when tab is visible — controls poll rate
}

// ── Section classification (single source of truth) ─────────────────────────

type Section = 'user' | 'inject' | 'assistant' | 'tool' | 'thinking' | 'separator' | 'statusbar' | 'cont';

const SECTION_COLORS: Record<Section, string> = {
  user: '#7aa2f7',
  inject: '#2ac3de',   // cyan — inter-session prompt (send_prompt envelope); blue-family, distinct from user blue
  assistant: '#9ece6a',
  tool: '#e0af68',
  thinking: '#bb9af7',
  separator: 'transparent',
  statusbar: 'transparent',
  cont: 'transparent',
};

// Thinking BODY text color (distinct from the THINKING label/marker color above).
// Deliberately bright per the overshoot rule — converge down from here if too much.
const THINKING_TEXT_COLOR = '#e3ccff';

// Backgrounds: darkened versions of the provided palette
// Source: User #4C72AD, Assistant #CBF5D6, Tool #FFDEC2, Thinking #C8A5FA, Cont #DBDBDB
// Brighter section backgrounds (≈2× luminance of the prior tints) — deliberately
// overshot per the overshoot rule; dial back if too strong.
const SECTION_BG: Record<Section, string> = {
  user: '#213450',       // blue tint
  inject: '#103039',     // teal/cyan tint — inter-session prompt
  assistant: '#1c3a26',  // green tint
  tool: '#3a2c18',       // orange tint
  thinking: '#2e2049',   // purple tint
  separator: '#0a0c10',
  statusbar: '#0a0c10',
  cont: '#181a20',       // neutral
};

const TRANSCRIPT_INSERT_HIGHLIGHT_MS = 1200;

/** Briefly identify a card that just replaced streamed terminal text. This is
 *  deliberately visual-only: Transcript authority is immediate and the raw live
 *  tail is never delayed merely to make the handoff look smoother. */
function highlightTranscriptChange(
  element: HTMLElement,
  section: Section,
  change: 'inserted' | 'updated',
): void {
  const color = SECTION_COLORS[section] || '#c0caf5';
  const background = SECTION_BG[section] || SECTION_BG.cont;
  element.dataset.transcriptChange = change;

  const animation = element.animate([
    {
      backgroundColor: `${color}66`,
      borderLeftColor: '#ffffff',
      boxShadow: `inset 0 0 0 1px ${color}, 0 0 14px ${color}`,
      filter: 'brightness(1.45)',
    },
    {
      backgroundColor: background,
      borderLeftColor: color,
      boxShadow: 'none',
      filter: 'brightness(1)',
    },
  ], {
    duration: TRANSCRIPT_INSERT_HIGHLIGHT_MS,
    easing: 'ease-out',
  });
  animation.addEventListener('finish', () => {
    delete element.dataset.transcriptChange;
  }, { once: true });
}

/** Derive platform name from session tracking ID suffix */
function platformFromSessionName(sessionName: string): string {
  if (sessionName.endsWith('_cod')) return 'CODEX';
  if (sessionName.endsWith('_gem')) return 'GEMINI';
  return 'CLAUDE';
}

function makeSectionLabels(platform: string): Record<Section, string> {
  return {
    user: 'YOU',
    inject: 'COMMS',  // inter-session injected prompt (e.g. from Git Guardian)
    assistant: platform,
    tool: '',       // filled dynamically with tool name
    thinking: 'THINKING',
    separator: '',
    statusbar: '',
    cont: '',
  };
}

const SEPARATOR_CHAR = '\u2500';  // ─ box drawing horizontal

/** The 256-color foreground index (the `N` in SGR `38;5;N`) active at the first
 *  occurrence of `glyph` in the raw (ANSI-preserving) line, or null if none / the
 *  immediately-preceding SGR isn't a 256-color foreground. Used to read the marker
 *  glyph's color — Claude colors a RESPONSE ⏺ white (231) and a TOOL ⏺ a non-white
 *  color (blue 75, salmon 210 for Search, …). */
function markerColor256(rawLine: string, glyph: string): string | null {
  const idx = rawLine.indexOf(glyph);
  if (idx < 0) return null;
  const prefix = rawLine.slice(0, idx);
  // eslint-disable-next-line no-control-regex
  const sgrs = [...prefix.matchAll(/\x1b\[([0-9;]*)m/g)];
  if (!sgrs.length) return null;
  const last = sgrs[sgrs.length - 1][1];        // e.g. "38;5;75", "1;38;5;231", or "0"
  const m = last.match(/38;5;(\d+)/);
  return m ? m[1] : null;
}

// Claude's RESPONSE-marker color (white). A ⏺ in any other color is a tool call.
const CLAUDE_RESPONSE_COLOR = '231';

// Inter-session prompt envelope — a prompt injected by another session (e.g. Git
// Guardian) via comms send_prompt. The body opens with a provenance header:
//   "From <trackingId> (<terminalSession>) at YYYY-MM-DD HH:MM:SS"
// These render as ❯ user prompts but are NOT human input, so we sub-type the ❯
// marker into 'inject' when the text after it matches this signature.
const INJECT_ENVELOPE_RE = /^From\s+\S+\s+\(\S+\)\s+at\s+\d{4}-\d{2}-\d{2}\b/;

function classifyLine(line: string): Section {
  const plain = stripAnsi(line);
  const trimmed = plain.trim();

  // ── Claude CLI markers ──
  if (plain.startsWith(P)) {
    // Sub-type the prompt marker: an injected inter-session prompt (send_prompt
    // envelope) vs a real human-typed prompt. Same disambiguation pattern as ⏺.
    const after = plain.slice(P.length).trim();
    return INJECT_ENVELOPE_RE.test(after) ? 'inject' : 'user';
  }
  // Horizontal rule separator — pure dash lines at column 0, not table borders or timing markers.
  if (isSeparatorLine(line)) {
    const hasTableChars = /[\u2502\u250C\u2510\u2514\u2518\u251C\u2524\u252C\u2534\u253C]/.test(trimmed);
    if (!hasTableChars) return 'separator';
  }
  // ∴ Thinking marker (Claude Code uses U+2234 THEREFORE) — column 0 only.
  if (plain.startsWith(T)) return 'thinking';
  // ⏺ Response/tool marker — column 0 only (an indented ⏺ is continuation).
  if (plain.startsWith(R)) {
    const after = plain.slice(1).trim();
    // PRIMARY: the ⏺ glyph's color. Claude paints a RESPONSE marker white (231) and a
    // TOOL marker a non-white color (blue 75; salmon 210 for Search; etc.). Robust
    // across tool-name shapes the text patterns below miss — dotted (folder.create,
    // workspace.tabs.open), multi-word (Stop Task, Background command), new tools.
    const markerCol = markerColor256(line, R);
    if (markerCol === CLAUDE_RESPONSE_COLOR) return 'assistant';
    if (markerCol !== null) return 'tool';
    // FALLBACK (no color info): text patterns. Native/dotted: "⏺ Bash(cmd)" "⏺ folder.create(...)".
    if (/^[\w.]+\(/.test(after)) return 'tool';
    // MCP tool: "⏺ comms - comms_send_prompt (MCP)(...)" "⏺ workflow - workflow_devtree_create (...)"
    if (/^[\w.]+\s*-\s*\w+/.test(after)) return 'tool';
    // Streaming tool verb: "⏺ Exploring…" — single word + ellipsis, tool in progress
    if (/^\w+\u2026$/.test(after)) return 'tool';
    return 'assistant';
  }

  // ── Codex CLI markers ──
  if (plain.startsWith(CODEX_PROMPT)) return 'user';
  if (trimmed.startsWith(CODEX_TOOL)) {
    const after = trimmed.slice(1).trim();
    // Codex tool calls: "• Ran cmd", "• Called tool(...)", "• Updated Plan", "• Edited file", etc.
    if (/^(Ran|Called|Updated|Waited|Read|Wrote|Created|Deleted|Edited)\b/.test(after)) return 'tool';
    // Codex activity indicator: "• Working (3s • esc to interrupt)" — not a section start
    if (/^Working\s*\(/.test(after)) return 'cont';
    // Codex assistant text starts with • too (response content)
    return 'assistant';
  }
  // Codex task list items
  if (trimmed.startsWith('\u2714') || trimmed.startsWith('\u25A1')) return 'cont';  // ✔ done, □ pending

  // ── Gemini CLI markers ──
  if (plain.startsWith(GEMINI_RESPONSE)) return 'assistant';
  // Gemini user prompt: " > text" (leading space + >)
  if (/^ > /.test(plain)) return 'user';
  // Gemini thinking: " Thinking..." (indent 1, plain text)
  if (/^ Thinking\.\.\./.test(plain)) return 'thinking';
  // Gemini inline tool results: "  ✓  ReadFolder ..." or "  ✓  ReadFile ..." (indent 2, ✓ U+2713)
  if (/^ {1,3}\u2713\s/.test(plain)) return 'tool';
  // Gemini tool box borders
  if (plain.startsWith(GEMINI_TOOL_TOP)) return 'tool';
  if (plain.startsWith(GEMINI_TOOL_BOT)) return 'cont';  // end of tool box, treat as continuation
  // Gemini info/cancel
  if (plain.startsWith(GEMINI_INFO)) return 'separator';

  return 'cont';
}

/**
 * Find line indices that belong to [/PRIVATE] thinking blocks.
 * A thinking block runs from a 'thinking' marker until the next non-cont marker.
 * If any line in the block contains [/PRIVATE], all lines in the block are skipped.
 */
function findPrivateLines(lines: string[]): Set<number> {
  const skip = new Set<number>();
  let i = 0;

  while (i < lines.length) {
    if (classifyLine(lines[i]) === 'thinking') {
      // Collect the full thinking block
      const start = i;
      let hasPrivate = false;
      i++;
      while (i < lines.length && classifyLine(lines[i]) === 'cont') {
        if (stripAnsi(lines[i]).includes('[/PRIVATE]')) hasPrivate = true;
        i++;
      }
      // Also check the marker line itself
      if (stripAnsi(lines[start]).includes('[/PRIVATE]')) hasPrivate = true;

      if (hasPrivate) {
        for (let j = start; j < i; j++) skip.add(j);
      }
    } else {
      i++;
    }
  }

  return skip;
}

/**
 * Find where the prompt area begins.
 * Strategy: find the LAST separator (────) that is near the bottom of the capture
 * and followed by a prompt or status area (not by content). This works for all platforms:
 * - Claude: ──── separator → ❯ prompt → ──── separator → status lines
 * - Codex: ─ Worked for... → content → › prompt → status line
 * - Gemini: ──── separator → YOLO → * Type your message → workspace info
 * Returns the line index, or lines.length if no prompt area found.
 */
function isSeparatorLine(line: string): boolean {
  const plain = stripAnsi(line);
  // A separator begins at column 0 with a run of >= 20 box-drawing dashes (U+2500).
  // Trailing content (a session badge like "── Broken-Clock──") is irrelevant —
  // badge length does not disqualify the line. Turn-timing markers like
  // "─ Worked for 1m 52s ────" start with a single dash + space (run length 1),
  // so they're excluded. Tables start with corner glyphs, also excluded.
  const m = plain.match(/^─+/);
  return m !== null && m[0].length >= 20;
}

/** Detect Claude Code verb line — both active and completed forms:
 *  Active:    "✻ Crystallizing… (33s · ↓ 264 tokens)"  — has ellipsis
 *  Completed: "✳ Churned for 3m 38s · 2 shells still running" — no ellipsis, has duration
 *  The bullet character varies (✻✽✳·∴) but the pattern is consistent:
 *  single-char bullet + space + word. */
function isVerbLine(line: string): boolean {
  // Marker glyph must be at column 0 (no leading whitespace), then a space.
  // The verb's FIRST letter can be transiently replaced by an animation glyph
  // (Claude spins the line; a capture frame caught "Saut\u00e9ed" as "\u23f5aut\u00e9ed",
  // U+23F5). So we anchor on STRUCTURE, not the verb spelling:
  //   present participle (still streaming): <glyph> <token\u2026>\u2026   (ends in U+2026)
  //   past tense (completed):               <glyph> <token\u2026> for <N><h|m|s>
  // verbs (past): Baked Brewed Churned Cogitated Cooked Crunched Saut\u00e9ed Worked
  const plain = stripAnsi(line);
  if (/^\S\s+\S+\u2026/u.test(plain)) return true;               // active: ellipsis tied to the gerund (NOT anywhere)
  if (/^\S\s+\S+\s+for\s+\d+\s*[hms]/u.test(plain)) return true;  // completed: <glyph> <word> for <dur>  (Claude "\u273b Baked for\u2026" / Codex "\u2500 Worked for\u2026")
  // Codex active thinking line: "<glyph> Working (<N>s \u00b7 esc to interrupt)". The leading
  // glyph animates (\u2022 \u25e6 \u2026); "Working (<digit>" is the discriminator (excludes the Codex
  // tool calls "\u2022 Ran\u2026/\u2022 Called\u2026/\u2022 Updated\u2026" and the status line). (Timbre/Codex, 2026-07-04.)
  if (/^\S\s+Working\s*\(\d/u.test(plain)) return true;
  // Active with a MULTI-WORD gerund phrase: "\u273b Writing spec and plan\u2026 (26m 52s \u00b7 \u2026)".
  // The single-word clause above misses these, so the verb line + task list collapse
  // into the preceding section (Timbre, 2026-07-04). Extend to a phrase, but keep the
  // \u00a72.5 guarantee that ordinary content ("\u23fa Now per the new\u2026 rule") never matches:
  //  (a) the glyph must be a symbol animation glyph, NOT a stable non-verb marker
  //      (\u23fa response/tool, \u23bf result, \u276f/\u203a prompt, \u2022 codex, \u25fc \u2714 \u25a1 \u2713 task item), so a
  //      response/result/task ENDING in an ellipsis is not misread as a verb line; and
  //  (b) the ellipsis must sit at the PHRASE END \u2014 before " (elapsed\u2026)" or EOL \u2014 so a
  //      MID-sentence content ellipsis ("new\u2026 rule") is rejected while "plan\u2026" matches.
  const g = plain[0];
  if (g && !NON_VERB_GLYPHS.has(g) && /[^\w\s]/u.test(g)
      && /^\S\s+\S[^\n]*\u2026(?:\s*\(|\s*$)/u.test(plain)) return true;
  return false;
}

function isCompletedVerbLine(line: string): boolean {
  return /^\S\s+\S+\s+for\s+\d+\s*[hms]/u.test(stripAnsi(line));
}

function isActiveVerbLine(line: string): boolean {
  return isVerbLine(line) && !isCompletedVerbLine(line);
}

/** Bound terminal-derived message creation to the unfinished turn. A completed
 * verb line closes the preceding terminal turn; when that marker is absent, the
 * newest submitted user marker is the safe fallback. Transcript settlement,
 * not this boundary, still owns every completed card. */
function currentTerminalRegionStart(
  lines: string[],
  promptStart: number,
  hasSettledTranscript: boolean,
): number {
  for (let i = promptStart - 1; i >= 0; i--) {
    if (isCompletedVerbLine(lines[i])) return i + 1;
  }
  for (let i = promptStart - 1; i >= 0; i--) {
    if (classifyLine(lines[i]) === 'user') return i;
  }
  return hasSettledTranscript ? promptStart : 0;
}

/** Convert a line boundary in a scrollback capture to the number of visible
 * terminal rows below it. captureScrollback may include blank padding beyond the
 * actual xterm viewport, so preserve only the trailing blanks visible in xterm. */
function visibleTerminalGapLineCount(
  lines: string[],
  gapStart: number | null,
  visibleRows: number,
  visibleTrailingBlankRows: number,
): number {
  if (gapStart === null || gapStart < 0 || gapStart >= lines.length) return 0;
  let capturedTrailingBlankRows = 0;
  for (let i = lines.length - 1; i >= 0 && lines[i] === ''; i--) {
    capturedTrailingBlankRows++;
  }
  const offscreenPaddingRows = Math.max(
    0,
    capturedTrailingBlankRows - Math.max(0, visibleTrailingBlankRows),
  );
  return Math.min(
    Math.max(0, Math.floor(visibleRows)),
    Math.max(0, (lines.length - offscreenPaddingRows) - gapStart),
  );
}

function visibleActiveVerbLineIndex(
  lines: string[],
  currentRegionStart: number,
  terminalMessageEnd: number,
  visibleRows: number,
  visibleTrailingBlankRows: number,
): number | null {
  let capturedTrailingBlankRows = 0;
  for (let i = lines.length - 1; i >= 0 && lines[i] === ''; i--) {
    capturedTrailingBlankRows++;
  }
  const visibleCaptureEnd = lines.length - Math.max(
    0,
    capturedTrailingBlankRows - Math.max(0, visibleTrailingBlankRows),
  );
  const visibleCaptureStart = Math.max(0, visibleCaptureEnd - Math.max(0, visibleRows));
  for (
    let i = Math.min(terminalMessageEnd - 1, visibleCaptureEnd - 1);
    i >= Math.max(currentRegionStart, visibleCaptureStart);
    i--
  ) {
    if (isActiveVerbLine(lines[i])) return i;
  }
  return null;
}

/** A tail that was already present when Transcript advanced belongs to the
 * settled message. Terminal repaint/reflow may still change its rendered rows,
 * but that must update neither the settled chain nor create a new provisional. */
function shouldSeedUpdatedTerminalTail(
  fingerprint: string | undefined,
  previousSnapshotTranscriptRevision: string,
  currentTranscriptRevision: string,
  settledFingerprints: ReadonlySet<string>,
): boolean {
  return Boolean(
    fingerprint
    && previousSnapshotTranscriptRevision === currentTranscriptRevision
    && !settledFingerprints.has(fingerprint),
  );
}

/** Once the terminal has emitted an explicit completed-turn marker and no
 * unfinished terminal cards remain, provisionals may only survive briefly while
 * JSONL catches up. Previously consumed fingerprints are removed individually;
 * the grace bound prevents any missed watcher/race remainder from persisting
 * forever. */
function shouldDrainClosedTerminalProvisionals(
  terminalRegionClosed: boolean,
  closedForMs: number,
): boolean {
  return terminalRegionClosed
    && closedForMs >= CLOSED_PROVISIONAL_GRACE_MS;
}

function provisionalReachedSettlement(
  expectedSettledCardCount: number | undefined,
  settledCardCount: number,
): boolean {
  return expectedSettledCardCount !== undefined
    && settledCardCount >= expectedSettledCardCount;
}

/** Suppress consumed fingerprints until (and only until) the next submitted
 * user marker. Process in terminal order so a stale prior-turn candidate that
 * precedes that marker stays suppressed, while an intentionally repeated
 * fingerprint after the marker belongs to the new turn and may be admitted. */
function filterTerminalCandidatesForTurn<
  T extends { type: string; terminalFingerprint?: string },
>(
  candidates: T[],
  settledFingerprints: Set<string>,
): T[] {
  const admitted: T[] = [];
  for (const candidate of candidates) {
    if (candidate.type === 'user') settledFingerprints.clear();
    if (candidate.terminalFingerprint
        && settledFingerprints.has(candidate.terminalFingerprint)) {
      continue;
    }
    admitted.push(candidate);
  }
  return admitted;
}
// Stable, non-animated markers that lead a NON-verb line. Used to keep the multi-word
// active clause from mistaking a response/tool/result/prompt/task line that ends in an
// ellipsis for a thinking verb line. (The animation glyphs \u273b\u273d\u2733\u00b7\u2234 are an open set \u2014 we
// match those by structure/exclusion, never by enumeration.)
const NON_VERB_GLYPHS = new Set([
  '\u23fa', // \u23fa response/tool
  '\u23bf', // \u23bf tool result
  '\u276f', // \u276f prompt
  '\u203a', // \u203a codex prompt
  '\u2022', // \u2022 codex tool
  '>',      // ascii prompt fallback
  '\u25fc', // \u25fc task item (pending)
  '\u2714', // \u2714 task item (done)
  '\u25a1', // \u25a1 task item (pending, hollow)
  '\u2713', // \u2713 tool/check
]);

// A Claude Code interactive DECISION area (tool-permission "Do you want to proceed?",
// plan approval, etc.) REPLACES the normal ──── ❯ ──── prompt block while the CLI waits
// for a choice: there are no separators, so findPromptAreaStart would otherwise fall
// through to `return lines.length` and the WHOLE viewport (the live dialog included)
// would otherwise be classified as message text. The discriminator (per PianoMan's
// spec, verified against Broken-Clock):
// the dialog's structural lines are indented by ONE space, so the option's ❯ sits at
// COLUMN 1 — whereas a real user/prompt ❯ sits at COLUMN 0. Detect the dialog and return
// its TOP so it stays in the plain terminal-chrome block. The dialog disappears once
// answered, so it only ever needs plain-chrome treatment (no settled-section type).
const DECISION_OPTION_RE = /^ ❯\s*\d+\./;   // " ❯ 1. Yes" — ❯ at column 1, numbered option

function findDecisionAreaStart(lines: string[]): number {
  // Anchor on the lowest column-1 ❯ numbered option near the bottom.
  let opt = -1;
  for (let i = lines.length - 1; i >= Math.max(0, lines.length - 24); i--) {
    if (DECISION_OPTION_RE.test(stripAnsi(lines[i]))) { opt = i; break; }
  }
  if (opt < 0) return -1;
  // Walk UP to the dialog top: contiguous COLUMN-1 lines (one leading space then a
  // non-space — the question, warning, footer) plus interspersed blanks. Stop at a
  // column-0 marker or ≥2-space agent/tool body. Require at least one column-1 line
  // that begins with a LETTER (the question) so a bare numbered list can't false-match.
  let sawLetterLine = false;
  let top = opt;
  for (let i = opt - 1; i >= Math.max(0, opt - 16); i--) {
    const plain = stripAnsi(lines[i]);
    if (plain.trim() === '') continue;          // blank — may sit between dialog lines
    if (!/^ \S/.test(plain)) break;             // column-0 marker or ≥2-space body → dialog top is below
    if (/^ [A-Za-z]/.test(plain)) sawLetterLine = true;
    top = i;
  }
  return sawLetterLine ? top : -1;
}

function findPromptAreaStart(lines: string[]): number {
  // From the bottom, find two horizontal separator lines.
  // Claude has two separators bracketing the prompt: ──── ❯ prompt ──── status
  // Codex/Gemini have one separator before the prompt area.
  // If two separators are found, verify the top one is a prompt boundary
  // (has a prompt marker between them), not a content separator.
  let bottomSep = -1;
  let topSep = -1;

  for (let i = lines.length - 1; i >= Math.max(0, lines.length - 50); i--) {
    if (isSeparatorLine(lines[i])) {
      if (bottomSep < 0) {
        bottomSep = i;
      } else {
        // Check if there's a prompt marker between this separator and bottomSep.
        // Claude prompt glyph is ❯ (U+276F); some renders show ">" (U+003E) at
        // column 0. Codex ›, Gemini " > ". Recognize all so the bracketing never
        // misfires on glyph variance.
        let hasPromptBetween = false;
        for (let j = i + 1; j < bottomSep; j++) {
          const p = stripAnsi(lines[j]);
          if (p.startsWith(P) || p.startsWith(CODEX_PROMPT)
              || p.startsWith('> ') || p === '>'
              || /^ > /.test(p)) {
            hasPromptBetween = true;
            break;
          }
        }
        if (hasPromptBetween) {
          topSep = i;
          break;
        }
        // No prompt marker recognized, but for Claude two ─ separators within a
        // small window at the bottom unambiguously bracket the prompt (Claude
        // content separators use ═, not ─). If the gap is small, accept it.
        if (bottomSep - i <= 6) {
          topSep = i;
          break;
        }
      }
    }
  }

  // Codex/Gemini: the › or > prompt placeholder is the definitive anchor.
  // Codex uses pure ──── lines as turn separators in content, so separator
  // detection is unreliable for Codex. Check for prompt placeholder first.
  for (let i = lines.length - 1; i >= Math.max(0, lines.length - 10); i--) {
    const plain = stripAnsi(lines[i]);
    if (plain.startsWith(CODEX_PROMPT)) return i;
    if (/^ > /.test(plain)) return i;  // Gemini prompt
  }

  // Claude: use two-separator detection (──── ❯ ────)
  if (topSep >= 0) return topSep;
  if (bottomSep >= 0) return bottomSep;
  // No normal prompt block — a decision/permission prompt has replaced it while the CLI
  // waits for an answer. Return the dialog's top so it stays uncovered (the reported bug
  // was the whole viewport, dialog included, getting covered).
  const dec = findDecisionAreaStart(lines);
  if (dec >= 0) return dec;
  return lines.length;
}

/** Format a single line with ANSI color passthrough. Returns div + section color. */
function formatLine(line: string, sectionColor: string): { div: HTMLDivElement; color: string } {
  const div = document.createElement('div');
  const section = classifyLine(line);
  const isMarker = section !== 'cont' && section !== 'separator';
  const color = isMarker ? SECTION_COLORS[section] : sectionColor;
  // Continuation lines get the same background as their parent section
  const bg = isMarker ? SECTION_BG[section] : SECTION_BG[
    sectionColor === SECTION_COLORS.user ? 'user' :
    sectionColor === SECTION_COLORS.assistant ? 'assistant' :
    sectionColor === SECTION_COLORS.tool ? 'tool' :
    sectionColor === SECTION_COLORS.thinking ? 'thinking' : 'cont'
  ];

  const gap = isMarker ? 'margin-top:8px;' : '';
  const dimStyle = section === 'thinking' ? 'opacity:0.7;' : '';
  const bgStyle = bg !== 'inherit' && bg !== 'transparent' ? `background:${bg};` : '';

  div.style.cssText = `${gap}border-left:2px solid ${color};padding-left:4px;white-space:pre-wrap;${dimStyle}${bgStyle}`;
  div.dataset.section = section;

  // Add section label as its own line above the content on marker lines
  if (isMarker) {
    let label = makeSectionLabels('CLAUDE')[section];
    if (section === 'tool') {
      const plain = stripAnsi(line).trim();
      const after = plain.slice(1).trim();
      const toolMatch = after.match(/^(\w+)/);
      if (toolMatch) label = toolMatch[1].toUpperCase();
    }
    if (label) {
      const labelEl = document.createElement('div');
      labelEl.style.cssText = `color:${color};font-size:11px;font-weight:700;letter-spacing:2px;padding:2px 0;`;
      labelEl.textContent = label;
      div.appendChild(labelEl);
    }
  }

  // Render content — strip ANSI from user lines to remove prompt highlighting
  const contentEl = document.createElement('div');
  if (section === 'user' || section === 'inject') {
    contentEl.style.color = '#c0caf5';
    contentEl.textContent = stripAnsi(line);
  } else {
    const defaultColor = (section === 'tool' || section === 'thinking') ? color : '#c0caf5';
    renderAnsiLine(line, contentEl, defaultColor);
  }
  div.appendChild(contentEl);

  return { div, color };
}

/** Group consecutive lines into sections for collapsible rendering */
interface SectionGroup {
  type: Section;
  label: string;
  lines: string[];
  startIdx: number;
  /** Stable identity for collapse/metadata/DOM-diff tracking — survives line index
   *  shifts across polls. Terminal sections: `${type}:${markerPrefix}[#occ]`.
   *  Synthetic (JSONL-backed reconciliation, future): `syn:msg<msgId>` — a distinct,
   *  position-independent id so inserting one never renumbers terminal neighbors
   *  (Codex review HIGH 5). Consumers key off `.key`; never assume content+occurrence. */
  key: string;
  /** Terminal fallback, transcript truth, or the terminal's folded tool rendering. */
  origin: 'terminal' | 'transcript' | 'terminal-tool';
  /** Content revision for incremental DOM replacement without changing collapse identity. */
  version: string;
  msgId?: number;
  lastMsgId?: number;
  turnNum?: number;
  timestamp?: string;
  /** Terminal-only opening-marker identity used to advance the provisional chain. */
  terminalFingerprint?: string;
  /** Settled-card count at which this FIFO position must already have been
   * consumed. This is positional bookkeeping, never terminal/Transcript content
   * matching. */
  expectedSettledCardCount?: number;
}

function sectionVersion(group: Pick<SectionGroup, 'type' | 'lines'>): string {
  let hash = 2166136261;
  const source = `${group.type}|${group.lines.join('\n')}`;
  for (let i = 0; i < source.length; i++) {
    hash ^= source.charCodeAt(i);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0).toString(36);
}

function sectionDefaultCollapsed(type: string, override: boolean | null | undefined, label?: string): boolean {
  // AskUserQuestion is an interactive DECISION prompt, not routine tool output. Its
  // question/options must be readable at a glance, so it renders EXPANDED by default
  // rather than collapsing to a "24 lines" header like ordinary tool cards. The
  // per-card collapse toggle still works (the caller inverts this default per key),
  // and an explicit Collapse/Expand-all override still takes precedence.
  if (override !== null && override !== undefined) return override;
  if (label === 'AskUserQuestion') return false;
  return type === 'tool' || type === 'thinking';
}

function groupIntoSections(lines: string[], stickyMap?: Map<string, Section>, sectionLabels?: Record<Section, string>): SectionGroup[] {
  const labels = sectionLabels || makeSectionLabels('CLAUDE');
  const groups: SectionGroup[] = [];
  let current: SectionGroup | null = null;
  let keySeen: Record<string, number> = {};

  for (let i = 0; i < lines.length; i++) {
    let section = classifyLine(lines[i]);

    // Sticky classification: once a line is classified as a section marker,
    // that classification persists for the turn. Prevents ANSI blink from
    // reclassifying a marker line as 'cont', which causes section bouncing.
    if (stickyMap) {
      // Trailing trim ONLY — leading whitespace must be preserved. A marker is
      // column-0 (per spec); trimming the leading margin made a real col-0
      // marker and an indented copy of the same text (e.g. a user pasting live
      // terminal feed into their prompt) share a key, so the sticky map
      // wrongly re-promoted the indented paste to a marker. Keeping the margin
      // in the key means col-0 "⏺ …" and col-2 "  ⏺ …" never collide.
      const plain = stripAnsi(lines[i]).replace(/\s+$/, '');
      const key = plain.slice(0, 60);
      const sticky = stickyMap.get(key);
      // If previously classified as a marker but now classified as cont, restore
      if (sticky && sticky !== 'cont' && sticky !== 'separator' && section === 'cont') {
        section = sticky;
      }
      // Also handle tool/assistant disambiguation on ⏺ lines
      if (sticky && plain.startsWith(R) && section === 'assistant' && sticky === 'tool') {
        section = 'tool';
      }
      // Record any non-cont, non-separator classification
      if (section !== 'cont' && section !== 'separator') {
        stickyMap.set(key, section);
      }
    }

    if (section !== 'cont' && section !== 'separator') {
      // New section starts
      if (current) groups.push(current);

      let label = labels[section];
      if (section === 'tool') {
        const plain = stripAnsi(lines[i]).trim();
        const after = plain.slice(1).trim();
        const toolMatch = after.match(/^(\w+)/);
        if (toolMatch) label = toolMatch[1].toUpperCase();
      }

      // Key: content-based prefix + occurrence count for uniqueness.
      // Multiple calls to the same tool (e.g., Read same file) get different keys.
      const keyContent = stripAnsi(lines[i]).trim().slice(0, 80);
      const baseKey = `${section}:${keyContent}`;
      keySeen[baseKey] = (keySeen[baseKey] || 0) + 1;
      const key = keySeen[baseKey] > 1 ? `${baseKey}#${keySeen[baseKey]}` : baseKey;
      current = { type: section, label, lines: [lines[i]], startIdx: i, key, origin: 'terminal', version: '' };
    } else if (section === 'separator') {
      if (current) groups.push(current);
      groups.push({ type: 'separator', label: '', lines: [lines[i]], startIdx: i, key: `sep-${i}`, origin: 'terminal', version: '' });
      current = null;
    } else {
      // Continuation line — add to current section
      if (current) {
        current.lines.push(lines[i]);
      } else {
        // Orphan continuation — parent marker scrolled off buffer
        current = { type: 'cont', label: '', lines: [lines[i]], startIdx: i, key: `cont-${i}`, origin: 'terminal', version: '' };
      }
    }
  }
  if (current) groups.push(current);

  // Clean up re-render scrollback corruption: drop verbatim block-duplications
  // within each section (separators are single lines — nothing to dedup).
  for (const g of groups) {
    if (g.type === 'separator') continue;
    if (g.lines.length >= 6) g.lines = dedupConsecutiveBlocks(g.lines);
    g.version = sectionVersion(g);
  }
  for (const g of groups) if (!g.version) g.version = sectionVersion(g);

  return groups;
}

function transcriptBlocksToGroups(
  blocks: SettledTranscriptBlock[],
  toolViews: Map<string, string[]>,
): SectionGroup[] {
  const rendered = applyTerminalToolViews(blocks, toolViews);
  return rendered.map((block) => ({
    type: block.section,
    label: block.label,
    lines: block.lines.length > 0 ? block.lines : [''],
    startIdx: block.firstMsgId,
    key: block.key,
    origin: block.section === 'tool' && toolViews.has(block.key) ? 'terminal-tool' : 'transcript',
    version: block.version,
    msgId: block.firstMsgId,
    lastMsgId: block.lastMsgId,
    turnNum: block.turnNum,
    timestamp: block.timestamp,
  }));
}

function terminalOpeningFingerprint(type: string, line: string): string {
  // Keep this prefix long enough to identify a message but short enough to
  // survive terminal reflow changing the latter half of a long opening row.
  // Settled Transcript cards eventually disambiguate any genuinely repeated
  // opening; provisional safety favors suppressing a repaint duplicate.
  const opening = stripAnsi(line).replace(/\s+/g, ' ').trim().slice(0, 96);
  return `${type}:${opening}`;
}

/** Build the terminal's ordered message-card list. Separators are chrome, not
 *  messages. An orphan continuation is shown as assistant output rather than
 *  allowing a missing opening marker to blank the live bottom. */
function terminalMessageGroups(
  lines: string[],
  stickyMap: Map<string, Section>,
  labels: Record<Section, string>,
): SectionGroup[] {
  const grouped = groupIntoSections(lines, stickyMap, labels)
    .filter((group) => (
      group.type !== 'separator'
      && group.lines.some((line) => stripAnsi(line).trim().length > 0)
    ));

  return grouped.map((group, index) => {
    const type = group.type === 'cont' ? 'assistant' : group.type;
    return {
      ...group,
      type,
      label: group.type === 'cont' ? labels.assistant : group.label,
      key: `terminal:${index}`,
      origin: 'terminal',
      version: sectionVersion({ type, lines: group.lines }),
      terminalFingerprint: terminalOpeningFingerprint(type, group.lines[0] || ''),
    };
  });
}

function isTaskChromeLine(line: string): boolean {
  const plain = stripAnsi(line);
  return /^\s*[◼✔□]\s/u.test(plain)
    || /^\S\s+Running\s+\S/u.test(plain);
}

/** Determine the section color at a given line index by scanning preceding lines */
function sectionColorAt(lines: string[], index: number): string {
  let color = 'transparent';
  for (let i = 0; i < index; i++) {
    const section = classifyLine(lines[i]);
    if (section !== 'cont') color = SECTION_COLORS[section];
  }
  return color;
}

const POLL_ACTIVE_MS = 1000;
const POLL_BACKGROUND_MS = 5000;
const INITIAL_CAPTURE_LINES = 50000;
const REFRESH_CAPTURE_LINES = 2000;
const CLOSED_PROVISIONAL_GRACE_MS = 10000;

// ── Memorex diagnostic recorder (todo_0392 / todo_0385) ────────────────────
// An always-on, bounded ring buffer of per-refresh frames: boundary state +
// DOM geometry rects + anomaly flags. Purely additive — it READS overlay state
// and never influences rendering. Its recordings double as fail-closed fixtures
// for record/replay verification (per Codex review MAJOR 7). Dump the last N
// frames after a visual glitch instead of trying to arm capture in time.
const MEMOREX_REC_CAP = 400;
const memorexRecBuffer: Array<Record<string, unknown>> = [];
function recordMemorexFrame(frame: Record<string, unknown>): void {
  memorexRecBuffer.push(frame);
  if (memorexRecBuffer.length > MEMOREX_REC_CAP) memorexRecBuffer.shift();
}
// Auto-persist an anomaly capture to disk via the command bus (main process writes
// it to a gitignored diagnostics dir) — no DevTools, no human action required.
function saveAnomalyToDisk(sessionId: string, reason: string, extra: Record<string, unknown>): void {
  try {
    const w = window as unknown as { uai?: { execute?: (c: unknown) => Promise<unknown> } };
    const c = crypto as unknown as { randomUUID?: () => string };
    const id = c.randomUUID ? c.randomUUID() : `mmx-${Date.now()}`;
    w.uai?.execute?.({ id, type: 'memorex.saveAnomaly', payload: { sessionId, reason, payload: extra } });
  } catch { /* best-effort — never break the overlay */ }
}
if (typeof window !== 'undefined' && !(window as unknown as Record<string, unknown>).__memorexRec) {
  (window as unknown as Record<string, unknown>).__memorexRec = {
    frames: () => memorexRecBuffer.slice(),
    anomalies: () => memorexRecBuffer.filter((f) => f.anomalyFull),
    count: () => memorexRecBuffer.length,
    dump: () => JSON.stringify(memorexRecBuffer),
    clear: () => { memorexRecBuffer.length = 0; },
  };
}

const TerminalFormatOverlay = ({ termRef, containerRef, sessionName, sessionId, enabled, active = true }: Props): JSX.Element | null => {
  const platform = platformFromSessionName(sessionName);
  const sectionLabelsRef = useRef(makeSectionLabels(platform));
  sectionLabelsRef.current = makeSectionLabels(platform);  // update if session changes
  const overlayRef = useRef<HTMLDivElement>(null);
  const contentHostRef = useRef<HTMLDivElement>(null);
  const coverRef = useRef<HTMLDivElement | null>(null);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const refreshInFlightRef = useRef(false);
  const refreshPendingRef = useRef(false);
  const lastTextRef = useRef('');
  const hasInitialCaptureRef = useRef(false);
  const lastTranscriptRenderRevisionRef = useRef('');
  const prevLinesRef = useRef<string[]>([]);
  const memorexStateRef = useRef<Record<string, unknown>>({});
  const autoScrollRef = useRef(true);
  const refreshRef = useRef<() => void>(() => {});
  const renderWindowRef = useRef<(force?: boolean) => void>(() => {});
  const windowRenderRafRef = useRef<number | null>(null);
  const virtualRenderGuardRef = useRef(false);
  const virtualRangeRef = useRef({ start: -1, end: -1 });
  const measuredHeightRef = useRef<Map<string, number>>(new Map());
  const renderedVersionsRef = useRef<Map<string, string>>(new Map());
  const hasRenderedTranscriptRef = useRef(false);
  // Debounce for auto-persisting Memorex anomalies to disk (todo_0385/0392).
  const lastAnomalySaveRef = useRef(0);
  // Sticky section classifications: once a ⏺ line is identified as 'tool',
  // that classification sticks across polls even if streaming changes the line content.
  // Key: stripped line text prefix (first 60 chars), Value: section type
  const stickyClassRef = useRef<Map<string, Section>>(new Map());
  // Transcript owns a persistent settled chain. Terminal-only opening markers append
  // to a persistent provisional FIFO below it; each new Transcript card consumes the
  // first provisional by position.
  const transcriptBlocksRef = useRef<SettledTranscriptBlock[]>([]);
  const liveGroupsRef = useRef<SectionGroup[]>([]);
  const terminalGroupsSnapshotRef = useRef<SectionGroup[]>([]);
  const hasTerminalSnapshotRef = useRef(false);
  const terminalSnapshotTranscriptRevisionRef = useRef('');
  const settledTerminalFingerprintsRef = useRef<Set<string>>(new Set());
  const closedTerminalSinceRef = useRef<number | null>(null);
  const nextProvisionalIdRef = useRef(1);
  const hasTranscriptBaselineRef = useRef(false);
  const terminalOutputEpochRef = useRef(0);
  const terminalChromeRef = useRef<SectionGroup[]>([]);
  const transcriptRevisionRef = useRef('');
  const transcriptLoadGenerationRef = useRef(0);
  const toolViewsRef = useRef<Map<string, string[]>>(new Map());
  // Per-type default override: when user clicks expand/collapse triangle for a type,
  // all future sections of that type inherit the override instead of the hardcoded default.
  // null = use hardcoded default, true = collapsed, false = expanded
  const defaultOverrideRef = useRef<Record<string, boolean | null>>({
    user: null, inject: null, assistant: null, tool: null, thinking: null,
  });

  // ── Viewport registration — makes Memorex a queryable tree citizen ──
  useViewport('memorex_view', () => ({
    visible: enabled && active,
    label: `memorex: ${sessionName}`,
    state: memorexStateRef.current,
    children: [],
  }), active);

  /** Fetch the canonical settled-message list. Rendering and live-tail trimming happen
   *  together on the next terminal capture. */
  const refreshTranscriptCache = useCallback(async (triggerRefresh = true): Promise<boolean> => {
    const api = window.uai;
    if (!api?.transcript?.read) return false;
    const generation = ++transcriptLoadGenerationRef.current;
    try {
      let result = api.transcript.getCached ? await api.transcript.getCached(sessionId) : null;
      if (!result || !result.ok || !result.days) {
        result = await api.transcript.read(sessionName, sessionId, 'structured');
      }
      if (generation !== transcriptLoadGenerationRef.current) return false;
      if (!result?.ok || !result.days) return false;

      const records = flattenStructuredTranscript(result.days);
      const last = records[records.length - 1];
      // Keep this source compatible with the currently committed preload type,
      // which predates the optional cache revision even though newer runtimes
      // already return it.
      const cacheRevision = (result as typeof result & { revision?: string }).revision;
      const revision = cacheRevision
        || `${result.path || sessionId}:${records.length}:${last?.msgId || 0}:${last?.timestamp || ''}`;
      if (revision === transcriptRevisionRef.current) return false;

      const previousBlocks = transcriptBlocksRef.current;
      const nextBlocks = buildSettledTranscriptBlocks(
        records,
        sectionLabelsRef.current.assistant,
      );
      const isAppend = previousBlocks.length <= nextBlocks.length
        && previousBlocks.every((block, index) => block.key === nextBlocks[index]?.key);
      const appendedSettledCards = hasTranscriptBaselineRef.current && isAppend
        ? nextBlocks.length - previousBlocks.length
        : 0;

      // Compaction/truncation: the settled Transcript got SHORTER. The old JSONL
      // was rewritten and renumbered, so the provisional chain hanging below the
      // previous (longer) settled tail is stale — every provisional's
      // expectedSettledCardCount referenced the old baseline and is now unreachable,
      // so it can never settle by position and, if the turn never cleanly closes,
      // never drains (the "message repeated many times, untagged, persists across
      // toggles" bug). Folded tool views keyed by the old msgId numbering would also
      // mis-apply to renumbered blocks. Drop the provisional + terminal snapshot
      // state so the chain rebuilds cleanly from the new baseline. Consistent with
      // invariant 8: when the settled prefix itself is redefined, the provisional
      // bottom rebuilds. Never fires on first load (previousBlocks empty) or a
      // growing/in-place revision (only a genuine shrink resets).
      if (hasTranscriptBaselineRef.current && nextBlocks.length < previousBlocks.length) {
        liveGroupsRef.current = [];
        terminalGroupsSnapshotRef.current = [];
        hasTerminalSnapshotRef.current = false;
        terminalSnapshotTranscriptRevisionRef.current = '';
        settledTerminalFingerprintsRef.current.clear();
        closedTerminalSinceRef.current = null;
        toolViewsRef.current.clear();
        stickyClassRef.current.clear();
      }

      if (appendedSettledCards > 0) {
        for (const group of liveGroupsRef.current.slice(0, appendedSettledCards)) {
          if (group.terminalFingerprint) {
            settledTerminalFingerprintsRef.current.add(group.terminalFingerprint);
          }
        }
        liveGroupsRef.current = settleProvisionalCards(
          liveGroupsRef.current,
          appendedSettledCards,
        );
      }

      // Preserve unchanged card objects so the settled chain remains stable across
      // cache refreshes. Tool-result updates replace only their existing card.
      transcriptBlocksRef.current = nextBlocks.map((block, index) => {
        const previous = previousBlocks[index];
        return previous?.key === block.key && previous.version === block.version ? previous : block;
      });
      hasTranscriptBaselineRef.current = true;
      transcriptRevisionRef.current = revision;
      if (triggerRefresh) refreshRef.current();
      return true;
    } catch {
      // Transcript lag/failure leaves the settled DOM intact.
      return false;
    }
  }, [sessionName, sessionId]);

  const lastDimsRef = useRef('');
  // Collapsed sections: tracked by stable key (type-ordinal, e.g. "tool-3")
  const collapsedRef = useRef<Set<string>>(new Set());
  // Type filters: which section types to show
  const filtersRef = useRef<Record<string, boolean>>({
    user: true, inject: true, assistant: true, tool: true, thinking: true,
  });

  /** Synchronous rebuild from cached lines — used by click/context handlers */
  // Track rendered section keys so we can do incremental updates
  const renderedKeysRef = useRef<string[]>([]);

  /** Render a single section group to a DOM element */
  const renderSectionDom = useCallback((group: SectionGroup, collapsed: Set<string>, sectionNum?: number, timestamp?: number, turnNum?: number): HTMLDivElement | null => {
    const filters = filtersRef.current;

    if (group.type === 'separator') {
      const sepDiv = document.createElement('div');
      sepDiv.style.cssText = 'white-space:pre-wrap;color:#333a4a;';
      sepDiv.textContent = group.lines[0];
      sepDiv.dataset.sectionKey = group.key;
      sepDiv.dataset.sectionVersion = group.version;
      return sepDiv;
    }

    // Prompt, decision dialog, and status rows are not messages. While idle,
    // render them plainly at the bottom of the full-height surface. During active
    // thinking, terminalChromeRef is empty because the real animated xterm chrome
    // is visible below the shortened cover.
    if (group.type === 'statusbar') {
      const chrome = document.createElement('div');
      chrome.style.cssText = 'white-space:pre-wrap;color:#8890b0;border-top:1px solid #333a4a;margin-top:8px;padding-top:4px;';
      chrome.dataset.section = 'statusbar';
      chrome.dataset.sectionKey = group.key;
      chrome.dataset.sectionVersion = group.version;
      for (const line of group.lines) {
        const lineDiv = document.createElement('div');
        lineDiv.style.cssText = 'white-space:pre-wrap;min-height:1.4em;';
        renderAnsiLine(line, lineDiv, '#8890b0');
        chrome.appendChild(lineDiv);
      }
      return chrome;
    }

    // Skip orphan cont groups (completion markers, blank lines between sections)
    // and filtered-out section types
    if (group.type === 'cont') return null;
    if (!filters[group.type]) return null;

    const sectionKey = group.key;
    const typeOverride = defaultOverrideRef.current[group.type];
    const defaultCollapsed = sectionDefaultCollapsed(group.type, typeOverride, group.label);
    const isCollapsed = collapsed.has(sectionKey) ? !defaultCollapsed : defaultCollapsed;

    const color = SECTION_COLORS[group.type] || SECTION_COLORS.cont;
    const bg = SECTION_BG[group.type] || SECTION_BG.cont;

    const container = document.createElement('div');
    container.style.cssText = `border-left:2px solid ${color};background:${bg};margin-top:8px;padding-left:4px;`;
    container.dataset.section = group.type;
    container.dataset.sectionKey = sectionKey;
    container.dataset.lineCount = String(group.lines.length);
    container.dataset.sectionVersion = group.version;

    if (group.label) {
      const header = document.createElement('div');
      header.style.cssText = 'display:flex;align-items:center;gap:6px;padding:2px 0;cursor:pointer;';

      const chevron = document.createElement('span');
      chevron.style.cssText = `color:${color};font-size:10px;`;
      chevron.textContent = isCollapsed ? '\u25B6' : '\u25BC';
      header.appendChild(chevron);

      const labelEl = document.createElement('span');
      labelEl.style.cssText = `color:${color};font-size:11px;font-weight:700;letter-spacing:2px;`;
      labelEl.textContent = group.label;
      header.appendChild(labelEl);

      // Section metadata (msg #, timestamp) — populated from JSONL cache when available
      {
        const metaEl = document.createElement('span');
        metaEl.style.cssText = 'color:#8890b0;font-size:10px;';
        metaEl.dataset.meta = '1';  // marker for in-place updates
        const parts: string[] = [];
        if (sectionNum !== undefined) {
          parts.push(turnNum !== undefined ? `Turn #${turnNum} Msg #${sectionNum}` : `Msg #${sectionNum}`);
        }
        if (timestamp) {
          const d = new Date(timestamp);
          const mo = (d.getMonth() + 1).toString().padStart(2, '0');
          const dy = d.getDate().toString().padStart(2, '0');
          const h = d.getHours().toString().padStart(2, '0');
          const m = d.getMinutes().toString().padStart(2, '0');
          const s = d.getSeconds().toString().padStart(2, '0');
          parts.push(`${mo}-${dy} ${h}:${m}:${s}`);
        }
        metaEl.textContent = parts.join('  ');
        header.appendChild(metaEl);
      }

      const lineCount = document.createElement('span');
      lineCount.style.cssText = 'color:#565f89;font-size:10px;margin-left:auto;padding-right:4px;';
      lineCount.textContent = `${group.lines.length} lines`;
      header.appendChild(lineCount);

      // Copy button — copies this section's text (clean, ANSI-stripped). Mirrors the
      // Transcript pane's per-message copy (⎘ glyph, ✓ on success). stopPropagation so
      // it doesn't toggle the section's collapse state.
      const copyLines = group.lines;
      const copyBtn = document.createElement('span');
      copyBtn.style.cssText = 'color:#565f89;font-size:17px;line-height:1;vertical-align:middle;cursor:pointer;padding:0 6px 0 2px;';
      copyBtn.textContent = '⎘';  // ⎘
      copyBtn.title = 'Copy section';
      copyBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const text = copyLines.map(l => stripAnsi(l)).join('\n');
        const done = () => { copyBtn.textContent = '✓'; setTimeout(() => { copyBtn.textContent = '⎘'; }, 1200); };
        const api = (window as any).uai;
        if (api?.clipboard?.write) { api.clipboard.write(text); done(); }
        else { navigator.clipboard.writeText(text).then(done).catch(() => {}); }
      });
      header.appendChild(copyBtn);

      const key = sectionKey;
      const sType = group.type;
      header.addEventListener('click', (e) => {
        e.stopPropagation();
        if (collapsed.has(key)) collapsed.delete(key);
        else collapsed.add(key);
        // A collapsed card changes the virtual row height. Re-render the small
        // visible window so the spacers and following cards remain aligned.
        renderWindowRef.current(true);
      });

      header.addEventListener('contextmenu', (e) => {
        e.preventDefault();
        e.stopPropagation();
        const existing = document.querySelector('.memorex-ctx-menu');
        if (existing) existing.remove();

        const menu = document.createElement('div');
        menu.className = 'memorex-ctx-menu';
        menu.style.cssText = `position:fixed;left:${e.clientX}px;top:${e.clientY}px;background:#1a1d28;border:1px solid #333a4a;border-radius:4px;padding:4px 0;z-index:100;font-family:'JetBrains Mono',monospace;font-size:11px;min-width:220px;`;

        for (const item of [
          { label: `Collapse all ${group.label} sections`, action: () => { collapseAllOfType(sType); } },
          { label: `Expand all ${group.label} sections`, action: () => { expandAllOfType(sType); } },
        ]) {
          const row = document.createElement('div');
          row.style.cssText = 'padding:6px 12px;cursor:pointer;color:#c0caf5;';
          row.textContent = item.label;
          row.addEventListener('mouseenter', () => { row.style.background = 'rgba(255,255,255,0.08)'; });
          row.addEventListener('mouseleave', () => { row.style.background = 'transparent'; });
          row.addEventListener('click', (ev) => { ev.stopPropagation(); item.action(); menu.remove(); });
          menu.appendChild(row);
        }

        document.body.appendChild(menu);
        const cleanup = (ev: Event) => {
          // Don't dismiss if clicking inside the menu itself
          if (menu.contains(ev.target as Node)) return;
          menu.remove();
          document.removeEventListener('mousedown', cleanup, true);
          window.removeEventListener('contextmenu', cleanupAndBlock, true);
        };
        // Capture phase: block right-click from reopening another menu
        const cleanupAndBlock = (ev: Event) => {
          if (menu.contains(ev.target as Node)) return;
          ev.preventDefault();
          ev.stopPropagation();
          menu.remove();
          document.removeEventListener('mousedown', cleanup, true);
          window.removeEventListener('contextmenu', cleanupAndBlock, true);
        };
        // Use capture phase to fire before any stopPropagation in the cover
        setTimeout(() => {
          document.addEventListener('mousedown', cleanup, true);
          window.addEventListener('contextmenu', cleanupAndBlock, true);
        }, 0);
      });

      container.appendChild(header);
    }

    if (!isCollapsed) {
      let prevBlank = false;
      for (const line of group.lines) {
        // Collapse a run of blank lines to a SINGLE *visible* blank line: keep one
        // line of separation, never collapse to consecutive (an empty div renders at
        // 0px → invisible → content looks adjacent), and never add lines.
        if (stripAnsi(line).trim() === '') {
          if (prevBlank) continue; // run already represented by one gap line
          prevBlank = true;
          const gap = document.createElement('div');
          gap.style.cssText = 'white-space:pre-wrap;min-height:1.4em;';
          container.appendChild(gap);
          continue;
        }
        prevBlank = false;
        const lineDiv = document.createElement('div');
        if (group.type === 'thinking') {
          // Thinking BODY text: Claude renders it dim-grey via ANSI, which
          // renderAnsiLine would honor and override any defaultColor. Strip the
          // ANSI and force a bright purple so the text itself reads clearly.
          // (The THINKING label/marker color is separate — SECTION_COLORS.thinking.)
          lineDiv.style.cssText = 'white-space:pre-wrap;';
          lineDiv.style.color = THINKING_TEXT_COLOR;
          lineDiv.textContent = stripAnsi(line);
        } else if (group.type === 'user' || group.type === 'inject') {
          lineDiv.style.cssText = 'white-space:pre-wrap;';
          lineDiv.style.color = '#c0caf5';
          lineDiv.textContent = stripAnsi(line);
        } else {
          lineDiv.style.cssText = 'white-space:pre-wrap;';
          const defaultColor = group.type === 'tool' ? color : '#c0caf5';
          renderAnsiLine(line, lineDiv, defaultColor);
        }
        linkifyElement(lineDiv);
        linkifyRefsInElement(lineDiv);
        container.appendChild(lineDiv);
      }
    }

    return container;
  }, []);

  const currentGroups = (): SectionGroup[] => {
    if (transcriptBlocksRef.current.length > 0) {
      return [
        ...transcriptBlocksToGroups(transcriptBlocksRef.current, toolViewsRef.current),
        ...liveGroupsRef.current,
        ...terminalChromeRef.current,
      ];
    }
    return [
      ...groupIntoSections(prevLinesRef.current, stickyClassRef.current, sectionLabelsRef.current),
      ...terminalChromeRef.current,
    ];
  };

  const groupIsCollapsed = (group: SectionGroup): boolean => {
    const override = defaultOverrideRef.current[group.type];
    const defaultCollapsed = sectionDefaultCollapsed(group.type, override, group.label);
    return collapsedRef.current.has(group.key) ? !defaultCollapsed : defaultCollapsed;
  };

  const visibleCurrentGroups = (): SectionGroup[] => currentGroups().filter((group) => (
    group.type === 'separator'
    || group.type === 'statusbar'
    || (group.type !== 'cont' && filtersRef.current[group.type])
  ));

  const estimatedGroupHeight = (group: SectionGroup): number => {
    if (group.type === 'separator') return 22;
    if (group.type === 'statusbar') return Math.max(22, group.lines.length * 18.2 + 8);
    const bodyLines = groupIsCollapsed(group) ? 0 : Math.max(1, group.lines.length);
    const headerHeight = group.label ? 24 : 0;
    return 8 + headerHeight + bodyLines * 18.2;
  };

  const heightCacheKey = (group: SectionGroup): string => (
    `${group.key}@${group.version}@${groupIsCollapsed(group) ? 'c' : 'e'}`
  );

  /** Render only the cards intersecting the viewport plus two viewports of
   *  overscan. Top/bottom spacers preserve the full scroll range. */
  const renderVirtualWindow = useCallback((force = false) => {
    const cover = coverRef.current;
    if (!cover) return;

    const groups = visibleCurrentGroups();
    // A transient empty scrape must not erase a previously good surface. An empty
    // result caused by the user's filters is intentional and may render empty.
    const anyFilterEnabled = Object.values(filtersRef.current).some(Boolean);
    if (groups.length === 0 && anyFilterEnabled && renderedKeysRef.current.length > 0) return;

    const viewportHeight = Math.max(1, cover.clientHeight || cover.getBoundingClientRect().height || 600);
    const heights = groups.map((group) => (
      measuredHeightRef.current.get(heightCacheKey(group)) ?? estimatedGroupHeight(group)
    ));
    const estimatedTotal = heights.reduce((sum, height) => sum + height, 0);
    const wantedScrollTop = autoScrollRef.current
      ? Math.max(0, estimatedTotal - viewportHeight)
      : cover.scrollTop;
    const range = calculateVirtualWindow(heights, wantedScrollTop, viewportHeight, viewportHeight * 2);

    if (!force
        && virtualRangeRef.current.start === range.start
        && virtualRangeRef.current.end === range.end) {
      return;
    }

    const anchorOffset = wantedScrollTop - range.beforePx;
    const fragment = document.createDocumentFragment();
    const topSpacer = document.createElement('div');
    topSpacer.dataset.virtualSpacer = 'top';
    topSpacer.style.cssText = `height:${range.beforePx}px;pointer-events:none;`;
    fragment.appendChild(topSpacer);

    const mounted: Array<{ group: SectionGroup; element: HTMLElement }> = [];
    const previousVersions = renderedVersionsRef.current;
    for (let index = range.start; index < range.end; index++) {
      const group = groups[index];
      const element = renderSectionDom(
        group,
        collapsedRef.current,
        group.msgId,
        group.timestamp ? new Date(group.timestamp).getTime() : undefined,
        group.turnNum,
      );
      if (!element) continue;
      fragment.appendChild(element);
      mounted.push({ group, element });

      if (hasRenderedTranscriptRef.current && group.origin !== 'terminal') {
        const previousVersion = previousVersions.get(group.key);
        if (previousVersion === undefined) highlightTranscriptChange(element, group.type, 'inserted');
        else if (previousVersion !== group.version) highlightTranscriptChange(element, group.type, 'updated');
      }
    }

    const bottomSpacer = document.createElement('div');
    bottomSpacer.dataset.virtualSpacer = 'bottom';
    bottomSpacer.style.cssText = `height:${range.afterPx}px;pointer-events:none;`;
    fragment.appendChild(bottomSpacer);

    virtualRenderGuardRef.current = true;
    cover.replaceChildren(fragment);

    let measurementChanged = false;
    for (const { group, element } of mounted) {
      const style = window.getComputedStyle(element);
      const measured = element.getBoundingClientRect().height
        + (parseFloat(style.marginTop) || 0)
        + (parseFloat(style.marginBottom) || 0);
      const key = heightCacheKey(group);
      const previous = measuredHeightRef.current.get(key);
      if (measured > 0 && (previous === undefined || Math.abs(previous - measured) > 0.5)) {
        measuredHeightRef.current.set(key, measured);
        measurementChanged = true;
      }
    }

    // Recalculate spacer heights from the new measurements without rendering any
    // additional cards. Preserve the first mounted card as the scroll anchor.
    const correctedHeights = groups.map((group) => (
      measuredHeightRef.current.get(heightCacheKey(group)) ?? estimatedGroupHeight(group)
    ));
    const correctedBefore = correctedHeights.slice(0, range.start).reduce((sum, height) => sum + height, 0);
    const correctedRendered = correctedHeights.slice(range.start, range.end).reduce((sum, height) => sum + height, 0);
    const correctedTotal = correctedHeights.reduce((sum, height) => sum + height, 0);
    topSpacer.style.height = `${correctedBefore}px`;
    bottomSpacer.style.height = `${Math.max(0, correctedTotal - correctedBefore - correctedRendered)}px`;

    if (autoScrollRef.current) {
      cover.scrollTop = cover.scrollHeight;
      autoScrollRef.current = true;
    } else {
      cover.scrollTop = Math.max(0, correctedBefore + anchorOffset);
    }

    virtualRangeRef.current = { start: range.start, end: range.end };
    renderedKeysRef.current = mounted.map(({ group }) => group.key);
    renderedVersionsRef.current = new Map(groups.map((group) => [group.key, group.version]));
    const activeHeightKeys = new Set(groups.map(heightCacheKey));
    for (const key of measuredHeightRef.current.keys()) {
      if (!activeHeightKeys.has(key)) measuredHeightRef.current.delete(key);
    }
    hasRenderedTranscriptRef.current = hasRenderedTranscriptRef.current
      || groups.some((group) => group.origin !== 'terminal');
    virtualRenderGuardRef.current = false;

    if (measurementChanged && windowRenderRafRef.current === null) {
      windowRenderRafRef.current = requestAnimationFrame(() => {
        windowRenderRafRef.current = null;
        renderWindowRef.current(true);
      });
    }
  }, [renderSectionDom]);

  renderWindowRef.current = renderVirtualWindow;

  /** A rebuild now means recalculating only the visible card window. */
  const fullRebuild = useCallback(() => renderVirtualWindow(true), [renderVirtualWindow]);
  const rebuildFromCache = fullRebuild;

  const refresh = useCallback(async () => {
    if (!enabled || !sessionName || !containerRef.current || !overlayRef.current) return;
    if (refreshInFlightRef.current) {
      refreshPendingRef.current = true;
      return;
    }
    refreshInFlightRef.current = true;

    try {
      const api = window.uai;
      if (!api?.terminal?.captureScrollback) return;

    let result: any = null;
    const captureOutputEpoch = terminalOutputEpochRef.current;
    try {
      result = await api.terminal.captureScrollback(
        sessionName,
        hasInitialCaptureRef.current ? REFRESH_CAPTURE_LINES : INITIAL_CAPTURE_LINES,
      );
    } catch {
      return;
    }

    if (!result?.ok || !result.text) return;
    hasInitialCaptureRef.current = true;
    // Clean ANSI noise (OSC hyperlinks + bare CSI codes with no ESC byte) once at
    // ingest so both change-detection and parsing/display see leak-free text.
    // ESC-prefixed SGR is preserved for renderAnsiLine's coloring.
    const text = stripNoise(result.text);
    const normalized = text.trimEnd();

    const overlay = overlayRef.current;
    if (!overlay) return;

    const screen = containerRef.current?.querySelector('.xterm-screen');
    if (!screen) return;
    const sr = screen.getBoundingClientRect();
    const cr = containerRef.current!.getBoundingClientRect();

    let cover = coverRef.current;
    if (!cover) {
      cover = document.createElement('div');
      cover.style.cssText = [
        'position:absolute',
        'background:var(--memorex-bg, #0a0c10)',
        'z-index:10',
        'pointer-events:auto',
        'overflow-y:auto',
        'overflow-x:hidden',
        'box-sizing:border-box',
        "font-family:var(--memorex-font, 'JetBrains Mono', 'Menlo', monospace)",
        'font-size:var(--memorex-font-size, 13px)',
        'line-height:var(--memorex-line-height, 1.4)',
        'padding:0',
        'cursor:text',
        'user-select:text',
        '-webkit-user-select:text',
      ].join(';');

      // Scroll tracking for auto-scroll
      cover.addEventListener('scroll', () => {
        if (virtualRenderGuardRef.current) return;
        autoScrollRef.current = cover!.scrollHeight - cover!.scrollTop - cover!.clientHeight < 50;
        if (windowRenderRafRef.current === null) {
          windowRenderRafRef.current = requestAnimationFrame(() => {
            windowRenderRafRef.current = null;
            renderWindowRef.current(false);
          });
        }
      });
      cover.addEventListener('wheel', (e: WheelEvent) => e.stopPropagation(), { passive: true });

      // Keyboard: Cmd+C copies from overlay, everything else goes to terminal
      cover.tabIndex = -1;
      cover.addEventListener('keydown', (e: KeyboardEvent) => {
        const selection = window.getSelection();
        const hasSelection = selection && selection.toString().length > 0;

        // Mirror the raw terminal's explicit history navigation while the Memorex
        // cover owns focus. Without this, the browser's default Home/ArrowUp action
        // can move the cover to the top without updating our bottom-follow state.
        if ((e.metaKey || e.ctrlKey) && (e.key === 'Home' || e.key === 'ArrowUp')) {
          e.preventDefault();
          cover!.scrollTop = 0;
          autoScrollRef.current = false;
          termRef.current?.scrollToTop();
          return;
        }
        if ((e.metaKey || e.ctrlKey) && (e.key === 'End' || e.key === 'ArrowDown')) {
          e.preventDefault();
          cover!.scrollTop = cover!.scrollHeight;
          autoScrollRef.current = true;
          termRef.current?.scrollToBottom();
          renderWindowRef.current(true);
          return;
        }

        // Cmd+C with selection: copy from overlay
        if (hasSelection && (e.metaKey || e.ctrlKey) && e.key === 'c') {
          e.preventDefault();
          navigator.clipboard.writeText(selection.toString());
          return;
        }

        // Cmd+A: select all text in the overlay
        if ((e.metaKey || e.ctrlKey) && e.key === 'a') {
          e.preventDefault();
          const range = document.createRange();
          range.selectNodeContents(cover!);
          const sel = window.getSelection();
          sel?.removeAllRanges();
          sel?.addRange(range);
          return;
        }

        // If text is selected, swallow non-modifier keys to preserve selection
        if (hasSelection) return;

        // Forward to terminal: focus xterm AND replay the keystroke via the PTY
        // so the current keypress isn't lost during focus transfer.
        const term = termRef.current;
        if (term) {
          let terminalInput: string | null = null;
          // Replay the first key directly: the cover owns focus, so
          // merely focusing xterm would otherwise discard the key that answered a
          // permission/decision dialog.
          if (e.ctrlKey && e.key.length === 1) {
            const charCode = e.key.toLowerCase().charCodeAt(0) - 96;  // Ctrl+A=1, Ctrl+U=21, etc.
            if (charCode > 0 && charCode < 27) {
              terminalInput = String.fromCharCode(charCode);
            }
          } else if (!e.metaKey) {
            const special: Record<string, string> = {
              Enter: '\r', Escape: '\x1b', Tab: '\t', Backspace: '\x7f',
              ArrowUp: '\x1b[A', ArrowDown: '\x1b[B', ArrowRight: '\x1b[C', ArrowLeft: '\x1b[D',
              Delete: '\x1b[3~', Home: '\x1b[H', End: '\x1b[F', PageUp: '\x1b[5~', PageDown: '\x1b[6~',
            };
            terminalInput = special[e.key] ?? (e.key.length === 1 ? e.key : null);
          }
          if (terminalInput !== null) {
            e.preventDefault();
            window.uai?.terminal?.input?.(sessionId, terminalInput);
          }
          term.focus();
          setTimeout(() => refreshRef.current(), 150);
        }
      });

      // Also handle copy event as backup
      cover.addEventListener('copy', (e: ClipboardEvent) => {
        const selection = window.getSelection();
        const text = selection?.toString();
        if (text) {
          e.preventDefault();
          e.clipboardData?.setData('text/plain', text);
        }
      });

      // Mouse events: capture all, ensure cover gets focus for keyboard
      for (const evt of ['mousemove', 'click', 'dblclick', 'contextmenu'] as const) {
        cover.addEventListener(evt, (e: Event) => {
          e.stopPropagation();
        });
      }

      // mousedown: focus cover for keyboard events, allow native text selection
      cover.addEventListener('mousedown', (e: MouseEvent) => {
        e.stopPropagation();
        cover!.focus();
      });

      // mouseup: allow propagation — stopping it breaks drag-end handlers
      // (e.g., PromptBox resize handle release) that listen on document.

      if (contentHostRef.current) {
        contentHostRef.current.replaceChildren(cover);
      }
      coverRef.current = cover;
    }

    // Remember the user's state before geometry or DOM updates can generate their
    // own scroll events. A layout-induced jump to 0 is not a user scroll-up.
    const shouldRestoreBottom = autoScrollRef.current;
    const restoreBottomAfterLayout = () => {
      if (!shouldRestoreBottom) return;
      const restore = () => {
        if (coverRef.current !== cover) return;
        cover.scrollTop = cover.scrollHeight;
        autoScrollRef.current = true;
      };
      restore();
      requestAnimationFrame(restore);
    };

    // Always update cover position and dimensions — even if content unchanged
    cover.style.left = '0px';
    cover.style.top = `${sr.top - cr.top}px`;
    cover.style.width = `${cr.width}px`;

    // Calculate dimensions
    const allLines = text.split('\n').map((l: string) => l.trimEnd());
    // For boundary DETECTION only, ignore a trailing run of blank lines: captureScrollback
    // can append many empty rows below the content (observed: 52 blanks under Anvil's
    // prompt), which defeats findPromptAreaStart's bottom-up scan → the whole buffer is
    // treated as settled content and the live prompt formats as a submitted user message.
    // Geometry + sectioning below MUST keep using the FULL `allLines` — those blank rows
    // are part of the on-screen live region, so trimming them from the length would size
    // the cover too short and slide the overlay down over the live prompt (regression).
    let detEnd = allLines.length;
    while (detEnd > 0 && allLines[detEnd - 1] === '') detEnd--;
    const detLines = detEnd < allLines.length ? allLines.slice(0, detEnd) : allLines;
    const promptStart = findPromptAreaStart(detLines);
    const term = termRef.current;
    const cellHeight = term?.rows ? sr.height / term.rows : 13 * 1.4;

    // Establish Transcript authority before deriving the first terminal live
    // region. This bootstrap read cannot overtake a provisional because none
    // exists yet; it prevents an initial full-history capture from being treated
    // as live merely because the settled baseline had not loaded.
    if (!hasTranscriptBaselineRef.current) {
      await refreshTranscriptCache(false);
    }

    const terminalKinds = detLines.map((line) => isVerbLine(line) ? 'boundary' : classifyLine(line));

    // Only the unfinished terminal turn may create provisional cards. Settled
    // history is already represented by Transcript and must never be reintroduced
    // by a mount repaint or a deep bounded scrape.
    const terminalMessageEnd = Math.max(0, promptStart);
    const isChrome = (line: string) => isVerbLine(line) || isTaskChromeLine(line);
    const fallbackTerminalLines = allLines
      .slice(0, terminalMessageEnd)
      .filter((line) => !isChrome(line));
    const fallbackPrivate = findPrivateLines(fallbackTerminalLines);
    const visibleFallbackLines = fallbackPrivate.size > 0
      ? fallbackTerminalLines.filter((_: string, index: number) => !fallbackPrivate.has(index))
      : fallbackTerminalLines;
    if (visibleFallbackLines.length > 0 || prevLinesRef.current.length === 0) {
      prevLinesRef.current = visibleFallbackLines;
    }

    const currentRegionStart = currentTerminalRegionStart(
      allLines,
      terminalMessageEnd,
      transcriptBlocksRef.current.length > 0,
    );
    const currentRegionLines = allLines.slice(currentRegionStart, terminalMessageEnd);
    const currentMessageLines = currentRegionLines.filter((line) => !isChrome(line));
    const currentPrivate = findPrivateLines(currentMessageLines);
    const visibleCurrentMessageLines = currentPrivate.size > 0
      ? currentMessageLines.filter((_: string, index: number) => !currentPrivate.has(index))
      : currentMessageLines;
    const allTerminalGroups = terminalMessageGroups(
      visibleCurrentMessageLines,
      stickyClassRef.current,
      sectionLabelsRef.current,
    );

    const previousTerminalGroups = terminalGroupsSnapshotRef.current;
    const previousSnapshotTranscriptRevision = terminalSnapshotTranscriptRevisionRef.current;
    const terminalDelta = !hasTerminalSnapshotRef.current
      ? {
          updatedTail: null,
          appended: [],
          anchored: true,
        }
      : previousTerminalGroups.length === 0
      ? {
          updatedTail: null,
          appended: allTerminalGroups,
          anchored: true,
        }
      : terminalCardDelta(
          previousTerminalGroups,
          allTerminalGroups,
          (group) => group.terminalFingerprint || '',
        );
    if (terminalDelta.anchored) {
      const previousTailFingerprint = previousTerminalGroups.at(-1)?.terminalFingerprint;
      const previousTailVersion = previousTerminalGroups.at(-1)?.version;
      const provisionalTail = liveGroupsRef.current.at(-1);
      const appendedCandidates = [...terminalDelta.appended];
      if (terminalDelta.updatedTail
          && provisionalTail
          && provisionalTail.terminalFingerprint === previousTailFingerprint) {
        liveGroupsRef.current[liveGroupsRef.current.length - 1] = {
          ...terminalDelta.updatedTail,
          key: provisionalTail.key,
          origin: 'terminal',
          expectedSettledCardCount: provisionalTail.expectedSettledCardCount,
        };
      } else if (terminalDelta.updatedTail
          && previousTailFingerprint
          && terminalDelta.updatedTail.terminalFingerprint === previousTailFingerprint
          && terminalDelta.updatedTail.version !== previousTailVersion
          && shouldSeedUpdatedTerminalTail(
            terminalDelta.updatedTail.terminalFingerprint,
            previousSnapshotTranscriptRevision,
            transcriptRevisionRef.current,
            settledTerminalFingerprintsRef.current,
          )) {
        // On a cold mount, the bounded unfinished-turn snapshot may already hold
        // settled cards from earlier in that turn. Do not seed them. If the tail
        // subsequently changes, it is the actual streaming card and can safely
        // become the first provisional.
        appendedCandidates.unshift(terminalDelta.updatedTail);
      }
      const currentTurnCandidates = filterTerminalCandidatesForTurn(
        appendedCandidates,
        settledTerminalFingerprintsRef.current,
      );
      const firstExpectedSettledCardCount = transcriptBlocksRef.current.length
        + liveGroupsRef.current.length
        + 1;
      const appendedWithKeys = currentTurnCandidates
        .map((group, index) => ({
          ...group,
          key: `provisional:${nextProvisionalIdRef.current++}`,
          origin: 'terminal',
          expectedSettledCardCount: firstExpectedSettledCardCount + index,
        } satisfies SectionGroup));
      liveGroupsRef.current = appendUniqueProvisionalCards(
        liveGroupsRef.current,
        appendedWithKeys,
        (group) => group.terminalFingerprint || '',
        (existing, replacement) => ({
          ...replacement,
          key: existing.key,
          expectedSettledCardCount: existing.expectedSettledCardCount,
        }),
      );
    }
    // A lost terminal-only anchor (capture eviction/reflow) resets only the scrape
    // baseline. It never rebuilds, slices, or discards the persistent card chain.
    terminalGroupsSnapshotRef.current = allTerminalGroups;
    // Store the revision that was current when this terminal snapshot was
    // ingested. If Transcript advances below, the next terminal repaint can see
    // that the old tail crossed the settlement boundary and must not be re-added.
    terminalSnapshotTranscriptRevisionRef.current = transcriptRevisionRef.current;
    hasTerminalSnapshotRef.current = true;

    // Terminal events must enter the provisional FIFO before the completed JSONL
    // record consumes that FIFO. Reading Transcript after the terminal snapshot
    // preserves that causal order even when the zero-delay file watcher wins the race.
    const terminalChangedDuringCapture = terminalOutputEpochRef.current !== captureOutputEpoch;
    // The terminal snapshot was ingested first, so a changed Transcript can settle
    // its FIFO head now. Never postpone Transcript reads until output pauses: a busy
    // stream may be continuous for minutes, and the old deferral loop accumulated a
    // large provisional backlog while starving settlement.
    const transcriptChanged = await refreshTranscriptCache(false);
    const blocks = transcriptBlocksRef.current;

    const terminalRegionClosed = allTerminalGroups.length === 0
      && currentRegionStart > 0
      && allLines.slice(0, terminalMessageEnd).some(isCompletedVerbLine);
    if (terminalRegionClosed) {
      const now = Date.now();
      if (closedTerminalSinceRef.current === null) closedTerminalSinceRef.current = now;
      // Remove only cards individually proven consumed first. Transcript can
      // append several records over successive watcher events after the terminal
      // closes; clearing the whole FIFO on the first changed revision would hide
      // later records during normal JSONL lag.
      liveGroupsRef.current = liveGroupsRef.current.filter((group) => (
        !provisionalReachedSettlement(group.expectedSettledCardCount, blocks.length)
        && (!group.terminalFingerprint
          || !settledTerminalFingerprintsRef.current.has(group.terminalFingerprint))
      ));
      const closedForMs = now - closedTerminalSinceRef.current;
      if (shouldDrainClosedTerminalProvisionals(
        true,
        closedForMs,
      )) {
        liveGroupsRef.current = [];
      }
    } else {
      closedTerminalSinceRef.current = null;
    }

    // Compact terminal tool cards are a display-only carve-out. Identity checks here
    // choose a folded rendering; they never place the settled/live split.
    if (blocks.length > 0) {
      const mountedToolViews = collectTerminalToolViews(
        blocks,
        detLines,
        terminalKinds,
        terminalMessageEnd,
      );
      for (const [key, lines] of mountedToolViews) {
        toolViewsRef.current.set(key, lines);
      }
    }

    const visibleRows = term?.rows ?? Math.max(1, Math.round(sr.height / cellHeight));
    let visibleTrailingBlankRows = 0;
    const visibleRowElements = containerRef.current?.querySelectorAll('.xterm-rows > div');
    if (visibleRowElements && visibleRowElements.length > 0) {
      for (let i = visibleRowElements.length - 1; i >= 0; i--) {
        if ((visibleRowElements[i].textContent || '').trim() !== '') break;
        visibleTrailingBlankRows++;
      }
    }
    const activeVerbLineIndex = visibleActiveVerbLineIndex(
      allLines,
      currentRegionStart,
      terminalMessageEnd,
      visibleRows,
      visibleTrailingBlankRows,
    );
    const hasActiveVerb = activeVerbLineIndex !== null;
    // While a verb is active, the real xterm rows from that animated line through
    // the prompt/status remain visible below the cover. Rendering a static chrome
    // card inside Memorex would duplicate and freeze the animation.
    const chromeLines = hasActiveVerb ? [] : detLines.slice(terminalMessageEnd);
    terminalChromeRef.current = chromeLines.length > 0 ? [{
      type: 'statusbar',
      label: '',
      lines: chromeLines,
      startIdx: terminalMessageEnd,
      key: 'terminal-chrome',
      origin: 'terminal',
      version: sectionVersion({ type: 'statusbar', lines: chromeLines }),
    }] : [];

    // Memorex owns the full viewport while idle. During active thinking only, yield
    // the bottom rows beginning at the real animated verb line so the terminal's
    // spinner, task rows, prompt, and status remain live rather than being replaced
    // by a static overlay copy.
    const liveFormattedLines = blocks.length > 0
      ? liveGroupsRef.current.reduce((sum, group) => sum + group.lines.length, 0)
      : 0;
    const liveAreaLines = visibleTerminalGapLineCount(
      allLines,
      activeVerbLineIndex,
      visibleRows,
      visibleTrailingBlankRows,
    );
    const liveAreaHeight = Math.min(sr.height, liveAreaLines * cellHeight);
    const coverHeight = Math.max(0, sr.height - liveAreaHeight);
    cover.style.height = `${coverHeight}px`;

    // Detect dimension changes — force content rebuild when layout changes
    const dims = `${Math.round(cr.width)}|${Math.round(sr.height)}|${Math.round(sr.top - cr.top)}|${Math.round(coverHeight)}`;
    if (dims !== lastDimsRef.current) {
      lastDimsRef.current = dims;
      lastTextRef.current = '';
    }

    // ── Memorex State API ──────────────────────────────────────────────
    // Exposes overlay state for AI diagnostic queries and future viewport tree.
    // Query via: window.__memorex (DevTools), uai:memorex:state (IPC),
    // or chrome-control execute_javascript.
    const sections = currentGroups();
    const memorexSnapshot: Record<string, any> = {
      sessionId,
      sessionName,
      platform,
      enabled,
      // Boundary analysis
      boundaries: {
        totalLines: allLines.length,
        promptStart,
        // Line-based seam fields are retained as null for diagnostic consumers;
        // the PM-locked seam is the persistent settled/provisional card link.
        contentEnd: null,
        markerContentEnd: null,
        settledTranscriptMsgId: blocks.at(-1)?.lastMsgId ?? 0,
        settledTranscriptCardCount: blocks.length,
        terminalCardCount: allTerminalGroups.length,
        firstLiveCardOrdinal: blocks.length,
        liveCardCount: liveGroupsRef.current.length,
        firstLiveExpectedSettledCardCount:
          liveGroupsRef.current[0]?.expectedSettledCardCount ?? null,
        terminalDeltaAppended: terminalDelta.appended.length,
        terminalDeltaAnchored: terminalDelta.anchored,
        terminalOutputEpoch: terminalOutputEpochRef.current,
        terminalChangedDuringCapture,
        terminalRegionClosed,
        hasActiveVerb,
        activeVerbLineIndex,
        closedTerminalAgeMs: closedTerminalSinceRef.current === null
          ? 0
          : Date.now() - closedTerminalSinceRef.current,
        transcriptChanged,
        liveAreaLines,
        liveFormattedLines,
        coverHeightPx: coverHeight,
        normalCoverHeightPx: Math.max(0, sr.height),
        cellHeightPx: cellHeight,
        termRows: term?.rows,
      },
      // Rendered sections — what the overlay is actually showing
      sections: sections.map(g => ({
        type: g.type,
        label: g.label,
        key: g.key,
        origin: g.origin,
        lineCount: g.lines.length,
        startIdx: g.startIdx,
        firstLine: stripAnsi(g.lines[0] || '').trim().slice(0, 100),
        lastLine: stripAnsi(g.lines[g.lines.length - 1] || '').trim().slice(0, 100),
        collapsed: collapsedRef.current.has(g.key),
      })),
      sectionCount: sections.length,
      renderedKeys: renderedKeysRef.current,
      virtualWindow: {
        start: virtualRangeRef.current.start,
        end: virtualRangeRef.current.end,
        mountedCardCount: renderedKeysRef.current.length,
        totalCardCount: sections.length,
      },
      // Persistent-chain seam diagnostics: settled Transcript tail followed by
      // the provisional FIFO. No terminal-history origin participates.
      boundaryZone: sections
        .slice(Math.max(0, blocks.length - 3), blocks.length + 3)
        .map((group, i) => {
        const idx = Math.max(0, blocks.length - 3) + i;
        const plain = stripAnsi(group.lines[0] || '').trim();
        return {
          idx,
          text: plain.slice(0, 120),
          classification: group.type,
          isVerbLine: false,
          isMarkerPattern: /^\S\s/.test(plain),
          role: idx < blocks.length
            ? 'SETTLED_TRANSCRIPT'
            : group.type === 'statusbar'
              ? 'TERMINAL_CHROME'
              : 'PROVISIONAL_TERMINAL',
        };
      }),
      lastOverlayLine: blocks.length > 0
        ? stripAnsi(blocks.at(-1)?.lines.at(-1) || '').trim().slice(0, 120)
        : null,
      firstLiveTerminalLine: liveGroupsRef.current.length > 0
        ? stripAnsi(liveGroupsRef.current[0].lines[0] || '').trim().slice(0, 120)
        : null,
      firstVisibleTerminalLine: activeVerbLineIndex !== null
        ? stripAnsi(allLines[activeVerbLineIndex] || '').trim().slice(0, 120)
        : null,
      // Timestamp
      updatedAt: new Date().toISOString(),
    };
    // Hidden mounted tabs retain queryable state under their exact tracking ID.
    // The active-session shortcut remains for compatibility, but diagnostics must
    // not select by a non-unique display name (two live/stopped sessions can both
    // be called "Relay").
    const diagnosticWindow = window as any;
    diagnosticWindow.__memorexSessions ??= {};
    diagnosticWindow.__memorexSessions[sessionId] = memorexSnapshot;
    if (active) diagnosticWindow.__memorex = memorexSnapshot;
    // ── Geometry snapshot + recorder frame (Codex MAJOR 7) ───────────────
    // The cover-blanket bug (todo_0385) is likely a DOM geometry/mask issue,
    // invisible in boundary text alone — so capture the actual rects. Best-effort:
    // the recorder must NEVER break the overlay.
    try {
      const coverRect = cover.getBoundingClientRect();
      const cs = window.getComputedStyle(cover);
      const geometry = {
        coverRectTop: Math.round(coverRect.top),
        coverRectHeight: Math.round(coverRect.height),
        coverStyleHeight: cover.style.height,
        screenTop: Math.round(sr.top),
        screenHeight: Math.round(sr.height),
        containerTop: Math.round(cr.top),
        containerHeight: Math.round(cr.height),
        fillerPx: 0,
        scrollTop: Math.round(cover.scrollTop),
        zIndex: cs.zIndex,
        pointerEvents: cs.pointerEvents,
        cellHeightPx: Math.round(cellHeight),
        termRows: term?.rows,
      };
      memorexSnapshot.geometry = geometry;
      // Idle full-height and bounded active-verb exposure are intentional. The
      // actionable anomaly is a visible cover with source content but no
      // formatted cards.
      const overlayVisible = sr.height > 20 && cellHeight > 1;
      const anomalyFull = active
        && overlayVisible
        && sections.length === 0
        && (blocks.length > 0 || terminalMessageEnd > 0);
      recordMemorexFrame({
        ts: Date.now(),
        sessionId,
        boundaries: memorexSnapshot.boundaries,
        geometry,
        firstLiveTerminalLine: memorexSnapshot.firstLiveTerminalLine,
        anomalyFull,
      });
      // Auto-persist to disk on a detected anomaly (debounced) — no DevTools needed.
      if (anomalyFull) {
        const now = Date.now();
        if (now - lastAnomalySaveRef.current > 10000) {
          lastAnomalySaveRef.current = now;
          saveAnomalyToDisk(sessionId, 'auto:blank-cover', {
            // Bound the scrape: the boundary/cover live in the bottom rows, so the
            // tail is all we need — the full scrollback can be 14k+ lines (MBs).
            frames: memorexRecBuffer.slice(-100),
            capturedText: allLines.slice(-1500).join('\n'),
            boundaryZone: memorexSnapshot.boundaryZone,
          });
        }
      }
    } catch { /* recorder is best-effort — never break the overlay */ }

    // Also update the viewport state ref so the tree sees the same data
    memorexStateRef.current = memorexSnapshot;

    // Skip DOM work only when BOTH the terminal and settled transcript are unchanged.
    if (normalized === lastTextRef.current
        && transcriptRevisionRef.current === lastTranscriptRenderRevisionRef.current) {
      // Geometry may still have changed even when text did not.
      restoreBottomAfterLayout();
      return;
    }
    lastTextRef.current = normalized;
    lastTranscriptRenderRevisionRef.current = transcriptRevisionRef.current;

    // Rebuild from the new content
    rebuildFromCache();

    // The cover height and card layout settle after this refresh. Restore once now
    // and once on the next frame so the final layout owns the scroll.
    restoreBottomAfterLayout();
    } finally {
      refreshInFlightRef.current = false;
      if (refreshPendingRef.current) {
        refreshPendingRef.current = false;
        setTimeout(() => refreshRef.current(), 0);
      }
    }
  }, [enabled, active, sessionName, sessionId, platform, containerRef, termRef, rebuildFromCache, refreshTranscriptCache]);

  // Keep ref current so event listeners can call latest refresh
  refreshRef.current = refresh;

  // Reset state when session changes
  useEffect(() => {
    lastTextRef.current = '';
    hasInitialCaptureRef.current = false;
    lastTranscriptRenderRevisionRef.current = '';
    prevLinesRef.current = [];
    stickyClassRef.current.clear();
    transcriptBlocksRef.current = [];
    transcriptRevisionRef.current = '';
    transcriptLoadGenerationRef.current++;
    toolViewsRef.current.clear();
    liveGroupsRef.current = [];
    terminalGroupsSnapshotRef.current = [];
    hasTerminalSnapshotRef.current = false;
    terminalSnapshotTranscriptRevisionRef.current = '';
    settledTerminalFingerprintsRef.current.clear();
    closedTerminalSinceRef.current = null;
    nextProvisionalIdRef.current = 1;
    hasTranscriptBaselineRef.current = false;
    terminalOutputEpochRef.current = 0;
    terminalChromeRef.current = [];
    renderedKeysRef.current = [];
    renderedVersionsRef.current.clear();
    measuredHeightRef.current.clear();
    virtualRangeRef.current = { start: -1, end: -1 };
    hasRenderedTranscriptRef.current = false;
    // Scroll state belongs to a session. A new/remounted session starts at its live
    // bottom rather than inheriting "scrolled up" from the previous session.
    autoScrollRef.current = true;
    if (coverRef.current) {
      coverRef.current.replaceChildren();
    }
  }, [sessionName, sessionId]);

  useEffect(() => () => {
    const sessions = (window as any).__memorexSessions;
    if (sessions) delete sessions[sessionId];
  }, [sessionId]);

  // One-key manual anomaly capture (⌘⇧M) for the ACTIVE session's overlay — the
  // reliable path when the auto-detector misses a transient (dumps to disk, no
  // DevTools). Only the focused/active overlay listens so it captures the session
  // the user is actually looking at.
  useEffect(() => {
    if (!active) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey && e.shiftKey && (e.key === 'm' || e.key === 'M')) {
        e.preventDefault();
        saveAnomalyToDisk(sessionId, 'manual:hotkey', {
          frames: memorexRecBuffer.slice(-150),
          capturedText: lastTextRef.current.split('\n').slice(-1500).join('\n'),
          boundaryZone: (window as any).__memorex?.boundaryZone,
          geometry: (window as any).__memorex?.geometry,
        });
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [active, sessionId]);

  useEffect(() => {
    if (!enabled) {
      if (timerRef.current) clearInterval(timerRef.current);
      coverRef.current = null;
      lastTextRef.current = '';
      lastTranscriptRenderRevisionRef.current = '';
      terminalChromeRef.current = [];
      renderedKeysRef.current = [];
      renderedVersionsRef.current.clear();
      virtualRangeRef.current = { start: -1, end: -1 };
      hasRenderedTranscriptRef.current = false;
      autoScrollRef.current = true;
      if (windowRenderRafRef.current !== null) cancelAnimationFrame(windowRenderRafRef.current);
      windowRenderRafRef.current = null;
      if (contentHostRef.current) contentHostRef.current.replaceChildren();
      return;
    }
    // Canonicalize scroll before the first capture. captureScrollback returns the
    // live buffer tail, but the geometry pass reads the xterm '.xterm-rows' DOM
    // (visibleRows / visibleTrailingBlankRows) — and those reflect the terminal's
    // CURRENT scroll viewport. If the terminal was scrolled up when Memorex is
    // enabled, the DOM rows describe mid-history while the captured text is the live
    // bottom; that mismatch corrupts the active-verb/gap math and can leave a
    // full-height cover with no proven live region (the "black screen on enable while
    // scrolled up" bug). Snapping the covered terminal to its live bottom makes the
    // DOM agree with the capture. Invariant 11: never inherit a stale scroll state.
    termRef.current?.scrollToBottom();
    refresh();
    const pollMs = active ? POLL_ACTIVE_MS : POLL_BACKGROUND_MS;
    timerRef.current = setInterval(refresh, pollMs);

    // The watcher event is the immediate path, but refresh always ingests terminal
    // cards before Transcript so a completed record cannot outrun its provisional.
    // These short warmup retries cover mount/order races.
    const warmupTimers = [250, 800, 2000].map((ms) => setTimeout(() => refreshRef.current(), ms));
    const unsubTranscript = window.uai?.transcript?.onUpdated
      ? window.uai.transcript.onUpdated((ref) => { if (ref === sessionId) refreshRef.current(); })
      : null;
    let outputRefreshTimer: ReturnType<typeof setTimeout> | null = null;
    const unsubTerminalData = active && window.uai?.terminal?.onData
      ? window.uai.terminal.onData((sid) => {
          if (sid !== sessionId) return;
          terminalOutputEpochRef.current++;
          if (outputRefreshTimer) return;
          // Bound capture work during token streaming while staying much faster than
          // the one-second safety poll. The terminal snapshot remains the parser.
          outputRefreshTimer = setTimeout(() => {
            outputRefreshTimer = null;
            refreshRef.current();
          }, 250);
        })
      : null;

    // Watch for container/terminal resize to refresh the overlay dimensions.
    // DEBOUNCED: a resize (e.g. dragging the PromptBox handle) fires the observer
    // continuously, and each refresh() forces another terminal capture and layout pass
    // (a dimension change clears lastTextRef on purpose, to reflow to the new width).
    // Un-debounced that was a storm of repeated rebuilds → multi-second lag. A
    // short trailing debounce collapses the whole drag into ONE rebuild after it
    // settles; semantics are unchanged (still reflows, still never blanks).
    let resizeObserver: ResizeObserver | null = null;
    let resizeTimer: ReturnType<typeof setTimeout> | null = null;
    const container = containerRef.current;
    if (container) {
      resizeObserver = new ResizeObserver(() => {
        if (resizeTimer) clearTimeout(resizeTimer);
        resizeTimer = setTimeout(() => { resizeTimer = null; refreshRef.current(); }, 80);
      });
      resizeObserver.observe(container);
      const screen = container.querySelector('.xterm-screen');
      if (screen) resizeObserver.observe(screen);
    }

    return () => {
      if (timerRef.current) clearInterval(timerRef.current);
      warmupTimers.forEach(clearTimeout);
      unsubTranscript?.();
      unsubTerminalData?.();
      if (outputRefreshTimer) clearTimeout(outputRefreshTimer);
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeObserver?.disconnect();
    };
  }, [enabled, active, refresh, refreshTranscriptCache, sessionId]);

  // Filter and collapse handlers — full rebuild since visibility changes
  const toggleFilter = useCallback((type: string) => {
    filtersRef.current[type] = !filtersRef.current[type];
    fullRebuild();
  }, [fullRebuild]);

  const collapseAllOfType = useCallback((type: string) => {
    // Set override so future sections of this type are also collapsed
    defaultOverrideRef.current[type] = true;
    // Clear per-section toggles so all use the new default
    const groups = currentGroups();
    for (const group of groups) {
      if (group.type !== type) continue;
      collapsedRef.current.delete(group.key);
    }
    fullRebuild();
  }, [fullRebuild]);

  const expandAllOfType = useCallback((type: string) => {
    // Set override so future sections of this type are also expanded
    defaultOverrideRef.current[type] = false;
    // Clear per-section toggles so all use the new default
    const groups = currentGroups();
    for (const group of groups) {
      if (group.type !== type) continue;
      collapsedRef.current.delete(group.key);
    }
    fullRebuild();
  }, [fullRebuild]);

  // Force re-render to pick up filter state for button styling
  const [, forceUpdate] = useState(0);

  if (!enabled) return null;

  const platformLabel = platform === 'CODEX' ? 'Codex' : platform === 'GEMINI' ? 'Gemini' : 'Claude';
  const filterTypes = [
    { key: 'user', label: 'You', color: SECTION_COLORS.user },
    { key: 'inject', label: 'Comms', color: SECTION_COLORS.inject },
    { key: 'assistant', label: platformLabel, color: SECTION_COLORS.assistant },
    { key: 'tool', label: 'Tools', color: SECTION_COLORS.tool },
    { key: 'thinking', label: 'Thinking', color: SECTION_COLORS.thinking },
  ];

  return (
    <div
      ref={overlayRef}
      data-memorex-session-id={sessionId}
      data-memorex-session-name={sessionName}
      data-memorex-active={active ? 'true' : 'false'}
      style={{
        position: 'absolute',
        top: 0, left: 0, right: 0, bottom: 0,
        pointerEvents: 'none',
        zIndex: 10,
      }}
    >
      {/* Content host for imperative DOM — separate from React filter bar */}
      <div ref={contentHostRef} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, pointerEvents: 'none' }} />

      {/* Filter bar */}
      <div style={{
        position: 'absolute', top: 0, right: 16, zIndex: 11,
        display: 'flex', gap: '4px', padding: '4px 8px',
        background: 'rgba(10,12,16,0.95)', borderRadius: '0 0 6px 6px',
        pointerEvents: 'auto', fontSize: '10px',
        fontFamily: "'JetBrains Mono', monospace",
        border: '1px solid #1a1d28', borderTop: 'none',
      }}>
        {filterTypes.map(({ key, label, color }) => {
          const isOn = filtersRef.current[key];
          return (
            <div key={key} style={{ display: 'flex', alignItems: 'center', gap: '2px' }}>
              <button
                onClick={() => { toggleFilter(key); forceUpdate((n: number) => n + 1); }}
                style={{
                  background: isOn ? 'rgba(255,255,255,0.08)' : 'transparent',
                  border: `1px solid ${color}`,
                  color: isOn ? color : '#414868',
                  padding: '2px 6px', borderRadius: '3px', cursor: 'pointer',
                  fontSize: '10px', fontFamily: 'inherit', opacity: isOn ? 1 : 0.4,
                }}
              >
                {label}
              </button>
              <button
                onClick={() => {
                  const override = defaultOverrideRef.current[key];
                  const currentlyCollapsed = sectionDefaultCollapsed(key, override);
                  if (currentlyCollapsed) { expandAllOfType(key); } else { collapseAllOfType(key); }
                  forceUpdate((n: number) => n + 1);
                }}
                title={`Toggle all ${label}`}
                style={{
                  background: 'transparent', border: 'none', color: '#8890b0',
                  cursor: 'pointer', fontSize: '14px', padding: '0 2px',
                }}
              >{(() => {
                  const override = defaultOverrideRef.current[key];
                  const currentlyCollapsed = sectionDefaultCollapsed(key, override);
                  return currentlyCollapsed ? '\u25B6' : '\u25BC';
                })()}</button>
            </div>
          );
        })}
      </div>
    </div>
  );
};

export default TerminalFormatOverlay;

// Exported for testing
export {
  classifyLine,
  currentTerminalRegionStart,
  filterTerminalCandidatesForTurn,
  findPrivateLines,
  findPromptAreaStart,
  groupIntoSections,
  isActiveVerbLine,
  isCompletedVerbLine,
  provisionalReachedSettlement,
  sectionDefaultCollapsed,
  shouldDrainClosedTerminalProvisionals,
  shouldSeedUpdatedTerminalTail,
  stripAnsi,
  terminalOpeningFingerprint,
  visibleActiveVerbLineIndex,
  visibleTerminalGapLineCount,
};
export type { Section, SectionGroup };
