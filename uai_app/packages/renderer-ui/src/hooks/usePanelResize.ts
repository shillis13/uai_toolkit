/**
 * usePanelResize — a shared draggable horizontal-resize hook for left/right panels,
 * persisted to AppState.panelSizes (survives reload). Generalizes the inline logic
 * that ContextPanel/ProjectEditor each had: on mousedown it captures the start width,
 * tracks the pointer on window listeners, clamps to [min, max], and writes the new
 * width back through updateAppState.
 *
 * `edge` is which edge of the panel the handle lives on:
 *   - 'right' (default): a LEFT panel resized from its right edge — drag right widens.
 *   - 'left':            a RIGHT panel resized from its left edge — drag left widens.
 *
 * Returns the current width (px, falling back to `def` if the persisted value is
 * missing — older saved state won't have the newer keys) and an onMouseDown to wire
 * onto the handle element.
 */
import { useCallback } from 'react';
import type { AppState } from '@uai/shared/types';
import { useAppStateStore } from '../stores';

type PanelSizeKey = keyof AppState['panelSizes'];

export interface PanelResizeOptions {
  /** Default width if no persisted value exists yet (px). */
  def: number;
  /** Clamp bounds (px). `max` may be a function evaluated at drag time so it can scale
   *  with the window (e.g. `() => window.innerWidth * 0.5`). */
  min: number;
  max: number | (() => number);
  /** Which edge the handle sits on. Default 'right' (left panel). */
  edge?: 'left' | 'right';
}

export function usePanelResize(
  key: PanelSizeKey,
  opts: PanelResizeOptions,
): { width: number; onMouseDown: (e: React.MouseEvent) => void } {
  const { appState, updateAppState } = useAppStateStore();
  const width = appState.panelSizes[key] ?? opts.def;

  const onMouseDown = useCallback((e: React.MouseEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startWidth = appState.panelSizes[key] ?? opts.def;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    const onMove = (ev: MouseEvent) => {
      const delta = opts.edge === 'left' ? startX - ev.clientX : ev.clientX - startX;
      const maxPx = typeof opts.max === 'function' ? opts.max() : opts.max;
      const next = Math.max(opts.min, Math.min(startWidth + delta, maxPx));
      updateAppState({ panelSizes: { ...appState.panelSizes, [key]: next } });
    };
    const onUp = () => {
      document.body.style.cursor = '';
      document.body.style.userSelect = '';
      window.removeEventListener('mousemove', onMove);
      window.removeEventListener('mouseup', onUp);
    };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
  }, [key, opts.def, opts.min, opts.max, opts.edge, appState.panelSizes, updateAppState]);

  return { width, onMouseDown };
}
