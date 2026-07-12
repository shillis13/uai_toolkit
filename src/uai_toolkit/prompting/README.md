# ~/bin/ai/prompting/ — Cross-Platform Prompt Delivery

Send messages to any AI target (Desktop app, CLI agents, web UIs) with busy detection, fallbacks, and scheduling.

## Which Script Do I Use?

| I want to...                              | Use this                        |
|-------------------------------------------|---------------------------------|
| Send a message to an AI right now         | `send_prompt.sh`                |
| Schedule a message for later              | `set_scheduled_prompt.sh`       |
| Fire a scheduled prompt manually          | `send_scheduled_prompt.sh`      |
| Run the scheduler daemon                  | `scheduled_prompts_daemon.sh`   |
| Check if a CLI agent is busy              | `ai_isBusy.sh`                 |
| Check if Desktop Claude is busy           | `check_desktop_busy.sh`        |

## Scripts

### send_prompt.sh — The Main Entry Point

Sends a message to any supported AI target. This is the script you want 90% of the time.

```bash
send_prompt.sh --target claude-cli --message "check inbox" --submit
send_prompt.sh --target claude-desktop --message "Read notes.md" --submit
send_prompt.sh --target gemini-cli --message "continue" --session gemini_shard_01 --submit
```

**Key flags:**
- `--target` (required): Where to send — `claude-desktop`, `claude-cli`, `codex-cli`, `gemini-cli`, `claude-web`, `chatgpt-web`, `user`
- `--message` (required): The text to send
- `--submit`: Press Enter after typing. **Without this, text is typed but NOT sent.**
- `--session <name>`: Target a specific Zellij session (CLI targets only)
- `--convo_id <url>`: Target a specific conversation (Desktop: `claude://` URLs, Web: chat URLs)
- `--force`: Skip busy checks
- `--fb_queue`: If busy, queue message to file-based inbox
- `--fb_notification`: If busy, send macOS notification

**Common mistake:** Forgetting `--submit`. The message gets typed into the prompt but never sent.

Run `send_prompt.sh --help` or `send_prompt.sh --help-examples` for full docs.

### set_scheduled_prompt.sh — Schedule Future Prompts

Create, update, cancel, and list scheduled prompts. Schedules are stored as `.schedule` files and processed by the daemon.

```bash
# Wake Desktop Claude in 1 hour
set_scheduled_prompt.sh create wake_001 claude-desktop "" "Check tasks" "+1h"

# Poll inbox every 30 minutes
set_scheduled_prompt.sh create poll_inbox claude-cli "" "check inbox" "*/30 * * * *"

# Schedule for specific datetime
set_scheduled_prompt.sh create morning claude-desktop "" "Good morning" "2026-04-02 09:00:00"

# List active schedules
set_scheduled_prompt.sh list

# Cancel
set_scheduled_prompt.sh cancel wake_001
```

**Schedule specs:** `+30m`, `+2h`, `+1d` (relative), `2026-04-02 15:00:00` (absolute), `*/5 * * * *` (cron), `@hourly`, `@daily`

**Arguments for `create`:** `{id} {target} {target_id} {prompt} {schedule_spec} [priority]`
- `target_id` is the session name or conversation URL (use `""` if not needed)

Run `set_scheduled_prompt.sh --help` or `set_scheduled_prompt.sh --help-examples` for full docs.

### send_scheduled_prompt.sh — Execute a Schedule File

Reads a `.schedule` file, sends the prompt, and manages lifecycle. **Normally called by the daemon, not directly.**

```bash
# Manual trigger (for testing)
send_scheduled_prompt.sh ai_general/data/scheduled_prompts/active/wake_001.schedule
```

One-time schedules move to `completed/` after firing. Periodic schedules update `next_run` and stay in `active/`.

### scheduled_prompts_daemon.sh — Background Scheduler

Polls active schedules every 60 seconds and fires any that are due.

```bash
scheduled_prompts_daemon.sh start     # Start background daemon
scheduled_prompts_daemon.sh status    # Check if running + next due schedule
scheduled_prompts_daemon.sh stop      # Stop daemon
scheduled_prompts_daemon.sh reload    # Trigger immediate scan
scheduled_prompts_daemon.sh process   # Single-pass scan (used internally)
```

**The daemon must be running for scheduled prompts to fire.**

### ai_isBusy.sh — CLI Busy Detection

Check if a CLI agent session is currently processing a response.

```bash
ai_isBusy.sh claude-cli                        # Auto-discover session
ai_isBusy.sh codex-cli --session codex_abc123   # Specific session
```

