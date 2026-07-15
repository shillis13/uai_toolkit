/**
 * SessionStore — main process adapter for session_store.py (SQLite).
 *
 * This is the app's interface to the external ground truth.
 * All reads go through session_store.py subprocess calls.
 * The app never opens the SQLite database directly.
 *
 * Carried forward from spike with minor type updates.
 */

import { execFile } from 'node:child_process';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import type { Session, SessionPref } from '@uai/shared/types';
import { getAppStatePath } from './app-state-path';
// Root resolution + child-process PATH now come from the shared paths.ts (the TS
// twin of paths.py). Aliased to the old local names so call sites are unchanged.
import { aiRoot as getAiRoot, aiRootMain as getAiRootMain, shellPath as getPythonPath } from './paths';

function getSessionStorePath(): string {
  return path.join(getAiRootMain(), 'ai_general/scripts/session_mgmt/session_store.py');
}

export function callStore(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const storePath = getSessionStorePath();
    execFile('python3', [storePath, ...args], {
      env: { ...process.env, PATH: getPythonPath(), AI_ROOT: getAiRootMain() },
      maxBuffer: 10 * 1024 * 1024,
    }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(`session_store.py ${args[0]} failed: ${stderr || error.message}`));
        return;
      }
      const trimmed = stdout.trim();
      if (!trimmed) {
        resolve(null);
        return;
      }
      try {
        resolve(JSON.parse(trimmed));
      } catch {
        // Non-JSON output from write commands (e.g. "ok") — treat as success
        resolve(null);
      }
    });
  });
}

// ─── Prompt-block helper (prompt_blocks.py) ─────────────────────────────────
// Noctis's prompt-block backend: a session can be blocked from receiving
// prompts from anyone but PianoMan. `list` returns the whole live roster in one
// call — cheapest for enriching the session list. Read-only; the app never
// sets/clears blocks (that is CLI/MCP).

interface PromptBlockRow {
  tracking_id: string;
  mode: string;
  turns_remaining?: number | null;
  expires_at?: string | null;
  reason?: string | null;
}

function getPromptBlocksPath(): string {
  return path.join(getAiRootMain(), 'ai_general/scripts/messages/prompt_blocks.py');
}

/**
 * Return a map of tracking_id → prompt-block for every live block. Best-effort:
 * any failure (script missing, parse error) resolves to an empty map so the
 * session list is never blocked by the prompt-block lookup.
 */
export function getPromptBlocks(): Promise<Map<string, PromptBlockRow>> {
  return new Promise((resolve) => {
    execFile('python3', [getPromptBlocksPath(), 'list'], {
      env: { ...process.env, PATH: getPythonPath(), AI_ROOT: getAiRootMain() },
      maxBuffer: 4 * 1024 * 1024,
    }, (error, stdout) => {
      const map = new Map<string, PromptBlockRow>();
      if (error) { resolve(map); return; }
      try {
        const parsed = JSON.parse(stdout.trim() || '{}');
        for (const b of (parsed.blocks ?? []) as PromptBlockRow[]) {
          if (b && b.tracking_id) map.set(b.tracking_id, b);
        }
      } catch { /* leave map empty */ }
      resolve(map);
    });
  });
}

// ─── Session Manager (session_mgr.py) helper ────────────────────────────

function getSessionMgrPath(): string {
  return path.join(getAiRootMain(), 'ai_general/scripts/session_mgmt/session_mgr.py');
}

export function callSessionMgr(args: string[]): Promise<unknown> {
  return new Promise((resolve, reject) => {
    const mgrPath = getSessionMgrPath();
    execFile('python3', [mgrPath, ...args], {
      env: { ...process.env, PATH: getPythonPath(), AI_ROOT: getAiRootMain() },
      maxBuffer: 10 * 1024 * 1024,
    }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(`session_mgr.py ${args[0]} failed: ${stderr || error.message}`));
        return;
      }
      const trimmed = stdout.trim();
      if (!trimmed) {
        resolve(null);
        return;
      }
      try {
        resolve(JSON.parse(trimmed));
      } catch {
        // Non-JSON output — treat as success with raw text
        resolve({ raw: trimmed });
      }
    });
  });
}

// ─── App State Loader (for session pref merge) ──────────────────────────

let _appStateCache: { data: Record<string, unknown>; mtime: number } | null = null;

