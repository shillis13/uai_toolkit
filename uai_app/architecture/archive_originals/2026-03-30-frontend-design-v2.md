# UCI Frontend Design v2

**Date:** 2026-03-30
**Status:** Complete draft — all major components covered. Search panel, context menu detail designs, and filter/group/sort dropdown designs still pending.
**Context:** Brainstorming sessions between PianoMan and Claude CLI. Mockups in `.superpowers/brainstorm/` directories.

---

## 1. Architectural UI Components

### Component Hierarchy

```
Window
  ├── SessionNavigator
  │   ├── Toolbar (Filter, Group, Sort controls)
  │   └── SessionList
  │       └── NavigatorGroup[] (collapsible, nestable)
  │           └── NavigatorItem[] (compact session references)
  │
  ├── Workspace
  │   ├── TabBar
  │   │   ├── Tab[] (individual session tabs)
  │   │   └── TabGroup[] (container of tabs)
  │   │       └── Tab[]
  │   ├── CenterPanel
  │   │   ├── CardGrid (browse mode — no tab focused)
  │   │   │   └── SessionCard[] (by reference to Session)
  │   │   ├── SessionPane (tab focused — live or transcript)
  │   │   │   ├── PaneHeader
  │   │   │   ├── TerminalView (live session)
  │   │   │   └── TranscriptView (review/stopped session)
  │   │   │       └── Exchange[]
  │   │   │           ├── UserBlock (collapsible)
  │   │   │           └── AIBlock (collapsible)
  │   │   │               ├── ToolBlock[] (collapsible)
  │   │   │               └── ThinkingBlock (collapsible)
  │   │   └── SplitLayout (Tab Group with 2+ visible sessions)
  │   │       └── SessionPane[] (2x1, 1x2, or 2x2 grid)
  │   └── PromptBox
  │       └── ShellOutputArea (appears on $ commands)
  │
  ├── ContextPanel (right)
  │   └── ContextTab[] (Details, Docs, Memories, Messages, Prompts)
  │
  └── BottomPanel
      ├── WorkersTab
      │   ├── ActiveGroup (expanded by default)
      │   │   └── WorkerCard[] (by reference to Session)
      │   └── StoppedGroup (collapsed by default)
      │       └── WorkerCard[] (by reference to Session)
      ├── LogsTab (per-session log viewer)
      └── AppLogTab (application-wide log)
```

### Component Data

**Session** is the primary entity. Components reference sessions by `tracking_id` — they don't duplicate session attributes.

#### Session (primary entity)

Defined in the requirements doc (Section 1.7). Keyed by `tracking_id`. All session data lives here. Components hold references, not copies.

**Data source mapping** (per session_identity_v4.2.md Section 4): The app merges session data from three stores at load time:

| Field(s) | Source | Writer |
|---|---|---|
| tracking_id, cli_uuid, platform, parent_tracking_id, created_at, terminal_session_id, display_name, working_dir, model, roles | sessionInfo.json (per-session dir) | CLI wrappers |
| Identity subset (derived index) | Session Registry | CLI wrappers |
| type, pinned, exchange_count, prompt_history | App State (`app_state.json`) | App only |
| status, context_percent, activity_state | Runtime (polling/events) | App (in-memory) |

**`--no-mux` / `--oneshot` sessions:** `terminal_session_id` is null. No terminal attachment, no dump-screen, no activity detection beyond PID-alive. The session appears in the navigator and card grid but cannot be opened in a live terminal pane — only transcript view (if cli_uuid is available).

#### SessionNavigator

| Field | Type | Description |
|---|---|---|
| filter_state | FilterConfig | Active filter settings (platform, status, type, role, text) |
| group_mode | enum | By Platform, By Role, By Status, By Parent, Custom, None |
| sort_mode | enum | Last Activity, Created, Name, Exchange Count, Context % |
| sort_direction | enum | asc, desc |
| groups | NavigatorGroup[] | Current group structure (derived from group_mode + sessions) |
| highlighted_groups | tracking_id[] | Groups containing the focused session (for membership highlight) |

#### NavigatorGroup

| Field | Type | Description |
|---|---|---|
| id | string | Group identifier |
| name | string | Display name |
| type | enum | auto_platform, auto_role, auto_status, auto_parent, custom |
| session_ids | tracking_id[] | Member sessions (by reference) |
| collapsed | boolean | Expand/collapse state |
| children | NavigatorGroup[] | Nested sub-groups |

**Note:** NavigatorGroups are **their own entities** — they hold real data (name, type, membership, collapse state, sub-groups). They are not sessions and are not stored in the Session store. The navigator's data model is: NavigatorGroups (own data) containing NavigatorItems (session references by `tracking_id`).

#### NavigatorItem

No own data — renders from Session by `tracking_id`. Shows: platform bar, name, ctx%, status dot.

#### Tab

| Field | Type | Description |
|---|---|---|
| session_id | tracking_id | Referenced session |
| active | boolean | Currently focused tab |
| group_id | string? | TabGroup this tab belongs to (null if standalone) |
| prompt_draft | string | Unsent text in prompt box for this tab |

