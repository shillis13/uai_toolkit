# UAI User Story Backlog v2.0

**Version:** 2.0
**Date:** 2026-03-31
**Author:** UI_Designer_0005ad68
**Status:** Approved (2026-03-31, PianoMan via Hamilton)
**Source:** 2026-03-30-frontend-design-v2.md, uai_architecture_v0.2.md, session_identity_v4.2.md, component_api_contracts.md
**Supersedes:** story_backlog_v0.1.md (Jan 2026, pre-redesign)

---

## MVCR Overview

┌────────┬────────────────────┬────────────────┬───────────────────────────────────────────────────────────────────────────────────────────┐
│ MVCR   │ Name               │ Theme          │ Summary                                                                                   │
├────────┼────────────────────┼────────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
│ MVCR-1 │ Working Foundation │ See it, use it │ Core layout, session discovery, terminal attachment, basic navigation. A usable app with  │
│        │                    │                │ one session at a time.                                                                    │
├────────┼────────────────────┼────────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
│ MVCR-2 │ Organized          │ Manage it      │ Navigator with filter/group/sort, session cards, tab management, Tab Groups, prompt box   │
│        │ Workspace          │                │ with two-step submit, transcript panel.                                                   │
├────────┼────────────────────┼────────────────┼───────────────────────────────────────────────────────────────────────────────────────────┤
│ MVCR-3 │ Full Productivity  │ Master it      │ Finalize/archive, activity states with notifications, worker dock, context panel, bottom  │
│        │                    │                │ panel logs, custom launch dialog, shell mode, drag-and-drop.                              │
└────────┴────────────────────┴────────────────┴───────────────────────────────────────────────────────────────────────────────────────────┘

**Principle:** Each MVCR is independently shippable and useful. MVCR-1 replaces a bare terminal. MVCR-2 makes it a workspace. MVCR-3 makes it a control tower.

### MVCR-to-Gate Alignment

Per the approved development plan (development_plan_v1.0.md):

┌────────┬─────────────────────────────────┬─────────────────────────────┬─────────────────────────────────────────────────────────────────┐
│ MVCR   │ Gate                            │ Phases Included             │ What Ships                                                      │
├────────┼─────────────────────────────────┼─────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ MVCR-1 │ Gate 2 (Usable Session Manager) │ Phase 0 + Phase 1 + Phase 2 │ Navigator, cards, tabs, terminal, prompt box (basic),           │
│        │                                 │                             │ transcript, session creation                                    │
├────────┼─────────────────────────────────┼─────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ MVCR-2 │ Gate 3 (Full Workspace)         │ + Phase 3                   │ Filter/group/sort, Tab Groups, split view, full prompt box      │
│        │                                 │                             │ (!commands, $ shell), full transcript                           │
├────────┼─────────────────────────────────┼─────────────────────────────┼─────────────────────────────────────────────────────────────────┤
│ MVCR-3 │ Gate 4 (Feature Complete)       │ + Phase 4 + Phase 5         │ Activity detection, notifications, worker dock, context panel,  │
│        │                                 │                             │ logs, finalize/archive, custom launch, drag-and-drop            │
└────────┴─────────────────────────────────┴─────────────────────────────┴─────────────────────────────────────────────────────────────────┘

### Story ID Legend

┌────────┬──────────────────────────┐
│ Prefix │ Component/Area           │
├────────┼──────────────────────────┤
│ I      │ Infrastructure           │
├────────┼──────────────────────────┤
│ N      │ Navigator                │
├────────┼──────────────────────────┤
│ C      │ Session Cards            │
├────────┼──────────────────────────┤
│ T      │ Tab Bar                  │
├────────┼──────────────────────────┤
│ P      │ Terminal / Session Pane  │
├────────┼──────────────────────────┤
│ B      │ Prompt Box               │
├────────┼──────────────────────────┤
│ R      │ Transcript               │
├────────┼──────────────────────────┤
│ V      │ Visual System            │
├────────┼──────────────────────────┤
│ E      │ Edge cases / Gap stories │
├────────┼──────────────────────────┤
│ G      │ Tab Groups               │
├────────┼──────────────────────────┤
│ SV     │ Split View               │
├────────┼──────────────────────────┤
│ M      │ Context Menus            │
├────────┼──────────────────────────┤
│ L      │ Launch / Files           │
├────────┼──────────────────────────┤
│ A      │ Activity / Notifications │
├────────┼──────────────────────────┤
│ W      │ Worker Dock              │
├────────┼──────────────────────────┤
│ X      │ Context Panel (right)    │
├────────┼──────────────────────────┤
│ O      │ Logs (bottom panel)      │
├────────┼──────────────────────────┤
│ F      │ Finalize / Lifecycle     │
└────────┴──────────────────────────┘

Number suffix: `{prefix}{MVCR}.{sequence}` — e.g., N2.1 = Navigator, MVCR-2, story 1.

---

## MVCR-1: Working Foundation

**Goal:** User can see all sessions, open them in tabs, interact via terminal, and launch new sessions. The core layout (navigator + workspace + prompt box) is functional. One session at a time — no split views, no groups.

**Acceptance Criteria:**
- App launches and displays the four-panel layout (navigator, workspace, context panel placeholder, bottom panel placeholder)
- Navigator shows all sessions from the registry (source of truth), with runtime status updated via substrate polling
- User can open a session in a tab and interact via live terminal
- User can launch new Claude, Codex, and Gemini sessions
- Prompt box stages text to the terminal via Cmd+Enter
- Transcript view works for stopped sessions (full-width) and as slide-over for running sessions
- Session identity uses Tracking ID as primary key (v4.2 model)
- Platform color bars appear consistently (navigator, tabs, cards, pane headers)

### Infrastructure Stories

