/**
 * Component API Contracts — Phase 0A
 *
 * Frozen types for component self-description, action context,
 * and the component tree model.
 */

import type { CommandSafety, Capability, CapabilityScope, StoreSlice } from './commands';

// ─── Component Self-Description ────────────────────────────────────────────

/**
 * Every architectural component provides describe() returning this interface.
 * Enables: embedded AI discovery, auto-generated help, diagram generation,
 * contract testing.
 */
export interface ComponentDescription {
  /** Schema version for the description format itself */
  schema_version: number;

  /** Stable component identifier, e.g., "session_navigator" */
  id: string;

  /** Stable dot-path in the component tree, e.g., "app.workspace.session_pane" */
  path: string;

  /** Instance ID if multiple instances exist (e.g., grid cells) */
  instance_id?: string;

  /** Human-readable name */
  name: string;

  /** Human-readable purpose description */
  description: string;

  /** Parent component ID (null for root) */
  parent: string | null;

  /** Child component IDs */
  children: string[];

  /** Readable/writable state keys */
  state: Record<string, StateDescriptor>;

  /** Available commands */
  commands: Record<string, ComponentCommandDescriptor>;

  /** Clickable/activatable UI actions */
  actions: Record<string, ActionDescriptor>;

  /** Events this component emits */
  events: Record<string, EventDescriptor>;

  /** Context this component requires from providers */
  context: ContextRequirement[];

  /** Deprecation info */
  deprecated?: {
    since: string;
    replacement?: string;
    removal_target?: string;
  };
}

export interface StateDescriptor {
  /** JSON Schema for the value */
  schema: Record<string, unknown>;
  description: string;
  readable: boolean;
  writable: boolean;
  /** If writable, is it local UI state or does it dispatch a command? */
  write_mechanism: 'local' | 'command';
  /** Default value */
  default_value?: unknown;
}

export interface ComponentCommandDescriptor {
  description: string;
  /** JSON Schema for command parameters */
  parameters: Record<string, unknown>;
  /** JSON Schema for return type */
  returns: Record<string, unknown>;
  /** Safety classification */
  safety: CommandSafety;
  /** Required capabilities to invoke */
  required_capabilities: Array<{ capability: Capability; scope?: CapabilityScope }>;
  /** Which stores this command may affect */
  affected_stores: StoreSlice[];
  /** Side effects beyond store mutations */
  side_effects: string[];
  /** Preconditions that must be true */
  preconditions: string[];
  /** Postconditions guaranteed on success */
  postconditions: string[];
  /** Is this command idempotent? */
  idempotent: boolean;
  /** Is this command async? */
  async: boolean;
  /** Expected latency category */
  latency: 'immediate' | 'fast' | 'slow';
  /** Error codes this command may return */
  error_codes: string[];
  /** Usage examples */
  examples?: Array<{ description: string; payload: Record<string, unknown> }>;
}

export interface ActionDescriptor {
  description: string;
  /** Which command this action invokes */
  trigger_command: string;
  /** What contextual data the parent provides for this action */
  context_description: string;
  /** Keyboard shortcut if any */
  shortcut?: string;
}

export interface EventDescriptor {
  description: string;
  /** JSON Schema for event data */
  data_schema: Record<string, unknown>;
  /** When this event fires */
  trigger: string;
}

export interface ContextRequirement {
  key: string;
  type: string;
  description: string;
  required: boolean;
}

// ─── Action Context Provider ───────────────────────────────────────────────

/**
 * Explicit context providers replace parent-chain querying.
 * Components declare what context they need; providers supply it.
 */
export interface ActionContext {
  /** Which entity this action applies to */
  entity_ref?: import('./entities').EntityRef;

  /** Multi-select: IDs of all selected entities */
  selection?: Set<string>;

  /** Is multi-select mode active? */
  select_mode?: boolean;

  /** Current folder/navigation location */
  location?: string;

  /** Active navigator tab */
  navigator_tab?: string;

  /** Focused grid cell index (for grid view) */
  grid_cell?: number;
}

/**
 * Resolves the effective targets for a context menu action.
 * If select mode is active AND the clicked entity is selected,
 * returns all selected entities. Otherwise returns just the clicked entity.
 */
export function resolveActionTargets(
  clicked_id: string,
  context: ActionContext,
): string[] {
  if (context.select_mode && context.selection?.has(clicked_id)) {
    return Array.from(context.selection);
  }
  return [clicked_id];
}

// ─── Focus Model ───────────────────────────────────────────────────────────

/**
 * Focus is a set of independent, related-but-distinct concepts.
 * Each has its own state and update mechanism.
 */
export interface FocusState {
  /** Which workspace tab/group is active */
  active_tab_id: string | null;

  /** Which grid cell has keyboard focus (in grid view) */
  active_grid_cell: number;

  /** Which session pane has terminal keyboard focus */
  focused_session_id: string | null;

  /** Which session the prompt box will stage to */
  prompt_target_id: string | null;

  /** Which entity is selected in the navigator */
  navigator_selected_id: string | null;

  /** Which entity's details are shown in the right panel */
  detail_entity_id: string | null;
}

// ─── Component Tree Types ──────────────────────────────────────────────────

export type NavigatorTab = 'sessions' | 'briefs' | 'projects' | 'webuis' | 'terminals' | 'apps' | 'news';
export type ContextPanelTab = 'details' | 'digests' | 'docs' | 'messages' | 'prompts';
export type BottomPanelTab = 'related' | 'logs' | 'app_log' | 'monitor';
export type PaneMode = 'terminal' | 'transcript';
export type PromptMode = 'prompt' | 'command' | 'shell';
export type GridLayout = 'single' | 'vertical_2' | 'horizontal_2' | 'grid_2x2';
export type SortField = 'activity' | 'created' | 'name';
export type SortDirection = 'asc' | 'desc';
