/**
 * Terminal management — main process.
 *
 * Each session gets a node-pty process that spawns the substrate CLI:
 *   python3 lib_session_substrate.py attach --session <name>
 * The substrate os.execvp's into the multiplexer (tmux/zellij), so
 * node-pty ends up owning a PTY connected to the live terminal session.
 * The app never calls tmux/zellij directly — the substrate owns that.
 *
 * PTY output forwards to renderer via IPC. Renderer input forwards back via IPC.
 */

import pty, { type IPty } from 'node-pty';
import * as path from 'node:path';
import * as fs from 'node:fs';
import * as os from 'node:os';
import type { BrowserWindow } from 'electron';

interface PtyEntry {
  process: IPty;
  sessionId: string;
  cols?: number;
  rows?: number;
  /** Timestamp of the last PTY output — used to tell whether the CLI is actively
   *  responding (streaming) vs idle, so we can hold resizes during a response. */
  lastDataAt?: number;
  /** A resize requested while the CLI was actively responding, held until the
   *  output goes quiet (so we don't repaint — and corrupt — an overflowing response
   *  mid-stream). Only the latest requested size is kept. */
  pendingResize?: { cols: number; rows: number };
  /** Timer that flushes pendingResize once output has been quiet long enough. */
  quietTimer?: ReturnType<typeof setTimeout>;
}

// A session is treated as "actively responding" if it produced PTY output within
// this window. A resize is held while responding and applied this long after the
// last output (i.e. once the response settles). Most tool calls emit output (⎿
// results) that re-arm the window, so the hold spans typical tool pauses too.
const RESPONDING_QUIET_MS = 1000;

const ptyEntries = new Map<string, PtyEntry>();

/** Canonical main ai_root — for production scripts and data. */
function getAiRootMain(): string {
  const resolved = process.env.AI_ROOT_MAIN || path.join(os.homedir(), 'AI/ai_root');
  console.log(`[terminal] getAiRootMain: ${resolved}`);
  return resolved;
}

function getSessionOpsPath(): string {
  return path.join(getAiRootMain(), 'ai_general/scripts/session_mgmt/session_ops.py');
}

/**
 * Build a PATH that always includes the standard system directories.
 *
 * When UAI is launched from the macOS GUI (Finder/Dock/launchd) or a wrapper
 * with a sanitized environment, the Electron main process can inherit a
 * minimal/empty PATH that lacks /bin and /usr/bin. Passing that straight to a
 * spawned shell makes even `ls`, `sed`, and `sh` "command not found"
 * (e.g. `env: sh: No such file or directory`). We prepend the caller's PATH
 * (so their preferences win) and append the standard locations, de-duplicated.
 */
function buildShellPath(): string {
  const dirs = [
    ...(process.env.PATH ? process.env.PATH.split(':') : []),
    '/opt/homebrew/bin',
    '/usr/local/bin',
    '/usr/bin',
    '/bin',
    '/usr/sbin',
    '/sbin',
  ];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const d of dirs) {
    if (!d || seen.has(d)) continue;
    seen.add(d);
    out.push(d);
  }
  return out.join(':');
}

function getPythonPath(): string {
  return buildShellPath();
}

/**
 * Build the attach command. Routes through session_ops.py which resolves
 * the correct tmux server per-session from the session store.
 */
function findPython(): string {
  const candidates = ['/opt/homebrew/bin/python3', '/usr/local/bin/python3', '/usr/bin/python3'];
  for (const p of candidates) {
    try { fs.accessSync(p, fs.constants.X_OK); return p; } catch { /* next */ }
  }
  return 'python3';  // fallback to PATH resolution
}

function buildAttachCommand(sessionName: string): { command: string; args: string[] } {
  return { command: 'python3', args: [getSessionOpsPath(), 'attach', sessionName] };
}

