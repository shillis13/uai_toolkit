/**
 * Contract Test: Activity Log
 *
 * Quality Gate 1D.3 — validates that:
 *   - Activity log writes are parseable JSONL
 *   - Entries conform to UAI Next Architecture Section 2 format
 *   - Read/tail operations return valid entries
 */

import { describe, it, expect, beforeAll, afterAll } from 'vitest';
import * as fs from 'node:fs';
import * as path from 'node:path';
import * as os from 'node:os';
import {
  initActivityLog,
  writeActivityLog,
  logCommandExecution,
  logLifecycleEvent,
  readActivityLog,
  tailActivityLog,
  getSystemMetrics,
} from '../main/activity-log';
import type { ActivityLogEntry } from '../main/activity-log';

// Use a temp directory for testing
const testDir = path.join(os.tmpdir(), `uai-test-${Date.now()}`);
const testAiRoot = testDir;
const testLogPath = path.join(testDir, 'ai_general', 'data', 'activity_log.jsonl');

beforeAll(() => {
  fs.mkdirSync(path.join(testDir, 'ai_general', 'data'), { recursive: true });
  initActivityLog(testAiRoot);
});

afterAll(() => {
  try {
    fs.rmSync(testDir, { recursive: true, force: true });
  } catch { /* cleanup best-effort */ }
});

describe('Activity log write', () => {
  it('writes a valid JSONL entry', () => {
    const entry: ActivityLogEntry = {
      ts: new Date().toISOString(),
      session: 'test_session',
      participant: 'test_participant',
      event: 'test.event',
      payload: { key: 'value' },
    };

    writeActivityLog(entry);

    const content = fs.readFileSync(testLogPath, 'utf-8');
    const lines = content.trim().split('\n');
    const parsed = JSON.parse(lines[lines.length - 1]);

    expect(parsed.ts).toBe(entry.ts);
    expect(parsed.session).toBe('test_session');
    expect(parsed.participant).toBe('test_participant');
    expect(parsed.event).toBe('test.event');
    expect(parsed.payload.key).toBe('value');
  });

  it('writes entries with optional correlation_id', () => {
    const entry: ActivityLogEntry = {
      ts: new Date().toISOString(),
      session: 'test_session',
      participant: 'uai_app',
      event: 'command.executed',
      payload: { type: 'session.update' },
      correlation_id: 'corr_test_123',
    };

    writeActivityLog(entry);

    const content = fs.readFileSync(testLogPath, 'utf-8');
    const lines = content.trim().split('\n');
    const parsed = JSON.parse(lines[lines.length - 1]);

    expect(parsed.correlation_id).toBe('corr_test_123');
  });

  it('every line in the log file is valid JSON', () => {
    const content = fs.readFileSync(testLogPath, 'utf-8');
    const lines = content.trim().split('\n').filter(l => l.trim());

    for (const line of lines) {
      expect(() => JSON.parse(line)).not.toThrow();
    }
  });
});

describe('Activity log convenience writers', () => {
  it('logCommandExecution writes proper format', () => {
    logCommandExecution('session.update', 'user', true, 42, undefined, 'cmd_abc');

    const content = fs.readFileSync(testLogPath, 'utf-8');
    const lines = content.trim().split('\n');
    const parsed = JSON.parse(lines[lines.length - 1]);

    expect(parsed.event).toBe('command.executed');
    expect(parsed.participant).toBe('uai_app');
    expect(parsed.payload.type).toBe('session.update');
    expect(parsed.payload.origin).toBe('user');
    expect(parsed.payload.ok).toBe(true);
    expect(parsed.payload.duration_ms).toBe(42);
    expect(parsed.correlation_id).toBe('cmd_abc');
  });

  it('logCommandExecution includes error_code on failure', () => {
    logCommandExecution('folder.create', 'user', false, 100, 'VALIDATION_ERROR');

    const content = fs.readFileSync(testLogPath, 'utf-8');
    const lines = content.trim().split('\n');
    const parsed = JSON.parse(lines[lines.length - 1]);

    expect(parsed.payload.ok).toBe(false);
    expect(parsed.payload.error_code).toBe('VALIDATION_ERROR');
  });

  it('logLifecycleEvent writes lifecycle events', () => {
    logLifecycleEvent('lifecycle.app_started', { version: '0.1.0' });

    const content = fs.readFileSync(testLogPath, 'utf-8');
    const lines = content.trim().split('\n');
    const parsed = JSON.parse(lines[lines.length - 1]);

    expect(parsed.event).toBe('lifecycle.app_started');
    expect(parsed.payload.version).toBe('0.1.0');
  });
});

