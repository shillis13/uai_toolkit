/**
 * UAI Shared Types — used by both main and renderer.
 *
 * Runtime types derived from architecture/contracts/.
 * The contracts are the canonical reference; these are the runtime subset.
 */

// Import contract types used locally in this file
import type { EntityType, CardId, RelationType, ActorRef, UndoDescriptor } from '../../../architecture/contracts';

// Re-export contract types that are used directly at runtime
export type { EntityType, EntityId, CardId, EntityRef } from '../../../architecture/contracts';
export type { Platform, PlatformCode, TrackingId, IdentityStatus, SessionProcessStatus } from '../../../architecture/contracts';
export type { Project, ProjectLifecycleStatus, ProjectGitStatus, Team, TeamSlot, TeamStatus, CommsPlan, CommsBoardRef, FeedbackMechanism } from '../../../architecture/contracts';
export type { StoreSlice, CommandOrigin, CommandSafety, Capability, CapabilityScope } from '../../../architecture/contracts';
export type { StoreChangedEvent, RuntimeChangedEvent, RuntimeChangeType } from '../../../architecture/contracts';
export type { ComponentDescription, ActionContext, FocusState } from '../../../architecture/contracts';
export type { ActorRef, UndoDescriptor } from '../../../architecture/contracts';
export type { RelationType } from '../../../architecture/contracts';
export { INVERSE_RELATIONS } from '../../../architecture/contracts';
export { makeEntityId, parseEntityId, resolveActionTargets } from '../../../architecture/contracts';
export { PLATFORM_CODES, CODE_TO_PLATFORM, TRACKING_ID_REGEX } from '../../../architecture/contracts';
export type { BaseCard, ContainerCapability, SessionCard as SessionCardType, BriefCard, FolderCard, AnyCard, PlacementRule, ContainerType } from '../../../architecture/contracts';
export { isContainerCard, isSessionCard, isBriefCard, isFolderCard } from '../../../architecture/contracts';

// ─── Session (renderer view) ───────────────────────────────────────────────

/**
 * Prompt-block state for a session (Noctis's `prompt_blocks` backend). When
 * present, the session is blocked from receiving prompts from anyone but
 * PianoMan. Read-only in the app — set/cleared via CLI/MCP. Surfaced as a 🔒
 * chip on session cards + the Recent Sessions list. Sourced from
 * `prompt_blocks.py list` (one call for the whole roster).
 */
export interface PromptBlock {
  mode: string;                          // 'indefinite' | 'until' | 'turns' (per backend)
  turns_remaining?: number | null;       // for turn-countdown blocks
  expires_at?: string | null;            // ISO time for timed blocks
  reason?: string | null;
}

export interface Session {
  tracking_id: string;
  cli_session_id: string | null;
  platform: 'claude_cli' | 'codex_cli' | 'gemini_cli';
  terminal_session: string | null;
  session_dir: string;
  project_dir: string;
  history_file: string | null;
  display_name: string | null;
  roles: string[];
  model: string | null;
  parent_tracking_id: string | null;
  identity_status: 'draft' | 'pending' | 'confirmed' | 'failed' | 'orphaned';
  process_status: 'running' | 'stopped' | 'exited';
  archived: boolean;
  created_at: string;
  // Runtime (not persisted)
  runtime_state: 'unknown' | 'running' | 'idle' | 'responding' | 'blocked' | 'error' | 'stopped';
  activity_state: 'idle' | 'responding' | 'prompt_occupied' | 'blocked' | 'permission_prompt' | 'error' | 'stopped' | 'unknown';
  context_percent: number | null;
  exchange_count: number;
  message_count: number | null;
  // Size in bytes of the session's JSONL transcript (history_file). Read-only,
  // derived by stat'ing the externally-owned transcript; null if unavailable.
  transcript_bytes: number | null;
  last_activity: string;
  // Local-time ISO timestamps of session (re)starts, appended by the
  // SessionStart hook. Most-recent-last; empty until the first recorded start.
  start_history: string[];
  // App UI state
  pinned: boolean;
  lastViewedAt: string | null;
  notes: string | null;
  tags: string[];
  loaded_briefs: string[];  // Brief names loaded into this session's context
  // Prompt-block state (null/absent when the session is not blocked). Read-only.
  prompt_block?: PromptBlock | null;
}

