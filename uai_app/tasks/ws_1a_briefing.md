# Workstream 1A Briefing: Core Stores + Command Bus

**Project:** UAI (Unified AI Interface) — architectural successor to UCI
**DevTree:** uai-resurrection
**AI_ROOT:** $HOME/Documents/AI/devTrees/AI_ROOT_uai-resurrection
**Project Dir:** ai_general/projects/unified_ai_interface

## Your Mission

Build the architectural foundation that all other workstreams depend on.
You are implementing the command bus, store layer, component API framework,
and action context providers. When you're done, the spike's ad-hoc IPC
becomes a proper architectural layer.

## Read Before Starting (in order)

1. **Architecture spec:** `architecture/uai_architecture_v1.1.md` — Sections 4 (Component API), 5 (Command System), 6 (Events)
2. **Contracts:** `architecture/contracts/*.ts` — frozen TypeScript interfaces you implement against
3. **Spike code:** `spikes/phase_0b_vertical_slice/` — working patterns to replicate and evolve
4. **Phase 0B completion:** `docs/phase_0b_completion.md` — lessons learned
5. **Delegation plan:** `tasks/phase_1_delegation.md` — Section "Workstream 1A" for your full scope and acceptance criteria

## Key Architectural Rules

1. **Path 1 (outbound):** UI action → command bus → main process handler → store mutation
2. **Path 2 (inbound):** Store change → event → renderer snapshot update → UI re-render
3. **Store mutation is the handoff point** — Path 1 ends there, Path 2 begins
4. **Components never mutate durable state directly** — they dispatch commands
5. **All domain mutations go through the command bus** — no direct IPC for writes
6. **Every architectural component provides describe()** returning ComponentDescription

## What You're Building

### 1A.1 — Command Bus (`src/main/command-bus.ts` + renderer bridge)
### 1A.2 — Store Layer (`src/renderer/stores/` — SessionStore, AppStateStore, FolderStore)
### 1A.3 — Component API Framework (`src/shared/component-registry.ts`)
### 1A.4 — Action Context Providers (`src/renderer/context/`)

See `tasks/phase_1_delegation.md` for detailed scope and acceptance criteria per sub-task.

## Output

Write production code in `src/`. Reference spike in `spikes/phase_0b_vertical_slice/`.
The spike app should still work when you're done — you're evolving it, not replacing it.

## Escalation

Architecture questions → prompt Continuity II at session 20260422_204104_640a7e0c_cla
Scope/UX questions → escalate to PianoMan

When done, send a prompt to Continuity II confirming completion.
