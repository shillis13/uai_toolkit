#!/usr/bin/env python3
"""
claude_cli.py - Claude CLI Wrapper.

Uses lib_cli_common.py for shared functionality.
Location: ~/bin/ai/cli/claude_cli.py
Version: 1.0.0
Created: 2026-01-01

Features:
- Session continue/resume/named via history.jsonl
- MCP configuration
- Agent mode with context inheritance
- Tmux background execution
- Task file execution
- Session locking and conflict handling
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

from uai_toolkit.cli.lib_cli_common import (
    BaseCLI,
    CLIConfig,
    CommonArgs,
    SessionRegistry,
    AgentSessionMap,
    colorize_help,
    create_common_parser,
    ensure_directory,
    find_binary,
    generate_fork_session_name,
    normalize_path,
    parse_common_args,
    parse_task_file,
)


# =============================================================================
# Platform Configuration
# =============================================================================

PLATFORM = "claude"

CLAUDE_CONFIG = CLIConfig(
    platform=PLATFORM,
    binary_path=Path.home() / ".local/bin/claude",
    working_dir_default=Path.home() / "Documents/AI/ai_root",
    log_dir=Path.home() / "Documents/AI/ai_root/ai_general/logs/claude_cli",
    registry_file=Path.home() / ".claude/session_registry.yml",
    agent_session_map=Path.home() / ".claude/agent_sessions.yml",
    tasks_dir=Path.home() / "Documents/AI/ai_root/ai_comms/claude_cli/tasks",
    lock_dir=Path.home() / ".claude/locks",
    prompts_dir=Path.home() / "Documents/AI/ai_root/ai_general/prompts",
)

HISTORY_FILE = Path.home() / ".claude/history.jsonl"
AGENTS_FILE = Path.home() / ".claude/agents.json"
MCP_CONFIG_FILE = Path.home() / ".claude/mcp_cli_config.json"


def build_mcp_config() -> str:
    """
    Build MCP configuration dynamically using detected binary paths.

    Returns:
        JSON string with MCP server configuration

    Raises:
        FileNotFoundError: If required binaries (node, npx) not found
    """
    home = str(Path.home())

    # Detect node and npx binaries via PATH
    node_bin = find_binary("node")
    npx_bin = find_binary("npx")

    if node_bin is None:
        raise FileNotFoundError(
            "Required binary 'node' not found in PATH. "
            "Install Node.js or add it to PATH."
        )
    if npx_bin is None:
        raise FileNotFoundError(
            "Required binary 'npx' not found in PATH. "
            "Install Node.js or add it to PATH."
        )

    # Desktop Commander extension path
    dc_extension = Path(home) / "Library/Application Support/Claude/Claude Extensions/ant.dir.gh.wonderwhy-er.desktopcommandermcp/dist/index.js"

    # Use current PATH from environment
    current_path = os.environ.get("PATH", "/usr/bin:/bin:/usr/sbin:/sbin")

    config = {
        "mcpServers": {
            "desktop-commander": {
                "command": str(node_bin),
                "args": [str(dc_extension)],
                "env": {"PATH": current_path}
            },
            "filesystem": {
                "command": str(npx_bin),
                "args": [
                    "-y",
                    "@modelcontextprotocol/server-filesystem",
                    f"{home}/bin",
                    f"{home}/Documents/AI"
                ],
                "env": {"PATH": current_path}
            }
        }
    }
    result = json.dumps(config, indent=2)
    return result


# =============================================================================
# Claude-Specific Functions
# =============================================================================

def ensure_mcp_config() -> None:
    """
    Ensure MCP configuration file exists.

    Writes default config if missing.
    """
    config_dir = MCP_CONFIG_FILE.parent
    ensure_directory(config_dir)

    if not MCP_CONFIG_FILE.exists():
        mcp_content = build_mcp_config()
        MCP_CONFIG_FILE.write_text(mcp_content)


def get_latest_session(project_dir: Path) -> str | None:
    """
    Get most recent session for project from history.jsonl.

    Args:
        project_dir: Project directory to filter by

    Returns:
        Session ID or None
    """
    result = None

    if HISTORY_FILE.exists():
        project_str = str(project_dir)
        try:
            with open(HISTORY_FILE) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("project") == project_str:
                            result = entry.get("sessionId")
                    except json.JSONDecodeError:
                        continue
        except OSError:
            pass  # result remains None

    return result


def get_session_info(session_id: str) -> str:
    """
    Get session info from history.

    Args:
        session_id: Session ID to look up

    Returns:
        Info string or "Not found"
    """
    result = "Not found"

    if not HISTORY_FILE.exists():
        result = "No history"
    else:
        try:
            with open(HISTORY_FILE) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("sessionId") == session_id:
                            ts = entry.get("timestamp", "?")
                            display = entry.get("display", "")[:80]
                            result = f"{ts} | {display}..."
                            break
                    except json.JSONDecodeError:
                        continue
        except OSError:
            result = "Error reading history"

    return result


def list_project_sessions(project_dir: Path, limit: int = 10) -> list[dict]:
    """
    List recent sessions for project.

    Args:
        project_dir: Project directory to filter by
        limit: Maximum number of sessions

    Returns:
        List of session info dicts
    """
    sessions: list[dict] = []

    if HISTORY_FILE.exists():
        project_str = str(project_dir)

        try:
            with open(HISTORY_FILE) as f:
                for line in f:
                    try:
                        entry = json.loads(line.strip())
                        if entry.get("project") == project_str:
                            sessions.append({
                                "session_id": entry.get("sessionId"),
                                "timestamp": entry.get("timestamp"),
                                "display": entry.get("display", "")[:60],
                            })
                    except json.JSONDecodeError:
                        continue
        except OSError:
            sessions = []

    # Deduplicate by session_id, keeping the entry with the most recent timestamp
    seen: dict[str, dict] = {}
    for s in sessions:
        sid = s["session_id"]
        if sid not in seen or s["timestamp"] > seen[sid]["timestamp"]:
            seen[sid] = s
    deduped = sorted(seen.values(), key=lambda x: x["timestamp"])

    # Return last N sessions
    result = deduped[-limit:]
    return result


# =============================================================================
# Claude CLI Class
# =============================================================================

class ClaudeCLI(BaseCLI):
    """Claude CLI wrapper with session history and MCP support."""

    def __init__(self, config: CLIConfig) -> None:
        """
        Initialize Claude CLI wrapper.

        Args:
            config: Platform configuration
        """
        super().__init__(config)
        self.agent_sessions = AgentSessionMap(config.agent_session_map)
        self.no_mcp = False
        self.resolved_session_id = None
        ensure_mcp_config()

    def resolve_session_mode(self, common_args: CommonArgs) -> int:
        """
        Resolve session mode with agent session tracking.

        Handles:
        - Agent session resolution (last session, named session lookup)
        - Named session registry lookup
        - Converts resolved sessions to resume: mode where appropriate

        Args:
            common_args: Parsed common arguments (may be mutated)

        Returns:
            Exit code (0 to continue, non-zero to stop)
        """
        session_mode = common_args.session_mode
        user_requested_continue = session_mode == "continue"
        self.resolved_session_id = None

        # Agent session resolution
        if common_args.agent_type:
            if session_mode == "continue":
                # Try last agent session first
                agent_last = self.agent_sessions.get_last_session(common_args.agent_type)
                if agent_last:
                    common_args.session_mode = f"resume:{agent_last}"
                    self.resolved_session_id = agent_last
                else:
                    # Try named session
                    named_id = self.registry.get_by_name(common_args.agent_type)
                    if named_id:
                        common_args.session_mode = f"named:{common_args.agent_type}"
                        self.resolved_session_id = named_id
                    else:
                        common_args.session_mode = "new"
            elif session_mode == "new":
                # Check for existing agent session (auto-resume with bootstrap)
                named_id = self.registry.get_by_name(common_args.agent_type)
                if named_id:
                    common_args.session_mode = f"named:{common_args.agent_type}"
                    self.resolved_session_id = named_id

        # Named session registry lookup
        if common_args.session_mode.startswith("named:"):
            name = common_args.session_mode.split(":", 1)[1]
            sid = self.registry.get_by_name(name)
            if not sid:
                print(f"Error: No session named '{name}'", file=sys.stderr)
                return 1
            self.registry.touch(name)
            self.resolved_session_id = sid
            # If user explicitly asked to continue, treat as resume (skip bootstrap)
            if user_requested_continue:
                common_args.session_mode = f"resume:{sid}"

        return 0

    def on_fork_conflict(self, common_args: CommonArgs, lock_name: str) -> str:
        """
        Handle fork conflict - also resets session mode to new.

        Args:
            common_args: Parsed common arguments (mutated)
            lock_name: Current lock name

        Returns:
            New lock name
        """
        common_args.tmux_session = generate_fork_session_name(lock_name)
        common_args.session_mode = "new"
        return common_args.tmux_session

    def build_command(
        self,
        prompt: str,
        common_args: CommonArgs,
        passthrough_args: list[str] | None = None
    ) -> list[str]:
        """
        Build claude binary command line.

        Args:
            prompt: Bootstrap prompt
            common_args: Common arguments
            passthrough_args: Unknown args to pass through to binary

        Returns:
            Command as list of strings
        """
        cmd = [str(self.config.binary_path)]
        passthrough = passthrough_args or []

        # Sync mode (non-interactive)
        if common_args.sync:
            cmd.append("--print")

        # Model selection
        if common_args.model:
            cmd.extend(["--model", common_args.model])

        # MCP config
        if not self.no_mcp:
            cmd.extend(["--mcp-config", str(MCP_CONFIG_FILE)])

        # Disable all tools (for read-only context search use cases)
        if common_args.no_tools:
            cmd.extend(["--tools", ""])
            cmd.append("--strict-mcp-config")

        # Auto-approve
        if common_args.auto_approve:
            cmd.append("--dangerously-skip-permissions")

        # Session flags
        session_mode = common_args.session_mode
        if session_mode == "continue":
            cmd.append("-c")
        elif session_mode.startswith("resume:"):
            session_id = session_mode.split(":", 1)[1]
            cmd.extend(["-r", session_id])
        elif session_mode.startswith("named:"):
            if self.resolved_session_id:
                cmd.extend(["-r", self.resolved_session_id])

        # Fork from parent
        if common_args.fork_from:
            cmd.extend(["--resume", common_args.fork_from, "--fork-session"])

        # Agent context
        if common_args.agent_type:
            if AGENTS_FILE.exists():
                agents_content = AGENTS_FILE.read_text()
                cmd.extend(["--agents", agents_content])
                cmd.extend(["--agent", common_args.agent_type])

        # Add passthrough args (unknown to wrapper, native to binary)
        if passthrough:
            cmd.extend(passthrough)

        # Add prompt (with -- separator to prevent argument parsing issues)
        if prompt:
            cmd.append("--")
            cmd.append(prompt)

        return cmd

    def execute(self, prompt: str, common_args: CommonArgs, passthrough: list[str]) -> int:
        """
        Execute Claude CLI command.

        Args:
            prompt: Resolved prompt
            common_args: Parsed common arguments
            passthrough: Passthrough args for native binary

        Returns:
            Exit code
        """
        cmd = self.build_command(prompt, common_args, passthrough)
        exit_code = self.execute_command(cmd, prompt, common_args)

        # Record agent session if applicable
        if common_args.agent_type and not self.resolved_session_id:
            latest = get_latest_session(common_args.working_dir)
            if latest:
                self.agent_sessions.record_session(common_args.agent_type, latest)

        return exit_code


# =============================================================================
# Subcommands
# =============================================================================

def cmd_list(args: list[str]) -> int:
    """List sessions for project."""
    from datetime import datetime

    project_dir = normalize_path(args[0] if args else ".")
    limit = int(args[1]) if len(args) > 1 else 10

    print(f"Sessions for: {project_dir}")
    print("-" * 80)

    sessions = list_project_sessions(project_dir, limit)
    if not sessions:
        print("None")
    else:
        print(f"{'TIMESTAMP':<20} | {'SESSION ID':<36} | FIRST MESSAGE")
        print("-" * 80)
        for s in sessions:
            raw_ts = s['timestamp']
            try:
                formatted_ts = datetime.fromtimestamp(int(raw_ts) / 1000).strftime("%Y-%m-%d %H:%M:%S")
            except (TypeError, ValueError, OSError):
                formatted_ts = str(raw_ts)
            print(f"{formatted_ts:<20} | {s['session_id']:<36} | {s['display']}...")

    return 0


def cmd_latest(args: list[str]) -> int:
    """Print most recent session ID."""
    project_dir = normalize_path(args[0] if args else ".")
    session_id = get_latest_session(project_dir)
    if session_id:
        print(session_id)
    return 0


def cmd_info(args: list[str]) -> int:
    """Show session details."""
    exit_code = 0

    if not args:
        print("Error: session_id required", file=sys.stderr)
        exit_code = 1
    else:
        info = get_session_info(args[0])
        print(info)

    return exit_code


def cmd_registry(args: list[str], registry: SessionRegistry) -> int:
    """List registered sessions."""
    verbose = "--verbose" in args

    print("Registered Sessions:")
    print("=" * 40)

    sessions = registry.list_all(verbose)
    if not sessions:
        print("  (none)")
    else:
        for s in sessions:
            status = s.get("status", "unknown")
            icon = "●" if status == "active" else "○"
            if verbose:
                print(f"\n{icon} {s['name']}")
                print(f"    ID:      {s.get('session_id', 'N/A')[:16]}...")
                print(f"    Project: {s.get('project_dir', 'N/A')}")
                print(f"    Desc:    {s.get('description', '')}")
                print(f"    Used:    {s.get('last_used', 'N/A')}")
            else:
                desc = s.get("description", "")[:40]
                print(f"  {icon} {s['name']:25} {desc}")

    return 0


def cmd_register(args: list[str], registry: SessionRegistry) -> int:
    """Register a named session."""
    exit_code = 0

    if len(args) < 3:
        print("Error: register NAME ID DIR [DESC]", file=sys.stderr)
        exit_code = 1
    else:
        name, session_id, project_dir = args[0], args[1], args[2]
        desc = args[3] if len(args) > 3 else ""

        registry.register(name, session_id, normalize_path(project_dir), desc)
        print(f"Registered: {name} -> {session_id}")

    return exit_code


def cmd_unregister(args: list[str], registry: SessionRegistry) -> int:
    """Remove from registry."""
    exit_code = 0

    if not args:
        print("Error: name required", file=sys.stderr)
        exit_code = 1
    else:
        if registry.unregister(args[0]):
            print(f"Unregistered: {args[0]}")
        else:
            print(f"Not found: {args[0]}")

    return exit_code


def cmd_task(args: list[str], cli: ClaudeCLI, auto_approve: bool) -> int:
    """Execute task file."""
    exit_code = 0
    task_info = None
    task_file = None
    task_file_orig = args[0] if args else None

    if not args:
        print("Error: task file required", file=sys.stderr)
        exit_code = 1
    else:
        task_file = normalize_path(args[0])
        try:
            task_info = parse_task_file(task_file)
        except FileNotFoundError:
            print(f"Error: Task file not found: {task_file}", file=sys.stderr)
            exit_code = 1

    if exit_code == 0 and task_info and task_file:
        cli.logger.info(f"Task: {task_file} | Mode: {task_info.session_mode} | Dir: {task_info.project_dir}")

        # Auto mode: continue if session exists, else new
        session_mode = task_info.session_mode
        if session_mode == "auto":
            latest = get_latest_session(task_info.project_dir)
            session_mode = "continue" if latest else "new"

        # Build minimal CommonArgs for task execution
        common_args = CommonArgs(
            exec_mode="tmux",
            session_mode=session_mode,
            working_dir=task_info.project_dir,
            auto_approve=auto_approve,
            output_file=None,
            tmux_session=f"claude_cli_{os.getpid()}",
            agent_type=None,
            task_file=task_file,
            task_file_orig=task_file_orig,
            any_task=False,
            any_task_dir=None,
            any_task_dir_orig=None,
            pre_prompt=None,
            post_prompt=None,
            on_conflict="fork",
            fork_from=None,
            dry_run=False,
            prompt=task_info.prompt,
            model=None,
            sync=False,
            start_clean=False,
            suppress_global_memory=False,
            no_tools=False,
        )

        exit_code = cli.run(common_args)

    return exit_code


# =============================================================================
# Main Entry Point
# =============================================================================

def print_usage() -> None:
    """Print help message."""
    print(colorize_help("""Usage: claude_cli.py [options] [prompt]

