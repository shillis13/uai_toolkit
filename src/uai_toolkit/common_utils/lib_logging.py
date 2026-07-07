"""
File: lib_logging.py

Reusable, configurable logging for all AI/Python tools.

Design goals (portable to macOS / Linux / WSL / Windows 10+):
  * NAMED loggers, never the root logger. Libraries call ``get_logger(__name__)``
    and log freely; the application entrypoint calls ``configure_logging()``
    exactly once to decide where records go.
  * Color lives in the CONSOLE FORMATTER (tty-aware), never baked into the
    message string — so file / JSONL output is never polluted with ANSI codes.
  * Pluggable destinations: colored console (stderr), rotating plain-text file,
    optional JSON-lines file. Each can be turned on/off independently.
  * Configuration knobs, in precedence order (later overrides earlier):
        env vars  ->  configure_logging(...) explicit args
    Env: AI_LOG_LEVEL, AI_LOG_FILE, AI_LOG_JSON, AI_LOG_CONSOLE, NO_COLOR.
  * Backward-compatible: the old helpers (setup_logging, log_info/error/debug/out,
    log_block, log_function, parse_args) still work, now routed through the new
    core with color moved to the formatter.

Quick start
-----------
Library / module code::

    from uai_toolkit.common_utils.lib_logging import get_logger
    log = get_logger(__name__)
    log.info("did a thing")
    log.debug("detail %s", value)

Application entrypoint (once, near the top of main())::

    from uai_toolkit.common_utils.lib_logging import configure_logging
    configure_logging(level="INFO", log_file=session_dir / "app.log")

Everything under the ``ai`` logger namespace then honors that config.
"""

from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import signal
import sys
from contextlib import contextmanager
from functools import wraps
from pathlib import Path
from typing import Optional, Union

try:  # color is optional; degrade gracefully if unavailable
    from uai_toolkit.common_utils.lib_outputColors import Colors
except Exception:  # pragma: no cover - color is a nicety, not a requirement
    Colors = None  # type: ignore


# =============================================================================
# Constants
# =============================================================================

#: Root of our logger namespace. All AI tool loggers hang off this so a single
#: ``configure_logging()`` call governs the whole tree without touching root.
ROOT_LOGGER_NAME = "ai"

#: Default record format (plain text — file/console share it, console adds color).
DEFAULT_FORMAT = "%(asctime)s %(levelname)-7s %(name)s %(funcName)s:%(lineno)d  %(message)s"
DEFAULT_DATEFMT = "%Y-%m-%d %H:%M:%S"

#: Per-level foreground color names understood by lib_outputColors.
_LEVEL_COLORS = {
    "DEBUG": "gray",
    "INFO": "white",
    "WARNING": "yellow",
    "ERROR": "red",
    "CRITICAL": "red",
}

# Guard so configure_logging is idempotent unless force=True.
_CONFIGURED = False


# =============================================================================
# Level coercion
# =============================================================================

def coerce_level(level: Union[int, str, None], default: int = logging.INFO) -> int:
    """Turn a level name/int/None into a numeric logging level.

    Accepts ``"DEBUG"``, ``"debug"``, ``logging.DEBUG``, ``"10"``, or ``None``.
    """
    if level is None:
        return default
    if isinstance(level, int):
        return level
    text = str(level).strip()
    if text.isdigit():
        return int(text)
    return getattr(logging, text.upper(), default)


# =============================================================================
# Formatters
# =============================================================================

class ColorFormatter(logging.Formatter):
    """Text formatter that colorizes the level name when writing to a TTY.

    Color is applied here (at format time, per handler) — never stored on the
    record — so the same record can also be written plain to a file.
    """

    def __init__(self, fmt=DEFAULT_FORMAT, datefmt=DEFAULT_DATEFMT, use_color=True):
        super().__init__(fmt=fmt, datefmt=datefmt)
        self.use_color = use_color and Colors is not None

    def format(self, record: logging.LogRecord) -> str:
        if not self.use_color:
            return super().format(record)
        # Apply the ANSI code DIRECTLY. We deliberately do NOT route through
        # Colors.colorize(), which re-runs its own global sys.stdout tty check
        # and would override this handler's stream-specific decision. The
        # handler already decided color is appropriate for its stream.
        original = record.levelname
        code = getattr(Colors, (_LEVEL_COLORS.get(original) or "").upper(), "")
        try:
            if code:
                record.levelname = f"{code}{original}{Colors.RESET}"
            return super().format(record)
        finally:
            record.levelname = original


