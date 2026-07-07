# Codex CLI & Coordination Install Guide (v1)

This guide walks through installing the Codex CLI, wiring it into Claude's coordination protocol, and validating the file-per-task workflow described in the v3.1 specification.

## 0. TODO
Add setting up of different Agent types and instructions, plus any use of plugins and skills

## 1. Prerequisites
- **Codex CLI binary** reachable on `PATH` (e.g., `/usr/local/bin/codex` or via Homebrew). Verify with `codex --version`.
- **Claude CLI** installed (the wrapper expects `/opt/homebrew/bin/claude`). Confirm with `claude --version`.
- **Claude Desktop configuration access** (`~/Library/Application Support/Claude/claude_desktop_config.json`).
- **Local documentation**: skim `~/.claude/CLAUDE.md` for filesystem safety requirements and coordination expectations.
- **Protocol reference**: `$HOME/AI/ai_comms/claude_cli/docs/protocol_v03.1_file_per_task.md` (file-per-task workflow details).

> Tip: Run `which codex` and `which claude` to confirm command paths and adjust the snippets below if your locations differ.

## 2. Directory Setup
Create the v3.1 coordination structure before first launch. The `CLAUDE.md` and protocol both stress using shell utilities (not filesystem connectors) for new files.

```bash
ln -s $AI_ROOT/ai_comms/claude_cli ~/.claude/coordination
```

## 3. MCP Configuration
Add the Codex CLI as an MCP server so Claude Desktop can launch it on demand.

1. Open `claude_desktop_config.json` in your preferred editor after creating a backup.
2. Locate (or create) the `"mcpServers"` object.
3. Add an entry similar to the following, updating paths as needed:

```json
{
  "mcpServers": {
    "codex": {
      "command": "/usr/local/bin/codex",
      "args": ["--stdio"],
      "autoLaunch": true,
      "env": {
        "CLAUDE_COORDINATION_ROOT": "~/.claude/coordination"
      }
    }
  }
}
```

4. Save and verify the JSON is valid (use `jq .` if available).
5. Restart Claude Desktop so the new MCP server loads.

## 4. Wrapper Script (`~/bin/bash/claude.sh`)
The existing wrapper launches Claude CLI with an initialization prompt:

```bash
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export DISABLE_PROMPT_CMD=1
export CLAUDECODE=1
CLAUDE_BIN="/opt/homebrew/bin/claude"
if [ $# -eq 0 ]; then
    exec "$CLAUDE_BIN" "Initialize coordination: read ~/.claude/CLAUDE.md coordination section and follow the setup steps, then check for pending broadcasts and direct tasks"
else
    exec "$CLAUDE_BIN" "$@"
fi
```

- If the file already matches the above (run `cat ~/bin/bash/claude.sh`), no action is needed.
- Otherwise, create/update it with `mkdir -p ~/bin/bash` followed by `cat > ~/bin/bash/claude.sh <<'EOF' ...` and `chmod +x ~/bin/bash/claude.sh`.
- Ensure `/opt/homebrew/bin` precedes other `PATH` entries if the `claude` binary lives there.

## 5. Test Procedure
1. **Dry run Codex CLI:** `codex --version` (checks binary availability).
2. **Dry run Claude CLI:** `~/bin/bash/claude.sh --version` or `claude --help`.
3. **Launch coordination session:** run `~/bin/bash/claude.sh` with no arguments. The wrapper instructs Claude to read `~/.claude/CLAUDE.md` and initialize coordination.
4. **Verify directories:** `ls ~/.claude/coordination/` should show `broadcasts/`, `direct/`, `responses/`, etc.
5. **Check for pending work:**
   ```bash
   ls ~/.claude/coordination/broadcasts/*.md 2>/dev/null
   ls ~/.claude/coordination/direct/cli_$(pgrep -f claude | head -1)/*.md 2>/dev/null
   ```
6. **Confirm response path:** after completing a test request, ensure a response file appears under `responses/cli_$CLI_INSTANCE_ID/` per the protocol example.

## 6. Troubleshooting
- **`codex` not found:** verify installation path, reinstall via Homebrew (`brew install codex-cli`) or npm (`npm install -g @anthropic-ai/codex-cli`) as appropriate.
- **`claude` not found:** reinstall Claude CLI or adjust `CLAUDE_BIN` in the wrapper.
- **MCP fails to launch:** check `claude_desktop_config.json` for JSON syntax errors; confirm the Codex binary is executable.
- **File operations silently fail:** revisit `~/.claude/CLAUDE.md`—always read a file before modifying it and use shell utilities for creation.
- **No coordination folders:** rerun the directory setup commands or allow the wrapper's initialization prompt to re-create them.
- **PID literal `$$_` in filenames:** export `CLI_INSTANCE_ID=$$` before creating liveness markers, as emphasized in the protocol document.

With prerequisites satisfied, directories seeded, MCP configured, and the wrapper script in place, the Codex CLI can participate fully in the v3.1 coordination workflow.
