# UAI — MVCR Status Tracker

**Maintained by:** Pixel (UX Designer), with input from Dev Lead, Test Lead, and Hamilton
**Last updated:** 2026-04-03 by Pixel
**Source of truth for stories:** `architecture/story_backlog_v2.0.md`
**Source of truth for defects:** this file (below) + `testing/defects-run6.md`

---

## MVCR-1: Working Foundation

**Theme:** See it, use it
**Goal:** User can see all sessions, open them in tabs, interact via terminal, and launch new sessions. Core layout functional. One session at a time.
**Gate:** P1.1 + P1.2 + B1.2 must pass (live terminal + prompt staging). 0 High defects open.

### User Stories

Status key: **Done** = implemented | **Pass** = tested + verified | **Partial** = works with caveats | **Fail** = broken | **Blocked** = can't test | **Open** = not started | **—** = unknown

| ID | Story (short) | Dev | E2E | UX Attest | Notes |
|----|--------------|-----|-----|-----------|-------|
| **Infrastructure** | | | | | |
| I1.1 | Session Store loads all sessions | Done | — | Pass | 321 sessions loaded (2026-04-03) |
| I1.2 | Sessions keyed by tracking_id | Done | — | Pass | |
| I1.3 | Session fields available after merge | Done | — | Pass | |
| I1.4 | Terminal via node-pty + tmux attach | Done | — | Blocked | Needs live session test in packaged app |
| I1.5 | Persist UI state across restarts | Done | — | Blocked | Needs app restart cycle test |
| I1.6 | Launch CLI via wrapper scripts | Done | — | Blocked | macOS sandbox blocked in earlier runs; ai_launcher.py now available |
| **Navigator** | | | | | |
| N1.1 | Navigator 240px full height | Done | — | Pass | |
| N1.2 | Compact items (bar, name, ctx%, dot) | Done | — | Pass | |
| N1.3 | Grouped by platform, collapsible | Done | — | Pass | Chevron + count working |
| N1.4 | Single-click selects | Done | — | Pass | .nav-item-focused class applied |
| N1.5 | Double-click opens tab | Done | — | Pass | Tab created on dblclick |
| N1.6 | Group header toggles collapse + cards | Done | — | Pass | |
| N1.7 | "+ New Session" dropdown | Done | — | Pass | Claude/Codex/Gemini options. DEF-2: Custom not disabled |
| N1.8 | Default sort by last activity | — | — | — | PianoMan request. Not yet implemented? |
| N1.9 | Compact + area with Search/Tab Group | — | — | — | PianoMan request |
| N1.10 | Click group = select; chevron = collapse | — | — | — | PianoMan request. Currently click does both |
| **Session Cards** | | | | | |
| C1.1 | Cards in center pane when browsing | Done | — | Pass | Card grid with platform bars |
| C1.2 | Cards show name, time, dot, meta, badges | Done | — | Pass | Verified in screenshot |
| C1.3 | Active full color; stopped muted | Done | — | Partial | DEF-1: platform bars also muted (should only mute text) |
| C1.4 | Focused card blue border + glow | — | — | — | |
| C1.5 | Cards open in tab show indicator | — | — | — | |
| C1.6 | Double-click card opens tab | Done | — | Pass | |
| C1.7 | Active/Stopped collapsible sections | — | — | — | PianoMan request (High) |
| C1.8 | Group headers show x/y active count | — | — | — | PianoMan request |
| C1.9 | Single-click card shows Session Details | — | — | — | PianoMan request (2026-04-03) |
| **Tab Bar** | | | | | |
| T1.1 | Browser-style tabs | Done | — | Pass | Platform bar, dot, name, close button |
| T1.2 | Running bright; stopped muted | Done | — | Pass | .stopped class applied |
| T1.3 | Cmd+1-9, Cmd+Shift+[/] switching | — | — | Blocked | Electron accelerator, untestable via CDP |
| T1.4 | Close with Cmd+W or x | Done | — | Partial | x works; Cmd+W untestable via CDP |
| T1.5 | Escape does NOT close tabs | — | — | Blocked | Needs live session |
| T1.6 | Tabs persist across restarts | Done | — | Blocked | Needs restart cycle |
| **Terminal / Session Pane** | | | | | |
| P1.1 | Live terminal for running session | Done | — | Blocked | **GATE STORY.** Saw live terminal in screenshot 2 (2026-04-03) but not attested by Pixel |
| P1.2 | Type in terminal, keystrokes reach CLI | Done | — | Blocked | **GATE STORY.** Needs live session |
| P1.3 | Pane header (bar, name, focus, ctx%) | Done | — | Pass | |
| P1.4 | Double-Esc clears input; Triple+ cancels AI | — | — | Blocked | **CORRECTED** by PianoMan. Needs live session |
| P1.5 | Escape does NOT close pane | — | — | Blocked | Needs live session. Customer decision pending |
| P1.6 | Stopped session shows transcript full-width | Done | — | Pass | |
| P1.7 | Pane header: Terminal ID, Session ID, Time | — | — | — | PianoMan request. Partially visible in Context panel |
| **Prompt Box** | | | | | |
| B1.1 | Prompt box at bottom with target + hint | Done | — | Pass | "-> Session Name" + "Cmd+Enter to stage" |
| B1.2 | Cmd+Enter stages text to CLI | — | — | Blocked | **GATE STORY.** Needs live session |
| B1.3 | Edit staged text before Enter | — | — | Blocked | Needs live session |
| B1.4 | Each tab maintains own prompt text | — | — | Blocked | Needs tab switching with typed text |
| B1.5 | Tab inserts indent | Done | — | Pass | |
| B1.6 | Visual focus distinction (prompt vs terminal) | — | — | — | |
| B1.7 | Auto-grow/shrink + resize handle | Done | — | Pass | Resize handle present |
| B1.8 | Prompt box looks like text input | — | — | — | PianoMan request. Needs border/bg styling |
| B1.9 | Resize drag works correctly | — | — | — | PianoMan request. Global mouseup listener |
| **Transcript** | | | | | |
| R1.2 | Exchanges (user + AI pairs) | Done | — | Pass | Renders, but DEF-3: user messages empty |
| R1.6 | Starts at bottom; Cmd+Home/End | — | — | — | |
| **Visual System** | | | | | |
| V1.1 | 2px borders at #606d94 | Done | — | Pass | |
| V1.2 | 3px platform color bars everywhere | Done | — | Pass | Navigator, cards, tabs, pane headers |
| V1.3 | Readable text sizes | Done | — | Pass | |
| V1.4 | Scrollbars wide enough to grab | — | — | — | PianoMan request |
| V1.5 | Focus = bright border, not text label | — | — | — | PianoMan request. Remove [FOCUS] tag |
| V1.6 | Slide-out panels consistent position | — | — | — | PianoMan request |
| V1.7 | Session Details panel visual hierarchy | — | — | — | PianoMan request (2026-04-03) |
| **Edge Cases** | | | | | |
| E1.1 | Zero sessions — empty state | Done | — | Pass | Tested in early runs |
| E1.2 | New session auto-opens in tab | — | — | Blocked | Needs session creation working |
| E1.3 | Session disappears while tab open | — | — | Blocked | Needs live session |
| E1.4 | Rapid tab switching | — | — | Blocked | Needs multiple open tabs with terminals |
| E1.5 | Window resize preserves layout | — | — | — | |