class JsonFormatter(logging.Formatter):
    """Emit each record as a single JSON object (one JSON per line = JSONL)."""

    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, DEFAULT_DATEFMT),
            "level": record.levelname,
            "logger": record.name,
            "func": record.funcName,
            "line": record.lineno,
            "message": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


# =============================================================================
# Handler construction
# =============================================================================

def _stream_supports_color(stream) -> bool:
    """Decide whether a console stream should get ANSI color."""
    if os.environ.get("NO_COLOR") is not None:
        return False
    if os.environ.get("TERM", "") == "dumb":
        return False
    isatty = getattr(stream, "isatty", None)
    return bool(isatty and isatty())


def _make_console_handler(level: int, stream=None, use_color=None) -> logging.Handler:
    stream = stream if stream is not None else sys.stderr
    if use_color is None:
        use_color = _stream_supports_color(stream)
    handler = logging.StreamHandler(stream)
    handler.setLevel(level)
    handler.setFormatter(ColorFormatter(use_color=use_color))
    return handler


def _make_file_handler(
    path: Union[str, Path],
    level: int,
    max_bytes: int = 5_000_000,
    backup_count: int = 3,
) -> logging.Handler:
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(DEFAULT_FORMAT, DEFAULT_DATEFMT))  # no color
    return handler


def _make_json_handler(
    path: Union[str, Path],
    level: int,
    max_bytes: int = 5_000_000,
    backup_count: int = 3,
) -> logging.Handler:
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.handlers.RotatingFileHandler(
        path, maxBytes=max_bytes, backupCount=backup_count, encoding="utf-8"
    )
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter())
    return handler


def _make_plain_file_handler(path: Union[str, Path], level: int) -> logging.Handler:
    """Non-rotating append file handler.

    Used for the per-session log: several short-lived processes may run under a
    single session and append concurrently. Plain append is multiprocess-safe
    for line-sized writes; RotatingFileHandler is NOT (rotation races), so the
    session log deliberately does not rotate — session lifetime bounds its size.
    """
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, mode="a", encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(logging.Formatter(DEFAULT_FORMAT, DEFAULT_DATEFMT))  # no color
    return handler


def _make_plain_json_handler(path: Union[str, Path], level: int) -> logging.Handler:
    """Non-rotating append JSONL handler — the machine-readable session twin.

    Same multiprocess-append rationale as _make_plain_file_handler: the session
    log is written by many short-lived processes, so it must not rotate.
    """
    path = Path(path)
    if path.parent and not path.parent.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(path, mode="a", encoding="utf-8")
    handler.setLevel(level)
    handler.setFormatter(JsonFormatter())
    return handler


def default_session_log_path() -> Optional[Path]:
    """The per-session text log path: ``$AI_SESSION_DIR/logs/session.log`` or None.

    Returns None when AI_SESSION_DIR is not set (e.g. running outside a managed
    session), in which case logging falls back to console-only.
    """
    sd = os.environ.get("AI_SESSION_DIR")
    return Path(sd) / "logs" / "session.log" if sd else None


def default_session_json_path() -> Optional[Path]:
    """The per-session JSONL log path: ``$AI_SESSION_DIR/logs/session.jsonl``.

    This is the structured twin of session.log — one JSON object per line
    ({ts, level, logger, func, line, message}); ``logger`` is
    ``ai.<component>.<module>``. Consumed by the UAI Session Log tab and
    read_jsonl tooling. None when AI_SESSION_DIR is unset.
    """
    sd = os.environ.get("AI_SESSION_DIR")
    return Path(sd) / "logs" / "session.jsonl" if sd else None


# =============================================================================
# Public API — configuration
# =============================================================================

