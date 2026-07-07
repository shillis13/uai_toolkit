/**
 * Entity Contracts — Phase 0A
 *
 * Frozen types for all UAI entities: Session, Brief, Project, Team, Tag.
 * Namespaced entity references and relationship model.
 */

import type { TrackingId, Platform, IdentityStatus, SessionProcessStatus } from './identity';

// ─── Entity References ─────────────────────────────────────────────────────

export type EntityType = 'session' | 'brief' | 'project' | 'team' | 'tag' | 'folder';

/**
 * Namespaced entity identifier. Prevents collision across entity types.
 * Format: "session:20260411_012005_fcf141f7_cla" or "brief:pixel_iii"
 */
export type EntityId = `${EntityType}:${string}`;

/**
 * Namespaced card identifier for UI card lists.
 * Subset of EntityId for entities that render as cards.
 */
export type CardId = `session:${string}` | `brief:${string}` | `project:${string}` | `team:${string}` | `folder:${string}`;

export interface EntityRef {
  type: EntityType;
  id: string;
  ref: EntityId;
}

export function makeEntityId(type: EntityType, id: string): EntityId {
  return `${type}:${id}` as EntityId;
}

export function parseEntityId(entityId: EntityId): EntityRef {
  const colonIdx = entityId.indexOf(':');
  const type = entityId.slice(0, colonIdx) as EntityType;
  const id = entityId.slice(colonIdx + 1);
  return { type, id, ref: entityId };
}

// ─── Session (renderer view) ───────────────────────────────────────────────

/**
 * Session as seen by the renderer. Assembled from SQLite + sessionInfo + runtime.
 * This is NOT the SQLite row — it's the merged view for UI consumption.
 */
export interface Session {
  // Identity
  tracking_id: TrackingId;
  cli_session_id: string | null;
  platform: Platform;
  terminal_session: string | null;
  session_dir: string;
  project_dir: string;
  history_file: string | null;

  // Metadata
  parent_tracking_id: string | null;
  display_name: string | null;
  roles: string[];
  model: string | null;
  substrate: string | null;

  // Lifecycle
  identity_status: IdentityStatus;
  process_status: SessionProcessStatus;
  archived: boolean;
  created_at: string;

  // Runtime (renderer-derived, not persisted)
  runtime_state: RuntimeState;
  activity_state: ActivityState;
  context_percent: number | null;
  exchange_count: number;
  last_activity: string;

  // App UI state (from app_state.json)
  pinned: boolean;
  lastViewedAt: string | null;
  notes: string | null;
  tags: string[];
}

/**
 * Independent state axes per UCI data architecture.
 */
export type TerminalState = 'unknown' | 'connected' | 'disconnected' | 'killed';
export type RuntimeState = 'unknown' | 'running' | 'idle' | 'responding' | 'blocked' | 'error' | 'stopped';
export type ActivityState = 'idle' | 'responding' | 'blocked' | 'permission_prompt' | 'error' | 'stopped';
export type ArchiveState = 'active' | 'archived';

// ─── Brief ─────────────────────────────────────────────────────────────────

export interface Brief {
  name: string;               // Unique identifier (filename stem)
  display_name: string;
  description: string | null;
  status: 'active' | 'superseded' | 'archived';
  created_at: string;
  updated_at: string | null;
  condenser_session: string | null;
  brief_path: string;
  schema_version: number;
  content_hash: string | null;
  file_size: number | null;
  folder: string | null;
  tags: string[];
}

// ─── Project ───────────────────────────────────────────────────────────────

export type ProjectLifecycleStatus = 'active' | 'sandbox' | 'paused' | 'complete' | 'archived';
export type ProjectGitStatus = 'clean' | 'dirty' | 'ahead' | 'behind' | 'unknown';

export interface Project {
  id: string;                 // Stable: hash of normalized working_dir, prefixed devtree_ or project_
  name: string;
  goal: string | null;
  lifecycle_status: ProjectLifecycleStatus | null;  // From project.yml; null if no YAML
  git_status: ProjectGitStatus;                     // Derived at index time
  branch: string | null;
  working_dir: string;
  tags: string[];

