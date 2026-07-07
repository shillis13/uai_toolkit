/**
 * Contract Test: Command Bus
 *
 * Quality Gate 1D.3 — validates that the command bus has the expected
 * command types registered and that the hook system works correctly.
 */

import { describe, it, expect, beforeEach } from 'vitest';
import { CommandBus, createCommand } from '../main/command-bus';

describe('CommandBus contract tests', () => {
  let bus: CommandBus;

  beforeEach(() => {
    bus = new CommandBus();
  });

  it('registers and executes a command handler', async () => {
    bus.register('test.echo', async (cmd) => ({
      ok: true,
      command_id: cmd.id,
      data: cmd.payload,
    }));

    const cmd = createCommand('test.echo', { message: 'hello' });
    const result = await bus.execute(cmd);

    expect(result.ok).toBe(true);
    expect(result.data).toEqual({ message: 'hello' });
  });

  it('returns error for unregistered command type', async () => {
    const cmd = createCommand('nonexistent.command', {});
    const result = await bus.execute(cmd);

    expect(result.ok).toBe(false);
    expect(result.error?.code).toBe('NO_HANDLER');
  });

  it('runs before hooks and can abort execution', async () => {
    let handlerCalled = false;

    bus.register('test.blocked', async (cmd) => {
      handlerCalled = true;
      return { ok: true, command_id: cmd.id };
    });

    bus.before('test.*', async () => ({
      ok: false,
      command_id: 'hook',
      error: { code: 'BLOCKED', message: 'Blocked by before hook' },
    }));

    const cmd = createCommand('test.blocked', {});
    const result = await bus.execute(cmd);

    expect(result.ok).toBe(false);
    expect(result.error?.code).toBe('BLOCKED');
    expect(handlerCalled).toBe(false);
  });

  it('runs after hooks after handler execution with result and duration', async () => {
    let afterCalled = false;
    let receivedResult: unknown = null;
    let receivedDuration: number | null = null;

    bus.register('test.logged', async (cmd) => ({
      ok: true,
      command_id: cmd.id,
    }));

    bus.after('*', async (_cmd, result, durationMs) => {
      afterCalled = true;
      receivedResult = result;
      receivedDuration = durationMs;
    });

    const cmd = createCommand('test.logged', {});
    await bus.execute(cmd);

    expect(afterCalled).toBe(true);
    expect(receivedResult).not.toBeNull();
    expect((receivedResult as { ok: boolean }).ok).toBe(true);
    expect(typeof receivedDuration).toBe('number');
    expect(receivedDuration).toBeGreaterThanOrEqual(0);
  });

  it('after hooks receive error results for failed commands', async () => {
    let receivedResult: unknown = null;

    bus.register('test.fail', async () => {
      throw new Error('boom');
    });

    bus.after('*', async (_cmd, result) => {
      receivedResult = result;
    });

    const cmd = createCommand('test.fail', {});
    await bus.execute(cmd);

    expect((receivedResult as { ok: boolean }).ok).toBe(false);
    expect((receivedResult as { error?: { code: string } }).error?.code).toBe('HANDLER_ERROR');
  });

  it('after hook errors do not propagate to caller', async () => {
    bus.register('test.ok', async (cmd) => ({
      ok: true,
      command_id: cmd.id,
      data: 'success',
    }));

    bus.after('*', async () => {
      throw new Error('hook exploded');
    });

    const cmd = createCommand('test.ok', {});
    const result = await bus.execute(cmd);

    // Caller still gets the successful result despite hook failure
    expect(result.ok).toBe(true);
    expect(result.data).toBe('success');
  });

  it('logs command execution with duration', async () => {
    bus.register('test.timed', async (cmd) => ({
      ok: true,
      command_id: cmd.id,
    }));

    const cmd = createCommand('test.timed', {});
    await bus.execute(cmd);

    const log = bus.getLog();
    expect(log.length).toBe(1);
    expect(log[0].type).toBe('test.timed');
    expect(log[0].ok).toBe(true);
    expect(typeof log[0].duration_ms).toBe('number');
    expect(log[0].duration_ms).toBeGreaterThanOrEqual(0);
  });

  it('listTypes() returns registered command types', () => {
    bus.register('session.update', async (cmd) => ({ ok: true, command_id: cmd.id }));
    bus.register('session.create', async (cmd) => ({ ok: true, command_id: cmd.id }));
    bus.register('folder.create', async (cmd) => ({ ok: true, command_id: cmd.id }));

    const types = bus.listTypes();
    expect(types).toContain('session.update');
    expect(types).toContain('session.create');
    expect(types).toContain('folder.create');
  });

  it('hasHandler() returns correct values', () => {
    bus.register('session.update', async (cmd) => ({ ok: true, command_id: cmd.id }));

    expect(bus.hasHandler('session.update')).toBe(true);
    expect(bus.hasHandler('nonexistent')).toBe(false);
  });

  it('catches handler errors and returns error result', async () => {
    bus.register('test.crash', async () => {
      throw new Error('Intentional crash');
    });

    const cmd = createCommand('test.crash', {});
    const result = await bus.execute(cmd);

    expect(result.ok).toBe(false);
    expect(result.error?.code).toBe('HANDLER_ERROR');
    expect(result.error?.message).toContain('Intentional crash');
  });

  it('glob pattern matching works for before/after hooks', async () => {
    const matched: string[] = [];

    bus.register('session.update', async (cmd) => ({ ok: true, command_id: cmd.id }));
    bus.register('folder.create', async (cmd) => ({ ok: true, command_id: cmd.id }));

    bus.after('session.*', async (cmd, _result, _durationMs) => { matched.push(cmd.type); });

    await bus.execute(createCommand('session.update', {}));
    await bus.execute(createCommand('folder.create', {}));

    expect(matched).toEqual(['session.update']);
    expect(matched).not.toContain('folder.create');
  });

  it('bounds log to 500 entries max', async () => {
    bus.register('test.bulk', async (cmd) => ({ ok: true, command_id: cmd.id }));

    for (let i = 0; i < 600; i++) {
      await bus.execute(createCommand('test.bulk', { i }));
    }

    const log = bus.getLog();
    expect(log.length).toBeLessThanOrEqual(500);
  });
});

describe('createCommand factory', () => {
  it('creates a command with all required fields', () => {
    const cmd = createCommand('session.update', { trackingId: 'test123' });

    expect(cmd.type).toBe('session.update');
    expect(cmd.payload).toEqual({ trackingId: 'test123' });
    expect(cmd.origin).toBe('user'); // default
    expect(cmd.id).toBeTypeOf('string');
    expect(cmd.id.length).toBeGreaterThan(0);
    expect(cmd.timestamp).toBeTypeOf('string');
  });

  it('accepts custom origin', () => {
    const cmd = createCommand('test.cmd', {}, 'internal');
    expect(cmd.origin).toBe('internal');
  });
});
