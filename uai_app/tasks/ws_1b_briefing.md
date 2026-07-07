# Workstream 1B Briefing: Core UI

**Project:** UAI (Unified AI Interface) — architectural successor to UCI
**DevTree:** uai-resurrection
**AI_ROOT:** $HOME/Documents/AI/devTrees/AI_ROOT_uai-resurrection
**Project Dir:** ai_general/projects/unified_ai_interface

## Your Mission

Build the core UI components: Tabbed Navigator, Workspace with tabs, Terminal Pane
with Memorex, PromptBox, and Context Panel. You build ON TOP of the 1A foundation
(command bus, stores, component registry, action context).

## Read Before Starting (in order)

1. **Architecture spec:** `architecture/uai_architecture_v1.1.md` — Sections 8 (UI Component Hierarchy), 9 (Visual System)
2. **Frontend design:** `architecture/archive_originals/2026-03-30-frontend-design-v2.md` — detailed UI specs
3. **1A code:** `src/main/`, `src/renderer/stores/`, `src/shared/` — the foundation you build on
4. **Spike code:** `spikes/phase_0b_vertical_slice/` — working terminal, Memorex, selection overlay
5. **Contracts:** `architecture/contracts/components.ts` — component types, NavigatorTab, GridLayout, etc.
6. **Delegation plan:** `tasks/phase_1_delegation.md` — Section "Workstream 1B" for scope and acceptance

## Key Rules

1. **Use stores from 1A** — useSessionStore(), useAppStateStore(), useFolderStore(). No direct IPC.
2. **Dispatch commands via command bus** — window.uai.execute() for mutations. Never direct IPC writes.
3. **Register every component** with ComponentRegistry and provide describe()
4. **Use ActionContextProvider** for regions with clickable actions
5. **Design tokens only** — use CSS custom properties from :root, no raw values
6. **Port from spike** — TerminalPane, MemorexView, SelectionOverlay are in spikes/phase_0b_vertical_slice/. Carry forward, integrate with 1A stores/commands.

## What You're Building

### 1B.1 — Tabbed Navigator (`src/renderer/components/Navigator.tsx`)
### 1B.2 — Workspace with tabs (`src/renderer/components/Workspace.tsx`)
### 1B.3 — Terminal Pane + Memorex (port from spike, wire to 1A)
### 1B.4 — PromptBox (`src/renderer/components/PromptBox.tsx`)
### 1B.5 — Context Panel (`src/renderer/components/ContextPanel.tsx`)

Plus: `src/renderer/App.tsx` wiring everything together, `src/renderer/styles/` with design tokens.

See `tasks/phase_1_delegation.md` for detailed acceptance criteria per sub-task.

## Important: Parallel Work

Workstream 1C (Organization — folders, tags, relationships) is running in parallel.
You may encounter incomplete folder/tag functionality. Use stubs where needed.
Do NOT modify files in `src/main/command-handlers.ts` for folder/tag commands — 1C owns those.

## Output

Production code in `src/renderer/` (components, styles) and `src/renderer/App.tsx`.
Port terminal/memorex/overlay from spike. Everything must compile and render.

## Escalation

Architecture questions → prompt Continuity II at session 20260422_204104_640a7e0c_cla
Scope/UX questions → escalate to PianoMan

When done, send a prompt to Continuity II confirming completion.