Claude-Specific Options:
  --no-mcp               Run without MCP configuration
  --fork-from ID         Fork from parent session (inherits full context)

Session Options:
  -c, --continue         Continue most recent session in project
  -r, --resume ID        Resume specific session by ID
  -n, --named NAME       Resume registered session by name

Execution Options:
  -m, --model MODEL      Model to use (e.g., claude-sonnet-4-5, claude-opus-4)
  -t, --tmux             Run in tmux (default - flag optional)
  -s, --session NAME     Tmux session name
  --no-tmux              Run without tmux (direct foreground, for pipes)
  -i, --interactive      [DEPRECATED: use --no-tmux] Same as --no-tmux
  -a, --auto-approve     Skip permission prompts (default: enabled)
  --no-auto-approve      Require permission prompts for tool calls
  -w, --workdir DIR      Working directory
  -A, --agent TYPE       Use agent type (librarian, dev-lead, custodian, peer-review, tester, researcher, validator)
  -T, --task FILE        Load task instructions from file
  --any-task             Claim first available task from queue
  --pre-prompt TEXT      Text to prepend to bootstrap prompt
  --post-prompt TEXT     Text to append to bootstrap prompt
  -o, --output FILE      Write output to file
  --on-conflict MODE     If requested session already running: fork (default), exit, queue
  --dry-run              Print bootstrap prompt without invoking binary
  --sync                 Non-interactive: run prompt, print output, exit (uses --print)

