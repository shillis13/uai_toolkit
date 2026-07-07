/**
 * Session traits operations — extracted from index.ts so both IPC handlers
 * and command-bus handlers can call the same logic.
 */

import * as path from 'node:path';

function getAiRootMain(): string {
  return process.env.AI_ROOT_MAIN || process.env.AI_ROOT || path.join(require('node:os').homedir(), 'AI/ai_root');
}

const SESSION_TRAITS_SCRIPT = path.join(
  getAiRootMain(),
  'ai_general', 'scripts', 'session_mgmt', 'session_traits.py',
);

export function runSessionTraits(args: string[]): Promise<unknown> {
  const { execFile } = require('node:child_process') as typeof import('node:child_process');
  const searchPath = [process.env.PATH || '', '/opt/homebrew/bin', '/usr/local/bin'].join(':');
  return new Promise((resolve, reject) => {
    execFile('python3', [SESSION_TRAITS_SCRIPT, ...args, '--json'], {
      maxBuffer: 2 * 1024 * 1024,
      timeout: 10_000,
      env: { ...process.env, PATH: searchPath },
    }, (err, stdout, stderr) => {
      if (err) { reject(new Error(stderr || err.message)); return; }
      try { resolve(JSON.parse(stdout)); } catch { resolve([]); }
    });
  });
}
