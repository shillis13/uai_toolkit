# UAI Gap Analysis: Archived Spec → UCI Reality → New Requirements

**Date:** 2026-04-22
**Author:** Continuity (Claude CLI, Architect)
**Purpose:** Map what the original UAI designed, what UCI actually built, and what the
new UAI needs. This document is the input for the updated architecture spec.

---

## 1. Architecture Foundation

### Component API Layer

┌────────────────┬────────────────────────────────┬──────────────────────────────────┬─────────────────────────────────┐
│   **Aspect**   │   **UAI Spec (archived)**      │   **UCI Reality**                │   **New UAI Need**              │
├────────────────┼────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────┤
│ Component      │ Fully specified per component  │ Not implemented. State in        │ Carry forward spec. Add command │
│ get/set/up     │                                │ useState hooks.                  │ result types `{ ok, previous,   │
│ date/delete    │                                │                                  │ effects }`.                     │
├────────────────┼────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────┤
│ Dot-path keys  │ `filter.platform`,             │ Not implemented.                 │ Carry forward.                  │
│                │ `tabs.active`                  │                                  │                                 │
├────────────────┼────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────┤
│ Event system   │ `EventBus.on/emit` with        │ Not implemented. Polling every   │ Carry forward. Add fine-grained │
│                │ standard events                │ 5s + ad-hoc `refreshSessions()`. │ per-path subscriptions.         │
├────────────────┼────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────┤
│ Testing        │ `C.get(key)` === expected, no  │ 222 unit tests, but mostly       │ Carry forward. This is the      │
│ contract       │ DOM                            │ testing isolated functions, not  │ primary testing strategy.       │
│                │                                │ component state.                 │                                 │
├────────────────┼────────────────────────────────┼──────────────────────────────────┼─────────────────────────────────┤
│ Debug          │ Mentioned as extension of      │ Not implemented.                 │ Carry forward.                  │
│ inspectability │ Debug API                      │                                  │                                 │
└────────────────┴────────────────────────────────┴──────────────────────────────────┴─────────────────────────────────┘

### Data Architecture

┌────────────────┬──────────────────┬────────────────────────────────────────┬─────────────────────────────────────────┐
│   **Aspect**   │   **UAI Spec**   │   **UCI Reality**                      │   **New UAI Need**                      │
├────────────────┼──────────────────┼────────────────────────────────────────┼─────────────────────────────────────────┤
│ Session Store  │ Three stores:    │ SessionManager merges from             │ **External ground truth principle.**    │
│ (single truth) │ registry,        │ session_store.py (SQLite) +            │ App reflects external state. Multiple   │
│                │ sessionInfo      │ app_state.json. Works but opaque.      │ writers (app, wrappers, scripts) write  │
│                │ dirs, app_state  │                                        │ to same stores. No divergent copies.    │
├────────────────┼──────────────────┼────────────────────────────────────────┼─────────────────────────────────────────┤
│ Idempotent     │ Specified as     │ Partially — sessions rebuildable from  │ Strengthen. App state that isn't        │
│ rebuild        │ requirement      │ SQLite + filesystem. App state (tabs,  │ rebuildable should be explicitly        │
│                │                  │ pinned, notes) not rebuildable.        │ identified and backed up.               │
├────────────────┼──────────────────┼────────────────────────────────────────┼─────────────────────────────────────────┤
│ Data ownership │ Wrappers own     │ Mostly followed. SessionManager writes │ Formalize ownership map for all fields  │
│                │ identity, app    │ pinned/lastViewedAt/notes/typeto       │ including new entities (Teams,          │
│                │ owns UI state    │ app_state.json.                        │ Projects, Tags, Briefs).                │
├────────────────┼──────────────────┼────────────────────────────────────────┼─────────────────────────────────────────┤
│ Persistence    │ JSON files       │ SQLite (session_store.py) +            │ Keep SQLite + JSON split. Add schema    │
│                │                  │ app_state.json + folders.json          │ versioning for external state           │
│                │                  │                                        │ evolution.                              │
└────────────────┴──────────────────┴────────────────────────────────────────┴─────────────────────────────────────────┘


### Command System

┌────────────────┬──────────────────┬─────────────────────────────────┬────────────────────────────────────────────────┐
│   **Aspect**   │   **UAI Spec**   │   **UCI Reality**               │   **New UAI Need**                             │
├────────────────┼──────────────────┼─────────────────────────────────┼────────────────────────────────────────────────┤
│ Command bus    │ Not designed     │ Not implemented. Actions are    │ **NEW.** Typed command hierarchy with          │
│                │                  │ `onClick → handler → setState`. │ entry/exit hooks. Every mutation goes through  │
│                │                  │                                 │ the bus.                                       │
├────────────────┼──────────────────┼─────────────────────────────────┼────────────────────────────────────────────────┤
│ Command        │ Not designed     │ N/A                             │ **NEW.** Commands have parents. Inheritance    │
│ hierarchy      │                  │                                 │ enables global behaviors (logging, undo).      │
├────────────────┼──────────────────┼─────────────────────────────────┼────────────────────────────────────────────────┤
│ Command origin │ Not designed     │ N/A                             │ **NEW.** Every command knows:                  │
│ tracking       │                  │                                 │ user-interaction, internal-component,          │
│                │                  │                                 │ external-api, embedded-ai, debug-console.      │
├────────────────┼──────────────────┼─────────────────────────────────┼────────────────────────────────────────────────┤
│ Undo           │ Not designed     │ Not implemented.                │ Enabled by command result types. Not required  │
│                │                  │                                 │ for Phase 0 but architecture must support it.  │
└────────────────┴──────────────────┴─────────────────────────────────┴────────────────────────────────────────────────┘

