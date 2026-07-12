# coordination

Scripts for observing and coordinating active AI sessions. Used by Hamilton (the orchestrator role) to get a snapshot of what all running sessions are doing.

## Scripts

### observer_checkin.py
Scans all active tmux sessions via `session_ops.py`, queries each session's status and terminal output, and writes a YAML report summarizing who is active, idle, blocked, or stopped. The report is written to `ai_comms/hamilton/observer_reports/report_YYYYMMDD_HHMMSS.yml`. Run manually or on a schedule when Hamilton needs a system-wide status check.

**Usage:**
```
observer_checkin.py                        # Full scan, write report to file
observer_checkin.py --quick                # Skip terminal reads (faster, no activity notes)
observer_checkin.py --stdout               # Print YAML to stdout instead of file
observer_checkin.py --idle-threshold 60    # Custom idle threshold in minutes (default: 120)
```

The report includes per-session fields: tracking ID, display name, status, context usage %, platform, model, and an activity note derived from the last visible terminal line. The `needs_attention` list flags sessions that are blocked on user input or idle.

## Dependencies

- `session_ops.py` at `$AI_ROOT/ai_general/scripts/session_mgmt/session_ops.py`
- `session_store.py` at `$AI_ROOT/ai_general/scripts/session_mgmt/session_store.py`
- `~/bin/ai/utils/standard_colors` for terminal color output
- `pyyaml` (pip) for YAML output

## Notes

Idle detection uses session creation time as a proxy for last-activity time, which is approximate. All idle sessions are currently flagged in `needs_attention`; Hamilton determines actual relevance. The `--quick` flag skips `read-terminal` calls and is useful when many sessions are running.
