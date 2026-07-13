# Design: `paths.ts` — the TypeScript twin of `paths.py`

Status: **standard / reference impl** — reconciled with Noctis (owner of the Python
env-var model) on 2026-07-12; `AI_ROOT_MAIN` promotion **approved by PianoMan
2026-07-12** (Noctis landing it in `paths.py`/`ai_env.sh`). Not landed in the app —
the uai_app owner integrates it and migrates the ~17 call sites. See §1.

## Problem

uai_app (`app/main/*`) has **no path pattern**: 17 hand-rolled `getAiRoot()` copies,
4 divergent precedence formulas, and 41 hardcoded `/opt/homebrew/*` fragments. This is
the same disease `paths.py` already cured on the Python side — the app just never got
the twin. `paths.ts` is that twin: **one module, one definition, imported everywhere.**

## The shared default map (single source of truth)

All three surfaces — `paths.py`, `ai_env.sh`, `paths.ts` — MUST resolve these
identically for a given `AI_ROOT`. Noctis is adding this map to a shared doc so no
surface drifts.

**Terms.** *Derived* = defaults under `AI_ROOT` but independently overridable.
*Independent* = never derived from `AI_ROOT` (a devTree can point elsewhere).

| Var | Kind | Default |
|---|---|---|
| `AI_ROOT` | anchor | env `AI_ROOT` → platform default (`~/AI/ai_root`) |
| `AI_ROOT_MAIN` | **independent** | env `AI_ROOT_MAIN` → `[paths]` toml → `~/AI/ai_root` |
| `AI_DATA` | derived | `AI_ROOT/ai_general/data` |
| `AI_SCRIPTS` | derived | `AI_ROOT/ai_general/scripts` |
| `AI_BIN` | derived | `AI_ROOT/ai_general/apps` (apps dir, **not** scripts) |
| `AI_LOGS` | derived | `AI_ROOT/ai_general/logs` |
| `AI_HOOKS` | derived | `AI_DATA/hooks` |
| `AI_UAI_APP` | derived | `AI_BIN/uai` (derives from `AI_BIN`) |
| `AI_CONTEXT_FILES` | derived | `AI_ROOT/ai_general/ai_context_files` |
| `AI_JSONL` | independent | `~/.claude/projects` (caller appends project slug) |
| `AI_PYTHON` | independent | installer-resolved interpreter (config.toml/env) |

Precedence for every var: **explicit env var > `config.toml` `[paths]` table > default.**
`config.toml` is in the chain so the resolver works **shell-less** — which is exactly
why the Electron app needs it: it can't source `ai_env.sh` (same reason native Windows
can't). `AI_CONFIG` env overrides the config file location (default `AI_ROOT/config.toml`).

## Config schema (corrected per Noctis)

`config.toml` is **not flat**. The AI_* vars live under a `[paths]` table; free-form
keys live at the top level and are read via `get("dotted.key")`:

```toml
[paths]
AI_DATA = "/custom/data"     # UPPER or lower accepted within [paths]
ai_python = "/opt/venv/bin/python"

[file_access]
db_path = "..."              # reached via get("file_access.db_path")
```

- AI_* resolution: `env > _CFG["paths"][NAME] > _CFG["paths"][name.lower()] > default`.
- `get(dotted, default)`: walks the **whole** doc for arbitrary keys.

## §1 — `AI_ROOT_MAIN` (APPROVED — now part of the shared model)

`paths.py` has no `AI_ROOT_MAIN`: it answers "the CURRENT root," which *inside a
devTree is the devTree*. But the app needs "the canonical MAIN root even from inside a
devTree" (14/17 files). Today that concept is scattered in Python too
(`cli/lib_cli_common.py`, `devTrees/*`) — the same disease as the app copies.

**Noctis's recommendation (I concur):** promote `AI_ROOT_MAIN` into the shared model as
an **independent** var (`env > [paths] toml > default ~/AI/ai_root`). Inside a devTree,
`AI_ROOT` = the devTree and `AI_ROOT_MAIN` = the production main — genuinely
independent, so it cannot derive. One definition unifies Python + shell + TS and
retires the scatter.

**PianoMan approved this (option a) on 2026-07-12.** Noctis is landing `AI_ROOT_MAIN`
as an independent var in `paths.py`/`ai_env.sh`; `paths.ts` (below) already uses it,
and the shared default-map doc becomes the one definition all three surfaces cite —
retiring the Python scatter (`cli/lib_cli_common.py`, `devTrees/*`).

## §4 — `buildChildEnv()` / `resolveBin()`

Kills the 41 `/opt/homebrew/*` fragments. Children get the interpreter via `AI_PYTHON`;
PATH = `dirname(AI_PYTHON)` + the same fallback bin dirs Python already enumerates in
`lib_session_substrate._FALLBACK_BINARY_DIRS`, plus a Linux/WSL arm:

- mac: `/opt/homebrew/bin`, `/opt/homebrew/sbin`, `/usr/local/bin`, `~/.local/bin`, `~/.npm-global/bin`
- linux/wsl: `/home/linuxbrew/.linuxbrew/bin`, `/usr/local/bin`, `/usr/bin`, `~/.local/bin`