// ─── Command Envelope (runtime version) ────────────────────────────────────

export interface Command<P = Record<string, unknown>> {
  id: string;
  type: string;
  payload: P;
  origin: 'user' | 'internal' | 'external-api' | 'embedded-ai' | 'debug';
  actor?: ActorRef;
  parent_id?: string;
  correlation_id?: string;
  idempotency_key?: string;
  timestamp: string;
  dry_run?: boolean;
}

export interface CommandResult<T = unknown> {
  ok: boolean;
  command_id: string;
  data?: T;
  error?: { code: string; message: string; details?: unknown; retryable?: boolean };
  changed?: Partial<Record<string, boolean>>;
  snapshots?: Partial<Record<string, unknown>>;
  effects?: Array<{ type: string; target?: string; description: string }>;
  undo?: UndoDescriptor;
}

// ─── App State ─────────────────────────────────────────────────────────────

export interface AppearancePrefs {
  fontUi: string | null;
  fontMono: string | null;
  fontSizeBase: number;
  fontSizeTerminal: number;
}

/**
 * Prompt Box configuration (global, persisted). Surfaced as quick toggles in the
 * Prompt Box control pane and in the full configurator. Optional fields so older
 * persisted state still loads; the UI falls back to the defaults.
 */
export interface PromptBoxConfig {
  /** Send both types the prompt AND presses Enter (default true). When false,
   *  Send stages the text into the CLI prompt area without submitting, so the
   *  user can review it and press Enter themselves. */
  autoSubmit: boolean;
  /** One-tap quick-react nudges shown in the control pane. Each is a {label, text};
   *  clicking sends `text` and submits it (regardless of autoSubmit). Order is the
   *  display order. Optional so older persisted state still loads; the UI falls back
   *  to a default set. Fully editable (label, text, add/remove, reorder) in the Config. */
  quickNudges?: { label: string; text: string }[];
  /** How many columns to lay the quick-react buttons out in (1–4, default 1). */
  quickNudgeColumns?: number;
  /** Whether the quick-react buttons are collapsed behind a "Quick Actions" toggle
   *  (click to expand/collapse, sticky). Default false = always visible. */
  quickNudgesCollapsed?: boolean;
  /** Whether the 📎 Attach button is shown in the control pane. Optional so older
   *  persisted state still loads; undefined = shown (default true). */
  showAttach?: boolean;
  /** Whether the 🔖 Library button (saved-prompts repository) is shown in the control
   *  pane. Optional so older persisted state still loads; undefined = shown (default true). */
  showLibrary?: boolean;
  /** Default prompt-box height, in lines (the resize floor the box opens at and
   *  collapses to). Optional so older persisted state still loads; undefined =
   *  15 lines. Clamped to a sane range in the UI. */
  defaultHeightLines?: number;
  /** When a single Send fans out to MULTIPLE recipients, pause this many seconds
   *  between each delivery (lets each session's terminal settle / avoids hammering).
   *  Optional; undefined or 0 = no pause (send back-to-back). Clamped in the UI. */
  multiSendDelaySec?: number;
}

/** A reusable prompt from the prompt library (repository). The store + CRUD live in
 *  scripts/prompts/prompt_library.py (YAML, single source of truth); the app reaches
 *  it through the prompt.library.* bus commands. Content only — no timing/delivery. */
export interface SavedPrompt {
  id: string;
  title: string;
  body: string;
  /** Optional single free-text tag for grouping/filtering (flat, no folders in v1). */
  tag?: string;
  /** ISO-8601 creation timestamp (UTC), for stable ordering. */
  created?: string;
}

