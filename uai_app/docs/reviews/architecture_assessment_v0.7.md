# UAI Architecture Assessment v0.7

**Date:** 2026-05-16  
**Reviewer:** Codex  
**Scope:** Architecture health check of contracts, command/data flow, preload/IPC bridge, renderer stores, and monorepo structure. This is **not** a feature review.

## Executive Summary

| Area | Rating | Summary |
|---|---|---|
| 1. Contract adherence | **RED** | The contract layer and runtime shared types have drifted in several important places (Session, CommandResult, EntityRelationship, and component tab enums). |
| 2. Command Bus consistency | **RED** | The app talks about “all domain mutations through the CommandBus,” but a non-trivial set of persisted mutations still bypass the bus. |
| 3. Data flow (Path 1 / Path 2) | **RED** | Path 1 snapshot application is mostly unimplemented, and Path 2 refresh coverage is incomplete for projects, teams, briefs, and some tag/relationship updates. |
| 4. Component API model | **YELLOW** | Props/interfaces are generally clean and prop drilling is controlled, but many components reach directly into `window.uai.*` instead of a thinner store/service layer. |
| 5. Preload bridge completeness | **YELLOW** | The bridge is broad and useful, but one registered IPC mutation is not exposed, and the package-level `window.uai` typing has already drifted from the real preload surface. |
| 6. Store architecture | **RED** | `card-store` is not the renderer's single source of truth; state is fragmented across multiple stores and local component state, with stale refresh paths. |
| 7. Code quality concerns | **YELLOW** | The codebase is functional, but several files are too large, some patterns are duplicated, and error handling/type discipline are inconsistent. |
| 8. Monorepo health | **YELLOW** | Package direction is mostly clean, but the shared runtime layer duplicates contracts instead of re-exporting them, and one renderer component imports contracts directly. |

## Bottom line

The app is **coherent enough to keep building on**, but the architecture claims are ahead of the implementation in three places:

1. **The contract layer is not the actual runtime source of truth yet.**
2. **The CommandBus is not the only mutation path.**
3. **Path 2 refresh coverage is incomplete, so some slices are “load once and hope.”**

That is fixable, but it is no longer just polish. It is structural maintenance.

---

## 1. Contract adherence — RED

## What is solid

- The project/team additions are at least moving in the right direction: `TeamCard` exists in the contract layer and is consumed by the renderer (`architecture/contracts/cards.ts:105-120`, `packages/renderer-ui/src/stores/card-store.ts:118-128`).
- Package boundaries generally try to consume shared types rather than inventing ad hoc local shapes.

## Findings

### 1.1 `Session` drift between contracts and runtime shared types

The architecture contract for `Session` includes:
- `history_file`
- `substrate`

See: `architecture/contracts/entities.ts:49-84`

The runtime `Session` type used by the app omits both fields:
- `packages/shared/src/types.ts:28-54`

`app/main/session-store.ts` also drops those fields when mapping store rows into renderer sessions:
- `app/main/session-store.ts:117-143`

This is classic contract drift: the contract says the renderer gets a merged `Session`, but the runtime type has already forked.

### 1.2 `CommandResult` is weaker in runtime than in the contract

The command contract uses store-safe typing:
- `changed?: Partial<Record<StoreSlice, boolean>>`
- `snapshots?: Partial<Record<StoreSlice, unknown>>`

See: `architecture/contracts/commands.ts:34-41`

The runtime shared type weakens both to string-keyed maps:
- `packages/shared/src/types.ts:71-79`

That means the architecture layer can no longer protect the runtime from typos or invalid store slice names.

### 1.3 `EntityRelationship` payload shape does not match how the app actually uses it

The contract says `EntityRelationship` contains:
- `metadata_json: Record<string, unknown> | null`

See: `architecture/contracts/entities.ts:206-213`

The runtime type repeats that same shape:
- `packages/shared/src/types.ts:157-165`

