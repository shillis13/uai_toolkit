/**
 * SessionStore — main process adapter for session_store.py (SQLite).
 *
 * This is the app's interface to the external ground truth.
 * All reads go through session_store.py subprocess calls.
 * The app never opens the SQLite database directly.
 */

import { execFile } from 'node:child_process';
import * as path from 'node:path';
import * as os from 'node:os';
import type { Session } from '../shared/types';

function getAiRoot(): string {
  return process.env.AI_ROOT || path.join(os.homedir(), 'Documents/AI/ai_root');
}

function getSessionStorePath(): string {
  return path.join(getAiRoot(), 'ai_general/scripts/session_mgmt/session_store.py');
}

function getPythonPath(): string {
  const extra = ['/opt/homebrew/bin', '/opt/homebrew/sbin', '/usr/local/bin', `${os.homedir()}/.local/bin`];
  return [process.env.PATH || '', ...extra].join(':');
}

/**
 * Call session_store.py with args, return parsed JSON.
 */
function callStore(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const storePath = getSessionStorePath();
    execFile('python3', [storePath, ...args], {
      env: { ...process.env, PATH: getPythonPath() },
      maxBuffer: 10 * 1024 * 1024,
    }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(`session_store.py ${args[0]} failed: ${stderr || error.message}`));
        return;
      }
      try {
        resolve(JSON.parse(stdout));
      } catch {
        reject(new Error(`session_store.py ${args[0]}: invalid JSON output`));
      }
    });
  });
}

/**
 * Map a session_store.py row to our Session type.
 */
function mapSession(raw: Record<string, unknown>): Session {
  return {
    tracking_id: raw.tracking_id as string,
    cli_session_id: (raw.cli_session_id as string) || null,
    platform: raw.platform as Session['platform'],
    terminal_session: (raw.terminal_session as string) || null,
    session_dir: (raw.session_dir as string) || null,
    project_dir: (raw.project_dir as string) || null,
    display_name: (raw.display_name as string) || null,
    roles: parseJsonArray(raw.roles),
    model: (raw.model as string) || null,
    parent_tracking_id: (raw.parent_tracking_id as string) || null,
    identity_status: (raw.identity_status as Session['identity_status']) || 'confirmed',
    process_status: mapProcessStatus(raw.status as string),
    archived: raw.archived === 1 || raw.archived === true,
    created_at: (raw.created_at as string) || '',
    // Runtime defaults — populated by activity detection later
    activity_state: 'unknown',
    context_percent: null,
    exchange_count: 0,
    last_activity: (raw.created_at as string) || '',
    // App state defaults — populated from app_state.json later
    pinned: false,
    notes: null,
    tags: [],
  };
}

function parseJsonArray(value: unknown): string[] {
  if (Array.isArray(value)) return value as string[];
  if (typeof value === 'string') {
    try {
      const parsed = JSON.parse(value);
      if (Array.isArray(parsed)) return parsed;
    } catch { /* not JSON */ }
  }
  return [];
}

function mapProcessStatus(status: string | undefined): Session['process_status'] {
  if (status === 'running') return 'running';
  if (status === 'exited') return 'exited';
  return 'stopped';
}

// ─── Public API ────────────────────────────────────────────────────────────

export async function listSessions(): Promise<Session[]> {
  const rows = await callStore(['list', '--json']) as Record<string, unknown>[];
  return rows.map(mapSession);
}

export async function getSession(trackingId: string): Promise<Session | null> {
  try {
    const row = await callStore(['get', trackingId]) as Record<string, unknown>;
    return mapSession(row);
  } catch {
    return null;
  }
}

export async function updateSession(trackingId: string, patch: Record<string, string>): Promise<void> {
  const setArgs: string[] = [];
  for (const [key, value] of Object.entries(patch)) {
    setArgs.push('--set', `${key}=${value}`);
  }
  await callStore(['update', trackingId, ...setArgs]);
}

/**
 * Create a draft session in the store. Returns the tracking ID.
 * The session is created with identity_status='draft' and the app-known fields.
 * The launcher will later fill in runtime fields and set status to 'confirmed'.
 */
export async function createDraftSession(opts: {
  platform: string;
  displayName?: string;
  projectDir?: string;
  roles?: string[];
  parentTrackingId?: string;
}): Promise<string> {
  const { execFileSync } = await import('node:child_process');
  const aiRoot = getAiRoot();

  // Generate tracking ID with app-unique marker.
  // Format: {YYYYMMDD}_{HHMMSS}_app{hex5}_{platform3}
  // The 'app' prefix on the uuid8 segment makes it unmistakably app-generated.
  // ai_launcher generates pure hex uuid8 segments — 'app' can never appear there.
  const now = new Date();
  const date = now.toISOString().replace(/[-:T]/g, '').slice(0, 8);
  const time = now.toISOString().replace(/[-:T]/g, '').slice(8, 14);
  const hex5 = Math.random().toString(16).slice(2, 7).padEnd(5, '0');
  const platformCodes: Record<string, string> = { claude_cli: 'cla', codex_cli: 'cod', gemini_cli: 'gem' };
  const code = platformCodes[opts.platform] || 'cla';
  const trackingId = `${date}_${time}_app${hex5}_${code}`;

  // Create draft in session store
  const createArgs = [
    'create',
    '--tracking-id', trackingId,
    '--terminal-session', trackingId,
    '--platform', opts.platform,
  ];
  if (opts.displayName) {
    createArgs.push('--display-name', opts.displayName);
  }
  if (opts.projectDir) {
    createArgs.push('--project-dir', opts.projectDir);
  }
  if (opts.parentTrackingId) {
    createArgs.push('--parent-tracking-id', opts.parentTrackingId);
  }

  await callStore(createArgs);

  // Set roles via update (session_store.py create doesn't have a --roles flag)
  if (opts.roles && opts.roles.length > 0) {
    await callStore(['update', trackingId, '--set', `roles=${JSON.stringify(opts.roles)}`]);
  }

  console.log(`[UAI] Draft session created: ${trackingId} (display_name=${opts.displayName}, roles=${opts.roles}, project_dir=${opts.projectDir})`);

  return trackingId;
}

/**
 * Launch a session via ai_launcher.py. If trackingId is provided,
 * the launcher uses the pre-created draft instead of generating a new ID.
 */
export function launchSession(platform: string, trackingId: string, opts?: {
  workdir?: string;
  roles?: string;
  displayName?: string;
}): void {
  const { spawn } = require('node:child_process');
  const aiRoot = getAiRoot();

  const launcherMap: Record<string, string> = {
    claude_cli: 'claudeCli',
    codex_cli: 'codexCli',
    gemini_cli: 'geminiCli',
  };
  const launcherScript = path.join(aiRoot, 'ai_general/scripts/cli/ai_launcher.py');

  const args = ['python3', launcherScript, '--tracking-id', trackingId];
  if (opts?.workdir) {
    args.push('-w', opts.workdir);
  }
  if (opts?.roles) {
    args.push('-A', opts.roles);
  }
  if (opts?.displayName) {
    args.push('--display-name', opts.displayName);
  }

  // Fire and forget — launcher creates the terminal session
  const child = spawn(args[0], args.slice(1), {
    env: { ...process.env, PATH: getPythonPath() },
    detached: true,
    stdio: 'ignore',
  });
  child.unref();
}
