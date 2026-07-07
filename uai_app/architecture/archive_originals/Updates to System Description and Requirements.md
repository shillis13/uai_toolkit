# Updates to System Description and Requirements

**Purpose:** Capture additional requirements and architectural refinements not yet reflected in `system_description_v0.1.md` or `requirements_v0.1.md`. These updates incorporate lessons from MVCR-1 and MVCR-2 implementation, the current APP_SPEC, and the architecture decision memo.

**Status:** Draft for curation
**Date:** 2026-03-30

---

## 1. Application Architecture

### 1.1 Component-Based UI Architecture

The application SHALL be composed of architecturally defined UI components arranged in a hierarchy. These architectural components are logical units with defined responsibilities, state, and APIs. They loosely correspond to implementation-level UI components (zellij sessions, iframes, panels, React components) but those are detailed design and implementation concerns encapsulated within the architectural definition.

**Architectural components are distinct from implementation components:**

| Architectural Component | Implementation (current) | Notes |
|---|---|---|
| Session Pane | zellij iframe + TerminalViewer.tsx | Implementation may change |
| Session Navigator | FocusPane.tsx + rail buttons | Redesigned for v0.2 |
| Transcript Viewer | TranscriptViewer.tsx | Structured JSONL parser |
| Prompt Box | textarea in TerminalViewer.tsx | Enhanced for v0.2 |

### 1.2 Component State and Idempotent Rebuilding

Each architectural UI component SHALL have state data that:

1. **May be cache-persisted** for fast startup (currently `session_metadata.json`)
2. **Must be rebuildable idempotently** from authoritative sources — meaning any component's state can be reconstructed from scratch without loss of correctness

This is essential for two reasons:
- **System-level testing:** Tests can verify component state by rebuilding it and comparing against cached state
- **Crash recovery:** If the persisted cache is corrupted or stale, the application reconstructs correct state on next launch

**Authoritative sources for rebuild:**

| Component State | Authoritative Source |
|---|---|
| Session list | `zellij list-sessions` + CLI session files |
| Session metadata | Registry file + zellij session names + JSONL files |
| Transcript content | `~/.claude/projects/<project>/<session-id>.jsonl` |
| Session relationships | Registry `spawned_by` + `CLI_PARENT_PID` env |
| Activity/status | Live `dump-screen` polling |
| Groups (auto) | Derived from session platform/role attributes |
| Groups (manual) | Persisted in app state (not rebuildable — user-created) |

### 1.3 Multiple Independent Instances

The application SHALL permit multiple, independent instances. Instances are non-interfering except to the extent that they impact running sessions (e.g., stopping a session in one instance affects the other).

**Primary use case:** System-level automated tests that run against a test instance without interfering with an operational/production instance.

**Requirements:**
- Each instance SHALL use its own configuration/state directory (or namespaced files)
- Instances SHALL NOT lock shared resources (registry, session metadata) exclusively
- Session operations (start, stop) naturally affect shared state (the running sessions themselves) — this is expected and acceptable
- <!--[CURATE: Should instances share the same session registry file with locking, or use independent registry files that each discover sessions independently? Independent registries are simpler but may show inconsistent state across instances.]-->
  Answer: independent registry files and independent discovery.  Also isolates test data.  Could identify test sessions by naming convention.

### 1.4 Component API Interfaces

Each architectural UI component SHALL provide an API interface supporting:

- **Get** — Retrieve specific data elements or child component state
- **Set** — Initialize or replace data elements
- **Update** — Modify existing data elements
- **Delete** — Remove data elements or child components
- **List children** — Enumerate contained child components

Through these interfaces, the entire application's data and state SHALL be discoverable and inspectable. This extends the existing Debug API (`debug:getState`, `debug:getFullState`) into a formal per-component contract.

**Relationship to existing Debug API:**
The current debug endpoints return a flat snapshot of all state. The component API model provides structured, hierarchical access — each component owns its subtree and exposes it through a consistent interface.

### 1.5 Window Layout