┌──────┬────────────────────────────────────────────┬───────────────────────────────────────────────────────────────────────┬──────────────┐
│ ID   │ Story                                      │ Acceptance Criteria                                                   │ Traces To    │
├──────┼────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┼──────────────┤
│ I1.1 │ As the app, I load sessions from           │ On startup: populate Session Store from registry + sessionInfo dirs + │ Identity     │
│      │ registry/sessionInfo (source of truth) and │ app state. Ongoing: poll substrate.list_sessions() every 5s to update │ v4.2,        │
│      │ use substrate polling for runtime state    │ runtime fields (running/stopped, live terminal handle). Orphan mux    │ Architecture │
│      │ updates                                    │ sessions (not in registry) surface as diagnostic candidates, not      │ Sec 3.3      │
│      │                                            │ first-class sessions.                                                 │              │
├──────┼────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┼──────────────┤
│ I1.2 │ As the app, I read session identity from   │ Session Store keyed by Tracking ID; lookups by CLI UUID and terminal  │ Identity     │
│      │ sessionInfo.json and registry files        │ session name use reverse-lookup; sessionInfo is source of truth,      │ v4.2 Sec 4   │
│      │                                            │ registry is derived index                                             │              │
├──────┼────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┼──────────────┤
│ I1.3 │ As the app, I merge session data from      │ Merge precedence: sessionInfo (truth) > registry (derived) > app      │ Identity     │
│      │ three stores (registry, sessionInfo, app   │ state (UI-only); type/pinned/exchange_count from app state only; all  │ v4.2 Sec 4   │
│      │ state)                                     │ fields available after merge                                          │              │
├──────┼────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┼──────────────┤
│ I1.4 │ As the app, I connect to a terminal        │ xterm.js renders live terminal; keystrokes pass through; colors and   │ Architecture │
│      │ session via node-pty + tmux attach         │ cursor work                                                           │ : tech stack │
├──────┼────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┼──────────────┤
│ I1.5 │ As the app, I persist UI state (open tabs, │ Tabs restored on relaunch; active tab re-selected; panel              │ Design Sec 1 │
│      │ active tab, panel sizes) across restarts   │ widths/heights preserved                                              │              │
├──────┼────────────────────────────────────────────┼───────────────────────────────────────────────────────────────────────┼──────────────┤
│ I1.6 │ As the app, I launch CLI sessions by       │ Wrapper called as subprocess; output parsed; session appears in       │ Identity     │
│      │ calling wrapper scripts and parsing        │ Session Store                                                         │ v4.2 Sec 8,  │
│      │ TRACKING_ID/TERMINAL_SESSION/CLI_UUID from │                                                                       │ Architecture │
│      │ stdout                                     │                                                                       │ Sec 3.2      │
└──────┴────────────────────────────────────────────┴───────────────────────────────────────────────────────────────────────┴──────────────┘

**Note on Component API:** Each component's API surface is storied as part of that component's stories (e.g., SessionNavigator API is part of N-stories). There is no standalone Component API story — the API is a cross-cutting requirement on every component.

### Navigator Stories

┌──────┬─────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────┬───────────────┐
│ ID   │ Story                                               │ Acceptance Criteria                                         │ Traces To     │
├──────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼───────────────┤
│ N1.1 │ As a user, I see a session navigator in the left    │ Navigator is 240px, full height; tab bar and center are in  │ Design Sec 2, │
│      │ panel extending full window height                  │ the right column only                                       │ 3             │
├──────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼───────────────┤
│ N1.2 │ As a user, I see compact session items (platform    │ Each item is single-line; platform color bar on left edge;  │ Design Sec 3  │
│      │ bar, name, ctx%, status dot) in the navigator       │ name 14px; status dot colored                               │               │
├──────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼───────────────┤
│ N1.3 │ As a user, sessions are grouped by platform by      │ Auto-generated groups with collapsible headers showing      │ Design Sec 3  │
│      │ default (Claude, Codex, Gemini)                     │ active/total count                                          │               │
├──────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼───────────────┤
│ N1.4 │ As a user, I can single-click a session to select   │ Selected session highlighted; details shown in context      │ Design Sec 3  │
│      │ it                                                  │ panel (placeholder for MVCR-1)                              │               │
├──────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼───────────────┤
│ N1.5 │ As a user, I can double-click a session to open it  │ Session opens in workspace as a new tab; terminal attaches  │ Design Sec 3  │
│      │ in a tab                                            │                                                             │               │
├──────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼───────────────┤
│ N1.6 │ As a user, I can single-click a group header to     │ Group toggles; center pane shows card grid for selected     │ Design Sec 3  │
│      │ expand/collapse it and show cards in center         │ group                                                       │               │
├──────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼───────────────┤
│ N1.7 │ As a user, I see a "+ New Session" button at the    │ Button with dropdown: Claude, Codex, Gemini quick-launch;   │ Design Sec 13 │
│      │ bottom of the navigator                             │ "Custom..." is disabled with tooltip "Coming in a future    │               │
│      │                                                     │ release"; newly launched sessions auto-open in a tab (E1.2) │               │
└──────┴─────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────┴───────────────┘

### Session Card Stories

┌──────┬──────────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────┬──────────────┐
│ ID   │ Story                                                    │ Acceptance Criteria                                     │ Traces To    │
├──────┼──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┼──────────────┤
│ C1.1 │ As a user, I see session cards in the center pane when   │ Card grid with responsive layout; left-bar accent       │ Design Sec 4 │
│      │ browsing (no tab focused)                                │ design; 3px platform color bar                          │              │
├──────┼──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┼──────────────┤
│ C1.2 │ As a user, cards show: name, time, status dot, meta row  │ All data fields rendered correctly from Session Store   │ Design Sec 4 │
│      │ (msgs, project), badge row (role, ctx%)                  │ by tracking_id reference                                │              │
├──────┼──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┼──────────────┤
│ C1.3 │ As a user, active cards have full color; stopped cards   │ No opacity dimming; stopped cards use gray bar and      │ Design Sec 4 │
│      │ have muted text but same opacity                         │ muted text color                                        │              │
├──────┼──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┼──────────────┤
│ C1.4 │ As a user, the focused card has a blue border, glow, and │ Focused state visually distinct from active and stopped │ Design Sec 4 │
│      │ widened bar                                              │                                                         │              │
├──────┼──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┼──────────────┤
│ C1.5 │ As a user, cards that are open in a tab show an          │ Thin accent line (1px) along top edge of card in        │ Design Sec 4 │
│      │ indicator                                                │ --gemini blue; visible at card-grid scanning distance;  │              │
│      │                                                          │ additive with other card states                         │              │
├──────┼──────────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────┼──────────────┤
│ C1.6 │ As a user, I can double-click a card to open it as a tab │ Same behavior as double-clicking in navigator           │ Design Sec 4 │
└──────┴──────────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────┴──────────────┘

### Tab Bar Stories

