# UAI Architecture Specification v1.0

**Date:** 2026-04-22
**Author:** Continuity (Claude CLI, Architect) with PianoMan
**Status:** Draft — pending Codex review
**Predecessors:** uai_architecture_v0.2.md, component_api_contracts.md, 2026-03-30-frontend-design-v2.md
**Input:** gap_analysis.md, Pixel III session brief, UCI codebase (v3.0.161)

---

## 1. Purpose & Principles

### What UAI Is

UAI is a desktop workspace for managing multiple simultaneously running AI CLI agent sessions. It preserves the terminal interaction model while adding organization, orchestration, communication, and automation.

### What UAI Is NOT

- A terminal replacement — the terminal is the interaction surface
- A message broker — CLI agents handle conversation logic
- A frontend with backend AI services — CLIs are the backends
- A conversation runtime — UAI manages sessions, not turns

### Architectural Principles

1. **External Ground Truth** — The app reflects external state. It never maintains divergent copies of data that exists elsewhere. When the app writes data, it writes to the same external stores that all other consumers read. Optimistic updates are shown as drafts until confirmed by the external store.

2. **Component API Layer** — Every architectural UI component exposes a typed API (get/set/update/delete/list) with dot-path keys. All state inspection and mutation flows through these APIs. Components are testable, debuggable, and discoverable without DOM access.

3. **Command Bus** — All user-initiated and programmatic actions route through a typed command hierarchy with entry/exit hooks. Commands have parents, results, and origin tracking. This enables logging, undo, access control, and AI interaction as emergent properties.

4. **Event & Notification System** — Fine-grained state subscriptions replace polling. Internal events drive reactive UI updates. A notification bus delivers cross-boundary signals (to AIs, users, team members, logs) through subscriber-specific mechanisms.

5. **MVC Separation** — Model (component state in stores), View (React rendering), Controller (command handlers). Views render from state and dispatch commands. Views never mutate state directly. State never contains rendering logic.

### Constraints

- **Platform:** Electron + xterm.js + node-pty + tmux (confirmed by UCI, carries forward)
- **Language:** TypeScript (main process + renderer)
- **Renderer:** React
- **User:** Single user (PianoMan), single machine (macOS)
- **CLI platforms:** Claude CLI, Codex CLI, Gemini CLI (extensible to future platforms)
- **Session identity:** Tracking IDs as primary keys (spec_session_identity v5)
- **Python 3.9+ compatibility** for all Python scripts (macOS system Python)

---

## 2. Entity Model

### 2.1 Session

The primary entity. Everything in the app ultimately references, displays, or operates on sessions.

#### Identity (Three-ID Model)

| ID | When Available | Mutability | Writer | Purpose |
|---|---|---|---|---|
| **Tracking ID** | At creation | Immutable | Wrapper or app (draft) | Primary key everywhere. Parent-child linking, filenames, logs. Format: `{YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}` |
| **CLI Session ID** | Discovered post-launch (or pre-assigned for Claude) | Set once, immutable | Wrapper | Cross-reference to CLI platform data (JSONL files, conversation history) |
| **Terminal Session Name** | At creation | Mutable (may change on resume) | Wrapper | Terminal operations: attach, dump-screen, send-keys. Operational handle, never a stable reference. |

#### Draft Tracking IDs

Any authorized writer can create a draft Tracking ID. The session exists in the store immediately but with limited data:

```
draft → pending → confirmed
```

- **draft**: App or script created the ID. Most fields null. Session visible in app as placeholder.
- **pending**: Launcher has been called with this ID. Waiting for identity completion.
- **confirmed**: Wrapper has finished. All identity fields populated. Session fully operational.

#### Field Ownership Map

| Field | Owner | Mutability | Store |
|---|---|---|---|
| tracking_id | Wrapper / App (draft) | Immutable | SQLite |
| cli_session_id | Wrapper | Set once | SQLite |
| terminal_session_name | Wrapper | Mutable | SQLite |
| platform | Wrapper | Immutable | SQLite |
| created_at | Wrapper / App (draft) | Immutable | SQLite |
| display_name | App / AI | Mutable | SQLite |
| role | Wrapper / App | Mutable | SQLite |
| project_dir | Wrapper | Mutable | SQLite |
| spawned_by | Wrapper | Immutable | SQLite |
| model | Wrapper | Immutable | SQLite |
| status | App (runtime) | Mutable | In-memory (derived from substrate) |
| activity_state | App (runtime) | Mutable | In-memory (derived from screen parsing) |
| context_percent | App (runtime) | Mutable | In-memory (derived from status bar) |
| exchange_count | App (runtime) | Mutable | In-memory (derived from JSONL) |
| last_activity | App (runtime) | Mutable | In-memory |
| type | App | Mutable | app_state.json |
| pinned | App | Mutable | app_state.json |
| lastViewedAt | App | Mutable | app_state.json |
| notes | App / AI | Mutable | app_state.json |
| tags | App / AI | Mutable | SQLite (card_tags) |
| transcript_path | Derived | Immutable | Derived from cli_session_id |
| identity_status | App | Mutable | SQLite | Values: draft, pending, confirmed |

#### Activity States

Detected via screen parsing through the platform adapter:

| State | Indicator | Detection Method |
|---|---|---|
| **idle** | Green steady | CLI at prompt, no thinking indicator |
| **responding** | Green pulsing | Thinking indicator visible (✻ for Claude) |
| **blocked** | Yellow steady | Permission prompt detected |
| **permission_prompt** | Orange steady | Explicit approval request detected |
| **error** | Red steady | Error state in terminal |
| **stopped** | Gray steady | Process exited |

#### Session Types

Session `type` is a mutable classification, not a fundamental distinction:

| Type | Meaning |
|---|---|
| **chat** | Interactive session with user |
| **worker** | Session spawned by another session for a specific task |

The worker/chat distinction is soft — any session can be reclassified. The "Related Entities" panel (Section 8.6) shows connections regardless of type.

### 2.2 Brief

A condensed session handoff document. Briefs are the mechanism for transferring context between sessions.

