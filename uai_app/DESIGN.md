# UAI — Unified AI Interface

## Project Identity

- **Name**: Unified AI Interface (UAI)
- **Deploy**: `ai_general/apps/unified_ai_ui/UnifiedAI.app`
- **Predecessor**: UCI (Unified CLI Interface) at `projects/unified_cli_interface/`
- **Archived predecessor**: `projects/archive/unified_ai_interface/`
- **Former DevTree**: `uai-resurrection` — merged to main 2026-05-21

## Purpose

Desktop workspace for managing multiple simultaneously running AI CLI agent sessions.
Preserves the terminal interaction model while adding organization, orchestration,
and automation. UAI is the architectural successor to UCI — same problem space,
new foundation.

## Key Architectural Principles

1. **External Ground Truth** — The app reflects external state, never maintains divergent copies.
   Optimistic updates shown as drafts until confirmed by external store.
2. **Component API Layer** — Every architectural UI component exposes get/set/update/delete/list.
   All state mutations flow through component APIs.
3. **Command Bus** — All actions route through a typed command hierarchy with entry/exit hooks.
   Enables logging, undo, access control, and embedded AI interaction.
4. **Event System** — Fine-grained subscriptions replace polling. Components react to state changes.
5. **MVC Separation** — Model (component state), View (React rendering), Controller (command handlers).
   Views never mutate state directly.
6. **Data Ownership Boundary** — *Only app-unique, app-specific data can be maintained and stored by
   the UAI app. All other state data pertaining to objects and entities that exist outside the app
   must be maintained and stored outside the app as part of the data store for those objects and
   entities.* The app may READ and DISPLAY external entity data (sourced live from that entity's own
   store), but must never own, persist, or become the source of truth for it. Examples of
   externally-owned data the app must only read: a session's Turns, Messages, Context Used, queued
   Prompts, and Comms (inbox) — these originate outside the app (per-session state file written by
   scaffolding; the `ai_comms` message store; the prompt queue) and are read-only to the app.
   App-unique data the app MAY own: tab layout, pinned session, panel/view UI state, per-session
   UI prefs (draft text, notes-display toggles), custom themes, feature flags.

## Directory Structure

```
architecture/                # Architecture docs, specs, component API contracts
architecture/adrs/           # Architecture Decision Records (one per decision, never edited)
architecture/current_references/  # Working reference docs (identity spec, UCI data arch)
architecture/archive_originals/   # Superseded specs (v0.2, v4.2, etc.)
docs/                        # General documentation
docs/plans/                  # Phase plans, workstream plans
docs/designs/                # Feature design docs
docs/issues/                 # Test findings, bug reports
reviews/                     # Code and design review artifacts
tasks/                       # Task tracking, workstream briefings
app/                         # Electron app (monorepo root)
  app/main/                  # Main process (IPC, node-pty, stores, indexers)
  app/renderer/              # App.tsx shell entry point
  app/resources/             # Icons, assets
  app/tests/                 # Test infrastructure
packages/shared/             # Types, contracts, entity types
packages/renderer-ui/        # All React components
scripts/                     # Build, deploy, utility scripts
spikes/                      # Proof-of-concept experiments
```

## Relationship to UCI

Both UAI and UCI (`projects/unified_cli_interface/`) are deployed production apps.
UCI's Electron main process, session management IPC, and visual component designs
(including Memorex/TerminalFormatOverlay) carried forward into UAI. UCI's renderer
architecture (monolithic App.tsx, prop-drilling, ad-hoc state) is replaced by the
UAI architecture (monorepo, component API, command bus).

## Constraints

- Electron + xterm.js + node-pty + tmux (decided, carries forward from UCI)
- TypeScript + React renderer
- Single user (PianoMan), single machine (macOS)
- Must support Claude CLI, Codex CLI, Gemini CLI simultaneously
- Session identity follows spec_session_identity (tracking IDs as primary keys)
