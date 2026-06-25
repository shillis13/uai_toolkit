"""Cross-platform process helpers.

Replaces Unix-only patterns (`os.kill(pid, 0)`, `ps`, `pstree`, SIGKILL) with
one portable surface. Uses psutil when available (the `full` extra), falls back
to stdlib where it can.
"""
from __future__ import annotations

import os

try:
    import psutil  # provided by the `full` extra
    _HAVE_PSUTIL = True
except ModuleNotFoundError:
    psutil = None  # type: ignore
    _HAVE_PSUTIL = False

_IS_WINDOWS = os.name == "nt"


def pid_alive(pid: int) -> bool:
    """True if a process with `pid` currently exists. (Replaces os.kill(pid, 0).)"""
    if _HAVE_PSUTIL:
        return psutil.pid_exists(pid)
    if _IS_WINDOWS:  # pragma: no cover - Windows path
        # Without psutil, best-effort via tasklist would go here; treat as alive.
        raise RuntimeError("pid_alive on Windows requires the 'full' extra (psutil)")
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, not ours to signal
    return True
