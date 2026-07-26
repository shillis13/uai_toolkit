---
name: ref_file_history_dir
title: File History Dir
description: Claude Code maintains per-session file snapshots in ~/.claude/file-history/<sessionId>/ for undo — stores full file contents at each version, hash-to-path mapping in session .jsonl
status: active
---

`~/.claude/file-history/<sessionId>/` is Claude Code's native file versioning/undo system. Each file a session modifies gets snapshotted here before changes.

Files are named `<hash>@v<N>` — hash derived from file path, N increments per edit. Contains the full file content (not diffs). The hash→path mapping is in `file-history-snapshot` entries in the session's `.jsonl` transcript.

**Why:** Discovered 2026-06-06. We didn't know this existed and may have lost recoverable file versions from sessions whose `.jsonl` transcripts were deleted — the file-history snapshots might still be on disk even when the transcript is gone, but without the transcript the hash→path mapping is lost.

**How to apply:**
- When a session's `.jsonl` is deleted/missing, check `~/.claude/file-history/<sessionId>/` — file snapshots may survive independently
- The hash→path mapping is only in the `.jsonl`, so without it you'd need to identify files by content inspection
- Consider this as a recovery avenue before declaring data lost
- Pair with `history.jsonl` (native prompt log) for a more complete picture of what happened in deleted sessions