But `command-handlers.ts` has to cast in a synthetic `metadata` field that is **not** in the type:
- `app/main/command-handlers.ts:178-181`

That is a strong sign that the app is receiving a different shape than the declared type. Whether the fix belongs in the upstream Python adapter or the TypeScript runtime type, the current state is inconsistent.

### 1.4 Component enum contracts have drifted from the visible UI

The component contract says:
- `NavigatorTab = 'sessions' | 'briefs' | 'groups' | 'teams' | 'projects'`
- `ContextPanelTab = 'details' | 'digests' | 'docs' | 'messages' | 'prompts'`
- `BottomPanelTab = 'related' | 'logs' | 'app_log' | 'monitor'`

See: `architecture/contracts/components.ts:201-205`

But the live UI exposes:
- Navigator tab bar only renders `sessions`, `teams`, `projects` (`Navigator.tsx:668-679`)
- Context panel renders `details`, `context`, `prompts`, `messages` (`ContextPanel.tsx:347-367`)
- Bottom panel default tabs are `related`, `session_log`, `app_log`, `monitor` (`BottomPanel.tsx:44-60`)

That is not just nomenclature drift. It means the architecture contract is no longer describing the user-facing component API.

### 1.5 `Tag.entity_types` contract is broader than the implementation emits

The contract allows tags across entity types:
- `architecture/contracts/entities.ts:197-201`

But the main-process tag list handler hardcodes only:
- `['session', 'brief']`

See: `app/main/index.ts:286-296`

That contradicts the current UI, because project and team detail views already expose tag editing surfaces.

### 1.6 `Tab` is effectively an implementation contract, not an architecture contract

The workspace `Tab` and `TabType` are defined only in runtime shared types:
- `packages/shared/src/types.ts:106-115`

The architecture/contracts layer does not contain a corresponding tab contract. Given how central tabs are to `Workspace`, `TabContentPane`, and app state, this is a missing architectural contract, not just a missing type export.

---

## 2. Command Bus consistency — RED

## What is solid

- The main happy path exists and is clean: renderer code calls `window.uai.execute(...)` via `executeCommand()`, then main routes through `IPC.COMMAND_EXECUTE` into `CommandBus.execute()` (`app/main/preload.ts:65-67`, `packages/renderer-ui/src/utils/execute-command.ts:13-24`, `app/main/index.ts:165-169`).
- A large set of domain mutations are in fact registered on the bus (`app/main/command-handlers.ts:190-1224`).

## Findings

### 2.1 Comms mutations bypass the CommandBus

These IPC handlers mutate persisted state directly without routing through the bus:
- `uai:comms:send` → `sendMessage()` (`app/main/index.ts:430-435`)
- `uai:comms:queue:hold` (`app/main/index.ts:439-440`)
- `uai:comms:queue:release` (`app/main/index.ts:443-444`)
- `uai:comms:queue:changeDelivery` (`app/main/index.ts:447-448`)
- `uai:comms:queue:remove` (`app/main/index.ts:451-452`)
- `uai:comms:lock:set` / `lock:remove` (`app/main/index.ts:461-470`)

That is a direct violation of the stated rule at the top of `index.ts`:
- “All domain mutations route through the CommandBus.” (`app/main/index.ts:9-11`)

This is not cosmetic. These operations skip the bus's structured logging, consistent policy enforcement, and future capability checks.

### 2.2 `APP_STATE_GET` mutates disk on a read path

`IPC.APP_STATE_GET` is registered as a read-only query, but it rewrites `app_state.json` when normalization changes are detected:
- `app/main/index.ts:213-223`

That is a write hidden inside a read handler. It bypasses the CommandBus entirely.

The normalization itself may be useful, but architecturally this is still a mutation leak.

### 2.3 Access control is only partially implemented relative to the command contract

The command contract defines a real capability/safety model:
- `CommandDescriptor`, `CapabilityRequirement`, `affected_stores`, etc. (`architecture/contracts/commands.ts:84-144`)