Native Flag Support:
  ALL native claude binary flags are supported and passed through.
  Some wrapper flags are processed first, then passed through (possibly modified):
    -m/--model      → Processed by wrapper, passed to binary
    -a/--auto-approve → Converted to --dangerously-skip-permissions for binary
    --resume/--continue → Processed and passed to binary

  All other native flags pass through unchanged.

  IMPORTANT: Passthrough flags with values should either:
    - Come AFTER the prompt: claude_cli.py "prompt" --native-flag value
    - Use = syntax: claude_cli.py --native-flag=value "prompt"

  Boolean passthrough flags work anywhere:
    claude_cli.py --verbose "prompt"
    claude_cli.py "prompt" --verbose

Commands:
  list <dir> [N]         List N recent sessions for project dir
  latest <dir>           Get most recent session ID
  info <session_id>      Get session info
  registry [--verbose]   List registered sessions
  register <n> <id> <d>  Register session with name
  unregister <n>         Remove from registry
  task <file>            Execute task file

Examples:
  # Simple prompt (runs in tmux by default)
  claude_cli.py "Check inbox and process tasks"

  # Direct foreground (no tmux) for pipes or terminal issues
  claude_cli.py --no-tmux "Have a conversation"

  # Continue previous session
  claude_cli.py -c "Continue the refactoring"

  # Resume named session
  claude_cli.py -n librarian "Process new exports"

  # Run with agent
  claude_cli.py -A librarian "Condense the batch files"

  # Execute task file
  claude_cli.py task ~/.claude/coordination/to_execute/req_1050.md

  # Dry run to see bootstrap prompt
  claude_cli.py --dry-run -A dev-lead "Plan the refactor"

  # Sync mode - run, print output, exit (no session)
  claude_cli.py --sync "What is 2+2?"

  # With permission prompts (non-default)
  claude_cli.py --no-auto-approve -A librarian "Review sensitive data"

  # Passthrough native claude flags
  claude_cli.py "prompt" --max-tokens=4096 --temperature=0.7