### Summary

| Status | Count |
|--------|-------|
| Pass | 22 |
| Partial | 2 |
| Fail | 0 |
| Blocked | 14 |
| Open/Unknown | 14 |
| **Total** | **52** |

**Gate stories (must pass for MVCR-1 ship):** P1.1, P1.2, B1.2 — all currently Blocked on live session testing.

---

### Defects

| ID | Summary | Severity | Status | Blocks Story |
|----|---------|----------|--------|--------------|
| DEF-1 | Platform color bars muted for stopped sessions | Medium | Open | C1.3 |
| DEF-2 | "Custom..." not disabled in dropdown | Low | Open | N1.7 |
| DEF-3 | Transcript shows empty user messages | **High** | Open | R1.2 |
| DEF-4 | "Open as Tab Group" splits center into grid (wrong behavior) | Medium | Open | N2.8 (MVCR-2 but button exists in MVCR-1) |
| DEF-5 | Tab text too hard to read, especially focused tab | Medium | Open | T1.1 |
| DEF-6 | Tab orange bar separator too contrasting | Low | Open | V1.2 |
| DEF-7 | Transcript yellow hover box unclear purpose | Low | Open | R1.2 |

### PianoMan Requests (not yet storied or in-progress)

Items from PianoMan's feedback that are tracked as customer requests, not defects:

| # | Request | Priority | MVCR | Story ID |
|---|---------|----------|------|----------|
| 1 | Cards: Active/Stopped collapsible sections | High | 1 | C1.7 |
| 2 | Navigator sort by last message time | Med-High | 1 | N1.8 |
| 3 | Prompt box resize fix | Med | 1 | B1.9 |
| 4 | Card state indicators (full set) | Mixed | 3 | A3.6 |
| 5 | Card context menu (Rename, Copy, etc.) | Med | 2 | M2.5 |
| 6 | Session Mgmt submenu (Resume, Stop, Fork) | Med | 2 | M2.6 |
| 7 | Multi-select Roles | Low | 3 | M3.1 |
| 8 | Compact + button with Search/Tab Group | Low-Med | 1 | N1.9 |
| 9 | Search button | Med | 2 | N2.9 |
| 10 | Slide-out panels consistent position | Med | 1 | V1.6 |
| 11 | Group cards show x/y active count | Low-Med | 1 | C1.8 |
| 12 | Consolidated group badges | Low | 2 | C2.1 |
| 13 | Scrollbars larger | Med | 1 | V1.4 |

### PianoMan Feedback Round 2 (2026-04-03)

