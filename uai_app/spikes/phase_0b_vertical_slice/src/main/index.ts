/**
 * UAI Main Process — Phase 0B Spike
 *
 * Architecture:
 *   Path 1 (outbound): Renderer dispatches commands via IPC → main handles → mutates stores
 *   Path 2 (inbound):  Main emits store/runtime change events → renderer updates snapshots
 *
 * The main process is the only app-side writer to external stores.
 * The renderer holds snapshots and dispatches commands.
 */

import { app, BrowserWindow, ipcMain, Menu, clipboard } from 'electron';
import * as path from 'node:path';
import * as fs from 'node:fs';
import { listSessions, getSession, updateSession, createDraftSession, launchSession } from './session-store';
import { attachTerminal, writeTerminal, resizeTerminal, detachTerminal, detachAll } from './terminal';
import { IPC } from '../shared/types';
import type { StoreChangedEvent, CommandResult } from '../shared/types';

// Squirrel startup handler
if (require('electron-squirrel-startup')) app.quit();

let mainWindow: BrowserWindow | null = null;
let changeSequence = 0;

function createWindow(): void {
  mainWindow = new BrowserWindow({
    width: 1400,
    height: 900,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
    titleBarStyle: 'hiddenInset',
    backgroundColor: '#0a0c10',
  });

  // Vite dev server or production build
  if (MAIN_WINDOW_VITE_DEV_SERVER_URL) {
    mainWindow.loadURL(MAIN_WINDOW_VITE_DEV_SERVER_URL);
  } else {
    mainWindow.loadFile(path.join(__dirname, `../renderer/${MAIN_WINDOW_VITE_NAME}/index.html`));
  }

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ─── IPC Handlers (Path 1: commands from renderer) ─────────────────────────

// Bootstrap: renderer requests initial snapshot on startup
ipcMain.handle(IPC.BOOTSTRAP, async () => {
  const sessions = await listSessions();
  const aiRoot = process.env.AI_ROOT || require('node:path').join(require('node:os').homedir(), 'Documents/AI/ai_root');
  return { sessions, aiRoot };
});

// Query: list all sessions
ipcMain.handle(IPC.SESSION_LIST, async () => {
  return await listSessions();
});

// Query: get single session
ipcMain.handle(IPC.SESSION_GET, async (_event, trackingId: string) => {
  return await getSession(trackingId);
});

// Command: update session fields
ipcMain.handle(IPC.SESSION_UPDATE, async (_event, trackingId: string, patch: Record<string, string>): Promise<CommandResult> => {
  try {
    await updateSession(trackingId, patch);
    emitStoreChanged('command', ['sessions']);
    return { ok: true, command_id: `cmd_${Date.now()}`, changed: { sessions: true } };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, command_id: `cmd_${Date.now()}`, error: { code: 'UPDATE_FAILED', message } };
  }
});

// ─── Session Create & Launch ───────────────────────────────────────────

ipcMain.handle('uai:sessions:create', async (_event, opts: {
  platform: string;
  displayName?: string;
  projectDir?: string;
  roles?: string[];
  parentTrackingId?: string;
}): Promise<CommandResult<{ trackingId: string }>> => {
  try {
    // Step 1: Create draft in session store
    const trackingId = await createDraftSession(opts);

    // Step 2: Launch via ai_launcher with --tracking-id
    launchSession(opts.platform, trackingId, {
      workdir: opts.projectDir,
      roles: opts.roles?.join(','),
      displayName: opts.displayName,
    });

    // The launcher will create the tmux session and update the store.
    // The signal file watch will pick up the change and refresh the renderer.
    emitStoreChanged('command', ['sessions']);

    return {
      ok: true,
      command_id: `cmd_${Date.now()}`,
      data: { trackingId },
      changed: { sessions: true },
    };
  } catch (err: unknown) {
    const message = err instanceof Error ? err.message : String(err);
    return { ok: false, command_id: `cmd_${Date.now()}`, error: { code: 'CREATE_FAILED', message } };
  }
});

// ─── Transcript IPC ────────────────────────────────────────────────────

