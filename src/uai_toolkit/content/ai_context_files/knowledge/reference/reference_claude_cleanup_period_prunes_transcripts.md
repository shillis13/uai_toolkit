---
name: reference_claude_cleanup_period_prunes_transcripts
description: Why session jsonl transcripts vanish (~30-day rolling) and how it was
  fixed + recovery path
status: active
---

Claude Code's native `cleanupPeriodDays` (defaults to **30** when unset) deletes top-level session transcripts in `~/.claude/projects/*/<uuid>.jsonl` whose mtime is older than the threshold, **on startup, rolling**. This silently pruned >300 of 556 tracked sessions (hard floor early June 2026 ≈ today−30; nested `subagents/` + chat-pipeline jsonls are treated differently and survive longer, which masks the cliff in a raw file count — isolate bare-uuid project-root jsonls to see it).

**It was NOT always running** — the 2026-05-26 Time Machine backup still held full history back to 2026-01-10, so enforcement began AFTER 5/26 (prime suspect: a Claude Code update ~late May / the Jun-11 2.1.173 bump flipping retention on). Consequence for recovery: **any TM backup from 5/26 or earlier is a complete pre-purge archive** — restore the whole pre-June history from one snapshot, not per-session. Apply the cleanupPeriodDays fix BEFORE restoring, or next startup re-purges the restored old-mtime files.

**Fix applied 2026-07-01:** set `"cleanupPeriodDays": 3650` in `~/.claude/settings.json` (was unset → default 30). Takes effect next CLI startup. Non-destructive (only prevents deletion).

**"deleted" in `sess_mgr search` is DERIVED, not stored** — `session_store.py::_derive_status()` returns "deleted" when `history_file` doesn't exist on disk. The DB row stays intact (status=running, archived=0). Soft/hard delete in session_store never touches jsonl files on disk; only this cleanup does.

**Recovery = Time Machine.** `~/.claude` is `[Included]`; daily backups cover the window. BUT the CLI/Claude process can't read `/Volumes/.timemachine/...` mounts (Full Disk Access / TCC wall — same as atrun; sandbox-off doesn't help). Restore needs Finder "Enter Time Machine" or `tmutil`/`cp` from a Terminal with FDA granted. See [[reference_atrun_permissions]]. Related recovery fragments: hook `stdin_dumps` under `ai_general/data/hooks/data/stdin_dumps/` carry full prompt text + tool input/output per session (partial, keyed by tracking_id).
