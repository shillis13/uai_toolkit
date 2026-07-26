/**
 * Command Handlers — registers all command types on the bus.
 *
 * Each handler was previously an ad-hoc ipcMain.handle() call.
 * Now they're registered as typed command handlers on the CommandBus.
 *
 * Command type hierarchy:
 *   session.update   — update session fields
 *   session.create   — create draft + launch
 *   session.archive  — archive a session
 *   app.state.update — update app state
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import type { CommandBus } from './command-bus';
import type { Command, CommandResult, Session, FolderStoreData, Tag, EntityRelationship, RelationType, EntityType, Tab, TabType, SavedPrompt } from '@uai/shared/types';
import { listSessions, getSession, updateSession, createDraftSession, launchSession, callStore as callSessionStore } from './session-store';
import { closeStandaloneTerminal } from './terminal';
import { getAppStatePath } from './app-state-path';
import {
  createFolder, renameFolder, deleteFolder, moveFolder,
  moveCard, unfileCard, reorderSubfolders, reorderCards,
  getSnapshot as getFolderSnapshot, validateTree, loadFolders,
} from './folder-manager';
import {
  createContainer, renameContainer, deleteContainer,
  addCardToContainer, removeCardFromContainer,
  moveCard as containerMoveCard,
  reorderContainerCards, getContainerSnapshot,
} from './container-manager';
import { setEntityHidden, setRoleAssignment, setRoleContext, setMembers, setPlaybook, promoteTeamToProject, createTeam, updateEntity } from './project-indexer';
import { createBrief } from './brief-ops';
import { runSessionTraits } from './session-traits';
import { runTodoMgr, resolveTodoDir } from './todo-ops';
import { sendMessage } from './comms-reader';
import { callAiEngine } from './assigned-tasks';
import { aiRootMain as getAiRootMain, shellPath } from './paths';


/**
 * Deliver prompt text to a session's CLI via the substrate's TYPED path
 * (`session_ops write-to --delivery typed`, i.e. `tmux send-keys -l`) instead of a
 * raw-byte burst into the client PTY.
 *
 * Why: writing text bytes straight into the tmux client PTY (writeTerminal) arrives
 * as one fast burst, which Claude Code treats as a paste and folds into a
 * "[Pasted text #N]" chip — and, worse, file paths in the text get stripped on
 * submit. The substrate already sets `assume-paste-time 0`, and `send-keys -l`
 * injects the characters into the pane as typed input: no chip, paths preserved
 * byte-exact. `--enter` presses a real, named Enter key (not a swallowed CR), so a
 * single Enter submits cleanly — no double-Enter workaround needed.
 *
 * Text is passed via a temp file to sidestep arg-length and shell-escaping limits
 * for long / multi-line prompts.
 */
async function deliverPromptTyped(sessionId: string, text: string, submit: boolean): Promise<void> {
  const os = require('node:os');
  const { execFile: ef } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(ef);
  const aiRoot = getAiRootMain();
  const sessionOpsPy = path.join(aiRoot, 'ai_general/scripts/session_mgmt/session_ops.py');
  const envPath = shellPath();
  const env = { ...process.env, AI_ROOT: aiRoot, PATH: envPath } as Record<string, string>;

  const tmpFile = path.join(os.tmpdir(), `uai_prompt_${Date.now()}_${Math.random().toString(36).slice(2, 8)}.txt`);
  fs.writeFileSync(tmpFile, text, 'utf8');
  const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
  const runOps = (opsArgs: string[]) =>
    execFileAsync('python3', [sessionOpsPy, ...opsArgs], { timeout: 30_000, env });
  try {
    // 1. Type the text (send-keys -l) — no Enter yet.
    await runOps(['write-to', sessionId, '--text-file', tmpFile, '--delivery', 'typed']);
    if (!submit) return;
    // 2. Let the input SETTLE, then press Enter as a SEPARATE keystroke. Firing Enter
    //    immediately after a large send-keys -l races the input on a heavy/slow session
    //    (e.g. a 500k-token Opus fork): the Enter arrives before the CLI finishes
    //    ingesting the paste, so the prompt just stages instead of submitting. The pause
    //    lets it settle. Claude Code wants a SECOND Enter (the first commits the typed
    //    input, the second submits); a surplus Enter is a harmless no-op on the now-empty
    //    prompt, so it's safe for fast sessions too.
    await sleep(300);
    await runOps(['write-to', sessionId, '--text', '', '--delivery', 'typed', '--enter']);
    if (sessionId.endsWith('_cla')) {
      await sleep(400);
      await runOps(['write-to', sessionId, '--text', '', '--delivery', 'typed', '--enter']);
    }
  } finally {
    try { fs.unlinkSync(tmpFile); } catch { /* best-effort cleanup */ }
  }
}

// ─── Emit helper (injected from index.ts) ─────────────────────────────────

type EmitFn = (source: 'command' | 'external' | 'poll', changed: string[]) => void;

const VALID_TAB_TYPES = new Set<TabType>([
  'session',
  'folder',
  'terminal',
  'brief',
  'transcript',
  'search',
  'project',
  'team',
  'webai',
  'app',
  'markdown',
]);

type PersistedTab = Partial<Tab> & {
  sessionTrackingId?: unknown;
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value);
}

function isTabType(value: unknown): value is TabType {
  return typeof value === 'string' && VALID_TAB_TYPES.has(value as TabType);
}