┌──────┬───────────────────────────────────────────────────┬──────────────────────────────────────────────────────────┬────────────────────┐
│ ID   │ Story                                             │ Acceptance Criteria                                      │ Traces To          │
├──────┼───────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┼────────────────────┤
│ T1.1 │ As a user, I see browser-style tabs for open      │ Tabs show platform color bar, status dot, session name,  │ Design Sec 5       │
│      │ sessions                                          │ close button                                             │                    │
├──────┼───────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┼────────────────────┤
│ T1.2 │ As a user, running tabs have full-brightness      │ Text brightness matches session status, independent of   │ Design Sec 5       │
│      │ text; stopped tabs have muted text                │ tab selection                                            │                    │
├──────┼───────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┼────────────────────┤
│ T1.3 │ As a user, I can switch tabs with Cmd+1-9,        │ Keyboard navigation cycles through tabs; Cmd+9 jumps to  │ Design Sec 5       │
│      │ Cmd+Shift+[/]                                     │ last                                                     │                    │
├──────┼───────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┼────────────────────┤
│ T1.4 │ As a user, I can close tabs with Cmd+W or click × │ Tab closes; if it was the active tab, adjacent tab       │ Design Sec 5       │
│      │                                                   │ activates                                                │                    │
├──────┼───────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┼────────────────────┤
│ T1.5 │ As a user, Escape does NOT close or deactivate    │ Escape in prompt box → focus terminal; Escape in         │ Design Sec 5,      │
│      │ tabs — it is a focus/pass-through key only        │ terminal → pass to CLI; Escape never affects tab state   │ PianoMan directive │
├──────┼───────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┼────────────────────┤
│ T1.6 │ As a user, open tabs persist across app restarts  │ Tab list and active tab saved to app state; restored on  │ Design Sec 1       │
│      │                                                   │ launch                                                   │                    │
└──────┴───────────────────────────────────────────────────┴──────────────────────────────────────────────────────────┴────────────────────┘

### Terminal & Session Pane Stories

┌──────┬──────────────────────────────────────────────────────────┬──────────────────────────────────────────────────┬─────────────────────┐
│ ID   │ Story                                                    │ Acceptance Criteria                              │ Traces To           │
├──────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┼─────────────────────┤
│ P1.1 │ As a user, I see a live terminal when a running session  │ xterm.js renders terminal via node-pty + tmux    │ Design Sec 2        │
│      │ tab is active                                            │ attach; full color, cursor, scrollback           │                     │
├──────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┼─────────────────────┤
│ P1.2 │ As a user, I can type directly in the terminal and       │ Keystrokes reach CLI stdin; responses render in  │ Design Sec 2        │
│      │ interact with the CLI                                    │ real-time                                        │                     │
├──────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┼─────────────────────┤
│ P1.3 │ As a user, the session pane has a header with platform   │ Pane header is slim, always visible; focus tag   │ Design Sec 7        │
│      │ bar, name, focus tag, ctx%                               │ shows when pane is targeted                      │                     │
├──────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┼─────────────────────┤
│ P1.4 │ As a user, double-Esc in the terminal clears typed       │ Double-Esc → clear CLI prompt bar input. Triple+ │ Design Sec 7,       │
│      │ input; triple+ Esc cancels the AI response               │ Esc → cancel/interrupt AI response. App does not │ PianoMan correction │
│      │                                                          │ consume Esc events in terminal context.          │ 2026-04-01          │
├──────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┼─────────────────────┤
│ P1.5 │ As a user, Escape in the terminal does NOT close the     │ Session pane is never dismissible via Escape     │ Design Sec 7        │
│      │ session pane                                             │                                                  │                     │
├──────┼──────────────────────────────────────────────────────────┼──────────────────────────────────────────────────┼─────────────────────┤
│ P1.6 │ As a user, I see a transcript for stopped sessions       │ Stopped session → transcript fills the pane (no  │ Design Sec 8        │
│      │ taking the full center pane width                        │ terminal underneath)                             │                     │
└──────┴──────────────────────────────────────────────────────────┴──────────────────────────────────────────────────┴─────────────────────┘

### Prompt Box Stories

┌──────┬────────────────────────────────────────────────────┬───────────────────────────────────────────────────────────────┬──────────────┐
│ ID   │ Story                                              │ Acceptance Criteria                                           │ Traces To    │
├──────┼────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┼──────────────┤
│ B1.1 │ As a user, I see a prompt box at the bottom of the │ Textarea with target indicator ("→ Session Name") and         │ Design Sec 7 │
│      │ center area                                        │ Cmd+Enter hint                                                │              │
├──────┼────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┼──────────────┤
│ B1.2 │ As a user, pressing Cmd+Enter stages text into the │ Text appears in CLI prompt bar with "staged · Enter to send"  │ Design Sec 7 │
│      │ focused pane's CLI prompt bar                      │ indicator                                                     │              │
├──────┼────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┼──────────────┤
│ B1.3 │ As a user, I can edit staged text in the CLI       │ Staged text is editable in the terminal; Enter sends to CLI   │ Design Sec 7 │
│      │ prompt bar before pressing Enter                   │                                                               │              │
├──────┼────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┼──────────────┤
│ B1.4 │ As a user, each tab maintains its own prompt text  │ Switching tabs preserves unsent text; restores on switch back │ Design Sec 7 │
├──────┼────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┼──────────────┤
│ B1.5 │ As a user, Tab key inserts indent in the prompt    │ Tab inserts spaces/tab character into text                    │ Design Sec 7 │
│      │ box (not UI cycle)                                 │                                                               │              │
├──────┼────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┼──────────────┤
│ B1.6 │ As a user, I can see which has focus: prompt box   │ Distinct visual treatment (border brightness, glow) for       │ Design Sec 7 │
│      │ or terminal pane                                   │ prompt box focus vs terminal focus                            │              │
├──────┼────────────────────────────────────────────────────┼───────────────────────────────────────────────────────────────┼──────────────┤
│ B1.7 │ As a user, the prompt box auto-grows and auto-     │ Default min: 2 lines. Max: 10 lines. Grows as content typed;  │ Design Sec 7 │
│      │ shrinks as I type                                  │ shrinks when content deleted below current height. Resize     │              │
│      │                                                    │ handle above for manual override; manual resize disables      │              │
│      │                                                    │ auto-sizing until tab switch.                                 │              │
└──────┴────────────────────────────────────────────────────┴───────────────────────────────────────────────────────────────┴──────────────┘

