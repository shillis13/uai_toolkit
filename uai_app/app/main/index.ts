/**
 * UAI Main Process — Phase 1
 *
 * Architecture:
 *   Path 1 (outbound): Renderer dispatches command via IPC → CommandBus.execute()
 *                       → handler → store mutation → CommandResult
 *   Path 2 (inbound):  Main emits store/runtime change events → renderer updates snapshots
 *
 * The main process is the only app-side writer to external stores.
 * All domain mutations route through the CommandBus.
 * Read-only queries use direct IPC handlers.
 */

import { app, BrowserWindow, ipcMain, Menu, clipboard, shell, dialog, screen } from 'electron';
import * as path from 'node:path';
import * as fs from 'node:fs';
import { CommandBus, createCommand } from './command-bus';
import { registerCommandHandlers, normalizePersistedAppState } from './command-handlers';
import { listSessions, getSession, callStore as callSessionStore, callSessionMgr } from './session-store';
import { loadFolders } from './folder-manager';
import { loadContainers } from './container-manager';
import { listProjects, listHiddenRegistryEntities } from './project-indexer';
import { indexBriefs } from './brief-indexer';
import {
  attachTerminal, writeTerminal, resizeTerminal, detachTerminal, detachAll,
  createStandaloneTerminal, writeStandaloneTerminal, resizeStandaloneTerminal, closeStandaloneTerminal,
} from './terminal';
import {
  initActivityLog,
  logCommandExecution,
  logLifecycleEvent,
  logError,
  getRecentErrors,
  getLastError,
  clearRecentErrors,
  readActivityLog,
  tailActivityLog,
  getSystemMetrics,
} from './activity-log';
import { IPC } from '@uai/shared/types';
import type { StoreChangedEvent, Command, DeepLinkEvent } from '@uai/shared/types';
import {
  listQueueEntries, countQueueEntries, listInboxMessages, listArchiveMessages, listSentMessages, countInboxMessages,
  holdQueueEntry, releaseQueueEntry, changeQueueDelivery, removeQueueEntry,
  sendMessage, markRead,
  archiveMessage, markUnread, deleteInboxMessage, replyToMessage,
} from './comms-reader';
import { isLocked, lockSession, unlockSession, listLocks } from './conversation-lock';
import { searchTranscripts, searchTranscriptsGrouped } from './search';
import { getAppStatePath } from './app-state-path';
import { createBrief } from './brief-ops';
import { runSessionTraits } from './session-traits';
import { runTodoMgr, resolveTodoDir, todosRoot } from './todo-ops';

// Squirrel startup handler
try {
  if (require('electron-squirrel-startup')) {
    console.log('[UAI] Squirrel startup detected, quitting');
    app.quit();
  }
} catch (e) {
  console.log('[UAI] electron-squirrel-startup not available (dev mode)');
}

// No single-instance lock — multiple instances can run simultaneously
// (e.g., production + test builds side by side).

// Chrome DevTools Protocol — always enabled for bgapp/E2E testing and dev tools
app.commandLine.appendSwitch('remote-debugging-port', process.env.UCI_DEBUG_PORT || process.env.UAI_DEBUG_PORT || '9226');
app.commandLine.appendSwitch('remote-allow-origins', '*');


let mainWindow: BrowserWindow | null = null;
let changeSequence = 0;

// ─── Command Bus ──────────────────────────────────────────────────────────

const commandBus = new CommandBus();

// ─── Dynamic Tabs Menu ───────────────────────────────────────────────────

function rebuildAppMenu(tabs?: any[], activeTabId?: string | null): void {
  const isMac = process.platform === 'darwin';

  // If not provided, read from app_state.json
  let tabList: any[] = tabs || [];
  let currentActiveTabId = activeTabId;
  if (tabs === undefined) {
    try {
      const statePath = appStatePath();
      const parsed = JSON.parse(fs.readFileSync(statePath, 'utf-8'));
      tabList = Array.isArray(parsed.tabs) ? parsed.tabs : [];
      currentActiveTabId = parsed.activeTabId ?? null;
    } catch {
      tabList = [];
      currentActiveTabId = null;
    }
  }

  const tabMenuItems: Electron.MenuItemConstructorOptions[] = tabList.map((tab: any, i: number) => ({
    label: tab.label || tab.targetId || 'Untitled',
    accelerator: i < 9 ? `CmdOrCtrl+${i + 1}` : undefined,
    click: () => {
      commandBus.execute(createCommand('workspace.tabs.activate', { tabId: tab.id }, 'internal'));
    },
    type: 'checkbox' as const,
    checked: tab.id === currentActiveTabId,
  }));

  if (tabMenuItems.length > 0) {
    tabMenuItems.push({ type: 'separator' });
  }
  tabMenuItems.push({
    label: 'Close Tab',
    accelerator: 'CmdOrCtrl+W',
    click: () => {
      // Close the currently active tab — read fresh state at click time
      try {
        const statePath = appStatePath();
        const parsed = JSON.parse(fs.readFileSync(statePath, 'utf-8'));
        const activeId = parsed.activeTabId;
        if (activeId) {
          commandBus.execute(createCommand('workspace.tabs.close', { tabId: activeId }, 'internal'));
        }
      } catch {
        // no-op if state can't be read
      }
    },
  });

  const template: Electron.MenuItemConstructorOptions[] = [
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
    { label: 'Tabs', submenu: tabMenuItems },
  ];

  Menu.setApplicationMenu(Menu.buildFromTemplate(template));
}

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
  // Rebuild Tabs menu whenever appState changes (tab list or active tab may have changed)
  if (changed.includes('appState')) {
    rebuildAppMenu();
  }
}

// Initialize activity log
const aiRootForLog = getAiRootMain();
initActivityLog(aiRootForLog);

// ─── Error capture ───────────────────────────────────────────────────────
// Persist uncaught errors and patch console.error/warn so the many existing
// `[uai:...] failed:` call sites flow into the App Log + error log + status bar.
process.on('uncaughtException', (err: Error) => {
  logError('main', err.message || String(err), { stack: err.stack, level: 'error', detail: { kind: 'uncaughtException' } });
});
process.on('unhandledRejection', (reason: unknown) => {
  const msg = reason instanceof Error ? reason.message : String(reason);
  const stack = reason instanceof Error ? reason.stack : undefined;
  logError('main', msg, { stack, level: 'error', detail: { kind: 'unhandledRejection' } });
});

const _origConsoleError = console.error.bind(console);
const _origConsoleWarn = console.warn.bind(console);
console.error = (...args: unknown[]): void => {
  _origConsoleError(...args);
  try { logError('main', args.map(a => (a instanceof Error ? a.stack || a.message : String(a))).join(' '), { level: 'error' }); } catch { /* noop */ }
};
console.warn = (...args: unknown[]): void => {
  _origConsoleWarn(...args);
  try { logError('main', args.map(a => String(a)).join(' '), { level: 'warn' }); } catch { /* noop */ }
};

// Register all command handlers
registerCommandHandlers(commandBus, emitStoreChanged);

// ─── Activity Log Hook (1D.2) ────────────────────────────────────────────
// After every command execution, write a formal activity log entry.
// After-hooks receive (command, result, durationMs) directly — no log scraping needed.
commandBus.after('*', async (command, result, durationMs) => {
  const payload = command.payload as Record<string, unknown> | undefined;
  // Prefer an explicit session in the payload; fall back to a tracking_id
  // produced by the handler (e.g. session.create returns the new id in data).
  const resultData = result.data as Record<string, unknown> | undefined;
  const targetSession = (payload?.trackingId as string)
    || (payload?.sessionId as string)
    || (resultData?.trackingId as string)
    || undefined;
  logCommandExecution(
    command.type,
    command.origin,
    result.ok,
    durationMs,
    result.error?.code,
    command.correlation_id,
    targetSession,
  );
  // Surface failed commands as errors so they show in the log + status bar.
  if (!result.ok) {
    logError('command', `${command.type} failed: ${result.error?.message || result.error?.code || 'unknown error'}`, {
      session: targetSession,
      level: 'error',
      detail: { command_type: command.type, error_code: result.error?.code },
    });
  }
});

// ─── Window state persistence ───────────────────────────────────────────────
// Remember the window's size/position/maximized-state across restarts so the app
// reopens exactly where it was last closed. Stored in Electron's per-app userData
// dir (per machine, not in the repo). Skipped entirely for offscreen test instances
// — they use fixed off-screen geometry and their own --user-data-dir, so real state
// is never touched.

interface WindowState { x?: number; y?: number; width: number; height: number; isMaximized?: boolean; }
const DEFAULT_WINDOW_STATE: WindowState = { width: 1800, height: 1100 };
const windowStateFile = (): string => path.join(app.getPath('userData'), 'window-state.json');

function loadWindowState(): WindowState {
  try {
    const s = JSON.parse(fs.readFileSync(windowStateFile(), 'utf8')) as WindowState;
    if (typeof s.width !== 'number' || typeof s.height !== 'number' || s.width < 400 || s.height < 300) {
      return { ...DEFAULT_WINDOW_STATE };
    }
    // A monitor may have been unplugged since last run. If the saved rect no longer
    // intersects any connected display, drop x/y so the window centers on-screen.
    if (typeof s.x === 'number' && typeof s.y === 'number') {
      const onScreen = screen.getAllDisplays().some((d) => {
        const wa = d.workArea;
        return s.x! < wa.x + wa.width && s.x! + s.width > wa.x && s.y! < wa.y + wa.height && s.y! + s.height > wa.y;
      });
      if (!onScreen) { delete s.x; delete s.y; }
    }
    return s;
  } catch { return { ...DEFAULT_WINDOW_STATE }; }
}

let saveWindowStateTimer: ReturnType<typeof setTimeout> | null = null;
function saveWindowState(): void {
  if (!mainWindow || mainWindow.isDestroyed()) return;
  if (process.env.UAI_TEST_OFFSCREEN === '1') return;
  try {
    // getNormalBounds() is the restore-to rect (ignores the maximized frame), so a
    // window closed while maximized still remembers where to land when un-maximized.
    const b = mainWindow.getNormalBounds();
    const state: WindowState = { x: b.x, y: b.y, width: b.width, height: b.height, isMaximized: mainWindow.isMaximized() };
    fs.writeFileSync(windowStateFile(), JSON.stringify(state));
  } catch { /* best-effort — window geometry is non-critical */ }
}
function scheduleSaveWindowState(): void {
  if (saveWindowStateTimer) clearTimeout(saveWindowStateTimer);
  saveWindowStateTimer = setTimeout(saveWindowState, 400);
}

// ─── Window ───────────────────────────────────────────────────────────────

function createWindow(): void {
  // Test/dev instances can render off-screen so they don't disturb the
  // user's running app. Gated behind UAI_TEST_OFFSCREEN — zero effect normally.
  const offscreen = process.env.UAI_TEST_OFFSCREEN === '1';
  // Restore last-session window geometry (real instances only).
  const saved = offscreen ? null : loadWindowState();
  mainWindow = new BrowserWindow({
    width: saved?.width ?? 1800,
    height: saved?.height ?? 1100,
    ...(saved && typeof saved.x === 'number' && typeof saved.y === 'number' ? { x: saved.x, y: saved.y } : {}),
    // Test/dev instances: create hidden + fully transparent + off-screen + off the
    // dock. `show:false` avoids the launch-time app activation that, on macOS, pulls
    // an off-screen window onto the active display (the bug: test windows filling the
    // built-in screen). We showInactive() it below so it still renders/layouts for
    // verification, but never appears or steals focus. opacity:0 is belt-and-suspenders
    // in case the OS repositions it on-screen anyway.
    ...(offscreen ? { x: -8000, y: -8000, show: false, opacity: 0, skipTaskbar: true } : {}),
    title: `UAI v${app.getVersion()}`,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      webviewTag: true,
      spellcheck: true,
    },
    titleBarStyle: 'default',
    backgroundColor: '#0a0c10',
  });

  if (offscreen) {
    // Render the instance without bringing it on-screen or stealing focus. On macOS
    // app activation pulls off-screen windows onto the active display; showInactive()
    // shows (so the renderer lays out for CDP verification) WITHOUT activating.
    try { app.dock?.hide(); } catch { /* non-macOS */ }
    mainWindow.setIgnoreMouseEvents(true);
    // Make the hidden window transparent BEFORE its first shown frame. Setting
    // opacity after showInactive() can flash one visible frame on the active display.
    mainWindow.setOpacity(0);
    mainWindow.showInactive();
    // showInactive() can pull the window back onto the active display (observed
    // landing at x:0 despite the -8000 constructor bounds). Force it truly off-screen
    // AFTER showing so a test instance never appears over PM's screen — not merely
    // transparent (todo_0631, per Hamilton: default to truly off-screen, safest).
    mainWindow.setPosition(-8000, -8000);
    const b = mainWindow.getBounds();
    console.log(`[UAI][offscreen] showInactive bounds=${JSON.stringify(b)} visible=${mainWindow.isVisible()} opacity=${mainWindow.getOpacity()}`);
  }

  // Spellchecker languages
  mainWindow.webContents.session.setSpellCheckerLanguages(['en-US', 'en-GB']);

  // Context menu — spelling suggestions, add-to-dictionary, cut/copy/paste
  mainWindow.webContents.on('context-menu', (_event, params) => {
    try {
      const menuItems: Electron.MenuItemConstructorOptions[] = [];

      // Spelling suggestions for misspelled words
      if (params.misspelledWord) {
        for (const suggestion of params.dictionarySuggestions.slice(0, 5)) {
          menuItems.push({
            label: suggestion,
            click: () => mainWindow!.webContents.replaceMisspelling(suggestion),
          });
        }
        if (params.dictionarySuggestions.length === 0) {
          menuItems.push({ label: 'No suggestions', enabled: false });
        }
        menuItems.push({ type: 'separator' });
        menuItems.push({
          label: 'Add to Dictionary',
          click: () => mainWindow!.webContents.session.addWordToSpellCheckerDictionary(params.misspelledWord),
        });
        menuItems.push({ type: 'separator' });
      }

      // Editable fields (textarea, input, contenteditable) — always show editing ops
      if (params.isEditable) {
        menuItems.push(
          { label: 'Cut', role: 'cut', enabled: params.editFlags.canCut },
          { label: 'Copy', role: 'copy', enabled: params.editFlags.canCopy },
          { label: 'Paste', role: 'paste', enabled: params.editFlags.canPaste },
          { label: 'Select All', role: 'selectAll' },
        );
      } else if (params.selectionText) {
        menuItems.push({ label: 'Copy', role: 'copy' });
      }

      // Fallback: if we have spelling suggestions but params.isEditable was false
      // (can happen with certain React-controlled inputs), still show paste
      if (params.misspelledWord && !params.isEditable) {
        menuItems.push(
          { label: 'Cut', role: 'cut' },
          { label: 'Copy', role: 'copy' },
          { label: 'Paste', role: 'paste' },
          { label: 'Select All', role: 'selectAll' },
        );
      }

      if (menuItems.length > 0) {
        Menu.buildFromTemplate(menuItems).popup();
      }
    } catch (err) {
      console.error('[context-menu] Error building menu:', err);
    }
  });

  // Resolve the Vite entry. electron-forge injects MAIN_WINDOW_VITE_DEV_SERVER_URL
  // and MAIN_WINDOW_VITE_NAME as build-time globals. A plain `vite build` (scripts/
  // start.sh, scripts/run_test_uai_app.sh) does NOT define them — and a bare reference
  // throws ReferenceError, so the window never loads (blank). `typeof` on an undeclared
  // global is safe; fall back to the launcher's env var, then a default. (todo_0321)
  const devServerUrl: string | undefined =
    (typeof MAIN_WINDOW_VITE_DEV_SERVER_URL !== 'undefined' ? MAIN_WINDOW_VITE_DEV_SERVER_URL : undefined)
    ?? process.env.MAIN_WINDOW_VITE_DEV_SERVER_URL;
  const rendererName: string =
    (typeof MAIN_WINDOW_VITE_NAME !== 'undefined' ? MAIN_WINDOW_VITE_NAME : undefined)
    ?? process.env.MAIN_WINDOW_VITE_NAME
    ?? 'main_window';

  if (devServerUrl) {
    // Retry loading dev server URL — Vite may not be ready when Electron starts
    const loadWithRetry = async (url: string, retries = 5, delay = 1000) => {
      for (let i = 0; i < retries; i++) {
        try {
          await mainWindow!.loadURL(url);
          return;
        } catch {
          if (i < retries - 1) {
            await new Promise(r => setTimeout(r, delay));
          }
        }
      }
      console.error('[UAI] Failed to load dev server after retries:', url);
    };
    loadWithRetry(devServerUrl);
  } else {
    mainWindow.loadFile(path.join(__dirname, `../renderer/${rendererName}/index.html`));
  }

  // Set distinctive title for window identification
  mainWindow.setTitle(`UAI v${app.getVersion()}`);
  mainWindow.webContents.on('did-finish-load', () => {
    mainWindow?.setTitle(`UAI v${app.getVersion()}`);
  });

  // Restore maximized state, and persist geometry on any change (real instances only).
  if (!offscreen) {
    if (saved?.isMaximized) mainWindow.maximize();
    mainWindow.on('resize', scheduleSaveWindowState);
    mainWindow.on('move', scheduleSaveWindowState);
    mainWindow.on('maximize', saveWindowState);
    mainWindow.on('unmaximize', saveWindowState);
    mainWindow.on('close', saveWindowState);
  }

  mainWindow.on('closed', () => { mainWindow = null; });
}

