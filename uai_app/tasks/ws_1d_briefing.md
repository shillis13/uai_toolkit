# Workstream 1D Briefing: Observability + Quality Gates

**Project:** UAI (Unified AI Interface) — architectural successor to UCI
**DevTree:** uai-resurrection
**AI_ROOT:** $HOME/Documents/AI/devTrees/AI_ROOT_uai-resurrection
**Project Dir:** ai_general/projects/unified_ai_interface

## Your Mission

Build the observability layer: bottom panel with related entities, logs, system
monitor, and command logging. Also build the quality gate infrastructure (contract
tests, packaged build smoke test).

You build ON TOP of 1A (command bus, stores) and alongside 1B (core UI) and 1C
(organization) deliverables already in src/.

## Read Before Starting (in order)

1. **UAI Next Architecture:** `$HOME/Documents/AI/ai_root/ai_general/docs/ideas/uai/uai_next_architecture_v0.1.md` — Sections 2 (Activity Log) and 7 (Inbox). Your log and monitoring work MUST align with the activity log schema and event namespace from this doc. Do NOT build a throwaway log viewer — build against the formal spec.
2. **Architecture spec:** `architecture/uai_architecture_v1.1.md` — Sections 16 (Observability), 18 (Quality Gates)
3. **1A/1B/1C code:** `src/` — 38 files already in place. Understand the command bus, stores, and component structure before adding to them.
4. **Lessons learned:** `docs/lessons-learned.md` — the "placeholder div catastrophe" and quality gate failures. Your quality gates must prevent these.
5. **Delegation plan:** `tasks/phase_1_delegation.md` — Section "Workstream 1D"

## Critical: Activity Log Alignment

The UAI Next Architecture (Section 2) defines a formal activity log:

- **Format:** JSONL with standard fields: `ts`, `session`, `participant`, `event`, `conversation`, `payload`, `correlation_id`
- **Event namespace:** `domain.action` format (e.g., `task.claimed`, `message.sent`, `session.started`, `bash.command`)
- **Correlation ID:** groups related events across participants for a single logical operation
- **Retention tiers:** raw (1 week) → daily summaries (1 month) → weekly (1 year) → monthly (never)

Your command logging (1D.2) should write activity log entries in this format. The command bus already has before/after hooks — your hook writes formal activity log entries, not ad-hoc console logs.

## Critical: Inbox Awareness

The UAI Next Architecture (Section 7) defines a user inbox where all user-targeted communications converge. Your bottom panel should be designed with awareness that a future Inbox tab will join the existing tabs. Don't hardcode the tab list — make it extensible.

## Key Rules

1. **Use command bus hooks for logging** — don't add logging inside individual command handlers
2. **Activity log format per UAI Next Architecture Section 2** — structured JSONL, not free-form text
3. **Extensible bottom panel tabs** — don't hardcode. Future tabs: Inbox, more collectors
4. **Quality gates must be structural** — "structure outlasts instructions." Encode gates as scripts, not docs.
5. **Design tokens only** — CSS custom properties, no raw values
6. **Register with ComponentRegistry** — BottomPanel provides describe()

## What You're Building

### 1D.1 — Bottom Panel (`src/renderer/components/BottomPanel.tsx`)

Collapsible panel at bottom of workspace:

- **Related Entities tab:** Children, linked sessions, briefs, team members for focused session. Uses relationship store from 1C.
- **Session Log tab:** Per-session activity log viewer. Reads activity log entries filtered by session.
- **App Log tab:** Application-wide activity log. All command executions, errors, lifecycle events.
- **System Monitor tab:** CPU, memory, active sessions, error count. Basic metrics from `process.memoryUsage()` and session count.
- **Drawer bar:** When collapsed, show summary: `Sessions: N | Errors: N | CPU: N%`
- **Tab list must be extensible** — future Inbox tab, future collector status tabs

### 1D.2 — Command Logging (Activity Log)

Wire command bus after-hooks to write activity log entries:

- Write to: `{AI_ROOT}/ai_general/data/activity_log.jsonl` (append-only)
- Format per UAI Next Architecture Section 2:
  ```jsonl
  {"ts":"...","session":"...","participant":"uai_app","event":"command.executed","payload":{"type":"session.update","origin":"user","ok":true,"duration_ms":42},"correlation_id":"cmd_xxx"}
  ```
- Include: command type, origin, success/failure, duration, error code if failed
- IPC handler to read/tail the log for the renderer log tabs

### 1D.3 — Quality Gates

Test and acceptance infrastructure:

- **Contract tests:** `npm run validate` runs:
  - Every registered component's `describe()` validates against ComponentDescription schema
  - Command bus has at least the expected command types registered
  - Stores bootstrap and refresh on signal events
  - Activity log writes are parseable JSONL
- **Packaged build smoke test:** Script that builds the packaged app and verifies it launches
- **Gate checklist:** `tests/gate_checklist.md` — falsifiable claims for each gate (from lessons-learned)

## Output

- `src/renderer/components/BottomPanel.tsx` + related sub-components
- `src/main/activity-log.ts` — activity log writer + reader
- Command bus hook registration in `src/main/index.ts`
- `tests/` directory with contract tests
- `scripts/smoke-test.sh` for packaged build verification
- `tests/gate_checklist.md`

## Parallel Work Note

1B and 1C code is already in src/. Don't modify their files unless necessary
for integration. Add your components alongside theirs.

## Escalation

Architecture questions → prompt Continuity II at session 20260422_204104_640a7e0c_cla
Scope/UX questions → escalate to PianoMan

When done, send a prompt to Continuity II confirming completion.
