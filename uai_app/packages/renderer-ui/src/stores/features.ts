/**
 * Feature flags — enable/disable UI components via configuration.
 *
 * The first use case is HIDING not-ready surfaces (Projects/Teams, Web UIs, and
 * Games Navigator tabs; the Session Work subtab) so they don't ship half-baked.
 * Each flag has a sensible default; the user can override any of them from
 * Settings → Features. Overrides persist in localStorage and take effect live
 * (components subscribe via useFeature / useFeatureFlags).
 *
 * A flag being OFF means "hide the surface"; a component reads the flag and
 * renders nothing (and, where relevant, falls back so a hidden-but-active view
 * doesn't strand the user).
 */

import { useEffect, useState } from 'react';

export interface FeatureFlag {
  key: string;
  label: string;
  description: string;
  /** Default when the user hasn't set an override. */
  defaultEnabled: boolean;
  /** Optional grouping for the Settings UI. */
  group?: string;
}

// The registry. Not-ready surfaces default to OFF (hidden) per the first use case.
export const FEATURES: FeatureFlag[] = [
  { key: 'nav.projectsTeams', label: 'Projects / Teams tab', description: 'Navigator tab for Projects and Teams.', defaultEnabled: false, group: 'Navigator' },
  { key: 'nav.webUis', label: 'Web UIs tab', description: 'Navigator tab for web-based AI UIs.', defaultEnabled: false, group: 'Navigator' },
  { key: 'nav.games', label: 'Games tab', description: 'Navigator tab for Games (e.g. Axis & Allies).', defaultEnabled: false, group: 'Navigator' },
  { key: 'session.workSubtab', label: 'Session Work subtab', description: "The Work view on a session tab (this session's worker page).", defaultEnabled: false, group: 'Session' },
];

const FEATURES_BY_KEY: Record<string, FeatureFlag> = Object.fromEntries(FEATURES.map((f) => [f.key, f]));

const STORAGE_KEY = 'uai:featureFlags';
const listeners = new Set<() => void>();

/** Load the persisted override map (key → boolean). Missing keys use the default. */
function loadOverrides(): Record<string, boolean> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw) as Record<string, boolean>;
  } catch { /* ignore */ }
  return {};
}

let overrides: Record<string, boolean> = loadOverrides();

function persist(): void {
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(overrides)); } catch { /* ignore */ }
}

/** Resolve whether a feature is enabled (override wins over default). Unknown
 *  keys resolve to true so a mis-typed flag never silently hides a surface. */
export function isFeatureEnabled(key: string): boolean {
  if (key in overrides) return overrides[key];
  const def = FEATURES_BY_KEY[key];
  return def ? def.defaultEnabled : true;
}

/** Set (or clear) an override and notify subscribers. Passing the default value
 *  still records an explicit override — call resetFeature to revert to default. */
export function setFeatureEnabled(key: string, enabled: boolean): void {
  overrides = { ...overrides, [key]: enabled };
  persist();
  for (const fn of listeners) fn();
}

/** Revert a feature to its registry default (drops the override). */
export function resetFeature(key: string): void {
  if (!(key in overrides)) return;
  const next = { ...overrides };
  delete next[key];
  overrides = next;
  persist();
  for (const fn of listeners) fn();
}

/** Snapshot of every flag with its resolved value (for the Settings UI). */
export function getResolvedFeatures(): Array<FeatureFlag & { enabled: boolean; overridden: boolean }> {
  return FEATURES.map((f) => ({ ...f, enabled: isFeatureEnabled(f.key), overridden: f.key in overrides }));
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** React hook: subscribe to a single flag. Re-renders when it changes. */
export function useFeature(key: string): boolean {
  const [, force] = useState(0);
  useEffect(() => subscribe(() => force((n) => n + 1)), []);
  return isFeatureEnabled(key);
}

/** React hook: the full resolved list + a setter, for the Settings panel. */
export function useFeatureFlags(): {
  features: Array<FeatureFlag & { enabled: boolean; overridden: boolean }>;
  setEnabled: (key: string, enabled: boolean) => void;
  reset: (key: string) => void;
} {
  const [, force] = useState(0);
  useEffect(() => subscribe(() => force((n) => n + 1)), []);
  return { features: getResolvedFeatures(), setEnabled: setFeatureEnabled, reset: resetFeature };
}
