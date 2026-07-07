/**
 * useViewport — React hook for viewport reporting.
 *
 * Register a viewport reporter for this component.
 * The reporter is called on-demand when describeViewport() is invoked.
 * Zero runtime cost otherwise. Callers do NOT need to useCallback.
 */

import { useRef, useEffect } from 'react';
import { ViewportRegistry } from './viewport-registry';
import type { ViewportReporter } from '@contracts/viewport';

export function useViewport(id: string, reporter: ViewportReporter): void {
  const reporterRef = useRef(reporter);
  reporterRef.current = reporter;

  useEffect(() => {
    const stableReporter: ViewportReporter = () => reporterRef.current();
    ViewportRegistry.register(id, stableReporter);
    return () => ViewportRegistry.unregister(id);
  }, [id]);
}
