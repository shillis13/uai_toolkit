/**
 * Session Activity & Badge Tracker — in-memory, renderer-side only.
 *
 * Tracks:
 * - Last user interaction time per session (terminal input, prompt submit, tab focus)
 * - Last viewed time per session (when the user last had this session's tab active)
 *
 * Used by RecentSessions for "ago" display and session badges.
 * NOT persisted to disk — purely ephemeral UI state.
 */

import { getSession } from './session-store';

const activityMap = new Map<string, number>(); // trackingId → Date.now() of last interaction
const viewedMap = new Map<string, number>();   // trackingId → Date.now() of last tab view
const seenCountMap = new Map<string, number>(); // trackingId → exchange_count snapshot at last view
const listeners = new Set<() => void>();

// The session whose tab is currently focused. While focused, its unread-reply
// count always reads 0 — the user is looking at it, so it's caught up. When focus
// moves away we re-baseline the outgoing session at its current exchange_count so
// it resumes counting from zero.
let activeSessionId: string | null = null;

/** Set which session tab is focused (or null for a non-session / no tab). */
export function setActiveSession(trackingId: string | null): void {
  if (activeSessionId === trackingId) return;
  if (activeSessionId) {
    // Re-baseline the session losing focus at its latest known count.
    const prev = getSession(activeSessionId)?.exchange_count;
    if (typeof prev === 'number') seenCountMap.set(activeSessionId, prev);
    viewedMap.set(activeSessionId, Date.now());
  }
  activeSessionId = trackingId;
  if (trackingId) {
    const cur = getSession(trackingId)?.exchange_count;
    if (typeof cur === 'number') seenCountMap.set(trackingId, cur);
    viewedMap.set(trackingId, Date.now());
  }
  for (const fn of listeners) fn();
}

/** Record user interaction with a session. Debounced to 1 update per second. */
export function touchSessionActivity(trackingId: string): void {
  const now = Date.now();
  const prev = activityMap.get(trackingId) || 0;
  if (now - prev < 1000) return;
  activityMap.set(trackingId, now);
  for (const fn of listeners) fn();
}

/** Record that the user viewed (focused on) a session tab. Snapshots the
 *  session's current exchange_count so unread-reply counts reset to zero. */
export function markSessionViewed(trackingId: string, exchangeCount?: number): void {
  viewedMap.set(trackingId, Date.now());
  if (typeof exchangeCount === 'number') seenCountMap.set(trackingId, exchangeCount);
  for (const fn of listeners) fn();
}

/** Get the last interaction timestamp (epoch ms), or 0. */
export function getSessionActivity(trackingId: string): number {
  return activityMap.get(trackingId) || 0;
}

/** Check if a session has activity newer than the last time the user viewed it.
 *  Uses backend last_activity as the "something happened" signal. */
export function hasUnreadResponse(trackingId: string, lastActivity: string | undefined): boolean {
  if (!lastActivity) return false;
  const lastViewed = viewedMap.get(trackingId) || 0;
  if (lastViewed === 0) return false; // never viewed in this app session — don't spam badges
  const activityTime = new Date(lastActivity).getTime();
  return activityTime > lastViewed;
}

/** Count of unread CLI assistant replies — the number of exchanges that have
 *  accrued since the user last viewed this session. Returns 0 for sessions never
 *  viewed in this app session (so we don't spam a count for everything on load).
 *  This is the count-valued extension of hasUnreadResponse. */
export function getUnreadReplyCount(trackingId: string, currentExchangeCount: number | undefined, lastActivity?: string): number {
  // The focused session is always caught up — the user is looking at it.
  if (trackingId === activeSessionId) return 0;
  if (typeof currentExchangeCount !== 'number') {
    // No count available — fall back to the boolean heuristic (1 or 0).
    return hasUnreadResponse(trackingId, lastActivity) ? 1 : 0;
  }
  if (!viewedMap.has(trackingId)) return 0; // never viewed this app session
  const seen = seenCountMap.get(trackingId);
  if (typeof seen !== 'number') return 0;   // viewed but no count snapshot yet
  return Math.max(0, currentExchangeCount - seen);
}

/** Subscribe to activity/viewed changes. Returns unsubscribe. */
export function onActivityChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}