| Field | Owner | Store |
|---|---|---|
| name | Creator (AI/App) | Filesystem (YAML at ai_general/data/session_briefs/) |
| display_name | Creator | YAML file |
| description | Creator | YAML file |
| created | Creator | YAML file |
| links | Creator / App | SQLite (entity_relationships) |
| folder | App | folders.json |
| fileSize | Derived | Filesystem |
| condenser_session | Creator | YAML file |

### 2.3 Project

A first-class entity representing a devTree / working context. Projects own sessions and briefs.

| Field | Owner | Store |
|---|---|---|
| id | devTree MCP | Filesystem (devTree directory name) |
| name | User / App | Project metadata YAML in devTree dir |
| goal | User / AI | Project metadata YAML |
| branch | Git | Derived from devTree git state |
| working_dir | devTree MCP | Filesystem path |
| assigned_ais | User | Project metadata YAML |
| linked_sessions | App | SQLite (entity_relationships) |
| linked_briefs | App | SQLite (entity_relationships) |
| status | devTree MCP | Derived (clean/dirty/ahead/behind) |

External ground truth: project metadata lives in the devTree directory itself. The app reflects it.

### 2.4 Team

A composition of AI profiles working together toward a shared objective.

| Field | Owner | Store |
|---|---|---|
| id | App / User | Team definition YAML |
| name | User | Team definition YAML |
| profiles | User | Team definition YAML (references to profile definitions) |
| role_assignments | User | Team definition YAML |
| comms_plan | User / AI | Team definition YAML |
| member_sessions | App (runtime) | In-memory (derived from active sessions matching team profiles) |
| status | App (runtime) | In-memory (derived from member session states) |

External ground truth: team definitions are YAML files. Runtime state (which sessions are active members) is derived.

#### Team Comms Plan

Each team defines how its members communicate:

```yaml
comms_plan:
  escalation_chain: [team_lead, user]
  feedback_mechanism: prompt          # none | message | prompt
  feedback_timeout: 300               # seconds before self-prompt fires
  notification_routing:
    blocked: [team_lead, user]
    error: [all_members, user]
    completion: [requester]
```

### 2.5 Tag

General-purpose labeling system for any entity.

| Field | Owner | Store |
|---|---|---|
| name | User / App | SQLite (tags table) |
| color | User | SQLite |
| icon | User | SQLite |
| entity_type | System | SQLite (which entity types can use this tag) |

Tags are many-to-many with entities via a join table. Any entity (Session, Brief, Project, Team) can have tags.

### 2.6 Entity Relationships

All inter-entity links use a unified relationship system:

| Field | Description |
|---|---|
| source_type | session, brief, project, team |
| source_id | Entity ID |
| target_type | session, brief, project, team |
| target_id | Entity ID |
| relationship | Typed link (see below) |
| created_at | Timestamp |

#### Relationship Types (paired, bidirectional)

| Forward | Reverse | Meaning |
|---|---|---|
| forked_from | forked_to | Session forked from another |
| briefed_to | brief_of | Session was briefed into a Brief |
| launched_from | launched | Session launched from a Brief |
| loaded | loaded_by | Brief loaded into a Session |
| supersedes | superseded_by | Newer entity replaces older |
| member_of | has_member | Session is member of Team/Project |
| relates_to | relates_to | Generic association |

---

## 3. Data Architecture

### 3.1 External Ground Truth Model

The app is a **view** of external state. Three authoritative stores, each with clear ownership:

```
┌─────────────────────────────────────────────────────────────┐
│                    External Ground Truth                      │
├──────────────────┬──────────────────┬───────────────────────┤
│   SQLite Store   │  Filesystem      │  App State            │
│   (session_store │  (YAML files,    │  (app_state.json,     │
│    .py)          │   devTree dirs,  │   folders.json)       │
│                  │   JSONL files)   │                       │
│  Sessions        │  Briefs          │  Tabs, pinned,        │
│  Tags            │  Projects        │  lastViewedAt,        │
│  Relationships   │  Teams           │  notes, folders,      │
│  Identity        │  Transcripts     │  UI preferences       │
├──────────────────┴──────────────────┴───────────────────────┤
│                         ↕ reads + writes                     │
├─────────────────────────────────────────────────────────────┤
│                    UAI Application                            │
│                    (reflects, never diverges)                 │
├─────────────────────────────────────────────────────────────┤
│                         ↕ reads + writes                     │
├──────────────────┬──────────────────┬───────────────────────┤
│  CLI Wrappers    │  MCP Servers     │  Scripts / Tools      │
│  (ai_launcher)   │  (prompting,     │  (session_store.py,   │
│                  │   messages, etc) │   deploy.sh, etc)     │
└──────────────────┴──────────────────┴───────────────────────┘
```

**Key rule:** Multiple writers are acceptable. Divergent copies are not. All consumers read from the same stores. The app does not maintain a shadow copy.

### 3.2 Optimistic Updates (Draft Pattern)

When the app initiates a change:

1. App writes to external store immediately
2. App shows the change in UI as a "draft" (visual indicator: subtle, e.g., italic or dimmed)
3. On next refresh cycle, app reads back from external store
4. If confirmed (data matches), draft indicator removed
5. If not confirmed (data doesn't match), app reconciles — either retry or roll back with notification

This replaces the current pattern of "write to local state, hope it persists, refresh later."

### 3.3 Store Details

#### SQLite (session_store.py)

Canonical identity, lifecycle, tags, relationships. The registrar of record.

- Sessions: identity fields, created_at, platform
- Tags: name, color, icon, entity assignments
- Entity relationships: typed links between any entity pair
- Brief metadata: indexed fields for search/filter

#### Filesystem

Source of truth for content and configuration:

- Brief YAML: `ai_general/data/session_briefs/{name}.yml`
- Project metadata: `{devTree_dir}/project.yml`
- Team definitions: `ai_general/data/teams/{name}.yml`
- Transcripts: `~/.claude/projects/{project}/{uuid}.jsonl`
- Session info: per-session directories with sessionInfo.json

#### App State (app_state.json + folders.json)

UI-owned ephemeral and preference state:

- Open tabs and active tab
- Pinned status, lastViewedAt, notes
- Folder structure and membership
- Panel sizes, collapse states
- Card display preferences
- Design token overrides

### 3.4 Schema Versioning

Each external store has a schema version. When the app reads a store:

1. Check schema_version field
2. If current version: proceed
3. If older version: run migration, update version
4. If newer version: warn user, operate in read-only mode for that store

Migrations are forward-only, idempotent, and logged.

---

## 4. Component API Contracts

### 4.1 Conventions

- **Keys** are dot-separated paths scoped to the component: `filter.platform`, `tabs.active`
- **Get** returns `T | null` (null if key doesn't exist)
- **Set** replaces a value. Returns `{ ok: boolean, previous?: T }`
- **Update** partial-merges. Returns `{ ok: boolean, previous?: T, effects?: string[] }`
- **Delete** returns `boolean` (true if removed)
- **List** returns typed arrays
- **Describe** returns JSON interface definition (see Section 4.2)
- **All state operations are synchronous** — state is in-memory. Persistence is async (debounced).
- **Command origin** is attached to every mutation: `user | internal | external-api | embedded-ai | debug`
- **Mutations restricted** to internal callers by default. External/AI callers require debug mode unless explicitly permitted per-command.

### 4.2 Component Self-Description

Every architectural component provides a `describe()` method returning a JSON interface definition:

```typescript
interface ComponentDescription {
  id: string;                        // e.g., "session_navigator"
  name: string;                      // e.g., "Session Navigator"
  description: string;               // Human-readable purpose
  parent: string | null;             // Parent component ID
  children: string[];                // Child component IDs

  state: {                           // Readable state keys
    [key: string]: {
      type: string;                  // TypeScript type as string
      description: string;
      readable: boolean;
      writable: boolean;
    }
  };

  commands: {                        // Available commands
    [name: string]: {
      description: string;           // What it does, for AI/user consumption
      parameters: {
        [param: string]: {
          type: string;
          description: string;
          required: boolean;
        }
      };
      returns: string;
      access: 'public' | 'internal' | 'debug';
    }
  };

  actions: {                         // Clickable/activatable UI elements
    [name: string]: {
      description: string;           // "Click to expand this group"
      trigger: string;               // command name this action invokes
      context: string;               // What contextual data the parent provides
    }
  };
}
```

This enables:
- **Embedded AI:** Discovers the app by walking the component tree, reading descriptions, invoking commands
- **Auto-generated help:** `!help navigator` renders the navigator's description + commands
- **Diagram generation:** Component tree with connections rendered from describe() output
- **Testing:** Contract verification — describe() matches actual API

### 4.3 Session Store API

The shared data layer. Not a UI component — all components reference it.

```
SessionStore {
  // Read
  get(tracking_id: TrackingId): Session | null
  list(filter?: SessionFilter): Session[]
  getByCliUuid(uuid: string): Session | null
  getByTerminalSession(name: string): Session | null
  getChildren(tracking_id: TrackingId): Session[]
  getRelated(tracking_id: TrackingId, relationship?: string): EntityRef[]

  // Write
  createDraft(platform: Platform, opts?: DraftOpts): TrackingId
  update(tracking_id: TrackingId, patch: SessionPatch): CommandResult
  updateRuntime(tracking_id: TrackingId, patch: RuntimePatch): void

  // Subscriptions
  onChange(tracking_id: TrackingId, path?: string, cb: Callback): Unsubscribe
  onAnyChange(cb: Callback): Unsubscribe

  // Lifecycle
  reload(): Promise<void>
}
```

### 4.4 SessionNavigator API

Owns: active navigator tab, filter/group/sort state, folder tree, selection.

```
SessionNavigator {
  // Tab
  get("active_tab"): NavigatorTab          // sessions | briefs | teams | projects
  set("active_tab", value: NavigatorTab): CommandResult

  // Filter
  get("filter"): FilterConfig
  update("filter", patch: Partial<FilterConfig>): CommandResult
  get("filter.platform"): Platform[]
  get("filter.status"): SessionStatus[]
  get("filter.tags"): string[]
  get("filter.text"): string
  get("filter.unaffiliated"): boolean
  get("filter.date_range"): DateRange | null

  // Sort
  get("sort_field"): SortField            // activity | created | name
  get("sort_direction"): SortDirection    // asc | desc
  set("sort_field", value: SortField): CommandResult
  set("sort_direction", value: SortDirection): CommandResult

  // Folders
  get("selected_folder"): string | null
  set("selected_folder", value: string | null): CommandResult
  list("folders"): Folder[]
  get("folders.{id}"): Folder | null

  // Selection (multi-select)
  get("select_mode"): boolean
  set("select_mode", value: boolean): CommandResult
  get("selected_ids"): Set<string>
  update("selected_ids.add", value: string): CommandResult
  update("selected_ids.remove", value: string): CommandResult
  update("selected_ids.toggle", value: string): CommandResult
  update("selected_ids.clear"): CommandResult

  // Computed
  list("visible_items"): EntityRef[]        // After filter/sort applied
}
```

### 4.5 Workspace API

Owns: tabs, tab groups, active tab, grid layout.

```
Workspace {
  // Tabs
  list("tabs"): Tab[]
  get("tabs.active"): Tab | null
  get("tabs.{session_id}"): Tab | null
  set("tabs.open", value: TrackingId): CommandResult
  delete("tabs.{session_id}"): CommandResult
  set("tabs.activate", value: TrackingId): CommandResult

  // Tab Groups
  list("tab_groups"): TabGroup[]
  get("tab_groups.{id}"): TabGroup | null
  set("tab_groups.create", value: TabGroupOpts): CommandResult
  delete("tab_groups.{id}"): CommandResult
  update("tab_groups.{id}", patch: Partial<TabGroup>): CommandResult
  update("tab_groups.{id}.layout", value: GridLayout): CommandResult

  // Grid Layout
  get("grid_layout"): GridLayout           // single | vertical_2 | horizontal_2 | grid_2x2
  set("grid_layout", value: GridLayout): CommandResult

  // Browse mode
  get("browse_mode"): boolean
}
```

### 4.6 SessionPane API

Owns: mode (terminal/transcript), focus state.

```
SessionPane {
  get("session_id"): TrackingId
  get("mode"): PaneMode                   // terminal | transcript
  set("mode", value: PaneMode): CommandResult
  get("focused"): boolean
  set("focused", value: boolean): CommandResult
}
```

### 4.7 TranscriptView API

Owns: filter toggles, scroll, search, selection.

```
TranscriptView {
  get("session_id"): TrackingId
  get("filters"): TranscriptFilters
  update("filters", patch: Partial<TranscriptFilters>): CommandResult
  get("auto_follow"): boolean
  set("auto_follow", value: boolean): CommandResult
  get("search_query"): string | null
  set("search_query", value: string | null): CommandResult
  get("width_percent"): number
  set("width_percent", value: number): CommandResult

  // Selection (multi-select)
  get("select_mode"): boolean
  set("select_mode", value: boolean): CommandResult
  get("selected_message_ids"): Set<number>

  // Content (read-only)
  list("day_groups"): DayGroup[]
  get("message_count"): number
}
```

### 4.8 PromptBox API

Owns: text, mode, target, history, shell output.

```
PromptBox {
  get("text"): string
  set("text", value: string): CommandResult
  get("target_session_id"): TrackingId
  set("target_session_id", value: TrackingId): CommandResult
  get("mode"): PromptMode                 // prompt | command | shell
  get("shell_output"): string | null
  get("shell_output_visible"): boolean
  set("shell_output_visible", value: boolean): CommandResult
  get("height"): number
  set("height", value: number): CommandResult

  // Actions
  execute("stage"): CommandResult          // Cmd+Enter: stage to target
  execute("submit_shell"): CommandResult   // Execute $ command
  execute("rewrite"): CommandResult        // Send to LLLM for rewrite
  execute("clear"): CommandResult

  // History
  list("history"): PromptHistoryEntry[]
  execute("history_prev"): CommandResult
  execute("history_next"): CommandResult

  // Pre/Post Prompt
  get("pre_prompt"): PromptAddendum[]
  get("post_prompt"): PromptAddendum[]
  update("pre_prompt.add", value: PromptAddendum): CommandResult
  update("post_prompt.add", value: PromptAddendum): CommandResult
  get("reminders"): PeriodicReminder[]
}
```

### 4.9 ContextPanel API (Right Panel)

Owns: open/closed, active tab, width, digest tracking.

```
ContextPanel {
  get("open"): boolean
  set("open", value: boolean): CommandResult
  get("active_tab"): ContextTab           // details | docs | memories | messages | prompts | digests
  set("active_tab", value: ContextTab): CommandResult
  get("width"): number
  set("width", value: number): CommandResult

  // Digest tracking (Knowledge, Traits, Roles loaded by focused session)
  list("digests.loaded"): DigestEntry[]
  list("digests.available"): DigestEntry[]
  execute("digests.load", { id: string }): CommandResult
}
```

### 4.10 BottomPanel API

Owns: open/closed, active tab, height, related entities, system monitor.

```
BottomPanel {
  get("open"): boolean
  set("open", value: boolean): CommandResult
  get("active_tab"): BottomTab            // related | logs | app_log | monitor
  set("active_tab", value: BottomTab): CommandResult
  get("height"): number
  set("height", value: number): CommandResult

  // Related Entities (replaces Workers)
  list("related"): EntityRef[]            // Children, linked sessions, briefs, team members
  get("related.scoped_to"): TrackingId | null

  // System Monitor
  get("monitor.cpu"): number
  get("monitor.memory"): number
  get("monitor.active_sessions"): number
  get("monitor.error_count"): number
  list("monitor.warnings"): Warning[]

  // Drawer bar (visible when panel closed)
  get("drawer_summary"): DrawerSummary    // Compact metrics for closed state
}
```

---

## 5. Command System

### 5.1 Command Bus

All mutations flow through a central command bus. Commands are typed, hierarchical, and observable.

```typescript
interface Command {
  type: string;                    // Dot-path: "workspace.tabs.open"
  payload: Record<string, any>;
  origin: CommandOrigin;           // user | internal | external-api | embedded-ai | debug
  timestamp: string;
  parent_command?: string;         // For nested commands (e.g., "move to folder" triggers "remove from old folder" + "add to new folder")
}

interface CommandResult {
  ok: boolean;
  previous?: any;                  // Previous state (enables undo)
  effects?: string[];              // Side effects that occurred
  error?: string;                  // If ok === false
}

type CommandOrigin = 'user' | 'internal' | 'external-api' | 'embedded-ai' | 'debug';
```

### 5.2 Command Hierarchy

Commands form a tree. Child commands inherit behaviors from parents:

```
app
├── session
│   ├── session.create
│   ├── session.stop
│   ├── session.resume
│   ├── session.fork
│   ├── session.archive
│   ├── session.update          // notes, display_name, tags, etc.
│   └── session.move_to_folder
├── workspace
│   ├── workspace.tabs.open
│   ├── workspace.tabs.close
│   ├── workspace.tabs.activate
│   └── workspace.tab_groups.*
├── navigator
│   ├── navigator.filter.*
│   ├── navigator.sort.*
│   └── navigator.select.*
├── prompt
│   ├── prompt.stage
│   ├── prompt.shell
│   └── prompt.rewrite
├── brief
│   ├── brief.create
│   ├── brief.launch
│   └── brief.load
├── project
│   ├── project.create
│   └── project.switch
├── team
│   ├── team.create
│   ├── team.launch
│   └── team.notify
└── notification
    ├── notification.emit
    └── notification.route
```

### 5.3 Entry/Exit Hooks

Every command type can have pre-execution and post-execution hooks:

```typescript
commandBus.before('session.*', (cmd) => {
  // Global: log every session command
  logger.log('command', cmd);
});

commandBus.after('session.stop', (cmd, result) => {
  // After stop: notify team if session was a team member
  if (result.ok) notificationBus.emit('session.stopped', cmd.payload);
});

commandBus.before('*', (cmd) => {
  // Global: access control check
  if (cmd.origin === 'external-api' && !debugMode) {
    throw new AccessDeniedError('External mutations require debug mode');
  }
});
```

### 5.4 Access Control

| Origin | Read (get/list) | Write (set/update/delete) | Execute (commands) |
|---|---|---|---|
| **user** | Always | Always | Always |
| **internal** | Always | Always | Always |
| **embedded-ai** | Always | Per-command whitelist | Per-command whitelist |
| **external-api** | Always | Debug mode only | Debug mode only |
| **debug** | Always | Always | Always |

Debug mode is toggled at runtime. When active, all origins have full access. The command origin field is always recorded regardless of access level.

---

## 6. Event & Notification System

### 6.1 Internal Event System

Components subscribe to state changes at arbitrary granularity:

```typescript
// Coarse: any session changes
sessionStore.onAnyChange((event) => { ... });

// Fine: specific session, specific field
sessionStore.onChange('20260420_145848_cb5a742f_cla', 'notes', (event) => { ... });

// Component-scoped
navigator.on('filter', (event) => { ... });
workspace.on('tabs.active', (event) => { ... });
```

Events are synchronous within the renderer. No polling required — state changes propagate immediately to all subscribers.

#### Standard Events

| Event | Data | Emitted By |
|---|---|---|
| `session:changed` | `{ tracking_id, fields: string[] }` | SessionStore |
| `session:added` | `{ tracking_id, identity_status }` | SessionStore |
| `session:removed` | `{ tracking_id }` | SessionStore |
| `tab:opened` | `{ tracking_id }` | Workspace |
| `tab:closed` | `{ tracking_id }` | Workspace |
| `tab:activated` | `{ tracking_id }` | Workspace |
| `command:executed` | `{ command, result }` | CommandBus |
| `notification:emitted` | `{ type, data, targets }` | NotificationBus |

### 6.2 Notification Bus

Cross-boundary delivery. A single emit reaches multiple subscribers through different mechanisms:

```typescript
interface Notification {
  type: string;                    // e.g., "session.waiting_for_input"
  source: EntityRef;               // Who/what generated this
  data: Record<string, any>;       // Notification payload
  urgency: 'info' | 'attention' | 'critical';
  targets?: string[];              // Specific targets, or all subscribers if omitted
}
```

#### Subscriber Types

| Subscriber | Delivery Mechanism | Latency |
|---|---|---|
| **App UI** | Internal event → Tab flash, icon decorator, badge, status bar | Immediate |
| **AI (Claude with hooks)** | Hook injection on next tool_use or notification hook | < 1 second |
| **AI (Codex/Gemini, no hooks)** | App queues prompt to session OR injects into next pre-prompt addendum | Next turn |
| **User** | macOS notification via send_user_notification.py | Immediate |
| **Team** | Routes to team's comms plan (escalation chain) | Per plan |
| **Log** | Appended to session activity log and/or app log | Immediate |

#### Platform Capability Adapter

The notification system uses a platform adapter to determine delivery mechanism:

```typescript
interface NotificationAdapter {
  canHook(platform: Platform): boolean;
  deliver(notification: Notification, session: Session): Promise<DeliveryResult>;
}
```

For platforms without hook support, the app compensates — it becomes the session's "hook runtime" by monitoring state and injecting prompts.

---

## 7. Hooks Architecture

### 7.1 Hook Levels

Hooks exist at three levels, each with different trigger mechanisms:

#### App-Level Hooks

Fire on command bus events. Available to all components.

| Hook | Trigger | Use Case |
|---|---|---|
| `command.before.*` | Before any command executes | Logging, access control, validation |
| `command.after.*` | After any command completes | Notifications, side effects, undo recording |
| `app.startup` | Application starts | Load state, connect to stores |
| `app.shutdown` | Application closing | Save state, cleanup |

#### Session-Level Hooks

Fire on session lifecycle and communication events. Delivered differently per platform.

| Hook | Trigger | Claude Delivery | Codex/Gemini Delivery |
|---|---|---|---|
| `session.pre_prompt` | Before a prompt is sent to session | Claude Code pre-tool hook | App injects addendum text |
| `session.post_response` | After session responds | Claude Code post-tool hook | App checks on next poll |
| `session.activity_change` | Status/activity state changes | Notification hook | App-side detection |
| `session.message_received` | Inter-session message arrives | Notification hook | App queues prompt |
| `session.reminder_due` | Periodic reminder timer fires | Injected into next prompt | Injected into next prompt |

#### Team-Level Hooks

Fire on team events. Routed per the team's comms plan.

| Hook | Trigger | Routing |
|---|---|---|
| `team.member_blocked` | Team member hits permission prompt | → team lead (prompt), → user (notification) |
| `team.member_error` | Team member in error state | → all members (notification), → user (notification) |
| `team.member_completed` | Team member finishes assigned task | → requester (per feedback_mechanism) |
| `team.escalation` | Member escalates issue | → escalation_chain in comms_plan |

### 7.2 AI Feedback Timeout Pattern

When an AI requests feedback (review, approval, "shall I proceed?"):

1. AI sends request with specified `feedback_mechanism` (none | message | prompt)
2. AI schedules a self-prompt timeout (via `prompting:schedule_future_prompt`)
3. If feedback arrives before timeout: process normally
4. If timeout fires without feedback: AI self-assesses
   - Can I proceed safely without the input? → proceed, note the assumption
   - Is this blocking? → retry the request
   - Still no response? → escalate per team comms plan or notify user

```yaml
# Example feedback request
feedback_request:
  from: session_A
  to: session_B
  type: review_request
  mechanism: prompt          # MUST be prompt — messages are not acceptable
  timeout_seconds: 300
  timeout_action: escalate   # retry | proceed | escalate
  content: "Please review the architecture spec at ..."
```

### 7.3 AI-to-AI Response Mechanism Enforcement

When one AI communicates with another:

1. The **requester** specifies the response mechanism: `none`, `message`, `prompt`
2. Default is `prompt` — the response is delivered as a prompt to the requester's session
3. **Using a CLI response message (displayed in terminal output) and assuming the other AI will read it is NOT an acceptable response mechanism.** AIs do not monitor each other's terminal output.
4. The notification bus routes the response through the specified mechanism
5. If the responder uses the wrong mechanism, the app detects this (response arrived as message when prompt was requested) and re-routes

---

## 8. UI Component Hierarchy

### 8.1 Component Tree

```
Application
├── SessionNavigator (Left Panel)
│   ├── NavigatorTabs (Sessions | Briefs | Teams | Projects)
│   ├── Toolbar (Filter, Sort controls — per active tab)
│   ├── FolderTree (within Sessions/Briefs tabs)
│   └── EntityList
│       └── EntityCard[] (compact items, multi-selectable)
│
├── Workspace (Center)
│   ├── TabBar
│   │   ├── Tab[] (individual session tabs)
│   │   └── TabGroup[] (container of tabs)
│   ├── GridLayout (1x1 | 2x1 | 1x2 | 2x2)
│   │   └── SessionPane[] (one per grid cell)
│   │       ├── PaneHeader
│   │       ├── TerminalView (live session)
│   │       └── TranscriptView (review/stopped)
│   └── PromptBox
│       ├── TextArea (with mode prefix detection)
│       ├── ShellOutputArea (above, for $ commands)
│       └── PrePostPromptIndicator
│
├── ContextPanel (Right, collapsible)
│   └── ContextTab[]
│       ├── DetailsTab (session metadata + notes)
│       ├── DigestsTab (Knowledge, Traits, Roles — loaded/available)
│       ├── DocsTab (loaded documents)
│       ├── MessagesTab (inter-session messages)
│       └── PromptsTab (queued prompts)
│
└── BottomPanel (collapsible, drawer bar visible when closed)
    ├── RelatedEntitiesTab (children, linked sessions, briefs, team members)
    ├── SessionLogTab (per-session log viewer)
    ├── AppLogTab (application-wide event log)
    └── SystemMonitorTab (CPU, memory, active sessions, errors)
```

### 8.2 Actionable Component Parent Hierarchy

Every actionable UI element (button, pill, checkbox, menu item, clickable text) has a parent component that provides context. The parent supplies:

- **Entity context:** Which session/brief/project/team does this action apply to?
- **Selection context:** Is multi-select active? Which items are selected?
- **Navigation context:** Where are we in the folder tree?

When an action fires, it queries its parent chain for context rather than receiving it via prop-drilling. This means:

```typescript
// A "Move to Folder" button inside a context menu doesn't need to know
// which session it operates on — it asks its parent chain:
const targets = this.getContext('selection.active_targets');
// Returns: [clicked_id] if not in multi-select, or [...selectedIds] if in multi-select
```

### 8.3 Multi-Select as Universal Pattern

Any component that renders a list of actionable items supports multi-select:

- **Entry:** Toggle button or keyboard shortcut enters select mode
- **Selection:** Checkboxes appear per item. Click toggles. Shift+click range selects.
- **Context actions:** Right-click on a selected item → actions apply to all selected. Right-click on an unselected item → actions apply to that item only.
- **Bulk actions:** Selection bar appears with applicable bulk actions.
- **Exit:** Cancel button, Escape key, or all items deselected.

Components that support multi-select: Navigator entity lists, CardListView, TranscriptView message list, Tags list, Related Entities list.

### 8.4 Tabbed Navigator (Left Panel)

The navigator has tabs along the top, each showing a different entity type:

| Tab | Contents | Filter/Sort |
|---|---|---|
| **Sessions** | Folder tree + session cards. Active/Stopped sections. | Platform, status, tags, date range, text, unaffiliated |
| **Briefs** | Folder tree + brief cards. | Text, date range, tags |
| **Teams** | Team cards with member counts and status. | Status, text |
| **Projects** | Project cards with branch status and session counts. | Status, text |

Each tab maintains its own filter and sort state independently.

### 8.5 Grid View

The workspace center supports grid layouts:

| Layout | Cells | Description |
|---|---|---|
| **1x1** | 1 | Default. Single session pane. |
| **2x1** | 2 | Two panes side by side (vertical split). |
| **1x2** | 2 | Two panes stacked (horizontal split). |
| **2x2** | 4 | Four panes in a grid. |

Each cell has its own tab and can display a different session. Focus (which cell receives keystrokes and prompt staging) is indicated by a bright border. Cmd+1-4 switches focus by position.

### 8.6 Related Entities (Bottom Panel, replaces Workers)

Shows entities related to the focused session:

| Section | Contents |
|---|---|
| **Children** | Sessions spawned by this session |
| **Parent** | Session that spawned this one (if any) |
| **Linked Sessions** | Sessions connected via entity_relationships |
| **Linked Briefs** | Briefs created from or loaded into this session |
| **Team Members** | If this session belongs to a team, show other team members |

Each entity is shown as a compact card. Click to open in a tab. Context menu for actions.

### 8.7 System Monitor (Bottom Panel)

Dashboard drawer with top-level metrics visible on the drawer bar even when the panel is closed:

**Drawer bar (always visible):** `CPU: 45% | Mem: 2.1GB | Sessions: 8 active | Errors: 0`

**Expanded panel:** Charts/graphs for CPU, memory, and per-session resource usage. Active session count over time. Error log with severity. Warnings (high context usage, stalled sessions, disk space).

### 8.8 Runtime-Configurable Card Display

Users can choose which fields appear on cards during runtime:

```typescript
interface CardDisplayConfig {
  fields: string[];              // e.g., ["display_name", "role", "exchange_count", "context_percent", "last_activity"]
  show_badges: boolean;
  show_platform_bar: boolean;
  compact_mode: boolean;
}
```

Configurable per entity type (Session cards, Brief cards, etc.) via a settings dialog or context menu.

---

## 9. Visual System

### 9.1 Design Tokens in Config

All visual constants live in a config file that generates CSS custom properties:

```json
{
  "colors": {
    "bg-deep": "#0a0c10",
    "bg-panel": "#12151c",
    "bg-card": "#1a1e2a",
    "bg-hover": "#222838",
    "border": "#2a3148",
    "border-strong": "#3d4663",
    "border-bright": "#606d94",
    "text": "#d0d8f0",
    "text-sec": "#8890b0",
    "text-muted": "#565f80",
    "accent-blue": "#7aa2f7",
    "accent-green": "#9ece6a",
    "accent-yellow": "#e0af68",
    "accent-red": "#f7768e",
    "accent-purple": "#bb9af7"
  },
  "platforms": {
    "claude": { "color": "#ff9e64", "label": "Claude" },
    "codex": { "color": "#bb9af7", "label": "Codex" },
    "gemini": { "color": "#7aa2f7", "label": "Gemini" }
  },
  "typography": {
    "font-family": "'SF Mono', 'Menlo', monospace",
    "font-family-ui": "-apple-system, BlinkMacSystemFont, sans-serif",
    "size-xs": "10px",
    "size-sm": "11px",
    "size-base": "12px",
    "size-md": "13px",
    "size-lg": "14px",
    "size-xl": "16px"
  },
  "spacing": {
    "xs": "2px",
    "sm": "4px",
    "md": "8px",
    "lg": "12px",
    "xl": "16px",
    "xxl": "24px"
  },
  "borders": {
    "radius-sm": "4px",
    "radius-md": "6px",
    "radius-lg": "8px",
    "panel-width": "2px",
    "card-width": "1px"
  }
}
```

At app startup, this config generates `:root` CSS custom properties. Components reference tokens only (`var(--bg-card)`), never raw values. Token overrides in app_state.json enable runtime theming.

### 9.2 Component CSS Strategy

Break the monolithic `styles.css` into:

```
styles/
  tokens.css          # Generated from config. :root variables only.
  base.css            # Reset, typography, scrollbar, global layout
  components/
    navigator.css
    workspace.css
    session-card.css
    brief-card.css
    tab-bar.css
    prompt-box.css
    transcript.css
    context-panel.css
    bottom-panel.css
    popover.css
    dialog.css
```

Each component CSS file uses only design tokens. No raw color values, no magic numbers.

---

## 10. Session Identity

### 10.1 Current Spec (v5)

Format: `{YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}`

Example: `20260420_145848_cb5a742f_cla`

- Timestamp in local time (not UTC)
- uuid8 for uniqueness
- platform3: `cla` (Claude), `cdx` (Codex), `gem` (Gemini)

Generated by CLI wrappers via `ai_launcher.py`.

### 10.2 Draft TrackingId Extension

The app can create draft TrackingIds before a session launches:

1. App generates ID using same format (timestamp + uuid8 + platform)
2. Writes to session_store with `identity_status: draft`
3. Passes TrackingId to `ai_launcher.py` via `--tracking-id` flag
4. Launcher matches ID, completes identity fields, updates status to `confirmed`
5. App reflects the confirmed state on next refresh

This enables:
- Session placeholders in the UI before launch completes
- Pre-assigned identity for team launches (all members get IDs simultaneously)
- Project-scoped session creation (link to project at draft time)

---

## 11. Terminal Substrate

### 11.1 Substrate Abstraction

Carried forward from UCI. All terminal operations go through `SessionSubstrate`:

```python
class SessionSubstrate(ABC):
    create_session(name, command, cwd, log_file) -> str
    session_exists(name) -> bool
    session_is_running(name) -> bool
    kill_session(name)
    list_sessions() -> list[SessionInfo]
    send_keys(name, keys)
    dump_screen(name, path?) -> str
    get_current_session_name() -> str | None
    attach(name)
```

Current implementation: `TmuxSubstrate` in `lib_session_substrate.py`.

### 11.2 Platform Adapter

Pure function: `(platform, screen_text) → structured_state`

```typescript
interface ParsedScreenState {
  activity_state: ActivityState;
  context_percent: number | null;
  permission_prompt: boolean;
  thinking_indicator: boolean;
  error_state: boolean;
}
```

Each platform has its own parser (different TUI layouts, different indicators). The adapter handles the differences — the rest of the app sees uniform `ParsedScreenState`.

---

## 12. AI Integration

### 12.1 Embedded AI

An AI agent that operates within the app, interacting through the component API:

1. **Discovery:** Walks the component tree via `describe()`. Learns what's available.
2. **Observation:** Reads state via `get()` and `list()`. Understands current context.
3. **Action:** Invokes commands via the command bus. Same commands as user actions.
4. **Learning:** Component descriptions include human-readable instructions. The AI reads the app the same way a user would read help docs.

The embedded AI has `embedded-ai` origin on all commands. Access is controlled per Section 5.4.

### 12.2 LLLM Integration

Local large language model for lightweight tasks that don't require cloud API:

- **Prompt rewrite:** PromptBox.execute("rewrite") sends text to LLLM, replaces with result
- **Summarization:** Condense transcript sections for brief generation
- **Classification:** Tag suggestions, session type inference

Integration via existing `local-llm` MCP server (reason_on_text, reason_on_file).

### 12.3 AI-to-AI Communication

#### Principles

1. **Prompt is the default delivery mechanism.** Not messages. Not CLI output. Prompts.
2. **Requester specifies mechanism.** Every request includes `feedback_mechanism: none | message | prompt`.
3. **Timeout is mandatory.** Every request that expects a response must schedule a timeout self-prompt.
4. **The app enforces delivery.** If an AI responds via the wrong mechanism, the app re-routes.
5. **Hooks trigger receipt.** AIs don't poll for messages — hooks (or app-injected prompts) force them to process incoming communications.

#### Communication Flow

```
AI_A wants review from AI_B:
  1. AI_A calls notification.emit({
       type: "review_request",
       to: AI_B.tracking_id,
       mechanism: "prompt",
       timeout: 300
     })
  2. NotificationBus routes to AI_B:
     - Claude: notification hook fires immediately
     - Codex: app queues prompt for next idle moment
  3. AI_A schedules self-prompt at +300s
  4. AI_B processes request, responds via prompt to AI_A
  5. AI_A receives response (hook or queued prompt)
  6. If timeout fires before response: AI_A self-assesses (retry/proceed/escalate)
```

---

## 13. Testing Strategy

### 13.1 Component API Testing (Primary)

Test through the API, not the DOM:

```typescript
// Setup
navigator.set("filter", { platform: ["claude_cli"] });

// Execute
const visible = navigator.list("visible_items");

// Assert
expect(visible.every(item => item.platform === "claude_cli")).toBe(true);
```

No CSS selectors. No DOM traversal. No querySelector. Components are tested through their contracts.

### 13.2 Command Testing

Test that commands produce correct state changes:

```typescript
// Setup
const session = sessionStore.get("some_tracking_id");

// Execute
const result = commandBus.execute({
  type: "session.update",
  payload: { tracking_id: "some_tracking_id", patch: { notes: "test" } },
  origin: "user"
});

// Assert
expect(result.ok).toBe(true);
expect(sessionStore.get("some_tracking_id")?.notes).toBe("test");
```

### 13.3 Integration Testing

Test cross-component workflows:

```typescript
// Open a session tab → verify navigator highlights it
commandBus.execute({ type: "workspace.tabs.open", payload: { tracking_id: id } });
expect(navigator.get("selected_ids").has(id)).toBe(true);
```

### 13.4 Packaged Build Testing

Every deploy must be tested as a packaged Electron app, not just the dev server. The first UAI attempt had infrastructure gaps invisible in dev mode (missing preload bundles, empty HOME env, FileLoader regex issues).

---

## 14. Migration Plan

### 14.1 What Carries Forward from UCI

| Component | Action | Notes |
|---|---|---|
| Electron main process | Refactor | SessionManager, IPC handlers, folder management adapt to new architecture |
| session_store.py (SQLite) | Keep | Add new tables (tags, projects, teams). Schema migration. |
| ai_launcher.py | Refactor | Split into param translation + param determination. Add --tracking-id. |
| lib_session_substrate.py | Keep | TmuxSubstrate works. |
| read_jsonl.py | Keep | Transcript parsing. |
| xterm.js + node-pty | Keep | Terminal embedding proven. |
| Session/Brief card visual design | Adapt | Extract CSS, apply design tokens. |
| TranscriptViewer rendering | Adapt | Extract from monolith, implement TranscriptView API. |
| Platform detection, time utils | Keep | Shared utilities. |
| 222 unit tests | Adapt | Rewrite against component APIs. |

### 14.2 What's Rewritten

| Component | Reason |
|---|---|
| App.tsx (1700 lines) | God component. Replaced by component API + command bus. |
| FocusPane.tsx (700 lines) | Mixed state/rendering/menus. Decomposed into Workspace components. |
| FilterBar.tsx | Replaced by NavigatorToolbar with per-tab filter/sort state. |
| CardListView.tsx | Replaced by EntityList with universal multi-select and configurable display. |
| NavigationPanel.tsx | Replaced by SessionNavigator with tabbed entity types. |
| styles.css (6000 lines) | Broken into component CSS modules with design tokens. |
| State management (useState hooks) | Replaced by component stores with event subscriptions. |

### 14.3 Build Order

**Phase 0 — Foundation Spike** (with PianoMan, ~2-3 days)
- Implement: SessionStore, CommandBus, EventSystem, one rendered component (Sessions list)
- Prove the architecture works in running code
- Establish patterns for recursive delegation

**Phase 1 — Core Architecture** (delegated, ~1-2 weeks)
1. State layer: stores, subscriptions, external truth sync
2. Command system: bus, hierarchy, hooks, logging
3. Core components: Navigator (tabbed), Workspace (tabs + grid), SessionPane
4. Support components: PromptBox, ContextPanel, BottomPanel
5. Main process adaptation: SessionManager refactor, new IPC, draft TrackingIds

**Phase 2 — Feature Build** (delegated, ongoing)
- Projects, Tags, Teams (design first, then implement)
- Full PromptBox (history, shell, rewrite, pre/post prompt)
- AI integration (embedded AI, LLLM, comms improvements)
- Notification bus + hooks infrastructure

**Phase 3 — Extended Features**
- WebUI as Session
- Advanced team orchestration
- Session playback / time travel
- Plugin/extension architecture

---

## Appendix A: Types Reference

```typescript
type TrackingId = string;
type Platform = 'claude_cli' | 'codex_cli' | 'gemini_cli';
type SessionStatus = 'running' | 'idle' | 'stopped' | 'archived';
type ActivityState = 'idle' | 'responding' | 'blocked' | 'permission_prompt' | 'error' | 'stopped';
type IdentityStatus = 'draft' | 'pending' | 'confirmed';
type SessionType = 'chat' | 'worker';

type NavigatorTab = 'sessions' | 'briefs' | 'teams' | 'projects';
type ContextTab = 'details' | 'digests' | 'docs' | 'messages' | 'prompts';
type BottomTab = 'related' | 'logs' | 'app_log' | 'monitor';
type PaneMode = 'terminal' | 'transcript';
type PromptMode = 'prompt' | 'command' | 'shell';
type GridLayout = 'single' | 'vertical_2' | 'horizontal_2' | 'grid_2x2';
type SortField = 'activity' | 'created' | 'name';
type SortDirection = 'asc' | 'desc';
type CommandOrigin = 'user' | 'internal' | 'external-api' | 'embedded-ai' | 'debug';
type FeedbackMechanism = 'none' | 'message' | 'prompt';

interface EntityRef {
  type: 'session' | 'brief' | 'project' | 'team';
  id: string;
}

interface CommandResult {
  ok: boolean;
  previous?: any;
  effects?: string[];
  error?: string;
}

interface DateRange {
  from?: string;   // YYYY-MM-DD or ISO
  to?: string;
}

interface TranscriptFilters {
  user: boolean;
  assistant: boolean;
  tools: boolean;
  thinking: boolean;
}

interface PromptAddendum {
  id: string;
  content: string;
  source: string;          // "reminder", "trait", "team_comms", etc.
  position: 'pre' | 'post';
}

interface PeriodicReminder {
  id: string;
  content: string;
  interval_turns: number;  // Every N turns
  position: 'pre' | 'post';
  active: boolean;
}

interface DigestEntry {
  id: string;
  name: string;
  category: 'knowledge' | 'trait' | 'role' | 'memory' | 'profile';
  loaded: boolean;
  loaded_at?: string;
}

interface Warning {
  severity: 'info' | 'warning' | 'error';
  message: string;
  session_id?: TrackingId;
  timestamp: string;
}

interface DrawerSummary {
  cpu_percent: number;
  memory_gb: number;
  active_sessions: number;
  error_count: number;
  top_warning?: string;
}
```

---

## Appendix B: Cross-References

| Document | Relationship |
|---|---|
| gap_analysis.md | Input — maps archived spec → UCI reality → requirements |
| DESIGN.md | Project identity and principles (subset of this spec) |
| spec_session_identity (current) | Session identity format and lifecycle |
| uci_data_architecture.md | UCI's data architecture — predecessor to Section 3 |
| component_api_contracts.md (archived) | Predecessor to Section 4 |
| 2026-03-30-frontend-design-v2.md (archived) | Predecessor to Sections 8-9 |
| lessons-learned.md | Process constraints informing Sections 13-14 |
