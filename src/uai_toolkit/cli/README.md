# cli

<<<<<<< Updated upstream
Core CLI session launcher and supporting libraries for all three AI platforms (Claude, Codex, Gemini). `ai_launcher.py` is the single entry point for launching any CLI agent session; everything else is a library, wrapper, or utility built around it.
=======
Core CLI session launcher and supporting libraries for all three AI platforms (Claude, Codex, Gemini). `ai_launch.py` is the canonical public entry point for launching any CLI agent session.
>>>>>>> Stashed changes

**Design rule:** Only `ai_launcher.py` calls the CLI binaries. No other script constructs or executes CLI commands. See `DESIGN.md` for the full constraint set.

## Scripts

<<<<<<< Updated upstream
### ai_launcher.py
The primary session launcher. Handles identity lifecycle (tracking ID generation, UUID assignment, session registry writes), constructs the bootstrap prompt, selects the terminal substrate (zellij or tmux), and launches the appropriate CLI binary (claude/codex/gemini). Implements a table-driven "busybox" design: the three symlinks `claudeCli`, `codexCli`, and `geminiCli` all point here, and `argv[0]` determines the platform.
=======
### ai_launch.py
The canonical session launcher entry point. Detects platform from the busybox symlink name (or explicit `--platform` when run directly), then delegates to `lib_orchestrator.py`, which uses `lib_cli_wrapper.py` and `lib_session_mgr.py`.

>>>>>>> Stashed changes

**Usage:**
```
claudeCli [--role ROLE] [--task TASK_ID] [--prompt TEXT] [--model MODEL]
           [--workdir DIR] [--display-name NAME] [--devtree] [--resume UUID]
           [--pre-prompt TEXT] [--any-task] [-a]
codexCli  [same flags]
geminiCli [same flags]
```

### claudeCli, codexCli, geminiCli
Symlinks to `ai_launcher.py`. Platform is detected from `argv[0]`.

### lib_cli_common.py
Shared library for all CLI wrappers. Provides: bootstrap prompt assembly, system instructions file writing, session registry operations, agent session tracking, zellij/tmux substrate helpers, task file parsing, `AI_ROOT` resolution (with devTree support), and common argparse setup. Imported by `ai_launch.py` and `lib_agent_ops.py`.

### lib_paths.py
Centralized path constants: `AI_ROOT`, `SESSION_REGISTRY_DIR`, `SESSIONS_DIR`, `UNIFIED_CLI_DIR`. All scripts needing these paths import from here rather than constructing them inline.

### lib_agent_ops.py
Business logic library for CLI-agent tooling. Provides agent launching, session listing, get-status, terminal interaction, and task factory operations. All functions return plain dicts/strings. It is imported by `agent_ops_cli.py`, not directly by the MCP tool layer. Agent launches flow through the canonical launcher entrypoints (`claudeCli` / `codexCli` / `geminiCli`); terminal session creation is owned by the launcher, not by this library.

### agent_ops_cli.py
CLI wrapper around `lib_agent_ops.py` — subprocess-callable interface matching the 15 operations the `sessions` MCP exposes. Used by MCP tools that call this via subprocess. Output is JSON to stdout. This is a specialized façade for role/task-oriented agent launches, not a replacement for the generic launcher entrypoints.

**Usage:**
```
agent_ops_cli.py list_sessions
agent_ops_cli.py launch_agent --platform claude_cli --role librarian --prompt "organize memories"
agent_ops_cli.py get_status --session-id TRACKING_ID
agent_ops_cli.py launch_dev_lead --platform claude_cli
agent_ops_cli.py launch_librarian --platform claude_cli
```

### find_jsonl_transcript.py
Locates the JSONL transcript file for a session given a tracking ID or session name. Queries `session_store.py` to get the platform and UUID, then computes the expected transcript path under `~/.claude/projects/` (Claude), `~/.codex/sessions/` (Codex), or `~/.gemini/tmp/` (Gemini).

**Usage:**
```
find_jsonl_transcript.py <tracking_id_or_name>
```

### fork_into_dir.py
Forks a CLI session into a different project directory by copying the session transcript to the new project's platform-specific location and optionally launching there via `ai_launch.py`. Preserves the session UUID so context carries over.

**Usage:**
```
fork_into_dir.py <uuid> <old_dir> <new_dir> --platform <platform> [--no-launch]
```

