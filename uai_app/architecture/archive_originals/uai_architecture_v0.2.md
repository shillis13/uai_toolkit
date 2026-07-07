# UAI (Unified AI Interface) — Architecture Document

**Version:** 0.2
**Date:** 2026-03-30
**Author:** Claude (CLI, UAI Architect) with PianoMan
**Status:** Draft — revised per peer reviews + frontend design alignment
**Dependencies:** session_identity_v4.2.md, 2026-03-30-frontend-design-v2.md

---

## 1. Purpose

UAI is a desktop workspace for managing multiple simultaneously running AI CLI agent sessions. It preserves the terminal interaction model that makes CLI tools useful while adding organization, search, navigation, and automation that don't scale in a plain terminal workflow.

**UAI is NOT:**
- A terminal replacement — the terminal is the interaction surface
- A message broker — CLI agents handle conversation logic
- A frontend with backend AI services — CLIs are the backends

**UAI IS:**
- A session manager with workspace UI
- A control tower for persistent terminal sessions
- An organization/search/navigation layer above the session substrate

---

## 2. Architecture Overview

```
┌──────────────────────────────────────────────────────────────────┐
│                          UAI Application                         │
├──────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────────────┐    │
│  │   Session    │  │   Workspace  │  │   Context Panel      │    │
│  │   Navigator  │  │   (Tabs)     │  │   (Docs/Mem/Msg)     │    │
│  └──────┬───────┘  └──────────────┘  └──────────────────────┘    │
│         │                  │                      │              │
│  ┌──────▼──────────────────▼──────────────────────▼───────────┐  │
│  │                    Component API Layer                     │  │
│  │          (Get/Set/Update/Delete/List children)             │  │
│  └──────────────────────────┬─────────────────────────────────┘  │
│                             │                                    │
│  ┌──────────────────────────▼─────────────────────────────────┐  │
│  │                    Session Data Model                      │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌──────────────────┐   │  │
│  │  │  Session    │  │  Session     │  │  App State       │   │  │
│  │  │  Registry   │  │  Info Dirs   │  │  (groups, tabs)  │   │  │
│  │  │  (index)    │  │  (truth)     │  │  (UI-only)       │   │  │
│  │  └─────────────┘  └──────────────┘  └──────────────────┘   │  │
│  └────────────────────────────────────────────────────────────┘  │
│                              │                                   │
├──────────────────────────────┼───────────────────────────────────┤
│                              │                                   │
│  ┌───────────────────────────▼────────────────────────────────┐  │
│  │              Session Substrate Abstraction                 │  │
│  │  ┌──────────────────┐  ┌──────────────────┐                │  │
│  │  │  ZellijSubstrat  │  │  TmuxSubstrat    │                │  │
│  │  └──────────────────┘  └──────────────────┘                │  │
│  └────────────────────────────────────────────────────────────┘  │
│                             │                                    │
│  ┌──────────────────────────▼─────────────────────────────────┐  │
│  │                    CLI Wrappers                            │  │
│  │  claude_cli.py  │  codex_cli.py  │  gemini_cli.py          │  │
│  │                lib_cli_common.py                           │  │
│  └────────────────────────────────────────────────────────────┘  │
│                                                                  │
└──────────────────────────────────────────────────────────────────┘
                               │
                               ▼
                    ┌─────────────────────┐
                    │  Terminal Sessions  │
                    │  (zellij or tmux)   │
                    │  ┌───┐ ┌───┐ ┌───┐  │
                    │  │ C │ │ X │ │ G │  │
                    │  └───┘ └───┘ └───┘  │
                    └─────────────────────┘
```

---

## 3. Layers

### 3.1 Session Substrate (Bottom)

**Responsibility:** PTY-backed session lifetime, attach/detach, multi-client, terminal semantics.

**Implementation:** Abstracted behind `SessionSubstrate` interface (see session_identity_v4.2.md Section 9). Concrete implementations for zellij and tmux. System-level configuration — all sessions on a machine use the same multiplexer. The app never knows which implementation is behind the interface.

**The app never calls tmux/zellij directly.** All terminal operations go through the abstraction.

### 3.2 CLI Wrappers

