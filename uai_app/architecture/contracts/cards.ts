/**
 * Card & Container Contracts — Phase 2A
 *
 * Base card abstraction and container capability.
 * Every entity in the system is a Card. Some cards are also Containers.
 */

import type { EntityId, EntityType, ProjectLifecycleStatus, ProjectGitStatus, TeamStatus } from './entities';
import type { Platform, SessionProcessStatus } from './identity';

// ─── Placement Rules ──────────────────────────────────────────────────────

export type PlacementRule = 'exclusive' | 'non-exclusive';

export type ContainerType = 'folder';
// Future: 'team' | 'project'

// ─── Base Card ────────────────────────────────────────────────────────────

export interface BaseCard {
  entity_id: EntityId;
  entity_type: EntityType;
  display_name: string;
  created_at: string;
  last_activity: string;
  tags: string[];
  icon?: string;
  color?: string;

  /** Container capability — undefined for leaf cards */
  container?: ContainerCapability;
}

export interface ContainerCapability {
  children: EntityId[];
  sub_containers: string[];
  placement_rule: PlacementRule;
}

// ─── Type-Specific Card Extensions ────────────────────────────────────────

export interface SessionCard extends BaseCard {
  entity_type: 'session';
  container?: undefined;  // leaf card — explicit for discriminated union narrowing
  tracking_id: string;
  platform: Platform;
  process_status: SessionProcessStatus;
  cli_session_id?: string | null;
  terminal_session?: string | null;
  session_dir?: string | null;
  project_dir?: string | null;
  parent_tracking_id?: string | null;
  roles?: string[];
  model?: string | null;
  identity_status?: string;
  archived?: boolean;
  activity_state?: string;
  context_percent?: number | null;
  exchange_count?: number;
  /** Number of times this session has been restarted (start_history length).
      Read-only display of externally-owned session state. */
  restart_count?: number;
  /** Size in bytes of the session's JSONL transcript. Read-only display. */
  transcript_bytes?: number | null;
  pinned?: boolean;
  notes?: string | null;
  // Prompt-block state (read-only) — drives the 🔒 chip. Structurally matches
  // PromptBlock in @uai/shared/types (inlined to keep contracts dependency-free).
  prompt_block?: { mode: string; turns_remaining?: number | null; expires_at?: string | null; reason?: string | null } | null;
}

export interface BriefCard extends BaseCard {
  entity_type: 'brief';
  container?: undefined;  // leaf card — explicit for discriminated union narrowing
  name: string;
  description: string | null;
  status: 'active' | 'superseded' | 'archived';
  brief_path: string;
  file_size: number | null;
  condenser_session?: string | null;
  content_hash?: string | null;
}

export interface FolderCard extends BaseCard {
  entity_type: 'folder';
  builtin: boolean;
  container: ContainerCapability;  // always present for folders
}

export interface ProjectCard extends BaseCard {
  entity_type: 'project';
  container?: undefined;  // leaf card — explicit for discriminated union narrowing
  project_id: string;
  working_dir: string;
  branch: string | null;
  git_status: ProjectGitStatus;
  lifecycle_status: ProjectLifecycleStatus | null;  // null if no project.yml
  goal: string | null;
  source_path: string;
  availability: 'available' | 'unavailable' | 'parse_error';
  session_count?: number;

  /** Organizing directory name (e.g. "society", "games") — null for top-level projects */
  category: string | null;

  /** @deprecated Use entity_relationships for assignment. Always empty. */
  assigned_ais: string[];

  /**
   * Team role assignments read from the registry `role_assignments:` block —
   * role name (e.g. "lead", "reviewer") → the member name(s) filling it.
   * Absent/empty for projects and for teams that declare no roles. Read-only
   * display of external registry data (principle #6); mutations route through
   * the command bus to the registry, never owned by the app.
   */
  role_assignments?: Record<string, string[]>;

  /**
   * Context reference(s) attached to each role, from the registry `role_contexts:`
   * block — role name → the context composition(s)/file(s) a session loads when it
   * assumes that role. Optional; a role can exist with no context. Same read-only,
   * registry-owned semantics as role_assignments (principle #6).
   */
  role_contexts?: Record<string, string[]>;

  /**
   * Playbook folders — top-level directory names under the project's working_dir
   * that make up its Playbook (from the registry `playbook:` list). The Playbook
   * aspect shows a tree of just these; the Workspace aspect shows everything else.
   * Projects only; empty/absent for teams.
   */
  playbook?: string[];
}

export interface TeamCard extends BaseCard {
  entity_type: 'team';
  container?: undefined;  // leaf card — teams are not containers
  description: string | null;
  status: TeamStatus;
  slot_count: number;         // Total slots defined
  filled_count: number;       // Slots currently occupied (from entity_relationships)
  project_ids: string[];      // Projects this team is assigned to
  source_path: string;
  availability: 'available' | 'unavailable' | 'parse_error';
}

// ─── Discriminated Union ──────────────────────────────────────────────────

export type AnyCard = SessionCard | BriefCard | FolderCard | ProjectCard | TeamCard;

// ─── Type Guards ──────────────────────────────────────────────────────────

export function isContainerCard(card: BaseCard): card is FolderCard {
  return card.entity_type === 'folder' && card.container !== undefined;
}

export function isSessionCard(card: BaseCard): card is SessionCard {
  return card.entity_type === 'session';
}

export function isBriefCard(card: BaseCard): card is BriefCard {
  return card.entity_type === 'brief';
}

export function isFolderCard(card: BaseCard): card is FolderCard {
  return card.entity_type === 'folder';
}

export function isProjectCard(card: BaseCard): card is ProjectCard {
  return card.entity_type === 'project';
}

export function isTeamCard(card: BaseCard): card is TeamCard {
  return card.entity_type === 'team';
}
