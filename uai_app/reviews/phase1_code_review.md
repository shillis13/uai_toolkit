# Phase 1 Code Review

**Reviewer:** Auditor (Claude CLI, session 20260424_221925_31fd0ea0_cla)
**Date:** 2026-04-24
**Requested by:** Continuity II (20260422_204104_640a7e0c_cla)
**Scope:** All 47 source files in `src/` (main, renderer, shared, tests)
**Method:** 3 parallel review agents (main process, renderer, shared+tests) against architecture contracts
**Verdict:** **Request Changes** — 6 critical, 11 major, 12 minor, 5 suggestions

---

## Executive Summary

Phase 1 delivers a structurally sound codebase — the command bus, Zustand stores, component registry, and folder manager all work as designed in isolation. The cross-workstream integration problems are concentrated in two areas:

1. **Contract drift** — `shared/types.ts` was written independently of `architecture/contracts/*.ts` and diverges in ~15 places. Fields are missing, discriminated unions are widened to `string`, and branded types (`CardId`, `EntityType`) are stripped. This is the single largest source of findings.

2. **Architecture bypass** — Several renderer components and one main-process handler route mutations outside the command bus (direct IPC writes), violating the stated architectural invariant.

Neither category requires redesign. Both are mechanical fixes — align the runtime types to contracts, route remaining mutations through the bus.

---

## Findings

### Critical (C) — Would break at runtime or violate core architectural invariants

#### C1. `get_relationships` call passes `--json` as unrecognized argument
**Files:** `main/command-handlers.ts:546`, `main/index.ts:208`
**Workstream:** 1A/1B integration

The `get_relationships` subcommand in `session_store.py` has no `--json` flag — it always outputs JSON. Passing `'--json'` as a positional argument causes argparse to fail, making every `relationship.list` command and `RELATIONSHIPS_FOR_ENTITY` query silently return `[]` (the error is caught and swallowed).

**Fix:** Remove `'--json'` from both calls.

---

#### C2. `APP_STATE_UPDATE` bypasses the command bus — direct IPC write
**File:** `main/index.ts:162-176`
**Workstream:** 1A

The `IPC.APP_STATE_UPDATE` handler directly reads/writes `app_state.json` via `fs.readFileSync`/`fs.writeFileSync`, skipping the command bus entirely. No hooks, no activity log, no access control. The comment in `command-handlers.ts:11` documents `app.state.update` as a planned command type that was never registered.

**Fix:** Register `app.state.update` on the bus; route the IPC handler through it.

---

#### C3. `listSessions` throws if `callStore` returns null — crashes bootstrap
**File:** `main/session-store.ts:100-102`
**Workstream:** 1A

`callStore` resolves to `null` when stdout is empty. `listSessions` immediately calls `.map(mapSession)` on the result — `null.map()` throws `TypeError`. Both `IPC.BOOTSTRAP` and `IPC.SESSION_LIST` handlers have no try/catch, so this propagates as an unhandled rejection and crashes the renderer's bootstrap flow.

**Fix:** `const rows = (await callStore(['list', '--json']) as Record<string, unknown>[] | null) ?? [];`

---

#### C4. Navigator session mutations bypass the command bus
**File:** `renderer/components/Navigator.tsx:373,383`
**Workstream:** 1B

`submitRename` calls `window.uai.sessions.update()` and `createSession` calls `window.uai.sessions.create()` — both legacy IPC paths. Other components (e.g., `ContextPanel.NotesEditor`) correctly use `window.uai.execute()`. The `IPC` constants explicitly label these as "Legacy commands" slated for replacement.

**Fix:** Route both through `window.uai.execute()` with appropriate command types.

---

#### C5. Contract drift: `shared/types.ts` Session type diverges from contract
**File:** `shared/types.ts:19-43` vs `architecture/contracts/entities.ts:49-84`
**Workstream:** 1D (shared layer)

Three divergences:
- **Missing `runtime_state: RuntimeState`** — the contract defines this as a distinct field; any renderer code reading it gets `undefined` with no type error.
- **`session_dir`/`project_dir` are `string | null`** — contract declares them as `string` (non-nullable). Runtime type is more permissive, masking cases where null values leak through.
- **Missing `lastViewedAt: string | null`** — present in contract's Session, absent in runtime type.

