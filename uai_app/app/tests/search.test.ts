/**
 * Search tests — literal + AND/OR/NOT expressions and regex, against a deterministic
 * JSONL fixture tree (mirrors ~/.claude/projects/<slug>/<sessionId>.jsonl). Covers the
 * transcript search path end-to-end (parse → ripgrep → group), the item-4 rule that
 * regex mode does NOT interpret AND/OR/NOT, message extraction (user/assistant/tool),
 * case sensitivity, dedup, and subagent exclusion.
 *
 * Requires ripgrep (rg) on the machine — search.ts findRg() resolves it.
 */
import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import { parseQueryExpression, searchTranscriptsGrouped } from '../main/search';

// ── fixture tree ─────────────────────────────────────────────────────────────
let root: string;

function jline(rec: any): string { return JSON.stringify(rec); }
function userMsg(text: string, ts: string) {
  return jline({ type: 'user', message: { role: 'user', content: text }, timestamp: ts });
}
function asstText(text: string, ts: string) {
  return jline({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'text', text }] }, timestamp: ts });
}
function asstTool(name: string, input: any, ts: string) {
  return jline({ type: 'assistant', message: { role: 'assistant', content: [{ type: 'tool_use', name, input }] }, timestamp: ts });
}

beforeAll(() => {
  root = fs.mkdtempSync(path.join(os.tmpdir(), 'mx-search-'));
  // Session A — projA
  const a = path.join(root, 'projA');
  fs.mkdirSync(a, { recursive: true });
  fs.writeFileSync(path.join(a, 'sessA.jsonl'), [
    userMsg('deploy the app to production', '2026-06-20T10:00:00Z'),
    asstText('I will deploy now and watch the rollout', '2026-06-20T10:01:00Z'),
    asstTool('Bash', { command: 'git push origin main' }, '2026-06-20T10:02:00Z'),
    userMsg('please rollback the change', '2026-06-20T10:03:00Z'),
  ].join('\n') + '\n');
  // Session B — projB
  const b = path.join(root, 'projB');
  fs.mkdirSync(b, { recursive: true });
  fs.writeFileSync(path.join(b, 'sessB.jsonl'), [
    userMsg('deploy the database migration', '2026-06-21T09:00:00Z'),
    asstText('running the migration against staging', '2026-06-21T09:01:00Z'),
    jline({ type: 'user', message: { role: 'user', content: [{ type: 'tool_result', content: 'migration complete' }] }, timestamp: '2026-06-21T09:02:00Z' }),
  ].join('\n') + '\n');
  // Subagent file — excluded by default
  const sub = path.join(a, 'subagents');
  fs.mkdirSync(sub, { recursive: true });
  fs.writeFileSync(path.join(sub, 'sub1.jsonl'),
    userMsg('secret subagent deploy note', '2026-06-20T10:05:00Z') + '\n');
});

afterAll(() => { try { fs.rmSync(root, { recursive: true, force: true }); } catch { /* noop */ } });

const search = (q: string, opts: any = {}) =>
  searchTranscriptsGrouped(q, { rootDir: root, deduplicate: false, ...opts });
const sessionIds = (r: any) => r.results.map((g: any) => g.sessionId).sort();
const allContent = (r: any) => r.results.flatMap((g: any) => g.matches.map((m: any) => m.content)).join(' || ');

// ── parseQueryExpression ──────────────────────────────────────────────────────
describe('parseQueryExpression (literal mode)', () => {
  it('plain query → single literal pattern', () => {
    expect(parseQueryExpression('deploy', false)).toEqual({ patterns: ['deploy'], invert: false, isOr: false });
  });
  it('NOT prefix → invert', () => {
    expect(parseQueryExpression('NOT deploy', false)).toEqual({ patterns: ['deploy'], invert: true, isOr: false });
  });
  it('OR → escaped alternation', () => {
    expect(parseQueryExpression('rollback OR migration', false)).toEqual({ patterns: ['rollback|migration'], invert: false, isOr: true });
  });
  it('OR escapes regex metachars in each literal part', () => {
    expect(parseQueryExpression('a.b OR c+d', false)).toEqual({ patterns: ['a\\.b|c\\+d'], invert: false, isOr: true });
  });
  it('AND → multiple patterns to intersect', () => {
    expect(parseQueryExpression('deploy AND production', false)).toEqual({ patterns: ['deploy', 'production'], invert: false, isOr: false });
  });
});