def configure_logging(
    *,
    level: Union[int, str, None] = None,
    console: Optional[bool] = None,
    log_file: Union[str, Path, None] = None,
    json_file: Union[str, Path, None] = None,
    session_file: Optional[bool] = None,
    stream=None,
    use_color: Optional[bool] = None,
    force: bool = False,
    logger_name: str = ROOT_LOGGER_NAME,
) -> logging.Logger:
    """Configure the AI logger namespace. Call ONCE, from the app entrypoint.

    Precedence: env vars set defaults, explicit kwargs override them.

    Destinations:
      * console  -> colored stderr (on by default)
      * session log -> ``$AI_SESSION_DIR/logs/session.log`` (plain append, no
        rotation), attached AUTOMATICALLY when AI_SESSION_DIR is set and no
        explicit ``log_file`` was given. Disable with ``session_file=False`` or
        env ``AI_LOG_SESSION=0``. Each record carries ``ai.<component>.<module>``
        so a single session log is filterable by subsystem and module.
      * log_file -> explicit rotating text log (overrides the session default).
      * json_file -> rotating JSONL log.

    Args:
        level: min level (name/int). Env fallback ``AI_LOG_LEVEL`` (default INFO).
        console: attach colored stderr handler. Env ``AI_LOG_CONSOLE`` (default on).
        log_file: explicit rotating text log. Env fallback ``AI_LOG_FILE``.
        json_file: JSONL rotating log. Env fallback ``AI_LOG_JSON``.
        session_file: attach the per-session log. Default (None) = auto: on when
            AI_SESSION_DIR is set and no explicit log_file. Env ``AI_LOG_SESSION``.
        stream: console stream (default ``sys.stderr``).
        use_color: force console color on/off (default: auto-detect the stream).
        force: reconfigure even if already configured (removes prior handlers).
        logger_name: namespace root to configure (default ``"ai"``).

    Returns:
        The configured logger.
    """
    global _CONFIGURED

    lvl = coerce_level(level if level is not None else os.environ.get("AI_LOG_LEVEL"))

    if console is None:
        env_console = os.environ.get("AI_LOG_CONSOLE")
        console = True if env_console is None else env_console.lower() not in ("0", "false", "no", "off")

    explicit_log_file = log_file is not None or bool(os.environ.get("AI_LOG_FILE"))
    if log_file is None:
        log_file = os.environ.get("AI_LOG_FILE") or None
    if json_file is None:
        json_file = os.environ.get("AI_LOG_JSON") or None

    explicit_json_file = json_file is not None or bool(os.environ.get("AI_LOG_JSON"))

    # Per-session logs: auto-on unless disabled. Text + JSONL twins written to
    # $AI_SESSION_DIR/logs/. Each is superseded by its explicit counterpart
    # (log_file supersedes session.log; json_file supersedes session.jsonl).
    if session_file is None:
        env_sess = os.environ.get("AI_LOG_SESSION")
        session_file = True if env_sess is None else env_sess.lower() not in ("0", "false", "no", "off")
    session_path = None
    session_json_path = None
    if session_file:
        if not explicit_log_file:
            session_path = default_session_log_path()
        if not explicit_json_file:
            session_json_path = default_session_json_path()

    logger = logging.getLogger(logger_name)

    if _CONFIGURED and not force:
        # Already set up; just make sure the level reflects the latest request.
        logger.setLevel(lvl)
        return logger

    # Fresh (or forced) configuration: clear our own handlers, keep others' alone.
    for h in list(logger.handlers):
        logger.removeHandler(h)
        try:
            h.close()
        except Exception:
            pass

    logger.setLevel(lvl)
    # Do not double-emit through the root logger's default handlers.
    logger.propagate = False

    if console:
        logger.addHandler(_make_console_handler(lvl, stream=stream, use_color=use_color))
    if log_file:
        logger.addHandler(_make_file_handler(log_file, lvl))          # explicit, rotating
    elif session_path:
        logger.addHandler(_make_plain_file_handler(session_path, lvl))  # session.log
    if json_file:
        logger.addHandler(_make_json_handler(json_file, lvl))          # explicit, rotating
    elif session_json_path:
        logger.addHandler(_make_plain_json_handler(session_json_path, lvl))  # session.jsonl

    # Never let the logger sit with zero handlers (would emit "no handlers" warnings
    # or fall through to root). A NullHandler is a safe floor.
    if not logger.handlers:
        logger.addHandler(logging.NullHandler())

    _CONFIGURED = True
    return logger


