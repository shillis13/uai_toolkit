# uai-toolkit — Design (work repo; public counterpart = ai-toolkit)

Portable distribution of AI tooling (ported from `~/bin/ai`). First consumer:
PianoMan on **Windows 11 at work**. Authored by the **Portage** session, 2026-06-20.

**Porting target — two phases (locked 2026-07-06):**
- **Phase 1 — WSL** (Ubuntu-on-Windows = Linux). The larger set. The macOS→Linux
  axis is near-zero and the tmux/zellij/fcntl/pty/signal substrate all work, so
  most of `~/bin/ai` is an ordinary mechanical port here. This is the near-term
  target; the WSL portability gaps are macOS-isms (osascript, BSD `date/sed/stat`,
  `pbcopy`), not substrate.
- **Phase 2 — native Windows, no WSL**. A deliberately *smaller* subset of
  cross-platform essentials. This is where the real `platform_compat` work lives
  (msvcrt locking, no-fork/ConPTY, `schtasks`, path semantics, no POSIX signals).

## Terms
- **Package** — the shipped, versioned code + read-only assets. Replaced wholesale on upgrade.
- **Instance / `AI_ROOT`** — the user's writable root: `config.toml`, logs, memories, overrides. Created once by the installer; **never** overwritten on upgrade.
- **`platform_compat`** — the Tier-B adapter layer: one module per OS-divergent concern, runtime dispatch, platform-blind callers.
- **Tier A/B/C** — the portability change taxonomy (below).

## Layout (src/uai_toolkit/)

Flat-by-domain — no generic `scripts/` bucket, one shared-utils home.

```
install.py            the `uai-toolkit install` command (create AI_ROOT, wire hooks + MCP)
install.py            the `uai-toolkit install` command (create AI_ROOT, seed content, wire hooks+MCP)
paths.py              AI_ROOT discovery + config.toml (→ merging into the shared env-var resolver)
jsonl/                read_jsonl (faithful, +archive/engram) + j-tools (catjsonl) + platform_adapters + deps
file_access/          SQLite anti-clobber tracker (forked) + hook handlers
guidance/             guidance_cli/lib + scan_registry (was scripts/context_files) — backs knowledge MCP
memory/  history/     memory_cli/lib, search_cli/lib (was scripts/memories, histories)
todo/    tasks/       todo_mgr (CRUD) ; task_coord (coordination, was scripts/tasks)
context_files/        context_mgr + trait_mgr + generate_frontmatter (authoring/index side)
session_mgmt/         session_store + substrate + ops + registry (~34 files)
messages/  callbacks/ messaging_mgr + comms libs (~24) ; callback_lib
cli/                  launcher (ai_launch/orchestrator) + agent-ops + fork/resume (~27)
prompting/  session_bounce/  send_prompt + isBusy + lib_send_prompt ; bounce/offload/resume
scheduling/           (macOS launchd — port deferred; schtasks backend later)
git_guardian/  audit/  coordination/   git_guardian ; lib_audit ; feed_lib/identity
hooks/                live dispatch.py + common/ libs + 49 per-event handlers + hook_exclusions
mcp/                  shared/ framework + knowledge/ workflow/ comms/ sessions/ servers (all 4)
common_utils/         shared CLI libs (lib_logging, standard_colors, repl_base, lib_clean_text, ...)
content/              ai_context_files + ai_profiles (shipped knowledge base; install seeds AI_ROOT)
platform_compat/      OS-divergence adapters (locking msvcrt/fcntl, process)
```
(above src/uai_toolkit/; plus repo-root sibling `uai_app/` = vendored UAI Electron source, and `tools/` = manifest.py + materialize.py.)

**Materialize keystone** (`tools/`): source-authoritative regeneration. `manifest.py`
declares MODULES (per-file) + MODULE_DIRS (dir-glob w/ exclude/include_only/overrides)
+ CONTENT + APP_TREES; `materialize.py` copies + rewrites imports (incl. an auto-derived
intra-package sibling index) + scrubs, dry-run/`--apply`/`--dirs`/`--content`/`--app`.
Provenance `kind`: clean (mechanical, invertible) / curated (`.materialized` sidecar,
lossy) / forked / native. **Direction: minimize curation, port faithfully → most files
clean/invertible.** Curated-file triage: path-curated (dissolve after the env-var
migration) vs platform-curated (launchd/osascript/playwright — stay) vs semantic-shim
(catjsonl→discovery, hooks 3→1 — stay). ~240 files; import tail closed.

