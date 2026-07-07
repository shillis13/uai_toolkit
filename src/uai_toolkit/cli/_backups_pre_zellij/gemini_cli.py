#!/usr/bin/env python3
"""
gemini_cli.py - Gemini CLI Wrapper.

Uses lib_cli_common.py for shared functionality.
Location: ~/bin/ai/cli/gemini_cli.py
Version: 1.0.0
Created: 2026-01-01

Features:
- Model selection
- Agent mode with context inheritance
- Tmux background execution
- Session locking and conflict handling
- Resume/continue session support
"""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

from uai_toolkit.cli.lib_cli_common import (
    BaseCLI,
    CLIConfig,
    CommonArgs,
    SessionRegistry,
    colorize_help,
    create_common_parser,
    ensure_directory,
    normalize_path,
    parse_common_args,
    parse_task_file,
)

from gemini_memory_lock import GeminiMemoryLock, GeminiMemoryLockError


# =============================================================================
# Platform Configuration
# =============================================================================

PLATFORM = "gemini"

GEMINI_CONFIG = CLIConfig(
    platform=PLATFORM,
    binary_path=Path("gemini"),  # Assumes in PATH
    working_dir_default=Path.home() / "Documents/AI/ai_root",
    log_dir=Path.home() / "Documents/AI/ai_root/ai_general/logs/gemini_cli",
    registry_file=Path.home() / ".gemini/session_registry.yml",
    agent_session_map=Path.home() / ".gemini/agent_sessions.yml",
    tasks_dir=Path.home() / "Documents/AI/ai_root/ai_comms/gemini_cli/tasks",
    lock_dir=Path.home() / ".gemini/locks",
    prompts_dir=Path.home() / "Documents/AI/ai_root/ai_general/prompts",
)


# =============================================================================
# Gemini CLI Class
# =============================================================================

class GeminiCLI(BaseCLI):
    """Gemini CLI wrapper with model selection."""

    def __init__(self, config: CLIConfig) -> None:
        """
        Initialize Gemini CLI wrapper.

        Args:
            config: Platform configuration
        """
        super().__init__(config)
        ensure_directory(config.registry_file.parent)

    def build_prompt(self, common_args: CommonArgs) -> str:
        """
        Build prompt with Gemini-specific suffix.

        Args:
            common_args: Parsed common arguments

        Returns:
            Complete bootstrap prompt with execution directive
        """
        prompt = super().build_prompt(common_args)

        # Counter gemini binary's "wait for next turn" behavior
        prompt += "\nExecute these instructions now."

        return prompt

    def execution_context(self, common_args: CommonArgs):
        """
        Suppress global memory during launch if requested.

        Args:
            common_args: Parsed common arguments

        Returns:
            Context manager (GeminiMemoryLock or nullcontext)
        """
        if common_args.start_clean or common_args.suppress_global_memory:
            return self._memory_lock_context()
        from contextlib import nullcontext
        return nullcontext()

    @contextmanager
    def _memory_lock_context(self):
        """Context manager for GeminiMemoryLock."""
        lock = None
        try:
            lock = GeminiMemoryLock()
            lock.acquire()
            self.logger.info("Global memory suppressed for this session")
        except GeminiMemoryLockError as e:
            print(f"Warning: Could not suppress global memory: {e}", file=sys.stderr)
        try:
            yield
        finally:
            if lock is not None:
                lock.release()

    def build_command(
        self,
        prompt: str,
        common_args: CommonArgs,
        passthrough_args: list[str] | None = None
    ) -> list[str]:
        """
        Build gemini binary command line.

        Args:
            prompt: Bootstrap prompt
            common_args: Common arguments
            passthrough_args: Unknown args to pass through to binary

        Returns:
            Command as list of strings
        """
        cmd = [str(self.config.binary_path)]
        passthrough = passthrough_args or []

        # Model selection
        if common_args.model:
            cmd.extend(["-m", common_args.model])

        # Auto-approve
        if common_args.auto_approve:
            cmd.append("--yolo")

        # Disable MCP tools (for shards that should only search in-memory context)
        if common_args.no_tools:
            cmd.extend(["--allowed-mcp-server-names", "NONE"])
            cmd.extend(["--allowed-tools", "NONE"])

        # Session handling
        session_mode = common_args.session_mode
        if session_mode == "continue":
            cmd.extend(["--resume", "latest"])
        elif session_mode == "resume":
            cmd.extend(["--resume", "latest"])
        elif session_mode.startswith("resume:"):
            session_id = session_mode.split(":", 1)[1]
            cmd.extend(["--resume", session_id])

        # Add passthrough args (unknown to wrapper, native to binary)
        if passthrough:
            cmd.extend(passthrough)

        # Prompt handling depends on exec_mode and sync
        if prompt:
            # Sync mode forces one-shot (positional prompt)
            if common_args.sync:
                cmd.append(prompt)
            elif common_args.exec_mode in ("tmux", "interactive"):
                cmd.extend(["--prompt-interactive", prompt])
            else:
                cmd.append(prompt)

        return cmd

    def execute(self, prompt: str, common_args: CommonArgs, passthrough: list[str]) -> int:
        """
        Execute Gemini CLI command.

        Args:
            prompt: Resolved prompt
            common_args: Parsed common arguments
            passthrough: Passthrough args for native binary

        Returns:
            Exit code
        """
        cmd = self.build_command(prompt, common_args, passthrough)
        return self.execute_command(cmd, prompt, common_args)