#### TabGroup

| Field | Type | Description |
|---|---|---|
| id | string | Group identifier |
| name | string | Display name |
| session_ids | tracking_id[] | All sessions in the group (visible + hidden) |
| visible_ids | tracking_id[] | Sessions currently shown as tabs |
| layout | enum | single, vertical_2, horizontal_2, grid_2x2 |
| collapsed | boolean | Tab bar collapse state |

#### SessionCard / WorkerCard

No own data — renders from Session by `tracking_id`. Cards are a **view** of a session, not a data container. Any component that shows cards (CardGrid, WorkersTab) holds a list of `tracking_id[]` and renders each by looking up the Session.

#### PromptBox

| Field | Type | Description |
|---|---|---|
| text | string | Current input text |
| target_session_id | tracking_id | Session that Cmd+Enter will stage to |
| mode | enum | prompt, command (!), shell ($) |
| shell_output | string? | Output from last $ command |
| shell_output_visible | boolean | Whether output area is showing |
| manual_height | number? | If user manually resized (null = auto-sizing) |

#### TranscriptView

| Field | Type | Description |
|---|---|---|
| session_id | tracking_id | Session being viewed |
| filters | { user, ai, tools, thinking } | Visibility toggles (boolean each) |
| scroll_position | number | Current scroll offset |
| auto_follow | boolean | Whether new content scrolls to bottom |
| search_query | string? | Active search filter |
| width_percent | number | Panel width as % of center pane (default: 50) |

#### ContextPanel

| Field | Type | Description |
|---|---|---|
| open | boolean | Visible or collapsed |
| active_tab | enum | details, docs, memories, messages, prompts |
| width | number | Panel width in px (default: 280) |

#### BottomPanel

| Field | Type | Description |
|---|---|---|
| open | boolean | Visible or collapsed |
| active_tab | enum | workers, logs, app_log |
| height | number | Panel height in px |

#### WorkersTab

| Field | Type | Description |
|---|---|---|
| scoped_to | tracking_id? | Focused session (workers filtered to its children) |
| active_collapsed | boolean | Active group collapse state |
| stopped_collapsed | boolean | Stopped group collapse state |

### Data Flow Principle

**Sessions are the single source of truth.** All UI components reference sessions by `tracking_id`. When a session's state changes (status, ctx%, activity), every component displaying that session updates from the same source. No component stores session attributes locally.

```
Session Store (source of truth)
  ↓ tracking_id references
  ├── NavigatorItem renders from Session
  ├── SessionCard renders from Session
  ├── Tab renders from Session
  ├── PaneHeader renders from Session
  └── WorkerCard renders from Session
```

---

## 2. Window Layout

```
Window
  ├── Left Panel: Session Navigator (full height, ~240px)
  │   ├── Title bar (session count)
  │   ├── Toolbar (Filter, Group, Sort)
  │   └── Browsable session list
  │
  └── Right Column (everything else)
      ├── Tab Bar (Tabs + Tab Groups)
      ├── Center Panel
      │   ├── Card Grid (browse mode — no tab focused)
      │   ├── Terminal View (tab focused — live session)
      │   └── Transcript View (tab focused — stopped session)
      ├── Prompt Box
      ├── Right Panel (Context Panel — collapsible)
      └── Bottom Panel (Workers, Activity Log — collapsible)
```

**Key change from v1:** The navigator extends the full height of the window. The tab bar and center area are in the right column only — the tab bar does not span over the navigator.

**Panel boundaries:** All major panel dividers use 2px borders at `#606d94` for clear visual separation. This is a significant contrast increase from v1 (`1px #333a4a`).

---

## 3. Session Navigator (Left Panel)

A compact, browsable list for navigating sessions. **Cards do not appear here** — they appear in the center pane when browsing.

### Layout

- **Title bar:** "Sessions · 12 total"
- **Toolbar:** Filter, Group, Sort dropdown buttons
- **Session list:** Groups and items, scrollable
- **Bottom:** "+ New Session" button

### Session Items (Compact)

Each item is a single-line entry:

```
[3px platform bar] [name]              [ctx%] [status dot]
```

- Platform color bar (orange/purple/blue) on left edge
- Session name (14px, truncated with ellipsis)
- Context % (colored: green ≥80%, yellow 20-79%, red <20%)
- Status dot — see Activity States below

No badges, no meta row, no multi-line content. The navigator is for fast scanning and selection.

### Activity States

Beyond running/stopped, sessions have observable activity states detected via screen parsing:

| State | Dot | Indicator | Description |
|---|---|---|---|
| **Running (idle)** | Green | Steady | CLI at prompt, waiting for input |
| **Responding** | Green | Pulsing | CLI thinking/generating (✻ indicator visible) |
| **Blocked** | Yellow | Steady | Permission prompt awaiting user action |
| **Error** | Red | Steady | Session in error state |
| **Stopped** | Gray | Steady | Session exited |

The pulsing dot for "responding" gives immediate visual feedback across navigator, cards, tabs, and worker cards without needing to open the session.