**Fix:** Re-export or extend the contract Session type rather than redeclaring it.

---

#### C6. Contract drift: `shared/types.ts` Command type missing fields, widened types
**File:** `shared/types.ts:47-57` vs `architecture/contracts/commands.ts:21-32`
**Workstream:** 1D (shared layer)

- `idempotency_key?: string` is missing — callers cannot request deduplication.
- `actor.origin` is typed `string` instead of `CommandOrigin` discriminated union — invalid origins pass silently.

Also affects `CommandResult`: `undo?: UndoDescriptor` is completely absent from the runtime type.

**Fix:** Import and use contract types directly.

---

### Major (M) — Incorrect behavior or significant quality issue

#### M1. Activity log after-hook reads log before `logCommand` runs
**File:** `main/index.ts:64-77` vs `main/command-bus.ts:149-155`
**Workstream:** 1A

After-hooks fire at line 149; `logCommand` executes at line 155 — after hooks complete. The after-hook reads `commandBus.getLog()` and gets the *previous* command's entry, logging wrong data. The current command's activity is never logged.

**Fix:** Move `logCommand` before the after-hooks, or pass result/duration directly to the hook.

---

#### M2. `tag.create` persists nothing but emits change events
**File:** `main/command-handlers.ts:365-398`
**Workstream:** 1C

The handler constructs a `Tag` object and returns it with `ok: true` and `changed: { tags: true }`, but writes nothing to the store. Callers get phantom success. The comment says "tags are implicit" but the change event triggers a re-fetch that always returns `[]`.

**Fix:** Either implement persistence or remove the change emission and document this as intentionally a no-op stub.

---

#### M3. Tracking ID format diverges from `TRACKING_ID_REGEX`
**File:** `main/session-store.ts:129-135`
**Workstream:** 1A

`createDraftSession` generates IDs like `20260424_123456_app3f2a1_cla` — the `app` prefix + 5 hex chars does not match the contract's `TRACKING_ID_REGEX` (`[0-9a-f]{8}`). Any tooling that validates or parses tracking IDs by regex will reject these.

**Fix:** Generate 8 hex chars from `crypto.randomUUID()` per the contract format.

---

#### M4. PromptBox sends text directly to PTY, bypassing the command bus
**File:** `renderer/components/PromptBox.tsx:56`
**Workstream:** 1B

`window.uai.terminal.input(sessionId, text)` sends staged prompts directly to the terminal, bypassing logging, capability checking (`terminal:send_staged` vs `terminal:send_submitted`), and the activity log.

**Fix:** Route through `window.uai.execute({ type: 'prompt.send', ... })`.

---

#### M5. Store bootstrap race condition — parallel bootstraps from simultaneous mounts
**Files:** All renderer stores (`session-store.ts`, `app-state-store.ts`, `folder-store.ts`, `tag-store.ts`)
**Workstream:** 1B/1C

Every store guards bootstrap with `if (!initialized)`, but `initialized` is set only after the async call resolves. All components mount simultaneously in `App.tsx`, so all observe `initialized === false` and all call `bootstrap()` in parallel — producing duplicate IPC requests and potential state corruption.

**Fix:** Add a synchronous `bootstrapping` guard set before the await.

---

#### M6. `session.archive` passes string '1' for boolean; no `session.unarchive` exists
**File:** `main/command-handlers.ts:95`
**Workstream:** 1A

`updateSession(trackingId, { archived: '1' })` sends a string. The `mapSession` function checks `raw.archived === 1 || raw.archived === true` — this works only if Python/SQLite coerces correctly. No `session.unarchive` command is registered for restoring archived sessions.

---

#### M7. `useRelationships` shows empty state after cache clear
**File:** `renderer/stores/relationship-store.ts:131-139`
**Workstream:** 1C

When `clearCache()` fires (from a `StoreChanged` event), the subscriber reads the now-empty cache and displays nothing. `reload()` is only called on mount and entity changes, not on cache clear notifications. The component shows empty relationships indefinitely until remounted.

**Fix:** Call `reload()` in the subscribe callback.

