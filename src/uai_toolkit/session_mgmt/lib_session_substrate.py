#!/usr/bin/env python3
"""Session substrate abstraction for terminal multiplexer operations.

Provides SessionSubstrate ABC and implementations for tmux, zellij, and no-mux modes.
Used by CLI wrappers and the Electron app (via subprocess CLI interface).

See: architecture/session_identity_v4.2.md Section 9
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


# Common install paths that GUI-launched macOS apps frequently omit from PATH.
_FALLBACK_BINARY_DIRS = (
    "/opt/homebrew/bin",
    "/opt/homebrew/sbin",
    "/usr/local/bin",
    "/usr/local/sbin",
    str(Path.home() / ".local" / "bin"),
    str(Path.home() / ".npm-global" / "bin"),
)

_AUTO_TMUX_SERVER = object()
sys.path.insert(0, os.environ.get("AI_SCRIPTS") or str(Path(__file__).resolve().parents[1]))
from uai_toolkit.paths import AI_ROOT  # noqa: E402
_DEFAULT_AI_ROOT = AI_ROOT


# =============================================================================
# Exceptions
# =============================================================================

class SubstrateError(RuntimeError):
    """Error from a substrate operation (multiplexer command failure, etc.)."""

    def __init__(self, message: str, code: str = "SUBSTRATE_ERROR"):
        super().__init__(message)
        self.code = code


# =============================================================================
# Data Structures
# =============================================================================

@dataclass(frozen=True)
class SessionInfo:
    """Information about a terminal multiplexer session."""
    name: str
    created: datetime | None = None  # None if multiplexer doesn't report it
    attached: bool = False
    running: bool = True


@dataclass(frozen=True)
class LaunchResult:
    """Result from create_session."""
    session_name: str
    pid: int | None = None  # PID of the launched CLI process (if discoverable)


# =============================================================================
# Abstract Base Class
# =============================================================================

class SessionSubstrate(ABC):
    """Abstract interface for terminal multiplexer operations.

    Implementations are stateless (one instance manages all sessions) except
    NoneSubstrate which holds process handles.
    """

    @property
    @abstractmethod
    def substrate_name(self) -> str:
        """Short name for this substrate type (e.g., 'tmux', 'zellij', 'none')."""

    @abstractmethod
    def create_session(self, name: str, command: list[str], cwd: str,
                       log_file: Path | None = None) -> LaunchResult:
        """Create a new named session running the given command.

        Kills any existing session with the same name first.
        Returns LaunchResult with the actual session name and the PID
        of the CLI process launched inside the session.
        """

    @abstractmethod
    def session_exists(self, name: str) -> bool:
        """Check if a session with this name exists (running or stopped)."""

    @abstractmethod
    def session_is_running(self, name: str) -> bool:
        """Check if a session is actively running."""

    @abstractmethod
    def kill_session(self, name: str) -> None:
        """Terminate a session. No-op if session doesn't exist."""

    @abstractmethod
    def rename_session(self, old_name: str, new_name: str) -> None:
        """Rename a terminal session."""

    @abstractmethod
    def list_sessions(self) -> list[SessionInfo]:
        """List all sessions with name, status, creation time."""

    @abstractmethod
    def send_keys(self, name: str, keys: str) -> None:
        """Send keystrokes to a session. Appends Enter after the text.

        Note: Enter delivery varies by substrate. TmuxSubstrate sends Enter
        atomically with the text. ZellijSubstrate sends Enter as a separate
        subprocess call (timing gap exists between text and Enter). Both are
        acceptable for current use cases.
        """

    def send_key_names(self, name, keys) -> None:
        """Send true NAMED key-presses (e.g. 'Up','Down','Escape','Tab','Enter').

        For driving interactive TUIs (e.g. /rewind), where a literal text paste
        cannot operate the picker. Concrete only on substrates that support it
        (tmux); others raise so the caller gets a clear, honest error.
        """
        raise NotImplementedError(
            f"send_key_names is not implemented for the "
            f"{getattr(self, 'substrate_name', type(self).__name__)} substrate")

    @abstractmethod
    def dump_screen(self, name: str, path: Path | None = None, plain_text: bool = True) -> str:
        """Capture current screen content. Optionally write to path.

        Args:
            plain_text: If True (default), strip escape sequences and return plain text.
                        If False, preserve terminal formatting (colors, bold, etc.).
        """

    @abstractmethod
    def get_current_session_name(self) -> str | None:
        """Get the terminal session name of the environment we're running in.

        Returns None if not running inside a session managed by this substrate.
        """

    @abstractmethod
    def write_chars(self, name: str, text: str) -> None:
        """Write characters to a session WITHOUT pressing Enter.

        Unlike send_keys, this only types the text — no newline or Enter
        is appended. Useful for staging text before an explicit submit.
        """

    @abstractmethod
    def attach(self, name: str) -> None:
        """Attach to a session (for interactive use). Blocks until detached."""

    def attach_pty(self, name: str, socket_dir: str = "/tmp/uai_pty") -> dict:
        """Attach to a session via a unix socket bridge for non-interactive clients.

        Returns {"socket_path": str, "pid": int} — the client connects to the
        unix socket for bidirectional PTY I/O. The substrate owns the multiplexer
        process; the client just reads/writes the stream.

        Override in subclasses. Default raises NotImplementedError.
        """
        raise NotImplementedError(
            f"{self.__class__.__name__} does not support attach_pty"
        )


# =============================================================================
# Helpers
# =============================================================================

def _find_binary(name: str) -> Path | None:
    """Find a binary on PATH or in common fallback install locations.

    Electron / GUI-launched processes on macOS often inherit a reduced PATH that
    excludes Homebrew directories such as /opt/homebrew/bin. The session
    wrappers already compensate for this when resolving Claude/Codex/Gemini
    binaries; substrate binaries need the same treatment so resume/fork flows
    launched from the app can still find tmux/zellij.
    """
    result = shutil.which(name)
    if result:
        return Path(result)

    for raw_dir in _FALLBACK_BINARY_DIRS:
        candidate = Path(raw_dir) / name
        if candidate.exists() and candidate.is_file() and os.access(candidate, os.X_OK):
            return candidate
    return None


def sanitize_tmux_server_name(server_name: str | None) -> str | None:
    """Normalize a tmux server name to a tmux-safe identifier."""
    if server_name is None:
        return None
    value = str(server_name).strip()
    if not value:
        return None
    sanitized = re.sub(r"[^A-Za-z0-9_.-]+", "_", value)
    sanitized = sanitized.strip("._-")
    return sanitized or None


