---
task_id: ws_2d
task_type: implementation
created: 2026-04-28T00:00:00Z
status: staged
depends_on: [ws_2b, ws_2c]
protocol: ai_general/ai_traits/processes/30_protocols/protocol_taskCoordination.latest.condensed.yml
---

# 2D: Tab Model Refactor + Group Tabs

**Project:** UAI (Unified AI Interface)
**DevTree:** AI_ROOT_uai-resurrection
**Project Dir:** ai_general/projects/unified_ai_interface
**Source Dir:** src/ (under project dir)

## Objective

Generalize the tab and workspace pane model to support multiple tab types (session, folder, group, terminal, brief), then implement Group Tab bracket rendering ported from UCI.

## Critical Design Decisions (from docs/plans/phase_2_plan.md)

**Tabs are entity views.** Every tab views an entity. The tab type determines what renders in the content pane.

**Folders vs Groups project differently into the workspace:**
- Opening a folder creates a **folder tab** — a content browser (like file explorer)
- Opening a group creates a **Group Tab** — a bracket in the tab bar with live member session tabs inside

**The current SessionPane becomes TabContentPane** — dispatches based on tab.type.

## What to Build

### Part 1: Tab Model Refactor

1. **New Tab type** — Replace `TabState` in `src/shared/types.ts`:
   ```typescript
   type TabType = 'session' | 'folder' | 'group' | 'terminal' | 'brief';
   interface Tab {
     id: string;
     type: TabType;
     label: string;
     targetId: string;  // tracking_id, folder_id, group_id, terminal_id, brief_name
     openedAt: string;
   }
   ```

2. **TabContentPane** — Rename/refactor SessionPane to dispatch based on tab.type:
   - `session` → SessionContent (terminal + Memorex + PromptBox — extract from current SessionPane)
   - `folder` → FolderContent (CardListView + ContainerTreeView + breadcrumbs)
   - `group` → GroupContent (group management: member list, add/remove, color, layout selector)
   - `terminal` → TerminalContent (raw xterm.js shell, no AI session)
   - `brief` → BriefContent (rendered brief document)

3. **Update Workspace.tsx** — Use TabContentPane instead of SessionPane

4. **Update App.tsx** — Handle opening different tab types

5. **Update app_state persistence** — Store Tab[] instead of TabState[]

6. **Update workspace.tabs.* commands** — Accept tab type in payload

### Part 2: Group Tab Brackets

7. **Bracket rendering** — When a group is "opened," render a visual bracket in the tab bar:
   - Color-coded left border from group's color
   - Group header tab with collapse toggle, group name, member count
   - Member session tabs nested inside the bracket
   - Collapsed state: only header shows with +N indicator
   - Port bracket rendering from UCI TabBar.tsx lines 327-378

8. **Open/close group semantics:**
   - Open group = create group header tab + open all visible member session tabs inside bracket
   - Close group = close all member tabs + remove bracket (group still exists in Navigator)
   - Collapse = hide member tabs, show only header with +N count

9. **Visibility management:**
   - `visibleIds` (shown as tabs) vs full membership (container.children) — stored in app_state per group
   - "Hide in Group" = remove from visibleIds, keep in container
   - "Show in Group" = add back to visibleIds

10. **Context menus:**
    - Group header tab: Rename, Delete, Collapse/Expand, Grid Layout (placeholder for 2E)
    - Session tab in bracket: Hide in Group, Remove from Group, Move to other Group

### UCI Reference

Read these files in the UCI codebase for reference implementation:
- `ai_general/projects/unified_cli_interface/src/src/renderer/components/TabBar.tsx` — bracket rendering (lines 327-378)
- `ai_general/projects/unified_cli_interface/src/src/shared/groups.ts` — TabGroup type, creation helper, GROUP_COLORS palette
- `ai_general/projects/unified_cli_interface/src/src/main/groups.ts` — IPC handlers
- `ai_general/projects/unified_cli_interface/src/src/renderer/components/GroupCard.tsx` — presentational
- `ai_general/projects/unified_cli_interface/src/src/renderer/App.tsx` — state management (search for tabGroups, openGroupIds)

Key UCI design decisions to preserve:
- `sessionIds` (all members) vs `visibleIds` (currently shown as tabs) split
- 8-color palette chosen to avoid confusion with active tab highlight
- Explicit membership (no auto-generation)
- Collapse optimization (one click to reduce clutter)

Key UCI design decisions to NOT port:
- Synthetic `group:<id>` tab IDs — use the proper Tab type with `type:'group'`
- Separate groups.json — groups live in containers.json
- Legacy Group system (GroupRail) — does not exist in UAI

## Validation

- `cd src && npx tsc --noEmit` — must pass
- `cd src && npx vitest run` — all tests must pass
- Session tabs still work as before
- Folder tabs open and show browsable content
- Group Tabs show bracket with member sessions
- Collapse/expand works
- Tab type persists across app restart
- Raw terminal tab can be created (even if no UI to create one yet — the type must be supported)

## Done When

Multiple tab types render correctly in the workspace. Folders open as browsable content tabs. Groups open as bracket Group Tabs with live member sessions. Collapse/expand and visibility management work. Tab type and state persist across restart.
