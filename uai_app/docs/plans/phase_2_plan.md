# UAI Phase 2 Plan

**Date:** 2026-04-27 (updated 2026-05-12)
**Author:** Session 20260425_234902_acd5d3bd_cla + PianoMan
**Status:** Phase 2 substantially complete — 7 of 11 workstreams done or implemented
**Predecessor:** Phase 1 (48 files, 30 tests) + Phase 2A (card/container abstraction, Codex review fixes)

---

## Scope

Phase 2 builds on the card/container abstraction (2A) to deliver the workspace experience: groups, tab groups, grid layouts, projects, tags, and the supporting UI. Heavy backend features (Teams, AI Comms, embedded AI) are Phase 2 late or Phase 3.

**As of 2026-05-12:** The core workspace experience workstreams (2A-2D, 2F, 2G) are complete and delivered via fork integration. AI Comms (2L) is implemented but untested end-to-end. Grid Layout (2E), Prompt Box (2H), and Right Panel (2I) are explicitly deferred. Inbox (2J) and Teams (2K) are staged but not started.

---

## Key Design Decisions

### Tabs Are Entity Views

Every tab in the workspace is a view of an entity. The tab model carries a type discriminant that determines what renders in the content pane:

```typescript
type TabType = 'session' | 'folder' | 'group' | 'terminal' | 'brief' | 'transcript' | 'search';

interface Tab {
  id: string;
  type: TabType;
  label: string;
  targetId: string;  // tracking_id, folder_id, group_id, terminal_id, brief_name, search_query
  openedAt: string;
}
```

The workspace content pane dispatches to the appropriate renderer based on `tab.type`:

| Tab Type | Content | Chrome |
|----------|---------|--------|
| `session` | Terminal + Memorex + PromptBox (active sessions) | Standard tab |
| `folder` | CardListView + ContainerTreeView + breadcrumbs (like file explorer) | Standard tab |
| `group` | Group management — member list, actions | Group Tab header (bracket start) |
| `terminal` | Raw shell (no AI session — ssh, bash, process watcher) | Standard tab |
| `brief` | Rendered brief document view | Standard tab |
| `transcript` | Formatted JSONL conversation history (inactive sessions) | Standard tab |
| `search` | Cross-session search results, click-to-navigate | Standard tab |

The current `SessionPane` becomes a `TabContentPane` that selects the right component. Same tab bar chrome (close button, context menu, drag), different guts.

### Folders vs Groups — Different Workspace Projections

Both folders and groups are containers in the card/container model. The difference is how they project into the workspace:

**Folders** (exclusive placement):
- Opening a folder creates a **folder tab** — a content browser showing session cards and child folders
- Navigable like a file explorer: click a session to open it in its own tab, click a child folder to drill in, breadcrumbs to go back up
- The folder tab is for browsing, not running

**Groups** (non-exclusive placement):
- Opening a group creates a **Group Tab** — a bracket in the tab bar containing all visible member session tabs
- Member sessions become live tabs with terminals inside the bracket
- The group header tab is a control surface: collapse/expand, manage members, grid layout selector
- A Group Tab is for working — multiple related sessions open at once

UCI's mistake was that folders had no tab representation at all, forcing Groups to be bolted on as a separate system. In UAI, both are containers — they just project differently into the workspace.

### Transcript — Dual Rendering Mode

TranscriptView renders formatted JSONL conversation history. It has two rendering modes depending on session state:

**Inactive session** → Transcript renders **in the center panel** as the tab content. This is the primary view for non-running sessions — read-only, scrollable, formatted conversation blocks. When you open an inactive session, you see its transcript, not a dead terminal.

**Active session** → Transcript renders in a **separate Electron `BrowserWindow`**. The center panel shows the live terminal (SessionView with TerminalPane + Memorex + PromptBox). The transcript window is a pop-out you can position on another monitor, resize, scroll independently while interacting with the live session.

Implementation:
- Both windows share the same main process, same IPC bridge, same preload
- The transcript window loads the same renderer entry with `?view=transcript&session=<id>` query param
- `App.tsx` checks the URL param and renders `TranscriptView` instead of the full shell
- Both windows call `window.uai.transcript.read()` — same data, same API
- Coordination between windows (e.g., "click turn in transcript → highlight in terminal") goes through the main process as relay

