/**
 * Session Identity Contracts — Phase 0A
 *
 * Frozen types for session identity per spec_session_identity_v5.4.
 * All consumers of session identity must use these types.
 */

// ─── Platform ──────────────────────────────────────────────────────────────

export type Platform = 'claude_cli' | 'codex_cli' | 'gemini_cli';

export type PlatformCode = 'cla' | 'cod' | 'gem';

export const PLATFORM_CODES: Record<Platform, PlatformCode> = {
  claude_cli: 'cla',
  codex_cli: 'cod',
  gemini_cli: 'gem',
};

export const CODE_TO_PLATFORM: Record<PlatformCode, Platform> = {
  cla: 'claude_cli',
  cod: 'codex_cli',
  gem: 'gemini_cli',
};

// ─── Tracking ID ───────────────────────────────────────────────────────────

/**
 * Format: {YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}
 * Timestamp is UTC launch time.
 * Example: 20260411_012005_fcf141f7_cla
 */
export type TrackingId = string;

export const TRACKING_ID_REGEX = /^(?<date>\d{8})_(?<time>\d{6})_(?<uuid8>[0-9a-f]{8})_(?<platform3>cla|cod|gem)$/;

// ─── Identity Lifecycle ────────────────────────────────────────────────────

export type IdentityStatus = 'draft' | 'pending' | 'confirmed' | 'failed' | 'orphaned';

// ─── Three-Store Field Ownership ───────────────────────────────────────────

/**
 * Identity Core — v5.3 contract, preserved in v5.4.
 * These fields form the immutable identity/pointer index in SQLite.
 */
export interface SessionIdentityCore {
  tracking_id: TrackingId;
  cli_session_id: string | null;
  platform: Platform;
  terminal_session: string | null;
  session_dir: string;
  project_dir: string;       // immutable: launch-time project root
  history_file: string | null;
}

/**
 * SQLite-Owned Metadata — v5.4 extension.
 * SQLite is authoritative for these fields.
 */
export interface SessionSqliteMetadata {
  parent_tracking_id: string | null;
  display_name: string | null;
  roles: string[];            // app-owned; wrapper reads at launch
  identity_status: IdentityStatus;
  archived: boolean;
  created_at: string;         // ISO 8601 UTC
}

/**
 * Denormalized Runtime Index — mirrored from sessionInfo for query performance.
 * sessionInfo is authoritative. SQLite values repaired from sessionInfo during reconciliation.
 */
export interface SessionRuntimeIndex {
  working_dir: string | null;
  model: string | null;
  substrate: string | null;   // tmux, zellij, none
  transcript_path: string | null;
  cli_pid: number | null;
  status: SessionProcessStatus;
}

/**
 * Wrapper-reported process/lifecycle status.
 * NOT the UAI renderer-derived RuntimeState.
 */
export type SessionProcessStatus = 'running' | 'stopped' | 'exited';

/**
 * Full SQLite session row = identity core + sqlite metadata + runtime index.
 */
export interface SessionRegistryRow extends
  SessionIdentityCore,
  SessionSqliteMetadata,
  SessionRuntimeIndex {
  schema_version: number;
}

// ─── sessionInfo.{uuid8}.json ──────────────────────────────────────────────

/**
 * Per-session state file. Wrapper-owned for runtime fields.
 * Schema version 4 (v5.4).
 */
export interface SessionInfoFile {
  schema_version: 4;
  tracking_id: TrackingId;
  cli_session_id: string | null;
  platform: Platform;
  terminal_session: string | null;
  session_dir: string;
  project_dir: string;
  working_dir: string | null;
  history_file: string | null;
  display_name: string | null;
  parent_tracking_id: string | null;
  model: string | null;
  roles: string[];
  cli_pid: number | null;
  substrate: string | null;
  status: SessionProcessStatus;
  created_at: string;
  updated_at: string;
  launch_context: LaunchContext | null;
}

// ─── Draft / Launch ────────────────────────────────────────────────────────

export interface LaunchContext {
  requested_by: 'app' | 'script' | 'ai';
  requested_at: string;       // ISO 8601 UTC
  launch_params: LaunchParams;
  immutable_after: 'pending';
  retry_count?: number;
  retry_history?: Array<{ at: string; reason: string }>;
}

export interface LaunchParams {
  platform: Platform;
  role?: string;
  project_dir?: string;
  model?: string;
  prompt_file?: string;
  system_prompt_additions?: string;
  auto_approve?: boolean;
  brief_to_load?: string;
  extra_args?: string[];
}

// ─── Lookup ────────────────────────────────────────────────────────────────

/**
 * Resolution order: tracking_id → terminal_session → cli_session_id
 */
export type SessionLookupKey =
  | { by: 'tracking_id'; value: TrackingId }
  | { by: 'terminal_session'; value: string }
  | { by: 'cli_session_id'; value: string };
