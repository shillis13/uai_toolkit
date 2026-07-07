/**
 * Session-state visual encoding — the ONE source of truth for how a session's
 * runtime state maps to a color, glyph, breathing animation, and label. Every
 * state indicator (Session Card dot, Recent icon, Tab icon) derives from this so
 * they can never drift apart.
 *
 * The state DATA comes from the session store (`Session.activity_state` /
 * `process_status`); this module only encodes how that data is shown.
 */

export type ActivityState =
  | 'idle' | 'responding' | 'prompt_occupied' | 'blocked' | 'permission_prompt'
  | 'error' | 'stopped' | 'unknown';

export type ProcessStatus = 'running' | 'stopped' | 'exited';

export interface SessionStateVisual {
  /** Dot color for this state. */
  color: string;
  /** Dot glyph — filled ● when running, hollow ○ when stopped. */
  glyph: string;
  /** True ⇒ the indicator should "breathe" (soft fade in/out — the session is
   *  actively doing something or is waiting on you). */
  breathing: boolean;
  /** Short human label. */
  label: string;
}

// Palette aligned with the app theme — mapped to semantic design tokens by ROLE
// so state colors track the active theme (see styles.css :root).
const C = {
  green: 'var(--accent-green)',
  blue: 'var(--accent-blue)',
  yellow: 'var(--accent-yellow)',
  orange: 'var(--accent-orange)',
  red: 'var(--accent-red)',
  muted: 'var(--text-muted)',
} as const;

/**
 * Resolve the visual for a session. `processStatus` wins when not running
 * (a stopped/exited session shows a hollow muted dot regardless of activity).
 *
 * `needs-input` (permission_prompt) gets its own distinct amber + breathing — the
 * "waiting on you" state you want to catch at a glance, set apart from
 * responding-blue and idle-green. `prompt_occupied` (done, but an unsent draft
 * sits in the prompt) reads as idle on the dot — the draft has its own ▎ marker.
 */
export function getSessionStateVisual(
  activityState: ActivityState | string | null | undefined,
  processStatus: ProcessStatus | string | null | undefined,
): SessionStateVisual {
  if (processStatus !== 'running') {
    return { color: C.muted, glyph: '○', breathing: false, label: processStatus === 'exited' ? 'Exited' : 'Stopped' };
  }
  switch (activityState) {
    case 'responding':       return { color: C.blue,   glyph: '●', breathing: true,  label: 'Responding' };
    case 'blocked':          return { color: C.orange, glyph: '●', breathing: true,  label: 'Blocked' };
    case 'permission_prompt':return { color: C.yellow, glyph: '●', breathing: true,  label: 'Needs input' };
    case 'error':            return { color: C.red,    glyph: '●', breathing: true,  label: 'Error' };
    case 'prompt_occupied':  return { color: C.green,  glyph: '●', breathing: false, label: 'Idle' };
    case 'idle':             return { color: C.green,  glyph: '●', breathing: false, label: 'Idle' };
    default:                 return { color: C.green,  glyph: '●', breathing: false, label: 'Running' };
  }
}

/** Whether a session's indicators should animate — true for any running state that
 *  is actively working or waiting on the user. The single predicate the Card dot,
 *  Recent icon, and Tab icon all use. */
export function isSessionBreathing(
  activityState: ActivityState | string | null | undefined,
  processStatus: ProcessStatus | string | null | undefined,
): boolean {
  return getSessionStateVisual(activityState, processStatus).breathing;
}