// ─── IPC: Command Bus Bridge ──────────────────────────────────────────────

// The single entry point for all domain mutations from the renderer.
// Renderer calls window.uai.execute(command) → this handler → CommandBus.
ipcMain.handle(IPC.COMMAND_EXECUTE, async (_event, command: Command) => {
  return await commandBus.execute(command);
});

// ─── IPC: Read-Only Queries (bypass command bus) ──────────────────────────

ipcMain.handle(IPC.BOOTSTRAP, async () => {
  const sessions = await listSessions();
  const aiRoot = getAiRootMain();
  return { sessions, aiRoot };
});

ipcMain.handle(IPC.SESSION_LIST, async () => {
  return await listSessions();
});

ipcMain.handle(IPC.SESSION_GET, async (_event, trackingId: string) => {
  return await getSession(trackingId);
});

// ─── IPC: Legacy Command Handlers (backward compat with spike) ────────────
// These route through the command bus internally so hooks and logging apply.

ipcMain.handle(IPC.SESSION_UPDATE, async (_event, trackingId: string, patch: Record<string, string>) => {
  const command = createCommand('session.update', { trackingId, patch }, 'user');
  return await commandBus.execute(command);
});

ipcMain.handle(IPC.SESSION_CREATE, async (_event, opts: {
  platform: string;
  displayName?: string;
  projectDir?: string;
  roles?: string[];
  parentTrackingId?: string;
}) => {
  const command = createCommand('session.create', opts, 'user');
  return await commandBus.execute(command);
});

// ─── IPC: App State ───────────────────────────────────────────────────────

const appStatePath = (): string => getAppStatePath();

ipcMain.handle(IPC.APP_STATE_GET, async () => {
  try {
    const content = fs.readFileSync(appStatePath(), 'utf-8');
    const parsed = JSON.parse(content);
    const current = typeof parsed === 'object' && parsed !== null && !Array.isArray(parsed)
      ? parsed as Record<string, unknown>
      : {};
    const { state, changed } = normalizePersistedAppState(current);
    if (changed) {
      fs.writeFileSync(appStatePath(), JSON.stringify(state, null, 2));
    }
    return state;
  } catch {
    return {};
  }
});

ipcMain.handle(IPC.APP_STATE_UPDATE, async (_event, patch: Record<string, unknown>) => {
  const command = createCommand('app.state.update', { patch }, 'user');
  return await commandBus.execute(command);
});

// ─── IPC: Folders ─────────────────────────────────────────────────────────

ipcMain.handle(IPC.FOLDER_LIST, async () => {
  try {
    return loadFolders();
  } catch {
    return null;
  }
});

ipcMain.handle(IPC.CONTAINER_LIST, async () => {
  try {
    return loadContainers();
  } catch {
    return null;
  }
});

// ─── IPC: Projects ───────────────────────────────────────────────────────

ipcMain.handle(IPC.PROJECT_LIST, async () => {
  try {
    // Gather session project_dirs for session counting
    const sessions = await listSessions();
    const sessionProjectDirs = sessions.map(s => s.project_dir).filter(Boolean);
    return await listProjects({ sessionProjectDirs });
  } catch {
    return [];
  }
});

// Hidden registry entities (projects + teams) for the Restore-hidden UI.
ipcMain.handle('uai:entities:listHidden', async () => {
  try {
    return listHiddenRegistryEntities();
  } catch {
    return [];
  }
});

// ─── IPC: Briefs ─────────────────────────────────────────────────────────

ipcMain.handle(IPC.BRIEF_LIST, async () => {
  try {
    return indexBriefs();
  } catch {
    return [];
  }
});

ipcMain.handle(IPC.BRIEF_CREATE, async (_event, sessionIds: string | string[], opts: {
  name: string;
  description?: string;
  folder: string;
  launch?: boolean;
  launchName?: string;
  launchPlatform?: string;
  condenserSession?: string;
  hostSession?: string;
}) => {
  const result = await createBrief(sessionIds, opts);
  if (result.ok) {
    emitStoreChanged('command', ['briefs']);
  }
  return result;
});

// ─── IPC: Tags (read-only queries) ───────────────────────────────────────

ipcMain.handle(IPC.TAGS_LIST, async () => {
  try {
    const { listDistinctTags } = require('./session-store');
    const distinct = await listDistinctTags();
    // Convert {name, count} to Tag objects for the renderer
    return distinct.map((t: { name: string; count: number }) => ({
      name: t.name,
      color: null,
      icon: null,
      entity_types: ['session', 'brief'],
    }));
  } catch {
    return [];
  }
});

ipcMain.handle(IPC.TAGS_FOR_CARD, async (_event, cardId: string) => {
  try {
    return await callSessionStore(['get_tags', cardId]);
  } catch {
    return [];
  }
});

// ─── IPC: Relationships (read-only queries) ──────────────────────────────

ipcMain.handle(IPC.RELATIONSHIPS_FOR_ENTITY, async (_event, entityType: string, entityId: string) => {
  try {
    return await callSessionStore(['get_relationships', entityType, entityId]);
  } catch {
    return [];
  }
});

// ─── IPC: Traits — Session context browser ──────────────────────────────
// runSessionTraits is now imported from './session-traits'

/**
 * Resolve a trait/role/skill/mslot name to its file path on disk.
 * Mirrors the resolution logic in session_traits.py.
 */
function resolveTraitFilePath(type: string, name: string): string | undefined {
  const aiRoot = getAiRootMain();
  const traitsDir = path.join(aiRoot, 'ai_general', 'ai_traits');
  const rolesDir = path.join(aiRoot, 'ai_general', 'ai_profiles', 'roles');
  const skillsDir = path.join(aiRoot, 'ai_general', 'ai_profiles', 'skills');
  const mslotDir = path.join(aiRoot, 'ai_memories', '80_working_memory');

  if (type === 'traits') {
    // Try resolution order matching session_traits.py _resolve_trait_path
    const suffixes = [
      '.latest.condensed.yml',
      '.latest.yml',
      '.latest.md',
      '.condensed.yml',
      '.yml',
      '.md',
    ];
    for (const suffix of suffixes) {
      const candidate = path.join(traitsDir, name + suffix);
      try { if (fs.existsSync(candidate)) return candidate; } catch { /* skip */ }
    }
    // Try as-is (already has extension)
    const asIs = path.join(traitsDir, name);
    try { if (fs.existsSync(asIs)) return asIs; } catch { /* skip */ }
  } else if (type === 'roles') {
    if (name.startsWith('skill:')) {
      const skillName = name.slice(6);
      const candidate = path.join(skillsDir, skillName + '.yml');
      try { if (fs.existsSync(candidate)) return candidate; } catch { /* skip */ }
    } else {
      const candidate = path.join(rolesDir, name + '.yml');
      try { if (fs.existsSync(candidate)) return candidate; } catch { /* skip */ }
    }
  } else if (type === 'profiles') {
    const profilesDir = path.join(aiRoot, 'ai_general', 'ai_profiles');
    const candidate = path.join(profilesDir, name + '.yml');
    try { if (fs.existsSync(candidate)) return candidate; } catch { /* skip */ }
  } else if (type === 'mslots') {
    const slotNum = name.includes(':') ? name.split(':')[0] : name;
    const candidate = path.join(mslotDir, slotNum + '.yml');
    try { if (fs.existsSync(candidate)) return candidate; } catch { /* skip */ }
  } else if (type === 'briefs') {
    const briefsDir = path.join(aiRoot, 'ai_general', 'data', 'session_briefs');
    const candidate = path.join(briefsDir, name + '.yml');
    try { if (fs.existsSync(candidate)) return candidate; } catch { /* skip */ }
  } else if (type === 'globals') {
    const globalsDir = path.join(aiRoot, 'ai_general', 'ai_context_files', 'globals');
    for (const suffix of ['.md', '.yml', '.txt']) {
      const candidate = path.join(globalsDir, name + suffix);
      try { if (fs.existsSync(candidate)) return candidate; } catch { /* skip */ }
    }
  }
  return undefined;
}

ipcMain.handle('traits:list', async (_event, sessionId: string) => {
  try {
    // Fetch all available, loaded, and pending separately
    const [allData, loadedData, pendingData] = await Promise.all([
      runSessionTraits(['--session', sessionId, 'list', '--all']) as Promise<Record<string, string[]>>,
      runSessionTraits(['--session', sessionId, 'list', '--loaded']) as Promise<Record<string, string[]>>,
      runSessionTraits(['--session', sessionId, 'pending']) as Promise<{ items: Array<{ type: string; name: string }>; count: number }>,
    ]);

    const loadedSets: Record<string, Set<string>> = {};
    for (const [type, names] of Object.entries(loadedData || {})) {
      loadedSets[type] = new Set(Array.isArray(names) ? names : []);
    }

    // Build set of pending keys for quick lookup
    const pendingKeys = new Set<string>();
    if (pendingData?.items) {
      for (const item of pendingData.items) {
        pendingKeys.add(`${item.type}::${item.name}`);
      }
    }

    // state: 'loaded' (delivered), 'pending' (queued for delivery), undefined (not loaded)
    const result: Array<{ type: string; name: string; loaded: boolean; state?: string; filePath?: string; mtime?: string }> = [];
    for (const [type, names] of Object.entries(allData || {})) {
      if (!Array.isArray(names)) continue;
      const loadedSet = loadedSets[type] || new Set();
      for (const name of names) {
        const filePath = resolveTraitFilePath(type, name);
        const isPending = pendingKeys.has(`${type}::${name}`);
        const isLoaded = loadedSet.has(name);
        let mtime: string | undefined;
        if (filePath) {
          try { mtime = fs.statSync(filePath).mtime.toISOString(); } catch { /* skip */ }
        }
        result.push({
          type, name,
          loaded: isLoaded && !isPending,
          state: isPending ? 'pending' : (isLoaded ? 'loaded' : undefined),
          filePath,
          mtime,
        });
      }
    }
    return result;
  } catch {
    return [];
  }
});

ipcMain.handle('traits:load', async (_event, sessionId: string, items: Array<{ type: string; name: string }>) => {
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
    return { success: true, results };
  } catch (e) {
    return { success: false, results: [], error: (e as Error).message };
  }
});

ipcMain.handle('traits:status', async (_event, sessionId: string) => {
  try {
    return await runSessionTraits(['--session', sessionId, 'status']);
  } catch {
    return null;
  }
});