describe('Activity log entry schema validation (UAI Next Architecture Section 2)', () => {
  it('all entries have required fields: ts, session, participant, event, payload', () => {
    const content = fs.readFileSync(testLogPath, 'utf-8');
    const lines = content.trim().split('\n').filter(l => l.trim());

    for (const line of lines) {
      const entry = JSON.parse(line);
      expect(entry.ts).toBeTypeOf('string');
      expect(entry.session).toBeTypeOf('string');
      expect(entry.participant).toBeTypeOf('string');
      expect(entry.event).toBeTypeOf('string');
      expect(typeof entry.payload).toBe('object');
    }
  });

  it('event names follow domain.action namespace format', () => {
    const content = fs.readFileSync(testLogPath, 'utf-8');
    const lines = content.trim().split('\n').filter(l => l.trim());

    for (const line of lines) {
      const entry = JSON.parse(line);
      // Accept both dot-separated (command.executed) and colon-separated (command:executed) namespaces
      expect(entry.event).toMatch(/^[a-z]+[.:][a-z_]+$/);
    }
  });

  it('timestamps are valid ISO 8601', () => {
    const content = fs.readFileSync(testLogPath, 'utf-8');
    const lines = content.trim().split('\n').filter(l => l.trim());

    for (const line of lines) {
      const entry = JSON.parse(line);
      const date = new Date(entry.ts);
      expect(date.getTime()).not.toBeNaN();
    }
  });
});

describe('Activity log read', () => {
  it('readActivityLog returns entries', async () => {
    const entries = await readActivityLog({ limit: 10 });
    expect(entries.length).toBeGreaterThan(0);
    expect(entries[0].ts).toBeTypeOf('string');
    expect(entries[0].event).toBeTypeOf('string');
  });

  it('readActivityLog respects limit', async () => {
    const entries = await readActivityLog({ limit: 2 });
    expect(entries.length).toBeLessThanOrEqual(2);
  });

  it('readActivityLog filters by event prefix', async () => {
    const entries = await readActivityLog({ eventFilter: 'command' });
    for (const entry of entries) {
      expect(entry.event.startsWith('command')).toBe(true);
    }
  });

  it('tailActivityLog returns entries after timestamp', async () => {
    // Write a known entry with a future-ish timestamp
    const futureTs = new Date(Date.now() - 1000).toISOString();
    writeActivityLog({
      ts: new Date().toISOString(),
      session: 'tail_test',
      participant: 'test',
      event: 'test.tail',
      payload: {},
    });

    const entries = await tailActivityLog(futureTs);
    const tailEntries = entries.filter(e => e.session === 'tail_test');
    expect(tailEntries.length).toBeGreaterThan(0);
  });
});

describe('System metrics', () => {
  it('returns valid metrics object', () => {
    const metrics = getSystemMetrics(5);

    expect(typeof metrics.cpu_percent).toBe('number');
    expect(metrics.cpu_percent).toBeGreaterThanOrEqual(0);
    expect(metrics.cpu_percent).toBeLessThanOrEqual(100);

    expect(typeof metrics.memory_used_mb).toBe('number');
    expect(metrics.memory_used_mb).toBeGreaterThan(0);

    expect(typeof metrics.memory_total_mb).toBe('number');
    expect(metrics.memory_total_mb).toBeGreaterThan(0);

    expect(typeof metrics.heap_used_mb).toBe('number');
    expect(typeof metrics.heap_total_mb).toBe('number');

    expect(metrics.active_sessions).toBe(5);

    expect(typeof metrics.uptime_seconds).toBe('number');
    expect(metrics.uptime_seconds).toBeGreaterThanOrEqual(0);

    expect(typeof metrics.error_count).toBe('number');
  });
});
