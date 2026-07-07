---
task_id: ws_2e
task_type: implementation
created: 2026-04-28T00:00:00Z
status: staged
depends_on: [ws_2d]
protocol: ai_general/ai_traits/processes/30_protocols/protocol_taskCoordination.latest.condensed.yml
---

# 2E: Grid Layout for Group Tabs

**Project:** UAI (Unified AI Interface)
**DevTree:** AI_ROOT_uai-resurrection
**Project Dir:** ai_general/projects/unified_ai_interface
**Source Dir:** src/ (under project dir)

## Objective

Implement split/grid pane layouts for Group Tabs so users can view multiple sessions side-by-side.

## What to Build

1. **SplitLayout type:** `'single' | 'vertical_2' | 'horizontal_2' | 'grid_2x2'`

2. **Grid rendering in Workspace** — When a Group Tab has a non-single layout, render 2-4 TabContentPane instances in a CSS grid/flex layout

3. **Grid selector UI** — Toolbar button or context menu item on Group Tab header to switch layouts. Show layout icons (single square, two vertical rectangles, two horizontal rectangles, four squares)

4. **Cell assignment** — Each grid cell displays one of the group's visible member sessions. Redistributing members across cells when switching layouts.

5. **Resizable pane dividers** — Same drag-to-resize pattern as the Memorex split divider in TerminalPane

6. **Per-group persistence** — Layout stored in app_state per group ID

7. **Grid layout applies to Group Tabs only** — Individual session/folder/brief tabs are always single pane

## Validation

- `cd src && npx tsc --noEmit` — must pass
- `cd src && npx vitest run` — all tests must pass
- User can switch between 1x1, 2x1, 1x2, 2x2 layouts
- Each cell shows a different session with its own terminal
- Layout persists across restart
- Resizing pane dividers works smoothly

## Done When

User can switch a Group Tab between all four layout modes. Each cell renders an independent session with terminal. Layout choice persists.
