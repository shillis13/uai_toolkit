/**
 * paths.ts — the single source of truth for AI_ROOT resolution and child-process
 * environment in the Electron main process. The TypeScript twin of Python's
 * `ai_general/scripts/utils/paths.py`, reconciled with Noctis's env-var model.
 *
 * Replaces ~17 hand-rolled getAiRoot()/getAiRootMain() copies (which had 4
 * divergent precedence formulas) and the ~41 inline /opt/homebrew PATH fragments.
 * Import from here; never inline a root formula or a bin dir again.
 *
 * Semantics (match paths.py exactly):
 *   AI_ROOT       = current root; inside a devTree this IS the devTree.
 *   AI_ROOT_MAIN  = canonical production main; independent var, DEFAULTS to the
 *                   resolved AI_ROOT (paths.py: _v("AI_ROOT_MAIN", AI_ROOT)).
 *                   Normal install: AI_ROOT_MAIN == AI_ROOT. In a devTree the
 *                   devTree tooling sets $AI_ROOT_MAIN to the production main.
 *
 * Precedence today: env var > default. The config.toml layer (env > [paths] toml >
 * default) from the shared design is DEFERRED until the app takes a TOML parser
 * dep — none of the current root call sites read config.toml, so this is faithful.
 * See uai_toolkit/docs/design_ts_paths_pattern.md.
 */
import * as os from 'node:os';
import * as path from 'node:path';

const home = (): string => os.homedir();

/** Current root — inside a devTree this is the devTree. */
export function aiRoot(): string {
  return process.env.AI_ROOT || path.join(home(), 'AI', 'ai_root');
}

/** Canonical MAIN root — independent var, defaults to the resolved AI_ROOT.
 *  Mirrors paths.py `AI_ROOT_MAIN = _v("AI_ROOT_MAIN", AI_ROOT)`, i.e.
 *  AI_ROOT_MAIN > AI_ROOT > default. */
export function aiRootMain(): string {
  return process.env.AI_ROOT_MAIN || aiRoot();
}

/** Derived accessors — default under the CURRENT root, env-overridable. Call
 *  sites that need production data keep their aiRootMain()-anchored inline joins. */
const v = (name: string, def: string): string => process.env[name] || def;
export const aiData = (): string => v('AI_DATA', path.join(aiRoot(), 'ai_general', 'data'));
export const aiScripts = (): string => v('AI_SCRIPTS', path.join(aiRoot(), 'ai_general', 'scripts'));
export const aiContextFiles = (): string => v('AI_CONTEXT_FILES', path.join(aiRoot(), 'ai_general', 'ai_context_files'));

/** Platform-appropriate fallback bin dirs — the ONE place a bin dir is named.
 *  Mirrors Python's lib_session_substrate._FALLBACK_BINARY_DIRS + a Linux/WSL arm. */
function fallbackBinDirs(): string[] {
  const h = home();
  if (process.platform === 'darwin') {
    return ['/opt/homebrew/bin', '/opt/homebrew/sbin', '/usr/local/bin', '/usr/local/sbin',
            path.join(h, '.local/bin'), path.join(h, '.npm-global/bin'),
            '/usr/bin', '/bin', '/usr/sbin', '/sbin'];
  }
  // linux / wsl (windows-native handled when it arrives)
  return ['/home/linuxbrew/.linuxbrew/bin', '/usr/local/bin', '/usr/bin', '/bin',
          path.join(h, '.local/bin')];
}

/** A PATH that prepends the caller's PATH (their prefs win) then appends the
 *  platform fallback dirs, de-duplicated. Replaces every getPythonPath()/
 *  buildShellPath() copy and the inline "/opt/homebrew/bin:..." strings. */
export function shellPath(): string {
  const sep = process.platform === 'win32' ? ';' : ':';
  const dirs = [...(process.env.PATH ? process.env.PATH.split(sep) : []), ...fallbackBinDirs()];
  const seen = new Set<string>();
  const out: string[] = [];
  for (const d of dirs) {
    if (d && !seen.has(d)) { seen.add(d); out.push(d); }
  }
  return out.join(sep);
}

/** Child-process env: caller's env + a healthy PATH + AI_ROOT/AI_ROOT_MAIN.
 *  The single Windows/PATH seam for spawned Python/rg/etc. */
export function buildChildEnv(extra: Record<string, string> = {}): Record<string, string> {
  return {
    ...process.env,
    AI_ROOT: aiRoot(),
    AI_ROOT_MAIN: aiRootMain(),
    PATH: shellPath(),
    ...extra,
  } as Record<string, string>;
}
