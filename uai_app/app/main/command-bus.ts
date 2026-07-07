/**
 * CommandBus — main process command dispatcher.
 *
 * All domain mutations route through this bus. Commands have typed handlers,
 * before/after hooks with glob-pattern matching, and structured results.
 *
 * Architecture:
 *   Path 1 (outbound): renderer dispatches command → IPC → CommandBus.execute()
 *                       → handler → store mutation → CommandResult
 *
 * The bus is the single entry point for all write operations.
 * Read-only queries bypass the bus (direct IPC for now).
 */

import type { Command, CommandResult } from '@uai/shared/types';
import { randomUUID } from 'node:crypto';

// ─── Types ────────────────────────────────────────────────────────────────

export type CommandHandler<P = Record<string, unknown>, T = unknown> =
  (command: Command<P>) => Promise<CommandResult<T>>;

export type BeforeHookFn = (command: Command) => Promise<void | CommandResult>;
export type AfterHookFn = (command: Command, result: CommandResult, durationMs: number) => Promise<void>;

interface BeforeHookEntry {
  pattern: string;
  fn: BeforeHookFn;
}

interface AfterHookEntry {
  pattern: string;
  fn: AfterHookFn;
}

interface CommandLog {
  command_id: string;
  type: string;
  origin: string;
  timestamp: string;
  duration_ms: number;
  ok: boolean;
  error_code?: string;
}

// ─── Glob Matching ────────────────────────────────────────────────────────

/**
 * Match a command type against a glob pattern.
 * Supports: '*' (match everything), 'session.*' (prefix match), exact match.
 */
function matchPattern(pattern: string, commandType: string): boolean {
  if (pattern === '*') return true;
  if (pattern === commandType) return true;

  // Convert glob to regex: 'session.*' → /^session\..*$/
  // Replace '*' with a placeholder first, then escape regex chars, then restore
  const placeholder = '\x00GLOB\x00';
  const withPlaceholder = pattern.replace(/\*/g, placeholder);
  const escaped = withPlaceholder.replace(/[.+^${}()|[\]\\]/g, '\\$&');
  const regexStr = escaped.replace(new RegExp(placeholder.replace(/\x00/g, '\\x00'), 'g'), '.*');
  const regex = new RegExp(`^${regexStr}$`);
  return regex.test(commandType);
}

// ─── CommandBus ───────────────────────────────────────────────────────────

export class CommandBus {
  private handlers = new Map<string, CommandHandler>();
  private beforeHooks: BeforeHookEntry[] = [];
  private afterHooks: AfterHookEntry[] = [];
  private log: CommandLog[] = [];

  /**
   * Register a command handler for a specific command type.
   * Only one handler per type — last registration wins.
   */
  register<P = Record<string, unknown>, T = unknown>(
    type: string,
    handler: CommandHandler<P, T>,
  ): void {
    this.handlers.set(type, handler as CommandHandler);
  }

  /**
   * Add a pre-execution hook. Runs before the handler.
   * If hook returns a CommandResult with ok=false, execution is aborted.
   * Pattern supports globs: '*', 'session.*', exact match.
   */
  before(pattern: string, fn: BeforeHookFn): void {
    this.beforeHooks.push({ pattern, fn });
  }

  /**
   * Add a post-execution hook. Runs after the handler completes.
   * After-hooks are observers only — they receive the result but cannot modify it.
   * Errors in after-hooks are logged but never propagate to the caller.
   * Pattern supports globs: '*', 'session.*', exact match.
   */
  after(pattern: string, fn: AfterHookFn): void {
    this.afterHooks.push({ pattern, fn });
  }

  /**
   * Execute a command through the bus.
   *
   * Flow: before hooks → handler → after hooks → result
   * If no handler is registered, returns an error result.
   */
  async execute<T = unknown>(command: Command): Promise<CommandResult<T>> {
    const start = Date.now();

    // Ensure command has an ID
    if (!command.id) {
      command.id = randomUUID();
    }

    // Run before hooks
    for (const hook of this.beforeHooks) {
      if (matchPattern(hook.pattern, command.type)) {
        const hookResult = await hook.fn(command);
        if (hookResult && !hookResult.ok) {
          this.logCommand(command, hookResult as CommandResult, Date.now() - start);
          return hookResult as CommandResult<T>;
        }
      }
    }

    // Find and run handler
    const handler = this.handlers.get(command.type);
    if (!handler) {
      const result: CommandResult<T> = {
        ok: false,
        command_id: command.id,
        error: {
          code: 'NO_HANDLER',
          message: `No handler registered for command type: ${command.type}`,
        },
      };
      this.logCommand(command, result, Date.now() - start);
      return result;
    }

    let result: CommandResult<T>;
    try {
      result = await handler(command) as CommandResult<T>;
    } catch (err: unknown) {
      const message = err instanceof Error ? err.message : String(err);
      result = {
        ok: false,
        command_id: command.id,
        error: { code: 'HANDLER_ERROR', message },
      };
    }

    const durationMs = Date.now() - start;

    // Log command before after hooks
    this.logCommand(command, result, durationMs);

    // Run after hooks — observers only, errors are logged but never propagate
    for (const hook of this.afterHooks) {
      if (matchPattern(hook.pattern, command.type)) {
        try {
          await hook.fn(command, result, durationMs);
        } catch (hookErr: unknown) {
          const msg = hookErr instanceof Error ? hookErr.message : String(hookErr);
          console.error(`[CommandBus] after-hook error for "${command.type}": ${msg}`);
        }
      }
    }

    return result;
  }

  /**
   * Check if a handler is registered for a command type.
   */
  hasHandler(type: string): boolean {
    return this.handlers.has(type);
  }

  /**
   * List all registered command types.
   */
  listTypes(): string[] {
    return Array.from(this.handlers.keys());
  }

  /**
   * Get the command execution log.
   */
  getLog(): ReadonlyArray<CommandLog> {
    return this.log;
  }

  /**
   * Clear the command log.
   */
  clearLog(): void {
    this.log = [];
  }

  private logCommand(command: Command, result: CommandResult, duration_ms: number): void {
    this.log.push({
      command_id: command.id,
      type: command.type,
      origin: command.origin,
      timestamp: command.timestamp,
      duration_ms,
      ok: result.ok,
      error_code: result.error?.code,
    });

    // Keep log bounded (last 500 entries)
    if (this.log.length > 500) {
      this.log = this.log.slice(-500);
    }
  }
}

// ─── Command Factory ──────────────────────────────────────────────────────

/**
 * Create a command envelope with defaults filled in.
 */
export function createCommand<P = Record<string, unknown>>(
  type: string,
  payload: P,
  origin: Command['origin'] = 'user',
): Command<P> {
  return {
    id: randomUUID(),
    type,
    payload,
    origin,
    timestamp: new Date().toISOString(),
  };
}