---

#### M8. Contract drift: `Tag.entity_types` is `string[]` instead of `EntityType[]`
**File:** `shared/types.ts:119-124`
**Workstream:** 1D

The contract uses `EntityType[]` — a discriminated union. The runtime type uses `string[]`, allowing typos like `'sessions'` to pass silently. Same issue applies to `EntityRelationship.source_type`/`target_type` (lines 151-160).

**Fix:** Import and use `EntityType` from contracts.

---

#### M9. Contract drift: `Folder.cards` is `string[]` instead of `CardId[]`
**File:** `shared/types.ts:100-108`
**Workstream:** 1D

The contract uses `CardId[]` — namespaced strings of form `"session:..."`. The runtime type uses plain `string[]`, losing the namespace guarantee.

**Fix:** Import and use `CardId` from contracts.

---

#### M10. Log bound test verifies wrong invariant
**File:** `tests/contract-command-bus.test.ts:143-152`
**Workstream:** 1D

Test asserts `log.length <= 1000`. Implementation trims to 500 when exceeding 1000. The test passes (500 < 1000) but documents the wrong bound. The comment in `command-bus.ts` also says "last 1000" but the code does `.slice(-500)`.

**Fix:** Align the comment, implementation, and test to the same number.

---

#### M11. Unhandled promise rejections in Navigator and ContextPanel
**Files:** `renderer/components/Navigator.tsx:368,382`, `renderer/components/ContextPanel.tsx:54`
**Workstream:** 1B

Async handlers (`submitRename`, `createSession`, notes `save`) are called from synchronous React event handlers. The returned Promise is never awaited by the caller. If the IPC call throws, the error is silently dropped — no user feedback, no error logging.

**Fix:** Add try/catch with user-visible error feedback.

---

### Minor (m) — Correctness or quality nit

#### m1. Read-only `folder.getSnapshot` / `folder.validateTree` registered on command bus
**File:** `main/command-handlers.ts:319-336`
The architecture comment states "Read-only queries bypass the bus." These are pure reads registered as commands, adding hook overhead and activity log noise.

#### m2. `as any` casts in multiple files
**Files:** `main/index.ts:230`, `renderer/components/BottomPanel.tsx:74,88`
Unnecessary `as any` on typed arrays and `updateAppState` calls. All target types exist and should be used directly.

#### m3. `preload.ts` types multiple IPC channels as `any`
**File:** `main/preload.ts:85-99`
Activity log, command log, system metrics, and transcript APIs all typed as `Promise<any>` despite having defined interfaces.

#### m4. Both reorder commands share identical error code `'REORDER_FAILED'`
**File:** `main/command-handlers.ts:289,314`
Should be `'SUBFOLDER_REORDER_FAILED'` and `'CARD_REORDER_FAILED'`.

#### m5. `RelationType` and `INVERSE_RELATIONS` duplicated in `shared/types.ts`
**File:** `shared/types.ts:128-149`
These are identical copies of the contract declarations. If either diverges, TypeScript won't catch it.

#### m6. `unfileCard` writes file even when no mutation occurred
**File:** `main/folder-manager.ts:392-410`
When card is already at root, the mutator returns early but `updateFolderStore` still increments revision and saves.

#### m7. No `app` root component registered in ComponentRegistry
**File:** `shared/component-descriptions.ts`
All 4 top-level components declare `parent: 'app'` but no component with `id: 'app'` is registered. Tree walking hits a dead end.

#### m8. Commands created with `id: ''` instead of UUID
**Files:** `renderer/components/Navigator.tsx:165`, `renderer/components/ContextPanel.tsx:55`
Contract requires `id` to be a unique UUID for correlation and logging.

#### m9. `Navigator.activeTab` seeded before store initializes
**File:** `renderer/components/Navigator.tsx:332-333`
`useState` initial value reads from `appState.navigatorTab` which may be the default if store hasn't bootstrapped. Persisted tab preference ignored until user interaction.

#### m10. `TerminalPane` ResizeObserver may cause infinite resize loop
**File:** `renderer/components/TerminalPane.tsx:175-179`
`fitAddon.fit()` resizes xterm internals, which can re-trigger the ResizeObserver. Should debounce.

