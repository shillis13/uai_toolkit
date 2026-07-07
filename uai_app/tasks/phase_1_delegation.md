# Phase 1 Delegation Package

**Date:** 2026-04-23
**Author:** Continuity II (Claude CLI, Architect)
**Status:** Draft — for PianoMan review before delegation

---

## Delegation Model

Recursive decomposition. Each workstream lead receives:
- This document (full plan for context)
- Their specific workstream section (execution scope)
- The spike codebase (proven patterns to replicate)
- The architecture spec + contracts (requirements)

Each workstream lead assesses whether to split further or execute directly.
If splitting, they become integration + test for their children.
Work stops splitting when it can't be broken into independent chunks.

**Integration checkpoints:** Each workstream produces deployable code that runs
in the spike app. No isolated components — everything must wire in and render.

**Escalation:** Questions about architecture → Continuity II (20260422_204104_640a7e0c_cla).
Questions about UX/scope → PianoMan. Blockers → don't stall, note the assumption
and proceed, flag in checkpoint.

---

## Dependency Order

```
Phase 0A: Contracts (DONE — architecture/contracts/*.ts)
Phase 0B: Spike (DONE — src/)
    │
    ▼
Phase 1A: Core Stores + Command Bus
    │     (no UI dependency — pure infrastructure)
    │
    ├──────────────────┐
    ▼                  ▼
Phase 1B:          Phase 1C:
Core UI            Organization
(depends 1A)       (depends 1A)
    │                  │
    └────────┬─────────┘
             ▼
         Phase 1D:
         Observability + Quality Gates
         (depends 1B + 1C)
```

1A must complete before 1B and 1C can start.
1B and 1C can run in parallel.
1D starts after both 1B and 1C deliver.

---

## Workstream 1A: Core Stores + Command Bus

**Goal:** Replace ad-hoc IPC with the architectural foundation. All subsequent
workstreams build on these abstractions.

**Scope:**

### 1A.1 — Command Bus

Implement the command bus from `contracts/commands.ts`:

- `CommandBus` class in main process
  - `register(type, handler)` — register command handler
  - `execute(command)` → `Promise<CommandResult>` — dispatch and execute
  - `before(pattern, hook)` — pre-execution hook (glob patterns: `session.*`)
  - `after(pattern, hook)` — post-execution hook
- Command envelope: `id`, `type`, `payload`, `origin`, `actor`, `timestamp`
- Command result: `ok`, `command_id`, `data`, `error`, `changed`, `effects`
- Global hooks:
  - `before('*')` — log every command
  - `before('*')` — access control check (origin vs command safety)
- IPC bridge: renderer calls `window.uai.execute(command)` → main process CommandBus

**Key pattern from spike:** Current IPC handlers (`ipcMain.handle('uai:sessions:update', ...)`)
become command handlers registered on the bus. The IPC layer becomes a thin dispatcher.

**Acceptance:**
- All existing spike functionality works through the command bus
- `session.update`, `session.create` commands registered and functional
- Before/after hooks fire and log
- Command results include `changed` slices

### 1A.2 — Store Layer

Formalize the renderer stores from the spike pattern:

- `SessionStore` — refactor from spike's `session-store.ts`
  - Singleton shared state with subscription model
  - `subscribe(listener)` → unsubscribe function
  - `getSession(trackingId)`, `listSessions(filter?)`, `getByCliUuid(uuid)`
  - Refreshes on `onStoreChanged` events (already working in spike)
- `AppStateStore` — new
  - Reads/writes `app_state.json` via main process IPC
  - Holds: tabs, pinned, notes, lastViewedAt, panel sizes, card display prefs
  - Same subscription model as SessionStore
- `FolderStore` — new (stub for 1C)
  - Reads `folders.json` via main process IPC
  - Holds folder tree for navigator
- Bootstrap: `window.uai.bootstrap()` returns all store snapshots in one call (already in spike)

