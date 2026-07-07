#!/usr/bin/env node
// scripts/check-no-inline-hex.mjs
//
// UAI design-token guard (todo_0384).
//
// PURPOSE
//   The renderer-ui inline styles were migrated to CSS custom-property design
//   tokens (e.g. `color: 'var(--text-primary)'`). This check fails the build if
//   a RAW hex color literal (e.g. '#1a2b3c' or '#abc') creeps back into a React
//   inline style. Zero dependencies -- plain Node, text-scan with a small
//   string/comment/brace state machine (no ESLint in this repo).
//
// WHAT COUNTS AS A VIOLATION
//   A hex color string literal that appears inside a "style context":
//     1. A JSX inline style attribute:  style={{ ... }}
//     2. An object literal typed React.CSSProperties / CSSProperties, i.e.
//          const X: React.CSSProperties = { ... }
//          (...) : CSSProperties => ({ ... })
//   ...AND that is NOT wrapped in a CSS var() fallback. The migrated/tokenized
//   form `var(--token, #fallback)` is ALLOWED -- the hex there is just the
//   fallback for the token and is the intended pattern. A bare `color: '#fff'`
//   is a violation.
//
// ALLOWLIST (intentionally exempt) -- see ALLOW_FILES / notes below:
//   - packages/renderer-ui/src/utils/session-color.ts
//       Identity-hash palette (deterministic per-session color); not a style
//       context, exempt outright.
//   - packages/renderer-ui/src/components/TerminalFormatOverlay.tsx
//       Memorex terminal-format overlay; token migration deferred.
//   - xterm `theme: { ... }` objects (e.g. in TerminalPane.tsx /
//       StandaloneTerminal.tsx) encode terminal ANSI identity colors. These are
//       `theme:` object literals, NOT `style=` / CSSProperties objects, so they
//       fall OUTSIDE the style-context definition above and are never scanned --
//       no explicit exemption needed. Documented here so it stays that way.
//   - Hex inside the CSS token DEFINITIONS themselves lives in .css (themes.css),
//       not .ts/.tsx, so it is out of scope for this scanner.
//
// SCOPE: .ts / .tsx under packages/renderer-ui/src
//
// USAGE:  node scripts/check-no-inline-hex.mjs
// EXIT:   0 = clean, 1 = violations found (prints file:line:col list)

import { readFileSync, readdirSync, statSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join, relative, sep } from 'node:path';

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const SCAN_ROOT = join(REPO_ROOT, 'packages', 'renderer-ui', 'src');

// Files exempt in their entirety (paths relative to repo root, normalized to /).
const ALLOW_FILES = new Set([
  'packages/renderer-ui/src/utils/session-color.ts',
  'packages/renderer-ui/src/components/TerminalFormatOverlay.tsx',
]);

// Specific hex VALUES that are exempt anywhere (per the migration contract's
// exclusions): pure white/black are theme-agnostic; brand/identity hues are a
// deliberate identity color space, not the themeable accent palette.
const ALLOW_VALUES = new Set([
  '#fff', '#ffffff', '#000', '#000000',   // pure white/black (rule 5)
  '#666', '#666666',                       // neutral swatch default (tag identity)
  '#e07a4a', '#8b5cf6', '#4285f4', '#74aa9c', // platform / web-AI brand identity
  '#bb9af7', // Perplexity brand marker (coincides w/ --accent-purple; identity here)
].map((s) => s.toLowerCase()));

const HEX = /#([0-9a-fA-F]{3,8})(?![0-9a-fA-F])/g;
const VALID_HEX_LEN = new Set([3, 4, 6, 8]);

function toPosix(p) {
  return p.split(sep).join('/');
}

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) {
      if (name === 'node_modules' || name.startsWith('.')) continue;
      walk(full, out);
    } else if (name.endsWith('.ts') || name.endsWith('.tsx')) {
      out.push(full);
    }
  }
  return out;
}

// Remove balanced var( ... ) spans from a string value so their hex fallbacks
// (the tokenized/allowed form) are not treated as bare hex.
function stripVarSpans(s) {
  let out = '';
  let i = 0;
  while (i < s.length) {
    const idx = s.indexOf('var(', i);
    if (idx === -1) {
      out += s.slice(i);
      break;
    }
    out += s.slice(i, idx);
    let depth = 0;
    let j = idx + 3; // at '('
    for (; j < s.length; j++) {
      const ch = s[j];
      if (ch === '(') depth++;
      else if (ch === ')') {
        depth--;
        if (depth === 0) { j++; break; }
      }
    }
    i = j; // continue after the closing ')'
  }
  return out;
}

function hexViolationsIn(value) {
  const stripped = stripVarSpans(value);
  const found = [];
  let m;
  HEX.lastIndex = 0;
  while ((m = HEX.exec(stripped)) !== null) {
    if (VALID_HEX_LEN.has(m[1].length)) found.push('#' + m[1]);
  }
  return found;
}