## §5 — Anti-drift

`paths.ts` carries its **own** test asserting the default map above for a fixed
`AI_ROOT` (not bolted onto the Python `test_paths_consistency.py`). The durable guard is
the shared default-map doc all three cite; an optional CI step can run all three
surfaces for one `AI_ROOT` and diff the resolved values.

## Reference implementation (app/main/paths.ts)

```ts
import * as os from 'node:os';
import * as path from 'node:path';
import * as fs from 'node:fs';
// TOML parse: Electron is shell-less, so we read config.toml directly.
// Needs a small TOML dep (e.g. smol-toml / @iarna/toml) — see "Dependencies".
import { parse as parseToml } from 'smol-toml';

const home = os.homedir();
const env = process.env;

// ---- config.toml (env > [paths] toml > default) -------------------------
function loadConfig(): Record<string, any> {
  const p = env.AI_CONFIG || path.join(aiRoot(), 'config.toml');
  try { return parseToml(fs.readFileSync(p, 'utf-8')) as Record<string, any>; }
  catch { return {}; }
}
let _cfg: Record<string, any> | null = null;
function cfg(): Record<string, any> { return (_cfg ??= loadConfig()); }

/** [paths] table lookup: env > [paths][NAME] > [paths][name] > default */
function v(name: string, def: string): string {
  const paths = (cfg().paths ?? {}) as Record<string, string>;
  return env[name] || paths[name] || paths[name.toLowerCase()] || def;
}

// ---- anchors ------------------------------------------------------------
export function aiRoot(): string {
  return env.AI_ROOT || path.join(home, 'AI', 'ai_root');   // platform default
}
/** Canonical MAIN root — independent of AI_ROOT (a devTree's AI_ROOT != main). */
export function aiRootMain(): string {
  return v('AI_ROOT_MAIN', path.join(home, 'AI', 'ai_root'));
}

// ---- derived (default under AI_ROOT, independently overridable) ----------
const R = () => aiRoot();
export const AI_DATA          = () => v('AI_DATA',          path.join(R(), 'ai_general', 'data'));
export const AI_SCRIPTS       = () => v('AI_SCRIPTS',       path.join(R(), 'ai_general', 'scripts'));
export const AI_BIN           = () => v('AI_BIN',           path.join(R(), 'ai_general', 'apps'));
export const AI_LOGS          = () => v('AI_LOGS',          path.join(R(), 'ai_general', 'logs'));
export const AI_HOOKS         = () => v('AI_HOOKS',         path.join(AI_DATA(), 'hooks'));
export const AI_UAI_APP       = () => v('AI_UAI_APP',       path.join(AI_BIN(), 'uai'));
export const AI_CONTEXT_FILES = () => v('AI_CONTEXT_FILES', path.join(R(), 'ai_general', 'ai_context_files'));
// ---- independent (NOT derived from AI_ROOT) -----------------------------
export const AI_JSONL  = () => v('AI_JSONL',  path.join(home, '.claude', 'projects'));
export const AI_PYTHON = () => v('AI_PYTHON', path.join(home, 'myenv', 'bin', 'python'));

// ---- free-form config accessor ------------------------------------------
export function config(): Record<string, any> { return cfg(); }
export function get(dotted: string, def: any = null): any {
  return dotted.split('.').reduce<any>((o, k) => (o == null ? o : o[k]), cfg()) ?? def;
}

// ---- child-process env (the single Windows/PATH seam) -------------------
function fallbackBinDirs(): string[] {
  if (process.platform === 'darwin')
    return ['/opt/homebrew/bin', '/opt/homebrew/sbin', '/usr/local/bin',
            path.join(home, '.local/bin'), path.join(home, '.npm-global/bin')];
  // linux / wsl
  return ['/home/linuxbrew/.linuxbrew/bin', '/usr/local/bin', '/usr/bin',
          path.join(home, '.local/bin')];
}
/** The ONLY place a bin dir is named. Prepends the interpreter dir + fallbacks. */
export function buildChildEnv(extra: Record<string, string> = {}): Record<string, string> {
  const sep = process.platform === 'win32' ? ';' : ':';
  const parts = [path.dirname(AI_PYTHON()), ...fallbackBinDirs(), env.PATH || ''];
  return { ...env, AI_ROOT: aiRoot(), AI_ROOT_MAIN: aiRootMain(),
           AI_PYTHON: AI_PYTHON(), PATH: parts.join(sep), ...extra } as Record<string, string>;
}
```

## Dependencies

- One small TOML parser (`smol-toml` or `@iarna/toml`). Alternative if a dep is
  unwanted: the installer writes a `config.json` mirror the app reads with `JSON.parse`
  — but a TOML lib keeps one config format across surfaces. **Owner's call.**

## Migration (app owner)

1. Land `paths.ts` (this spec).
2. Replace the 17 `getAiRoot()`/`getAiRootMain()` copies with `aiRoot()`/`aiRootMain()`.
3. Replace the 41 `/opt/homebrew/*` PATH builds with `buildChildEnv()`.
4. Add the `paths.ts` anti-drift test (§5).