# =============================================================================
# Subcommands
# =============================================================================

def cmd_list(args: list[str]) -> int:
    """List sessions by delegating to gemini --list-sessions."""
    import subprocess
    cmd = ["gemini", "--list-sessions"]
    result = subprocess.run(cmd)
    return result.returncode


def cmd_latest(args: list[str]) -> int:
    """Get latest session (not available for Gemini)."""
    print("")  # Return empty like shell version
    return 0


def cmd_info(args: list[str]) -> int:
    """Get session info (not available for Gemini)."""
    print("Session info not available for Gemini")
    return 0


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


def cmd_task(args: list[str], cli: GeminiCLI, auto_approve: bool) -> int:
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

        # Build minimal CommonArgs for task execution
        common_args = CommonArgs(
            exec_mode="tmux",
            session_mode=task_info.session_mode,
            working_dir=task_info.project_dir,
            auto_approve=auto_approve,
            output_file=None,
            tmux_session=f"gemini_cli_{os.getpid()}",
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
    print(colorize_help("""Usage: gemini_cli.py [options] [prompt]

Models:
  gemini-2.5-pro         Latest Pro model
  gemini-2.5-flash       Fast balanced model
  gemini-2.5-flash-lite  Lightweight fast model
  gemini-3-flash-preview Preview of Gemini 3 Flash
  gemini-3-pro-preview   Preview of Gemini 3 Pro

Session Options:
  -c, --continue         Continue most recent session
  -r, --resume ID        Resume specific session by ID
  -n, --named NAME       Resume registered session by name

Execution Options:
  -m, --model MODEL      Model to use (see Models above)
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
  --start-clean          Skip all bootstrap, suppress ~/.gemini/GEMINI.md - just explicit prompt
  --suppress-global-memory  Suppress ~/.gemini/GEMINI.md only (without skipping bootstrap)
  --sync                 Non-interactive: run prompt, print output, exit (one-shot mode)

Native Flag Support:
  ALL native gemini binary flags are supported and passed through.
  Some wrapper flags are processed first, then passed through (possibly modified):
    -m/--model      → Processed by wrapper, passed as -m to binary
    -a/--auto-approve → Converted to --yolo for binary
    --resume/--continue → Processed and passed as --resume to binary

  All other native flags pass through unchanged.

  Boolean passthrough flags work anywhere:
    gemini_cli.py --verbose "prompt"

Commands:
  list <dir> [N]         List N recent sessions (not available)
  latest <dir>           Get most recent session ID (not available)
  info <session_id>      Get session info (not available)
  registry [--verbose]   List registered sessions
  register <n> <id> <d>  Register session with name
  unregister <n>         Remove from registry
  task <file>            Execute task file

Examples:
  # Simple prompt (runs in tmux by default)
  gemini_cli.py "Explain quantum computing"

  # Direct foreground (no tmux) for pipes or terminal issues
  gemini_cli.py --no-tmux "Let's work on this together"

  # With agent and task
  gemini_cli.py -A librarian -T condense_batch_001 "Start processing"

  # Foreground mode with specific model
  gemini_cli.py --no-tmux -m gemini-2.5-pro "Let's work on this together"

  # Named tmux session for orchestrator supervision
  gemini_cli.py -s worker_gem -A librarian -T task_v21 -m gemini-2.5-pro

  # Dry run to see bootstrap prompt
  gemini_cli.py --dry-run -A custodian "Check system health"

  # With permission prompts (non-default)
  gemini_cli.py --no-auto-approve -A librarian "Review sensitive data"

  # Passthrough native gemini flags
  gemini_cli.py "prompt" --sandbox=none --temperature=0.8

  # Shard workflow: launch clean for resume (no bootstrap)
  gemini_cli.py -a -s shard-01.tmux.20260204 --start-clean

Tmux Commands (when using -t):
  tmux capture-pane -t <session> -p      # View current output
  tmux send-keys -t <session> 'msg' Enter    # Send message
  tmux attach -t <session>               # Attach to session
  tmux kill-session -t <session>         # Kill session

Orchestrator Usage (for Desktop Claude, scripts, etc.):
  # Launch worker with prompt (tmux default)
  gemini_cli.py -s worker_001 -m gemini-2.5-pro -A librarian "Analyze the data"

  # Launch worker with task file
  gemini_cli.py -s task_runner -T path/to/task.md

  # Launch worker claiming next available task
  gemini_cli.py -s queue_worker --any-task
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

    if not handled:
        # Check for subcommands
        if args and args[0] in ("list", "latest", "info", "registry", "register", "unregister", "task"):
            cmd = args[0]
            cmd_args = args[1:]

            cli = GeminiCLI(GEMINI_CONFIG)

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
                exit_code = cmd_task(cmd_args, cli, auto_approve)

            handled = True

    if not handled:
        # Show usage only for completely bare invocation (no arguments at all)
        if not args:
            print_usage()
            handled = True

    if not handled:
        # Parse common arguments (includes -m/--model)
        parser = create_common_parser(PLATFORM)
        common_args, passthrough_args = parse_common_args(parser, args, GEMINI_CONFIG)

        # Run CLI — all three launch modes (bare, prompt+interactive, prompt+exit)
        # work through the same path regardless of exec environment (tmux, foreground, sync)
        cli = GeminiCLI(GEMINI_CONFIG)
        exit_code = cli.run(common_args, passthrough_args)

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
