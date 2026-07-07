/**
 * Search — cross-session transcript search via ripgrep.
 *
 * Searches JSONL transcript files for text matches. Returns structured
 * results with session context, message type, and surrounding content.
 * Supports text and regex modes, AND/OR/NOT expressions, deduplication,
 * and result grouping by session.
 */

import { execFile } from 'node:child_process';
import * as path from 'node:path';
import * as os from 'node:os';
import * as fs from 'node:fs';

/** Resolve rg binary — Electron GUI apps don't inherit shell PATH */
function findRg(): string {
  const candidates = [
    '/opt/homebrew/bin/rg',
    '/usr/local/bin/rg',
    '/usr/bin/rg',
  ];
  for (const p of candidates) {
    if (fs.existsSync(p)) return p;
  }
  return 'rg'; // fallback to PATH lookup
}

export interface SearchMatch {
  lineNumber: number;
  messageType: string;
  content: string;
  matchText: string;
  matchStart?: number;
  matchEnd?: number;
  timestamp: string;
}

export interface SessionSearchResult {
  sessionId: string;
  sessionName: string | null;
  filePath: string;
  projectSlug: string;
  matchCount: number;
  matches: SearchMatch[];
}

/** Flat result for backward compat */
export interface SearchResult {
  sessionTrackingId: string;
  sessionName: string | null;
  filePath: string;
  lineNumber: number;
  messageType: string;
  matchText: string;
  content: string;
}

export interface SearchOptions {
  limit?: number;
  caseSensitive?: boolean;
  sessionFilter?: string;
  regex?: boolean;
  deduplicate?: boolean;
  includeSubagents?: boolean;
  /** Override the JSONL root to search. Defaults to ~/.claude/projects.
   *  Used by tests to search a deterministic fixture tree. */
  rootDir?: string;
}

export interface GroupedSearchResponse {
  results: SessionSearchResult[];
  totalMatches: number;
  sessionsSearched: number;
  searchTimeMs: number;
}

function getClaudeJsonlDir(): string {
  return path.join(os.homedir(), '.claude', 'projects');
}

/**
 * Parse a LITERAL query's AND/OR/NOT expression into rg-compatible patterns.
 * Supports (literal mode only):
 *   - "foo AND bar"  -> run multiple searches, intersect
 *   - "foo OR bar"   -> "foo|bar" regex alternation (parts escaped first)
 *   - "NOT foo"      -> invert match
 *   - plain text     -> literal search
 *
 * In REGEX mode the query IS a regular expression — AND/OR/NOT are NOT treated as
 * operators (regex already expresses alternation `|`, negative lookahead `(?!…)`,
 * etc.). The whole query is passed through as a single pattern, untouched. This is
 * the deliberate split: boolean expressions belong to literal search; regex has its
 * own syntax for the same intent.
 *
 * Returns { patterns: string[], invert: boolean, isOr: boolean }
 */