Naming: **repo == package each** — work repo `uai_toolkit` / package `uai_toolkit`;
public repo `ai_toolkit` / package `ai_toolkit` (conventional; see decision 6).
The MCP servers invoke their backing domain CLIs via `python -m uai_toolkit.<domain>.<cli>`.

## Decisions (locked)

1. **Ship vs. install split.** Package is read-only and upgradeable; the writable
   instance (`AI_ROOT`) is separate and durable. No personal data in the package.

2. **Installable Python distribution**, not a script dump. `pyproject.toml` +
   `console_scripts` entry points. Entry points generate real per-OS launchers —
   which **eliminates the jcat/jgrep symlink-dispatch problem** (no symlinks, no
   Developer Mode, no PATH surgery on Windows).

3. **Platform divergence — three tiers, never fork whole files:**
   - **Tier A** — macOS-neutral portability fixes: inline in source (pathlib,
     explicit UTF-8, guarded optional imports). Improves macOS too.
   - **Tier B** — genuinely OS-divergent behavior: one module in `platform_compat/`,
     branch at runtime (`locking`, `process`, `scheduler`, `links`). macOS keeps its
     existing branch; we add siblings.
   - **Tier C** — platform-impossible features (Claude Desktop AppleScript control):
     capability flags, degrade gracefully. Never import-and-crash.
   - 100%-platform-bound components → backend behind an ABC (e.g. `SessionSubstrate`).

