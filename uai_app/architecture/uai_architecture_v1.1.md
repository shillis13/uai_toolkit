# UAI Architecture Specification v1.1

**Date:** 2026-04-22
**Author:** Continuity (Claude CLI, Architect) with PianoMan
**Status:** Draft — addresses Codex review findings (codex_architecture_review_v1.md)
**Predecessors:** uai_architecture_v1.0.md, codex_architecture_review_v1.md, uci_data_architecture.md
**Input:** gap_analysis.md, Pixel III session brief, UCI codebase (v3.0.161), spec_session_identity v5.3

**Changes from v1.0:** This revision addresses all critical, major, and relevant minor findings from the Codex architecture review. Key changes: session identity alignment with v5.3, concrete store synchronization contract, dovetailed renderer/main/store authority model, enriched command and component description schemas, structured AI comms protocol with message IDs and threading, durable notification lifecycle, namespaced entity IDs, dependency-ordered migration plan, and nine new sections covering store sync, sagas, conceptual model, focus model, observability, performance, quality gates, security, and URI protocol.

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

1. **External Ground Truth** — The app reflects external state. It never maintains divergent copies of data that exists elsewhere. When the app writes data, it writes to the same external stores that all other consumers read. The renderer holds snapshots of authoritative state, not a second truth. Optimistic updates are shown as drafts until confirmed by store revision.

2. **Component API Layer** — Every architectural UI component exposes a typed API. Read operations (get/list/describe) are synchronous against renderer snapshots. Domain mutations dispatch commands returning `Promise<CommandResult>`. Components never mutate durable state directly.

3. **Command Bus** — All user-initiated and programmatic domain mutations route through a typed command hierarchy with entry/exit hooks. Commands have IDs, correlation, results, and origin tracking. This enables logging, undo, access control, and AI interaction as emergent properties.

4. **Event & Notification System** — Two notification channels: `onStoreChanged` for durable data changes, `onRuntimeChanged` for ephemeral state. Internal events drive reactive UI updates. A notification bus delivers cross-boundary signals (to AIs, users, team members, logs) through subscriber-specific mechanisms with durable delivery lifecycle.

5. **Dovetailed Authority (Renderer/Main/Store)** — Two paths, one handoff point:
   - **Path 1 (outbound):** User Action -> Command Bus -> Main Process -> Store Mutation -> emits Change Event
   - **Path 2 (inbound):** Change Event -> Renderer Store Snapshot Update -> UI Re-render
   - The store mutation is the handoff point. Path 1 ends there, Path 2 begins.
   - The UI never knows whether a change came from its own command or an external writer — it reacts to store changes uniformly.

6. **MVC Separation** — Durable domain model lives in external stores. Renderer stores hold snapshots and UI-only state. Components render from selectors and dispatch commands. Command handlers mutate authoritative stores through main-process services. Views never mutate domain state directly. State never contains rendering logic.

7. **Additive Schema Evolution** — The data model grows by adding tables and optional columns, never by breaking existing structures. Core principles:
   - **Normalized tables** — junction/relationship tables (card_tags, entity_relationships, group_members) handle many-to-many without schema changes. New relationship types, tag semantics, or entity pairings are data, not DDL.
   - **New concepts are new tables** — conversations, messages, env_vars, activity_log, inbox, story_cards arrive as additive tables alongside existing ones. No existing table is restructured to accommodate them.
   - **Backwards-compatible columns** — `ALTER TABLE ADD COLUMN` with defaults for optional fields. Existing queries continue to work against the prior column set.
   - **Schema version gating** — `metadata.schema_version` declares which tables/columns exist. Application code checks version before accessing newer structures. Older consumers ignore tables they don't know about.
   - **Single API layer** — all DB access goes through `session_store.py` (or its successor). The CLI interface is the stability contract. Schema changes behind that interface don't ripple to consumers.
   - **Migration is forward-only and idempotent** — each migration runs exactly once, is logged, and can be re-run safely on an already-migrated DB.

8. **Mutable Runtime Environment** — A live key-value store (ENV MCP) provides namespaced mutable state accessible to all participants at runtime. Unlike shell environment variables (immutable within a process), ENV keys can be set, read, updated, and added at any time by any authorized participant. Namespaces (global, group, individual, user, conversation) scope visibility and write access. This replaces static configuration for runtime-tunable parameters like routing policy, workspace mode, and session paths.

### Constraints

- **Platform:** Electron + xterm.js + node-pty + tmux (confirmed by UCI, carries forward)
- **Language:** TypeScript (main process + renderer)
- **Renderer:** React
- **User:** Single user (PianoMan), single machine (macOS)
- **CLI platforms:** Claude CLI, Codex CLI, Gemini CLI (extensible to future platforms)
- **Session identity:** Tracking IDs as primary keys (spec_session_identity v5.3)
- **Python 3.9+ compatibility** for all Python scripts (macOS system Python)

---

## 2. Entity Model

### 2.1 Session

The primary entity. Everything in the app ultimately references, displays, or operates on sessions.

#### Identity (Three-ID Model)

| ID | When Available | Mutability | Writer | Purpose |
|---|---|---|---|---|
| **Tracking ID** | At creation | Immutable | Wrapper or app (draft) | Primary key everywhere. Parent-child linking, filenames, logs. Format: `{YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}` where timestamp is local time for human readability. |
| **CLI Session ID** | Discovered post-launch (or pre-assigned for Claude) | Set once, immutable | Wrapper | Cross-reference to CLI platform data (JSONL files, conversation history) |
| **Terminal Session Name** | At creation | Mutable (may change on resume) | Wrapper | Terminal operations: attach, dump-screen, send-keys. Operational handle, never a stable reference. |

Platform codes: `cla` (Claude), `cod` (Codex), `gem` (Gemini).

Timestamps in Tracking IDs use local time for human readability. All internal timestamps (created_at, updated_at, event timestamps) are stored and transported in UTC. Display layer converts to local time.

#### Namespaced Entity IDs

All entity references use namespaced IDs to prevent collision across entity types:

```typescript
type EntityType = 'session' | 'brief' | 'project' | 'team' | 'tag' | 'folder';
type EntityId = `${EntityType}:${string}`;

interface EntityRef {
  type: EntityType;
  id: string;       // raw ID (e.g., tracking_id, brief name)
  ref: EntityId;    // namespaced string (e.g., "session:20260420_145848_cb5a742f_cla")
}
```

Generic APIs (folders, tags, navigation, selection) use `EntityId`. Entity-specific APIs accept raw IDs when the entity type is unambiguous from context. `CardId` is an alias for session/brief entity IDs used in folder and list contexts:

```typescript
type CardId = `session:${string}` | `brief:${string}`;
```

#### Draft Tracking IDs

Any authorized writer can create a draft Tracking ID. The session exists in the store immediately but with limited data:

```
draft -> pending -> confirmed
                 -> failed
                 -> orphaned
```

- **draft**: App or script created the ID. Most fields null. Session visible in app as placeholder. App pre-populates all context-known fields (display_name, project_dir, roles, tags, relationships) at draft time.
- **pending**: Launcher has been called with this ID. Waiting for identity completion.
- **confirmed**: Wrapper has finished. All identity fields populated. Session fully operational.
- **failed**: Launch attempt failed. App shows error state and offers retry/cleanup.
- **orphaned**: Pending timeout exceeded without confirmation. Cleanup candidate.

Draft pre-population: When the app creates a draft TrackingId, it writes all context-known fields to the store before calling ai_launcher. The launcher reads from the store via `--tracking-id` instead of receiving everything as CLI args. This simplifies the launcher interface and ensures the store is the single source of pre-launch context.

#### Three-Store Field Ownership

Session data is split across three stores with clear ownership. This aligns with the slim registry model from spec_session_identity v5.3:

**SQLite Registry (session_store.py)** — Slim identity pointers and cross-tool queryable metadata:

| Field | Owner | Mutability |
|---|---|---|
| tracking_id | Wrapper / App (draft) | Immutable |
| cli_session_id | Wrapper | Set once |
| terminal_session_name | Wrapper | Mutable |
| platform | Wrapper | Immutable |
| created_at | Wrapper / App (draft) | Immutable |
| session_dir | Wrapper | Immutable |
| project_dir | Wrapper | Mutable |
| history_file | Wrapper | Mutable |
| display_name | App / AI | Mutable |
| role | Wrapper / App | Mutable |
| spawned_by | Wrapper | Immutable |
| archived | App | Mutable |
| identity_status | App | Mutable |
| tags | App / AI | Mutable (card_tags join table) |

**sessionInfo.{uuid8}.json** — Mutable runtime metadata, wrapper-owned. Instance-scoped naming using the uuid8 from the tracking ID:

| Field | Owner | Mutability |
|---|---|---|
| working_dir | Wrapper | Mutable |
| model | Wrapper | Mutable |
| parent_tracking_id | Wrapper | Immutable |
| roles | Wrapper / App | Mutable |
| status_bar_data | Wrapper | Mutable |
| launch_params | Wrapper | Immutable |

**app_state.json** — App-owned UI state with no domain meaning outside the app:

| Field | Owner | Mutability |
|---|---|---|
| pinned | App | Mutable |
| lastViewedAt | App | Mutable |
| notes | App / AI | Mutable |
| promptbox_config | App | Mutable |

#### Independent State Axes

Session state is tracked across four independent axes, each with its own owner and source:

```typescript
// Identity lifecycle — persisted in SQLite
type IdentityStatus = 'draft' | 'pending' | 'confirmed' | 'failed' | 'orphaned';

// Terminal/substrate state — derived from substrate, not persisted
// On startup everything is "unknown" until substrate reports
type TerminalState = 'unknown' | 'connected' | 'disconnected' | 'killed';

// Interaction/runtime state — observed from terminal output, not persisted
// Independent from terminal state: terminal can be connected but session stopped
type RuntimeState = 'unknown' | 'running' | 'idle' | 'responding' | 'blocked' | 'permission_prompt' | 'error' | 'stopped';

// Archival state — user intent, persisted in SQLite
type ArchiveState = 'active' | 'archived';
```

Activity indicators for the UI are derived from RuntimeState:

| RuntimeState | Indicator | Detection Method |
|---|---|---|
| **idle** | Green steady | CLI at prompt, no thinking indicator |
| **responding** | Green pulsing | Thinking indicator visible |
| **blocked** | Yellow steady | Permission prompt detected |
| **permission_prompt** | Orange steady | Explicit approval request detected |
| **error** | Red steady | Error state in terminal |
| **stopped** | Gray steady | Process exited |

#### Session Kind (Derived, Not Persisted)

Session kind (chat vs worker) is derived from role per UCI data architecture:

- Has assistant/chat role -> chat
- Any other role -> worker
- Missing/unknown role on legacy sessions -> unknown

Not persisted as a type field. If the UI needs a manual override, it is stored as an annotation in app_state.json, but the primary derivation is always from role. Derived selectors:

```typescript
function isInteractiveAssistant(session: Session): boolean;
function isSpawned(session: Session): boolean;
function roleCategory(role: string): 'chat' | 'worker' | 'unknown';
```

### 2.2 Brief

A condensed session handoff document. Briefs are the mechanism for transferring context between sessions.

| Field | Owner | Store |
|---|---|---|
| name | Creator (AI/App) | SQLite (brief metadata) + Filesystem (YAML at ai_general/data/session_briefs/) |
| display_name | Creator | SQLite + YAML file |
| description | Creator | SQLite + YAML file |
| status | App | SQLite (active, superseded, archived) |
| created_at | Creator | SQLite |
| updated_at | System | SQLite |
| content_hash | System | SQLite (SHA256 of YAML content for change detection) |
| brief_path | System | SQLite (path to YAML content file) |
| schema_version | System | SQLite (YAML format version) |
| condenser_session | Creator | SQLite + YAML file |
| links | Creator / App | SQLite (entity_relationships) |
| folder | App | folders.json |
| fileSize | Derived | Filesystem |

