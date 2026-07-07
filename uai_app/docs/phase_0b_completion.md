# Phase 0B Completion — Vertical Slice Spike

**Date:** 2026-04-23
**Author:** Continuity II (Claude CLI, Architect)
**Status:** Complete

## What Was Proven

The UAI architecture works in running code. Every foundational pattern has been
demonstrated with a functional Electron app.

### Infrastructure Patterns

| Pattern | How Proven |
|---------|-----------|
| External ground truth | App reads from session_store.py (SQLite), never opens DB directly |
| Path 1 (outbound) | Rename: UI action → IPC command → session_store.py update → SQLite |
| Path 2 (inbound) | Signal file watch → main detects → emits onStoreChanged → renderer refreshes |
| Dovetailed paths | Store mutation is the handoff point. UI reacts uniformly to own commands and external changes. |
| Shared store | useSessionStore() singleton — all components read from same snapshot, no prop-drilling |
| Draft session creation | App generates tracking ID (app-unique prefix), pre-populates fields, calls ai_launcher --tracking-id |
| External session detection | sessions.changed signal file → fs.watch → debounced refresh → new sessions appear |

### Terminal Patterns

| Pattern | How Proven |
|---------|-----------|
| Terminal embedding | xterm.js + node-pty + tmux attach-session |
| Selection overlay | Ported TerminalSelectionOverlay from UCI — click, drag, shift-click, scroll, copy, paste |
| Shift+Enter newline | Custom key handler: LF instead of CR |
| Clipboard | Electron main process clipboard API via IPC (not navigator.clipboard) |
| Application menu | Required for Cmd+C/V to work in Electron |

### Memorex Overlay

| Pattern | How Proven |
|---------|-----------|
| JSONL transcript rendering | read_jsonl.py → structured JSON → formatted blocks (user/assistant/tool/thinking) |
| Split view | Memorex zone (transcript) above, Live zone (terminal) below |
| Draggable divider | Mouse drag resizes split, clamped 15-85%, terminal re-fits automatically |
| Toggle | Button in terminal header enables/disables Memorex without remounting terminal |

### Session Identity

| Pattern | How Proven |
|---------|-----------|
| App-generated TrackingId | Format: {date}_{time}_app{hex5}_{platform3} — unmistakably app-originated |
| Draft pre-population | App sets display_name, roles, project_dir before launcher runs |
| Launcher reads draft | ai_launcher --tracking-id reads pre-populated fields from session store |

## What Was NOT Proven (by design — not risky)

| Pattern | Why Deferred |
|---------|-------------|
| Component API (get/set/update/delete/list) | Well-understood pattern. Contracts typed in architecture/contracts/. |
| Component self-description (describe()) | No technical risk. Implementation is type+schema work. |
| Command bus with hierarchy | Standard middleware pattern. No novel mechanics. |
| Action context providers | React context pattern. Well-understood. |
| Access control matrix | Configuration, not architecture risk. |
| Notification bus | Extension of event system. Delivery adapters are the work. |

## Files Created

```
src/
  package.json
  tsconfig.json
  forge.config.ts
  vite.main.config.ts
  vite.preload.config.ts
  vite.renderer.config.ts
  index.html
  src/
    main/
      index.ts              — Main process: IPC, signal file watch, app menu, session create/launch
      preload.ts            — IPC bridge: window.uai API
      session-store.ts      — session_store.py adapter (list, get, update, createDraft, launch)
      terminal.ts           — node-pty management (attach, write, resize, detach)
    renderer/
      App.tsx               — Navigator + workspace layout with session selection
      index.tsx             — React root
      global.d.ts           — window.uai type declaration
      styles.css            — Design tokens + all component styles
      stores/
        session-store.ts    — Shared singleton store with useSessionStore() hook
      components/
        SessionList.tsx     — Session cards, context menu, rename, create buttons
        TerminalPane.tsx    — xterm.js terminal with Memorex toggle and draggable split
        TerminalSelectionOverlay.tsx — Selection, copy, paste, links (ported from UCI)
        MemorexView.tsx     — Formatted JSONL transcript zone (ported from Canopy)
    shared/
      types.ts              — Session, StoreChangedEvent, CommandResult, IPC channels
scripts/
  start.sh                  — Launch from anywhere
```

## Lessons Learned

1. **Electron requires application menu for clipboard** — Cmd+C/V don't work without Menu.setApplicationMenu() with Edit roles.
2. **Don't reparent xterm.js** — Wrapping a mounted xterm instance in a new DOM parent breaks it. Use sibling layout instead.
3. **read_jsonl.py interface** — Uses `find <uuid>` then `read-file <path> --format structured`, not flags.
4. **sessionInfo uses instance naming** — `sessionInfo.{uuid8}.json`, not plain `sessionInfo.json`.
5. **session_store.py create doesn't have --roles** — Set roles via separate `update --set roles=...` call.
6. **Claude CLI requires full UUID** — The uuid8 from tracking ID is not a valid session ID. Generate a proper UUID.
7. **Signal file debounce** — Multiple rapid writes → debounce to 300ms before refresh.
8. **Memorex polling at 5s** — 2s caused scroll lag on large sessions.

## Next: Phase 1 Delegation

The spike establishes patterns that Phase 1 workers replicate. Key reference points:
- session-store.ts: how to call session_store.py
- stores/session-store.ts: how to build a shared renderer store
- TerminalPane.tsx: how to integrate xterm.js + overlays
- index.ts: how to set up IPC handlers and signal file watching
- styles.css: design token convention

Architecture spec: architecture/uai_architecture_v1.1.md
Contracts: architecture/contracts/*.ts
Identity spec: architecture/spec_session_identity_v5.4.md
