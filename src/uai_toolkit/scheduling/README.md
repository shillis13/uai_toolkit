# scheduling

Scripts and shell utilities for managing scheduled cron jobs defined as YAML task files. Job definitions live in `$AI_ROOT/ai_general/data/scheduled_tasks/` and are installed into the system crontab as a managed block.

## Scripts

### scheduled_task_mgr.py
The main tool for managing scheduled tasks. Supports both an interactive REPL (no-args mode with readline history) and direct CLI subcommands. Reads YAML task definition files, generates a managed crontab block delimited by `# >>> AI_SCHEDULED_TASKS MANAGED BLOCK >>>` markers, and installs it via `crontab`. Provides CRUD operations, status diffing (current vs. expected), log viewing, and human-readable cron expression translation.

Also symlinked as `install_scheduled_tasks.py` for legacy compatibility — when invoked under that name it behaves as the original installer script.

**Usage:**
```
scheduled_task_mgr.py              # REPL mode
scheduled_task_mgr.py list         # List task groups
scheduled_task_mgr.py view GROUP   # View jobs in a group
scheduled_task_mgr.py status       # Show crontab vs expected state
scheduled_task_mgr.py install      # Install to crontab
scheduled_task_mgr.py install --dry-run   # Preview without installing

# Per-job control + reschedule:
scheduled_task_mgr.py disable GROUP JOB             # disable a single job (removes just its agent)
scheduled_task_mgr.py enable  GROUP JOB             # re-enable a single job
scheduled_task_mgr.py reschedule GROUP JOB "53 8 * * *"        # change a job's schedule (cron)
scheduled_task_mgr.py reschedule GROUP JOB "2026-06-25 08:53"  # ...or a one-time absolute date
scheduled_task_mgr.py add GROUP --id job1 --schedule "2026-06-25 08:53" --command "..." --once  # run-once job

# One-shots (LaunchAgents that fire once, then DISABLE themselves by default):
scheduled_task_mgr.py once --command "<cmd>" --now            # fire immediately
scheduled_task_mgr.py once --command "<cmd>" --at 04:30       # fire at next 04:30
scheduled_task_mgr.py once --command "<cmd>" --in 90m         # fire 90 min from now
scheduled_task_mgr.py once --command "<cmd>" --now --remove   # delete plist on fire (vs disable)
scheduled_task_mgr.py once --list                            # list one-shots (pending + fired)
scheduled_task_mgr.py once --cancel <id>                     # remove a one-shot (pending or fired)
scheduled_task_mgr.py once --clear                           # remove all fired (disabled) one-shots

# Legacy (install_scheduled_tasks.py symlink):
install_scheduled_tasks.py --dry-run
install_scheduled_tasks.py --status
install_scheduled_tasks.py --bootstrap   # Install + add @reboot self-entry
```

### install_scheduled_tasks.py
Symlink to `scheduled_task_mgr.py`. See above.

### crontab_delete.sh
Shell helper to remove a specific entry from the crontab by pattern. Used for manual cleanup.

### crontab_toggle.sh
Shell helper to enable or disable a crontab entry by commenting/uncommenting it.

### launchd_delete.sh
Shell helper to unload and remove a launchd plist. Kept for environments where some jobs use launchd instead of cron.

### manageCronJobs.sh
Earlier shell-based cron management script, predating `scheduled_task_mgr.py`. Retained for reference.

## Dependencies

- `pyyaml` (pip) — preferred YAML parser; falls back to a built-in minimal parser if unavailable
- `~/bin/ai/utils/standard_colors` for REPL color output
- `readline` (stdlib) for REPL history

## Notes

**Per-job enable/disable, reschedule, and one-time dates.** `enable`/`disable` take an optional `job_id` to toggle a single job's `enabled` field (without it, they toggle the whole group). The install sync then adds or removes just that one job's LaunchAgent — disabling a job boots out and removes its agent, leaving the YAML intact for re-enabling. `reschedule GROUP JOB <schedule>` changes one job's schedule and reinstalls (equivalent to `edit GROUP JOB --schedule ...`). The schedule may be a 5-field cron expression, `@reboot`, or a **one-time absolute date** `YYYY-MM-DD HH:MM`, which maps to a launchd `{Month, Day, Hour, Minute}` calendar slot. (launchd has no year field, so that slot technically recurs annually — pair a one-time date with a *run-once* job so it fires only once.)

**Run-once jobs (`once: true`).** Mark a managed job `once: true` (CLI: `add … --once`, or `edit GROUP JOB --once true`) and the tool makes it fire exactly once, then retire itself — no hand-written command tail required. Under the hood `generate_task_file` appends a self-retire step to the agent's wrapped command: after the job runs (and records its last-run state) it calls an internal `_self_retire GROUP JOB` to flip the job's `enabled: false` in YAML (without a full reinstall — that would churn every agent and race the teardown), then deletes its own plist and boots itself out. So the job lands in a `disabled` state, visible to `status`/`status --json` and to the install sync, until something re-enables it. `once` and `background` are mutually exclusive (a run-once job can't be a persistent `@reboot` agent).

**Trigger-driven cycle.** Per-job `enabled` is exposed in `status --json` (each job carries an `enabled` boolean and a `state` of `scheduled`/`once`/`disabled`/`persistent`), so an external trigger script can branch on it: when its event fires, check whether either job is disabled and, if so, `reschedule` both to new dates and `enable` both. Re-enabling a `once` job regenerates its agent (with the self-retire tail) so it fires once again at the new date. (For a standalone fire-once agent that isn't part of a managed group, use the `once` *command* instead — see below.)

**One-shots** (`once` command) are deliberately kept OUTSIDE the managed set, in the `com.shawnhillis.oneshot.*` label namespace (managed jobs use `com.shawnhillis.ai.*`). A one-shot fires exactly once, then retires itself. **By default it DISABLES itself** (`launchctl disable` writes a persistent override so launchd refuses to run it again, even when it auto-reloads on the next login) and the plist stays on disk as an auditable, re-enableable record. Pass `--remove` to delete the plist instead. Either way it boots itself out of the live gui domain so no further triggers fire that session. Keeping one-shots out of the managed set means `status`/`install` never treat their retirement as drift.

Implementation notes that matter:
- **Self-retire ordering**: the retire step (disable, or `rm` under `--remove`) runs *before* `launchctl bootout`, because bootout terminates the running job and anything after it may never execute. `launchctl disable` does not kill the process and its override survives bootout, so disable-then-bootout is safe.
- **The disable override is keyed by label and is sticky** — it survives `bootout` and outlives the plist. So removal (`--cancel`/`--clear`) must `launchctl enable` to clear it, and installation `launchctl enable`s the label *before* bootstrapping (this is what lets a fired id be re-armed — reusing a fired id clears its override automatically). Removal order is bootout → enable → rm, so a job that disables itself mid-cancel can't re-set the override after it's cleared.
- `once --list` tags each one-shot **pending** or **fired (disabled)** by parsing `launchctl print-disabled`. `once --clear` sweeps only the fired ones.

The managed crontab block is delimited by begin/end markers so the installer can replace it atomically without touching other crontab entries. Task YAML files follow the schema in `ai_general/ai_context_files/knowledge/schemas/schema_scheduled_task.latest.yml`. The `scheduled_tasks` symlink in this directory points to `$AI_ROOT/ai_general/data/scheduled_tasks` for quick access to the task definitions.
