---
name: feedback_cli_statusline_git_branch
description: Codex CLI supports git-branch as a native statusline field; verify CLI
  config capabilities before asserting limits
status: active
---

Codex CLI `tui.status_line` supports a `git-branch` built-in identifier natively. Don't claim a CLI only supports a fixed set without custom-command support — check the actual available identifiers before saying something isn't possible.

(Gemini CLI, retired 2026-07-11 as a current tool, had the same via `ui.footer.items` — noted only as history; Gemini is no longer a launchable platform. See [[project_gemini_retired]].)

**Why:** I incorrectly told the user these platforms couldn't show git branch in their status bars, when they simply have a field for it.

**How to apply:** When asked about CLI platform config capabilities, verify available options rather than assuming a limited set. If unsure, say so instead of asserting it can't be done.