### Controls

**Filter** — controls which sessions appear. Additive (AND logic).

| Dimension | Options |
|---|---|
| Platform | Claude, Codex, Gemini (multi-select) |
| Status | Running, Stopped, Error |
| Type | Chat, Worker |
| Role | Any assigned role |
| Text | Display name substring |

**Group** — controls how sessions are structured.

| Mode | Behavior |
|---|---|
| By Platform | Claude Sessions, Codex Sessions, Gemini Sessions |
| By Role | Role: dev_lead, Role: librarian, Ungrouped |
| By Status | Active, Stopped, Error |
| By Parent | Orchestrator chains + Unaffiliated |
| Custom | User-defined groups |
| None | Flat list |

**Sort** — controls ordering of groups and sessions within groups.

| Dimension | Default |
|---|---|
| Last Activity | Newest first (default) |
| Created | Newest first |
| Name | Alphabetical |
| Exchange Count | Most first |
| Context % | Lowest remaining first |

### Interactions

| Action | Behavior |
|---|---|
| Single-click Group | Select group; toggle expand/collapse; show cards in center |
| Double-click Group | Open group's content as a Tab in the workspace |
| Single-click Session | Select session (highlight, show details in Context Panel) |
| Double-click Session | Open session as a Tab in the workspace |

### Multi-Group Membership

Sessions can belong to multiple Navigator Groups simultaneously. Auto-generated groups (by platform, by role) inherently overlap. Custom groups support multi-membership via "Add to Group" (not "Move to").

**Membership highlighting:** When a session tab has focus, every Navigator Group containing that session shows a blue left bar and tinted group name. This surfaces multi-membership at a glance without cluttering cards.

**Focused session:** The focused session's navigator item is highlighted with blue text and tinted background, visually correlating with the focused tab.

### Browse Mode (Card Grid)

The center pane shows the **Card Grid** when:
- A Navigator Group is selected (single-click) — shows that group's sessions as cards
- App launches with no tabs open

The Card Grid is a **browse view**, not a mode that replaces session panes. Tabs remain open — clicking a tab switches back to the session pane. The PromptBox remains visible in browse mode for application-level commands (`!` prefix).

### Filter/Group/Sort Affect Center

The navigator controls are the single source of truth for what's visible. If you filter to "running only" and select a group, the center pane shows only the running sessions from that group as cards.

---

## 4. Session Cards (Center Pane)

Cards appear in the center pane when browsing (no tab focused). They use the **left-bar accent** design.

### Card Structure

```
[3px platform bar] | Session Name                    2m  [●]
                   | 12 msgs · ai_root · ◉ working
                   | [chat] [ctx:79%] [▬▬▬▬▬▬▬░░]
```

- **Platform color bar** — 3px left edge (orange/purple/blue)
- **Name** — 14px, semibold, truncated
- **Time** — relative ("2m", "1h", "3d")
- **Status dot** — activity state (see Section 3, Activity States)
- **Meta row** — exchange count, working directory, activity indicator
- **Badge row** — role, ctx% badge, context meter bar, worker count

### Card States

| State | Treatment |
|---|---|
| **Active** | Full color rendering. Platform bar in platform color. |
| **Stopped** | Same opacity as active. Muted text color. Gray platform bar. Gray status dot. Slightly muted border. |
| **Focused** | Blue border (`#7aa2f7`). Subtle blue glow (`box-shadow`). Platform bar widens from 3px to 4px. Background tint. |
| **Open in tab** | Subtle indicator that this session is already open as a tab — e.g., a small tab icon badge or a thin top/bottom accent line. Distinguishable at a glance when scanning a card grid. |

**No opacity dimming anywhere.** Stopped cards are visually quieter through color treatment, not transparency.

**Open-in-tab indicator** applies additively — an active card that is also open in a tab shows both active treatment and the open indicator. A focused card that is open in a tab shows the focus treatment (which already implies open).

### No-Mux Session Indicator (--no-mux / --oneshot)

Sessions without terminal backing display a **CMD badge** to distinguish them from terminal-backed sessions.

**Badge spec:**
- **Text:** `CMD` (3 chars, uppercase)
- **Font:** 9px, weight 700, letter-spacing 0.3px
- **Color:** `var(--text-muted)` (`#565f80`) text on `rgba(86, 95, 128, 0.15)` background
- **Border:** 1px solid `var(--border)` (`#2a3148`)
- **Border-radius:** 3px
- **Padding:** 1px 4px

**Position on card:** Badge row, alongside role/ctx% badges. Same visual weight as other badges.

**Position on navigator item:** Right-aligned, before the status dot. Replaces the ctx% display (no ctx% available without dump-screen).

**Behavior:** When a no-mux session is opened, the terminal pane shows either transcript (if cli_uuid available) or a centered message: "Transcript unavailable — CLI UUID not discovered" (if cli_uuid is null). No live terminal view, no activity detection, no status dot animation.

### Card Interactions