---

## 2. Entity Model

### Sessions

┌───────────────┬────────────────────────────┬───────────────────────────────────┬─────────────────────────────────────┐
│ **Aspect**    │ **UAI Spec**               │ **UCI Reality**                   │ **New UAI Need**                    │
├───────────────┼────────────────────────────┼───────────────────────────────────┼─────────────────────────────────────┤
│ Primary key   │ TrackingId                 │ TrackingId (wrapper-generated).   │ Add: app-generated draft            │
│               │ (wrapper-generated)        │ Works.                            │ TrackingIds. Status field: `draft → │
│               │                            │                                   │ pending → confirmed`.               │
├───────────────┼────────────────────────────┼───────────────────────────────────┼─────────────────────────────────────┤
│ Identity IDs  │ Three-ID model: TrackingId │ TrackingId + cli_session_id +     │ Carry forward three-ID model.       │
│               │ + CLI UUID + Terminal      │ zellij_session. All three used.   │ Entity model must explicitly list   │
│               │ Session Name               │                                   │ all three as identity fields with   │
│               │                            │                                   │ lifecycle (when set, mutability).   │
├───────────────┼────────────────────────────┼───────────────────────────────────┼─────────────────────────────────────┤
│ Fields        │ 17 fields in spec          │ ~35 fields (added tags, notes,    │ Audit and categorize all fields by  │
│               │                            │ transcript_path, context_percent, │ ownership (wrapper-owned,           │
│               │                            │ lastCreatedBriefAt, etc.)         │ app-owned, runtime-only).           │
├───────────────┼────────────────────────────┼───────────────────────────────────┼─────────────────────────────────────┤
│ Session types │ chat, worker               │ chat, worker                      │ Add: team_member (session that's    │
│               │                            │                                   │ part of a Team). Or keep type       │
│               │                            │                                   │ simple and track team membership    │
│               │                            │                                   │ separately.                         │
├───────────────┼────────────────────────────┼───────────────────────────────────┼─────────────────────────────────────┤
│ Activity      │ idle, responding, blocked, │ running, idle, stopped, archived. │ Restore full activity state         │
│ states        │ permission_prompt, error,  │ No responding/blocked detection.  │ detection. Requires screen parsing  │
│               │ stopped                    │                                   │ (platform adapter).                 │
├───────────────┼────────────────────────────┼───────────────────────────────────┼─────────────────────────────────────┤
│ Relationships │ parent_tracking_id,        │ spawned_by, children. Plus typed  │ Carry forward typed links. Extend   │
│               │ children_tracking_ids      │ links (forked_from, briefed_to,   │ for Team membership, Project        │
│               │                            │ etc.) via SQLite                  │ membership.                         │
│               │                            │ entity_relationships.             │                                     │
└───────────────┴────────────────────────────┴───────────────────────────────────┴─────────────────────────────────────┘

### Briefs (NEW — not in archived UAI)

┌────────────┬────────────────────────────────────────────────────┬────────────────────────────────────────────────────┐
│ **Aspect** │ **UCI Reality**                                    │ **New UAI Need**                                   │
├────────────┼────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
│ Data model │ BriefMeta YAML files at                            │ Carry forward. Brief is an entity alongside        │
│            │ ai_general/data/session_briefs/                    │ Session.                                           │
├────────────┼────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
│ Links      │ Typed bidirectional links (briefed_to/brief_of,    │ Carry forward via entity_relationships.            │
│            │ loaded/loaded_by)                                  │                                                    │
├────────────┼────────────────────────────────────────────────────┼────────────────────────────────────────────────────┤
│ UI         │ BriefCard, BriefDialog, browse view, context menus │ Carry forward visual design. Integrate into Tabbed │
│            │                                                    │ Navigator.                                         │
└────────────┴────────────────────────────────────────────────────┴────────────────────────────────────────────────────┘

### Projects (NEW — devTrees)

┌────────────┬────────────────────────────────────────────┬────────────────────────────────────────────────────────────┐
│ **Aspect** │ **Current State**                          │ **New UAI Need**                                           │
├────────────┼────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ Entity     │ devTree MCP manages git worktrees. No UI   │ First-class entity. Metadata: goal/purpose, assigned AIs,  │
│            │ entity.                                    │ linked sessions, linked briefs, working directory, branch. │
├────────────┼────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ Storage    │ devTree data on filesystem (git            │ External truth: project metadata YAML in the devTree       │
│            │ worktrees).                                │ directory itself. App reflects.                            │
├────────────┼────────────────────────────────────────────┼────────────────────────────────────────────────────────────┤
│ UI         │ Not in app.                                │ Navigator tab, Project cards, Project detail panel.        │
└────────────┴────────────────────────────────────────────┴────────────────────────────────────────────────────────────┘

