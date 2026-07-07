/**
 * Global type declarations for the UAI renderer.
 */

import type { UaiApi } from '../main/preload';

declare global {
  interface Window {
    uai: UaiApi;
  }
}