function loadAppState(): Record<string, unknown> {
  const statePath = getAppStatePath();
  try {
    const stat = fs.statSync(statePath);
    if (_appStateCache && _appStateCache.mtime === stat.mtimeMs) {
      return _appStateCache.data;
    }
    const data = JSON.parse(fs.readFileSync(statePath, 'utf-8'));
    _appStateCache = { data, mtime: stat.mtimeMs };
    return data;
  } catch {
    return {};
  }
}

function getSessionPref(trackingId: string): SessionPref {
  const appState = loadAppState();
  const prefs = (appState.sessionPrefs || {}) as Record<string, SessionPref>;
  return prefs[trackingId] || {};
}

// ─── Session State Loader (telemetry from Stop hook) ─────────────────────

function getSessionState(sessionDir: string, trackingId: string): Record<string, unknown> {
  if (!sessionDir || !trackingId) return {};
  const statePath = path.join(sessionDir, `${trackingId}_state.json`);
  try {
    return JSON.parse(fs.readFileSync(statePath, 'utf-8'));
  } catch {
    return {};
  }
}

// ─── Tags Loader (for session tag merge) ─────────────────────────────────

async function getTagsForSession(trackingId: string): Promise<string[]> {
  try {
    const result = await callStore(['get_tags', trackingId]);
    return Array.isArray(result) ? result as string[] : [];
  } catch {
    return [];
  }
}

async function getAllSessionTags(): Promise<Record<string, string[]>> {
  try {
    const result = await callStore(['get_all_session_tags']);
    if (result && typeof result === 'object') return result as Record<string, string[]>;
  } catch {
    // Fallback: try legacy command name
    try {
      const result = await callStore(['get_all_card_tags']);
      if (result && typeof result === 'object') return result as Record<string, string[]>;
    } catch { /* */ }
    console.warn('[UAI] get_all_session_tags not available in session_store.py');
  }
  return {};
}

export async function listDistinctTags(): Promise<Array<{ name: string; count: number }>> {
  try {
    const result = await callStore(['list_distinct_tags']);
    if (Array.isArray(result)) return result as Array<{ name: string; count: number }>;
  } catch {
    // Fallback: derive distinct tags from loaded sessions
    console.warn('[UAI] list_distinct_tags not available — deriving from session data');
  }
  return [];
}

/** If a session has a UUID but identity_status isn't confirmed, fix it. */
function resolveIdentityStatus(raw: Record<string, unknown>): Session['identity_status'] {
  const stored = (raw.identity_status as string) || 'confirmed';
  // A 'draft' is an intentional pre-launch state. Claude drafts now carry a
  // pre-assigned cli_session_id at reserve time (so the launch can reuse it as
  // --session-id), so UUID-presence no longer implies "launched". Only repair
  // stale non-draft states; a draft is confirmed by the launcher at actual
  // launch, never by a read-time heuristic.
  if (stored !== 'confirmed' && stored !== 'draft' && raw.cli_session_id) {
    // Has UUID but wasn't marked confirmed — auto-fix by updating store in background.
    const tid = raw.tracking_id as string;
    if (tid) {
      updateSession(tid, { identity_status: 'confirmed' }).catch(() => {});
    }
    return 'confirmed';
  }
  return stored as Session['identity_status'];
}