Orchestrator Usage (for Desktop Claude, scripts, etc.):
  # Launch worker with prompt (tmux default)
  claude_cli.py -s worker_001 -A librarian "Process the export queue"

  # Launch worker with task file
  claude_cli.py -s task_runner -T path/to/task.md

  # Launch worker claiming next available task
  claude_cli.py -s queue_worker --any-task
"""))


def main() -> int:
    """Main entry point."""
    exit_code = 0
    args = sys.argv[1:]
    handled = False

    # Handle --help
    if "--help" in args or "-h" in args:
        print_usage()
        handled = True

    # Extract Claude-specific flags before parsing
    no_mcp = False
    if not handled:
        no_mcp = "--no-mcp" in args
        if no_mcp:
            args.remove("--no-mcp")

        # Check for subcommands
        if args and args[0] in ("list", "latest", "info", "registry", "register", "unregister", "task"):
            cmd = args[0]
            cmd_args = args[1:]

            cli = ClaudeCLI(CLAUDE_CONFIG)

            if cmd == "list":
                exit_code = cmd_list(cmd_args)
            elif cmd == "latest":
                exit_code = cmd_latest(cmd_args)
            elif cmd == "info":
                exit_code = cmd_info(cmd_args)
            elif cmd == "registry":
                exit_code = cmd_registry(cmd_args, cli.registry)
            elif cmd == "register":
                exit_code = cmd_register(cmd_args, cli.registry)
            elif cmd == "unregister":
                exit_code = cmd_unregister(cmd_args, cli.registry)
            elif cmd == "task":
                auto_approve = "-a" in args or "--auto-approve" in args
                cli.no_mcp = no_mcp
                exit_code = cmd_task(cmd_args, cli, auto_approve)

            handled = True

    if not handled:
        # Show usage only for completely bare invocation (no arguments at all)
        if not args:
            print_usage()
            handled = True

    if not handled:
        # Parse common arguments
        parser = create_common_parser(PLATFORM)
        common_args, passthrough_args = parse_common_args(parser, args, CLAUDE_CONFIG)

        # Run CLI — all three launch modes (bare, prompt+interactive, prompt+exit)
        # work through the same path regardless of exec environment (tmux, foreground, sync)
        cli = ClaudeCLI(CLAUDE_CONFIG)
        cli.no_mcp = no_mcp
        exit_code = cli.run(common_args, passthrough_args)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