def sanitize_substrate_context(context_name: str | None) -> str | None:
    """Generic alias for the substrate runtime context identifier."""
    return sanitize_tmux_server_name(context_name)


def derive_tmux_server_name(ai_root: str | Path | None = None) -> str:
    """Derive tmux server name from the current AI_ROOT context basename."""
    raw_root = ai_root or os.environ.get("AI_ROOT") or _DEFAULT_AI_ROOT
    base = Path(str(raw_root)).resolve().name or _DEFAULT_AI_ROOT.name
    return sanitize_tmux_server_name(base) or _DEFAULT_AI_ROOT.name


def derive_substrate_context_name(ai_root: str | Path | None = None) -> str:
    """Generic alias for the substrate runtime context identifier."""
    return derive_tmux_server_name(ai_root)


def resolve_tmux_server_name(
    server_name: str | None | object = _AUTO_TMUX_SERVER,
    *,
    ai_root: str | Path | None = None,
    config_value: str | None = None,
) -> str | None:
    """Resolve tmux server name from explicit value, env, config, or AI_ROOT.

    Passing server_name=None means legacy/default tmux server (no -L flag).
    Passing the internal sentinel means auto-resolve from env/config/AI_ROOT.
    """
    if server_name is None:
        return None
    if server_name is not _AUTO_TMUX_SERVER:
        return sanitize_tmux_server_name(str(server_name))

    substrate_ctx = os.environ.get("AI_SUBSTRATE_CONTEXT", "").strip()
    if substrate_ctx:
        return sanitize_tmux_server_name(substrate_ctx)

    tmux_server_env = os.environ.get("AI_TMUX_SERVER", "").strip()
    if tmux_server_env:
        return sanitize_tmux_server_name(tmux_server_env)

    if config_value:
        return sanitize_tmux_server_name(config_value)

    # No explicit server configured — use legacy default tmux server.
    # To enable isolation, set AI_TMUX_SERVER env var or config.
    return None


def resolve_substrate_context(
    context_name: str | None | object = _AUTO_TMUX_SERVER,
    *,
    ai_root: str | Path | None = None,
    config_value: str | None = None,
) -> str | None:
    """Generic alias for runtime substrate context resolution."""
    return resolve_tmux_server_name(
        context_name,
        ai_root=ai_root,
        config_value=config_value,
    )


def build_tmux_command(
    args: list[str],
    *,
    tmux_bin: Path | str | None = None,
    server_name: str | None | object = _AUTO_TMUX_SERVER,
) -> list[str]:
    """Build a tmux command, prepending -L when targeting an isolated server."""
    binary = str(tmux_bin) if tmux_bin is not None else str(_require_binary("tmux"))
    cmd = [binary]
    resolved_server = resolve_tmux_server_name(server_name)
    if resolved_server:
        cmd.extend(["-L", resolved_server])
    cmd.extend(args)
    return cmd




def _write_launch_script(name: str, command: list[str], cwd: str) -> Path:
    """Write a short shell launcher for long CLI commands.

    DEPRECATED: No longer used. tmux create_session now passes the command
    directly to `tmux new-session` as a subprocess argument, avoiding send-keys
    entirely. Retained temporarily for reference; safe to delete.
    """
    import shlex

    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:80] or "session"
    script_dir = Path(tempfile.gettempdir()) / "unified_cli_launchers"
    script_dir.mkdir(mode=0o700, exist_ok=True)
    script_path = script_dir / f"{safe_name}_{os.getpid()}.sh"

    cmd_str = " ".join(shlex.quote(str(arg)) for arg in command)
    env_exports = []
    for key in (
        "AI_TRACKING_ID",
        "AI_CLI_SESSION_ID",
        "AI_SESSION_DIR",
        "AI_SESSION_PLATFORM",
        "AI_PROJECT_DIR",
        "AI_SUBSTRATE_CONTEXT",
        "AI_TMUX_SERVER",
    ):
        if key in os.environ:
            env_exports.append(f"export {key}={shlex.quote(os.environ.get(key, ''))}")

    script_parts = [
        "#!/usr/bin/env bash",
        "export PATH=\"$PATH\"",
        "export NODE_OPTIONS=\"--max-old-space-size=8192\"",
        *env_exports,
        f"cd {shlex.quote(cwd)} || exit 1",
        cmd_str,
        "status=$?",
        "sleep 30",
        "exit $status",
        "",
    ]
    script = "\n".join(script_parts)
    script_path.write_text(script)
    script_path.chmod(0o700)
    return script_path

def _require_binary(name: str) -> Path:
    """Find a required binary, raising error if not found."""
    result = _find_binary(name)
    if result is None:
        raise FileNotFoundError(
            f"Required binary '{name}' not found in PATH or common fallback locations"
        )
    return result


def _validate_session_name(name: str) -> None:
    """Validate session name (alphanumeric, hyphen, underscore, dot)."""
    if not name or not all(c.isalnum() or c in '-_.' for c in name):
        raise SubstrateError(
            f"Invalid session name '{name}': must be non-empty and contain "
            "only alphanumeric, hyphen, underscore, or dot characters",
            code="INVALID_ARGS",
        )


def _run_cmd(cmd: list[str], check: bool = True, **kwargs) -> subprocess.CompletedProcess:
    """Run a subprocess command with standard error handling."""
    result = subprocess.run(cmd, capture_output=True, text=True, **kwargs)
    if check and result.returncode != 0:
        stderr = result.stderr.strip()
        raise SubstrateError(
            f"Command failed (exit {result.returncode}): {' '.join(cmd)}"
            + (f"\n{stderr}" if stderr else "")
        )
    return result


# =============================================================================
# TmuxSubstrate
# =============================================================================