New command: `transcript.openWindow` spawns the `BrowserWindow`. Action available from active session's context menu or a toolbar button.

### Search — Center Panel View

SearchView renders cross-session search results in the center panel. Clicking a result navigates to the matching session/turn — either opening a transcript tab (inactive session) or scrolling the live terminal (active session).

Search is a tab type (`type: 'search'`) with `targetId` holding the search query or search ID. Multiple search tabs can be open simultaneously with different queries.

### Extensible Tab Types

The `TabType` union is extensible. Adding a new tab type requires:
1. Add the type string to `TabType`
2. Create a content component for that tab type
3. Add the dispatch case in `TabContentPane`
4. Define the context menu for tabs of that type

No changes to the tab bar, tab management, or persistence — those are generic.

### App Shell Layout Model

**Decision (2026-05-07):** Tab Bar and Title Bar are top-level shell elements, not owned by the center panel. The right panel sits below the tab bar, sharing vertical space with the focus area.

```
┌─────────────────────────────────────────────────────────┐
│  App Window                                             │
├────────┬────────────────────────────────────────────────┤
│        │  Tab Bar (full width minus nav)          [1]   │
│        ├────────────────────────────────────────────────┤
│  Nav   │  Title Bar / Session Info                [2]   │
│  Panel ├──────────────────────────┬─────────────────────┤
│  [0]   │                          │                     │
│        │  Focus Area        [3]   │  Right Panel  [4]   │
│        │  (content for active     │  (Details, Docs,    │
│        │   tab type)              │   Memory, Messages, │
│        │                          │   Prompts)          │
│        │                          │                     │
│        ├──────────────────────────┴─────────────────────┤
│        │  Bottom Panel (Activity, Metrics)        [5]   │
├────────┴────────────────────────────────────────────────┤
│  Status Bar                                       [6]   │
└─────────────────────────────────────────────────────────┘
```

**Top-level layout zones (shell-owned):**

| Zone | Name | Behavior |
|------|------|----------|
| [0] | Nav Panel | Left, full height. Collapsible. Contains Navigator component. |
| [1] | Tab Bar | Top, full width minus nav. Contains tabs + group brackets. Shell-owned — not part of center panel. |
| [2] | Title Bar | Below tab bar, full width minus nav. Shows active session/entity info, action buttons. |
| [3] | Focus Area | Below title bar, left side. Renders content for the active tab type via TabContentPane. Shares width with right panel. |
| [4] | Right Panel | Below title bar, right side. Resizable width. Multiple tabs (Details, Docs, Memory, Messages, Prompts). Pushes into center area, does NOT extend above tab bar. |
| [5] | Bottom Panel | Below focus area + right panel. Collapsible. Activity log, metrics. |
| [6] | Status Bar | Bottom edge. App version, connection status. |

**Why Tab Bar is shell-level:** The tab bar shows tabs for sessions, folders, groups, search — things that affect what both the focus area AND the right panel display. Group tab brackets span the full width above both. It doesn't belong to the center panel.

**Why Right Panel is below Tab Bar:** The right panel shows contextual details for the active tab. It shouldn't compete with the tab bar for visual hierarchy. The tab bar and title bar extend full-width to the window edge, establishing the navigation context. The right panel lives within that context, not alongside it.

**Resizing interactions:**
- Right panel width resize: focus area shrinks/grows, tab bar and title bar unaffected
- Bottom panel height resize: focus area and right panel shrink/grow equally
- Nav panel width resize: tab bar, title bar, focus area, right panel all adjust

### Microfrontend Architecture — Component-as-Package

**Decision (2026-05-03):** UAI uses a monorepo with independently-developable component packages, Storybook for isolated UI development, and a thin app shell that discovers and mounts components via a registry.