#### m11. Spike debug status bar left in `MemorexView` production render
**File:** `renderer/components/MemorexView.tsx:210-212`
Exposes internal state (session IDs, error states) unconditionally. Gate behind `NODE_ENV` or remove.

#### m12. Activity log test event name regex too narrow; naming convention diverges from contracts
**File:** `tests/contract-activity-log.test.ts:148-156`
Regex requires `dot.underscore_name` format. Contract events use `colon:separated` names. Neither convention is documented or cross-validated.

---

### Suggestions (S)

#### S1. `RelatedEntitiesTab` label ternary has identical branches
**File:** `renderer/components/BottomPanel.tsx:165-168`
`const label = isSource ? rel.relation_type : rel.relation_type;` — should use `inverseLabel()` for the non-source side.

#### S2. Store hooks inconsistent `useCallback` wrapping
**Files:** All renderer stores
`session-store.ts` wraps `getSession` in `useCallback`; other stores return module-level functions unwrapped. Harmless but inconsistent.

#### S3. Missing `<React.StrictMode>` wrapper
**File:** `renderer/index.tsx`
StrictMode's double-invocation would surface the bootstrap race (M5) in development.

#### S4. `ComponentRegistry` has no `clear()` method for test isolation
**File:** `shared/component-registry.ts:87-88`
The singleton accumulates registrations across test files with no reset capability.

#### S5. `MemorexView.parseResponse` uses untyped `any` for transcript data
**File:** `renderer/components/MemorexView.tsx:61-91`
Spike-era parsing with no type contract for `window.uai.transcript.read()` return shape.

---

## Summary Table

| ID | Severity | File(s) | Issue |
|----|----------|---------|-------|
| C1 | Critical | command-handlers.ts, index.ts | `--json` arg crashes `get_relationships` |
| C2 | Critical | index.ts | APP_STATE_UPDATE bypasses command bus |
| C3 | Critical | session-store.ts | `listSessions` null crash on bootstrap |
| C4 | Critical | Navigator.tsx | Session create/rename bypass command bus |
| C5 | Critical | shared/types.ts | Session type missing fields, wrong nullability |
| C6 | Critical | shared/types.ts | Command type missing fields, widened types |
| M1 | Major | index.ts, command-bus.ts | Activity log hook timing race |
| M2 | Major | command-handlers.ts | tag.create persists nothing, emits phantom changes |
| M3 | Major | session-store.ts | Tracking ID format fails regex validation |
| M4 | Major | PromptBox.tsx | Prompt send bypasses command bus |
| M5 | Major | All stores | Bootstrap race from parallel mounts |
| M6 | Major | command-handlers.ts | session.archive string/boolean mismatch |
| M7 | Major | relationship-store.ts | Empty state after cache clear |
| M8 | Major | shared/types.ts | Tag/Relationship types widened to string |
| M9 | Major | shared/types.ts | Folder.cards loses CardId branding |
| M10 | Major | command-bus test | Log bound test/comment disagree with implementation |
| M11 | Major | Navigator.tsx, ContextPanel.tsx | Unhandled promise rejections |
| m1-m12 | Minor | Various | See minor findings above |
| S1-S5 | Suggestion | Various | See suggestions above |

---

## Recommended Fix Order

1. **C3** (null crash) — immediate; blocks all testing
2. **C1** (`--json` arg) — immediate; all relationship features are broken
3. **C5 + C6 + M8 + M9 + m5** (contract alignment) — batch as one PR; largest surface area
4. **C2 + C4 + M4** (command bus bypass) — batch as one PR; architectural consistency
5. **M1** (activity log timing) — standalone fix
6. **M5** (bootstrap race) — standalone fix across stores
7. **M3** (tracking ID format) — standalone fix
8. Everything else in severity order

---

## Verdict

**Request Changes** — 6 critical findings, 11 major. No architectural redesign needed. The critical bugs (C1, C3) would cause runtime failures; the contract drift (C5, C6) would cause silent type-level corruption as the codebase grows. All are mechanical fixes. The codebase is well-structured and the individual workstreams produced clean, consistent code within their boundaries — the issues are almost entirely at the integration seams.
