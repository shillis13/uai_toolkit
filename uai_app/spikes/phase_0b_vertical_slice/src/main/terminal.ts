/**
 * Terminal management — main process.
 *
 * Each session gets a node-pty process running `tmux attach-session -t <name>`.
 * PTY output forwards to renderer via IPC. Renderer input forwards back via IPC.
 */

import pty, { type IPty } from 'node-pty';
import type { BrowserWindow } from 'electron';

interface PtyEntry {
  process: IPty;
  sessionId: string;
}

const ptyEntries = new Map<string, PtyEntry>();

/**
 * Attach to a tmux session, forwarding I/O to the renderer.
 */
export function attachTerminal(
  sessionId: string,
  terminalSession: string,
  cols: number,
  rows: number,
  window: BrowserWindow,
): void {
  // Kill existing PTY for this session
  const existing = ptyEntries.get(sessionId);
  if (existing) {
    try { process.kill(existing.process.pid, 'SIGKILL'); } catch { /* ignore */ }
    ptyEntries.delete(sessionId);
  }

  const ptyProcess = pty.spawn(
    'tmux',
    ['attach-session', '-t', terminalSession],
    {
      name: 'xterm-256color',
      cols: Math.max(2, cols),
      rows: Math.max(2, rows),
      cwd: process.env.HOME ?? '/',
      env: { ...process.env, TERM: 'xterm-256color', COLORTERM: 'truecolor' } as Record<string, string>,
    },
  );

  const entry: PtyEntry = { process: ptyProcess, sessionId };
  ptyEntries.set(sessionId, entry);

  // Forward PTY output → renderer
  ptyProcess.onData((data: string) => {
    if (ptyEntries.get(sessionId) !== entry) return;
    if (window && !window.isDestroyed()) {
      window.webContents.send('terminal:data', sessionId, data);
    }
  });

  // Handle PTY exit
  ptyProcess.onExit(({ exitCode }) => {
    if (ptyEntries.get(sessionId) !== entry) return;
    ptyEntries.delete(sessionId);
    if (window && !window.isDestroyed()) {
      window.webContents.send('terminal:exit', sessionId, exitCode);
    }
  });
}

/**
 * Write input from renderer to the session's PTY.
 */
export function writeTerminal(sessionId: string, data: string): void {
  const entry = ptyEntries.get(sessionId);
  if (entry) {
    entry.process.write(data);
  }
}

/**
 * Resize the session's PTY.
 */
export function resizeTerminal(sessionId: string, cols: number, rows: number): void {
  const entry = ptyEntries.get(sessionId);
  if (entry) {
    entry.process.resize(Math.max(2, cols), Math.max(2, rows));
  }
}

/**
 * Detach (kill PTY) for a session.
 */
export function detachTerminal(sessionId: string): void {
  const entry = ptyEntries.get(sessionId);
  if (entry) {
    try { process.kill(entry.process.pid, 'SIGKILL'); } catch { /* ignore */ }
    ptyEntries.delete(sessionId);
  }
}

/**
 * Cleanup all PTYs on app quit.
 */
export function detachAll(): void {
  for (const [id] of ptyEntries) {
    detachTerminal(id);
  }
}