### Teams (NEW)

┌────────────┬───────────────────────┬─────────────────────────────────────────────────────────────────────────────────┐
│ **Aspect** │ **Current State**     │ **New UAI Need**                                                                │
├────────────┼───────────────────────┼─────────────────────────────────────────────────────────────────────────────────┤
│ Entity     │ Not implemented.      │ First-class entity. A composition of AI profiles with role assignments, comms   │
│            │                       │ routing, and shared context.                                                    │
├────────────┼───────────────────────┼─────────────────────────────────────────────────────────────────────────────────┤
│ Storage    │ N/A                   │ Team definition YAML (external). Team runtime state in app.                     │
├────────────┼───────────────────────┼─────────────────────────────────────────────────────────────────────────────────┤
│ UI         │ N/A                   │ Navigator tab, Team cards, Team management panel. Tab Groups seeded from Teams. │
├────────────┼───────────────────────┼─────────────────────────────────────────────────────────────────────────────────┤
│ Comms      │ messages MCP exists   │ Extend: team-scoped addressing, inner-team routing, reply-with-prompt           │
│            │ for direct/broadcast. │ enforcement.                                                                    │
└────────────┴───────────────────────┴─────────────────────────────────────────────────────────────────────────────────┘

### Tags (NEW — partial in UCI)

┌────────────┬──────────────────────────────────────────────────┬──────────────────────────────────────────────────────┐
│ **Aspect** │ **UCI Reality**                                  │ **New UAI Need**                                     │
├────────────┼──────────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ Data model │ `tags` field on Session. Only used for           │ General-purpose tag system. Tags as entities with    │
│            │ "condenser" tag.                                 │ name, color, icon.                                   │
├────────────┼──────────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ Storage    │ Tags stored in app_state.json per-session and    │ Consolidate to SQLite. Tags are their own table.     │
│            │ SQLite card_tags.                                │                                                      │
├────────────┼──────────────────────────────────────────────────┼──────────────────────────────────────────────────────┤
│ UI         │ Condenser checkbox in FilterBar.                 │ Tag management UI. Bulk tag operations (multi-select │
│            │                                                  │ → add/remove tags). Filter by tags in Navigator.     │
└────────────┴──────────────────────────────────────────────────┴──────────────────────────────────────────────────────┘

---

## 3. UI Components

### Session Navigator (Left Panel)
┌───────────────────┬───────────────────┬───────────────────────────────────────┬──────────────────────────────────────┐
│   **Aspect**      │   **UAI Spec**    │   **UCI Reality**                     │   **New UAI Need**                   │
├───────────────────┼───────────────────┼───────────────────────────────────────┼──────────────────────────────────────┤
│ Design            │ 240px             │ NavigationPanel with folder tree,     │ **Tabbed Navigator.** Tabs for:      │
│                   │ full-height,      │ tri-counts. Different approach —      │ Sessions, Briefs, Teams, Projects.   │
│                   │ compact items     │ folders instead of dynamic groups.    │ Each tab has its own                 │
│                   │ (bar, name, ctx%, │                                       │ filter/sort/group. Folders carry     │
│                   │ dot)              │                                       │ forward within Sessions tab.         │
├───────────────────┼───────────────────┼───────────────────────────────────────┼──────────────────────────────────────┤
│ Filter/Group/Sort │ Fully specified   │ FilterBar with status pills, platform │ Merge: keep FilterBar pill approach  │
│                   │ dropdowns         │ pills, date range, condensers,        │ (compact), add Group modes from UAI  │
│                   │                   │ unaffiliated. CardListView has sort.  │ spec. Sort already implemented.      │
├───────────────────┼───────────────────┼───────────────────────────────────────┼──────────────────────────────────────┤
│ Interactions      │ Single-click      │ Single-click opens tab (UCI).         │ Decide: UCI's direct-click-to-open   │
│                   │ select,           │                                       │ is faster. UAI's select-then-open is │
│                   │ double-click open │                                       │ more standard. Lean toward UCI       │
│                   │                   │                                       │ behavior.                            │
└───────────────────┴───────────────────┴───────────────────────────────────────┴──────────────────────────────────────┘

### Workspace (Center)