**Package manager:** npm workspaces (not pnpm — Electron Forge doesn't follow pnpm symlinks for native modules, issue #4188).

**Structure:**
```
unified_ai_interface/
├── packages/
│   ├── shared/              # Types, contracts, component registry, entity types
│   ├── renderer-ui/         # All React components + Storybook stories
│   └── (future packages as components grow and need isolation)
├── app/
│   ├── main/                # Main process (IPC handlers, node-pty, stores, indexers)
│   ├── renderer/            # App.tsx entry point — shell that mounts layout zones
│   ├── forge.config.ts
│   └── vite.*.config.ts
├── .storybook/              # Global Storybook config with window.uai mock decorator
└── package.json             # npm workspaces root
```

**Shell responsibility:** The `app/renderer/` shell owns the layout grid (zones 0-6 above), IPC bridge setup, event bus, and component mounting. It does NOT contain UI component logic — it imports components from packages and mounts them into zones.

**Storybook mocking:** A global decorator in `.storybook/preview.tsx` sets up `window.uai` with a mock implementing the `UaiApi` type. Components that talk to the main process through `window.uai.*` work identically in Storybook with mock data. Only TerminalPane (node-pty + xterm.js) is truly platform-coupled — everything else is Storybook-able.

**Component contracts:** Each component declares what it provides to children and requires from its parent, using TypeScript interfaces in the shared package. The shell mounts components based on their registered `handles` (which tab types, which panel zones).

**Component discovery:** Build-time Vite plugin scans package directories and generates a registry import. No runtime module loading — components are bundled into the app at build time.

**Start small, split later:** Begin with shared + renderer-ui + app. Split renderer-ui into separate packages (navigator, session-view, prompt-box, etc.) only when parallel development actually creates merge conflicts. Premature splitting adds build complexity without benefit.

### UCI Feature Patterns to Port

**Decision (2026-05-07):** These UCI patterns should be adopted in UAI, porting the design approach but implementing against UAI's card/container/tab architecture.

| UCI Feature | Implementation Pattern | Priority |
|-------------|----------------------|----------|
| **Memorex pill filters** | 4 toggle pills (You/Claude/Tools/Thinking) with per-type expand/collapse. Dual-button: toggle visibility + collapse all. Tokyo Night colors. | High |
| **Rich session tooltips** | Portal-based (`createPortal` to `document.body`). 200ms hover delay. Positioned above card, 125% width. Comprehensive data: status, platform, role, IDs, context %, tags, timestamps. | High |
| **Pinned session cards** | 📌 icon on card. Pinned items sort to top regardless of sort field. Pin/unpin via context menu. | High |
| **Right panel 5 tabs** | Details, Docs, Memory, Messages, Prompts. Lazy-load per tab. Badge counts on Messages (unread) and Prompts (queued). | Medium |
| **Right panel Messages tab** | 3 folders (Inbox/Sent/Archive). Multi-select checkboxes. Actions: Add Pre/Post Prompt, Remind, Archive. Feeds into UAI's 2J Inbox workstream. | Medium |
| **Filter bar pill pattern** | Uniform 26px height, 14px radius. Status/Platform/Date groups with separators. On/off color states. Date range with duration parser. | Medium |

## Current State

**As of 2026-05-12:**

- **55 tests passing**, TypeScript clean (2A alone has 55 tests)
- Card/container abstraction done: BaseCard, ContainerCapability, AnyCard discriminated union
- Container manager with exclusive (folders) and non-exclusive (groups) placement rules
- Generic card rendering: CardListView, ContainerTreeView, CardRenderer with type dispatch
- Command result handling: executeCommand wrapper with toast/inline/log/silent channels
- External change signals for all store slices
- After-hook model with result/duration and error isolation
- Launch lifecycle with spawn monitoring and identity_status persistence
- Codex review: two rounds, most findings resolved
- Navigator fully refactored with all 5 nav tabs working (Sessions, Folders, Groups, Tags, Projects)
- Generic TabType with TabContentPane dispatch and workspace-tab-type indicators
- 18 project cards rendered from real devTree data
- TagBadge and TagPicker components integrated
- AI Comms backend phases 1-3 implemented with MessagesTab, PromptsTab, ComposeMessage, conversation locks

### Current Architecture

- **Monorepo structure** completed 2026-05-08: `packages/shared` + `packages/renderer-ui` + `app/`
- **Storybook** configured with mock `UaiApi` — components develop in isolation
- **Old `src/` directory** is stale and can be removed (superseded by monorepo packages)
- **Electron Forge start** has a process management bug; use `scripts/start.sh` or the packaged `.app` instead

## Reference Implementations

### UCI Tab Groups (to port/adapt)
- **Source:** `ai_general/projects/unified_cli_interface/src/src/renderer/`
- **Key files:** `GroupCard.tsx`, `GroupRail.tsx`, `TabBar.tsx` (bracket rendering), `shared/groups.ts` (TabGroup type), `main/groups.ts` (IPC)
- **Design worth preserving:**
  - `sessionIds` (all members) vs `visibleIds` (currently shown as tabs) split
  - Bracket rendering in tab bar with color-coding and collapse/expand
  - Open/close group = open/close member tabs (not delete)
  - Explicit membership (no auto-generation)
  - `SplitLayout` type defined: `'single' | 'vertical_2' | 'horizontal_2' | 'grid_2x2'`
  - 8-color palette chosen to avoid confusion with active tab highlight
- **What to fix in UAI:**
  - No separate `groups.json` — groups live in `containers.json` via container manager
  - Group home tab should be a real entity card, not a synthetic `group:<id>` special-case
  - No legacy Group system to conflict with — clean namespace
  - `SplitLayout` actually gets implemented (2E)

### Memorex Overlay
- **Source:** Ported from UCI production (`unified_cli_interface/src/src/renderer/components/TerminalFormatOverlay.tsx`) on 2026-05-21
- **Current:** `TerminalFormatOverlay.tsx` in `packages/renderer-ui/src/components/`, rendered as sibling overlay in `TerminalPane.tsx`
- **Status:** Working in production. Scrollback-based opaque overlay with Unicode marker classification, pill filters, section collapsing.

---

## Workstreams

### 2B — Groups (Navigator)
**Status:** DONE (fork delivery integrated)
**Effort:** Small
**Dependencies:** 2A (done)
**What:** Make non-exclusive container groups visible and manageable in the Navigator.

- ~~Add "Groups" tab to Navigator tab bar~~
- ~~Register `'group'` container type (already defined in contracts)~~
- ~~`container.create` with `type:'group'` already works — wire to "Create Group" UI~~
- ~~CardListView + ContainerTreeView with entity_type filter for groups~~
- ~~Context menu: rename, delete, add session to group, remove from group~~
- ~~Group cards show member count and non-exclusive badge~~

**Done when:** User can create groups, add/remove sessions, see groups in Navigator, delete groups. Groups persist across app restart.

### 2C — Navigator Refactor
**Status:** DONE (fork delivery integrated; all 5 nav tabs working)
**Effort:** Medium
**Dependencies:** 2A (done)
**What:** Replace Navigator's inline SessionCard rendering with the generic card components.

- ~~Sessions tab uses `CardListView` (replacing inline `SessionCard` function component)~~
- ~~Folder tree navigation via `ContainerTreeView` with breadcrumbs~~
- ~~Briefs tab (currently placeholder) renders BriefCards via CardListView~~
- ~~Filter/sort controls work with the generic card model~~
- ~~Multi-select works through CardListView's cmd/ctrl+click~~

**Done when:** Navigator renders all entity types through the generic card system. Folder navigation works with breadcrumbs. Briefs tab shows real data.

### 2D — Tab Model + Workspace Pane Abstraction
**Status:** DONE (generic TabType, TabContentPane dispatch, workspace-tab-type indicators)
**Effort:** Medium
**Dependencies:** 2B (done), 2C (done)
**What:** Generalize the tab and workspace pane model to support multiple tab types, then implement Group Tabs with bracket rendering.

**Tab model refactor:**
- ~~Replace `TabState` (session-only) with generic `Tab` type carrying `type: TabType` discriminant~~
- ~~`TabType = 'session' | 'folder' | 'group' | 'terminal' | 'brief'`~~
- ~~Each tab has `targetId` (what entity it views) instead of `sessionTrackingId`~~
- ~~Rename `SessionPane` to `TabContentPane` — dispatches to type-specific content components~~
- ~~`SessionContent` — terminal + Memorex + PromptBox (extracted from current SessionPane)~~
- ~~`FolderContent` — CardListView + ContainerTreeView + breadcrumbs (file-explorer-style browsing)~~
- ~~`GroupContent` — group management detail view (member list, actions)~~
- ~~`TerminalContent` — raw shell tab, no AI session (ssh, bash, process watcher)~~
- ~~`BriefContent` — rendered brief document view~~
- ~~Opening a folder from Navigator creates a folder tab (browse contents)~~
- ~~Opening a session from anywhere creates a session tab (terminal view)~~

**Group Tab bracket rendering** (port from UCI TabBar.tsx):
- ~~Opening a group creates a Group Tab bracket in the tab bar containing visible member session tabs~~
- ~~Color-coded left border, collapse toggle, member count, +N hidden indicator~~
- ~~Collapse = show only group header tab with +N count~~
- ~~UCI `sessionIds` = container.children, `visibleIds` = app_state per-group preference~~
- ~~Add to group: context menu on session tab → submenu of groups~~
- ~~Hide in group: remove from visible, keep in members~~

**Done when:** Multiple tab types render correctly. Folders open as browsable content tabs. Groups open as bracket Group Tabs with member sessions. Raw terminal tabs can be created. Tab type persists across restart.

### 2E — Grid Layout
**Status:** DEFERRED (explicitly deferred by user in favor of AI Comms work)
**Effort:** Medium
**Dependencies:** 2D (done)
**What:** Implement the split/grid pane layouts that UCI defined but never built.

- `SplitLayout` type: `'single' | 'vertical_2' | 'horizontal_2' | 'grid_2x2'`
- Workspace renders 1-4 `TabContentPane` instances based on layout
- Each cell gets its own tab content (terminal, folder browser, brief — whatever the tab type is)
- Grid selector UI (toolbar button or context menu on Group Tab header)
- Layout stored per group in app_state
- Resizable pane dividers (same pattern as Memorex split)
- Default: single. Switching layout redistributes visible group members across cells.
- Grid layout applies to Group Tabs only (individual tabs are always single pane)

**Done when:** User can switch a Group Tab between 1x1, 2x1, 1x2, 2x2 layouts. Each cell shows a different session with its own terminal. Layout persists.

### 2F — Tags Integration
**Status:** DONE (fork delivery integrated; TagBadge/TagPicker components exist)
**Effort:** Small
**Dependencies:** None (C4 read path done, write path needs tag loading)
**What:** Make tags actually work end-to-end.

- ~~Load tags into Session.tags in `mapSession()` (call `getTagsForSession` or batch)~~
- ~~TagPicker in ContextPanel wired to `tag.add`/`tag.remove` commands~~
- ~~Tag filtering in Navigator (filter chips or search)~~
- ~~Tag display on session cards (TagBadge component already exists)~~

**Done when:** User can add/remove tags on sessions, see them on cards, filter by tag.

### 2G — Projects Entity
**Status:** DONE (18 project cards from real devTree data)
**Effort:** Medium
**Dependencies:** 2A (done)
**What:** DevTrees/projects as first-class entities in the app.

- ~~`ProjectCard` type extending BaseCard (contracts already define Project interface)~~
- ~~DevTree indexer: scan `~/Documents/AI/devTrees/` for project metadata~~
- ~~Projects tab in Navigator with CardListView~~
- ~~Project detail view: working dir, branch, status, assigned AIs~~
- ~~Associate sessions with projects (relationship or project_dir matching)~~

**Done when:** User can see all projects in Navigator, view project details, see which sessions belong to which project.

### 2H — Prompt Box + Input UX (PianoMan track)
**Status:** DEFERRED (PianoMan track, not yet started)
**Effort:** Medium
**Dependencies:** None
**What:** Enhanced prompt input experience. PianoMan may work this in parallel.

- Staged prompt with per-session draft preservation (basic version exists)
- Multi-line editing (Shift+Enter exists from spike)
- Prompt history (up/down arrow)
- Prompt templates / snippets
- Integration with Memorex view (send prompt, see formatted response)

**Note:** Scope TBD by PianoMan. Listed here for coordination, not assignment.

### 2I — Right Panel / Context Panel (PianoMan track)
**Status:** DEFERRED (pushed later; dependency 2F now satisfied)
**Effort:** Medium
**Dependencies:** 2F (done)
**What:** Enhanced session detail panel. PianoMan may work this in parallel.

- Session details (exists: tracking ID, platform, status, roles)
- Notes (exists, write path now fixed to app_state)
- Tags (needs 2F — now available)
- Relationships / lineage view
- Session metrics (context %, exchange count, duration)
- Related entities panel

**Note:** Scope TBD by PianoMan. Listed here for coordination, not assignment.

### 2J — Notification/Inbox Panel
**Status:** STAGED (not yet started)
**Effort:** Medium-Large
**Dependencies:** M9 (done — external change signals)
**What:** Converge all user-targeted communications into an inbox.

- Inbox data model (from UAI Next Architecture v0.1 Section 7)
- Inbox panel in bottom area or dedicated tab
- Priority levels: critical/high/normal/low
- Sources: task completions, session events, collector alerts, command failures
- Read/dismiss/pin actions
- Threading (related alerts collapse)

**Done when:** User sees notifications from system events in a single panel, can dismiss/pin them.

### 2K — Teams Entity
**Status:** STAGED (not yet started; dependencies 2A and 2G now satisfied)
**Effort:** Large
**Dependencies:** 2A (done), 2G (done)
**What:** Teams as first-class entities with composition and role assignment.

- `TeamCard` type extending BaseCard with container capability
- Team composition UI: add/remove AI participants
- Role assignment (session role → team role mapping)
- Comms plan definition (escalation chain, feedback mechanism)
- Team detail view

**Done when:** User can create teams, assign AIs with roles, define comms plans.

### 2L — AI Comms Protocol
**Status:** IMPLEMENTED (backend phases 1-3, UI components built; never tested end-to-end through the UI)
**Effort:** Large
**Dependencies:** 2K (staged — 2L was pulled forward ahead of 2K)
**What:** Structured inter-AI communication.

- ~~Conversation threading with `conversation_id` + `sequence` (contracts already define this)~~
- ~~Message IDs with `inReplyTo` correlation~~
- ~~Request/response with timeout and durable FeedbackRequest records~~
- Embedded AI with restricted permissions and safety classification — not yet implemented
- Notification enforcement via hooks — not yet implemented
- **UI components built:** MessagesTab, PromptsTab, ComposeMessage, conversation locks
- **Needs:** End-to-end testing through the UI to verify the full flow works

**Done when:** AIs can send structured requests to each other, receive responses, and escalate on timeout. **Current gap:** Never tested end-to-end through the UI.

---

## Dependency Graph

**Status: Partially resolved.** All first- and second-batch dependencies are satisfied. 2L was pulled forward ahead of its dependency 2K.

```
2A (DONE) ──┬── 2B Groups (DONE) ──┬── 2D Tab Model (DONE) ──── 2E Grid Layout (DEFERRED)
            │                      │
            ├── 2C Navigator (DONE) ┘
            │
            ├── 2G Projects (DONE) ──── 2K Teams (STAGED)
            │                                  │
            │                           2L AI Comms (IMPLEMENTED, pulled forward)
            │
            └── 2F Tags (DONE) ──── 2I Right Panel* (DEFERRED)

2H Prompt Box* (DEFERRED, PianoMan)
2I Right Panel* (DEFERRED, PianoMan)
2J Inbox (STAGED, independent after M9)
```

`*` = PianoMan may work in parallel; listed for coordination.

## Ordering Recommendation (updated 2026-05-12)

**First batch (workspace experience) — COMPLETE:**
1. ~~2B Groups — small, unblocks 2D~~
2. ~~2C Navigator refactor — medium, improves all entity display~~
3. ~~2F Tags — small, standalone~~

**Second batch (tab groups + grid) — PARTIALLY COMPLETE:**
4. ~~2D Tab Groups — medium, the signature workspace feature~~
5. 2E Grid Layout — DEFERRED in favor of AI Comms

**Third batch (entities) — PARTIALLY COMPLETE:**
6. ~~2G Projects — medium, standalone~~
7. 2J Inbox — STAGED, not yet started

**Fourth batch (heavy) — PARTIALLY COMPLETE:**
8. 2K Teams — STAGED, not yet started
9. ~~2L AI Comms — IMPLEMENTED (pulled forward, needs end-to-end testing)~~

PianoMan's 2H/2I work is DEFERRED and can proceed when prioritized.

## Remaining Debt

| Item | Status | Notes |
|------|--------|-------|
| Codex re-review M2: tags still `[]` | Addressed by 2F | |
| Codex re-review M3: dry_run/idempotency/access-control | Deferred | Contract should stop advertising unimplemented features |
| DevTree sync (stale launcher copy) | Open | DevTree refresh needed, or hooks to prevent out-of-tree edits |
| Command bus access control for container.* commands | Open | Stub only blocks session.create/archive for external-api |
| Component registry: FolderTree, Breadcrumbs, TagBadge, TagPicker | Low priority | Register when components are actively used |