```
Window
  ├── Left Panel (Session Navigator)
  ├── Center Area (Workspace)
  │   ├── Focus Bar (status indicators, action buttons)
  │   ├── Tab Bar (Tabs + Tab Groups)
  │   ├── Center Panel
  │   │   ├── Tab → single Session Pane
  │   │   └── Tab Group → layout of Session Panes
  │   │       └── Grid → Session Panes (split/stack)
  │   └── Prompt Box
  ├── Right Panel (Context Panel)
  └── Bottom Panel (Workers, Activity Log)
```

**Changes from current implementation:**
- **Tab Groups** are new — currently only individual tabs exist. Tab Groups enable split-view layouts (2x vertical, 2x horizontal, 2x2 grid) within a single tab position, as listed in MVCR-3 roadmap.
- **Focus Bar** formalizes the current session toolbar (breadcrumb bar with back button, session name, action buttons, status pill).
- **Grid layout within Tab Groups** is new — enables the split-view feature.

### 1.6 Architectural UI Components

| Component | Location | Responsibility |
|---|---|---|
| **Session Navigator** | Left Panel | Filter, group, sort, browse sessions |
| **Workspace** | Center Area | Tab management, layout, session display |
| **Session Pane** | Within Workspace tabs | Live terminal or transcript for one session |
| **Prompt Box** | Bottom of Center Area | User input, command handling, history |
| **Context Panel** | Right Panel | Session info, docs, memories, messages, prompts |
| **Worker Panel** | Bottom Panel | Child CLI instances and subagent monitoring |
| **Session Activity Log** | Bottom Panel | Per-session action/event history |

### 1.7 Sessions as Primary Entities

Sessions are the primary entities in the application. All UI components ultimately reference, display, or operate on sessions.

**Primary key:** Tracking ID (app-generated, see Section 1.9)

**Session state model:**

| Field | Mutability | Description |
|---|---|---|
| `tracking_id` | Immutable | App-generated primary key (e.g., `claude_20260330_021500`) |
| `ai_platform` | Immutable | claude, codex, gemini |
| `cli_uuid` | Set once | CLI platform's session/conversation UUID (discovered post-launch for Codex/Gemini, pre-assigned for Claude) |
| `ai_model` | Immutable | Model used (e.g., claude-opus-4-6) |
| `display_name` | Mutable | Human-readable name (user or AI editable) |
| `parent_tracking_id` | Immutable | Tracking ID of parent/spawner, if any |
| `terminal_session_id` | Mutable | Maps to zellij session name; may change on resume |
| `messages_file` | Mutable | Path to JSONL file (linkable once `cli_uuid` discovered) |
| `active_pids` | Mutable | Currently active process IDs (normally 1; >1 is an error) |
| `roles` | Mutable | Assigned roles (dev_lead, librarian, etc.) |
| `children_tracking_ids` | Mutable | Tracking IDs of child/spawned sessions |
| `status` | Mutable | running, stopped, error |
| `type` | Mutable | chat, worker (promotable via "Promote to Chat") |
| `created_at` | Immutable | Creation timestamp (also embedded in tracking_id) |
| `last_activity` | Mutable | Last detected activity timestamp |
| `context_percent` | Mutable | Last known context window remaining % |
| `exchange_count` | Mutable | Number of user/assistant exchanges |

**Key changes from v0.1:**
- The v0.1 system description used tmux session name as the session `id`. This update introduces an app-generated Tracking ID as the primary key (see Section 1.9).
- Parent-child relationships use Tracking IDs, which are available immediately at spawn time — no dependency on CLI UUID discovery.
- `cli_uuid` is a "set once" field: `null` at creation for Codex/Gemini sessions, populated when discovery completes, immutable thereafter.

### 1.8 Tech Stack

Current implementation uses:
- **Electron** — Desktop application framework (TypeScript/Node.js main process, React renderer)
- **Zellij** — Terminal multiplexer providing persistent sessions with web client capability

**Open questions for v0.2:**

