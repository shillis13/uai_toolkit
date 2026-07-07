#!/usr/bin/env python3
"""
codex_cli.py - Codex CLI Wrapper.

Uses lib_cli_common.py for shared functionality.
Location: ~/bin/ai/cli/codex_cli.py
Version: 1.1.0
Created: 2026-01-01

Features:
- Agent mode with context inheritance
- Tmux background execution
- Session locking and conflict handling
- Session listing via ~/.codex/sessions/ parsing
- Session resume via native `codex resume` command
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from uai_toolkit.cli.lib_cli_common import (
    BaseCLI,
    CLIConfig,
    CommonArgs,
    SessionRegistry,
    colorize_help,
    create_common_parser,
    find_binary,
    normalize_path,
    parse_common_args,
)


# =============================================================================
# Platform Configuration
# =============================================================================

PLATFORM = "codex"


def _get_codex_binary() -> Path:
    """
    Get codex binary path from PATH.

    Returns:
        Path to codex binary

    Raises:
        FileNotFoundError: If codex not found in PATH
    """
    result = find_binary("codex")
    if result is None:
        raise FileNotFoundError(
            "Required binary 'codex' not found in PATH. "
            "Install Codex CLI or add it to PATH."
        )
    return result


CODEX_CONFIG = CLIConfig(
    platform=PLATFORM,
    binary_path=_get_codex_binary(),
    working_dir_default=Path.home() / "Documents/AI/ai_root",
    log_dir=Path.home() / "Documents/AI/ai_root/ai_general/logs/codex_cli",
    registry_file=Path.home() / ".codex/session_registry.yml",
    agent_session_map=Path.home() / ".codex/agent_sessions.yml",
    tasks_dir=Path.home() / "Documents/AI/ai_root/ai_comms/codex_cli/tasks",
    lock_dir=Path.home() / ".codex/locks",
    prompts_dir=Path.home() / "Documents/AI/ai_root/ai_general/prompts",
)


# =============================================================================
# Codex CLI Class
# =============================================================================

class CodexCLI(BaseCLI):
    """Codex CLI wrapper with session management."""

    def get_lock_name(self, common_args: CommonArgs) -> str:
        """
        Build lock name with codex suffix.

        Args:
            common_args: Parsed common arguments

        Returns:
            Lock name string
        """
        return f"{common_args.agent_type or 'default'}_codex"

    def build_command(
        self,
        prompt: str,
        common_args: CommonArgs,
        passthrough_args: list[str] | None = None
    ) -> list[str]:
        """
        Build codex binary command line.

        Args:
            prompt: Bootstrap prompt
            common_args: Common arguments
            passthrough_args: Unknown args to pass through to binary

        Returns:
            Command as list of strings
        """
        cmd = [str(self.config.binary_path)]
        passthrough = passthrough_args or []

        # Sync mode (non-interactive) - use exec subcommand
        if common_args.sync:
            cmd.append("exec")

        # Model selection
        if common_args.model:
            cmd.extend(["--model", common_args.model])

        # Disable tools / read-only mode (takes precedence over auto_approve)
        if common_args.no_tools:
            cmd.extend(["--sandbox", "read-only"])
        # Auto-approve (only if not in no_tools mode)
        elif common_args.auto_approve:
            cmd.append("--dangerously-bypass-approvals-and-sandbox")

        # Add passthrough args (unknown to wrapper, native to binary)
        if passthrough:
            cmd.extend(passthrough)

        # Add prompt
        if prompt:
            cmd.append(prompt)

        return cmd

    def _build_resume_command(
        self,
        common_args: CommonArgs,
        passthrough: list[str],
        session_id: str | None = None,
        last: bool = False
    ) -> list[str]:
        """
        Build codex resume command.

        Args:
            common_args: Common arguments
            passthrough: Passthrough args
            session_id: Specific session to resume, or None
            last: If True, resume last session

        Returns:
            Command as list of strings
        """
        cmd = [str(self.config.binary_path)]

        # Global options before subcommand
        if common_args.model:
            cmd.extend(["--model", common_args.model])
        if common_args.auto_approve:
            cmd.append("--dangerously-bypass-approvals-and-sandbox")

        # Passthrough args (global options)
        if passthrough:
            cmd.extend(passthrough)

        # Resume subcommand
        if last:
            cmd.extend(["resume", "--last"])
        elif session_id:
            cmd.extend(["resume", session_id])

        return cmd

    def execute(self, prompt: str, common_args: CommonArgs, passthrough: list[str]) -> int:
        """
        Execute Codex CLI command with resume support.

        Args:
            prompt: Resolved prompt
            common_args: Parsed common arguments
            passthrough: Passthrough args for native binary

        Returns:
            Exit code
        """
        session_mode = common_args.session_mode

        if session_mode == "continue":
            cmd = self._build_resume_command(common_args, passthrough, last=True)
        elif session_mode.startswith("resume:"):
            session_id = session_mode.split(":", 1)[1]
            cmd = self._build_resume_command(common_args, passthrough, session_id=session_id)
        else:
            cmd = self.build_command(prompt, common_args, passthrough)

        return self.execute_command(cmd, prompt, common_args)


# =============================================================================
# Subcommands
# =============================================================================

def _get_codex_sessions(limit: int = 20, cwd_filter: str | None = None) -> list[dict]:
    """
    Parse Codex session files from ~/.codex/sessions/.
    
    Args:
        limit: Maximum sessions to return
        cwd_filter: If provided, only return sessions from this directory
        
    Returns:
        List of session dicts sorted by timestamp (newest first)
    """
    import json
    from datetime import datetime
    
    sessions_dir = Path.home() / ".codex" / "sessions"
    if not sessions_dir.exists():
        return []
    
    sessions = []
    
    # Walk through year/month/day structure
    for session_file in sessions_dir.rglob("rollout-*.jsonl"):
        try:
            with open(session_file, "r") as f:
                first_line = f.readline()
                if not first_line:
                    continue
                    
                data = json.loads(first_line)
                if data.get("type") != "session_meta":
                    continue
                    
                payload = data.get("payload", {})
                session_cwd = payload.get("cwd", "")
                
                # Apply cwd filter if specified
                if cwd_filter and not session_cwd.startswith(cwd_filter):
                    continue
                
                sessions.append({
                    "id": payload.get("id", ""),
                    "timestamp": payload.get("timestamp", ""),
                    "cwd": session_cwd,
                    "model": payload.get("model_provider", ""),
                    "version": payload.get("cli_version", ""),
                    "file": str(session_file),
                })
        except (json.JSONDecodeError, IOError):
            continue
    
    # Sort by timestamp descending
    sessions.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    
    return sessions[:limit]


def cmd_list(args: list[str]) -> int:
    """List Codex sessions by parsing ~/.codex/sessions/."""
    limit = 20
    cwd_filter = None
    verbose = "--verbose" in args or "-v" in args
    all_sessions = "--all" in args
    
    # Parse limit argument
    for i, arg in enumerate(args):
        if arg.isdigit():
            limit = int(arg)
        elif arg not in ("--verbose", "-v", "--all"):
            # Treat as cwd filter
            cwd_filter = normalize_path(arg)
    
    if all_sessions:
        cwd_filter = None
    
    sessions = _get_codex_sessions(limit=limit, cwd_filter=cwd_filter)
    
    if not sessions:
        print("No sessions found")
        return 0
    
    print(f"Codex Sessions (showing {len(sessions)}):")
    print("=" * 80)

    if not verbose:
        print(f"  {'SESSION ID':<16}  {'TIMESTAMP':<19}  CWD")
        print("  " + "-" * 76)

    for s in sessions:
        session_id = s["id"]
        ts = s["timestamp"][:19].replace("T", " ") if s["timestamp"] else "unknown"
        cwd = s["cwd"]
        
        if verbose:
            print(f"\n  ID:        {session_id}")
            print(f"  Timestamp: {ts}")
            print(f"  CWD:       {cwd}")
            print(f"  Version:   {s['version']}")
        else:
            # Truncate cwd for display
            cwd_display = cwd[-40:] if len(cwd) > 40 else cwd
            if len(cwd) > 40:
                cwd_display = "..." + cwd_display
            print(f"  {session_id[:16]}  {ts}  {cwd_display}")
    
    if not verbose:
        print()
        print("Use --verbose for full details, --all to ignore cwd filter")
        print("Resume: codex_cli.py resume <session_id>")
    
    return 0


def cmd_latest(args: list[str]) -> int:
    """Get latest session ID."""
    cwd_filter = None
    if args and args[0] not in ("--all",):
        cwd_filter = normalize_path(args[0])
    
    sessions = _get_codex_sessions(limit=1, cwd_filter=cwd_filter)
    
    if sessions:
        print(sessions[0]["id"])
    
    return 0


def cmd_info(args: list[str]) -> int:
    """Get session info by ID."""
    if not args:
        print("Error: session_id required", file=sys.stderr)
        return 1
    
    target_id = args[0]
    sessions = _get_codex_sessions(limit=1000)  # Get all to search
    
    for s in sessions:
        if s["id"] == target_id or s["id"].startswith(target_id):
            print(f"Session ID:  {s['id']}")
            print(f"Timestamp:   {s['timestamp']}")
            print(f"CWD:         {s['cwd']}")
            print(f"CLI Version: {s['version']}")
            print(f"File:        {s['file']}")
            return 0
    
    print(f"Session not found: {target_id}", file=sys.stderr)
    return 1


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


# =============================================================================
# Main Entry Point
# =============================================================================

def _normalize_wrapper_args(args: list[str]) -> list[str]:
    """Normalize wrapper-only aliases before parsing."""
    normalized: list[str] = []
    for arg in args:
        if arg == "--print":
            # Alias for sync mode
            normalized.append("--sync")
            continue
        normalized.append(arg)
    return normalized


def print_usage() -> None:
    """Print help message."""
    print(colorize_help("""Usage: codex_cli.py [options] [--prompt PROMPT]

