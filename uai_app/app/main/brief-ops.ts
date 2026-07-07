/**
 * Brief operations — extracted from index.ts so both IPC handlers
 * and command-bus handlers can call the same logic.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';

function getAiRootMain(): string {
  return process.env.AI_ROOT_MAIN || process.env.AI_ROOT || path.join(require('node:os').homedir(), 'AI/ai_root');
}

export interface CreateBriefOpts {
  name: string;
  description?: string;
  folder: string;
  launch?: boolean;
  launchName?: string;
  launchPlatform?: string;
  condenserSession?: string;
}

export interface CreateBriefResult {
  ok: boolean;
  briefPath?: string;
  briefName?: string;
  error?: string;
}

export async function createBrief(
  sessionIds: string | string[],
  opts: CreateBriefOpts,
): Promise<CreateBriefResult> {
  const { execFile: ef } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(ef);
  const aiRoot = getAiRootMain();
  const condensePy = path.join(aiRoot, 'ai_general/scripts/jsonl/condense.py');
  const sessionOpsPy = path.join(aiRoot, 'ai_general/scripts/session_mgmt/session_ops.py');
  const briefsDir = path.join(aiRoot, 'ai_general/data/session_briefs');
  const envPath = [process.env.PATH || '', '/opt/homebrew/bin', '/usr/local/bin', `${require('node:os').homedir()}/.local/bin`].join(':');
  const env = { ...process.env, AI_ROOT: aiRoot, PATH: envPath } as Record<string, string>;

  const ids = Array.isArray(sessionIds) ? sessionIds : [sessionIds];

  // Build output path: briefsDir / folder / name.yml
  const folder = opts.folder || '';
  const outputDir = folder && folder !== '/' ? path.join(briefsDir, folder.replace(/^\//, '')) : briefsDir;
  if (!fs.existsSync(outputDir)) {
    fs.mkdirSync(outputDir, { recursive: true });
  }
  const outputPath = path.join(outputDir, `${opts.name}.yml`);

  // Build condense.py args
  const args: string[] = [];
  for (const id of ids) args.push('--src-uuid', id);
  args.push('--name', opts.name, '--output', outputPath);
  if (opts.description) args.push('--description', opts.description);
  if (opts.condenserSession) args.push('--condenser', opts.condenserSession);

  try {
    await execFileAsync('python3', [condensePy, ...args], {
      timeout: 300_000 * ids.length,
      env,
    });
  } catch (err: any) {
    const msg = err.stderr || err.message || String(err);
    console.error('[briefs:create] condense.py failed:', msg);
    return { ok: false, error: `condense.py failed: ${msg}` };
  }

  // If condense.py didn't write a brief_meta block, prepend one
  let existingContent = '';
  try {
    existingContent = fs.readFileSync(outputPath, 'utf-8');
  } catch { /* file may not exist */ }

  if (!existingContent.includes('brief_meta:')) {
    const now = new Date().toISOString();
    const metaBlock = [
      'brief_meta:',
      `  name: ${opts.name}`,
      `  display_name: ${opts.name}`,
      `  description: ${opts.description || ''}`,
      `  folder: ${opts.folder || '/'}`,
      `  created: '${now}'`,
      `  condenser_session: ${opts.condenserSession || ids[0]}`,
      '  status: active',
      '  links:',
      ...ids.map(id => `  - type: brief_of\n    target: ${id}\n    created: '${now}'`),
      '',
    ].join('\n');
    fs.writeFileSync(outputPath, metaBlock + existingContent, 'utf-8');
  }

  // Write briefed_to link to each source session
  for (const id of ids) {
    try {
      await execFileAsync('python3', [
        sessionOpsPy, 'add-link', id,
        '--type', 'briefed_to',
        '--target', opts.name,
      ], { timeout: 10_000, env });
    } catch { /* best effort */ }
  }

  return { ok: true, briefPath: outputPath, briefName: opts.name };
}
