/**
 * Session context-registry operations — extracted from index.ts so both IPC
 * handlers and command-bus handlers can call the same logic.
 *
 * Backed by scripts/session_mgmt/session_context_registry.py (formerly
 * session_traits.py — renamed 2026-07; a working-tree symlink briefly bridged the
 * gap, todo_0621). The exported name stays `runSessionTraits` since every caller
 * uses it; only the underlying script path changed.
 */

import * as path from 'node:path';
import { aiRootMain as getAiRootMain, shellPath } from './paths';


const SESSION_CONTEXT_REGISTRY_SCRIPT = path.join(
  getAiRootMain(),
  'ai_general', 'scripts', 'session_mgmt', 'session_context_registry.py',
);

export function runSessionTraits(args: string[]): Promise<unknown> {
  const { execFile } = require('node:child_process') as typeof import('node:child_process');
  const searchPath = shellPath();
  return new Promise((resolve, reject) => {
    execFile('python3', [SESSION_CONTEXT_REGISTRY_SCRIPT, ...args, '--json'], {
      maxBuffer: 2 * 1024 * 1024,
      timeout: 10_000,
      env: { ...process.env, PATH: searchPath },
    }, (err, stdout, stderr) => {
      if (err) { reject(new Error(stderr || err.message)); return; }
      try { resolve(JSON.parse(stdout)); } catch { resolve([]); }
    });
  });
}