**Responsibility:** Session creation, bootstrap prompt assembly, identity generation, resume/fork logic.

**Key principle:** The wrapper is the authority for session identity. It generates the Tracking ID, discovers the CLI UUID (waits for Codex/Gemini session file), and generates the terminal session name. The wrapper does NOT exit until identity is complete. The app reads the finished identity from wrapper output.

**Interface with the app:** The app calls the wrapper as a subprocess. The wrapper prints `TRACKING_ID=`, `TERMINAL_SESSION=`, `CLI_UUID=` to stdout after all identity is resolved. The app parses these. No async discovery needed.

### 3.3 Session Data Model

Three stores with clear ownership (see session_identity_v4.2.md Section 4):

| Store | Writer | Purpose |
|-------|--------|---------|
| Session Registry | Wrappers only | Identity index (derived, rebuildable) |
| Per-Session Dirs | Wrappers only | Source of truth for session metadata |
| App State | App only | UI state (groups, tabs, pinned, type) |

**No fswatch handlers.** The wrapper owns all identity writes. No external watchers or background processes modify session identity.

**Idempotent rebuilding:** Any component's state can be reconstructed from authoritative sources. The session list is rebuildable from the registry. Session metadata is rebuildable from sessionInfo.json. Transcript content comes from JSONL files. Only manual user state (custom groups, pinned status) is non-rebuildable.

### 3.4 Component API Layer

**Responsibility:** Structured, hierarchical access to application state. This is production-critical infrastructure — all data mutations in the UI flow through component APIs. It also serves testing and debugging (component state is inspectable and verifiable without UI selectors).

Each architectural UI component exposes:
- **Get(key)** → typed value — Retrieve a specific data element
- **Set(key, value)** → void — Initialize or replace a data element
- **Update(key, patch)** → void — Modify existing element (partial update)
- **Delete(key)** → boolean — Remove an element (returns success)
- **List()** → typed array — Enumerate children or contained elements

**Keys** are dot-separated paths scoped to the component: `filter.platform`, `tabs.active`, `session.{tracking_id}.status`.

**Errors:** Operations on nonexistent keys return `null` (Get) or `false` (Delete). Type mismatches throw. The API is synchronous — state is in-memory with async persistence.

**This is the interface to the Model in MVC.** All data changes in the UI go through these components. The component data definitions are in the frontend design doc (Section 1, Component Data).

**Scope:** Architectural components only:

| Component | Data Exposed (key examples) |
|-----------|---------------------------|
| SessionNavigator | `filter.*`, `group_mode`, `sort_mode`, `groups[]`, `highlighted_groups[]` |
| Workspace | `tabs[]`, `tabs.active`, `tab_groups[]` |
| SessionPane | `session_id`, `mode` (terminal/transcript), `transcript.filters.*` |
| PromptBox | `text`, `target_session_id`, `mode`, `shell_output` |
| ContextPanel | `open`, `active_tab`, `width` |
| BottomPanel | `open`, `active_tab`, `height`, `workers.scoped_to` |

Session data itself is NOT in component APIs — it's in the Session Store (single source of truth). Components hold `tracking_id` references and render by lookup.

### 3.5 UI Components (Top)

**Responsibility:** Render state, handle user interaction, delegate to Component API.

See Section 5 for the component hierarchy and layout.

---

## 4. Session Identity

Defined in `session_identity_v4.2.md`. Key points for the architecture:

- **Tracking ID** is the primary key everywhere in the app
- **CLI UUID** is a linked cross-reference for JSONL file access
- **Terminal Session Name** is a mutable operational handle for terminal operations
- Parent-child relationships use Tracking IDs (available immediately, no discovery dependency)
- The app never generates IDs — it reads them from wrapper output

---

## 5. UI Component Hierarchy

