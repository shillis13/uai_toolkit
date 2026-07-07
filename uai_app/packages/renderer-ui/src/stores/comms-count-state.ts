/**
 * Comms Inbox Count Store — renderer-side cache of each session's comms inbox
 * counts ({ total, unread }), so badges can render without each component
 * firing its own IPC. Mirrors prompt-area-state: a bulk scan over a set of
 * sessions plus targeted per-session rescans, both debounced.
 *
 * "Comms" = messages other agents sent to this session (the comms inbox),
 * distinct from "Messages" (the session's own chat-history message count).
 *
 * NOT persisted — purely ephemeral UI state.
 */

interface CommsCount { total: number; unread: number }

const counts = new Map<string, CommsCount>();
const listeners = new Set<() => void>();

function notify(): void { for (const fn of listeners) fn(); }

/** Get the cached comms inbox count for a session, or undefined if not scanned. */
export function getCommsCount(trackingId: string): CommsCount | undefined {
  return counts.get(trackingId);
}

/** Subscribe to comms-count changes. Returns unsubscribe. */
export function onCommsCountChange(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function sameCount(a: CommsCount | undefined, b: CommsCount): boolean {
  return a != null && a.total === b.total && a.unread === b.unread;
}

/** Bulk scan: fetch inbox counts for the given sessions. Debounced. There is no
 *  bulk IPC endpoint, so this fans out one inboxCount call per session — keep the
 *  caller list bounded (e.g. the visible / recent set). */
let bulkTimer: ReturnType<typeof setTimeout> | null = null;
export function scanCommsCounts(trackingIds: string[]): void {
  if (bulkTimer) clearTimeout(bulkTimer);
  bulkTimer = setTimeout(async () => {
    let changed = false;
    await Promise.all(trackingIds.map(async (id) => {
      try {
        const c = await window.uai.comms.inboxCount(id);
        if (!sameCount(counts.get(id), c)) { counts.set(id, c); changed = true; }
      } catch { /* ignore unreachable session */ }
    }));
    if (changed) notify();
  }, 300);
}

/** Targeted single-session rescan, debounced per session. Use after the user
 *  reads/archives a message or when a new comms message is known to have arrived. */
const sessionTimers = new Map<string, ReturnType<typeof setTimeout>>();
export function scanSessionCommsCount(trackingId: string, delay = 500): void {
  const existing = sessionTimers.get(trackingId);
  if (existing) clearTimeout(existing);
  sessionTimers.set(trackingId, setTimeout(async () => {
    sessionTimers.delete(trackingId);
    try {
      const c = await window.uai.comms.inboxCount(trackingId);
      if (!sameCount(counts.get(trackingId), c)) { counts.set(trackingId, c); notify(); }
    } catch { /* ignore */ }
  }, delay));
}
