#!/usr/bin/env python3
"""
lib_cli_common.py - Shared library for AI CLI wrappers.

Used by: claude_cli.py, codex_cli.py, gemini_cli.py
Location: ~/bin/ai/cli/lib_cli_common.py
Version: 1.0.0
Created: 2026-01-01

Provides:
- Configuration dataclasses
- Path utilities
- Bootstrap prompt assembly
- Session registry operations
- Agent session tracking
- Session locking
- Tmux operations
- Task file parsing
- Common argument parsing
- Logging
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# External dependency
import yaml


# =============================================================================
# ANSI Color Codes for Help Output
# =============================================================================

class Colors:
    """ANSI color codes for terminal output."""
    CYAN = "\033[36m"
    YELLOW = "\033[33m"
    GREEN = "\033[32m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    RESET = "\033[0m"

    @classmethod
    def disable(cls) -> None:
        """Disable colors (for non-TTY output)."""
        cls.CYAN = ""
        cls.YELLOW = ""
        cls.GREEN = ""
        cls.DIM = ""
        cls.BOLD = ""
        cls.RESET = ""


# Disable colors if stdout is not a TTY
if not sys.stdout.isatty():
    Colors.disable()


def colorize_help(text: str) -> str:
    """
    Apply ANSI colors to help text.
    
    - Section headers (ending with :) -> Cyan + Bold
    - Flags (-x, --flag) -> Yellow
    - Commands (list, registry, etc.) -> Green
    - Descriptions after flags -> Dim
    
    Args:
        text: Raw help text
        
    Returns:
        Colorized help text
    """
    import re
    
    lines = text.split('\n')
    result = []
    
    for line in lines:
        # Section headers (lines ending with : like "Session Options:")
        if line.strip().endswith(':') and not line.strip().startswith('-'):
            result.append(f"{Colors.CYAN}{Colors.BOLD}{line}{Colors.RESET}")
        # Flag lines (start with whitespace + -)
        elif line.strip().startswith('-'):
            # Match: leading indent + flag + spacing + description
            match = re.match(r'^(\s*)(-\S+(?:,\s*--?\S+)?(?:\s+\S+)?)(\s{2,})(.*)$', line)
            if match:
                indent, flag, spacing, desc = match.groups()
                result.append(f"{indent}{Colors.YELLOW}{flag}{Colors.RESET}{spacing}{Colors.DIM}{desc}{Colors.RESET}")
            else:
                # Fallback: colorize whole line as flag
                result.append(f"{Colors.YELLOW}{line}{Colors.RESET}")
        # Command lines in Examples or Commands sections (indented, start with word)
        elif re.match(r'^\s{2,}[a-z_]+(\s|$)', line) and not line.strip().startswith('#'):
            # Match command name at start
            match = re.match(r'^(\s+)([a-z_]+)(.*)$', line)
            if match:
                indent, cmd, rest = match.groups()
                result.append(f"{indent}{Colors.GREEN}{cmd}{Colors.RESET}{rest}")
            else:
                result.append(line)
        # Example command lines (start with # or contain cli.py)
        elif 'cli.py' in line or 'cli.sh' in line:
            result.append(f"{Colors.DIM}{line}{Colors.RESET}")
        else:
            result.append(line)
    
    return '\n'.join(result)


# =============================================================================
# Binary Detection
# =============================================================================

def find_binary(name: str, fallback_paths: list[str] | None = None) -> Path | None:
    """
    Find a binary by name using PATH, with optional fallback paths.

    Args:
        name: Binary name to find
        fallback_paths: Optional list of absolute paths to check if not in PATH

    Returns:
        Path to binary if found, None otherwise
    """
    result = None

    # Try PATH first
    path_result = shutil.which(name)
    if path_result:
        result = Path(path_result)
    elif fallback_paths:
        # Check fallback paths
        for fallback in fallback_paths:
            candidate = Path(fallback)
            if candidate.exists() and candidate.is_file():
                result = candidate
                break

    return result


def require_binary(name: str, fallback_paths: list[str] | None = None) -> Path:
    """
    Find a required binary, raising error if not found.

    Args:
        name: Binary name to find
        fallback_paths: Optional fallback paths to check

    Returns:
        Path to binary

    Raises:
        FileNotFoundError: If binary not found
    """
    result = find_binary(name, fallback_paths)
    if result is None:
        msg = f"Required binary '{name}' not found in PATH"
        if fallback_paths:
            msg += f" or fallback paths: {fallback_paths}"
        raise FileNotFoundError(msg)
    return result


# =============================================================================
# Configuration Dataclasses
# =============================================================================

@dataclass
class CLIConfig:
    """Platform configuration."""

    platform: str  # 'claude', 'codex', 'gemini'
    binary_path: Path
    working_dir_default: Path
    log_dir: Path
    registry_file: Path
    agent_session_map: Path
    tasks_dir: Path
    lock_dir: Path
    prompts_dir: Path

    agent_dirs: dict[str, Path] = field(default_factory=lambda: {
        # All roles point to ai_root - both hyphenated and underscored versions
        "librarian": Path.home() / "Documents/AI/ai_root",
        "researcher": Path.home() / "Documents/AI/ai_root",
        "dev-lead": Path.home() / "Documents/AI/ai_root",
        "dev_lead": Path.home() / "Documents/AI/ai_root",
        "custodian": Path.home() / "Documents/AI/ai_root",
        "peer-review": Path.home() / "Documents/AI/ai_root",
        "peer_review": Path.home() / "Documents/AI/ai_root",
        "tester": Path.home() / "Documents/AI/ai_root",
        "validator": Path.home() / "Documents/AI/ai_root",
    })


@dataclass
class TaskInfo:
    """Parsed task file information."""

    session_mode: str  # 'auto', 'new', 'continue'
    project_dir: Path
    prompt: str


@dataclass
class CommonArgs:
    """Common CLI arguments across all platforms."""

    exec_mode: str  # 'default', 'tmux', 'interactive'
    session_mode: str  # 'new', 'continue', 'resume:{id}', 'named:{name}'
    working_dir: Path
    auto_approve: bool
    output_file: Path | None
    tmux_session: str
    agent_type: str | None
    task_file: Path | None
    task_file_orig: str | None  # Original task file path as given
    any_task: bool
    any_task_dir: Path | None
    any_task_dir_orig: str | None  # Original any_task_dir as string
    pre_prompt: str | None
    post_prompt: str | None
    on_conflict: str  # 'fork', 'exit', 'queue'
    fork_from: str | None
    dry_run: bool
    prompt: str | None
    model: str | None  # Model override (platform-specific)
    sync: bool  # Non-interactive mode: Claude --print, Codex exec, Gemini positional
    start_clean: bool  # Launch with zero bootstrap - no project docs, no framework prompts
    suppress_global_memory: bool  # Suppress ~/.gemini/GEMINI.md during session (Gemini only)
    no_tools: bool  # Disable all MCP tools (Gemini: --allowed-mcp-server-names with empty value)


# =============================================================================
# Path Utilities
# =============================================================================

def normalize_path(path: str | Path) -> Path:
    """
    Normalize a path, expanding ~ and resolving to absolute.

    Args:
        path: Path string or Path object, may contain ~

    Returns:
        Absolute Path with ~ expanded and trailing slashes removed
    """
    result = Path.cwd()

    if path:
        path_obj = Path(path).expanduser()
        result = path_obj.resolve()

    return result


def ensure_directory(path: Path) -> None:
    """
    Ensure directory exists, creating if necessary.

    Args:
        path: Directory path to create

    Raises:
        OSError: If directory cannot be created
    """
    path.mkdir(parents=True, exist_ok=True)


# =============================================================================
# Bootstrap Prompt Assembly
# =============================================================================

def load_role_config(role: str, prompts_dir: Path) -> dict[str, Any]:
    """
    Load role configuration from role.yml.

    Args:
        role: Role name (librarian, dev_lead, custodian, ops, peer_review, tester)
        prompts_dir: Base prompts directory (ai_general/prompts)

    Returns:
        Dict with role config, or empty dict if not found
    """
    # Handle hyphenated vs underscored role names
    role_normalized = role.replace("-", "_")
    role_file = prompts_dir / "roles" / role_normalized / "role.yml"

    if not role_file.exists():
        # Try hyphenated version as fallback
        role_file = prompts_dir / "roles" / role / "role.yml"
        if not role_file.exists():
            return {}

    try:
        with open(role_file) as f:
            data = yaml.safe_load(f)
        return data if data else {}
    except (yaml.YAMLError, OSError):
        return {}


def get_role_context_files(role: str, prompts_dir: Path) -> list[str]:
    """
    Get context_files list from role.yml, supporting both old and new formats.

    Old format (backward compatible):
        context_files:
          - REF:path/to/file.yml
          - REF:another/file.md

    New format (load_sequence with tiers):
        load_sequence:
          auto:
            files:
              - pointer: REF:path/to/file.yml
              - pointer: REF:another/file.md
          topic:
            files: [...]  # Also included for CLI agents
          demand:
            files: [...]  # Excluded - on-demand only

    For CLI agents, we flatten auto + topic tiers (demand is excluded).

    Args:
        role: Role name
        prompts_dir: Base prompts directory

    Returns:
        List of file paths (relative to ai_root) from role's context_files
    """
    config = load_role_config(role, prompts_dir)
    result = []

    def extract_pointer(item: str | dict) -> str | None:
        """Extract file path from string or dict, stripping REF: prefix."""
        if isinstance(item, str):
            return item.replace("REF:", "").strip() or None
        elif isinstance(item, dict):
            pointer = item.get("pointer", "")
            return pointer.replace("REF:", "").strip() or None
        return None

    # Check for new format first (load_sequence)
    load_sequence = config.get("load_sequence")
    if load_sequence and isinstance(load_sequence, dict):
        # New tiered format - flatten auto + topic for CLI agents
        for tier in ["auto", "topic"]:
            tier_config = load_sequence.get(tier, {})
            if isinstance(tier_config, dict):
                files = tier_config.get("files", [])
                for item in files:
                    path = extract_pointer(item)
                    if path:
                        result.append(path)
    else:
        # Old format - flat context_files list
        context_files = config.get("context_files", [])
        for item in context_files:
            path = extract_pointer(item)
            if path:
                result.append(path)

    return result


def build_file_list(
    agent: str | None,
    has_task: bool,
    platform: str,
    prompts_dir: Path
) -> list[str]:
    """
    Determine which prompt files to include based on mode.

    Bootstrap hierarchy:
    1. Global (always) - universal instructions
    2. Platform (always) - platform-specific behavior
    3. Role context_files (if -A) - role's docs + prompt from role.yml
    4. Tasking (if -T/--any-task) - task execution protocol

    Args:
        agent: Role type (librarian, dev_lead, custodian, ops, peer_review, tester) or None
        has_task: True if -T or --any-task specified
        platform: One of 'claude', 'codex', 'gemini'
        prompts_dir: Base directory for prompt files

    Returns:
        Ordered list of relative path strings to prompt files
        Paths are relative to ai_root (e.g., 'ai_general/prompts/global.md')
    """
    base_prefix = "ai_general/prompts"
    files = []

    # 1. Global (always)
    files.append(f"{base_prefix}/global.md")

    # 2. Platform (always) - now in platforms/ subdirectory
    files.append(f"{base_prefix}/platforms/{platform}.md")

    # 3. Role context_files (if agent/role specified)
    # Reads from roles/{role}/role.yml and includes all context_files
    # This includes the role's prompt.md and supporting docs
    if agent:
        role_files = get_role_context_files(agent, prompts_dir)
        files.extend(role_files)

    # 4. Tasking (if task mode)
    if has_task:
        files.append(f"{base_prefix}/tasking.md")

    return files


def build_bootstrap_prompt(
    files: list[str],
    task_file: str | None,
    any_task_dir: str | None,
    pre_prompt: str | None,
    post_prompt: str | None,
    user_prompt: str | None,
    ai_root: str | None = None
) -> str:
    """
    Assemble the bootstrap prompt from components.

    Args:
        files: List of prompt file paths to reference (relative to ai_root)
        task_file: Specific task file path, or None
        any_task_dir: Directory for --any-task mode, or None
        pre_prompt: Text to prepend, or None
        post_prompt: Text to append, or None
        user_prompt: The actual user prompt, or None
        ai_root: AI root directory path (e.g., ~/Documents/AI/ai_root)

    Returns:
        Complete bootstrap prompt string:
        AI_ROOT: {ai_root}
        {pre_prompt}
        Read and follow instructions in: {file_list}.
        {task_clause}
        {post_prompt}
        {user_prompt}
    """
    parts = []

    # AI root directory - critical for file resolution
    if ai_root:
        parts.append(f"AI_ROOT: {ai_root}")

    # Pre-prompt
    if pre_prompt:
        parts.append(pre_prompt)

    # File list instruction
    file_refs = ", ".join(f"'{f}'" for f in files)
    instruction = f"Read and follow instructions in: {file_refs}."
    parts.append(instruction)

    # Task clause
    if task_file:
        task_clause = f"Claim and execute task: '{task_file}'."
        parts.append(task_clause)
    elif any_task_dir:
        task_clause = f"Claim and execute first available task from: '{any_task_dir}'."
        parts.append(task_clause)

    # Post-prompt
    if post_prompt:
        parts.append(post_prompt)

    # User prompt
    if user_prompt:
        parts.append(user_prompt)

    result = "\n".join(parts)
    return result


# =============================================================================
# Logging
# =============================================================================

class CLILogger:
    """Structured logging for CLI operations."""

    def __init__(self, log_dir: Path, platform: str) -> None:
        """
        Initialize logger.

        Args:
            log_dir: Directory for log files
            platform: Platform name for log file naming
        """
        self.log_dir = log_dir
        self.platform = platform
        ensure_directory(log_dir)
        self._wrapper_log = log_dir / f"{platform}_wrapper.log"

    def _write(self, level: str, message: str) -> None:
        """Write a log entry."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        entry = f"[{timestamp}] [{level}] {message}\n"
        with open(self._wrapper_log, "a") as f:
            f.write(entry)

    def info(self, message: str) -> None:
        """Log info level message."""
        self._write("INFO", message)

    def warn(self, message: str) -> None:
        """Log warning level message."""
        self._write("WARN", message)

    def error(self, message: str) -> None:
        """Log error level message."""
        self._write("ERROR", message)

    def session_start(
        self,
        session_mode: str,
        exec_mode: str,
        working_dir: Path,
        prompt: str
    ) -> Path:
        """
        Log session start with metadata.

        Args:
            session_mode: Session mode (new, continue, resume)
            exec_mode: Execution mode (default, tmux, interactive)
            working_dir: Working directory
            prompt: Prompt being executed

        Returns:
            Path to this session's log file
        """
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_file = self.log_dir / f"{self.platform}_cli_{ts}.log"

        header = f"""=== {self.platform.upper()} CLI: {datetime.now()} ===
Session: {session_mode} | Exec: {exec_mode} | Dir: {working_dir}
Prompt: {prompt[:100]}...
====================================
"""
        with open(log_file, "w") as f:
            f.write(header)

        return log_file

    def session_end(self, log_file: Path, exit_code: int) -> None:
        """
        Log session end.

        Args:
            log_file: Log file from session_start
            exit_code: Process exit code
        """
        entry = f"=== Ended: {datetime.now()} (exit: {exit_code}) ===\n"
        with open(log_file, "a") as f:
            f.write(entry)