### Transcript Stories (MVCR-1 minimal — basic view for stopped sessions)

┌──────┬─────────────────────────────────────────────────────────┬──────────────────────────────────────────────────────────┬──────────────┐
│ ID   │ Story                                                   │ Acceptance Criteria                                      │ Traces To    │
├──────┼─────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┼──────────────┤
│ R1.2 │ As a user, the transcript shows exchanges (user prompt  │ User blocks (blue bar), AI blocks (amber bar), grouped   │ Design Sec 8 │
│      │ + AI response pairs)                                    │ as exchanges; JSONL parsed correctly                     │              │
├──────┼─────────────────────────────────────────────────────────┼──────────────────────────────────────────────────────────┼──────────────┤
│ R1.6 │ As a user, the transcript starts at the bottom and      │ Auto-scroll to bottom on load; Cmd+Home → top, Cmd+End → │ Design Sec 8 │
│      │ supports Cmd+Home/End                                   │ bottom                                                   │              │
└──────┴─────────────────────────────────────────────────────────┴──────────────────────────────────────────────────────────┴──────────────┘

**Note:** Full transcript features (slide-over on running sessions, filters, collapse, hover actions, persist across nav, refresh) are MVCR-2. See MVCR-2 section. MVCR-1 transcript is a basic read-only exchange view for stopped sessions (full-width per P1.6).

### Visual System Stories

┌──────┬───────────────────────────────────────────────────────────┬────────────────────────────────────────────────────────────┬───────────────┐
│ ID   │ Story                                                     │ Acceptance Criteria                                        │ Traces To     │
├──────┼───────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┼───────────────┤
│ V1.1 │ As a user, I see 2px panel borders at #606d94 for clear │ Navigator, tab bar, prompt box, and panel boundaries all   │ Design Sec 12 │
│      │ panel separation                                          │ use bright 2px borders                                     │               │
├──────┼───────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┼───────────────┤
│ V1.2 │ As a user, I see consistent 3px platform color bars       │ Navigator items, cards, tabs, pane headers all use left-   │ Design Sec 14 │
│      │ everywhere                                                │ edge platform bar                                          │               │
├──────┼───────────────────────────────────────────────────────────┼────────────────────────────────────────────────────────────┼───────────────┤
│ V1.3 │ As a user, text sizes are readable: session names 14px,   │ No text smaller than 10px; primary content at 13-14px      │ Design Sec 12 │
│      │ meta 12px, group headers 13px                             │                                                            │               │
└──────┴───────────────────────────────────────────────────────────┴────────────────────────────────────────────────────────────┴───────────────┘


### Edge Case Stories

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| E1.1 | As a user, when zero sessions exist I see an empty state with guidance | Navigator empty; center shows "No sessions" message + New Session button | Design Sec 2 |
| E1.2 | As a user, a newly launched session auto-opens in a tab | Session created via + button immediately opens as active tab | Design Sec 13 |
| E1.3 | As a user, if a session disappears while its tab is open, the tab shows a graceful state | Tab shows "Session ended" or similar; terminal detaches without crash | Design Sec 7 |
| E1.4 | As a user, rapid tab switching does not cause flicker or stale content | Terminal content updates atomically on tab switch; no flash of previous session | Design Sec 5 |
| E1.5 | As a user, resizing the window preserves panel layout proportionally | All panels reflow; no content clipped or hidden | Design Sec 2 |

### PianoMan Feedback Stories (added 2026-04-01)

Stories added from PianoMan's first hands-on testing of the MVCR-1 build. Pixel triaged MVCR assignment; customer confirmation pending (see docs/decision-logs.md).

#### MVCR-1 Additions

