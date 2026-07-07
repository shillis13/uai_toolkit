# Phase 2 Batch 1 Codex Review

**Reviewer:** Codex CLI  
**Date:** 2026-04-29  
**Scope:** Phase 2 batch 1 workstreams 2B, 2C, 2F, and 2G, focused on `src/`, `architecture/contracts/`, and the external store integration points used by the Electron app.  
**Predecessor:** `reviews/phase2a_codex_re-review.md`  
**Verdict:** **REQUEST CHANGES**

## Executive Summary

The batch moves the UI in the intended direction: session cards now render through the generic card system, groups are visible from the card store, ProjectCard contracts and IPC exist, notes now refresh on `appState` changes, and the local contract suite is green.

The main issue is that several deliverables are present in code but not actually usable in the app. The Projects tab still renders a placeholder instead of the new `ProjectsTab`; the Briefs tab has a generic empty state but no brief loading path; groups can be created and added to, but non-empty group deletion uses folder reparent semantics and remove-from-group is missing from the UI. Tags are also fragile: the renderer now depends on new `session_store.py` batch/list subcommands, but the default runtime `AI_ROOT` copy does not have them, so tags silently load as empty in the normal unset-`AI_ROOT` environment.

This is not ready for real-world Phase 2 usage yet. It is type-safe and test-clean, but the visible Navigator experience still has broken or incomplete entity tabs and group/tag workflows.

## Validation

Commands requested from `src/`:

| Check | Result | Notes |
|---|---:|---|
| `npx tsc --noEmit` | PASS | Completed with no output. |
| `npx vitest run` | PASS | 5 files, 55 tests passed. Vite printed only its CJS API deprecation warning; one command-bus test intentionally logs an isolated after-hook error. |

Additional integration check:

| Check | Result | Notes |
|---|---:|---|
| `python3 $HOME/Documents/AI/ai_root/ai_general/scripts/session_mgmt/session_store.py list_distinct_tags` | FAIL | The default runtime store reports `invalid choice: 'list_distinct_tags'`. The devTree copy has the new tag commands, but `AI_ROOT` is unset here, so the app defaults to `$HOME/Documents/AI/ai_root`. |

I did not launch the Electron UI interactively; the readiness assessment below is based on source review plus the requested validation commands.

## Critical Findings

None.

## Major Findings

### M1. Projects are indexed into the card store but the Navigator still hides them behind a placeholder

**Severity:** Major  
**Files:** `src/renderer/components/Navigator.tsx:684`, `src/renderer/components/ProjectsTab.tsx:20`, `src/renderer/stores/card-store.ts:97`, `src/main/index.ts:198`

The 2G backend and renderer pieces exist: `PROJECT_LIST` is exposed, `card-store` loads `window.uai.projects.list()`, and `ProjectsTab` renders `ProjectCard`s with search/status filters. The actual Navigator tab never uses that component. It still renders:

```tsx
<p>Projects — coming in 2G</p>
```

Result: the user cannot see projects in the Navigator, even though project cards are being loaded. This fails the 2G "User can see all projects in Navigator" acceptance path.

**Fix:** Import and render `ProjectsTab` in the `projects` branch of `Navigator`, and wire at least a no-op or detail callback intentionally. Add a renderer-level test or component smoke test for the Projects tab branch.

### M2. Tag loading depends on undeployed store commands and silently degrades to empty tags

**Severity:** Major  
**Files:** `src/main/session-store.ts:94`, `src/main/session-store.ts:103`, `src/main/session-store.ts:160`, `src/main/index.ts:211`, `src/renderer/components/ContextPanel.tsx:120`, `src/renderer/stores/tag-store.ts:35`

`listSessions()` now batches tags via `get_all_card_tags`, and `TAGS_LIST` uses `list_distinct_tags`. Those calls are caught and converted to `{}` / `[]` on failure. In this environment `AI_ROOT` is unset, so the app uses `$HOME/Documents/AI/ai_root`; that copy of `session_store.py` supports `add_tag`, `remove_tag`, and `get_tags`, but not `get_all_card_tags` or `list_distinct_tags`.

Result on the normal default runtime path:

- session cards and ContextPanel receive `session.tags: []`;
- TagPicker has no available tags;
- adding a tag can succeed in SQLite but the UI refresh still shows no tag because the batch/list read path fails silently.

This makes the 2F tag integration appear broken in real usage.

**Fix:** Deploy the new subcommands to the default `AI_ROOT` store before relying on them, or add a compatibility fallback: batch from `get_tags` per listed session and derive distinct tags from loaded session tags when `list_distinct_tags` is unavailable. Avoid swallowing these failures without at least logging them.

### M3. Deleting non-empty groups uses exclusive-folder reparent semantics

**Severity:** Major  
**Files:** `src/main/container-manager.ts:329`, `src/main/container-manager.ts:344`, `src/renderer/components/Navigator.tsx:273`

`deleteContainer()` always pushes the deleted container's cards into its parent on `reparent` and `cascade`. That is correct for folders but wrong for groups. Groups are non-exclusive membership containers; deleting a group should remove the membership record, not move its members into the parent folder.