export function parseQueryExpression(query: string, regexMode: boolean): {
  patterns: string[];
  invert: boolean;
  isOr: boolean;
} {
  const trimmed = query.trim();

  // Regex mode: pass through verbatim, no operator interpretation.
  if (regexMode) {
    return { patterns: [trimmed], invert: false, isOr: false };
  }

  // ── Literal mode: interpret NOT / OR / AND ──
  // Check for NOT prefix
  let invert = false;
  let working = trimmed;
  if (/^NOT\s+/i.test(working)) {
    invert = true;
    working = working.replace(/^NOT\s+/i, '');
  }

  // Check for OR — escape each literal part, join as regex alternation.
  if (/\s+OR\s+/i.test(working)) {
    const parts = working.split(/\s+OR\s+/i).map(p => p.trim()).filter(Boolean);
    const escaped = parts.map(p => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    return { patterns: [escaped.join('|')], invert, isOr: true };
  }

  // Check for AND
  if (/\s+AND\s+/i.test(working)) {
    const parts = working.split(/\s+AND\s+/i).map(p => p.trim()).filter(Boolean);
    return { patterns: parts, invert, isOr: false };
  }

  // Plain query
  return { patterns: [working], invert, isOr: false };
}

/**
 * Run a single ripgrep search pass.
 */
/** Summarize a tool_use input object to a short readable string. */
function summarizeToolInput(input: any): string {
  if (input == null) return '';
  if (typeof input === 'string') return input;
  if (typeof input !== 'object') return String(input);
  for (const k of ['command', 'file_path', 'path', 'pattern', 'query', 'url', 'description', 'prompt', 'skill', 'content']) {
    if (typeof input[k] === 'string' && input[k]) return input[k];
  }
  try { return JSON.stringify(input); } catch { return ''; }
}

/** Extract readable text from a tool_result content payload. */
function extractToolResultText(c: any): string {
  if (typeof c === 'string') return c;
  if (Array.isArray(c)) {
    return c
      .map((b: any) => (b && typeof b === 'object' && b.type === 'text') ? (b.text || '') : (typeof b === 'string' ? b : ''))
      .filter(Boolean)
      .join(' ');
  }
  if (c && typeof c === 'object' && typeof c.text === 'string') return c.text;
  return '';
}

/**
 * Turn a raw Claude/Codex JSONL record into a readable { role, text } pair,
 * or null for noise records that should not appear as search results. Mirrors
 * the UCI search formatter so tool calls / tool results / non-text messages
 * render as readable text instead of raw JSON.
 */
function extractMessage(parsed: any): { role: string; text: string } | null {
  const recType = typeof parsed?.type === 'string' ? parsed.type : '';
  if (recType === 'file-history-snapshot' || recType === 'custom-title' || recType === 'summary') {
    return null;
  }

  const msg = (parsed && typeof parsed.message === 'object' && parsed.message) ? parsed.message : parsed;

  // Role — prefer message.role, fall back to record type; refine to 'tool' below.
  const rawRole = (msg && msg.role) || parsed?.role || recType || '';
  let role = 'unknown';
  if (rawRole === 'user' || rawRole === 'human') role = 'user';
  else if (rawRole === 'assistant' || rawRole === 'ai') role = 'assistant';
  else if (rawRole === 'system') role = 'system';
  else if (rawRole === 'tool') role = 'tool';

  // Readable text
  let text = '';
  const content = msg ? msg.content : undefined;
  if (typeof content === 'string') {
    text = content;
  } else if (Array.isArray(content)) {
    const parts: string[] = [];
    let sawText = false;
    let sawTool = false;
    for (const b of content) {
      if (typeof b === 'string') { parts.push(b); sawText = true; continue; }
      if (!b || typeof b !== 'object') continue;
      if (b.type === 'text' && typeof b.text === 'string') { parts.push(b.text); sawText = true; }
      else if (b.type === 'tool_use') { sawTool = true; const i = summarizeToolInput(b.input); parts.push(`[${b.name || 'tool'}]${i ? ' ' + i : ''}`); }
      else if (b.type === 'tool_result') { sawTool = true; const t = extractToolResultText(b.content); parts.push(`[tool result]${t ? ' ' + t : ''}`); }
    }
    text = parts.join('\n').trim();
    if (!sawText && sawTool) role = 'tool';
  }

  if (!text) {
    if (typeof parsed?.text === 'string') text = parsed.text;
    else if (typeof parsed?.content === 'string') text = parsed.content;
  }

  return { role, text };
}

async function rgSearch(
  pattern: string,
  searchDir: string,
  opts: { limit: number; caseSensitive: boolean; regex: boolean; invert: boolean; includeSubagents: boolean },
): Promise<Map<string, SearchMatch[]>> {
  return new Promise((resolve) => {
    const flags: string[] = [];
    if (!opts.caseSensitive) flags.push('-i');
    if (opts.invert) flags.push('--invert-match');

    const globArgs = ['--glob', '*.jsonl'];
    if (!opts.includeSubagents) {
      globArgs.push('--glob', '!**/subagents/**');
    }

    const args = [
      '--json',
      '-m', String(opts.limit),
      ...flags,
      ...globArgs,
      ...(opts.regex ? [] : ['-F']),
      pattern,
      searchDir,
    ];

    const rgPath = findRg();
    // execFile is used intentionally (not exec) — no shell injection risk
    execFile(rgPath, args, { maxBuffer: 10 * 1024 * 1024, timeout: 30000 }, (error, stdout, stderr) => {
      if (error && !stdout) {
        console.error(`[search] rg failed: ${error.message}`, stderr ? `stderr: ${stderr.slice(0, 200)}` : '');
        resolve(new Map());
        return;
      }

      const fileMatches = new Map<string, SearchMatch[]>();
      const lines = stdout.trim().split('\n').filter(Boolean);

      for (const line of lines) {
        try {
          const rg = JSON.parse(line);
          if (rg.type !== 'match') continue;

          const filePath: string = rg.data?.path?.text || '';
          const lineNum: number = rg.data?.line_number || 0;
          const matchText: string = rg.data?.lines?.text?.trim() || '';

          // Parse JSONL line into a readable role + text; skip noise records.
          let messageType = 'unknown';
          let content = matchText;
          let timestamp = '';
          try {
            const parsed = JSON.parse(matchText);
            if (parsed.timestamp) timestamp = parsed.timestamp;
            const extracted = extractMessage(parsed);
            if (!extracted) continue; // file-history-snapshot / custom-title / summary
            messageType = extracted.role;
            content = extracted.text || matchText.slice(0, 500);
          } catch {
            content = matchText.slice(0, 500);
          }

          // Find match positions within the extracted, human-readable content.
          let matchStart: number | undefined;
          let matchEnd: number | undefined;
          if (content && pattern) {
            const searchPattern = opts.regex ? pattern : pattern.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
            try {
              const re = new RegExp(searchPattern, opts.caseSensitive ? '' : 'i');
              const m = re.exec(content);
              if (m) {
                matchStart = m.index;
                matchEnd = m.index + m[0].length;
              }
            } catch { /* invalid regex — skip highlighting */ }
          }

          // Window long content around the match so the hit stays visible
          // (mirrors UCI); otherwise cap to a sane length.
          const WINDOW = 60;
          if (content.length > 300 && matchStart !== undefined && matchStart > 100) {
            const fullLen = content.length;
            const windowStart = matchStart - WINDOW;
            const tail = windowStart + 300 < fullLen ? '...' : '';
            content = '...' + content.slice(windowStart, windowStart + 300) + tail;
            const delta = -windowStart + 3; // drop windowStart chars, add 3 for the '...' prefix
            matchStart += delta;
            if (matchEnd !== undefined) matchEnd += delta;
          } else if (content.length > 500) {
            content = content.slice(0, 500);
          }

          if (!fileMatches.has(filePath)) fileMatches.set(filePath, []);
          fileMatches.get(filePath)!.push({
            lineNumber: lineNum,
            messageType,
            content,
            matchText: matchText.slice(0, 500),
            matchStart,
            matchEnd,
            timestamp,
          });
        } catch {
          // Skip unparseable rg output
        }
      }

      resolve(fileMatches);
    });
  });
}

/**
 * Deduplicate matches within a session: same content text is collapsed.
 */
function deduplicateMatches(matches: SearchMatch[]): SearchMatch[] {
  const seen = new Set<string>();
  return matches.filter(m => {
    const key = m.content.trim().slice(0, 200);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

/**
 * Search transcripts with full expression support (AND/OR/NOT), regex,
 * deduplication, and grouped results.
 */
export async function searchTranscriptsGrouped(
  query: string,
  opts?: SearchOptions,
): Promise<GroupedSearchResponse> {
  const limit = opts?.limit || 100;
  const caseSensitive = opts?.caseSensitive || false;
  const regex = opts?.regex || false;
  const deduplicate = opts?.deduplicate !== false; // default true
  const includeSubagents = opts?.includeSubagents || false; // default: exclude subagents
  const start = Date.now();

  const claudeDir = opts?.rootDir || getClaudeJsonlDir();
  if (!fs.existsSync(claudeDir)) {
    return { results: [], totalMatches: 0, sessionsSearched: 0, searchTimeMs: 0 };
  }

  const { patterns, invert, isOr } = parseQueryExpression(query, regex);

  // For AND queries, run each pattern and intersect by file
  let fileMatches: Map<string, SearchMatch[]>;

  if (patterns.length === 1 || isOr) {
    // Single pattern or OR (already combined into one regex)
    fileMatches = await rgSearch(patterns[0], claudeDir, {
      limit, caseSensitive, regex: regex || isOr, invert, includeSubagents,
    });
  } else {
    // AND: intersect results from all patterns
    const allResults = await Promise.all(
      patterns.map(p => rgSearch(p, claudeDir, {
        limit, caseSensitive, regex, invert, includeSubagents,
      }))
    );

    // Intersect: keep only files that appear in ALL result sets
    const fileSets = allResults.map(r => new Set(r.keys()));
    const commonFiles = [...fileSets[0]].filter(f => fileSets.every(s => s.has(f)));

    fileMatches = new Map();
    for (const file of commonFiles) {
      // Merge matches from all patterns for this file
      const merged: SearchMatch[] = [];
      const seenLines = new Set<number>();
      for (const resultMap of allResults) {
        for (const match of resultMap.get(file) || []) {
          if (!seenLines.has(match.lineNumber)) {
            seenLines.add(match.lineNumber);
            merged.push(match);
          }
        }
      }
      fileMatches.set(file, merged);
    }
  }

  // Apply session filter if specified
  const sessionFilter = opts?.sessionFilter;

  // Group by session (file)
  const grouped: SessionSearchResult[] = [];
  let sessionsSearched = 0;

  for (const [filePath, matches] of fileMatches) {
    const pathParts = filePath.split('/');
    const jsonlFile = pathParts[pathParts.length - 1] || '';
    const sessionId = jsonlFile.replace('.jsonl', '');
    const projectSlug = pathParts[pathParts.length - 2] || '';

    if (sessionFilter && !sessionId.includes(sessionFilter)) continue;

    sessionsSearched++;

    const finalMatches = deduplicate ? deduplicateMatches(matches) : matches;

    grouped.push({
      sessionId,
      sessionName: null,
      filePath,
      projectSlug,
      matchCount: finalMatches.length,
      matches: finalMatches,
    });
  }

  // Sort by match count descending
  grouped.sort((a, b) => b.matchCount - a.matchCount);

  const totalMatches = grouped.reduce((sum, g) => sum + g.matchCount, 0);

  return {
    results: grouped,
    totalMatches,
    sessionsSearched,
    searchTimeMs: Date.now() - start,
  };
}

/**
 * Backward-compatible flat search (used by existing preload API).
 */
export async function searchTranscripts(
  query: string,
  opts?: SearchOptions,
): Promise<SearchResult[]> {
  const grouped = await searchTranscriptsGrouped(query, opts);
  const flat: SearchResult[] = [];
  for (const group of grouped.results) {
    for (const match of group.matches) {
      flat.push({
        sessionTrackingId: group.sessionId,
        sessionName: group.sessionName,
        filePath: group.filePath,
        lineNumber: match.lineNumber,
        messageType: match.messageType,
        matchText: match.matchText,
        content: match.content,
      });
    }
  }
  return flat;
}