| Action | Behavior |
|---|---|
| Double-click | Open as tab (or add to active Tab Group) |
| Right-click | Context menu: Rename, Stop, View History, Delete, Add to Group |
| Single-click | Select (highlight, show in Context Panel) |

---

## 5. Tab Bar

Browser-style tabs with platform color bars and Tab Group containers.

### Tab Structure

```
[3px platform bar] [status dot] Session Name [×]
```

- **Platform color bar** — 3px left edge, same as cards and navigator
- **Status dot** — activity state (see Section 3, Activity States)
- **Session name** — 12px
- **Close button** — × on hover

### Tab Text Brightness

- **Running tabs** (green dot) — full brightness text
- **Stopped tabs** (gray dot) — muted text
- **Active tab** — full brightness + blue bottom border + slight background tint

### Keyboard Shortcuts

| Key | Action |
|---|---|
| Cmd+1-9 | Jump to tab by position |
| Cmd+Shift+[ | Previous tab (cycles) |
| Cmd+Shift+] | Next tab (cycles) |
| Cmd+W | Close current tab |

**Escape does NOT affect tabs.** Escape is a focus/pass-through key only (see Section 7, Keyboard Behavior in Prompt Box). It never closes, deactivates, or hides tabs. The only ways to close a tab are Cmd+W or click ×. (PianoMan directive, 2026-03-31.)

---

## 6. Tab Groups

Tab Groups are **containers** that hold sessions. Some sessions are visible as tabs, others are hidden inside the group. Closing a tab hides it back into the group — it does not remove it.

### Visual Treatment

- **Border:** 2px solid `#7aa2f7` (100% opacity blue). Clean, no glow.
- **Background:** Subtle blue tint (`rgba(122,162,247,0.10)`)
- **Group header tab:** Slightly more prominent than a regular tab, but not dramatically different. Shows group name + session count badge.
- **"+N" indicator:** Shows count of hidden sessions. Click to open group popup.

### States

| State | Appearance |
|---|---|
| **Collapsed** | Single tab: group name + count badge. All sessions hidden. |
| **Expanded** | Group bracket in tab bar showing header + visible tabs + "+N more". |

### Group Popup

Accessed by double-clicking a collapsed group, or clicking "+N more" on an expanded group.

Shows all sessions in the group:
- "Open" tag on sessions that are currently visible as tabs
- Double-click a hidden session to surface it as a tab
- Right-click → "Remove from Group" to take a session out entirely
- Right-click → "Open as Split" for multi-pane layout

### Lifecycle

| Action | Behavior |
|---|---|
| **Create** | Select tabs → right-click → "Create Group". Or drag tab onto another tab. |
| **Add** | Drag tab into group. Or right-click → "Add to Group". Or double-click session from navigator. |
| **Hide** | Close (×) a tab inside a group → hidden, not removed. "+N" updates. |
| **Surface** | Click "+N" or double-click in popup → becomes visible tab again. |
| **Remove** | Right-click → "Remove from Group" → standalone tab or closes. |
| **Ungroup** | Right-click group header → "Ungroup" → all sessions become standalone tabs. |

### Tab Groups and Split View

Split view is a layout property of a Tab Group, not a separate concept. Grid layouts:

| Visible Sessions | Layout |
|---|---|
| 1 | Full width |
| 2 | 2×1 (vertical) or 1×2 (horizontal) |
| 3-4 | 2×2 grid |

### Tab Groups vs Navigator Groups

Independent. No automatic linking.

**Bridge:** A Navigator Group's "Open as Tab Group" button creates a Tab Group from its sessions. But the two don't stay synchronized — they're created from a navigator group but live independently after that.

**Double-clicking a Tab Group header** shows its member sessions as cards in the center pane.

---

## 7. Prompt Box

Enhanced input at the bottom of the center area.

### Two-Step Submit

```
Prompt Box → Cmd+Enter → CLI Prompt Bar (focused pane) → Enter → CLI
```

The prompt box is the **compose-and-aim** tool. The CLI's own prompt bar (`❯`) is the **fire** button.

| Path | Flow |
|---|---|
| **Deliberate** | Type in prompt box → Cmd+Enter stages text in focused pane's CLI prompt → editable → Enter sends |
| **Fast** | Type directly in terminal pane → Enter sends immediately |

### Staging

When text is staged from the prompt box into a pane's CLI prompt bar:
- The CLI prompt bar shows the staged text (editable)
- A "staged · Enter to send" indicator appears
- User can edit, switch focus to a different pane, or press Enter to send

### Focus Targeting

- **Prompt box shows target:** "→ Front-end Designer" indicating where Cmd+Enter will stage
- **Click a pane** to switch focus target
- **Cmd+1-4** to switch focus by position (in split view)
- **Escape** returns focus to the prompt box

### Focus Indicators

| Indicator | Location |
|---|---|
| Blue outline (2px) | Around focused pane |
| "FOCUS" tag | In pane header |
| "→ target name" | In prompt box |
| Dimmed chevron | Unfocused panes' CLI prompt |
| Prompt box border highlight | When prompt box has focus (vs terminal pane) |
| Terminal pane border highlight | When terminal pane has focus (vs prompt box) |