The Navigator creates groups under `all_sessions` and deletes them with `policy: 'reparent'`. For a typical session already present in `all_sessions` or another exclusive folder, deleting the group duplicates that `session:*` card into an exclusive container and validation rejects the whole deletion. For other card types or malformed states, it can also place cards into the wrong root tree.

**Fix:** Branch deletion behavior by `placement_rule` or `container_type`. For non-exclusive containers, delete the container and its membership edges without reparenting cards into an exclusive parent. Add a regression test for deleting a non-empty group whose member is also in an exclusive folder/root.

### M4. Groups can be added to, but there is no usable remove-from-group workflow

**Severity:** Major  
**Files:** `src/renderer/components/Navigator.tsx:161`, `src/renderer/components/Navigator.tsx:458`, `src/renderer/components/Navigator.tsx:642`

The session context menu can add a session to any group. The Groups tab renders group cards and has rename/delete context actions. There is no member list, no group detail, no "remove from group" context action, and clicking a group card is explicitly a no-op.

Result: users can create accumulating group memberships but cannot manage or remove them from the Navigator UI. That misses the 2B done condition for add/remove sessions.

**Fix:** Add a group detail/member view or group-card expansion that lists member session cards with `container.removeCard`. At minimum, show current membership in the session context menu and offer remove for groups the session already belongs to.

### M5. Briefs tab is not actually backed by brief data

**Severity:** Major  
**Files:** `src/renderer/components/Navigator.tsx:658`, `src/renderer/stores/card-store.ts:97`

The Briefs tab now uses `CardListView`, but `card-store` only hydrates sessions, containers, and projects. There is no IPC/read path for `list_briefs`, no `Brief -> BriefCard` adapter, and no code that adds `BriefCard`s to the card map.

Result: the tab can only render "No briefs loaded. Briefs will appear here when indexed." It is a cleaner placeholder, not an implemented Briefs tab.

**Fix:** Add a `BRIEF_LIST` IPC/preload API, map store rows into `BriefCard`, hydrate them in `card-store`, and add at least one contract test for the adapter.

### M6. Navigator tag filtering is still absent

**Severity:** Major  
**Files:** `src/renderer/components/Navigator.tsx:48`, `src/renderer/components/Navigator.tsx:60`, `tasks/phase_2/ws_2f_tags_integration.md:37`

The 2F task requires tag filtering. The current `FilterState` only tracks status, platform, and free-text search; `filterSessions()` searches display name, role, and tracking ID, but not `session.tags`. There are also no tag chips in the filter toolbar.

**Fix:** Add a selected-tag set or make text search match tags, then apply it consistently to the card-based session list.

## Minor Findings

### m1. Component descriptions are stale for the new Groups tab

**Severity:** Minor  
**Files:** `src/shared/component-descriptions.ts:19`, `src/shared/component-descriptions.ts:24`, `architecture/contracts/components.ts:201`, `src/renderer/components/Navigator.tsx:529`

`NavigatorTab` and the rendered tab bar now include `groups`, but the component description still documents only `sessions | briefs | teams | projects`. This widens the existing registry drift noted in Phase 2A.

### m2. New UI classes are mostly unstyled

**Severity:** Minor  
**Files:** `src/renderer/components/ProjectsTab.tsx:48`, `src/renderer/components/tags/TagPicker.tsx:60`, `src/renderer/components/tags/TagBadge.tsx:30`, `src/renderer/components/cards/SessionCardVisual.tsx:39`, `src/renderer/styles/styles.css`

The batch adds classes such as `projects-tab`, `tag-picker`, `tag-badge`, `tag-list`, `card-tags`, `card-tag-pill`, `context-submenu`, and `nav-folder-section`, but `styles.css` does not define them. The UI will render, but several controls/pills/submenus will be visually unpolished or layout-dependent.

### m3. Project status support is narrower than the contract

**Severity:** Minor  
**Files:** `src/main/project-indexer.ts:43`, `architecture/contracts/cards.ts:94`

`ProjectCard.status` allows `clean | dirty | ahead | behind | unknown`, but the indexer only returns `clean`, `dirty`, or `unknown`. That is acceptable for a first pass, but the UI exposes `ahead`/`behind` filters in `ProjectsTab`, so those filters currently cannot match anything.

## Phase 2A Regression Check

| Prior concern | Batch 1 status |
|---|---|
| Launch lifecycle / `identity_status` | Not made worse by this batch. The default `ai_root` store now has `identity_status` schema/migration support and `create()` updates existing draft rows. I did not run a live session launch. |
| Notes stale after `appState` updates | Appears fixed in current source: `session-store.ts` refreshes on both `sessions` and `appState` changes. |
| Tags still `[]` | Improved in source, but not reliable in the default runtime because the new batch/list store commands are missing there. |
| Groups invisible | Improved: generic containers/groups are hydrated into `card-store` and rendered in a Groups tab. Management is incomplete and group deletion is wrong for non-exclusive membership. |
| Command safety semantics | Unchanged; dry-run/idempotency/capability semantics remain deferred. |

## Verdict

**REQUEST CHANGES.** The code compiles and the contract tests pass, but the batch is not functionally complete enough to accept. Fix the visible Projects tab, deploy or fallback the tag read commands, correct non-exclusive group deletion, add remove-from-group UI, and add real BriefCard hydration before treating this batch as ready for hands-on app usage.