# =============================================================================
# Session Registry
# =============================================================================

class SessionRegistry:
    """Manages named session persistence in YAML format."""

    def __init__(self, registry_file: Path) -> None:
        """
        Initialize registry with file path.

        Args:
            registry_file: Path to session_registry.yml
        """
        self.registry_file = registry_file
        self._ensure_file()

    def _ensure_file(self) -> None:
        """Create registry file if it doesn't exist."""
        if self.registry_file.exists():
            return
        ensure_directory(self.registry_file.parent)
        data = {"schema_version": "1.0", "sessions": {}}
        with open(self.registry_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def _load(self) -> dict[str, Any]:
        """Load registry data, recreating if corrupt."""
        default_data = {"schema_version": "1.0", "sessions": {}}
        result = default_data

        try:
            with open(self.registry_file) as f:
                data = yaml.safe_load(f)
            if data is not None:
                result = data
        except yaml.YAMLError as e:
            # Corrupt file - log warning and recreate
            print(f"Warning: Registry file corrupt ({e}), recreating.", file=sys.stderr)
            self._ensure_file()
        except FileNotFoundError:
            self._ensure_file()

        return result

    def _save(self, data: dict[str, Any]) -> None:
        """Save registry data."""
        with open(self.registry_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def register(
        self,
        name: str,
        session_id: str,
        project_dir: Path,
        description: str = ""
    ) -> None:
        """
        Register a named session.

        Args:
            name: Human-readable session name
            session_id: Platform session identifier
            project_dir: Associated project directory
            description: Optional description
        """
        data = self._load()
        if data.get("sessions") is None:
            data["sessions"] = {}

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data["sessions"][name] = {
            "session_id": session_id,
            "project_dir": str(project_dir),
            "description": description,
            "created": ts,
            "last_used": ts,
            "status": "active",
        }
        self._save(data)

    def get_by_name(self, name: str) -> str | None:
        """
        Look up session ID by name.

        Args:
            name: Session name to look up

        Returns:
            Session ID string or None if not found
        """
        result = None

        data = self._load()
        sessions = data.get("sessions") or {}
        session_info = sessions.get(name)
        if session_info:
            result = session_info.get("session_id")

        return result

    def touch(self, name: str) -> None:
        """
        Update last_used timestamp for session.

        Args:
            name: Session name to touch
        """
        data = self._load()
        sessions = data.get("sessions") or {}
        if name in sessions:
            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            sessions[name]["last_used"] = ts
            self._save(data)

    def unregister(self, name: str) -> bool:
        """
        Remove a session from registry.

        Args:
            name: Session name to remove

        Returns:
            True if removed, False if not found
        """
        removed = False

        data = self._load()
        sessions = data.get("sessions") or {}
        if name in sessions:
            del sessions[name]
            self._save(data)
            removed = True

        return removed

    def list_all(self, verbose: bool = False) -> list[dict]:
        """
        List all registered sessions.

        Args:
            verbose: If True, include full details

        Returns:
            List of session dictionaries
        """
        data = self._load()
        sessions = data.get("sessions") or {}
        result = []
        for name, info in sessions.items():
            entry = {"name": name, **info}
            result.append(entry)
        return result


# =============================================================================
# Agent Session Tracking
# =============================================================================

class AgentSessionMap:
    """Tracks last session used by each agent type."""

    def __init__(self, map_file: Path) -> None:
        """
        Initialize agent session map.

        Args:
            map_file: Path to agent_sessions.yml
        """
        self.map_file = map_file
        self._ensure_file()

    def _ensure_file(self) -> None:
        """Create map file if it doesn't exist."""
        if self.map_file.exists():
            return
        ensure_directory(self.map_file.parent)
        data = {"agents": {}}
        with open(self.map_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def _load(self) -> dict[str, Any]:
        """Load map data, recreating if corrupt."""
        default_data = {"agents": {}}
        result = default_data

        try:
            with open(self.map_file) as f:
                data = yaml.safe_load(f)
            if data is not None:
                result = data
        except yaml.YAMLError as e:
            # Corrupt file - log warning and recreate
            print(f"Warning: Agent session map corrupt ({e}), recreating.", file=sys.stderr)
            self._ensure_file()
        except FileNotFoundError:
            self._ensure_file()

        return result

    def _save(self, data: dict[str, Any]) -> None:
        """Save map data."""
        with open(self.map_file, "w") as f:
            yaml.dump(data, f, default_flow_style=False, sort_keys=False)

    def get_last_session(self, agent: str) -> str | None:
        """
        Get last session ID for agent.

        Args:
            agent: Agent type name

        Returns:
            Session ID or None
        """
        result = None

        data = self._load()
        agents = data.get("agents") or {}
        agent_info = agents.get(agent)
        if agent_info:
            result = agent_info.get("session_id")

        return result

    def record_session(self, agent: str, session_id: str) -> None:
        """
        Record session for agent.

        Args:
            agent: Agent type name
            session_id: Session identifier
        """
        data = self._load()
        if data.get("agents") is None:
            data["agents"] = {}

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        data["agents"][agent] = {
            "session_id": session_id,
            "last_used": ts,
        }
        self._save(data)


# =============================================================================
# Session Locking
# =============================================================================

class SessionLock:
    """File-based session locking for conflict prevention."""

    def __init__(self, lock_dir: Path, session_name: str) -> None:
        """
        Initialize lock for session.

        Args:
            lock_dir: Directory for lock files
            session_name: Name of session to lock
        """
        self.lock_dir = lock_dir
        self.session_name = session_name
        self.lock_file = lock_dir / f"{session_name}.lock"
        ensure_directory(lock_dir)

    def is_available(self) -> bool:
        """
        Check if session is available (no active lock).

        Returns:
            True if available, False if locked by active process
        """
        available = True

        if self.lock_file.exists():
            try:
                with open(self.lock_file) as f:
                    lines = f.readlines()
                if not lines:
                    self.lock_file.unlink()
                else:
                    pid = int(lines[0].strip())
                    # Check if process is running
                    try:
                        os.kill(pid, 0)
                        available = False  # Process exists, lock is active
                    except OSError:
                        # Process doesn't exist, stale lock
                        self.lock_file.unlink()
            except (ValueError, OSError):
                # Corrupt lock file, remove it
                self.lock_file.unlink()

        return available

    def acquire(self) -> None:
        """
        Acquire lock for this process.

        Writes PID and timestamp to lock file.
        """
        ts = datetime.now().astimezone().isoformat()
        pid = os.getpid()
        tmux_session = os.environ.get("TMUX_SESSION", "default")

        with open(self.lock_file, "w") as f:
            f.write(f"{pid}\n{ts}\n{tmux_session}\n")

    def release(self) -> None:
        """
        Release lock by removing lock file.
        """
        if self.lock_file.exists():
            self.lock_file.unlink()

    def get_info(self) -> dict | None:
        """
        Get information about current lock holder.

        Returns:
            Dict with pid, timestamp, tmux_session or None if unlocked
        """
        result = None

        if self.lock_file.exists():
            try:
                with open(self.lock_file) as f:
                    lines = f.readlines()
                if len(lines) >= 3:
                    result = {
                        "pid": int(lines[0].strip()),
                        "timestamp": lines[1].strip(),
                        "tmux_session": lines[2].strip(),
                    }
            except (ValueError, OSError):
                pass  # result remains None

        return result


# =============================================================================
# Tmux Operations
# =============================================================================

class TmuxSession:
    """Manages tmux session creation and interaction."""

    def __init__(
        self,
        session_name: str,
        working_dir: Path,
        tmux_bin: Path | None = None
    ) -> None:
        """
        Initialize tmux session handler.

        Args:
            session_name: Name for tmux session
            working_dir: Working directory for session
            tmux_bin: Path to tmux binary (auto-detected if None)

        Raises:
            FileNotFoundError: If tmux binary not found
        """
        self.session_name = session_name
        self.working_dir = working_dir
        if tmux_bin is None:
            self.tmux_bin = require_binary("tmux")
        else:
            self.tmux_bin = tmux_bin

    def exists(self) -> bool:
        """
        Check if session already exists.

        Returns:
            True if session exists
        """
        result = subprocess.run(
            [str(self.tmux_bin), "has-session", "-t", self.session_name],
            capture_output=True
        )
        return result.returncode == 0

    def kill(self) -> None:
        """
        Kill existing session if present.
        """
        subprocess.run(
            [str(self.tmux_bin), "kill-session", "-t", self.session_name],
            capture_output=True
        )

    def create(self, command: list[str], log_file: Path) -> None:
        """
        Create new session with command.

        Args:
            command: Command and arguments to run
            log_file: File for output capture
        """
        # Kill existing if present
        self.kill()

        # Build shell command string - preserve existing PATH and set Node heap
        path_setup = 'export PATH="$PATH"; '
        node_heap = 'export NODE_OPTIONS="--max-old-space-size=8192"; '
        cd_cmd = f"cd '{self.working_dir}'; "

        # Escape single quotes in command args
        escaped_args = []
        for arg in command:
            escaped = arg.replace("'", "'\\''")
            escaped_args.append(f"'{escaped}'")
        cmd_str = " ".join(escaped_args)

        full_cmd = f"{path_setup}{node_heap}{cd_cmd}{cmd_str}; sleep 30"

        # Create session
        subprocess.run([
            str(self.tmux_bin),
            "new-session", "-d",
            "-s", self.session_name,
            "-c", str(self.working_dir),
            full_cmd
        ])

        # Setup output capture
        output_log = log_file.with_suffix(".output.log")
        subprocess.run([
            str(self.tmux_bin),
            "pipe-pane", "-t", self.session_name,
            f"cat >> '{output_log}'"
        ])

        # Create symlink for session-name based log lookup
        # Allows tools like SwiftBar to find log by session name
        session_link = output_log.parent / f"{self.session_name}.output.log"
        try:
            if session_link.is_symlink() or session_link.exists():
                session_link.unlink()
            session_link.symlink_to(output_log.name)
        except OSError:
            pass  # Best effort - don't fail if symlink creation fails

    def capture_pane(self) -> str:
        """
        Capture current pane output.

        Returns:
            Current visible output
        """
        result = subprocess.run(
            [str(self.tmux_bin), "capture-pane", "-t", self.session_name, "-p"],
            capture_output=True,
            text=True
        )
        return result.stdout

    def send_keys(self, text: str) -> None:
        """
        Send input to session.

        Args:
            text: Text to send (Enter appended automatically)
        """
        subprocess.run([
            str(self.tmux_bin),
            "send-keys", "-t", self.session_name,
            text, "Enter"
        ])


# =============================================================================
# Task File Parsing
# =============================================================================

def parse_task_file(task_file: Path) -> TaskInfo:
    """
    Parse task file YAML front matter and content.

    Args:
        task_file: Path to task markdown file

    Returns:
        TaskInfo with parsed values

    Raises:
        FileNotFoundError: If task file doesn't exist
    """
    if not task_file.exists():
        raise FileNotFoundError(f"Task file not found: {task_file}")

    content = task_file.read_text()
    lines = content.split("\n")

    # Default values
    session_mode = "auto"
    project_dir = None
    prompt = content

    # Look for YAML front matter fields
    for line in lines:
        if line.startswith("session_mode:"):
            session_mode = line.split(":", 1)[1].strip()
        elif line.startswith("project_dir:"):
            dir_val = line.split(":", 1)[1].strip()
            project_dir = normalize_path(dir_val)

    # Extract prompt (after --- delimiter or full file)
    if "---" in content:
        parts = content.split("---", 2)
        if len(parts) >= 3:
            prompt = parts[2].strip()

    if project_dir is None:
        project_dir = Path.home() / "Documents/AI/ai_root"

    result = TaskInfo(
        session_mode=session_mode,
        project_dir=project_dir,
        prompt=prompt
    )
    return result


# =============================================================================
# Common Argument Parsing
# =============================================================================

def create_common_parser(platform: str) -> argparse.ArgumentParser:
    """
    Create argument parser with common options.

    Args:
        platform: Platform name for help text

    Returns:
        ArgumentParser with session, execution, agent/task options
    """
    parser = argparse.ArgumentParser(
        prog=f"{platform}_cli.py",
        description=f"{platform.capitalize()} CLI wrapper with session management",
        formatter_class=argparse.RawDescriptionHelpFormatter
    )

    # Session options
    session = parser.add_argument_group("Session Options")
    session.add_argument(
        "-c", "--continue", dest="continue_session", action="store_true",
        help="Continue most recent session in project"
    )
    session.add_argument(
        "-r", "--resume", metavar="ID",
        help="Resume specific session by ID"
    )
    session.add_argument(
        "-n", "--named", metavar="NAME",
        help="Resume registered session by name"
    )
    session.add_argument(
        "--fork-from", metavar="ID",
        help="Fork from parent session (inherits full context)"
    )

    # Execution options
    exec_opts = parser.add_argument_group("Execution Options")
    exec_opts.add_argument(
        "-m", "--model", metavar="MODEL",
        help="Model to use (platform-specific)"
    )
    exec_opts.add_argument(
        "-t", "--tmux", action="store_true",
        help="Run in tmux session (default behavior, flag optional)"
    )
    exec_opts.add_argument(
        "-s", "--session", metavar="NAME",
        help="Tmux session name"
    )
    exec_opts.add_argument(
        "--no-tmux", action="store_true",
        help="Run without tmux wrapper (direct foreground, for pipes or terminal issues)"
    )
    exec_opts.add_argument(
        "-i", "--interactive", action="store_true",
        help="[DEPRECATED: use --no-tmux] Run without tmux wrapper"
    )
    exec_opts.add_argument(
        "-a", "--auto-approve", action="store_true", default=True,
        help="Skip permission prompts (default: enabled)"
    )
    exec_opts.add_argument(
        "--no-auto-approve", action="store_false", dest="auto_approve",
        help="Require permission prompts for tool calls"
    )
    exec_opts.add_argument(
        "-w", "--workdir", metavar="DIR",
        help="Working directory"
    )
    exec_opts.add_argument(
        "-o", "--output", metavar="FILE",
        help="Write output to file"
    )
    exec_opts.add_argument(
        "--on-conflict", choices=["fork", "exit", "queue"], default="fork",
        help="Handle session conflicts (default: fork)"
    )
    exec_opts.add_argument(
        "--sync", action="store_true",
        help="Non-interactive mode: run prompt, print output, exit (Claude: --print, Codex: exec)"
    )

    # Agent/Task options
    agent_opts = parser.add_argument_group("Agent/Task Options")
    agent_opts.add_argument(
        "-A", "--agent", metavar="TYPE",
        help="Use agent type (librarian, dev-lead, custodian, peer-review, tester, researcher, validator)"
    )
    agent_opts.add_argument(
        "-T", "--task", metavar="FILE",
        help="Load task instructions from file"
    )
    agent_opts.add_argument(
        "--any-task", action="store_true",
        help="Claim first available task from queue"
    )
    agent_opts.add_argument(
        "--pre-prompt", metavar="TEXT",
        help="Text to prepend to bootstrap prompt"
    )
    agent_opts.add_argument(
        "--post-prompt", metavar="TEXT",
        help="Text to append to bootstrap prompt"
    )

    # Control options
    control = parser.add_argument_group("Control Options")
    control.add_argument(
        "--dry-run", action="store_true",
        help="Print bootstrap prompt without invoking binary"
    )
    control.add_argument(
        "--start-clean", action="store_true",
        help="Skip all bootstrap, suppress ~/.gemini/GEMINI.md - use only explicit --prompt"
    )
    control.add_argument(
        "--suppress-global-memory", action="store_true",
        help="Gemini: suppress ~/.gemini/GEMINI.md during session (for shard initialization)"
    )
    control.add_argument(
        "--no-tools", action="store_true",
        help="Disable all MCP tools (Gemini: passes --allowed-mcp-server-names with empty value)"
    )

    # Prompt as named argument (not positional)
    # This allows passthrough flags with values to work correctly
    # Note: -p not used as short form - conflicts with native binary flags
    parser.add_argument(
        "--prompt",
        help="Prompt text (passed to binary as positional argument)"
    )

    return parser


def parse_common_args(
    parser: argparse.ArgumentParser,
    args: list[str],
    config: CLIConfig
) -> tuple[CommonArgs, list[str]]:
    """
    Parse command line arguments to CommonArgs, passing through unknown args.

    Uses parse_known_args() to split arguments into:
    - Known args: handled by the wrapper (session, execution, agent options)
    - Unknown args: passed through to the underlying binary

    This allows users to specify binary-native flags without the wrapper
    needing to explicitly support them.

    EXECUTION MODES:
      Default: tmux (session is discoverable, attachable, orchestrator-friendly)
      --no-tmux/-i: foreground (direct subprocess, for pipes or terminal issues)
      --sync: non-interactive (process prompt, exit - for fire-and-forget/pipes)

    WRAPPER-SPECIFIC FLAGS (not passed to binary):
      -t/--tmux, -s/--session    Tmux execution control
      --no-tmux, -i              Foreground execution (no tmux)
      -w/--workdir               Working directory (wrapper does cd)
      -A/--agent                 Agent context loading
      -T/--task, --any-task      Task file handling
      --pre-prompt, --post-prompt  Prompt assembly
      -o/--output                Output file (wrapper-level)
      --on-conflict              Session conflict handling
      --dry-run                  Wrapper testing
      --sync                     Non-interactive mode

    PASSTHROUGH FLAGS (handled by wrapper AND passed to binary):
      -m/--model                 Model selection
      -a/--auto-approve          Permission handling
      -c/--continue, -r/--resume Session continuation
      -n/--named                 Named session lookup
      --fork-from                Session forking

    Args:
        parser: Configured ArgumentParser
        args: Command line arguments
        config: Platform configuration

    Returns:
        Tuple of (CommonArgs dataclass, list of unknown args to pass through)
    """
    parsed, passthrough = parser.parse_known_args(args)

    # Determine execution mode
    # Default: tmux (discoverable, attachable, orchestrator-friendly)
    # --no-tmux or -i: direct foreground (for pipes, terminal issues)
    # Note: -i is deprecated, use --no-tmux
    no_tmux = parsed.no_tmux or parsed.interactive
    if no_tmux:
        exec_mode = "interactive"  # "interactive" exec_mode = direct foreground (no tmux)
    else:
        exec_mode = "tmux"  # Default: always use tmux

    # Determine session mode
    session_mode = "new"
    if parsed.continue_session:
        session_mode = "continue"
    elif parsed.resume:
        session_mode = f"resume:{parsed.resume}"
    elif parsed.named:
        session_mode = f"named:{parsed.named}"

    # Working directory
    working_dir = config.working_dir_default
    if parsed.workdir:
        working_dir = normalize_path(parsed.workdir)
    elif parsed.agent and parsed.agent in config.agent_dirs:
        working_dir = config.agent_dirs[parsed.agent]

    # Tmux session name
    tmux_session = parsed.session or f"{config.platform}_cli_{os.getpid()}"

    # Task file - keep both normalized path and original string
    task_file = None
    task_file_orig = None
    if parsed.task:
        task_file = normalize_path(parsed.task)
        task_file_orig = parsed.task  # Keep original as given

    # Any-task directory - keep both normalized path and relative string
    any_task_dir = None
    any_task_dir_orig = None
    if parsed.any_task:
        any_task_dir = config.tasks_dir / "to_execute"
        # Build relative path like: ai_comms/{platform}_cli/tasks/to_execute/
        any_task_dir_orig = f"ai_comms/{config.platform}_cli/tasks/to_execute/"

    # Output file
    output_file = None
    if parsed.output:
        output_file = normalize_path(parsed.output)

    result = CommonArgs(
        exec_mode=exec_mode,
        session_mode=session_mode,
        working_dir=working_dir,
        auto_approve=parsed.auto_approve,
        output_file=output_file,
        tmux_session=tmux_session,
        agent_type=parsed.agent,
        task_file=task_file,
        task_file_orig=task_file_orig,
        any_task=parsed.any_task,
        any_task_dir=any_task_dir,
        any_task_dir_orig=any_task_dir_orig,
        pre_prompt=parsed.pre_prompt,
        post_prompt=parsed.post_prompt,
        on_conflict=parsed.on_conflict,
        fork_from=parsed.fork_from,
        dry_run=parsed.dry_run,
        prompt=parsed.prompt,
        model=parsed.model,
        sync=parsed.sync,
        start_clean=parsed.start_clean,
        suppress_global_memory=parsed.suppress_global_memory,
        no_tools=parsed.no_tools,
    )
    return result, passthrough


# =============================================================================
# Utility Functions
# =============================================================================

def generate_fork_session_name(base: str) -> str:
    """
    Generate a unique forked session name.

    Args:
        base: Base session name

    Returns:
        Unique session name with fork suffix
    """
    ts = int(datetime.now().timestamp())
    result = f"{base}_fork_{os.getpid()}_{ts}"
    return result


def queue_task(
    agent_type: str | None,
    prompt: str,
    tasks_dir: Path,
    platform: str
) -> str:
    """
    Queue a task for later execution.

    Args:
        agent_type: Target agent type or None for any
        prompt: Task prompt
        tasks_dir: Base tasks directory
        platform: Platform name

    Returns:
        Task filename
    """
    ts = int(datetime.now().timestamp())
    task_target = agent_type or "any"
    task_name = f"queued_{ts}_{task_target}"

    queue_dir = tasks_dir / "to_execute"
    ensure_directory(queue_dir)

    task_file = queue_dir / f"{task_name}.md"
    created = datetime.now().astimezone().isoformat()

    content = f"""---
target_worker: {task_target}
created: {created}
created_by: {platform}_cli_queue
---

# Queued Task

{prompt}
"""
    task_file.write_text(content)
    return task_name


# =============================================================================
# Base CLI Template
# =============================================================================

class BaseCLI(ABC):
    """Template for platform CLI wrappers."""

    def __init__(self, config: CLIConfig) -> None:
        """
        Initialize shared CLI resources.

        Args:
            config: Platform configuration
        """
        self.config = config
        self.logger = CLILogger(config.log_dir, config.platform)
        self.registry = SessionRegistry(config.registry_file)

        ensure_directory(config.log_dir)
        ensure_directory(config.lock_dir)

    def build_prompt(self, common_args: CommonArgs) -> str:
        """
        Build the bootstrap prompt from common arguments.

        Args:
            common_args: Parsed common arguments

        Returns:
            Complete bootstrap prompt
        """
        has_task = common_args.task_file is not None or common_args.any_task
        files = build_file_list(
            agent=common_args.agent_type,
            has_task=has_task,
            platform=self.config.platform,
            prompts_dir=self.config.prompts_dir
        )

        return build_bootstrap_prompt(
            files=files,
            task_file=common_args.task_file_orig,
            any_task_dir=common_args.any_task_dir_orig,
            pre_prompt=common_args.pre_prompt,
            post_prompt=common_args.post_prompt,
            user_prompt=common_args.prompt,
            ai_root=str(self.config.working_dir_default)
        )

    def resolve_session_mode(self, common_args: CommonArgs) -> int:
        """
        Resolve or mutate session mode before execution.

        Override in subclasses for platform-specific behavior.

        Args:
            common_args: Parsed common arguments (may be mutated)

        Returns:
            Exit code (0 to continue, non-zero to stop)
        """
        return 0

    def get_lock_name(self, common_args: CommonArgs) -> str:
        """
        Build lock name for this invocation.

        Args:
            common_args: Parsed common arguments

        Returns:
            Lock name string
        """
        return f"{common_args.agent_type or 'default'}_session"

    def on_fork_conflict(self, common_args: CommonArgs, lock_name: str) -> str:
        """
        Handle lock conflict with fork mode.

        Args:
            common_args: Parsed common arguments (may be mutated)
            lock_name: Current lock name

        Returns:
            New lock name
        """
        common_args.tmux_session = generate_fork_session_name(lock_name)
        return common_args.tmux_session

    def execution_context(self, common_args: CommonArgs):
        """
        Optional execution context around process launch.

        Override for platform-specific pre/post launch behavior.
        """
        return nullcontext()

    def run(self, common_args: CommonArgs, passthrough_args: list[str] | None = None) -> int:
        """
        Execute CLI using shared run template.

        Args:
            common_args: Parsed common arguments
            passthrough_args: Unknown args to pass through to native binary

        Returns:
            Exit code
        """
        passthrough = passthrough_args or []
        lock: SessionLock | None = None
        lock_acquired = False

        # Validate agent type
        if common_args.agent_type and common_args.agent_type not in self.config.agent_dirs:
            valid = ", ".join(self.config.agent_dirs.keys())
            print(f"Error: Unknown agent '{common_args.agent_type}'. Valid: {valid}", file=sys.stderr)
            return 1

        # Platform-specific session resolution
        resolution_exit = self.resolve_session_mode(common_args)
        if resolution_exit != 0:
            return resolution_exit

        session_mode = common_args.session_mode
        is_resuming = session_mode == "continue" or session_mode.startswith("resume:")
        skip_bootstrap = common_args.start_clean or is_resuming

        # Session lock handling
        lock_name = self.get_lock_name(common_args)
        lock = SessionLock(self.config.lock_dir, lock_name)
        if not lock.is_available():
            lock_info = lock.get_info()
            self.logger.warn(f"Session conflict for '{lock_name}': {lock_info}")

            if common_args.on_conflict == "exit":
                print(f"ERROR: Session '{lock_name}' is busy ({lock_info})", file=sys.stderr)
                return 3
            if common_args.on_conflict == "fork":
                lock_name = self.on_fork_conflict(common_args, lock_name)
                lock = SessionLock(self.config.lock_dir, lock_name)
            elif common_args.on_conflict == "queue":
                if skip_bootstrap:
                    prompt = common_args.prompt or ""
                else:
                    prompt = self.build_prompt(common_args)
                task_name = queue_task(
                    common_args.agent_type,
                    prompt,
                    self.config.tasks_dir,
                    self.config.platform,
                )
                print(f"Queued as: {task_name}")
                return 0

        try:
            lock.acquire()
            lock_acquired = True

            # Validate working directory exists
            if not common_args.working_dir.is_dir():
                print(f"Error: Working directory does not exist: {common_args.working_dir}", file=sys.stderr)
                return 1

            # Fixed behavior: always bootstrap unless --start-clean or resuming
            if skip_bootstrap:
                prompt = common_args.prompt or ""
            else:
                prompt = self.build_prompt(common_args)

            # Dry run - just print prompt
            if common_args.dry_run:
                print(prompt)
                return 0

            # Validate task file if specified (after dry-run check)
            if common_args.task_file and not common_args.task_file.is_file():
                print(f"Error: Task file does not exist: {common_args.task_file}", file=sys.stderr)
                return 1

            return self.execute(prompt, common_args, passthrough)

        except FileNotFoundError as e:
            print(f"Error: {e}", file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            return 130
        finally:
            if lock_acquired and lock:
                lock.release()

    def execute_command(self, cmd: list[str], prompt: str, common_args: CommonArgs) -> int:
        """
        Execute a prepared command with shared logging and mode handling.

        Args:
            cmd: Native command line
            prompt: Resolved prompt used for this launch
            common_args: Parsed common arguments

        Returns:
            Exit code
        """
        exit_code = 0
        log_file = self.logger.session_start(
            session_mode=common_args.session_mode,
            exec_mode=common_args.exec_mode,
            working_dir=common_args.working_dir,
            prompt=prompt,
        )

        try:
            os.chdir(common_args.working_dir)
            
            # Log the final command being executed
            cmd_str = " ".join(cmd)
            print(f"CMD: {cmd_str}", file=sys.stderr)
            
            with self.execution_context(common_args):
                if common_args.sync:
                    result = subprocess.run(
                        cmd,
                        capture_output=True,
                        text=True,
                        stdin=subprocess.DEVNULL,
                    )
                    print(result.stdout)
                    if result.stderr:
                        print(result.stderr, file=sys.stderr)
                    exit_code = result.returncode
                elif common_args.exec_mode == "tmux":
                    tmux = TmuxSession(common_args.tmux_session, common_args.working_dir)
                    tmux.create(cmd, log_file)

                    output_log = log_file.with_suffix(".output.log")
                    print(f"TMUX_SESSION={common_args.tmux_session}")
                    print(f"OUTPUT_LOG={output_log}")
                    print()
                    print("Commands:")
                    print(f"  Monitor:     tmux capture-pane -t {common_args.tmux_session} -p")
                    print(f"  Send input:  tmux send-keys -t {common_args.tmux_session} 'message' Enter")
                    print(f"  Attach:      tmux attach -t {common_args.tmux_session}")
                    print(f"  Kill:        tmux kill-session -t {common_args.tmux_session}")
                    exit_code = 0
                elif common_args.exec_mode == "interactive":
                    result = subprocess.run(cmd)
                    exit_code = result.returncode
        finally:
            self.logger.session_end(log_file, exit_code)

        return exit_code

    @abstractmethod
    def execute(self, prompt: str, common_args: CommonArgs, passthrough: list[str]) -> int:
        """Execute platform-specific command flow."""

    @abstractmethod
    def build_command(
        self,
        prompt: str,
        common_args: CommonArgs,
        passthrough_args: list[str] | None = None
    ) -> list[str]:
        """Build platform-specific native command."""
