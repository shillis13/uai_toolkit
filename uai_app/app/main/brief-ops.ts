/**
 * Brief operations — extracted from index.ts so both IPC handlers
 * and command-bus handlers can call the same logic.
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import { aiRootMain as getAiRootMain, shellPath } from './paths';


export interface CreateBriefOpts {
  name: string;
  description?: string;
  folder: string;
  launch?: boolean;
  launchName?: string;
  launchPlatform?: string;
  condenserSession?: string;
  // NEW model (todo_0506): the session chosen to host the briefing subagent.
  // The host→subagent dispatch now happens in the `brief.create` command handler
  // (deliverPromptTyped → auto_brief.py emit-subagent-task); this legacy createBrief
  // path is only reached when NO host is chosen. If present here (defensive), the
  // host is recorded as the brief's actor.
  hostSession?: string;
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
  const envPath = shellPath();
  const env = { ...process.env, AI_ROOT: aiRoot, PATH: envPath } as Record<string, string>;

  const ids = Array.isArray(sessionIds) ? sessionIds : [sessionIds];

  // Legacy path only (host-dispatch is handled in the command layer). If a host
  // was somehow passed here, record it as the actor; else the condenser session.
  const actorSession = opts.hostSession || opts.condenserSession;

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
  if (actorSession) args.push('--condenser', actorSession);

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
      `  condenser_session: ${actorSession || ids[0]}`,
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
