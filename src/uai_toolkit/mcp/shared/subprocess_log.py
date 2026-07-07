"""
MCP subprocess logger — logs every subprocess call made by MCP servers.

Appends one JSONL line per call to ai_general/logs/mcp/<server_name>.jsonl.
Always-on, lightweight (no parsing, just append).

Usage in a tool module:
    from uai_toolkit.mcp.shared.subprocess_log import logged_run

    result = logged_run("comms", cmd, capture_output=True, text=True, timeout=30)
    # Same interface as subprocess.run, returns CompletedProcess

Or wrap an existing _run function:
    from uai_toolkit.mcp.shared.subprocess_log import log_call

    log_call("comms", cmd, returncode, stderr_snippet)
"""

import json
import os
import subprocess
import time
from datetime import datetime
from pathlib import Path

AI_ROOT = Path(os.environ.get("AI_ROOT", Path.home() / "AI" / "ai_root"))
LOG_DIR = AI_ROOT / "ai_general" / "logs" / "mcp"


def _ensure_log_dir():
    if not LOG_DIR.exists():
        LOG_DIR.mkdir(parents=True, exist_ok=True)


def log_call(server_name: str, cmd: list, returncode: int = 0,
             stderr: str = "", duration_ms: int = 0, error: str = ""):
    """Append a subprocess call record to the server's log file."""
    try:
        _ensure_log_dir()
        log_path = LOG_DIR / f"{server_name}.jsonl"
        entry = {
            "ts": datetime.now().isoformat(),
            "cmd": cmd,
            "rc": returncode,
            "ms": duration_ms,
        }
        if stderr:
            entry["stderr"] = stderr[:500]
        if error:
            entry["error"] = error[:500]
        # Include caller session for traceability
        tid = os.environ.get("AI_TRACKING_ID", "")
        if tid:
            entry["session"] = tid
        with open(log_path, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError:
        pass  # Never fail the tool call due to logging


def logged_run(server_name: str, cmd: list, **kwargs) -> subprocess.CompletedProcess:
    """Run a subprocess and log the call. Same interface as subprocess.run.

    Raises the same exceptions as subprocess.run (TimeoutExpired, etc.)
    but logs the attempt regardless of outcome.
    """
    start = time.time()
    error = ""
    returncode = -1
    stderr = ""
    try:
        result = subprocess.run(cmd, **kwargs)
        returncode = result.returncode
        stderr = (result.stderr or "")[:500] if hasattr(result, 'stderr') and result.stderr else ""
        return result
    except subprocess.TimeoutExpired as e:
        error = f"timeout ({kwargs.get('timeout', '?')}s)"
        raise
    except FileNotFoundError as e:
        error = f"not found: {cmd[0] if cmd else '?'}"
        raise
    except Exception as e:
        error = str(e)[:200]
        raise
    finally:
        duration_ms = int((time.time() - start) * 1000)
        log_call(server_name, cmd, returncode=returncode,
                 stderr=stderr, duration_ms=duration_ms, error=error)
