# ai-toolkit — Design

Portable distribution of AI tooling (ported from `~/bin/ai`). First consumer:
PianoMan on **Windows 11 at work**. Targets Linux (near-zero) and Windows 11
with native Python (no WSL). Authored by the **Portage** session, 2026-06-20.

## Terms
- **Package** — the shipped, versioned code + read-only assets. Replaced wholesale on upgrade.
- **Instance / `AI_ROOT`** — the user's writable root: `config.toml`, logs, memories, overrides. Created once by the installer; **never** overwritten on upgrade.
- **`platform_compat`** — the Tier-B adapter layer: one module per OS-divergent concern, runtime dispatch, platform-blind callers.
- **Tier A/B/C** — the portability change taxonomy (below).

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

6. **Two repos — Model A (public = subset of work):**
   - **work/private repo** (this one) = source of truth; what PianoMan installs at work.
   - **public repo** = a curated subset, pushed *out* of this one when a tool is
     ready to share. They look the same because public is literally a slice.
   - Scrub is a one-time promotion gate, not a recurring sync diff — safe because
     **code carries no personal data** (it all lives in `config.toml`/`AI_ROOT`,
     which is never part of the public subset).
   - **Memorex is separate** — it's TypeScript/Node (`node-pty`, `@xterm`), its own
     repo with an `npm` install path, not part of this Python package.
   - HARD GATE before any public push: PII/secret scrub; tie to Git Guardian.

## Min Python: 3.10 (pervasive `X | Y` unions). Target 3.11+.

## Status
- **Tool #1 ported: `read_jsonl`** (the cleanest, and work-critical). Closure carried:
  `jsonl/{read_jsonl,standardized_session}.py`, `jsonl/platform_adapters/`,
  `utils/standard_colors.py`. The `~/bin/ai` `sys.path` hack removed; imports now
  resolve as `ai_toolkit.*`. Heavier features (archive/engram/REPL) are lazy and
  deferred to a `full` extra.
- `platform_compat/{locking,process}.py` — first Tier-B adapters (the pattern).

## Roadmap
- P1 (Windows-first MVP): `read_jsonl` ✅ → `file_access` (move to SQLite; fixes a
  current macOS locking bug) → `hooks` (`dispatch.sh` → Python).
- `ai-toolkit init` + MCP/hook registration.
- P2 (home/Mac): `session_mgmt` (Windows substrate, psutil discovery, DB registry),
  `prompting` (scheduler backend; Desktop control stays macOS-only).

See full portability assessment: `/Users/shawnhillis/bin/ai/docs/portability_assessment_20260620.md`.
