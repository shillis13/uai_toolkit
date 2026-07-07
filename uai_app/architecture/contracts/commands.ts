/**
 * Command System Contracts — Phase 0A
 *
 * Frozen types for command bus, command results, and access control.
 */

import type { EntityId, EntityType } from './entities';

// ─── Command Origin & Actor ────────────────────────────────────────────────

export type CommandOrigin = 'user' | 'internal' | 'external-api' | 'embedded-ai' | 'debug';

export interface ActorRef {
  origin: CommandOrigin;
  session_id?: string;        // For embedded-ai: which session is acting
  client_id?: string;         // For external-api: which client
}

// ─── Command Envelope ──────────────────────────────────────────────────────

export interface Command<P = Record<string, unknown>> {
  id: string;                          // Unique command ID (UUID)
  type: string;                        // Dot-path: "session.update", "workspace.tabs.open"
  payload: P;
  origin: CommandOrigin;
  actor?: ActorRef;
  parent_id?: string;                  // For nested/composed commands
  correlation_id?: string;             // For tracking related commands
  idempotency_key?: string;            // Prevents duplicate execution
  timestamp: string;                   // ISO 8601 UTC
  dry_run?: boolean;                   // If true, validate but don't execute
}

// ─── Command Result ────────────────────────────────────────────────────────

export interface CommandResult<T = unknown> {
  ok: boolean;
  command_id: string;
  data?: T;
  error?: CommandError;
  changed?: Partial<Record<StoreSlice, boolean>>;
  snapshots?: Partial<Record<StoreSlice, unknown>>;
  effects?: EffectRecord[];
  undo?: UndoDescriptor;
}

export interface CommandError {
  code: string;                        // Machine-readable: "NOT_FOUND", "CONFLICT", "FORBIDDEN"
  message: string;                     // Human-readable
  details?: unknown;
  retryable?: boolean;
}

export type StoreSlice =
  | 'sessions'
  | 'briefs'
  | 'projects'
  | 'teams'
  | 'folders'
  | 'appState'
  | 'tags'
  | 'relationships'
  | 'notifications'
  | 'config';

export interface EffectRecord {
  type: string;                        // "notification.emitted", "signal.written", "file.created"
  target?: string;
  description: string;
}

export interface UndoDescriptor {
  command_id: string;
  inverse_type: string;                // Command type that would undo this
  inverse_payload: Record<string, unknown>;
  undoable: boolean;
  expires_at?: string;                 // Undo window
}

// ─── Command Safety & Access ───────────────────────────────────────────────

export type CommandSafety = 'safe' | 'destructive' | 'requires_confirmation';

export interface CommandDescriptor {
  type: string;
  description: string;
  safety: CommandSafety;
  required_capabilities: CapabilityRequirement[];
  payload_schema?: Record<string, unknown>;  // JSON Schema
  result_schema?: Record<string, unknown>;   // JSON Schema
  idempotent: boolean;
  affected_stores: StoreSlice[];
}

// ─── Capabilities ──────────────────────────────────────────────────────────

export type Capability =
  | 'sessions:read'
  | 'sessions:write'
  | 'sessions:create'
  | 'sessions:archive'
  | 'terminal:read'
  | 'terminal:send_staged'
  | 'terminal:send_submitted'
  | 'terminal:send_keys'
  | 'terminal:kill'
  | 'briefs:read'
  | 'briefs:write'
  | 'projects:read'
  | 'projects:write'
  | 'teams:read'
  | 'teams:write'
  | 'folders:read'
  | 'folders:write'
  | 'tags:read'
  | 'tags:write'
  | 'relationships:read'
  | 'relationships:write'
  | 'notifications:read'
  | 'notifications:write'
  | 'app:config'
  | 'app:debug'
  | 'comms:send'
  | 'comms:read'
  | 'transcript:read'
  | 'transcript:private'       // Access to private thinking blocks
  | 'notes:read'
  | 'notes:write'
  | 'shell:execute';

export type CapabilityScope =
  | EntityId                   // Specific entity
  | 'focused'                  // Currently focused session
  | 'own-session'              // The embedded AI's own session
  | 'descendants'              // Own session + children
  | '*';                       // All (requires debug or user origin)

export interface CapabilityRequirement {
  capability: Capability;
  scope?: CapabilityScope;
}

export interface CapabilityGrant {
  capability: Capability;
  scope: CapabilityScope;
  expires_at?: string;
}

// ─── Command Hierarchy Categories ──────────────────────────────────────────

/**
 * Command type prefixes forming the hierarchy.
 * Entry/exit hooks can attach at any level.
 */
export type CommandCategory =
  | 'app'
  | 'session'
  | 'workspace'
  | 'navigator'
  | 'prompt'
  | 'brief'
  | 'project'
  | 'team'
  | 'folder'
  | 'tag'
  | 'relationship'
  | 'notification'
  | 'comms'
  | 'terminal'
  | 'transcript'
  | 'debug';
