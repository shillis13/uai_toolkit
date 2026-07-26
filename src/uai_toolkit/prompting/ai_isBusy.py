#!/usr/bin/env python3
"""ai_isBusy.py — check if an AI CLI session is currently processing.

Ported from ai_isBusy.sh. Same CLI and exit codes:

  Usage: ai_isBusy.py <claude-cli|codex-cli|gemini-cli> [--session <name>]
  Exit:  0 = idle (not busy) · 1 = busy (processing) · 2 = usage / no session

Detection: read the session's terminal screen and scan the last few lines for a
platform-specific busy indicator. Indicators can briefly vanish mid-response, so
idle requires TWO consecutive clean checks ~2s apart (busy on EITHER => busy).

  Gemini CLI:  "esc to cancel"
  Codex CLI:   "esc to interrupt"
  Claude CLI:  (thought…), (thinking…), (N tokens), …

Note vs. the original .sh: this routes through session_ops.py (the substrate
abstraction) instead of calling zellij directly — policy-compliant and portable
(tmux/zellij/none/WSL), no raw terminal-multiplexer dependency.
"""
from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

_ai_scripts = os.environ.get("AI_SCRIPTS")
if _ai_scripts:
    sys.path.insert(0, _ai_scripts)
from uai_toolkit.paths import AI_ROOT  # noqa: E402

# common_utils (shared logging core)
_PY_SRC = Path.home() / "bin" / "all_languages" / "python" / "src"
if str(_PY_SRC) not in sys.path:
    sys.path.insert(0, str(_PY_SRC))
from uai_toolkit.common_utils.lib_logging import get_logger, configure_logging  # noqa: E402

log = get_logger(__name__)

SESSION_OPS = AI_ROOT / "ai_general" / "scripts" / "session_mgmt" / "session_ops.py"

BUSY_PATTERNS = {
    "gemini-cli": r"esc to cancel",
    "codex-cli": r"esc to interrupt",
    "claude-cli": r"\((thought|thinking|[0-9]+ tokens)",
    "grok-cli": r"\[stop\]",
    "antigravity-cli": r"Working\.\.\.",
}
SESSION_HINT = {"claude-cli": "claude", "codex-cli": "codex", "gemini-cli": "gemini",
                "grok-cli": "grok", "antigravity-cli": "agy"}

USAGE = "Usage: ai_isBusy.py <claude-cli|codex-cli|gemini-cli|grok-cli|antigravity-cli> [--session <name>]"
RECHECK_DELAY_S = 2
TAIL_LINES = 5


def _die(msg: str, code: int = 2):
    log.error(msg)
    sys.exit(code)


def _session_ops(*args: str) -> tuple[int, str]:
    """Run session_ops.py; return (returncode, stdout)."""
    try:
        r = subprocess.run(
            [sys.executable, str(SESSION_OPS), *args],
            capture_output=True, text=True,
        )
        return r.returncode, r.stdout
    except OSError:
        return 1, ""


def find_session(hint: str) -> str | None:
    """First session whose name contains `hint` (case-insensitive).

    Best-effort fallback — most callers pass --session explicitly. Mirrors the
    original `zellij list-sessions | grep` behavior, via session_ops."""
    rc, out = _session_ops("list-sessions", "--oneline")
    if rc != 0:
        return None
    for line in out.splitlines():
        name = line.split("\t", 1)[0].strip()
        if name and hint.lower() in name.lower():
            return name
    return None


def check_busy(session: str, pattern: re.Pattern) -> bool:
    """True if a busy indicator appears in the last TAIL_LINES screen lines.

    An unreadable/empty screen is treated as not-busy (matches the original)."""
    rc, out = _session_ops("read-terminal", session)
    if rc != 0:
        return False
    tail = "\n".join(out.splitlines()[-TAIL_LINES:])
    if not tail.strip():
        return False
    return bool(pattern.search(tail))


def main(argv: list[str] | None = None) -> int:
    configure_logging()
    argv = list(sys.argv[1:] if argv is None else argv)

    target = ""
    session = ""
    if argv and not argv[0].startswith("-"):
        target = argv.pop(0)
    while argv:
        arg = argv.pop(0)
        if arg == "--session":
            if not argv:
                _die("Error: --session requires a value")
            session = argv.pop(0)
        else:
            _die(f"Error: Unknown option '{arg}'")

    if not target:
        _die(USAGE)
    if target not in BUSY_PATTERNS:
        _die(f"Error: Unknown target '{target}'")

    if not session:
        session = find_session(SESSION_HINT[target]) or ""
    if not session:
        _die(f"Error: No session found for '{target}'")

    pattern = re.compile(BUSY_PATTERNS[target], re.IGNORECASE)

    if check_busy(session, pattern):
        return 1
    time.sleep(RECHECK_DELAY_S)
    if check_busy(session, pattern):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