export interface AppState {
  tabs: Tab[];
  activeTabId: string | null;
  panelSizes: {
    navigatorWidth: number;
    contextPanelWidth: number;
    bottomPanelHeight: number;
    // Inner master/detail left-panel widths (px), draggable + persisted. Optional so
    // older persisted state still loads; the resize hook falls back to a default.
    workMgrListWidth?: number;
    sessionStoreListWidth?: number;
    contextMgrCatalogWidth?: number;
    sessionWorkListWidth?: number;
  };
  navigatorTab: string;
  contextPanelOpen: boolean;
  bottomPanelOpen: boolean;
  sessionPrefs: Record<string, SessionPref>;
  appearance?: AppearancePrefs;
  // Right panel: which sub-tab is shown (persists across tab switches), and an
  // optional pinned session — when set, the right panel stays showing that
  // session's data regardless of the active tab (for compare/copy).
  contextPanelActiveTab?: string;
  contextPanelPinnedSession?: string | null;
  // Transcript: optional pinned session — stays on that session across tabs.
  transcriptPinnedSession?: string | null;
  // Prompt Box config (global). Optional so older persisted state still loads.
  promptBoxConfig?: PromptBoxConfig;
}

export type TabType = 'session' | 'folder' | 'terminal' | 'brief' | 'transcript' | 'search' | 'project' | 'team' | 'webai' | 'app' | 'markdown';
export type GridLayout = 'single' | 'vertical_2' | 'horizontal_2' | 'grid_2x2';

export interface Tab {
  id: string;
  type: TabType;
  label: string;
  targetId: string;  // tracking_id, folder_id, terminal_id, brief_name
  openedAt: string;
  groupId?: string;  // TeamId or ProjectId — brackets tabs together in tab bar
  deepLinkId?: string;  // Item ID from uai:// deep link — used by manager panes to navigate to specific items
}

/** @deprecated Use Tab instead */
export type TabState = Tab;

export interface SessionPref {
  pinned?: boolean;
  lastViewedAt?: string;
  notes?: string;
  loaded_briefs?: string[];
  promptDraft?: string;
  /** Per-session prompt reminder — a prefix/suffix that auto-wraps outgoing prompts
   *  to this session on a cadence. The in-band, visible cousin of comms post_standing. */
  reminder?: PromptReminder;
}

/** A per-session prepend/append that auto-wraps outgoing prompts on a cadence.
 *  Optional fields so older persisted state still loads. */
export interface PromptReminder {
  /** Master on/off. When false the reminder is retained but not applied. */
  enabled: boolean;
  /** Text prepended above the prompt (blank line between). Empty = no prefix. */
  prepend?: string;
  /** Text appended below the prompt (blank line between). Empty = no suffix. */
  append?: string;
  /** Cadence: 'every' = wrap every send; 'nth' = wrap send #1 then every Nth;
   *  'once' = wrap the next send only, then auto-disable. */
  cadence: 'every' | 'nth' | 'once';
  /** N for the 'nth' cadence (min 2). Ignored for other cadences. */
  n?: number;
}

// ─── Folder (runtime) ──────────────────────────────────────────────────────

export interface Folder {
  id: string;
  name: string;
  icon: string | null;
  color: string | null;
  builtin: boolean;
  subfolders: string[];
  cards: CardId[];
}

export interface FolderStoreData {
  schema_version: number;
  revision: number;
  roots: { sessions: string; briefs: string };
  folders: Record<string, Folder>;
}

// ─── Tag (runtime) ─────────────────────────────────────────────────────────

export interface Tag {
  name: string;
  color: string | null;
  icon: string | null;
  entity_types: EntityType[];  // Which entity types can use this tag
}

// ─── Entity Relationship (runtime) ─────────────────────────────────────────
// RelationType, INVERSE_RELATIONS re-exported from contracts above.

export interface EntityRelationship {
  source_type: EntityType;
  source_id: string;
  relation_type: RelationType;
  target_type: EntityType;
  target_id: string;
  created_at: string;
  created_by: string | null;
  metadata_json: Record<string, unknown> | null;
}

// ─── Comms Types ──────────────────────────────────────────────────────────

