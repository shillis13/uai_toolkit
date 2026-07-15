/**
 * Conversation Lock — per-session lock to block automated prompt delivery.
 *
 * Per AI Communication Protocol v1.0 §4.3.5:
 * - Lock file at ai_general/data/comms/locks/{session_tracking_id}.lock
 * - Presence blocks all automated prompt delivery to that session
 * - Interrupt-urgency messages escalate to user notification instead
 * - Queue continues to accumulate; entries delivered when lock is removed
 */

import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import { aiRootMain as getAiRootMain } from './paths';


function getLocksDir(): string {
  return path.join(getAiRootMain(), 'ai_general', 'data', 'comms', 'locks');
}

function getLockPath(sessionTrackingId: string): string {
  return path.join(getLocksDir(), `${sessionTrackingId}.lock`);
}

function ensureLocksDir(): void {
  const dir = getLocksDir();
  if (!fs.existsSync(dir)) {
    const commsDir = path.dirname(dir);
    if (!fs.existsSync(commsDir)) {
      fs.mkdirSync(commsDir);
    }
    fs.mkdirSync(dir);
  }
}

export function isLocked(sessionTrackingId: string): boolean {
  return fs.existsSync(getLockPath(sessionTrackingId));
}

export function lockSession(sessionTrackingId: string, reason?: string): void {
  ensureLocksDir();
  const lockPath = getLockPath(sessionTrackingId);
  const content = JSON.stringify({
    locked_by: 'uai_app',
    locked_at: new Date().toISOString(),
    reason: reason || 'User locked via UAI',
  }, null, 2);
  fs.writeFileSync(lockPath, content);
}

export function unlockSession(sessionTrackingId: string): void {
  const lockPath = getLockPath(sessionTrackingId);
  if (fs.existsSync(lockPath)) {
    fs.unlinkSync(lockPath);
  }
}

export function listLocks(): Array<{ sessionTrackingId: string; locked_at: string; reason: string }> {
  const dir = getLocksDir();
  if (!fs.existsSync(dir)) return [];

  return fs.readdirSync(dir)
    .filter(f => f.endsWith('.lock'))
    .map(f => {
      const sessionId = f.replace('.lock', '');
      try {
        const content = JSON.parse(fs.readFileSync(path.join(dir, f), 'utf-8'));
        return {
          sessionTrackingId: sessionId,
          locked_at: content.locked_at || '',
          reason: content.reason || '',
        };
      } catch {
        return { sessionTrackingId: sessionId, locked_at: '', reason: '' };
      }
    });
}
