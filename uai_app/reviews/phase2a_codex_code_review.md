# Phase 2A Codex Code Review

**Reviewer:** Codex CLI  
**Date:** 2026-04-26  
**Scope:** Phase 2A card/container abstraction work plus Codex Phase 1 review fixes in `src/`, with targeted checks against `architecture/uai_architecture_v1.1.md`, `reviews/phase1_codex_code_review.md`, and the launcher/store contracts used by the Electron main process.  
**Verdict:** **REQUEST CHANGES**

---

## Executive Summary

Phase 2A compiles and the contract tests pass, but the implementation is not ready to merge. The most serious issue is still session launch lifecycle correctness: `session.create` pre-creates a draft tracking ID, but the launcher path invoked by Electron does not actually accept or use `--tracking-id`, and the attempted `identity_status=pending|failed` updates target a field that does not exist in `session_store.py`. The app can therefore return one tracking ID while launching or recording another, and failed/pending lifecycle status is not persisted.

The container abstraction is a useful direction, but it currently has data integrity holes. `addCardToContainer()` enforces session-vs-brief folder roots, while `moveCard()` and `moveContainer()` bypass those constraints. The generic `group` container path is also effectively write-only from the renderer: main can create groups in `containers.json`, but the only renderer read path is the folder compatibility projection, which filters groups back out.

The Phase 1 fixes are mixed. M7 is resolved. C4, M3, M4, M5, M8, and M11 are only partially resolved or still broken in important paths. M9 and M10 remain open and are made more important by the new `container.*` command surface.

---

## Validation Performed

Commands run from `ai_general/projects/unified_ai_interface/src/`:

| Check | Result | Notes |
|---|---:|---|
| `npx tsc --noEmit` | PASS | Full source is now included by `tsconfig.json`; no TypeScript errors. |
| `npx vitest run` | PASS | 50 tests passed across 5 test files. Vite emitted only the CJS Node API deprecation warning. |

I ran the requested validation as two separate commands rather than a single shell chain so failures would be attributable. The result is equivalent to `cd src && npx tsc --noEmit && npx vitest run`.

---

## Critical Findings

### C1. `session.create` still does not launch or track the app-created draft session correctly

**Severity:** Critical  
**Files:** `src/main/session-store.ts:167`, `src/main/session-store.ts:222`, `src/main/session-store.ts:263`, `src/main/session-store.ts:280`, `../../scripts/cli/ai_launcher.py:165`, `../../scripts/cli/ai_launcher.py:1387`, `../../scripts/session_mgmt/session_store.py:621`

`createDraftSession()` creates a tracking ID and writes a draft row, then `launchSession()` invokes the platform symlink with:

```text
<launcher> --tracking-id <draft-id>
```

The platform symlink fix addresses the Phase 1 "Codex/Gemini launch Claude" bug, but the lifecycle is still broken because `ai_launcher.py` does not define a `--tracking-id` argument. It parses known args only, so `--tracking-id` becomes passthrough to the underlying CLI. In the new-session path, the launcher generates its own tracking ID instead of consuming the app's draft ID.

That has two bad outcomes:

- The command result returns the draft `trackingId`, but the launcher can create or run a different terminal/session identity.
- The unknown `--tracking-id` flag may be forwarded to Claude/Codex/Gemini, producing a failed CLI launch that the launcher may still treat as successful.

The pending/failed status handling also does not work. `markPending()` and `markFailed()` call `session_store.py update ... --set identity_status=...`, but the Python store's editable fields do not include `identity_status`. Those calls reject and are swallowed by the `.catch()`, so the renderer generally sees `mapSession()`'s default `confirmed` state even for drafts and failures.

Even if the field existed, `markPending()` and `markFailed()` are fire-and-forget. `session.create` emits `sessions` immediately after `await launchSession()`, but the status update may not have completed yet and no store event is emitted after it completes.

**Fix:** Make one source own launch identity. Either add a real `--tracking-id` path to `ai_launcher.py` that resumes/uses the pre-created draft row, or stop pre-creating the draft in Electron and return the launcher's actual tracking ID. Add `identity_status` to the authoritative store schema and editable fields, await pending/failed writes before resolving, and emit after the persisted lifecycle transition.

---

## Major Findings

### M1. Container placement rules are enforced on add, but bypassed on move and folder reparent

**Severity:** Major  
**Files:** `src/main/container-manager.ts:352`, `src/main/container-manager.ts:402`, `src/main/container-manager.ts:478`, `src/main/folder-manager.ts:79`, `src/tests/contract-container-manager.test.ts:117`

`addCardToContainer()` correctly blocks a `session:*` card from being added under the briefs root tree. `moveCard()` does not repeat that check. A caller can move a session card from any source container into a folder under `all_briefs`, and validation will pass because the exclusive-placement duplicate check only detects "same card in two exclusive containers."

`moveContainer()` has the same root-boundary problem for whole subtrees. A folder containing session cards can be moved from the sessions tree into the briefs tree with no validation error. Once that happens, descendants and folder projections can return cards under the wrong root.