| Question | Context |
|---|---|
| Electron: stay or switch? | Working well for the use case. Electron is heavy (~200MB) but provides excellent xterm.js integration, CDP debugging, and mature ecosystem. Tauri would be lighter but terminal embedding is less proven. <!--[CURATE: You wrote "Electrum" in the source — I assumed Electron. The architecture memo recommended PySide6+Qt but implementation went Electron. Is there appetite to revisit, or is Electron confirmed for the foreseeable future?]--> |
| Zellij: stay or switch to tmux? | Zellij provides more than needed (layout engine, plugin system) but its web client enables iframe embedding which is core to the current architecture. Switching to tmux would require building a separate terminal rendering solution (xterm.js + custom PTY bridge). <!--[CURATE: The architecture memo leaned tmux, but implementation went zellij specifically for the web client iframe capability. Is this settled, or still open?]--> |

### 1.9 Session Identity Discovery and Tracking

Session identity architecture should be revisited per `spec_session_identity_v3.0.md`.

#### The Discovery Gap Problem

Each CLI platform has its own session/conversation UUID, but availability varies:

| Platform | UUID Availability | Mechanism |
|---|---|---|
| Claude CLI | At launch | Pre-assigned via `--session-id` flag |
| Codex CLI | Post-launch | Discovered from transcript files or scrollback parsing |
| Gemini CLI | Post-launch | Discovered from transcript files or scrollback parsing |

This creates a temporal gap: the app needs a stable primary key the moment a session is created, but for Codex and Gemini, the CLI UUID isn't available until some asynchronous discovery process completes. Building a universal identity model on a capability only one platform has (Claude's `--session-id`) is fragile.

#### Solution: App-Generated Tracking ID

Introduce a wrapper-generated **Tracking ID** as the primary key for all sessions, available from the moment of creation. The CLI wrapper generates the Tracking ID (not the app) — the app reads finished identity from wrapper output. The CLI UUID and terminal session name become linked attributes discovered or assigned after creation.

**Format:** `{platform}_{YYYYMMDD}_{HHMMSS}[_{NNN}]`

Examples:
```
claude_20260330_021500
codex_20260330_021512
gemini_20260330_021512_002   ← rolling index for same-second collision
```

- **Platform prefix** — instant visual identification in logs, filenames, registry, debug output. Short form (`claude`, `codex`, `gemini`) — the `_cli` suffix used in sessionInfo's `platform` field (`claude_cli`, etc.) is the full form.
- **Timestamp** — UTC creation time; human-readable, eyeball creation order without lookups
- **Rolling index `_NNN`** — three-digit, only appended on collision within the same platform+second (e.g., spawning a wave of workers). Allocated atomically via `mkdir` (POSIX atomic). Supports `_002` through `_999`.

**Note:** The CLI wrapper generates the Tracking ID (not the app). See session_identity_v4.2.md for full allocation protocol.

#### Three-ID Identity Model

| ID | When Available | Lifespan | Purpose |
|---|---|---|---|
| **Tracking ID** | At creation (app-generated) | Birth to archive | App primary key, parent-child linking, filenames, logs |
| **CLI UUID** | Discovered post-launch (or pre-assigned for Claude) | Set once, immutable | Cross-reference to CLI platform's data (JSONL files, conversation history) |
| **Terminal Session Name** | At creation (zellij session name) | Mutable — may change on resume, may be reused | Terminal attachment, dump-screen, send-keys |

**Rationale for a 3rd ID rather than using CLI UUID directly:**

1. **Solves the discovery gap** — stable key exists from birth, no placeholder/pending states while waiting for UUID discovery
2. **Platform-agnostic** — same scheme for Claude, Codex, Gemini, and any future CLI platform
3. **Parent-child relationships established immediately** — parent knows child's tracking ID at spawn time without waiting for UUID discovery
4. **Human-readable** — platform and creation time embedded in the ID itself, unlike opaque UUIDs
5. **Self-sorting** — lexicographic ordering matches chronological ordering within platform

