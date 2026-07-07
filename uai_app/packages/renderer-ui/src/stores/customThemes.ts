/**
 * Custom themes — "save current colors & fonts as a new theme".
 *
 * A custom theme is a snapshot of every design token currently resolved on
 * <html> (all the --bg-*, --text-*, --accent-*, --font-*, --size-* CSS custom
 * properties) plus the appearance/font prefs. Because it's read via
 * getComputedStyle, it captures whatever is live — the active built-in theme,
 * plus any inline/devtools overrides. Applying a custom theme sets those tokens
 * inline on <html>; switching away clears them.
 *
 * Persisted in localStorage. Built-in themes still live in themes.css and are
 * selected via [data-theme]; custom themes are the runtime-inline variety.
 */

import type { AppearancePrefs } from '@uai/shared/types';

export interface CustomTheme {
  name: string;
  tokens: Record<string, string>;
  fonts: AppearancePrefs | null;
  created: string;
}

const STORE_KEY = 'uai:customThemes';
// Prefix used in the theme <select> value to distinguish custom from built-in.
export const CUSTOM_PREFIX = 'custom:';

// Track which token props we set inline for the active custom theme, so we can
// cleanly remove exactly those when switching to another theme.
let appliedTokenKeys: string[] = [];

/** All design-token custom-property NAMES declared on :root, across stylesheets. */
function tokenNames(): string[] {
  const names = new Set<string>();
  for (const sheet of Array.from(document.styleSheets)) {
    let rules: CSSRuleList;
    try { rules = sheet.cssRules; } catch { continue; } // cross-origin — skip
    for (const rule of Array.from(rules)) {
      if (rule instanceof CSSStyleRule && rule.selectorText && rule.selectorText.split(',').some((s) => s.trim() === ':root')) {
        for (const prop of Array.from(rule.style)) {
          if (prop.startsWith('--')) names.add(prop);
        }
      }
    }
  }
  return Array.from(names);
}

/** Snapshot the resolved value of every :root token as currently applied. */
export function snapshotTokens(): Record<string, string> {
  const cs = getComputedStyle(document.documentElement);
  const out: Record<string, string> = {};
  for (const name of tokenNames()) {
    const v = cs.getPropertyValue(name).trim();
    if (v) out[name] = v;
  }
  return out;
}

function loadAll(): Record<string, CustomTheme> {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    if (raw) return JSON.parse(raw) as Record<string, CustomTheme>;
  } catch { /* ignore */ }
  return {};
}
function persist(all: Record<string, CustomTheme>): void {
  try { localStorage.setItem(STORE_KEY, JSON.stringify(all)); } catch { /* ignore */ }
}

/** List saved custom themes (newest first). */
export function listCustomThemes(): CustomTheme[] {
  return Object.values(loadAll()).sort((a, b) => (b.created || '').localeCompare(a.created || ''));
}

export function getCustomTheme(name: string): CustomTheme | null {
  return loadAll()[name] || null;
}

/** Save the current live colors + fonts as a named custom theme (overwrites a
 *  same-named one). `createdAt` is passed in because Date.now() isn't available
 *  in every context; callers stamp it. */
export function saveCurrentAsTheme(name: string, fonts: AppearancePrefs | null, createdAt: string): CustomTheme {
  const theme: CustomTheme = { name, tokens: snapshotTokens(), fonts, created: createdAt };
  const all = loadAll();
  all[name] = theme;
  persist(all);
  return theme;
}

export function removeCustomTheme(name: string): void {
  const all = loadAll();
  if (name in all) { delete all[name]; persist(all); }
}

/** Remove the inline token overrides set by the last applied custom theme. */
export function clearAppliedTokens(): void {
  const root = document.documentElement;
  for (const key of appliedTokenKeys) root.style.removeProperty(key);
  appliedTokenKeys = [];
}

/** Apply a custom theme: clear any prior inline tokens, then set this theme's.
 *  Also clears [data-theme] so a built-in doesn't shadow the inline values. */
export function applyCustomTheme(name: string): CustomTheme | null {
  const theme = getCustomTheme(name);
  if (!theme) return null;
  clearAppliedTokens();
  delete document.documentElement.dataset.theme;
  const root = document.documentElement;
  const keys: string[] = [];
  for (const [k, v] of Object.entries(theme.tokens)) {
    root.style.setProperty(k, v);
    keys.push(k);
  }
  appliedTokenKeys = keys;
  return theme;
}