Prompt Options:
  --prompt TEXT          Prompt text (wrapper passes to codex)

Execution Options:
  -m, --model MODEL      Model to use (e.g., o3, o4-mini, gpt-4.1)
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
  --sync                 Non-interactive: run prompt, print output, exit (uses exec subcommand)
  --print                Alias for --sync (compatibility)

Native Flag Support:
  ALL native codex binary flags are supported and passed through.
  Some wrapper flags are processed first, then passed through (possibly modified):
    -m/--model      → Processed by wrapper, passed to binary
    -a/--auto-approve → Converted to appropriate flag for binary
    --resume/--continue → Processed and passed to binary

  All other native flags pass through unchanged.

  Passthrough flags can appear anywhere; the wrapper keeps them intact.

  Note: -p is reserved by the native codex binary and is not supported here.

Commands:
  list [dir] [N]         List N recent sessions (default: 20, filters by cwd)
  list --all             List all sessions regardless of cwd
  latest [dir]           Get most recent session ID
  info <session_id>      Get session info
  registry [--verbose]   List registered sessions
  register <n> <id> <d>  Register session with name
  unregister <n>         Remove from registry

Examples:
  # Quick task (runs in tmux by default)
  codex_cli.py --prompt "List all Python files"

  # Direct foreground (no tmux) for pipes or terminal issues
  codex_cli.py --no-tmux --prompt "Have a conversation"

  # With agent role
  codex_cli.py -A librarian --prompt "Process the queue"

  # Named tmux session
  codex_cli.py -s my_task --prompt "Run analysis"

  # Dry run to see bootstrap prompt
  codex_cli.py --dry-run --any-task

  # Sync mode - run, print output, exit
  codex_cli.py --sync --prompt "What files are in the current directory?"

  # With permission prompts (non-default)
  codex_cli.py --no-auto-approve -A librarian --prompt "Review sensitive data"

  # Passthrough native codex flags
  codex_cli.py --prompt "prompt" --approval-policy=on-failure --sandbox=workspace-write

  # List recent sessions
  codex_cli.py list
  codex_cli.py list --verbose
  codex_cli.py list --all 50

  # Resume a session
  codex_cli.py resume              # picker
  codex_cli.py resume --last       # most recent
  codex_cli.py resume <session_id> # specific