```
Application
├── Session Navigator (Left Panel)
│   ├── Filter Bar (platform, status, type, role, text)
│   ├── Group Control (by platform, role, status, parent, custom, none)
│   ├── Sort Control (activity, created, name, exchanges, context%)
│   └── Session/Group List
│       ├── Pinned Sessions (top)
│       ├── Groups (collapsible, nestable)
│       │   └── Session Items
│       └── Unaffiliated (bottom)
│
├── Workspace (Center)
│   ├── Tab Bar
│   │   ├── Tabs (individual sessions)
│   │   └── Tab Groups (split layouts: 2x-v, 2x-h, 2x2)
│   ├── Focus Bar (status, breadcrumb, action buttons)
│   ├── Session Pane(s)
│   │   ├── Live Terminal Mode (attached multiplexer session)
│   │   └── Transcript Mode (parsed JSONL)
│   └── Prompt Box (per-tab state, history, auto-grow)
│
├── Context Panel (Right, collapsible)
│   ├── Session Details Tab
│   ├── Docs Tab (document tree, loaded tracking)
│   ├── Memory Tab (slot manifest, loaded tracking)
│   ├── Messages Tab (inter-session messages)
│   └── Prompts Tab (queued prompts)
│
└── Worker Panel (Bottom, collapsible)
    ├── Orchestrator Chains (grouped by parent)
    │   └── Worker Cards (platform icon, status, badges)
    └── Unaffiliated Workers
```

---

## 6. Data Flow

### 6.1 New Session

```
User clicks [+]
    │
    ▼
App calls CLI wrapper (subprocess)
    │ python3 claude_cli.py -n "my chat" -t
    │
    ▼
Wrapper:
    1. Generates Tracking ID (atomic mkdir)
    2. Generates CLI UUID (Claude) or writes breadcrumb (Codex/Gemini)
    3. Generates terminal session name
    4. Writes registry + sessionInfo + PID file
    5. Creates multiplexer session (via substrate abstraction)
    6. Launches CLI binary inside session
    7. Prints TRACKING_ID=, TERMINAL_SESSION=, CLI_UUID= to stdout
    │
    ▼
App parses wrapper output
    │
    ▼
App creates internal session entry (from registry)
    │
    ▼
Session appears in Navigator, tab opens
```

### 6.2 Transcript Load

```
User clicks Transcript button (or session is stopped)
    │
    ▼
App reads session.cli_uuid
    │
    ├── cli_uuid exists → read JSONL file → render transcript
    │
    └── cli_uuid is null → return empty (no guessing, no fallback matching)
```

### 6.3 UUID Discovery (Codex/Gemini)

```
Wrapper snapshots session file directory
    │
    ▼
Wrapper creates terminal session + launches CLI binary
    │
    ▼
Wrapper polls for new file (vs snapshot, timeout: 30s)
    │
    ▼
New file appears → wrapper extracts UUID
    │
    ▼
Wrapper updates sessionInfo + registry with cli_uuid
    │
    ▼
Wrapper prints complete identity (TRACKING_ID, TERMINAL_SESSION, CLI_UUID)
    │
    ▼
App receives complete identity — no async discovery needed
```

**No external infrastructure.** No fswatch, no breadcrumbs, no handler scripts. The wrapper owns the full identity lifecycle.

### 6.4 Activity Detection

```
Poll loop (every 5s for running sessions):
    │
    ▼
substrate.dump_screen(terminal_session)
    │
    ▼
Parse screen for:
    - Thinking indicator (✻ timer) → responding/idle
    - Status bar (ctx:XX%) → context_percent
    - Permission prompt → blocked state
    │
    ▼
Update runtime state → UI reflects
```

---

## 7. Session Substrate Abstraction

Defined in session_identity_v4.2.md Section 9. The abstraction provides:

```python
class SessionSubstrate(ABC):
    create_session(name, command, cwd, log_file) -> str   # returns actual name
    session_exists(name) -> bool
    session_is_running(name) -> bool
    kill_session(name)
    list_sessions() -> list[SessionInfo]
    send_keys(name, keys)
    dump_screen(name, path?) -> str
    get_current_session_name() -> str | None
    attach(name)
```

**Selection:** System-level configuration. All sessions on a machine use the same multiplexer. The app calls the abstraction — it never knows which concrete implementation is behind it.

---

## 8. Platform Adapter Layer

The session substrate provides raw terminal operations (dump_screen, send_keys). But interpreting screen content is platform-specific — Claude, Codex, and Gemini have different TUI layouts, different thinking indicators, different status bar formats.

A **platform adapter** sits between the substrate and the app's activity detection:

```
substrate.dump_screen()
    │ raw screen text
    ▼
PlatformAdapter.parse(platform, screen_text)
    │ structured state
    ▼
{ status: "responding", ctx_percent: 72, permission_prompt: false }
```

| Platform | Thinking Indicator | Status Bar | Permission Prompt |
|----------|-------------------|------------|-------------------|
| Claude | `✻` + verb + timer | `ctx:XX%` in bottom bar | "Do you want to proceed?" |
| Codex | TBD — different TUI | TBD | TBD |
| Gemini | TBD — different TUI | TBD | TBD |

The adapter is a pure function: `(platform, raw_text) → structured_state`. No side effects, easily testable, each platform's parser is independent.

**`--no-mux` sessions:** No dump_screen available. Activity state is limited to PID-alive check (running/stopped). No ctx%, no responding detection.

---

## 9. Session Lifecycle

Beyond running/stopped, sessions have a **finalize** flow for controlled wrap-up:

```
Running → Stopped → (Resume) → Running
Running → Finalize → Wrap-up prompt → Stop → Archived
```

**Finalize** is an active process — the session must be running to receive the wrap-up prompt:

1. User triggers finalize (context menu, `!finalize` command)
2. Structured wrap-up prompt fires, asking the CLI to produce: lessons learned, memory updates, key decisions, unfinished work, handoff notes
3. Session responds with wrap-up content
4. User reviews/edits
5. Session stops and moves to Archive

**Archived sessions:** Hidden from navigator by default, visible with "Show Archived" filter. Transcript and logs remain accessible. Can be un-archived.

---

## 10. Tech Stack — Decided

Two spikes evaluated the terminal embedding options (2026-03-30). Results at `spikes/spike1_pyside6_tmux/` and `spikes/spike2_electron_tmux/`.