The Brief YAML file on disk is the content store. SQLite holds the registry for queryability. Brief relationships use the entity_relationships table.

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

External ground truth: project metadata lives in the devTree directory itself. The app reflects it. Projects are indexed into SQLite for search/filter performance with change detection via filesystem mtime. Schema versioning via YAML frontmatter field. If a project dir is deleted/moved/renamed, the app marks it as unavailable and surfaces this in the UI.

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

External ground truth: team definitions are YAML files at `ai_general/data/teams/{name}.yml`. Runtime state (which sessions are active members) is derived. Teams are indexed into SQLite for queryability with change detection via filesystem mtime.

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

Tags are many-to-many with entities via a join table using namespaced EntityIds. Any entity (Session, Brief, Project, Team) can have tags.

```sql
card_tags (
  card_id TEXT NOT NULL,   -- namespaced: "session:..." or "brief:..."
  tag TEXT NOT NULL,
  PRIMARY KEY(card_id, tag)
)
```

### 2.6 Entity Relationships

All inter-entity links use a unified relationship system:

```sql
entity_relationships (
  source_type TEXT NOT NULL,    -- 'session' | 'brief' | 'project' | 'team'
  source_id TEXT NOT NULL,
  relation_type TEXT NOT NULL,
  target_type TEXT NOT NULL,    -- 'session' | 'brief' | 'project' | 'team'
  target_id TEXT NOT NULL,
  created_at TEXT,              -- UTC ISO timestamp
  created_by TEXT,              -- origin: 'wrapper' | 'app' | 'ai' | 'script'
  metadata_json TEXT,           -- role-in-team, launch params, review status, etc.
  PRIMARY KEY(source_type, source_id, relation_type, target_type, target_id)
)
```

Paired relationships are stored as a single row; the inverse is derived by query. `parent_tracking_id` remains as a legacy/convenience column on the sessions table, but the relationships table is authoritative for graph traversal.

#### Relationship Types (paired, bidirectional)

| Forward | Reverse | Meaning |
|---|---|---|
| forked_from | forked_to | Session forked from another |
| briefed_to | brief_of | Session was briefed into a Brief |
| launched_from | launched | Session launched from a Brief |
| loaded | loaded_by | Brief loaded into a Session |
| supersedes | superseded_by | Newer entity replaces older |
| member_of | has_member | Session is member of Team/Project |
| assigned_to | has_assignment | Session assigned to project/task/team role |
| continues | continued_by | Successor session from handoff/compaction/resume |
| relates_to | relates_to | Generic association |

Extensibility: New relationship types can be added without schema migration. The `metadata_json` field carries relationship-specific data (e.g., role_in_group for member_of, review_status for assigned_to). Allowed source/target type combinations per relationship type are validated at the application layer.

Delete/cascade behavior: Deleting an entity marks its relationships as orphaned but does not cascade-delete related entities. Archiving an entity preserves all relationships.

### 2.7 Folders, Views, Tags, and Relationships — Conceptual Model

Five distinct organizational concepts. They do not overlap:

| Concept | What it answers | Storage | Mutability |
|---|---|---|---|
| **Folders** | Where did I put this? | `folders.json` | User-managed containment hierarchy |
| **Views** | Show me a filtered subset | Computed at runtime (not stored) | Ephemeral filter presets |
| **Tags** | What metadata label does this have? | SQLite | User/AI-managed labels |
| **Relationships** | How are entities connected? | SQLite (entity_relationships) | Domain-driven graph edges |
| **Teams/Projects** | What organizational unit does this belong to? | YAML files + SQLite index | Domain entities with membership |

Views are computed filter presets over session metadata. They are NOT Groups, NOT Folders, NOT stored entities. Platform views (Claude/Codex/Gemini), Archive view, and Condenser view are all computed from session properties and tags.

Folders own their children (containers own children). A card belongs to exactly one folder (or root if unassigned). "Move to Folder" removes from old folder, adds to new. Two roots: `all_sessions` (session folder tree), `all_briefs` (brief folder tree). Session cards may only appear under the sessions root tree. Brief cards may only appear under the briefs root tree.

---

## 3. Data Architecture

### 3.1 External Ground Truth Model

The app is a **view** of external state. Three authoritative store categories, each with clear ownership:

```
+---------------------------------------------------------+
|                  External Ground Truth                   |
+------------------+------------------+-------------------+
| SQLite Store     | Filesystem       | App State         |
| (session_store   | (YAML files,     | (app_state.json,  |
|  .py)            |  devTree dirs,   |  folders.json)    |
|                  |  JSONL files,    |                   |
| Sessions         |  sessionInfo.    | Tabs, pinned,     |
| Tags             |  {uuid8}.json)   | lastViewedAt,     |
| Relationships    |                  | notes, folders,   |
| Identity         | Briefs           | UI preferences    |
| Brief metadata   | Projects         |                   |
|                  | Teams            |                   |
|                  | Transcripts      |                   |
|                  | sessionInfo      |                   |
+------------------+------------------+-------------------+
|                       reads + writes                    |
+---------------------------------------------------------+
|                    UAI Application                       |
|                    (reflects, never diverges)            |
+---------------------------------------------------------+
|                       reads + writes                    |
+------------------+------------------+-------------------+
| CLI Wrappers     | MCP Servers      | Scripts / Tools   |
| (ai_launcher)    | (prompting,      | (session_store.py |
|                  |  messages, etc)  |  deploy.sh, etc)  |
+------------------+------------------+-------------------+
```

**Key rules:**
- Multiple writers are acceptable, but all must use sanctioned APIs.
- SQLite writers MUST use `session_store.py`. Raw SQLite writes are unsupported.
- `folders.json` and `app_state.json` have exactly one writer: app main process.
- YAML writes use atomic file write and index update through the brief/team/project API.
- External tools that need durable session/brief/group/tag data use `session_store.py` directly.
- The renderer holds snapshots of authoritative state. Snapshots are caches, not truth.

### 3.2 Optimistic Updates (Draft Pattern)

When the app initiates a change:

1. App dispatches command through the command bus
2. Main process writes to external store immediately
3. Command result includes `commandId`, `changed` slices, and optionally `snapshots`
4. Renderer applies snapshots immediately (optimistic update shown as draft with subtle visual indicator)
5. On next store change event, renderer checks revision: if revision >= expected, draft confirmed and indicator removed
6. If store change event does not arrive within timeout (5 seconds), renderer re-reads affected store slices
7. If confirmed (data matches): draft indicator removed
8. If not confirmed (data diverges): renderer reconciles with authoritative store data and surfaces discrepancy in app log

### 3.3 Store Details

#### SQLite (session_store.py)

Canonical identity, lifecycle, tags, relationships. The registrar of record.

- Sessions: identity fields, created_at, platform, display_name, role, archived, identity_status
- Tags: name, color, icon, entity assignments (card_tags join table)
- Entity relationships: typed links between any entity pair with metadata
- Brief metadata: indexed fields for search/filter (name, display_name, status, content_hash, brief_path, schema_version)
- Groups: future expansion for team membership queries

Schema version stored in `PRAGMA user_version`. Migrations are forward-only, idempotent, logged, and preceded by automatic backup.

**Signal contract:** All SQLite writers MUST use `session_store.py`. After every successful commit, `session_store.py` MUST write the `sessions.changed` signal file:

```json
{
  "seq": 42,
  "changed": ["sessions", "briefs"],
  "source": "condense.py",
  "timestamp": "2026-04-19T04:00:00Z"
}
```

If the signal file only contains a touch/mtime (legacy), the app refreshes all SQLite-backed slices as fallback.

#### Filesystem

Source of truth for content and configuration:

- Brief YAML: `ai_general/data/session_briefs/{name}.yml`
- Project metadata: `{devTree_dir}/project.yml`
- Team definitions: `ai_general/data/teams/{name}.yml`
- Transcripts: `~/.claude/projects/{project}/{uuid}.jsonl`
- Session info: `sessionInfo.{uuid8}.json` — instance-scoped naming using the uuid8 from the tracking ID. Active and wrapper-owned.

Brief YAML changes must go through the brief/session_store API, which updates `content_hash` in SQLite and emits the change signal. Raw YAML edits are not automatically tracked; manual refresh/repair handles out-of-band edits.

#### App State (app_state.json + folders.json)

UI-owned ephemeral and preference state. Exactly one writer: app main process.

**app_state.json:**
- Open tabs and active tab
- Tab view history (back/forward stacks)
- Per-session: pinned status, lastViewedAt, notes, promptbox_config
- Per-folder: collapsed state, show_all_descendants
- Panel sizes, collapse states
- Card display preferences
- Design token overrides

Schema version stored as top-level `schema_version` field.

**folders.json:**

```typescript
interface FolderStore {
  schema_version: number;
  revision: number;           // incremented on every write
  roots: {
    sessions: string;         // "all_sessions"
    briefs: string;           // "all_briefs"
  };
  folders: Record<string, Folder>;
}

interface Folder {
  id: string;
  name: string;         // unique within same parent
  icon?: string;
  color?: string;
  builtin: boolean;
  subfolders: string[]; // ordered IDs of child folders
  cards: CardId[];      // ordered namespaced card IDs
}
```

Validation rules enforced after every mutation (always in dev builds):
- Every folder is reachable from exactly one root
- No cycles in the tree
- No folder appears in two parents' subfolders
- No card appears in two folders' cards
- cards entries are valid namespaced CardIds
- Builtin folders cannot be deleted
- Root folders cannot be moved or deleted

### 3.4 Schema Versioning

Each external store has a schema version with defined placement:

| Store | Version Location | Migration Scripts |
|---|---|---|
| SQLite | `PRAGMA user_version` | `migrations/sqlite/` |
| app_state.json | Top-level `schema_version` | `migrations/app_state/` |
| folders.json | Top-level `schema_version` | `migrations/folders/` |
| Brief YAML | Frontmatter `schema_version` | `migrations/briefs/` |
| sessionInfo.{uuid8}.json | Top-level `schema_version` | `migrations/session_info/` |

When the app reads a store:

1. Check schema_version
2. If current version: proceed
3. If older version: back up store, run migration, update version, log migration
4. If newer version: warn user, operate in read-only mode for that store

Migrations are forward-only, idempotent, logged, and preceded by backup. If one store migrates and another fails, the app logs the partial state and continues in degraded mode for the failed store.

---

## 4. Store Synchronization Contract

### 4.1 Two-Channel Change Notification

Data changes flow through two separate notification channels to the renderer:

**Channel 1: `onStoreChanged`** — durable/persisted store changes

```
Persistent data change (SQLite, folders.json, app_state.json, Brief YAML)
  -> Main process detects change
  -> Main process emits: onStoreChanged(event)
  -> Renderer refreshes ONLY the affected store(s)
```

**Channel 2: `onRuntimeChanged`** — ephemeral state changes

```
Runtime state change (terminal state, interaction state, statusline)
  -> Main process detects change
  -> Main process emits: onRuntimeChanged(event)
  -> Renderer updates runtime/telemetry state only -- never triggers store refresh
```

Statusline updates are high-frequency. They flow through `onRuntimeChanged` and are throttled/coalesced. They never trigger session/folder/appState refresh.

### 4.2 Store Change Event

