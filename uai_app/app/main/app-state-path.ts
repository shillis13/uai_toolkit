/**
 * Single source of truth for the app_state.json location (tabs, activeTabId,
 * sessionPrefs — the writable UI state).
 *
 * `UAI_APP_STATE_PATH` overrides it. A second/test instance launched with this
 * env var keeps its UI state in an isolated file, so its tab operations never
 * write the user's shared app_state.json. Without this, two instances sharing
 * the same AI_ROOT_MAIN share one app_state.json, and one instance switching
 * tabs makes the other instance follow (cross-instance tab bleed-over).
 */
import * as path from 'node:path';
import * as os from 'node:os';

export function getAppStatePath(): string {
  if (process.env.UAI_APP_STATE_PATH) return process.env.UAI_APP_STATE_PATH;
  const aiRoot = process.env.AI_ROOT_MAIN || process.env.AI_ROOT || path.join(os.homedir(), 'AI/ai_root');
  return path.join(aiRoot, 'ai_general', 'data', 'app_state.json');
}