**Prompt box vs terminal focus** must be visually distinct — the user needs to know at a glance whether keystrokes are going to the prompt box (composing) or the terminal pane (live CLI interaction). The prompt box gets a brighter border and subtle glow when focused; the terminal pane's blue outline intensifies when it has focus.

### Per-Session State

Each session maintains its own prompt text. Switching tabs preserves unsent text.

### History

Separate histories for user messages and commands:

| Type | Source | Navigation |
|---|---|---|
| User messages | Rebuilt from JSONL | Up/Down arrow |
| Commands | Persisted file | TBD |

### `!history` Command

Popup with paginated prompt history. Actions: Copy, Edit & Send, Re-send, Jump to, Rewind to, Fork from.

### Auto-sizing

- Default minimum lines, auto-grow to max
- Auto-shrink when content decreases
- Resize handle above for manual override
- Manual resize resets on tab switch

### Command Modes

The prompt box is a multi-modal input:

| Prefix | Mode | Output | Examples |
|---|---|---|---|
| (none) | Prompt | Stages to CLI via Cmd+Enter | Regular conversation |
| `!` | App command | Command-specific (popup, panel, etc.) | `!history`, `!help` |
| `$` | Shell | Output area above prompt box | `$ git status`, `$ ls` |

### Shell Mode (`$` prefix)

`$ command` executes bash in the focused session's working directory. Output stays in the prompt box area — it is **not** sent to the CLI.

**Output area:**
- Appears above the prompt box when a `$` command returns
- Monospace, scrollable, max height before scrolling
- Dismissible (Escape or click ×)
- Persists until dismissed or next command replaces it
- "Send to CLI" action available on the output area (stages command into the CLI prompt bar)
- Copy/paste from the output is natural (selectable text)

**Use cases:**
- Practice runs — get a command right before sending it to the CLI
- Quick checks — `$ git status`, `$ ls`, system info commands without cluttering the conversation

### `!history` Command

Popup with paginated prompt history:
- One-line truncated display per prompt, hover for full text
- Most recent at bottom, older going up
- Arrow key navigation, sliding window pagination
- Actions (same as transcript user prompt context menu): Copy, Edit & Send, Re-send, Jump to, Rewind to, Fork from

### Submit Key

**Cmd+Enter** to stage (replaces Enter for submit). Prevents accidental submission of multi-line prompts.

### Auto-sizing

- Default minimum lines, auto-grow to max
- Auto-shrink when content decreases
- Resize handle above for manual override
- Manual resize resets on tab switch

### Keyboard Behavior in Prompt Box

| Key | Behavior |
|---|---|
| **Tab** | Inserts indent (tab/spaces) into text. Does NOT cycle UI elements. |
| **Cmd+Enter** | Stage to focused pane |
| **Escape** | Returns focus to terminal pane. Does NOT close the session pane. |
| **Up/Down** | History navigation (when at first/last line) |

### Pass-through

**Double-Esc** in the terminal pane passes straight through to the CLI (clears the CLI prompt bar). The app does not intercept it.

**Escape** in the terminal pane does NOT close the session pane — it only affects the CLI's own behavior (e.g., canceling inline edit). Session panes are not dismissible via Escape.

---

## 8. Transcript Panel

A slide-over panel for reviewing session conversation history. Primary use case: **review** — understanding what happened in a session.

### Presentation

- **Slide-over** from the right side of the center pane, overlaying ~50% of the terminal
- **Resizable** left edge (drag handle, same 2px bright border style)
- **Refresh button** in the transcript header
- **Toggle** via toolbar button + keyboard shortcut (current behavior preserved)
- Terminal remains visible behind the transcript for reference
- **Stopped sessions:** Transcript takes full width of the center pane (no terminal underneath to show)
- **Stays visible when navigating:** Pull-out transcript remains open when switching to other tabs/cards. This enables viewing a transcript while interacting with a different session — useful for copying content between sessions. Dismissed only by explicit close (× or toggle).

### Block Types and Colors

| Block | Bar Color | Text Color | Default State |
|---|---|---|---|
| User prompt | Blue `#7aa2f7` | Light blue tint `#c5d5f9` | Visible, expanded |
| AI response | Amber `#e0af68` | Brightest `#d0d8f0` | Visible, expanded |
| Tool calls | Green `#9ece6a` | Secondary `#8890b0` | Visible, **collapsed** |
| Thinking | Purple `#bb9af7` | Secondary | **Hidden** (filter off) |
| System | Gray `#3d4663` | Muted | **Collapsed** to summary line |

**Color rationale:** AI responses (amber) are the primary review content and get the most visual prominence. Tool calls (green) recede — tool names like `Read`, `Write` no longer jump out. User prompts (blue) are distinct but not competing with AI responses.

### Visual Structure