### fork_session.py
Forks a session with optional one-shot mode and callback support. Resolves the parent session's project directory, then calls the CLI wrapper with `--fork-from`. Supports writing the response to a file or forwarding it as a prompt to another session.

**Usage:**
```
fork_session.py --from <id> --prompt "task"
fork_session.py --from abc12345 --prompt "review" --oneshot --response-file /tmp/review.md
fork_session.py --from abc12345 --prompt "analyze" --oneshot --prompt-target claude_cli_95993
```

### change_proj_dir.py
Moves (not copies) a CLI session's transcript to a different project directory, then optionally relaunches there. Uses shared helpers from `fork_into_dir.py`. For Codex sessions, no file move is needed.

**Usage:**
```
change_proj_dir.py <uuid> <old_dir> <new_dir> --platform <platform> [--no-launch]
```

### launch_from_brief.py
Launches a new CLI session pre-loaded with a session brief YAML file as context. The brief is injected via `--pre-prompt` as a file-read instruction, so the successor AI loads it from disk as background/reference context before processing user instructions rather than receiving the full brief body inline.

**Usage:**
```
launch_from_brief.py --platform claude --brief /path/to/brief.yml
launch_from_brief.py --platform codex --brief /path/to/brief.yml --name "successor session"
launch_from_brief.py --platform gemini --brief brief.yml --workdir /some/project --dry-run
```

### load_brief_into.py
Loads a brief into an already-running CLI session by sending a submitted wrapper prompt that tells the AI to read the brief from disk as background/reference context.

**Usage:**
```
load_brief_into.py --session 20260510_101846_d5109a3b_cod --brief /path/to/brief.yml
load_brief_into.py --session my-terminal-session --brief brief.yml --dry-run
```

### generate_skill_artifacts.py
Generates `SKILL.md` files and system-prompt injection text from skill YAML definitions in `ai_profiles/skills/*.yml`. Outputs to `ai_profiles/skills/generated/`. Run manually when skill definitions change.

**Usage:**
```
generate_skill_artifacts.py                    # Generate all skills
generate_skill_artifacts.py <skill_name>       # Generate one skill
generate_skill_artifacts.py --list             # List available skills
generate_skill_artifacts.py --dry-run          # Preview without writing
generate_skill_artifacts.py --format skill_md  # Only SKILL.md files
generate_skill_artifacts.py --format prompt    # Only system prompt text
```

### gemini_mcp_lock.py
Reference-counted lock for temporarily disabling MCP servers in Gemini. When multiple shard processes need to run without MCP tool access (to avoid initialization delays and prevent unintended tool usage), they acquire this lock. The `mcpServers` config is cleared on first acquire and restored on last release. Used as a context manager or manual acquire/release.

### gemini_memory_lock.py
Reference-counted lock for suppressing `~/.gemini/GEMINI.md` during shard operations. Works identically to `gemini_mcp_lock.py` but hides the global memory file instead of MCP config.

### capture_uuid_playwright.py
Captures the CLI session UUID from a running UnifiedCLI Electron app using Playwright automation + zellij screen dump. Connects to the app via CDP on port 9224, sends `/status`, and reads the UUID from the terminal output. Run manually when a session UUID was not captured at launch time.

**Usage:**
```
capture_uuid_playwright.py <zellij_session_name>
capture_uuid_playwright.py --all
```

## Dependencies

- `pyyaml` — required by `lib_cli_common.py` and `generate_skill_artifacts.py`
- `~/bin/ai/utils/standard_colors` — color output in multiple scripts
- `~/bin/ai/session_mgmt/` — `lib_session.py`, `lib_session_substrate.py`, `session_store.py`
- `playwright` (pip) — required only for `capture_uuid_playwright.py`
- `zellij` or `tmux` — terminal substrate

## Notes

The `archive/` subdirectory contains retired launcher implementations and the old per-platform scripts (`claude_cli.py`, `codex_cli.py`, `gemini_cli.py`). Do not use them. The `gemini_mcp_lock.py` and `gemini_memory_lock.py` files predate the current architecture and may need review; they reference a "shard" approach that is no longer the primary execution model. `capture_uuid_playwright.py` requires the UnifiedCLI Electron app to be running and is primarily a recovery tool.