export function attachTerminal(
  sessionId: string,
  terminalSession: string,
  cols: number,
  rows: number,
  window: BrowserWindow,
): void {
  const existing = ptyEntries.get(sessionId);
  if (existing) {
    try { process.kill(existing.process.pid, 'SIGKILL'); } catch { /* ignore */ }
    ptyEntries.delete(sessionId);
  }

  const { command, args } = buildAttachCommand(terminalSession);
  console.log(`[terminal] attachTerminal: sessionId=${sessionId} terminalSession=${terminalSession} cmd=${command} args=${JSON.stringify(args)}`);

  const ptyProcess = pty.spawn(
    command,
    args,
    {
      name: 'xterm-256color',
      cols: Math.max(2, cols),
      rows: Math.max(2, rows),
      cwd: process.env.HOME ?? '/',
      env: { ...process.env, TERM: 'xterm-256color', COLORTERM: 'truecolor', PATH: getPythonPath(), AI_ROOT: getAiRootMain() } as Record<string, string>,
    },
  );

  const entry: PtyEntry = { process: ptyProcess, sessionId, cols: Math.max(2, cols), rows: Math.max(2, rows) };
  ptyEntries.set(sessionId, entry);

  ptyProcess.onData((data: string) => {
    if (ptyEntries.get(sessionId) !== entry) return;
    entry.lastDataAt = Date.now();
    // Output is flowing → the CLI is responding. If a resize is being held, push its
    // flush back so it only lands once the response settles.
    if (entry.pendingResize) armQuietFlush(entry);
    if (window && !window.isDestroyed()) {
      window.webContents.send('terminal:data', sessionId, data);
    }
  });

  ptyProcess.onExit(({ exitCode }) => {
    console.log(`[terminal] PTY exited: sessionId=${sessionId} exitCode=${exitCode}`);
    if (ptyEntries.get(sessionId) !== entry) return;
    if (entry.quietTimer) { clearTimeout(entry.quietTimer); entry.quietTimer = undefined; }
    ptyEntries.delete(sessionId);
    if (window && !window.isDestroyed()) {
      window.webContents.send('terminal:exit', sessionId, exitCode);
    }
  });
}

/** Write raw data to terminal PTY. No newline appended — caller controls framing. */
export function writeTerminal(sessionId: string, data: string): boolean {
  const entry = ptyEntries.get(sessionId);
  if (!entry) return false;
  try {
    entry.process.write(data);
    return true;
  } catch {
    return false;
  }
}

/** Apply a resize to the PTY now (fires SIGWINCH). No-op if the size is unchanged. */
function applyResize(entry: PtyEntry, c: number, r: number): void {
  if (entry.cols === c && entry.rows === r) return;
  try {
    entry.process.resize(c, r);
    entry.cols = c;
    entry.rows = r;
  } catch {
    // PTY may have exited — ignore EBADF
  }
}

/** (Re)arm the timer that flushes a held resize once PTY output has been quiet. */
function armQuietFlush(entry: PtyEntry): void {
  if (entry.quietTimer) clearTimeout(entry.quietTimer);
  entry.quietTimer = setTimeout(() => {
    entry.quietTimer = undefined;
    const pending = entry.pendingResize;
    if (pending) {
      entry.pendingResize = undefined;
      applyResize(entry, pending.cols, pending.rows);  // safe now — output has settled
    }
  }, RESPONDING_QUIET_MS);
}

export function resizeTerminal(sessionId: string, cols: number, rows: number): void {
  const entry = ptyEntries.get(sessionId);
  if (!entry) return;
  const c = Math.max(2, cols);
  const r = Math.max(2, rows);

  // Skip a same-size resize: pty.resize() fires ioctl(TIOCSWINSZ) → SIGWINCH even
  // when the grid is unchanged, and that spurious SIGWINCH makes the CLI repaint —
  // which corrupts an overflowing response's scrollback. Only resize on real change.
  if (entry.cols === c && entry.rows === r) {
    entry.pendingResize = undefined;  // a held resize that matches reality is moot
    return;
  }

  // If the CLI is actively responding (recent PTY output), HOLD the resize — a
  // repaint mid-response is what corrupts an overflowing response. Keep only the
  // latest requested size; it's flushed once output goes quiet (armQuietFlush).
  const responding = entry.lastDataAt !== undefined && (Date.now() - entry.lastDataAt) < RESPONDING_QUIET_MS;
  if (responding) {
    entry.pendingResize = { cols: c, rows: r };
    armQuietFlush(entry);
    return;
  }

  applyResize(entry, c, r);
}

export function detachTerminal(sessionId: string): void {
  const entry = ptyEntries.get(sessionId);
  if (entry) {
    if (entry.quietTimer) { clearTimeout(entry.quietTimer); entry.quietTimer = undefined; }
    try { process.kill(entry.process.pid, 'SIGKILL'); } catch { /* ignore */ }
    ptyEntries.delete(sessionId);
  }
}