| Decision | Choice | Rationale |
|----------|--------|-----------|
| **App framework** | Electron | Production-proven for terminal apps (VS Code, Hyper, Tabby). Full web stack for UI. Native OS integration. |
| **Terminal widget** | xterm.js + node-pty | Battle-tested (VS Code's terminal). WebGL rendering, truecolor, built-in link detection, automatic resize via FitAddon. |
| **Multiplexer** | tmux (default via substrate abstraction) | Simpler reading (capture-pane), no iframe/web-client layer needed. Substrate abstraction allows switching to zellij later if needed. |
| **Terminal connection** | node-pty → `tmux attach-session` | Direct PTY bridge. No web server, no iframe, no websocket, no cross-origin barriers. |
| **State management** | TBD (likely Zustand or similar lightweight store) | Must integrate with Component API layer. |
| **Persistence** | JSON files | Sufficient for session metadata. Three stores: registry, sessionInfo dirs, app state. |

### Why Electron + xterm.js (not PySide6 + pyte)

**Spike 1 (PySide6 + pyte)** was "viable" — pyte parses VT100 escape sequences and a custom QWidget renders cell-by-cell. But this is essentially building a terminal emulator from scratch: no GPU rendering, no built-in links, no scrollback, performance at scale is unknown. Large custom maintenance surface.

**Spike 2 (Electron + xterm.js + node-pty)** uses the exact architecture VS Code's terminal uses — proven by millions of users. Terminal rendering is a solved problem in this stack. WebGL, truecolor, links, resize, scrollback all built in.

**Key insight:** The current app's problems (iframe cross-origin, keyboard passthrough workarounds, broken link handling) were caused by the **zellij iframe layer**, not by Electron or xterm.js. Removing zellij's web client and connecting xterm.js directly to the PTY via node-pty eliminates all of those issues.

### Why tmux (not zellij)

Zellij's unique value was its web client for iframe embedding. With xterm.js + node-pty, that's unnecessary. The zellij friction inventory (ANSI stripping scripts, keyboard filter, cross-origin injection, broken Linkifier2, xterm canvas rendering issues) all came from the iframe layer. tmux provides the same session persistence and attach/detach semantics with simpler tooling and a larger ecosystem.

The substrate abstraction makes this reversible — switching multiplexers requires only a new `SessionSubstrate` implementation, not app changes.

### What changes from the current app

| Current (Electron + zellij iframe) | New (Electron + xterm.js + node-pty + tmux) |
|-----------------------------------|--------------------------------------------|
| Terminal via zellij web client iframe | Terminal via xterm.js direct in renderer |
| Cross-origin barriers, webFrameMain injection | No cross-origin — xterm.js is native to renderer |
| Custom link handler (registerLinkProvider broken) | WebLinksAddon (built-in) |
| 50+ line keyboard filter (before-input-event) | Standard Electron key handling |
| ANSI stripping Python scripts for dump-screen | tmux capture-pane (cleaner output) + Platform Adapter |
| zellij-specific session management | Substrate-abstracted (tmux default) |

---

## 11. Testability

### 9.1 Component API Testing

Each architectural component's state is inspectable via its API. Tests can:
1. Set up state via the API
2. Trigger an action
3. Read state via the API
4. Assert expected state

No CSS selectors, no DOM traversal, no brittle positional queries.

### 9.2 Idempotent Rebuild Verification

For any component backed by persistent data:
1. Read current component state via API
2. Delete the cached state
3. Trigger rebuild from authoritative sources
4. Compare rebuilt state to original
5. Assert equivalence (excluding runtime-only fields)

### 9.3 Multiple Independent Instances

The app supports multiple independent instances via separate config/state directories. Test instances create sessions with test-prefixed names (convention-based isolation). Some CLI wrapper paths can specify names and UUIDs; others cannot. Minor spillover is tolerable.

### 9.4 Session Identity Verification

Test that:
- Wrapper output matches registry content
- Registry matches sessionInfo.json
- CLI UUID symlinks resolve correctly
- Breadcrumb-based UUID discovery links correctly
- No time-based matching anywhere in the pipeline

---

## 12. Anti-Clobbering

Multiple AI sessions editing the same source files is a known problem. The current hook system (`ai_general/scripts/fs/`) tracks reads and writes per session and blocks writes when another session has modified the file since last read.

**For the rewrite:** The architecture should minimize high-conflict files. The current app has 5 files modified by almost every session (index.ts, App.tsx, TerminalViewer.tsx, FocusPane.tsx, styles.css). The component-based architecture should distribute responsibility so no single file is a bottleneck.

---

## 13. What Carries Forward

| From Current App | Disposition |
|-----------------|-------------|
| Zellij terminal embedding (iframe) | Preserved if zellij stays; replaced by terminal widget if tmux |
| Tab bar with keyboard navigation | Carry forward (Cmd+1-9, Cmd+Shift+[/]) |
| Transcript viewer (JSONL parser) | Carry forward, enhance with filtering |
| Platform color coding (orange/purple/blue) | Carry forward |
| Worker dock with chain visualization | Carry forward |
| Activity detection (dump-screen polling) | Carry forward via substrate abstraction |
| Link handling (Shift+click, Ctrl+click) | Carry forward |
| Session detail panel with click-to-copy | Carry forward |
| Per-tab prompt state | Carry forward |
| Heuristic UUID matching (history.jsonl, mtime scan) | **DELETE** |
| Monolithic session_metadata.json (v2 registry) | **Replace** with v4 Tracking ID registry |
| Time-based session matching of any kind | **DELETE** |
| fswatch UUID discovery pipeline | **DELETE** — wrapper polls directly |
| Breadcrumb files for UUID linking | **DELETE** — not needed |
| `handle_new_session_file.py` | **DELETE** — wrapper owns discovery |
| `resolve_missing_uuids.py` | **KEEP** as manual fallback for timeout cases |

---

## 14. Open Architecture Questions

1. **Session list vs session navigator:** Current app has a flat session list that appears when no tab is focused. The new design has a persistent navigator in the left panel. Are these redundant, or does the list serve a different purpose (e.g., "home screen" showing recent activity)?

2. **Group persistence model:** Auto-generated groups (by platform, role) are rebuildable. Custom groups are not. Should custom groups be stored per-session or globally? If globally, what happens when the sessions they reference are archived?

3. **Transcript caching:** Reading and parsing JSONL files on every transcript open is expensive for large sessions. Should the app maintain a parsed/indexed cache? What invalidation strategy?

4. **Session archival:** When do sessions move from active registry to archive? After N days stopped? Manual only? What happens to their data stores?