Exit codes: `0` = idle, `1` = busy, `2` = error/not found.

Detection: captures last 5 lines of Zellij pane, looks for platform-specific busy indicators (`(thinking...)` for Claude, `esc to interrupt` for Codex, `esc to cancel` for Gemini). Uses double-check with 2s gap to avoid false negatives from flickering indicators.

### check_desktop_busy.sh — Desktop Busy Detection

Check if Claude Desktop is currently generating a response.

```bash
check_desktop_busy.sh
```

Exit codes: `0` = idle, `1` = busy, `2` = error (not running).

Uses macOS accessibility API (`AXElementBusy` attribute).

### poll_desktop_busy.sh — Desktop Busy Polling (Debug)

Polls Desktop busy status every second for 30 seconds. Useful for testing/debugging the busy detection.

## Library Scripts (Internal)

These are called by `send_prompt.sh` — you don't call them directly.

| Script                      | Purpose                                                  |
|-----------------------------|----------------------------------------------------------|
| `lib_send_prompt_cli.sh`    | Send to CLI agents via `zellij action write-chars`       |
| `lib_send_prompt_desktop.sh`| Send to Desktop Claude via AppleScript clipboard paste   |
| `lib_send_prompt_webui.sh`  | Send to web UIs via Chrome CDP (requires port 9222)      |

### lib_send_prompt_cli.sh

Discovers active Zellij sessions by pattern (`claude_cli_*`, `codex_*`, `gemini_*`) or accepts explicit `--session`. Sends text via `zellij action write-chars` and optionally presses Enter.

### lib_send_prompt_desktop.sh

Sends to Claude Desktop via AppleScript. Uses atomic clipboard paste to avoid interleaving with user typing. Shows a 10-second heads-up notification before stealing focus (bypass with `--no-confirm`). Supports `claude://` deep links via `--convo_id`.

### lib_send_prompt_webui.sh

Sends to Claude or ChatGPT web UIs via Chrome DevTools Protocol (CDP). Requires Chrome running with `--remote-debugging-port=9222`. Delegates to `~/bin/ai/chat/chat-send.js`.

## Other Files

| File                         | Purpose                                          |
|------------------------------|--------------------------------------------------|
| `SendToClaudeDesktop.app`    | macOS Automator app wrapper (legacy)             |
| `*.bak`                      | Backup files from previous versions              |

## File Locations

```
Schedules:  ai_general/data/scheduled_prompts/
              active/          .schedule files waiting to fire
              completed/       one-time schedules that have fired
              cancelled/       cancelled schedules
              daemon.pid       daemon process ID
              daemon.lock      processing lock
              scheduling.log   execution log

Queued:     Messages queued via --fb_queue go to platform-specific inboxes:
              claude-desktop: ai_comms/claude/prompting/incoming/scheduled/
              claude-cli:     ai_comms/claude_cli/tasks/to_execute/
              codex-cli:      ai_comms/codex_cli/to_execute/
              gemini-cli:     ai_comms/gemini_cli/to_execute/
```

## Prerequisites

- **CLI targets:** Zellij must be running with sessions matching expected name patterns
- **Desktop target:** Claude Desktop app must be running on macOS
- **Web targets:** Chrome must be running with `--remote-debugging-port=9222`
- **Scheduling:** The daemon must be started: `scheduled_prompts_daemon.sh start`

## Typical Workflows

### AI Agent Sending to Another AI Agent

```bash
# Claude CLI worker sends status to Desktop Claude
send_prompt.sh --target claude-desktop --message "Task req_1042 complete" --submit

# Orchestrator sends work to a CLI agent
send_prompt.sh --target claude-cli --session claude_cli_dev-lead_abc123 \
  --message "Review PR #42" --submit

# Queue if target is busy (message saved to file, not lost)
send_prompt.sh --target codex-cli --message "Run tests" --submit --fb_queue
```

### Self-Wake (Schedule a Prompt to Yourself)

```bash
# Desktop Claude schedules its own wake-up
set_scheduled_prompt.sh create self_wake claude-desktop "" \
  "Wake: check if CLI workers finished" "+20m"

# Make sure daemon is running
scheduled_prompts_daemon.sh start
```

### Periodic Monitoring

```bash
# Poll CLI inbox every 30 minutes
set_scheduled_prompt.sh create poll claude-cli "" "check inbox" "*/30 * * * *"
scheduled_prompts_daemon.sh start
```
