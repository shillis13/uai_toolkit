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
- Zellij operations
- Task file parsing
- Common argument parsing
- Logging
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import uuid as _uuid
from abc import ABC, abstractmethod
from contextlib import nullcontext
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Ensure session_mgmt/ is importable (lib_session, lib_session_substrate moved there)
_SESSION_MGMT_DIR = Path(__file__).resolve().parent.parent / "session_mgmt"
if str(_SESSION_MGMT_DIR) not in sys.path:
    sys.path.insert(0, str(_SESSION_MGMT_DIR))

# Ensure the shared common_utils logging core is importable (same idiom used by
# projects_mgr.py, teams_mgr.py, trait_mgr.py, session_context_registry.py, ...).
_PY_SRC = Path.home() / "bin/all_languages/python/src"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))
from uai_toolkit.common_utils.lib_logging import configure_logging, get_logger

# External dependency
import yaml

# Shared color library
sys.path.insert(0, os.path.join(os.path.expanduser("~"), "bin", "ai"))
from uai_toolkit.common_utils.standard_colors import c, success, error, warn, info, dim, bold, heading, format_help, colors_enabled


# =============================================================================
# AI_ROOT Resolution
# =============================================================================

AI_ROOT_MAIN = Path(os.environ.get(
    "AI_ROOT_MAIN", str(Path.home() / "AI/ai_root")
))

DEVTREES_DIR = Path.home() / "AI/devTrees"


def get_ai_root() -> Path:
    """Resolve AI_ROOT dynamically.

    Priority:
      1. AI_ROOT environment variable (set by session MCP, settings.json, or caller)
      2. Default: ~/AI/ai_root

    All scripts should use this instead of hardcoding paths.
    """
    return Path(os.environ.get("AI_ROOT", str(Path.home() / "AI/ai_root")))


def resolve_ai_root(use_devtree: bool, uuid8: str) -> Path:
    """Resolve AI_ROOT based on devTree preference.

    When use_devtree=True: returns devTree path (creates dir if needed).
    When use_devtree=False: returns AI_ROOT_MAIN (ignores inherited AI_ROOT).

    Args:
        use_devtree: Whether to use an isolated devTree workspace.
        uuid8: Session uuid8 for devTree naming.

    Returns:
        Resolved AI_ROOT path.
    """
    if use_devtree:
        devtree = DEVTREES_DIR / f"AI_ROOT_{uuid8}"
        devtree.mkdir(parents=True, exist_ok=True)
        return devtree
    return AI_ROOT_MAIN


# =============================================================================
# Help Text Colorization (delegates to standard_colors)
# =============================================================================