┌────────────────┬───────────────────────┬─────────────────────────────────────────┬───────────────────────────────────┐
│   **Aspect**   │   **UAI Spec**        │   **UCI Reality**                       │   **New UAI Need**                │
├────────────────┼───────────────────────┼─────────────────────────────────────────┼───────────────────────────────────┤
│ Tab Bar        │ Platform bars, status │ TabBar with platform icons, status      │ Add Tab Groups (#7), Grid View    │
│                │ dots, Tab Groups      │ dots, context menus. No Tab Groups.     │ (#8).                             │
├────────────────┼───────────────────────┼─────────────────────────────────────────┼───────────────────────────────────┤
│ Session Pane   │ Terminal mode +       │ FocusPane switches between CardListView │ Formalize modes. Add Grid View    │
│                │ Transcript mode       │ (browse) and terminal/transcript.       │ (1x1, 2x1, 1x2, 2x2).             │
├────────────────┼───────────────────────┼─────────────────────────────────────────┼───────────────────────────────────┤
│ Browse mode    │ Card Grid when no tab │ CardListView with session cards, sort,  │ Carry forward. Extend for Brief   │
│                │ focused               │ search, select.                         │ cards, Project cards, Team cards  │
│                │                       │                                         │ per Navigator tab.                │
└────────────────┴───────────────────────┴─────────────────────────────────────────┴───────────────────────────────────┘

### Prompt Box

┌───────────────────┬──────────────────────────────────┬───────────────────────────┬───────────────────────────────────┐
│   **Aspect**      │   **UAI Spec**                   │   **UCI Reality**         │   **New UAI Need**                │
├───────────────────┼──────────────────────────────────┼───────────────────────────┼───────────────────────────────────┤
│ Core              │ Cmd+Enter stage, per-session     │ Implemented. Stage prompt │ Carry forward.                    │
│                   │ state, auto-size                 │ works. Auto-grow works.   │                                   │
├───────────────────┼──────────────────────────────────┼───────────────────────────┼───────────────────────────────────┤
│ Command modes     │ ! prefix (app commands), $       │ Not implemented in UCI.   │ Implement per spec.               │
│                   │ prefix (shell)                   │                           │                                   │
├───────────────────┼──────────────────────────────────┼───────────────────────────┼───────────────────────────────────┤
│ History           │ Up/Down arrow, !history popup    │ Not implemented.          │ Implement per spec.               │
│                   │ with actions                     │                           │                                   │
├───────────────────┼──────────────────────────────────┼───────────────────────────┼───────────────────────────────────┤
│ **NEW: Rewrite**  │ Not designed                     │ N/A                       │ Send prompt to LLLM/embedded AI,  │
│                   │                                  │                           │ replace prompt text with rewrite. │
├───────────────────┼──────────────────────────────────┼───────────────────────────┼───────────────────────────────────┤
│ **NEW: Pre/post   │ `[CURATE]` noted in spec,        │ N/A                       │ Per-session config for pre-prompt │
│ prompt**          │ deferred                         │                           │ and post-prompt addendums.        │
│                   │                                  │                           │ Periodic reminders on turn count. │
├───────────────────┼──────────────────────────────────┼───────────────────────────┼───────────────────────────────────┤
│ **NEW: Markdown   │ Not designed                     │ N/A                       │ Toggle between raw text and       │
│ toggle**          │                                  │                           │ rendered markdown view.           │
└───────────────────┴──────────────────────────────────┴───────────────────────────┴───────────────────────────────────┘

### Transcript Viewer

┌────────────┬───────────────────────────────┬─────────────────────────────────┬───────────────────────────────────────┐
│ **Aspect** │ **UAI Spec**                  │ **UCI Reality**                 │ **New UAI Need**                      │
├────────────┼───────────────────────────────┼─────────────────────────────────┼───────────────────────────────────────┤
│ Layout     │ Slide-over right panel,       │ Implemented — overlay or        │ Carry forward.                        │
│            │ resizable                     │ inline, resizable.              │                                       │
├────────────┼───────────────────────────────┼─────────────────────────────────┼───────────────────────────────────────┤
│ Blocks     │ User (blue), AI (amber), Tool │ User (blue), Response (green),  │ Reconcile. UAI spec colors had better │
│            │ (green), Thinking (purple),   │ Tool (amber), Thinking          │ rationale (AI amber = primary review  │
│            │ System (gray)                 │ (purple). Colors differ from    │ content). Discuss with PianoMan.      │
│            │                               │ spec.                           │                                       │
├────────────┼───────────────────────────────┼─────────────────────────────────┼───────────────────────────────────────┤
│ Filters    │ User, AI, Tools, Thinking     │ User, Response, Tools, Thinking │ Carry forward.                        │
│            │ checkboxes                    │ checkboxes. All implemented.    │                                       │
├────────────┼───────────────────────────────┼─────────────────────────────────┼───────────────────────────────────────┤
│ Copy       │ Per-block, per-turn, per-day, │ Fully implemented including     │ Carry forward. Tool call copy bug     │
│            │ copy-all, multi-select        │ multi-select, day groups.       │ fixed (copies displayed content now). │
├────────────┼───────────────────────────────┼─────────────────────────────────┼───────────────────────────────────────┤
│ Search     │ Cmd+F with match navigation   │ Implemented with highlight,     │ Carry forward.                        │
│            │                               │ prev/next.                      │                                       │
├────────────┼───────────────────────────────┼─────────────────────────────────┼───────────────────────────────────────┤
│ Context    │ Per-block: Collapse/Expand,   │ Partially — collapse all per    │ Complete per spec.                    │
│ menus      │ Collapse All, Jump, Rewind,   │ type via right-click chevron.   │                                       │
│            │ Fork                          │ No Jump/Rewind/Fork.            │                                       │
└────────────┴───────────────────────────────┴─────────────────────────────────┴───────────────────────────────────────┘

### Context Panel (Right)

┌────────────┬───────────────────────────────────────┬─────────────────────────────────┬───────────────────────────────┐
│ **Aspect** │ **UAI Spec**                          │ **UCI Reality**                 │ **New UAI Need**              │
├────────────┼───────────────────────────────────────┼─────────────────────────────────┼───────────────────────────────┤
│ Tabs       │ Details, Docs, Memories, Messages,    │ Details tab only.               │ Implement remaining tabs. Add │
│            │ Prompts                               │                                 │ Knowledge/Traits/Roles digest │
│            │                                       │                                 │ tracking (#4).                │
├────────────┼───────────────────────────────────────┼─────────────────────────────────┼───────────────────────────────┤
│ Notes      │ Not designed                          │ Implemented — collapsible Notes │ Carry forward.                │
│            │                                       │ section in Session Details.     │                               │
├────────────┼───────────────────────────────────────┼─────────────────────────────────┼───────────────────────────────┤
│ Width      │ 280px default, resizable, collapsible │ Implemented, resizable.         │ Carry forward.                │
└────────────┴───────────────────────────────────────┴─────────────────────────────────┴───────────────────────────────┘

### Bottom Panel

┌─────────────┬─────────────────────────────────────────┬────────────────────────────────────────┬──────────────────┐
│ **Aspect**  │ **UAI Spec**                            │ **UCI Reality**                        │ **New UAI Need** │
├─────────────┼─────────────────────────────────────────┼────────────────────────────────────────┼──────────────────┤
│ Workers tab │ Scoped by parent, active/stopped groups │ WorkerDock implemented. Scoping works. │ Carry forward.   │
├─────────────┼─────────────────────────────────────────┼────────────────────────────────────────┼──────────────────┤
│ Logs tab    │ Per-session log viewer                  │ Not implemented.                       │ Implement (#10). │
├─────────────┼─────────────────────────────────────────┼────────────────────────────────────────┼──────────────────┤
│ App Log tab │ Application-wide event log              │ Not implemented.                       │ Implement (#11). │
└─────────────┴─────────────────────────────────────────┴────────────────────────────────────────┴──────────────────┘

---

## 4. Infrastructure

### Session Identity

┌────────────┬──────────────────────────────┬───────────────────────────────┬──────────────────────────────────────────┐
│ **Aspect** │ **UAI Spec (v4.2)**          │ **Current State (v5)**        │ **New UAI Need**                         │
├────────────┼──────────────────────────────┼───────────────────────────────┼──────────────────────────────────────────┤
│ Format     │ `{platform}_{YYYYMMDD}_{     │ `{YYYYMMDD}_{HHMMSS}_{uuid8}  │ Carry forward current v5 format.         │
│            │ HHMMSS}[_{NNN}]`             │ _{platform3}`                 │                                          │
├────────────┼──────────────────────────────┼───────────────────────────────┼──────────────────────────────────────────┤
│ Generator  │ CLI wrappers only            │ CLI wrappers via              │ Add: app can create draft TrackingIds.   │
│            │                              │ ai_launcher.py                │ Any authorized writer can create drafts. │
├────────────┼──────────────────────────────┼───────────────────────────────┼──────────────────────────────────────────┤
│ Storage    │ Registry (flat file) +       │ SQLite (session_store.py) +   │ Carry forward SQLite.                    │
│            │ sessionInfo dirs             │ per-session dirs              │                                          │
├────────────┼──────────────────────────────┼───────────────────────────────┼──────────────────────────────────────────┤
│ Discovery  │ Wrapper polls for            │ Same, with fswatch fallback   │ Wrapper-first. App reads finished        │
│            │ Codex/Gemini UUID            │                               │ identity.                                │
└────────────┴──────────────────────────────┴───────────────────────────────┴──────────────────────────────────────────┘

### Terminal Substrate

┌────────────────┬───────────────────────────────┬───────────────────────────────────────────┬─────────────────────────┐
│ **Aspect**     │ **UAI Spec**                  │ **UCI Reality**                           │ **New UAI Need**        │
├────────────────┼───────────────────────────────┼───────────────────────────────────────────┼─────────────────────────┤
│ Abstraction    │ SessionSubstrate ABC with     │ TmuxSubstrate in                          │ Carry forward. Tmux     │
│                │ zellij/tmux impls             │ lib_session_substrate.py. Works.          │ confirmed.              │
├────────────────┼───────────────────────────────┼───────────────────────────────────────────┼─────────────────────────┤
│ Screen parsing │ Platform adapter: `(platform, │ Partial — context_percent parsed from     │ Implement full platform │
│                │ raw_text) → structured_state` │ status bar. No responding/blocked         │ adapter per spec.       │
│                │                               │ detection.                                │                         │
└────────────────┴───────────────────────────────┴───────────────────────────────────────────┴─────────────────────────┘

### MCP Servers

┌─────────────────┬───────────────────┬────────────────────────────────────────────────────────────────────────────────┐
│ **Aspect**      │ **Current State** │ **New UAI Need**                                                               │
├─────────────────┼───────────────────┼────────────────────────────────────────────────────────────────────────────────┤
│ Count           │ 15+ MCP servers   │ Consolidate (#9). Separate stateless (guidance, knowledge-search) from         │
│                 │                   │ stateful (prompting, messages, cli-agent).                                     │
├─────────────────┼───────────────────┼────────────────────────────────────────────────────────────────────────────────┤
│ App integration │ App uses IPC, not │ Consider: should app components call MCP servers directly for some operations? │
│                 │ MCP directly      │ Or always go through main process IPC?                                         │
└─────────────────┴───────────────────┴────────────────────────────────────────────────────────────────────────────────┘

### AI Integration

┌────────────────┬───────────────────────────────────────┬─────────────────────────────────────────────────────────────┐
│ **Aspect**     │ **Current State**                     │ **New UAI Need**                                            │
├────────────────┼───────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ Local LLM      │ local-llm MCP server exists           │ Test integration (#3). Use for prompt rewrite (#5.2).       │
│                │ (reason_on_text, reason_on_file)      │                                                             │
├────────────────┼───────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ Embedded AI    │ Not implemented                       │ AI that can navigate component tree, invoke commands,       │
│                │                                       │ activate UI components. Requires command bus + component    │
│                │                                       │ API.                                                        │
├────────────────┼───────────────────────────────────────┼─────────────────────────────────────────────────────────────┤
│ AI-to-AI comms │ messages MCP (direct, broadcast).     │ Extend: reply-with-prompt enforcement, team-scoped routing, │
│                │ Prompt queues.                        │ periodic reminder delivery via pre/post prompt hooks.       │
└────────────────┴───────────────────────────────────────┴─────────────────────────────────────────────────────────────┘

---

## 5. Visual System

┌───────────────┬────────────────────────────┬──────────────────────────────┬──────────────────────────────────────────┐
│ **Aspect**    │ **UAI Spec**               │ **UCI Reality**              │ **New UAI Need**                         │
├───────────────┼────────────────────────────┼──────────────────────────────┼──────────────────────────────────────────┤
│ Color palette │ Fully specified (--bg-deep │ Partial — CSS custom         │ **Design tokens in config (#2).**        │
│               │ through --border-bright)   │ properties exist but not     │ Generate :root variables from config     │
│               │                            │ fully tokenized.             │ file. Components use tokens only.        │
├───────────────┼────────────────────────────┼──────────────────────────────┼──────────────────────────────────────────┤
│ Platform      │ Orange/Purple/Blue fully   │ Implemented. SVG platform    │ Carry forward. Extend for new platforms  │
│ colors        │ specified                  │ icons.                       │ (ChatGPT web, etc.).                     │
├───────────────┼────────────────────────────┼──────────────────────────────┼──────────────────────────────────────────┤
│ Typography    │ 14px names, 12px meta,     │ Ad-hoc sizes throughout      │ Tokenize. Type scale in config.          │
│               │ 13px headers               │ styles.css.                  │                                          │
├───────────────┼────────────────────────────┼──────────────────────────────┼──────────────────────────────────────────┤
│ Card design   │ Left-bar accent, detailed  │ Implemented. Session cards + │ Unify: all entity cards (Session, Brief, │
│               │ spec                       │ Brief cards.                 │ Project, Team) share base card pattern.  │
│               │                            │                              │ Min-height for uniform grid sizing.      │
├───────────────┼────────────────────────────┼──────────────────────────────┼──────────────────────────────────────────┤
│ styles.css    │ N/A                        │ 6000+ line monolith          │ Break into component-scoped CSS modules  │
│               │                            │                              │ or CSS-in-JS. Design tokens separate.    │
└───────────────┴────────────────────────────┴──────────────────────────────┴──────────────────────────────────────────┘

---

## 6. Process & Team (from lessons-learned.md)

### Lessons to Apply to UAI Resurrection

┌────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────────────┐
│ **Lesson**                                     │ **How to Apply**                                                    │
├────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────┤
│ **Placeholder div catastrophe** — 322 tests    │ Phase 0 vertical slice proves integration. Every Phase 1 workstream │
│ passed but app showed nothing                  │ must produce running, deployable code, not isolated components.     │
├────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────┤
│ **Structure outlasts instructions** — verbal   │ Encode architectural rules as: TypeScript interfaces                │
│ rules have message half-life                   │ (compile-time), linting rules, test assertions. Not prose in docs.  │
├────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────┤
│ **Cross-platform diversity** — same-platform   │ Use Codex or Gemini for review/testing roles, not just Claude for   │
│ testing shares blind spots                     │ everything.                                                         │
├────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────┤
│ **Agents capable but not self-sustaining** —   │ Integration checkpoints every 1-2 days. Recursive delegation        │
│ every stall traced to no pulse loop            │ includes escalation protocol.                                       │
├────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────┤
│ **Fire-and-forget prompt model** — completed   │ Command bus entry/exit hooks provide natural completion signals.    │
│ work with no notification                      │                                                                     │
├────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────────────┤
│ **Packaged app vs dev server divergence** —    │ Test packaged builds early and often. Not just at the end.          │
│ dev works, packaged doesn't                    │                                                                     │
└────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────────────┘

---

## 7. Resolved Decisions (from customer-decisions-pending.md)

These were pending in the archived UAI. UCI usage resolved them:

┌───────┬─────────────────────────────────────────────┬────────────────────────────────────────────────────────────────┐
│ **#** │ **Decision**                                │ **Resolution**                                                 │
├───────┼─────────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ 2     │ Should Escape close terminal pane?          │ **No.** Confirmed by UCI usage. Escape never closes            │
│       │                                             │ panes/tabs.                                                    │
├───────┼─────────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ 4     │ Replace [FOCUS] text tag with bright border │ **Yes.** Done in UCI.                                          │
├───────┼─────────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ 5     │ Worker panel below prompt box               │ **Yes.** Done in UCI (WorkerDock below FocusPane).             │
├───────┼─────────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ 7     │ 2x2 grid is MVCR-2, not MVCR-1              │ **Confirmed.** Grid View is a separate feature from Tab        │
│       │                                             │ Groups.                                                        │
├───────┼─────────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ 8     │ Rename "Context" panel to "Session Details" │ **Yes.** Done in UCI (RightPanel with Details tab).            │
├───────┼─────────────────────────────────────────────┼────────────────────────────────────────────────────────────────┤
│ 9     │ "Open as Tab Group" should NOT change grid  │ **Confirmed.** Tab Group = bracket in tab bar, not grid.       │
│       │ layout                                      │                                                                │
└───────┴─────────────────────────────────────────────┴────────────────────────────────────────────────────────────────┘

---

## 8. New Requirements Not in Any Prior Spec

These emerge from the 2026-04-20 architecture discussion:

┌───────┬───────────────────────────────────────────────────────┬───────────────────────────┬──────────────────────────┐
│ **#** │ **Requirement**                                       │ **Source**                │ **Priority**             │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 1     │ Command hierarchy with entry/exit hooks               │ PianoMan architecture req │ Foundation               │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 2     │ Display data (fonts, sizes, spacing) in config files  │ PianoMan architecture req │ Foundation               │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 3     │ Actionable component parent hierarchy (context        │ PianoMan architecture req │ Foundation               │
│       │ provision)                                            │                           │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 4     │ External ground truth — app reflects, doesn't diverge │ PianoMan architecture req │ Foundation               │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 5     │ Embedded AI that can call commands and navigate       │ PianoMan roadmap #5.2, #6 │ Phase 2                  │
│       │ component tree                                        │                           │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 6     │ Draft TrackingIds from any authorized writer          │ PianoMan session identity │ Phase 1                  │
│       │                                                       │ evolution                 │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 7     │ Pre/post prompt addendums with periodic reminders     │ PianoMan roadmap #5.3     │ Phase 2                  │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 8     │ Teams as first-class entity with compositions         │ PianoMan roadmap #6       │ Phase 2 (design in Phase │
│       │                                                       │                           │ 1)                       │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 9     │ Projects (devTrees) as first-class entity             │ PianoMan roadmap #1       │ Phase 1                  │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 10    │ Grid View (1x1, 2x1, 1x2, 2x2)                        │ PianoMan roadmap #8       │ Phase 1                  │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 11    │ Tab Groups (not Teams, but can be created from Teams) │ PianoMan roadmap #7       │ Phase 1                  │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 12    │ Tabbed Navigator (Sessions, Briefs, Teams, Projects)  │ PianoMan roadmap #17      │ Phase 1                  │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 13    │ Prompt rewrite via LLLM                               │ PianoMan roadmap #5.2     │ Phase 2                  │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 14    │ Session Knowledge/Traits/Roles digest tracking        │ PianoMan roadmap #4       │ Phase 1                  │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 15    │ AI-to-AI comms improvements                           │ PianoMan roadmap #14      │ Phase 2                  │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 16    │ Session-to-Session and Session-to-Brief linking UI    │ PianoMan roadmap #18      │ Phase 1                  │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 17    │ ai_launcher split (param translation vs param         │ PianoMan roadmap #20      │ Phase 1                  │
│       │ determination)                                        │                           │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 18    │ WebUI as Session (devTree)                            │ PianoMan roadmap #13      │ Phase 3                  │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 19    │ Controlled API access (reads open, mutations          │ PianoMan architecture     │ Foundation               │
│       │ restricted unless debug)                              │ concern                   │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 20    │ Improved exception handling and logging               │ PianoMan roadmap #12      │ Phase 1                  │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 21    │ Component self-description: every actionable UI       │ PianoMan 2026-04-22       │ Foundation               │
│       │ element provides JSON interface definition with       │                           │                          │
│       │ instructions. Enables embedded AI discovery,          │                           │                          │
│       │ auto-generated help docs, and diagram generation.     │                           │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 22    │ Multi-select as universal pattern: Transcript viewer, │ PianoMan 2026-04-22       │ Phase 1                  │
│       │ cards, navigator items, tags — anywhere lists of      │                           │                          │
│       │ actionable items appear.                              │                           │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 23    │ Bottom panel "Related Entities" replaces Workers.     │ PianoMan 2026-04-22       │ Phase 1                  │
│       │ Shows children, linked sessions, linked briefs,       │                           │                          │
│       │ team members — not just workers. Workers/chat         │                           │                          │
│       │ distinction eliminated.                               │                           │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 24    │ System monitor dashboard in bottom panel drawer.      │ PianoMan 2026-04-22       │ Phase 1                  │
│       │ Top-level metrics/warnings visible on drawer bar      │                           │                          │
│       │ when closed (CPU, memory, active sessions, errors).   │                           │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 25    │ Runtime-configurable card display: user chooses       │ PianoMan 2026-04-22       │ Phase 1                  │
│       │ which fields appear on cards during runtime.          │                           │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 26    │ AI feedback timeout pattern: when AI requests         │ PianoMan 2026-04-22       │ Foundation (comms)       │
│       │ input (review, approval, feedback), it schedules      │                           │                          │
│       │ a self-prompt timeout to detect stalls and decide:    │                           │                          │
│       │ retry, proceed without, or escalate.                  │                           │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 27    │ AI-to-AI response mechanism enforcement: requester    │ PianoMan 2026-04-22       │ Foundation (comms)       │
│       │ specifies feedback mechanism (none, message, prompt). │                           │                          │
│       │ Default is prompt. Using CLI response message and     │                           │                          │
│       │ assuming the other AI reads it is NOT acceptable.     │                           │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 28    │ Unified notification bus: single event emit reaches   │ PianoMan 2026-04-22       │ Foundation               │
│       │ AI (hook/reminder), app (tab indicator), user         │                           │                          │
│       │ (macOS notification), team (routing), and log —       │                           │                          │
│       │ through subscriber-specific delivery mechanisms.      │                           │                          │
├───────┼───────────────────────────────────────────────────────┼───────────────────────────┼──────────────────────────┤
│ 29    │ Hooks as first-class architectural concept: app-level │ PianoMan 2026-04-22       │ Foundation               │
│       │ (command entry/exit), session-level (pre/post         │                           │                          │
│       │ prompt), team-level (member notifications). Platform  │                           │                          │
│       │ adapter handles hook capability differences (Claude   │                           │                          │
│       │ has hooks, Codex/Gemini don't — app compensates).     │                           │                          │
└───────┴───────────────────────────────────────────────────────┴───────────────────────────┴──────────────────────────┘

---

## 9. Recommended Architecture Document Structure

Based on this analysis, the updated UAI architecture spec should have these sections:

1. **Purpose & Principles** — What UAI is, the 5 architectural principles (DESIGN.md), constraints
2. **Entity Model** — Session (incl. three-ID model), Brief, Project, Team, Tag with field ownership maps
3. **Data Architecture** — External stores, ownership, event flow, schema versioning
4. **Component API Contracts** — Updated per-component APIs with self-description interfaces (JSON interface definitions for embedded AI discovery, auto-generated help, diagrams)
5. **Command System** — Command bus, hierarchy, hooks, origin tracking, result types, access control
6. **Event & Notification System** — Internal events (fine-grained subscriptions), notification bus (multi-medium: AI hook, app indicator, user notification, team routing, log)
7. **Hooks Architecture** — App-level, session-level, team-level hooks. Platform capability differences (Claude has hooks, Codex/Gemini don't — app compensates). Hooks as enforcement layer for comms.
8. **UI Component Hierarchy** — Updated layout with Tabbed Navigator, Grid View, Tab Groups, Related Entities (replaces Workers), System Monitor dashboard, multi-select as universal pattern
9. **Visual System** — Design tokens in config, color palette, typography scale, component CSS strategy, runtime-configurable card display
10. **Session Identity** — Current v5 + draft TrackingId extension
11. **Terminal Substrate** — Carried forward, platform adapter completion
12. **AI Integration** — Embedded AI discovery via component self-description, LLLM, AI-to-AI comms with response mechanism enforcement and feedback timeout patterns
13. **Testing Strategy** — Component API testing, integration testing, packaged-build testing
14. **Migration Plan** — What carries from UCI, what's rewritten, build order

---

## Appendix: File Map

```
architecture/
  gap_analysis.md                           ← THIS FILE
  archive_originals/                        ← Archived UAI docs (unmodified)
    component_api_contracts.md
    uai_architecture_v0.2.md
    2026-03-30-frontend-design-v2.md
    session_identity_v4.2.md
    story_backlog_v2.0.md
    mvcr-status.md
    customer-decisions-pending.md
    Updates to System Description and Requirements.md
    system_description_v0.1.md
  current_references/                       ← Current state docs from UCI + specs
    spec_session_identity_current.md
    uci_data_architecture.md
    uci_ipc_reference.md
docs/
  lessons-learned.md                        ← Copied from archive (gold)
```