```typescript
window.terminalApi.onStoreChanged(callback: (event: StoreChangedEvent) => void)

interface StoreChangedEvent {
  eventId: string;                        // unique event ID
  sequence: number;                       // monotonic sequence number
  commandId?: string;                     // if triggered by a command, its ID
  changed: StoreSlice[];                  // which stores changed
  source: 'command' | 'external' | 'poll';
  revisions?: Partial<Record<StoreSlice, number>>;
  snapshots?: Partial<Record<StoreSlice, unknown>>;
}

type StoreSlice = 'sessions' | 'folders' | 'appState' | 'briefs' | 'groups';
```

### 4.3 Runtime Change Event

```typescript
window.terminalApi.onRuntimeChanged(callback: (event: RuntimeChangedEvent) => void)

interface RuntimeChangedEvent {
  changed: RuntimeSlice[];
  sessionId?: string;                     // which session, if applicable
  data?: {
    terminalState?: TerminalStateSnapshot;
    runtimeState?: RuntimeStateSnapshot;
    statusline?: StatuslineSnapshot;
  };
}

type RuntimeSlice = 'terminalState' | 'runtimeState' | 'statusline';
```

### 4.4 Change Detection by Source

| Source | How Main Process Detects It |
|---|---|
| App's own commands | Command handler knows what it changed — emits immediately after write |
| External SQLite writes | `sessions.changed` signal file + `fs.watch` with debounce. Fallback: periodic mtime/revision poll every N seconds. |
| Terminal/substrate state | Substrate poll/watch, attach/detach callbacks |
| Interaction/runtime state | Terminal output observer |
| Statusline telemetry | Statusline callback, throttled |
| Brief YAML content | Not auto-detected. Brief API updates SQLite + signal. Manual refresh/repair for raw edits. |

### 4.5 Renderer Refresh Rules

1. **Command snapshots apply immediately.** When a command result includes snapshots, update stores directly — no need to wait for a change event.
2. **Change events refresh only affected slices.** The `changed` array tells the renderer which stores to refresh.
3. **Ignore stale revisions.** If event revision <= store's current revision, skip. Prevents double-refresh when command result and change event both arrive.
4. **Debounce/coalesce external events.** Multiple rapid signal file touches -> one refresh.
5. **Runtime events never trigger store refresh.** Statusline/terminal/runtime state updates are separate from persisted data.

### 4.6 Multi-Store Command/Saga Protocol

Commands that touch multiple stores write in a defined order and emit one combined change event.

Example — `briefs.create`:
1. Write YAML content file
2. Hash YAML content
3. Insert SQLite brief metadata + relationships
4. Add brief card to `all_briefs` root in `folders.json`
5. Emit `changed: ['briefs', 'folders']`

If a crash occurs between steps 3 and 4, startup reconciliation adds missing brief cards to root or marks as unfiled. The app runs reconciliation checks on bootstrap.

**Saga protocol for multi-store commands:**
- Define write order per command type (most critical store first)
- No distributed transactions — accept partial writes with repair
- Each saga step records intent before execution
- Compensation/repair runs on startup: detect incomplete sagas, complete or roll back
- App log records saga steps for debugging
- Test fixtures verify reconciliation after simulated partial failures

---

## 5. Component API Contracts

### 5.1 Conventions

- **Keys** are dot-separated paths scoped to the component: `filter.platform`, `tabs.active`
- **get/list/describe** are synchronous reads against renderer snapshots
- **execute(command)** dispatches commands returning `Promise<CommandResult>` — the only path for domain mutations
- **set/update** on component-local UI state (e.g., filter selection, panel width) are synchronous and local-only
- **Delete** returns `boolean` (true if removed)
- **Describe** returns JSON interface definition (see Section 5.2)
- **Command origin** is attached to every mutation: `user | internal | external-api | embedded-ai | debug`
- **Mutations restricted** to internal callers by default. External/AI callers require appropriate capabilities unless explicitly permitted per-command.
- **Serialization:** All API values must be JSON-serializable. Use arrays instead of Sets at API boundaries. Dynamic paths with dots in IDs use bracket notation: `get("folders[my.id]")`.

### 5.2 Component Self-Description

Every architectural component provides a `describe()` method returning a JSON interface definition:

```typescript
interface ComponentDescription {
  schemaVersion: number;               // Description schema version (currently 1)
  id: string;                          // e.g., "session_navigator"
  path: string;                        // Stable component path: "app.navigator"
  instanceId?: string;                 // For multi-instance components
  name: string;                        // e.g., "Session Navigator"
  description: string;                 // Human-readable purpose
  parent: string | null;               // Parent component path
  children: string[];                  // Child component paths

  state: {                             // Readable state keys
    [key: string]: {
      type: JSONSchema;                // JSON Schema, not TypeScript string
      description: string;
      readable: boolean;
      writable: boolean;               // true only for local UI state
      enumValues?: any[];
      defaultValue?: any;
      examples?: any[];
    }
  };

  commands: {                          // Available commands (domain mutations)
    [name: string]: {
      description: string;             // What it does, for AI/user consumption
      parameters: JSONSchema;          // Full JSON Schema with constraints
      returns: JSONSchema;
      access: CommandAccess;
      safety: CommandSafety;
      sideEffects: string[];           // e.g., ["writes:sqlite", "writes:folders.json"]
      affectedStores: StoreSlice[];
      preconditions?: string[];
      postconditions?: string[];
      idempotent: boolean;
      async: boolean;
      latencyHint?: 'fast' | 'moderate' | 'slow';
      errorCodes?: string[];
    }
  };

  actions: {                           // Clickable/activatable UI elements
    [name: string]: {
      description: string;             // "Click to expand this group"
      trigger: string;                 // command name this action invokes
      context: string;                 // What contextual data the parent provides
    }
  };

  context: {                           // Context this component needs from providers
    [key: string]: {
      type: JSONSchema;
      required: boolean;
      provider: string;                // Which context provider supplies this
    }
  };

  events: {                            // Events this component emits/subscribes to
    emits: string[];
    subscribes: string[];
  };

  deprecated?: {
    since: string;
    replacement?: string;
    message?: string;
  };
}

type CommandAccess = 'public' | 'internal' | 'debug';
type CommandSafety = 'safe' | 'destructive' | 'requires_confirmation';
type JSONSchema = Record<string, any>; // Standard JSON Schema object
```

This enables:
- **Embedded AI:** Discovers the app by walking the component tree, reading descriptions, invoking commands with full schema knowledge
- **Auto-generated help:** `!help navigator` renders the navigator's description + commands
- **Diagram generation:** Component tree with connections rendered from describe() output
- **Testing:** Contract verification — describe() matches actual API
- **Safety:** AI and external callers can check safety level and preconditions before executing

### 5.3 Session Store API

The shared data layer. Not a UI component — all components reference it.

```
SessionStore {
  // Read (synchronous against renderer snapshot)
  get(tracking_id: TrackingId): Session | null
  list(filter?: SessionFilter): Session[]
  getByCliUuid(uuid: string): Session | null
  getByTerminalSession(name: string): Session | null
  getChildren(tracking_id: TrackingId): Session[]
  getRelated(tracking_id: TrackingId, relationship?: string): EntityRef[]

  // Write (dispatches commands, returns Promise)
  createDraft(platform: Platform, opts?: DraftOpts): Promise<CommandResult<TrackingId>>
  update(tracking_id: TrackingId, patch: SessionPatch): Promise<CommandResult>

  // Runtime (local renderer state, synchronous)
  updateRuntime(tracking_id: TrackingId, patch: RuntimePatch): void

  // Subscriptions
  onChange(tracking_id: TrackingId, path?: string, cb: Callback): Unsubscribe
  onAnyChange(cb: Callback): Unsubscribe

  // Lifecycle
  reload(): Promise<void>
}
```

### 5.4 SessionNavigator API

Owns: active navigator tab, filter/group/sort state, folder tree, selection.

```
SessionNavigator {
  // Tab
  get("active_tab"): NavigatorTab          // sessions | briefs | teams | projects
  set("active_tab", value: NavigatorTab): void

  // Filter (carries forward UCI's FilterBar patterns)
  get("filter"): FilterConfig
  update("filter", patch: Partial<FilterConfig>): void
  get("filter.platform"): Platform[]
  get("filter.status"): RuntimeState[]
  get("filter.tags"): string[]
  get("filter.text"): string
  get("filter.unaffiliated"): boolean
  get("filter.date_range"): DateRange | null

  // Sort
  get("sort_field"): SortField            // activity | created | name
  get("sort_direction"): SortDirection    // asc | desc
  set("sort_field", value: SortField): void
  set("sort_direction", value: SortDirection): void

  // Folders
  get("selected_folder"): string | null
  set("selected_folder", value: string | null): void
  list("folders"): Folder[]
  get("folders[id]"): Folder | null

  // Selection (multi-select)
  get("select_mode"): boolean
  set("select_mode", value: boolean): void
  get("selected_ids"): EntityId[]
  update("selected_ids.add", value: EntityId): void
  update("selected_ids.remove", value: EntityId): void
  update("selected_ids.toggle", value: EntityId): void
  update("selected_ids.clear"): void

  // Computed
  list("visible_items"): EntityRef[]        // After filter/sort applied
}
```

The navigator toolbar carries forward UCI's proven patterns: FilterBar pills, date range with duration mode, text search, and sort controls.

### 5.5 Workspace API

Owns: tabs, tab groups, active tab, grid layout.

```
Workspace {
  // Tabs
  list("tabs"): Tab[]
  get("tabs.active"): Tab | null
  get("tabs[session_id]"): Tab | null
  execute("tabs.open", { tracking_id }): Promise<CommandResult>
  execute("tabs.close", { tracking_id }): Promise<CommandResult>
  execute("tabs.activate", { tracking_id }): Promise<CommandResult>

  // Tab Groups
  list("tab_groups"): TabGroup[]
  get("tab_groups[id]"): TabGroup | null
  execute("tab_groups.create", opts: TabGroupOpts): Promise<CommandResult>
  execute("tab_groups.delete", { id }): Promise<CommandResult>
  execute("tab_groups.update", { id, patch }): Promise<CommandResult>
  execute("tab_groups.layout", { id, layout: GridLayout }): Promise<CommandResult>

  // Grid Layout
  get("grid_layout"): GridLayout           // single | vertical_2 | horizontal_2 | grid_2x2
  set("grid_layout", value: GridLayout): void

  // Browse mode
  get("browse_mode"): boolean
}
```

### 5.6 SessionPane API

Owns: mode (terminal/transcript), focus state.

```
SessionPane {
  get("session_id"): TrackingId
  get("mode"): PaneMode                   // terminal | transcript
  set("mode", value: PaneMode): void
  get("focused"): boolean
  set("focused", value: boolean): void
}
```

### 5.7 TranscriptView API

Owns: filter toggles, scroll, search, selection.

```
TranscriptView {
  get("session_id"): TrackingId
  get("filters"): TranscriptFilters
  update("filters", patch: Partial<TranscriptFilters>): void
  get("auto_follow"): boolean
  set("auto_follow", value: boolean): void
  get("search_query"): string | null
  set("search_query", value: string | null): void
  get("width_percent"): number
  set("width_percent", value: number): void

  // Selection (multi-select)
  get("select_mode"): boolean
  set("select_mode", value: boolean): void
  get("selected_message_ids"): number[]

  // Content (read-only)
  list("day_groups"): DayGroup[]
  get("message_count"): number
}
```

### 5.8 PromptBox API

Owns: text, mode, target, history, shell output.