ipcMain.handle('transcript:read', async (_event, zellijSession: string, cliSessionId: string | undefined, format: string) => {
  const { execFile: ef } = require('node:child_process');
  const aiRoot = process.env.AI_ROOT || path.join(require('node:os').homedir(), 'Documents/AI/ai_root');
  const readJsonlPath = path.join(aiRoot, 'ai_general/scripts/jsonl/read_jsonl.py');
  const envPath = [process.env.PATH || '', '/opt/homebrew/bin', '/usr/local/bin'].join(':');

  const uuid = cliSessionId;
  if (!uuid) {
    return { ok: false, error: 'No CLI UUID available for transcript' };
  }

  // Step 1: find the JSONL file path using read_jsonl.py find
  const findResult: string = await new Promise<string>((resolve, reject) => {
    ef('python3', [readJsonlPath, 'find', uuid], {
      maxBuffer: 1024 * 1024,
      timeout: 10000,
      env: { ...process.env, PATH: envPath },
    }, (error: any, stdout: string) => {
      if (error) {
        reject(new Error(`find failed: ${error.message}`));
        return;
      }
      resolve(stdout.trim());
    });
  }).catch(() => '');

  if (!findResult) {
    return { ok: false, error: `Session file not found for UUID ${uuid}` };
  }

  // Step 2: read the file with structured format
  const outputFormat = format || 'structured';
  return new Promise((resolve) => {
    ef('python3', [readJsonlPath, 'read-file', findResult, '--format', outputFormat], {
      maxBuffer: 20 * 1024 * 1024,
      timeout: 30000,
      env: { ...process.env, PATH: envPath },
    }, (error: any, stdout: string, stderr: string) => {
      if (error) {
        resolve({ ok: false, error: stderr || error.message });
        return;
      }
      try {
        const parsed = JSON.parse(stdout);
        resolve({ ok: true, days: parsed, uuid, format: outputFormat });
      } catch {
        resolve({ ok: false, error: 'Invalid JSON from read_jsonl.py' });
      }
    });
  });
});

// ─── Clipboard IPC ─────────────────────────────────────────────────────

ipcMain.handle('clipboard:write', (_event, text: string) => {
  clipboard.writeText(text);
  return { success: true };
});

ipcMain.handle('clipboard:read', () => {
  return clipboard.readText();
});

// ─── Terminal IPC ──────────────────────────────────────────────────────

ipcMain.handle('terminal:attach', (_event, sessionId: string, terminalSession: string, cols: number, rows: number) => {
  if (!mainWindow) return;
  attachTerminal(sessionId, terminalSession, cols, rows, mainWindow);
});

ipcMain.on('terminal:input', (_event, sessionId: string, data: string) => {
  writeTerminal(sessionId, data);
});

ipcMain.on('terminal:resize', (_event, sessionId: string, cols: number, rows: number) => {
  resizeTerminal(sessionId, cols, rows);
});

ipcMain.handle('terminal:detach', (_event, sessionId: string) => {
  detachTerminal(sessionId);
});

// ─── Store Change Events (Path 2: main → renderer) ────────────────────────

function emitStoreChanged(source: 'command' | 'external' | 'poll', changed: string[]): void {
  if (!mainWindow) return;
  changeSequence++;
  const event: StoreChangedEvent = {
    event_id: `evt_${Date.now()}_${changeSequence}`,
    sequence: changeSequence,
    changed: changed as StoreChangedEvent['changed'],
    source,
  };
  mainWindow.webContents.send(IPC.STORE_CHANGED, event);
}

// ─── Vite global declarations ──────────────────────────────────────────────

declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string | undefined;
declare const MAIN_WINDOW_VITE_NAME: string;

// ─── App Lifecycle ─────────────────────────────────────────────────────────

app.whenReady().then(() => {
  // Application menu — required for clipboard shortcuts (Cmd+C/V/X/A) to work
  const isMac = process.platform === 'darwin';
  const appMenu = Menu.buildFromTemplate([
    ...(isMac ? [{ label: app.name, submenu: [
      { role: 'about' as const },
      { type: 'separator' as const },
      { role: 'hide' as const },
      { role: 'hideOthers' as const },
      { type: 'separator' as const },
      { role: 'quit' as const },
    ]}] : []),
    { label: 'Edit', submenu: [
      { role: 'undo' as const },
      { role: 'redo' as const },
      { type: 'separator' as const },
      { role: 'cut' as const },
      { role: 'copy' as const },
      { role: 'paste' as const },
      { role: 'selectAll' as const },
    ]},
    { label: 'View', submenu: [
      { role: 'reload' as const },
      { role: 'toggleDevTools' as const },
      { type: 'separator' as const },
      { role: 'resetZoom' as const },
      { role: 'zoomIn' as const },
      { role: 'zoomOut' as const },
    ]},
    { label: 'Window', submenu: [
      { role: 'minimize' as const },
      { role: 'close' as const },
    ]},
  ]);
  Menu.setApplicationMenu(appMenu);

  createWindow();

  // Watch sessions.changed signal file for external writes (Path 2: external → renderer)
  const aiRoot = process.env.AI_ROOT || path.join(require('node:os').homedir(), 'Documents/AI/ai_root');
  const signalFile = path.join(aiRoot, 'ai_general', 'data', 'sessions.changed');
  let signalDebounce: NodeJS.Timeout | null = null;
  try {
    // Ensure signal file exists
    if (!fs.existsSync(signalFile)) {
      fs.writeFileSync(signalFile, '');
    }
    fs.watch(signalFile, () => {
      if (signalDebounce) clearTimeout(signalDebounce);
      signalDebounce = setTimeout(() => {
        emitStoreChanged('external', ['sessions']);
      }, 300);
    });
  } catch (err) {
    console.error('[UAI] Failed to watch signal file:', err);
  }
});

app.on('window-all-closed', () => {
  detachAll();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  detachAll();
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});
