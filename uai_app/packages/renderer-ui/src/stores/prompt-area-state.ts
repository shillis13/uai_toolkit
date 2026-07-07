/**
 * Prompt-Area State — tracks which sessions have unsent text in their CLI
 * prompt area. Event-driven (no continuous polling):
 *   - one bulk scan on startup / when Recent Sessions first renders
 *   - targeted single-session scan on: typing in the terminal, PromptBox submit,
 *     and leaving a session's tab
 *   - optimistic set on PromptBox submit for instant feedback
 *
 * Backed by window.uai.prompts (get_prompt_area_texts.py).
 */

const hasText = new Map<string, boolean>();   // trackingId → prompt area occupied
const listeners = new Set<() => void>();

function notify(): void { for (const fn of listeners) fn(); }

export function getPromptAreaState(trackingId: string): boolean {
  return hasText.get(trackingId) === true;
}

export function onPromptAreaChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Optimistically set (e.g. right after PromptBox stages text). */
export function setPromptAreaOptimistic(trackingId: string, value: boolean): void {
  if (hasText.get(trackingId) === value) return;
  hasText.set(trackingId, value);
  notify();
}

/** Bulk scan — refresh all sessions' occupied state in one call. */
let bulkTimer: ReturnType<typeof setTimeout> | null = null;
export function scanAllPromptAreas(): void {
  if (bulkTimer) clearTimeout(bulkTimer);
  bulkTimer = setTimeout(async () => {
    try {
      const areas = await window.uai.prompts.getPromptAreas();
      const occupied = new Set(
        areas.filter(a => (a.prompt_text || '').trim().length > 0).map(a => a.tracking_id),
      );
      let changed = false;
      // mark occupied true
      for (const id of occupied) {
        if (hasText.get(id) !== true) { hasText.set(id, true); changed = true; }
      }
      // anything previously true but no longer occupied → false
      for (const [id, v] of hasText) {
        if (v && !occupied.has(id)) { hasText.set(id, false); changed = true; }
      }
      if (changed) notify();
    } catch { /* ignore */ }
  }, 250);
}

/** Targeted single-session scan, debounced per session. */
const sessionTimers = new Map<string, ReturnType<typeof setTimeout>>();
export function scanSessionPromptArea(trackingId: string, delay = 500): void {
  const existing = sessionTimers.get(trackingId);
  if (existing) clearTimeout(existing);
  sessionTimers.set(trackingId, setTimeout(async () => {
    sessionTimers.delete(trackingId);
    try {
      const occupied = await window.uai.prompts.hasPromptText(trackingId);
      if (hasText.get(trackingId) !== occupied) {
        hasText.set(trackingId, occupied);
        notify();
      }
    } catch { /* ignore */ }
  }, delay));
}