```
PromptBox {
  get("text"): string
  set("text", value: string): void
  get("target_session_id"): TrackingId
  set("target_session_id", value: TrackingId): void
  get("mode"): PromptMode                 // prompt | command | shell
  get("shell_output"): string | null
  get("shell_output_visible"): boolean
  set("shell_output_visible", value: boolean): void
  get("height"): number
  set("height", value: number): void

  // Actions (domain mutations via commands)
  execute("stage"): Promise<CommandResult>          // Cmd+Enter: stage to target
  execute("submit_shell"): Promise<CommandResult>   // Execute $ command
  execute("rewrite"): Promise<CommandResult>        // Send to LLLM for rewrite (shows diff/preview)
  execute("clear"): Promise<CommandResult>

  // History
  list("history"): PromptHistoryEntry[]
  execute("history_prev"): Promise<CommandResult>
  execute("history_next"): Promise<CommandResult>

  // Pre/Post Prompt
  get("pre_prompt"): PromptAddendum[]
  get("post_prompt"): PromptAddendum[]
  execute("pre_prompt.add", { addendum: PromptAddendum }): Promise<CommandResult>
  execute("post_prompt.add", { addendum: PromptAddendum }): Promise<CommandResult>
  get("reminders"): PeriodicReminder[]
}
```

Prompt delivery safety:
- **Staged vs submitted:** Staging writes text to the target terminal. Submission is the terminal's job.
- **Target follows focus:** Prompt target defaults to the focused grid cell's session.
- **Busy-state behavior:** If target session is responding, the prompt is queued with visible pending indicator.
- **Queue behavior:** Queued prompts are visible and cancellable. FIFO delivery.
- **Provenance:** Every staged prompt is logged with source (user/AI/comms), timestamp, and target.
- **Pre/post merge order:** pre-prompts prepended in order, post-prompts appended in order.
- **Rewrite safety:** Rewrite shows diff/preview before replacing. Undo available.
- **Shell mode:** Shell commands require confirmation for destructive operations.

### 5.9 ContextPanel API (Right Panel)

Owns: open/closed, active tab, width, digest tracking.

```
ContextPanel {
  get("open"): boolean
  set("open", value: boolean): void
  get("active_tab"): ContextTab           // details | docs | memories | messages | prompts | digests
  set("active_tab", value: ContextTab): void
  get("width"): number
  set("width", value: number): void

  // Digest tracking (Knowledge, Traits, Roles loaded by focused session)
  list("digests.loaded"): DigestEntry[]
  list("digests.available"): DigestEntry[]
  execute("digests.load", { id: string }): Promise<CommandResult>
}
```

### 5.10 BottomPanel API

Owns: open/closed, active tab, height, related entities, system monitor.

```
BottomPanel {
  get("open"): boolean
  set("open", value: boolean): void
  get("active_tab"): BottomTab            // related | logs | app_log | monitor
  set("active_tab", value: BottomTab): void
  get("height"): number
  set("height", value: number): void

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

## 6. Command System

### 6.1 Command Bus

All domain mutations flow through a central command bus. Commands are typed, hierarchical, and observable.

```typescript
interface Command {
  id: string;                      // Unique command ID (UUID)
  type: string;                    // Dot-path: "workspace.tabs.open"
  payload: Record<string, any>;
  origin: CommandOrigin;           // user | internal | external-api | embedded-ai | debug
  actor?: ActorRef;                // Actor identity with session scoping
  parentId?: string;               // For nested commands
  correlationId?: string;          // Groups related commands
  idempotencyKey?: string;         // For retry safety
  timestamp: string;               // UTC ISO timestamp
  dryRun?: boolean;                // Preview effects without execution
}

interface CommandResult<T = unknown> {
  ok: boolean;
  commandId: string;
  data?: T;                        // Command-specific result data
  error?: CommandError;
  changed?: Partial<Record<StoreSlice, boolean>>;
  snapshots?: Partial<Record<StoreSlice, unknown>>;
  effects?: EffectRecord[];
  undo?: UndoDescriptor;
}

interface CommandError {
  code: string;                    // Machine-readable error code
  message: string;                 // Human-readable description
  details?: unknown;               // Structured error details
  retryable?: boolean;
}

interface EffectRecord {
  type: string;                    // e.g., "notification.emitted", "file.written"
  target?: string;
  timestamp: string;
}

interface UndoDescriptor {
  commandId: string;
  undoable: boolean;
  description: string;             // "Undo: move session to folder X"
  reverseCommand?: Command;        // The command that reverses this one
  expiresAt?: string;              // Undo window
}

interface ActorRef {
  type: 'user' | 'embedded-ai' | 'external-client' | 'system';
  sessionId?: string;              // For AI actors: which session
  clientId?: string;               // For external clients
}

type CommandOrigin = 'user' | 'internal' | 'external-api' | 'embedded-ai' | 'debug';
```

### 6.2 Command Hierarchy

Commands form a tree. Child commands inherit behaviors from parents:

```
app
+-- session
|   +-- session.create
|   +-- session.stop
|   +-- session.resume
|   +-- session.fork
|   +-- session.archive
|   +-- session.unarchive
|   +-- session.update          // notes, display_name, tags, etc.
|   +-- session.move_to_folder
+-- workspace
|   +-- workspace.tabs.open
|   +-- workspace.tabs.close
|   +-- workspace.tabs.activate
|   +-- workspace.tab_groups.*
+-- navigator
|   +-- navigator.filter.*
|   +-- navigator.sort.*
|   +-- navigator.select.*
+-- prompt
|   +-- prompt.stage
|   +-- prompt.shell
|   +-- prompt.rewrite
|   +-- prompt.cancel_queued
+-- brief
|   +-- brief.create
|   +-- brief.launch
|   +-- brief.load
|   +-- brief.archive
+-- project
|   +-- project.create
|   +-- project.switch
+-- team
|   +-- team.create
|   +-- team.launch
|   +-- team.notify
+-- folders
|   +-- folders.create
|   +-- folders.rename
|   +-- folders.delete
|   +-- folders.moveFolder
|   +-- folders.moveCard
|   +-- folders.unfileCard
|   +-- folders.reorderCards
|   +-- folders.reorderSubfolders
+-- tags
|   +-- tags.add
|   +-- tags.remove
|   +-- tags.toggle
|   +-- tags.create
|   +-- tags.delete
+-- relationships
|   +-- relationships.link
|   +-- relationships.unlink
|   +-- relationships.update_metadata
+-- terminal
|   +-- terminal.attach
|   +-- terminal.detach
|   +-- terminal.kill
|   +-- terminal.send_keys
|   +-- terminal.dump_screen
+-- transcript
|   +-- transcript.search
|   +-- transcript.load_range
|   +-- transcript.export_excerpt
+-- notification
|   +-- notification.emit
|   +-- notification.route
|   +-- notification.ack
|   +-- notification.cancel
+-- comms
|   +-- comms.request
|   +-- comms.respond
|   +-- comms.escalate
+-- appState
|   +-- appState.setPinned
|   +-- appState.setFolderPref
|   +-- appState.setPromptBoxConfig
+-- debug
    +-- debug.inspect
    +-- debug.validate_stores
    +-- debug.repair_indexes
```

### 6.3 Entry/Exit Hooks

Every command type can have pre-execution and post-execution hooks:

```typescript
commandBus.before('session.*', (cmd) => {
  // Global: log every session command
  logger.log('command', cmd);
});

commandBus.after('session.stop', (cmd, result) => {
  // After stop: notify team if session was a team member
  if (result.ok) {
    notificationBus.emit('session.stopped', cmd.payload);
  }
});

commandBus.before('*', (cmd) => {
  // Global: access control check
  if (!accessControl.check(cmd)) {
    throw new AccessDeniedError(cmd);
  }
});
```

### 6.4 Access Control

#### Capabilities and Scopes

Access control uses a capabilities model rather than a flat origin-based matrix:

```typescript
type Capability =
  | 'sessions:read'
  | 'sessions:write'
  | 'terminal:send'
  | 'terminal:read'
  | 'files:read'
  | 'files:write'
  | 'app:configure'
  | 'app:debug'
  | 'comms:send'
  | 'comms:receive';
```

#### Origin Capability Matrix

| Origin | Default Capabilities | Notes |
|---|---|---|
| **user** | All | Full access |
| **internal** | All except app:debug | System-internal commands |
| **embedded-ai** | sessions:read, terminal:read, comms:send, comms:receive + per-command whitelist | Scoped to relevant sessions |
| **external-api** | sessions:read, terminal:read | Additional capabilities require debug mode |
| **debug** | All | Logged and time-limited. Auto-expires after configured duration (default 30 min). |

#### Command Safety Classification

Every command declares a safety level:

| Safety | Meaning | Policy |
|---|---|---|
| **safe** | Read-only or trivially reversible | Execute immediately |
| **destructive** | Data loss or irreversible terminal action | Require confirmation for embedded-ai and external-api origins |
| **requires_confirmation** | Sensitive operation regardless of origin | Always prompt for confirmation |

#### Privacy Considerations

Read access for embedded-ai and external-api respects privacy boundaries:
- Transcript thinking blocks: redacted unless explicitly permitted
- Session notes: redacted for external-api unless debug mode
- Private messages: visible only to sender, recipient, and user
- All denied/allowed access decisions are logged to the command audit log

---

## 7. Event & Notification System

### 7.1 Internal Event System

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

Renderer-local events are synchronous. Store change events from main process are async (IPC). No polling required for renderer-local state.

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
| `store:changed` | `StoreChangedEvent` | Main Process (IPC) |
| `runtime:changed` | `RuntimeChangedEvent` | Main Process (IPC) |

### 7.2 Notification Bus

Cross-boundary delivery. A single emit reaches multiple subscribers through different mechanisms.

#### Notification Envelope

```typescript
interface Notification {
  id: string;                      // Unique notification ID
  type: string;                    // e.g., "session.waiting_for_input"
  source: EntityRef;               // Who/what generated this
  data: Record<string, any>;       // Notification payload
  urgency: 'info' | 'attention' | 'critical';
  targets?: EntityId[];            // Specific targets, or all subscribers if omitted
  messageId: string;               // For threading (see AI Comms)
  inReplyTo?: string;              // References a previous messageId
  dedupeKey?: string;              // Prevent duplicate delivery
}
```

#### Subscriber Types

| Subscriber | Delivery Mechanism | Latency |
|---|---|---|
| **App UI** | Internal event -> Tab flash, icon decorator, badge, status bar | Immediate |
| **AI (Claude with hooks)** | Hook injection on next tool_use or notification hook | Best-effort < 1 second |
| **AI (Codex/Gemini, no hooks)** | App queues prompt for next idle moment | Best-effort next turn |
| **User** | macOS notification via send_user_notification.py | Immediate |
| **Team** | Routes to team's comms plan (escalation chain) | Per plan |
| **Log** | Appended to session activity log and/or app log | Immediate |

Latency claims are best-effort by adapter capability. Delivery is measured and recorded in the notification log.

#### Notification Delivery Lifecycle

Every cross-boundary notification has a durable delivery record:

```typescript
interface NotificationRecord {
  id: string;
  correlationId?: string;          // Groups related notifications
  replyTo?: string;                // For response threading
  messageId: string;               // Unique message ID for threading
  source: EntityRef;
  target: EntityRef;
  type: string;
  urgency: 'info' | 'attention' | 'critical';
  mechanismRequested: FeedbackMechanism;
  mechanismActual?: FeedbackMechanism;
  status: DeliveryStatus;
  createdAt: string;               // UTC
  expiresAt?: string;              // TTL
  deliveredAt?: string;
  acknowledgedAt?: string;
  retryCount: number;
  maxRetries: number;
  failureReason?: string;
  dedupeKey?: string;
  ackRequired: boolean;
  contentRef?: string;             // Reference to notification content
  responseRef?: string;            // Reference to response content
}

