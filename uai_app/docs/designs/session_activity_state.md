# Session Activity State — Design

Status: **v1 implemented + live-CDP-verified** (hidden offscreen instance, port 9227, 2026-06-21)
Owner: Relay (claude_cli_8866) — single session, end-to-end (crosses app + scaffolding per PianoMan's "one session owns a crossing feature" rule)
Date: 2026-06-21

## Implementation status (v1)

Built:
- `ai_general/scripts/session_mgmt/lib_session_activity.py` — shared, change-guarded writer of `session.activity_state` (+ `_at`) to the per-session state file; touches `sessions.changed`.
- `UserPromptSubmit/00_mark_busy_async.py` → also writes `responding`.
- `Stop/04_store_session_data_async.py` → writes `idle` (the designated shared-file Stop writer; `mark_idle` keeps its dedicated `activity_state.json`).
- `session_ops.get_ai_status` → persists its reconciled ground-truth state on change (catches prompt_occupied / permission / blocked + interrupt-idle).
- App: `session-store.ts` reads `state['session.activity_state']`; `shared/types.ts` gains `prompt_occupied`.
- Renderer: `pulse`→`breathing` rename across `session-state.ts`, `SessionStateIndicator.tsx`, `Navigator.tsx`, `Workspace.tsx`, `styles.css` (`.session-breathing` + keyframes). `needs-input` (permission_prompt) keeps a distinct amber + breathing.

Verified: app `tsc --noEmit` EXIT 0 (full type context); rename has zero leftovers (grep); `lib_session_activity` functional test (change-guard, unknown-rejection, signal-file touch all pass).

Live CDP verification (2026-06-21, hidden offscreen instance on :9227, built v1.1.99):
- App rendered with no error; renamed `.session-breathing` CSS rule present in bundle; zero stale `.session-pulse`.
- Real IPC `sessions.list()` (runs the edited main-process `mapSession`) reported live states: responding 5, idle 13, permission_prompt 1, unknown 495 (historical/stopped). Sensible per-session (e.g. Noctis responding while active).
- Cross-check: 5 responding + 1 permission_prompt = 6 breathing-eligible == exactly the 6 `.session-breathing` elements in the DOM.
- Causality toggle: writing `session.activity_state=responding` to a session's state file + touching `sessions.changed` → IPC reported `responding` within the debounce; revert → `idle` (target restored net-zero).

## Terms

- **activity_state** — what a session's CLI agent is *doing right now*: `idle`, `responding`, `working` (running a tool), or `needs-input` (waiting on the user). The live counterpart to the already-tracked `last_activity` timestamp.
- **Session-Breathing** — the soft fade in/out animation on a session's status dot while it is non-idle. (Renamed from "pulse" — that term has a legacy meaning. Affected code: `.session-pulse` class/keyframes → `.session-breathing`.)
- **The state file** — `{session_dir}/{tracking_id}_state.json`. The model of record; hooks write it, the app reads it.
- **Signal file** — `ai_general/data/sessions.changed`. Touched by `session_store.py`; the app `fs.watch`es it to know the store changed.
- **Route B** — the chosen architecture: session state changes are captured as discrete *events* (hooks) written into the state file and propagated via the signal file. (Route A — deriving state from a continuously-fed per-session Memorex model in the app — was rejected for activity_state because it can only see sessions the user has open as tabs; see "Why Route B".)

## Why Route B (not the renderer/Memorex-model route)

The indicators (Recent Sessions, cards, tabs) are **system-wide** — they show sessions running in other terminals and on other tmux servers, most of which the user has *not* opened as a tab. A model fed by open tabs' live terminals (Route A) structurally cannot produce state for those sessions. Hooks fire **inside each session's own process**, independent of UAI focus or whether UAI is even running — so they are the only source that covers the full set the UI displays.

This keeps MVC clean without renderer-side logic:
- **Model** = the state file (`session.activity_state` is one more field, exactly like `session.last_activity`).
- **Controller** = the hooks (+ a shared writer + a read-time staleness rule).
- **View** = cards/tabs/Recent/Memorex read the model; the focused Memorex viewer still kicks in on focus.

The larger "move Memorex's model+controller out of the overlay into a service" refactor (PianoMan's Route A mental model) remains an attractive *separate* future decision — justified by instant-focus rendering — but the activity indicator is **not** gated on it.

## Propagation chain (verified in code, fully event-driven, no poll)

```
hook fires (UserPromptSubmit / PreToolUse / PostToolUse / Stop / Notification / SessionStart)
  └─ update_state(state_file, {"session.activity_state": <state>})        # model write
  └─ session_store.py edit <tid> --set activity_state=<state>             # store + signal
       └─ SessionStore._signal_change() touches ai_general/data/sessions.changed
            └─ app  fs.watch(sessions.changed)  (debounced 300ms)         # app/main/index.ts:2080
                 └─ emitStoreChanged('external', ['sessions'])
                      └─ session-store re-reads the state file
                           └─ activity_state read at session-store.ts:207 (currently hardcoded 'unknown')
                                └─ View renders Session-Breathing
```

Reference template for the writer: `ai_general/data/hooks/Stop/04_store_session_data_async.py` already does exactly this for `session.last_activity` (write state file + `session_store.py edit --set last_activity=...`).

## Transition map — every activity_state transition → its hook

Hook event dirs that exist in this system: `UserPromptSubmit, PreToolUse, PostToolUse, Stop, Notification, PreCompact, PostCompact, SessionStart`. (No `SubagentStart/Stop`, `StopFailure`, `PostToolUseFailure`, or `SessionEnd` are wired here.)

| # | Transition | Trigger | Hook | Exists? |
|---|---|---|---|---|
| 1 | `*` → `idle` | session starts / resumes | **SessionStart** | ✅ (initialize) |
| 2 | `*` → `responding` | user submits a prompt | **UserPromptSubmit** | ✅ authoritative onset |
| 3 | `responding` → `working` | a tool call begins | **PreToolUse** | ✅ (optional granularity) |
| 4 | `working` → `responding` | a tool call returns | **PostToolUse** | ✅ |
| 5 | `responding`/`working` → `needs-input` | agent asks for input or permission | **Notification** | ✅ |
| 6 | `needs-input` → `responding` | user answers / grants | **UserPromptSubmit** | ✅ |
| 7 | `responding`/`working` → `idle` | turn finishes **normally** | **Stop** | ✅ (already writes last_activity here) |
| 8 | `responding`/`working` → `idle` | **user interrupts (Esc / Ctrl-C)** | — | ❌ no hook — covered by the **aged-timestamp derivation** (below), NOT by an app write |
| — | `*` → `prompt_occupied` | user types unsent text in the CLI prompt | — | ❌ no hook; **already solved** by `prompt-area-state.ts` targeted scans. Orthogonal signal, not part of activity_state. |
| — | `*` → `ended` | `/clear` / exit | SessionEnd | ❌ not wired; SessionStart on next run re-initializes — acceptable |

**The only hole in activity_state proper is row 8: return-to-idle after a user interrupt.** `Stop` is documented to NOT fire on user interrupt (Claude Code hooks reference: *"Does not run if the stoppage occurred due to a user interrupt"*), and no other hook fires on Esc-abort.

## REVISION (2026-06-21): get-status as the ground-truth writer

Investigation found the spine mostly already exists — superseding the "hooks-only + read-time decay timer" plan below. Three layers:

1. **Fast event-driven (exists):** `UserPromptSubmit/00_mark_busy_async.py` writes `{session_dir}/activity_state.json = busy`; `Stop/00_mark_idle_async.py` writes `idle`. The responding axis, instant.
2. **Ground-truth reconciler (exists):** `session_ops.get_ai_status` (`get-status`) reads the **terminal** → full state (`idle / prompt_occupied / responding / blocked / permission_prompt / exited`), then overlays `activity_state.json` on the responding axis (`_read_activity_state`, session_ops.py:562-639). Because it reads the terminal, it reflects ground truth **even after a user interrupt** (no Stop hook needed — the verb-line is gone and the prompt has returned). Callers today: `observer_checkin`, `agent_ops_cli`, `auto_brief`, `get_prompt_area_texts`, `desktop_monitor`, sessions MCP, UCI. The UAI app does **not** call it for session state (only `scheduledTasks:getStatus`, unrelated).
3. **Missing links:** `get_ai_status` never *persists* its determination; the app hardcodes `activity_state:'unknown'` (session-store.ts:207).

**The design:** make `get-status` a **writer** — persist its computed state to the session store's `activity_state` field + signal, **guarded to write only on change** (it is called frequently; unconditional writes would storm `sessions.changed`). Then:

- The store is populated by **two scaffolding writers**: the busy/idle hooks (fast lifecycle transitions) and `get-status` (on-demand reconciled ground truth — catches prompt_occupied, blocked, permission_prompt, and **interrupt-idle**).
- Every existing get-status caller refreshes the store as a **side effect of calls that already happen** — no new polling loop. (Any already-periodic caller rides its existing cadence; we add none.)
- **The interrupt case dissolves** — ground-truth terminal read; no decay timer, no JSONL watcher, no app-as-writer.
- The app becomes a pure reader: one-line change at session-store.ts:207 → `state['session.activity_state']`.

This is the chosen architecture. The "interrupt / decay" discussion below is retained for context but is **superseded** — the decay timer and JSONL-watcher are no longer needed (get-status ground-truth covers interrupt; measured JSONL turn-start silent gap of 77.8s made quiescence-watching unreliable anyway).

### Implementation (revised)
1. `get_ai_status` (or a thin wrapper / `get-status --persist`): after computing `result["state"]`, if it differs from the stored `activity_state`, write `activity_state` + `activity_state_at` to the session store via `session_store.py edit` (touches `sessions.changed`). Change-guarded.
2. App read: `session-store.ts:207` → `activity_state: (state['session.activity_state'] as string) || 'unknown'`.
3. Rename `.session-pulse` → `.session-breathing`.
4. (Optional, later) the busy/idle hooks could also persist directly to the store for the fastest responding-onset, but get-status persistence + the existing `activity_state.json` overlay may already suffice.

---

## (Superseded) The interrupt: covered by derivation, NOT by an app write

**Architectural constraint (PianoMan):** the store is the source; consumers are downstream readers; the store must be fed by **scaffolding** only. The app must never become a *required writer* of authoritative state — otherwise the store is wrong whenever UAI isn't running, and a pure view has become a source.

So the interrupt is resolved by separating the **stored fact** from the **effective state**:

1. **Hooks write only raw facts** — `activity_state` + `activity_state_at` (timestamp), on transitions 1–7. No hook fires on interrupt (row 8), so after an Esc the store simply *keeps* the last-written `responding` and its timestamp.
2. **Effective state is a pure function of (state, age), applied at read by every consumer** — `if state in {responding, working} and (now − activity_state_at) > TTL → idle`. **No writer, no timer, no poll.** The interrupt converges to idle everywhere purely from the aged timestamp. The decay rule is shared read logic, defined once (documented here; applied by both the Python store-readers and the app's derived-status layer — the stored facts are identical, only the derivation is duplicated, trivially).
3. **The app's Esc keystroke is a pure LOCAL VIEW optimization, never a store write.** For the *focused* session, `TerminalPane.onData` sees the interrupt sequence (`\x1b` / `\x03`) and the app may render that session idle instantly — the same legitimate pattern already used to show a focused session's unread count as 0 locally without touching the backend. The app remains a pure consumer; correctness never depends on it.

**Net:** scaffolding → store (raw facts) → consumers (apply shared decay; app may locally short-circuit the focused view). The store is authoritative with zero dependence on UAI running. Cost: a non-focused consumer reflects interrupt-idle after the TTL, not instantly — acceptable for this indicator; the user who hit Esc (focused) sees it immediately. Row 8 is therefore **not a hole requiring an app plug** — it is covered by the aged-timestamp derivation every consumer needs anyway.

## Implementation plan (for review — not yet built)

Enforcement-in-infrastructure, isolated from existing handlers:

1. **`ai_general/data/hooks/common/lib_activity_state.py`** — shared writer: `mark(event_name, context)` maps event → state and does the write-state-file + `session_store.py edit --set activity_state=...,activity_state_at=...`.
2. **One tiny handler per relevant event dir** (`UserPromptSubmit`, `PreToolUse`, `PostToolUse`, `Stop`, `Notification`, `SessionStart`) — a ~3-line file calling `lib_activity_state.mark(...)`. Does not touch existing handlers. (Stop already writes telemetry; the new handler just adds the state, or we fold it into 04.)
3. **App read + decay** — `app/main/session-store.ts:207`: `activity_state: (state['session.activity_state'] as string) || 'unknown'` (+ read `activity_state_at`), and apply the shared aged-timestamp decay in the derived-status layer. (This is a READ/derivation — the app never writes activity_state back to the store.)
4. **Interrupt keystroke (optional, local view only)** — `TerminalPane.onData`: detect `\x1b`/`\x03` → render the *focused* session idle immediately in renderer-local state. **Must not write to the store.** Purely a snappiness optimization over the decay; can be deferred to a later pass.
5. **Rename** `.session-pulse` → `.session-breathing` (class + keyframes + `stores/session-state.ts` `pulse` field naming).

## Open questions

- "working" granularity (rows 3–4): worth the PreToolUse/PostToolUse churn, or collapse `working` into `responding` for v1? (Lean: collapse for v1, add later.)
- Staleness TTL value — pick a generous bound that won't flip a slow-but-live turn to idle.
- Visual distinction: does `needs-input` get its own color (vs just breathing)? (Likely yes — it's the "needs you" state.)