def colorize_help(text: str) -> str:
    """Apply ANSI colors to help text. Delegates to standard_colors.format_help()."""
    return format_help(text)


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
    project_dir_default: Path
    log_dir: Path
    registry_file: Path
    agent_session_map: Path
    tasks_dir: Path
    lock_dir: Path
    prompts_dir: Path

    agent_dirs: dict[str, Path] = field(default_factory=lambda: {
        # All roles point to ai_root - both hyphenated and underscored versions
        "librarian": Path.home() / "AI/ai_root",
        "researcher": Path.home() / "AI/ai_root",
        "dev-lead": Path.home() / "AI/ai_root",
        "dev_lead": Path.home() / "AI/ai_root",
        "custodian": Path.home() / "AI/ai_root",
        "peer-review": Path.home() / "AI/ai_root",
        "peer_review": Path.home() / "AI/ai_root",
        "tester": Path.home() / "AI/ai_root",
        "validator": Path.home() / "AI/ai_root",
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
    session_mode: str  # 'new', 'resume:{id}', 'fork:{id}'
    project_dir: Path
    auto_approve: bool
    output_file: Path | None
    tmux_session: str
    display_name: str | None  # Human-readable name (-n/--name)
    agent_type: str | None  # First role (for backward compat)
    agent_roles: list[str]  # All roles (-A/--agent comma-separated)
    task_file: Path | None
    task_file_orig: str | None  # Original task file path as given
    any_task: bool
    any_task_dir: Path | None
    any_task_dir_orig: str | None  # Original any_task_dir as string
    pre_prompt: str | None
    post_prompt: str | None
    fork_from: str | None
    dry_run: bool
    prompt: str | None
    model: str | None  # Model override (platform-specific)
    sync: bool  # Non-interactive mode: Claude --print, Codex exec, Gemini positional
    start_clean: bool  # Launch with zero bootstrap - no project docs, no framework prompts
    suppress_global_memory: bool  # Suppress ~/.gemini/GEMINI.md during session (Gemini only)
    no_tools: bool  # Disable all MCP tools (Gemini: --allowed-mcp-server-names with empty value)
    use_devtree: bool  # Use isolated devTree workspace (AI_ROOT_{uuid8})
    system_instructions: str | None  # Concatenated role context_files content for system prompt injection
    system_instructions_file: Path | None  # Temp file path for platforms that need file-based injection
    cli_uuid_pregenerated: str | None  # Pre-generated CLI UUID (Claude only, for --session-id)


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

# NOTE (todo_0319): load_role_config() and get_role_context_files() were removed.
# They read the defunct prompts/roles/<role>/role.yml in the retired
# load_sequence/REF: tier format and had no live callers. Role/profile context now
# loads through the guidance MCP (knowledge_get_context), which walks the registry
# reference graph with a uniform load depth (none | direct | recursive).


def build_file_list(
    agent: str | None,
    has_task: bool,
    platform: str,
    prompts_dir: Path
) -> list[str]:
    """
    Determine which prompt files to reference in the user prompt.

    All bootstrap content (global.md, platform.md, role context_files) is now
    injected via system prompt. The user prompt only references task files.

    Args:
        agent: Role type or None
        has_task: True if -T or --any-task specified
        platform: One of 'claude', 'codex', 'gemini'
        prompts_dir: Base directory for prompt files

    Returns:
        Ordered list of relative path strings to prompt files
        (empty unless task mode is active)
    """
    base_prefix = "ai_general/prompts"
    files = []

    # Global, platform, and role context_files are ALL in system prompt now.
    # No "Read and follow" instructions needed in user prompt.

    # Tasking (if task mode) — still referenced in user prompt since it's per-invocation
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
    ai_root: str | None = None,
    identity_block: str | None = None,
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
        ai_root: AI root directory path (e.g., ~/AI/ai_root)

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

    # Session identity — prepended so it's the first thing in the conversation record
    if identity_block:
        parts.append(identity_block)

    # AI root directory - critical for file resolution
    if ai_root:
        parts.append(f"AI_ROOT: {ai_root}")

    # Pre-prompt
    if pre_prompt:
        parts.append(pre_prompt)

    # File list instruction (only if there are files to reference)
    if files:
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


def build_system_instructions(
    agent: str | None,
    prompts_dir: Path,
    ai_root: Path,
    platform: str = "claude",
) -> str | None:
    """
    Read and concatenate all bootstrap content into a single string for system prompt injection.

    Includes (in order):
    1. global.md — universal instructions
    2. platforms/{platform}.md — platform-specific behavior
    3. Role context_files from role.yml — domain docs and instructions

    This keeps the user prompt minimal (just AI_ROOT + user's actual prompt).
    Default role is cli_interactive when agent is None.

    Args:
        agent: Role type or None (defaults to cli_interactive)
        prompts_dir: Base prompts directory
        ai_root: AI root directory for resolving file paths
        platform: Platform name ('claude', 'codex', 'gemini')

    Returns:
        Concatenated file contents as string, or None if no files
    """
    parts = []

    def _read_file(rel_path: str) -> None:
        full_path = ai_root / rel_path
        if full_path.exists():
            try:
                content = full_path.read_text()
                parts.append(f"# === {rel_path} ===\n{content}")
            except Exception as e:
                parts.append(f"# === {rel_path} === (read error: {e})")
        else:
            parts.append(f"# === {rel_path} === (file not found)")

    # 1. Global instructions (always)
    _read_file("ai_general/prompts/global.md")

    # 2. Platform-specific instructions (always)
    _read_file(f"ai_general/prompts/platforms/{platform}.md")

    # 3. Role assignment
    # New architecture: roles are loaded via guidance MCP at runtime.
    # System prompt just declares which roles are assigned.
    if agent:
        # Parse comma-separated roles
        roles = [r.strip() for r in agent.split(",") if r.strip()]
    else:
        roles = ["assistant"]

    parts.append(f"# === Role Assignment ===\nYour roles: [{', '.join(roles)}]\nLoad each role's details via guidance:get_role before your first response.")

    # (Removed 2026-06-30: a legacy fallback here called get_role_context_files(),
    # which todo_0319 deleted (see NOTE above) — but the call was left behind,
    # crashing build_system_instructions for any single non-'assistant' role and
    # breaking those session launches. Roles now load via guidance:get_role.)

    return "\n\n".join(parts) if parts else None


def write_system_instructions_file(content: str, session_name: str) -> Path:
    """
    Write system instructions to a temp file for platforms that need file-based injection.

    Args:
        content: System instructions content
        session_name: Session name for unique file naming

    Returns:
        Path to the temp file
    """
    import tempfile
    # Use user-private temp dir with restricted permissions
    tmp_dir = Path(tempfile.gettempdir()) / f"cli_bootstrap_{os.getuid()}"
    tmp_dir.mkdir(mode=0o700, exist_ok=True)
    # Use mkstemp for secure creation (no race condition)
    fd, tmp_path = tempfile.mkstemp(
        prefix=f"{session_name}_",
        suffix="_instructions.md",
        dir=str(tmp_dir),
    )
    try:
        os.write(fd, content.encode("utf-8"))
    finally:
        os.close(fd)
    os.chmod(tmp_path, 0o600)
    # Clean up stale files (older than 24h) on each write
    import time
    cutoff = time.time() - 86400
    for old_file in tmp_dir.iterdir():
        if old_file.is_file() and old_file.stat().st_mtime < cutoff:
            old_file.unlink(missing_ok=True)
    return Path(tmp_path)


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

        # CLI-wrapper diagnostics flow into the UNIFIED per-session log rather than
        # a separate {platform}_wrapper.log. We use a namespaced child logger
        # (ai.cli.<platform>) that PROPAGATES to the root 'ai' handlers — i.e. the
        # per-session session.log + session.jsonl the core attaches — so these
        # records land in the one session log, tagged by component.
        #
        # configure_logging() here is idempotent and safe: if the app entrypoint
        # already configured logging, this only refreshes the level and preserves
        # the entrypoint's console/handler choices; if nothing configured (a
        # standalone/legacy launch path), it attaches the default session sinks so
        # these logs are still captured. No dedicated handler, no dedup needed.
        configure_logging()
        self._logger = get_logger(f"cli.{platform}")

    def info(self, message: str) -> None:
        """Log info level message."""
        self._logger.info(message)

    def warn(self, message: str) -> None:
        """Log warning level message."""
        self._logger.warning(message)

    def error(self, message: str) -> None:
        """Log error level message."""
        self._logger.error(message)

    def session_start(
        self,
        session_mode: str,
        exec_mode: str,
        project_dir: Path,
        prompt: str
    ) -> None:
        """Log a session-start event into the unified session log.

        Formerly wrote a separate {platform}_cli_{ts}.log transcript file, but
        nothing consumed those files. The start metadata is now a single log
        record. Returns None (kept for call-site compatibility with
        session_end, which no longer needs a file handle).
        """
        self._logger.info(
            "cli session start: mode=%s exec=%s dir=%s prompt=%s",
            session_mode, exec_mode, project_dir, (prompt or "")[:100],
        )
        return None

    def session_end(self, log_file, exit_code: int) -> None:
        """Log a session-end event. ``log_file`` is ignored (kept for
        call-site compatibility; no transcript file is written any more)."""
        self._logger.info("cli session end: exit=%s", exit_code)


# =============================================================================
# Session Registry (v2 — monolithic session_metadata.json)
# =============================================================================

# Set to False to disable v2 registry writes. v3 (segmented per-file) is primary.
# Re-enable if v3 paths have issues and you need the monolithic fallback.
V2_REGISTRY_ENABLED = False


class SessionRegistry:
    """
    Manages CLI session persistence in JSON format.

    Schema v2.0: Sessions are keyed by UUID and tracked as an instance catalog.
    Replaces the v1.0 named-session model and subsumes AgentSessionMap functionality.

    Each entry records everything known at launch time (pid, role, platform,
    zellij_session, parent_pid, project_dir, model). The platform session UUID
    is filled in later when it becomes available.

    File location: ai_general/data/unified_cli/session_metadata.json (shared by all platforms)
    """

    SCHEMA_VERSION = "2.0"
    FILE_EXT = ".json"

    def __init__(self, registry_file: Path) -> None:
        self.registry_file = registry_file
        # Migrate from .yml to .json if needed
        self._migrate_if_needed()
        self._ensure_file()

    def _migrate_if_needed(self) -> None:
        """If registry_file points to .yml and a .yml exists but no .json, migrate."""
        json_path = self.registry_file.with_suffix('.json')
        yml_path = self.registry_file.with_suffix('.yml')

        # If we're already pointing at .json, check for stale .yml
        if self.registry_file.suffix == '.json':
            if not self.registry_file.exists() and yml_path.exists():
                # Migrate .yml -> .json
                try:
                    with open(yml_path) as f:
                        data = yaml.safe_load(f) or {}
                    data["schema_version"] = self.SCHEMA_VERSION
                    with open(json_path, "w") as f:
                        json.dump(data, f, indent=2)
                    yml_path.rename(yml_path.with_suffix('.yml.bak'))
                    print(f"Migrated {yml_path} -> {json_path}", file=sys.stderr)
                except Exception as e:
                    print(f"Warning: Migration failed ({e})", file=sys.stderr)
            return

        # If pointing at .yml, switch to .json
        if self.registry_file.suffix == '.yml':
            if yml_path.exists() and not json_path.exists():
                try:
                    with open(yml_path) as f:
                        data = yaml.safe_load(f) or {}
                    data["schema_version"] = self.SCHEMA_VERSION
                    with open(json_path, "w") as f:
                        json.dump(data, f, indent=2)
                    yml_path.rename(yml_path.with_suffix('.yml.bak'))
                    print(f"Migrated {yml_path} -> {json_path}", file=sys.stderr)
                except Exception as e:
                    print(f"Warning: Migration failed ({e})", file=sys.stderr)
            self.registry_file = json_path

    def _ensure_file(self) -> None:
        """Create registry file if it doesn't exist."""
        # Ensure we're using .json extension
        if self.registry_file.suffix != '.json':
            self.registry_file = self.registry_file.with_suffix('.json')
        if self.registry_file.exists():
            return
        ensure_directory(self.registry_file.parent)
        data = {"sessions": {}, "groups": {}}
        with open(self.registry_file, "w") as f:
            json.dump(data, f, indent=2)

    def _load(self) -> dict[str, Any]:
        """Load registry data, recreating if corrupt."""
        default_data = {"sessions": {}, "groups": {}}
        result = default_data

        try:
            with open(self.registry_file) as f:
                data = json.load(f)
            if data is not None:
                result = data
        except json.JSONDecodeError as e:
            print(f"Warning: Registry file corrupt ({e}), recreating.", file=sys.stderr)
            self._ensure_file()
        except FileNotFoundError:
            self._ensure_file()

        return result

    def _save(self, data: dict[str, Any]) -> None:
        """Save registry data."""
        with open(self.registry_file, "w") as f:
            json.dump(data, f, indent=2)

    # ── v2.0 Instance Catalog API ──────────────────────────────────────

    def register_launch(
        self,
        pid: int,
        platform: str,
        project_dir: Path,
        role: str | None = None,
        zellij_session: str | None = None,
        parent_pid: int | None = None,  # DEPRECATED
        parent_zellij: str | None = None,
        parent_uuid: str | None = None,
        model: str | None = None,
        cli_session_id: str | None = None,
        **_kwargs: Any,
    ) -> str:
        """
        Record a new CLI instance launch.

        Called by {ai}_cli.py before execvp / subprocess launch.
        The platform session UUID is not yet known at this point.

        Writes in the consolidated MetadataStore / SessionMetadata schema
        (uuid-keyed) so that both CLI wrappers and the Electron app share
        one file at ai_general/data/unified_cli/session_metadata.json.

        Args:
            pid: OS process ID (os.getpid() before execvp)
            platform: Platform identifier (claude_cli, codex_cli, gemini_cli)
            project_dir: Absolute working directory
            role: Agent role if applicable (librarian, dev_lead, etc.)
            zellij_session: Zellij session name if launched in background
            parent_pid: PID of parent CLI instance (None = top-level / user)
            model: Model override if specified
            **_kwargs: Accepts (and ignores) legacy parameters for caller compat

        Returns:
            The session key (zellij name or generated UUID).
        """
        if not V2_REGISTRY_ENABLED:
            # v2 writes disabled — return key without writing to monolithic file
            return zellij_session or str(_uuid.uuid4())

        data = self._load()
        if data.get("sessions") is None:
            data["sessions"] = {}
        if data.get("groups") is None:
            data["groups"] = {}

        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        # Zellij session name IS the registry key (globally unique via uuid8 suffix).
        # zellij_session and cli_session_id are 1-to-1 paired identifiers.
        session_key = zellij_session or str(_uuid.uuid4())

        # --- Duplicate check ---
        # If this zellij session name already exists, update instead of creating
        if session_key in data["sessions"]:
            existing = data["sessions"][session_key]
            # Update mutable fields, preserve groups/pinned/exchange_count
            existing["last_activity"] = ts
            existing["agent_pid"] = pid
            if cli_session_id:
                existing["cli_session_id"] = cli_session_id
            if role:
                existing["role"] = role
            if project_dir:
                existing["project_dir"] = str(project_dir)
            if model:
                existing["model"] = model
            self._save(data)
            return session_key

        # Also check if cli_session_id already exists under a different key
        if cli_session_id:
            for existing_key, entry in data["sessions"].items():
                if entry.get("cli_session_id") == cli_session_id and existing_key != session_key:
                    # UUID already registered — update the existing entry
                    entry["last_activity"] = ts
                    entry["agent_pid"] = pid
                    entry["zellij_session"] = zellij_session
                    if role:
                        entry["role"] = role
                    self._save(data)
                    return existing_key

        # Auto-detect parent from ZELLIJ_SESSION_NAME env var.
        # The wrapper runs inside the parent's zellij session, so zellij sets this.
        # Read it BEFORE creating our own session (wrapper env isn't overwritten).
        detected_parent = os.environ.get("ZELLIJ_SESSION_NAME", "")
        parent_zellij_name = parent_zellij or detected_parent or None

        # Look up parent in registry to get their CLI UUID
        parent_cli_id: str | None = parent_uuid
        if parent_zellij_name and parent_zellij_name in data["sessions"]:
            parent_entry = data["sessions"][parent_zellij_name]
            if not parent_cli_id:
                parent_cli_id = parent_entry.get("cli_session_id")
        elif parent_zellij_name:
            # Parent name might not be the key (old format) — search by field
            for entry in data["sessions"].values():
                if entry.get("zellij_session") == parent_zellij_name:
                    if not parent_cli_id:
                        parent_cli_id = entry.get("cli_session_id")
                    break

        # Determine session type: has parent = worker
        has_parent = bool(parent_zellij_name and parent_zellij_name != session_key)
        session_type = "worker" if has_parent else "chat"

        data["sessions"][session_key] = {
            "id": session_key,
            "type": session_type,
            "display_name": zellij_session,
            "platform": platform,
            "role": role,
            "parent_zellij": parent_zellij_name if has_parent else None,
            "parent_cli_session_id": parent_cli_id if has_parent else None,
            "created_at": ts,
            "last_activity": ts,
            "groups": [],
            "pinned": False,
            "exchange_count": 0,
            "zellij_session": zellij_session,
            "cli_session_id": cli_session_id,
            "agent_pid": pid,
            "project_dir": str(project_dir) if project_dir else None,
            "model": model,
        }
        self._save(data)
        return session_key

    def update_uuid(self, pid: int, uuid: str) -> bool:
        """Fill in cli_session_id for a registered instance by PID."""
        if not V2_REGISTRY_ENABLED:
            return False
        data = self._load()
        sessions = data.get("sessions") or {}
        for entry in sessions.values():
            if entry.get("agent_pid") == pid:
                entry["cli_session_id"] = uuid
                self._save(data)
                return True
        return False

    def update_uuid_by_id(self, session_id: str, uuid: str) -> bool:
        """Set cli_session_id for a session by registry key."""
        if not V2_REGISTRY_ENABLED:
            return False
        data = self._load()
        sessions = data.get("sessions") or {}
        if session_id in sessions:
            sessions[session_id]["cli_session_id"] = uuid
            self._save(data)
            return True
        return False

    def mark_stopped(self, pid: int) -> bool:
        """
        Mark a session as stopped (remove agent_pid).

        Args:
            pid: The PID of the stopped session

        Returns:
            True if updated, False if PID not found
        """
        if not V2_REGISTRY_ENABLED:
            return False
        data = self._load()
        sessions = data.get("sessions") or {}
        for entry in sessions.values():
            if entry.get("agent_pid") == pid:
                entry.pop("agent_pid", None)
                self._save(data)
                return True
        return False

    def get_by_pid(self, pid: int) -> dict[str, Any] | None:
        """Look up session entry by agent_pid."""
        data = self._load()
        sessions = data.get("sessions") or {}
        for entry in sessions.values():
            if entry.get("agent_pid") == pid:
                return entry
        return None

    def get_by_zellij(self, zellij_session: str) -> dict[str, Any] | None:
        """Look up session entry by zellij session name."""
        data = self._load()
        sessions = data.get("sessions") or {}
        for entry in sessions.values():
            if entry.get("zellij_session") == zellij_session:
                return entry
        return None

    def get_by_uuid(self, uuid: str) -> dict[str, Any] | None:
        """Look up session entry by platform session UUID (cli_session_id)."""
        data = self._load()
        sessions = data.get("sessions") or {}
        for entry in sessions.values():
            if entry.get("cli_session_id") == uuid:
                return entry
        return None

    def get_by_name(self, name: str) -> str | None:
        """
        Look up session key by role/agent_type name.

        Adapts v1's name-keyed lookup to v2's UUID-keyed schema.
        Returns the key of the most recent session matching the given role.

        Args:
            name: Role/agent_type to look up (e.g., 'dev_lead', 'tester')

        Returns:
            Session key (UUID or zellij name) or None if not found
        """
        data = self._load()
        sessions = data.get("sessions") or {}
        candidates = [
            (key, entry) for key, entry in sessions.items()
            if entry.get("role") == name
        ]
        if not candidates:
            return None
        best = max(candidates, key=lambda pair: pair[1].get("created_at", ""))
        return best[0]

    def touch(self, name: str) -> None:
        """
        Update last_used timestamp for a session looked up by role/agent_type.

        Adapts v1's name-keyed touch to v2's UUID-keyed schema.

        Args:
            name: Role/agent_type to touch (e.g., 'dev_lead', 'tester')
        """
        key = self.get_by_name(name)
        if key:
            data = self._load()
            sessions = data.get("sessions") or {}
            if key in sessions:
                ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
                sessions[key]["last_used"] = ts
                self._save(data)

    def get_latest_by_role(self, role: str) -> dict[str, Any] | None:
        """
        Get most recent session for a given role.

        Replaces AgentSessionMap.get_last_session() behavior.
        """
        data = self._load()
        sessions = data.get("sessions") or {}
        candidates = [
            e for e in sessions.values()
            if e.get("role") == role
        ]
        if not candidates:
            return None
        return max(candidates, key=lambda e: e.get("created_at", ""))

    def list_all(self, verbose: bool = False) -> list[dict]:
        """List all registered sessions."""
        data = self._load()
        sessions = data.get("sessions") or {}
        result = []
        for key, info in sessions.items():
            entry = {"name": key, **info}
            result.append(entry)
        return result

    def list_by_status(self, status: str) -> list[dict]:
        """List sessions filtered by status (running, stopped).

        Status is inferred from the presence of agent_pid:
        - agent_pid present → "running"
        - agent_pid absent  → "stopped"
        """
        data = self._load()
        sessions = data.get("sessions") or {}
        results = []
        for entry in sessions.values():
            inferred = "running" if entry.get("agent_pid") else "stopped"
            if inferred == status:
                results.append(entry)
        return results

    def list_by_platform(self, platform: str) -> list[dict]:
        """List sessions filtered by platform."""
        data = self._load()
        sessions = data.get("sessions") or {}
        return [e for e in sessions.values() if e.get("platform") == platform]

    # v1.0 backward compat methods removed in Session Identity v3 (T3)


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
# Zellij Operations (backwards-compat wrapper — delegates to ZellijSubstrate)
# =============================================================================

# Import the substrate abstraction
from uai_toolkit.session_mgmt.lib_session_substrate import ZellijSubstrate as _ZellijSubstrate


class ZellijSession:
    """Backwards-compat wrapper around ZellijSubstrate.

    Preserves the old stateful API (session name bound at construction) while
    delegating to the new stateless substrate. Will be removed when callers
    migrate to the substrate interface directly (WP-1B).
    """

    TRANSCRIPT_DIR = Path.home() / ".zellij" / "transcripts"

    def __init__(
        self,
        session_name: str,
        project_dir: Path,
        zellij_bin: Path | None = None
    ) -> None:
        self.session_name = session_name
        self.project_dir = project_dir
        self._substrate = _ZellijSubstrate(zellij_bin=zellij_bin)

    def exists(self) -> bool:
        return self._substrate.session_exists(self.session_name)

    def kill(self) -> None:
        self._substrate.kill_session(self.session_name)

    def create(self, command: list[str], log_file: Path) -> None:
        self._substrate.create_session(
            self.session_name, command, str(self.project_dir), log_file
        )

    def dump_screen(self, output_path: Path | None = None) -> str:
        return self._substrate.dump_screen(self.session_name, output_path)

    def send_keys(self, text: str) -> None:
        self._substrate.send_keys(self.session_name, text)


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
        project_dir = Path.home() / "AI/ai_root"

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

    # Session identity
    session = parser.add_argument_group("Session Identity")
    session.add_argument(
        "-n", "--name", metavar="NAME",
        help="Display name for session (used in zellij name generation)"
    )
    session.add_argument(
        "--session-id", metavar="UUID",
        help="Explicit CLI UUID (Claude only; auto-generated if omitted)"
    )

    # Session lifecycle
    lifecycle = parser.add_argument_group("Session Lifecycle")
    lifecycle.add_argument(
        "-r", "--resume", metavar="ID",
        help="Resume session by zellij name or CLI UUID"
    )
    lifecycle.add_argument(
        "-f", "--fork-from", metavar="ID",
        help="Fork from parent session (zellij name or CLI UUID)"
    )

    # Execution options
    exec_opts = parser.add_argument_group("Execution Options")
    exec_opts.add_argument(
        "-m", "--model", metavar="MODEL",
        help="Model to use (platform-specific)"
    )
    exec_opts.add_argument(
        "-t", "--tmux", action="store_true",
        help="Run in Zellij session (default behavior, flag optional)"
    )
    exec_opts.add_argument(
        "-s", "--session", metavar="NAME",
        help="Zellij session name"
    )
    exec_opts.add_argument(
        "--no-tmux", action="store_true",
        help="Run without Zellij wrapper (direct foreground, for pipes or terminal issues)"
    )
    # Keep -i as hidden alias for --no-tmux to prevent it leaking to native
    # binaries where it may have different meaning (e.g., codex -i = --image)
    exec_opts.add_argument(
        "-i", action="store_true", dest="no_tmux",
        help=argparse.SUPPRESS
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
        "--targetDir", metavar="DIR",
        help="Working/project directory (where CLAUDE.md lives)"
    )
    exec_opts.add_argument(
        "-o", "--output", metavar="FILE",
        help="Write output to file"
    )
    exec_opts.add_argument(
        "--oneshot", "--sync", action="store_true", dest="sync",
        help="Non-interactive: run prompt, print output, exit (no session persistence)"
    )

    # Agent/Task options
    agent_opts = parser.add_argument_group("Agent/Task Options")
    agent_opts.add_argument(
        "-A", "--agent", metavar="ROLE[,ROLE]",
        help="Agent roles, comma-separated (librarian, dev-lead, custodian, peer-review, tester, researcher, validator)"
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
    control.add_argument(
        "--use-devtree", action="store_true", default=False,
        help="Run in isolated devTree workspace (AI_ROOT_{uuid8}). Default: use main repo."
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
      Default: Zellij (session is discoverable, attachable, orchestrator-friendly)
      --no-tmux/-i: foreground (direct subprocess, for pipes or terminal issues)
      --sync: non-interactive (process prompt, exit - for fire-and-forget/pipes)

    WRAPPER-SPECIFIC FLAGS (not passed to binary):
      -t/--tmux, -s/--session    Zellij execution control
      --no-tmux, -i              Foreground execution (no Zellij)
      --targetDir DIR            Working/project directory
      -A/--agent                 Agent roles (comma-separated)
      -n/--name                  Display name for session
      -T/--task, --any-task      Task file handling
      --pre-prompt, --post-prompt  Prompt assembly
      -o/--output                Output file (wrapper-level)
      --dry-run                  Wrapper testing
      --sync                     Non-interactive mode

    PASSTHROUGH FLAGS (handled by wrapper AND passed to binary):
      -m/--model                 Model selection
      -a/--auto-approve          Permission handling
      -r/--resume                Session continuation
      -f/--fork-from             Session forking

    Args:
        parser: Configured ArgumentParser
        args: Command line arguments
        config: Platform configuration

    Returns:
        Tuple of (CommonArgs dataclass, list of unknown args to pass through)
    """
    parsed, passthrough = parser.parse_known_args(args)

    # Determine execution mode
    # Default: Zellij (discoverable, attachable, orchestrator-friendly)
    # --no-tmux: direct foreground (for pipes, terminal issues)
    if parsed.no_tmux:
        exec_mode = "interactive"  # direct foreground (no Zellij)
    else:
        exec_mode = "tmux"  # Default: always use Zellij (exec_mode name kept for compat)

    # Determine session mode
    session_mode = "new"
    if parsed.resume:
        session_mode = f"resume:{parsed.resume}"
    elif parsed.fork_from:
        session_mode = f"fork:{parsed.fork_from}"

    # Parse agent roles (comma-separated)
    agent_roles: list[str] = []
    agent_type = parsed.agent
    if parsed.agent:
        agent_roles = [r.strip() for r in parsed.agent.split(",") if r.strip()]
        agent_type = agent_roles[0] if agent_roles else None

    # Working directory
    project_dir = config.project_dir_default
    if parsed.targetDir:
        project_dir = normalize_path(parsed.targetDir)
    elif agent_type and agent_type in config.agent_dirs:
        project_dir = config.agent_dirs[agent_type]

    # Display name from -n/--name
    display_name = getattr(parsed, "name", None)

    # CLI UUID: pre-generate for Claude (uuid8 correlates with zellij name).
    # For Codex/Gemini: random uuid8 (their CLI UUID is discovered later).
    if config.platform == "claude_cli":
        _cli_uuid = getattr(parsed, "session_id", None) or str(_uuid.uuid4())
        _uid8 = _cli_uuid.replace("-", "")[:8]
    else:
        _cli_uuid = None
        _uid8 = _uuid.uuid4().hex[:8]

    # Resolve AI_ROOT: --use-devtree creates isolated workspace, otherwise use main repo.
    # This prevents accidental inheritance of a parent's devTree AI_ROOT.
    _use_devtree = parsed.use_devtree
    _resolved_ai_root = resolve_ai_root(use_devtree=_use_devtree, uuid8=_uid8)
    os.environ["AI_ROOT"] = str(_resolved_ai_root)

    # Zellij session name: {display}_{uuid8}
    if parsed.session:
        tmux_session = parsed.session  # Explicit -s overrides generation
    elif display_name:
        tmux_session = f"{display_name}_{_uid8}"
    else:
        _role = agent_type or "chat"
        tmux_session = f"{config.platform}_{_role}_{_uid8}"

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
        project_dir=project_dir,
        auto_approve=parsed.auto_approve,
        output_file=output_file,
        tmux_session=tmux_session,
        display_name=display_name,
        agent_type=agent_type,
        agent_roles=agent_roles,
        task_file=task_file,
        task_file_orig=task_file_orig,
        any_task=parsed.any_task,
        any_task_dir=any_task_dir,
        any_task_dir_orig=any_task_dir_orig,
        pre_prompt=parsed.pre_prompt,
        post_prompt=parsed.post_prompt,
        fork_from=parsed.fork_from,
        dry_run=parsed.dry_run,
        prompt=parsed.prompt,
        model=parsed.model,
        sync=parsed.sync,
        start_clean=parsed.start_clean,
        suppress_global_memory=parsed.suppress_global_memory,
        no_tools=parsed.no_tools,
        use_devtree=_use_devtree,
        system_instructions=None,  # Populated later by build_prompt()
        system_instructions_file=None,  # Populated later by build_prompt()
        cli_uuid_pregenerated=_cli_uuid,  # Claude only — correlated with zellij name uuid8
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

    def pre_build_prompt(self, common_args: CommonArgs) -> None:
        """Hook for platform-specific setup before prompt assembly.

        Override to set common_args fields that affect prompt/system instructions.
        Called before build_prompt() and build_command().
        Default: no-op.
        """
        pass

    def build_prompt(self, common_args: CommonArgs) -> str:
        """
        Build the bootstrap prompt and system instructions from common arguments.

        User prompt contains: AI_ROOT + task clause + user text (minimal).
        System instructions contain: global.md + platform.md + role context_files
        (injected via platform mechanism: --append-system-prompt, model_instructions_file, GEMINI_SYSTEM_MD).

        Also populates common_args.system_instructions and system_instructions_file.

        Args:
            common_args: Parsed common arguments (mutated: system_instructions set)

        Returns:
            Complete bootstrap prompt (user-facing portion only)
        """
        has_task = common_args.task_file is not None or common_args.any_task
        files = build_file_list(
            agent=common_args.agent_type,
            has_task=has_task,
            platform=self.config.platform,
            prompts_dir=self.config.prompts_dir
        )

        # Build system instructions (global.md + platform.md + role context_files)
        sys_content = build_system_instructions(
            agent=common_args.agent_type,
            prompts_dir=self.config.prompts_dir,
            ai_root=self.config.project_dir_default,
            platform=self.config.platform,
        )
        # Build session identity block (all platforms).
        # Goes into BOTH system prompt and first user prompt.
        identity_lines = []
        if common_args.tmux_session:
            identity_lines.append(f"Zellij session: {common_args.tmux_session}")
        cli_uuid = getattr(common_args, 'cli_session_id', None)
        if cli_uuid:
            identity_lines.append(f"CLI session ID: {cli_uuid}")
        # Parent auto-detected from ZELLIJ_SESSION_NAME env
        _parent_zellij = os.environ.get("ZELLIJ_SESSION_NAME", "")
        if _parent_zellij and _parent_zellij != common_args.tmux_session:
            identity_lines.append(f"Parent zellij: {_parent_zellij}")
        if getattr(common_args, 'fork_from', None):
            identity_lines.append("Forked from parent session (shares conversation history).")

        if identity_lines:
            identity_block = "<<<SESSION_IDENTITY>>> " + " | ".join(identity_lines) + " <<<END SESSION_IDENTITY>>>"
        else:
            identity_block = None

        # Append identity to system instructions
        if identity_block:
            sys_content = (sys_content + "\n\n" + identity_block) if sys_content else identity_block

        common_args.system_instructions = sys_content

        # Write to temp file for platforms that need file-based injection (Codex, Gemini)
        if sys_content:
            common_args.system_instructions_file = write_system_instructions_file(
                sys_content, common_args.tmux_session
            )
        else:
            common_args.system_instructions_file = None

        # Identity also prepended to first user prompt (appears in conversation record)
        return build_bootstrap_prompt(
            files=files,
            task_file=common_args.task_file_orig,
            any_task_dir=common_args.any_task_dir_orig,
            pre_prompt=common_args.pre_prompt,
            post_prompt=common_args.post_prompt,
            user_prompt=common_args.prompt,
            ai_root=os.environ.get("AI_ROOT", str(self.config.project_dir_default)),
            identity_block=identity_block,
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
        is_resuming = session_mode.startswith("resume:")
        skip_bootstrap = common_args.start_clean or is_resuming

        # Session lock handling — error if locked
        lock_name = self.get_lock_name(common_args)
        lock = SessionLock(self.config.lock_dir, lock_name)
        if not lock.is_available():
            lock_info = lock.get_info()
            print(f"Error: Session '{lock_name}' is locked: {lock_info}", file=sys.stderr)
            print(f"  Lock file: {self.config.lock_dir / (lock_name + '.lock')}", file=sys.stderr)
            print(f"  Remove the lock file if the owning process is dead.", file=sys.stderr)
            return 1

        try:
            lock.acquire()
            lock_acquired = True

            # Validate working directory exists
            if not common_args.project_dir.is_dir():
                print(f"Error: Working directory does not exist: {common_args.project_dir}", file=sys.stderr)
                return 1

            # Hook for platform-specific pre-prompt setup (e.g., Claude UUID assignment)
            self.pre_build_prompt(common_args)

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
            project_dir=common_args.project_dir,
            prompt=prompt,
        )

        # Register launch in both v2 (monolithic) and v3 (per-file) registries
        zellij_name = common_args.tmux_session if common_args.exec_mode == "tmux" else None
        cli_session_id = getattr(common_args, 'cli_session_id', None) or common_args.cli_uuid_pregenerated

        # v2: monolithic session_metadata.json (backward compat)
        registry_id = self.registry.register_launch(
            pid=os.getpid(),
            platform=self.config.platform,
            project_dir=common_args.project_dir,
            role=common_args.agent_type,
            zellij_session=zellij_name,
            model=common_args.model,
            cli_session_id=cli_session_id,
        )
        self._registry_id = registry_id

        # v3: segmented registry file + per-session dir (source of truth)
        if zellij_name:
            from uai_toolkit.session_mgmt.lib_session import write_registry, create_session_dir

            # Auto-detect parent from ZELLIJ_SESSION_NAME env
            parent_zellij = os.environ.get("ZELLIJ_SESSION_NAME") or None
            if parent_zellij == zellij_name:
                parent_zellij = None  # Don't self-parent

            ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

            # Registry = identity index (derived, rebuildable)
            write_registry(zellij_name, {
                "zellij_session": zellij_name,
                "cli_session_id": cli_session_id,
                "platform": self.config.platform,
                "parent_zellij": parent_zellij,
                "parent_cli_session_id": None,
                "created_at": ts,
            })

            # Session dir = source of truth (sessionInfo.json + PID file)
            create_session_dir(
                platform=self.config.platform,
                zellij_name=zellij_name,
                cli_session_id=cli_session_id,
                parent_zellij=parent_zellij,
                display_name=common_args.display_name or zellij_name,
                working_dir=str(common_args.project_dir),
                model=common_args.model,
                roles=common_args.agent_roles or ([common_args.agent_type] if common_args.agent_type else []),
                pid=os.getpid(),
                created_at=ts,
            )

        # Set minimal env vars for process identification (NOT for identity passing)
        os.environ["CLI_SESSION_PID"] = str(os.getpid())
        if common_args.agent_type:
            os.environ["CLI_AGENT_ROLE"] = common_args.agent_type
        # NOTE: Do NOT set ZELLIJ_SESSION_NAME here — ZellijSession.create() checks it
        # to detect if we're already inside the target session. Setting it prematurely
        # causes create() to execvp instead of creating a new session.

        try:
            os.chdir(common_args.project_dir)
            
            # Log the final command being executed (truncate system prompt to avoid log spam)
            cmd_display = []
            skip_next = False
            for i, arg in enumerate(cmd):
                if skip_next:
                    skip_next = False
                    continue
                if arg == "--append-system-prompt" and i + 1 < len(cmd):
                    cmd_display.append(f"--append-system-prompt [<{len(cmd[i+1])} chars>]")
                    skip_next = True
                else:
                    cmd_display.append(arg)
            print(f"CMD: {' '.join(cmd_display)}", file=sys.stderr)
            
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
                    session = ZellijSession(common_args.tmux_session, common_args.project_dir)
                    session.create(cmd, log_file)

                    assigned_uuid = getattr(common_args, 'cli_session_id', None)
                    print(f"ZELLIJ_SESSION={common_args.tmux_session}")
                    if assigned_uuid:
                        print(f"CLI_SESSION_UUID={assigned_uuid}")
                    print()
                    print("Commands:")
                    print(f"  Screen dump: zellij --session {common_args.tmux_session} action dump-screen /tmp/dump.txt")
                    print(f"  Send input:  zellij --session {common_args.tmux_session} action write-chars 'message' && zellij --session {common_args.tmux_session} action write 13")
                    print(f"  Attach:      zellij attach {common_args.tmux_session}")
                    print(f"  Kill:        zellij delete-session {common_args.tmux_session} --force")
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