4. **Config:** one env var `AI_ROOT` locates the instance (discovery cascade if
   unset). Everything else in `$AI_ROOT/config.toml` (TOML, not a shell `.rc` —
   rc files can't `source` on Windows). See `src/ai_toolkit/paths.py`.

5. **Installer:** no native `.pkg`/`.msi`. `pipx install ai-toolkit` +
   an `ai-toolkit init` subcommand (idempotent: create `AI_ROOT`, write config,
   register MCP servers + hooks).

6. **Two repos — two distinct products, each repo==package (revised 2026-06-24):**
   - **work repo `uai_toolkit`** (package `uai_toolkit`) = source of truth; the
     full UAI-flavored kit PianoMan installs at work (`uai-toolkit install`).
   - **public repo `ai_toolkit`** (package `ai_toolkit`) = the general/public kit.
   - Each is conventionally named (repo==package). Superseded the original
     "Model A / byte-identical subset": promoting a tool work→public now copies
     the files **and rewrites the namespace** (`uai_toolkit.`→`ai_toolkit.`, a
     one-line `sed` in a promotion script). Trade chosen for naming clarity;
     promotion is occasional so the rewrite cost is negligible.
   - Scrub is a one-time promotion gate — safe because **code carries no personal
     data** (it all lives in `config.toml`/`AI_ROOT`, never shipped).
   - **Memorex is separate** — it's TypeScript/Node (`node-pty`, `@xterm`), its own
     repo with an `npm` install path, not part of this Python package.
   - HARD GATE before any public push: PII/secret scrub; tie to Git Guardian.

8. **UAI app is included as a Node sibling (revised 2026-07-06).** Supersedes the
   original "TS/Node stays out of the package." The Electron monorepo
   (`unified_ai_interface`) is vendored SOURCE-ONLY to a repo-root sibling
   `uai_app/` (git-tracked, NOT Python package-data) via the materialize keystone
   (`APP_TREES`; excludes `node_modules` + `.vite`/`dist`/`out`/`UAI.app`).
   `node_modules` restore via `npm ci`; the app builds with its own
   electron-forge/vite toolchain. So the repo is a **Python-package + Node-app
   monorepo**: `pip install` gets the Python kit; a git clone additionally gets
   `uai_app/` to `npm ci` + build. Build automation (a `uai-toolkit build-app`
   step vs. left to the in-WSL session) is TBD.

7. **Hooks wire directly; no directory-scanning dispatcher.** The live
   `dispatch.py` scans a dir for executable handlers (`os.access(X_OK)`) and
   shells to `bash`/`python3` — both Windows-hostile, and redundant with Claude
   Code's native multi-hook-per-event + block-on-deny semantics. So the toolkit
   ships handlers as console_scripts and `ai-toolkit init` writes them straight
   into `settings.json` (idempotent merge). The dir-scanning dispatcher is a
   deferred, optional power-user feature.

## Sync from source — `tools/materialize.py` (source-authoritative)

The package is a **derived artifact**. Source of truth stays in the live tree
(`~/bin/ai` == `ai_general/scripts/`, `~/bin/all_languages/python/src`,
`ai_general/apps/mcps`); `tools/manifest.py` maps source→package and
`tools/materialize.py` regenerates the curated subset so drift is a reviewable
`git diff`, not silent rot. (Mirrors the UAI app: `work/projects/…` source →
`apps/` build artifact via `uai.sh`.)

Workflow: edit source → `python3 tools/materialize.py` (dry run) → `--apply` →
review `git diff` → commit. Provenance class per file (manifest `kind`):
- **clean** — copy + mechanical import rewrite (`common_utils.`→`uai_toolkit.…`,
  etc.) + machine-path scrub; written in place. The drift-prone bulk (this is
  how `lib_logging` silently went stale).
- **curated** — source was semantically trimmed here (stripped optional deps,
  `file_utils`→`discovery` shim, hand-wired MCP subsets). Materialize writes a
  `<file>.materialized` sidecar (gitignored) for manual diff — never clobbers.
- **forked** — toolkit improvement absent from source (`file_access/tracker.py`
  SQLite/WAL). Skipped; back-porting to source is the real fix.
- **native** — no source (`discovery.py`, `platform_compat/*`, `install.py`,
  `paths.py`, `__init__.py`). Never touched.

Manifest corrections vs the layout table above: `todo/todo_mgr.py` ←
`pylib:todo_mgr/` (NOT `ai:tasks/`); `jsonl/standardized_session.py` ←
`lib_standardized_session.py` (rename); `file_access/tracker.py` ←
`file_access_tracker.py` (rename, and forked); `file_access/hooks.py` merges 3
source hook scripts. The MCP SDK imports (`from mcp.server`/`mcp.types`) are
deliberately NOT rewritten — only internal `from shared.`/`from tools` patterns.

## Min Python: 3.10 (pervasive `X | Y` unions). Target 3.11+.

## Status
- **`read_jsonl`** ✅ ported + verified. Closure: `jsonl/{read_jsonl,standardized_session}.py`,
  `jsonl/platform_adapters/`, `utils/standard_colors.py`. `sys.path` hack removed;
  imports resolve as `ai_toolkit.*`. Archive/engram/REPL lazy → `full` extra.
- **`file_access`** ✅ ported + verified. `file_access/tracker.py` (SQLite WAL,
  drop-in API, fixes the JSONL no-locking + non-atomic-prune bug; 8-proc×250-write
  zero-loss proof in `tests/`). `file_access/hooks.py` = 3 console-script handlers
  (`ai-fa-track-read/-write`, `ai-fa-check-write`); conflict→exit2 verified.
- **`ai-toolkit init`** ✅ built + verified (`cli.py`). Creates AI_ROOT, copies
  config.toml, idempotent `settings.json` hook merge (preserves existing), --dry-run.
- **j-tools** ✅ ported + verified: `jcat/jgrep/jhead/jtail/jwc/jfmt` as console_scripts
  (`catjsonl.py`, `main(tool=...)` per-tool entries). 3 `sys.path` hacks removed;
  pager `less`→`more` on Windows + graceful fallback when absent. The heavy
  `file_utils.fsFind/fsFilters` (~2.5k LoC + common_utils + yaml) dependency
  **replaced** by a 90-line stdlib shim `jsonl/discovery.py` (recursive .jsonl/logs.json
  + since/before mtime window; gitignore-respect dropped as moot for transcript dirs).
- `platform_compat/{locking,process}.py` — Tier-B adapters (the pattern).

## Roadmap
- P1 (Windows-first MVP): `read_jsonl` ✅ · `file_access` ✅ · hooks-via-`init` ✅.
  Remaining P1 polish: `jcat/jgrep/...` as console_scripts; Windows validation on a real box.
- Next: port the **MCP servers** (the bulk of skills) + have `init` register them.
- P2 (home/Mac): `session_mgmt` (Windows substrate, psutil discovery, DB registry),
  `prompting` (scheduler backend; Desktop control stays macOS-only).

See full portability assessment: `/Users/shawnhillis/bin/ai/docs/portability_assessment_20260620.md`.
