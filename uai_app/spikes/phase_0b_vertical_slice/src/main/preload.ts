/**
 * UAI Preload — exposes IPC bridge to renderer.
 *
 * The renderer never calls IPC directly. It calls typed methods on window.uai.
 * This is the only bridge between renderer and main process.
 */

import { contextBridge, ipcRenderer } from 'electron';
import { IPC } from '../shared/types';
import type { Session, StoreChangedEvent, RuntimeChangedEvent, CommandResult } from '../shared/types';

const uaiApi = {
  // ── Bootstrap ────────────────────────────────────────────────────────
  bootstrap: (): Promise<{ sessions: Session[]; aiRoot: string }> =>
    ipcRenderer.invoke(IPC.BOOTSTRAP),

  // ── Session Queries ──────────────────────────────────────────────────
  sessions: {
    list: (): Promise<Session[]> =>
      ipcRenderer.invoke(IPC.SESSION_LIST),
    get: (trackingId: string): Promise<Session | null> =>
      ipcRenderer.invoke(IPC.SESSION_GET, trackingId),
    update: (trackingId: string, patch: Record<string, string>): Promise<CommandResult> =>
      ipcRenderer.invoke(IPC.SESSION_UPDATE, trackingId, patch),
    create: (opts: {
      platform: string;
      displayName?: string;
      projectDir?: string;
      roles?: string[];
      parentTrackingId?: string;
    }): Promise<CommandResult<{ trackingId: string }>> =>
      ipcRenderer.invoke('uai:sessions:create', opts),
  },

  // ── Transcript ───────────────────────────────────────────────────────
  transcript: {
    read: (zellijSession: string, cliSessionId: string | undefined, format: string): Promise<any> =>
      ipcRenderer.invoke('transcript:read', zellijSession, cliSessionId, format),
  },

  // ── Clipboard ────────────────────────────────────────────────────────
  clipboard: {
    write: (text: string): Promise<{ success: boolean }> =>
      ipcRenderer.invoke('clipboard:write', text),
    read: (): Promise<string> =>
      ipcRenderer.invoke('clipboard:read'),
  },

  // ── Terminal ──────────────────────────────────────────────────────────
  terminal: {
    attach: (sessionId: string, terminalSession: string, cols: number, rows: number): Promise<void> =>
      ipcRenderer.invoke('terminal:attach', sessionId, terminalSession, cols, rows),
    input: (sessionId: string, data: string): void =>
      ipcRenderer.send('terminal:input', sessionId, data),
    resize: (sessionId: string, cols: number, rows: number): void =>
      ipcRenderer.send('terminal:resize', sessionId, cols, rows),
    detach: (sessionId: string): Promise<void> =>
      ipcRenderer.invoke('terminal:detach', sessionId),
    onData: (callback: (sessionId: string, data: string) => void): (() => void) => {
      const handler = (_event: Electron.IpcRendererEvent, sessionId: string, data: string) => callback(sessionId, data);
      ipcRenderer.on('terminal:data', handler);
      return () => ipcRenderer.removeListener('terminal:data', handler);
    },
    onExit: (callback: (sessionId: string, exitCode: number) => void): (() => void) => {
      const handler = (_event: Electron.IpcRendererEvent, sessionId: string, exitCode: number) => callback(sessionId, exitCode);
      ipcRenderer.on('terminal:exit', handler);
      return () => ipcRenderer.removeListener('terminal:exit', handler);
    },
  },

  // ── Path 2: Store/Runtime Change Subscriptions ───────────────────────
  onStoreChanged: (callback: (event: StoreChangedEvent) => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent, data: StoreChangedEvent) => callback(data);
    ipcRenderer.on(IPC.STORE_CHANGED, handler);
    return () => ipcRenderer.removeListener(IPC.STORE_CHANGED, handler);
  },

  onRuntimeChanged: (callback: (event: RuntimeChangedEvent) => void): (() => void) => {
    const handler = (_event: Electron.IpcRendererEvent, data: RuntimeChangedEvent) => callback(data);
    ipcRenderer.on(IPC.RUNTIME_CHANGED, handler);
    return () => ipcRenderer.removeListener(IPC.RUNTIME_CHANGED, handler);
  },
};

contextBridge.exposeInMainWorld('uai', uaiApi);

export type UaiApi = typeof uaiApi;
