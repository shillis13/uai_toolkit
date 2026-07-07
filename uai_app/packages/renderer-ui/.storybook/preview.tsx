import type { Preview } from '@storybook/react';

/**
 * Mock window.uai for Storybook stories.
 *
 * In the Electron app, window.uai is injected by preload.ts via contextBridge.
 * Storybook runs in a plain browser, so we provide a mock that returns
 * sensible defaults for all API methods.
 */
const noopPromise = () => Promise.resolve(null);
const noopResult = () => Promise.resolve({ ok: true, command_id: 'mock' });

(window as any).uai = {
  bootstrap: () => Promise.resolve({ sessions: [], aiRoot: '/mock/ai_root' }),
  execute: (cmd: any) => Promise.resolve({ ok: true, command_id: cmd?.id || 'mock' }),
  sessions: {
    list: () => Promise.resolve([]),
    get: () => Promise.resolve(null),
    update: () => noopResult(),
    create: () => Promise.resolve({ ok: true, command_id: 'mock', data: { trackingId: 'mock_id' } }),
  },
  appState: {
    get: () => Promise.resolve({}),
    update: () => Promise.resolve({ ok: true }),
  },
  folders: { list: noopPromise },
  containers: { list: noopPromise },
  projects: { list: () => Promise.resolve([]) },
  briefs: { list: () => Promise.resolve([]) },
  comms: {
    queue: { list: () => Promise.resolve([]), count: () => Promise.resolve(0) },
    inbox: { list: () => Promise.resolve([]), count: () => Promise.resolve({ total: 0, unread: 0 }) },
  },
  tags: {
    list: () => Promise.resolve([]),
    forCard: () => Promise.resolve([]),
  },
  relationships: {
    forEntity: () => Promise.resolve([]),
  },
  activityLog: {
    read: () => Promise.resolve([]),
    tail: () => Promise.resolve([]),
  },
  commandLog: () => Promise.resolve([]),
  systemMetrics: () => Promise.resolve({
    cpu_percent: 0, memory_used_mb: 0, memory_total_mb: 0,
    heap_used_mb: 0, heap_total_mb: 0, active_sessions: 0,
    uptime_seconds: 0, error_count: 0,
  }),
  transcript: { read: () => Promise.resolve({ ok: false, error: 'mock' }) },
  clipboard: {
    write: () => Promise.resolve({ success: true }),
    read: () => Promise.resolve(''),
  },
  terminal: {
    attach: noopPromise,
    input: () => {},
    resize: () => {},
    detach: noopPromise,
    onData: () => () => {},
    onExit: () => () => {},
  },
  onStoreChanged: () => () => {},
  onRuntimeChanged: () => () => {},
};

const preview: Preview = {
  parameters: {
    controls: {
      matchers: {
        color: /(background|color)$/i,
        date: /Date$/i,
      },
    },
  },
};

export default preview;