The tests cover root enforcement for `addCardToContainer()`, but not for `moveCard()` or `moveContainer()`.

**Fix:** Centralize card/root compatibility validation and call it from add, move, reorder/reparent, and delete reparent/cascade paths. Add tests for moving a card across roots and moving a folder subtree across roots.

### M2. Generic groups are persisted by main, but invisible to the renderer

**Severity:** Major  
**Files:** `src/main/command-handlers.ts:436`, `src/main/folder-manager.ts:25`, `src/main/index.ts:182`, `src/renderer/stores/card-store.ts:104`, `src/renderer/stores/card-store.ts:239`

The new `container.*` handlers can create `group` containers in `containers.json`, but the renderer has no generic container read IPC. It still calls `window.uai.folders.list()`, which goes through `loadFolders()` and `toFolderStore()`. That adapter explicitly filters out every `ContainerEntry` whose `container_type` is not `folder`.

Result: `container.create` with `type: 'group'` can succeed, but `useCardStore().groups` remains empty after refresh because `card-store.ts` rebuilds its container state from the folder-only projection. `ContainerTreeView` and `FolderCardVisual` advertise group support, but no current read path can display persisted groups.

**Fix:** Add a `containers.list`/snapshot IPC that returns `ContainerStoreData` directly, add a `containers` store slice or explicit generic-container event, and have `card-store.ts` hydrate from that generic snapshot instead of reconstructing from `FolderStoreData`.

### M3. C4 is only partially fixed: app-state prefs read back, but notes writes and tags are still wrong

**Severity:** Major  
**Files:** `src/main/session-store.ts:83`, `src/main/session-store.ts:119`, `src/renderer/components/ContextPanel.tsx:61`, `src/main/command-handlers.ts:41`, `../../scripts/session_mgmt/session_store.py:621`

`mapSession()` now reads `pinned`, `lastViewedAt`, and `notes` from `app_state.json`, which addresses part of Phase 1 C4.

However, `ContextPanel` still saves notes through `session.update` with `{ patch: { notes } }`. The authoritative Python session store does not allow `notes` as an editable field, so saving notes returns an error. The read side expects notes in `app_state.json`, while the write side still targets SQLite.

Tags are also still not merged into the session view model. `getTagsForSession()` exists, but `listSessions()` and `getSession()` never call it, and `mapSession()` always returns `tags: []`.

**Fix:** Route notes through an app-state/session-pref command that updates `sessionPrefs[trackingId].notes`. Load tags into `Session.tags` either by batching tag reads for listed sessions or by adding tags to the store list response.

### M4. The M3 command wrapper exists, but it does not cover transport failures or several false-success paths

**Severity:** Major  
**Files:** `src/renderer/utils/execute-command.ts:18`, `src/renderer/components/Navigator.tsx:167`, `src/renderer/components/Navigator.tsx:381`, `src/renderer/components/Navigator.tsx:384`, `src/main/command-handlers.ts:746`, `src/main/terminal.ts:64`

`executeCommand()` handles returned `CommandResult.ok === false`, but it does not catch rejected IPC calls, missing preload APIs, malformed results, or after-hook exceptions. Those failures reject to the caller. Several migrated callers do not catch them, and some do not await the command at all.

There are also still false-success paths:

- `Navigator.submitRename()` clears rename mode after `await executeCommand(...)` without checking `result.ok`.
- The archive context menu closes immediately and does not await the archive command.
- `prompt.send` returns `ok: true` whenever `writeTerminal()` does not throw, but `writeTerminal()` silently no-ops when no PTY entry exists.

This is better than Phase 1, but the pattern still allows UI state to advance after failed or undelivered commands.

**Fix:** Make `executeCommand()` return a normalized failure result for rejected IPC/invalid responses and optionally throw only when the caller opts in. Update callers to gate local state changes on `result.ok`. Make `writeTerminal()` report whether data was actually written and have `prompt.send` return `ok:false` when there is no attached terminal.

### M5. M4 is only partially fixed: tab close/activate use commands, but tab open still bypasses the bus

**Severity:** Major  
**Files:** `src/renderer/App.tsx:23`, `src/renderer/App.tsx:28`, `src/renderer/stores/app-state-store.ts:105`, `src/main/command-handlers.ts:769`

`Workspace` now routes close and activate through `workspace.tabs.close` and `workspace.tabs.activate`. But the main user path for opening a tab still calls `useAppStateStore().openTab()` directly from `App.handleSelectSession()`.

That direct helper mutates local renderer state and persists through `window.uai.appState.update()` rather than dispatching `workspace.tabs.open`. It bypasses command IDs, command logging, access control, and the new handler at `command-handlers.ts:769`.

**Fix:** Replace the direct `openTab()` call in `App.tsx` with `executeCommand('workspace.tabs.open', ...)`, and either remove the mutable tab helpers from `AppStateStore` or keep them private to store snapshot application.

### M6. M9 and M10 remain open, and `container.*` expands their blast radius