┌───────┬─────────────────────────────────────────────────────┬─────────────────────────────────────────────────────────────┬──────────────┐
│ ID    │ Story                                               │ Acceptance Criteria                                         │ Source       │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ C1.7  │ As a user, cards in the center pane are grouped     │ Active section expanded by default; Stopped section         │ PianoMan #1  │
│       │ into collapsible Active and Stopped sections        │ collapsed by default. Section headers show count.           │ (High)       │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ N1.8  │ As a user, navigator sessions are sorted by last    │ Default sort is last_activity descending; most recent       │ PianoMan #2  │
│       │ message time by default                             │ activity at top. (Pulls default sort from N2.3 into         │ (Med-High)   │
│       │                                                     │ MVCR-1.)                                                    │              │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ V1.4  │ As a user, scrollbars are wide enough to grab       │ Scrollbar width minimum 12px; styled to match dark theme    │ PianoMan #13 │
│       │ easily                                              │ but clearly visible and grabbable.                          │ (Med)        │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ B1.8  │ As a user, the prompt box looks like a text input   │ Prompt box has visible border, subtle background            │ PianoMan #6, │
│       │ field                                               │ differentiation from surrounding panels, and placeholder    │ #7 (Med)     │
│       │                                                     │ text. Default height is 2-3 lines (min-height ~56px).       │              │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ B1.9  │ As a user, resizing the prompt box works correctly: │ Resize listener on document (not element); no max-height    │ PianoMan #3  │
│       │ I can drag beyond content height, and the drag      │ clamp during manual drag; mouseup fires globally to release │ (Med)        │
│       │ handle releases cleanly when mouse leaves the box   │ drag state.                                                 │              │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ N1.9  │ As a user, the "+ New Session" area is compact with │ + button is narrow; Search button opens text filter; Open   │ PianoMan #8  │
│       │ Search and Open as Tab Group buttons alongside it   │ as Tab Group opens current group as tabs. All three sit in  │ (Low-Med)    │
│       │                                                     │ a toolbar row above or below the navigator list.            │              │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ V1.5  │ As a user, focus is indicated by a bright border on │ Remove [FOCUS] text tag from pane header. Focused pane gets │ PianoMan #2  │
│       │ the focused pane, not a text label                  │ a brighter border (e.g., #7aa2f7 2px). Unfocused panes use│ center pane, │
│       │                                                     │ standard #606d94 border.                                  │ confirmed    │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ N1.10 │ As a user, single-clicking a group header selects   │ Click on group row = select + show cards in center. Click   │ PianoMan #10 │
│       │ the group (showing its cards); collapse/expand is   │ on chevron (▼/▶) = toggle collapse. Separates selection     │ (Med)        │
│       │ via the chevron only                                │ from collapse.                                              │              │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ C1.8  │ As a user, group headers in the card grid show x/y  │ Group section headers display "3 active / 12 total" or      │ PianoMan #11 │
│       │ (x active out of y total)                           │ similar active/total count.                                 │ (Low-Med)    │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ P1.7  │ As a user, the session pane header shows Terminal   │ Additional metadata fields in the pane header; collapsible  │ PianoMan #12 │
│       │ ID, Session ID, and Time Started                    │ or in a secondary row to avoid clutter.                     │ (Med)        │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ V1.6  │ As a user, slide-out panels open and close in the   │ Context panel always slides from right edge; bottom panel   │ PianoMan #10 │
│       │ same position                                       │ always slides from bottom edge. No position drift between   │ (Med)        │
│       │                                                     │ open/close cycles.                                          │              │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ C1.9  │ As a user, single-clicking a card shows its session │ Single-click selects card and populates Context panel with  │ PianoMan #5  │
│       │ details in the Context panel (Session Details)       │ session identity, state, timeline. Does not open a tab.     │ 2026-04-03   │
│       │                                                     │ Double-click opens tab.                                     │              │
├───────┼─────────────────────────────────────────────────────┼─────────────────────────────────────────────────────────────┼──────────────┤
│ V1.7  │ As a user, the Context panel (Session Details) has  │ Fields grouped: Identity (tracking ID, CLI UUID, platform), │ PianoMan #1  │
│       │ visual hierarchy, not a flat key-value dump          │ State (status, activity, ctx%), Timeline (created, last     │ 2026-04-03   │
│       │                                                     │ activity). Values copyable. Status uses colored dot.        │              │
└───────┴─────────────────────────────────────────────────────┴─────────────────────────────────────────────────────────────┴──────────────┘

#### Deferred to MVCR-2

┌──────┬─────────────────────────────────────────────────────────────────────┬─────────────────────────────────────────────────┬───────────┐
│ ID   │ Story                                                               │ Acceptance Criteria                             │ Source    │
├──────┼─────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────┼───────────┤
│ M2.5 │ As a user, I can right-click a card for: Rename, Copy submenu       │ Extends M2.1 with Copy submenu and additional   │ PianoMan  │
│      │ (Name, Terminal ID, Session ID), Show Mgmt, Session Details, Close  │ actions.                                        │ #5 (Med)  │
│      │ Tab                                                                 │                                                 │           │
├──────┼─────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────┼───────────┤
│ M2.6 │ As a user, the card context menu has a Session Mgmt submenu:        │ Nested submenu for lifecycle management. Fork   │ PianoMan  │
│      │ Resume, Stop, Archive/Finalize, Delete, Fork                        │ creates a new session with same context.        │ #6 (Med)  │
├──────┼─────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────┼───────────┤
│ N2.9 │ As a user, I see a Search button in the navigator toolbar           │ Opens text filter input; filters navigator list │ PianoMan  │
│      │                                                                     │ and card grid by session name, tracking ID, or  │ #9 (Med)  │
│      │                                                                     │ content. Same behavior as existing UCI search.  │           │
├──────┼─────────────────────────────────────────────────────────────────────┼─────────────────────────────────────────────────┼───────────┤
│ C2.1 │ As a user, group headers show consolidated badges/indicators of     │ Rolled-up counts: "3 responding, 2 unread" or   │ PianoMan  │
│      │ contained cards                                                     │ similar badge summary on group headers.         │ #12 (Low) │
└──────┴─────────────────────────────────────────────────────────────────────┴─────────────────────────────────────────────────┴───────────┘

#### Deferred to MVCR-3

┌──────┬──────────────────────────────────────────────────┬──────────────────────────────────────────────────────────────────┬─────────────┐
│ ID   │ Story                                            │ Acceptance Criteria                                              │ Source      │
├──────┼──────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────┼─────────────┤
│ A3.6 │ As a user, cards show state indicators: focus,   │ Full indicator set on cards. "Sessionless" = no terminal backing │ PianoMan #4 │
│      │ responding, idle, waiting on input, sessionless, │ (CMD badge). "Dead/gone" = terminal cleaned up but registry      │ (Mixed)     │
│      │ stopped, dead/gone, has unread response          │ entry remains. Definitions pending customer confirmation.        │             │
├──────┼──────────────────────────────────────────────────┼──────────────────────────────────────────────────────────────────┼─────────────┤
│ M3.1 │ As a user, the card context menu and/or right    │ Roles assignable per session; multi-select checkboxes.           │ PianoMan #7 │
│      │ panel includes a multi-select Roles list         │                                                                  │ (Low)       │
└──────┴──────────────────────────────────────────────────┴──────────────────────────────────────────────────────────────────┴─────────────┘

### MVCR-1 UI States

┌──────────────────────┬────────────────────────────────────────────┬──────────────────────────────────────────────────┐
│ State                │ Condition                                  │ Display                                          │
├──────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────┤
│ Empty                │ No sessions discovered                     │ Navigator empty; center shows "No sessions"      │
│                      │                                            │ message + New Session button                     │
├──────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────┤
│ Browsing             │ No tab active; group selected in navigator │ Card grid in center pane                         │
├──────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────┤
│ Terminal             │ Running session tab active                 │ Live terminal in center pane                     │
├──────────────────────┼────────────────────────────────────────────┼──────────────────────────────────────────────────┤
│ Transcript (stopped) │ Stopped session tab active                 │ Full-width transcript in center pane (basic      │
│                      │                                            │ exchange view)                                   │
└──────────────────────┴────────────────────────────────────────────┴──────────────────────────────────────────────────┘

---

## MVCR-2: Organized Workspace

**Goal:** Full navigator with filter/group/sort. Tab Groups with split view. Full prompt box with history, commands, and shell mode. Context menus. Right-click everything. Session launching with Custom dialog. The app becomes a workspace, not just a viewer.

**Depends on:** MVCR-1

**Acceptance Criteria:**
- Navigator has working Filter, Group, Sort controls
- Sessions can be in multiple navigator groups; membership highlighted when session focused
- Tab Groups work as containers (close = hide, not remove; popup for hidden sessions)
- Split view (2x1, 1x2, 2x2) works within Tab Groups
- Prompt box supports !commands and $ shell mode
- Custom launch dialog exposes wrapper parameters
- Drag-and-drop files into prompt box, terminal, and launch dialog
- Right-click context menus on cards, tabs, groups, transcript blocks

### Navigator Enhancement Stories

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| N2.1 | As a user, I can filter sessions by platform, status, type, role, and text | Filter dropdown with multi-select; additive AND logic; center card grid shows ONLY sessions matching current filter/group/sort (navigator is single source of truth for card visibility) | Design Sec 3 |
| N2.2 | As a user, I can group sessions by platform, role, status, parent, custom, or none | Group dropdown; groups are collapsible and nestable | Design Sec 3 |
| N2.3 | As a user, I can sort sessions by last activity, created, name, exchanges, or ctx% | Sort dropdown with ascending/descending | Design Sec 3 |
| N2.4 | As a user, sessions can belong to multiple navigator groups simultaneously | Multi-membership via "Add to Group" (not move); same session appears in multiple groups | Design Sec 3 |
| N2.5 | As a user, when a session tab is focused, its navigator groups are highlighted | Blue left bar + tinted name on all groups containing the focused session | Design Sec 3 |
| N2.6 | As a user, the focused session in the navigator is highlighted with blue text | Visual correlation between focused tab and navigator item | Design Sec 3 |
| N2.7 | As a user, I can create custom groups via context menu | Right-click → Create Group; name input; sessions assigned via Add to Group | Design Sec 3 |
| N2.8 | As a user, I see "Open as Tab Group" button when viewing a navigator group's cards | Breadcrumb bar action creates a Tab Group from the navigator group's sessions | Design Sec 3 |

### Tab Group Stories

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| G2.1 | As a user, I can create a Tab Group by selecting tabs and right-clicking → Create Group | Selected tabs move into a group container in the tab bar | Design Sec 6 |
| G2.2 | As a user, Tab Groups show as a bracket in the tab bar with group name + count | Group header, visible tabs, "+N more" indicator | Design Sec 6 |
| G2.3 | As a user, closing a tab inside a Tab Group hides it (does not remove it) | × closes the tab view; session remains in the group; "+N" updates | Design Sec 6 |
| G2.4 | As a user, I can collapse a Tab Group to a single tab showing group name + count | All tabs hidden; click to expand or double-click for group popup | Design Sec 6 |
| G2.5 | As a user, I can click "+N more" or double-click collapsed group to see the group popup | Popup shows all sessions; "open" tagged; double-click to surface a hidden session | Design Sec 6 |
| G2.6 | As a user, I can remove a session from a Tab Group via right-click → Remove from Group | Session becomes a standalone tab or closes | Design Sec 6 |
| G2.7 | As a user, I can ungroup a Tab Group via right-click → Ungroup | All sessions become standalone tabs | Design Sec 6 |
| G2.8 | As a user, Tab Groups have solid #7aa2f7 border (no glow) | Clear visual boundary distinguishing group from standalone tabs | Design Sec 6 |
| G2.9 | As a user, double-clicking a Tab Group header shows its member cards in the center | Card grid scoped to Tab Group membership | Design Sec 6 |

### Split View Stories

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| SV2.1 | As a user, Tab Groups with 2+ visible sessions show in a split layout | 2 sessions = 2x1 or 1x2; 3-4 sessions = 2x2 grid | Design Sec 6 |
| SV2.2 | As a user, I can click a pane to switch focus within a split view | Focused pane gets blue outline + FOCUS tag; prompt box target updates | Design Sec 7 |
| SV2.3 | As a user, I can switch focus between panes with Cmd+1-4 | Keyboard shortcut focuses pane by position | Design Sec 7 |
| SV2.4 | As a user, the split divider is draggable to resize panes | Same 2px bright border drag handle as other panel dividers | Design Sec 2 |

### Prompt Box Enhancement Stories

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| B2.1 | As a user, I can navigate prompt history with Up/Down arrow | Per-session history; rebuilt from JSONL; cycles through past prompts | Design Sec 7 |
| B2.2 | As a user, I can type !history for a paginated prompt history popup | One-line truncated per prompt; hover for full; actions: Copy, Edit & Send, Re-send, Jump to, Rewind to, Fork from | Design Sec 7 |
| B2.3 | As a user, I can type $ commands to execute bash in the session's cwd | Output appears in output area above prompt box; monospace, scrollable, dismissible | Design Sec 7 |
| B2.4 | As a user, the shell output area has a "Send to CLI" action | Stages the command (without $) into the focused pane's CLI prompt | Design Sec 7 |
| B2.5 | As a user, I can type !help to see available commands | Lists all ! and $ commands | Design Sec 7 |
| B2.6 | As the app, the prompt box recognizes `!` and `$` prefixes and routes to command/shell handlers | `!` → command handler; `$` → shell executor; no prefix → staging flow; routing is extensible for future commands | Design Sec 7, Nitpicker I-4 |

### Launch & File Stories

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| L2.1 | As a user, I can open a Custom Launch dialog from the + button | Dialog with: platform, role, working dir, session name, model, prompt, system prompt, auto mode, parent | Design Sec 13 |
| L2.2 | As a user, I can attach files to prompt and system prompt fields in the Custom Launch dialog | Drag-and-drop or browse; files shown as pills; passed by reference to wrapper | Design Sec 13 |
| L2.3 | As a user, I can drag-and-drop files into the prompt box | File path added as reference (pill/chip above textarea) | Design Sec 13 |
| L2.4 | As a user, I can drag-and-drop files into the terminal pane | File path sent to CLI stdin | Design Sec 13 |

### Full Transcript Stories (moved from MVCR-1 per reviewer feedback)

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| R2.1 | As a user, I can open a transcript as a slide-over panel (50% width, resizable) on running sessions | Transcript overlays right side of center pane; drag handle on left edge; terminal visible behind | Design Sec 8 |
| R2.3 | As a user, tool calls are visible but collapsed by default; thinking is hidden by default | Tool blocks (green bar) collapsed within AI blocks; thinking filter off by default | Design Sec 8 |
| R2.4 | As a user, I see filter checkboxes: User, AI, Tools, Thinking | Toggle visibility of each block type | Design Sec 8 |
| R2.5 | As a user, I can collapse/expand any block (user, AI, tool, thinking) | ▼/▶ toggle on each block; collapsed shows one-line preview | Design Sec 8 |
| R2.6 | As a user, the transcript respects manual scroll position | Manual scroll sticks until user scrolls back to bottom (resumes auto-follow) | Design Sec 8 |
| R2.7 | As a user, the pull-out transcript stays visible when navigating to other tabs | Transcript persists until explicitly dismissed (× or toggle); enables cross-session copy/paste | Design Sec 8 |
| R2.8 | As a user, I see a refresh button in the transcript header | Button reloads transcript from JSONL file | Design Sec 8 |
| R2.9 | As a user, I see hover actions (Copy, Jump) on message blocks | Actions appear on hover; Copy copies block text to clipboard; Jump scrolls the transcript view to that exchange | Design Sec 8 |

### Context Menu Stories

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| M2.1 | As a user, I can right-click a card for: Rename, Stop, View History, Delete, Add to Group | Context menu on session cards in center pane | Design Sec 4 |
| M2.2 | As a user, I can right-click a tab for: Rename, Close, Stop, Add to Group | Context menu on tabs in tab bar | Design Sec 5 |
| M2.3 | As a user, I can right-click transcript blocks for type-scoped actions | User block: Copy, Jump, Rewind, Fork. AI block: Copy, Copy exchange. Tool/Thinking: Copy, Collapse All, Expand All, Hide All. | Design Sec 8 |
| M2.4 | As a user, I can right-click navigator groups for: Assign Session, Add Sub-group, Delete | Context menu on group headers | Design Sec 3 |

---

## MVCR-3: Full Productivity

**Goal:** Activity detection with notifications. Worker dock with parent-child scoping. Context panel with docs/memories/messages/prompts. Session finalize/archive lifecycle. Bottom panel with logs. The app becomes a control tower.

**Depends on:** MVCR-2

**Acceptance Criteria:**
- Activity states (responding, idle, blocked, permission prompt, error) reflected in badges and decorators
- macOS notifications fire for blocked, permission prompt, and error states
- Worker dock shows child sessions grouped by Active/Stopped
- Context panel tabs work (Session Details, Docs, Memories, Messages, Prompts)
- Bottom panel has Workers, Logs, and App Log tabs
- Finalize flow produces wrap-up content and archives session
- Promote Worker to Chat preserves parent-child relationship

### Activity & Notification Stories

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| A3.1 | As a user, I see animated status dots when a session is actively responding | Pulse animation on status dot in navigator, card, and tab | Design Sec 11 |
| A3.2 | As a user, I see orange badge when a session is blocked or waiting for permission | Badge on tab and card; distinct from running/stopped | Design Sec 11 |
| A3.3 | As a user, I receive a macOS notification when a session is blocked or needs permission approval | Native notification with session name and state | Design Sec 11 |
| A3.4 | As a user, I receive a macOS notification when a session encounters an error | Native notification; red badge on tab and card | Design Sec 11 |
| A3.5 | As the app, I detect activity states by polling dump-screen via the platform adapter | Platform-specific parsing: Claude (✻ timer), Codex/Gemini (TBD) | Architecture: platform adapter |

### Worker Dock Stories

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| W3.1 | As a user, I see a Worker dock in the bottom panel with Active and Stopped groups | Active expanded by default; Stopped collapsed; scoped to focused session's children | Design Sec 10 |
| W3.2 | As a user, when no workers exist for the focused session, I see "No workers" with a Show All toggle | Not an automatic fallback to all workers; explicit user action required | Design Sec 10 |
| W3.3 | As a user, I can promote a worker to chat via context menu | Type changes to chat; session appears in navigator; parent-child preserved | Design Sec 10 |
| W3.4 | As a user, the bottom panel is resizable via drag handle | Same 2px bright border pattern as other panel dividers | Design Sec 10 |

### Context Panel Stories

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| X3.1 | As a user, I see a collapsible right panel with tabs: Details, Docs, Memories, Messages, Prompts | 280px default; compresses center pane; closed by default | Design Sec 9 |
| X3.2 | As a user, the Session Details tab shows all metadata with click-to-copy | Status, tracking ID, CLI UUID, role, working dir, parent, created, terminal session, exchanges, type | Design Sec 9 |
| X3.3 | As a user, context panel content updates when I focus a different session | Panel reflects the focused session's data | Design Sec 9 |

### Log Stories

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| O3.1 | As a user, I see a Logs tab in the bottom panel showing per-session log files | Monospace viewer; tailing with auto-follow; manual scroll sticks | Design Sec 10 |
| O3.2 | As a user, I see an App Log tab showing application-wide events | Session discoveries, stops, group operations, errors | Design Sec 10 |

### Lifecycle Stories

| ID | Story | Acceptance Criteria | Traces To |
|----|-------|---------------------|-----------|
| F3.1 | As a user, I can finalize a running session via context menu or !finalize | Wrap-up prompt fires; CLI produces lessons learned, memory updates, decisions, handoff notes | Design Sec 11 |
| F3.2 | As a user, I can review and edit the wrap-up content before archiving | Editable before commit | Design Sec 11 |
| F3.3 | As a user, finalized sessions move to Archive | Hidden from navigator by default; visible with "Show Archived" filter | Design Sec 11 |
| F3.4 | As a user, I can un-archive a session | Session reappears in navigator; can be resumed | Design Sec 11 |

---

## v0.1 Backlog Cross-Reference

Coverage check against the original v0.1 stories to ensure nothing was dropped:

| v0.1 Story | v2.0 Coverage | Notes |
|------------|---------------|-------|
| S1.1 Session list in sidebar | N1.1, N1.2 | Redesigned as full-height navigator with compact items |
| S1.2 Session metadata display | C1.2 | Moved to cards in center pane |
| S1.3 Click to select | N1.4, C1.4 | Single-click selects; double-click opens |
| S1.4 Terminal in main pane | P1.1 | Same concept, now via xterm.js + node-pty |
| S1.5 Terminal input | P1.2 | Unchanged |
| S1.6 Status indicators | C1.3, V1.2, A3.1-A3.4 | Expanded: now includes responding, blocked, permission states |
| S1.7 Empty state | MVCR-1 UI States | Covered |
| S1.8 Auto-discovery | I1.1 | Via substrate abstraction polling |
| S1.9 Session disappearance | I1.1 | Polling detects; status updates |
| S1.10 Connection failure | Not explicitly storied | Edge case — should add |
| S2.1 New Chat button | N1.7 | Expanded to multi-platform dropdown + Custom dialog |
| S2.2 Auto-select on launch | Not explicitly storied | Should add to N1.7 behavior |
| S2.3 Default title | Covered by identity model | display_name in sessionInfo |
| S2.4 Hook firing | Deferred | Hooks not in MVCR-1 scope; revisit for MVCR-3+ |
| S2.5 Launch failure error | Not explicitly storied | Should add |
| S3.1-S3.5 MCP tools | Deferred to post-MVCR | MCP self-management is future scope |
| S4.1-S4.4 Multi-AI tabs | N1.3, N2.1 | Replaced by navigator groups (platform filter/group) |
| SF.1 Terminate from UI | M2.1 (Stop in context menu) | Covered |
| SF.2 Search/filter | N2.1 | Covered by navigator filter |
| SF.3 Session history | R1.1-R1.9, F3.3 | Covered by transcript + archive |
| SF.5 Broadcast | Future (Design Sec 17) | v2-3 scope |

### Gap Stories (from cross-reference)

| ID | Story | MVCR | Notes |
|----|-------|------|-------|
| E1.1 | As a user, if terminal connection fails, I see an error with retry option | MVCR-1 | From S1.10 |
| E1.2 | As a user, newly launched sessions auto-open in a tab | MVCR-1 | From S2.2 |
| E1.3 | As a user, if session launch fails, I see an error message | MVCR-1 | From S2.5 |
| E1.4 | As a user, sessions without terminal backing (--no-mux/--oneshot) appear in navigator with a "CMD" badge (distinguishing from terminal-backed sessions) and open without a terminal pane. If cli_uuid is available, show transcript. If cli_uuid is null, show "Transcript unavailable — CLI UUID not discovered." | MVCR-1 | From open question #5, Architect F5 |
| E1.5 | As a user, when a session stops or disappears while I'm viewing it, I see a notification and the pane transitions gracefully | Toast notification: "Session ended." Terminal pane shows "Session ended" message with Resume button. Tab stays open (does not close). If transcript available, offer "View transcript" action. | MVCR-1 | From Dev Lead I-1 |

---

## Story Dependencies (MVCR-1)

```
Infrastructure
  I1.1 Session Discovery
  I1.2 Identity Loading ──────────┐
  I1.3 Data Store Merge ──────────┤
  I1.4 Terminal Connection         │
  I1.5 State Persistence           │
  I1.6 Component API               │
                                   ▼
Navigator                     Session Store
  N1.1 Layout ──────────────── (populated)
  N1.2 Compact Items                │
  N1.3 Platform Groups              │
  N1.4 Select ─────────────────────┤
  N1.5 Open in Tab ────────────────┤
  N1.6 Group Cards ────────────────┤
  N1.7 New Session                  │
                                   │
Cards                              │
  C1.1 Card Grid ──────────────────┤
  C1.2 Card Data                   │
  C1.3 Card States                 │
  C1.4 Focused State               │
  C1.5 Open-in-Tab Indicator       │
  C1.6 Open from Card ─────────────┤
                                   │
Tabs                               │
  T1.1 Tab Bar ────────────────────┤
  T1.2 Text Brightness             │
  T1.3 Keyboard Nav                │
  T1.4 Close                       │
  T1.5 Escape                      │
  T1.6 Persistence ────────── I1.5 │
                                   │
Terminal/Pane                      │
  P1.1 Live Terminal ──────── I1.4 │
  P1.2 Terminal Input              │
  P1.3 Pane Header                 │
  P1.4 Double-Esc Pass             │
  P1.5 Esc No-Close                │
  P1.6 Stopped Full-Width          │
                                   │
Prompt Box                         │
  B1.1 Layout                      │
  B1.2 Cmd+Enter Stage ──── P1.1   │
  B1.3 Edit Staged Text            │
  B1.4 Per-Tab State ──────── T1.6 │
  B1.5 Tab Key Indent              │
  B1.6 Focus Indicators            │
  B1.7 Auto-Sizing                 │
                                   │
Transcript (MVCR-1 minimal)        │
  R1.2 Exchange View               │
  R1.6 Scroll (Cmd+Home/End)      │
  (Full transcript → MVCR-2)      │
```

---

## Open Questions for Peer Review

### Resolved

1. **MVCR-1 scope — transcript panel:** YES, keep in MVCR-1. Stopped sessions need a view, and the transcript is it. The dev plan places it in Phase 3 (MVCR-2), but a minimal read-only transcript for stopped sessions should be in Phase 2 (MVCR-1). The full-featured transcript (filters, context menus, scroll persistence, slide-over on running sessions) is Phase 3. **Decision: split R1.x stories — R1.2 (basic exchange view) and R1.6 (stopped = full width) move to MVCR-1. Remaining R1.x stays MVCR-2.**

4. **Search panel:** MVCR-3. It depends on transcript indexing and content search infrastructure that won't exist until Phase 4+. The design doc lists it as "still pending" which means the UX isn't finalized — another reason to defer.

5. **`--no-mux` session display:** These sessions appear in the navigator and card grid like any other session. They show in transcript-only mode (no terminal pane). Add story: "As a user, sessions without terminal backing (--no-mux/--oneshot) show in navigator with a visual indicator and open in transcript-only mode." **Added as E1.4 in gap stories below.**

### Resolved by Architect (during review)

2. **MCP self-management (v0.1 S3.x):** **No new Session MCP.** Per Architect: set_chat_title is handled by sessionInfo.json display_name writes; signal_error and request_attention are handled by platform adapter activity detection; get_session_info and list_sessions are handled by Component API (SessionStore). Gap: no way for CLI to proactively push info to the app (e.g., "loaded these docs") — deferred, solvable via CLI writing to known file location that app polls. **Disposition: covered by existing mechanisms for MVCR-1-3. No stories needed.**

3. **Hook system:** **Not in UAI scope.** Per Architect: Claude Code's native hook system (`pre_tool_use`, `post_tool_use`, `pre_message`, `post_message` in settings.json) covers the v0.1 hooks. session_start/session_end handled by wrapper lifecycle. periodic handled by app polling + CLI native hooks. **Disposition: removed from backlog. No stories needed.**
