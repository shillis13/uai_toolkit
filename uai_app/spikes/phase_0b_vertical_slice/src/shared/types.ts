/**
 * UAI Shared Types — used by both main and renderer.
 *
 * These are the runtime types. The frozen contract types live in
 * architecture/contracts/ and are the canonical reference.
 * These types are derived from contracts but adapted for runtime use.
 */

// ─── Session (renderer view) ───────────────────────────────────────────────

export interface Session {
  tracking_id: string;
  cli_session_id: string | null;
  platform: 'claude_cli' | 'codex_cli' | 'gemini_cli';
  terminal_session: string | null;
  session_dir: string | null;
  project_dir: string | null;
  display_name: string | null;
  roles: string[];
  model: string | null;
  parent_tracking_id: string | null;
  identity_status: 'draft' | 'pending' | 'confirmed' | 'failed' | 'orphaned';
  process_status: 'running' | 'stopped' | 'exited';
  archived: boolean;
  created_at: string;
  // Runtime (not persisted)
  activity_state: 'idle' | 'responding' | 'blocked' | 'permission_prompt' | 'error' | 'stopped' | 'unknown';
  context_percent: number | null;
  exchange_count: number;
  last_activity: string;
  // App UI state
  pinned: boolean;
  notes: string | null;
  tags: string[];
}

// ─── Store Change Events (Path 2: inbound) ─────────────────────────────────

export type StoreSlice = 'sessions' | 'folders' | 'appState' | 'briefs';

export interface StoreChangedEvent {
  event_id: string;
  sequence: number;
  command_id?: string;
  changed: StoreSlice[];
  source: 'command' | 'external' | 'poll';
}

export interface RuntimeChangedEvent {
  changed: Array<'activityState' | 'statusline'>;
  session_id?: string;
}

// ─── Command (Path 1: outbound) ────────────────────────────────────────────

export interface CommandResult<T = unknown> {
  ok: boolean;
  command_id: string;
  data?: T;
  error?: { code: string; message: string; details?: unknown };
  changed?: Partial<Record<StoreSlice, boolean>>;
}

// ─── IPC Channel Names ─────────────────────────────────────────────────────

export const IPC = {
  // Queries (renderer → main)
  SESSION_LIST: 'uai:sessions:list',
  SESSION_GET: 'uai:sessions:get',
  BOOTSTRAP: 'uai:bootstrap',

  // Commands (renderer → main → store mutation → change event)
  SESSION_UPDATE: 'uai:sessions:update',

  // Events (main → renderer, Path 2)
  STORE_CHANGED: 'uai:store:changed',
  RUNTIME_CHANGED: 'uai:runtime:changed',
} as const;