**Severity:** Major  
**Files:** `src/main/index.ts:369`, `src/main/command-handlers.ts:436`, `src/main/command-handlers.ts:860`, `src/main/command-bus.ts:151`

The main process still watches only `sessions.changed`. There is no external change signal for `containers.json`, `folders.json`, tags, relationships, or app state. Phase 2A adds `containers.json`, but external writers cannot notify the renderer about it except through an in-app command event.

The command bus access-control model is also still the Phase 1 stub. The new `container.create`, `container.delete`, `container.rename`, `container.addCard`, `container.removeCard`, `container.moveCard`, and `container.reorder` commands are all mutable organization commands, but the before hook only blocks `external-api` for `session.create` and `session.archive`. `embedded-ai` is mentioned in the comment but not blocked by the condition.

`dry_run` and `idempotency_key` remain accepted by the command contract and ignored by execution. After hooks still receive only the command, so logging continues to scrape the in-memory command log rather than receiving the actual result.

**Fix:** Add store change signals/watchers for folders/containers and other durable slices. Add command descriptors/capability checks for `container.*`, implement dry-run/idempotency semantics or remove them from accepted contracts for now, and pass result/duration into after hooks.

### M7. Container loading still fails open on corrupt JSON

**Severity:** Major  
**Files:** `src/main/container-manager.ts:61`

`loadContainers()` catches every error while reading or parsing `containers.json`, then falls back to `folders.json`, then to a default store. A malformed existing `containers.json` will be treated the same as a missing file. The next successful mutation writes the fallback/default store back to `containers.json`, which can overwrite recoverable user data.

This is the same failure mode called out against Phase 1 folder persistence, now moved into the generic manager.

**Fix:** Distinguish `ENOENT` from parse/schema errors. Missing file can migrate or initialize; corrupt existing data should fail closed with an explicit error and no write.

---

## Minor Findings

### m1. `folder-manager.validateTree()` ignores its argument

**Severity:** Minor  
**Files:** `src/main/folder-manager.ts:56`

The wrapper signature accepts a `FolderStoreData`, but the implementation discards it and validates `loadContainers()` from disk. That makes it impossible to validate an in-memory snapshot and can surprise tests or future tooling that passes a candidate tree.

### m2. Component registry coverage is improved but still incomplete

**Severity:** Minor  
**Files:** `src/shared/component-descriptions.ts:497`, `src/renderer/components/folders/FolderTree.tsx`, `src/renderer/components/folders/Breadcrumbs.tsx`, `src/renderer/components/tags/TagBadge.tsx`, `src/renderer/components/tags/TagPicker.tsx`

The specific M5 fixes for `PromptBox`, `TerminalPane`, and `MemorexView` are present. Phase 2A also registers `card_list` and `container_tree`.

The registry is still not complete for implemented architectural components. `FolderTree`, `Breadcrumbs`, `TagBadge`, and `TagPicker` remain unregistered. The parent/child tree is also stale: `workspace` does not list `prompt_box`, and `session_pane` does not list `terminal_pane`.

### m3. Card/container contracts are looser than the advertised discriminated model

**Severity:** Minor  
**Files:** `architecture/contracts/entities.ts:24`, `architecture/contracts/cards.ts:89`, `src/shared/cards.ts:39`, `src/main/container-manager.ts:144`

`CardId` includes `project:*` and `team:*`, but `AnyCard` does not include project or team card variants, and `cardRootType()` only understands `session:*` and `brief:*`. The runtime `ContainerEntry.cards` field is `string[]`, so invalid or unsupported card IDs can enter container state unless callers validate before insert.

---

## Phase 1 Finding Status

| Phase 1 finding | Status in this review |
|---|---|
| C4 session view model/app-state/tags | Partially resolved. App-state prefs read back; notes write path and tags remain broken. |
| M3 command result handling | Partially resolved. Wrapper exists; rejected IPC, malformed results, no-op handlers, and some UI state transitions remain unsafe. |
| M4 workspace tab commands | Partially resolved. Close/activate use commands; open still bypasses the bus. |
| M5 component registry | Partially resolved. PromptBox/TerminalPane/MemorexView registered; folder/tag components and tree relationships remain incomplete. |
| M7 relationship reload loop | Resolved. Cache presence now uses `cache.has()`. |
| M8 per-session activity log target | Partially resolved. `trackingId`/`sessionId` payloads are captured, but commands targeting `cardId: session:*` still log as `uai_app`. |
| M11 launch lifecycle | Not resolved. Platform symlink selection is fixed, but draft tracking ID consumption and lifecycle persistence are broken. |
| M9 external change handling | Still open. Phase 2A adds container state without an external change signal. |
| M10 command bus result/access model | Still open. New mutable `container.*` commands rely on the same weak hook/access-control model. |

---

## Verdict

**REQUEST CHANGES.** Validation is green, but the session launch lifecycle, container placement rules, renderer group read path, notes/tags integration, and command-result handling need fixes before Phase 2A can be considered sound.