function normalizePersistedTab(raw: unknown): Tab | null {
  if (!isRecord(raw)) {
    return null;
  }

  const candidate = raw as PersistedTab;
  const targetId =
    typeof candidate.targetId === 'string' && candidate.targetId
      ? candidate.targetId
      : typeof candidate.sessionTrackingId === 'string' && candidate.sessionTrackingId
        ? candidate.sessionTrackingId
        : '';

  if (!targetId) {
    return null;
  }

  const id =
    typeof candidate.id === 'string' && candidate.id
      ? candidate.id
      : `tab_legacy_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
  const label =
    typeof candidate.label === 'string' && candidate.label
      ? candidate.label
      : targetId;
  const openedAt =
    typeof candidate.openedAt === 'string' && candidate.openedAt
      ? candidate.openedAt
      : new Date().toISOString();

  return {
    id,
    type: isTabType(candidate.type) ? candidate.type : 'session',
    label,
    targetId,
    openedAt,
  };
}

export function normalizePersistedAppState(
  current: Record<string, unknown>,
): { state: Record<string, unknown>; changed: boolean } {
  const rawTabs = Array.isArray(current.tabs) ? current.tabs : [];
  let changed = !Array.isArray(current.tabs);

  const normalizedTabs: Tab[] = [];
  for (const rawTab of rawTabs) {
    const normalizedTab = normalizePersistedTab(rawTab);
    if (normalizedTab === null) {
      changed = true;
      continue;
    }
    if (!isRecord(rawTab)) {
      changed = true;
    } else if (
      rawTab.id !== normalizedTab.id ||
      rawTab.type !== normalizedTab.type ||
      rawTab.label !== normalizedTab.label ||
      rawTab.targetId !== normalizedTab.targetId ||
      rawTab.openedAt !== normalizedTab.openedAt ||
      'sessionTrackingId' in rawTab
    ) {
      changed = true;
    }
    normalizedTabs.push(normalizedTab);
  }

  const rawActiveTabId = typeof current.activeTabId === 'string' ? current.activeTabId : null;
  const normalizedActiveTabId = rawActiveTabId && normalizedTabs.some((tab) => tab.id === rawActiveTabId)
    ? rawActiveTabId
    : rawActiveTabId === null
      ? null
      : normalizedTabs.length > 0
        ? normalizedTabs[normalizedTabs.length - 1].id
        : null;

  if (normalizedActiveTabId !== rawActiveTabId) {
    changed = true;
  }

  if (!changed) {
    return { state: current, changed: false };
  }

  return {
    state: {
      ...current,
      tabs: normalizedTabs,
      activeTabId: normalizedActiveTabId,
    },
    changed: true,
  };
}

function loadNormalizedAppState(statePath: string): Record<string, unknown> {
  let current: Record<string, unknown> = {};
  try {
    const parsed = JSON.parse(fs.readFileSync(statePath, 'utf-8'));
    current = isRecord(parsed) ? parsed : {};
  } catch {
    current = {};
  }

  return normalizePersistedAppState(current).state;
}

/**
 * Close any open tabs that target the given entity ids. A tab's `targetId` holds
 * the entity id regardless of tab type (session tracking_id, folder/project/team
 * id), and entity ids don't collide across types, so a targetId match is sufficient.
 * Mirrors the inline tab cleanup in session.delete so EVERY entity deletion can
 * close its orphaned tab(s). Returns true if appState changed (caller should then
 * emit 'appState' so the renderer reloads its tabs). Best-effort; never throws.
 */
function closeTabsForTargets(targetIds: string[]): boolean {
  if (targetIds.length === 0) return false;
  const ids = new Set(targetIds);
  const statePath = getAppStatePath();
  let appState: { tabs?: Array<{ id: string; targetId: string }>; activeTabId?: string | null };
  try { appState = JSON.parse(fs.readFileSync(statePath, 'utf-8')); } catch { return false; }
  if (!Array.isArray(appState.tabs)) return false;
  const before = appState.tabs.length;
  appState.tabs = appState.tabs.filter((t) => !ids.has(t.targetId));
  if (appState.tabs.length === before) return false; // nothing matched — no write
  // Re-point activeTabId if the active tab was one of the closed ones.
  if (appState.activeTabId && !appState.tabs.some((t) => t.id === appState.activeTabId)) {
    appState.activeTabId = appState.tabs.length > 0 ? appState.tabs[appState.tabs.length - 1].id : null;
  }
  try { fs.writeFileSync(statePath, JSON.stringify(appState, null, 2)); } catch { return false; }
  return true;
}

// ─── Register All Handlers ────────────────────────────────────────────────

export function registerCommandHandlers(bus: CommandBus, emit: EmitFn): void {

  // ── session.update ────────────────────────────────────────────────────

  bus.register('session.update', async (command: Command): Promise<CommandResult> => {
    const { trackingId, patch } = command.payload as {
      trackingId: string;
      patch: Record<string, string>;
    };
    try {
      await updateSession(trackingId, patch);
      emit('command', ['sessions']);
      return {
        ok: true,
        command_id: command.id,
        changed: { sessions: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'UPDATE_FAILED', message },
      };
    }
  });

  // ── work.landscape ────────────────────────────────────────────────────
  // Read-only. Runs the cross-session work landscape (scripts/work/work_landscape.py
  // --enrich --json) and returns its model (rows + NEEDS PIANOMAN). Backs the Work
  // tab and the Ask-Hamilton needs-you counter. No mutation, no side effects —
  // reflects external ground truth (External Ground Truth principle).

  bus.register('work.landscape', async (command: Command): Promise<CommandResult<{ model: unknown }>> => {
    try {
      const { execFile: ef } = require('node:child_process');
      const { promisify } = require('node:util');
      const execFileAsync = promisify(ef);
      const rootMain = getAiRootMain();
      const scriptPath = path.join(rootMain, 'ai_general/scripts/work/work_landscape.py');

      const { stdout } = await execFileAsync('python3', [scriptPath, '--enrich', '--json'], {
        timeout: 20000,
        maxBuffer: 4 * 1024 * 1024,
        env: {
          ...process.env,
          AI_ROOT: rootMain,
          PATH: shellPath(),
        },
      });

      const model = JSON.parse(stdout);
      return { ok: true, command_id: command.id, data: { model } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[work.landscape] Failed:', message);
      return {
        ok: false, command_id: command.id,
        error: { code: 'LANDSCAPE_FAILED', message },
      };
    }
  });

  // ── work.decision.answer ──────────────────────────────────────────────
  // PM answers a "Needs Me" decision from the Live Board (todo_0578/0579):
  // mark it answered in the store (needs_user_mgr) AND route the answer back to
  // Hamilton so he actions it + relays to the source session; then it clears.
  bus.register('work.decision.answer', async (command: Command): Promise<CommandResult<{ result: unknown }>> => {
    const { id, answer } = command.payload as { id: string; answer: string };
    try {
      const { execFile: ef } = require('node:child_process');
      const { promisify } = require('node:util');
      const execFileAsync = promisify(ef);
      const rootMain = getAiRootMain();
      const scriptPath = path.join(rootMain, 'ai_general/scripts/work/needs_user_mgr.py');
      const { stdout } = await execFileAsync(
        'python3', [scriptPath, '--answer', String(id), '--text', String(answer), '--json'],
        { timeout: 15000, maxBuffer: 1024 * 1024, env: { ...process.env, AI_ROOT: rootMain, PATH: shellPath() } },
      );
      const res = JSON.parse(stdout);
      if (!res.success) {
        return { ok: false, command_id: command.id, error: { code: 'ANSWER_FAILED', message: res.error || 'answer failed' } };
      }
      const rec = res.record || {};
      const content =
        `PianoMan answered your escalated decision:\n\n` +
        `Decision: ${rec.decision || ''}\n` +
        `Answer:   ${answer}\n\n` +
        `Source: ${[rec.source_todo, rec.source_session].filter(Boolean).join(' · ') || '(n/a)'}\n\n` +
        `Please action it and relay to the source session.`;
      await sendMessage({ from: 'piano_man', to: 'Hamilton', content, urgency: 'prompt', responseType: 'acknowledge', subject: 'PM decision' });
      return { ok: true, command_id: command.id, data: { result: rec } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[work.decision.answer] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'ANSWER_FAILED', message } };
    }
  });

  // ── work.decision.dismiss ─────────────────────────────────────────────
  // PM dismisses/archives a "Needs Me" decision as already-addressed or moot
  // (todo_0579): mark it 'addressed' in the store (no routed answer) so it drops
  // off the board, and send Hamilton a light heads-up so he stops waiting on it.
  bus.register('work.decision.dismiss', async (command: Command): Promise<CommandResult<{ result: unknown }>> => {
    const { id, reason } = command.payload as { id: string; reason?: string };
    try {
      const { execFile: ef } = require('node:child_process');
      const { promisify } = require('node:util');
      const execFileAsync = promisify(ef);
      const rootMain = getAiRootMain();
      const scriptPath = path.join(rootMain, 'ai_general/scripts/work/needs_user_mgr.py');
      const args = [scriptPath, '--addressed', String(id), '--json'];
      if (reason && String(reason).trim()) { args.push('--text', String(reason)); }
      const { stdout } = await execFileAsync(
        'python3', args,
        { timeout: 15000, maxBuffer: 1024 * 1024, env: { ...process.env, AI_ROOT: rootMain, PATH: shellPath() } },
      );
      const res = JSON.parse(stdout);
      if (!res.success) {
        return { ok: false, command_id: command.id, error: { code: 'DISMISS_FAILED', message: res.error || 'dismiss failed' } };
      }
      const rec = res.record || {};
      const content =
        `PianoMan dismissed your escalated decision as already-addressed:\n\n` +
        `Decision: ${rec.decision || ''}\n` +
        `Reason:   ${(reason && String(reason).trim()) || '(marked already addressed)'}\n\n` +
        `Source: ${[rec.source_todo, rec.source_session].filter(Boolean).join(' · ') || '(n/a)'}\n\n` +
        `No action needed — it no longer needs the user.`;
      await sendMessage({ from: 'piano_man', to: 'Hamilton', content, urgency: 'async', responseType: 'acknowledge', subject: 'PM decision dismissed' });
      return { ok: true, command_id: command.id, data: { result: rec } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[work.decision.dismiss] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'DISMISS_FAILED', message } };
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  // NOTE COMMANDS — scripts/notes/notes_mgr.py (filesystem notes backend)
  // ═══════════════════════════════════════════════════════════════════════
  // Add Note + Ask Hamilton + Notes Mgr are ONE primitive over the same notes
  // store. These wrappers mirror work.landscape: run notes_mgr.py --json from
  // ai_root via execFileAsync and return the parsed model. Mutating commands
  // emit 'notes' so any open Notes Mgr re-reads.

  const runNotesMgr = async (args: string[]): Promise<unknown> => {
    const { execFile: ef } = require('node:child_process');
    const { promisify } = require('node:util');
    const execFileAsync = promisify(ef);
    const rootMain = getAiRootMain();
    const scriptPath = path.join(rootMain, 'ai_general/scripts/notes/notes_mgr.py');
    const { stdout } = await execFileAsync('python3', [scriptPath, '--json', ...args], {
      timeout: 20000,
      maxBuffer: 8 * 1024 * 1024,
      env: {
        ...process.env,
        AI_ROOT: rootMain,
        PATH: shellPath(),
      },
    });
    return JSON.parse(stdout);
  };

  // ── note.create ───────────────────────────────────────────────────────
  bus.register('note.create', async (command: Command): Promise<CommandResult<{ note: unknown }>> => {
    const { text, recipients, sourceTab, createdBy, name, title, status } = command.payload as {
      text: string;
      recipients?: string[];
      sourceTab?: string;
      createdBy?: string;
      name?: string;
      title?: string;
      status?: string;
    };
    try {
      const args = ['create', '--text', text];
      if (recipients && recipients.length > 0) args.push('--recipients', recipients.join(','));
      if (sourceTab) args.push('--source-tab', sourceTab);
      if (createdBy) args.push('--created-by', createdBy);
      if (name) args.push('--name', name);
      if (title) args.push('--title', title);
      if (status) args.push('--status', status);
      const note = await runNotesMgr(args);
      emit('command', ['notes']);
      return { ok: true, command_id: command.id, data: { note }, changed: { notes: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[note.create] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'NOTE_CREATE_FAILED', message } };
    }
  });

  // ── note.setTitle ─────────────────────────────────────────────────────
  bus.register('note.setTitle', async (command: Command): Promise<CommandResult<{ result: unknown }>> => {
    const { id, title } = command.payload as { id: string; title: string };
    try {
      const result = await runNotesMgr(['set-title', '--id', id, '--title', title ?? '']);
      emit('command', ['notes']);
      return { ok: true, command_id: command.id, data: { result }, changed: { notes: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[note.setTitle] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'NOTE_SET_TITLE_FAILED', message } };
    }
  });

  // ── note.list ─────────────────────────────────────────────────────────
  bus.register('note.list', async (command: Command): Promise<CommandResult<{ notes: unknown }>> => {
    const { status, recipient } = command.payload as { status?: string; recipient?: string };
    try {
      const args = ['list'];
      if (status) args.push('--status', status);
      if (recipient) args.push('--recipient', recipient);
      const result = await runNotesMgr(args) as { notes?: unknown };
      return { ok: true, command_id: command.id, data: { notes: result.notes ?? [] } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[note.list] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'NOTE_LIST_FAILED', message } };
    }
  });

  // ── note.read ─────────────────────────────────────────────────────────
  bus.register('note.read', async (command: Command): Promise<CommandResult<{ note: unknown }>> => {
    const { id } = command.payload as { id: string };
    try {
      const note = await runNotesMgr(['read', '--id', id]);
      return { ok: true, command_id: command.id, data: { note } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[note.read] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'NOTE_READ_FAILED', message } };
    }
  });

  // ── note.addMessage ───────────────────────────────────────────────────
  bus.register('note.addMessage', async (command: Command): Promise<CommandResult<{ result: unknown }>> => {
    const { id, author, body, replyTo } = command.payload as {
      id: string;
      author: string;
      body: string;
      replyTo?: string;
    };
    try {
      const args = ['add-message', '--id', id, '--author', author, '--body', body];
      if (replyTo) args.push('--reply-to', replyTo);
      const result = await runNotesMgr(args);
      emit('command', ['notes']);
      return { ok: true, command_id: command.id, data: { result }, changed: { notes: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[note.addMessage] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'NOTE_ADD_MESSAGE_FAILED', message } };
    }
  });

  // ── note.edit ─────────────────────────────────────────────────────────
  bus.register('note.edit', async (command: Command): Promise<CommandResult<{ result: unknown }>> => {
    const { id, text } = command.payload as { id: string; text: string };
    try {
      const result = await runNotesMgr(['edit', '--id', id, '--text', text]);
      emit('command', ['notes']);
      return { ok: true, command_id: command.id, data: { result }, changed: { notes: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[note.edit] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'NOTE_EDIT_FAILED', message } };
    }
  });

  // ── note.linkTodo ─────────────────────────────────────────────────────
  bus.register('note.linkTodo', async (command: Command): Promise<CommandResult<{ result: unknown }>> => {
    const { id, todo } = command.payload as { id: string; todo: string };
    try {
      const result = await runNotesMgr(['link-todo', '--id', id, '--todo', todo]);
      emit('command', ['notes']);
      return { ok: true, command_id: command.id, data: { result }, changed: { notes: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[note.linkTodo] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'NOTE_LINK_TODO_FAILED', message } };
    }
  });

  // ── note.setStatus ────────────────────────────────────────────────────
  bus.register('note.setStatus', async (command: Command): Promise<CommandResult<{ result: unknown }>> => {
    const { id, status } = command.payload as { id: string; status: string };
    try {
      const result = await runNotesMgr(['set-status', '--id', id, '--status', status]);
      emit('command', ['notes']);
      return { ok: true, command_id: command.id, data: { result }, changed: { notes: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[note.setStatus] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'NOTE_SET_STATUS_FAILED', message } };
    }
  });

  // ── note.addCapture ───────────────────────────────────────────────────
  bus.register('note.addCapture', async (command: Command): Promise<CommandResult<{ result: unknown }>> => {
    const { id, componentPath, sourceTab, data } = command.payload as {
      id: string;
      componentPath: string;
      sourceTab?: string;
      data?: string;
    };
    try {
      const args = ['add-capture', '--id', id, '--component-path', componentPath];
      if (sourceTab) args.push('--source-tab', sourceTab);
      if (data) args.push('--data', data);
      const result = await runNotesMgr(args);
      emit('command', ['notes']);
      return { ok: true, command_id: command.id, data: { result }, changed: { notes: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[note.addCapture] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'NOTE_ADD_CAPTURE_FAILED', message } };
    }
  });

  // ── note.deleteCapture ────────────────────────────────────────────────
  bus.register('note.deleteCapture', async (command: Command): Promise<CommandResult<{ result: unknown }>> => {
    const { id, file } = command.payload as { id: string; file: string };
    try {
      const result = await runNotesMgr(['delete-capture', '--id', id, '--file', file]);
      emit('command', ['notes']);
      return { ok: true, command_id: command.id, data: { result }, changed: { notes: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[note.deleteCapture] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'NOTE_DELETE_CAPTURE_FAILED', message } };
    }
  });

  // ── session.create ────────────────────────────────────────────────────

  bus.register('session.create', async (command: Command): Promise<CommandResult<{ trackingId: string }>> => {
    const opts = command.payload as {
      platform: string;
      displayName?: string;
      projectDir?: string;
      roles?: string[];
      parentTrackingId?: string;
      contextItems?: Array<{ type: string; name: string; filePath?: string }>;
      model?: string;
      prePrompt?: string;
      notes?: string;
    };
    try {
      const trackingId = await createDraftSession(opts);
      emit('command', ['sessions']);  // emit immediately so draft appears in UI

      // Stage context items for delivery via the hook pipeline.
      // Items are written as .ref files into context_to_load/ and delivered
      // on the session's first prompt by 06_deliver_pending_context_sync.py.
      if (opts.contextItems && opts.contextItems.length > 0) {
        for (const item of opts.contextItems) {
          try {
            await runSessionTraits(['--session', trackingId, '--json', 'pend', item.type, item.name]);
          } catch (e) {
            console.warn(`[UAI] Failed to pend context ${item.type}/${item.name}:`, e);
          }
        }
      }

      const launch = await launchSession(opts.platform, trackingId, {
        workdir: opts.projectDir,
        roles: opts.roles?.join(','),
        displayName: opts.displayName,
        forkFrom: opts.parentTrackingId,
        model: opts.model,
        appendSystemPrompt: opts.prePrompt,
      });

      emit('command', ['sessions']);  // emit again to reflect pending/failed status

      if (!launch.ok) {
        return {
          ok: false,
          command_id: command.id,
          data: { trackingId },
          error: { code: 'LAUNCH_FAILED', message: launch.error || 'Unknown launch error' },
          changed: { sessions: true },
        };
      }

      return {
        ok: true,
        command_id: command.id,
        data: { trackingId },
        changed: { sessions: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'CREATE_FAILED', message },
      };
    }
  });

  // ── session.setBriefs ─────────────────────────────────────────────────
  // Record which briefs were loaded into a session's context.
  // Stored in app_state.json sessionPrefs (same pattern as notes).

  bus.register('session.setBriefs', async (command: Command): Promise<CommandResult> => {
    const { trackingId, briefs } = command.payload as {
      trackingId: string;
      briefs: string[];
    };
    try {
      const aiRoot = getAiRootMain();
      const statePath = getAppStatePath();
      const current = loadNormalizedAppState(statePath);
      const prefs = (current.sessionPrefs || {}) as Record<string, Record<string, unknown>>;
      const sessionPref = prefs[trackingId] || {};
      const updated = {
        ...current,
        sessionPrefs: {
          ...prefs,
          [trackingId]: { ...sessionPref, loaded_briefs: briefs },
        },
      };
      fs.writeFileSync(statePath, JSON.stringify(updated, null, 2));
      emit('command', ['appState', 'sessions']);
      return {
        ok: true,
        command_id: command.id,
        changed: { appState: true, sessions: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'SET_BRIEFS_FAILED', message },
      };
    }
  });

  // ── session.stop ─────────────────────────────────────────────────────

  bus.register('session.stop', async (command: Command): Promise<CommandResult> => {
    const { trackingId, force } = command.payload as { trackingId: string; force?: boolean };
    try {
      // Get session to find terminal session name
      const session = await getSession(trackingId);
      if (!session) {
        return {
          ok: false, command_id: command.id,
          error: { code: 'NOT_FOUND', message: `Session ${trackingId} not found` },
        };
      }

      // If already stopped, just return success
      if (session.process_status !== 'running') {
        return { ok: true, command_id: command.id, changed: {} };
      }

      const terminalName = session.terminal_session || trackingId;
      const { execFile: ef } = require('node:child_process');
      const { promisify } = require('node:util');
      const execFileAsync = promisify(ef);
      const rootMain = getAiRootMain();
      const sessionOpsPath = path.join(rootMain, 'ai_general/scripts/session_mgmt/session_ops.py');

      const killArgs = [sessionOpsPath, 'kill', terminalName];
      if (force === true) {
        killArgs.push('--force');
      }

      await execFileAsync('python3', killArgs, {
        timeout: 15000,
        env: {
          ...process.env,
          AI_ROOT: rootMain,
          PATH: shellPath(),
        },
      });

      emit('command', ['sessions']);
      return {
        ok: true, command_id: command.id,
        changed: { sessions: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[session.stop] Failed:', message);
      return {
        ok: false, command_id: command.id,
        error: { code: 'STOP_FAILED', message },
      };
    }
  });

  // ── session.block / session.unblock (prompt-blocks) ───────────────────────
  // Block/unblock a session from receiving prompts from anyone but PianoMan
  // (Noctis's prompt_blocks backend). Mutating wrappers over the same CLI the
  // read-only 🔒 chip already reads via `prompt_blocks.py list`. After the write
  // we emit a 'sessions' refresh so the list re-reads the blocks and the chip
  // flips immediately.

  const runPromptBlocks = async (args: string[]): Promise<void> => {
    const { execFile: ef } = require('node:child_process');
    const { promisify } = require('node:util');
    const execFileAsync = promisify(ef);
    const rootMain = getAiRootMain();
    const scriptPath = path.join(rootMain, 'ai_general/scripts/messages/prompt_blocks.py');
    await execFileAsync('python3', [scriptPath, ...args], {
      timeout: 15000,
      env: {
        ...process.env,
        AI_ROOT: rootMain,
        PATH: shellPath(),
      },
    });
  };

  bus.register('session.block', async (command: Command): Promise<CommandResult> => {
    const { trackingId, turns, until, reason } = command.payload as {
      trackingId: string; turns?: number; until?: string; reason?: string;
    };
    try {
      const args = ['block', trackingId];
      if (turns != null) args.push('--turns', String(turns));
      else if (until) args.push('--until', until);
      else args.push('--indefinite');
      if (reason) args.push('--reason', reason);
      await runPromptBlocks(args);
      emit('command', ['sessions']);
      return { ok: true, command_id: command.id, changed: { sessions: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[session.block] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'BLOCK_FAILED', message } };
    }
  });

  bus.register('session.unblock', async (command: Command): Promise<CommandResult> => {
    const { trackingId } = command.payload as { trackingId: string };
    try {
      await runPromptBlocks(['unblock', trackingId]);
      emit('command', ['sessions']);
      return { ok: true, command_id: command.id, changed: { sessions: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[session.unblock] Failed:', message);
      return { ok: false, command_id: command.id, error: { code: 'UNBLOCK_FAILED', message } };
    }
  });

  // ── session.resume ────────────────────────────────────────────────────

  bus.register('session.resume', async (command: Command): Promise<CommandResult> => {
    const { trackingId, workdir, model, roles, prePrompt } = command.payload as {
      trackingId: string;
      workdir?: string;
      model?: string;
      roles?: string[];
      prePrompt?: string;
    };
    try {
      const session = await getSession(trackingId);
      if (!session) {
        return {
          ok: false, command_id: command.id,
          error: { code: 'NOT_FOUND', message: `Session ${trackingId} not found` },
        };
      }

      // Use the platform-specific launcher with --resume flag
      const { spawn: sp } = require('node:child_process');
      const rootMain = getAiRootMain();
      const launcherNames: Record<string, string> = {
        claude_cli: 'claudeCli',
        codex_cli: 'codexCli',
        gemini_cli: 'geminiCli',
        grok_cli: 'grokCli',
        antigravity_cli: 'antigravityCli',
      };
      const platform = session.platform || 'claude_cli';
      const launcherName = launcherNames[platform] || 'claudeCli';
      const launcherPath = path.join(rootMain, 'ai_general/scripts/cli', launcherName);

      const args = [launcherPath, '--resume', trackingId];
      // Custom overrides take precedence over the session's stored values
      const effectiveWorkdir = workdir || session.project_dir;
      if (effectiveWorkdir) args.push('-w', effectiveWorkdir);
      if (model) args.push('-m', model);
      if (roles && roles.length > 0) args.push('-A', roles.join(','));
      if (prePrompt) args.push('--pre-prompt', prePrompt);

      const pythonPath = shellPath();

      return new Promise((resolve) => {
        let stderrChunks: string[] = [];
        let settled = false;

        const child = sp(args[0], args.slice(1), {
          env: { ...process.env, PATH: pythonPath },
          detached: true,
          stdio: ['ignore', 'ignore', 'pipe'],
        });

        child.stderr.on('data', (chunk: Buffer) => {
          stderrChunks.push(chunk.toString());
        });

        const timeout = setTimeout(() => {
          if (settled) return;
          settled = true;
          child.unref();
          resolve({
            ok: false, command_id: command.id,
            error: { code: 'RESUME_TIMEOUT', message: `Resume timed out after 15s` },
          });
        }, 15000);

        child.on('error', (err: Error) => {
          if (settled) return;
          settled = true;
          clearTimeout(timeout);
          resolve({
            ok: false, command_id: command.id,
            error: { code: 'RESUME_FAILED', message: `Launcher failed to start: ${err.message}` },
          });
        });

        child.on('exit', (code: number | null, signal: string | null) => {
          if (settled) return;
          settled = true;
          clearTimeout(timeout);
          child.unref();

          if (code === 0) {
            emit('command', ['sessions']);
            resolve({
              ok: true, command_id: command.id,
              changed: { sessions: true },
            });
          } else {
            const stderr = stderrChunks.join('').trim();
            const detail = stderr
              ? stderr.split('\n').pop() || `exit code ${code}`
              : signal ? `killed by ${signal}` : `exit code ${code}`;
            resolve({
              ok: false, command_id: command.id,
              error: { code: 'RESUME_FAILED', message: `Resume failed: ${detail}` },
            });
          }
        });
      });
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      console.warn('[session.resume] Failed:', message);
      return {
        ok: false, command_id: command.id,
        error: { code: 'RESUME_FAILED', message },
      };
    }
  });

  // ── session.archive ───────────────────────────────────────────────────

  bus.register('session.archive', async (command: Command): Promise<CommandResult> => {
    const { trackingId } = command.payload as { trackingId: string };
    try {
      await updateSession(trackingId, { archived: 'true' });
      emit('command', ['sessions']);
      return {
        ok: true,
        command_id: command.id,
        changed: { sessions: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'ARCHIVE_FAILED', message },
      };
    }
  });

  // ── session.unarchive ────────────────────────────────────────────────

  bus.register('session.unarchive', async (command: Command): Promise<CommandResult> => {
    const { trackingId } = command.payload as { trackingId: string };
    try {
      await updateSession(trackingId, { archived: 'false' });
      emit('command', ['sessions']);
      return {
        ok: true,
        command_id: command.id,
        changed: { sessions: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'UNARCHIVE_FAILED', message },
      };
    }
  });

  // ── session.delete ──────────────────────────────────────────────────

  bus.register('session.delete', async (command: Command): Promise<CommandResult> => {
    const { trackingId } = command.payload as { trackingId: string };
    try {
      // 1. Archive the session
      await updateSession(trackingId, { archived: 'true' });

      // 2. Remove from all tabs
      const aiRoot = getAiRootMain();
      const statePath = getAppStatePath();
      const loadNormalized = (p: string) => {
        try { return JSON.parse(fs.readFileSync(p, 'utf-8')); } catch { return {}; }
      };
      const appState = loadNormalized(statePath);
      if (appState.tabs) {
        appState.tabs = appState.tabs.filter((t: any) => t.targetId !== trackingId);
        // If active tab was deleted, switch to last remaining tab
        if (appState.activeTabId) {
          const activeTab = appState.tabs.find((t: any) => t.id === appState.activeTabId);
          if (!activeTab && appState.tabs.length > 0) {
            appState.activeTabId = appState.tabs[appState.tabs.length - 1].id;
          } else if (appState.tabs.length === 0) {
            appState.activeTabId = null;
          }
        }
        fs.writeFileSync(statePath, JSON.stringify(appState, null, 2));
      }

      // 3. Remove from containers (folders + groups)
      const containersPath = path.join(aiRoot, 'ai_general', 'data', 'containers.json');
      try {
        const containersData = JSON.parse(fs.readFileSync(containersPath, 'utf-8'));
        const cardId = `session:${trackingId}`;
        for (const container of Object.values(containersData.containers || {})) {
          const c = container as any;
          if (c.cards && Array.isArray(c.cards)) {
            c.cards = c.cards.filter((id: string) => id !== cardId);
          }
        }
        fs.writeFileSync(containersPath, JSON.stringify(containersData, null, 2));
      } catch { /* containers.json may not exist */ }

      emit('command', ['sessions', 'appState', 'folders']);
      return {
        ok: true,
        command_id: command.id,
        changed: { sessions: true, appState: true, folders: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'DELETE_FAILED', message },
      };
    }
  });

  // ── app.state.update ─────────────────────────────────────────────────

  bus.register('app.state.update', async (command: Command): Promise<CommandResult> => {
    const { patch } = command.payload as { patch: Record<string, unknown> };
    try {
      const aiRoot = getAiRootMain();
      const statePath = getAppStatePath();
      const current = loadNormalizedAppState(statePath);
      const updated = { ...current, ...patch };
      fs.writeFileSync(statePath, JSON.stringify(updated, null, 2));
      emit('command', ['appState']);
      return {
        ok: true,
        command_id: command.id,
        changed: { appState: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'APP_STATE_UPDATE_FAILED', message },
      };
    }
  });

  // ── folder.create ──────────────────────────────────────────────────────

  bus.register('folder.create', async (command: Command): Promise<CommandResult<{ folderId: string }>> => {
    const { parentId, name, icon } = command.payload as {
      parentId: string;
      name: string;
      icon?: string;
    };
    try {
      const { store, folderId } = createFolder(parentId, name, icon);
      emit('command', ['folders']);
      return {
        ok: true,
        command_id: command.id,
        data: { folderId },
        changed: { folders: true },
        snapshots: { folders: store },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'FOLDER_CREATE_FAILED', message },
      };
    }
  });

  // ── folder.rename ─────────────────────────────────────────────────────

  bus.register('folder.rename', async (command: Command): Promise<CommandResult> => {
    const { folderId, name } = command.payload as { folderId: string; name: string };
    try {
      const store = renameFolder(folderId, name);
      emit('command', ['folders']);
      return {
        ok: true,
        command_id: command.id,
        changed: { folders: true },
        snapshots: { folders: store },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'FOLDER_RENAME_FAILED', message },
      };
    }
  });

  // ── folder.delete ─────────────────────────────────────────────────────

  bus.register('folder.delete', async (command: Command): Promise<CommandResult> => {
    const { folderId, policy } = command.payload as {
      folderId: string;
      policy?: 'reparent' | 'cascade';
    };
    try {
      const store = deleteFolder(folderId, policy);
      const tabsChanged = closeTabsForTargets([folderId]);
      emit('command', tabsChanged ? ['folders', 'appState'] : ['folders']);
      return {
        ok: true,
        command_id: command.id,
        changed: { folders: true, ...(tabsChanged ? { appState: true } : {}) },
        snapshots: { folders: store },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'FOLDER_DELETE_FAILED', message },
      };
    }
  });

  // ── folder.moveFolder ─────────────────────────────────────────────────

  bus.register('folder.moveFolder', async (command: Command): Promise<CommandResult> => {
    const { folderId, targetParentId, index } = command.payload as {
      folderId: string;
      targetParentId: string;
      index?: number;
    };
    try {
      const store = moveFolder(folderId, targetParentId, index);
      emit('command', ['folders']);
      return {
        ok: true,
        command_id: command.id,
        changed: { folders: true },
        snapshots: { folders: store },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'FOLDER_MOVE_FAILED', message },
      };
    }
  });

  // ── folder.moveCard ───────────────────────────────────────────────────

  bus.register('folder.moveCard', async (command: Command): Promise<CommandResult> => {
    const { cardId, targetFolderId, index } = command.payload as {
      cardId: string;
      targetFolderId: string;
      index?: number;
    };
    try {
      const store = moveCard(cardId, targetFolderId, index);
      emit('command', ['folders']);
      return {
        ok: true,
        command_id: command.id,
        changed: { folders: true },
        snapshots: { folders: store },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'CARD_MOVE_FAILED', message },
      };
    }
  });

  // ── folder.unfileCard ─────────────────────────────────────────────────

  bus.register('folder.unfileCard', async (command: Command): Promise<CommandResult> => {
    const { cardId } = command.payload as { cardId: string };
    try {
      const store = unfileCard(cardId);
      emit('command', ['folders']);
      return {
        ok: true,
        command_id: command.id,
        changed: { folders: true },
        snapshots: { folders: store },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'UNFILE_FAILED', message },
      };
    }
  });

  // ── folder.reorderSubfolders ──────────────────────────────────────────

  bus.register('folder.reorderSubfolders', async (command: Command): Promise<CommandResult> => {
    const { parentId, orderedIds } = command.payload as {
      parentId: string;
      orderedIds: string[];
    };
    try {
      const store = reorderSubfolders(parentId, orderedIds);
      emit('command', ['folders']);
      return {
        ok: true,
        command_id: command.id,
        changed: { folders: true },
        snapshots: { folders: store },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'SUBFOLDER_REORDER_FAILED', message },
      };
    }
  });

  // ── folder.reorderCards ───────────────────────────────────────────────

  bus.register('folder.reorderCards', async (command: Command): Promise<CommandResult> => {
    const { folderId, orderedCardIds } = command.payload as {
      folderId: string;
      orderedCardIds: string[];
    };
    try {
      const store = reorderCards(folderId, orderedCardIds);
      emit('command', ['folders']);
      return {
        ok: true,
        command_id: command.id,
        changed: { folders: true },
        snapshots: { folders: store },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'CARD_REORDER_FAILED', message },
      };
    }
  });

  // ── folder.getSnapshot ────────────────────────────────────────────────

  bus.register('folder.getSnapshot', async (command: Command): Promise<CommandResult<FolderStoreData>> => {
    try {
      const store = getFolderSnapshot();
      return {
        ok: true,
        command_id: command.id,
        data: store,
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'SNAPSHOT_FAILED', message },
      };
    }
  });

  // ── folder.validateTree ───────────────────────────────────────────────

  bus.register('folder.validateTree', async (command: Command): Promise<CommandResult<{ errors: string[] }>> => {
    try {
      const store = loadFolders();
      const errors = validateTree(store);
      return {
        ok: true,
        command_id: command.id,
        data: { errors },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'VALIDATE_FAILED', message },
      };
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  // GENERIC CONTAINER COMMANDS — Phase 2A
  // ═══════════════════════════════════════════════════════════════════════

  bus.register('container.create', async (command: Command): Promise<CommandResult<{ containerId: string }>> => {
    const { type, name, parentId, icon, color } = command.payload as {
      type: 'folder';
      name: string;
      parentId: string;
      icon?: string;
      color?: string;
    };
    try {
      const { containerId } = createContainer(type, name, parentId, { icon, color });
      emit('command', ['folders']);
      return {
        ok: true, command_id: command.id,
        data: { containerId },
        changed: { folders: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'CONTAINER_CREATE_FAILED', message } };
    }
  });

  bus.register('container.delete', async (command: Command): Promise<CommandResult> => {
    const { containerId, policy } = command.payload as {
      containerId: string;
      policy?: 'reparent' | 'cascade';
    };
    try {
      deleteContainer(containerId, policy);
      // Containers are folders/projects/teams — close any open tab for the deleted one.
      const tabsChanged = closeTabsForTargets([containerId]);
      emit('command', tabsChanged ? ['folders', 'appState'] : ['folders']);
      return { ok: true, command_id: command.id, changed: { folders: true, ...(tabsChanged ? { appState: true } : {}) } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'CONTAINER_DELETE_FAILED', message } };
    }
  });

  bus.register('container.rename', async (command: Command): Promise<CommandResult> => {
    const { containerId, name } = command.payload as { containerId: string; name: string };
    try {
      renameContainer(containerId, name);
      emit('command', ['folders']);
      return { ok: true, command_id: command.id, changed: { folders: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'CONTAINER_RENAME_FAILED', message } };
    }
  });

  bus.register('container.addCard', async (command: Command): Promise<CommandResult> => {
    const { containerId, cardId } = command.payload as { containerId: string; cardId: string };
    try {
      addCardToContainer(containerId, cardId);
      emit('command', ['folders']);
      return { ok: true, command_id: command.id, changed: { folders: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'CONTAINER_ADD_FAILED', message } };
    }
  });

  bus.register('container.removeCard', async (command: Command): Promise<CommandResult> => {
    const { containerId, cardId } = command.payload as { containerId: string; cardId: string };
    try {
      removeCardFromContainer(containerId, cardId);
      emit('command', ['folders']);
      return { ok: true, command_id: command.id, changed: { folders: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'CONTAINER_REMOVE_FAILED', message } };
    }
  });

  bus.register('container.moveCard', async (command: Command): Promise<CommandResult> => {
    const { cardId, fromContainerId, toContainerId, index } = command.payload as {
      cardId: string;
      fromContainerId: string;
      toContainerId: string;
      index?: number;
    };
    try {
      containerMoveCard(cardId, fromContainerId, toContainerId, index);
      emit('command', ['folders']);
      return { ok: true, command_id: command.id, changed: { folders: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'CONTAINER_MOVE_FAILED', message } };
    }
  });

  bus.register('container.reorder', async (command: Command): Promise<CommandResult> => {
    const { containerId, orderedCardIds } = command.payload as {
      containerId: string;
      orderedCardIds: string[];
    };
    try {
      reorderContainerCards(containerId, orderedCardIds);
      emit('command', ['folders']);
      return { ok: true, command_id: command.id, changed: { folders: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'CONTAINER_REORDER_FAILED', message } };
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  // TAG COMMANDS — SQLite card_tags via session_store.py
  // ═══════════════════════════════════════════════════════════════════════

  // ── tag.create ────────────────────────────────────────────────────────

  bus.register('tag.create', async (command: Command): Promise<CommandResult<{ tag: Tag }>> => {
    const { name, color, icon, entity_types } = command.payload as {
      name: string;
      color?: string;
      icon?: string;
      entity_types?: string[];
    };
    try {
      // Tags in session_store.py are implicit — they exist when added to a card.
      // tag.create is a no-op stub: tag definitions (color, icon) are not
      // persisted yet. Returns the constructed tag but does NOT emit a change
      // event (no data was written, so re-fetch would return empty).
      // Future: persist tag definitions in a tags table.
      return {
        ok: true,
        command_id: command.id,
        data: {
          tag: {
            name,
            color: color || null,
            icon: icon || null,
            entity_types: (entity_types || ['session', 'brief']) as EntityType[],
          },
        },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'TAG_CREATE_FAILED', message },
      };
    }
  });

  // ── tag.add ───────────────────────────────────────────────────────────

  bus.register('tag.add', async (command: Command): Promise<CommandResult> => {
    const { cardId, tag } = command.payload as { cardId: string; tag: string };
    try {
      await callSessionStore(['add_tag', cardId, tag]);
      emit('command', ['sessions', 'tags']);
      return {
        ok: true,
        command_id: command.id,
        changed: { sessions: true, tags: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'TAG_ADD_FAILED', message },
      };
    }
  });

  // ── tag.remove ────────────────────────────────────────────────────────

  bus.register('tag.remove', async (command: Command): Promise<CommandResult> => {
    const { cardId, tag } = command.payload as { cardId: string; tag: string };
    try {
      await callSessionStore(['remove_tag', cardId, tag]);
      emit('command', ['sessions', 'tags']);
      return {
        ok: true,
        command_id: command.id,
        changed: { sessions: true, tags: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'TAG_REMOVE_FAILED', message },
      };
    }
  });

  // ── tag.toggle ────────────────────────────────────────────────────────

  bus.register('tag.toggle', async (command: Command): Promise<CommandResult> => {
    const { cardId, tag } = command.payload as { cardId: string; tag: string };
    try {
      // Check if tag exists, then add or remove
      const existingTags = await callSessionStore(['get_tags', cardId]) as string[];
      const hasTag = Array.isArray(existingTags) && existingTags.includes(tag);
      if (hasTag) {
        await callSessionStore(['remove_tag', cardId, tag]);
      } else {
        await callSessionStore(['add_tag', cardId, tag]);
      }
      emit('command', ['sessions', 'tags']);
      return {
        ok: true,
        command_id: command.id,
        changed: { sessions: true, tags: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'TAG_TOGGLE_FAILED', message },
      };
    }
  });

  // ── tag.rename ───────────────────────────────────────────────────────
  // Renames a tag across all sessions that have it.
  // Implemented as: find all cards with oldTag, remove oldTag, add newTag.

  bus.register('tag.rename', async (command: Command): Promise<CommandResult> => {
    const { oldTag, newTag } = command.payload as { oldTag: string; newTag: string };
    try {
      // Find all card_ids that have this tag
      const cardIds = await callSessionStore(['find_by_tag', oldTag]) as string[];
      if (Array.isArray(cardIds)) {
        for (const cardId of cardIds) {
          await callSessionStore(['remove_tag', cardId, oldTag]);
          await callSessionStore(['add_tag', cardId, newTag]);
        }
      }
      emit('command', ['sessions', 'tags']);
      return {
        ok: true,
        command_id: command.id,
        changed: { sessions: true, tags: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'TAG_RENAME_FAILED', message },
      };
    }
  });

  // ── tag.delete ───────────────────────────────────────────────────────
  // Deletes a tag from all sessions that have it.

  bus.register('tag.delete', async (command: Command): Promise<CommandResult> => {
    const { tag } = command.payload as { tag: string };
    try {
      // Find all card_ids that have this tag and remove it
      const cardIds = await callSessionStore(['find_by_tag', tag]) as string[];
      if (Array.isArray(cardIds)) {
        for (const cardId of cardIds) {
          await callSessionStore(['remove_tag', cardId, tag]);
        }
      }
      emit('command', ['sessions', 'tags']);
      return {
        ok: true,
        command_id: command.id,
        changed: { sessions: true, tags: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'TAG_DELETE_FAILED', message },
      };
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  // RELATIONSHIP COMMANDS — SQLite entity_relationships via session_store.py
  // ═══════════════════════════════════════════════════════════════════════

  // ── relationship.link ─────────────────────────────────────────────────

  bus.register('relationship.link', async (command: Command): Promise<CommandResult> => {
    const { sourceType, sourceId, relationType, targetType, targetId, metadata } = command.payload as {
      sourceType: string;
      sourceId: string;
      relationType: RelationType;
      targetType: string;
      targetId: string;
      metadata?: Record<string, unknown>;
    };
    try {
      const args = ['add_relationship', sourceType, sourceId, relationType, targetType, targetId];
      if (metadata) {
        args.push('--metadata', JSON.stringify(metadata));
      }
      await callSessionStore(args);
      emit('command', ['relationships']);
      return {
        ok: true,
        command_id: command.id,
        changed: { relationships: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'LINK_FAILED', message },
      };
    }
  });

  // ── relationship.unlink ───────────────────────────────────────────────

  bus.register('relationship.unlink', async (command: Command): Promise<CommandResult> => {
    const { sourceType, sourceId, relationType, targetType, targetId } = command.payload as {
      sourceType: string;
      sourceId: string;
      relationType: RelationType;
      targetType: string;
      targetId: string;
    };
    try {
      await callSessionStore(['remove_relationship', sourceType, sourceId, relationType, targetType, targetId]);
      emit('command', ['relationships']);
      return {
        ok: true,
        command_id: command.id,
        changed: { relationships: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'UNLINK_FAILED', message },
      };
    }
  });

  // ── relationship.list ─────────────────────────────────────────────────

  bus.register('relationship.list', async (command: Command): Promise<CommandResult<{ relationships: EntityRelationship[] }>> => {
    const { entityType, entityId } = command.payload as {
      entityType: string;
      entityId: string;
    };
    try {
      const rows = await callSessionStore(['get_relationships', entityType, entityId]) as EntityRelationship[];
      return {
        ok: true,
        command_id: command.id,
        data: { relationships: rows },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'LIST_RELATIONSHIPS_FAILED', message },
      };
    }
  });

  // ── prompt.send ───────────────────────────────────────────────────────

  bus.register('prompt.send', async (command: Command): Promise<CommandResult> => {
    const { sessionId, text, submit } = command.payload as { sessionId: string; text: string; submit?: boolean };
    try {
      // Deliver via the substrate's TYPED path (send-keys -l) rather than a raw-byte
      // burst into the client PTY. The burst was read by Claude Code as a paste — it
      // folded into a "[Pasted text #N]" chip and stripped file paths on submit. Typed
      // delivery injects the text as keystrokes (no chip, paths byte-exact) and, when
      // submitting, presses a real named Enter — so one Enter submits cleanly with no
      // double-Enter / paste-swallow workaround.
      // submit === false stages the text into the CLI prompt area without Enter.
      await deliverPromptTyped(sessionId, text, submit !== false);
      return {
        ok: true,
        command_id: command.id,
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'PROMPT_SEND_FAILED', message },
      };
    }
  });

  // ── prompt.queue ────────────────────────────────────────────────────────
  // STACK a prompt into the target session's incoming prompt queue
  // (ai_comms/prompts_inbox/<tid>/) instead of typing it into the live prompt
  // area. Used when the session is busy (actively responding): the queued prompt
  // is delivered by the comms daemon when the session next goes idle, so it can't
  // collide with the in-flight response. Enqueue goes through the canonical path
  // (messaging.py send-prompt); attribute the sender to the app (AI_TRACKING_ID).
  bus.register('prompt.queue', async (command: Command): Promise<CommandResult<{ queueId?: string }>> => {
    const { sessionId, text } = command.payload as { sessionId: string; text: string };
    try {
      const os = require('node:os');
      const { execFile: ef } = require('node:child_process');
      const { promisify } = require('node:util');
      const execFileAsync = promisify(ef);
      const aiRoot = getAiRootMain();
      const messagingPy = path.join(aiRoot, 'ai_general/scripts/messages/messaging.py');
      const envPath = shellPath();
      const env = { ...process.env, AI_ROOT: aiRoot, PATH: envPath } as Record<string, string>;
      // queue-prompt writes the entry directly (takes --source, no session-sender
      // requirement). Attribute to the user so prompt-blocks — which always allow the
      // user — let it through. `post-prompt` delivers after the session's current turn.
      const { stdout } = await execFileAsync('python3', [
        messagingPy, 'queue-prompt',
        '--to', sessionId,
        '--content', text,
        '--source', 'uai://user/piano_man',
        '--delivery', 'post-prompt',
        '--urgency', 'prompt',
        '--format', 'json',
      ], { timeout: 30_000, env });
      const out = String(stdout || '').trim();
      try {
        const parsed = JSON.parse(out);
        if (parsed && parsed.success === false) {
          return { ok: false, command_id: command.id, error: { code: 'PROMPT_QUEUE_FAILED', message: parsed.error || 'queue-prompt failed' } };
        }
        return { ok: true, command_id: command.id, data: { queueId: parsed?.queue_id } };
      } catch {
        return { ok: true, command_id: command.id };
      }
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'PROMPT_QUEUE_FAILED', message } };
    }
  });

  // ── prompt.library.* — the saved-prompts repository (thin wrapper) ───────
  // Logic + storage live in scripts/prompts/prompt_library.py (YAML store is the
  // single source of truth). The app NEVER keeps its own copy; every call shells
  // the script and returns the full current list so the renderer refreshes in one
  // round-trip. Same store an MCP tool / CLI session uses — no divergent state.
  const runPromptLibrary = async (args: string[]): Promise<{ ok?: boolean; prompts?: SavedPrompt[]; error?: string }> => {
    const os = require('node:os');
    const { execFile: ef } = require('node:child_process');
    const { promisify } = require('node:util');
    const execFileAsync = promisify(ef);
    const aiRoot = getAiRootMain();
    const script = path.join(aiRoot, 'ai_general/scripts/prompts/prompt_library.py');
    const envPath = shellPath();
    const env = { ...process.env, AI_ROOT: aiRoot, PATH: envPath } as Record<string, string>;
    try {
      const { stdout } = await execFileAsync('python3', [script, ...args, '--json'],
        { timeout: 30_000, env, maxBuffer: 8 * 1024 * 1024 });
      return JSON.parse(String(stdout || '').trim() || '{}');
    } catch (err: unknown) {
      // The script exits nonzero on logical failure but still prints its JSON to
      // stdout — recover it so the renderer sees a real error, not a spawn crash.
      const e = err as { stdout?: string; message?: string };
      if (e.stdout) { try { return JSON.parse(String(e.stdout).trim()); } catch { /* fall through */ } }
      return { ok: false, error: e.message || 'prompt_library failed' };
    }
  };
  const plResult = (command: Command, r: { ok?: boolean; prompts?: SavedPrompt[]; error?: string }): CommandResult<{ prompts: SavedPrompt[] }> =>
    (r.ok === false
      ? { ok: false, command_id: command.id, error: { code: 'PROMPT_LIBRARY_FAILED', message: r.error || 'prompt_library failed' } }
      : { ok: true, command_id: command.id, data: { prompts: r.prompts || [] } });

  bus.register('prompt.library.list', async (command: Command): Promise<CommandResult<{ prompts: SavedPrompt[] }>> => {
    const { search, tag } = (command.payload || {}) as { search?: string; tag?: string };
    const args = ['--mode', 'list'];
    if (tag) args.push('--tag', tag);
    if (search) args.push('--search', search);
    return plResult(command, await runPromptLibrary(args));
  });
  bus.register('prompt.library.save', async (command: Command): Promise<CommandResult<{ prompts: SavedPrompt[] }>> => {
    const { title, body, tag } = command.payload as { title: string; body: string; tag?: string };
    const args = ['--mode', 'save', '--title', title, '--body', body];
    if (tag) args.push('--tag', tag);
    return plResult(command, await runPromptLibrary(args));
  });
  bus.register('prompt.library.update', async (command: Command): Promise<CommandResult<{ prompts: SavedPrompt[] }>> => {
    const { id, title, body, tag, clearTag } = command.payload as { id: string; title?: string; body?: string; tag?: string; clearTag?: boolean };
    const args = ['--mode', 'update', id];
    if (title !== undefined) args.push('--title', title);
    if (body !== undefined) args.push('--body', body);
    if (clearTag) args.push('--clear-tag'); else if (tag !== undefined) args.push('--tag', tag);
    return plResult(command, await runPromptLibrary(args));
  });
  bus.register('prompt.library.delete', async (command: Command): Promise<CommandResult<{ prompts: SavedPrompt[] }>> => {
    const { id } = command.payload as { id: string };
    return plResult(command, await runPromptLibrary(['--mode', 'delete', id]));
  });

  // ── ai.rewrite — improve the Prompt Box text with an AI (thin wrapper) ───
  // Reuses callAiEngine (lllm_prompt.py / claude -p). The user's improvement
  // instruction becomes the system prompt; the prompt text is the input to rewrite.
  bus.register('ai.rewrite', async (command: Command): Promise<CommandResult<{ text: string }>> => {
    const { instruction, text, engine } = command.payload as { instruction?: string; text: string; engine?: 'lllm' | 'claude' };
    try {
      if (!text || !text.trim()) {
        return { ok: false, command_id: command.id, error: { code: 'AI_REWRITE_EMPTY_INPUT', message: 'Nothing to rewrite.' } };
      }
      const aiRoot = getAiRootMain();
      const eng = engine === 'claude' ? 'claude' : 'lllm';
      const system =
        'You are an expert prompt editor. Rewrite the prompt below so it is clearer, more specific, '
        + 'and more effective, while preserving its original intent. Output ONLY the rewritten prompt — '
        + 'no preamble, no explanation, no surrounding code fences.\n\nImprovement instructions: '
        + (instruction && instruction.trim() ? instruction.trim() : 'Improve clarity, specificity, and structure.');
      const out = await callAiEngine(eng, system, text, aiRoot);
      if (!out || !out.trim()) {
        return { ok: false, command_id: command.id, error: { code: 'AI_REWRITE_EMPTY', message: `The ${eng} engine returned nothing — is the local LLM running? Try the Claude engine.` } };
      }
      return { ok: true, command_id: command.id, data: { text: out.trim() } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'AI_REWRITE_FAILED', message } };
    }
  });

  // ── memorex.saveAnomaly ─────────────────────────────────────────────────
  // Auto-persist a Memorex diagnostic anomaly (cover blanketing prompt/status,
  // headless response, etc.) to disk so it needs NO DevTools / human action —
  // the renderer's always-on recorder calls this when it detects one. Dumps land
  // in a gitignored diagnostics dir; read them anytime to diagnose todo_0385/0392.
  bus.register('memorex.saveAnomaly', async (command: Command): Promise<CommandResult<{ file: string }>> => {
    const { sessionId, reason, payload } = command.payload as {
      sessionId?: string; reason?: string; payload?: unknown;
    };
    try {
      const aiRoot = getAiRootMain();
      const dir = path.join(aiRoot, 'ai_general', 'data', 'memorex', 'anomalies');
      fs.mkdirSync(dir, { recursive: true });
      const safeSid = (sessionId || 'unknown').replace(/[^A-Za-z0-9_]/g, '');
      const stamp = new Date().toISOString().replace(/[:.]/g, '-');
      const file = path.join(dir, `anomaly_${safeSid}_${stamp}.json`);
      fs.writeFileSync(file, JSON.stringify({
        sessionId, reason, savedAt: new Date().toISOString(), payload,
      }, null, 2));
      return { ok: true, command_id: command.id, data: { file } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'MEMOREX_ANOMALY_SAVE_FAILED', message } };
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  // WORKSPACE TAB COMMANDS — M4 fix: route tab ops through command bus
  // ═══════════════════════════════════════════════════════════════════════

  bus.register('workspace.tabs.open', async (command: Command): Promise<CommandResult<{ tabId: string }>> => {
    const { targetId, label, type, sessionTrackingId, groupId } = command.payload as {
      targetId?: string;
      label: string;
      type?: string;
      sessionTrackingId?: string;  // backward compat
      groupId?: string;  // TeamId or ProjectId for tab grouping
    };
    const tabType = type || 'session';
    const resolvedTargetId = targetId || sessionTrackingId || '';
    try {
      const aiRoot = getAiRootMain();
      const statePath = getAppStatePath();
      const current = loadNormalizedAppState(statePath);

      const tabs = (current.tabs as any[] || []);
      const existing = tabs.find((t: any) => t.targetId === resolvedTargetId && t.type === tabType);
      if (existing) {
        // Update groupId if provided (session may be added to a team/project)
        if (groupId && existing.groupId !== groupId) {
          existing.groupId = groupId;
        }
        current.activeTabId = existing.id;
        fs.writeFileSync(statePath, JSON.stringify(current, null, 2));
        emit('command', ['appState']);
        return { ok: true, command_id: command.id, data: { tabId: existing.id }, changed: { appState: true } };
      }

      const tab: Record<string, unknown> = {
        id: `tab_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`,
        type: tabType,
        targetId: resolvedTargetId,
        label,
        openedAt: new Date().toISOString(),
      };
      if (groupId) tab.groupId = groupId;
      current.tabs = [...tabs, tab];
      current.activeTabId = tab.id as string;
      fs.writeFileSync(statePath, JSON.stringify(current, null, 2));
      emit('command', ['appState']);
      return { ok: true, command_id: command.id, data: { tabId: tab.id as string }, changed: { appState: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'TAB_OPEN_FAILED', message } };
    }
  });

  bus.register('workspace.tabs.close', async (command: Command): Promise<CommandResult> => {
    const { tabId } = command.payload as { tabId: string };
    try {
      const aiRoot = getAiRootMain();
      const statePath = getAppStatePath();
      const current = loadNormalizedAppState(statePath);

      const allTabs = (current.tabs as any[] || []);
      const closingTab = allTabs.find((t: any) => t.id === tabId);
      if (!closingTab) {
        return {
          ok: false,
          command_id: command.id,
          error: {
            code: 'TAB_NOT_FOUND',
            message: `No tab with id "${tabId}" found. Note: workspace.tabs.close expects a tab id, not a targetId.`,
          },
        };
      }
      // A real tab close is the only time we tear down a standalone terminal's
      // PTY. (Tab switches unmount the renderer component but keep the shell
      // alive so it can be re-attached — see createStandaloneTerminal.)
      if (closingTab.type === 'terminal') {
        closeStandaloneTerminal(closingTab.id);
      }

      const tabs = allTabs.filter((t: any) => t.id !== tabId);
      let activeTabId = current.activeTabId;
      if (activeTabId === tabId) {
        // Return to sibling session tab with same targetId (e.g., transcript → session)
        const sibling = tabs.find((t: any) => t.targetId === closingTab.targetId && t.type === 'session');
        activeTabId = sibling ? sibling.id : (tabs.length > 0 ? tabs[tabs.length - 1].id : null);
      }
      current.tabs = tabs;
      current.activeTabId = activeTabId;
      fs.writeFileSync(statePath, JSON.stringify(current, null, 2));
      emit('command', ['appState']);
      return { ok: true, command_id: command.id, changed: { appState: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'TAB_CLOSE_FAILED', message } };
    }
  });

  // ── workspace.tabs.update — update an existing tab's properties (reuse tab for preview)
  bus.register('workspace.tabs.update', async (command: Command): Promise<CommandResult> => {
    const { tabId, patch } = command.payload as { tabId: string; patch: Record<string, unknown> };
    try {
      const aiRoot = getAiRootMain();
      const statePath = getAppStatePath();
      const current = loadNormalizedAppState(statePath);
      const tabs = (current.tabs || []) as any[];
      const tab = tabs.find((t: any) => t.id === tabId);
      if (!tab) {
        return { ok: false, command_id: command.id, error: { code: 'TAB_NOT_FOUND', message: `No tab with id "${tabId}"` } };
      }
      Object.assign(tab, patch);
      current.tabs = tabs;
      fs.writeFileSync(statePath, JSON.stringify(current, null, 2));
      emit('command', ['appState']);
      return { ok: true, command_id: command.id, changed: { appState: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'TAB_UPDATE_FAILED', message } };
    }
  });

  bus.register('workspace.tabs.activate', async (command: Command): Promise<CommandResult> => {
    const { tabId } = command.payload as { tabId: string };
    try {
      const aiRoot = getAiRootMain();
      const statePath = getAppStatePath();
      const current = loadNormalizedAppState(statePath);

      current.activeTabId = tabId;
      fs.writeFileSync(statePath, JSON.stringify(current, null, 2));
      emit('command', ['appState']);
      return { ok: true, command_id: command.id, changed: { appState: true } };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: 'TAB_ACTIVATE_FAILED', message } };
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  // BRIEF COMMANDS
  // ═══════════════════════════════════════════════════════════════════════

  bus.register('brief.create', async (command: Command): Promise<CommandResult<{ briefPath: string; briefName: string; dispatched?: boolean; host?: string }>> => {
    const { sessionIds, opts } = command.payload as {
      sessionIds: string | string[];
      opts: {
        name: string;
        description?: string;
        folder: string;
        launch?: boolean;
        launchName?: string;
        launchPlatform?: string;
        condenserSession?: string;
        hostSession?: string;
        targetName?: string;
      };
    };
    try {
      // NEW model (todo_0506): when a host session is chosen, the app authors NO
      // briefing logic — it delivers a short prompt to the host, which runs
      // Tideline's `auto_brief.py emit-subagent-task` helper and spawns a Task
      // subagent to prepare, author, write + register the brief (fire-and-forget).
      // The registration branch (host==target → register_self_brief; host!=target →
      // register_brief) lives entirely in the helper's emitted recipe.
      if (opts.hostSession) {
        const target = Array.isArray(sessionIds) ? sessionIds[0] : sessionIds;
        const host = opts.hostSession;
        const targetLabel = opts.targetName || target;
        const prompt = [
          `Please create a session brief for **${targetLabel}** (target \`${target}\`), requested from the UAI "Create Brief" dialog.`,
          '',
          '1. Run this to get the exact subagent instructions (recipe lives in Python — do not hand-author it):',
          `   python3 ~/AI/ai_root/ai_general/scripts/jsonl/auto_brief.py emit-subagent-task --target ${target} --condenser ${host}`,
          '2. Spawn a Task subagent whose prompt is that command\'s stdout, verbatim.',
          '',
          'The subagent prepares the source transcript, authors a fresh-snapshot brief, writes + registers it under auto_briefs/, and posts a feed line when done. Fire-and-forget — you do not need to report back here.',
        ].join('\n');
        await deliverPromptTyped(host, prompt, true);
        return {
          ok: true,
          command_id: command.id,
          data: { briefPath: '', briefName: opts.name, dispatched: true, host },
        };
      }

      // Legacy path (no host chosen): local condense.py flow. Kept alive until the
      // full cutover sweep (Tideline's todo_0507).
      const result = await createBrief(sessionIds, opts);
      if (!result.ok) {
        return {
          ok: false,
          command_id: command.id,
          error: { code: 'BRIEF_CREATE_FAILED', message: result.error || 'Unknown error' },
        };
      }
      emit('command', ['briefs']);
      return {
        ok: true,
        command_id: command.id,
        data: { briefPath: result.briefPath!, briefName: result.briefName! },
        changed: { briefs: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'BRIEF_CREATE_FAILED', message },
      };
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  // TRAITS COMMANDS
  // ═══════════════════════════════════════════════════════════════════════

  bus.register('traits.load', async (command: Command): Promise<CommandResult<{ results: Array<{ type: string; name: string; success: boolean; error?: string }> }>> => {
    const { sessionId, items } = command.payload as {
      sessionId: string;
      items: Array<{ type: string; name: string }>;
    };
    try {
      const results: Array<{ type: string; name: string; success: boolean; error?: string }> = [];
      for (const item of items) {
        try {
          await runSessionTraits(['--session', sessionId, 'load', item.type, item.name]);
          // Also add to pending_context_load so the hook delivers content on next prompt
          await runSessionTraits(['--session', sessionId, 'pend', item.type, item.name]);
          results.push({ type: item.type, name: item.name, success: true });
        } catch (e) {
          results.push({ type: item.type, name: item.name, success: false, error: (e as Error).message });
        }
      }
      emit('command', ['sessions']);
      return {
        ok: true,
        command_id: command.id,
        data: { results },
        changed: { sessions: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'TRAITS_LOAD_FAILED', message },
      };
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  // TODO (WORK) COMMANDS — mutations route through the bus so they are logged,
  // hookable, and invocable from the viewport `actions` API. Reads stay on the
  // direct uai:todos:* IPC (queries don't need the bus). Engine bridge: todo-ops.
  // ═══════════════════════════════════════════════════════════════════════

  const todoCmd = (
    code: string,
    run: (p: Record<string, unknown>) => Promise<string>,
  ) => bus.register(`todo.${code}`, async (command: Command): Promise<CommandResult<{ out: string }>> => {
    try {
      const out = (await run(command.payload as Record<string, unknown>)).trim();
      emit('command', ['todos']);
      return { ok: true, command_id: command.id, data: { out }, changed: { todos: true } as Record<string, boolean> };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: `TODO_${code.toUpperCase()}_FAILED`, message } };
    }
  });

  todoCmd('setStatus', (p) => runTodoMgr('status', [String(p.status), String(p.id), ...(p.note ? ['--note', String(p.note)] : [])]));
  todoCmd('priority', (p) => runTodoMgr('priority', [String(p.level), String(p.id)]));   // todo_0652
  todoCmd('move', (p) => runTodoMgr('move', [String(p.target || 'root'), String(p.id)]));
  todoCmd('assign', (p) => runTodoMgr('assign', [String(p.id), String(p.uri)]));
  todoCmd('unassign', (p) => runTodoMgr('unassign', [String(p.id), String(p.uri)]));
  todoCmd('tag', (p) => runTodoMgr('tag', [String(p.action), String(p.id), String(p.tag)]));
  todoCmd('create', (p) => runTodoMgr('create', [String(p.name), ...((p.extra as string[]) || [])]));
  // Move a todo to trash (recoverable). Bulk Delete in the Work Mgr calls this per id.
  todoCmd('trash', (p) => runTodoMgr('delete', [String(p.id)]));
  // Routes through todo_mgr set-notes (the data authority) — never writes notes.md directly.
  todoCmd('writeNotes', (p) => runTodoMgr('set-notes', [String(p.id), '--content', String(p.content)]));
  // Append a comment to a todo's history.log (status 'comment'; never changes real status).
  // Optional replyTo nests it under an existing comment (threaded comments).
  todoCmd('comment', (p) => runTodoMgr('comment', [
    String(p.id), '--text', String(p.text), '--session', String(p.author || 'PianoMan'),
    ...(p.replyTo ? ['--reply-to', String(p.replyTo)] : []),
  ]));

  // ── team.* create/update/archive: registry-backed (todo_0633). These REPLACE the
  // former teamCmd(runTeamsMgr) bridge, which wrote data/teams/<id>.yml — a store the
  // UI never reads, so Team-Editor creates/updates silently never appeared (the
  // split-brain). They're registered further down (after resolveSrc), alongside the
  // members/roles registry ops. team.addRole/removeRole/setRoleAssignment already go
  // through the registry via setRole/roleLifecycle below; the old teamCmd duplicates
  // (which Map.set-overwrote to the registry anyway) and the dead assign/unassign
  // teams_mgr paths are removed here as the reconciliation Hamilton asked for.

  // ── project.setHidden / team.setHidden — "Delete" == HIDE (todo_0532).
  // A pure visibility flag: flips `ui_hidden` in the entity's own source yml. It
  // NEVER moves, renames, or deletes any directory (esp. a project's working_dir)
  // — fully reversible by setting hidden:false. The renderer passes the card's
  // `sourcePath` (the exact yml it was read from); we fall back to resolving by id
  // in the registry if omitted.
  const registryDir = path.join(getAiRootMain(), 'ai_general', 'data', 'projects');
  const isTeamRegistrySource = (sourcePath: string): boolean => {
    const src = path.resolve(sourcePath);
    return path.dirname(src) === path.resolve(registryDir) && src.endsWith('.team.yml');
  };
  const resolveEntityYml = (id: string, prefer: 'project' | 'team'): string | null => {
    const candidates = prefer === 'team'
      ? [path.join(registryDir, `${id}.team.yml`)]
      : [path.join(registryDir, `${id}.proj.yml`), path.join(registryDir, `${id}.team.yml`)];
    return candidates.find(c => fs.existsSync(c)) || null;
  };
  const setHidden = (
    cmdName: string,
    prefer: 'project' | 'team',
    storeKey: string,
  ) => bus.register(cmdName, async (command: Command): Promise<CommandResult<{ hidden: boolean; sourcePath: string }>> => {
    const p = command.payload as { id?: string; hidden?: boolean; sourcePath?: string };
    const hidden = p.hidden !== false; // default to hiding
    try {
      const id = String(p.id ?? '').replace(/^(project|team):/, '');
      let src = p.sourcePath && fs.existsSync(p.sourcePath)
        && (prefer !== 'team' || isTeamRegistrySource(p.sourcePath))
        ? p.sourcePath
        : null;
      if (!src) src = resolveEntityYml(id, prefer);
      if (!src) {
        return { ok: false, command_id: command.id, error: { code: `${storeKey.toUpperCase()}_SET_HIDDEN_FAILED`, message: `No source file for id "${id}"` } };
      }
      setEntityHidden(src, hidden);
      emit('command', [storeKey]);
      return { ok: true, command_id: command.id, data: { hidden, sourcePath: src }, changed: { [storeKey]: true } as Record<string, boolean> };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return { ok: false, command_id: command.id, error: { code: `${storeKey.toUpperCase()}_SET_HIDDEN_FAILED`, message } };
    }
  });
  setHidden('project.setHidden', 'project', 'projects');
  setHidden('team.setHidden', 'team', 'teams');

  // ── Members & Roles editing (todo_0544) ─────────────────────────────────
  // All of these edit the entity's own registry yml in place (same reversible,
  // never-touch-a-directory approach as setHidden) and emit a store refresh.
  const resolveSrc = (p: { id?: string; sourcePath?: string }, prefer: 'project' | 'team'): string | null => {
    const id = String(p.id ?? '').replace(/^(project|team):/, '');
    if (p.sourcePath && fs.existsSync(p.sourcePath)
        && (prefer !== 'team' || isTeamRegistrySource(p.sourcePath))) return p.sourcePath;
    return resolveEntityYml(id, prefer);
  };

  // role holder: member=a name assigns; member=''/null UNASSIGNS but keeps the
  // slot (an empty `role:`). Deleting a role entirely is removeRoleAssignment.
  const setRole = (cmdName: string, prefer: 'project' | 'team', storeKey: string) =>
    bus.register(cmdName, async (command: Command): Promise<CommandResult<{ role: string; member: string; sourcePath: string }>> => {
      const p = command.payload as { id?: string; role?: string; member?: string | null; sourcePath?: string };
      const role = String(p.role ?? '').trim();
      const member = p.member ? String(p.member) : '';   // '' = keep empty slot
      const CODE = `${storeKey.toUpperCase()}_SET_ROLE_FAILED`;
      try {
        if (!role) return { ok: false, command_id: command.id, error: { code: CODE, message: 'role name is required' } };
        const src = resolveSrc(p, prefer);
        if (!src) return { ok: false, command_id: command.id, error: { code: CODE, message: `No source file for id "${p.id}"` } };
        setRoleAssignment(src, role, member);
        emit('command', [storeKey]);
        return { ok: true, command_id: command.id, data: { role, member, sourcePath: src }, changed: { [storeKey]: true } as Record<string, boolean> };
      } catch (err: unknown) {
        return { ok: false, command_id: command.id, error: { code: CODE, message: err instanceof Error ? err.message : String(err) } };
      }
    });
  setRole('project.setRoleAssignment', 'project', 'projects');
  setRole('team.setRoleAssignment', 'team', 'teams');

  // addRole: create an empty, unassigned slot. removeRole: delete the role.
  const roleLifecycle = (cmdName: string, prefer: 'project' | 'team', storeKey: string, mode: 'add' | 'remove') =>
    bus.register(cmdName, async (command: Command): Promise<CommandResult<{ role: string; sourcePath: string }>> => {
      const p = command.payload as { id?: string; role?: string; sourcePath?: string };
      const role = String(p.role ?? '').trim();
      const CODE = `${storeKey.toUpperCase()}_${mode.toUpperCase()}_ROLE_FAILED`;
      try {
        if (!role) return { ok: false, command_id: command.id, error: { code: CODE, message: 'role name is required' } };
        const src = resolveSrc(p, prefer);
        if (!src) return { ok: false, command_id: command.id, error: { code: CODE, message: `No source file for id "${p.id}"` } };
        setRoleAssignment(src, role, mode === 'add' ? '' : null);
        emit('command', [storeKey]);
        return { ok: true, command_id: command.id, data: { role, sourcePath: src }, changed: { [storeKey]: true } as Record<string, boolean> };
      } catch (err: unknown) {
        return { ok: false, command_id: command.id, error: { code: CODE, message: err instanceof Error ? err.message : String(err) } };
      }
    });
  roleLifecycle('project.addRole', 'project', 'projects', 'add');
  roleLifecycle('team.addRole', 'team', 'teams', 'add');
  roleLifecycle('project.removeRole', 'project', 'projects', 'remove');
  roleLifecycle('team.removeRole', 'team', 'teams', 'remove');

  // team.create — a NEW team in the registry (data/projects/<slug>.team.yml), the
  // store the UI reads. Replaces the legacy teams_mgr create that wrote data/teams/
  // (todo_0633). members/roles start empty; a team gets a home only when promoted.
  bus.register('team.create', async (command: Command): Promise<CommandResult<{ id: string; sourcePath: string }>> => {
    const p = command.payload as { name?: string; team?: string; description?: string; tags?: string[] | string };
    const name = String(p.name ?? p.team ?? '').trim();
    try {
      if (!name) return { ok: false, command_id: command.id, error: { code: 'TEAM_CREATE_FAILED', message: 'team name is required' } };
      const tags = Array.isArray(p.tags) ? p.tags : (p.tags ? String(p.tags).split(',') : []);
      const { id, sourcePath } = createTeam(name, p.description ? String(p.description) : undefined, tags);
      emit('command', ['teams']);
      return { ok: true, command_id: command.id, data: { id, sourcePath }, changed: { teams: true } as Record<string, boolean> };
    } catch (err: unknown) {
      return { ok: false, command_id: command.id, error: { code: 'TEAM_CREATE_FAILED', message: err instanceof Error ? err.message : String(err) } };
    }
  });

  // team.update — scalar metadata (name/description/tags/status) in the registry yml.
  bus.register('team.update', async (command: Command): Promise<CommandResult<{ sourcePath: string }>> => {
    const p = command.payload as { id?: string; sourcePath?: string; name?: string; description?: string; tags?: string[] | string; status?: string };
    try {
      const src = resolveSrc(p, 'team');
      if (!src) return { ok: false, command_id: command.id, error: { code: 'TEAM_UPDATE_FAILED', message: `No source file for id "${p.id}"` } };
      const tags = p.tags == null ? undefined : (Array.isArray(p.tags) ? p.tags : String(p.tags).split(','));
      updateEntity(src, { name: p.name, description: p.description, tags, status: p.status });
      emit('command', ['teams']);
      return { ok: true, command_id: command.id, data: { sourcePath: src }, changed: { teams: true } as Record<string, boolean> };
    } catch (err: unknown) {
      return { ok: false, command_id: command.id, error: { code: 'TEAM_UPDATE_FAILED', message: err instanceof Error ? err.message : String(err) } };
    }
  });

  // team.archive == hide (the entity's own ui_hidden flag) — never moves/deletes a
  // directory; mirrors team.setHidden. Kept for callers using the archive verb.
  bus.register('team.archive', async (command: Command): Promise<CommandResult<{ sourcePath: string }>> => {
    const p = command.payload as { id?: string; sourcePath?: string };
    try {
      const src = resolveSrc(p, 'team');
      if (!src) return { ok: false, command_id: command.id, error: { code: 'TEAM_ARCHIVE_FAILED', message: `No source file for id "${p.id}"` } };
      setEntityHidden(src, true);
      emit('command', ['teams']);
      return { ok: true, command_id: command.id, data: { sourcePath: src }, changed: { teams: true } as Record<string, boolean> };
    } catch (err: unknown) {
      return { ok: false, command_id: command.id, error: { code: 'TEAM_ARCHIVE_FAILED', message: err instanceof Error ? err.message : String(err) } };
    }
  });

  // setRoleContext: attach/clear a role's context reference (role_contexts: block).
  // context = a string sets it; ''/null clears it.
  const setRoleCtx = (cmdName: string, prefer: 'project' | 'team', storeKey: string) =>
    bus.register(cmdName, async (command: Command): Promise<CommandResult<{ role: string; context: string | null; sourcePath: string }>> => {
      const p = command.payload as { id?: string; role?: string; context?: string | null; sourcePath?: string };
      const role = String(p.role ?? '').trim();
      const context = p.context ? String(p.context) : null;
      const CODE = `${storeKey.toUpperCase()}_SET_ROLE_CONTEXT_FAILED`;
      try {
        if (!role) return { ok: false, command_id: command.id, error: { code: CODE, message: 'role name is required' } };
        const src = resolveSrc(p, prefer);
        if (!src) return { ok: false, command_id: command.id, error: { code: CODE, message: `No source file for id "${p.id}"` } };
        setRoleContext(src, role, context);
        emit('command', [storeKey]);
        return { ok: true, command_id: command.id, data: { role, context, sourcePath: src }, changed: { [storeKey]: true } as Record<string, boolean> };
      } catch (err: unknown) {
        return { ok: false, command_id: command.id, error: { code: CODE, message: err instanceof Error ? err.message : String(err) } };
      }
    });
  setRoleCtx('project.setRoleContext', 'project', 'projects');
  setRoleCtx('team.setRoleContext', 'team', 'teams');

  // setMembers: replace the whole `members:` list (add/remove are computed caller-side).
  const setMembersCmd = (cmdName: string, prefer: 'project' | 'team', storeKey: string) =>
    bus.register(cmdName, async (command: Command): Promise<CommandResult<{ members: string[]; sourcePath: string }>> => {
      const p = command.payload as { id?: string; members?: string[]; sourcePath?: string };
      const members = Array.isArray(p.members) ? p.members.map(String) : [];
      const CODE = `${storeKey.toUpperCase()}_SET_MEMBERS_FAILED`;
      try {
        const src = resolveSrc(p, prefer);
        if (!src) return { ok: false, command_id: command.id, error: { code: CODE, message: `No source file for id "${p.id}"` } };
        setMembers(src, members);
        emit('command', [storeKey]);
        return { ok: true, command_id: command.id, data: { members, sourcePath: src }, changed: { [storeKey]: true } as Record<string, boolean> };
      } catch (err: unknown) {
        return { ok: false, command_id: command.id, error: { code: CODE, message: err instanceof Error ? err.message : String(err) } };
      }
    });
  setMembersCmd('project.setMembers', 'project', 'projects');
  setMembersCmd('team.setMembers', 'team', 'teams');

  // project.setPlaybook: set which top-level folders make up the project's Playbook.
  bus.register('project.setPlaybook', async (command: Command): Promise<CommandResult<{ folders: string[]; sourcePath: string }>> => {
    const p = command.payload as { id?: string; folders?: string[]; sourcePath?: string };
    const folders = Array.isArray(p.folders) ? p.folders.map(String) : [];
    const CODE = 'PROJECT_SET_PLAYBOOK_FAILED';
    try {
      const src = resolveSrc(p, 'project');
      if (!src) return { ok: false, command_id: command.id, error: { code: CODE, message: `No source file for id "${p.id}"` } };
      setPlaybook(src, folders);
      emit('command', ['projects']);
      return { ok: true, command_id: command.id, data: { folders, sourcePath: src }, changed: { projects: true } };
    } catch (err: unknown) {
      return { ok: false, command_id: command.id, error: { code: CODE, message: err instanceof Error ? err.message : String(err) } };
    }
  });

  // team.promoteToProject: give a Team a home directory and convert its registry
  // file .team.yml → .proj.yml (todo_0320). Members/roles/contexts carry over.
  bus.register('team.promoteToProject', async (command: Command): Promise<CommandResult<{ workingDir: string; newSourcePath: string }>> => {
    const p = command.payload as { id?: string; dirName?: string; sourcePath?: string };
    const CODE = 'TEAM_PROMOTE_FAILED';
    try {
      const src = resolveSrc(p, 'team');
      if (!src) return { ok: false, command_id: command.id, error: { code: CODE, message: `No source file for id "${p.id}"` } };
      if (!src.endsWith('.team.yml')) return { ok: false, command_id: command.id, error: { code: CODE, message: 'Only a team can be promoted to a project' } };
      const res = promoteTeamToProject(src, p.dirName && String(p.dirName).trim() ? String(p.dirName).trim() : undefined);
      emit('command', ['teams', 'projects']);
      return { ok: true, command_id: command.id, data: res, changed: { teams: true, projects: true } };
    } catch (err: unknown) {
      return { ok: false, command_id: command.id, error: { code: CODE, message: err instanceof Error ? err.message : String(err) } };
    }
  });

  // ═══════════════════════════════════════════════════════════════════════
  // COMMS COMMANDS
  // ═══════════════════════════════════════════════════════════════════════

  bus.register('comms.send', async (command: Command): Promise<CommandResult<{ messageId?: string }>> => {
    const { from, to, content, urgency, responseType, ttlSeconds, replyTo, subject } = command.payload as {
      from: string;
      to: string;
      content: string;
      urgency?: string;
      responseType?: string;
      ttlSeconds?: number;
      replyTo?: string;
      subject?: string;
    };
    try {
      const result = await sendMessage({ from, to, content, urgency, responseType, ttlSeconds, replyTo, subject });
      if (!result.ok) {
        return {
          ok: false,
          command_id: command.id,
          error: { code: 'COMMS_SEND_FAILED', message: result.error || 'Unknown error' },
        };
      }
      emit('command', ['comms']);
      return {
        ok: true,
        command_id: command.id,
        data: { messageId: result.messageId },
        changed: { comms: true },
      };
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      return {
        ok: false,
        command_id: command.id,
        error: { code: 'COMMS_SEND_FAILED', message },
      };
    }
  });

  // ── Global hooks ──────────────────────────────────────────────────────

  // Log every command
  bus.before('*', async (command: Command): Promise<void> => {
    console.log(`[CommandBus] ${command.type} from=${command.origin} id=${command.id}`);
  });

  // Access control: block external-api/embedded-ai from destructive commands
  bus.before('*', async (command: Command): Promise<void | CommandResult> => {
    if (command.origin === 'external-api' || command.origin === 'embedded-ai') {
      // For now, only block explicitly dangerous patterns
      // This will be expanded with the full capability system
      const blocked = ['session.create', 'session.archive'];
      if (blocked.includes(command.type) && command.origin === 'external-api') {
        return {
          ok: false,
          command_id: command.id,
          error: {
            code: 'FORBIDDEN',
            message: `Command ${command.type} not allowed from origin ${command.origin}`,
          },
        };
      }
    }
  });
}
