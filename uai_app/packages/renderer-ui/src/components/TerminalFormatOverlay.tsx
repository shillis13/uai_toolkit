/**
 * TerminalFormatOverlay — Formatted view of tmux scrollback.
 *
 * Opaque panel covers the terminal. Captures tmux scrollback every second,
 * formats lines by Unicode markers, writes into the panel.
 *
 * Mouse: overlay captures all mouse events (scroll, selection).
 * Keyboard: all keys pass through to terminal except Cmd+C (copies from overlay).
 * Security: all text rendered via textContent.
 */

import { useEffect, useCallback, useRef, useState } from 'react';
import { useViewport } from '../viewport';
import type { Terminal } from 'xterm';
import { dedupConsecutiveBlocks } from './memorex-dedup';
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

/** Lightweight message metadata from JSONL for section annotation */
interface TranscriptMeta {
  msgId: number;        // sequential message number from JSONL
  turnNum: number;      // turn number (user prompt = new turn)
  type: string;         // user, response, tool_use, tool_result, thinking
  timestamp: string;    // ISO timestamp
  toolName?: string;
  contentPreview: string; // first ~80 chars for matching
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

/** Find where the message content ends — the index where the overlay's live
 *  region begins.
 *
 *  Spec (PianoMan): "The overlay stops one above the thinking/verb line; failing
 *  to find that, one above the prompt's top separator."
 *
 *  The verb line is the topmost element of the live tail. Below it sit the task
 *  summary, task list, blank lines, and the prompt — all outside the overlay.
 *  So: scan up from the prompt for the verb line and stop AT it (slice excludes
 *  it). If none is found, stop at the prompt's top separator.
 *
 *  Returns an index `c` such that lines[0..c-1] are overlay content and lines[c..]
 *  are the live terminal region. */
/** Max size of the live tail above the prompt: verb line + task summary/list +
 *  blank lines. The live-tail verb line always sits within this many lines of the
 *  prompt; anything farther up is a stale marker from a previous turn. */
const LIVE_TAIL_MAX_LINES = 20;

function findContentEnd(lines: string[], promptStart: number, visibleRows?: number): number {
  // Boundary = the LOWEST (most recent) verb line _within the live tail_ — active OR
  // completed (per PianoMan's spec: "when the verb line is encountered, nothing below
  // it is part of a message; the line above it is the last line of the overlay").
  // Detection relies on the gerund-tied ellipsis / "for <dur>" structure (see
  // isVerbLine), NOT a bare ellipsis.
  //
  // The scan is BOUNDED to a live-tail window just above the prompt. Completed verb
  // lines persist in scrollback (a settled buffer holds several). An unbounded scan
  // would latch onto a STALE verb line from a previous turn that the current turn's
  // streaming content pushed far above the viewport; then liveAreaLines saturates to
  // visibleRows, the cover collapses to 0px, and the whole overlay blanks until the
  // turn ends. Clamping the window keeps the boundary within the lower viewport.
  // No verb line in the window ⇒ fall back to promptStart (cover the full visible
  // region — the SAFE direction; blanking is never acceptable).
  // Returns index c: lines[0..c-1] = overlay content, lines[c..] = live region.
  const rows = visibleRows && visibleRows > 0 ? visibleRows : 9999;
  const window = Math.max(4, Math.min(LIVE_TAIL_MAX_LINES, rows - 12));
  const stop = Math.max(0, promptStart - window);
  for (let i = promptStart - 1; i >= stop; i--) {
    if (isVerbLine(lines[i])) return i;  // lowest live-tail verb line = boundary
  }
  return promptStart;  // no live-tail verb line — stop one above the prompt-area top separator
}

// A Claude Code interactive DECISION area (tool-permission "Do you want to proceed?",
// plan approval, etc.) REPLACES the normal ──── ❯ ──── prompt block while the CLI waits
// for a choice: there are no separators, so findPromptAreaStart would otherwise fall
// through to `return lines.length` and the WHOLE viewport (the live dialog included)
// gets covered — the user can't see the prompt they must answer without toggling
// Memorex off. The discriminator (per PianoMan's spec, verified against Broken-Clock):
// the dialog's structural lines are indented by ONE space, so the option's ❯ sits at
// COLUMN 1 — whereas a real user/prompt ❯ sits at COLUMN 0. Detect the dialog and return
// its TOP so it stays in the raw (uncovered) live tail. The dialog disappears once
// answered, so it only ever needs this live-region treatment (no settled-section type).
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
  /** Where this section came from. 'terminal' = scraped/classified from the live
   *  terminal (all current sections). 'synthetic' = reconstructed from the JSONL to
   *  heal a markerless/dropped section (reconciler, todo_0392 — not yet emitted). */
  origin: 'terminal' | 'synthetic';
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
      current = { type: section, label, lines: [lines[i]], startIdx: i, key, origin: 'terminal' };
    } else if (section === 'separator') {
      if (current) groups.push(current);
      groups.push({ type: 'separator', label: '', lines: [lines[i]], startIdx: i, key: `sep-${i}`, origin: 'terminal' });
      current = null;
    } else {
      // Continuation line — add to current section
      if (current) {
        current.lines.push(lines[i]);
      } else {
        // Orphan continuation — parent marker scrolled off buffer
        current = { type: 'cont', label: '', lines: [lines[i]], startIdx: i, key: `cont-${i}`, origin: 'terminal' };
      }
    }
  }
  if (current) groups.push(current);

  // Clean up re-render scrollback corruption: drop verbatim block-duplications
  // within each section (separators are single lines — nothing to dedup).
  for (const g of groups) {
    if (g.type === 'separator') continue;
    if (g.lines.length >= 6) g.lines = dedupConsecutiveBlocks(g.lines);
  }

  return groups;
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
  const fillerPxRef = useRef(0);  // last bottom-mask height, guards redundant re-renders
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const lastTextRef = useRef('');
  const prevLinesRef = useRef<string[]>([]);
  const memorexStateRef = useRef<Record<string, unknown>>({});
  const autoScrollRef = useRef(true);
  const refreshRef = useRef<() => void>(() => {});
  // Debounce for auto-persisting Memorex anomalies to disk (todo_0385/0392).
  const lastAnomalySaveRef = useRef(0);
  // Sticky section classifications: once a ⏺ line is identified as 'tool',
  // that classification sticks across polls even if streaming changes the line content.
  // Key: stripped line text prefix (first 60 chars), Value: section type
  const stickyClassRef = useRef<Map<string, Section>>(new Map());
  // Track last section key from previous render — used for blink protection
  const lastSectionKeyRef = useRef<string | null>(null);
  // Transcript cache — lightweight JSONL metadata for section annotation
  const transcriptCacheRef = useRef<TranscriptMeta[]>([]);
  const transcriptTimerRef = useRef<ReturnType<typeof setInterval> | null>(null);
  // Map from section key → matched transcript metadata
  const sectionMetaRef = useRef<Map<string, { msgId: number; turnNum: number; timestamp: string }>>(new Map());
  // Per-type default override: when user clicks expand/collapse triangle for a type,
  // all future sections of that type inherit the override instead of the hardcoded default.
  // null = use hardcoded default, true = collapsed, false = expanded
  const defaultOverrideRef = useRef<Record<string, boolean | null>>({
    user: null, inject: null, assistant: null, tool: null, thinking: null,
  });

  // ── Viewport registration — makes Memorex a queryable tree citizen ──
  useViewport('memorex_view', () => ({
    visible: enabled,
    label: `memorex: ${sessionName}`,
    state: memorexStateRef.current,
    children: [],
  }));

  /** Fetch JSONL transcript metadata, match to sections, and inject metadata in-place */
  const refreshTranscriptCache = useCallback(async () => {
    const api = window.uai;
    if (!api?.transcript?.read) return;
    try {
      const result = await api.transcript.read(sessionName, sessionId, 'structured');
      if (!result?.ok || !result.days) return;
      const metas: TranscriptMeta[] = [];
      // Turn/Msg numbers MUST match the Transcript pane (TranscriptViewer):
      //  • Turn = the backend's `turn.number` (read_jsonl._assign_turn_numbers — prologue
      //    is turn 0, each real user prompt opens a new turn). A local 1..N counter drifts
      //    from Transcript whenever a prologue/turn-0 exists.
      //  • Msg = a flat 1-indexed counter over every message in days→turns→messages order,
      //    identical to TranscriptViewer's `id = msgId++`.
      let msgId = 0;
      let fallbackTurn = 0;
      for (const day of result.days as any[]) {
        for (const turn of (day.turns ?? [])) {
          fallbackTurn++;
          const turnNum = (typeof turn.number === 'number') ? turn.number : fallbackTurn;
          for (const m of (turn.messages ?? [])) {
            msgId++;
            metas.push({
              msgId,
              turnNum,
              type: m.type ?? m.role ?? 'unknown',
              timestamp: m.timestamp ?? '',
              toolName: m.tool_name,
              contentPreview: (m.content ?? '').slice(0, 80),
            });
          }
        }
      }
      transcriptCacheRef.current = metas;
      matchSectionsToTranscript();

      // Inject metadata into existing DOM elements in-place (no rebuild needed)
      const cover = coverRef.current;
      if (cover) {
        for (let i = 0; i < cover.children.length; i++) {
          const el = cover.children[i] as HTMLElement;
          const key = el.dataset.sectionKey;
          if (!key) continue;
          const meta = sectionMetaRef.current.get(key);
          if (!meta) continue;
          // Find or create the metadata span in the header
          const header = el.querySelector('[data-meta]') as HTMLElement | null;
          if (header) {
            const parts: string[] = [];
            parts.push(meta.turnNum !== undefined ? `Turn #${meta.turnNum} Msg #${meta.msgId}` : `Msg #${meta.msgId}`);
            if (meta.timestamp) {
              const d = new Date(meta.timestamp);
              const mo = (d.getMonth() + 1).toString().padStart(2, '0');
              const dy = d.getDate().toString().padStart(2, '0');
              const h = d.getHours().toString().padStart(2, '0');
              const m = d.getMinutes().toString().padStart(2, '0');
              const s = d.getSeconds().toString().padStart(2, '0');
              parts.push(`${mo}-${dy} ${h}:${m}:${s}`);
            }
            header.textContent = parts.join('  ');
          }
        }
      }
    } catch { /* non-critical — timestamps just won't appear */ }
  }, [sessionName, sessionId]);

  /** Match overlay sections to transcript messages by walking backward from the end.
   *  The overlay only has recent scrollback; the transcript has full history.
   *  Matching from the end aligns the most recent sections correctly. */
  const matchSectionsToTranscript = useCallback(() => {
    const groups = groupIntoSections(prevLinesRef.current, stickyClassRef.current, sectionLabelsRef.current);
    const metas = transcriptCacheRef.current;
    if (metas.length === 0) return;

    const sectionToMsgType: Record<string, string[]> = {
      user: ['user'],
      inject: ['user', 'injected'],  // inter-session prompts land as on-chain user / injected records
      assistant: ['response'],
      tool: ['tool_use', 'tool_result'],
      thinking: ['thinking'],
    };

    // Filter to matchable sections (skip separators, cont)
    const matchable = groups.filter(g => g.type !== 'separator' && g.type !== 'cont' && sectionToMsgType[g.type]);

    // Walk backward through both sequences
    const metaMap = new Map<string, { msgId: number; turnNum: number; timestamp: string }>();
    let metaIdx = metas.length - 1;

    for (let i = matchable.length - 1; i >= 0; i--) {
      const group = matchable[i];
      const matchTypes = sectionToMsgType[group.type];

      // Find previous matching message in transcript (walking backward)
      while (metaIdx >= 0 && !matchTypes.includes(metas[metaIdx].type)) {
        metaIdx--;
      }
      if (metaIdx >= 0) {
        metaMap.set(group.key, {
          msgId: metas[metaIdx].msgId,
          turnNum: metas[metaIdx].turnNum,
          timestamp: metas[metaIdx].timestamp,
        });
        metaIdx--;
      }
    }
    sectionMetaRef.current = metaMap;
  }, []);
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
      return sepDiv;
    }

    // Skip orphan cont groups (completion markers, blank lines between sections)
    // and filtered-out section types
    if (group.type === 'cont') return null;
    if (!filters[group.type]) return null;

    const sectionKey = group.key;
    const typeOverride = defaultOverrideRef.current[group.type];
    const defaultCollapsed = typeOverride !== null && typeOverride !== undefined
      ? typeOverride
      : (group.type === 'tool' || group.type === 'thinking');
    const isCollapsed = collapsed.has(sectionKey) ? !defaultCollapsed : defaultCollapsed;

    const color = SECTION_COLORS[group.type] || SECTION_COLORS.cont;
    const bg = SECTION_BG[group.type] || SECTION_BG.cont;

    const container = document.createElement('div');
    container.style.cssText = `border-left:2px solid ${color};background:${bg};margin-top:8px;padding-left:4px;`;
    container.dataset.section = group.type;
    container.dataset.sectionKey = sectionKey;
    container.dataset.lineCount = String(group.lines.length);

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
      const groupLines = group.lines;
      const groupType = group.type;
      header.addEventListener('click', (e) => {
        e.stopPropagation();
        if (collapsed.has(key)) collapsed.delete(key);
        else collapsed.add(key);
        const parent = header.parentElement;
        if (parent) {
          const nowCollapsed = collapsed.has(key) ? !defaultCollapsed : defaultCollapsed;
          chevron.textContent = nowCollapsed ? '\u25B6' : '\u25BC';
          if (nowCollapsed) {
            // Hide content children
            for (let ci = 1; ci < parent.children.length; ci++) {
              (parent.children[ci] as HTMLElement).style.display = 'none';
            }
          } else {
            if (parent.children.length <= 1) {
              // Content was never created (built collapsed) — create it now
              for (const line of groupLines) {
                const lineDiv = document.createElement('div');
                if (groupType === 'thinking') {
                  lineDiv.style.cssText = 'white-space:pre-wrap;';
                  lineDiv.style.color = THINKING_TEXT_COLOR;
                  lineDiv.textContent = stripAnsi(line);
                } else if (groupType === 'user' || groupType === 'inject') {
                  lineDiv.style.cssText = 'white-space:pre-wrap;';
                  lineDiv.style.color = '#c0caf5';
                  lineDiv.textContent = stripAnsi(line);
                } else {
                  lineDiv.style.cssText = 'white-space:pre-wrap;';
                  const dc = groupType === 'tool' ? color : '#c0caf5';
                  renderAnsiLine(line, lineDiv, dc);
                }
                linkifyElement(lineDiv);
                linkifyRefsInElement(lineDiv);
                parent.appendChild(lineDiv);
              }
            } else {
              // Content exists — show it
              for (let ci = 1; ci < parent.children.length; ci++) {
                (parent.children[ci] as HTMLElement).style.display = '';
              }
            }
          }
        }
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

  /** Get section metadata from transcript cache */
  const getSectionMeta = (key: string): { msgId: number; turnNum: number; timestamp: string } | undefined => {
    return sectionMetaRef.current.get(key);
  };

  /** Full rebuild — used by filter/collapse toggles and session changes */
  const fullRebuild = useCallback(() => {
    const cover = coverRef.current;
    if (!cover || prevLinesRef.current.length === 0) return;

    // Preserve scroll position across rebuild
    const scrollBefore = cover.scrollTop;
    const scrollHeightBefore = cover.scrollHeight;

    const groups = groupIntoSections(prevLinesRef.current, stickyClassRef.current, sectionLabelsRef.current);
    const collapsed = collapsedRef.current;

    cover.replaceChildren();
    const keys: string[] = [];

    let firstRealSection = 0;
    while (firstRealSection < groups.length && groups[firstRealSection].type === 'cont') firstRealSection++;

    for (let g = firstRealSection; g < groups.length; g++) {
      const group = groups[g];
      const meta = getSectionMeta(group.key);
      const el = renderSectionDom(group, collapsed,
        meta?.msgId,
        meta?.timestamp ? new Date(meta.timestamp).getTime() : undefined, meta?.turnNum);
      if (el) { cover.appendChild(el); keys.push(group.key); }
    }
    renderedKeysRef.current = keys;

    // Restore scroll position — keep the same visual position
    // If user was at the bottom, stay at bottom; otherwise maintain offset from bottom
    const scrollHeightAfter = cover.scrollHeight;
    if (autoScrollRef.current) {
      cover.scrollTop = scrollHeightAfter;
    } else {
      // Keep the same distance from the bottom
      const distFromBottom = scrollHeightBefore - scrollBefore;
      cover.scrollTop = scrollHeightAfter - distFromBottom;
    }
  }, [renderSectionDom]);

  /** Incremental update — only rebuild the last section and append new ones */
  const incrementalUpdate = useCallback(() => {
    const cover = coverRef.current;
    if (!cover || prevLinesRef.current.length === 0) return;

    const groups = groupIntoSections(prevLinesRef.current, stickyClassRef.current, sectionLabelsRef.current);
    const collapsed = collapsedRef.current;

    // Skip orphan cont groups at the start
    let firstRealSection = 0;
    while (firstRealSection < groups.length && groups[firstRealSection].type === 'cont') firstRealSection++;

    // Filter to groups that will actually render (renderSectionDom returns null for cont)
    const visibleGroups = groups.slice(firstRealSection).filter(g =>
      g.type === 'separator' || (g.type !== 'cont' && filtersRef.current[g.type])
    );
    const newKeys = visibleGroups.map(g => g.key);
    const oldKeys = renderedKeysRef.current;

    // Find how many leading sections are unchanged
    let commonPrefix = 0;
    while (commonPrefix < oldKeys.length && commonPrefix < newKeys.length &&
           oldKeys[commonPrefix] === newKeys[commonPrefix]) {
      commonPrefix++;
    }

    // If everything matches and count is equal, only the last section may have new content
    if (commonPrefix === oldKeys.length && commonPrefix === newKeys.length && commonPrefix > 0) {
      // Last section may have grown — only replace if line count changed
      const lastIdx = commonPrefix - 1;
      const lastChild = cover.children[lastIdx] as HTMLElement | undefined;
      if (lastChild) {
        const group = visibleGroups[lastIdx];
        const oldLineCount = lastChild.dataset.lineCount;
        if (oldLineCount !== String(group.lines.length)) {
          const meta = getSectionMeta(group.key);
          const el = renderSectionDom(group, collapsed, meta?.msgId,
            meta?.timestamp ? new Date(meta.timestamp).getTime() : undefined, meta?.turnNum);
          if (el) { cover.replaceChild(el, lastChild); }
        }
      }
      return;
    }

    // Blink protection: if sections shrank (last marker blinked away) and no
    // new marker appeared after it, keep the existing DOM — don't remove sections.
    // Only update the last rendered section's content (new cont lines may have arrived).
    if (newKeys.length < oldKeys.length && commonPrefix === newKeys.length) {
      // All new keys match the prefix of old keys — tail keys disappeared (blink).
      // Update the last visible section in case it grew with new cont lines.
      const lastVisibleIdx = newKeys.length - 1;
      if (lastVisibleIdx >= 0 && lastVisibleIdx < (cover.children.length)) {
        const lastChild = cover.children[lastVisibleIdx] as HTMLElement;
        const group = visibleGroups[lastVisibleIdx];
        if (lastChild && group) {
          const oldLineCount = lastChild.dataset.lineCount;
          if (oldLineCount !== String(group.lines.length)) {
            const meta = getSectionMeta(group.key);
            const el = renderSectionDom(group, collapsed, meta?.msgId,
              meta?.timestamp ? new Date(meta.timestamp).getTime() : undefined, meta?.turnNum);
            if (el) { cover.replaceChild(el, lastChild); }
          }
        }
      }
      return;
    }

    // Sections diverge at commonPrefix — remove from there, append new
    while (cover.children.length > commonPrefix) {
      cover.removeChild(cover.lastChild!);
    }

    for (let i = commonPrefix; i < visibleGroups.length; i++) {
      const group = visibleGroups[i];
      const meta = getSectionMeta(group.key);
      const el = renderSectionDom(group, collapsed, meta?.msgId,
        meta?.timestamp ? new Date(meta.timestamp).getTime() : undefined, meta?.turnNum);
      if (el) cover.appendChild(el);
    }

    renderedKeysRef.current = newKeys;
  }, [renderSectionDom]);

  /** Main rebuild entry — uses incremental when possible, full when needed */
  const rebuildFromCache = useCallback(() => {
    if (renderedKeysRef.current.length === 0) {
      fullRebuild();
    } else {
      incrementalUpdate();
    }
  }, [fullRebuild, incrementalUpdate]);

  const refresh = useCallback(async () => {
    if (!enabled || !sessionName || !containerRef.current || !overlayRef.current) return;

    const api = window.uai;
    if (!api?.terminal?.captureScrollback) return;

    let result: any = null;
    try {
      result = await api.terminal.captureScrollback(sessionName, 50000);
    } catch {
      return;
    }

    if (!result?.ok || !result.text) return;
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
        autoScrollRef.current = cover!.scrollHeight - cover!.scrollTop - cover!.clientHeight < 50;
      });

      // Keyboard: Cmd+C copies from overlay, everything else goes to terminal
      cover.tabIndex = -1;
      cover.addEventListener('keydown', (e: KeyboardEvent) => {
        const selection = window.getSelection();
        const hasSelection = selection && selection.toString().length > 0;

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
          term.focus();
          // Replay control characters (Ctrl+key) directly via PTY input
          if (e.ctrlKey && e.key.length === 1) {
            const charCode = e.key.toLowerCase().charCodeAt(0) - 96;  // Ctrl+A=1, Ctrl+U=21, etc.
            if (charCode > 0 && charCode < 27) {
              window.uai?.terminal?.input?.(sessionId, String.fromCharCode(charCode));
            }
          }
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
      for (const evt of ['wheel', 'mousemove', 'click', 'dblclick', 'contextmenu'] as const) {
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
    const visibleRows = term?.rows ?? Math.max(1, Math.round(sr.height / cellHeight));

    // Content ends at the verb line (if present) or the separator.
    // The verb line and everything below it (task list, completion markers,
    // separator, prompt, status) are fixed live terminal — not overlay content.
    // visibleRows bounds the live-tail scan so a stale verb line far up the
    // scrollback can't become the boundary and collapse the cover (see findContentEnd).
    const contentEnd = findContentEnd(detLines, promptStart, visibleRows);
    // The live region's height is measured against the VISIBLE viewport, not the
    // full scrollback. `allLines` spans the whole scrollback (hundreds of lines),
    // but only the bottom `term.rows` are on screen. Counting the raw scrollback
    // distance (allLines.length - contentEnd) over-counts whenever a long tool
    // result or streamed response sits below the verb line — liveAreaHeight then
    // exceeds sr.height, the cover collapses to 0px, and the formatted overlay
    // vanishes mid-stream (showing raw terminal) until the tail shrinks. Clamp the
    // live tail to the visible rows so the overlay only yields to genuinely
    // on-screen live content. (visibleRows computed above.)
    // …but `allLines` can ALSO carry trailing blank rows BEYOND the visible viewport
    // (terminal padding below the last on-screen row) — and turning the tmux status
    // bar OFF increased that padding. Those phantom rows inflate the live-area count
    // and pull the cover UP over real content (the "overlay too short by a line or two"
    // seen after status-off: the last content line leaks out raw below the cover).
    // Cap the buffer's trailing blanks to what's actually ON SCREEN (from the live xterm
    // DOM). On-screen trailing blanks (e.g. a band of empty rows under the prompt) are
    // preserved — only genuinely off-screen padding is discounted. (todo_0450.)
    let bufTrailBlanks = 0;
    for (let i = allLines.length - 1; i >= 0 && allLines[i] === ''; i--) bufTrailBlanks++;
    let domTrailBlanks = 0;
    const trailRows = containerRef.current?.querySelectorAll('.xterm-rows > div');
    if (trailRows && trailRows.length) {
      for (let i = trailRows.length - 1; i >= 0; i--) {
        if ((trailRows[i].textContent || '').trim() === '') domTrailBlanks++;
        else break;
      }
    }
    const offscreenPad = Math.max(0, bufTrailBlanks - domTrailBlanks);
    const liveAreaLines = Math.min(Math.max(0, (allLines.length - offscreenPad) - contentEnd), visibleRows);
    const liveAreaHeight = liveAreaLines * cellHeight;
    cover.style.height = `${Math.max(0, sr.height - liveAreaHeight)}px`;

    // ── Bottom mask (no-redraw "spacing below the statusline" fix) ──────────
    // A space-needing interaction (typing "/" for the command menu, then
    // backspacing it away; or a pane-size mismatch) can leave the CLI's status
    // footer drawn HIGH with a band of blank rows below it, down to the tmux
    // status bar. We must NOT fix this by forcing the CLI to redraw — that
    // re-renders an overflowing response and corrupts the scrollback (interleaved
    // blanks, duplication, sometimes a dropped ⏺ marker). Instead we mask the dead
    // band at the overlay layer: measure the contiguous blank rows directly above
    // the tmux status bar (the last on-screen row) and cover them + the status bar
    // with a filler, so the terminal reads as ending cleanly at the footer.
    // Measured from the live xterm DOM (not the capture) so it reflects exactly
    // what's on screen. Threshold ≥3 so the normal 0–1 trailing blank is untouched.
    {
      const rowEls = containerRef.current?.querySelectorAll('.xterm-rows > div');
      let bandRows = 0;
      if (rowEls && rowEls.length > 1) {
        // Skip the last row (tmux status bar), count contiguous blank rows above it.
        for (let i = rowEls.length - 2; i >= 0; i--) {
          if ((rowEls[i].textContent || '').trim() === '') bandRows++;
          else break;
        }
      }
      // Clamp so the mask can never climb into live content (cap at ~40% of the pane).
      const maxBand = Math.floor(visibleRows * 0.4);
      const mask = bandRows >= 3 ? Math.min(bandRows, maxBand) + 1 : 0; // +1 covers the tmux bar
      const px = Math.round(mask * cellHeight);
      if (px !== fillerPxRef.current) {
        fillerPxRef.current = px;
        setFillerPx(px);
      }
    }

    // Detect dimension changes — force content rebuild when layout changes
    const dims = `${Math.round(cr.width)}|${Math.round(sr.height)}|${Math.round(sr.top - cr.top)}`;
    if (dims !== lastDimsRef.current) {
      lastDimsRef.current = dims;
      lastTextRef.current = '';
    }

    // ── Memorex State API ──────────────────────────────────────────────
    // Exposes overlay state for AI diagnostic queries and future viewport tree.
    // Query via: window.__memorex (DevTools), uai:memorex:state (IPC),
    // or chrome-control execute_javascript.
    const sections = groupIntoSections(
      allLines.slice(0, contentEnd),
      stickyClassRef.current,
      sectionLabelsRef.current,
    );
    (window as any).__memorex = {
      sessionId,
      sessionName,
      platform,
      enabled,
      // Boundary analysis
      boundaries: {
        totalLines: allLines.length,
        promptStart,
        contentEnd,
        liveAreaLines,
        coverHeightPx: Math.max(0, sr.height - liveAreaHeight),
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
      // Boundary zone — lines around contentEnd for diagnosing overlap
      boundaryZone: allLines.slice(Math.max(0, contentEnd - 3), Math.min(allLines.length, promptStart + 2)).map((l: string, i: number) => {
        const idx = Math.max(0, contentEnd - 3) + i;
        const plain = stripAnsi(l).trim();
        return {
          idx,
          text: plain.slice(0, 120),
          classification: classifyLine(l),
          isVerbLine: isVerbLine(l),
          isMarkerPattern: /^\S\s/.test(plain),
          role: idx < contentEnd ? 'OVERLAY' : idx === contentEnd ? 'CONTENT_END' : idx === promptStart ? 'PROMPT_START' : 'LIVE_TERMINAL',
        };
      }),
      // Last overlay line vs first live terminal line — the overlap diagnostic
      lastOverlayLine: contentEnd > 0 ? stripAnsi(allLines[contentEnd - 1] || '').trim().slice(0, 120) : null,
      firstLiveTerminalLine: contentEnd < allLines.length ? stripAnsi(allLines[contentEnd] || '').trim().slice(0, 120) : null,
      // Timestamp
      updatedAt: new Date().toISOString(),
    };
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
        fillerPx: fillerPxRef.current,
        scrollTop: Math.round(cover.scrollTop),
        zIndex: cs.zIndex,
        pointerEvents: cs.pointerEvents,
        cellHeightPx: Math.round(cellHeight),
        termRows: term?.rows,
      };
      (window as any).__memorex.geometry = geometry;
      // Anomaly: the cover reaches (near) full screen height while ~no live area
      // remains — i.e. it is blanketing the prompt/status region.
      // GUARD: only meaningful when the overlay is actually visible/laid-out. An
      // inactive (display:none) tab reports sr.height=0 / cellHeight=0, which made
      // `coverPx(0) >= sr.height(0)` trivially true and spammed false captures.
      const overlayVisible = sr.height > 20 && cellHeight > 1;
      const coverPx = Math.max(0, sr.height - liveAreaHeight);
      const anomalyFull = overlayVisible && (liveAreaLines <= 1 || coverPx >= sr.height - cellHeight);
      recordMemorexFrame({
        ts: Date.now(),
        sessionId,
        boundaries: (window as any).__memorex.boundaries,
        geometry,
        firstLiveTerminalLine: (window as any).__memorex.firstLiveTerminalLine,
        anomalyFull,
      });
      // Auto-persist to disk on a detected anomaly (debounced) — no DevTools needed.
      if (anomalyFull) {
        const now = Date.now();
        if (now - lastAnomalySaveRef.current > 10000) {
          lastAnomalySaveRef.current = now;
          saveAnomalyToDisk(sessionId, 'auto:cover-full', {
            // Bound the scrape: the boundary/cover live in the bottom rows, so the
            // tail is all we need — the full scrollback can be 14k+ lines (MBs).
            frames: memorexRecBuffer.slice(-100),
            capturedText: allLines.slice(-1500).join('\n'),
            boundaryZone: (window as any).__memorex.boundaryZone,
          });
        }
      }
    } catch { /* recorder is best-effort — never break the overlay */ }

    // Also update the viewport state ref so the tree sees the same data
    memorexStateRef.current = (window as any).__memorex;

    // Skip content rebuild if text unchanged
    if (normalized === lastTextRef.current) return;
    lastTextRef.current = normalized;

    // Content lines stop at the verb line (or separator if no verb line)
    const contentLines = allLines.slice(0, contentEnd);

    // Strip [/PRIVATE] thinking blocks
    const privateSkip = findPrivateLines(contentLines);
    const newLines = privateSkip.size > 0
      ? contentLines.filter((_: string, i: number) => !privateSkip.has(i))
      : contentLines;

    prevLinesRef.current = newLines;

    // Rebuild from the new content
    rebuildFromCache();

    if (autoScrollRef.current) {
      cover.scrollTop = cover.scrollHeight;
    }
  }, [enabled, sessionName, containerRef, termRef]);

  // Keep ref current so event listeners can call latest refresh
  refreshRef.current = refresh;

  // Reset state when session changes
  useEffect(() => {
    lastTextRef.current = '';
    prevLinesRef.current = [];
    stickyClassRef.current.clear();
    lastSectionKeyRef.current = null;
    transcriptCacheRef.current = [];
    sectionMetaRef.current.clear();
    renderedKeysRef.current = [];
    if (coverRef.current) {
      coverRef.current.replaceChildren();
    }
  }, [sessionName]);

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
      if (transcriptTimerRef.current) clearInterval(transcriptTimerRef.current);
      coverRef.current = null;
      lastTextRef.current = '';
      prevLinesRef.current = [];
      renderedKeysRef.current = [];
      sectionMetaRef.current.clear();
      if (contentHostRef.current) contentHostRef.current.replaceChildren();
      return;
    }
    refresh();
    const pollMs = active ? POLL_ACTIVE_MS : POLL_BACKGROUND_MS;
    timerRef.current = setInterval(refresh, pollMs);

    // Fetch transcript metadata periodically (every 10s) for section annotations
    refreshTranscriptCache();
    transcriptTimerRef.current = setInterval(refreshTranscriptCache, 10000);

    // Watch for container/terminal resize to refresh the overlay dimensions.
    // DEBOUNCED: a resize (e.g. dragging the PromptBox handle) fires the observer
    // continuously, and each refresh() forces a full recapture+reparse+DOM rebuild
    // (a dimension change clears lastTextRef on purpose, to reflow to the new width).
    // Un-debounced that was a storm of full 50k-line rebuilds → multi-second lag. A
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
      if (transcriptTimerRef.current) clearInterval(transcriptTimerRef.current);
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeObserver?.disconnect();
    };
  }, [enabled, active, refresh, refreshTranscriptCache]);

  // Filter and collapse handlers — full rebuild since visibility changes
  const toggleFilter = useCallback((type: string) => {
    filtersRef.current[type] = !filtersRef.current[type];
    fullRebuild();
  }, [fullRebuild]);

  const collapseAllOfType = useCallback((type: string) => {
    // Set override so future sections of this type are also collapsed
    defaultOverrideRef.current[type] = true;
    // Clear per-section toggles so all use the new default
    const groups = groupIntoSections(prevLinesRef.current, undefined, sectionLabelsRef.current);
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
    const groups = groupIntoSections(prevLinesRef.current, undefined, sectionLabelsRef.current);
    for (const group of groups) {
      if (group.type !== type) continue;
      collapsedRef.current.delete(group.key);
    }
    fullRebuild();
  }, [fullRebuild]);

  // Force re-render to pick up filter state for button styling
  const [, forceUpdate] = useState(0);
  // Bottom-mask height (px) for the "spacing below the statusline" dead band.
  // 0 = no band. Driven imperatively from the geometry loop; fillerPxRef guards
  // against redundant re-renders.
  const [fillerPx, setFillerPx] = useState(0);

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
      style={{
        position: 'absolute',
        top: 0, left: 0, right: 0, bottom: 0,
        pointerEvents: 'none',
        zIndex: 10,
      }}
    >
      {/* Content host for imperative DOM — separate from React filter bar */}
      <div ref={contentHostRef} style={{ position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, pointerEvents: 'none' }} />

      {/* Bottom mask: covers the dead "spacing below the statusline" band + tmux
          status bar so the terminal reads as ending cleanly at the footer. No CLI
          redraw involved (a redraw would corrupt the scrollback). Hidden (0px) in
          the normal case. */}
      {fillerPx > 0 && (
        <div
          style={{
            position: 'absolute', left: 0, right: 0, bottom: 0,
            height: `${fillerPx}px`,
            background: 'var(--bg-panel, #0a0c10)',
            pointerEvents: 'none', zIndex: 10,
          }}
        />
      )}

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
                  const hardDefault = key === 'tool' || key === 'thinking';
                  const currentlyCollapsed = override !== null && override !== undefined ? override : hardDefault;
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
                  const hardDefault = key === 'tool' || key === 'thinking';
                  const currentlyCollapsed = override !== null && override !== undefined ? override : hardDefault;
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
export { classifyLine, groupIntoSections, findPromptAreaStart, findPrivateLines, stripAnsi };
export type { Section, SectionGroup };
