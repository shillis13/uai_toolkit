/**
 * Viewport Description Contracts
 *
 * Live runtime viewport state. Complements static ComponentDescription
 * (what components CAN do) with what's ACTUALLY visible and actionable.
 */

/** A node in the live viewport tree. */
export interface ViewportNode {
  /** Matches ComponentRegistry id */
  id: string;
  /** Is this component currently rendered? */
  visible: boolean;
  /** Human context: "Sessions tab", "Ember session" */
  label?: string;
  /** Only children the parent is currently rendering */
  children: ViewportNode[];
  /** Key/value pairs reflecting current state */
  state?: Record<string, unknown>;
  /** Actions available at this node right now */
  actions?: ViewportAction[];
  /** ISO timestamp — present only on the root node */
  timestamp?: string;
}

/** An action available at a viewport node. */
export interface ViewportAction {
  /** Action identifier, e.g., "toggle", "selectTab" */
  id: string;
  /** CommandBus command type — the SAME command the UI button fires */
  command: string;
  /** Pre-filled payload for this context */
  payload?: Record<string, unknown>;
  /** Human-readable description */
  label: string;
}

/** Reporter function that components provide to the ViewportRegistry. */
export type ViewportReporter = () => ViewportReporterResult;

/** Return type of a viewport reporter. */
export interface ViewportReporterResult {
  visible: boolean;
  label?: string;
  /** String = registered child ID to recurse into. ViewportNode = inline child. */
  children: (string | ViewportNode)[];
  state?: Record<string, unknown>;
  actions?: ViewportAction[];
}
