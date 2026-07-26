---
name: Identity verification before claims
description: Always check AI_TRACKING_ID, AI_CLI_SESSION_ID, and ZELLIJ_SESSION_NAME
  env vars before claiming or denying session identity
status: active
---

Never assume session identity — verify it first by checking env vars.

**Key env vars (set by ai_launcher.py wrapper):**
- `AI_TRACKING_ID` — session tracking ID (e.g., `claude_cli_8866`, `20260419_194737_a9a8dd81_cla`)
- `AI_CLI_SESSION_ID` — CLI UUID (also visible in tool result paths: `.claude/projects/.../{uuid}/tool-results/`)
- `AI_SESSION_DIR` — per-session data directory
- `AI_SESSION_PLATFORM` — platform name (e.g., `claude_cli`)
- `ZELLIJ_SESSION_NAME` — zellij terminal session name (if running in zellij)
- Terminal session name: `tmux display-message -p '#{session_name}'` (if running in tmux)

**Why:** When told "only claude_cli_95993 should see this," I assumed I was NOT that session and said so. Checking env vars proved I WAS that session. In a later session, I checked wrong variable names (`CLAUDE_SESSION_ID`) and concluded I had no identity, then walked the process tree unnecessarily.

**How to apply:** When identity is needed, run `echo $AI_TRACKING_ID $AI_CLI_SESSION_ID` first. This takes 1 second. Also: the CLI UUID appears in every tool result path — look there before hunting through process trees.
