# Absolute-Path Audit — uai_app (Electron monorepo)

Generated from a scan of the vendored `uai_app` source **after** the scrubber runs.
Companion list: `audit_abspaths_everything_else.md`. Same detector and term
definitions as that file.

**Scope note:** uai_app is explicitly *out of scope* for the current WSL-readiness
pass ("the toolkit minus the UAI app"). This list is the backlog for whoever ports
the app itself. Nothing here is auto-fixable by the materialize scrubber — these are
runtime behaviors in TypeScript, not machine paths a text substitution should touch.

---

## Summary: 53 occurrences / 19 files; 41 are `/opt/homebrew/*` in the Electron main process

| Class | Occurrences | Action |
|---|---|---|
| **REAL — `/opt/homebrew/*` runtime PATH/binary hardcodes** | 41 | Cross-platform work (deferred; app-owned) |
| Test/story fixtures (`/Users/test/*`) | 8 | Benign — test data |
| Doc examples in `.md` (`/Users/.../*`) | 4 | Benign — documentation |

---

## A. REAL — Electron main-process hardcodes (the actual porting work)

These spawn child processes with an augmented PATH or invoke a binary by absolute
path. On Windows/WSL they must become PATH lookups (`which`/`where`), an env var, or
platform detection. **This is the substance of "port the app," not an easy fix.**

| File | Lines | Hardcode |
|---|---|---|
| `app/main/index.ts` | 1206, 1251, 1283, 1307, 1328, 1347, +12 | `/opt/homebrew/bin` (×18, PATH augmentation) |
| `app/main/command-handlers.ts` | 67, 326, 362, 682, 719, 796, +2 | `/opt/homebrew/bin` (×8) |
| `app/main/assigned-tasks.ts` | 125 | `/opt/homebrew/bin`, `/opt/homebrew/sbin` |
| `app/main/session-store.ts` | 32 | `/opt/homebrew/bin`, `/opt/homebrew/sbin` |
| `app/main/terminal.ts` | 52, 78 | `/opt/homebrew/bin`, `/opt/homebrew/bin/python3` |
| `app/main/search.ts` | 18 | `/opt/homebrew/bin/rg` (hardcoded ripgrep) |
| `app/main/brief-ops.ts` | 47 | `/opt/homebrew/bin` |
| `app/main/comms-reader.ts` | 293 | `/opt/homebrew/bin` |
| `app/main/session-traits.ts` | 19 | `/opt/homebrew/bin` |
| `app/main/teams-ops.ts` | 23 | `/opt/homebrew/bin` |
| `app/main/todo-ops.ts` | 29 | `/opt/homebrew/bin` |
| `spikes/phase_0b_vertical_slice/src/main/index.ts` | 122 | `/opt/homebrew/bin` |
| `spikes/phase_0b_vertical_slice/src/main/session-store.ts` | 23 | `/opt/homebrew/bin`, `/opt/homebrew/sbin` |

**Recommended pattern:** a single `resolveBinPath()` / `buildChildEnv()` helper that
(a) uses `process.env.PATH` + a `which`-style lookup, (b) falls back to
platform-appropriate dirs (Homebrew on mac, Linuxbrew/`/usr/bin` on Linux), and (c)
is the *only* place any bin dir is named. ~41 call sites collapse to one helper.

## B. Test / story fixtures — benign

Fake `/Users/test` user in test data; never executed as a real path.

| File | Lines |
|---|---|
| `app/tests/contract-cards.test.ts` | 92, 98 |
| `packages/renderer-ui/src/components/cards/CardRenderer.stories.tsx` | 91, 95 |

## C. Documentation examples — benign

Elided example paths (`/Users/.../…`) in architecture/design docs.

| File | Lines |
|---|---|
| `architecture/current_references/spec_session_identity_current.md` | 190, 193 |
| `architecture/spec_session_identity_v5.4.md` | 276, 279 |
| `docs/designs/2026-06-22-project-team-registry-design.md` | 67 |
| `docs/designs/project_creator_editor_design.md` | 38, 175, 219 |