export type CommsUrgency = 'interrupt' | 'prompt' | 'async' | 'passive';
export type CommsDelivery = 'pre-prompt' | 'post-prompt' | 'postResponse';
export type CommsMessageType = 'request' | 'expiring-request' | 'advisory' | 'delivery' | 'question';
export type CommsResponseType = 'reply' | 'acknowledge' | 'none';

export interface QueueEntry {
  id: string;
  message_id?: string;
  to: string;
  content: string;
  urgency: CommsUrgency;
  delivery: CommsDelivery;
  ready_for_delivery: boolean;
  queued_at: string;
  expires_at?: string;
  source: string;
  callback_endpoint: string | null;
}

export interface InboxMessage {
  id: string;
  type: CommsMessageType;
  urgency: CommsUrgency;
  response_type: CommsResponseType;
  from: string;
  to: string;
  subject?: string;
  content: string;
  /** Path to an offloaded large message body, if the body was externalized. */
  body_file?: string;
  created_at: string;
  ttl_seconds: number | null;
  expires_at?: string;
  reply_to: string | null;
  /** Conversation/thread this message belongs to (groups a thread). */
  conversation_id?: string | null;
  /** Parent message this is a reply to (replies set this, not reply_to). */
  replying_to?: string | null;
  callback_endpoint: string | null;
  attachments?: Array<{ path: string; description: string }>;
  read_by?: Array<{ by: string; at: string }>;
  acknowledgments?: string[];
}

// ─── IPC Channel Names ─────────────────────────────────────────────────────

export const IPC = {
  // Queries (renderer → main)
  SESSION_LIST: 'uai:sessions:list',
  SESSION_GET: 'uai:sessions:get',
  BOOTSTRAP: 'uai:bootstrap',

  // Command bus (renderer → main)
  COMMAND_EXECUTE: 'uai:command:execute',

  // Legacy commands (renderer → main → store mutation → change event)
  SESSION_UPDATE: 'uai:sessions:update',
  SESSION_CREATE: 'uai:sessions:create',

  // App state
  APP_STATE_GET: 'uai:appstate:get',
  APP_STATE_UPDATE: 'uai:appstate:update',

  // Folders
  FOLDER_LIST: 'uai:folders:list',

  // Containers (generic — includes folders + groups)
  CONTAINER_LIST: 'uai:containers:list',

  // Projects
  PROJECT_LIST: 'uai:projects:list',

  // Briefs
  BRIEF_LIST: 'uai:briefs:list',
  BRIEF_CREATE: 'uai:briefs:create',

  // Tags
  TAGS_LIST: 'uai:tags:list',
  TAGS_FOR_CARD: 'uai:tags:forCard',

  // Relationships
  RELATIONSHIPS_FOR_ENTITY: 'uai:relationships:forEntity',

  // Comms — prompt queue + inbox
  COMMS_QUEUE_LIST: 'uai:comms:queue:list',
  COMMS_QUEUE_COUNT: 'uai:comms:queue:count',
  COMMS_INBOX_LIST: 'uai:comms:inbox:list',
  COMMS_INBOX_COUNT: 'uai:comms:inbox:count',

  // Events (main → renderer, Path 2)
  STORE_CHANGED: 'uai:store:changed',
  RUNTIME_CHANGED: 'uai:runtime:changed',
  DEEP_LINK: 'uai:deeplink',
} as const;

// ─── Deep Link Types ───────────────────────────────────────────────────────

/** Managers addressable via uai://<manager>/<id> */
export type UaiManager =
  | 'session'
  | 'project'
  | 'game'
  | 'todo_mgr'
  | 'task_mgr'
  | 'context_mgr'
  | 'session_store'
  | 'project_mgr';

export interface DeepLinkEvent {
  /** The raw URI string: uai://context_mgr/dev */
  raw: string;
  /** Parsed manager segment */
  manager: UaiManager | string;
  /** Parsed ID/name segment (may be empty for manager-level links) */
  id: string;
  /** Any query params from the URI */
  params: Record<string, string>;
}