**How this differs from what v3 eliminated:** The v3 simplification removed the old registry UUID because it was redundant with the zellij name and was an opaque random value. The Tracking ID serves a different role — it's a **lifecycle-spanning, human-readable, immediately-available** primary key. The zellij name is ephemeral (sessions die, names get reused). The CLI UUID is durable but not immediately available for all platforms. The Tracking ID fills the gap.

**Collision handling:** The CLI wrapper generating the Tracking ID checks the registry — simple, deterministic, no coordination beyond reading the registry. Collisions within the same platform+second are rare (spawning workers in rapid succession) and handled by the rolling index suffix.

#### Key Principles

- The **Tracking ID** is the primary key in the app registry — all internal references (parent-child, worker dock, groups) use it
- The **CLI UUID** is the cross-reference to platform-specific data (JSONL files, `~/.claude/projects/`, etc.) — linked once discovered
- The **Terminal Session Name** is a mutable operational handle — used for `dump-screen`, `send-keys`, iframe attachment, but never as a stable reference

---

## 2. Architectural UI Element Specifications

### 2.1 Left Panel: Session Navigator

**Redesigned from current implementation.** The current left rail uses platform icon buttons with auto-generated groups. This specification replaces that with a more flexible navigator.

#### Layout

```
┌─────────────────────────┐
│ [Filter ▼] [Group ▼] [Sort ▼] │  ← Button bar
├─────────────────────────┤
│ ▼ Group: Claude Sessions  (3) │  ← Collapsible group
│   ● Session: Debug memory...  │
│   ● Session: Architecture...  │
│   ○ Session: Old review       │
│ ▶ Group: Codex Sessions  (1) │  ← Collapsed
│ ▼ Group: Role: dev_lead  (2) │  ← Nested allowed
│   ● Session: Sprint planning  │
│   ● Session: Code review      │
└─────────────────────────┘
```

#### Controls

**Filter bar** — Controls which sessions appear in the navigator. Filters are additive (AND logic).

| Filter Dimension | Options |
|---|---|
| Platform | Claude, Codex, Gemini (multi-select) |
| Status | Running, Stopped, Error (multi-select) |
| Type | Chat, Worker |
| Role | Any assigned role |
| Text | Search display name substring |

**Group control** — Controls how sessions are structured within the navigator.

| Grouping Mode | Behavior |
|---|---|
| By Platform | Groups: Claude Sessions, Codex Sessions, Gemini Sessions |
| By Role | Groups: Role: dev_lead, Role: librarian, Ungrouped |
| By Status | Groups: Active, Stopped, Error |
| By Parent | Groups: Orchestrator chains + Unaffiliated |
| Custom | User-defined groups (sessions can belong to multiple) |
| None | Flat list, no grouping |

**Sort control** — Controls ordering of both groups and sessions within groups.

| Sort Dimension | Direction |
|---|---|
| Last Activity | Newest first (default) |
| Created | Newest first |
| Name | Alphabetical |
| Exchange Count | Most first |
| Context % | Lowest remaining first (critical sessions surface) |

#### Interactions

| Action | Behavior |
|---|---|
| Single-click Group | Select group; toggle expand/collapse |
| Double-click Group | Open the group's content view as a Tab in the Workspace (shows all sessions in group) |
| Single-click Session | Select session (highlight, show details in Context Panel) |
| Double-click Session | Open the session's content view as a Tab in the Workspace |

**Change from current:** Current implementation uses single-click on a session card to open it in a new tab. The new design separates selection (single-click) from opening (double-click), matching standard file-browser conventions. <!--[CURATE: This is a significant interaction change from the current app. Current: single-click opens tab. Proposed: single-click selects, double-click opens. The current behavior is more immediate but the proposed behavior is more standard. Confirm preference.]-->

### 2.2 Center Panel: Workspace

The center area is the **Workspace** — analogous to a web browser's tab area. It contains one or more tabs, and tabs can be individual or grouped.

