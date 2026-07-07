/**
 * Types for the Session Store Manager components.
 *
 * Mirrors the interfaces defined in preload.ts. Kept in renderer-ui
 * to avoid cross-package import paths that break TypeScript resolution.
 */

export interface SessionStoreRecord {
  tracking_id: string;
  terminal_session: string | null;
  cli_session_id: string | null;
  platform: string;
  session_dir: string;
  project_dir: string;
  display_name: string | null;
  model: string | null;
  substrate: string | null;
  tmux_server: string | null;
  roles: string | string[] | null;
  notes: string | null;
  status: string;
  identity_status: string;
  created_at: string;
  archived: boolean | number;
  last_activity: string | null;
  parent_tracking_id?: string | null;
  history_file?: string | null;
  tags?: string[];
  // Local-time ISO timestamps of session (re)starts (SessionStart hook).
  start_history?: string[];
}

export interface ChangeLogEntry {
  id?: number;
  tracking_id: string;
  field: string;
  old_value: string | null;
  new_value: string | null;
  changed_at: string;
  changed_by: string | null;
  pid?: number | null;
}

export interface ValidationResult {
  stale?: Array<{ tracking_id: string; display_name?: string; status?: string; last_activity?: string }>;
  fixed?: Array<{ tracking_id: string; action: string }>;
  orphans?: Array<{ tracking_id: string; display_name?: string; reason?: string }>;
  message?: string;
}