def add_file_handler(
    path: Union[str, Path],
    *,
    level: Union[int, str, None] = None,
    json: bool = False,
    logger_name: str = ROOT_LOGGER_NAME,
) -> logging.Handler:
    """Attach an extra file (text or JSONL) destination after initial config.

    Useful when a session directory only becomes known after startup — e.g. the
    launcher learns its per-session log path mid-run.
    Returns the handler so the caller can later ``remove_handler`` it.
    """
    logger = logging.getLogger(logger_name)
    lvl = coerce_level(level, default=logger.level or logging.INFO)
    handler = _make_json_handler(path, lvl) if json else _make_file_handler(path, lvl)
    logger.addHandler(handler)
    return handler


def set_level(level: Union[int, str], logger_name: str = ROOT_LOGGER_NAME) -> int:
    """Change the effective log level at RUNTIME, without reconfiguring handlers.

    Updates the namespace logger and all of its handlers, so a level drop to
    DEBUG takes effect immediately for every sink. Returns the numeric level.

    Use directly (``set_level("DEBUG")``) or wire it to a trigger — e.g. a
    SIGUSR1 handler in a long-running daemon, or a control message on the comms
    bus — to flip verbosity on a running process. Short-lived scripts don't need
    this: they re-read ``AI_LOG_LEVEL`` from the env on their next invocation.
    """
    lvl = coerce_level(level)
    logger = logging.getLogger(logger_name)
    logger.setLevel(lvl)
    for h in logger.handlers:
        h.setLevel(lvl)
    return lvl


def install_sigusr_level_toggle(
    debug_signal: int = signal.SIGUSR1,
    reset_signal: int = signal.SIGUSR2,
    reset_level: Union[int, str] = "INFO",
    logger_name: str = ROOT_LOGGER_NAME,
) -> None:
    """Opt-in: let a long-running process flip log level via Unix signals.

    ``kill -USR1 <pid>`` -> DEBUG, ``kill -USR2 <pid>`` -> reset (default INFO).
    Call once from a daemon's setup. No-op on platforms without SIGUSR (Windows);
    there, use ``set_level()`` via the comms bus or a control file instead.
    """
    if not hasattr(signal, "SIGUSR1"):  # e.g. Windows
        return
    signal.signal(debug_signal, lambda *_: set_level("DEBUG", logger_name))
    signal.signal(reset_signal, lambda *_: set_level(reset_level, logger_name))


def remove_handler(handler: logging.Handler, logger_name: str = ROOT_LOGGER_NAME) -> None:
    """Detach and close a handler previously returned by add_file_handler."""
    logger = logging.getLogger(logger_name)
    logger.removeHandler(handler)
    try:
        handler.close()
    except Exception:
        pass


def _derive_from_caller(depth: int = 2):
    """Best-effort (component, module) from the CALLER's file.

    component = the directory the file lives in; module = the file stem.
    e.g. ``.../scripts/prompting/send_prompt.py`` -> ``("prompting", "send_prompt")``.
    Walks up ``depth`` frames (get_logger's caller by default). Returns
    ``(None, None)`` if it can't be determined (frozen/exec/REPL).
    """
    try:
        import sys as _sys
        frame = _sys._getframe(depth)
        f = frame.f_globals.get("__file__")
        if not f:
            return None, None
        p = Path(f).resolve()
        return (p.parent.name or None), (p.stem or None)
    except Exception:
        return None, None