#### Tab Bar

Extends the current browser-style tab bar with **Tab Groups**.

| Concept | Description |
|---|---|
| **Tab** | A single session pane (live chat or transcript). Current behavior. |
| **Tab Group** | A named collection of tabs displayed together in a split layout. New. |

**Tab Group layouts:**

| Layout | Description |
|---|---|
| 2x Vertical | Two session panes side by side |
| 2x Horizontal | Two session panes stacked |
| 2x2 Grid | Four session panes in a grid |

Tab Groups enable comparing sessions side-by-side or monitoring multiple workers simultaneously — a capability listed in the MVCR-3 roadmap as "Split view."

#### Live Chat Panel (Session Pane — Live Mode)

Supports passing of live keystrokes to the CLI and real-time terminal view. This is the primary interaction surface.

- Full PTY-backed terminal rendering
- Low-latency keystroke transmission
- Color, cursor, and scrollback support
- Keyboard shortcut passthrough (with Cmd-key interception for app shortcuts)
- Link handling (Shift+click to open, Ctrl+click to copy)

This corresponds to the current zellij iframe implementation.

#### Transcript Panel (Session Pane — Transcript Mode)

Shows a formatted, structured view of the session history parsed from the JSONL file.

**Filter controls** (checkboxes at top of panel):

| Filter | Default | Description |
|---|---|---|
| User Messages | On | Show user prompts |
| AI Responses | On | Show assistant responses |
| Tool Usage | On | Show tool calls with inputs and results |
| Thinking Blocks | Off | Show model thinking/reasoning blocks |

**Message structure:**

Messages are separated into blocks with distinct visual treatment:

| Block Type | Contains | Color Set |
|---|---|---|
| System Prompt | Bootstrap/system content | Gray |
| User Message | PrePrompt + User Prompt + PostPrompt (each collapsible) | Blue |
| AI Message | Thinking + Tool Usage + AI Response (each collapsible) | Green (response), Amber (tools), Purple (thinking) |

