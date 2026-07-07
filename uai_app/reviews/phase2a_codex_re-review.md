# Phase 2A Codex Re-Review

**Reviewer:** Codex CLI  
**Date:** 2026-04-26  
**Scope:** Follow-up review of the fixes listed against `reviews/phase2a_codex_code_review.md`, focused on `src/` plus the launcher/store contracts used by `src/main/session-store.ts`.  
**Verdict:** **REQUEST CHANGES**

## Executive Summary

Several Phase 2A fixes are real: container root validation is now centralized for the folder move paths, generic container snapshots are exposed to the renderer, tab open now goes through the command bus, after-hooks receive result/duration, and malformed `containers.json` no longer silently falls back to defaults.

The main blocker remains the session launch lifecycle. The default `ai_root` launcher now accepts `--tracking-id`, so my prior note that the argument did not exist was stale for that copy. However, the handoff is still not correct: Electron pre-creates the draft row, and the launcher then calls `_store.create()` with the same tracking ID instead of updating the draft. That is a duplicate primary-key insert on the normal path. Separately, `identity_status` is editable but not part of the SQLite schema or migration list, so pending/failed status writes still fail on a fresh or schema-managed store.

There is also a new notes synchronization bug: notes now persist to `app_state.json`, but the renderer session model does not refresh on `appState` changes, so the ContextPanel can revert to stale notes after switching sessions.

## Validation

Commands requested from `src/`:

| Check | Result | Notes |
|---|---:|---|
| `npx tsc --noEmit` | PASS | Completed with no output. |
| `npx vitest run` | BLOCKED | Vitest could not run in the read-only sandbox. It failed before collecting tests with `EPERM: operation not permitted, mkdir '/tmp/...'` and then could not write `src/node_modules/.vite/vitest/results.json`. |

I also tried `npx vitest run --no-cache --no-file-parallelism --maxWorkers=1`; it still failed on the sandbox `/tmp` mkdir. No Vitest test result should be inferred from this run.

## Critical Findings

### C1. `session.create` still cannot reliably transition the app-created draft into a launched session

**Severity:** Critical  
**Files:** `src/main/session-store.ts:167`, `src/main/session-store.ts:222`, `$HOME/Documents/AI/ai_root/ai_general/scripts/cli/ai_launcher.py:1398`, `$HOME/Documents/AI/ai_root/ai_general/scripts/cli/ai_launcher.py:1542`, `$HOME/Documents/AI/ai_root/ai_general/scripts/session_mgmt/session_store.py:509`, `$HOME/Documents/AI/ai_root/ai_general/scripts/session_mgmt/session_store.py:622`

The `--tracking-id` parser fix exists in the default `ai_root` launcher, and the new-session path does use `args.tracking_id` instead of generating a second ID.

The remaining problem is that the launcher still treats that tracking ID as a new store row. `createDraftSession()` writes the row first via `session_store.py create`, then `launchSession()` invokes the launcher with `--tracking-id`. In the default launcher path, after starting the substrate session, it calls `_store.create(tracking_id=tracking_id, ...)`. `SessionStore.create()` uses a plain `INSERT INTO sessions`, not an upsert or update. With the app-created draft already present, that insert hits the `tracking_id` primary key.

Bad outcomes:

- The terminal session may already have been created before `_store.create()` throws.
- The launcher exits non-zero, so Electron marks the draft failed even though a terminal may be running.
- CLI UUID, PID, substrate, transcript path, and other launch metadata do not get written back to the draft row.

There is a second lifecycle issue: `identity_status` was added to `EDITABLE_FIELDS`, but it is not in the `sessions` table schema, not in the migration block, and not in `SESSION_FIELDS`. `markPending()` / `markFailed()` therefore still fail on any DB that does not already have a manually-added `identity_status` column.

**Fix:** When `--tracking-id` refers to an existing draft row, update that row instead of calling `_store.create()`. Add `identity_status` to the authoritative schema, migration path, row field list, and create/register paths, with an initial `draft` value for app-created rows.

## Major Findings

### M1. Notes persist to the right file, but the session view model stays stale