ipcMain.handle('traits:openFile', async (_event, filePath: string) => {
  try {
    // Validate the path exists and is within ai_root before opening
    const aiRoot = getAiRootMain();
    const resolved = path.resolve(filePath);
    if (!resolved.startsWith(aiRoot)) {
      return { ok: false, error: 'Path outside ai_root' };
    }
    if (!fs.existsSync(resolved)) {
      return { ok: false, error: 'File not found' };
    }
    await shell.openPath(resolved);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
});

ipcMain.handle('uai:openPath', async (_event, filePath: string) => {
  try {
    const resolved = path.resolve(filePath.replace(/^~/, require('node:os').homedir()));
    if (!fs.existsSync(resolved)) {
      return { ok: false, error: 'Path not found' };
    }
    await shell.openPath(resolved);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
});

// ─── URL opening: force web links into the frontmost NON-incognito Chrome ────
// Electron's default handler for window.open / target=_blank spawns a native
// child BrowserWindow — which reads as a stray "UAI" browser window. We deny
// that everywhere (setWindowOpenHandler below) and route http/https URLs into
// Chrome instead: a new tab of the topmost *normal* (non-incognito) window, or a
// new window if none exists / Chrome isn't running. Non-web schemes and any
// failure fall back to the OS default opener so the click never dead-ends.
const CHROME_OPEN_SCRIPT = `on run argv
  set theURL to item 1 of argv
  tell application "Google Chrome"
    activate
    if (count of windows) = 0 then
      make new window
      set URL of active tab of front window to theURL
      return
    end if
    set targetWin to missing value
    repeat with w in windows
      try
        if mode of w is "normal" then
          set targetWin to w
          exit repeat
        end if
      end try
    end repeat
    if targetWin is missing value then
      make new window
      set URL of active tab of front window to theURL
    else
      tell targetWin to make new tab with properties {URL:theURL}
      set index of targetWin to 1
    end if
  end tell
end run`;

function openUrlInChrome(rawUrl: string): void {
  const url = String(rawUrl || '').trim();
  if (!url) return;
  let scheme = '';
  try { scheme = new URL(url).protocol; } catch { scheme = ''; }
  // Only web URLs go to Chrome; mailto:/file:/etc. use the OS default handler.
  if (scheme !== 'http:' && scheme !== 'https:') {
    shell.openExternal(url).catch(() => { /* nothing more we can do */ });
    return;
  }
  if (process.platform !== 'darwin') {
    shell.openExternal(url).catch(() => {});
    return;
  }
  const { execFile } = require('node:child_process');
  execFile('osascript', ['-e', CHROME_OPEN_SCRIPT, url], { timeout: 8000 }, (err: Error | null) => {
    // Chrome missing, quit mid-script, or automation denied → default browser.
    if (err) shell.openExternal(url).catch(() => {});
  });
}

ipcMain.handle('uai:openUrl', async (_event, url: string) => {
  try {
    openUrlInChrome(url);
    return { ok: true };
  } catch (e) {
    return { ok: false, error: (e as Error).message };
  }
});

// Deny every renderer/webview attempt to spawn a native child window and route
// web URLs to Chrome. One registration covers the main window AND every
// <webview> pane (each gets its own webContents via this event).
app.on('web-contents-created', (_e, contents) => {
  contents.setWindowOpenHandler(({ url }) => {
    if (url && /^https?:\/\//i.test(url)) openUrlInChrome(url);
    else if (url && url !== 'about:blank') shell.openExternal(url).catch(() => {});
    return { action: 'deny' };
  });
});

// ─── IPC: Comms — Prompt Queue + Inbox (2L) ─────────────────────────────

ipcMain.handle(IPC.COMMS_QUEUE_LIST, async (_event, sessionTrackingId: string) => {
  try {
    return listQueueEntries(sessionTrackingId);
  } catch {
    return [];
  }
});

ipcMain.handle(IPC.COMMS_QUEUE_COUNT, async (_event, sessionTrackingId: string) => {
  try {
    return countQueueEntries(sessionTrackingId);
  } catch {
    return 0;
  }
});

ipcMain.handle(IPC.COMMS_INBOX_LIST, async (_event, sessionTrackingId: string) => {
  try {
    return listInboxMessages(sessionTrackingId);
  } catch {
    return [];
  }
});

ipcMain.handle(IPC.COMMS_INBOX_COUNT, async (_event, sessionTrackingId: string) => {
  try {
    return countInboxMessages(sessionTrackingId);
  } catch {
    return { total: 0, unread: 0 };
  }
});

ipcMain.handle('uai:comms:archive:list', async (_event, sessionTrackingId: string) => {
  try {
    return listArchiveMessages(sessionTrackingId);
  } catch {
    return [];
  }
});

ipcMain.handle('uai:comms:sent:list', async (_event, sessionTrackingId: string) => {
  try {
    // Sends record `from` as either the tracking ID or the display name, so
    // resolve both and match against either (see listSentMessages).
    const rec = await getSession(sessionTrackingId);
    const identities = [sessionTrackingId];
    if (rec?.display_name) identities.push(rec.display_name);
    return listSentMessages(sessionTrackingId, identities);
  } catch {
    return [];
  }
});

// ─── IPC: Message Sending (2L Phase 3) ──────────────────────────────────

ipcMain.handle('uai:comms:send', async (_event, opts: {
  from: string; to: string; content: string;
  urgency?: string; responseType?: string; ttlSeconds?: number; replyTo?: string;
}) => {
  return await sendMessage(opts);
});

ipcMain.handle('uai:comms:read', async (_event, messageId: string, reader: string) => {
  return await markRead(messageId, reader);
});

ipcMain.handle('uai:comms:archive', async (_event, messageId: string) => {
  return await archiveMessage(messageId);
});

ipcMain.handle('uai:comms:markUnread', async (_event, sessionTrackingId: string, messageId: string, reader: string) => {
  return markUnread(sessionTrackingId, messageId, reader);
});

ipcMain.handle('uai:comms:delete', async (_event, sessionTrackingId: string, messageId: string) => {
  return deleteInboxMessage(sessionTrackingId, messageId);
});

ipcMain.handle('uai:comms:reply', async (_event, messageId: string, from: string, content: string) => {
  return await replyToMessage(messageId, from, content);
});

// ─── IPC: Queue Management (2L Phase 2) ─────────────────────────────────

ipcMain.handle('uai:comms:queue:hold', async (_event, sessionTrackingId: string, entryId: string) => {
  return { ok: holdQueueEntry(sessionTrackingId, entryId) };
});

ipcMain.handle('uai:comms:queue:release', async (_event, sessionTrackingId: string, entryId: string) => {
  return { ok: releaseQueueEntry(sessionTrackingId, entryId) };
});

ipcMain.handle('uai:comms:queue:changeDelivery', async (_event, sessionTrackingId: string, entryId: string, delivery: string) => {
  return { ok: changeQueueDelivery(sessionTrackingId, entryId, delivery as any) };
});

ipcMain.handle('uai:comms:queue:remove', async (_event, sessionTrackingId: string, entryId: string) => {
  return { ok: removeQueueEntry(sessionTrackingId, entryId) };
});

// ─── IPC: Conversation Locks (2L) ───────────────────────────────────────

ipcMain.handle('uai:comms:lock:status', async (_event, sessionTrackingId: string) => {
  return isLocked(sessionTrackingId);
});

ipcMain.handle('uai:comms:lock:set', async (_event, sessionTrackingId: string, reason?: string) => {
  lockSession(sessionTrackingId, reason);
  emitStoreChanged('command', ['sessions']);
  return { ok: true };
});

ipcMain.handle('uai:comms:lock:remove', async (_event, sessionTrackingId: string) => {
  unlockSession(sessionTrackingId);
  emitStoreChanged('command', ['sessions']);
  return { ok: true };
});

ipcMain.handle('uai:comms:lock:list', async () => {
  return listLocks();
});

// ─── IPC: Search ────────────────────────────────────────────────────────

ipcMain.handle('uai:search', async (_event, query: string, opts?: {
  limit?: number;
  caseSensitive?: boolean;
  sessionFilter?: string;
  regex?: boolean;
  deduplicate?: boolean;
}) => {
  try {
    return await searchTranscripts(query, opts);
  } catch {
    return [];
  }
});

ipcMain.handle('uai:search:grouped', async (_event, query: string, opts?: {
  limit?: number;
  caseSensitive?: boolean;
  sessionFilter?: string;
  regex?: boolean;
  deduplicate?: boolean;
  includeSubagents?: boolean;
}) => {
  console.log(`[search:grouped] query="${query}" opts=${JSON.stringify(opts)}`);
  try {
    const result = await searchTranscriptsGrouped(query, opts);
    console.log(`[search:grouped] ${result.totalMatches} matches in ${result.results.length} sessions (${result.searchTimeMs}ms)`);
    return result;
  } catch (err) {
    console.error('[search:grouped] Error:', err);
    return { results: [], totalMatches: 0, sessionsSearched: 0, searchTimeMs: 0 };
  }
});

// ─── IPC: Viewport Description (dev/test only) ─────────────────────────────

ipcMain.handle('uai:viewport:describeViewport', async () => {
  // Dev gate: only available when not packaged, or when UAI_VIEWPORT=1
  if (app.isPackaged && process.env.UAI_VIEWPORT !== '1') return null;
  if (!mainWindow || mainWindow.isDestroyed()) return null;

  try {
    return await mainWindow.webContents.executeJavaScript(
      'window.__viewportRegistry?.describeViewport() ?? null'
    );
  } catch {
    return null;
  }
});

// ─── IPC: Activity Log + System Metrics (1D) ─────────────────────────────

ipcMain.handle('uai:activityLog:read', async (_event, opts: {
  limit?: number;
  sessionFilter?: string;
  eventFilter?: string;
}) => {
  return await readActivityLog(opts || {});
});

ipcMain.handle('uai:activityLog:tail', async (_event, sinceTs: string, limit?: number) => {
  return await tailActivityLog(sinceTs, limit);
});

// ─── Error reporting + recent-errors ─────────────────────────────────────
// Renderer reports its own uncaught errors here; they flow into the same
// activity log + error log + status-bar ring buffer as main-process errors.
ipcMain.handle('uai:logError', async (_event, payload: { message: string; stack?: string; session?: string; level?: 'error' | 'warn' }) => {
  logError('renderer', payload?.message || 'unknown renderer error', {
    stack: payload?.stack,
    session: payload?.session,
    level: payload?.level || 'error',
  });
  return { ok: true };
});

ipcMain.handle('uai:getRecentErrors', async (_event, limit?: number) => {
  return getRecentErrors(limit || 10);
});

ipcMain.handle('uai:getLastError', async () => {
  return getLastError();
});

ipcMain.handle('uai:clearErrors', async () => {
  clearRecentErrors();
  return { ok: true };
});

ipcMain.handle('uai:getVersion', () => app.getVersion());

// Memorex overlay debug — returns current overlay state for AI diagnostic queries
ipcMain.handle('uai:memorex:state', async () => {
  if (!mainWindow) return null;
  try {
    return await mainWindow.webContents.executeJavaScript('window.__memorex || null');
  } catch {
    return null;
  }
});

ipcMain.handle('uai:systemMetrics', async () => {
  const sessions = await listSessions();
  const activeCount = sessions.filter((s) => s.process_status === 'running').length;
  return getSystemMetrics(activeCount);
});

// Mounted volumes for the Disk gauge details (on-demand — only when opened).
ipcMain.handle('uai:diskVolumes', async () => {
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);

  // Time Machine destinations to exclude (the backup disk itself + every mounted
  // snapshot). `tmutil destinationinfo` enumerates the registered backup targets;
  // we exclude those mount points plus the whole /Volumes/.timemachine/ tree and
  // any `com.apple.TimeMachine.*` backup device. PianoMan: TM shouldn't count as
  // "disk usage" — it's backup storage, not a working volume.
  const tmMounts = new Set<string>();
  try {
    const { stdout: tm } = await execFileAsync('tmutil', ['destinationinfo'], { timeout: 5000 });
    for (const line of String(tm).split('\n')) {
      const mp = line.match(/^\s*Mount Point\s*:\s*(\/.*\S)\s*$/);
      if (mp) tmMounts.add(mp[1]);
    }
  } catch { /* tmutil unavailable — fall back to path/device heuristics below */ }

  const isTimeMachine = (fs: string, mount: string): boolean =>
    tmMounts.has(mount)
    || mount.startsWith('/Volumes/.timemachine')
    || fs.startsWith('com.apple.TimeMachine');

  try {
    // -k = 1K blocks, -l = local only (skip network mounts).
    const { stdout } = await execFileAsync('df', ['-kl'], { timeout: 5000 });
    const lines = String(stdout).trim().split('\n').slice(1);
    const vols = lines.map((line: string) => {
      // Filesystem 1K-blocks Used Avail Capacity iused ifree %iused Mounted on
      const m = line.match(/^(.+?)\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)%\s+.*?\s+(\/.*)$/);
      if (!m) return null;
      const toGb = (kb: number) => Math.round((kb / 1024 / 1024) * 10) / 10;
      const total = Number(m[2]), used = Number(m[3]), free = Number(m[4]);
      return {
        fs: m[1], mount: m[6],
        total_gb: toGb(total), used_gb: toGb(used), free_gb: toGb(free),
        used_pct: Number(m[5]),
      };
    }).filter((v: any): v is NonNullable<typeof v> => v !== null
      && v.total_gb >= 1
      // ATTACHED volumes only ('/Volumes/*'). The built-in boot volume is shown
      // separately from the sysmon container figure (df's '/' reports the sealed
      // system volume at a misleadingly-low %, not the shared APFS container);
      // and the /System/Volumes/* firmlinks are just boot-container noise.
      && v.mount.startsWith('/Volumes/')
      // …but NOT Time Machine backup disks/snapshots.
      && !isTimeMachine(v.fs, v.mount));
    vols.sort((a: any, b: any) => a.mount.localeCompare(b.mount));
    return vols;
  } catch {
    return [];
  }
});

// ─── IPC: Boot history (Uptime card details) ────────────────────────────
// `last reboot` lists prior boots newest-first. Each line ends with a
// weekday/month/day/time stamp (no year). Returns up to `limit` entries.
ipcMain.handle('uai:bootHistory', async (_event, limit = 10) => {
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  try {
    const { stdout } = await execFileAsync('last', ['reboot'], { timeout: 5000 });
    const re = /\b([A-Z][a-z]{2}\s+[A-Z][a-z]{2}\s+\d{1,2}\s+\d{1,2}:\d{2})\s*$/;
    const boots: Array<{ when: string }> = [];
    for (const line of String(stdout).split('\n')) {
      if (!/^reboot\b/.test(line)) continue;
      const m = line.match(re);
      if (m) boots.push({ when: m[1] });
      if (boots.length >= limit) break;
    }
    return boots;
  } catch {
    return [];
  }
});

// ─── IPC: AI awareness feed (ai_comms/feed/activity.jsonl) ───────────────
// Append-only JSONL of cross-session activity. Returns the most-recent `limit`
// entries, newest first, for the AI Feed pane.
ipcMain.handle('uai:aiFeed:read', async (_event, limit = 300) => {
  try {
    const p = path.join(getAiRootMain(), 'ai_comms', 'feed', 'activity.jsonl');
    const raw = fs.readFileSync(p, 'utf8');
    const lines = raw.split('\n').filter(l => l.trim());
    const entries: Array<Record<string, unknown>> = [];
    // Parse from the tail so a huge feed stays cheap.
    for (let i = lines.length - 1; i >= 0 && entries.length < limit; i--) {
      try { entries.push(JSON.parse(lines[i])); } catch { /* skip malformed */ }
    }
    return entries;  // newest first
  } catch {
    return [];
  }
});

// ─── IPC: Trait Manager (trait_mgr.py) ──────────────────────────────────

ipcMain.handle('uai:traitMgr:run', async (_event, command: string, args: string[]) => {
  // NOTE (todo_0319): "traitMgr"/trait_mgr is old terminology (traits → context files);
  // quickfixed the path here (scripts/traits/ was the deleted old dir). A full rename to
  // ctx-files-mgr / context_mgr is a follow-up.
  const traitMgrPath = path.join(getAiRootMain(), 'ai_general/scripts/context_files/trait_mgr.py');
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  const envPath = shellPath();
  try {
    const { stdout, stderr } = await execFileAsync('python3', [traitMgrPath, '--json', command, ...args], {
      timeout: 30000,
      cwd: getAiRootMain(),
      env: { ...process.env, AI_ROOT: getAiRootMain(), PATH: envPath },
    });
    return { ok: true, data: stdout.trim() ? JSON.parse(stdout.trim()) : null, errors: stderr || undefined };
  } catch (err: any) {
    return { ok: false, error: err.stderr || err.message || String(err), data: null };
  }
});

// ─── IPC: Context Manager (context_mgr.py) ──────────────────────────────
// Read-only index access plus a tight set of graph-edge write verbs. The reads
// are the original Phase-1 surface; `link`/`unlink` are the only writes exposed
// — they edit a bundle's YAML in a formatting-preserving way (ruamel) with
// self/cycle/missing guards in context_mgr, and drive the Link Matrix's
// add/remove-link actions. Other writes (delete/move/create) stay withheld.
// Args are validated against a tight charset (anti-injection), mirroring the
// isValidSchedName guard on scheduled-task names.
const CONTEXT_READ_VERBS = new Set(['list', 'get', 'search', 'refs', 'tree', 'resolve', 'preview', 'validate', 'graph', 'history', 'reindex', 'content', 'categories']);
// link/unlink edit reference edges; archive/delete is a SOFT delete (moves the
// file into the kind's _archive/ subtree — reversible by moving it back).
// create authors a new stub (a leaf .md or a composition .yml skeleton) — it is
// collision-safe (never overwrites) and slug-validated in context_mgr. Hard
// removal and move stay withheld from the UI.
const CONTEXT_WRITE_VERBS = new Set(['link', 'unlink', 'archive', 'delete', 'create']);
function isValidContextArg(arg: string): boolean {
  // Plain values/ids (incl. flag values via `--flag=value`) or bare `--flag`.
  return /^[A-Za-z0-9_:./@%-]+$/.test(arg) || /^--[A-Za-z0-9-]+(=[A-Za-z0-9_:./@%-]+)?$/.test(arg);
}
// `create` carries free-text --title / --description; execFile passes args as an
// array (no shell), so there is no injection vector — only control chars are
// rejected. Bare flags and `--flag=value` (value free-text) both pass.
function isValidCreateArg(arg: string): boolean {
  if (/[\n\r\x00]/.test(arg)) return false;
  return /^--[A-Za-z0-9-]+(=.*)?$/.test(arg) || arg.length > 0;
}

ipcMain.handle('uai:context:run', async (_event, verb: string, args?: string[]) => {
  if (typeof verb !== 'string' || (!CONTEXT_READ_VERBS.has(verb) && !CONTEXT_WRITE_VERBS.has(verb))) {
    return { ok: false, error: 'unknown verb' };
  }
  const safeArgs = Array.isArray(args) ? args : [];
  const argOk = verb === 'create' ? isValidCreateArg : isValidContextArg;
  for (const a of safeArgs) {
    if (typeof a !== 'string' || !argOk(a)) {
      return { ok: false, error: `invalid arg: ${String(a)}` };
    }
  }
  const contextMgrPath = path.join(getAiRootMain(), 'ai_general/scripts/context_files/context_mgr.py');
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  const envPath = shellPath();
  try {
    // NOTE: --json is a per-subcommand flag in context_mgr.py, so it must come
    // AFTER the verb (e.g. `list --json`), not before it. Placing it first makes
    // argparse reject it ("unrecognized arguments: --json") and every call fails.
    const { stdout } = await execFileAsync('python3', [contextMgrPath, verb, '--json', ...safeArgs], {
      timeout: 30000,
      cwd: getAiRootMain(),
      env: { ...process.env, AI_ROOT: getAiRootMain(), PATH: envPath },
    });
    let data: any = null;
    const out = stdout.trim();
    if (out) {
      try { data = JSON.parse(out); } catch { data = null; }
    }
    return { ok: true, data };
  } catch (err: any) {
    return { ok: false, error: err.stderr || err.message || String(err) };
  }
});

// ─── IPC: apply a role's context to its assigned member (load-on-assume) ────
// Resolves a role's context reference (a composition/bundle id, or a file/context
// ref) to its leaf context files via context_mgr, then stages them into the
// member's session inbox (stage_context.py). They load on that session's NEXT
// prompt — non-intrusive; if the member has no running session, stage_context
// errors and we surface that. This is the explicit "make the recorded role
// context actually load" action.
ipcMain.handle('uai:roleContext:apply', async (_event, member: string, context: string) => {
  if (typeof member !== 'string' || !member.trim() || typeof context !== 'string' || !context.trim()) {
    return { ok: false, error: 'member and context are required' };
  }
  const root = getAiRootMain();
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  const env = { ...process.env, AI_ROOT: root, PATH: shellPath() };
  try {
    // 1. Resolve the context ref → leaf file paths.
    const ctxMgr = path.join(root, 'ai_general/scripts/context_files/context_mgr.py');
    let files: string[] = [];
    try {
      const { stdout } = await execFileAsync('python3', [ctxMgr, 'resolve', context, '--json'], { timeout: 30000, cwd: root, env });
      const parsed = JSON.parse((stdout || '').trim() || '{}');
      const resolved = Array.isArray(parsed?.resolved) ? parsed.resolved : [];
      files = resolved.map((r: { path?: string }) => r.path).filter(Boolean)
        .map((p: string) => (path.isAbsolute(p) ? p : path.join(root, p)));
    } catch { files = []; }
    // Fallback: a bare file/free-text ref — treat context as a path.
    if (files.length === 0) {
      const asPath = path.isAbsolute(context) ? context : path.join(root, context);
      if (fs.existsSync(asPath)) files = [asPath];
    }
    if (files.length === 0) return { ok: false, error: `Could not resolve "${context}" to any files` };
    // 2. Stage the files into the member's session inbox.
    const stage = path.join(root, 'ai_general/scripts/cli/stage_context.py');
    await execFileAsync('python3', [stage, member, ...files], { timeout: 30000, cwd: root, env });
    return { ok: true, member, context, count: files.length, staged: files.map(f => path.basename(f)) };
  } catch (err: unknown) {
    const e = err as { stderr?: string; message?: string };
    return { ok: false, error: (e.stderr || e.message || String(err)).trim() };
  }
});

// ─── IPC: Git File View (git_file_view.py) ──────────────────────────
// Returns the commit changelog for a directory over a time range (each commit
// that touches the dir recursively, with per-file A/M/D). The renderer computes
// net deltas between any two commits client-side. Args go straight to argv (no
// shell), so the git --since/--until strings can't inject.
ipcMain.handle('uai:gitFileView:read', async (_event, dir: string, since?: string, until?: string) => {
  if (typeof dir !== 'string' || !dir.trim()) return { ok: false, error: 'dir required' };
  const scriptPath = path.join(getAiRootMain(), 'ai_general/scripts/utils/git_file_view.py');
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  const envPath = shellPath();
  const argv = [scriptPath, '--dir', dir, '--since', (typeof since === 'string' && since) ? since : '30 days ago'];
  if (typeof until === 'string' && until.trim()) argv.push('--until', until);
  try {
    const { stdout } = await execFileAsync('python3', argv, {
      timeout: 30000,
      maxBuffer: 64 * 1024 * 1024,
      cwd: getAiRootMain(),
      env: { ...process.env, AI_ROOT: getAiRootMain(), PATH: envPath },
    });
    try { return JSON.parse(stdout); }
    catch { return { ok: false, error: 'invalid JSON from git_file_view.py' }; }
  } catch (err: any) {
    return { ok: false, error: err.stderr || err.message || String(err) };
  }
});

// Full detail of one commit (Git Commit View): message, trailers, files changed.
ipcMain.handle('uai:gitFileView:commit', async (_event, dir: string, commitHash: string) => {
  if (typeof dir !== 'string' || !dir.trim() || typeof commitHash !== 'string' || !commitHash.trim()) return { ok: false, error: 'dir + commit required' };
  const scriptPath = path.join(getAiRootMain(), 'ai_general/scripts/utils/git_file_view.py');
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  const envPath = shellPath();
  try {
    const { stdout } = await execFileAsync('python3', [scriptPath, '--dir', dir, '--commit', commitHash], {
      timeout: 30000, maxBuffer: 64 * 1024 * 1024, cwd: getAiRootMain(),
      env: { ...process.env, AI_ROOT: getAiRootMain(), PATH: envPath },
    });
    try { return JSON.parse(stdout); }
    catch { return { ok: false, error: 'invalid JSON from git_file_view.py' }; }
  } catch (err: any) {
    return { ok: false, error: err.stderr || err.message || String(err) };
  }
});

// Unified diff of one file across a [from..to] commit span (Git File View detail).
ipcMain.handle('uai:gitFileView:diff', async (_event, dir: string, file: string, fromHash: string, toHash: string) => {
  if (typeof dir !== 'string' || !dir.trim() || typeof file !== 'string' || !file.trim()) return { ok: false, error: 'dir + file required' };
  if (typeof fromHash !== 'string' || typeof toHash !== 'string') return { ok: false, error: 'from + to required' };
  const scriptPath = path.join(getAiRootMain(), 'ai_general/scripts/utils/git_file_view.py');
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  const envPath = shellPath();
  try {
    const { stdout } = await execFileAsync('python3', [scriptPath, '--dir', dir, '--file', file, '--from', fromHash, '--to', toHash], {
      timeout: 30000, maxBuffer: 64 * 1024 * 1024, cwd: getAiRootMain(),
      env: { ...process.env, AI_ROOT: getAiRootMain(), PATH: envPath },
    });
    try { return JSON.parse(stdout); }
    catch { return { ok: false, error: 'invalid JSON from git_file_view.py' }; }
  } catch (err: any) {
    return { ok: false, error: err.stderr || err.message || String(err) };
  }
});

// List git repos under a root (repo selector — #4). Returns {path,name,host,remote}.
ipcMain.handle('uai:gitFileView:repos', async (_event, root: string) => {
  const scriptPath = path.join(getAiRootMain(), 'ai_general/scripts/utils/git_file_view.py');
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  const envPath = shellPath();
  try {
    const { stdout } = await execFileAsync('python3', [scriptPath, '--dir', (root && root.trim()) || '.', '--repos'], {
      timeout: 30000, maxBuffer: 16 * 1024 * 1024, cwd: getAiRootMain(),
      env: { ...process.env, AI_ROOT: getAiRootMain(), PATH: envPath },
    });
    try { return JSON.parse(stdout); }
    catch { return { ok: false, error: 'invalid JSON from git_file_view.py' }; }
  } catch (err: any) {
    return { ok: false, error: err.stderr || err.message || String(err) };
  }
});

// File CONTENT at a git ref (Before / After views — #1 view toggle).
ipcMain.handle('uai:gitFileView:content', async (_event, dir: string, file: string, ref: string) => {
  if (typeof dir !== 'string' || !dir.trim() || typeof file !== 'string' || !file.trim()) return { ok: false, error: 'dir + file required' };
  if (typeof ref !== 'string' || !ref.trim()) return { ok: false, error: 'ref required' };
  const scriptPath = path.join(getAiRootMain(), 'ai_general/scripts/utils/git_file_view.py');
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  const envPath = shellPath();
  try {
    const { stdout } = await execFileAsync('python3', [scriptPath, '--dir', dir, '--file', file, '--show', ref], {
      timeout: 30000, maxBuffer: 64 * 1024 * 1024, cwd: getAiRootMain(),
      env: { ...process.env, AI_ROOT: getAiRootMain(), PATH: envPath },
    });
    try { return JSON.parse(stdout); }
    catch { return { ok: false, error: 'invalid JSON from git_file_view.py' }; }
  } catch (err: any) {
    return { ok: false, error: err.stderr || err.message || String(err) };
  }
});

ipcMain.handle('uai:gitFileView:grep', async (_event, dir: string, pattern: string, toRef?: string) => {
  if (typeof dir !== 'string' || !dir.trim()) return { ok: false, error: 'dir required' };
  if (typeof pattern !== 'string' || !pattern.trim()) return { ok: true, matches: [] };
  const scriptPath = path.join(getAiRootMain(), 'ai_general/scripts/utils/git_file_view.py');
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  const envPath = shellPath();
  const argv = [scriptPath, '--dir', dir, '--grep', pattern];
  if (typeof toRef === 'string' && toRef.trim()) argv.push('--to', toRef);
  try {
    const { stdout } = await execFileAsync('python3', argv, {
      timeout: 30000, maxBuffer: 32 * 1024 * 1024, cwd: getAiRootMain(),
      env: { ...process.env, AI_ROOT: getAiRootMain(), PATH: envPath },
    });
    try { return JSON.parse(stdout); }
    catch { return { ok: false, error: 'invalid JSON from git_file_view.py' }; }
  } catch (err: any) {
    return { ok: false, error: err.stderr || err.message || String(err) };
  }
});

// ─── IPC: Globals (context files) ───────────────────────────────────

ipcMain.handle('uai:globals:list', async () => {
  const globalsDir = path.join(getAiRootMain(), 'ai_general', 'ai_context_files', 'globals');
  try {
    const entries = fs.readdirSync(globalsDir, { withFileTypes: true });
    const globals = entries
      .filter(e => e.isFile() && /\.(md|yml|txt)$/.test(e.name) && !e.name.startsWith('.'))
      .map(e => ({
        name: path.parse(e.name).name,
        path: path.join(globalsDir, e.name),
        ext: path.parse(e.name).ext,
      }))
      .sort((a, b) => a.name.localeCompare(b.name));
    return globals;
  } catch {
    return [];
  }
});

// ─── IPC: Filesystem — lazy directory listing for project file/doc trees ────
// (todo_0317) Powers the Project Editor's file/doc trees. One level per call;
// the renderer expands on demand. Reflect-only (no writes). Hidden + heavy build
// dirs are skipped so trees stay readable.
ipcMain.handle('uai:fs:listDir', async (_event, dirPath: string, opts?: { dirsOnly?: boolean; showHidden?: boolean }) => {
  const EXCLUDE = new Set(['.git', 'node_modules', '.vite', 'out', '__pycache__', '.DS_Store', '.cache', '.pytest_cache']);
  try {
    if (!dirPath || typeof dirPath !== 'string') return [];
    // Expand a leading `~`/`~/` to the home dir so callers (e.g. the @-path
    // autocomplete) can pass home-relative paths.
    let resolvedDir = dirPath;
    if (resolvedDir === '~' || resolvedDir.startsWith('~/')) {
      resolvedDir = path.join(require('node:os').homedir(), resolvedDir.slice(1));
    }
    const entries = fs.readdirSync(resolvedDir, { withFileTypes: true });
    const rows: Array<{ name: string; path: string; type: 'file' | 'directory'; size: number | null; modified: string | null }> = [];
    for (const e of entries) {
      if (EXCLUDE.has(e.name)) continue;
      if (!opts?.showHidden && e.name.startsWith('.')) continue;
      const isDir = e.isDirectory();
      if (opts?.dirsOnly && !isDir) continue;
      const full = path.join(resolvedDir, e.name);
      let size: number | null = null;
      let modified: string | null = null;
      try { const st = fs.statSync(full); size = isDir ? null : st.size; modified = st.mtime.toISOString(); } catch { /* unreadable entry */ }
      rows.push({ name: e.name, path: full, type: isDir ? 'directory' : 'file', size, modified });
    }
    rows.sort((a, b) => (a.type === b.type ? a.name.localeCompare(b.name) : a.type === 'directory' ? -1 : 1));
    return rows;
  } catch (err: any) {
    // ENOENT/ENOTDIR are EXPECTED for speculative listings (the @-path autocomplete
    // lists as-you-type; a partial or not-yet-real path just yields no rows). Don't
    // log those as errors — only genuinely unexpected failures (EACCES, EMFILE, …).
    if (err?.code !== 'ENOENT' && err?.code !== 'ENOTDIR') {
      console.error('[uai:fs:listDir] Failed:', err?.message);
    }
    return [];
  }
});

// Read a text file by absolute path — backs the in-app document/markdown viewer
// tab (News & Reports, and any other .md opened in a tab rather than externally).
// Capped so a runaway file can't blow up the renderer.
ipcMain.handle('uai:fs:readFile', async (_event, filePath: string): Promise<{ ok: boolean; content?: string; truncated?: boolean; error?: string }> => {
  const MAX_BYTES = 5 * 1024 * 1024;   // 5 MB
  try {
    if (!filePath || typeof filePath !== 'string') return { ok: false, error: 'no path' };
    let resolved = filePath.trim();
    if (resolved === '~' || resolved.startsWith('~/')) {
      resolved = path.join(require('node:os').homedir(), resolved.slice(1));
    }
    // Resolve $AI_ROOT / ${AI_ROOT} and AI_ROOT-relative paths (e.g. scheduled
    // job commands reference scripts as $AI_ROOT/ai_general/... or ai_general/...).
    resolved = resolved.replace(/^\$\{?AI_ROOT\}?\/?/, () => getAiRootMain() + '/');
    if (!path.isAbsolute(resolved)) {
      resolved = path.join(getAiRootMain(), resolved);
    }
    const st = fs.statSync(resolved);
    if (st.isDirectory()) return { ok: false, error: 'is a directory' };
    const truncated = st.size > MAX_BYTES;
    const fd = fs.openSync(resolved, 'r');
    try {
      const len = truncated ? MAX_BYTES : st.size;
      const buf = Buffer.alloc(len);
      fs.readSync(fd, buf, 0, len, 0);
      return { ok: true, content: buf.toString('utf8'), truncated };
    } finally { fs.closeSync(fd); }
  } catch (err: any) {
    console.error('[uai:fs:readFile] Failed:', err?.message);
    return { ok: false, error: err?.message || 'read failed' };
  }
});

// ─── IPC: Todo Manager ──────────────────────────────────────────────

// ─── IPC: Comms index — conversations/messages read CLI (comms_index.py) ────
// Wraps the Python JSON query CLI (SQLite-backed; Node has no sqlite binding) —
// same subprocess pattern as session_store/trait_mgr. Verbs: conversations |
// conversation <id> | view <inbox|sent|archive> <entity>. Returns [] on error/empty.
ipcMain.handle('uai:comms:index', async (_event, verb: string, args: string[] = []) => {
  const script = path.join(getAiRootMain(), 'ai_general/scripts/messages/comms_index.py');
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  const envPath = shellPath();
  try {
    const { stdout } = await execFileAsync('python3', [script, verb, ...(args || []), '--json'], {
      timeout: 15000,
      cwd: getAiRootMain(),
      env: { ...process.env, AI_ROOT: getAiRootMain(), PATH: envPath },
      maxBuffer: 8 * 1024 * 1024,
    });
    return stdout.trim() ? JSON.parse(stdout.trim()) : [];
  } catch (err: any) {
    console.error('[uai:comms:index] Failed:', err?.stderr || err?.message);
    return [];
  }
});

// ─── todo_mgr engine bridge ─────────────────────────────────────────────
// The authoritative todo reader/writer is todo_mgr.py (single source of truth
// for the on-disk model: nesting=parent/child, *.status/*.tag markers,
// assigned.yml, origin.yml, history.log). It needs common_utils on PYTHONPATH
// and TODO_ROOT pointing at the todos dir. We shell out with --json where the
// verb supports it (mirrors uai:tasks:list). See docs/designs/work_mgr.md.
// Engine bridge lives in ./todo-ops (shared with the todo.* Command Bus
// handlers) so the read (IPC) and write (command) paths can't drift.

ipcMain.handle('uai:todos:list', async (_e, includeFinalized?: boolean) => {
  // Full hierarchical contract straight from the engine's own serializer:
  // id, ref, rel_path, parent, children[], assigned[], owner, project, status,
  // tags[], flags[], title, summary. dirName (leaf basename) is added so the
  // pre-rebuild WorkMgrPane keeps working. includeFinalized adds Done/Cancelled (todo_0404).
  try {
    const parsed = JSON.parse(await runTodoMgr('json', includeFinalized ? ['--include-finalized'] : []));
    if (!Array.isArray(parsed)) return [];
    return parsed.map((t: any) => ({
      ...t,
      dirName: (t.rel_path ? String(t.rel_path).split('/').pop() : t.id) || t.id,
      name: t.id,
    }));
  } catch (err: any) {
    console.error('[uai:todos:list] todo_mgr json failed:', err.message);
    return [];
  }
});

// Read notes.md by todo id (resolves nested paths, unlike the old dirName join).
ipcMain.handle('uai:todos:read', async (_event, id: string) => {
  const dir = resolveTodoDir(id);
  if (!dir) return '';
  try {
    return fs.readFileSync(path.join(dir, 'notes.md'), 'utf-8');
  } catch {
    return '';
  }
});

// NOTE: todo MUTATIONS (status/move/assign/unassign/tag/create/writeNotes) now
// route through the Command Bus (todo.* handlers in command-handlers.ts) so the
// bus is the single, logged, hookable mutation path. The IPC surface below is
// READ-only (queries don't need the bus). runTodoMgr stays imported for the
// list/json read.

// Open the todo in the OS — reveal its directory in Finder.
ipcMain.handle('uai:todos:open', async (_e, id: string) => {
  const dir = resolveTodoDir(id);
  if (!dir) return { ok: false, error: 'todo not found' };
  shell.showItemInFolder(dir);
  return { ok: true };
});

// List attachments under <id>/data/.
ipcMain.handle('uai:todos:data', async (_e, id: string) => {
  const dir = resolveTodoDir(id);
  if (!dir) return [];
  const dataDir = path.join(dir, 'data');
  try {
    return fs.readdirSync(dataDir, { withFileTypes: true })
      .filter(e => e.isFile())
      .map(e => {
        const p = path.join(dataDir, e.name);
        let size = 0; try { size = fs.statSync(p).size; } catch { /* ignore */ }
        return { name: e.name, path: p, size };
      });
  } catch { return []; }
});

// Open one attachment file.
ipcMain.handle('uai:todos:openData', async (_e, id: string, fileName: string) => {
  if (fileName.includes('..') || fileName.includes('/') || fileName.includes('\\')) {
    return { ok: false, error: 'invalid file' };
  }
  const dir = resolveTodoDir(id);
  if (!dir) return { ok: false, error: 'todo not found' };
  shell.openPath(path.join(dir, 'data', fileName));
  return { ok: true };
});

// Merged provenance: origin.yml fields + history.log timeline.
// Files modified for a set of todos — git ground truth via the `Todo: <id>` commit
// trailer (todo_0417). Union of `git log --grep=Todo:…<id> --name-only` across ai_general.
ipcMain.handle('uai:git:filesForTodos', async (_e, todoIds: string[]) => {
  const { execFile } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(execFile);
  const repo = path.resolve(todosRoot(), '..', '..'); // ai_general
  const files = new Set<string>();
  for (const raw of (Array.isArray(todoIds) ? todoIds : [])) {
    const m = String(raw).match(/todo_\d+/);
    if (!m) continue;
    try {
      const { stdout } = await execFileAsync('git', ['-C', repo, 'log', '--all', `--grep=Todo:.*${m[0]}`, '--name-only', '--pretty=format:'], { timeout: 8000, maxBuffer: 8 * 1024 * 1024 });
      String(stdout).split('\n').map(s => s.trim()).filter(Boolean).forEach(f => files.add(f));
    } catch { /* no commits for this todo */ }
  }
  // Exclude todo-internal bookkeeping (status/tag/notes/origin/assigned + data/) —
  // the Files view is the CODE files a todo changed, not the todo's own folder.
  return [...files].filter(f => !f.startsWith('work/todos/')).sort();
});

// Notes this worker is tagged on (todo_0419): scan work/notes/*/meta.yml, match the
// worker's name/id against the note's recipients (or title). Returns {id, title, status}.
ipcMain.handle('uai:notes:forWorker', async (_e, names: string[]) => {
  const notesDir = path.resolve(todosRoot(), '..', 'notes'); // ai_general/work/notes
  const wanted = (Array.isArray(names) ? names : []).map(n => String(n).toLowerCase().trim()).filter(Boolean);
  if (!wanted.length) return [];
  const out: Array<{ id: string; title: string; status: string }> = [];
  try {
    for (const d of fs.readdirSync(notesDir)) {
      const meta = path.join(notesDir, d, 'meta.yml');
      let raw: string;
      try { raw = fs.readFileSync(meta, 'utf-8'); } catch { continue; }
      // recipients block: the `- ` lines under `recipients:`
      const recipBlock = (raw.match(/recipients:\s*\n((?:\s*-\s*.+\n?)*)/) || [])[1] || '';
      const recips = [...recipBlock.matchAll(/-\s*(.+)/g)].map(m => m[1].trim().toLowerCase());
      const title = (raw.match(/^title:\s*(.+)$/m) || [])[1]?.trim() || d;
      const status = (raw.match(/^status:\s*(.+)$/m) || [])[1]?.trim() || 'open';
      const id = (raw.match(/^id:\s*(.+)$/m) || [])[1]?.trim() || d;
      // Workers are tagged via recipients, the title, or an @mention in the content.
      let content = '';
      try { content = fs.readFileSync(path.join(notesDir, d, 'content.md'), 'utf-8'); } catch { /* no content */ }
      const hay = (recips.join(' ') + ' ' + title + ' ' + content).toLowerCase();
      if (wanted.some(w => hay.includes(w))) out.push({ id, title, status });
    }
  } catch { /* no notes dir */ }
  return out;
});

ipcMain.handle('uai:todos:provenance', async (_e, id: string) => {
  const dir = resolveTodoDir(id);
  if (!dir) return { origin: {}, history: [] };
  const origin: Record<string, string> = {};
  try {
    const raw = fs.readFileSync(path.join(dir, 'origin.yml'), 'utf-8');
    for (const line of raw.split('\n')) {
      const m = line.match(/^([a-z_]+):\s*(.*)$/i);
      if (m) origin[m[1]] = m[2].replace(/^['"]|['"]$/g, '').trim();
    }
  } catch { /* no origin */ }
  const history: Array<{ ts: string; status: string; session: string; note: string }> = [];
  try {
    const raw = fs.readFileSync(path.join(dir, 'history.log'), 'utf-8');
    for (const line of raw.split('\n')) {
      if (!line.trim()) continue;
      const [ts, status, session, ...rest] = line.split('|').map(s => s.trim());
      history.push({ ts, status, session, note: rest.join(' | ') });
    }
  } catch { /* no history */ }
  return { origin, history };
});

// (todo.writeNotes is a Command Bus handler now — see command-handlers.ts.)

// Recursive file listing under a todo dir — backs the detail file explorer.
// Returns relative paths (posix) + size; dirs are implied by the path segments.
ipcMain.handle('uai:todos:files', async (_e, id: string) => {
  const dir = resolveTodoDir(id);
  if (!dir) return [];
  const out: Array<{ rel: string; size: number; isDir: boolean }> = [];
  const walk = (abs: string, rel: string) => {
    let entries: fs.Dirent[];
    try { entries = fs.readdirSync(abs, { withFileTypes: true }); } catch { return; }
    for (const e of entries) {
      const childRel = rel ? `${rel}/${e.name}` : e.name;
      const childAbs = path.join(abs, e.name);
      if (e.isDirectory()) {
        out.push({ rel: childRel, size: 0, isDir: true });
        walk(childAbs, childRel);
      } else if (e.isFile()) {
        let size = 0; try { size = fs.statSync(childAbs).size; } catch { /* ignore */ }
        out.push({ rel: childRel, size, isDir: false });
      }
    }
  };
  walk(dir, '');
  return out;
});

// Read one file's text content (scoped to the todo dir, traversal-guarded, capped).
ipcMain.handle('uai:todos:readFile', async (_e, id: string, rel: string) => {
  if (!rel || rel.includes('..') || rel.startsWith('/') || rel.includes('\\')) {
    return { ok: false, error: 'invalid path' };
  }
  const dir = resolveTodoDir(id);
  if (!dir) return { ok: false, error: 'todo not found' };
  const abs = path.join(dir, rel);
  if (!abs.startsWith(dir + path.sep)) return { ok: false, error: 'out of bounds' };
  try {
    const size = fs.statSync(abs).size;
    if (size > 512 * 1024) return { ok: true, truncated: true, content: fs.readFileSync(abs, 'utf-8').slice(0, 512 * 1024) };
    return { ok: true, content: fs.readFileSync(abs, 'utf-8') };
  } catch (err: any) {
    return { ok: false, error: err.message };
  }
});

// ─── IPC: Task Manager ─────────────────────────────────────────────

ipcMain.handle('uai:tasks:list', async (_event, opts?: { platform?: string; status?: string }) => {
  const taskCoordCli = path.join(getAiRootMain(), 'ai_general', 'scripts', 'tasks', 'task_coord_cli.py');
  const { execFile: ef } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(ef);
  const envPath = shellPath();

  const args = ['list_tasks'];
  if (opts?.platform) { args.push('--platform', opts.platform); }
  if (opts?.status) { args.push('--status', opts.status); }

  try {
    const { stdout } = await execFileAsync('python3', [taskCoordCli, ...args], {
      timeout: 15000,
      cwd: getAiRootMain(),
      env: { ...process.env, AI_ROOT: getAiRootMain(), PATH: envPath },
    });
    const parsed = JSON.parse(stdout.trim());
    return Array.isArray(parsed) ? parsed : [];
  } catch (err: any) {
    console.warn('[uai:tasks:list] task_coord_cli.py failed:', err.message);
    // Fallback: return empty array if script fails
    return [];
  }
});

// ─── IPC: Assigned Tasks ────────────────────────────────────────────────

import { loadStore as loadAssignedStore, saveStore as saveAssignedStore, runFullScan, updateTask as updateAssignedTask } from './assigned-tasks';
import type { ScanEngine } from './assigned-tasks';
import { aiRootMain as getAiRootMain, shellPath, buildChildEnv } from './paths';
import { transcriptCache } from './transcript-cache-service';

let assignedTasksScanAbort: AbortController | null = null;

ipcMain.handle('uai:assignedTasks:load', async () => {
  try {
    return await loadAssignedStore(getAiRootMain());
  } catch (err: any) {
    console.warn('[uai:assignedTasks:load] failed:', err.message);
    return { version: 1, lastScanAt: null, tasks: [] };
  }
});

ipcMain.handle('uai:assignedTasks:scan', async (_event, opts: { engine: string; daysBack: number }) => {
  const engine = (opts.engine === 'claude' ? 'claude' : 'lllm') as ScanEngine;
  const daysBack = opts.daysBack || 5;

  // Cancel any running scan
  if (assignedTasksScanAbort) {
    assignedTasksScanAbort.abort();
  }
  assignedTasksScanAbort = new AbortController();

  try {
    const result = await runFullScan(
      getAiRootMain(),
      engine,
      daysBack,
      (progress) => {
        const mw = BrowserWindow.getAllWindows()[0];
        if (mw && !mw.isDestroyed()) {
          mw.webContents.send('uai:assignedTasks:progress', progress);
        }
      },
      assignedTasksScanAbort.signal,
    );
    // Notify renderer that scan completed (in case component remounted mid-scan)
    const mw = BrowserWindow.getAllWindows()[0];
    if (mw && !mw.isDestroyed()) {
      mw.webContents.send('uai:assignedTasks:scanComplete', result);
    }
    return result;
  } catch (err: any) {
    if (err.name === 'AbortError') {
      return await loadAssignedStore(getAiRootMain());
    }
    console.warn('[uai:assignedTasks:scan] failed:', err.message);
    throw err;
  } finally {
    assignedTasksScanAbort = null;
  }
});

ipcMain.handle('uai:assignedTasks:cancelScan', async () => {
  if (assignedTasksScanAbort) {
    assignedTasksScanAbort.abort();
    assignedTasksScanAbort = null;
  }
  return { ok: true };
});

ipcMain.handle('uai:assignedTasks:isScanning', async () => {
  return assignedTasksScanAbort !== null;
});

ipcMain.handle('uai:assignedTasks:updateTask', async (_event, taskId: string, patch: { status?: string; dismissed?: boolean; userNotes?: string }) => {
  try {
    return await updateAssignedTask(getAiRootMain(), taskId, patch);
  } catch (err: any) {
    console.warn('[uai:assignedTasks:updateTask] failed:', err.message);
    throw err;
  }
});

// ─── IPC: MCP Server Discovery ──────────────────────────────────────────

ipcMain.handle('uai:mcp:list', async () => {
  const discoverScript = path.join(getAiRootMain(), 'ai_general/scripts/setup/discover_mcp_tools.py');
  const pythonCmd = 'python3';   // resolved via the healthy PATH from buildChildEnv
  const { execFile: ef } = require('node:child_process');
  const { promisify } = require('node:util');
  const execFileAsync = promisify(ef);

  try {
    const { stdout } = await execFileAsync(pythonCmd, [discoverScript], {
      timeout: 60000,
      env: buildChildEnv({ AI_ROOT: getAiRootMain() }),
    });
    return JSON.parse(stdout.trim());
  } catch (err) {
    console.warn('[mcp:list] discover_mcp_tools.py failed:', err);
    return [];
  }
});

// ─── IPC: MCP Config & Server Files ─────────────────────────────────────────

ipcMain.handle('uai:mcp:readConfigFile', async (_event, serverName: string) => {
  const os = require('node:os');
  const homedir = os.homedir();

  // Config file candidates in priority order
  const candidates: Array<{ filePath: string; shortPath: string; parser: 'json' | 'toml' }> = [
    { filePath: path.join(homedir, '.claude', 'settings.json'), shortPath: '~/.claude/settings.json', parser: 'json' },
    { filePath: path.join(homedir, '.codex', 'config.toml'), shortPath: '~/.codex/config.toml', parser: 'toml' },
    { filePath: path.join(homedir, '.codex', 'hooks.json'), shortPath: '~/.codex/hooks.json', parser: 'json' },
    { filePath: path.join(homedir, '.gemini', 'settings.json'), shortPath: '~/.gemini/settings.json', parser: 'json' },
  ];

  // Also check for project-level .mcp.json
  const aiRoot = getAiRootMain();
  const projectMcp = path.join(aiRoot, '.mcp.json');
  if (fs.existsSync(projectMcp)) {
    candidates.unshift({ filePath: projectMcp, shortPath: '.mcp.json (project)', parser: 'json' });
  }

  // Also check the central MCP.json
  const centralMcp = path.join(aiRoot, 'ai_general', 'data', 'MCP.json');
  if (fs.existsSync(centralMcp)) {
    candidates.unshift({ filePath: centralMcp, shortPath: 'ai_general/data/MCP.json', parser: 'json' });
  }

  for (const candidate of candidates) {
    try {
      if (!fs.existsSync(candidate.filePath)) continue;
      const raw = fs.readFileSync(candidate.filePath, 'utf-8');

      if (candidate.parser === 'json') {
        const parsed = JSON.parse(raw);
        // Look for the server in mcpServers, servers, or nested structures
        const mcpServers = parsed.mcpServers || parsed.servers || parsed;
        if (mcpServers && typeof mcpServers === 'object' && mcpServers[serverName]) {
          return {
            filePath: candidate.filePath,
            shortPath: candidate.shortPath,
            content: JSON.stringify(mcpServers[serverName], null, 2),
          };
        }
      } else if (candidate.parser === 'toml') {
        // Simple TOML section extraction: find [mcp.servers.NAME] or [servers.NAME]
        const sectionRegex = new RegExp(`^\\[(?:mcp\\.)?servers\\.${serverName.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}\\]`, 'm');
        const match = raw.match(sectionRegex);
        if (match && match.index !== undefined) {
          // Extract until next section header
          const start = match.index;
          const rest = raw.slice(start + match[0].length);
          const nextSection = rest.search(/^\[/m);
          const section = match[0] + (nextSection >= 0 ? rest.slice(0, nextSection) : rest);
          return {
            filePath: candidate.filePath,
            shortPath: candidate.shortPath,
            content: section.trim(),
          };
        }
      }
    } catch {
      // Skip unparseable files
    }
  }

  return null;
});

ipcMain.handle('uai:mcp:listServerFiles', async (_event, serverName: string) => {
  const aiRoot = getAiRootMain();
  const mcpJsonPath = path.join(aiRoot, 'ai_general', 'data', 'MCP.json');

  try {
    if (!fs.existsSync(mcpJsonPath)) return [];
    const mcpConfig = JSON.parse(fs.readFileSync(mcpJsonPath, 'utf-8'));
    const serverCfg = mcpConfig.servers?.[serverName];
    if (!serverCfg) return [];

    // Determine the script directory from args_relative or args
    let scriptDir: string | null = null;
    const argsRelative = serverCfg.args_relative || [];
    const args = serverCfg.args || [];
    const candidates = [...argsRelative.map((a: string) => path.join(aiRoot, a)), ...args];

    for (const arg of candidates) {
      const resolved = path.resolve(arg);
      if (fs.existsSync(resolved)) {
        scriptDir = path.dirname(resolved);
        break;
      }
    }

    if (!scriptDir) return [];

    // Validate path is within ai_root or home
    const os = require('node:os');
    if (!scriptDir.startsWith(aiRoot) && !scriptDir.startsWith(os.homedir())) return [];

    const entries = fs.readdirSync(scriptDir, { withFileTypes: true });
    const files: Array<{ name: string; size: number; path: string }> = [];
    for (const entry of entries) {
      if (!entry.isFile()) continue;
      if (entry.name.startsWith('.')) continue;
      const filePath = path.join(scriptDir, entry.name);
      try {
        const stat = fs.statSync(filePath);
        files.push({ name: entry.name, size: stat.size, path: filePath });
      } catch { /* skip */ }
    }
    return files.sort((a, b) => a.name.localeCompare(b.name));
  } catch (err) {
    console.warn('[mcp:listServerFiles] failed:', err);
    return [];
  }
});

ipcMain.handle('uai:mcp:readServerFile', async (_event, filePath: string) => {
  try {
    const resolved = path.resolve(filePath);
    const aiRoot = getAiRootMain();
    const os = require('node:os');
    // Security: only allow reading files under ai_root or home
    if (!resolved.startsWith(aiRoot) && !resolved.startsWith(os.homedir())) {
      return '(path not allowed)';
    }
    if (!fs.existsSync(resolved)) return '(file not found)';
    const content = fs.readFileSync(resolved, 'utf-8');
    // Return first 100 lines
    const lines = content.split('\n');
    if (lines.length > 100) {
      return lines.slice(0, 100).join('\n') + `\n\n... (${lines.length - 100} more lines)`;
    }
    return content;
  } catch (err: any) {
    return `(error reading file: ${err.message})`;
  }
});

// ─── IPC: Command Log (1D) ───────────────────────────────────────────────

ipcMain.handle('uai:commandLog', async () => {
  return commandBus.getLog();
});

// ─── IPC: Transcript ───────���──────────────────────────────────────────────

ipcMain.handle('transcript:read', async (_event, zellijSession: string, cliSessionId: string | undefined, format: string) => {
  const { execFile: ef } = require('node:child_process');
  const aiRootMain = getAiRootMain();
  const readJsonlPath = path.join(aiRootMain, 'ai_general/scripts/jsonl/read_jsonl.py');
  const envPath = shellPath();

  const uuid = cliSessionId;
  if (!uuid) {
    return { ok: false, error: 'No CLI UUID available for transcript' };
  }

  const findResult: string = await new Promise<string>((resolve, reject) => {
    ef('python3', [readJsonlPath, 'find', uuid], {
      maxBuffer: 1024 * 1024,
      timeout: 10000,
      env: { ...process.env, PATH: envPath, AI_ROOT: aiRootMain },
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

  const outputFormat = format || 'structured';
  return new Promise((resolve) => {
    ef('python3', [readJsonlPath, 'read-file', findResult, '--format', outputFormat], {
      // Long-lived sessions build huge transcripts — e.g. Git-Guardian's Codex
      // rollout is ~59MB raw / ~35MB structured, well over the old 20MB cap
      // ("stdout maxBuffer length exceeded"). 256MB clears the largest real
      // transcripts (~109MB raw). If a transcript ever exceeds this, the viewer
      // should switch to interval/turn-ranged loading rather than the whole file.
      maxBuffer: 256 * 1024 * 1024,
      timeout: 30000,
      env: { ...process.env, PATH: envPath, AI_ROOT: aiRootMain },
    }, (error: any, stdout: string, stderr: string) => {
      if (error) {
        resolve({ ok: false, error: stderr || error.message });
        return;
      }
      try {
        const parsed = JSON.parse(stdout);
        resolve({ ok: true, days: parsed, uuid, format: outputFormat, path: findResult });
      } catch {
        resolve({ ok: false, error: 'Invalid JSON from read_jsonl.py' });
      }
    });
  });
});

// Cheap transcript change-check: find the session file and return size + mtime.
// The overlay stats before reading and skips the full parse when unchanged, so a
// quiet 10s tick costs a find + stat instead of re-parsing the whole JSONL.
ipcMain.handle('transcript:stat', async (_event, cliSessionId: string | undefined) => {
  const { execFile: ef } = require('node:child_process');
  const aiRootMain = getAiRootMain();
  const readJsonlPath = path.join(aiRootMain, 'ai_general/scripts/jsonl/read_jsonl.py');
  const envPath = shellPath();
  const uuid = cliSessionId;
  if (!uuid) return { ok: false, error: 'No CLI UUID available for transcript' };

  const findResult: string = await new Promise<string>((resolve, reject) => {
    ef('python3', [readJsonlPath, 'find', uuid], {
      maxBuffer: 1024 * 1024, timeout: 10000,
      env: { ...process.env, PATH: envPath, AI_ROOT: aiRootMain },
    }, (error: any, stdout: string) => {
      if (error) { reject(new Error(`find failed: ${error.message}`)); return; }
      resolve(stdout.trim());
    });
  }).catch(() => '');
  if (!findResult) return { ok: false, error: `Session file not found for UUID ${uuid}` };

  try {
    const st = fs.statSync(findResult);
    return { ok: true, size: st.size, mtimeMs: st.mtimeMs, path: findResult };
  } catch (err: unknown) {
    return { ok: false, error: err instanceof Error ? err.message : String(err) };
  }
});

// ─── IPC: Cached transcript (main-process pool + file-watcher; DESIGN.md #4) ──
// Persistent, cross-tab transcript cache: get() serves a warm pooled copy or cold-
// loads, keeping the last N viewed sessions warm; each pooled session's watcher pushes
// 'transcript:updated' on a real file change, so the overlay can drop its 10s poll.
transcriptCache.onUpdate = (ref: string) => {
  if (mainWindow && !mainWindow.isDestroyed()) {
    mainWindow.webContents.send('transcript:updated', ref);
  }
};
ipcMain.handle('transcript:getCached', async (_event, ref: string | undefined) => {
  return transcriptCache.get(ref || '');
});

// ─── IPC: Scrollback Capture ────────────────────────────────────────────────

ipcMain.handle('terminal:captureScrollback', async (_event, params: { sessionName: string; lines?: number }) => {
  const { execFile: ef } = require('node:child_process');
  const { sessionName, lines = 50000 } = params;
  if (!sessionName || typeof sessionName !== 'string' || sessionName.length > 200) {
    return { ok: false, error: 'Invalid session name' };
  }

  const aiRootMain = getAiRootMain();
  const sessionOpsPath = path.join(aiRootMain, 'ai_general/scripts/session_mgmt/session_ops.py');
  const envPath = shellPath();

  try {
    const text: string = await new Promise((resolve, reject) => {
      const captureLines = Math.max(1, Math.min(Number(lines) || 50000, 50000));
      ef('python3', [
        sessionOpsPath,
        'read-terminal',
        sessionName,
        '--lines',
        String(captureLines),
        '--styled',
      ], {
        maxBuffer: 20 * 1024 * 1024,
        timeout: 10000,
        env: { ...process.env, PATH: envPath, AI_ROOT: aiRootMain, AI_TMUX_SERVER: '' },
      }, (error: any, stdout: string) => {
        if (error) reject(error);
        else resolve(stdout);
      });
    });
    if (text && text.trim().length > 0) {
      return { ok: true, text };
    }
  } catch { /* fall through */ }
  return { ok: false, error: 'Failed to capture scrollback via substrate' };
});

// ── Single-session prompt-area check ────────────────────────────────────
// Uses the same get_prompt_area_texts.py backend as the bulk getPromptAreas,
// but for one tracking_id — for targeted, event-driven scans (on type / submit
// / tab-leave). Returns true if that session's prompt area holds unsent text.
ipcMain.handle('uai:prompts:hasPromptText', async (_event, trackingId: string) => {
  if (!trackingId || typeof trackingId !== 'string' || trackingId.length > 200) return false;
  const { execFile: ef } = require('node:child_process') as typeof import('node:child_process');
  const { homedir } = require('node:os') as typeof import('node:os');
  const script = path.join(homedir(), 'bin', 'ai', 'prompting', 'get_prompt_area_texts.py');
  const envPath = shellPath();
  try {
    const stdout: string = await new Promise((resolve, reject) => {
      // default (no --include-empty) returns only occupied prompt areas
      ef('python3', [script, trackingId], {
        timeout: 8000, maxBuffer: 1024 * 1024,
        env: { ...process.env, PATH: envPath, AI_ROOT: getAiRootMain() },
      }, (error: any, out: string) => { if (error) reject(error); else resolve(out); });
    });
    const arr = JSON.parse(stdout.trim());
    return Array.isArray(arr) && arr.some((e: any) => (e.prompt_text || '').trim().length > 0);
  } catch {
    return false;
  }
});

// ─── IPC: Prompt History ──────────────────────────────────────────────────

ipcMain.handle('transcript:history', async (_event, cliSessionId: string) => {
  const { execFile: ef } = require('node:child_process');
  const aiRootMain = getAiRootMain();
  const readJsonlPath = path.join(aiRootMain, 'ai_general/scripts/jsonl/read_jsonl.py');
  const envPath = shellPath();

  if (!cliSessionId) return { ok: false, error: 'No CLI UUID', messages: [] };

  const findResult: string = await new Promise<string>((resolve, reject) => {
    ef('python3', [readJsonlPath, 'find', cliSessionId], {
      maxBuffer: 1024 * 1024, timeout: 10000,
      env: { ...process.env, PATH: envPath, AI_ROOT: aiRootMain },
    }, (error: any, stdout: string) => {
      if (error) { reject(error); return; }
      resolve(stdout.trim());
    });
  }).catch(() => '');

  if (!findResult) return { ok: false, error: 'Session file not found', messages: [] };

  return new Promise((resolve) => {
    ef('python3', [readJsonlPath, 'read-file', findResult, '--format', 'json', '--type', 'user,response'], {
      maxBuffer: 20 * 1024 * 1024, timeout: 30000,
      env: { ...process.env, PATH: envPath, AI_ROOT: aiRootMain },
    }, (error: any, stdout: string) => {
      if (error) { resolve({ ok: false, error: error.message, messages: [] }); return; }
      try {
        const parsed = JSON.parse(stdout);
        const messages = Array.isArray(parsed) ? parsed : (parsed.messages || []);
        resolve({ ok: true, messages });
      } catch {
        resolve({ ok: false, error: 'Invalid JSON from read_jsonl.py', messages: [] });
      }
    });
  });
});

// ─── IPC: News & Reports ──────────────────────────────────────────────────

ipcMain.handle('uai:news:list', async () => {
  const aiRoot = getAiRootMain();
  const newsDir = path.join(aiRoot, 'ai_general', 'docs', 'news');
  const reportsDir = path.join(aiRoot, 'ai_general', 'research_and_reports');
  const newsAgentState = path.join(aiRoot, 'ai_general', 'data', 'news_agent', 'state.yml');
  const items: Array<{ type: 'news' | 'report'; name: string; path: string; size: number; modified: string; kind?: string; relPath?: string; isDir?: boolean }> = [];

  // News articles from docs/news/ — recurse so the archived weekly_<date>/ and
  // monthly_<YYYYMM>/ folders and their nested dailies appear as a tree (mirrors
  // walkReports). A weekly_/monthly_ DIR is a folder; only FILES carry a `kind`
  // (the weekly_<date>.html summary stays 'weekly').
  const walkNews = (dir: string, depth: number) => {
    if (depth > 4) return;
    let entries: fs.Dirent[];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue;
      const filePath = path.join(dir, entry.name);
      try {
        const stat = fs.statSync(filePath);
        const isDir = entry.isDirectory();
        const kind = isDir ? undefined : (entry.name.startsWith('weekly_') ? 'weekly' : 'daily');
        items.push({
          type: 'news',
          name: entry.name,
          path: filePath,
          relPath: path.relative(newsDir, filePath),
          isDir,
          size: isDir ? 0 : stat.size,
          modified: stat.mtime.toISOString(),
          kind,
        });
        if (isDir) walkNews(filePath, depth + 1);
      } catch { /* skip */ }
    }
  };
  walkNews(newsDir, 0);

  // Research & reports — recurse to reflect the folder hierarchy. Each item
  // carries relPath (relative to reportsDir) + isDir so the renderer can build
  // the tree; depth-bounded to stay cheap.
  const walkReports = (dir: string, depth: number) => {
    if (depth > 4) return;
    let entries: fs.Dirent[];
    try { entries = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const entry of entries) {
      if (entry.name.startsWith('.')) continue;
      const filePath = path.join(dir, entry.name);
      try {
        const stat = fs.statSync(filePath);
        const isDir = entry.isDirectory();
        items.push({
          type: 'report',
          name: entry.name.replace(/[-_]/g, ' ').replace(/\b\w/g, (c: string) => c.toUpperCase()),
          path: filePath,
          relPath: path.relative(reportsDir, filePath),
          isDir,
          size: isDir ? 0 : stat.size,
          modified: stat.mtime.toISOString(),
        });
        if (isDir) walkReports(filePath, depth + 1);
      } catch { /* skip */ }
    }
  };
  walkReports(reportsDir, 0);

  // Sort: newest first
  items.sort((a, b) => b.modified.localeCompare(a.modified));
  return items;
});

// ─── News/Reports read-state (external data store) ──────────────────────────
// A small JSON file maps item path → read timestamp. Presence == read. This is
// the external source of truth for which news/reports the user has read.

function newsReadStatePath(): string {
  return path.join(getAiRootMain(), 'ai_general', 'data', 'news_read_state.json');
}

function loadNewsReadState(): Record<string, string> {
  try {
    const data = JSON.parse(fs.readFileSync(newsReadStatePath(), 'utf-8'));
    return (data && typeof data === 'object' && data.read && typeof data.read === 'object') ? data.read : {};
  } catch { return {}; }
}

ipcMain.handle('uai:news:readState', async (): Promise<string[]> => {
  return Object.keys(loadNewsReadState());
});

ipcMain.handle('uai:news:mark', async (_event, paths: string[], read: boolean): Promise<{ ok: boolean; error?: string }> => {
  try {
    const read_map = loadNewsReadState();
    const now = new Date().toISOString();
    for (const p of (paths || [])) {
      if (read) read_map[p] = now; else delete read_map[p];
    }
    const file = newsReadStatePath();
    fs.mkdirSync(path.dirname(file), { recursive: true });
    fs.writeFileSync(file, JSON.stringify({ read: read_map }, null, 2));
    return { ok: true };
  } catch (e: any) {
    return { ok: false, error: e?.message || 'write failed' };
  }
});

// ─── IPC: File Tail Service ───────────────────────────────────────────────

const tailSessions = new Map<string, { watcher: fs.FSWatcher | null; offset: number; filePath: string }>();

ipcMain.handle('log:tail:start', async (_event, tailId: string, filePath: string) => {
  // Read initial content
  let lines: string[] = [];
  let offset = 0;
  try {
    const content = fs.readFileSync(filePath, 'utf-8');
    offset = Buffer.byteLength(content, 'utf-8');
    lines = content.split('\n').filter(l => l.trim()).slice(-500); // last 500 lines
  } catch (err: any) {
    if (err.code !== 'ENOENT') return { ok: false, error: err.message, lines: [] };
    // File doesn't exist yet — that's ok, we'll watch for it
  }

  // Set up watcher
  let watcher: fs.FSWatcher | null = null;
  let debounceTimer: ReturnType<typeof setTimeout> | null = null;

  const sendNewLines = () => {
    try {
      const stat = fs.statSync(filePath);
      if (stat.size <= offset) return; // no new data
      const fd = fs.openSync(filePath, 'r');
      const buf = Buffer.alloc(stat.size - offset);
      fs.readSync(fd, buf, 0, buf.length, offset);
      fs.closeSync(fd);
      offset = stat.size;
      const newLines = buf.toString('utf-8').split('\n').filter(l => l.trim());
      if (newLines.length > 0 && mainWindow) {
        mainWindow.webContents.send('log:tail:data', tailId, newLines);
      }
    } catch { /* file may have been truncated or deleted */ }
  };

  try {
    // Watch the directory (more reliable than watching the file directly for new files)
    const dir = path.dirname(filePath);
    const basename = path.basename(filePath);
    watcher = fs.watch(dir, (eventType, filename) => {
      if (filename !== basename) return;
      if (debounceTimer) clearTimeout(debounceTimer);
      debounceTimer = setTimeout(sendNewLines, 200);
    });
  } catch { /* directory doesn't exist — no watcher */ }

  const session = { watcher, offset, filePath };
  tailSessions.set(tailId, session);

  return { ok: true, lines };
});

ipcMain.handle('log:tail:stop', async (_event, tailId: string) => {
  const session = tailSessions.get(tailId);
  if (session?.watcher) session.watcher.close();
  tailSessions.delete(tailId);
  return { ok: true };
});

// ─── IPC: Prompt Areas ────────────────────────────────────────────────────

ipcMain.handle('uai:prompts:getPromptAreas', async () => {
  const { execFile: ef } = require('node:child_process') as typeof import('node:child_process');
  const { homedir } = require('node:os') as typeof import('node:os');
  const script = path.join(homedir(), 'bin', 'ai', 'prompting', 'get_prompt_area_texts.py');
  const envPath = shellPath();
  const timeoutMs = 45_000;
  try {
    const stdout: string = await new Promise((resolve, reject) => {
      ef('python3', [script, '--all-active'], {
        // --all-active serially captures tmux for every active session (~1s each),
        // so runtime scales with session count/load. 15s was too tight and the
        // process got SIGTERM'd under load, surfacing as a bogus "Command failed"
        // (todo_0674). 45s gives ample headroom for a large fleet.
        timeout: timeoutMs,
        maxBuffer: 4 * 1024 * 1024,
        env: { ...process.env, PATH: envPath, AI_ROOT: getAiRootMain() },
      }, (error: any, out: string) => {
        if (error) reject(error);
        else resolve(out);
      });
    });
    return JSON.parse(stdout.trim());
  } catch (err: any) {
    // Distinguish a timeout kill (killed + SIGTERM) from a real non-zero exit so
    // the log says WHY — a plain err.message just reads "Command failed" (0674).
    const timedOut = err?.killed && err?.signal === 'SIGTERM';
    const why = timedOut
      ? `timed out after ${timeoutMs / 1000}s (${err.signal}) — likely too many active sessions to capture in time`
      : (err?.code != null ? `failed (${err.code}): ${err.message || 'no detail'}` : err?.message);
    console.warn('[uai:prompts:getPromptAreas] failed:', why);
    return [];
  }
});

// ─── IPC: Scheduled Tasks ─────────────────────────────────────────────────

const SCHED_TASKS_SCRIPT = path.join(getAiRootMain(), 'ai_general', 'scripts', 'scheduling', 'scheduled_task_mgr.py');

/** Validate group/job names: [a-z0-9_-], max 64 chars */
function isValidSchedName(name: string): boolean {
  return /^[a-z0-9_-]{1,64}$/.test(name);
}

/** Shell out to scheduled_task_mgr.py using execFile (no shell injection). */
function runSchedTaskMgr(args: string[], timeoutMs = 30000): Promise<{ ok: boolean; stdout: string; stderr: string }> {
  const { execFile: ef } = require('node:child_process') as typeof import('node:child_process');
  const envPath = shellPath();
  return new Promise((resolve) => {
    ef('python3', [SCHED_TASKS_SCRIPT, ...args], {
      timeout: timeoutMs,
      cwd: getAiRootMain(),
      env: { ...process.env, AI_ROOT: getAiRootMain(), PATH: envPath } as Record<string, string>,
      maxBuffer: 5 * 1024 * 1024,
    }, (err: any, stdout: string, stderr: string) => {
      if (err) {
        resolve({ ok: false, stdout: stdout || '', stderr: stderr || err.message || String(err) });
      } else {
        resolve({ ok: true, stdout: stdout || '', stderr: stderr || '' });
      }
    });
  });
}

// Scheduled task data is sourced exclusively through scheduled_task_mgr.py
// (the CLI is the single source of truth). listGroups/viewGroup parse the CLI's
// `list`/`view` text output; status comes from `status --json`.

ipcMain.handle('uai:scheduledTasks:listGroups', async () => {
  const result = await runSchedTaskMgr(['list', '--all']);
  if (!result.ok) return [];
  const groups: Array<{ name: string; description?: string; enabled: boolean; jobCount: number }> = [];
  for (const rawLine of result.stdout.split('\n')) {
    // Row format: "  1    chat_pipeline    yes    4    Daily chat history..."
    const m = rawLine.match(/^\s*\d+\s+(\S+)\s+(yes|no)\s+(\d+)\s+(.*)$/);
    if (!m) continue;
    groups.push({
      name: m[1],
      enabled: m[2] === 'yes',
      jobCount: parseInt(m[3], 10),
      description: m[4].trim() || undefined,
    });
  }
  return groups;
});

ipcMain.handle('uai:scheduledTasks:viewGroup', async (_event, group: string) => {
  if (!isValidSchedName(group)) return null;
  const result = await runSchedTaskMgr(['view', group]);
  if (!result.ok) return null;
  let name = group;
  let description: string | undefined;
  let enabled = true;
  const env: Record<string, string> = {};
  const jobs: Array<{ id: string; description: string; schedule: string; command: string; log?: string; background?: boolean }> = [];
  let section: 'head' | 'meta' | 'env' | 'jobs' = 'head';
  let current: (typeof jobs)[number] | null = null;

  for (const rawLine of result.stdout.split('\n')) {
    const line = rawLine.replace(/\r$/, '');
    const gm = line.match(/^\s*Group:\s+(.+)$/);
    if (gm) { name = gm[1].trim(); section = 'meta'; continue; }
    const dm = line.match(/^\s*Desc:\s+(.+)$/);
    if (dm && section !== 'jobs') { description = dm[1].trim(); continue; }
    const em = line.match(/^\s*Enabled:\s+(yes|no)\s*$/);
    if (em) { enabled = em[1] === 'yes'; continue; }
    if (/^\s*Env:\s*$/.test(line)) { section = 'env'; continue; }
    if (/^\s*#\s+ID\s+Schedule/.test(line)) { section = 'jobs'; continue; }

    if (section === 'env') {
      const kv = line.match(/^\s+(\w+)=(.+)$/);
      if (kv) { env[kv[1]] = kv[2].trim(); continue; }
    }

    if (section === 'jobs') {
      // Job row: "  1   fetch_metadata   0 4 * * *   Fetch chat registry metadata"
      const jh = line.match(/^\s*\d+\s+(\S+)\s+(.+?)\s{2,}(\S.*)$/);
      if (jh) {
        current = { id: jh[1], schedule: jh[2].trim(), description: jh[3].trim(), command: '' };
        jobs.push(current);
        continue;
      }
      if (current) {
        const cm = line.match(/^\s+cmd:\s+(.+)$/);
        if (cm) { current.command = cm[1].trim(); continue; }
        const lm = line.match(/^\s+log:\s+(.+)$/);
        if (lm) { current.log = lm[1].trim(); continue; }
        // "↳ <english>" continuation lines are ignored
      }
    }
  }
  return { name, description, enabled, env, jobs };
});

ipcMain.handle('uai:scheduledTasks:getStatus', async () => {
  const result = await runSchedTaskMgr(['status', '--json']);
  const empty = { groups: [] as any[], sync: { inSync: false, missing: [] as string[], extra: [] as string[] }, errors: [] as string[] };
  if (!result.ok) return { ...empty, errors: [result.stderr || 'status command failed'] };
  try {
    return JSON.parse(result.stdout.trim());
  } catch {
    return { ...empty, errors: ['Failed to parse status JSON'] };
  }
});

ipcMain.handle('uai:scheduledTasks:getLogTail', async (_event, group: string, jobId: string, lines?: number) => {
  if (!isValidSchedName(group) || !isValidSchedName(jobId)) return '';
  const result = await runSchedTaskMgr(['logs', group, jobId, '-n', String(lines || 50)]);
  if (!result.ok) return result.stderr || '';
  return result.stdout || '';
});

ipcMain.handle('uai:scheduledTasks:enableGroup', async (_event, group: string) => {
  if (!isValidSchedName(group)) return { ok: false, error: 'Invalid group name' };
  const result = await runSchedTaskMgr(['enable', group]);
  return { ok: result.ok, error: result.ok ? undefined : result.stderr };
});

ipcMain.handle('uai:scheduledTasks:disableGroup', async (_event, group: string) => {
  if (!isValidSchedName(group)) return { ok: false, error: 'Invalid group name' };
  const result = await runSchedTaskMgr(['disable', group]);
  return { ok: result.ok, error: result.ok ? undefined : result.stderr };
});

ipcMain.handle('uai:scheduledTasks:createGroup', async (_event, opts: {
  name: string; description?: string;
  firstJob: { id: string; schedule: string; command: string; description?: string; log?: string; background?: boolean };
}) => {
  if (!isValidSchedName(opts.name)) return { ok: false, error: 'Invalid group name' };
  const args = ['create', opts.name, '--job-id', opts.firstJob.id, '--schedule', opts.firstJob.schedule, '--command', opts.firstJob.command];
  if (opts.description) args.push('--description', opts.description);
  if (opts.firstJob.description) args.push('--job-description', opts.firstJob.description);
  if (opts.firstJob.log) args.push('--log', opts.firstJob.log);
  if (opts.firstJob.background) args.push('--background');
  const result = await runSchedTaskMgr(args);
  return { ok: result.ok, error: result.ok ? undefined : result.stderr };
});

ipcMain.handle('uai:scheduledTasks:addJob', async (_event, group: string, job: {
  id: string; schedule: string; command: string; description?: string; log?: string; background?: boolean;
}) => {
  if (!isValidSchedName(group) || !isValidSchedName(job.id)) return { ok: false, error: 'Invalid name' };
  const args = ['add', group, '--job-id', job.id, '--schedule', job.schedule, '--command', job.command];
  if (job.description) args.push('--description', job.description);
  if (job.log) args.push('--log', job.log);
  if (job.background) args.push('--background');
  const result = await runSchedTaskMgr(args);
  return { ok: result.ok, error: result.ok ? undefined : result.stderr };
});

ipcMain.handle('uai:scheduledTasks:editGroup', async (_event, group: string, patch: { description?: string; enabled?: boolean }) => {
  if (!isValidSchedName(group)) return { ok: false, error: 'Invalid group name' };
  const args = ['edit', group];
  if (patch.description !== undefined) args.push('--description', patch.description);
  if (patch.enabled !== undefined) args.push('--enabled', String(patch.enabled));
  const result = await runSchedTaskMgr(args);
  return { ok: result.ok, error: result.ok ? undefined : result.stderr };
});

ipcMain.handle('uai:scheduledTasks:editJob', async (_event, group: string, jobId: string, patch: {
  schedule?: string; command?: string; description?: string; log?: string; background?: boolean;
}) => {
  if (!isValidSchedName(group) || !isValidSchedName(jobId)) return { ok: false, error: 'Invalid name' };
  const args = ['edit', group, jobId];
  if (patch.schedule !== undefined) args.push('--schedule', patch.schedule);
  if (patch.command !== undefined) args.push('--command', patch.command);
  if (patch.description !== undefined) args.push('--description', patch.description);
  if (patch.log !== undefined) args.push('--log', patch.log);
  if (patch.background !== undefined) args.push('--background', String(patch.background));
  const result = await runSchedTaskMgr(args);
  return { ok: result.ok, error: result.ok ? undefined : result.stderr };
});

ipcMain.handle('uai:scheduledTasks:deleteGroup', async (_event, group: string) => {
  if (!isValidSchedName(group)) return { ok: false, error: 'Invalid group name' };
  const result = await runSchedTaskMgr(['delete', group, '--yes']);
  return { ok: result.ok, error: result.ok ? undefined : result.stderr };
});

ipcMain.handle('uai:scheduledTasks:deleteJob', async (_event, group: string, jobId: string) => {
  if (!isValidSchedName(group) || !isValidSchedName(jobId)) return { ok: false, error: 'Invalid name' };
  const result = await runSchedTaskMgr(['delete', group, jobId, '--yes']);
  return { ok: result.ok, error: result.ok ? undefined : result.stderr };
});

ipcMain.handle('uai:scheduledTasks:install', async () => {
  const result = await runSchedTaskMgr(['install']);
  return { ok: result.ok, error: result.ok ? undefined : result.stderr };
});

ipcMain.handle('uai:scheduledTasks:dryRun', async () => {
  const result = await runSchedTaskMgr(['install', '--dry-run']);
  return { ok: result.ok, preview: result.stdout, error: result.ok ? undefined : result.stderr };
});

// Drop-and-reinstall ONE group's launchd agents (todo_0440 #8) — Noctis's
// backend `reinstall` verb force-reloads only this group, not the whole fleet.
ipcMain.handle('uai:scheduledTasks:reinstall', async (_event, group: string) => {
  if (!isValidSchedName(group)) return { ok: false, error: 'Invalid group name' };
  const result = await runSchedTaskMgr(['reinstall', group]);
  return { ok: result.ok, error: result.ok ? undefined : result.stderr };
});

ipcMain.handle('uai:scheduledTasks:runJob', async (_event, group: string, jobId: string) => {
  if (!isValidSchedName(group) || !isValidSchedName(jobId)) return { ok: false, exitCode: -1, stdout: '', stderr: '', error: 'Invalid name' };
  const result = await runSchedTaskMgr(['run', group, jobId], 60000);
  const exitCode = result.ok ? 0 : 1;
  return { ok: result.ok, exitCode, stdout: result.stdout, stderr: result.stderr, error: result.ok ? undefined : result.stderr };
});

// ─── IPC: Clipboard ───────────────────────────────────────────────────────

ipcMain.handle('clipboard:write', (_event, text: string) => {
  clipboard.writeText(text);
  return { success: true };
});

ipcMain.handle('clipboard:read', () => {
  return clipboard.readText();
});

// ─── IPC: Native Dialogs ──────────────────────────────────────────────────

ipcMain.handle('uai:dialog:openDirectory', async (_event, defaultPath?: string) => {
  if (!mainWindow) return null;
  // NSOpenPanel silently fails to present when handed a relative or non-existent
  // defaultPath (e.g. the Git Viewer's default dir 'ai_general'). Resolve it to an
  // existing absolute directory, walking up to the nearest existing ancestor, and
  // fall back to ai_root if nothing resolves — so the panel ALWAYS opens.
  const resolveDefault = (p?: string): string => {
    const aiRoot = getAiRootMain();
    let cand = p && p.trim() ? p.trim() : aiRoot;
    if (cand === '~' || cand.startsWith('~/')) cand = path.join(require('node:os').homedir(), cand.slice(1));
    if (!path.isAbsolute(cand)) cand = path.join(aiRoot, cand);
    for (let cur = cand; ;) {
      try { if (fs.statSync(cur).isDirectory()) return cur; } catch { /* keep walking up */ }
      const parent = path.dirname(cur);
      if (parent === cur) return aiRoot;
      cur = parent;
    }
  };
  try {
    const result = await dialog.showOpenDialog(mainWindow, {
      properties: ['openDirectory'],
      defaultPath: resolveDefault(defaultPath),
      title: 'Select Directory',
    });
    if (result.canceled || result.filePaths.length === 0) return null;
    return result.filePaths[0];
  } catch (err: any) {
    console.error('[uai:dialog:openDirectory] Failed:', err?.message);
    return null;
  }
});

// Prompt Box attach: pick one or more files → return absolute paths so the Prompt Box
// can insert `@path` mentions (Claude Code reads the referenced file inline).
ipcMain.handle('uai:dialog:openFile', async (_event, defaultPath?: string) => {
  if (!mainWindow) return null;
  const result = await dialog.showOpenDialog(mainWindow, {
    properties: ['openFile', 'multiSelections'],
    defaultPath: defaultPath || require('node:os').homedir(),
    title: 'Attach file(s)',
  });
  if (result.canceled || result.filePaths.length === 0) return null;
  return result.filePaths;
});

// Prompt Box attach: if the OS clipboard holds an image (e.g. a screenshot), write it
// to a temp PNG and return the path so the Prompt Box can insert an `@path` mention.
ipcMain.handle('uai:clipboard:saveImage', async () => {
  const { clipboard } = require('electron');
  const img = clipboard.readImage();
  if (!img || img.isEmpty()) return null;
  const os = require('node:os'), fs = require('node:fs');
  const dir = path.join(os.tmpdir(), 'uai_pasted_images');
  if (!fs.existsSync(dir)) fs.mkdirSync(dir);
  const file = path.join(dir, `paste_${Date.now()}.png`);
  fs.writeFileSync(file, img.toPNG());
  return file;
});

// ─── IPC: Terminal ────────────────────────────────────────────────────────

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

// ─── IPC: Standalone Terminal (raw shell, no session) ────────────────────

ipcMain.handle('standalone-terminal:create', (_event, id: string, cols: number, rows: number, cwd?: string) => {
  if (!mainWindow) return { reattached: false };
  return createStandaloneTerminal(id, cols, rows, cwd, mainWindow);
});

ipcMain.on('standalone-terminal:input', (_event, id: string, data: string) => {
  writeStandaloneTerminal(id, data);
});

ipcMain.on('standalone-terminal:resize', (_event, id: string, cols: number, rows: number) => {
  resizeStandaloneTerminal(id, cols, rows);
});

ipcMain.handle('standalone-terminal:close', (_event, id: string) => {
  closeStandaloneTerminal(id);
});

// ─── IPC: Session Store Manager ──────────────────────────────────────────

ipcMain.handle('uai:sessionStore:list', async (_event, opts?: { text?: string; status?: string; platform?: string }) => {
  try {
    const args = ['list', '--json'];
    if (opts?.text) args.push('--text', opts.text);
    if (opts?.status) args.push('--status', opts.status);
    if (opts?.platform) args.push('--platform', opts.platform);
    const rows = await callSessionStore(args);
    return Array.isArray(rows) ? rows : [];
  } catch (err: any) {
    console.error('[sessionStore:list]', err.message);
    return [];
  }
});

ipcMain.handle('uai:sessionStore:update', async (_event, trackingId: string, fields: Record<string, string | null>) => {
  try {
    const setArgs: string[] = [];
    for (const [key, value] of Object.entries(fields)) {
      if (value === null) continue;
      setArgs.push('--set', `${key}=${value}`);
    }
    if (setArgs.length === 0) return { ok: true };
    await callSessionStore(['update', trackingId, ...setArgs]);
    return { ok: true };
  } catch (err: any) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('uai:sessionStore:history', async (_event, trackingId: string, opts?: { limit?: number }) => {
  try {
    const args = ['history', '--tracking-id', trackingId];
    if (opts?.limit) args.push('--limit', String(opts.limit));
    const result = await callSessionStore(args);
    return Array.isArray(result) ? result : [];
  } catch (err: any) {
    console.error('[sessionStore:history]', err.message);
    return [];
  }
});

ipcMain.handle('uai:sessionStore:stateList', async (_event, trackingId: string, _prefix?: string) => {
  try {
    const result = await callSessionMgr(['state_list', trackingId]);
    if (result && typeof result === 'object') return result;
    return {};
  } catch (err: any) {
    console.error('[sessionStore:stateList]', err.message);
    return {};
  }
});

ipcMain.handle('uai:sessionStore:stateSet', async (_event, trackingId: string, key: string, value: string) => {
  try {
    await callSessionMgr(['state_set', trackingId, key, value]);
    return { ok: true };
  } catch (err: any) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('uai:sessionStore:stateDelete', async (_event, trackingId: string, key: string) => {
  try {
    await callSessionMgr(['state_delete', trackingId, key]);
    return { ok: true };
  } catch (err: any) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('uai:sessionStore:addTag', async (_event, trackingId: string, tag: string) => {
  try {
    await callSessionStore(['add_tag', trackingId, tag]);
    return { ok: true };
  } catch (err: any) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('uai:sessionStore:removeTag', async (_event, trackingId: string, tag: string) => {
  try {
    await callSessionStore(['remove_tag', trackingId, tag]);
    return { ok: true };
  } catch (err: any) {
    return { ok: false, error: err.message };
  }
});

ipcMain.handle('uai:sessionStore:findOrphans', async () => {
  try {
    const result = await callSessionStore(['find_orphans']);
    return Array.isArray(result) ? result : [];
  } catch (err: any) {
    console.error('[sessionStore:findOrphans]', err.message);
    return [];
  }
});

ipcMain.handle('uai:sessionStore:validateRunning', async (_event, fix?: boolean) => {
  try {
    const args = ['validate_running_sessions'];
    if (fix) args.push('--fix');
    const result = await callSessionStore(args);
    return result || {};
  } catch (err: any) {
    console.error('[sessionStore:validateRunning]', err.message);
    return { message: err.message };
  }
});

ipcMain.handle('uai:sessionStore:delete', async (_event, trackingId: string) => {
  try {
    await callSessionStore(['delete', trackingId]);
    return { ok: true };
  } catch (err: any) {
    return { ok: false, error: err.message };
  }
});

// ─── Vite global declarations ─────────────────────────────────────────────

declare const MAIN_WINDOW_VITE_DEV_SERVER_URL: string | undefined;
declare const MAIN_WINDOW_VITE_NAME: string;

// ─── Deep Link (uai:// protocol) ─────────────────────────────────────────

function parseUaiUri(uri: string): DeepLinkEvent | null {
  // uai://manager/id?key=val
  try {
    // URL constructor needs a valid base for custom schemes
    const parsed = new URL(uri.replace('uai://', 'http://uai/'));
    const segments = parsed.pathname.split('/').filter(Boolean);
    const manager = segments[0] || '';
    const id = segments.slice(1).join('/');
    const params: Record<string, string> = {};
    parsed.searchParams.forEach((v, k) => { params[k] = v; });
    return { raw: uri, manager, id, params };
  } catch {
    return null;
  }
}

function handleDeepLink(uri: string): void {
  const event = parseUaiUri(uri);
  if (!event) {
    console.warn(`[UAI] Invalid deep link URI: ${uri}`);
    return;
  }

  console.log(`[UAI] Deep link: ${event.manager}/${event.id}`);
  logLifecycleEvent('deeplink.received', { uri, manager: event.manager, id: event.id });

  // Bring window to front
  if (mainWindow) {
    if (mainWindow.isMinimized()) mainWindow.restore();
    mainWindow.focus();
    // Forward to renderer for navigation
    mainWindow.webContents.send(IPC.DEEP_LINK, event);
  }
}

// macOS: app already running, receives URL
app.on('open-url', (event, url) => {
  event.preventDefault();
  handleDeepLink(url);
});

// ─── App Lifecycle ────────────────────────────────────────────────────────

// Whether THIS process is the primary (user-facing) UAI instance. A PID marker
// file records the primary; a process that starts while a live primary already
// exists is a SECONDARY instance (e.g. an off-screen render-verify launched by
// another AI session). UAI has no single-instance lock by design, so secondary
// instances are normal — but their windows can flash on screen, which is
// disconcerting. A secondary instance announces itself to the user so an
// unexpected extra window is explained rather than mysterious.
let uaiIsPrimaryInstance = false;
function announceInstanceRole(): void {
  const markerPath = path.join(getAiRootMain(), 'ai_general', 'data', 'uai_instance.pid');
  let primaryAlive = false;
  try {
    if (fs.existsSync(markerPath)) {
      const pid = parseInt(fs.readFileSync(markerPath, 'utf-8').trim(), 10);
      if (pid && pid !== process.pid) {
        try { process.kill(pid, 0); primaryAlive = true; } catch { primaryAlive = false; }  // signal 0 = liveness probe
      }
    }
  } catch { /* treat as no primary */ }

  if (!primaryAlive) {
    // We are the primary — claim the marker.
    uaiIsPrimaryInstance = true;
    try { fs.writeFileSync(markerPath, String(process.pid)); } catch { /* non-fatal */ }
    return;
  }

  // Secondary instance — notify the user.
  uaiIsPrimaryInstance = false;
  const launcher = process.env.UAI_LAUNCHED_BY || process.env.AI_TRACKING_ID || 'unknown source';
  const msg = `UAI: a secondary instance launched (v${app.getVersion()}). Source: ${launcher}. `
    + `Normal for off-screen render-verify by another AI session — close it if you didn't expect it.`;
  logLifecycleEvent('lifecycle.secondary_instance', { version: app.getVersion(), launcher });
  try {
    const { spawn } = require('node:child_process');
    const notifier = path.join(getAiRootMain(), 'ai_general', 'scripts', 'notifications', 'send_user_notification.py');
    const envPath = shellPath();
    spawn('python3', [notifier, 'info', msg], {
      detached: true, stdio: 'ignore',
      env: { ...process.env, PATH: envPath, AI_ROOT: getAiRootMain() },
    }).unref();
  } catch (err: any) {
    console.warn('[UAI] secondary-instance notify failed:', err?.message);
  }
}

app.whenReady().then(() => {
  logLifecycleEvent('lifecycle.app_started', { version: app.getVersion(), platform: process.platform });
  announceInstanceRole();
  rebuildAppMenu();

  // Register uai:// protocol handler
  if (!app.isDefaultProtocolClient('uai')) {
    app.setAsDefaultProtocolClient('uai');
  }

  createWindow();

  // Handle deep link from cold start (macOS passes URI as argv on fresh launch)
  const launchUrl = process.argv.find(arg => arg.startsWith('uai://'));
  if (launchUrl) {
    // Delay to let the window finish loading
    setTimeout(() => handleDeepLink(launchUrl), 500);
  }

  // Watch signal files for external writes (Path 2)
  const localRoot = getAiRootMain();
  const dataDir = path.join(localRoot, 'ai_general', 'data');

  function watchSignalFile(filePath: string, changedSlices: string[]): void {
    let debounce: NodeJS.Timeout | null = null;
    try {
      if (!fs.existsSync(filePath)) {
        fs.writeFileSync(filePath, '');
      }
      fs.watch(filePath, () => {
        if (debounce) clearTimeout(debounce);
        debounce = setTimeout(() => {
          emitStoreChanged('external', changedSlices);
        }, 300);
      });
    } catch (err) {
      console.error(`[UAI] Failed to watch signal file ${filePath}:`, err);
    }
  }

  watchSignalFile(path.join(dataDir, 'sessions.changed'), ['sessions']);
  watchSignalFile(path.join(dataDir, 'containers.changed'), ['folders']);
  watchSignalFile(path.join(dataDir, 'tags.changed'), ['tags']);
  watchSignalFile(path.join(dataDir, 'relationships.changed'), ['relationships']);
  watchSignalFile(path.join(dataDir, 'appstate.changed'), ['appState']);
});

app.on('window-all-closed', () => {
  detachAll();
  if (process.platform !== 'darwin') app.quit();
});

app.on('before-quit', () => {
  detachAll();
  transcriptCache.dispose();
  // Release the primary marker so the next instance can claim primary.
  if (uaiIsPrimaryInstance) {
    try {
      const markerPath = path.join(getAiRootMain(), 'ai_general', 'data', 'uai_instance.pid');
      if (fs.existsSync(markerPath) && fs.readFileSync(markerPath, 'utf-8').trim() === String(process.pid)) {
        fs.unlinkSync(markerPath);
      }
    } catch { /* non-fatal */ }
  }
});

app.on('activate', () => {
  if (BrowserWindow.getAllWindows().length === 0) createWindow();
});

// ─── Export for testing ───────────────────────────────────────────────────

export { commandBus };