- **4px left bar** per block, spanning full height, with gap (margin) from content
- **Exchanges grouped** — user prompt + AI response visually paired, exchange boundary is the primary rhythm
- **All blocks collapsible** — ▼ expanded, ▶ collapsed with one-line preview
- **Tool calls nested** inside AI responses — collapsed by default, expandable
- **Hover actions** — Copy and Jump buttons appear on hover per message (not cluttering default view)

### Filter Bar

Checkboxes at top: User (on), AI (on), Tools (on), Thinking (off). Plus Cmd+F search.

### Context Menus (per block type)

Right-click any block for actions scoped to that block type:
- **All types:** Copy, Collapse/Expand this block
- **User:** Jump to in terminal, Rewind to here, Fork from here
- **All types (bulk):** Collapse All / Expand All / Hide All (applies to that block type across entire transcript)

### Scroll Behavior

- **Default:** starts at bottom (most recent exchange visible)
- **Manual scroll up:** position persists while session is open
- **Scroll to bottom:** re-enables auto-follow for new content
- **Cmd+Home / Cmd+End:** jump to top/bottom

---

## 9. Right Panel (Context Panel)

Tabbed panel providing contextual information for the focused session. Current implementation preserved — no significant redesign needed.

- **Width:** 280px default, resizable, collapsible
- **Behavior:** slides out and compresses center pane (not an overlay)
- **Closed by default** on startup
- **Close affordance:** × button in the panel header (top-right corner). Must be discoverable — double-click on resize handle also closes, but users won't find that. The × button is the primary close mechanism.

### Panel Open/Close

All collapsible panels (Context Panel, Bottom Panel) must have:
1. **× button** in the panel header — primary close mechanism
2. **Double-click resize handle** — secondary (power-user)
3. **Keyboard shortcut** (TBD) — tertiary
4. **Programmatic toggle** via Component API

This was a gap in the original design. The UCI version had close buttons; the v3 design omitted them. Added 2026-03-31 per PianoMan feedback.

### Tabs

| Tab | Content |
|---|---|
| **Session Details** | Full session metadata with click-to-copy |
| **Docs** | Documents loaded by the session |
| **Memories** | Memory slots loaded/written by the session |
| **Messages** | Inter-session messages (direct + broadcasts) |
| **Prompts** | Queued prompts awaiting delivery |

Content updates when focused session changes. Panel state (open/closed, active tab) persists across restarts.

---

## 10. Bottom Panel

Collapsible, resizable panel at the bottom of the center area. Drag handle on top edge (2px bright border).

### Workers Tab

Shows child CLI instances grouped by status:

| Group | Default State | Content |
|---|---|---|
| **Active** | Expanded | Running worker sessions |
| **Stopped** | Collapsed | Completed/stopped workers |

**Scoping:**
- When a session is focused: show workers where `parent_tracking_id === focused session's tracking_id`
- If focused session has no workers: show "No workers for this session" with a "Show All" toggle
- "Show All" displays all workers across all sessions
- Sessions without a parent are "Unaffiliated"

Worker cards use the same compact card style as the navigator, with platform bar, name, status dot.

**Promote Worker to Chat:**
- Context menu on worker card → "Promote to Chat"
- Changes `type` from `worker` to `chat`
- Session appears in navigator as a regular chat session
- **Parent-child relationship is preserved** — `parent_tracking_id` does not change
- The session simply becomes visible/accessible as a first-class chat while retaining its lineage

### Logs Tab

Per-session log file viewer scoped to the focused session.

- Reads log files associated with the session (hook output, action logs, etc.)
- If multiple log files exist: sub-tabs or dropdown to switch
- **Monospace, minimal formatting** — it's log output
- **Tailing:** auto-follows new lines. Manual scroll up sticks. Scroll to bottom resumes auto-follow.

### App Log Tab

Application-wide event log — session discoveries, stops, group operations, errors. Not scoped to any particular session.

---

## 11. Session Lifecycle

### States

```
Running → Stopped → (Resume) → Running
Running → Finalize → Wrap-up conversation → Stop → Archived
Stopped → Resume → Finalize → Wrap-up conversation → Stop → Archived
```

### Activity States

Beyond the basic running/stopped status, sessions have finer-grained **activity states** that drive badges, decorators, and notifications:

| Activity State | Indicator | Badge/Decorator | Notification |
|---|---|---|---|
| **Responding** | Animated pulse on status dot | Animated icon in tab | None |
| **Idle** | Static green dot | None | None |
| **Blocked** | Orange/yellow dot | ⚠ badge on tab and card | macOS notification: "Session X is blocked" |
| **Permission prompt** | Orange dot + attention ring | 🔑 badge on tab and card | macOS notification: "Session X needs approval" |
| **Error** | Red dot | ❌ badge | macOS notification: "Session X encountered an error" |
| **Stopped** | Gray dot | None | None |

**macOS notifications:** The app uses native macOS notifications for states requiring user attention (blocked, permission prompt, error). These are especially important when the app is not in focus or the session is not the active tab.

Activity states are derived from polling/events, not user-set. They affect the `status` and related fields in the Session entity.

### Finalize Flow

Finalize is an **active process** — the session must be running (or resumed) to receive the wrap-up prompt.

