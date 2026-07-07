# Unified CLI Session Manager - System Description

**Version:** 0.1 (Draft)  
**Date:** 2026-01-19  
**Status:** Replaces conversation_runtime_spec_v0.1.md and component_design_v0.1.md

---

## 1. Overview

The Unified CLI Session Manager is a desktop application that provides a graphical interface for managing AI CLI sessions. It replaces Claude Desktop as the primary interaction surface while gaining access to hooks, plugins, and extensibility that Desktop lacks.

**Core concept:** A GUI shell around tmux-managed CLI sessions. The user interacts directly with AI CLIs - the application provides session management, not message brokering.

---

## 2. What This Is (and Isn't)

### What It IS

- A session manager with a chat-style UI
- A terminal emulator with a session sidebar
- A unified view of ALL CLI sessions (frontend-launched, agent-launched, terminal-launched)
- An extensibility layer via hooks at session/message boundaries

### What It Is NOT

- A message broker routing prompts to backends
- A dispatcher normalizing responses from multiple AIs
- A "frontend" with "backend" AI services
- A conversation runtime processing turns

**Key distinction:** Claude CLI (or Codex CLI, Gemini CLI, etc.) handles conversation logic. This app handles session visibility and lifecycle.

---

## 3. Architecture

```
┌─────────────────────────────────────────────────────────────┐
│              Unified CLI Session Manager                     │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  ┌─────────────────┐    ┌─────────────────────────────────┐ │
│  │  Session List   │    │    Terminal Pane                │ │
│  │  ─────────────  │    │    (attached tmux session)      │ │
│  │  [Claude][Codex]│    │                                 │ │
│  │  [Gemini][Cline]│    │    $ claude                     │ │
│  │  ─────────────  │    │    > processing request...      │ │
│  │  🟢 Chat title  │    │                                 │ │
│  │  🟡 Chat title  │    │                                 │ │
│  │  ⚫ Chat title  │    │                                 │ │
│  │  ...            │    │                                 │ │
│  │  ─────────────  │    │                                 │ │
│  │  [+ New Chat]   │    │                                 │ │
│  └─────────────────┘    └─────────────────────────────────┘ │
│                                                              │
└─────────────────────────────────────────────────────────────┘
                              │
                              ▼
                    tmux sessions (existing)
                              │
            ┌─────────────────┼─────────────────┐
            ▼                 ▼                 ▼
      Claude CLI         Codex CLI        Gemini CLI
            │                 │                 │
            └─────────────────┴─────────────────┘
                              │
                    Existing Infrastructure
                    (MCPs, task coordination,
                     chat-playwright, etc.)
```

---

## 4. Core Components

### 4.1 Session Registry

**Purpose:** Track all CLI sessions with metadata.

**Data model:**
```yaml
session:
  id: string              # tmux session name
  ai: claude|codex|gemini|cline
  title: string           # user-visible, AI-editable
  status: running|stopped|error
  created_at: datetime
  last_activity: datetime
  has_new_output: boolean
  launched_by: frontend|agent|terminal
  tmux_pane: string       # for attach
```

**Operations:**
- List sessions (filtered by AI, status, recency)
- Get session details
- Create session (launches CLI in tmux)
- Attach to session (for terminal pane)
- Terminate session
- Update metadata (title, etc.)

### 4.2 Session MCP Server

**Purpose:** Allow AIs to interact with the session manager.

**Tools:**
- `set_chat_title(title: str)` - Update current session's title
- `get_session_info()` - Get current session metadata
- `list_sessions(ai?: str, status?: str)` - Query sessions
- `signal_error(message: str)` - Set error indicator
- `request_attention()` - Trigger new-output indicator

### 4.3 UI Shell

**Purpose:** Render session list and terminal pane.

**Left pane:**
- Tabs per AI (Claude, Codex, Gemini, Cline)
- Session list with title, status indicator, recency
- New chat button
- (Future) Search/filter controls

**Main pane:**
- Embedded terminal displaying attached tmux session
- Standard terminal interaction (no special input handling)

**Status indicators:**
- 🟢 Running, idle
- 🟡 Running, has new output
- 🔴 Error state
- ⚫ Stopped

### 4.4 Hook System

**Purpose:** Extensibility at session lifecycle and message boundaries.

**Hook points:**
- `session_start` - After CLI launches
- `session_end` - Before/after termination
- `pre_message` - Before user input sent (if intercepted)
- `post_message` - After AI response complete
- `periodic` - Timer-based (like pulse system)

**Note:** Hooks operate alongside the CLI, not in its message path. They can observe and react, but don't process turns.

