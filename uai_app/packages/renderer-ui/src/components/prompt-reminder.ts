/**
 * prompt-reminder — pure logic for the Prompt Box's per-session periodic reminder
 * (todo_0355). A reminder is a prepend/append that auto-wraps outgoing prompts on a
 * cadence. Kept DOM-free so it can be unit-tested and reused by the live preview.
 */

import type { PromptReminder } from '@uai/shared/types';

/** True when the reminder has content worth applying (enabled + at least one side). */
export function reminderHasContent(r: PromptReminder | undefined | null): boolean {
  if (!r || !r.enabled) return false;
  return !!(r.prepend && r.prepend.trim()) || !!(r.append && r.append.trim());
}

/**
 * Whether the reminder fires for THIS send.
 * @param sendCountBefore number of prior outgoing prompts this session (0 for the first).
 *   'every' → always; 'once' → always (caller disables after); 'nth' → send #1 then every N.
 */
export function reminderFires(r: PromptReminder | undefined | null, sendCountBefore: number): boolean {
  if (!reminderHasContent(r)) return false;
  const rem = r as PromptReminder;
  switch (rem.cadence) {
    case 'every':
      return true;
    case 'once':
      return true;
    case 'nth': {
      const n = Math.max(2, Math.floor(rem.n ?? 3));
      // sendCountBefore is a 0-based index for this send: fires on 0, n, 2n, …
      return sendCountBefore % n === 0;
    }
    default:
      return false;
  }
}

/** Wrap `text` with the reminder's prepend/append, blank-line separated. Present
 *  sides only; the user's text is never modified beyond the surrounding wrap. */
export function wrapWithReminder(text: string, r: PromptReminder): string {
  const parts: string[] = [];
  const pre = r.prepend ? r.prepend.replace(/\s+$/, '') : '';
  const post = r.append ? r.append.replace(/^\s+/, '') : '';
  if (pre) parts.push(pre);
  parts.push(text);
  if (post) parts.push(post);
  return parts.join('\n\n');
}

/**
 * Apply the reminder to an outgoing prompt given the prior send count.
 * Returns the (possibly wrapped) text, whether it fired, and whether the reminder
 * should be disabled afterward ('once' cadence).
 */
export function applyReminder(
  text: string,
  r: PromptReminder | undefined | null,
  sendCountBefore: number,
): { text: string; applied: boolean; disableAfter: boolean } {
  if (!reminderFires(r, sendCountBefore)) {
    return { text, applied: false, disableAfter: false };
  }
  const rem = r as PromptReminder;
  return {
    text: wrapWithReminder(text, rem),
    applied: true,
    disableAfter: rem.cadence === 'once',
  };
}