1. **User triggers finalize** — context menu on card/tab, or `!finalize` command
2. **Wrap-up prompt fires** — structured prompt asking the CLI to produce:
   - Lessons learned
   - Things to remember (memory updates)
   - Persona model changes
   - Key decisions made
   - Unfinished work / handoff notes
3. **Session responds** with wrap-up content
4. **User reviews** — can edit, add, or skip sections
5. **Export/condensation** may run (future pipeline integration)
6. **Session stops and moves to Archive**

### Archive Behavior

- Archived sessions **hidden** from navigator by default
- Visible when "Show Archived" filter is enabled
- Appear in a dedicated "Archived" group
- Transcript and logs remain accessible
- Can be un-archived if needed (resume from archive)

---

## 12. Color System (Updated)

### Palette

```css
--bg-deep:       #0a0c10   /* deepest background */
--bg-panel:      #12151c   /* panel backgrounds */
--bg-card:       #1a1e2a   /* card/input backgrounds */
--bg-hover:      #222838   /* hover state */
--border:        #2a3148   /* subtle borders */
--border-strong: #3d4663   /* card borders, internal dividers */
--border-bright: #606d94   /* panel boundaries (2px) */
--text:          #d0d8f0   /* primary text */
--text-sec:      #8890b0   /* secondary text */
--text-muted:    #565f80   /* muted/disabled text */
```

### Platform Colors

| Platform | Color | Usage |
|---|---|---|
| Claude | `#ff9e64` (orange) | Bars, icons, badges |
| Codex | `#bb9af7` (purple) | Bars, icons, badges |
| Gemini | `#7aa2f7` (blue) | Bars, icons, badges |

### Status Colors

| Status | Color |
|---|---|
| Running/Active | `#9ece6a` (green) |
| Warning/Context | `#e0af68` (yellow) |
| Error/Critical | `#f7768e` (red) |

### Key Changes from v1

- Panel borders: 1px `#333a4a` → 2px `#606d94` (+70% luminance, doubled width)
- Card borders: `#333a4a` → `#3d4663`
- Text sizes bumped: session names 14px, meta text 12px, group headers 13px semibold
- Tab Group: solid `#7aa2f7` border (100% opacity)
- No opacity dimming for stopped state

---

## 13. Action Buttons

### Navigator Bottom Bar

**+ New Session** button with dropdown:

| Option | Behavior |
|---|---|
| **Claude** | Quick launch with defaults |
| **Codex** | Quick launch with defaults |
| **Gemini** | Quick launch with defaults |
| **Custom...** | Opens Custom Launch dialog |

**Search** button — opens search panel in center pane (current behavior).

### Custom Launch Dialog

Exposes CLI wrapper parameters in a GUI form:

| Parameter | Control | Required |
|---|---|---|
| Platform | Claude / Codex / Gemini radio buttons | Yes |
| Role | Dropdown: chat, dev_lead, librarian, custodian, peer_review, tester, researcher, validator | No (default: chat) |
| Working directory | Path picker (default: ai_root) | No |
| Session name | Text input (auto-generated if blank) | No |
| Model | Dropdown (platform-specific options) | No |
| Prompt | Textarea + file attachment zone | No |
| System prompt additions | Textarea + file attachment zone | No |
| Auto mode | Checkbox | No |
| Parent session | Dropdown of running sessions, or "none" | No |

### File Attachments

The Prompt and System Prompt fields each support file attachments:
- **Drag-and-drop** or **click to browse**
- Attached files shown as pills/chips: filename + size + × to remove
- Multiple files allowed
- Files are passed **by reference** (file paths) to the CLI wrapper — the CLI reads them

### Drag-and-Drop (Global)

Consistent file drop behavior everywhere:

| Drop Target | Behavior |
|---|---|
| **Prompt box** | Adds file path reference (shown as pill/chip above textarea) |
| **Terminal pane** | Sends file path to CLI stdin |
| **Custom launch dialog** | Adds to prompt/system prompt attachment list |

Pattern: drop a file anywhere you can type → it becomes a path reference.

---

## 14. Consistent Visual Language

Platform identification uses the same visual element everywhere:

| Location | Element |
|---|---|
| Navigator items | 3px left-edge color bar |
| Session cards | 3px left-edge color bar |
| Tabs | 3px left-edge color bar |
| Pane headers | 3px left-edge color bar |

This creates instant, consistent platform identification across all components.

---

## 15. Cross-References to Architecture Docs

This design doc is aligned with:

- **session_identity_v4.2.md** — Tracking ID format (`_NNN` three-digit rolling index, UTC timestamps, atomic mkdir allocation), three data stores (registry, sessionInfo dirs, app state), wrapper-generated IDs, no fswatch/breadcrumbs
- **uai_architecture_v0.2.md** — Tech stack (Electron + xterm.js + node-pty + tmux), substrate abstraction, platform adapter layer, component API layer

**Architecture questions resolved by this design:**
- **Open Q1 (session list vs navigator):** Navigator is the left panel, cards appear in center pane when browsing. No flat session list.
- **Open Q2 (group persistence):** Auto groups are rebuildable from session attributes. Custom groups persist in app state. Archived sessions retain group memberships.