The runtime bus does not implement any descriptor registry or capability enforcement. Instead there is a very small hardcoded blocklist:
- `app/main/command-handlers.ts:1235-1248`

This means the architecture contract is ahead of the actual enforcement model.

### 2.4 `AppStateStore` performs optimistic local mutation with no rollback

On the renderer side, `updateAppState()` mutates local singleton state immediately, then attempts to persist:
- `packages/renderer-ui/src/stores/app-state-store.ts:92-100`

If persistence fails, the local state is left mutated and the function only logs an error. That means the renderer can temporarily diverge from the persisted source of truth.

That is not a CommandBus bypass in the main process, but it is still a mutation-discipline problem.

---

## 3. Data flow (Path 1 / Path 2) — RED

## What is solid

- Path 1 transport exists: renderer → preload → `IPC.COMMAND_EXECUTE` → `CommandBus` (`packages/renderer-ui/src/utils/execute-command.ts:13-24`, `app/main/index.ts:165-169`).
- Path 2 event emission exists: `emitStoreChanged()` raises `StoreChangedEvent` to the renderer (`app/main/index.ts:80-89`).

## Findings

### 3.1 Path 1 “snapshot apply immediately” is mostly not implemented

The renderer session store claims:
- “Path 1: Command result snapshots apply immediately” (`packages/renderer-ui/src/stores/session-store.ts:5-7`)

But `executeCommand()` only forwards the command and handles errors:
- `packages/renderer-ui/src/utils/execute-command.ts:13-55`

There is no generic snapshot application path there.

The only real snapshot application I found is folder-specific:
- `packages/renderer-ui/src/stores/folder-store.ts:113-119`
- and its event-time use at `packages/renderer-ui/src/stores/folder-store.ts:211-217`

So Path 1 immediate state application is largely an architectural promise, not a general implementation.

### 3.2 Path 2 refresh coverage is incomplete for projects, teams, and briefs

Main watches only these signal files:
- `sessions.changed`
- `containers.changed`
- `tags.changed`
- `relationships.changed`
- `appstate.changed`

See: `app/main/index.ts:767-771`

There are **no** watched signals for:
- projects
- teams
- briefs

And `card-store` only refreshes on:
- `'sessions'`
- `'folders'`

See: `packages/renderer-ui/src/stores/card-store.ts:262-268`

That means project/team/brief cards are effectively bootstrap-loaded and then refreshed only incidentally when some unrelated slice changes.

This is a structural Path 2 hole.

### 3.3 Tag and relationship updates do not propagate cleanly to non-session cards

Tag mutations emit:
- `changed: { sessions: true, tags: true }`

See: `app/main/command-handlers.ts:730-785`

But `card-store` ignores `tags` changes and only listens for `sessions`/`folders` (`packages/renderer-ui/src/stores/card-store.ts:264-268`).

That is especially problematic because project and team detail views expose tag editing surfaces. A project or team tag change does not have a clean store refresh path.

### 3.4 Some UI count/badge data is loaded ad hoc instead of through Path 2

Example: `ContextPanel` fetches queue/inbox badge counts once on session change:
- `packages/renderer-ui/src/components/ContextPanel.tsx:288-297`

It does not subscribe to a comms-specific store or refresh event. This is a smaller issue than the missing project/team/brief path, but it follows the same pattern: read-once ad hoc queries instead of store-driven inbound flow.

---

## 4. Component API model — YELLOW

## What is solid

- Most components have explicit props interfaces, e.g.:
  - `WorkspaceProps` (`Workspace.tsx:66-68`)
  - `ContextPanelProps` (`ContextPanel.tsx:270-272`)
  - `SettingsPanelProps` (`SettingsPanel.tsx:34-39`)
  - `TabContentPaneProps` (`TabContentPane.tsx:23-25`)
