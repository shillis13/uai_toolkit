# Component API Contracts

**Version:** 1.0
**Date:** 2026-03-30
**Author:** Claude (CLI, UAI Architect)
**Status:** Draft
**Dependencies:** uai_architecture_v0.2.md, 2026-03-30-frontend-design-v2.md

---

## 1. Overview

Each architectural UI component exposes a typed API for state access and mutation. This is production infrastructure — all data changes flow through these APIs. They also serve testing and debugging (state is inspectable without DOM traversal).

### Conventions

- **Keys** are dot-separated paths scoped to the component: `filter.platform`, `tabs.active`
- **Get** returns `T | null` (null if key doesn't exist)
- **Set/Update** throw on type mismatch
- **Delete** returns `boolean` (true if removed, false if not found)
- **List** returns typed arrays
- **All operations are synchronous** — state is in-memory. Persistence is async (debounced writes to JSON files).

### Component vs Session Store

Components own UI state. Session data lives in the **Session Store** (single source of truth). Components hold `tracking_id` references and look up session data via the store. The Component API never returns raw session objects — it returns references that the caller resolves against the Session Store.

---

## 2. Session Store API

The Session Store is not a UI component — it's the shared data layer that all components reference.

```
SessionStore {
  // Read
  get(tracking_id: TrackingId): Session | null
  list(filter?: SessionFilter): Session[]
  getByCliUuid(uuid: string): Session | null
  getByTerminalSession(name: string): Session | null
  getChildren(tracking_id: TrackingId): Session[]
  getAncestors(tracking_id: TrackingId): Session[]

  // Write (wrappers own identity fields; app owns UI fields)
  updateRuntime(tracking_id: TrackingId, patch: RuntimePatch): void
  updateAppState(tracking_id: TrackingId, patch: AppStatePatch): void

  // Lifecycle
  reload(): void                    // Re-merge from all three stores
  onSessionChanged(cb): Unsubscribe // Notify when any session changes
}
```

**Types referenced:**
```
TrackingId = string  // e.g., "claude_20260330_061500"

SessionFilter = {
  platform?: Platform[]
  status?: SessionStatus[]
  type?: SessionType[]
  role?: string[]
  text?: string                    // display_name substring match
  parent?: TrackingId | "none"     // "none" = unaffiliated
}

RuntimePatch = Partial<{
  status: SessionStatus
  activity_state: ActivityState
  context_percent: number
  terminal_session_id: string
}>

AppStatePatch = Partial<{
  type: SessionType
  pinned: boolean
  exchange_count: number
  display_name: string
}>
```

---

## 3. SessionNavigator API

Owns: filter/group/sort state, navigator group structure, group membership highlights.

```
SessionNavigator {
  // Filter
  get("filter"): FilterConfig
  get("filter.platform"): Platform[]
  get("filter.status"): SessionStatus[]
  get("filter.type"): SessionType[]
  get("filter.role"): string[]
  get("filter.text"): string
  set("filter", value: FilterConfig): void
  update("filter", patch: Partial<FilterConfig>): void

  // Grouping
  get("group_mode"): GroupMode
  set("group_mode", value: GroupMode): void

  // Sorting
  get("sort_mode"): SortMode
  get("sort_direction"): SortDirection
  set("sort_mode", value: SortMode): void
  set("sort_direction", value: SortDirection): void

  // Groups (derived from group_mode + sessions + custom groups)
  list("groups"): NavigatorGroup[]
  get("groups.{id}"): NavigatorGroup | null
  get("groups.{id}.collapsed"): boolean
  set("groups.{id}.collapsed", value: boolean): void

  // Highlights (which groups contain the focused session)
  get("highlighted_groups"): string[]

  // Custom groups (user-created, persisted)
  set("groups.create", value: { name: string }): NavigatorGroup
  update("groups.{id}", patch: { name?: string }): void
  delete("groups.{id}"): boolean
  update("groups.{id}.sessions.add", value: TrackingId): void
  update("groups.{id}.sessions.remove", value: TrackingId): void

  // Computed
  list("visible_sessions"): TrackingId[]  // After filter/group/sort applied
}
```

**Types:**
```
FilterConfig = {
  platform: Platform[]
  status: SessionStatus[]
  type: SessionType[]
  role: string[]
  text: string
}

GroupMode = "platform" | "role" | "status" | "parent" | "custom" | "none"
SortMode = "last_activity" | "created" | "name" | "exchange_count" | "context_percent"
SortDirection = "asc" | "desc"

NavigatorGroup = {
  id: string
  name: string
  type: "auto_platform" | "auto_role" | "auto_status" | "auto_parent" | "custom"
  session_ids: TrackingId[]
  collapsed: boolean
  children: NavigatorGroup[]
}
```

---

## 4. Workspace API

Owns: tabs, tab groups, active tab.

```
Workspace {
  // Tabs
  list("tabs"): Tab[]
  get("tabs.active"): Tab | null
  get("tabs.{session_id}"): Tab | null
  set("tabs.open", value: TrackingId): Tab           // Open or switch to
  delete("tabs.{session_id}"): boolean                // Close tab
  set("tabs.activate", value: TrackingId): void       // Switch focus

  // Tab Groups
  list("tab_groups"): TabGroup[]
  get("tab_groups.{id}"): TabGroup | null
  set("tab_groups.create", value: { name: string, session_ids: TrackingId[] }): TabGroup
  delete("tab_groups.{id}"): boolean                  // Ungroup
  update("tab_groups.{id}", patch: Partial<TabGroup>): void
  update("tab_groups.{id}.sessions.add", value: TrackingId): void
  update("tab_groups.{id}.sessions.remove", value: TrackingId): void
  update("tab_groups.{id}.layout", value: TabLayout): void
  update("tab_groups.{id}.visible.add", value: TrackingId): void    // Surface hidden tab
  update("tab_groups.{id}.visible.remove", value: TrackingId): void // Hide tab in group

  // Browse mode
  get("browse_mode"): boolean           // True when no tab is active (card grid shown)
  get("browse_group"): string | null    // Navigator group being browsed
}
```

**Types:**
```
Tab = {
  session_id: TrackingId
  active: boolean
  group_id: string | null
  prompt_draft: string
}

TabGroup = {
  id: string
  name: string
  session_ids: TrackingId[]
  visible_ids: TrackingId[]
  layout: TabLayout
  collapsed: boolean
}

TabLayout = "single" | "vertical_2" | "horizontal_2" | "grid_2x2"
```

---

## 5. SessionPane API

Owns: pane mode (terminal/transcript), focus state.

```
SessionPane {
  get("session_id"): TrackingId
  get("mode"): PaneMode
  set("mode", value: PaneMode): void
  get("focused"): boolean
  set("focused", value: boolean): void
}
```

**Types:**
```
PaneMode = "terminal" | "transcript"
```

---

## 6. TranscriptView API

Owns: filter toggles, scroll state, search.

```
TranscriptView {
  get("session_id"): TrackingId
  get("filters"): TranscriptFilters
  update("filters", patch: Partial<TranscriptFilters>): void
  get("scroll_position"): number
  set("scroll_position", value: number): void
  get("auto_follow"): boolean
  set("auto_follow", value: boolean): void
  get("search_query"): string | null
  set("search_query", value: string | null): void
  get("width_percent"): number
  set("width_percent", value: number): void

  // Content (read-only, derived from JSONL)
  list("exchanges"): Exchange[]
  get("exchange_count"): number
}
```

**Types:**
```
TranscriptFilters = {
  user: boolean
  ai: boolean
  tools: boolean
  thinking: boolean
}

Exchange = {
  index: number
  user: MessageBlock
  assistant: MessageBlock
}

MessageBlock = {
  content: string
  timestamp: string
  tool_calls?: ToolCall[]
  thinking?: string
  collapsed: boolean
}

ToolCall = {
  name: string
  input: string
  result: string
  collapsed: boolean
}
```

---

## 7. PromptBox API

Owns: current text, mode, target session, shell output.

```
PromptBox {
  get("text"): string
  set("text", value: string): void
  get("target_session_id"): TrackingId
  set("target_session_id", value: TrackingId): void
  get("mode"): PromptMode
  get("shell_output"): string | null
  get("shell_output_visible"): boolean
  set("shell_output_visible", value: boolean): void
  get("manual_height"): number | null
  set("manual_height", value: number | null): void

  // Actions
  set("stage"): void               // Cmd+Enter: stage text to target pane
  set("execute_shell"): void        // Execute $ command
  set("clear"): void                // Clear text
}
```

**Types:**
```
PromptMode = "prompt" | "command" | "shell"
```

---

## 8. ContextPanel API

Owns: open/closed, active tab, width.

```
ContextPanel {
  get("open"): boolean
  set("open", value: boolean): void
  get("active_tab"): ContextTab
  set("active_tab", value: ContextTab): void
  get("width"): number
  set("width", value: number): void
}
```

**Types:**
```
ContextTab = "details" | "docs" | "memories" | "messages" | "prompts"
```

---

## 9. BottomPanel API

Owns: open/closed, active tab, height, worker scoping.

```
BottomPanel {
  get("open"): boolean
  set("open", value: boolean): void
  get("active_tab"): BottomTab
  set("active_tab", value: BottomTab): void
  get("height"): number
  set("height", value: number): void

  // Workers tab
  get("workers.scoped_to"): TrackingId | null
  set("workers.scoped_to", value: TrackingId | null): void
  get("workers.show_all"): boolean
  set("workers.show_all", value: boolean): void
  get("workers.active_collapsed"): boolean
  set("workers.active_collapsed", value: boolean): void
  get("workers.stopped_collapsed"): boolean
  set("workers.stopped_collapsed", value: boolean): void
  list("workers.active"): TrackingId[]
  list("workers.stopped"): TrackingId[]
}
```

**Types:**
```
BottomTab = "workers" | "logs" | "app_log"
```

---

## 10. Shared Types

```
Platform = "claude_cli" | "codex_cli" | "gemini_cli"
SessionStatus = "running" | "stopped" | "error"
SessionType = "chat" | "worker"
ActivityState = "idle" | "responding" | "blocked" | "permission_prompt" | "error" | "stopped"

Session = {
  // Identity (from sessionInfo.json — wrapper-owned)
  tracking_id: TrackingId
  cli_uuid: string | null
  platform: Platform
  parent_tracking_id: TrackingId | null
  created_at: string              // ISO timestamp
  terminal_session_id: string | null
  display_name: string
  working_dir: string | null
  model: string | null
  roles: string[]

  // App state (from app_state.json — app-owned)
  type: SessionType
  pinned: boolean
  exchange_count: number

  // Runtime (in-memory — app-owned)
  status: SessionStatus
  activity_state: ActivityState
  context_percent: number | null
  last_activity: string           // ISO timestamp
}
```

---

## 11. Event System

Components emit events when state changes. Any consumer can subscribe.

```
EventBus {
  on(event: string, callback: (data: any) => void): Unsubscribe
  emit(event: string, data: any): void
}
```

**Standard events:**

| Event | Data | Emitted by |
|-------|------|------------|
| `session:changed` | `{ tracking_id, fields: string[] }` | SessionStore |
| `session:added` | `{ tracking_id }` | SessionStore |
| `session:removed` | `{ tracking_id }` | SessionStore |
| `tab:opened` | `{ tracking_id }` | Workspace |
| `tab:closed` | `{ tracking_id }` | Workspace |
| `tab:activated` | `{ tracking_id }` | Workspace |
| `navigator:selection` | `{ tracking_id }` | SessionNavigator |
| `navigator:group_selected` | `{ group_id }` | SessionNavigator |
| `prompt:staged` | `{ tracking_id, text }` | PromptBox |
| `panel:toggled` | `{ panel, open }` | ContextPanel / BottomPanel |

---

## 12. Testing Contract

For any component `C`:

```
// State inspection
const state = C.get("some.key")
assert(state === expectedValue)

// State mutation + verification
C.set("some.key", newValue)
assert(C.get("some.key") === newValue)

// Listing
const items = C.list("children")
assert(items.length === expectedCount)

// Event verification
let fired = false
events.on("tab:opened", () => { fired = true })
Workspace.set("tabs.open", someTrackingId)
assert(fired === true)
```

No CSS selectors. No DOM traversal. No `querySelector`. Components are tested through their API contracts.