<!--[CURATE: The PrePrompt/PostPrompt sub-blocks within User Messages are new — these don't exist in the current transcript viewer. I believe these refer to hook-injected content (pre_message/post_message hooks) or system-injected content (skills, system reminders). Confirm whether this is the intent and what specifically constitutes PrePrompt vs PostPrompt content.]-->

**Visual indicators:**
- Each block displays a colored vertical bar on the left edge spanning its full extent
- Blocks are collapsible/expandable individually
- Context menu on each block: Collapse/Expand, Collapse All/Expand All (applies to that block type only across the entire transcript)

**Additional features (carried from current):**
- Copy buttons per prompt, per response, per turn, and copy-all
- Search (Cmd+F) filters turns to matches
- Transcript scrolls to bottom on load (latest visible first)

#### Prompt Box

Enhanced prompt input at the bottom of the center area.

**Core behavior:**
- Textarea for user input
- Supports both regular prompts and commands (prefixed with `!`)
- Submit via **Cmd+Enter** or Send button <!--[CURATE: Current implementation uses Enter to submit and Shift+Enter for newline. This spec says Cmd+Enter to submit. Which is preferred? Cmd+Enter is safer (prevents accidental submission of multi-line prompts) but Enter is faster for quick exchanges. This affects muscle memory significantly.]-->

**Per-session state:**
- Each session maintains its own prompt text independently
- Switching between session tabs preserves unsent text and restores it
- Prompt state is ephemeral (not persisted across app restarts)

**History navigation:**

The prompt box SHALL support separate histories for:

| History Type | Source | Navigation |
|---|---|---|
| User messages | Rebuilt from JSONL file | Up/Down arrow |
| Commands | Persisted command history file | <!--[CURATE: Separate navigation key? Or same Up/Down with a mode indicator? Need to define the interaction model for switching between message history and command history.]-->  |

Each prompt box's history state is independent across sessions.

**History command (`!history`):**

Opens a popup showing paginated history of user messages:
- Most recent at bottom, older messages going up
- Each line shows date/time and first N characters of message
- Hover to show complete message
- Enter on selected item shows action dialog:
  - **Copy** — Copy to clipboard
  - **Edit & Send** — Copy to prompt box for editing
  - **Re-send** — Send directly to session
  - **Jump to** — Scroll transcript to that message
  - **Rewind to** — Send /rewind command to CLI (interactive mode)
  - **Fork from** — Create new session forked from that point

**Auto-sizing:**
- Default to a configured minimum number of lines
- Auto-grow as content is typed, up to a configured maximum
- Auto-shrink when content decreases below current size
- Resize handle above the prompt box for manual sizing
- Manual resize overrides auto-sizing until the next session switch or until content shrinks below the manual size

**Standard operations:** Select-all (Cmd+A scoped to textarea), Copy (Cmd+C), Paste (Cmd+V), Cut (Cmd+X)

### 2.3 Right Panel: Context Panel

Tabbed panel providing contextual information for the selected/focused session.

| Tab | Content |
|---|---|
| **Session Details** | Full session metadata with click-to-copy (status, ID, role, working dir, parent, created, zellij session, UUID, exchanges, type) |
| **Docs** | Documents loaded by the session (tracked per-session) |
| **Memories** | Memory slots loaded/written by the session |
| **Messages** | Inter-session messages (via messages MCP — direct messages and broadcasts) |
| **Prompts** | Queued prompts from the prompt queue awaiting delivery |

**Behavior:**
- Closed by default on startup
- Content updates when the focused session changes
- Panel state (open/closed, active tab) persists across app restarts

### 2.4 Bottom Panel

Tabbed bottom panel with collapsible sections.

#### Worker Panel

Shows child CLI instances and subagents related to the current context.

**Scoping rules:**
- When a chat session is focused: show workers where `parent_tracking_id === focused session's tracking_id`
- If focused session has no scoped workers: show all workers (fallback)
- Sessions without a parent are "Unaffiliated"

**Display:**
- Collapsible sections grouped by parent session (orchestrator chain)
- Headers show active worker count
- Worker cards with platform icon, status, activity indicators
- Entire panel is collapsible

#### Session Activity Log

<!--[CURATE: This is a new component not present in the current implementation. I believe it would show a chronological log of actions/events for the focused session — tool calls, file reads/writes, session state changes, hook firings. Is this the intent? Should it pull from the JSONL file (structured events) or from the action logging protocol (ai_claude_cli/logs/)? Or both?]-->

Shows a chronological event log for the focused session, useful for understanding what a session has been doing without reading the full transcript.

---

## 3. Relationship to Existing Documents

| Document | Disposition |
|---|---|
| `system_description_v0.1.md` | To be superseded by v0.2 incorporating these updates |
| `requirements_v0.1.md` | To be superseded by v0.2 incorporating these updates |
| `component_design_v0.2.md` | To be revised — current design references tmux; update to reflect zellij and component API model |
| `interface_session_mcp_v0.1.md` | To be revised — session identification model changes (UUID primary key) |
| `APP_SPEC.md` | Implementation reference — captures what exists today; architecture docs capture what should exist |
| Architecture decision memo | Historical context — captures the reasoning behind tmux-style substrate decision |

---

## 4. Items Requiring Curation

Summary of all `<!--[CURATE:]-->` markers in this document:

1. **Section 1.3** — Multiple instances: shared vs independent registry files
2. **Section 1.8** — "Electrum" typo? Electron confirmed, or revisiting PySide6+Qt?
3. **Section 1.8** — Zellij vs tmux: settled or still open?
4. **Section 2.1** — Session Navigator: single-click select vs single-click open
5. **Section 2.2** — Transcript: PrePrompt/PostPrompt sub-blocks definition
6. **Section 2.2** — Prompt Box: Cmd+Enter vs Enter for submit
7. **Section 2.2** — Prompt Box: command history navigation model
8. **Section 2.4** — Session Activity Log: data source and scope