def get_logger(name: Optional[str] = None, component: Optional[str] = None) -> logging.Logger:
    """Return a namespaced logger under the ``ai`` root: ``ai.<component>.<module>``.

    The component makes logs filterable by subsystem; the module is the leaf.

      get_logger(__name__)  (from prompting/send_prompt.py)  -> "ai.prompting.send_prompt"
      get_logger("send_prompt", component="prompting")       -> "ai.prompting.send_prompt"
      get_logger("cli.claude")   (already dotted)            -> "ai.cli.claude"
      get_logger("ai.foo.bar")   (already namespaced)        -> used as-is
      get_logger() / get_logger("__main__")                  -> the "ai" root

    Component resolution order: explicit ``component=`` arg > the first segment
    of a dotted ``name`` > auto-derived from the caller's directory > none.
    """
    if name == "__main__":
        # Script run directly: __name__ is "__main__". Recover component+module
        # from the entrypoint file so `get_logger(__name__)` in a directly-run
        # script STILL lands under ai.<component>.<module> (the common case).
        comp, mod = _derive_from_caller(2)
        comp = component or comp
        if comp and mod:
            return logging.getLogger(f"{ROOT_LOGGER_NAME}.{comp}.{mod}")
        if mod:
            return logging.getLogger(f"{ROOT_LOGGER_NAME}.{mod}")
        return logging.getLogger(f"{ROOT_LOGGER_NAME}.{comp}" if comp else ROOT_LOGGER_NAME)

    if not name or name == ROOT_LOGGER_NAME:
        if component:
            return logging.getLogger(f"{ROOT_LOGGER_NAME}.{component}")
        return logging.getLogger(ROOT_LOGGER_NAME)

    if name.startswith(ROOT_LOGGER_NAME + "."):
        return logging.getLogger(name)  # already fully qualified

    if component:
        leaf = name.rsplit(".", 1)[-1]
        return logging.getLogger(f"{ROOT_LOGGER_NAME}.{component}.{leaf}")

    if "." in name:
        # Caller supplied its own component.module path — preserve it verbatim.
        return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")

    # Bare module name: auto-derive the component from the caller's directory so
    # already-migrated `get_logger(__name__)` sites become component-namespaced
    # with zero code churn.
    comp = _derive_from_caller(2)[0]
    if comp:
        return logging.getLogger(f"{ROOT_LOGGER_NAME}.{comp}.{name}")
    return logging.getLogger(f"{ROOT_LOGGER_NAME}.{name}")


def is_configured() -> bool:
    """True if configure_logging() has run."""
    return _CONFIGURED


# =============================================================================
# Context manager + decorators (attribution-correct; no hardcoded stacklevel)
# =============================================================================

@contextmanager
def log_block(name: str, logger: Optional[logging.Logger] = None):
    """Log entry/exit around a code block::

        with log_block("process_data"):
            ...
    """
    log = logger or get_logger()
    log.info("Entering block: %s", name)
    try:
        yield
    finally:
        log.info("Exiting block: %s", name)


def log_function(func):
    """Decorator: debug-log a function's call args and return value."""
    log = get_logger(getattr(func, "__module__", None))

    @wraps(func)
    def wrapper(*args, **kwargs):
        log.debug("%s called args=%s kwargs=%s", func.__name__, args, kwargs)
        result = func(*args, **kwargs)
        log.debug("%s returned %r", func.__name__, result)
        return result

    return wrapper


# =============================================================================
# Backward-compatible helpers
# =============================================================================
# These keep older call sites working. Color is NOT baked into the message any
# more — the console formatter applies per-level color, so file output stays clean.

def setup_logging(level=logging.INFO):
    """Back-compat shim for the old root-logger setup.

    Now routes through configure_logging() so callers get named-logger behavior,
    colored console, and clean files for free.
    """
    return configure_logging(level=level, force=True)


def _emit(level: int, message, stacklevel: int = 2):
    # Two wrapper frames sit between the user and logging: log_info() -> _emit()
    # -> logger.log(). So attributing the record to the user's call site needs
    # stacklevel+1 (default 2 -> 3) to skip both this frame and the log_* shim.
    get_logger().log(level, str(message), stacklevel=stacklevel + 1)


def log_info(message, stacklevel: int = 2):
    _emit(logging.INFO, message, stacklevel)


def log_error(message, stacklevel: int = 2):
    _emit(logging.ERROR, message, stacklevel)


def log_debug(message, stacklevel: int = 2):
    _emit(logging.DEBUG, message, stacklevel)


def log_out(message):
    """Plain program output (NOT a log record) — goes to stdout verbatim."""
    print(message)


def parse_args():
    """Back-compat: parse ``--log-level`` and configure logging as a side effect.

    Prefer configuring explicitly in new code; this remains for old CLIs.
    """
    parser = argparse.ArgumentParser(description="Set the logging level.")
    parser.add_argument(
        "--log-level",
        default=os.environ.get("AI_LOG_LEVEL", "INFO"),
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level (default: INFO)",
    )
    args, _ = parser.parse_known_args()
    level = coerce_level(args.log_level)
    configure_logging(level=level, force=True)
    return level