class TmuxSubstrate(SessionSubstrate):
    """Session substrate using tmux."""

    def __init__(
        self,
        tmux_bin: Path | None = None,
        server_name: str | None | object = _AUTO_TMUX_SERVER,
    ):
        if tmux_bin is None:
            self._bin = _require_binary("tmux")
        else:
            self._bin = tmux_bin
        self._server_name = resolve_tmux_server_name(server_name)

    @property
    def substrate_name(self) -> str:
        return "tmux"

    @property
    def server_name(self) -> str | None:
        return self._server_name

    def __repr__(self) -> str:
        return f"TmuxSubstrate(server_name={self._server_name!r})"

    def _tmux_cmd(self, *args: str) -> list[str]:
        return build_tmux_command(list(args), tmux_bin=self._bin, server_name=self._server_name)

    def create_session(self, name: str, command: list[str], cwd: str,
                       log_file: Path | None = None) -> LaunchResult:
        _validate_session_name(name)

        # Kill existing session with same name
        if self.session_exists(name):
            self.kill_session(name)

        # Build the shell command string.
        # Includes env setup and a post-exit sleep so the tmux session stays
        # visible briefly after the CLI exits (app can still read its state).
        import shlex
        cmd_str = " ".join(shlex.quote(str(arg)) for arg in command)

        env_exports = []
        for key in (
            "AI_TRACKING_ID", "AI_CLI_SESSION_ID", "AI_SESSION_DIR",
            "AI_SESSION_PLATFORM", "AI_PROJECT_DIR",
            "AI_SUBSTRATE_CONTEXT", "AI_TMUX_SERVER",
        ):
            if key in os.environ:
                env_exports.append(f"export {key}={shlex.quote(os.environ[key])}")
        if "AI_SUBSTRATE_CONTEXT" in os.environ and "AI_TMUX_SERVER" not in os.environ:
            env_exports.append(
                f"export AI_TMUX_SERVER={shlex.quote(os.environ['AI_SUBSTRATE_CONTEXT'])}"
            )

        env_block = "; ".join(env_exports) + "; " if env_exports else ""
        shell_cmd = (
            f"export NODE_OPTIONS='--max-old-space-size=8192'; "
            f"{env_block}"
            f"{cmd_str}; "
            f"sleep 30"
        )

        # Create detached session with the command directly.
        # tmux new-session accepts the command as trailing args -- no send-keys needed.
        # This avoids all send-keys length limits and typing semantics issues.
        _run_cmd(self._tmux_cmd(
            "new-session", "-d", "-s", name,
            "-c", cwd,
            "-x", "200", "-y", "50",
            "/bin/bash", "-c", shell_cmd,
        ))
        # Mouse ON for scroll support (tmux owns the alternate screen buffer).
        _run_cmd(self._tmux_cmd("set-option", "-t", name, "mouse", "on"))

        # Status bar OFF. tmux's default green status bar is pure redundant chrome for
        # a UAI-managed session (the app tab + the CLI's own statusline already show
        # session/window/time), and its default status-right surfaces the pane TITLE —
        # which the CLI sets to its live activity ("…thinking with high effort"), so the
        # bar shows a leaked verb-line string and, when it bleeds into scrollback, the
        # Memorex overlay renders it as a green content block. Off eliminates that whole
        # class of weirdness and reclaims a content row.
        _run_cmd(self._tmux_cmd("set-option", "-t", name, "status", "off"))

        # Disable assume-paste-time: tmux wraps rapid input in bracketed paste
        # sequences when chars arrive within this threshold (default 1ms).
        # send-keys -l chunks trigger this, causing Claude Code to show
        # "{Pasted text #N}" even for typed delivery. Setting to 0 disables.
        _run_cmd(self._tmux_cmd("set-option", "-t", name, "assume-paste-time", "0"))

        # Wheel scroll: copy-mode -e auto-exits when user scrolls back to bottom.
        _run_cmd(self._tmux_cmd("bind-key", "-n", "WheelUpPane",
                  "if-shell", "-Ft=", "#{mouse_any_flag}",
                  "send-keys -M",
                  "if-shell -Ft= '#{pane_in_mode}' 'send-keys -M' 'copy-mode -e'"))

        # Click in copy-mode: select-pane only (stay in copy-mode, don't scroll
        # to bottom). User scrolls to bottom to auto-exit via -e flag.
        _run_cmd(self._tmux_cmd("bind-key", "-T", "copy-mode", "MouseDown1Pane",
                  "select-pane"))
        _run_cmd(self._tmux_cmd("bind-key", "-T", "copy-mode-vi", "MouseDown1Pane",
                  "select-pane"))

        # Disable mouse drag/drag-end in copy-mode — no tmux text selection.
        # Text selection is handled by xterm.js + Cmd+C in the Electron app.
        _run_cmd(self._tmux_cmd("unbind-key", "-T", "copy-mode", "MouseDrag1Pane"))
        _run_cmd(self._tmux_cmd("unbind-key", "-T", "copy-mode-vi", "MouseDrag1Pane"))
        _run_cmd(self._tmux_cmd("unbind-key", "-T", "copy-mode", "MouseDragEnd1Pane"))
        _run_cmd(self._tmux_cmd("unbind-key", "-T", "copy-mode-vi", "MouseDragEnd1Pane"))

        # Get PID of the process running in the session
        import time
        time.sleep(1)  # Brief wait for process to start
        pid = self._get_session_pid(name)

        return LaunchResult(session_name=name, pid=pid)

    def _get_session_pid(self, name: str) -> int | None:
        """Get the PID of the foreground process in a tmux session."""
        result = subprocess.run(
            self._tmux_cmd("list-panes", "-t", name, "-F", "#{pane_pid}"),
            capture_output=True, text=True,
        )
        if result.returncode == 0 and result.stdout.strip():
            try:
                return int(result.stdout.strip().splitlines()[0])
            except ValueError:
                pass
        return None

    def session_exists(self, name: str) -> bool:
        result = subprocess.run(
            self._tmux_cmd("has-session", "-t", name),
            capture_output=True, text=True,
        )
        return result.returncode == 0

    def session_is_running(self, name: str) -> bool:
        # tmux sessions persist until killed; existence implies running
        return self.session_exists(name)

    def kill_session(self, name: str) -> None:
        if not self.session_exists(name):
            raise SubstrateError(
                f"Session '{name}' does not exist",
                code="SESSION_NOT_FOUND",
            )
        result = subprocess.run(
            self._tmux_cmd("kill-session", "-t", name),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise SubstrateError(
                f"Failed to kill session '{name}': "
                + (result.stderr.strip() or f"exit {result.returncode}"),
                code="KILL_FAILED",
            )

    def rename_session(self, old_name: str, new_name: str) -> None:
        result = subprocess.run(
            self._tmux_cmd("rename-session", "-t", old_name, new_name),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise SubstrateError(
                f"Failed to rename session '{old_name}' to '{new_name}': "
                + (result.stderr.strip() or f"exit {result.returncode}"),
                code="RENAME_FAILED",
            )

    def list_sessions(self) -> list[SessionInfo]:
        result = subprocess.run(
            self._tmux_cmd("list-sessions", "-F",
             "#{session_name}|#{session_created}|#{session_attached}"),
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return []  # No server running = no sessions

        sessions = []
        for line in result.stdout.strip().splitlines():
            parts = line.split("|", 2)
            if len(parts) < 3:
                continue
            name, created_ts, attached = parts
            try:
                created = datetime.fromtimestamp(int(created_ts), tz=timezone.utc)
            except (ValueError, OSError):
                created = None
            sessions.append(SessionInfo(
                name=name,
                created=created,
                attached=(attached == "1"),
                running=True,
            ))
        return sessions

    def send_keys(self, name: str, keys: str) -> None:
        if not self.session_exists(name):
            raise SubstrateError(
                f"Session '{name}' does not exist",
                code="SESSION_NOT_FOUND",
            )
        if keys:
            self.write_chars(name, keys)
            # Keep submit separate from paste. Long multi-line prompts can be
            # staged successfully but miss/absorb an Enter when text and Enter
            # are delivered in the same tmux send-keys invocation.
            time.sleep(0.05)
        _run_cmd(self._tmux_cmd("send-keys", "-t", name, "Enter"))

    def send_key_names(self, name, keys) -> None:
        """Send true NAMED key-presses (e.g. 'Up','Down','Escape','Enter','Tab','C-c').

        Unlike send_keys (which pastes literal text + Enter), this uses
        `tmux send-keys` WITHOUT `-l`, so tmux interprets each token as a key
        name. This is the only way to drive an interactive TUI — e.g. /rewind's
        arrow/Esc picker, which a literal paste cannot operate.

        `keys` may be a single key string or a list of key-name tokens, applied
        in order in one send-keys call.
        """
        if not self.session_exists(name):
            raise SubstrateError(
                f"Session '{name}' does not exist", code="SESSION_NOT_FOUND")
        if isinstance(keys, str):
            keys = [keys]
        keys = [str(k) for k in keys if str(k)]
        if not keys:
            return
        self._cancel_copy_mode_if_needed(name)
        _run_cmd(self._tmux_cmd("send-keys", "-t", name, *keys))

    def _cancel_copy_mode_if_needed(self, name: str) -> None:
        """Exit tmux copy-mode before writing prompt text.

        UCI's live terminal uses a tmux attach client. Scrolling/selecting can
        leave the pane in copy-mode; prompt text delivered while copy-mode is
        active is consumed as tmux navigation/search commands rather than being
        sent to the AI CLI. Cancel only confirmed copy-mode instead of sending a
        blind Escape into the foreground application.
        """
        result = subprocess.run(
            self._tmux_cmd("display-message", "-p", "-t", name, "#{pane_in_mode}"),
            capture_output=True,
            text=True,
        )
        if result.returncode == 0 and result.stdout.strip() == "1":
            _run_cmd(self._tmux_cmd("send-keys", "-t", name, "-X", "cancel"))
            time.sleep(0.025)

    def write_chars(self, name: str, text: str) -> None:
        if not self.session_exists(name):
            raise SubstrateError(
                f"Session '{name}' does not exist",
                code="SESSION_NOT_FOUND",
            )
        if not text:
            return
        self._cancel_copy_mode_if_needed(name)

        buffer_name = f"unified_cli_write_{os.getpid()}"
        try:
            subprocess.run(
                self._tmux_cmd("load-buffer", "-b", buffer_name, "-"),
                input=text,
                capture_output=True,
                text=True,
                check=True,
            )
            _run_cmd(self._tmux_cmd(
                "paste-buffer", "-d",
                "-b", buffer_name,
                "-t", name,
            ))
        except subprocess.CalledProcessError as e:
            stderr = (e.stderr or "").strip()
            raise SubstrateError(
                f"Command failed (exit {e.returncode}): tmux load-buffer/paste-buffer"
                + (f"\n{stderr}" if stderr else "")
            )

    def write_chars_typed(self, name: str, text: str) -> None:
        """Type literal characters without tmux paste-buffer/bracketed paste.

        Some AI CLIs detect tmux paste-buffer as pasted content and collapse it
        into placeholders such as "[Pasted text #1 +23 lines]". PromptBox input
        should behave like typed text, so use tmux send-keys -l in chunks.
        """
        if not self.session_exists(name):
            raise SubstrateError(
                f"Session '{name}' does not exist",
                code="SESSION_NOT_FOUND",
            )
        if not text:
            return
        self._cancel_copy_mode_if_needed(name)

        # Guarantee assume-paste-time is disabled on THIS session before typing.
        # create_session sets it, but attach/resume does NOT — so sessions created
        # before that fix (or resumed) still wrap rapid send-keys -l input in a
        # bracketed paste, which the CLI collapses into "[Pasted text #N]". Setting it
        # here (idempotent, cheap) makes typed delivery chip-proof for ANY session age.
        try:
            _run_cmd(self._tmux_cmd("set-option", "-t", name, "assume-paste-time", "0"))
        except Exception:
            pass  # best-effort; the send below still proceeds

        # Chunk the literal send. A single large `send-keys -l` is delivered to the
        # pane PTY in ~1KB reads; a CLI reads each multi-line fragment as a separate
        # bracketed paste and collapses it into "[Pasted text #N]" — even with
        # assume-paste-time 0, because the fragmentation happens below tmux. (Verified:
        # a 4KB/31-line prompt produced 4 chips; the SAME text sent in 400-byte chunks
        # produced none; a <1KB prompt never chips.) Send in sub-threshold chunks with
        # a brief inter-chunk pause so each read stays small enough to read as typed
        # input; assume-paste-time 0 (set above) stops tmux from re-coalescing them.
        CHUNK = 400           # bytes per send — comfortably under the ~1KB chip threshold
        INTER_CHUNK_S = 0.06  # pause so the CLI processes each chunk as typed input
        # NOTE the `--` after `-l`: it terminates tmux option parsing so a chunk that
        # begins with '-' (a markdown "- " bullet, a "--flag", or a hyphen that lands on
        # a CHUNK boundary) is sent as LITERAL text, not misread as a send-keys option.
        # Without it, tmux parses that chunk as options and either errors (raise → abort)
        # or — worse — silently consumes it and returns 0, so delivery reports SUCCESS
        # while the chunk's text is dropped. Either way the prompt truncates at that
        # chunk. Observed live: a 596-char prompt whose "pre-configuring" hyphen sat on
        # the 400 boundary delivered only 400 chars with success=True.
        if len(text) <= CHUNK:
            _run_cmd(self._tmux_cmd("send-keys", "-t", name, "-l", "--", text))
        else:
            for i in range(0, len(text), CHUNK):
                _run_cmd(self._tmux_cmd("send-keys", "-t", name, "-l", "--", text[i:i + CHUNK]))
                if i + CHUNK < len(text):
                    time.sleep(INTER_CHUNK_S)

        # ── Post-send verification (defense-in-depth) ────────────────────────
        # A dropped chunk (see the `--` note above) or any other delivery fault leaves
        # the prompt area SHORT while send-keys still returns 0 — a SILENT truncation.
        # Before the caller submits, confirm the TAIL of what we typed actually landed
        # in the pane; if it didn't, raise so a truncated prompt is a LOUD failure (the
        # caller won't press Enter) rather than a silent bad send. The tail is matched
        # whitespace-normalized so the CLI's soft-wrapping of the input line is tolerated,
        # and re-checked with a short backoff so a slow render isn't a false alarm.
        import re as _re
        _norm = lambda s: _re.sub(r"\s+", "", s)
        needle = _norm(text)[-28:]
        if needle:
            for _delay in (0.15, 0.25, 0.4):
                time.sleep(_delay)
                try:
                    if needle in _norm(self.dump_screen(name, plain_text=True)):
                        return
                except Exception:
                    pass
            raise SubstrateError(
                "Typed delivery verification failed: the end of the prompt did not appear "
                "in the prompt area (likely truncated in transit) — NOT submitted.",
                code="DELIVERY_TRUNCATED",
            )

    def dump_screen(self, name: str, path: Path | None = None, plain_text: bool = True,
                     full: bool = False) -> str:
        if not self.session_exists(name):
            raise SubstrateError(
                f"Session '{name}' does not exist",
                code="SESSION_NOT_FOUND",
            )
        cmd = self._tmux_cmd("capture-pane")
        if not plain_text:
            cmd.append("-e")  # preserve escape sequences
        scroll_lines = "-50000" if full else "-1000"
        cmd.extend(["-p", "-t", name, "-S", scroll_lines])
        result = _run_cmd(cmd)
        content = result.stdout
        if path is not None:
            path.write_text(content)
        return content

    def get_current_session_name(self) -> str | None:
        tmux_env = os.environ.get("TMUX")
        if not tmux_env:
            return None
        # TMUX env var format: /tmp/tmux-UID/default,PID,SESSION_INDEX
        # Get the actual session name via tmux command
        result = subprocess.run(
            self._tmux_cmd("display-message", "-p", "#{session_name}"),
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip() or None
        return None

    def attach(self, name: str, replace_process: bool = False) -> None:
        if not self.session_exists(name):
            raise SubstrateError(
                f"Session '{name}' does not exist",
                code="SESSION_NOT_FOUND",
            )
        cmd = self._tmux_cmd("attach-session", "-t", name)
        if replace_process:
            os.execvp(cmd[0], cmd)
        else:
            subprocess.run(cmd)

    def attach_pty(self, name: str, socket_dir: str = "/tmp/uai_pty") -> dict:
        """Spawn tmux attach inside a PTY and bridge it to a unix socket.

        The substrate owns the tmux process. The caller connects to the returned
        socket path for bidirectional terminal I/O. This lets Electron/node apps
        embed a live terminal without knowing about tmux.
        """
        import pty as pty_mod
        import socket
        import threading
        import select

        if not self.session_exists(name):
            raise SubstrateError(
                f"Session '{name}' does not exist",
                code="SESSION_NOT_FOUND",
            )

        os.makedirs(socket_dir, exist_ok=True)
        sock_path = os.path.join(socket_dir, f"{name}.sock")

        # Clean up stale socket
        if os.path.exists(sock_path):
            os.unlink(sock_path)

        cmd = self._tmux_cmd("attach-session", "-t", name)

        # Spawn tmux in a PTY
        child_pid, master_fd = pty_mod.fork()
        if child_pid == 0:
            # Child: exec tmux
            os.execvp(cmd[0], cmd)
            os._exit(1)

        # Parent: create unix socket server, bridge master_fd <-> client socket
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(sock_path)
        srv.listen(1)

        def bridge():
            conn, _ = srv.accept()
            try:
                while True:
                    readable, _, _ = select.select([master_fd, conn], [], [], 1.0)
                    for fd in readable:
                        if fd == master_fd:
                            try:
                                data = os.read(master_fd, 4096)
                                if not data:
                                    return
                                conn.sendall(data)
                            except OSError:
                                return
                        elif fd == conn:
                            try:
                                data = conn.recv(4096)
                                if not data:
                                    return
                                os.write(master_fd, data)
                            except OSError:
                                return
            finally:
                conn.close()
                srv.close()
                try:
                    os.close(master_fd)
                except OSError:
                    pass
                try:
                    os.waitpid(child_pid, os.WNOHANG)
                except ChildProcessError:
                    pass
                try:
                    os.unlink(sock_path)
                except OSError:
                    pass

        thread = threading.Thread(target=bridge, daemon=True)
        thread.start()

        return {"socket_path": sock_path, "pid": child_pid}


# =============================================================================
# ZellijSubstrate
# =============================================================================

class ZellijSubstrate(SessionSubstrate):
    """Session substrate using zellij. Refactored from ZellijSession in lib_cli_common.py.

    Preserves all battle-tested internals: PTY allocation via script(1),
    TIOCSWINSZ, tip dismissal, layout support.
    """

    def __init__(self, zellij_bin: Path | None = None):
        if zellij_bin is None:
            self._bin = _require_binary("zellij")
        else:
            self._bin = zellij_bin
        # Holds PTY master fds to keep sessions alive (keyed by session name)
        self._pty_masters: dict[str, int] = {}

    @property
    def substrate_name(self) -> str:
        return "zellij"

    def create_session(self, name: str, command: list[str], cwd: str,
                       log_file: Path | None = None) -> LaunchResult:
        _validate_session_name(name)

        # If we're already inside the target session, exec the command directly.
        # This handles the cli-agent case where we're sent into an existing session.
        current_session = os.environ.get("ZELLIJ_SESSION_NAME", "")
        if current_session == name:
            os.chdir(cwd)
            os.environ["NODE_OPTIONS"] = "--max-old-space-size=8192"
            os.execvp(command[0], command)
            # execvp doesn't return

        # Kill existing session with same name
        if self.session_exists(name):
            self.kill_session(name)

        # Transcript disabled (900MB/12h was unsustainable).
        # script(1) still used for PTY allocation; output goes to /dev/null.
        transcript = Path("/dev/null")

        # Build a short launcher command for zellij. The actual CLI command can
        # include multi-KB prompt arguments; typing those through write-chars is
        # unreliable and literal newlines would submit partial commands.
        import shlex
        launch_script = _write_launch_script(name, command, cwd)
        full_cmd = f"/bin/bash {shlex.quote(str(launch_script))}"

        # Pre-create PTY with large window size so zellij sees a large client.
        import pty as pty_mod, fcntl, struct, termios
        master_fd, slave_fd = pty_mod.openpty()
        winsize = struct.pack('HHHH', 999, 999, 0, 0)
        fcntl.ioctl(master_fd, termios.TIOCSWINSZ, winsize)

        # Launch env
        launch_env = os.environ.copy()
        launch_env["COLUMNS"] = "999"
        launch_env["LINES"] = "999"
        launch_env.setdefault("TERM", "xterm-256color")

        # Layout support
        app_layout = Path.home() / "AI/ai_root/ai_general/config/zellij_app_layout.kdl"
        if app_layout.exists():
            zellij_args = [
                str(self._bin), "-s", name,
                "--new-session-with-layout", str(app_layout),
            ]
        else:
            zellij_args = [str(self._bin), "-s", name]

        # Launch zellij inside script(1) for PTY allocation
        proc = subprocess.Popen(
            ["script", "-q", "-F", str(transcript)] + zellij_args,
            stdin=slave_fd,
            stdout=slave_fd,
            stderr=slave_fd,
            start_new_session=True,
            cwd=cwd,
            env=launch_env,
        )
        os.close(slave_fd)
        # Keep master_fd open — closing it would signal EOF to the PTY
        self._pty_masters[name] = master_fd

        # Wait for session to be ready
        if not self._wait_for_session(name):
            raise SubstrateError(
                f"Zellij session '{name}' did not appear within timeout",
                code="SUBSTRATE_ERROR",
            )

        # Dismiss any zellij modal (tip screen) with Enter
        import time
        time.sleep(0.5)
        subprocess.run([
            str(self._bin), "--session", name,
            "action", "write", "13",
        ], capture_output=True)
        time.sleep(0.5)

        # Send the actual command into the session
        self.send_keys(name, full_cmd)

        # Wait for the CLI process to start, then find its PID
        time.sleep(2)
        pid = self._get_session_pid(name, command[0])

        return LaunchResult(session_name=name, pid=pid)

    def _get_session_pid(self, name: str, binary_name: str, timeout: float = 10.0) -> int | None:
        """Find the PID of the CLI binary running inside a zellij session.

        Uses ps to find processes whose command matches the binary and whose
        ancestor is the zellij server for this session.
        """
        import time
        # Find the zellij server PID for this session
        binary_base = Path(binary_name).name  # e.g., "claude", "codex", "gemini"
        deadline = time.monotonic() + timeout

        while time.monotonic() < deadline:
            try:
                result = subprocess.run(
                    ["ps", "-eo", "pid,ppid,command"],
                    capture_output=True, text=True, timeout=5,
                )
                # Find processes matching our binary
                for line in result.stdout.splitlines():
                    parts = line.strip().split(None, 2)
                    if len(parts) < 3:
                        continue
                    pid_str, ppid_str, cmd = parts
                    if binary_base in cmd and name in cmd:
                        # This process has both the binary name and session name in its command
                        try:
                            return int(pid_str)
                        except ValueError:
                            continue
                    if binary_base in cmd and "session" not in cmd.lower():
                        # Binary running, check if it might be ours by recency
                        # (fallback — less precise but catches cases where session
                        # name isn't in the command args)
                        pass
            except (subprocess.TimeoutExpired, OSError):
                pass
            time.sleep(1)

        return None

    def _wait_for_session(self, name: str, timeout: float = 10.0) -> bool:
        """Poll until session appears in zellij list-sessions."""
        import time
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self.session_exists(name):
                return True
            time.sleep(0.5)
        return False

    def session_exists(self, name: str) -> bool:
        result = subprocess.run(
            [str(self._bin), "list-sessions", "--short", "--no-formatting"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return False
        return name in result.stdout.splitlines()

    def session_is_running(self, name: str) -> bool:
        # Zellij sessions in list-sessions are running
        return self.session_exists(name)

    def kill_session(self, name: str) -> None:
        if not self.session_exists(name):
            raise SubstrateError(
                f"Session '{name}' does not exist",
                code="SESSION_NOT_FOUND",
            )
        result = subprocess.run(
            [str(self._bin), "delete-session", name, "--force"],
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise SubstrateError(
                f"Failed to kill session '{name}': "
                + (result.stderr.strip() or f"exit {result.returncode}"),
                code="KILL_FAILED",
            )
        # Clean up PTY master fd if we hold one
        fd = self._pty_masters.pop(name, None)
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass

    def rename_session(self, old_name: str, new_name: str) -> None:
        raise SubstrateError(
            "rename_session not supported by zellij",
            code="NOT_SUPPORTED",
        )

    def list_sessions(self) -> list[SessionInfo]:
        result = subprocess.run(
            [str(self._bin), "list-sessions", "--short", "--no-formatting"],
            capture_output=True, text=True,
        )
        if result.returncode != 0:
            return []
        sessions = []
        for line in result.stdout.strip().splitlines():
            name = line.strip()
            if name:
                sessions.append(SessionInfo(name=name, running=True))
        return sessions

    def _cancel_scroll_mode(self, name: str) -> None:
        """Send Escape to exit scroll/search mode if active.

        Zellij has no query for pane mode (unlike tmux #{pane_in_mode}).
        Sending Escape (byte 27) exits scroll/search mode if active. In
        normal mode it's harmless — just cancels any partial input, which
        is fine since we're about to overwrite the prompt anyway.
        """
        _run_cmd([
            str(self._bin), "--session", name,
            "action", "write", "27",  # ESC
        ])
        time.sleep(0.05)

    def send_keys(self, name: str, keys: str) -> None:
        self._cancel_scroll_mode(name)
        _run_cmd([
            str(self._bin), "--session", name,
            "action", "write-chars", keys,
        ])
        # Press Enter
        _run_cmd([
            str(self._bin), "--session", name,
            "action", "write", "13",
        ])

    def write_chars(self, name: str, text: str) -> None:
        self._cancel_scroll_mode(name)
        _run_cmd([
            str(self._bin), "--session", name,
            "action", "write-chars", text,
        ])

    def dump_screen(self, name: str, path: Path | None = None, plain_text: bool = True) -> str:
        import tempfile
        # Note: zellij dump-screen does not support styled output; plain_text param is accepted but ignored
        cleanup = False
        if path is None:
            fd, tmp = tempfile.mkstemp(suffix=".txt")
            os.close(fd)
            path = Path(tmp)
            cleanup = True

        try:
            _run_cmd([
                str(self._bin), "--session", name,
                "action", "dump-screen", str(path),
            ])
            content = ""
            if path.exists():
                content = path.read_text()
            return content
        finally:
            if cleanup:
                try:
                    path.unlink()
                except OSError:
                    pass

    def get_current_session_name(self) -> str | None:
        return os.environ.get("ZELLIJ_SESSION_NAME") or None

    def attach(self, name: str, replace_process: bool = False) -> None:
        if not self.session_exists(name):
            raise SubstrateError(
                f"Session '{name}' does not exist",
                code="SESSION_NOT_FOUND",
            )
        cmd = [str(self._bin), "attach", name]
        if replace_process:
            os.execvp(cmd[0], cmd)
        else:
            subprocess.run(cmd)


# =============================================================================
# NoneSubstrate
# =============================================================================

class NoneSubstrate(SessionSubstrate):
    """Stub substrate for --no-mux / --oneshot mode.

    Runs the command in the foreground with no multiplexer.
    Only send_keys (via stdin pipe) and basic lifecycle ops are supported.
    """

    def __init__(self):
        self._processes: dict[str, subprocess.Popen] = {}

    @property
    def substrate_name(self) -> str:
        return "none"

    def create_session(self, name: str, command: list[str], cwd: str,
                       log_file: Path | None = None) -> LaunchResult:
        # Kill existing if present
        if name in self._processes:
            self.kill_session(name)

        proc = subprocess.Popen(
            command,
            cwd=cwd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        self._processes[name] = proc
        return LaunchResult(session_name=name, pid=proc.pid)

    def session_exists(self, name: str) -> bool:
        return name in self._processes

    def session_is_running(self, name: str) -> bool:
        proc = self._processes.get(name)
        return proc is not None and proc.poll() is None

    def kill_session(self, name: str) -> None:
        proc = self._processes.pop(name, None)
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()

    def rename_session(self, old_name: str, new_name: str) -> None:
        raise SubstrateError(
            "rename_session not supported without multiplexer",
            code="NOT_SUPPORTED",
        )

    def list_sessions(self) -> list[SessionInfo]:
        raise SubstrateError(
            "list_sessions not supported without multiplexer",
            code="NOT_SUPPORTED",
        )

    def send_keys(self, name: str, keys: str) -> None:
        proc = self._processes.get(name)
        if proc is None or proc.stdin is None:
            raise SubstrateError(
                f"Cannot send keys: no stdin pipe for '{name}'",
                code="SESSION_NOT_FOUND",
            )
        if proc.poll() is not None:
            raise SubstrateError(
                f"Cannot send keys: process '{name}' has exited",
                code="SESSION_NOT_FOUND",
            )
        proc.stdin.write(keys + "\n")
        proc.stdin.flush()

    def write_chars(self, name: str, text: str) -> None:
        proc = self._processes.get(name)
        if proc is None or proc.stdin is None:
            raise SubstrateError(
                f"Cannot write chars: no stdin pipe for '{name}'",
                code="SESSION_NOT_FOUND",
            )
        if proc.poll() is not None:
            raise SubstrateError(
                f"Cannot write chars: process '{name}' has exited",
                code="SESSION_NOT_FOUND",
            )
        proc.stdin.write(text)
        proc.stdin.flush()

    def dump_screen(self, name: str, path: Path | None = None, plain_text: bool = True) -> str:
        raise SubstrateError(
            "dump_screen not supported without multiplexer",
            code="NOT_SUPPORTED",
        )

    def get_current_session_name(self) -> str | None:
        return None

    def attach(self, name: str) -> None:
        raise SubstrateError(
            "attach not supported without multiplexer",
            code="NOT_SUPPORTED",
        )


# =============================================================================
# Factory / Substrate Selection
# =============================================================================

def _get_substrate_config_path() -> Path:
    ai_root = Path(os.environ.get("AI_ROOT", str(_DEFAULT_AI_ROOT))).expanduser()
    return ai_root / "ai_general" / "data" / "substrate_config.json"

_SUBSTRATE_MAP = {
    "tmux": TmuxSubstrate,
    "zellij": ZellijSubstrate,
    "none": NoneSubstrate,
}


def _detect_substrate_from_env() -> str | None:
    """Auto-detect substrate from environment variables.

    Returns substrate name if running inside a known multiplexer, else None.
    """
    if os.environ.get("ZELLIJ_SESSION_NAME"):
        return "zellij"
    if os.environ.get("TMUX"):
        return "tmux"
    return None


def get_substrate(
    override: str | None = None,
    config_path: Path | None = None,
    tmux_server_name: str | None | object = _AUTO_TMUX_SERVER,
    runtime_context: str | None | object = _AUTO_TMUX_SERVER,
) -> SessionSubstrate:
    """Get the configured session substrate.

    Args:
        override: Force a specific substrate ("tmux", "zellij", "none").
        config_path: Custom config file path (for testing).
        tmux_server_name: Explicit tmux server name, None for legacy/default server,
            or omitted for auto-resolution from env/config/AI_ROOT.
        runtime_context: Generic alias for tmux_server_name used by callers
            outside the substrate module.

    Resolution order: override -> config file -> env auto-detect -> default ("tmux").
    """
    substrate_name = override
    config_tmux_server_name: str | None = None

    if substrate_name is None:
        cfg_path = config_path or _get_substrate_config_path()
        if cfg_path.exists():
            try:
                with open(cfg_path) as f:
                    cfg = json.load(f)
                substrate_name = cfg.get("substrate")
                config_tmux_server_name = (
                    cfg.get("substrate_context")
                    or cfg.get("runtime_context")
                    or cfg.get("tmux_server")
                    or cfg.get("tmux_server_name")
                )
            except (json.JSONDecodeError, OSError):
                pass

    if substrate_name is None:
        substrate_name = _detect_substrate_from_env()

    if substrate_name is None:
        substrate_name = "tmux"

    cls = _SUBSTRATE_MAP.get(substrate_name)
    if cls is None:
        raise SubstrateError(
            f"Unknown substrate '{substrate_name}'. "
            f"Valid options: {', '.join(_SUBSTRATE_MAP)}",
            code="INVALID_ARGS",
        )

    if cls is TmuxSubstrate:
        context_name = runtime_context
        if context_name is _AUTO_TMUX_SERVER:
            context_name = tmux_server_name
        resolved_server_name = resolve_tmux_server_name(
            context_name,
            config_value=config_tmux_server_name,
        )
        return cls(server_name=resolved_server_name)

    return cls()


# =============================================================================
# CLI Command Interface
# =============================================================================

def _json_response(ok: bool, result: Any = None, error: str | None = None,
                   code: str | None = None) -> str:
    """Build JSON response envelope."""
    resp: dict[str, Any] = {"ok": ok}
    if ok:
        resp["result"] = result
    else:
        resp["error"] = error
        if code:
            resp["code"] = code
    return json.dumps(resp)


def _discover_uuid_before_kill(session_name: str) -> None:
    """If the session store has no UUID for this session, try screen parsing before kill.

    The CLI is still alive at this point, so the terminal footer is visible.
    Silent failure — never blocks the kill.
    """
    try:
        _script_dir = Path(__file__).resolve().parent
        if str(_script_dir) not in sys.path:
            sys.path.insert(0, str(_script_dir))
        from uai_toolkit.session_mgmt.session_ops import get_ai_status, _resolve_session, _infer_platform

        stored = _resolve_session(session_name)
        if not stored or stored.get("cli_session_id"):
            return  # Already has UUID or not in store

        platform = stored.get("platform") or _infer_platform(session_name)
        if platform not in ("codex_cli", "gemini_cli"):
            return  # Claude UUIDs are pre-assigned

        status = get_ai_status(session_name, platform=platform)
        live_uuid = status.get("uuid")
        if live_uuid and len(live_uuid) >= 8:
            tracking_id = stored.get("tracking_id", session_name)
            from uai_toolkit.session_mgmt.session_store import SessionStore
            store = SessionStore()
            store.update(tracking_id, cli_session_id=live_uuid)
    except Exception:
        pass  # Never block the kill


def _session_info_to_dict(info: SessionInfo) -> dict:
    """Convert SessionInfo to JSON-serializable dict."""
    d = asdict(info)
    if d["created"] is not None:
        d["created"] = d["created"].isoformat()
    return d


def _cli_main(argv: list[str] | None = None) -> int:
    """CLI entry point for subprocess callers (Electron app, scripts)."""
    parser = argparse.ArgumentParser(
        prog="lib_session_substrate",
        description="Session substrate CLI — JSON interface for terminal multiplexer operations",
    )
    parser.add_argument(
        "--substrate", choices=list(_SUBSTRATE_MAP),
        help="Override substrate type (default: from config)",
    )

    sub = parser.add_subparsers(dest="command", required=True)

    # list-sessions
    sub.add_parser("list-sessions", help="List all sessions")

    # session-exists
    p = sub.add_parser("session-exists", help="Check if session exists")
    p.add_argument("--session", required=True, help="Session name")

    # session-is-running
    p = sub.add_parser("session-is-running", help="Check if session is actively running")
    p.add_argument("--session", required=True, help="Session name")

    # create-session
    p = sub.add_parser("create-session", help="Create a new session")
    p.add_argument("--name", required=True, help="Session name")
    p.add_argument("--cmd", required=True, dest="session_command",
                   help="Command to run (shell string, will be split)")
    p.add_argument("--cwd", required=True, help="Working directory")
    p.add_argument("--log-file", help="Log file path")

    # kill-session
    p = sub.add_parser("kill-session", help="Kill a session")
    p.add_argument("--session", required=True, help="Session name")

    # send-keys
    p = sub.add_parser("send-keys", help="Send keystrokes to a session")
    p.add_argument("--session", required=True, help="Session name")
    p.add_argument("--keys", required=True, help="Text to send")

    # dump-screen
    p = sub.add_parser("dump-screen", help="Capture screen content")
    p.add_argument("--session", required=True, help="Session name")
    p.add_argument("--path", help="Output file path")

    # attach
    p = sub.add_parser("attach", help="Attach to a session")
    p.add_argument("--session", required=True, help="Session name")

    # attach-pty
    p = sub.add_parser("attach-pty", help="Attach via unix socket (for Electron/non-interactive clients)")
    p.add_argument("--session", required=True, help="Session name")

    args = parser.parse_args(argv)

    try:
        substrate = get_substrate(override=args.substrate)
    except (SubstrateError, FileNotFoundError) as e:
        print(_json_response(False, error=str(e), code="SUBSTRATE_ERROR"), file=sys.stderr)
        return 1

    try:
        if args.command == "list-sessions":
            sessions = substrate.list_sessions()
            result = [_session_info_to_dict(s) for s in sessions]
            print(_json_response(True, result=result))

        elif args.command == "session-exists":
            exists = substrate.session_exists(args.session)
            print(_json_response(True, result=exists))

        elif args.command == "session-is-running":
            running = substrate.session_is_running(args.session)
            print(_json_response(True, result=running))

        elif args.command == "create-session":
            import shlex
            cmd_parts = shlex.split(args.session_command)
            log_path = Path(args.log_file) if args.log_file else None
            launch = substrate.create_session(args.name, cmd_parts, args.cwd, log_path)
            print(_json_response(True, result={"session_name": launch.session_name, "pid": launch.pid}))

        elif args.command == "kill-session":
            # Before killing, discover UUID if the session store doesn't have one.
            # The CLI is still alive at this point, so screen parsing works.
            _discover_uuid_before_kill(args.session)
            substrate.kill_session(args.session)
            print(_json_response(True, result=None))

        elif args.command == "send-keys":
            substrate.send_keys(args.session, args.keys)
            print(_json_response(True, result=None))

        elif args.command == "dump-screen":
            out_path = Path(args.path) if args.path else None
            content = substrate.dump_screen(args.session, out_path)
            print(_json_response(True, result=content))

        elif args.command == "attach":
            # exec into the multiplexer — replaces this process so the
            # terminal session gets direct PTY ownership
            substrate.attach(args.session, replace_process=True)

        elif args.command == "attach-pty":
            # Spawn multiplexer in a PTY, bridge to a unix socket.
            # Returns socket path for non-interactive clients (Electron apps).
            result = substrate.attach_pty(args.session)
            print(_json_response(True, result=result))

    except SubstrateError as e:
        print(_json_response(False, error=str(e), code=e.code), file=sys.stderr)
        return 1
    except Exception as e:
        print(_json_response(False, error=str(e), code="SUBSTRATE_ERROR"), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(_cli_main())
