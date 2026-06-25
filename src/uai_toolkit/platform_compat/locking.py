"""Cross-platform advisory file locking.

The canonical Tier-B pattern: ONE module, ONE public API, runtime dispatch on
the OS. Callers stay platform-blind:

    from uai_toolkit.platform_compat.locking import file_lock
    with file_lock(path):
        ...  # exclusive across processes on macOS, Linux, and Windows

macOS/Linux keep their existing fcntl behavior (this just adds a sibling
branch). Windows uses msvcrt. No forked files, no caller-visible #ifdefs.
"""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

_IS_WINDOWS = os.name == "nt"


@contextmanager
def file_lock(path: str | os.PathLike) -> Iterator[None]:
    """Acquire an exclusive advisory lock for the duration of the block."""
    lock_path = Path(f"{os.fspath(path)}.lock")
    fh = open(lock_path, "a+")
    try:
        _acquire(fh)
        yield
    finally:
        _release(fh)
        fh.close()


if _IS_WINDOWS:  # pragma: no cover - exercised on Windows
    import msvcrt

    def _acquire(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)

    def _release(fh) -> None:
        fh.seek(0)
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
else:
    import fcntl

    def _acquire(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_EX)

    def _release(fh) -> None:
        fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
