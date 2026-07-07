# Quality Gate Checklist — Phase 1D

**Last verified:** (updated by CI/manual run)
**Status:** All gates defined, tests written

---

## Contract Tests (`npm run validate`)

| # | Gate | Test File | Falsifiable Claim |
|---|------|-----------|-------------------|
| 1 | Component descriptions schema | `contract-component-descriptions.test.ts` | Every registered component's `describe()` output has: schema_version (number ≥ 1), id (matches registered key), path (contains 'app'), name (non-empty string), description (non-empty string), parent (null or string), children (array), state (record with valid StateDescriptors), commands (record with valid CommandDescriptors), actions (record), events (record), context (array of {key, type, required}) |
| 2 | At least 5 components registered | `contract-component-descriptions.test.ts` | `ComponentRegistry.list().length >= 5` |
| 3 | Expected components present | `contract-component-descriptions.test.ts` | session_navigator, workspace, session_pane, context_panel, bottom_panel all return `has(id) === true` |
| 4 | Command bus registers/executes | `contract-command-bus.test.ts` | Registered handler receives command and returns CommandResult |
| 5 | Command bus before hooks abort | `contract-command-bus.test.ts` | Before hook returning `ok: false` prevents handler execution |
| 6 | Command bus after hooks fire | `contract-command-bus.test.ts` | After hook callback is invoked after handler completes |
| 7 | Command bus logs execution | `contract-command-bus.test.ts` | `getLog()` contains entry with type, ok, duration_ms |
| 8 | Command bus glob matching | `contract-command-bus.test.ts` | `session.*` hook matches `session.update`, not `folder.create` |
| 9 | Command bus error handling | `contract-command-bus.test.ts` | Throwing handler returns `ok: false` with HANDLER_ERROR code |
| 10 | Activity log writes valid JSONL | `contract-activity-log.test.ts` | Every line in activity_log.jsonl parses as valid JSON |
| 11 | Activity log entry schema | `contract-activity-log.test.ts` | All entries have: ts (ISO 8601), session (string), participant (string), event (domain.action format), payload (object) |
| 12 | Activity log read/filter | `contract-activity-log.test.ts` | `readActivityLog({eventFilter: 'command'})` returns only command.* events |
| 13 | Activity log tail | `contract-activity-log.test.ts` | `tailActivityLog(ts)` returns only entries after timestamp |
| 14 | System metrics valid | `contract-activity-log.test.ts` | `getSystemMetrics(N)` returns cpu_percent (0-100), memory_used_mb (>0), active_sessions (=N), uptime_seconds (≥0) |

## Packaged Build Smoke Test (`scripts/smoke-test.sh`)

| # | Gate | Falsifiable Claim |
|---|------|-------------------|
| S1 | Package builds | `electron-forge package` exits 0 |
| S2 | App binary exists | `.app` bundle exists in out/ directory |
| S3 | App launches | Process starts and stays running for 5 seconds |
| S4 | Main process runs | No crash in first 5 seconds (check exit code) |

## Structural Gates (manual verification)

| # | Gate | Falsifiable Claim |
|---|------|-------------------|
| M1 | BottomPanel imported in App.tsx | `grep -q 'BottomPanel' src/renderer/App.tsx` — not a placeholder div |
| M2 | Activity log hook registered | `grep -q 'commandBus.after' src/main/index.ts` — logging hook present |
| M3 | IPC handlers registered | `grep -q 'activityLog:read' src/main/index.ts` — log IPC exists |
| M4 | No raw color values in BottomPanel CSS | All colors use `var(--...)` tokens |
| M5 | BottomPanel registered in ComponentRegistry | `bottom_panel` key exists in component-descriptions.ts |
| M6 | Tab list is data-driven | BottomPanel uses `tabs.map()` not hardcoded JSX per tab |

---

## How to Run

```bash
cd src/
npm run validate          # Contract tests (gates 1-14)
bash ../scripts/smoke-test.sh  # Packaged build (gates S1-S4)
```