export function detachAll(): void {
  for (const [id] of ptyEntries) {
    detachTerminal(id);
  }
  for (const [id] of standalonePtys) {
    closeStandaloneTerminal(id);
  }
}

// ─── Standalone Terminal (raw shell, no session) ─────────────────────────

interface StandalonePtyEntry {
  process: IPty;
  window: BrowserWindow;
  /**
   * Rolling scrollback buffer. The renderer's terminal component unmounts on
   * every tab switch (only the active tab is mounted). Rather than killing the
   * shell on unmount, we keep the PTY alive here and replay this buffer when
   * the renderer re-attaches, so shell state, running processes, and scrollback
   * survive tab switches. The PTY is only torn down on a real tab close
   * (see workspace.tabs.close → closeStandaloneTerminal).
   */
  buffer: string;
}

const standalonePtys = new Map<string, StandalonePtyEntry>();

/** Cap the replay buffer so a long-lived terminal can't grow unbounded. */
const STANDALONE_BUFFER_MAX = 512 * 1024; // ~512 KB of recent output

/**
 * Create or re-attach a standalone PTY with the user's default shell.
 * No session association — just a raw shell for the Terminal tab type.
 *
 * If a PTY already exists for `id` (the renderer remounted after a tab switch),
 * we re-attach to the live shell and replay its scrollback instead of
 * respawning — this is what makes the terminal survive tab switches.
 *
 * Returns `{ reattached }` so the renderer knows the replay is already in
 * flight on the data channel.
 */
export function createStandaloneTerminal(
  id: string,
  cols: number,
  rows: number,
  cwd: string | undefined,
  window: BrowserWindow,
): { reattached: boolean } {
  const existing = standalonePtys.get(id);
  if (existing) {
    existing.window = window;
    try { existing.process.resize(Math.max(2, cols), Math.max(2, rows)); } catch { /* ignore */ }
    if (existing.buffer && window && !window.isDestroyed()) {
      window.webContents.send('standalone-terminal:data', id, existing.buffer);
    }
    return { reattached: true };
  }

  const shell = process.env.SHELL || '/bin/zsh';
  const home = process.env.HOME || os.homedir();

  const ptyProcess = pty.spawn(
    shell,
    [],
    {
      name: 'xterm-256color',
      cols: Math.max(2, cols),
      rows: Math.max(2, rows),
      cwd: cwd || home,
      env: {
        ...process.env,
        TERM: 'xterm-256color',
        COLORTERM: 'truecolor',
        PATH: buildShellPath(),
      } as Record<string, string>,
    },
  );

  const entry: StandalonePtyEntry = { process: ptyProcess, window, buffer: '' };
  standalonePtys.set(id, entry);

  ptyProcess.onData((data: string) => {
    if (standalonePtys.get(id) !== entry) return;
    entry.buffer += data;
    if (entry.buffer.length > STANDALONE_BUFFER_MAX) {
      entry.buffer = entry.buffer.slice(entry.buffer.length - STANDALONE_BUFFER_MAX);
    }
    const w = entry.window;
    if (w && !w.isDestroyed()) {
      w.webContents.send('standalone-terminal:data', id, data);
    }
  });

  ptyProcess.onExit(({ exitCode }) => {
    console.log(`[terminal] Standalone PTY exited: id=${id} exitCode=${exitCode}`);
    if (standalonePtys.get(id) !== entry) return;
    standalonePtys.delete(id);
    const w = entry.window;
    if (w && !w.isDestroyed()) {
      w.webContents.send('standalone-terminal:exit', id, exitCode);
    }
  });

  return { reattached: false };
}

export function writeStandaloneTerminal(id: string, data: string): boolean {
  const entry = standalonePtys.get(id);
  if (!entry) return false;
  try {
    entry.process.write(data);
    return true;
  } catch {
    return false;
  }
}

export function resizeStandaloneTerminal(id: string, cols: number, rows: number): void {
  const entry = standalonePtys.get(id);
  if (entry) {
    try {
      entry.process.resize(Math.max(2, cols), Math.max(2, rows));
    } catch {
      // PTY may have exited
    }
  }
}

export function closeStandaloneTerminal(id: string): void {
  const entry = standalonePtys.get(id);
  if (entry) {
    try { process.kill(entry.process.pid, 'SIGKILL'); } catch { /* ignore */ }
    standalonePtys.delete(id);
  }
}
