# Scheduled Tasks Manager — UI Design Document

**Date:** 2026-06-03
**Status:** Design — ready for implementation review

---

## 1. Backend Capabilities Summary

Source: `$AI_ROOT/ai_general/scripts/scheduling/scheduled_task_mgr.py`

### Data Model

YAML files in `$AI_ROOT/ai_general/data/scheduled_tasks/*.yml`. Each file is a **task group**:

```yaml
name: string          # must match filename stem
description: string   # optional
enabled: bool         # controls whether group is included in crontab
env: {}               # key-value env var pairs
jobs:
  - id: string        # unique within group
    description: str
    schedule: string   # 5-field cron OR @reboot
    command: string
    log: string        # optional path for >> redirection
    background: bool   # appends & to entry
```

The crontab contains a `# >>> AI_SCHEDULED_TASKS MANAGED BLOCK >>>` section rebuilt from all enabled YAML files.

### CLI Operations

| Operation | CLI form | Description |
|---|---|---|
| list groups | `list [--all]` | All groups with enabled status and job count |
| view group | `view <group>` | Group metadata + job details |
| status | `status` | Diff current crontab vs expected; detect drift |
| create group | `create <group>` | New YAML file with first job |
| add job | `add <group>` | Append job to existing group |
| edit group | `edit <group> [--field val]` | Update group-level fields |
| edit job | `edit <group> <job_id> [--field val]` | Update job-level fields |
| delete group | `delete <group> [--yes]` | Remove YAML file |
| delete job | `delete <group> <job_id> [--yes]` | Remove single job |
| enable | `enable <group>` | Set `enabled: true`, auto-install |
| disable | `disable <group>` | Set `enabled: false`, auto-install |
| install | `install [--dry-run] [--bootstrap]` | Rebuild managed crontab block |
| run now | `run <group> <job_id>` | Execute job immediately, tee to log |
| view logs | `logs <group> <job_id> [--lines N]` | Tail job log file |
| live crontab | `crontab` | Pretty-print live crontab |

Key behaviors:
- Every mutation auto-calls `auto_install()` — crontab always rebuilt immediately
- YAML files are the source of truth; no database
- `schedule_to_english()` converts cron → human-readable
- Bootstrap entry: `@reboot` job that reinstalls crontab after reboot

---

## 2. Use Cases

1. **UC-01 — Browse groups**: See all task groups, enabled/disabled state, job counts
2. **UC-02 — View group details**: Inspect jobs — schedules, commands, logs, human-readable descriptions
3. **UC-03 — Enable a group**: Activate disabled group
4. **UC-04 — Disable a group**: Temporarily stop group without deleting
5. **UC-05 — Create new group**: Schedule new recurring task from scratch
6. **UC-06 — Add job to group**: Add another job to existing group
7. **UC-07 — Edit a job**: Change schedule, command, description, or log path
8. **UC-08 — Delete a job**: Remove specific job from group
9. **UC-09 — Delete a group**: Remove entire task group
10. **UC-10 — Run job now**: Immediately execute for testing
11. **UC-11 — View job logs**: See recent output from job's log file
12. **UC-12 — Check crontab sync**: Verify live crontab matches YAML definitions
13. **UC-13 — Reinstall crontab**: Force-rebuild managed block
14. **UC-14 — Preview dry-run**: See what crontab would look like without committing
15. **UC-15 — Bootstrap @reboot**: Ensure crontab survives system reboots
16. **UC-16 — View raw crontab**: See full live crontab with highlighting

---

## 3. Workflow Descriptions

### UC-01: Browse Groups
1. Click "Sched Tasks" in Navigator Tools.
2. Groups tab (default) loads via IPC.
3. Each row: enabled indicator, group name, job count, description.
4. Filter pills: All / Enabled / Disabled.

### UC-02: View Group Details
1. Select group row in list.
2. Right pane shows: name, description, enabled state, env vars.
3. Job table: ID, schedule (human-readable), description, command preview, log path.
4. Expand job row for full command and log.

### UC-03/04: Enable/Disable
1. Click toggle control on group row.
2. IPC call fires. On success, list refreshes.
3. Toast: "Group 'ai_memory' enabled. Crontab updated."

### UC-05: Create New Group
1. Click "+ New Group" button.
2. Form replaces right pane: Group Name, Description, First Job (ID, Schedule, Command, Description, Log).
3. Schedule field has live cron helper preview.
4. "Create" → IPC → form closes, list refreshes.

### UC-06: Add Job
1. Select group, click "+ Add Job" in job list header.
2. Inline form at bottom: Job ID, Schedule (cron helper), Command, Description, Log.
3. "Add" → IPC → form collapses, job list refreshes.

### UC-07: Edit Job
1. Click edit icon on job row (or double-click).
2. Row expands to inline edit mode — each field becomes input.
3. Save/Cancel. Schedule field shows cron helper inline.

### UC-10: Run Job Now
1. Click "Run Now" on job row.
2. Button shows spinner.
3. IPC call with ~60s timeout. On completion, output panel shows captured stdout.
4. Exit code: green "Exit 0" or red "Exit 1".

### UC-11: View Logs
1. Click log icon on job row with configured log path.
2. Log viewer shows last 50 lines. "Refresh" re-fetches.
3. "Back" returns to group detail.