describe('parseQueryExpression (regex mode) — operators NOT interpreted', () => {
  it('AND is passed through literally as regex', () => {
    expect(parseQueryExpression('deploy AND production', true)).toEqual({ patterns: ['deploy AND production'], invert: false, isOr: false });
  });
  it('OR is passed through (regex uses | itself)', () => {
    expect(parseQueryExpression('deploy OR rollback', true)).toEqual({ patterns: ['deploy OR rollback'], invert: false, isOr: false });
  });
  it('NOT is not an invert in regex mode', () => {
    expect(parseQueryExpression('NOT deploy', true)).toEqual({ patterns: ['NOT deploy'], invert: false, isOr: false });
  });
  it('a real regex alternation is preserved verbatim', () => {
    expect(parseQueryExpression('depl(oy|oyed)', true)).toEqual({ patterns: ['depl(oy|oyed)'], invert: false, isOr: false });
  });
});

// ── transcript search end-to-end ───────────────────────────────────────────────
describe('searchTranscriptsGrouped — literal', () => {
  it('plain term matches across sessions', async () => {
    const r = await search('deploy');
    expect(sessionIds(r)).toEqual(['sessA', 'sessB']);
  });
  it('AND intersects within a session (only A has both)', async () => {
    const r = await search('deploy AND production');
    expect(sessionIds(r)).toEqual(['sessA']);
  });
  it('OR unions matches across sessions', async () => {
    const r = await search('rollback OR migration');
    expect(sessionIds(r)).toEqual(['sessA', 'sessB']);
  });
  it('NOT excludes matching lines', async () => {
    const r = await search('NOT deploy');
    // every returned line must NOT contain "deploy"
    expect(allContent(r).toLowerCase()).not.toContain('deploy');
    // but real non-deploy content is still found (e.g. "rollback", "migration")
    expect(allContent(r).toLowerCase()).toMatch(/rollback|migration|answer|staging/);
  });
});

describe('searchTranscriptsGrouped — regex (item 4: no operator interpretation)', () => {
  it('"x AND y" in regex mode matches NOTHING (no literal "AND" in transcripts)', async () => {
    const r = await search('deploy AND production', { regex: true });
    expect(r.totalMatches).toBe(0);
  });
  it('a genuine regex alternation works', async () => {
    const r = await search('rollback|migration', { regex: true });
    expect(sessionIds(r)).toEqual(['sessA', 'sessB']);
  });
  it('regex metacharacters are honored (not escaped)', async () => {
    const r = await search('depl\\w+', { regex: true });
    expect(r.totalMatches).toBeGreaterThan(0);
  });
});

describe('searchTranscriptsGrouped — options', () => {
  it('case-insensitive by default; case-sensitive excludes wrong case', async () => {
    expect((await search('DEPLOY')).totalMatches).toBeGreaterThan(0);
    expect((await search('DEPLOY', { caseSensitive: true })).totalMatches).toBe(0);
  });
  it('excludes subagent files by default, includes them when asked', async () => {
    expect((await search('secret subagent')).totalMatches).toBe(0);
    expect((await search('secret subagent', { includeSubagents: true })).totalMatches).toBe(1);
  });
  it('extracts readable tool content (tool_use → [Bash] …)', async () => {
    const r = await search('git push');
    const m = r.results[0].matches[0];
    expect(m.messageType).toBe('tool');
    expect(m.content).toContain('[Bash]');
    expect(m.content).toContain('git push origin main');
  });
  it('extracts assistant text and tags role', async () => {
    const r = await search('rollout');
    const m = r.results.flatMap((g: any) => g.matches).find((m: any) => m.content.includes('rollout'));
    expect(m?.messageType).toBe('assistant');
  });
  it('carries timestamps through for time sorting', async () => {
    const r = await search('deploy');
    const allTs = r.results.flatMap((g: any) => g.matches.map((m: any) => m.timestamp));
    expect(allTs.every((t: string) => /^2026-06-2\dT/.test(t))).toBe(true);
  });
});