**Severity:** Major  
**Files:** `src/renderer/components/ContextPanel.tsx:61`, `src/main/command-handlers.ts:158`, `src/main/command-handlers.ts:169`, `src/renderer/stores/session-store.ts:78`, `src/renderer/components/ContextPanel.tsx:225`

The write target was corrected: `NotesEditor.save()` now dispatches `app.state.update` with `sessionPrefs[trackingId].notes`.

The renderer data flow was not completed. `ContextPanel` reads `session.notes` from `useSessionStore()`. `app.state.update` emits only `['appState']`, and `session-store.ts` refreshes only on `event.changed.includes('sessions')`. After saving notes, the local editor state shows the new text, but the canonical session snapshot remains stale. Switching to another session and back can reinitialize the editor from the old `session.notes` value until some unrelated session refresh or app restart occurs.

**Fix:** Either emit `sessions` when `sessionPrefs` changes, make `SessionStore` refresh on relevant `appState` changes, or update the renderer session snapshot directly after a successful notes save.

### M2. The tags half of the prior notes/tags finding remains open

**Severity:** Major  
**Files:** `src/main/session-store.ts:83`, `src/main/session-store.ts:119`, `src/renderer/components/ContextPanel.tsx:214`

`getTagsForSession()` still exists but is unused, and `mapSession()` still returns `tags: []`. As acknowledged in the fix notes, batching tag reads was deferred. That means the ContextPanel tags section and any session-card tag filtering still cannot reflect persisted tags.

This is not a regression from the fixes, but it means the prior M3 finding is only partially resolved.

### M3. M10 after-hooks are fixed, but command safety semantics are still incomplete

**Severity:** Major  
**Files:** `src/main/command-bus.ts:161`, `src/main/command-handlers.ts:860`, `src/shared/types.ts:65`

The after-hook model is materially improved: hooks receive `(command, result, durationMs)` and hook errors are isolated.

The rest of the prior command model concern remains. `dry_run` and `idempotency_key` are still accepted by the command contract but ignored by execution. The access-control hook still only blocks `session.create` / `session.archive` for `external-api`; despite the comment mentioning `embedded-ai`, the condition excludes it from the block. Mutable `container.*`, tag, relationship, app-state, and tab commands still have no capability descriptors.

If those semantics are intentionally deferred, the contract should not advertise them as active behavior yet.

## Fix Verification

| Prior finding | Re-review status |
|---|---|
| C1 identity/launch lifecycle | **Not resolved.** `--tracking-id` exists in default `ai_root`, but the launcher duplicates the app-created row and `identity_status` is not in the schema/migrations. |
| M1 container root validation | **Mostly resolved.** `addCardToContainer`, `moveCard`, and `moveContainer` now share the root constraint for exclusive containers. Add regression tests for move-card and move-subtree paths; current tests only cover add. |
| M2 groups invisible | **Resolved.** `CONTAINER_LIST`, preload `containers.list()`, and `card-store` hydration now expose generic containers/groups. |
| M3 notes + tags | **Partially resolved.** Notes write to `app_state.json`, but renderer session notes stay stale; tags are still not loaded. |
| M4 tab open bypasses bus | **Resolved.** `App.handleSelectSession()` now dispatches `workspace.tabs.open`. |
| M5 registry incomplete | **Deferred.** No new concern beyond the acknowledged low-priority gap. |
| M6/M9 external signals | **Mostly resolved.** Watchers exist for the new signal files and container writes touch `containers.changed`. |
| M6/M10 after-hook model | **Partially resolved.** Result/duration hook plumbing is fixed; access-control, dry-run, and idempotency semantics remain open. |
| M7 corrupt container load | **Resolved for malformed JSON.** `loadContainers()` now fails closed on parse/read errors other than `ENOENT`. |

## Verdict

**REQUEST CHANGES.** The container/renderer fixes are moving in the right direction, but Phase 2A should not be accepted until the draft launch handoff is fixed end to end and `identity_status` is an actual persisted schema field. The notes refresh bug should also be addressed because it makes the fixed write path look unreliable in the UI.