- There is no obvious deep prop drilling problem. The main app composes high-level pieces with fairly small prop surfaces (`app/renderer/App.tsx:116-139`).
- Renderer code does not import `ipcRenderer` directly; it goes through `window.uai` (`rg` scan across renderer-ui/app renderer). That part is clean.

## Findings

### 4.1 Many components reach directly into `window.uai.*`

Examples:
- `ContextTab` directly calls `window.uai.traits.list/load` (`ContextTab.tsx:209-218`, `264-284`)
- `MessagesTab` directly calls `window.uai.comms.inboxList` (`MessagesTab.tsx:60-69`)
- `PromptsTab` directly calls `window.uai.comms.queueList` (`PromptsTab.tsx:47-56`)
- `MemorexView` directly calls `window.uai.transcript.read` (`MemorexView.tsx:102-132`)
- `BottomPanel` directly calls `window.uai.systemMetrics()` and `window.uai.getVersion()` (`BottomPanel.tsx:81-99`)

That is not automatically wrong, but it means the component layer is tightly coupled to the preload bridge rather than talking through reusable store/service hooks.

### 4.2 The component-description model is static rather than component-owned

The contract language says every architectural component provides `describe()` (`architecture/contracts/components.ts:12-17`), and `ComponentRegistry` is built around `DescribableComponent.describe()` (`packages/shared/src/component-registry.ts:12-51`).

In practice, the descriptions are centralized as static objects in `component-descriptions.ts`, then wrapped by `makeDescribable()` and registered in one place. That is workable, but it is not the same model as “each component provides describe().” It increases drift risk because descriptions and implementations can move independently.

### 4.3 Navigator and Workspace are carrying too many responsibilities per file

This is more code-quality than API-model, but it affects component clarity.

- `Navigator.tsx` contains the main navigator, two context menus, the filter toolbar, and the recent-sessions strip in one ~938-line file (`Navigator.tsx:142-359`, `362-429`, `896-930`).
- `Workspace.tsx` owns tab switching, keyboard shortcuts, group-layout state, context menu behavior, and rendering in one ~440-line file (`Workspace.tsx:79-220`, `242-345`).

The prop interfaces are clean, but the component boundaries inside these files are not.

---

## 5. Preload bridge completeness — YELLOW

## What is solid

- The preload is broad and genuinely useful. It exposes most read and command surfaces the renderer needs (`app/main/preload.ts:60-269`).
- Renderer code does not bypass it.

## Findings

### 5.1 One registered IPC mutation is not exposed through preload

Main registers:
- `uai:comms:lock:list` (`app/main/index.ts:473-475`)

But preload does not expose a corresponding method in `uaiApi.comms` (`app/main/preload.ts:140-166`).

So there is at least one bridge completeness gap already.

### 5.2 There are two independent `UaiApi` type surfaces, and they have already drifted

Real preload/exported API:
- `app/main/preload.ts:60-269`
- exported as `UaiApi` at `app/main/preload.ts:267-269`

Package-level duplicate interface:
- `packages/renderer-ui/src/global.d.ts:52-132`

App-level renderer type:
- `app/renderer/global.d.ts:5-10`

The duplicate package-level interface is missing methods that preload actually exposes, including:
- `briefs` (`preload.ts:120-124`)
- `search` (`preload.ts:178-180`)
- `logTail` (`preload.ts:204-215`)
- `getVersion` (`preload.ts:261-265`)
- `transcript.history` (`preload.ts:196-201`)

The app-level `global.d.ts` importing `UaiApi` from preload masks this for app compilation, but `renderer-ui` as a package is carrying a stale shadow interface.

This is a real maintenance smell.

### 5.3 Many IPC channels are still stringly typed instead of using `IPC` constants

Examples in preload and main:
- `'traits:list'`, `'traits:load'`, `'traits:status'`
- `'uai:search'`
- `'uai:activityLog:read'`
- `'transcript:read'`
- `'terminal:attach'`

See: `app/main/preload.ts:150-265`, `app/main/index.ts:342-699`