**Key pattern from spike:** `useSessionStore()` hook — singleton state, listener set, notify on change.
Replicate for AppState and Folders.

**Acceptance:**
- Three stores initialized from bootstrap
- All stores refresh on `onStoreChanged` events
- Components use stores via hooks, never direct IPC
- Switching sessions updates all consuming components reactively

### 1A.3 — Component API Framework

Implement the `describe()` and component registration system from `contracts/components.ts`:

- `ComponentRegistry` — holds all registered components
  - `register(id, component)` — register a component with its description
  - `get(id)` → component instance
  - `describe(id)` → `ComponentDescription`
  - `describeAll()` → full component tree
  - `list()` → all component IDs
- Each architectural component provides `describe()` returning `ComponentDescription`
- Start with: `SessionNavigator`, `Workspace`, `SessionPane`, `ContextPanel`, `BottomPanel`
- Descriptions include: state keys, commands, actions, events, context requirements

**Acceptance:**
- `ComponentRegistry.describeAll()` returns the full tree
- At least 3 components registered with meaningful descriptions
- Description schema matches `contracts/components.ts` `ComponentDescription` interface

### 1A.4 — Action Context Providers

Implement `ActionContextProvider` from contracts:

- React context provider wrapping actionable regions
- Provides: `entity_ref`, `selection`, `select_mode`, `location`
- `resolveActionTargets(clicked_id, context)` works per contract
- `useActionContext()` hook for consuming components