type DeliveryStatus =
  | 'queued'
  | 'delivering'
  | 'delivered'
  | 'acknowledged'
  | 'failed'
  | 'expired'
  | 'cancelled';
```

Notification records are persisted in the notification log (app-local SQLite table or JSON log). They enable:
- Tracking whether a feedback request was delivered and acknowledged
- Detecting stalled conversations ("waiting for response from session X since N minutes ago")
- Retry with backoff for failed deliveries
- Deduplication of repeated notifications
- Audit trail for inter-session communications

---

## 8. Hooks Architecture

### 8.1 Hook Levels

Hooks exist at three levels, each with different trigger mechanisms:

#### App-Level Hooks

Fire on command bus events. Available to all components.

| Hook | Trigger | Use Case |
|---|---|---|
| `command.before.*` | Before any command executes | Logging, access control, validation |
| `command.after.*` | After any command completes | Notifications, side effects, undo recording |
| `app.startup` | Application starts | Load state, connect to stores, reconciliation |
| `app.shutdown` | Application closing | Save state, cleanup |

#### Session-Level Hooks

Fire on session lifecycle and communication events. Delivered differently per platform.

| Hook | Trigger | Claude Delivery | Codex/Gemini Delivery |
|---|---|---|---|
| `session.pre_prompt` | Before a prompt is sent to session | Claude Code hook | App injects addendum text |
| `session.post_response` | After session responds | Claude Code hook | App checks on next poll |
| `session.activity_change` | Status/activity state changes | Notification hook | App-side detection |
| `session.message_received` | Inter-session message arrives | Notification hook | App queues prompt |
| `session.reminder_due` | Periodic reminder timer fires | Injected into next prompt | Injected into next prompt |

#### Team-Level Hooks

Fire on team events. Routed per the team's comms plan.

| Hook | Trigger | Routing |
|---|---|---|
| `team.member_blocked` | Team member hits permission prompt | -> team lead (prompt), -> user (notification) |
| `team.member_error` | Team member in error state | -> all members (notification), -> user (notification) |
| `team.member_completed` | Team member finishes assigned task | -> requester (per feedback_mechanism) |
| `team.escalation` | Member escalates issue | -> escalation_chain in comms_plan |

### 8.2 Platform Capability Matrix

Instead of vague hook descriptions, each platform's actual capabilities are defined:

| Capability | Claude CLI | Codex CLI | Gemini CLI |
|---|---|---|---|
| Inject before user-submitted prompt | Yes (pre-tool hook) | No | No |
| Inject while idle without user action | Yes (notification hook) | No | No |
| Notify after model response completion | Yes (post-tool hook) | No | No |
| Read status/busy state | Yes (statusline) | Partial (process state) | Partial (process state) |
| Write queued prompt without accidental submission | Yes (hook injection) | No (send-keys only) | No (send-keys only) |
| Distinguish staged vs submitted | Yes | No | No |

For platforms without hook support, the app compensates by becoming the session's "hook runtime": monitoring state via screen parsing and injecting prompts via send-keys when the session is idle.

### 8.3 AI Feedback Timeout Pattern

When an AI requests feedback (review, approval, "shall I proceed?"):

1. AI sends request with specified `feedback_mechanism` (none | message | prompt)
2. App records a `FeedbackRequest` with `messageId`, `dueAt`, delivery status
3. AI schedules a self-prompt timeout (via `prompting:schedule_future_prompt`)
4. If feedback arrives before timeout: process normally, update FeedbackRequest status
5. If timeout fires without feedback: AI self-assesses
   - Can I proceed safely without the input? -> proceed, note the assumption
   - Is this blocking? -> retry the request
   - Still no response? -> escalate per team comms plan or notify user

```yaml
# Example feedback request
feedback_request:
  messageId: "msg_abc123"
  from: session_A
  to: session_B
  type: review_request
  mechanism: prompt
  timeout_seconds: 300
  timeout_action: escalate   # retry | proceed | escalate
  content: "Please review the architecture spec at ..."
```

Timeout profiles for different request types:

| Type | Default Timeout | Notes |
|---|---|---|
| Review | 5 min | Active review expected |
| Permission/Approval | Immediate + periodic reminder | Time-sensitive |
| Long-running work | Heartbeat interval (30 min) | Progress check |
| Low-priority FYI | No timeout | Informational only |

---

## 9. AI Integration

### 9.1 Embedded AI

An AI agent that operates within the app, interacting through the component API:

1. **Discovery:** Walks the component tree via `describe()`. Learns what's available, including schemas, safety levels, and preconditions.
2. **Observation:** Reads state via `get()` and `list()`. Understands current context.
3. **Action:** Invokes commands via the command bus. Same commands as user actions. Safety classification determines whether confirmation is needed.
4. **Learning:** Component descriptions include human-readable instructions. The AI reads the app the same way a user would read help docs.

The embedded AI has `embedded-ai` origin on all commands. Access is controlled per Section 6.4.

**Operational boundaries:**
- Runs in the renderer process as a controlled agent
- Authenticates to command bus with `embedded-ai` origin and session-scoped ActorRef
- Can read state within its capability grants (default: sessions:read, terminal:read)
- Cannot execute destructive commands without confirmation
- All actions are visible in the command log and app log
- Rate-limited: maximum N commands per minute (configurable, default 60)
- Loop detection: if the same command fails 3 times consecutively, pause and surface to user
- Can be disabled/killed via `app.embedded_ai.disable` command (user-only)

### 9.2 LLLM Integration

Local large language model for lightweight tasks that don't require cloud API:

- **Prompt rewrite:** PromptBox.execute("rewrite") sends text to LLLM, shows diff/preview, replaces with result on confirmation
- **Summarization:** Condense transcript sections for brief generation
- **Classification:** Tag suggestions, session kind inference

Integration via a service adapter in main process. The adapter wraps the existing `local-llm` MCP server (reason_on_text, reason_on_file) but provides a clean boundary. Failure fallback: if LLLM is unavailable, features degrade gracefully (rewrite disabled, summarization skipped, classification deferred).

### 9.3 AI-to-AI Communication

#### Principles

1. **Every message has an ID.** All prompts and messages get a unique `messageId`. Responses reference `inReplyTo: <messageId>`. This enables conversation thread visualization and stall detection.
2. **Requester specifies mechanism.** Every request includes `feedback_mechanism: none | message | prompt`. Default is `prompt`.
3. **Timeout is mandatory.** Every request that expects a response must have a `dueAt` timestamp.
4. **The app enforces for mediated responses; flags non-mediated responses when detectable.** The app does NOT attempt to detect wrong mechanisms and reroute. Instead, it monitors the durable response channel and times out if no mediated response arrives.
5. **Hooks trigger receipt.** AIs don't poll for messages — hooks (or app-injected prompts) force them to process incoming communications.

#### Structured Request/Response Protocol

```typescript
interface CommsRequest {
  messageId: string;               // Unique ID for this message
  inReplyTo?: string;              // Previous messageId this responds to
  from: TrackingId;                // Requester session
  to: TrackingId;                  // Responder session
  type: string;                    // "review_request", "status_update", etc.
  feedbackMechanism: FeedbackMechanism;  // none | message | prompt
  content: string;                 // Human-readable request content
  structuredData?: Record<string, any>;  // Machine-readable payload
  dueAt?: string;                  // When response is expected (UTC)
  timeoutAction: 'retry' | 'proceed' | 'escalate';
  priority: 'low' | 'normal' | 'high';
}

interface CommsResponse {
  messageId: string;               // Unique ID for this response
  inReplyTo: string;               // The request's messageId
  from: TrackingId;
  to: TrackingId;
  content: string;
  structuredData?: Record<string, any>;
}
```

#### Communication Flow

```
AI_A wants review from AI_B:
  1. AI_A calls comms.request({
       messageId: "msg_001",
       type: "review_request",
       to: AI_B.tracking_id,
       feedbackMechanism: "prompt",
       dueAt: "2026-04-22T15:05:00Z"
     })
  2. App records FeedbackRequest with delivery status
  3. NotificationBus routes to AI_B:
     - Claude: notification hook fires with structured request including messageId
     - Codex: app queues prompt for next idle moment with structured request
  4. App surfaces in UI: tab indicator showing "waiting for response from AI_B"
  5. AI_B processes request, responds via comms.respond({
       messageId: "msg_002",
       inReplyTo: "msg_001",
       content: "Review complete. Approved with notes..."
     })
  6. AI_A receives response (hook or queued prompt) with inReplyTo correlation
  7. If dueAt passes without response: AI_A self-assesses per timeoutAction
```

#### Waiting-for-Response Detection

The app knows a request was sent (has messageId) and a response was expected (has dueAt). This is surfaced in the UI:

- Tab indicator: badge showing "waiting for response from session X since N minutes ago"
- Bottom panel: comms status in related entities view
- Notification: if wait exceeds threshold, notify user

---

## 10. UI Component Hierarchy

### 10.1 Component Tree

```
Application
+-- SessionNavigator (Left Panel)
|   +-- NavigatorTabs (Sessions | Briefs | Teams | Projects)
|   +-- Toolbar (Filter pills, date range, text search, sort — per active tab)
|   +-- FolderTree (within Sessions/Briefs tabs)
|   +-- EntityList
|       +-- EntityCard[] (compact items, multi-selectable)
|
+-- Workspace (Center)
|   +-- TabBar
|   |   +-- Tab[] (individual session tabs, with comms status badges)
|   |   +-- TabGroup[] (container of tabs)
|   +-- GridLayout (1x1 | 2x1 | 1x2 | 2x2)
|   |   +-- SessionPane[] (one per grid cell)
|   |       +-- PaneHeader
|   |       +-- TerminalView (live session)
|   |       +-- TranscriptView (review/stopped)
|   +-- PromptBox
|       +-- TextArea (with mode prefix detection)
|       +-- ShellOutputArea (above, for $ commands)
|       +-- PrePostPromptIndicator
|
+-- ContextPanel (Right, collapsible)
|   +-- ContextTab[]
|       +-- DetailsTab (session metadata + notes)
|       +-- DigestsTab (Knowledge, Traits, Roles -- loaded/available)
|       +-- DocsTab (loaded documents)
|       +-- MessagesTab (inter-session messages with thread view)
|       +-- PromptsTab (queued prompts)
|
+-- BottomPanel (collapsible, drawer bar visible when closed)
    +-- RelatedEntitiesTab (children, linked sessions, briefs, team members)
    +-- SessionLogTab (per-session log viewer)
    +-- AppLogTab (application-wide event log)
    +-- SystemMonitorTab (CPU, memory, active sessions, errors)
```

### 10.2 Action Context Providers

Instead of actions querying parent chains (service-locator anti-pattern), components use explicit context providers:

```typescript
// Provider wraps a subtree with context
<ActionContextProvider value={{ entityRef, selectionScope, location }}>
  <EntityCard />
</ActionContextProvider>

