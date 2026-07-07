# CLI MCP Server Configuration

**Created:** 2025-11-18  
**Purpose:** Enable CLI instances to use Desktop Commander and BrowserMCP  
**Script:** `$HOME/bin/setup_cli_mcp_servers.sh`

## Summary

Both Claude CLI (Claude Code) and Codex CLI now have access to:
- **desktop-commander** - Filesystem operations, process management, REPL interaction, search
- **browsermcp** - Chrome browser automation via CDP

## What Was Configured

### Codex CLI
**Config:** `~/.codex/config.toml`

Added MCP servers section:
```toml
[mcp_servers.desktop-commander]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-desktop-commander"]

[mcp_servers.browsermcp]
command = "npx"
args = ["@browsermcp/mcp"]
```

### Claude CLI (Claude Code)
**Config:** `~/.claude/config.json` (managed via CLI commands)

Added servers using:
```bash
claude mcp add desktop-commander --transport stdio --scope user -- npx -y @modelcontextprotocol/server-desktop-commander
claude mcp add browsermcp --transport stdio --scope user -- npx @browsermcp/mcp
```

## Verification

Check configured servers:
```bash
# Codex CLI
codex mcp list

# Claude CLI
claude mcp list
```

## Usage in Coordination Tasks

### Desktop Claude → CLI Coordination

Desktop Claude can now delegate tasks that require these tools to CLI instances:

**Example task file:**
```markdown
# Request #1050: Analyze Browser State

## Task Description
Use BrowserMCP to capture current Chrome tab state and extract form data.

## Task Commands
```bash
# CLI will use browsermcp MCP tools automatically
# Desktop Commander tools also available for file operations
```

## Expected Response
Extracted form fields as JSON.
```

### Tool Availability

**CLI instances can now:**
- Use `desktop_commander:*` tools for filesystem/process work
- Use `browsermcp:*` tools for Chrome automation
- Combine both for complex workflows (e.g., capture browser snapshot → write to file → analyze)

## Relationship to Desktop Claude

**Desktop Claude config:** `~/Library/Application Support/Claude/claude_desktop_config.json`

Active MCP servers:
- desktop-commander ✅
- browsermcp ✅
- pdf-tools ✅
- codex ✅

**All instances now have:**
- ✅ Desktop Commander (filesystem, processes, search)
- ✅ BrowserMCP (Chrome automation)

**Desktop Claude additionally has:**
- PDF tools (form filling, manipulation)
- Codex MCP (synchronous autonomous execution)

## Next Steps

1. **Restart any active CLI instances** to load new MCP servers
2. **Test in new session:**
   ```bash
   # Start Codex
   codex
   
   # Or Claude CLI
   claude
   ```

3. **Try a test task:**
   - Desktop posts browser snapshot task
   - CLI uses BrowserMCP to capture
   - Desktop Commander writes results

## Troubleshooting

If MCP servers don't appear:
1. Ensure CLI instance fully restarted
2. Check config files are correct (see paths above)
3. Run `codex mcp list` or `claude mcp list` to verify
4. First-time `npx` calls will download packages (may take a few seconds)

## Re-running Setup

The setup script is idempotent. Running again will:
- Skip if servers already configured in Codex
- Add or update servers in Claude CLI
- Preserve existing configuration

```bash
$HOME/bin/setup_cli_mcp_servers.sh
```

---

**Integration with existing systems:**
- CLI Coordination Protocol v4.0 ✅ Compatible
- Chat Orchestrator ✅ Compatible  
- Desktop Commander workflows ✅ Compatible
- BrowserMCP automation ✅ Compatible