---

## 5. Session Lifecycle

### 5.1 New Session (Frontend-Launched)

```
1. User clicks [+ New Chat] on Claude tab
2. Session Registry creates metadata entry
3. tmux new-session with claude_cli.py
4. Hook: session_start fires
5. Terminal pane attaches to session
6. User interacts directly with Claude CLI
```

### 5.2 Existing Session (Discovered)

```
1. On startup, scan tmux sessions
2. Match patterns (claude-*, codex-*, etc.)
3. Create/update registry entries
4. Sessions appear in UI regardless of launch origin
```

### 5.3 Session Resume

```
1. User clicks stopped session
2. If tmux session exists: attach
3. If tmux session gone: relaunch with continuation flag
4. Claude CLI handles conversation continuity
```

### 5.4 Session Termination

```
1. User closes session (or CLI exits)
2. Hook: session_end fires
3. Registry marks status=stopped
4. Session remains in list (history)
5. tmux session cleanup (configurable: keep vs destroy)
```

---

## 6. Multi-Session Features (Extended Vision)

### 6.1 One-to-Many (Broadcast)

**Trigger:** User selects multiple AIs for a prompt

**Behavior:**
1. Create N sessions (one per selected AI)
2. Send same prompt to each
3. Sessions run independently
4. UI shows all in parallel (split view or tabs)

**Implementation:** Just session multiplication. No aggregation.

### 6.2 Many-to-Many (Group Chat)

**Trigger:** User initiates group conversation

**Behavior:**
1. Create sessions for each participant AI
2. User prompt → all AIs
3. Collect responses (with timeout)
4. Aggregate with source annotations
5. Send aggregated message to all (excluding self-echo)
6. Repeat

**Implementation:** Builds on existing chat orchestrator pattern.

---

## 7. Integration Points

| System | Integration | Notes |
|--------|-------------|-------|
| tmux | Session management | Core dependency |
| CLI wrappers | claude_cli.py, codex_cli.py, etc. | Launch commands |
| SwiftBar | Session status | Pattern reference |
| Existing MCPs | Available to CLIs | No change |
| Task coordination | Agent-launched sessions visible | Discovery |
| Chat orchestrator | Group chat foundation | Reuse |

---

## 8. What Already Exists

| Need | Existing Solution | Gap |
|------|-------------------|-----|
| CLI session management | tmux + wrappers | None |
| Session visibility | SwiftBar menu | Not a full UI |
| AI orchestration | Claude CLI + MCPs | None |
| Task-launched sessions | ai_comms/ coordination | Discovery needed |
| Chat history | ai_memories/ pipeline | None |
| Multi-AI chat | chat_orchestrator | UI integration |

---

## 9. What Needs Building

| Component | Effort | Notes |
|-----------|--------|-------|
| Session Registry | Medium | New, but simple data model |
| Session MCP Server | Low | Standard MCP pattern |
| UI Shell | High | Requires framework decision |
| Terminal embedding | Medium | Depends on framework |
| Session discovery | Low | tmux list-sessions + patterns |
| Hook system | Medium | Event emission + handlers |

---

## 10. Open Questions

1. **Framework:** Electron (mature, heavy) vs Tauri (newer, lighter) vs web app + terminal in browser?

2. **Terminal embedding:** xterm.js? Native terminal view? Depends on framework.

3. **Session naming:** Convention for tmux session names to enable discovery?

4. **History retention:** How long to keep stopped sessions in list?

5. **Hook implementation:** Scripts? Plugins? Built-in only?

---

## 11. Out of Scope (Deferred)

- Turn processing / message interception
- Backend dispatching / response normalization
- Context building (Claude CLI handles this)
- Response processing (hooks can observe, not transform)
- Intelligent routing (user picks AI manually)

---

## 12. Success Criteria (MVP)

1. Launch Claude CLI sessions from UI
2. See all Claude CLI sessions (any launch origin)
3. Attach to any session from UI
4. Status indicators (running/stopped/new output)
5. AI can set chat title via MCP
6. At least one hook fires (session_start)

---

## Appendix: Relationship to Previous Specs

| Previous Document | Status | Notes |
|-------------------|--------|-------|
| conversation_runtime_spec_v0.1.md | Superseded | Over-engineered for different problem |
| component_design_v0.1.md | Superseded | Components for message brokering we don't need |
| req_*.md (all four) | Partially relevant | Some requirements apply, routing/dispatching don't |

The previous specs designed a conversation runtime with turn processing and backend dispatching. This spec describes a session manager with a UI shell. Different problem, simpler solution.