**Acceptance:**
- Context menu actions use `resolveActionTargets` (replaces spike's ad-hoc logic)
- Multi-select + context menu applies to all selected when clicking a selected item

**Deliverable:** All code in `src/shared/` (bus, registry) and `src/renderer/stores/` (stores).
Main process command bus in `src/main/command-bus.ts`. Update `src/main/index.ts` to route
IPC through command bus.

---

## Workstream 1B: Core UI

**Goal:** Replace the spike's minimal UI with the architectural components from the
frontend design spec. Must use stores and command bus from 1A.

**Depends on:** 1A complete.

**Scope:**

### 1B.1 — Tabbed Navigator (Left Panel)

Replace the spike's `SessionList` with the full navigator:

- Tab bar at top: Sessions | Briefs | Teams | Projects
  - Start with Sessions and Briefs tabs functional
  - Teams and Projects tabs show "Coming soon" placeholder
- Sessions tab:
  - Filter toolbar: status pills (Active/Stopped/Archived), platform pills, text search
  - Sort control: Activity | Created | Name, asc/desc
  - Collapsible Active/Stopped sections
  - Session cards with platform color bars, status dots, meta fields
  - Right-click context menu: Rename, Copy IDs, Move to Folder (stub)
  - Multi-select mode with bulk actions
- Briefs tab:
  - Brief cards with parchment styling (from UCI)
  - Basic list with search
- Carry forward: UCI's `FilterBar` pill design, `CardListView` sort controls

**Key pattern from spike:** `SessionList.tsx` — replace with `Navigator.tsx` that reads
from `useSessionStore()` and dispatches commands.

**Acceptance:**
- Sessions tab renders all sessions from store
- Filter by platform and status works
- Sort by activity/created/name works
- Context menu with Rename dispatches `session.update` command
- Briefs tab renders briefs from store (requires brief store from 1A.2 or stub)
- Navigator registers with ComponentRegistry and provides `describe()`

### 1B.2 — Workspace (Center)

Replace the spike's direct session rendering with tab-based workspace:

- Tab bar with platform color indicators
- Click session in navigator → opens in tab
- Multiple tabs open simultaneously
- Active tab highlighted
- Close tab (× button, Cmd+W)
- Tab switching (click, Cmd+1-9, Cmd+Shift+[/])
- When no tab active → show card grid (browse mode)
- Tab state persisted in AppStateStore

**Key pattern from spike:** `App.tsx` currently tracks `activeSessionId`. Replace with
`useAppStateStore()` for tab state.

**Acceptance:**
- Multiple sessions open in tabs
- Switching tabs switches terminal
- Tab state survives app restart (via app_state.json)
- Workspace registers with ComponentRegistry

### 1B.3 — Terminal Pane + Memorex

Carry forward from spike with architectural integration:

- Terminal pane renders inside workspace tabs
- Memorex toggle and draggable split (already working)
- Terminal selection overlay (already working)
- Session pane header with session info
- Stopped sessions show transcript-only mode (no terminal)

**Acceptance:**
- Spike terminal functionality preserved
- Memorex preserved
- SessionPane registers with ComponentRegistry

### 1B.4 — PromptBox (Bottom of Center)

New component — staged prompt input:

- Text area at bottom of workspace
- Shows target session: "→ Session Name"
- Cmd+Enter stages text to active terminal
- Per-session prompt state (switching tabs preserves draft)
- Auto-grow/shrink
- Resize handle

**Acceptance:**
- Cmd+Enter sends text to the active terminal session
- Switching tabs preserves unsent text
- PromptBox registers with ComponentRegistry

### 1B.5 — Context Panel (Right, Collapsible)

New component — session details:

- Collapsible right panel (toggle button in header)
- Details tab: session metadata (tracking ID, CLI UUID, platform, status, roles, notes, tags)
- Click-to-copy on identity fields
- Notes section: collapsible, editable, saves via `session.update` command
- Resizable width

**Acceptance:**
- Panel opens/closes
- Shows details for the active tab's session
- Notes edit and save via command bus
- Panel width persisted in AppStateStore
- ContextPanel registers with ComponentRegistry

**Deliverable:** All code in `src/renderer/components/`. CSS in component-scoped files
under `src/renderer/styles/`.

---

## Workstream 1C: Organization Entities

**Goal:** Folders, tags, and entity relationships — the organizational layer.

**Depends on:** 1A complete.

**Scope:**

### 1C.1 — Folder System

Implement folder CRUD and navigation:

- Folder tree in navigator (within Sessions and Briefs tabs)
- Create folder (inline input in navigator)
- Move session/brief to folder (context menu → folder cascade submenu)
- Breadcrumb navigation
- Show All Descendants toggle
- folders.json persistence via main process IPC
- FolderStore in renderer with subscription model

**Key reference:** UCI's folder system is proven. Port the data model and IPC handlers.
Use command bus for all mutations.

**Acceptance:**
- Create, rename, delete folders
- Move cards between folders
- Folder tree renders in navigator
- Breadcrumbs show current location
- All mutations go through command bus

### 1C.2 — Tag System

General-purpose tags beyond the single "condenser" tag:

- Tag CRUD (create with name + color)
- Add/remove tags on sessions and briefs
- Tag management UI (settings or dedicated panel)
- Filter by tags in navigator
- Bulk tag operations (multi-select → add/remove tag)
- SQLite `card_tags` table (already exists)

**Acceptance:**
- Create tags with custom colors
- Tag/untag sessions via context menu
- Filter navigator by tag
- Bulk tag via multi-select

### 1C.3 — Entity Relationships

Typed links between sessions, briefs, and other entities:

- Relationship CRUD via `entity_relationships` table (already exists)
- Display relationships in context panel
- Link types: forked_from, briefed_to, launched_from, loaded, member_of, continues, relates_to
- Visual indicators on cards when linked

**Acceptance:**
- Create relationships via context menu or automated flows
- View relationships in context panel
- Relationships display on cards (small badge/indicator)

**Deliverable:** Folder, tag, and relationship code in stores + components + main process handlers.

---

## Workstream 1D: Observability + Quality Gates

**Goal:** Logging, monitoring, and the test/acceptance infrastructure that prevents
the "placeholder div catastrophe" from recurring.

**Depends on:** 1B + 1C complete.

**Scope:**

### 1D.1 — Bottom Panel

New component with tabs:

- Related Entities tab: children, linked sessions, briefs, team members for focused session
- Session Log tab: per-session log viewer (reads from session dir logs)
- App Log tab: application-wide event log
- System Monitor tab: CPU, memory, active sessions, error count
- Drawer bar: summary metrics visible when panel is collapsed

**Acceptance:**
- Panel opens/closes, resizable height
- Related entities shows connections for active session
- App log shows command execution history
- Monitor shows basic system metrics
- BottomPanel registers with ComponentRegistry

### 1D.2 — Command Logging

All command bus activity logged:

- Command log: type, origin, timestamp, result, duration
- Viewable in App Log tab
- Filterable by command type, origin, success/failure

**Acceptance:**
- Every command execution appears in the log
- Errors are visually distinct
- Log persists for session lifetime

### 1D.3 — Quality Gates

Acceptance test infrastructure:

- Component description contract tests: every registered component's `describe()` output
  validates against the `ComponentDescription` schema
- Command schema tests: every registered command type has a valid descriptor
- Store refresh tests: external signal file touch → renderer store updates
- Packaged app smoke test: build, launch, verify sessions load
- Test script that runs all gates and produces pass/fail report

**Acceptance:**
- `npm run validate` passes all contract tests
- Packaged app launches and loads real sessions
- Gate checklist artifact produced

---

## Cross-Cutting Concerns

### Design Tokens

All workstreams use design tokens from `styles.css` `:root` variables.
No raw color values, no magic numbers. If a token is missing, add it to `:root`.

### Component CSS

Each new component gets its own CSS section in `styles.css` (or a separate file
if we split later). Token-only values.

### ComponentRegistry

Every architectural component (Navigator, Workspace, SessionPane, PromptBox,
ContextPanel, BottomPanel) registers with the ComponentRegistry and provides
`describe()`. This is not optional — it's what makes UAI different from UCI.

### Command Bus

All domain mutations go through the command bus. No direct IPC for mutations.
Queries (read-only) can use direct IPC for now.

### Store Subscriptions

Components subscribe to stores. No polling. No prop-drilling for domain state.
Local UI state (e.g., dropdown open) stays in component useState.

---

## Team Composition (Recommended)

| Role | Platform | Workstream |
|------|----------|------------|
| Architect / Integrator | Claude CLI | Oversees all, integrates at checkpoints |
| 1A Lead | Claude CLI or Codex | Core infra — needs architecture precision |
| 1B Lead | Claude CLI | UI work — needs React + xterm.js experience |
| 1C Lead | Claude CLI | Organization — needs UCI folder/tag knowledge |
| 1D Lead | Codex | Testing/observability — cross-platform rigor |
| Reviewer | Codex | Reviews all workstream deliverables |

PianoMan's involvement: review integration checkpoints (15-30 min/day),
UX judgment calls when escalated, scope decisions.

---

## Reference Documents

| Document | Path | Purpose |
|----------|------|---------|
| Architecture spec | `architecture/uai_architecture_v1.1.md` | Requirements |
| Contracts | `architecture/contracts/*.ts` | Frozen type definitions |
| Identity spec | `architecture/spec_session_identity_v5.4.md` | Session identity contract |
| Gap analysis | `architecture/gap_analysis.md` | What carries from UCI |
| Phase 0B completion | `docs/phase_0b_completion.md` | Spike patterns + lessons |
| Spike codebase | `spikes/phase_0b_vertical_slice/` | Working reference implementation |
| UCI data architecture | `architecture/current_references/uci_data_architecture.md` | Store sync protocol |
| Codex reviews | `reviews/codex_architecture_review_v1.md`, `v1.1.md`, `codex_identity_v5.4_review.md` | Architectural constraints |
| Lessons learned | `docs/lessons-learned.md` | Process failures to avoid |
