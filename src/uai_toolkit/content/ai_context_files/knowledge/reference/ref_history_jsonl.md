---
name: ref_history_jsonl
title: History Jsonl
description: ~/.claude/history.jsonl is a native Claude Code file that logs every prompt sent to any session — we built a redundant UserPromptSubmitted hook doing the same thing
status: active
---

`~/.claude/history.jsonl` is maintained natively by Claude Code. It logs every prompt/message sent to any session with fields: `display`, `timestamp`, `sessionId`, `project`, `pastedContents`. Input-side only — no AI responses.

**Why:** Discovered 2026-06-06 during a search for old session data. We had separately implemented a UserPromptSubmitted hook handler to capture the same information, not knowing Claude Code already does this natively. The native file goes back to Nov 1, 2025.

**How to apply:** Before building custom logging/tracking for Claude Code behaviors, check whether the CLI already maintains the data natively. Also: `history.jsonl` is a useful cross-session search tool — it can identify which sessions received specific prompts even when the session's own `.jsonl` transcript is gone.