  /** @deprecated Use entity_relationships for assignment. Always empty. */
  assigned_ais: string[];

  // Indexed from filesystem, not authoritative
  source_path: string;        // Path to project.yml if it exists
  content_hash: string | null;
  indexed_at: string | null;
  availability: 'available' | 'unavailable' | 'parse_error';
  parse_error: string | null;
}

// ─── Team ──────────────────────────────────────────────────────────────────

export type TeamStatus = 'active' | 'disbanded' | 'paused';

export interface Team {
  id: string;                 // Filename stem (e.g. "uai-core" from uai-core.yml)
  name: string;
  description: string | null;
  status: TeamStatus;
  slots: TeamSlot[];
  comms_plan: CommsPlan;
  tags: string[];
  created_at: string;

  // Bootstrap hints — seed entity_relationships on first index.
  // After first index, relationships table is authoritative.
  project_ids: string[];      // Seeds team -> assigned_to -> project

  // Indexed from filesystem
  source_path: string;
  content_hash: string | null;
  indexed_at: string | null;
  availability: 'available' | 'unavailable' | 'parse_error';
  parse_error: string | null;
}

/**
 * A team slot defines a role to be filled by one or more sessions.
 * Slot definition is declarative (from YAML). Who fills the slot
 * is tracked in entity_relationships, not here.
 */
export interface TeamSlot {
  role: string;               // Semantic role (lead, worker, reviewer, etc.)
  description: string | null;
  platform: Platform | 'any'; // Preferred platform
  profile_ref: string | null; // Reference to a guidance profile
  count: number;              // How many sessions can fill this slot
}

export interface CommsPlan {
  escalation_chain: string[];
  feedback_mechanism: FeedbackMechanism;
  feedback_timeout: number;   // seconds
  notification_routing: Record<string, string[]>;
  boards: CommsBoardRef[];
}

export interface CommsBoardRef {
  type: string;               // Board type (comms, todos, tasks)
  scope: string;              // Board scope (team, project, global)
  id: string;                 // Board identifier
}

export type FeedbackMechanism = 'none' | 'message' | 'prompt';

// ─── Tag ───────────────────────────────────────────────────────────────────

export interface Tag {
  name: string;
  color: string | null;
  icon: string | null;
  entity_types: EntityType[];  // Which entity types can use this tag
}

// ─── Entity Relationships ──────────────────────────────────────────────────

export interface EntityRelationship {
  source_type: EntityType;
  source_id: string;
  relation_type: RelationType;
  target_type: EntityType;
  target_id: string;
  created_at: string;
  created_by: string | null;   // Who created this relationship
  metadata_json: Record<string, unknown> | null;
}

/**
 * Paired bidirectional relationship types.
 * Each row stores the forward direction; inverse is derived by query.
 */
export type RelationType =
  | 'forked_from'       // inverse: forked_to
  | 'briefed_to'        // inverse: brief_of
  | 'launched_from'     // inverse: launched
  | 'loaded'            // inverse: loaded_by
  | 'supersedes'        // inverse: superseded_by
  | 'member_of'         // inverse: has_member
  | 'assigned_to'       // inverse: has_assignment
  | 'continues'         // inverse: continued_by
  | 'relates_to';       // inverse: relates_to (symmetric)

export const INVERSE_RELATIONS: Record<RelationType, string> = {
  forked_from: 'forked_to',
  briefed_to: 'brief_of',
  launched_from: 'launched',
  loaded: 'loaded_by',
  supersedes: 'superseded_by',
  member_of: 'has_member',
  assigned_to: 'has_assignment',
  continues: 'continued_by',
  relates_to: 'relates_to',
};

// ─── Folders ───────────────────────────────────────────────────────────────

export interface Folder {
  id: string;
  name: string;
  icon: string | null;
  color: string | null;
  builtin: boolean;
  subfolders: string[];       // Ordered IDs of child folders
  cards: CardId[];            // Ordered namespaced card IDs
}

export interface FolderStore {
  schema_version: number;
  revision: number;
  roots: {
    sessions: string;         // "all_sessions"
    briefs: string;           // "all_briefs"
  };
  folders: Record<string, Folder>;
}
