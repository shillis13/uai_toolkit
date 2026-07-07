/**
 * SessionStateIndicator — the canonical session-state dot. Colored + (when the
 * session is non-idle) breathing, driven entirely by the single source of truth in
 * stores/session-state.ts. Reused by the Session Card, Recent list, and anywhere
 * else a state dot is shown, so they can never diverge.
 */

import { getSessionStateVisual, type ActivityState, type ProcessStatus } from '../stores/session-state';

interface SessionStateIndicatorProps {
  activityState: ActivityState | string | null | undefined;
  processStatus: ProcessStatus | string | null | undefined;
  /** Show the text label after the dot (e.g. "Responding"). */
  withLabel?: boolean;
  /** Dot font-size in px (label scales with surrounding text). Default 10. */
  size?: number;
}

export function SessionStateIndicator({
  activityState, processStatus, withLabel = false, size = 10,
}: SessionStateIndicatorProps): JSX.Element {
  const v = getSessionStateVisual(activityState, processStatus);
  return (
    <span className="session-state-indicator" title={v.label}>
      <span
        className={`session-state-dot${v.breathing ? ' session-breathing' : ''}`}
        style={{ color: v.color, fontSize: `${size}px` }}
      >{v.glyph}</span>
      {withLabel && <span className="session-state-label">{v.label}</span>}
    </span>
  );
}
