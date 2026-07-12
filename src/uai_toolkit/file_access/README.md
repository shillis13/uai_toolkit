# file_access

Anti-clobbering infrastructure that tracks which sessions have read and written files. Claude Code hooks call these scripts automatically on every Read, Edit, and Write tool use to prevent two sessions from unknowingly overwriting each other's work.

## Scripts

### file_access_tracker.py
Core library. Maintains two JSONL files in `$AI_ROOT/ai_general/data/file_access/`:
- `access_state.jsonl` — rolling operational state (who last read/wrote each file, pruned to 48 hours)
- `access_log.jsonl` — durable audit trail of conflicts and denials, never pruned

Provides `log_read`, `log_write`, `log_deny`, `check_conflict`, and `prune`. `check_conflict` returns a `ConflictInfo` if another session wrote a file after the current session last read it. Paths are canonicalized so symlinks and hardlinks compare as the same file. Imported by the three hook scripts below.

### hook_track_read.py
PostToolUse hook for the `Read` tool. Reads `session_id` and `file_path` from stdin (Claude Code hook JSON), calls `log_read`, and exits. Run automatically by Claude Code after every successful file read.

**Usage:** Configured in `.claude/settings.json` as a hook, not called directly.

### hook_track_write.py
PostToolUse hook for `Edit` and `Write` tools. Records the write via `log_write` and triggers `prune()` with ~1% probability to keep the state file from growing unbounded.

**Usage:** Configured in `.claude/settings.json` as a hook, not called directly.

### hook_check_before_write.py
PreToolUse hook for `Edit` and `Write` tools. Calls `check_conflict` before allowing the write. If a conflict is detected, returns a `permissionDecision: deny` JSON response with instructions to re-read the file first. The blocking message names the conflicting session.

**Usage:** Configured in `.claude/settings.json` as a hook, not called directly.

## Dependencies

- `~/bin/ai/cli/lib_paths.py` for `AI_ROOT` resolution
- Standard library only (`json`, `os`, `time`, `pathlib`)

## Notes

The `config.json` in the data directory controls `log_all_checks` (default: true = verbose). When false, only denials and conflicts are logged, reducing I/O. The state file is pruned to at most 5,000 entries and 48 hours of history; the audit log is permanent. To temporarily disable conflict detection, clear `access_state.jsonl` — sessions will need to re-read files before the system can detect conflicts again.