### UC-12: Check Status
1. Click "Status" tab.
2. Shows "In sync" or "Drift detected" banner.
3. If drift: table of missing/extra crontab lines.
4. "Install" button resolves drift.

---

## 4. UI Component Design

### Overall Structure

```
┌─────────────────────────────────────────────────┐
│ Scheduled Tasks                 [Status] [Refresh]│
├─────────────────────────────────────────────────┤
│ [Groups] [Status] [Crontab]                      │
├────────────────┬────────────────────────────────┤
│ Group list     │ Detail / Form / Logs pane       │
│                │                                 │
└────────────────┴────────────────────────────────┘
```

### Groups Tab — Left Pane
- Header: "Groups" label, count, "+ New Group" button
- Filter pills: All / Enabled / Disabled
- Row: enabled dot (green/muted), name, job count badge, description (truncated)
- Selected: `var(--bg-active)` background, left border `var(--accent-blue)`

### Groups Tab — Right Pane (Detail)
- Group metadata: name, description, enabled toggle, env vars (collapsible)
- Job table: ID (cyan monospace), schedule (green human-readable, cron on tooltip), description, action icons on hover (Run ▶, Logs ≡, Edit ✎, Delete 🗑)
- Expanded job: full command, log path, background flag

### Status Tab
- Sync status banner
- Group list with enabled/disabled/job counts
- Bootstrap status
- Drift details (missing/extra lines)
- Install / Dry Run / Bootstrap buttons

### Crontab Tab
- Full raw crontab in scrollable `<pre>` block
- Line coloring: block markers (blue), group headers (cyan), env (orange), schedules (green), commands (default), @reboot (yellow)
- "Copy" button

### Component States
| State | Treatment |
|---|---|
| Loading | Spinner text |
| Error | Red banner |
| Empty | Muted centered text |
| Mutating | Buttons disabled, spinner |
| Run in progress | "Running..." in job row |
| Confirm delete | Inline confirm row below target |

---

## 5. Alternate Entry Points

### A. Navigator Tools — rename button
Current: `targetId: 'crontab-manager'`, label `'Crontab Manager'`
Change to: `targetId: 'scheduled-tasks'`, label `'Scheduled Tasks'`, button `'Sched Tasks'`

### B. Bottom Panel Tab (future)
Compact read-only view: group list with enabled indicators and sync status badge.

### C. Status Bar Indicator (future)
Persistent sync status badge. Click opens Scheduled Tasks pane to Status tab.

### D. Command Palette (future)
"Run job now", "Enable group", "Check crontab status" entries.

---

## 6. IPC Channel Design

### Preload API: `window.uai.scheduledTasks`

```typescript
scheduledTasks: {
  listGroups: () => Promise<ScheduledGroup[]>
  viewGroup: (group: string) => Promise<ScheduledGroupDetail | null>
  getStatus: () => Promise<ScheduledTasksStatus>
  getLiveCrontab: () => Promise<string>
  getLogTail: (group: string, jobId: string, lines?: number) => Promise<string>
  enableGroup: (group: string) => Promise<MutationResult>
  disableGroup: (group: string) => Promise<MutationResult>
  createGroup: (opts: CreateGroupOpts) => Promise<MutationResult>
  addJob: (group: string, job: JobDefinition) => Promise<MutationResult>
  editGroup: (group: string, patch: GroupPatch) => Promise<MutationResult>
  editJob: (group: string, jobId: string, patch: JobPatch) => Promise<MutationResult>
  deleteGroup: (group: string) => Promise<MutationResult>
  deleteJob: (group: string, jobId: string) => Promise<MutationResult>
  install: () => Promise<MutationResult>
  dryRun: () => Promise<{ ok: boolean; preview: string; error?: string }>
  bootstrap: () => Promise<MutationResult>
  runJob: (group: string, jobId: string) => Promise<RunJobResult>
}
```

### Read Strategy
- `listGroups` / `viewGroup`: direct YAML reads in Node.js (fast)
- `getStatus`: shell out to Python script
- `getLiveCrontab`: `execFile('crontab', ['-l'])`
- `getLogTail`: direct file read
- All mutations: shell out to Python CLI (reuses validation + auto-install)

### Security
- Group/job names validated: `[a-z0-9_-]` only, max 64 chars
- Log paths sandboxed to `$AI_ROOT`

---

## 7. Files to Create/Modify

### Create
1. `packages/renderer-ui/src/components/ScheduledTasksPane.tsx` — main pane component
2. This design document

### Modify
3. `app/main/index.ts` — add 16 `uai:scheduledTasks:*` IPC handlers
4. `app/main/preload.ts` — add `scheduledTasks` namespace + TypeScript interfaces
5. `packages/renderer-ui/src/components/TabContentPane.tsx` — add `case 'scheduled-tasks'`
6. `packages/renderer-ui/src/components/Navigator.tsx` — rename Crontab Mgr button
7. `app/renderer/styles/styles.css` — add `sched-mgr-*` CSS classes

### Build Sequence
1. IPC layer (preload types + index.ts handlers)
2. Component skeleton + CSS + routing
3. Groups tab read path (list + detail + job table)
4. Mutations (enable/disable, create, edit, delete)
5. Status tab (sync check, install, dry run, bootstrap)
6. Log viewer + Run Now
7. Crontab tab (raw view with colorization)