| # | Feedback | Action |
|---|----------|--------|
| 1 | Session Details panel needs visual improvement | Storied as V1.7 |
| 2 | Transcript/history is MVCR-1 | Confirmed — R1.2, P1.6 in scope. DEF-3 blocks. |
| 3 | Grid not required, lots of work | Grid is MVCR-2 (SV2.x). Don't invest now. |
| 4 | Open as Tab Group wrong behavior | DEF-4 filed. Correct: creates tab bracket, not grid. |
| 5 | Single-click card shows Session Details | Storied as C1.9 |

---

## MVCR-2: Organized Workspace

**Theme:** Manage it
**Goal:** Full navigator with filter/group/sort. Tab Groups with split view. Full prompt box with history, commands, shell mode. Context menus. Custom launch dialog.
**Depends on:** MVCR-1

### User Stories

| ID | Story (short) | Dev | E2E | Notes |
|----|--------------|-----|-----|-------|
| **Navigator Enhancements** | | | | |
| N2.1 | Filter by platform/status/type/role/text | — | — | |
| N2.2 | Group by platform/role/status/parent/custom | — | — | |
| N2.3 | Sort by activity/created/name/exchanges/ctx% | — | — | Default sort pulled to MVCR-1 as N1.8 |
| N2.4 | Multi-group membership | — | — | |
| N2.5 | Focused session highlights its groups | — | — | |
| N2.6 | Focused session highlighted in navigator | — | — | |
| N2.7 | Create custom groups via context menu | — | — | |
| N2.8 | "Open as Tab Group" from navigator group | — | — | DEF-4: currently does wrong thing |
| N2.9 | Search button in navigator toolbar | — | — | PianoMan request |
| **Tab Groups** | | | | |
| G2.1 | Create Tab Group via right-click | — | — | |
| G2.2 | Tab Groups show bracket + name + count | — | — | |
| G2.3 | Close tab in group = hide, not remove | — | — | |
| G2.4 | Collapse Tab Group to single tab | — | — | |
| G2.5 | "+N more" popup for hidden sessions | — | — | |
| G2.6 | Remove from group via right-click | — | — | |
| G2.7 | Ungroup via right-click | — | — | |
| G2.8 | Tab Groups #7aa2f7 border | — | — | |
| G2.9 | Double-click group header shows member cards | — | — | |
| **Split View** | | | | |
| SV2.1 | 2+ visible sessions in split layout | — | — | Grid partially works already |
| SV2.2 | Click pane to switch focus in split | — | — | |
| SV2.3 | Cmd+1-4 focus pane by position | — | — | |
| SV2.4 | Draggable split divider | — | — | |
| **Prompt Box Enhancements** | | | | |
| B2.1 | Up/Down arrow prompt history | — | — | |
| B2.2 | !history popup | — | — | |
| B2.3 | $ commands for bash | — | — | |
| B2.4 | Shell output "Send to CLI" action | — | — | |
| B2.5 | !help lists commands | — | — | |
| B2.6 | !/$ prefix routing | — | — | |
| **Launch & Files** | | | | |
| L2.1 | Custom Launch dialog | — | — | |
| L2.2 | Attach files in launch dialog | — | — | |
| L2.3 | Drag-drop files into prompt box | — | — | |
| L2.4 | Drag-drop files into terminal | — | — | |
| **Full Transcript** | | | | |
| R2.1 | Transcript as slide-over on running sessions | — | — | |
| R2.3 | Tool calls collapsed; thinking hidden | — | — | |
| R2.4 | Filter checkboxes (User/AI/Tools/Thinking) | — | — | |
| R2.5 | Collapse/expand any block | — | — | |
| R2.6 | Manual scroll position respected | — | — | |
| R2.7 | Transcript persists across tab nav | — | — | |
| R2.8 | Refresh button | — | — | |
| R2.9 | Hover actions (Copy, Jump) | — | — | |
| **Context Menus** | | | | |
| M2.1 | Right-click card: Rename/Stop/History/Delete/Add to Group | — | — | |
| M2.2 | Right-click tab: Rename/Close/Stop/Add to Group | — | — | |
| M2.3 | Right-click transcript blocks | — | — | |
| M2.4 | Right-click navigator groups | — | — | |
| M2.5 | Card context menu: Copy submenu, Session Details | — | — | PianoMan request |
| M2.6 | Session Mgmt submenu: Resume/Stop/Archive/Delete/Fork | — | — | PianoMan request |
| **PianoMan additions** | | | | |
| C2.1 | Consolidated group badges/indicators | — | — | PianoMan request |

### Summary

| Status | Count |
|--------|-------|
| Open/Unknown | 42 |
| **Total** | **42** |

---

## Cross-Reference

| File | Purpose |
|------|---------|
| `architecture/story_backlog_v2.0.md` | Full story definitions with acceptance criteria |
| `architecture/customer-decisions-pending.md` | Decisions made on customer's behalf, pending review |
| `docs/decision-logs.md` | All team decisions with rationale |
| `testing/attestation-mvp-pixel.md` | UX attestation runs and results |
| `testing/defects-run6.md` | Detailed defect descriptions |

---

*On the question of tracking tools: this markdown file works for now. If the story count grows or we need richer querying (filter by status, owner, MVCR), a SQLite backend or todo_mgr with typed items (story/bug/task) would scale better. For now, one file everyone can read and update is the right level of overhead.*