function mapSession(raw: Record<string, unknown>, pref?: SessionPref, tags?: string[], state?: Record<string, unknown>, promptBlock?: PromptBlockRow | null): Session {
  if (!state) {
    const sid = (raw.session_dir as string) || '';
    const tid = (raw.tracking_id as string) || '';
    state = getSessionState(sid, tid);
  }
  const p = pref || {};
  return {
    tracking_id: raw.tracking_id as string,
    cli_session_id: (raw.cli_session_id as string) || null,
    platform: raw.platform as Session['platform'],
    terminal_session: (raw.terminal_session as string) || null,
    session_dir: (raw.session_dir as string) || '',
    project_dir: (raw.project_dir as string) || '',
    history_file: (raw.history_file as string) || null,
    display_name: (raw.display_name as string) || null,
    roles: parseJsonArray(raw.roles),
    model: (raw.model as string) || null,
    parent_tracking_id: (raw.parent_tracking_id as string) || null,
    identity_status: resolveIdentityStatus(raw),
    process_status: mapProcessStatus(raw.status as string),
    archived: raw.archived === 1 || raw.archived === true || raw.archived === 'true' || raw.archived === '1',
    created_at: (raw.created_at as string) || '',
    runtime_state: 'unknown',
    // Live activity state, written into the per-session state file by scaffolding
    // (UserPromptSubmit→responding, Stop→idle, get-status→reconciled ground truth).
    // Read here exactly like last_activity below; the app never writes it.
    activity_state: (state['session.activity_state'] as Session['activity_state']) || 'unknown',
    context_percent: state['context.used_pct'] as number ?? null,
    exchange_count: (state['transcript.turns'] as number) || 0,
    message_count: (state['transcript.messages'] as number) ?? null,
    last_activity: (state['session.last_activity'] as string) || (raw.last_activity as string) || (raw.created_at as string) || '',
    start_history: Array.isArray(state['session.start_history'])
      ? (state['session.start_history'] as string[])
      : (Array.isArray(raw.start_history) ? (raw.start_history as string[]) : []),
    pinned: p.pinned ?? false,
    lastViewedAt: p.lastViewedAt ?? null,
    notes: p.notes ?? null,
    tags: tags ?? [],
    loaded_briefs: p.loaded_briefs ?? [],
    prompt_block: promptBlock
      ? {
          mode: promptBlock.mode,
          turns_remaining: promptBlock.turns_remaining ?? null,
          expires_at: promptBlock.expires_at ?? null,
          reason: promptBlock.reason ?? null,
        }
      : null,
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
  if (status === 'running' || status === 'active') return 'running';
  if (status === 'exited') return 'exited';
  return 'stopped';
}

// ─── Public API ───────────────────────────────────────────────────────────

export async function listSessions(): Promise<Session[]> {
  const [rows, allTags, blocks] = await Promise.all([
    callStore(['list', '--json']) as Promise<Record<string, unknown>[] | null>,
    getAllSessionTags(),
    getPromptBlocks(),
  ]);
  return (rows ?? []).map(raw => {
    const tid = raw.tracking_id as string;
    // Tags keyed by tracking_id (from get_all_session_tags) or session:tracking_id
    return mapSession(raw, getSessionPref(tid), allTags[tid] || allTags[`session:${tid}`], undefined, blocks.get(tid) ?? null);
  });
}

export async function getSession(trackingId: string): Promise<Session | null> {
  try {
    const [row, tags, blocks] = await Promise.all([
      callStore(['get', trackingId]) as Promise<Record<string, unknown>>,
      getTagsForSession(trackingId),
      getPromptBlocks(),
    ]);
    return mapSession(row, getSessionPref(trackingId), tags, undefined, blocks.get(trackingId) ?? null);
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
 * Reserve a draft session via the launcher (`--reserve`).
 *
 * Identity creation is owned exclusively by the launcher (ai_launcher.py) — see
 * session_mgmt/DESIGN.md, and UAI's own "External Ground Truth" principle. The
 * app must NOT mint tracking IDs itself: doing so in TypeScript (a) duplicated
 * the ID format, (b) used UTC while Python uses local time, and (c) threw away
 * the full UUID, so the reserved Claude session never adopted it and
 * `tracking_id` uuid8 diverged from `cli_session_id[:8]`.
 *
 * The launcher mints one UUID, derives the tracking-ID uuid8 from it, persists
 * the draft row (and, for Claude, stores the full UUID as cli_session_id so the
 * later launch reuses it as `--session-id`), then prints `TRACKING_ID=...`.
 */
function reserveDraftViaLauncher(opts: {
  platform: string;
  displayName?: string;
  projectDir?: string;
  roles?: string[];
  parentTrackingId?: string;
  notes?: string;
}): Promise<string> {
  return new Promise((resolve, reject) => {
    const aiRoot = getAiRootMain();
    const launcherNames: Record<string, string> = {
      claude_cli: 'claudeCli', codex_cli: 'codexCli', gemini_cli: 'geminiCli',
      grok_cli: 'grokCli', antigravity_cli: 'antigravityCli',
    };
    const launcherName = launcherNames[opts.platform] || 'claudeCli';
    const launcherPath = path.join(aiRoot, 'ai_general/scripts/cli', launcherName);

    const args: string[] = ['--reserve'];
    if (opts.displayName) args.push('--display-name', opts.displayName);
    if (opts.projectDir) args.push('-w', opts.projectDir);
    if (opts.parentTrackingId) args.push('--parent', opts.parentTrackingId);
    if (opts.roles && opts.roles.length > 0) args.push('-A', opts.roles.join(','));
    if (opts.notes && opts.notes.trim()) args.push('--notes', opts.notes.trim());

    execFile(launcherPath, args, {
      env: { ...process.env, PATH: getPythonPath(), AI_ROOT: aiRoot },
      maxBuffer: 10 * 1024 * 1024,
    }, (error, stdout, stderr) => {
      if (error) {
        reject(new Error(`${launcherName} --reserve failed: ${stderr || error.message}`));
        return;
      }
      const match = stdout.match(/^TRACKING_ID=(.+)$/m);
      if (!match) {
        reject(new Error(`${launcherName} --reserve: no TRACKING_ID in output: ${stdout.trim()}`));
        return;
      }
      resolve(match[1].trim());
    });
  });
}

export async function createDraftSession(opts: {
  platform: string;
  displayName?: string;
  projectDir?: string;
  roles?: string[];
  parentTrackingId?: string;
  notes?: string;
}): Promise<string> {
  const trackingId = await reserveDraftViaLauncher(opts);
  console.log(`[UAI] Draft session reserved via launcher: ${trackingId}`);
  return trackingId;
}

const LAUNCH_TIMEOUT_MS = 15000;

export async function launchSession(platform: string, trackingId: string, opts?: {
  workdir?: string;
  roles?: string;
  displayName?: string;
  appendSystemPrompt?: string;
  forkFrom?: string;
  model?: string;
}): Promise<{ ok: boolean; error?: string }> {
  const { spawn } = require('node:child_process');
  const aiRoot = getAiRoot();

  // Use platform-specific launcher symlink so ai_launcher.py detects
  // the correct platform from argv[0]
  const launcherNames: Record<string, string> = {
    claude_cli: 'claudeCli',
    codex_cli: 'codexCli',
    gemini_cli: 'geminiCli',
    grok_cli: 'grokCli',
    antigravity_cli: 'antigravityCli',
  };
  const launcherName = launcherNames[platform] || 'claudeCli';
  const launcherPath = path.join(aiRoot, 'ai_general/scripts/cli', launcherName);

  const args = [launcherPath];
  if (opts?.forkFrom) {
    args.push('--fork-from', opts.forkFrom);
    args.push('--tracking-id', trackingId);
  } else {
    args.push('--tracking-id', trackingId);
  }
  if (opts?.workdir) args.push('-w', opts.workdir);
  if (opts?.roles) args.push('-A', opts.roles);
  if (opts?.displayName) args.push('--display-name', opts.displayName);
  if (opts?.model) args.push('-m', opts.model);
  if (opts?.appendSystemPrompt) {
    args.push('--pre-prompt', opts.appendSystemPrompt);
  }

  return new Promise((resolve) => {
    let stderrChunks: string[] = [];
    let settled = false;

    const child = spawn(args[0], args.slice(1), {
      env: { ...process.env, PATH: getPythonPath() },
      detached: true,
      stdio: ['ignore', 'ignore', 'pipe'],  // capture stderr only
    });

    child.stderr.on('data', (chunk: Buffer) => {
      stderrChunks.push(chunk.toString());
    });

    const timeout = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.unref();
      markFailed(trackingId, 'Launch timed out').then(() =>
        resolve({ ok: false, error: `Launch timed out after ${LAUNCH_TIMEOUT_MS / 1000}s` })
      );
    }, LAUNCH_TIMEOUT_MS);

    child.on('error', (err: Error) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      markFailed(trackingId, err.message).then(() =>
        resolve({ ok: false, error: `Launcher failed to start: ${err.message}` })
      );
    });

    child.on('exit', (code: number | null, signal: string | null) => {
      if (settled) return;
      settled = true;
      clearTimeout(timeout);
      child.unref();

      if (code === 0) {
        // Launcher completed setup — CLI is now running in its tmux session.
        // Transition draft → pending (confirmation comes from sessionInfo appearing).
        markPending(trackingId).then(() => resolve({ ok: true }));
      } else {
        const stderr = stderrChunks.join('').trim();
        const detail = stderr
          ? stderr.split('\n').pop() || `exit code ${code}`
          : signal ? `killed by ${signal}` : `exit code ${code}`;
        markFailed(trackingId, detail).then(() =>
          resolve({ ok: false, error: `Launcher failed: ${detail}` })
        );
      }
    });
  });
}

async function markFailed(trackingId: string, reason: string): Promise<void> {
  try {
    await callStore(['update', trackingId, '--set', 'identity_status=failed']);
  } catch (err) {
    console.error(`[UAI] Failed to mark session ${trackingId} as failed:`, err);
  }
  console.error(`[UAI] Session launch failed: ${trackingId} — ${reason}`);
}

async function markPending(trackingId: string): Promise<void> {
  try {
    await callStore(['update', trackingId, '--set', 'identity_status=pending']);
  } catch (err) {
    console.error(`[UAI] Failed to mark session ${trackingId} as pending:`, err);
  }
  console.log(`[UAI] Session launched: ${trackingId} — pending confirmation`);
}