// Does the '{' at position i open a style context, given source before it?
// (Inheritance handles nested braces: a child of a style frame is also style.)
function opensStyleContext(src, braceIdx) {
  const before = src.slice(Math.max(0, braceIdx - 120), braceIdx);
  // JSX: style={  (the outer container brace of style={{ ... }})
  if (/style\s*=\s*$/.test(before)) return true;
  // Typed CSSProperties object:  : (React.)CSSProperties = {  |  => {  |  => ({
  if (/:\s*(React\.)?CSSProperties\s*(=|=>)\s*\(?\s*$/.test(before)) return true;
  return false;
}

function lineColAt(src, offset) {
  let line = 1;
  let col = 1;
  for (let i = 0; i < offset; i++) {
    if (src[i] === '\n') { line++; col = 1; }
    else col++;
  }
  return { line, col };
}

// Scan one file; return array of {line, col, value, hexes}.
function scanFile(src) {
  const violations = [];
  const braceStack = []; // frames: { isStyle }
  const inStyle = () => braceStack.length > 0 && braceStack[braceStack.length - 1].isStyle;

  let i = 0;
  const n = src.length;
  while (i < n) {
    const c = src[i];

    // line comment
    if (c === '/' && src[i + 1] === '/') {
      const nl = src.indexOf('\n', i);
      i = nl === -1 ? n : nl;
      continue;
    }
    // block comment
    if (c === '/' && src[i + 1] === '*') {
      const end = src.indexOf('*/', i + 2);
      i = end === -1 ? n : end + 2;
      continue;
    }
    // single/double quoted string
    if (c === '"' || c === "'") {
      const quote = c;
      const startContent = i + 1;
      let j = i + 1;
      while (j < n) {
        if (src[j] === '\\') { j += 2; continue; }
        if (src[j] === quote) break;
        j++;
      }
      const value = src.slice(startContent, j);
      if (inStyle()) {
        const hexes = hexViolationsIn(value);
        if (hexes.length) {
          const { line, col } = lineColAt(src, i);
          violations.push({ line, col, value, hexes });
        }
      }
      i = j + 1;
      continue;
    }
    // template literal
    if (c === '`') {
      const startContent = i + 1;
      let j = i + 1;
      let literalText = '';
      while (j < n) {
        if (src[j] === '\\') { literalText += src[j + 1] ?? ''; j += 2; continue; }
        if (src[j] === '`') break;
        if (src[j] === '$' && src[j + 1] === '{') {
          // interpolation: skip balanced braces (treat as code, ignore for hex)
          let depth = 0;
          j += 1; // at '{'
          for (; j < n; j++) {
            if (src[j] === '{') depth++;
            else if (src[j] === '}') { depth--; if (depth === 0) { j++; break; } }
          }
          continue;
        }
        literalText += src[j];
        j++;
      }
      if (inStyle()) {
        const hexes = hexViolationsIn(literalText);
        if (hexes.length) {
          const { line, col } = lineColAt(src, startContent);
          violations.push({ line, col, value: literalText, hexes });
        }
      }
      i = j + 1;
      continue;
    }
    // brace open
    if (c === '{') {
      const localStyle = opensStyleContext(src, i);
      const parentStyle = inStyle();
      braceStack.push({ isStyle: localStyle || parentStyle });
      i++;
      continue;
    }
    if (c === '}') {
      braceStack.pop();
      i++;
      continue;
    }
    i++;
  }
  return violations;
}

function main() {
  let files;
  try {
    files = walk(SCAN_ROOT);
  } catch (e) {
    console.error(`[lint:tokens] cannot scan ${SCAN_ROOT}: ${e.message}`);
    process.exit(2);
  }

  const allViolations = [];
  for (const file of files) {
    const rel = toPosix(relative(REPO_ROOT, file));
    if (ALLOW_FILES.has(rel)) continue;
    let src;
    try { src = readFileSync(file, 'utf8'); } catch { continue; }
    const vs = scanFile(src);
    for (const v of vs) {
      // Drop allowlisted values; only flag if a non-exempt hex remains.
      const bad = v.hexes.filter((h) => !ALLOW_VALUES.has(String(h).toLowerCase()));
      if (bad.length === 0) continue;
      allViolations.push({ rel, ...v, hexes: bad });
    }
  }

  if (allViolations.length === 0) {
    console.log('[lint:tokens] OK -- no raw hex color literals in React inline styles.');
    process.exit(0);
  }

  console.error('[lint:tokens] FAIL -- raw hex color literals found in inline styles.');
  console.error('  Use a CSS design token instead, e.g.  color: \'var(--text-primary)\'');
  console.error('  (a var() fallback like \'var(--x, #123)\' is allowed).\n');
  for (const v of allViolations) {
    console.error(`  ${v.rel}:${v.line}:${v.col}  ${v.hexes.join(', ')}   ->  ${v.value.trim().slice(0, 80)}`);
  }
  console.error(`\n[lint:tokens] ${allViolations.length} violation(s).`);
  process.exit(1);
}

main();