Orchestrator Usage (for Desktop Claude, scripts, etc.):
  # Launch worker with prompt (tmux default)
  codex_cli.py -s worker_001 -A dev-lead --prompt "Implement the feature"

  # Launch worker with task file
  codex_cli.py -s task_runner -T path/to/task.md

  # Launch worker claiming next available task
  codex_cli.py -s queue_worker --any-task
"""))


def main() -> int:
    """Main entry point."""
    exit_code = 0
    raw_args = sys.argv[1:]
    if "-p" in raw_args:
        print(
            "Error: -p is reserved by the native codex binary and is not supported "
            "by this wrapper. Use --prompt TEXT.",
            file=sys.stderr,
        )
        return 2
    args = _normalize_wrapper_args(raw_args)
    handled = False

    # Pass through native subcommands directly to codex binary FIRST
    # (before --help check, so `codex_cli.py resume --help` works)
    if args and args[0] in ("resume", "fork", "exec", "review", "apply"):
        cmd = [str(CODEX_CONFIG.binary_path)] + args
        result = subprocess.run(cmd)
        exit_code = result.returncode
        handled = True

    # Handle --help
    if not handled and ("--help" in args or "-h" in args):
        print_usage()
        handled = True

    if not handled:
        # Check for subcommands (including native ones to pass through)
        if args and args[0] in ("list", "latest", "info", "registry", "register", "unregister"):
            cmd = args[0]
            cmd_args = args[1:]

            cli = CodexCLI(CODEX_CONFIG)

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

            handled = True

    if not handled:
        # Parse common arguments
        parser = create_common_parser(PLATFORM)
        common_args, passthrough_args = parse_common_args(parser, args, CODEX_CONFIG)

        # Handle empty invocation - only show usage if background mode with no agent
        # Interactive mode (-i) without prompt is valid - launches CLI directly
        # Resume/continue without prompt is valid - continuing existing session
        if not common_args.prompt and not common_args.task_file and not common_args.any_task:
            is_resuming = common_args.session_mode != "new"
            if common_args.exec_mode == "tmux" and not common_args.agent_type and not is_resuming:
                print(
                    "Error: missing --prompt/--task/--any-task. Provide one, or use "
                    "-i/--interactive or a resume/continue option.",
                    file=sys.stderr,
                )
                print_usage()
                handled = True

        if not handled:
            # Run CLI
            cli = CodexCLI(CODEX_CONFIG)
            exit_code = cli.run(common_args, passthrough_args)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