The `IPC` constant object exists (`packages/shared/src/types.ts:209-255`), but it is only partially used. That makes channel drift more likely over time.

---

## 6. Store architecture — RED

## What is solid

- The renderer does have reusable stores, not pure component-local state.
- `SessionStore`, `FolderStore`, `CardStore`, `TagStore`, and `RelationshipStore` each have a clear local responsibility.

## Findings

### 6.1 `card-store` is not the renderer's single source of truth

The renderer is actually pulling from multiple overlapping stores:
- `useSessionStore()`
- `useAppStateStore()`
- `useFolderStore()`
- `useCardStore()`
- `useRelationships()`
- direct `window.uai` query usage

`Navigator` alone consumes four of them:
- `packages/renderer-ui/src/components/Navigator.tsx:445-449`

That is not “card-store as source of truth.” It is a composite, partially duplicated store graph.

### 6.2 `card-store` duplicates upstream data instead of owning it

`card-store` rebuilds its own map from:
- bootstrap sessions
- container data
- projects
- briefs
- teams

See: `packages/renderer-ui/src/stores/card-store.ts:97-128`, `138-172`

So it is not an authoritative card source. It is an adapter cache layered on top of other stores and APIs.

That is workable, but then its refresh policy must be excellent. Currently it is not.

### 6.3 `card-store` refresh logic ignores most of the slices it serves

The store exposes sessions, folders, groups, projects, briefs, and teams (`card-store.ts:293-298`), but it only refreshes when store changes include `sessions` or `folders` (`card-store.ts:264-268`).

That is the most important store-architecture problem in the current app.

### 6.4 `BottomPanel` keeps its own tab model outside shared state

`BottomPanel` maintains:
- `activeTab`
- `tabs`
- `logFilter`
- `addMenuOpen`

as local component state (`BottomPanel.tsx:75-78`).

For transient UI this is fine, but these are still structural state concepts for a configurable drawer. They are not represented in any shared store, so the bottom panel is effectively a local mini-store.

### 6.5 `AppStateStore` contains stale mutation helpers that bypass the architectural direction

`openTab()`, `closeTab()`, and `activateTab()` still mutate `appState` locally and persist through `updateAppState()` (`app-state-store.ts:105-138`).

Search shows these helpers are mostly no longer the preferred path, but the API still exists. That is architectural residue from pre-CommandBus tab handling.

---

## 7. Code quality concerns — YELLOW

## Findings

### 7.1 Several files are too large and mix unrelated responsibilities

Biggest examples:
- `app/main/command-handlers.ts` — **1253 lines**
- `packages/renderer-ui/src/components/Navigator.tsx` — **938 lines**
- `app/main/index.ts` — **789 lines**
- `packages/renderer-ui/src/components/ContextPanel.tsx` — **472 lines**
- `packages/renderer-ui/src/components/Workspace.tsx` — **440 lines**

This shows up concretely as:
- repeated ad hoc file mutation code for app state in `command-handlers.ts:307-315`, `1148-1220`
- multiple nested UI mini-components living inside `Navigator.tsx`
- preload acting as a giant manually maintained API object

### 7.2 `any` and unchecked casts are still used in architecture-sensitive paths

Examples:
- `MemorexView.tsx` parses transcript payloads using `any` (`MemorexView.tsx:83-97`)
- `TabContentPane.tsx` uses `(card as any).tracking_id` (`TabContentPane.tsx:291-296`)
- `command-handlers.ts` casts in undeclared relationship metadata (`command-handlers.ts:178-180`)

These are exactly the spots where contract drift tends to hide.

### 7.3 Error handling is inconsistent and often too quiet

Patterns like these appear frequently:
- `catch { return []; }`
- `catch { return {}; }`
- `catch { /* ignore */ }`

Examples:
- `app/main/index.ts:237-318`, `396-425`, `479-489`
- `packages/renderer-ui/src/stores/card-store.ts:132-135`, `173-175`
- `packages/renderer-ui/src/stores/session-store.ts:48-52`

