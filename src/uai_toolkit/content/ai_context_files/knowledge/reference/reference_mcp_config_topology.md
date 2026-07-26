---
name: reference_mcp_config_topology
description: How MCP server config is sourced/deployed for Claude Code, why consolidated-away
  servers linger as 'failed', and the symlink-path project-key gotcha
status: active
---

**Canonical source:** `ai_general/data/MCP.json` (dict under `servers`). Deployed by `ai_general/scripts/setup/deploy_mcp_configs.py` to per-platform TARGETS:
- `claude_cli` → `~/.claude/mcp_cli_config.json` ← the file CLI sessions are launched with (`--mcp-config`)
- `claude_desktop` → Claude desktop config; `gemini` → `~/.gemini/settings.json`; `uci` → `~/.mcp.json`

**Why consolidated/removed servers linger as "✘ Failed to connect" (the 2026-06-14 cleanup):** Claude Code *merges* the `--mcp-config` file WITH the normal `~/.claude.json` scopes (it is not launched `--strict-mcp-config`). The pre-consolidation servers (chat-pipeline, cli-agent, knowledge-search, memory, messages, prompting, task-coord, todo) and `codex` were registered in `~/.claude.json` **user scope**, which the canonical deploy NEVER touches/prunes. So editing `data/MCP.json` only governs `mcp_cli_config.json`; the stale user-scope entries persist and fail (their `apps/mcps/<name>/server.py` no longer exist).

**Correct removal paths:**
- User/project-scope entries in `~/.claude.json`: use `claude mcp remove <name>` (race-safe; `~/.claude.json` is live-written by the running CC process — do NOT hand-edit it). It auto-resolves scope.
- Canonical-managed servers (e.g. obsidian-vault): remove from `data/MCP.json` then run `deploy_mcp_configs.py` (auto-backs-up targets).

**Symlink-path gotcha:** `~/Documents/AI` is a symlink; the real path is `~/AI`. `claude mcp` canonicalizes cwd via realpath, so **project/local-scope** entries keyed under the `~/Documents/AI/...` path are invisible to the CLI (it looks under `~/AI/...`). Such entries (e.g. a stray `obsidian` http + `local-llm` under this workspace) are inert — CC never loads them — but `claude mcp remove -s local/project` can't find them either; they'd need a hand-edit. Leave unless they actually load.

**Durable fix (proposed, PianoMan's call):** launch sessions `--strict-mcp-config` so ONLY `mcp_cli_config.json` counts and stale `~/.claude.json` blocks become irrelevant. Requires first migrating the user-scope-only keepers (`chat`, `macos-tools`) into canonical `data/MCP.json`. See [[reference_adding_mcp_tools.md]], [[reference_mcp_schema_validation.md]].
