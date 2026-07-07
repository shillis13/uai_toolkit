/**
 * Event & Notification Contracts — Phase 0A
 *
 * Frozen types for store change events, runtime events, and
 * cross-boundary notifications.
 */

import type { StoreSlice } from './commands';
import type { EntityId, FeedbackMechanism } from './entities';

// ─── Store Change Events (Channel 1: durable/persisted changes) ────────────

export interface StoreChangedEvent {
  event_id: string;                    // Unique event ID
  sequence: number;                    // Monotonic sequence number
  command_id?: string;                 // If triggered by a command
  changed: StoreSlice[];
  source: 'command' | 'external' | 'poll';
  revisions?: Partial<Record<StoreSlice, number>>;
  snapshots?: Partial<Record<StoreSlice, unknown>>;
}

// ─── Runtime Change Events (Channel 2: ephemeral state) ────────────────────

export type RuntimeChangeType = 'terminalState' | 'runtimeState' | 'statusline' | 'activityState';

export interface RuntimeChangedEvent {
  changed: RuntimeChangeType[];
  session_id?: string;
  data?: {
    terminal_state?: unknown;
    runtime_state?: unknown;
    statusline?: unknown;
    activity_state?: unknown;
  };
}

// ─── Renderer Refresh Rules ────────────────────────────────────────────────

/**
 * Rules for how the renderer processes change events:
 *
 * 1. Command snapshots apply immediately — no need to wait for change event.
 * 2. Change events refresh only affected slices (use `changed` array).
 * 3. Ignore stale revisions — if event revision <= store's current, skip.
 * 4. Debounce/coalesce external events — multiple rapid signals → one refresh.
 * 5. Runtime events NEVER trigger store refresh — separate channels.
 */

// ─── Standard Internal Events ──────────────────────────────────────────────

export type InternalEventType =
  | 'session:changed'
  | 'session:added'
  | 'session:removed'
  | 'tab:opened'
  | 'tab:closed'
  | 'tab:activated'
  | 'command:executed'
  | 'notification:emitted';

export interface InternalEvent {
  type: InternalEventType;
  data: Record<string, unknown>;
  timestamp: string;
}

// ─── Signal File ───────────────────────────────────────────────────────────

export interface SignalFileContent {
  seq: number;
  changed: StoreSlice[];
  source: string;              // e.g., "session_store.py", "condense.py"
  timestamp: string;           // ISO 8601 UTC
}

// ─── Cross-Boundary Notifications ──────────────────────────────────────────

export type NotificationUrgency = 'info' | 'attention' | 'critical';

export interface Notification {
  type: string;                // e.g., "session.waiting_for_input"
  source: EntityId;
  data: Record<string, unknown>;
  urgency: NotificationUrgency;
  targets?: EntityId[];        // Specific targets, or all subscribers if omitted
}

// ─── Durable Notification Record ───────────────────────────────────────────

export type DeliveryStatus =
  | 'queued'
  | 'delivering'
  | 'delivered'
  | 'acknowledged'
  | 'failed'
  | 'expired'
  | 'cancelled';

export interface NotificationRecord {
  id: string;                  // Unique notification ID
  type: string;
  source: EntityId;
  target: EntityId;
  urgency: NotificationUrgency;
  data: Record<string, unknown>;

  // Delivery lifecycle
  status: DeliveryStatus;
  mechanism_requested: FeedbackMechanism;
  mechanism_used?: FeedbackMechanism;
  created_at: string;
  delivered_at?: string;
  acknowledged_at?: string;
  expires_at?: string;
  retry_count: number;
  failure_reason?: string;

  // Correlation
  correlation_id?: string;
  reply_to?: string;           // notification ID this responds to
  dedupe_key?: string;
}

// ─── AI-to-AI Communication ────────────────────────────────────────────────

export interface CommsRequest {
  message_id: string;          // Unique message ID for threading
  conversation_id: string;     // Conversation this message belongs to
  sequence: number;            // Monotonic order within conversation (spans sessions)
  from: EntityId;              // Requester session
  to: EntityId;                // Responder session
  type: string;                // "review_request", "feedback_request", etc.
  mechanism: FeedbackMechanism;
  content: string;
  content_ref?: string;        // Path to detailed content if too large for inline
  timeout_seconds: number;
  timeout_action: 'retry' | 'proceed' | 'escalate';
  due_at: string;              // ISO 8601 UTC
  created_at: string;
}

export interface CommsResponse {
  message_id: string;
  conversation_id: string;     // Same conversation as the request
  sequence: number;            // Next sequence in conversation
  in_reply_to: string;         // References CommsRequest.message_id
  from: EntityId;
  to: EntityId;
  mechanism: FeedbackMechanism;
  content: string;
  content_ref?: string;
  created_at: string;
}

// ─── Conversation ──────────────────────────────────────────────────────────

/**
 * A conversation spans multiple sessions and participants.
 * Messages within a conversation are ordered by sequence, not timestamp.
 * Reconstruct any conversation by filtering messages on conversation_id
 * and ordering by sequence.
 */
export interface Conversation {
  id: string;                  // e.g., "conv_a4f2"
  title: string | null;
  participants: EntityId[];    // Sessions/users in this conversation
  status: 'active' | 'paused' | 'closed';
  created_at: string;
  last_sequence: number;       // Highest assigned sequence (monotonic counter)
}

// ─── Feedback Request (durable, tracked) ───────────────────────────────────

export type FeedbackRequestStatus =
  | 'pending'
  | 'delivered'
  | 'responded'
  | 'timed_out'
  | 'retried'
  | 'escalated'
  | 'cancelled';

export interface FeedbackRequest {
  id: string;
  requester: EntityId;
  responder: EntityId;
  mechanism: FeedbackMechanism;
  status: FeedbackRequestStatus;
  created_at: string;
  due_at: string;
  timeout_action: 'retry' | 'proceed' | 'escalate';
  content_ref?: string;
  response_ref?: string;       // notification/comms ID of the response
  retries: number;
  escalation_state?: string;
}
