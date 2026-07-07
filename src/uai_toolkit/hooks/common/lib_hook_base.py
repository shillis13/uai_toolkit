"""
Hook handler base — standardized entry point with logging for all hook handlers.

Every handler calls run_hook() which:
  1. Reads and parses stdin JSON
  2. Logs start
  3. Calls the handler function
  4. Logs outcome (action + reason + duration)
  5. Returns the appropriate exit code

Log output: {session_dir}/hook_events.jsonl
Fallback:   /tmp/hook_events_{tracking_id}.jsonl

Usage in a handler:

    from uai_toolkit.hooks.common.lib_hook_base import run_hook

    def my_handler(hook_input, context):
        # hook_input = parsed JSON from stdin
        # context = HookContext with tracking_id, session_dir, etc.
        # Return: HookResult
        return HookResult.allow()
        return HookResult.skip("response too short")
        return HookResult.block("You stated intent without acting")

    if __name__ == "__main__":
        sys.exit(run_hook("my_handler_name", "Stop", my_handler))
"""

import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Optional


@dataclass
class HookContext:
    """Context available to every hook handler."""
    tracking_id: str
    session_dir: str
    hook_type: str
    handler_name: str
    raw_input: str
    hook_input: dict = field(default_factory=dict)


class HookResult:
    """Result from a hook handler."""

    def __init__(self, exit_code, action, reason="", stderr_msg="", stdout_msg=""):
        self.exit_code = exit_code
        self.action = action      # "allow", "skip", "block", "error"
        self.reason = reason
        self.stderr_msg = stderr_msg
        self.stdout_msg = stdout_msg

    @classmethod
    def allow(cls, reason=""):
        return cls(0, "allow", reason)

    @classmethod
    def skip(cls, reason):
        return cls(0, "skip", reason)

    @classmethod
    def block(cls, message, reason=""):
        return cls(2, "block", reason or message, stderr_msg=message)

    @classmethod
    def error(cls, reason):
        return cls(1, "error", reason)

    @classmethod
    def output(cls, stdout_text, reason=""):
        """Allow, but produce stdout (e.g., context prepend)."""
        return cls(0, "output", reason, stdout_msg=stdout_text)


# Type alias for handler functions
HandlerFn = Callable[[dict, HookContext], HookResult]


def _get_log_path(session_dir, tracking_id):
    """Get the hook events log path."""
    if session_dir and Path(session_dir).is_dir():
        return Path(session_dir) / "hook_events.jsonl"
    if tracking_id:
        return Path("/tmp") / f"hook_events_{tracking_id}.jsonl"
    return Path("/tmp") / "hook_events_unknown.jsonl"


def _log_event(log_path, entry):
    """Append a JSON event to the hook log."""
    try:
        with open(log_path, "a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def run_hook(handler_name, hook_type, handler_fn):
    """Run a hook handler with standardized stdin parsing, logging, and exit codes.

    Args:
        handler_name: Short name for logging (e.g., "block_permission_seeking")
        hook_type: Hook event type (e.g., "Stop", "PreToolUse")
        handler_fn: Function(hook_input: dict, context: HookContext) -> HookResult

    Returns:
        Exit code (0, 1, or 2)
    """
    start = time.time()

    # Read stdin
    raw_input = ""
    try:
        raw_input = sys.stdin.read()
    except (IOError, OSError):
        pass

    # Parse JSON
    hook_input = {}
    if raw_input.strip():
        try:
            hook_input = json.loads(raw_input)
        except json.JSONDecodeError:
            pass

    # Build context
    tracking_id = os.environ.get("AI_TRACKING_ID", "")
    session_dir = os.environ.get("AI_SESSION_DIR", "")

    context = HookContext(
        tracking_id=tracking_id,
        session_dir=session_dir,
        hook_type=hook_type,
        handler_name=handler_name,
        raw_input=raw_input,
        hook_input=hook_input,
    )

    log_path = _get_log_path(session_dir, tracking_id)

    # Run handler
    try:
        result = handler_fn(hook_input, context)
    except Exception as e:
        result = HookResult.error(str(e))

    duration_ms = int((time.time() - start) * 1000)

    # Log outcome
    _log_event(log_path, {
        "ts": datetime.now().isoformat(),
        "tracking_id": tracking_id,
        "hook_type": hook_type,
        "handler": handler_name,
        "action": result.action,
        "reason": result.reason,
        "exit_code": result.exit_code,
        "duration_ms": duration_ms,
    })

    # Output
    if result.stdout_msg:
        sys.stdout.write(result.stdout_msg)
        if not result.stdout_msg.endswith("\n"):
            sys.stdout.write("\n")
    if result.stderr_msg:
        sys.stderr.write(result.stderr_msg)
        if not result.stderr_msg.endswith("\n"):
            sys.stderr.write("\n")

    return result.exit_code
