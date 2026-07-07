/**
 * Card & Container runtime types — used by both main and renderer.
 *
 * Re-exports contract types and adds runtime helpers.
 */

// Re-export all card contract types
export type {
  BaseCard, ContainerCapability, SessionCard, BriefCard,
  FolderCard, ProjectCard, TeamCard, AnyCard, PlacementRule, ContainerType,
} from '../../../architecture/contracts';

export {
  isContainerCard, isSessionCard, isBriefCard, isFolderCard, isProjectCard, isTeamCard,
} from '../../../architecture/contracts';

// ─── Container Store Data ────────────────────────────────────────────────

/**
 * Extends FolderStoreData to support multiple container types.
 * Backward-compatible: folders.json still works as-is.
 */
export interface ContainerStoreData {
  schema_version: number;
  revision: number;
  roots: Record<string, string>;  // e.g. { sessions: 'all_sessions', briefs: 'all_briefs' }
  containers: Record<string, ContainerEntry>;
}

export interface ContainerEntry {
  id: string;
  name: string;
  container_type: 'folder' | 'group';
  icon: string | null;
  color: string | null;
  builtin: boolean;
  placement_rule: 'exclusive' | 'non-exclusive';
  sub_containers: string[];
  cards: string[];
}

// ─── CardFilter ──────────────────────────────────────────────────────────

export interface CardFilter {
  entity_types?: string[];
  tags?: string[];
  search?: string;
  containerId?: string;
  descendants?: boolean;
}