**Tech stack impact:** The decided stack (Electron + xterm.js + node-pty + tmux) eliminates the zellij iframe layer. All terminal references in this design doc describe the **logical** terminal pane — the implementation is now xterm.js direct in the Electron renderer, connected via node-pty to `tmux attach-session`. No cross-origin barriers, no keyboard filter workarounds, no custom link handlers.

---

## 16. Still Pending

- Search panel design
- Filter/Group/Sort dropdown detailed designs
- Context menu complete catalog
- Full app frame composite mockup with all panels
- General button design language (primary, secondary, destructive styles)
- Finalize wrap-up prompt template design

---

## 17. Future Considerations (v2-3 Scope)

Documented here so v1 architecture doesn't preclude these features. **None of this is v1 scope.**

### 17.1 Multi-AI Chats

Three modes, increasing complexity:

| Mode | Description | Scope |
|---|---|---|
| **Broadcast (User → N AIs)** | User sends one prompt, N AIs each receive it independently. Responses compared side-by-side or collected. | v2 |
| **Orchestrated (1 AI → N AIs)** | One AI delegates to N others. Already partially supported via parent-child + worker dock. | v2 |
| **Group Chat (M AIs → N AIs)** | Multiple AIs in a shared conversation. Parallel delivery, responses consolidated into a single annotated prompt with per-participant attribution. App manages consolidation with human-in-the-loop and autonomous modes. | v3 |

**Broadcast** is the nearest-term need. Could leverage Tab Groups (create N sessions, send same prompt, view in grid layout) with a lightweight broadcast mechanism on top.

**Group Chat** requires:
- A "virtual session" or "room" concept that is not a single CLI session
- Consolidation logic: collect N responses → annotate → compose next prompt
- Turn management: parallel delivery, configurable wait/timeout
- Attribution: each AI's contribution clearly marked in the consolidated view
- Human-in-the-loop: user can edit consolidated prompt before delivery, or let it auto-send

### 17.2 Non-CLI Sessions (Web UI)

The v1 model assumes every session is a CLI process in a terminal. Future versions must support **Web UI sessions** — AI conversations running in browser tabs (claude.ai, chatgpt.com, gemini.google.com, etc.).

Web UI sessions differ fundamentally:

| Aspect | CLI Session | Web UI Session |
|---|---|---|
| Substrate | Terminal multiplexer (tmux/zellij) | Browser tab (CDP / Puppeteer) |
| Input | stdin / send-keys | DOM injection / clipboard paste |
| Output | dump-screen / JSONL | DOM scraping / message extraction |
| Monitoring | Terminal polling | DOM polling / MutationObserver |
| Process | Local CLI binary | Remote web service |
| Platforms | Claude CLI, Codex CLI, Gemini CLI | claude.ai, chatgpt.com, gemini.google.com, Grok, etc. |

**v1 architecture implications — do NOT assume:**
- Every session has a terminal session name
- Every session can be dump-screened
- Every session has a local JSONL file
- Every session is driven via PTY input
- The platform list is limited to CLI-equipped platforms

**v1 architecture should:**
- Keep the Session entity flexible enough for sessions without terminals
- Keep the substrate abstraction generic (a WebUISubstrate could implement send_keys via DOM injection, dump_screen via DOM scraping)
- Keep platform identification in the data model (not hard-coded to claude/codex/gemini)

### 17.3 Non-CLI Platform Colors

When Web UI sessions arrive, new platforms need visual identity:

| Platform | Color (tentative) |
|---|---|
| Claude (CLI + Web) | `#ff9e64` (orange) — existing |
| Codex (CLI) | `#bb9af7` (purple) — existing |
| Gemini (CLI + Web) | `#7aa2f7` (blue) — existing |
| ChatGPT (Web) | `#10a37f` (green) — OpenAI brand |
| Grok (Web) | TBD |

---

## 17. Mockup Reference

**Session 1** — `.superpowers/brainstorm/77092-1774854764/`:

| File | Content |
|---|---|
| `session-navigator-layout.html` | Card vs Row layout comparison |
| `card-variants.html` | Three card design variants (A: compact, B: detailed, C: left-bar) |
| `split-view-focus.html` | Split view with focus indicators and prompt staging |
| `tab-groups-v2.html` | Tab Group container model (collapsed, expanded, popup) |
| `navigator-cards-center.html` | Compact navigator + center pane cards |
| `layout-v2-fixed.html` | Full-height navigator + group membership highlights |
| `layout-v3-contrast.html` | Card states (active/stopped/focused) + tab color bars |
| `tab-group-contrast.html` | Tab Group boundary contrast options (A/B/C) |

**Session 2** — `.superpowers/brainstorm/58691-1774870121/`:

| File | Content |
|---|---|
| `transcript-panel.html` | Transcript panel v1 (original colors) |
| `transcript-v2.html` | Transcript panel v2 (swapped colors, bar gap, collapsed blocks) |
