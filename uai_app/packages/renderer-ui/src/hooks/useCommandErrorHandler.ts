import { useRef, useCallback } from 'react';
import type { RefObject } from 'react';

const ERROR_CLEAR_MS = 5000;
const ERROR_CLASS = 'command-error';

export interface CommandErrorHandler {
  setFieldError: (field: string, message: string) => void;
  clearFieldError: (field: string) => void;
}

export function useCommandErrorHandler(opts: {
  fields: Record<string, RefObject<HTMLElement | null>>;
}): CommandErrorHandler {
  const timersRef = useRef<Map<string, ReturnType<typeof setTimeout>>>(new Map());

  const clearFieldError = useCallback((field: string) => {
    const ref = opts.fields[field];
    const el = ref?.current;
    if (el) {
      el.classList.remove(ERROR_CLASS);
      el.removeAttribute('data-error-message');
    }
    const timer = timersRef.current.get(field);
    if (timer) {
      clearTimeout(timer);
      timersRef.current.delete(field);
    }
  }, [opts.fields]);

  const setFieldError = useCallback((field: string, message: string) => {
    const ref = opts.fields[field];
    const el = ref?.current;
    if (!el) return;

    el.classList.add(ERROR_CLASS);
    el.setAttribute('data-error-message', message);

    const existingTimer = timersRef.current.get(field);
    if (existingTimer) clearTimeout(existingTimer);

    const timer = setTimeout(() => clearFieldError(field), ERROR_CLEAR_MS);
    timersRef.current.set(field, timer);

    const onInteract = () => {
      clearFieldError(field);
      el.removeEventListener('input', onInteract);
      el.removeEventListener('focus', onInteract);
    };
    el.addEventListener('input', onInteract);
    el.addEventListener('focus', onInteract);
  }, [opts.fields, clearFieldError]);

  return { setFieldError, clearFieldError };
}