This keeps the UI alive, which is good, but it also suppresses architectural symptoms. For a system driven by cross-process coordination, silent fallback makes real drift harder to detect.

### 7.4 `app.state.update` is too generic

The app-state command currently accepts an arbitrary `patch` bag and does a shallow merge:
- `app/main/command-handlers.ts:307-315`

That forces renderer callers to do read-modify-write logic themselves (see pinning in `Navigator.tsx:203-209`) and makes nested updates collision-prone. This is a design-quality issue that will keep resurfacing as more UI state is added.

---

## 8. Monorepo health — YELLOW

## What is solid

At the package level, the dependency direction is mostly clean:
- `packages/shared` depends on `architecture/contracts` (`packages/shared/src/cards.ts:8-15`, `packages/shared/src/types.ts:11-24`)
- `packages/renderer-ui` depends on `@uai/shared`
- `app` depends on `@uai/shared` and `@uai/renderer-ui` (`app/renderer/App.tsx:15-25`, `app/main/preload.ts:14-27`)

I do **not** see an obvious package-level circular dependency in the core app/package layering.

## Findings

### 8.1 `renderer-ui` leaks directly into `architecture/contracts`

`Navigator.tsx` imports contract types directly:
- `packages/renderer-ui/src/components/Navigator.tsx:24`

That bypasses the shared runtime facade and weakens the intended package layering.

### 8.2 `packages/shared/src/types.ts` is acting as a shadow contract layer

Instead of cleanly re-exporting contract types, it duplicates several important runtime interfaces (Session, Command, CommandResult, AppState, EntityRelationship).

See: `packages/shared/src/types.ts:28-205`

That is the main monorepo health problem. `shared` should be the stable runtime facade over contracts, not a second contract system.

### 8.3 The packages are not being type-checked as isolated packages

`app/tsconfig.json` pulls the whole tree together:
- `app/tsconfig.json:17-26`

That means `renderer-ui` can accidentally rely on app-level global typings (for example via `app/renderer/global.d.ts:5-10`) and still compile, even if its own package-local typing is stale.

So the dependency direction is conceptually clean, but the compile boundary is not very strict.

---

## Recommended next moves

## Priority 1 — fix structural drift

1. **Make `packages/shared/src/types.ts` stop redefining contract-owned shapes.**  
   Re-export where possible; define only truly runtime-only additions.

2. **Route all persisted comms mutations through the CommandBus.**  
   Especially `send`, queue hold/release/change/remove, and lock set/remove.

3. **Close the Path 2 gaps.**  
   Add signal/watch coverage for projects, teams, and briefs, and make `card-store` refresh all slices it owns.

## Priority 2 — clean the store model

4. **Decide whether `card-store` is an adapter cache or the renderer source of truth.**  
   Right now it claims both and achieves neither cleanly.

5. **Remove or privatize stale local tab mutation helpers in `app-state-store.ts`.**

6. **Replace generic `app.state.update` patch bags with narrower commands for durable UI state changes.**

## Priority 3 — tighten package boundaries

7. **Make `renderer-ui` consume `@uai/shared` only; remove direct contract imports.**

8. **Unify the `UaiApi` type definition.**  
   The preload export should be the single source of truth, and package-local `global.d.ts` should derive from it or be generated.

9. **Consider separate package-level typechecks** for `packages/shared` and `packages/renderer-ui`, not just the umbrella app build.

---

## Final assessment

The architecture is **promising but not yet self-consistent**.

The best parts are:
- the package direction,
- the existence of a real CommandBus,
- and the move toward shared card/entity abstractions.

The weakest parts are:
- contract/runtime drift,
- incomplete CommandBus discipline,
- and partial Path 2/store refresh behavior.

If you want one sentence:

> The app has a recognizable architecture, but it is currently enforced by convention more than by the code itself.

That is still fixable at this stage, but I would treat it as priority maintenance rather than cosmetic cleanup.
