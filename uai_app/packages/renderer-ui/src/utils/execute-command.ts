import type { CommandResult } from '@uai/shared/types';
import type { CommandErrorHandler } from '../hooks/useCommandErrorHandler';

type FailurePolicy = 'toast' | 'inline' | 'log' | 'silent';

interface ExecuteOpts {
  errorHandler?: CommandErrorHandler;
  field?: string;
  onFailure?: FailurePolicy;
  toastFn?: (message: string, type?: 'error' | 'info' | 'warning') => void;
}

export async function executeCommand<T = unknown>(
  type: string,
  payload: Record<string, unknown>,
  opts?: ExecuteOpts,
): Promise<CommandResult<T>> {
  const result = await window.uai.execute({
    id: crypto.randomUUID(),
    type,
    payload,
    origin: 'user',
    timestamp: new Date().toISOString(),
  }) as CommandResult<T>;

  if (!result.ok) {
    const message = result.error?.message || 'Command failed';
    const policy = opts?.onFailure || 'log';

    switch (policy) {
      case 'toast':
        if (opts?.toastFn) {
          opts.toastFn(message, 'error');
        } else {
          console.error(`[executeCommand] ${type}: ${message}`);
        }
        break;
      case 'inline':
        if (opts?.errorHandler && opts?.field) {
          opts.errorHandler.setFieldError(opts.field, message);
        } else if (opts?.toastFn) {
          opts.toastFn(message, 'error');
        } else {
          console.error(`[executeCommand] ${type}: ${message}`);
        }
        break;
      case 'log':
        console.error(`[executeCommand] ${type}: ${message}`);
        break;
      case 'silent':
        break;
    }
  }

  return result;
}