// Consumer declares what context it needs
function useActionContext(requiredKeys: string[]): ActionContext;
```

Components declare their context requirements in `describe().context`. Tests verify context contracts — a component that requires `entityRef` context will fail if rendered outside a provider.

Benefits over parent-chain querying:
- Dependencies are explicit and testable
- Moving a component to a different parent is safe if providers are present
- Missing context fails loudly, not silently

### 10.3 Multi-Select as Universal Pattern

Any component that renders a list of actionable items supports multi-select:

- **Entry:** Toggle button or keyboard shortcut enters select mode
- **Selection:** Checkboxes appear per item. Click toggles. Shift+click range selects.
- **Context actions:** Right-click on a selected item -> actions apply to all selected. Right-click on an unselected item -> actions apply to that item only.
- **Bulk actions:** Selection bar appears with applicable bulk actions.
- **Exit:** Cancel button, Escape key, or all items deselected.

Components that support multi-select: Navigator entity lists, CardListView, TranscriptView message list, Tags list, Related Entities list.

### 10.4 Tabbed Navigator (Left Panel)

The navigator has tabs along the top, each showing a different entity type:

| Tab | Contents | Filter/Sort |
|---|---|---|
| **Sessions** | Folder tree + session cards. Active/Stopped sections. | Platform, status, tags, date range with duration mode, text, unaffiliated, sort by activity/created/name |
| **Briefs** | Folder tree + brief cards. | Text, date range, tags, sort by created/name |
| **Teams** | Team cards with member counts and status. | Status, text |
| **Projects** | Project cards with branch status and session counts. | Status, text |

Each tab maintains its own filter and sort state independently. Filter controls carry forward UCI's proven FilterBar patterns: pills for active filters, date range picker with duration mode, text search with debounce.

### 10.5 Grid View

The workspace center supports grid layouts:

| Layout | Cells | Description |
|---|---|---|
| **1x1** | 1 | Default. Single session pane. |
| **2x1** | 2 | Two panes side by side (vertical split). |
| **1x2** | 2 | Two panes stacked (horizontal split). |
| **2x2** | 4 | Four panes in a grid. |

Each cell has its own tab and can display a different session. Focus (which cell receives keystrokes and prompt staging) is indicated by a bright border. Cmd+1-4 switches focus by position.

### 10.6 Related Entities (Bottom Panel, replaces Workers)

Shows entities related to the focused session:

| Section | Contents |
|---|---|
| **Children** | Sessions spawned by this session |
| **Parent** | Session that spawned this one (if any) |
| **Linked Sessions** | Sessions connected via entity_relationships |
| **Linked Briefs** | Briefs created from or loaded into this session |
| **Team Members** | If this session belongs to a team, show other team members |

Each entity is shown as a compact card. Click to open in a tab. Context menu for actions.

### 10.7 System Monitor (Bottom Panel)

Dashboard drawer with top-level metrics visible on the drawer bar even when the panel is closed:

**Drawer bar (always visible):** `CPU: 45% | Mem: 2.1GB | Sessions: 8 active | Errors: 0`

**Expanded panel:** Charts/graphs for CPU, memory, and per-session resource usage. Active session count over time. Error log with severity. Warnings (high context usage, stalled sessions, disk space).

### 10.8 Runtime-Configurable Card Display

Users can choose which fields appear on cards during runtime:

```typescript
interface CardDisplayConfig {
  fields: CardFieldRef[];          // References to registered card fields
  show_badges: boolean;
  show_platform_bar: boolean;
  compact_mode: boolean;
}

interface CardFieldRef {
  id: string;                      // Registered field ID
  label: string;                   // Display label
  type: string;                    // Data type for formatting
  source: 'sqlite' | 'runtime' | 'derived';
  cost: 'free' | 'moderate' | 'expensive';
  private: boolean;                // Whether field contains sensitive data
}
```

Configurable per entity type (Session cards, Brief cards, etc.) via a settings dialog or context menu. Only registered fields from the card field registry are allowed.

---

## 11. Focus and Prompt Target Model

### 11.1 Focus Hierarchy

Six related but distinct focus concepts:

| Concept | What it means | How it changes |
|---|---|---|
| **Active workspace tab/group** | Which tab group is foregrounded | Clicking tab, Cmd+1-4 for grid cells |
| **Active grid cell** | Which cell in the grid has visual focus border | Cmd+1-4, clicking in a cell |
| **Focused session pane** | Which SessionPane receives keyboard events | Follows active grid cell |
| **Prompt target session** | Which session receives staged prompts from PromptBox | Follows focused session pane by default; can be pinned |
| **Terminal keyboard focus** | Which terminal instance receives raw keystrokes | Follows focused session pane when in terminal mode |
| **Navigator selection** | Which entity is highlighted in the navigator | Clicking an entity card; independent of workspace focus |

### 11.2 Focus Rules

1. Clicking a grid cell sets: active grid cell, focused session pane, prompt target (if not pinned), terminal keyboard focus
2. Clicking a tab: activates the tab group, sets active grid cell to the tab's cell, cascades per rule 1
3. Clicking a navigator entity: sets navigator selection only. Does NOT change workspace focus.
4. Double-clicking a navigator entity: opens in workspace (sets active tab), then cascades per rule 2
5. Prompt target can be pinned to a specific session: `PromptBox.set("target_pinned", true)`. When pinned, workspace focus changes do not update the prompt target.
6. When grid layout changes (e.g., 1x1 to 2x2), focus stays on the cell containing the previously focused session.

### 11.3 Focus Indicators

| Focus Type | Visual Indicator |
|---|---|
| Active grid cell | Bright border (accent-blue) |
| Prompt target | PromptBox header shows target session name + platform badge |
| Navigator selection | Highlighted row background |
| Terminal keyboard focus | Cursor blink in terminal |

---

## 12. Visual System

### 12.1 Design Tokens in Config

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

At app startup, this config generates `:root` CSS custom properties. Components reference tokens only (`var(--bg-card)`), never raw values. Token overrides in app_state.json enable runtime theming. A JSON schema validates the token config. Generated TypeScript token names prevent typos. Dev builds enforce no raw colors/magic spacing in component CSS via lint rules.

### 12.2 Component CSS Strategy

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

Each component CSS file uses only design tokens. No raw color values, no magic numbers. This is enforced by lint/review script.

---

## 13. Session Identity

### 13.1 Current Spec (v5.3)

Format: `{YYYYMMDD}_{HHMMSS}_{uuid8}_{platform3}`

Example: `20260420_145848_cb5a742f_cla`

- Timestamp in local time for human readability (Tracking ID display convention)
- uuid8 for uniqueness
- platform3: `cla` (Claude), `cod` (Codex), `gem` (Gemini)
- Regex validation: `\d{8}_\d{6}_[a-f0-9]{8}_(cla|cod|gem)`

All internal timestamps (created_at, events, logs) stored in UTC. Display layer converts to local time.

Generated by CLI wrappers via `ai_launcher.py`.

### 13.2 Draft TrackingId Extension

The app can create draft TrackingIds before a session launches:

1. App generates ID using same format (timestamp + uuid8 + platform)
2. App pre-populates all context-known fields: display_name, project_dir, roles, tags, relationships
3. Writes to session_store with `identity_status: draft`
4. Passes TrackingId to `ai_launcher.py` via `--tracking-id` flag
5. Launcher reads pre-populated context from store via `--tracking-id` (no need for extensive CLI args)
6. Launcher matches ID, completes identity fields (cli_session_id, terminal_session_name), updates status to `confirmed`
7. App reflects the confirmed state on next store change event

This enables:
- Session placeholders in the UI before launch completes
- Pre-assigned identity for team launches (all members get IDs simultaneously)
- Project-scoped session creation (link to project at draft time)
- Simplified launcher interface (reads from store instead of many CLI args)

#### Draft Lifecycle Rules

- **Who may create drafts:** App main process, scripts using session_store.py API
- **Idempotency:** Repeated launch attempts with same tracking ID are idempotent
- **Pending timeout:** Drafts in `pending` state for longer than 5 minutes transition to `orphaned`
- **Failed status:** If launcher reports error, draft transitions to `failed` with error details
- **Existing confirmed ID:** Launcher called with an already-confirmed ID is a no-op (logs warning)
- **UUID mismatch:** If wrapper discovers a different CLI UUID than expected, it updates the record and logs the discrepancy
- **Cleanup:** Orphaned and failed drafts are cleaned up after 24 hours (configurable)
- **Partial session dirs:** Repair/removal runs during startup reconciliation

---

## 14. Terminal Substrate

### 14.1 Substrate Abstraction

Carried forward from UCI. All terminal operations go through `SessionSubstrate`:

```python
class SessionSubstrate(ABC):
    def create_session(self, name, command, cwd, log_file) -> str: ...
    def session_exists(self, name) -> bool: ...
    def session_is_running(self, name) -> bool: ...
    def kill_session(self, name) -> None: ...
    def list_sessions(self) -> list: ...
    def send_keys(self, name, keys) -> None: ...
    def dump_screen(self, name, path=None) -> str: ...
    def get_current_session_name(self) -> str | None: ...
    def attach(self, name) -> None: ...
```

Current implementation: `TmuxSubstrate` in `lib_session_substrate.py`.

**TypeScript boundary:** The Electron main process calls substrate operations via a TypeScript service that shells out to the Python substrate library. Error shapes, timeouts (default 5s per operation), and concurrency behavior (serialized per-session, parallelized across sessions) are defined at this boundary.

### 14.2 Platform Adapter

Pure function: `(platform, screen_text) -> structured_state`

```typescript
interface ParsedScreenState {
  activity_state: RuntimeState;
  context_percent: number | null;
  permission_prompt: boolean;
  thinking_indicator: boolean;
  error_state: boolean;
  confidence: 'high' | 'medium' | 'low' | 'unknown';
}
```

Each platform has its own parser (different TUI layouts, different indicators). The adapter handles the differences — the rest of the app sees uniform `ParsedScreenState`.

#### Parser Requirements

For each platform, define:
- **Fixture screens:** idle, responding, permission_prompt, error, stopped states captured as text fixtures
- **Parser output schema:** validated against the `ParsedScreenState` interface
- **Confidence/unknown behavior:** When parser cannot determine state, it returns `confidence: 'unknown'` and the UI shows a neutral indicator rather than false precision
- **Throttling cadence:** Screen parsing runs at most every 500ms per session (configurable)
- **Fallback:** When parser fails after CLI UI changes, session falls back to `unknown` state with a warning in app log. Parser fixtures are updated as part of CLI platform upgrade process.

---

## 15. URI Protocol Scheme

### 15.1 `uai://` Deep Links

Custom Electron protocol handler for deep links into the application:

```
uai://session/<trackingId|uuid|terminalName>
uai://brief/<name>
uai://project/<id>
uai://team/<id>
```

#### Action Paths

Deep links support action paths for specific views:

```
uai://session/20260420_145848_cb5a742f_cla/transcript?line=42
uai://session/20260420_145848_cb5a742f_cla/details
uai://brief/pixel_ux_uci_app/content
uai://project/uai-resurrection/sessions
```

#### Resolution Order for Session Links

When a session link is provided, resolution tries in order:
1. TrackingId (exact match)
2. CLI Session UUID (exact match)
3. Terminal session name (exact match, returns most recent if multiple)

If no match is found, the app shows a "session not found" message with the attempted identifier.

#### Registration

The `uai://` protocol is registered during Electron app startup via `protocol.registerSchemesAsPrivileged`. External tools (scripts, CLI wrappers, MCP servers) can open deep links via `open uai://...` on macOS.

---

## 16. Observability and Logging

### 16.1 Log Schema

All logs use a consistent JSON structure:

```typescript
interface LogEntry {
  timestamp: string;               // UTC ISO
  level: 'debug' | 'info' | 'warn' | 'error';
  category: LogCategory;
  sessionId?: string;              // If session-scoped
  commandId?: string;              // If command-related
  messageId?: string;              // If comms-related
  message: string;
  data?: Record<string, any>;
}

type LogCategory =
  | 'command'        // Command execution
  | 'notification'   // Notification delivery
  | 'comms'          // AI-to-AI communication
  | 'store'          // Store mutations and sync
  | 'substrate'      // Terminal operations
  | 'parser'         // Screen parsing
  | 'access'         // Access control decisions
  | 'lifecycle'      // App/session lifecycle
  | 'error';         // Errors and exceptions
```

### 16.2 Log Destinations

