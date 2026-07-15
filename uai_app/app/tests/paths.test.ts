import { describe, it, expect, beforeEach, afterEach } from 'vitest';
import * as path from 'node:path';
import {
  aiRoot, aiRootMain, aiData, aiScripts, aiContextFiles, shellPath, buildChildEnv,
} from '../main/paths';

/**
 * Anti-drift test for paths.ts — the TS twin of paths.py. Asserts the SAME
 * default map (AI_ROOT -> derived) that paths.py + ai_env.sh resolve, so the
 * three surfaces can't silently diverge. See uai_toolkit/docs/design_ts_paths_pattern.md.
 *
 * Harness note (from Noctis): clear ALL non-AI_ROOT ambient AI_* vars before
 * probing, or an ambient override leaks in and masks drift.
 */
const AI_VARS = [
  'AI_ROOT', 'AI_ROOT_MAIN', 'AI_DATA', 'AI_SCRIPTS', 'AI_BIN', 'AI_LOGS',
  'AI_HOOKS', 'AI_UAI_APP', 'AI_CONTEXT_FILES', 'AI_JSONL', 'AI_PYTHON',
];
const FIXED_ROOT = path.join('/tmp', 'uai_paths_fixture', 'ai_root');

let saved: Record<string, string | undefined>;
beforeEach(() => {
  saved = {};
  for (const v of AI_VARS) { saved[v] = process.env[v]; delete process.env[v]; }
  process.env.AI_ROOT = FIXED_ROOT;   // fix the anchor; test defaults, not the env
});
afterEach(() => {
  for (const v of AI_VARS) {
    if (saved[v] === undefined) delete process.env[v];
    else process.env[v] = saved[v];
  }
});

describe('paths.ts default map', () => {
  it('aiRoot() is the AI_ROOT anchor', () => {
    expect(aiRoot()).toBe(FIXED_ROOT);
  });

  it('aiRootMain() defaults to the resolved AI_ROOT (paths.py _v("AI_ROOT_MAIN", AI_ROOT))', () => {
    expect(aiRootMain()).toBe(FIXED_ROOT);
  });

  it('aiRootMain() honors an explicit AI_ROOT_MAIN (devTree case)', () => {
    process.env.AI_ROOT_MAIN = '/tmp/production_main';
    expect(aiRootMain()).toBe('/tmp/production_main');
    expect(aiRoot()).toBe(FIXED_ROOT);   // stays the devTree
  });

  it('derived paths default under AI_ROOT', () => {
    expect(aiData()).toBe(path.join(FIXED_ROOT, 'ai_general', 'data'));
    expect(aiScripts()).toBe(path.join(FIXED_ROOT, 'ai_general', 'scripts'));
    expect(aiContextFiles()).toBe(path.join(FIXED_ROOT, 'ai_general', 'ai_context_files'));
  });

  it('an explicit env var overrides the derived default', () => {
    process.env.AI_DATA = '/custom/data';
    expect(aiData()).toBe('/custom/data');
  });
});

describe('paths.ts child-process env', () => {
  it('shellPath() prepends the caller PATH and appends fallback dirs, de-duplicated', () => {
    process.env.PATH = '/usr/local/bin:/custom/tool';
    const parts = shellPath().split(path.delimiter);
    expect(parts[0]).toBe('/usr/local/bin');       // caller PATH first
    expect(parts[1]).toBe('/custom/tool');
    expect(new Set(parts).size).toBe(parts.length); // no dupes
  });

  it('buildChildEnv() sets AI_ROOT, AI_ROOT_MAIN and a PATH', () => {
    const env = buildChildEnv({ EXTRA: 'x' });
    expect(env.AI_ROOT).toBe(FIXED_ROOT);
    expect(env.AI_ROOT_MAIN).toBe(FIXED_ROOT);
    expect(env.PATH).toBeTruthy();
    expect(env.EXTRA).toBe('x');
  });
});
