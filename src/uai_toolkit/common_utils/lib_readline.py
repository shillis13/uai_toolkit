"""
Portable readline helpers — abstracts macOS libedit vs GNU readline differences.

Usage:
    from uai_toolkit.common_utils.lib_readline import setup_readline, bind_key, IS_LIBEDIT
    from uai_toolkit.common_utils.lib_readline import make_session_completer

    setup_readline(history_file="~/.myapp_history", history_length=500)
    setup_readline(completer=make_session_completer())  # tab-complete session names
    bind_key("tab", "complete")        # tab completion
    bind_key("esc-esc", "kill-line")   # double-escape clears line
"""

from __future__ import annotations

import atexit
import readline
from pathlib import Path
from typing import Callable, List, Optional


IS_LIBEDIT = "libedit" in (readline.__doc__ or "")

# Mapping of portable key names to platform-specific bindings.
# GNU readline uses: "keyseq": function-name
# libedit uses: bind "keyseq" command-name
_KEY_BINDINGS = {
    ("tab", "complete"): (
        'bind ^I rl_complete' if IS_LIBEDIT else 'tab: complete'
    ),
    ("esc-esc", "kill-line"): (
        'bind "\\e\\e" em-kill-line' if IS_LIBEDIT else '"\\e\\e": kill-whole-line'
    ),
}


def bind_key(key: str, action: str) -> None:
    """Bind a key to an action, using the right syntax for the platform.

    Supports predefined portable bindings (tab/complete, esc-esc/kill-line)
    and falls back to raw parse_and_bind for unknown combos.
    """
    binding = _KEY_BINDINGS.get((key, action))
    if binding:
        readline.parse_and_bind(binding)
    else:
        # Fall back: assume caller knows the raw syntax
        readline.parse_and_bind(f'{key}: {action}')


def setup_readline(
    history_file: str | Path | None = None,
    history_length: int = 500,
    completer: Optional[Callable] = None,
    completer_delims: str = " \t",
) -> None:
    """One-call readline setup: history, tab completion, esc-esc kill-line.

    Args:
        history_file: Path to history file (~ expanded). None to skip history.
        history_length: Max history entries to keep.
        completer: Tab completion function (signature: completer(text, state) -> str|None).
        completer_delims: Characters that delimit completion words.
    """
    # History
    if history_file:
        path = Path(history_file).expanduser()
        try:
            readline.read_history_file(str(path))
        except (FileNotFoundError, PermissionError, OSError):
            pass
        readline.set_history_length(history_length)
        atexit.register(readline.write_history_file, str(path))

    # Tab completion
    if completer:
        readline.set_completer(completer)
        readline.set_completer_delims(completer_delims)
        bind_key("tab", "complete")

    # Esc-Esc clears line (single Esc can't — it's the arrow key prefix)
    bind_key("esc-esc", "kill-line")


# =========================================================================
# Reusable completers
# =========================================================================

def make_static_completer(candidates: List[str]) -> Callable:
    """Create a completer from a static list of strings (case-sensitive prefix match)."""
    def completer(text: str, state: int) -> str | None:
        matches = [c for c in candidates if c.startswith(text)]
        return matches[state] if state < len(matches) else None
    return completer


def make_session_completer(limit: int = 50) -> Callable:
    """Create a tab completer that resolves session display names and tracking IDs.

    Queries the SessionStore SQLite database. Falls back gracefully if the
    store is unavailable.

    Usage:
        from uai_toolkit.common_utils.lib_readline import setup_readline, make_session_completer
        setup_readline(completer=make_session_completer())
    """
    _store = None
    _store_loaded = False

    def _get_store():
        nonlocal _store, _store_loaded
        if _store_loaded:
            return _store
        _store_loaded = True
        try:
            import sys
            sm_path = str(Path.home() / "Documents/AI/ai_root/ai_general/scripts/session_mgmt")
            if sm_path not in sys.path:
                sys.path.insert(0, sm_path)
            from uai_toolkit.session_mgmt.session_store import SessionStore
            _store = SessionStore()
        except Exception:
            pass
        return _store

    def completer(text: str, state: int) -> str | None:
        store = _get_store()
        if store is None:
            return None
        try:
            with store._connect() as conn:
                rows = conn.execute(
                    "SELECT display_name, tracking_id FROM sessions "
                    "ORDER BY created_at DESC LIMIT ?",
                    (limit,)
                ).fetchall()
            candidates = []
            seen = set()
            for row in rows:
                for val in (row[0], row[1]):
                    if val and val not in seen:
                        seen.add(val)
                        candidates.append(val)
            matches = [c for c in candidates if c.startswith(text)]
            return matches[state] if state < len(matches) else None
        except Exception:
            return None

    return completer