| Log | Contents | Storage | Retention |
|---|---|---|---|
| **Command log** | Every command executed with result summary | SQLite (app_logs table) | 30 days |
| **Notification log** | Notification delivery lifecycle | SQLite (app_logs table) | 30 days |
| **Session activity log** | Per-session state changes, comms, errors | SQLite (app_logs table) | 30 days |
| **App log** | Application-wide events, warnings, errors | Rotating file log | 7 days |
| **Access log** | Access control decisions (allowed/denied) | SQLite (app_logs table) | 30 days |

### 16.3 Debug Inspection

The debug command family enables live inspection:

- `debug.inspect(componentPath)`: Returns component state and description
- `debug.validate_stores()`: Runs reconciliation checks, reports discrepancies
- `debug.repair_indexes()`: Fixes known inconsistencies (missing folder entries, orphaned relationships)
- `debug.dump_state()`: Exports full renderer state snapshot for diagnosis

All debug operations are logged. Debug mode auto-expires after configured duration.

---

## 17. Performance and Backpressure

### 17.1 High-Frequency Data Sources

| Source | Strategy |
|---|---|
| Statusline telemetry | Throttle to max 2 updates/second per session. Coalesce intermediate values. |
| Screen parsing | Max every 500ms per session. Skip if previous parse still pending. |
| Signal file watches | Debounce to 200ms. Coalesce multiple touches into one refresh. |
| Store change events | Coalesce rapid events into batched refresh. Max one render cycle per 16ms (60fps). |

### 17.2 Many-Session Scaling

- Screen parsing: Only parse visible/focused sessions at full cadence. Background sessions parse at reduced rate (every 5s).
- Event storms: If more than 50 store change events arrive within 1 second, switch to full-refresh mode instead of incremental updates.
- Transcript loading: Load transcript chunks on demand (virtual scrolling). Never load full JSONL into memory.
- Session list rendering: Virtual list with windowed rendering for navigator entity lists.

### 17.3 JSONL Parsing

Transcript-derived metrics (exchange count, prompt history) are computed on demand when opening session detail. Cached values are non-authoritative and invalidated by transcript file mtime/hash.

---

## 18. Quality Gates

### 18.1 Gate Hierarchy

Quality gates are falsifiable checklists with attestation artifacts:

| Gate | What Must Pass | Attestation |
|---|---|---|
| **Unit tests** | Component API contract tests, command schema tests, parser fixture tests | Test runner output |
| **Contract tests** | describe() schema compliance, command access-control matrix, event subscription granularity | Contract test suite output |
| **Integration tests** | Cross-component workflows, store reconciliation after partial saga, comms request/response/timeout | Integration test suite output |
| **Store tests** | External SQLite write signal -> renderer refresh, folders/app_state atomic mutation, startup reconciliation | Store test suite output |
| **Packaged app smoke** | App launches from packaged build, loads real sessions, opens terminal, stages prompt | Smoke test script output |
| **E2E terminal fixture** | Tests create fake/live terminal sessions, verify parse -> state -> UI pipeline | E2E test output |

### 18.2 Contract Test Families

Required test families for each component:

1. **describe() schema:** Output validates against ComponentDescription JSON Schema
2. **Command schema:** Every command validates input against declared parameter schema
3. **Access control matrix:** Test that each origin/capability combination is correctly allowed/denied
4. **Event subscription:** Test that state changes emit correct events at correct granularity
5. **Store reconciliation:** Simulate crash between saga steps, verify startup repair
6. **Parser fixtures:** Every platform parser tested against fixture screens for all states

### 18.3 Packaged Build Testing

Every deploy must be tested as a packaged Electron app, not just the dev server. Known infrastructure gaps from UCI v1: missing preload bundles, empty HOME env, FileLoader regex issues, window.api undefined in packaged build. Smoke test must verify:

- App launches without crash
- Session list populates from real SQLite data
- Terminal opens and connects to live tmux session
- Prompt staging works end-to-end
- Store change events flow correctly (create a session externally, verify it appears)

---

## 19. Security and Safety Model

### 19.1 Embedded AI Boundary

The embedded AI operates within defined boundaries:

- **Read boundary:** Can read component state, session metadata, and transcript content within capability grants. Thinking blocks and private notes require explicit permission.
- **Write boundary:** Can execute commands within capability grants. Destructive commands require confirmation. Cannot directly write to filesystem or execute shell commands outside the app.
- **Rate limiting:** Maximum commands per minute. Configurable per safety level.
- **Loop prevention:** Consecutive failures of the same command type trigger pause.

### 19.2 Shell Command Policy

PromptBox shell mode (`$` prefix) executes commands in the app's process context:

- Commands run with app's user permissions (no elevation)
- Destructive commands (rm, git reset, etc.) require confirmation
- Output is captured and displayed in shell output area
- Commands are logged in the command log
- No raw terminal escape sequence injection

### 19.3 Prompt Injection Considerations

Even in single-user mode, prompt injection risks exist when AI sessions process untrusted content:

- AI-to-AI messages include machine-readable headers that are validated before processing
- Notification content is sanitized before display in UI
- Deep link parameters are validated against expected formats
- Component descriptions are static and cannot be modified by AI actions

### 19.4 External API Safety

The external UI command/query IPC (Unix domain socket) is restricted:

- Same-user restriction via socket permissions
- Request IDs for correlation with 2-second default timeout
- Read-only by default; write commands require debug mode
- All external API calls are logged

---

## 20. Testing Strategy

### 20.1 Component API Testing (Primary)

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

### 20.2 Command Testing

Test that commands produce correct state changes:

```typescript
// Setup
const session = sessionStore.get("some_tracking_id");

// Execute
const result = await commandBus.execute({
  id: crypto.randomUUID(),
  type: "session.update",
  payload: { tracking_id: "some_tracking_id", patch: { notes: "test" } },
  origin: "user",
  timestamp: new Date().toISOString()
});

// Assert
expect(result.ok).toBe(true);
expect(result.commandId).toBeDefined();
expect(sessionStore.get("some_tracking_id")?.notes).toBe("test");
```

### 20.3 Integration Testing

Test cross-component workflows:

```typescript
// Open a session tab -> verify navigator highlights it
await commandBus.execute({
  id: crypto.randomUUID(),
  type: "workspace.tabs.open",
  payload: { tracking_id: id },
  origin: "user",
  timestamp: new Date().toISOString()
});
expect(navigator.get("selected_ids")).toContain(`session:${id}`);
```

### 20.4 E2E Terminal Fixture Strategy

Tests create controlled terminal environments:

- **Fake substrate:** Mock `SessionSubstrate` with scripted screen output for deterministic testing
- **Live substrate:** Integration tests against real tmux sessions in CI (headless, short-lived)
- **Fixture library:** Captured screen dumps per platform per state, versioned alongside parser code
- **Regression detection:** New CLI platform versions trigger fixture regeneration and parser verification

---

## 21. Migration Plan

### 21.1 What Carries Forward from UCI

| Component | Action | Notes |
|---|---|---|
| Electron main process | Refactor | SessionManager, IPC handlers, folder management adapt to new architecture |
| session_store.py (SQLite) | Keep | Add new tables (tags, projects, teams, app_logs). Schema migration. |
| ai_launcher.py | Refactor | Add --tracking-id flag. Launcher reads pre-populated context from store. |
| lib_session_substrate.py | Keep | TmuxSubstrate works. |
| read_jsonl.py | Keep | Transcript parsing. |
| xterm.js + node-pty | Keep | Terminal embedding proven. |
| Session/Brief card visual design | Adapt | Extract CSS, apply design tokens. |
| TranscriptViewer rendering | Adapt | Extract from monolith, implement TranscriptView API. |
| Platform detection, time utils | Keep | Shared utilities. |
| FilterBar patterns | Carry forward | Pills, date range with duration mode, text search, sort controls. |
| 222 unit tests | Adapt | Rewrite against component APIs. |

### 21.2 What's Rewritten

| Component | Reason |
|---|---|
| App.tsx (1700 lines) | God component. Replaced by component API + command bus. |
| FocusPane.tsx (700 lines) | Mixed state/rendering/menus. Decomposed into Workspace components. |
| FilterBar.tsx | Replaced by NavigatorToolbar with per-tab filter/sort state (patterns carry forward). |
| CardListView.tsx | Replaced by EntityList with universal multi-select and configurable display. |
| NavigationPanel.tsx | Replaced by SessionNavigator with tabbed entity types. |
| styles.css (6000 lines) | Broken into component CSS modules with design tokens. |
| State management (useState hooks) | Replaced by component stores with event subscriptions. |

### 21.3 Existing Data Migration

Explicit migration plan for UCI data:

| Data | Migration Path |
|---|---|
| Existing SQLite schema | Forward migration via session_store.py. Add new tables, preserve existing data. Backup before migration. |
| Existing app_state.json | Schema version bump. Migrate to new field structure. Preserve user preferences. |
| Existing folders.json | Add schema_version, revision, convert roots format. Validate tree integrity. |
| Legacy session IDs | Map to new format where possible. Legacy sessions marked with metadata flag. |
| Existing briefs | Index into SQLite brief metadata table. Compute content_hash. |
| sessionInfo.json files | Read existing data, index relevant fields. Transition to sessionInfo.{uuid8}.json naming. |
| UCI app package/user data paths | Document old and new paths. Support both during transition. |

Rollback: Each migration step creates a backup. UCI and UAI can run side-by-side during resurrection by using separate app_state and folders files.

### 21.4 Build Order

#### Phase 0A — Contract Freeze

Deliverable: docs + schemas + tests only.

- Identity contract aligned with v5.3 (platform codes, timestamp semantics, three-store split)
- Store synchronization contract (signal files, revisions, change events, refresh rules)
- Command schema/result shape (CommandResult with commandId, structured error, changed slices, snapshots)
- Component description schema (JSON Schema for parameters, safety levels, side effects)
- Notification/feedback request schema (messageId, inReplyTo, delivery lifecycle)
- Entity ref/relationship schema (namespaced IDs, metadata_json, relationship types)
- Focus/prompt target model
- Project schema design (indexing strategy, schema version)

#### Phase 0B — Vertical Slice Spike

Deliverable: packaged app proves architecture.

- Bootstrap snapshot from stores (SQLite + folders.json + app_state.json)
- Render sessions list through component API with describe()
- Draft session creation -> launcher -> confirmed identity
- Open session in workspace with terminal
- Safe staged prompt delivery
- Store change event refresh (external SQLite write -> signal -> renderer update)
- Packaged app smoke test (real sessions, real tmux)

#### Phase 1A — Core Stores and Commands

- SessionStore adapter (SQLite + sessionInfo reader + runtime state)
- FolderStore / AppState store with revision tracking
- Command bus with schemas, access control, logging
- Two-channel event system (onStoreChanged, onRuntimeChanged)

#### Phase 1B — Core UI

- Navigator sessions/briefs with filter toolbar
- Workspace tabs/grid with focus model
- SessionPane terminal/transcript mode switching
- PromptBox with safe delivery (target tracking, busy-state queue, provenance logging)

#### Phase 1C — Organization Entities

- Folders CRUD with tree validation
- Tags CRUD with namespaced card IDs
- Entity relationships with metadata
- Brief registry integration (SQLite index + YAML content)
- Related entities panel

#### Phase 1D — Observability and Quality Gates

- App log, command log, notification log
- System monitor drawer
- Packaged app test harness
- Acceptance attestation scripts
- Parser fixture library

#### Phase 2 — Projects, Teams, and AI Comms

- Project entity UI (schema designed in Phase 0A)
- Team definitions and membership
- Notification bus with full delivery lifecycle
- AI feedback timeout with durable FeedbackRequest records
- Embedded AI with restricted permissions and safety classification
- Comms request/response protocol with message IDs and threading
- `uai://` protocol handler

#### Phase 3 — Extended Features

- WebUI as Session
- Advanced team orchestration
- Session playback / time travel
- Plugin/extension architecture

---

## Appendix A: Types Reference

```typescript
// -- Identity --
type TrackingId = string;
type Platform = 'claude_cli' | 'codex_cli' | 'gemini_cli';
type PlatformCode = 'cla' | 'cod' | 'gem';
type IdentityStatus = 'draft' | 'pending' | 'confirmed' | 'failed' | 'orphaned';

// -- State Axes --
type TerminalState = 'unknown' | 'connected' | 'disconnected' | 'killed';
type RuntimeState = 'unknown' | 'running' | 'idle' | 'responding' | 'blocked' | 'permission_prompt' | 'error' | 'stopped';
type ArchiveState = 'active' | 'archived';

// -- Entity --
type EntityType = 'session' | 'brief' | 'project' | 'team' | 'tag' | 'folder';
type EntityId = `${EntityType}:${string}`;
type CardId = `session:${string}` | `brief:${string}`;

interface EntityRef {
  type: EntityType;
  id: string;
  ref: EntityId;
}

// -- UI --
type NavigatorTab = 'sessions' | 'briefs' | 'teams' | 'projects';
type ContextTab = 'details' | 'digests' | 'docs' | 'messages' | 'prompts';
type BottomTab = 'related' | 'logs' | 'app_log' | 'monitor';
type PaneMode = 'terminal' | 'transcript';
type PromptMode = 'prompt' | 'command' | 'shell';
type GridLayout = 'single' | 'vertical_2' | 'horizontal_2' | 'grid_2x2';
type SortField = 'activity' | 'created' | 'name';
type SortDirection = 'asc' | 'desc';

// -- Command --
type CommandOrigin = 'user' | 'internal' | 'external-api' | 'embedded-ai' | 'debug';
type CommandAccess = 'public' | 'internal' | 'debug';
type CommandSafety = 'safe' | 'destructive' | 'requires_confirmation';
type FeedbackMechanism = 'none' | 'message' | 'prompt';

// -- Store --
type StoreSlice = 'sessions' | 'folders' | 'appState' | 'briefs' | 'groups';
type RuntimeSlice = 'terminalState' | 'runtimeState' | 'statusline';

// -- Notification --
type DeliveryStatus = 'queued' | 'delivering' | 'delivered' | 'acknowledged' | 'failed' | 'expired' | 'cancelled';

// -- Capabilities --
type Capability =
  | 'sessions:read'
  | 'sessions:write'
  | 'terminal:send'
  | 'terminal:read'
  | 'files:read'
  | 'files:write'
  | 'app:configure'
  | 'app:debug'
  | 'comms:send'
  | 'comms:receive';

// -- Command Interfaces --
interface Command {
  id: string;
  type: string;
  payload: Record<string, any>;
  origin: CommandOrigin;
  actor?: ActorRef;
  parentId?: string;
  correlationId?: string;
  idempotencyKey?: string;
  timestamp: string;
  dryRun?: boolean;
}

interface CommandResult<T = unknown> {
  ok: boolean;
  commandId: string;
  data?: T;
  error?: CommandError;
  changed?: Partial<Record<StoreSlice, boolean>>;
  snapshots?: Partial<Record<StoreSlice, unknown>>;
  effects?: EffectRecord[];
  undo?: UndoDescriptor;
}

interface CommandError {
  code: string;
  message: string;
  details?: unknown;
  retryable?: boolean;
}

interface EffectRecord {
  type: string;
  target?: string;
  timestamp: string;
}

interface UndoDescriptor {
  commandId: string;
  undoable: boolean;
  description: string;
  reverseCommand?: Command;
  expiresAt?: string;
}

interface ActorRef {
  type: 'user' | 'embedded-ai' | 'external-client' | 'system';
  sessionId?: string;
  clientId?: string;
}

// -- Store Events --
interface StoreChangedEvent {
  eventId: string;
  sequence: number;
  commandId?: string;
  changed: StoreSlice[];
  source: 'command' | 'external' | 'poll';
  revisions?: Partial<Record<StoreSlice, number>>;
  snapshots?: Partial<Record<StoreSlice, unknown>>;
}

interface RuntimeChangedEvent {
  changed: RuntimeSlice[];
  sessionId?: string;
  data?: {
    terminalState?: TerminalStateSnapshot;
    runtimeState?: RuntimeStateSnapshot;
    statusline?: StatuslineSnapshot;
  };
}

// -- Notification --
interface Notification {
  id: string;
  type: string;
  source: EntityRef;
  data: Record<string, any>;
  urgency: 'info' | 'attention' | 'critical';
  targets?: EntityId[];
  messageId: string;
  inReplyTo?: string;
  dedupeKey?: string;
}

interface NotificationRecord {
  id: string;
  correlationId?: string;
  replyTo?: string;
  messageId: string;
  source: EntityRef;
  target: EntityRef;
  type: string;
  urgency: 'info' | 'attention' | 'critical';
  mechanismRequested: FeedbackMechanism;
  mechanismActual?: FeedbackMechanism;
  status: DeliveryStatus;
  createdAt: string;
  expiresAt?: string;
  deliveredAt?: string;
  acknowledgedAt?: string;
  retryCount: number;
  maxRetries: number;
  failureReason?: string;
  dedupeKey?: string;
  ackRequired: boolean;
  contentRef?: string;
  responseRef?: string;
}

// -- Comms --
interface CommsRequest {
  messageId: string;
  inReplyTo?: string;
  from: TrackingId;
  to: TrackingId;
  type: string;
  feedbackMechanism: FeedbackMechanism;
  content: string;
  structuredData?: Record<string, any>;
  dueAt?: string;
  timeoutAction: 'retry' | 'proceed' | 'escalate';
  priority: 'low' | 'normal' | 'high';
}

interface CommsResponse {
  messageId: string;
  inReplyTo: string;
  from: TrackingId;
  to: TrackingId;
  content: string;
  structuredData?: Record<string, any>;
}

// -- UI Data --
interface DateRange {
  from?: string;   // YYYY-MM-DD or ISO
  to?: string;
  durationMode?: boolean;  // UCI carry-forward: interpret as "last N days"
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

interface LogEntry {
  timestamp: string;
  level: 'debug' | 'info' | 'warn' | 'error';
  category: string;
  sessionId?: string;
  commandId?: string;
  messageId?: string;
  message: string;
  data?: Record<string, any>;
}

// -- Component Description --
interface ComponentDescription {
  schemaVersion: number;
  id: string;
  path: string;
  instanceId?: string;
  name: string;
  description: string;
  parent: string | null;
  children: string[];
  state: Record<string, StateDescriptor>;
  commands: Record<string, CommandDescriptor>;
  actions: Record<string, ActionDescriptor>;
  context: Record<string, ContextRequirement>;
  events: { emits: string[]; subscribes: string[] };
  deprecated?: { since: string; replacement?: string; message?: string };
}

interface StateDescriptor {
  type: Record<string, any>;       // JSON Schema
  description: string;
  readable: boolean;
  writable: boolean;
  enumValues?: any[];
  defaultValue?: any;
  examples?: any[];
}

interface CommandDescriptor {
  description: string;
  parameters: Record<string, any>; // JSON Schema
  returns: Record<string, any>;    // JSON Schema
  access: CommandAccess;
  safety: CommandSafety;
  sideEffects: string[];
  affectedStores: StoreSlice[];
  preconditions?: string[];
  postconditions?: string[];
  idempotent: boolean;
  async: boolean;
  latencyHint?: 'fast' | 'moderate' | 'slow';
  errorCodes?: string[];
}

interface ActionDescriptor {
  description: string;
  trigger: string;
  context: string;
}

interface ContextRequirement {
  type: Record<string, any>;       // JSON Schema
  required: boolean;
  provider: string;
}

// -- Card Display --
interface CardDisplayConfig {
  fields: CardFieldRef[];
  show_badges: boolean;
  show_platform_bar: boolean;
  compact_mode: boolean;
}

interface CardFieldRef {
  id: string;
  label: string;
  type: string;
  source: 'sqlite' | 'runtime' | 'derived';
  cost: 'free' | 'moderate' | 'expensive';
  private: boolean;
}

// -- Parsed Screen --
interface ParsedScreenState {
  activity_state: RuntimeState;
  context_percent: number | null;
  permission_prompt: boolean;
  thinking_indicator: boolean;
  error_state: boolean;
  confidence: 'high' | 'medium' | 'low' | 'unknown';
}

// -- Folder Store --
interface FolderStore {
  schema_version: number;
  revision: number;
  roots: { sessions: string; briefs: string };
  folders: Record<string, Folder>;
}

interface Folder {
  id: string;
  name: string;
  icon?: string;
  color?: string;
  builtin: boolean;
  subfolders: string[];
  cards: CardId[];
}
```

---

## Appendix B: Cross-References

| Document | Relationship |
|---|---|
| gap_analysis.md | Input -- maps archived spec -> UCI reality -> requirements |
| codex_architecture_review_v1.md | Review -- all findings addressed in this revision |
| uci_data_architecture.md | Reference -- store sync protocol, command result shape, conceptual model imported |
| DESIGN.md | Project identity and principles (subset of this spec) |
| spec_session_identity v5.3 | Session identity format and lifecycle -- this spec aligns with v5.3 |
| component_api_contracts.md (archived) | Predecessor to Section 5 |
| 2026-03-30-frontend-design-v2.md (archived) | Predecessor to Sections 10-12 |
| lessons-learned.md | Process constraints informing Sections 18-20 |

---

## Appendix C: Codex Review Finding Disposition

| Finding | Disposition | Section |
|---|---|---|
| F01 (Critical) Session Identity | Fixed: aligned with v5.3, `cod` not `cdx`, UTC storage, three-store split | 2.1, 13 |
| F02 (Critical) Store Sync | Fixed: imported two-channel model, signal contract, refresh rules | 4 |
| F03 (Critical) Renderer/Main/Store Authority | Fixed: dovetailed path model, explicit authority boundaries | 1 (Principle 5), 5.1 |
| F04 (Major) Namespaced Entity IDs | Fixed: EntityId type, CardId, EntityRef with ref field | 2.1 |
| F05 (Major) ComponentDescription | Fixed: JSON Schema, safety, side effects, preconditions, versioning | 5.2 |
| F06 (Major) Command Shape | Fixed: id, correlationId, idempotencyKey, structured error, changed slices, snapshots, undo | 6.1 |
| F07 (Major) Access Control | Fixed: capabilities/scopes, safety classification, actor identity, privacy | 6.4 |
| F08 (Major) Notification Lifecycle | Fixed: durable NotificationRecord with delivery status, retry, dedupe | 7.2 |
| F09 (Critical) AI Comms | Fixed: structured request/response, messageId/inReplyTo, no rerouting | 9.3 |
| F10 (Major) Hook Platform Capabilities | Fixed: precise capability matrix | 8.2 |
| F11 (Major) Parent-Chain Context | Fixed: explicit ActionContextProvider | 10.2 |
| F12 (Major) Testing | Fixed: quality gates, contract test families, E2E fixtures | 18, 20 |
| F13 (Major) Migration | Fixed: dependency-ordered phases 0A/0B/1A/1B/1C/1D, data migration | 21 |
| F14 (Major) Observability | Added: Section 16 | 16 |
| F15 (Major) Performance | Added: Section 17 | 17 |
| F16 (Major) Security/Safety | Added: Section 19 | 19 |
